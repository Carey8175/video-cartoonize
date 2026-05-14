"""State file (state.json) read/write helpers."""
import fcntl
import json
import os
from contextlib import contextmanager
from typing import List, Optional

from video_cartoonize.models import ClipInfo

STATE_FILE = "state.json"
LOCK_FILE  = ".state.lock"


def path(work_dir: str) -> str:
    return os.path.join(work_dir, STATE_FILE)


def load(work_dir: str) -> Optional[dict]:
    p = path(work_dir)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(work_dir: str, state: dict) -> None:
    p   = path(work_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def require(work_dir: str) -> dict:
    """Load state or exit with error."""
    s = load(work_dir)
    if s is None:
        raise SystemExit(
            f"state.json not found in {work_dir}\n"
            "Run `cartoonize init --input VIDEO` first."
        )
    return s


# ── ClipInfo serialization ──────────────────────────────────────────────────

def clip_to_dict(c: ClipInfo) -> dict:
    return {
        "clip_id":               c.clip_id,
        "raw_path":              c.raw_path,
        "resized_path":          c.resized_path,
        "subshot_frame_paths":   c.subshot_frame_paths,
        "subshot_cartoon_paths": c.subshot_cartoon_paths,
        "subshot_cartoon_urls":  c.subshot_cartoon_urls,
        "task_id":               c.task_id,
        "output_url":            c.output_url,
        "output_path":           c.output_path,
        "status":                c.status,
        "retries":               c.retries,
        "style_verified":        c.style_verified,
        "verify_attempts":       c.verify_attempts,
        "verify_reason":         c.verify_reason,
    }


def dict_to_clip(d: dict) -> ClipInfo:
    c = ClipInfo(clip_id=d["clip_id"],
                 raw_path=d["raw_path"],
                 resized_path=d["resized_path"])
    c.subshot_frame_paths   = d.get("subshot_frame_paths", [])
    c.subshot_cartoon_paths = d.get("subshot_cartoon_paths", [])
    c.subshot_cartoon_urls  = d.get("subshot_cartoon_urls", [])
    c.task_id               = d.get("task_id", "")
    c.output_url            = d.get("output_url", "")
    c.output_path           = d.get("output_path", "")
    c.status                = d.get("status", "pending")
    c.retries               = d.get("retries", 0)
    c.style_verified        = d.get("style_verified", False)
    c.verify_attempts       = d.get("verify_attempts", 0)
    c.verify_reason         = d.get("verify_reason", "")
    return c


def clips_from_state(state: dict) -> List[ClipInfo]:
    return [dict_to_clip(d) for d in state.get("clips", [])]


def clips_to_state(state: dict, clips: List[ClipInfo]) -> None:
    """整体替换 clips 数组（用于 split 阶段第一次写入）。"""
    state["clips"] = [clip_to_dict(c) for c in clips]


def merge_clips(state: dict, updated: List[ClipInfo]) -> None:
    """按 clip_id 增量合并；只更新传入的 clip，其他 clip 字段保持不变。

    用于并发安全的 per-clip 写入场景（cartoon / vlm / upload / submit）。
    """
    by_id = {c["clip_id"]: c for c in state.get("clips", [])}
    for c in updated:
        by_id[c.clip_id] = clip_to_dict(c)
    state["clips"] = [by_id[k] for k in sorted(by_id.keys())]


# ── 跨进程互斥锁 ─────────────────────────────────────────────────────────────

@contextmanager
def lock(work_dir: str):
    """对 state.json 加排他锁，配合 read-modify-write 防止并发覆盖。

    用法:
        with state.lock(work_dir):
            s = state.require(work_dir)   # 重新读取最新状态
            ... 增量修改 s ...
            state.save(work_dir, s)
    """
    os.makedirs(work_dir, exist_ok=True)
    lock_path = os.path.join(work_dir, LOCK_FILE)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cfg_from_state(state: dict):
    from video_cartoonize.config import PipelineConfig
    c = state["config"]
    return PipelineConfig(
        scene_threshold     = c.get("scene_threshold",    25.0),
        min_clip_duration   = c.get("min_clip_duration",   4.0),
        max_clip_duration   = c.get("max_clip_duration",  15.0),
        pixel_limit         = c.get("pixel_limit",      927408),
        subshot_threshold   = c.get("subshot_threshold",  27.0),
        style_id            = c.get("style_id",         "anime"),
        seedream_model      = c.get("seedream_model",   "seedream-5-0-260128"),
        seedream_image_size = c.get("seedream_image_size", "1440x2560"),
        analyse_fps         = c.get("analyse_fps",           4),
        api_key             = c.get("api_key",              ""),
        seedance_model      = c.get("seedance_model",   "dreamina-seedance-2-0-260128"),
        seedance_resolution = c.get("seedance_resolution",  "720p"),
        max_retries         = c.get("max_retries",           2),
        poll_interval       = c.get("poll_interval",        10),
    )
