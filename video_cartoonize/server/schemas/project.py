"""API response schemas (Pydantic v2)。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SubshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    t_start: float
    t_end: float
    keyframe_url: str | None = None
    cartoon_url: str | None = None
    cartoon_asset_url: str | None = None
    vlm_pass: bool | None = None
    vlm_score: float | None = None
    vlm_reason: str = ""


class ClipView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    clip_id: int
    duration_s: float
    ratio: str
    width: int
    height: int
    status: str
    task_id: str = ""
    task_status: str | None = None
    task_progress: float = 0
    retries: int = 0
    style_verified: bool = False
    subshots: list[SubshotView] = []
    attempts: list[dict[str, Any]] = []


class SourceInfo(BaseModel):
    name: str
    size_mb: float
    duration_s: float
    resolution: str
    fps: int
    codec: str


class ProjectView(BaseModel):
    id: str
    work_dir: str
    version: int
    source: SourceInfo
    config: dict[str, Any]
    clips: list[ClipView]
    merged: bool = False
    final_video_url: str | None = None


class ProjectSummary(BaseModel):
    id: str
    source_name: str | None
    style_id: str
    created_at: int
    clips_done: int
    clips_total: int
