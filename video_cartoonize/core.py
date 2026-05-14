"""Seedance submission helpers + audio utilities."""
import json
import math
import os
import subprocess
from typing import Optional

from video_cartoonize import billing
from video_cartoonize.ark_client import (
    create_task, get_task, DEFAULT_MODEL,
)

from video_cartoonize.config import PipelineConfig
from video_cartoonize.models import ClipInfo

# Seedance 接受的 duration 范围（秒，整数）
SEEDANCE_MIN_DURATION = 2
SEEDANCE_MAX_DURATION = 15


def _ffprobe_duration(path: str) -> Optional[float]:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            text=True,
        ).strip()
        return float(out) if out else None
    except Exception:
        return None


def seedance_duration_for(clip_path: str, fallback: int = 5) -> int:
    """根据原片实际时长向上取整为 Seedance 整数 duration（保证 ≥ 原片）。"""
    d = _ffprobe_duration(clip_path)
    if d is None:
        return fallback
    return max(SEEDANCE_MIN_DURATION, min(SEEDANCE_MAX_DURATION, math.ceil(d)))

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
        "This is an ANIME generation task. Every element and character in the "
        "output video MUST be in the specified animated/cartoon style — no "
        "real-life scenes, no photoreal humans, no live-action footage is allowed. "
        "Follow the action, motion, and plot from the reference video exactly, "
        "but render everything in the target animated style. "
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


def _atempo_chain(factor: float) -> str:
    """atempo 单滤镜只支持 0.5–2.0，超出范围需要级联。"""
    if 0.5 <= factor <= 2.0:
        return f"atempo={factor:.6f}"
    parts = []
    remaining = factor
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


def mux_original_audio(cartoon_path: str, original_path: str, out_path: str) -> bool:
    """把原视频音轨贴回卡通化视频；若两者时长不同，按比例拉伸音频。

    Seedance 输出会向上取整到整数秒，可能比原片长。直接 mux 会出现尾段
    无声/早结束，所以这里用 atempo 把音频拉伸到与画面等长。
    """
    cart_dur = _ffprobe_duration(cartoon_path)
    orig_dur = _ffprobe_duration(original_path)

    # 时长差小于 50ms 直接 copy 不动音轨
    if cart_dur and orig_dur and abs(cart_dur - orig_dur) >= 0.05:
        factor = orig_dur / cart_dur          # < 1 表示音频要变慢（变长）
        af = _atempo_chain(factor)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", cartoon_path, "-i", original_path,
               "-filter_complex", f"[1:a]{af}[a]",
               "-map", "0:v:0", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               out_path]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", cartoon_path, "-i", original_path,
               "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               out_path]
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
    # 用原片时长向上取整作为 Seedance duration（保证生成视频 ≥ 原片）
    duration = seedance_duration_for(clip.resized_path, fallback=5)
    try:
        result = create_task(
            api_key=api_key,
            prompt=prompt,
            image_urls=image_urls,
            video_urls=[clip_video_url],
            model=cfg.seedance_model,
            ratio=ratio,
            duration=duration,
            resolution=cfg.seedance_resolution,
            watermark=False,
        )
        # 不在 submit 时记账（此刻还拿不到 usage tokens），
        # 在 cli.cmd_poll 检测到 succeeded 时才记 billing
        return result.get("id")
    except Exception as e:
        print(f"[Seedance] clip {clip.clip_id:02d} submit error: {e}")
        return None


def poll_task(api_key: str, task_id: str) -> dict:
    """Poll one task. Returns the raw API response dict."""
    return get_task(api_key=api_key, task_id=task_id)
