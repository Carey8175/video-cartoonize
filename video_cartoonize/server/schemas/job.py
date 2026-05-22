from __future__ import annotations
from pydantic import BaseModel


class PipelineJobView(BaseModel):
    job_id: str
    project_id: str
    step: str
    clip_id: int | None = None
    status: str
    error: str | None = None
    log_path: str | None = None
    started_at: int | None = None
    finished_at: int | None = None
    created_at: int


class StepRequest(BaseModel):
    """通用 pipeline 步骤请求体；所有字段可选，由 registry 按需取用。"""
    clip_id: int | None = None
    dry_run: bool = False
    # split overrides
    scene_threshold: float | None = None
    min_clip_duration: float | None = None
    max_clip_duration: float | None = None
    # keyframes override
    subshot_threshold: float | None = None
    # cartoon overrides
    style_id: str | None = None
    style_strength: float | None = None
    seed: int | None = None
    custom_ref_urls: list[str] = []
    prompt_override: str | None = None


class RegenRequest(BaseModel):
    scope: str = "frame"          # frame | whole-clip
    frame_idx: int | None = None
    prompt: str | None = None
    style_strength: float = 0.75
    seed: int | None = None


class CredentialVerifyRequest(BaseModel):
    ark_api_key: str
    tos_ak: str | None = None
    tos_sk: str | None = None


class CredentialResult(BaseModel):
    valid: bool
    error: str | None = None


class CredentialVerifyResponse(BaseModel):
    ark: CredentialResult
    tos: CredentialResult | None = None
