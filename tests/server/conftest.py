"""Shared pytest fixtures for server tests.

All fixtures use:
  - SQLite in-memory (aiosqlite) — no real DB needed
  - fakeredis — no real Redis needed
  - httpx AsyncClient — no real network needed
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from video_cartoonize.server.db.engine import Base
from video_cartoonize.server.db import models  # noqa: F401 — ensure models are registered


# ── In-memory SQLite ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


# ── Fake Redis ────────────────────────────────────────────────────────────────

class FakeRedis:
    """In-process fake Redis with minimal command support."""

    def __init__(self):
        self._store: dict = {}
        self._published: list[tuple[str, str]] = []

    async def set(self, key, val, *, nx=False, ex=None, **_):
        if nx and key in self._store:
            return None
        self._store[key] = val
        return True

    async def get(self, key):
        return self._store.get(key)

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)

    async def hset(self, key, mapping=None, **kw):
        self._store.setdefault(key, {}).update(mapping or kw)

    async def hgetall(self, key):
        return dict(self._store.get(key, {}))

    async def expire(self, key, seconds):
        pass  # not implemented in fake

    async def publish(self, channel, message):
        self._published.append((channel, message))

    async def eval(self, script, numkeys, *args):
        # Simulate the lock-release Lua script
        key = args[0]
        val = args[1]
        if self._store.get(key) == val:
            del self._store[key]
            return 1
        return 0

    async def ttl(self, key):
        return 30 if key in self._store else -2

    async def ping(self):
        return True

    async def aclose(self):
        pass

    def pubsub(self):
        return FakePubSub()


class FakePubSub:
    async def subscribe(self, *a): pass
    async def unsubscribe(self, *a): pass
    async def get_message(self, **_):
        import asyncio
        await asyncio.sleep(0.01)
        return None
    async def aclose(self): pass


@pytest.fixture
def fake_redis():
    return FakeRedis()


# ── Work dir with a minimal state.json ───────────────────────────────────────

MINIMAL_STATE = {
    "version": 5,
    "work_dir": "/tmp/test_project",
    "input_video": "/tmp/test.mp4",
    "started_at": "2026-05-22T00:00:00",
    "config": {
        "style_id": "anime",
        "seedream_model": "seedream-5-0-260128",
        "seedance_model": "dreamina-seedance-2-0-260128",
        "seedance_resolution": "720p",
        "scene_threshold": 25.0,
        "min_clip_duration": 4.0,
        "max_clip_duration": 15.0,
        "subshot_threshold": 27.0,
    },
    "clips": [
        {
            "clip_id": 0,
            "raw_path": "clips/clip_001.mp4",
            "resized_path": "resized/clip_00.mp4",
            "duration_s": 7.5,
            "ratio": "9:16",
            "width": 720,
            "height": 1280,
            "status": "done",
            "task_id": "cgt-20260522000001-abcde",
            "task_status": "succeeded",
            "task_progress": 100,
            "retries": 0,
            "style_verified": True,
            "verify_attempts": 1,
            "verify_reason": "",
            "subshot_frame_paths": ["keyframes/clip_00_sub_00.jpg"],
            "subshot_cartoon_paths": ["cartoons/clip_00_sub_00.jpg"],
            "subshot_cartoon_urls": ["https://ark-asset.example.com/clip_00_sub_00.jpg"],
            "attempts": [],
        },
        {
            "clip_id": 1,
            "raw_path": "clips/clip_002.mp4",
            "resized_path": "resized/clip_01.mp4",
            "duration_s": 5.2,
            "ratio": "9:16",
            "width": 720,
            "height": 1280,
            "status": "split",
            "task_id": "",
            "task_status": None,
            "task_progress": 0,
            "retries": 0,
            "style_verified": False,
            "verify_attempts": 0,
            "verify_reason": "",
            "subshot_frame_paths": [],
            "subshot_cartoon_paths": [],
            "subshot_cartoon_urls": [],
            "attempts": [],
        },
    ],
    "prompts": {},
    "clip_asset_urls": {},
    "final_video": "",
    "characters": [],
    "char_keyframe_map": {},
}


@pytest.fixture
def work_dir(tmp_path):
    """Temp directory with a valid state.json."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(MINIMAL_STATE))
    return str(tmp_path)


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def app(db_engine, fake_redis, work_dir, monkeypatch) -> FastAPI:
    """Test app with overridden DB, Redis, and work_root."""
    monkeypatch.setenv("WORK_ROOT", str(os.path.dirname(work_dir)))
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///:memory:",
    )

    from video_cartoonize.server.main import create_app
    from video_cartoonize.server import db as db_module
    from video_cartoonize.server.db import engine as engine_module

    # Patch the engine used by the app
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "async_session", session_factory)

    application = create_app()
    application.state.redis = fake_redis

    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
