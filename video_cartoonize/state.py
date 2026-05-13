"""State file (state.json) read/write helpers."""
import json
import os
from typing import List, Optional

from video_cartoonize.models import ClipInfo

STATE_FILE = "state.json"


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
    return c


def clips_from_state(state: dict) -> List[ClipInfo]:
    return [dict_to_clip(d) for d in state.get("clips", [])]


def clips_to_state(state: dict, clips: List[ClipInfo]) -> None:
    state["clips"] = [clip_to_dict(c) for c in clips]


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
