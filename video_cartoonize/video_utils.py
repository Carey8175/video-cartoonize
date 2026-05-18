import json
import math
import os
import ssl
import subprocess
import tempfile
import urllib.request
from typing import List, Optional

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from scenedetect.frame_timecode import FrameTimecode

from video_cartoonize.config import PipelineConfig


def download_url(url: str, save_path: str) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, context=ctx) as r, open(save_path, "wb") as f:
        f.write(r.read())
    print(f"[Download] saved → {save_path}")


def _timecode_to_seconds(v) -> float:
    return float(v.get_seconds()) if hasattr(v, "get_seconds") else float(v)


def _ffprobe_duration(path: str) -> Optional[float]:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", path]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        return float((proc.stdout or "").strip())
    except Exception:
        return None


def _ffprobe_has_video(path: str) -> bool:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "json", path]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        streams = json.loads(proc.stdout or "{}").get("streams", [])
        return bool(streams) and int(streams[0].get("width", 0)) > 0
    except Exception:
        return False


def _split_one_ffmpeg(src: str, start: float, dur: float, dst: str, reencode: bool) -> None:
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.6f}", "-t", f"{dur:.6f}", "-i", src]
    if reencode:
        extra = ["-map", "0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                 "-movflags", "+faststart", "-avoid_negative_ts", "make_zero"]
    else:
        extra = ["-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"]
    subprocess.run(base + extra + [dst], check=True, timeout=300)


def _split_clips_ffmpeg(src: str, clips: list, out_dir: str, video_name: str) -> None:
    for idx, (start, end) in enumerate(clips, 1):
        s = _timecode_to_seconds(start)
        e = _timecode_to_seconds(end)
        d = e - s
        if d <= 0:
            continue
        dst = os.path.join(out_dir, f"{video_name}-Clip-{idx:03d}.mp4")
        _split_one_ffmpeg(src, s, d, dst, reencode=False)
        actual = _ffprobe_duration(dst)
        ok = actual is not None and abs(actual - d) <= 0.12
        if not ok or not _ffprobe_has_video(dst):
            _split_one_ffmpeg(src, s, d, dst, reencode=True)


def _adjust_scenes(scene_list, min_sec, max_sec, framerate):
    if not scene_list:
        return []
    merged = [[scene_list[0][0], scene_list[0][1]]]
    for start, end in scene_list[1:]:
        prev_dur = (_timecode_to_seconds(merged[-1][1]) -
                    _timecode_to_seconds(merged[-1][0]))
        if prev_dur < min_sec:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    if len(merged) > 1:
        last_dur = (_timecode_to_seconds(merged[-1][1]) -
                    _timecode_to_seconds(merged[-1][0]))
        if last_dur < min_sec:
            short = merged.pop()
            merged[-1][1] = short[1]
    final = []
    for start, end in merged:
        dur = _timecode_to_seconds(end) - _timecode_to_seconds(start)
        if dur > max_sec:
            remainder = dur % max_sec
            if 0 < remainder < min_sec:
                n = math.ceil(dur / max_sec)
                total_f = end.get_frames() - start.get_frames()
                fpb = math.ceil(total_f / n)
                cur = start
                for _ in range(n):
                    nxt = FrameTimecode(min(cur.get_frames() + fpb, end.get_frames()), framerate)
                    final.append((cur, nxt))
                    cur = nxt
                    if cur >= end:
                        break
            else:
                cur = start
                while cur < end:
                    nxt = FrameTimecode(
                        min(cur.get_frames() + int(max_sec * framerate), end.get_frames()),
                        framerate,
                    )
                    final.append((cur, nxt))
                    cur = nxt
        elif dur >= min_sec:
            final.append((start, end))
    return final


def split_video(video_path: str, out_dir: str, cfg: PipelineConfig) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    video = open_video(video_path)             # PySceneDetect 0.7+ API
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=cfg.scene_threshold))
    sm.detect_scenes(video=video)
    fps = video.frame_rate
    scenes = sm.get_scene_list()
    print(f"[Split] detected {len(scenes)} raw scenes")
    clips = _adjust_scenes(scenes, cfg.min_clip_duration, cfg.max_clip_duration, fps)
    print(f"[Split] → {len(clips)} clips after duration adjustment")
    name = os.path.basename(video_path).rsplit(".", 1)[0]
    _split_clips_ffmpeg(video_path, clips, out_dir, name)
    result = sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".mp4"))
    print(f"[Split] saved {len(result)} clips → {out_dir}")
    return result


# Seedance Assets API 对 Video 输入的像素范围限制（实测）
# 太小（< 720p ≈ 921600）会被 InvalidParameter.PixelCount 拒掉
# 太大（> ~4K）也会被拒
SEEDANCE_VIDEO_MIN_PIXELS = 921600     # 1280×720
SEEDANCE_VIDEO_MAX_PIXELS = 4194304    # 2048×2048 等价


