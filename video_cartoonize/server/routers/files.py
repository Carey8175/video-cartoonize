"""GET /api/projects/{id}/files/{path}   — 安全文件代理
   GET /api/projects/{id}/download/final — 下载最终视频
"""
from __future__ import annotations

import mimetypes
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from video_cartoonize.server.config import settings
from video_cartoonize.server.deps import WorkDir

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])

_CHUNK = 1 << 20  # 1 MB streaming chunk


def _safe_path(work_dir: str, rel: str) -> str:
    """验证 rel 在白名单前缀内，返回绝对路径；否则抛 403。"""
    # 去掉开头的 /
    rel = rel.lstrip("/")

    allowed = any(rel.startswith(p) for p in settings.allowed_file_prefixes)
    if not allowed:
        raise HTTPException(403, f"Access to {rel!r} not allowed. "
                            f"Allowed prefixes: {settings.allowed_file_prefixes}")

    abs_path = os.path.realpath(os.path.join(work_dir, rel))
    real_work = os.path.realpath(work_dir)

    # 防路径穿越
    if not abs_path.startswith(real_work + os.sep) and abs_path != real_work:
        raise HTTPException(403, "Path traversal detected")

    if not os.path.isfile(abs_path):
        raise HTTPException(404, f"File not found: {rel}")

    return abs_path


@router.get("/files/{file_path:path}")
async def serve_file(project_id: str, file_path: str, work_dir: WorkDir, request: Request):
    """代理 work_dir 下的静态文件，支持 Range 请求（视频 seek）。"""
    abs_path = _safe_path(work_dir, file_path)
    mime, _ = mimetypes.guess_type(abs_path)
    mime = mime or "application/octet-stream"

    # 视频文件：FileResponse 自动处理 Range
    if mime.startswith("video/"):
        return FileResponse(abs_path, media_type=mime, filename=os.path.basename(abs_path))

    # 图片等：直接 FileResponse
    return FileResponse(abs_path, media_type=mime)


@router.get("/download/final")
async def download_final(project_id: str, work_dir: WorkDir):
    """以 attachment 形式下载 final/merged.mp4。"""
    abs_path = _safe_path(work_dir, "final/merged.mp4")
    return FileResponse(
        abs_path,
        media_type="video/mp4",
        filename="merged.mp4",
        headers={"Content-Disposition": 'attachment; filename="merged.mp4"'},
    )
