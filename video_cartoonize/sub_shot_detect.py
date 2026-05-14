import os
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


# PySceneDetect 默认 min_scene_len=15 帧（24fps ≈ 0.6s）会把极短镜头
# 合并到下一个，导致短剧封面（0.1-0.2s）这种"开头一闪而过"的镜头被吞掉。
# 改成 3 帧（≈ 0.125s @24fps），实测:
#   - 21 个 clip 中 17 个保持不变
#   - 4 个 clip 多抓到真实存在的快切
#   - 不会过敏（降到 2 帧 Clip-021 会跳到 9 个，已经开始误判）
DEFAULT_MIN_SCENE_LEN = 3


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


def extract_sub_shot_keyframes(
    clip_path: str,
    out_dir: str,
    threshold: float = 27.0,
    min_scene_len: int = DEFAULT_MIN_SCENE_LEN,
) -> List[Tuple[float, str]]:
    """Extract first frame of each sub-shot. Returns [(timestamp_s, jpg_path), ...]."""
    os.makedirs(out_dir, exist_ok=True)
    boundaries = detect_sub_shots(clip_path, threshold, min_scene_len)
    out: List[Tuple[float, str]] = []
    clip_stem = Path(clip_path).stem
    for i, t in enumerate(boundaries):
        seek = max(0.05, t + 0.1)
        dst = str(Path(out_dir) / f"{clip_stem}_sub{i:02d}_t{t:.2f}.jpg")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{seek:.3f}", "-i", clip_path,
               "-frames:v", "1", "-update", "1", dst]
        try:
            subprocess.run(cmd, check=True, timeout=60)
            out.append((t, dst))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"[sub_shot] ✗ failed at t={t}: {e}")
    return out
