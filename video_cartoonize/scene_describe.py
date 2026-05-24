import base64
import json
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from video_cartoonize import billing
from video_cartoonize.sub_shot_detect import extract_sub_shot_keyframes

_ARK_IMAGE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations"

# Seedream 5.0 lite (and 4-5) require output pixels ∈ [3_686_400, 16_777_216]
# and aspect (w/h) ∈ [1/16, 16]. Target sits ~6% above the floor so any
# multiple-of-8 rounding still clears it.
_SEEDREAM_PX_FLOOR  = 3_686_400
_SEEDREAM_PX_TARGET = 3_900_000


def _seedream_size_for_frame(frame_path: str) -> str:
    """Return ``WxH`` matching the frame's aspect ratio at the Seedream
    pixel floor. Falls back to ``1440x2560`` (9:16, floor) if the image
    cannot be opened.
    """
    try:
        from PIL import Image
        with Image.open(frame_path) as im:
            w, h = im.size
    except Exception:
        return "1440x2560"
    if not w or not h:
        return "1440x2560"
    ar = max(1 / 16, min(16.0, w / h))
    out_h = (_SEEDREAM_PX_TARGET / ar) ** 0.5
    out_w = out_h * ar
    out_w = ((int(out_w) + 7) // 8) * 8
    out_h = ((int(out_h) + 7) // 8) * 8
    while out_w * out_h < _SEEDREAM_PX_FLOOR:
        out_w += 8
        out_h += 8
    return f"{out_w}x{out_h}"


def _seedream_i2i(
    frame_path: str,
    style_ref_paths: List[str],
    api_key: str,
    prompt: str,
    model: str = "seedream-5-0-260128",
    size: Optional[str] = None,
    clip_id: int | None = None,
) -> Optional[bytes]:
    if not size or size == "auto":
        size = _seedream_size_for_frame(frame_path)
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
        usage = result.get("usage") or {}
        with urllib.request.urlopen(img_url, timeout=60) as r:
            img_bytes = r.read()
        # 记账：Seedream 返回 usage.output_tokens / total_tokens / generated_images
        billing.record(
            "seedream",
            clip_id=clip_id,
            model=model,
            size=size,
            ref_count=len(image_refs),
            images=int(usage.get("generated_images", 1) or 1),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )
        return img_bytes
    except Exception as e:
        print(f"[Seedream I2I] error: {e}")
        return None


def _extract_last_frame(clip_path: str, out_dir: str, clip_id: int) -> Optional[str]:
    """提取 clip 尾帧，严格取最后一帧。

    不再选择末尾区域的"最清晰"帧，避免改变剧情时间点。只有最后一帧全黑或全白
    时，才逐帧向前回退，直到找到亮度正常的帧。
    """
    from video_cartoonize.sub_shot_detect import _extract_fixed_endpoint_frame

    dst = os.path.join(out_dir, f"clip_{clip_id:02d}_last_frame.jpg")
    seek = _extract_fixed_endpoint_frame(clip_path, dst, endpoint="last")
    if seek is None:
        return None
    print(f"[sub_shot] clip {clip_id:02d} last_frame fixed t={seek:.2f}")
    return dst


def _get_duration(clip_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", clip_path]
    try:
        return float(subprocess.check_output(cmd, text=True, timeout=30).strip())
    except Exception:
        return 0.0


def extract_keyframes(
    clip_path: str,
    out_dir: str,
    clip_id: int,
    threshold: float = 27.0,
    last_frame_min_gap: float = 1.0,
    include_last_frame: bool = False,   # 默认不取末帧（内部参数，CLI 不暴露）
) -> List[str]:
    """Phase 2a — sub-shot first frames (+ optional last frame)。

    默认只取子镜头切换后的首帧（用户定义的"关键帧"）。
    include_last_frame=True 时才追加末帧，且要求与最后一个子镜头帧间隔
    > last_frame_min_gap，避免帧过近引起视频跳变。

    最少保证 2 张关键帧：若提取后只剩 1 张，自动强制追加末帧，让 Seedance
    有足够的时间轴锚点，不用考虑 last_frame_min_gap。
    """
    clip_frame_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(clip_frame_dir, exist_ok=True)

    subshot_kfs = extract_sub_shot_keyframes(clip_path, clip_frame_dir, threshold=threshold)
    paths = [p for _t, p in subshot_kfs]

    added_last = False
    need_last = include_last_frame or (len(paths) < 2)   # 不足 2 张时强制加末帧

    if need_last:
        dur = _get_duration(clip_path)
        last_kf_time   = subshot_kfs[-1][0] if subshot_kfs else 0.0
        last_kf_actual = max(0.05, last_kf_time + 0.1)
        # 只有 1 张时忽略 gap 限制（哪怕末帧很近也要加，保证最少 2 张）
        min_gap = last_frame_min_gap if include_last_frame else 0.0
        if dur > 0 and (dur - last_kf_actual) > min_gap:
            last = _extract_last_frame(clip_path, clip_frame_dir, clip_id)
            if last:
                paths.append(last)
                added_last = True
        elif len(paths) < 2:
            # gap 太小（短 clip）：直接把中间帧作为第二张
            mid_t = dur / 2.0 if dur > 0 else 0.5
            from video_cartoonize.sub_shot_detect import _extract_frame
            mid_dst = os.path.join(clip_frame_dir,
                                   f"{Path(clip_path).stem}_mid_t{mid_t:.2f}.jpg")
            if _extract_frame(clip_path, mid_t, mid_dst):
                paths.append(mid_dst)
                added_last = True

    suffix = " + 1 last" if added_last else ""
    if len(paths) < 2 and not added_last:
        print(f"[Phase 2a] clip {clip_id:02d}: ⚠ only {len(paths)} frame(s) after best-effort")
    else:
        print(f"[Phase 2a] clip {clip_id:02d}: {len(paths)} key frame(s) "
              f"({len(subshot_kfs)} sub-shot first{suffix})")
    return paths


def cartoonize_subshot_frames(
    frame_paths: List[str],
    out_dir: str,
    style,
    api_key: str,
    clip_id: int = 0,
    model: str = "seedream-5-0-260128",
    size: Optional[str] = None,
    max_workers: int = 5,
    extra_refs_per_frame: Optional[List[List[str]]] = None,
) -> List[str]:
    """Phase 2b — Seedream I2I on every key frame for one clip (concurrent).

    extra_refs_per_frame (0.14.10+):
      Optional list of per-frame extra reference image paths, indexed by frame
      position (same length as frame_paths).  When provided, frame j's Seedream
      call receives `style_refs + extra_refs_per_frame[j]` as image references,
      allowing per-keyframe character consistency anchoring.
    """
    style_refs  = list(style.ref_images) + list(style.user_ref_images)
    cartoon_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(cartoon_dir, exist_ok=True)

    def process_one(j: int, frame_path: str):
        cartoon_path = os.path.join(cartoon_dir, f"sub_{j:02d}_cartoon.jpg")
        # Merge global style refs with per-frame character refs (if any)
        frame_refs = style_refs.copy()
        if extra_refs_per_frame and j < len(extra_refs_per_frame):
            frame_refs = frame_refs + extra_refs_per_frame[j]
        img_bytes = _seedream_i2i(
            frame_path=frame_path,
            style_ref_paths=frame_refs,
            api_key=api_key,
            prompt=style.seedream_prompt,
            model=model,
            size=size,
            clip_id=clip_id,
        )
        if img_bytes:
            with open(cartoon_path, "wb") as f:
                f.write(img_bytes)
            has_char = bool(extra_refs_per_frame and extra_refs_per_frame[j])
            suffix   = " [+char_ref]" if has_char else ""
            print(f"[Phase 2b] clip {clip_id:02d} sub {j:02d} ✓{suffix}")
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


def cartoonize_extra_subshot_frames(
    new_frame_paths: List[str],
    out_dir: str,
    style,
    api_key: str,
    clip_id: int,
    start_index: int,
    model: str = "seedream-5-0-260128",
    size: Optional[str] = None,
    max_workers: int = 5,
) -> List[str]:
    """Append-only Seedream I2I — used by `cmd_poll` for attempt-2/3 retries.

    Same as `cartoonize_subshot_frames` but for *additional* frames only.
    Writes `sub_{start_index+j:02d}_cartoon.jpg` so existing cartoons (indices
    0..start_index-1) are never overwritten. Returns the list of newly-written
    cartoon paths in order; failed Seedream calls are silently dropped (the
    caller can detect a short return list and decide whether to bail).
    """
    style_refs = list(style.ref_images) + list(style.user_ref_images)
    cartoon_dir = os.path.join(out_dir, f"clip_{clip_id:02d}")
    os.makedirs(cartoon_dir, exist_ok=True)

    def process_one(j: int, frame_path: str):
        idx = start_index + j
        cartoon_path = os.path.join(cartoon_dir, f"sub_{idx:02d}_cartoon.jpg")
        img_bytes = _seedream_i2i(
            frame_path=frame_path,
            style_ref_paths=style_refs,
            api_key=api_key,
            prompt=style.seedream_prompt,
            model=model,
            size=size,
            clip_id=clip_id,
        )
        if img_bytes:
            with open(cartoon_path, "wb") as f:
                f.write(img_bytes)
            print(f"[Retry-Phase2b] clip {clip_id:02d} sub {idx:02d} ✓")
            return idx, cartoon_path
        print(f"[Retry-Phase2b] clip {clip_id:02d} sub {idx:02d} ✗ Seedream failed")
        return idx, None

    results: Dict[int, Optional[str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_one, j, p): j for j, p in enumerate(new_frame_paths)}
        for f in as_completed(futures):
            idx, path = f.result()
            results[idx] = path

    return [results[k] for k in sorted(results) if results[k]]
