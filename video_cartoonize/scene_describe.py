import base64
import json
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from video_cartoonize.sub_shot_detect import extract_sub_shot_keyframes

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
    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", clip_path]
    try:
        dur = float(subprocess.check_output(cmd_dur, text=True).strip())
    except Exception:
        return None
    seek = max(0.0, dur - 0.1)
    dst = os.path.join(out_dir, f"clip_{clip_id:02d}_last_frame.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{seek:.3f}", "-i", clip_path,
           "-frames:v", "1", "-update", "1", dst]
    try:
        subprocess.run(cmd, check=True)
        return dst
    except subprocess.CalledProcessError:
        return None


def extract_keyframes(
    clip_path: str,
    out_dir: str,
    clip_id: int,
    threshold: float = 27.0,
) -> List[str]:
    """Phase 2a — sub-shot first frames + last frame for one clip."""
    clip_frame_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(clip_frame_dir, exist_ok=True)

    subshot_kfs = extract_sub_shot_keyframes(clip_path, clip_frame_dir, threshold=threshold)
    paths = [p for _t, p in subshot_kfs]

    last = _extract_last_frame(clip_path, clip_frame_dir, clip_id)
    if last:
        paths.append(last)

    print(f"[Phase 2a] clip {clip_id:02d}: {len(paths)} key frame(s) "
          f"({len(subshot_kfs)} sub-shot first + 1 last)")
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
