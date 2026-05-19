"""State file (state.json) read/write helpers.

State schema 版本管理:
- 每个 state.json 顶层有 `version` 字段
- load() 读到旧版本时自动 migrate 到 CURRENT_SCHEMA_VERSION
- 不兼容的破坏性变更需要写 _migrate_vN_to_vN1 函数

历史版本:
  v1: 初始版本
  v2: 新增 clip.attempts[]、clip.style_verified、clip.verify_attempts、verify_reason
  v3: 新增 clip.subshot_cartoon_urls、prompts dict、clip_asset_urls dict
"""
import fcntl
import json
import os
from contextlib import contextmanager
from typing import List, Optional

from video_cartoonize.errors import StateError
from video_cartoonize.logsetup import get_logger
from video_cartoonize.models import ClipInfo

LOGGER = get_logger("state")

STATE_FILE = "state.json"
LOCK_FILE  = ".state.lock"

# 当前 state schema 版本。改 ClipInfo 字段或 state 顶层结构时 +1，
# 并加一个 _migrate_vN_to_vN1 函数。
CURRENT_SCHEMA_VERSION = 4


def path(work_dir: str) -> str:
    return os.path.join(work_dir, STATE_FILE)


def load(work_dir: str) -> Optional[dict]:
    p = path(work_dir)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        raise StateError(f"state.json 损坏（无法解析）: {e}") from e

    # 自动迁移到当前 schema
    state = _migrate(state, p)
    return state


# ── Schema 迁移 ─────────────────────────────────────────────────────────────

def _migrate(state: dict, path: str) -> dict:
    """如果 state.version < CURRENT_SCHEMA_VERSION，按版本号顺序迁移。"""
    v = int(state.get("version", 1))
    if v == CURRENT_SCHEMA_VERSION:
        return state
    if v > CURRENT_SCHEMA_VERSION:
        raise StateError(
            f"state.json 版本 v{v} 比当前 CLI 支持的 v{CURRENT_SCHEMA_VERSION} 新，"
            "请升级 cartoonize CLI"
        )

    LOGGER.info("迁移 state.json: v%d → v%d", v, CURRENT_SCHEMA_VERSION)
    migrations = {
        1: _migrate_v1_to_v2,
        2: _migrate_v2_to_v3,
        3: _migrate_v3_to_v4,
    }
    while v < CURRENT_SCHEMA_VERSION:
        state = migrations[v](state)
        v += 1
        state["version"] = v

    # 备份原文件再覆写
    if path and os.path.exists(path):
        try:
            backup = path + f".v{int(state.get('version', 1))-1}.bak"
            if not os.path.exists(backup):
                with open(backup, "w", encoding="utf-8") as f:
                    f.write(open(path, encoding="utf-8").read())
                LOGGER.info("已备份旧 state 到 %s", backup)
        except Exception as e:
            LOGGER.warning("备份失败: %s", e)
        save_path = path
        tmp = save_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, save_path)

    return state


def _migrate_v1_to_v2(state: dict) -> dict:
    """v1 → v2: 给每个 clip 补 verify 相关字段。"""
    for c in state.get("clips", []):
        c.setdefault("attempts", [])
        c.setdefault("style_verified", False)
        c.setdefault("verify_attempts", 0)
        c.setdefault("verify_reason", "")
    return state


def _migrate_v2_to_v3(state: dict) -> dict:
    """v2 → v3: 确保 prompts / clip_asset_urls 为 dict 而非 list。"""
    if isinstance(state.get("prompts"), list):
        state["prompts"] = {}
    if isinstance(state.get("clip_asset_urls"), list):
        state["clip_asset_urls"] = {}
    state.setdefault("prompts", {})
    state.setdefault("clip_asset_urls", {})
    return state


def _migrate_v3_to_v4(state: dict) -> dict:
    """v3 → v4: 安全修复 — 清除 state.config 里明文 API key。

    早期版本错误地把 api_key 写到 state.json，会被 commit / 备份 / 分享。
    迁移时直接抹掉，运行时从环境变量或 ~/.config/video-cartoonize/ark_api_key.txt 读。
    """
    cfg = state.get("config", {})
    if "api_key" in cfg:
        had_key = bool(cfg["api_key"])
        del cfg["api_key"]
        if had_key:
            LOGGER.warning(
                "🔒 已从 state.json 移除明文 API key（v3 历史遗留）。"
                "后续运行从 ARK_API_KEY 环境变量或 ~/.config/video-cartoonize/ark_api_key.txt 读取。"
            )
    return state


