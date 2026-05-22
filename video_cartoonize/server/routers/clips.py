"""POST /api/projects/{id}/clips/{clip_id}/regen"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from video_cartoonize.server.db import models as db_models
from video_cartoonize.server.deps import DB, Credentials, Redis, WorkDir, load_state
from video_cartoonize.server.schemas.job import PipelineJobView, RegenRequest
from video_cartoonize.server.services import job_service

router = APIRouter(prefix="/api/projects/{project_id}/clips", tags=["clips"])


@router.post("/{clip_id}/regen", response_model=PipelineJobView, status_code=202)
async def regen_clip(
    project_id: str,
    clip_id: int,
    req: RegenRequest,
    work_dir: WorkDir,
    db: DB,
    redis: Redis,
    creds: Credentials,
):
    """重新生成单帧（scope=frame）或整片（scope=whole-clip）。"""
    state = load_state(work_dir)
    clips = {c["clip_id"]: c for c in state.get("clips", [])}
    if clip_id not in clips:
        raise HTTPException(404, f"clip_id {clip_id} not found")

    if req.scope == "frame" and req.frame_idx is None:
        raise HTTPException(422, "frame_idx is required when scope=frame")

    # step 选择：帧级 → cartoon（单帧 I2I），整片 → run（完整编排）
    step = "cartoon" if req.scope == "frame" else "run"

    step_request = {
        "clip_id": clip_id,
        "scope": req.scope,
        "frame_idx": req.frame_idx,
        "style_strength": req.style_strength,
        "seed": req.seed,
    }
    if req.prompt:
        step_request["prompt_override"] = req.prompt

    try:
        job = await job_service.submit_job(
            db=db,
            redis=redis,
            project_id=project_id,
            work_dir=work_dir,
            step=step,
            step_request=step_request,
            credentials=creds,
            work_root=work_dir,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    # 记录 regen 历史
    db.add(db_models.RegenHistory(
        project_id=project_id,
        clip_id=clip_id,
        frame_idx=req.frame_idx,
        scope=req.scope,
        prompt=req.prompt,
        style_strength=req.style_strength,
        seed=req.seed,
        job_id=job.job_id,
        created_at=int(time.time()),
    ))
    await db.commit()

    return PipelineJobView(
        job_id=job.job_id,
        project_id=job.project_id,
        step=job.step,
        clip_id=job.clip_id,
        status=job.status,
        created_at=job.created_at,
    )
