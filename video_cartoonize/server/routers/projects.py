"""GET /api/projects, GET /api/projects/{id}"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from video_cartoonize.server.config import settings
from video_cartoonize.server.db import models as db_models
from video_cartoonize.server.deps import DB, WorkDir, load_state
from video_cartoonize.server.schemas.project import ProjectSummary, ProjectView
from video_cartoonize.server.services.state_adapter import state_to_project_view

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
async def list_projects(db: DB):
    """列出所有已注册项目（按 updated_at 降序）。"""
    rows = (await db.execute(
        select(db_models.Project)
        .where(db_models.Project.archived == 0)
        .order_by(db_models.Project.updated_at.desc())
    )).scalars().all()

    result = []
    for row in rows:
        # 尝试从 state.json 读取 clip 统计（轻量 read，不做完整 adaptation）
        state_path = os.path.join(row.work_dir, "state.json")
        clips_done = clips_total = 0
        if os.path.exists(state_path):
            try:
                with open(state_path) as f:
                    state = json.load(f)
                clips = state.get("clips", [])
                clips_total = len(clips)
                clips_done = sum(1 for c in clips if c.get("status") == "done")
            except Exception:
                pass

        result.append(ProjectSummary(
            id=row.id,
            source_name=row.source_name,
            style_id=row.style_id,
            created_at=row.created_at,
            clips_done=clips_done,
            clips_total=clips_total,
        ))
    return result


@router.get("/{project_id}", response_model=ProjectView)
async def get_project(work_dir: WorkDir, project_id: str):
    """读取完整 project state（含所有 clips）。"""
    state = load_state(work_dir)
    return state_to_project_view(state, project_id, work_dir)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: DB):
    """软删除（archived=1）。不删除磁盘文件。"""
    from sqlalchemy import update
    await db.execute(
        update(db_models.Project)
        .where(db_models.Project.id == project_id)
        .values(archived=1, updated_at=int(time.time()))
    )
    await db.commit()
