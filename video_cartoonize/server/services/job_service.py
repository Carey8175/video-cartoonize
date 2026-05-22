"""Job Service — 异步 Pipeline Job 生命周期管理。

职责：
  - 在 DB 创建 / 更新 PipelineJob 记录
  - 通过 cli_runner 执行 cartoonize 子命令
  - 完成后通过 sse_service 推送 state_update 事件
  - 通过 Redis 管理并发锁 + 细粒度进度

不关心：
  - 步骤内部业务逻辑（由 CLI 处理）
  - state.json schema（由 state_adapter 处理）
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from video_cartoonize.server import state as st_module
from video_cartoonize.server.db import models as db_models
from video_cartoonize.server.pipeline.registry import get_step
from video_cartoonize.server.services import cli_runner, sse_service
from video_cartoonize.server.services.state_adapter import state_to_project_view

logger = logging.getLogger(__name__)


async def submit_job(
    *,
    db: AsyncSession,
    redis,
    project_id: str,
    work_dir: str,
    step: str,
    step_request: dict[str, Any],
    credentials: dict[str, str],
    work_root: str,
) -> db_models.PipelineJob:
    """创建 PipelineJob 记录，调度后台执行，立即返回 job 对象（202 语义）。"""
    step_def = get_step(step)  # 未知 step 立即抛 KeyError → 422

    # ── 并发锁：同一 project 同时只能跑一个 job ────────────────────────────
    lock_key = f"cartoonize:lock:{project_id}"
    job_id = str(uuid.uuid4())
    acquired = await redis.set(lock_key, job_id, nx=True, ex=3600)
    if not acquired:
        running_job_id = await redis.get(lock_key)
        raise RuntimeError(
            f"Project {project_id!r} already has a running job "
            f"({running_job_id.decode() if running_job_id else '?'}). "
            "Wait for it to finish or cancel it first."
        )

    # ── 写 DB ────────────────────────────────────────────────────────────────
    now = int(time.time())
    log_path = str(Path(work_dir) / "logs" / f"job-{job_id}.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    job = db_models.PipelineJob(
        job_id=job_id,
        project_id=project_id,
        step=step,
        clip_id=step_request.get("clip_id"),
        scope=step_request.get("scope"),
        frame_idx=step_request.get("frame_idx"),
        status="pending",
        log_path=log_path,
        created_at=now,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # ── 后台执行 ─────────────────────────────────────────────────────────────
    asyncio.create_task(
        _run_job(
            job_id=job_id,
            project_id=project_id,
            work_dir=work_dir,
            step=step,
            step_def=step_def,
            step_request=step_request,
            credentials=credentials,
            log_path=log_path,
            lock_key=lock_key,
            redis=redis,
            work_root=work_root,
        )
    )

    return job


async def _run_job(
    *,
    job_id: str,
    project_id: str,
    work_dir: str,
    step: str,
    step_def,
    step_request: dict[str, Any],
    credentials: dict[str, str],
    log_path: str,
    lock_key: str,
    redis,
    work_root: str,
) -> None:
    """后台协程：执行 CLI → 更新 DB → 推送 SSE → 释放锁。"""
    from video_cartoonize.server.db.engine import async_session

    start = int(time.time())
    extra_args = step_def.cli_args(step_request)

    # 进度写入 Redis Hash
    prog_key = f"cartoonize:job:{job_id}:progress"
    await redis.hset(prog_key, mapping={"status": "running", "step": step})
    await redis.expire(prog_key, 86400)

    async with async_session() as db:
        # status → running
        await _update_job(db, job_id, status="running", started_at=start)

    await sse_service.publish(redis, project_id, {"type": "job_update", "data": {
        "job_id": job_id, "step": step, "status": "running",
    }})

    try:
        returncode, tail = await cli_runner.run_step(
            step=step,
            work_dir=work_dir,
            extra_args=extra_args,
            credentials=credentials,
            timeout=step_def.timeout,
            log_file=log_path,
        )
        success = (returncode == 0)
        error = None if success else f"exit {returncode}\n{tail}"

    except Exception as exc:
        success = False
        error = str(exc)
        logger.exception("Job %s step=%s raised", job_id, step)

    finish = int(time.time())

    # ── DB 更新 ───────────────────────────────────────────────────────────────
    async with async_session() as db:
        status = "done" if success else "error"
        await _update_job(db, job_id, status=status, finished_at=finish, error=error)

        # Seedance submit 步骤额外写 seedance_tasks 历史
        if step in ("submit", "run") and success:
            await _record_seedance_tasks(db, project_id, work_dir, credentials)

    await redis.hset(prog_key, mapping={"status": "done" if success else "error"})

    # ── SSE 推送最新 state ────────────────────────────────────────────────────
    try:
        from video_cartoonize.server.config import settings
        import json, os

        state_path = os.path.join(work_dir, "state.json")
        if os.path.exists(state_path):
            with open(state_path) as f:
                state = json.load(f)
            view = state_to_project_view(state, project_id, work_dir)
            await sse_service.publish(redis, project_id, {
                "type": "state_update",
                "data": view.model_dump(),
            })
    except Exception:
        logger.exception("Failed to push state_update after job %s", job_id)

    await sse_service.publish(redis, project_id, {"type": "job_update", "data": {
        "job_id": job_id, "step": step,
        "status": "done" if success else "error",
        "error": error,
    }})

    # ── 释放锁（Lua 原子操作，只释放自己持有的锁）─────────────────────────
    LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
    await redis.eval(LUA, 1, lock_key, job_id)


async def _update_job(db: AsyncSession, job_id: str, **fields) -> None:
    from sqlalchemy import update
    await db.execute(
        update(db_models.PipelineJob)
        .where(db_models.PipelineJob.job_id == job_id)
        .values(**fields)
    )
    await db.commit()


async def _record_seedance_tasks(
    db: AsyncSession,
    project_id: str,
    work_dir: str,
    credentials: dict[str, str],
) -> None:
    """从 state.json 读取新产生的 task_id，写入 seedance_tasks 历史表。"""
    import json, os, time as _time

    api_key = credentials.get("ark_api_key", "")
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    state_path = os.path.join(work_dir, "state.json")
    if not os.path.exists(state_path):
        return

    with open(state_path) as f:
        state = json.load(f)

    from sqlalchemy import select
    existing = set(
        row[0] for row in (
            await db.execute(
                select(db_models.SeedanceTask.task_id)
                .where(db_models.SeedanceTask.project_id == project_id)
            )
        ).all()
    )

    now = int(_time.time())
    for clip in state.get("clips", []):
        tid = clip.get("task_id", "")
        if tid and tid not in existing:
            db.add(db_models.SeedanceTask(
                task_id=tid,
                project_id=project_id,
                clip_id=clip["clip_id"],
                api_key_hash=key_hash,
                model=state.get("config", {}).get("seedance_model", ""),
                resolution=state.get("config", {}).get("seedance_resolution", "720p"),
                status=clip.get("task_status") or "queued",
                submitted_at=clip.get("created_at", now),
            ))
    await db.commit()
