import base64
import json
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from video_cartoonize.sub_shot_detect import detect_sub_shots, extract_sub_shot_keyframes

_ARK_IMAGE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations"


def _seedream_i2i(
    frame_path: str,
    style_ref_paths: List[str],
    api_key: str,
    prompt: str,
    model: str = "seedream-5-0-260128",
    size: str = "1440x2560",
) -> Optional[bytes]:
    all_paths = [frame_path] + style_ref_paths[:13]
    image_refs = []
    for p in all_paths:
        with open(p, "rb") as f:
            b64 = base64.standard_b64encode(f.read()).decode()
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        image_refs.append(f"data:image/{mime};base64,{b64}")

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "size": size,
        "image": image_refs,
        "watermark": False,
    }).encode()

    req = urllib.request.Request(
        _ARK_IMAGE_URL,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        img_url = result["data"][0]["url"]
        with urllib.request.urlopen(img_url, timeout=60) as r:
            return r.read()
    except Exception as e:
        print(f"[Seedream I2I] error: {e}")
        return None


def _extract_last_frame(clip_path: str, out_dir: str, clip_id: int) -> Optional[str]:
    """提取 clip 真正的最后一帧。

    用 accurate seek（-ss 放在 -i 之后），精确定位到 dur-0.05s 附近的真实帧，
    避免快速 seek（-ss before -i）跳到最近关键帧，也避免 -sseof 极小偏移
    引发的 mjpeg 编码失败。
    """
    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", clip_path]
    try:
        dur = float(subprocess.check_output(cmd_dur, text=True).strip())
    except Exception:
        return None

    seek = max(0.0, dur - 0.05)  # 距片尾 1 帧左右（@20fps），保证有内容
    dst  = os.path.join(out_dir, f"clip_{clip_id:02d}_last_frame.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", clip_path,           # input 在前 → accurate seek
           "-ss", f"{seek:.3f}",
           "-frames:v", "1", "-update", "1", dst]
    try:
        subprocess.run(cmd, check=True)
        return dst if os.path.exists(dst) and os.path.getsize(dst) > 0 else None
    except subprocess.CalledProcessError:
        return None


def _get_duration(clip_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", clip_path]
    try:
        return float(subprocess.check_output(cmd, text=True).strip())
    except Exception:
        return 0.0


def _extract_frame_at(clip_path: str, seek: float, dst: str) -> Optional[str]:
    """Accurate seek 提取指定时间的一帧 JPEG。"""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", clip_path,                # input 在前 → accurate seek
           "-ss", f"{seek:.3f}",
           "-frames:v", "1", "-update", "1", dst]
    try:
        subprocess.run(cmd, check=True)
        return dst if os.path.exists(dst) and os.path.getsize(dst) > 0 else None
    except subprocess.CalledProcessError:
        return None


def extract_keyframes(
    clip_path: str,
    out_dir: str,
    clip_id: int,
    threshold: float = 27.0,
    last_frame_min_gap: float = 1.0,
    max_gap: float = 2.0,
) -> List[str]:
    """Phase 2a — 提取关键帧，保证时间均匀覆盖。

    生成的关键帧 = 子镜头首帧 + (可选) 末帧 + 大间隔内的等距填充帧。

    参数:
        threshold: 子镜头检测阈值（PySceneDetect ContentDetector）
        last_frame_min_gap: 末帧与最后一个子镜头帧的最小时间差，小于此值不加末帧
        max_gap: 任意两个相邻关键帧的最大允许时间差，超过则按 max_gap 等距填充
    """
    clip_frame_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(clip_frame_dir, exist_ok=True)

    # 1) 子镜头边界（每个都会作为关键帧）
    boundaries = detect_sub_shots(clip_path, threshold=threshold)
    dur = _get_duration(clip_path)

    # 2) 构造目标时间列表（含 nudge 后的实际取帧时刻）
    target_times: List[float] = []
    for t in boundaries:
        target_times.append(max(0.05, t + 0.1))  # 子镜头首帧 nudge

    # 3) 末帧（若距最后子镜头帧 > last_frame_min_gap）
    add_last = False
    if dur > 0 and target_times and (dur - target_times[-1]) > last_frame_min_gap:
        target_times.append(max(0.0, dur - 0.05))
        add_last = True

    # 4) 检查相邻间隔，> max_gap 的位置插入等距填充帧
    filled: List[float] = [target_times[0]]
    insert_count = 0
    for i in range(1, len(target_times)):
        gap = target_times[i] - target_times[i - 1]
        if gap > max_gap:
            n = int(gap // max_gap)              # 需要插入的帧数
            step = gap / (n + 1)
            for j in range(1, n + 1):
                filled.append(round(target_times[i - 1] + j * step, 3))
                insert_count += 1
        filled.append(target_times[i])

    # 5) 提取每个时间点的帧到 jpg
    paths: List[str] = []
    sub_idx = 0
    fill_idx = 0
    for t in filled:
        # 判断是哪种帧（用于文件名）
        if t in target_times[:len(boundaries)]:
            name = f"sub_{sub_idx:02d}_t{t:.2f}.jpg"
            sub_idx += 1
        elif add_last and t == target_times[-1]:
            name = f"last_frame_t{t:.2f}.jpg"
        else:
            name = f"fill_{fill_idx:02d}_t{t:.2f}.jpg"
            fill_idx += 1
        dst = os.path.join(clip_frame_dir, f"clip_{clip_id:02d}_{name}")
        got = _extract_frame_at(clip_path, t, dst)
        if got:
            paths.append(got)

    print(
        f"[Phase 2a] clip {clip_id:02d}: {len(paths)} frames "
        f"(boundaries={len(boundaries)}, last={'+1' if add_last else '0'}, "
        f"fills={insert_count}, dur={dur:.2f}s, max_gap={max_gap}s)"
    )
    return paths


def cartoonize_subshot_frames(
    frame_paths: List[str],
    out_dir: str,
    style,
    api_key: str,
    clip_id: int = 0,
    model: str = "seedream-5-0-260128",
    size: str = "1440x2560",
    max_workers: int = 5,
) -> List[str]:
    """Phase 2b — Seedream I2I on every key frame for one clip (concurrent)."""
    style_refs = list(style.ref_images) + list(style.user_ref_images)
    cartoon_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(cartoon_dir, exist_ok=True)

    def process_one(j: int, frame_path: str):
        cartoon_path = os.path.join(cartoon_dir, f"sub_{j:02d}_cartoon.jpg")
        img_bytes = _seedream_i2i(
            frame_path=frame_path,
            style_ref_paths=style_refs,
            api_key=api_key,
            prompt=style.seedream_prompt,
            model=model,
            size=size,
        )
        if img_bytes:
            with open(cartoon_path, "wb") as f:
                f.write(img_bytes)
            print(f"[Phase 2b] clip {clip_id:02d} sub {j:02d} ✓")
            return j, cartoon_path
        print(f"[Phase 2b] clip {clip_id:02d} sub {j:02d} ✗ Seedream failed")
        return j, None

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_one, j, p): j for j, p in enumerate(frame_paths)}
        for f in as_completed(futures):
            j, path = f.result()
            results[j] = path

    return [results[j] for j in sorted(results) if results[j]]
