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
            text=True, timeout=30,
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
    """Seedance prompt 的固定前置（manhwa_adaptation 风格，A/B 测试胜出）。

    实测对 5 个泄漏真人内容的 clip 通过率 4/5（80%），显著优于其他变体。
    与 build_image_order_hint() 配合使用，构成完整 prompt 头部。
    """
    return (
        "Task: adapt the live-action reference video into a manhwa/anime "
        "animated short. Like adapting a TV drama into its animated "
        "counterpart — same plot, same beats, same camera moves, but the "
        "entire visual is now hand-drawn animation. Follow the key frame "
        "images exactly for character design and color palette. No frames of "
        "the output may resemble live-action footage. "
        f"Visual style: {style_description}."
    )


def build_image_order_hint(n_keyframes: int) -> str:
    """Image 顺序提示（A/B 实验出来的简洁版，比长形式 +2 通过）。

    n_keyframes <= 1 时返回空（单帧无需排序）。
    """
    if n_keyframes <= 1:
        return ""
    seq = ", ".join(f"image{i+1}" for i in range(n_keyframes))
    return f"Use the key frame images in this order: {seq}."


def detect_ratio(video_path: str) -> str:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "json", video_path]
    out = subprocess.check_output(cmd, text=True, timeout=30)
    stream = json.loads(out)["streams"][0]
    w, h = int(stream["width"]), int(stream["height"])
    actual = w / h
    return min(SUPPORTED_RATIOS.items(), key=lambda kv: abs(kv[1] - actual))[0]


def _ffprobe_fps(path: str) -> float:
    """获取视频 fps（fallback 24.0）。r_frame_rate 形如 "24/1" 或 "30000/1001"。"""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=nw=1:nk=1", path],
            text=True, timeout=10,
        ).strip()
        if "/" in out:
            n, d = out.split("/", 1)
            d_f = float(d)
            return float(n) / d_f if d_f != 0 else 24.0
        return float(out)
    except Exception:
        return 24.0


def mux_original_audio(cartoon_path: str, original_path: str, out_path: str) -> bool:
    """把原视频音轨贴回卡通化视频；若两者时长不同，**拉伸视频对齐原片**。

    0.14.8+: 之前的做法是用 atempo 缩放音频去匹配 Seedance 输出的时长，但这会带来
    时间拉伸伪影（人声变调、长片累积漂移）。新做法是反过来——保留原音频不动，用
    setpts 拉伸视频的播放速度，让卡通视频的时长精确匹配原片。Seedance 通常向上
    取整到整数秒（cart_dur ≥ orig_dur），所以 factor ≤ 1，视频微微加速 5-15%，
    动作差异几乎肉眼无感，但音频质量是无损的，长片对齐也不漂移。

    setpts 只改时间戳不动帧数，会让有效 fps 偏离标准值；末尾再叠一个 fps 滤镜
    把帧率规整化，避免下游 merge 拼接时帧率不一致。
    """
    cart_dur = _ffprobe_duration(cartoon_path)
    orig_dur = _ffprobe_duration(original_path)

    # 时长差小于 50ms 直接 mux 不动视频
    # 音频用 `-c:a copy` 是关键——0.14.8 的核心约束是音频 bit-for-bit 透传，
    # 不能再走 aac 重编（即便不拉伸，重编码也会产生轻微的 lossy 漂移）
    if cart_dur and orig_dur and abs(cart_dur - orig_dur) >= 0.05:
        factor = orig_dur / cart_dur          # < 1 视频加速；> 1 视频减速
        target_fps = _ffprobe_fps(cartoon_path)
        # setpts 拉伸时间戳 → fps 规整化 → 输出 frames 数 = target_fps × orig_dur
        vf = f"setpts={factor:.6f}*PTS,fps={target_fps:.6f}"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", cartoon_path, "-i", original_path,
               "-filter_complex", f"[0:v]{vf}[v]",
               "-map", "[v]", "-map", "1:a:0",
               "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-c:a", "copy",
               "-shortest",  # 兜底：万一音频比拉伸后视频还长，剪到短者
               out_path]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-i", cartoon_path, "-i", original_path,
               "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "copy",
               out_path]
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[mux] {os.path.basename(out_path)} ✗ {e}")
        return False


def submit_clip(
    api_key: str,
    clip: ClipInfo,
    clip_video_url: str,
    prompt: str,
    ratio: str,
    cfg: PipelineConfig,
    use_reference_video: bool = True,
) -> Optional[str]:
    """Submit one clip to Seedance. Returns task_id or None on error.

    use_reference_video:
      True  → 传原视频作动作参考（默认，前两次重试）
      False → 不传原视频，只用 key frame images + prompt timeline 生成
              （第三次重试用，避免原视频真人内容污染输出）
    """
    image_urls = list(clip.subshot_cartoon_urls) or None
    video_urls = [clip_video_url] if (use_reference_video and clip_video_url) else None
    # 用原片时长向上取整作为 Seedance duration（保证生成视频 ≥ 原片）
    duration = seedance_duration_for(clip.resized_path, fallback=5)
    try:
        result = create_task(
            api_key=api_key,
            prompt=prompt,
            image_urls=image_urls,
            video_urls=video_urls,
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
