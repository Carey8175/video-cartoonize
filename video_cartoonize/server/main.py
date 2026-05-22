"""FastAPI application factory。"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from video_cartoonize.server.config import settings
from video_cartoonize.server.db.engine import init_db
from video_cartoonize.server.pipeline.registry import STEP_REGISTRY
from video_cartoonize.server.routers import clips, credentials, files, jobs, pipeline, projects

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cartoonize Console API",
        description="Backend for the Cartoonize Console web UI. "
                    "Service layer only — business logic lives in the cartoonize CLI.",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(projects.router)
    app.include_router(pipeline.router)
    app.include_router(files.router)
    app.include_router(credentials.router)
    app.include_router(clips.router)
    app.include_router(jobs.router)

    # ── Lifespan ─────────────────────────────────────────────────────────────
    @app.on_event("startup")
    async def startup():
        # DB
        await init_db()
        logger.info("Database initialized at %s", settings.database_url)

        # Redis（可选，降级模式下跳过）
        if settings.redis_enabled:
            app.state.redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await app.state.redis.ping()
            logger.info("Redis connected at %s", settings.redis_url)
        else:
            app.state.redis = _FakeRedis()
            logger.warning("Redis disabled — SSE will use polling fallback")

        logger.info(
            "Server ready. Registered pipeline steps: %s",
            list(STEP_REGISTRY),
        )

    @app.on_event("shutdown")
    async def shutdown():
        if settings.redis_enabled and hasattr(app.state, "redis"):
            await app.state.redis.aclose()

    # ── Health ────────────────────────────────────────────────────────────────
    @app.get("/api/health", tags=["meta"])
    async def health():
        return {
            "status": "ok",
            "work_root": settings.work_root,
            "redis_enabled": settings.redis_enabled,
            "pipeline_steps": list(STEP_REGISTRY),
        }

    return app


class _FakeRedis:
    """No-op Redis stub，Redis 不可用时降级使用。"""
    async def set(self, *a, **kw): return None
    async def get(self, *a, **kw): return None
    async def delete(self, *a, **kw): return None
    async def hset(self, *a, **kw): return None
    async def hgetall(self, *a, **kw): return {}
    async def expire(self, *a, **kw): return None
    async def publish(self, *a, **kw): return None
    async def eval(self, *a, **kw): return None
    async def ttl(self, *a, **kw): return -1
    async def ping(self): return True
    def pubsub(self): return _FakePubSub()
    async def aclose(self): pass


class _FakePubSub:
    async def subscribe(self, *a): pass
    async def unsubscribe(self, *a): pass
    async def get_message(self, **kw):
        import asyncio
        await asyncio.sleep(1)
        return None
    async def aclose(self): pass
