"""subprocess 封装：统一加 timeout、统一异常类型。

避免散落各处的 `subprocess.run(..., check=True)` 永久卡死。
"""
from __future__ import annotations

import subprocess
from typing import Sequence

from video_cartoonize.errors import FFmpegError
from video_cartoonize.logsetup import get_logger

LOGGER = get_logger("proc")

# 各类调用的默认 timeout（秒）
DEFAULT_FFPROBE_TIMEOUT = 30
DEFAULT_FFMPEG_TIMEOUT  = 300   # 5min，足够处理 ≤15s 单 clip


def run_check(
    cmd: Sequence[str],
    *,
    timeout: float = DEFAULT_FFMPEG_TIMEOUT,
    capture: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """子进程封装，必须带 timeout，失败抛 FFmpegError。"""
    try:
        return subprocess.run(
            list(cmd),
            check=True,
            capture_output=capture,
            text=text,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        LOGGER.error("subprocess timeout (%.0fs): %s", timeout, cmd[0])
        raise FFmpegError(
            f"{cmd[0]} timed out after {timeout}s. "
            f"Command: {' '.join(map(str, cmd[:6]))}..."
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")[:300] if capture else "(no stderr captured)"
        LOGGER.error("subprocess failed: %s (exit %d) %s", cmd[0], e.returncode, stderr)
        raise FFmpegError(
            f"{cmd[0]} exited with {e.returncode}. {stderr}"
        ) from e
