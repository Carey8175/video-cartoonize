"""Pipeline Step Registry.

每个 CLI 步骤在此注册一条 StepDef。
后端不关心步骤的内部实现——只知道「调哪个 cartoonize 子命令、传哪些参数」。

**新增 CLI 步骤时只需：**
    1. 在 STEP_REGISTRY 里加一条 StepDef
    2. 如有需要，在 StepRequest 里加可选字段

后端 HTTP 路由、Job 执行、SSE 推送均无需改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class StepDef:
    """描述一个 CLI 步骤如何被调用。

    cli_args: 接收 StepRequest dict，返回追加到 `cartoonize <step>` 之后的参数列表。
              保持为 Callable 而非固定字符串，以便按请求动态构造（如 --clip-id）。
    timeout:  该步骤最长允许运行的秒数（传给 subprocess）。
    description: 可读描述，用于日志和 /api/health 输出。
    """
    cli_args: Callable[[dict[str, Any]], list[str]] = field(default_factory=lambda: lambda _: [])
    timeout: int = 600
    description: str = ""


# ── 注册表 ────────────────────────────────────────────────────────────────────
# key = step name（与 POST /api/projects/{id}/pipeline/{step} 的 path 参数一致）
# value = StepDef（描述如何构造 cartoonize 子命令）
#
# ⚠️ 不要在这里写任何业务逻辑，只写「怎么调 CLI」。

def _clip_flag(req: dict) -> list[str]:
    """若 req 包含 clip_id，追加 --clip-id N。"""
    cid = req.get("clip_id")
    return ["--clip-id", str(cid)] if cid is not None else []


STEP_REGISTRY: dict[str, StepDef] = {
    # Phase 1 — 场景切分
    "split": StepDef(
        cli_args=lambda req: [
            *(["--scene-threshold", str(req["scene_threshold"])] if "scene_threshold" in req else []),
            *(["--min-duration",    str(req["min_clip_duration"])] if "min_clip_duration" in req else []),
            *(["--max-duration",    str(req["max_clip_duration"])] if "max_clip_duration" in req else []),
        ],
        timeout=600,
        description="PySceneDetect scene split + ffmpeg resize",
    ),

    # Phase 2a — 子镜头关键帧提取
    "keyframes": StepDef(
        cli_args=lambda req: [
            *_clip_flag(req),
            *(["--subshot-threshold", str(req["subshot_threshold"])] if "subshot_threshold" in req else []),
        ],
        timeout=300,
        description="ffmpeg sub-shot keyframe extraction",
    ),

    # Phase 2b — Seedream I2I 卡通化
    "cartoon": StepDef(
        cli_args=lambda req: [
            *_clip_flag(req),
            *(["--style", req["style_id"]] if "style_id" in req else []),
            *(["--strength", str(req["style_strength"])] if "style_strength" in req else []),
            *(["--seed", str(req["seed"])] if req.get("seed") is not None else []),
        ],
        timeout=1800,
        description="Seedream I2I cartoon stylization",
    ),

    # Phase 3 — VLM 场景分析（生成 Seedance prompt）
    "vlm": StepDef(
        cli_args=lambda req: _clip_flag(req),
        timeout=600,
        description="Seed 2.0 Lite video analysis → Seedance prompt",
    ),

    # Phase 4 — TOS 上传 + Assets API 注册
    "upload": StepDef(
        cli_args=lambda req: _clip_flag(req),
        timeout=900,
        description="TOS upload + BytePlus Assets API registration",
    ),

    # Phase 5a — 提交 Seedance 任务
    "submit": StepDef(
        cli_args=lambda req: [
            *_clip_flag(req),
            *(["--dry-run"] if req.get("dry_run") else []),
        ],
        timeout=120,
        description="Submit Seedance generation tasks",
    ),

    # Phase 5b — 轮询 Seedance 任务状态（单次，不阻塞）
    "poll": StepDef(
        cli_args=lambda req: _clip_flag(req),
        timeout=300,
        description="Poll Seedance task status (single pass)",
    ),

    # Phase 5+ — 单 clip 并行编排（cartoon + vlm → upload → submit）
    "run": StepDef(
        cli_args=lambda req: [
            *_clip_flag(req),
        ],
        timeout=3600,
        description="Orchestrated per-clip run (cartoon+vlm → upload → submit)",
    ),

    # Phase 6 — ffmpeg 混入原始音轨
    "mux": StepDef(
        cli_args=lambda req: _clip_flag(req),
        timeout=600,
        description="ffmpeg mux original audio into cartoonized clip",
    ),

    # Phase 7 — 拼接最终视频
    "merge": StepDef(
        cli_args=lambda _: [],
        timeout=600,
        description="ffmpeg concat all muxed clips into final video",
    ),
}


def get_step(name: str) -> StepDef:
    """查找步骤；未知步骤抛 KeyError，由路由层转成 422。"""
    if name not in STEP_REGISTRY:
        raise KeyError(f"Unknown pipeline step: {name!r}. "
                       f"Known steps: {list(STEP_REGISTRY)}")
    return STEP_REGISTRY[name]
