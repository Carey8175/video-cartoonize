"""State Adapter — state.json → API schema.

**这是 CLI schema 变更时唯一需要修改的地方。**

当 CLI 把 state.json 升级到 v6、v7… 时：
  1. 在 _adapt_clip() / _adapt_subshot() 里加/改字段映射
  2. 更新 SUPPORTED_VERSIONS 集合
  3. 其余 service / router 层无需改动

设计原则：
  - 只做字段映射，不做业务计算
  - 对未知/缺失字段给安全默认值（.get with default），不抛 KeyError
  - 把 local 文件路径转成 /api/…/files/ URL（路径到 URL 的唯一转换点）
"""
from __future__ import annotations

import os
from typing import Any

from video_cartoonize.server.schemas.project import (
    ClipView,
    ProjectView,
    SourceInfo,
    SubshotView,
)

# state.json schema 版本白名单；版本不在此集合时打 warning 但仍尝试适配
SUPPORTED_VERSIONS = {4, 5}


def state_to_project_view(
    state: dict[str, Any],
    project_id: str,
    work_dir: str,
) -> ProjectView:
    """顶层转换入口：整个 state.json → ProjectView。"""
    version = state.get("version", 1)
    if version not in SUPPORTED_VERSIONS:
        import logging
        logging.getLogger(__name__).warning(
            "state.json version=%s not in supported set %s; attempting adaptation",
            version, SUPPORTED_VERSIONS,
        )

    clips = [
        _adapt_clip(c, project_id, work_dir)
        for c in state.get("clips", [])
    ]

    final_video = state.get("final_video", "")
    final_video_url = (
        f"/api/projects/{project_id}/files/final/merged.mp4"
        if final_video and os.path.exists(final_video)
        else None
    )

    return ProjectView(
        id=project_id,
        work_dir=work_dir,
        version=version,
        source=_adapt_source(state.get("source") or state),  # v4 puts source fields at top level
        config=_adapt_config(state.get("config", {})),
        clips=clips,
        merged=bool(final_video),
        final_video_url=final_video_url,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _adapt_source(raw: dict[str, Any]) -> SourceInfo:
    """state.source → SourceInfo。兼容 v4（顶层）和 v5（嵌套）。"""
    return SourceInfo(
        name=raw.get("name") or raw.get("input_video", ""),
        size_mb=float(raw.get("size_mb", 0)),
        duration_s=float(raw.get("duration_s", 0)),
        resolution=raw.get("resolution", ""),
        fps=int(raw.get("fps", 0)),
        codec=raw.get("codec", ""),
    )


def _adapt_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """state.config → 前端 config 对象（去掉 api_key，只透传展示字段）。"""
    safe_keys = {
        "style_id", "seedream_model", "seedance_model", "seedance_resolution",
        "seedream_image_size", "scene_threshold", "min_clip_duration",
        "max_clip_duration", "subshot_threshold", "analyse_fps",
        "max_retries", "poll_interval",
    }
    return {k: v for k, v in cfg.items() if k in safe_keys}


def _adapt_clip(raw: dict[str, Any], project_id: str, work_dir: str) -> ClipView:
    """单个 clip dict → ClipView。"""
    clip_id = raw["clip_id"]

    subshots = [
        _adapt_subshot(s, clip_id, project_id, work_dir)
        for s in raw.get("subshots", _build_subshots_from_paths(raw))
    ]

    return ClipView(
        clip_id=clip_id,
        duration_s=float(raw.get("duration_s", 0)),
        ratio=raw.get("ratio", ""),
        width=int(raw.get("width", 0)),
        height=int(raw.get("height", 0)),
        status=raw.get("status", "pending"),
        task_id=raw.get("task_id", ""),
        task_status=raw.get("task_status"),
        task_progress=float(raw.get("task_progress", 0)),
        retries=int(raw.get("retries", 0)),
        style_verified=bool(raw.get("style_verified", False)),
        subshots=subshots,
        attempts=raw.get("attempts", []),
    )


def _adapt_subshot(
    raw: dict[str, Any],
    clip_id: int,
    project_id: str,
    work_dir: str,
) -> SubshotView:
    """单个 subshot dict → SubshotView；把本地路径转成 API URL。"""
    idx = raw.get("idx", raw.get("index", 0))

    def to_url(local_path: str | None) -> str | None:
        """本地绝对/相对路径 → /api/projects/{id}/files/{rel} URL。"""
        if not local_path:
            return None
        # 若已经是 URL，直接返回
        if local_path.startswith("http"):
            return local_path
        # 转成相对于 work_dir 的路径
        abs_path = local_path if os.path.isabs(local_path) else os.path.join(work_dir, local_path)
        try:
            rel = os.path.relpath(abs_path, work_dir)
        except ValueError:
            rel = local_path
        return f"/api/projects/{project_id}/files/{rel}"

    # subshot_frame_paths / subshot_cartoon_paths 是 per-clip 的 list，
    # subshots 可能用 idx 索引；两种 schema 都兼容。
    kf_path = (raw.get("keyframe_path") or raw.get("frame_path") or "")
    cartoon_path = raw.get("cartoon_path") or raw.get("cartoon") or ""

    # cartoon_asset_url 是持久 TOS URL，直接透传（不走 /files/ 代理）
    cartoon_asset_url = raw.get("cartoon_asset_url") or raw.get("cartoon_url") or ""
    if cartoon_asset_url and not cartoon_asset_url.startswith("http"):
        cartoon_asset_url = ""  # 非 http URL 视为无效

    return SubshotView(
        idx=idx,
        t_start=float(raw.get("t_start", 0)),
        t_end=float(raw.get("t_end", 0)),
        keyframe_url=to_url(kf_path),
        cartoon_url=to_url(cartoon_path) if cartoon_path else None,
        cartoon_asset_url=cartoon_asset_url or None,
        vlm_pass=raw.get("vlm_pass"),
        vlm_score=raw.get("vlm_score"),
        vlm_reason=raw.get("vlm_reason") or raw.get("verify_reason") or "",
    )


def _build_subshots_from_paths(clip: dict[str, Any]) -> list[dict]:
    """兼容旧 schema：subshots 字段不存在时，从 subshot_frame_paths 重建。"""
    frame_paths   = clip.get("subshot_frame_paths", [])
    cartoon_paths = clip.get("subshot_cartoon_paths", [])
    cartoon_urls  = clip.get("subshot_cartoon_urls", [])

    result = []
    for i, fp in enumerate(frame_paths):
        result.append({
            "idx": i,
            "t_start": 0.0,
            "t_end": 0.0,
            "keyframe_path": fp,
            "cartoon_path": cartoon_paths[i] if i < len(cartoon_paths) else "",
            "cartoon_asset_url": cartoon_urls[i] if i < len(cartoon_urls) else "",
            "vlm_pass": None,
            "vlm_score": None,
            "vlm_reason": clip.get("verify_reason", ""),
        })
    return result
