"""CLI Runner — 以子进程方式调用 cartoonize CLI。

**后端与 CLI 的唯一耦合点在此文件。**

设计：
  - 只调用 `cartoonize <step> --work-dir <dir> [extra args]`
  - 不 import 任何 video_cartoonize.* 业务模块
  - stdout 实时 yield，供 SSE 或日志写入
  - 凭据通过环境变量注入，不落盘

CLI 更新（新 flag、新子命令）时只需：
  1. 在 pipeline/registry.py 里更新 StepDef.cli_args
  2. 本文件无需改动
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# cartoonize 可执行路径：优先用与当前 Python 同 venv 的版本
_CARTOONIZE = shutil.which("cartoonize") or "cartoonize"


def _build_env(credentials: dict[str, str] | None) -> dict[str, str]:
    """构造子进程环境变量：继承父进程环境，叠加凭据。"""
    env = os.environ.copy()
    if credentials:
        if ak := credentials.get("ark_api_key"):
            env["ARK_API_KEY"] = ak
        if tos_ak := credentials.get("tos_ak"):
            env["TOS_ACCESS_KEY"] = tos_ak
        if tos_sk := credentials.get("tos_sk"):
            env["TOS_SECRET_KEY"] = tos_sk
    return env


async def run_step(
    step: str,
    work_dir: str,
    extra_args: list[str],
    credentials: dict[str, str] | None = None,
    timeout: int = 600,
    log_file: str | None = None,
) -> tuple[int, str]:
    """运行一个 pipeline 步骤，等待完成，返回 (returncode, stderr_tail)。

    适合非实时场景（job worker 调用，完成后写 DB）。
    实时输出请用 stream_step()。
    """
    cmd = [_CARTOONIZE, step, "--work-dir", work_dir, *extra_args]
    env = _build_env(credentials)

    logger.info("Running: %s", " ".join(cmd))

    lf = open(log_file, "a") if log_file else None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            env=env,
        )
        lines: list[str] = []
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            lines.append(line)
            if lf:
                lf.write(line + "\n")
                lf.flush()
            logger.debug("[%s] %s", step, line)

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            tail = "\n".join(lines[-20:])
            return -1, f"Timeout after {timeout}s.\n{tail}"

        tail = "\n".join(lines[-30:])
        return proc.returncode or 0, tail

    finally:
        if lf:
            lf.close()


async def stream_step(
    step: str,
    work_dir: str,
    extra_args: list[str],
    credentials: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """流式运行步骤，逐行 yield 输出。适合 SSE log-tail 场景。"""
    cmd = [_CARTOONIZE, step, "--work-dir", work_dir, *extra_args]
    env = _build_env(credentials)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    assert proc.stdout
    async for raw in proc.stdout:
        yield raw.decode(errors="replace").rstrip()
    await proc.wait()
