"""HTTP / subprocess 调用的重试装饰器，带指数退避 + jitter。

设计:
- HTTP 502/503/504/429 / 网络错误 (URLError, timeout) 自动重试
- 5xx / network 默认 retry 3 次
- 业务 4xx（如 400 Bad Request, 401, 403）不重试
- subprocess.TimeoutExpired 不重试（卡死说明深层问题）
- 重试间隔: 1s, 2s, 4s + ±25% jitter
"""
from __future__ import annotations

import logging
import random
import socket
import time
from functools import wraps
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError

from video_cartoonize.errors import APIError

LOGGER = logging.getLogger("cartoonize.retry")

T = TypeVar("T")

# HTTP 状态码是否值得重试
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in _RETRYABLE_STATUS
    if isinstance(exc, (URLError, socket.timeout, ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, APIError):
        return exc.retryable
    return False


def with_retry(
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避重试装饰器。只重试 _is_retryable 判定为 True 的异常。"""
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt >= max_attempts or not _is_retryable(exc):
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay *= (1 + random.uniform(-jitter, jitter))
                    LOGGER.warning(
                        "%s attempt %d/%d failed (%s: %s), retry in %.1fs",
                        fn.__name__, attempt, max_attempts,
                        exc.__class__.__name__, str(exc)[:120], delay,
                    )
                    time.sleep(delay)
            # 不会到这里（前面 raise 了），但 mypy 需要
            raise RuntimeError("unreachable")
        return wrapper
    return deco
