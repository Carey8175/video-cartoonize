import os
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector


def detect_sub_shots(clip_path: str, threshold: float = 27.0) -> List[float]:
    """Return sub-shot start times (seconds). Always includes 0.0."""
    video = open_video(clip_path)
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    sm.detect_scenes(video=video)
    scenes = sm.get_scene_list()
    if not scenes:
        return [0.0]
    return [round(start.get_seconds(), 3) for start, _end in scenes]


def extract_sub_shot_keyframes(
    clip_path: str,
    out_dir: str,
    threshold: float = 27.0,
) -> List[Tuple[float, str]]:
    """Extract first frame of each sub-shot. Returns [(timestamp_s, jpg_path), ...]."""
    os.makedirs(out_dir, exist_ok=True)
    boundaries = detect_sub_shots(clip_path, threshold)
    out: List[Tuple[float, str]] = []
    clip_stem = Path(clip_path).stem
    for i, t in enumerate(boundaries):
        seek = max(0.05, t + 0.1)
        dst = str(Path(out_dir) / f"{clip_stem}_sub{i:02d}_t{t:.2f}.jpg")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{seek:.3f}", "-i", clip_path,
               "-frames:v", "1", "-update", "1", dst]
        try:
            subprocess.run(cmd, check=True)
            out.append((t, dst))
        except subprocess.CalledProcessError as e:
            print(f"[sub_shot] ✗ failed at t={t}: {e}")
    return out
