import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


# PySceneDetect 默认 min_scene_len=15 帧（24fps ≈ 0.6s）会把极短镜头
# 合并到下一个，导致短剧封面（0.1-0.2s）这种"开头一闪而过"的镜头被吞掉。
# 改成 3 帧（≈ 0.125s @24fps），实测:
#   - 21 个 clip 中 17 个保持不变
#   - 4 个 clip 多抓到真实存在的快切
#   - 不会过敏（降到 2 帧 Clip-021 会跳到 9 个，已经开始误判）
DEFAULT_MIN_SCENE_LEN = 3

# 候选 nudge 偏移（秒）：先试 0.1，不清晰就 0.25, 0.5, 1.0, 1.5
# 大多数镜头在 0.1 就稳了；过渡较长的（淡入/运动模糊）需要往后退
NUDGE_CANDIDATES = (0.1, 0.25, 0.5, 1.0, 1.5)

# 清晰度阈值（Laplacian 方差）：< 80 视为模糊
SHARPNESS_THRESHOLD = 80.0
# 过曝判断：平均亮度 > 235（接近全白）或 < 15（接近全黑）
BRIGHTNESS_MIN = 15.0
BRIGHTNESS_MAX = 235.0


def _frame_quality_ok(img_path: str) -> bool:
    """检查帧质量：不模糊、不过曝、不全黑。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return True   # cv2 没装就不挑了

    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        return False

    # 1) 清晰度：Laplacian 方差越大越清晰
    lap_var = cv2.Laplacian(img, cv2.CV_64F).var()
    if lap_var < SHARPNESS_THRESHOLD:
        return False

    # 2) 亮度范围：不过曝、不全黑
    mean = float(np.mean(img))
    if mean < BRIGHTNESS_MIN or mean > BRIGHTNESS_MAX:
        return False

    return True


def detect_sub_shots(
    clip_path: str,
    threshold: float = 27.0,
    min_scene_len: int = DEFAULT_MIN_SCENE_LEN,
) -> List[float]:
    """Return sub-shot start times (seconds). Always includes 0.0."""
    video = open_video(clip_path)
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    sm.detect_scenes(video=video)
    scenes = sm.get_scene_list()
    if not scenes:
        return [0.0]
    return [round(start.seconds, 3) for start, _end in scenes]


def _extract_frame(clip_path: str, seek: float, dst: str) -> bool:
    """提取单帧。成功返回 True。"""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{seek:.3f}", "-i", clip_path,
           "-frames:v", "1", "-update", "1", dst]
    try:
        subprocess.run(cmd, check=True, timeout=60)
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _probe_duration(clip_path: str) -> float:
    """ffprobe duration in seconds (0.0 on failure)."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", clip_path],
            timeout=10,
        )
        return float(out.strip())
    except Exception:
        return 0.0


def _extract_at_timestamps(
    clip_path: str,
    out_dir: str,
    timestamps: List[float],
) -> List[Tuple[float, str]]:
    """Extract first quality-OK frame at each requested timestamp.

    Shared body of all sub-shot keyframe strategies. For each `t`, nudges
    forward by NUDGE_CANDIDATES and picks the first sharp / well-exposed frame.
    Returns list of (requested_t, dst_path) for frames that landed successfully.
    """
    os.makedirs(out_dir, exist_ok=True)
    out: List[Tuple[float, str]] = []
    clip_stem = Path(clip_path).stem

    for i, t in enumerate(timestamps):
        dst = str(Path(out_dir) / f"{clip_stem}_sub{i:02d}_t{t:.2f}.jpg")
        picked_seek: Optional[float] = None
        last_seek:   Optional[float] = None

        for nudge in NUDGE_CANDIDATES:
            seek = max(0.05, t + nudge)
            if not _extract_frame(clip_path, seek, dst):
                continue
            last_seek = seek
            if _frame_quality_ok(dst):
                picked_seek = seek
                break

        if picked_seek is not None:
            out.append((t, dst))
        elif last_seek is not None:
            # 所有 nudge 都不清晰，保底用最后一次（有帧总比没帧好）
            print(f"[sub_shot] ⚠ t={t:.2f} 所有 nudge 都质量不佳，用 t+{NUDGE_CANDIDATES[-1]} 保底")
            out.append((t, dst))
        else:
            print(f"[sub_shot] ✗ t={t:.2f} 完全提取失败")

    return out


def extract_sub_shot_keyframes(
    clip_path: str,
    out_dir: str,
    threshold: float = 27.0,
    min_scene_len: int = DEFAULT_MIN_SCENE_LEN,
) -> List[Tuple[float, str]]:
    """Extract first frame of each sub-shot, skipping blurry / overexposed frames.

    Default (attempt 1) strategy: PySceneDetect ContentDetector at `threshold`.
    Works well for footage with hard cuts; can under-detect on soft-cut /
    same-scene framing changes. For retries, `cmd_poll` appends extra
    keyframes via `_compute_topup_timestamps_floor` (attempt 2, 3s gap floor)
    and `_compute_topup_timestamps_uniform` (attempt 3, top up to 10 frames).
    """
    boundaries = detect_sub_shots(clip_path, threshold, min_scene_len)
    return _extract_at_timestamps(clip_path, out_dir, boundaries)
