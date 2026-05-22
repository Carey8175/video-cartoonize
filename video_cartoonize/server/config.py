"""Server configuration — 全部通过环境变量覆盖，零魔法。"""
from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── 服务器 ────────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 7317
    work_root: str = str(Path.home() / "cartoonize")  # project work_dir 的根目录

    # ── 数据库 ────────────────────────────────────────────────────────────────
    # 本地开发：sqlite+aiosqlite:///./server.db
    # 生产：  postgresql+asyncpg://user:pass@localhost/cartoonize
    database_url: str = f"sqlite+aiosqlite:///{Path.home()}/.local/share/video-cartoonize/server.db"
    db_echo: bool = False  # True → SQLAlchemy 打印所有 SQL

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True   # False → 降级为无 Redis 模式（SSE 轮询）

    # ── 文件代理白名单（相对于 work_dir）────────────────────────────────────
    allowed_file_prefixes: list[str] = [
        "keyframes/",
        "cartoons/",
        "resized/",
        "final/",
        "logs/",
    ]

    # ── CORS（前端 dev server 端口）──────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()

# 确保 work_root 存在
Path(settings.work_root).mkdir(parents=True, exist_ok=True)
