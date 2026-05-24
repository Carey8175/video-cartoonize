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

# 候选 nudge 偏移（秒）：先试 0.1，不清晰就退避 0.3、0.5
# 3 档退避覆盖大多数转场模糊（快切 0.1、普通过渡 0.3、慢溶 0.5）。
# 原来的 1.0 / 1.5 对 5s 以内的短 clip 过于激进（可能直接跳到 clip 结尾），已移除。
NUDGE_CANDIDATES = (0.1, 0.3, 0.5)

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
    luma_only: bool = True,
) -> List[float]:
    """Return sub-shot start times (seconds). Always includes 0.0.

    luma_only=True（默认）：仅用亮度（Value）检测镜头切换，忽略色调和饱和度。
    对急速灯光变色（disco、彩色聚光灯等）引起的误检有显著抑制效果——同一场景
    在不同颜色光照下亮度不变，HSV 等权模式下 Hue 差异会被误判为镜头切换。
    """
    video = open_video(clip_path)
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len,
                                    luma_only=luma_only))
    sm.detect_scenes(video=video)
    scenes = sm.get_scene_list()
    if not scenes:
        return [0.0]
    return [round(start.seconds, 3) for start, _end in scenes]


def _extract_frame(clip_path: str, seek: float, dst: str) -> bool:
    """提取单帧。成功返回 True。

    -pix_fmt yuvj420p: 强制输出 JPEG full-range YUV，解决源视频 limited-range
    YUV 导致 MJPEG encoder 拒绝写帧的问题（"Non full-range YUV is non-standard"）。
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{seek:.3f}", "-i", clip_path,
           "-frames:v", "1", "-pix_fmt", "yuvj420p", "-update", "1", dst]
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


def _probe_frame_interval(clip_path: str) -> float:
    """Best-effort frame interval in seconds, defaulting to 25fps."""
    try:
        import json
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate,r_frame_rate",
             "-of", "json", clip_path],
            text=True,
            timeout=10,
        )
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""
        if "/" in rate:
            num, den = rate.split("/", 1)
            fps = float(num) / float(den)
        else:
            fps = float(rate)
        if fps > 0:
            return 1.0 / fps
    except Exception:
        pass
    return 1.0 / 25.0


def _brightness_ok(img_path: str) -> bool:
    """True unless the image is effectively all black or all white."""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            return False
        mean = float(np.mean(img))
        return BRIGHTNESS_MIN < mean < BRIGHTNESS_MAX
    except Exception:
        return True


def _extract_fixed_endpoint_frame(
    clip_path: str,
    dst: str,
    *,
    endpoint: str,
    max_shift_s: float = 2.0,
) -> Optional[float]:
    """Extract a fixed first/last frame, only shifting past black/white frames.

    Unlike sub-shot boundary extraction, endpoints must not choose the sharpest
    nearby frame: that changes story timing.  Start at the true first/last frame
    and move one frame at a time only when the frame is essentially all black or
    all white. Returns the actual seek time used.
    """
    duration = _probe_duration(clip_path)
    frame_dt = _probe_frame_interval(clip_path)
    if duration <= 0:
        duration = frame_dt

    if endpoint == "first":
        start = 0.0
        direction = 1.0
    elif endpoint == "last":
        start = max(0.0, duration - frame_dt)
        direction = -1.0
    else:
        raise ValueError(f"unsupported endpoint: {endpoint}")

    max_steps = max(1, int(max_shift_s / frame_dt))
    base, ext = os.path.splitext(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    for step in range(max_steps + 1):
        seek = start + direction * frame_dt * step
        seek = max(0.0, min(seek, max(0.0, duration - frame_dt)))
        tmp = f"{base}_{endpoint}_fixed{step}{ext}"
        if not _extract_frame(clip_path, seek, tmp):
            continue

        if _brightness_ok(tmp):
            import shutil
            shutil.copy2(tmp, dst)
            for old in Path(os.path.dirname(dst)).glob(f"{Path(base).name}_{endpoint}_fixed*{ext}"):
                try:
                    os.remove(old)
                except FileNotFoundError:
                    pass
            return seek

        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass

    return None


def _extract_at_timestamps(
    clip_path: str,
    out_dir: str,
    timestamps: List[float],
) -> List[Tuple[float, str]]:
    """Extract a key frame at each requested timestamp.

    The true clip first frame is fixed at t=0 unless it is black/white. Other
    sub-shot boundaries still use the nudge candidates and choose the clearest
    non-black/non-white frame.
    """
    os.makedirs(out_dir, exist_ok=True)
    out: List[Tuple[float, str]] = []
    clip_stem = Path(clip_path).stem

    for i, t in enumerate(timestamps):
        dst = str(Path(out_dir) / f"{clip_stem}_sub{i:02d}_t{t:.2f}.jpg")

        if abs(t) < 1e-3:
            seek = _extract_fixed_endpoint_frame(clip_path, dst, endpoint="first")
            if seek is not None:
                if seek > 1e-3:
                    print(f"[sub_shot] ⚠ first frame at t=0.00 is black/white, shifted to t={seek:.2f}")
                out.append((t, dst))
            else:
                print("[sub_shot] ✗ first frame extraction failed")
            continue

        # best-effort: 尝试所有 nudge，选 Laplacian 方差最大的帧（最清晰）。
        # 不再做 pass/fail 二选一——柔焦/慢镜拍摄的帧 Laplacian 可能本来就低，
        # 强行拒绝会导致所有候选都走"保底"，最终用偏移最远的那帧（可能更差）。
        best_seek:     Optional[float] = None
        best_lap:      float           = -1.0
        any_extracted: bool            = False

        # 临时文件用合法的 .jpg 扩展名，放在同目录下
        base, ext = os.path.splitext(dst)

        for ni, nudge in enumerate(NUDGE_CANDIDATES):
            seek = max(0.05, t + nudge)
            tmp  = f"{base}_nudge{ni}{ext}"   # e.g. sub00_t3.04_nudge0.jpg
            if not _extract_frame(clip_path, seek, tmp):
                continue
            any_extracted = True

            # 计算清晰度；同时过滤全黑/全白帧（亮度硬限制保留）
            try:
                import cv2
                import numpy as np
                import shutil
                img = cv2.imread(tmp, cv2.IMREAD_GRAYSCALE)
                if img is None or img.size == 0:
                    continue
                mean = float(np.mean(img))
                if mean < BRIGHTNESS_MIN or mean > BRIGHTNESS_MAX:
                    continue   # 全黑/全白帧彻底跳过
                lap = float(cv2.Laplacian(img, cv2.CV_64F).var())
            except Exception:
                lap = 0.0

            if lap > best_lap:
                best_lap  = lap
                best_seek = seek
                # 把当前最优帧写到最终 dst（覆盖上一次的）
                shutil.copy2(tmp, dst)

            # 提前退出：已达质量阈值，没必要继续更大的偏移
            if lap >= SHARPNESS_THRESHOLD:
                break

        # 清理临时 nudge 文件
        for ni in range(len(NUDGE_CANDIDATES)):
            tmp = f"{base}_nudge{ni}{ext}"
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass

        if best_seek is not None:
            quality_note = "" if best_lap >= SHARPNESS_THRESHOLD else f" (best_lap={best_lap:.0f}<{SHARPNESS_THRESHOLD:.0f}, cinematic/soft-focus)"
            if quality_note:
                print(f"[sub_shot] ⚠ t={t:.2f} 柔焦素材，选 Laplacian 最优帧 t+{best_seek-t:.2f}{quality_note}")
            out.append((t, dst))
        elif any_extracted:
            print(f"[sub_shot] ⚠ t={t:.2f} 所有帧亮度异常（全黑/全白），跳过")
        else:
            print(f"[sub_shot] ✗ t={t:.2f} 完全提取失败")

    return out


# 感知相似度去重阈值：16×16 缩略图像素 MSE < 此值认为两帧视觉相同
# 值越小越严格（保留更多）；500 对应约 90% 相似度
DEDUP_MSE_THRESHOLD = 500.0


def _frame_thumbnail(path: str, size: int = 16) -> Optional["np.ndarray"]:
    """Return grayscale {size}×{size} thumbnail for perceptual comparison."""
    try:
        import cv2
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA).astype(float)
    except Exception:
        return None


def _dedup_similar_frames(
    frames: List[Tuple[float, str]],
    mse_threshold: float = DEDUP_MSE_THRESHOLD,
) -> List[Tuple[float, str]]:
    """Remove consecutive keyframes that look visually identical.

    Compares each frame to the last *accepted* frame using MSE on a 16×16
    grayscale thumbnail.  Keeps the first of any near-duplicate group.
    Frames that can't be read are kept (safe default).
    """
    if len(frames) <= 1:
        return frames

    try:
        import numpy as np
    except ImportError:
        return frames   # numpy not available, skip dedup

    kept: List[Tuple[float, str]] = []
    last_thumb: Optional["np.ndarray"] = None

    for t, path in frames:
        thumb = _frame_thumbnail(path)
        if thumb is None or last_thumb is None:
            kept.append((t, path))
            last_thumb = thumb
            continue

        mse = float(np.mean((thumb - last_thumb) ** 2))
        if mse < mse_threshold:
            print(f"[sub_shot] ⊘ t={t:.2f} 与前一帧视觉相似(MSE={mse:.0f}<{mse_threshold:.0f})，跳过")
            # Remove the duplicate file to keep cartoons/ clean
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        else:
            kept.append((t, path))
            last_thumb = thumb

    return kept


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
    frames     = _extract_at_timestamps(clip_path, out_dir, boundaries)
    return _dedup_similar_frames(frames)
