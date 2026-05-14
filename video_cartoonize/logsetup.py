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


# ── Per-clip 事件日志 (JSONL) ──────────────────────────────────────────────
# 每个 clip 一个 logs/clip_NN.jsonl，append-only。
# run / poll / verify / mux 都会写事件进去，方便事后排查任何一个 clip。

def log_clip_event(work_dir: str, clip_id: int, event: str, **fields) -> None:
    """追加一行 JSONL 到 <work_dir>/logs/clip_{N:02d}.jsonl

    event 用 "phase.action" 命名：
        run.start / run.cartoon_done / run.vlm_done / run.upload_done /
        run.submit_done / run.end
        poll.check / poll.running / poll.verify_pass / poll.verify_fail /
        poll.auto_resubmit / poll.done / poll.fallback / poll.error
        mux.download / mux.muxed / mux.error

    fields 是任意键值（task_id / duration_s / reason / video_url 等）。
    """
    if not work_dir or clip_id is None:
        return
    import json as _json
    import os as _os
    from datetime import datetime as _dt

    log_dir = _os.path.join(work_dir, "logs")
    try:
        _os.makedirs(log_dir, exist_ok=True)
        path = _os.path.join(log_dir, f"clip_{clip_id:02d}.jsonl")
        rec = {
            "ts":    _dt.now().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 写日志失败不能影响主流程