def save(work_dir: str, state: dict) -> None:
    p   = path(work_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def require(work_dir: str) -> dict:
    """Load state or raise StateError（CLI 入口处统一捕获并退出）。"""
    s = load(work_dir)
    if s is None:
        raise StateError(
            f"state.json not found in {work_dir}\n"
            "Run `cartoonize init --input VIDEO` first."
        )
    return s


# ── ClipInfo serialization ──────────────────────────────────────────────────

def clip_to_dict(c: ClipInfo) -> dict:
    return {
        "clip_id":               c.clip_id,
        "raw_path":              c.raw_path,
        "resized_path":          c.resized_path,
        "subshot_frame_paths":   c.subshot_frame_paths,
        "subshot_cartoon_paths": c.subshot_cartoon_paths,
        "subshot_cartoon_urls":  c.subshot_cartoon_urls,
        "task_id":               c.task_id,
        "output_url":            c.output_url,
        "output_path":           c.output_path,
        "status":                c.status,
        "retries":               c.retries,
        "style_verified":        c.style_verified,
        "verify_attempts":       c.verify_attempts,
        "verify_reason":         c.verify_reason,
        "attempts":              c.attempts,
    }


def dict_to_clip(d: dict) -> ClipInfo:
    c = ClipInfo(clip_id=d["clip_id"],
                 raw_path=d["raw_path"],
                 resized_path=d["resized_path"])
    c.subshot_frame_paths   = d.get("subshot_frame_paths", [])
    c.subshot_cartoon_paths = d.get("subshot_cartoon_paths", [])
    c.subshot_cartoon_urls  = d.get("subshot_cartoon_urls", [])
    c.task_id               = d.get("task_id", "")
    c.output_url            = d.get("output_url", "")
    c.output_path           = d.get("output_path", "")
    c.status                = d.get("status", "pending")
    c.retries               = d.get("retries", 0)
    c.style_verified        = d.get("style_verified", False)
    c.verify_attempts       = d.get("verify_attempts", 0)
    c.verify_reason         = d.get("verify_reason", "")
    c.attempts              = list(d.get("attempts", []))
    return c


def clips_from_state(state: dict) -> List[ClipInfo]:
    return [dict_to_clip(d) for d in state.get("clips", [])]


def clips_to_state(state: dict, clips: List[ClipInfo]) -> None:
    """整体替换 clips 数组（用于 split 阶段第一次写入）。"""
    state["clips"] = [clip_to_dict(c) for c in clips]


def merge_clips(state: dict, updated: List[ClipInfo]) -> None:
    """按 clip_id 整体替换。⚠ 会覆盖该 clip 的所有字段。

    并发场景下慎用：如果两个进程同时改同一 clip 的不同字段，会丢失另一方写入。
    优先使用 merge_clip_fields 做字段级合并。
    """
    by_id = {c["clip_id"]: c for c in state.get("clips", [])}
    for c in updated:
        by_id[c.clip_id] = clip_to_dict(c)
    state["clips"] = [by_id[k] for k in sorted(by_id.keys())]


def merge_clip_fields(state: dict, clip_id: int, **fields) -> None:
    """字段级合并 - 只更新指定字段，保留其他字段。

    并发安全：多个 cmd_* 同时改同一 clip 的不同字段时，互不覆盖。

    用法:
        with state.lock(work_dir):
            s = state.require(work_dir)
            state.merge_clip_fields(s, clip_id=0,
                subshot_cartoon_urls=urls, status="success")
            state.save(work_dir, s)
    """
    by_id = {c["clip_id"]: c for c in state.get("clips", [])}
    if clip_id in by_id:
        by_id[clip_id].update(fields)
    state["clips"] = [by_id[k] for k in sorted(by_id.keys())]


# ── 跨进程互斥锁 ─────────────────────────────────────────────────────────────

@contextmanager
def lock(work_dir: str):
    """对 state.json 加排他锁，配合 read-modify-write 防止并发覆盖。

    用法:
        with state.lock(work_dir):
            s = state.require(work_dir)   # 重新读取最新状态
            ... 增量修改 s ...
            state.save(work_dir, s)
    """
    os.makedirs(work_dir, exist_ok=True)
    lock_path = os.path.join(work_dir, LOCK_FILE)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def cfg_from_state(state: dict):
    from video_cartoonize.config import PipelineConfig
    c = state["config"]
    return PipelineConfig(
        scene_threshold     = c.get("scene_threshold",    25.0),
        min_clip_duration   = c.get("min_clip_duration",   4.0),
        max_clip_duration   = c.get("max_clip_duration",  15.0),
        pixel_limit         = c.get("pixel_limit",      927408),
        subshot_threshold   = c.get("subshot_threshold",  27.0),
        style_id            = c.get("style_id",         "anime"),
        seedream_model      = c.get("seedream_model",   "seedream-5-0-260128"),
        seedream_image_size = c.get("seedream_image_size", "auto"),
        analyse_fps         = c.get("analyse_fps",           4),
        api_key             = "",   # 永远不从 state 读密钥，由上层 _resolve_key() 解析
        seedance_model      = c.get("seedance_model",   "dreamina-seedance-2-0-260128"),
        seedance_resolution = c.get("seedance_resolution",  "720p"),
        max_retries         = c.get("max_retries",           2),
        poll_interval       = c.get("poll_interval",        10),
    )
