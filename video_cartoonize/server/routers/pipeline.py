"""POST /api/projects/{id}/pipeline/{step}
   GET  /api/projects/{id}/events  (SSE)
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from video_cartoonize.server.deps import DB, Credentials, Redis, WorkDir
from video_cartoonize.server.pipeline.registry import STEP_REGISTRY
from video_cartoonize.server.schemas.job import PipelineJobView, StepRequest
from video_cartoonize.server.services import job_service, sse_service

router = APIRouter(prefix="/api/projects/{project_id}", tags=["pipeline"])


@router.post("/pipeline/{step}", response_model=PipelineJobView, status_code=202)
async def trigger_step(
    project_id: str,
    step: str,
    req: StepRequest,
    work_dir: WorkDir,
    db: DB,
    redis: Redis,
    creds: Credentials,
):
    """触发一个 pipeline 步骤（异步执行）。

    未知 step → 422（KeyError from registry）。
    已有 job 运行中 → 409。
    """
    # 校验步骤名
    try:
        from video_cartoonize.server.pipeline.registry import get_step
        get_step(step)
    except KeyError as e:
        raise HTTPException(422, str(e))

    # merge 前置检查：所有 clips 必须 done
    if step == "merge":
        import json, os
        state_path = os.path.join(work_dir, "state.json")
        with open(state_path) as f:
            state = json.load(f)
        not_done = [c["clip_id"] for c in state.get("clips", []) if c.get("status") != "done"]
        if not_done:
            raise HTTPException(
                409,
                f"Cannot merge: {len(not_done)} clip(s) not done yet: {not_done[:5]}…"
            )

    try:
        job = await job_service.submit_job(
            db=db,
            redis=redis,
            project_id=project_id,
            work_dir=work_dir,
            step=step,
            step_request=req.model_dump(exclude_none=True),
            credentials=creds,
            work_root=work_dir,
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e))

    return PipelineJobView(
        job_id=job.job_id,
        project_id=job.project_id,
        step=job.step,
        clip_id=job.clip_id,
        status=job.status,
        created_at=job.created_at,
    )


@router.get("/pipeline", summary="List available pipeline steps")
async def list_steps(_: WorkDir):
    """返回所有已注册步骤（及描述），方便前端或 CLI 动态发现。"""
    return {
        name: {"description": sd.description, "timeout": sd.timeout}
        for name, sd in STEP_REGISTRY.items()
    }


@router.get("/events", summary="SSE event stream")
async def event_stream(
    project_id: str,
    _work_dir: WorkDir,
    redis: Redis,
):
    """Server-Sent Events — 实时推送 state_update / job_update / heartbeat。"""
    async def generate():
        async for chunk in sse_service.subscribe(redis, project_id):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 告知 nginx 不要缓冲 SSE
        },
    )
