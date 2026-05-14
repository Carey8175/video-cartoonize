"""Logging 配置。所有进度/调试信息走 stderr，stdout 只放最终 JSON。"""
from __future__ import annotations

import logging
import os
import sys


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """配置全局 logging。

    输出全部走 stderr，stdout 保留给最终 JSON。
    - quiet  : WARNING 以上才显示
    - verbose: DEBUG 以上全显示
    - 默认   : INFO 以上
    """
    level = (logging.DEBUG if verbose
             else logging.WARNING if quiet
             else logging.INFO)

    # 优先环境变量覆盖（用于自动化场景）
    env_level = os.environ.get("CARTOONIZE_LOG_LEVEL", "").upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        level = getattr(logging, env_level)

    root = logging.getLogger("cartoonize")
    root.setLevel(level)
    root.handlers.clear()

    h = logging.StreamHandler(sys.stderr)
    h.setLevel(level)
    h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(h)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """业务模块统一通过这个拿 logger。"""
    return logging.getLogger(f"cartoonize.{name}")
