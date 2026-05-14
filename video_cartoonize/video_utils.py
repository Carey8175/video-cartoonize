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


def resize_video(src: str, dst: str, limit: int) -> None:
    vf = (
        f"scale='if(lte(iw*ih,{limit}),iw,floor(iw*sqrt({limit}/(iw*ih))/2)*2)':"
        f"'if(lte(iw*ih,{limit}),ih,floor(ih*sqrt({limit}/(iw*ih))/2)*2)'"
    )
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
    audio_crossfade: float = 0.1,
) -> None:
    """拼接所有片段，音轨在相邻片段间做 crossfade 平滑过渡。

    audio_crossfade: 相邻 clip 之间音频交叉淡化的时长（秒），设 0 关闭。
    视频按 hard cut 拼接（无视觉过渡），音频用 acrossfade 平滑。
    总体音频会因 crossfade 略短于视频 (N-1)*fade 秒，mp4 容器允许末尾
    短时无声，绝大多数播放器无感。
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
