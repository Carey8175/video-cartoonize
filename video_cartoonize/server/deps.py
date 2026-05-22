"""FastAPI dependencies — 注入 DB session、Redis、凭据。"""
from __future__ import annotations

import json
import os
from typing import Annotated, AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from video_cartoonize.server.config import settings
from video_cartoonize.server.db.engine import async_session


# ── DB session ────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

DB = Annotated[AsyncSession, Depends(get_db)]


# ── Redis ─────────────────────────────────────────────────────────────────────

async def get_redis(request: Request):
    return request.app.state.redis

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


# ── Credentials（从 Header 读，不落盘）───────────────────────────────────────

def get_credentials(
    ark_api_key: str = Header(default="", alias="X-Ark-Api-Key"),
    tos_ak: str      = Header(default="", alias="X-Tos-Ak"),
    tos_sk: str      = Header(default="", alias="X-Tos-Sk"),
) -> dict[str, str]:
    return {
        "ark_api_key": ark_api_key,
        "tos_ak": tos_ak,
        "tos_sk": tos_sk,
    }

Credentials = Annotated[dict[str, str], Depends(get_credentials)]


# ── Project resolution ────────────────────────────────────────────────────────

def _project_work_dir(project_id: str) -> str:
    """project_id → 绝对 work_dir 路径（防路径穿越）。"""
    # project_id 只允许字母数字、下划线、连字符
    if not project_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(422, f"Invalid project_id: {project_id!r}")
    work_dir = os.path.join(settings.work_root, project_id)
    # 确保在 work_root 下
    if not os.path.realpath(work_dir).startswith(os.path.realpath(settings.work_root)):
        raise HTTPException(403, "Path traversal detected")
    return work_dir


async def get_project_work_dir(
    project_id: str = Path(...),
) -> str:
    work_dir = _project_work_dir(project_id)
    state_path = os.path.join(work_dir, "state.json")
    if not os.path.exists(state_path):
        raise HTTPException(404, f"Project {project_id!r} not found (no state.json)")
    return work_dir

WorkDir = Annotated[str, Depends(get_project_work_dir)]


def load_state(work_dir: str) -> dict:
    state_path = os.path.join(work_dir, "state.json")
    with open(state_path) as f:
        return json.load(f)
