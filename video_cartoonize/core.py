"""Seedance submission helpers + audio utilities."""
import json
import os
import subprocess
from typing import Optional

from video_cartoonize.ark_client import (
    create_task, get_task, DEFAULT_MODEL,
)

from video_cartoonize.config import PipelineConfig
from video_cartoonize.models import ClipInfo

SUPPORTED_RATIOS = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "1:1":  1.0,
    "4:3":  4 / 3,
    "3:4":  3 / 4,
    "21:9": 21 / 9,
}


def build_preamble(style_description: str) -> str:
    return (
        "This is a video generation task — generate a brand-new animated video, "
        "do NOT edit or alter the original footage. "
        "Follow the action, motion, and plot from the reference video exactly. "
        "Use the reference key frame images to determine the visual style and "
        "character appearance for the generated video. "
        f"Target style: {style_description}"
    )


def detect_ratio(video_path: str) -> str:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "json", video_path]
    out = subprocess.check_output(cmd, text=True)
    stream = json.loads(out)["streams"][0]
    w, h = int(stream["width"]), int(stream["height"])
    actual = w / h
    return min(SUPPORTED_RATIOS.items(), key=lambda kv: abs(kv[1] - actual))[0]


def mux_original_audio(cartoon_path: str, original_path: str, out_path: str) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", cartoon_path, "-i", original_path,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-shortest", out_path]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[mux] {os.path.basename(out_path)} ✗ {e}")
        return False


def submit_clip(
    api_key: str,
    clip: ClipInfo,
    clip_video_url: str,
    prompt: str,
    ratio: str,
    cfg: PipelineConfig,
) -> Optional[str]:
    """Submit one clip to Seedance. Returns task_id or None on error."""
    image_urls = list(clip.subshot_cartoon_urls) or None
    try:
        result = create_task(
            api_key=api_key,
            prompt=prompt,
            image_urls=image_urls,
            video_urls=[clip_video_url],
            model=cfg.seedance_model,
            ratio=ratio,
            duration=5,
            resolution=cfg.seedance_resolution,
            watermark=False,
        )
        return result.get("id")
    except Exception as e:
        print(f"[Seedance] clip {clip.clip_id:02d} submit error: {e}")
        return None


def poll_task(api_key: str, task_id: str) -> dict:
    """Poll one task. Returns the raw API response dict."""
    return get_task(api_key=api_key, task_id=task_id)
