"""GET /api/jobs/{job_id}  GET /api/jobs  GET /api/tasks/history"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Header, Query
from sqlalchemy import select, desc

from video_cartoonize.server.db import models as db_models
from video_cartoonize.server.deps import DB
from video_cartoonize.server.schemas.job import PipelineJobView

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=PipelineJobView)
async def get_job(job_id: str, db: DB):
    job = await db.get(db_models.PipelineJob, job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(404, f"Job {job_id!r} not found")
    return PipelineJobView.model_validate(job)


@router.get("/jobs", response_model=list[PipelineJobView])
async def list_jobs(
    db: DB,
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, le=100),
):
    """列出 job 历史（最近 N 条）。"""
    q = select(db_models.PipelineJob).order_by(desc(db_models.PipelineJob.created_at)).limit(limit)
    if project_id:
        q = q.where(db_models.PipelineJob.project_id == project_id)
    if status:
        q = q.where(db_models.PipelineJob.status == status)
    rows = (await db.execute(q)).scalars().all()
    return [PipelineJobView.model_validate(r) for r in rows]


@router.get("/tasks/history")
async def task_history(
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=100),
    x_ark_api_key: str = Header(default="", alias="X-Ark-Api-Key"),
):
    """按 API key 查询 Seedance 历史任务（Tasks History 页面）。

    key 本体不落库；用 SHA-256 hash 做查询 token。
    """
    if not x_ark_api_key:
        from fastapi import HTTPException
        raise HTTPException(401, "X-Ark-Api-Key header required")

    key_hash = hashlib.sha256(x_ark_api_key.encode()).hexdigest()
    offset = (page - 1) * page_size

    rows = (await db.execute(
        select(db_models.SeedanceTask)
        .where(db_models.SeedanceTask.api_key_hash == key_hash)
        .order_by(desc(db_models.SeedanceTask.submitted_at))
        .limit(page_size)
        .offset(offset)
    )).scalars().all()

    return [
        {
            "task_id": r.task_id,
            "project_id": r.project_id,
            "clip_id": r.clip_id,
            "model": r.model,
            "resolution": r.resolution,
            "status": r.status,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "submitted_at": r.submitted_at,
            "finished_at": r.finished_at,
            "is_regen": bool(r.is_regen),
        }
        for r in rows
    ]