def resize_video(src: str, dst: str, limit: int,
                 min_pixels: int = SEEDANCE_VIDEO_MIN_PIXELS) -> None:
    """缩放视频到 [min_pixels, limit] 区间内（≥ 720p, ≤ pixel_limit）。

    - 像素数 > limit         → 等比缩小到 limit
    - 像素数 < min_pixels    → 等比放大到 min_pixels（避免被 Seedance 拒）
    - 中间                  → 保持原尺寸（仅重新编码）

    Seedance 对输入视频有最小像素要求（实测 480x848 = 407K 会被
    InvalidParameter.PixelCount 拒掉），所以小视频必须放大。
    """
    # ffmpeg 表达式: pixels 用 (iw*ih)
    #  scale 后宽:
    #    若 iw*ih > limit      → floor 到偶数（缩小，允许略低于 limit）
    #    若 iw*ih < min_pixels → ceil  到偶数（放大，保证 ≥ min_pixels）
    #    否则 → iw
    #  高同理
    #  注意：floor 用于缩小，ceil 用于放大；都必须落在偶数上（H.264 yuv420p 要求）
    safe_min = int(min_pixels * 1.02)  # 2% 余量，防止两边 ceil 后乘积仍卡边界
    vf_w = (
        f"if(gt(iw*ih,{limit}),floor(iw*sqrt({limit}/(iw*ih))/2)*2,"
        f"if(lt(iw*ih,{min_pixels}),ceil(iw*sqrt({safe_min}/(iw*ih))/2)*2,iw))"
    )
    vf_h = (
        f"if(gt(iw*ih,{limit}),floor(ih*sqrt({limit}/(iw*ih))/2)*2,"
        f"if(lt(iw*ih,{min_pixels}),ceil(ih*sqrt({safe_min}/(iw*ih))/2)*2,ih))"
    )
    vf = f"scale='{vf_w}':'{vf_h}'"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", src, "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "18", "-preset", "medium", "-c:a", "copy", dst]
    subprocess.run(cmd, check=True, timeout=300)


def _ffprobe_sig(path: str) -> dict:
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,sample_rate,channels",
           "-of", "json", path]
    data = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30).stdout or "{}")
    sig = {"video": None, "audio": None}
    for s in data.get("streams", []):
        t = s.get("codec_type")
        if t == "video" and sig["video"] is None:
            sig["video"] = {k: s.get(k) for k in ("codec_name", "width", "height", "pix_fmt", "avg_frame_rate")}
        if t == "audio" and sig["audio"] is None:
            sig["audio"] = {k: s.get(k) for k in ("codec_name", "sample_rate", "channels")}
    return sig


def merge_clips(
    clip_paths: List[str],
    output_path: str,
    audio_crossfade: float = 0.0,
) -> None:
    """拼接所有片段。默认走 concat 路径（无损 -c copy，无音画漂移）。

    audio_crossfade > 0 时启用相邻 clip 音频 acrossfade 平滑过渡，但每次
    crossfade 会让音轨比视频短 `audio_crossfade` 秒，N 段累积 (N-1)*fade
    秒——长片（如 50+ clip）末尾音画偏差可达数秒，**不要在长片打开**。
    """
    if not clip_paths:
        print("[Merge] nothing to merge")
        return

    # 单 clip 直接 copy
    if len(clip_paths) == 1:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", clip_paths[0], "-c", "copy", "-movflags", "+faststart", output_path],
            check=True, timeout=300,
        )
        print(f"[Merge] → {output_path}")
        return

    # crossfade=0：走老的 concat 路径（快、无损）
    if audio_crossfade <= 0:
        return _merge_clips_concat(clip_paths, output_path)

    # 主路径：filter_complex + 音频 acrossfade 链
    n = len(clip_paths)
    inputs: List[str] = []
    for p in clip_paths:
        inputs += ["-i", p]

    # 视频拼接（hard cut）
    v_in = "".join(f"[{i}:v]" for i in range(n))
    v_part = f"{v_in}concat=n={n}:v=1:a=0[v]"

    # 音频 acrossfade 链：[0:a][1:a]acrossfade=...[a01]; [a01][2:a]acrossfade=...[a02] ...
    a_parts = []
    prev = "[0:a]"
    for i in range(1, n):
        out = "[a]" if i == n - 1 else f"[a{i:03d}]"
        a_parts.append(f"{prev}[{i}:a]acrossfade=d={audio_crossfade}:c1=tri:c2=tri{out}")
        prev = out

    fc = ";".join([v_part] + a_parts)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + inputs + [
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, check=True, timeout=600)   # merge 整片可能多个 clip 时间较长
    print(f"[Merge] → {output_path}  (audio crossfade {audio_crossfade}s)")


def _merge_clips_concat(clip_paths: List[str], output_path: str) -> None:
    """老的快速 concat（无音频平滑，保留作为 audio_crossfade=0 的回退）。"""
    sigs = [_ffprobe_sig(p) for p in clip_paths]
    compatible = all(s == sigs[0] for s in sigs[1:])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_path = f.name
        for p in clip_paths:
            escaped = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    try:
        base_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", list_path]
        if compatible:
            extra = ["-c", "copy", "-movflags", "+faststart"]
        else:
            extra = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
                     "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
        subprocess.run(base_cmd + extra + [output_path], check=True, timeout=600)
        print(f"[Merge] → {output_path}")
    finally:
        try:
            os.remove(list_path)
        except Exception:
            pass
