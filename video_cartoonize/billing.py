"""项目级别用量记账 + 成本换算 (USD)。

每次 API 调用都追加一行 JSONL；汇总时按 BytePlus 官方价目表逐条换算成 USD。
价格可在 ~/.config/video-cartoonize/prices.json 覆盖（嵌套结构同 DEFAULT_PRICES）。

设计：
- 每个 work_dir 下一个 billing.jsonl（append-only，并发安全）
- 通过模块级 _current_project 在 CLI 入口设置当前项目，无需把 work_dir
  穿透到每个 API 调用点
- 不同模型用不同计价单位（per image / per token / token+输入模态），
  在 _cost_of_record() 里逐条处理；不要把所有服务都套 token 单价
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Optional

BILLING_FILE = "billing.jsonl"

# 当前项目的工作目录（CLI 入口设置）
_current_project: Optional[str] = None


# ── BytePlus ModelArk 官方价目（USD）──────────────────────────────────────
# 不同模型计价口径不同：
#   per_image       — 按张计价（Seedream）
#   per_token_io    — input / output 分开按 token（VLM）
#   per_token_video — 按 token，但 with-video 输入和 without-video 输入价不同（Seedance）
#
# 用户可在 ~/.config/video-cartoonize/prices.json 覆盖（同结构，整个 model 项替换）。
DEFAULT_PRICES: dict = {
    # Seedream 5.0 Lite：官方按张 $0.035/image
    "seedream-5-0-260128": {
        "type": "per_image",
        "per_image_usd": 0.035,
    },
    # Seed 2.0 Lite VLM：0–128K input 档 $0.25/M，output 通常 ~2× input
    "seed-2-0-lite-260228": {
        "type": "per_token_io",
        "input_usd_per_m":  0.25,
        "output_usd_per_m": 0.50,   # 估值（公开页未单独披露 output 价）
    },
    # Seedance 2.0 标准：with-video $4.30/M、without-video $7.00/M（官方）
    "dreamina-seedance-2-0-260128": {
        "type": "per_token_video",
        "with_video_usd_per_m":    4.30,
        "without_video_usd_per_m": 7.00,
    },
    # Seedance 2.0 Fast：with-video $3.30/M（官方资源包）；
    # without-video 公开页未明示，按 standard 比例 (7/4.3≈1.63×) 估算
    "dreamina-seedance-2-0-fast-260128": {
        "type": "per_token_video",
        "with_video_usd_per_m":    3.30,
        "without_video_usd_per_m": 5.40,
    },
}


def load_prices() -> dict:
    """Load prices from config dir or fall back to defaults.

    用户覆盖的格式：与 DEFAULT_PRICES 一致的嵌套 dict；用户给的 model 项
    会整体替换默认那一项（不会与默认 merge 字段）。
    """
    try:
        from video_cartoonize.settings import CONFIG_DIR
        f = CONFIG_DIR / "prices.json"
        if f.exists():
            user = json.loads(f.read_text(encoding="utf-8"))
            merged = {k: dict(v) for k, v in DEFAULT_PRICES.items()}
            for k, v in (user or {}).items():
                merged[k] = v
            return merged
    except Exception:
        pass
    return {k: dict(v) for k, v in DEFAULT_PRICES.items()}


def set_project(work_dir: Optional[str]) -> None:
    """设置当前 billing 写入的目录。传 None 关闭记账。"""
    global _current_project
    _current_project = os.path.abspath(work_dir) if work_dir else None


def current_project() -> Optional[str]:
    return _current_project


def record(service: str, **fields: Any) -> None:
    """追加一条用量记录。

    service: "seedream" / "vlm" / "seedance"
    fields:  任意键值（clip_id / model / tokens / images / has_video_input / ...）
    """
    if not _current_project:
        return
    rec = {
        "ts":      _dt.datetime.now().isoformat(timespec="seconds"),
        "service": service,
        **fields,
    }
    path = os.path.join(_current_project, BILLING_FILE)
    try:
        os.makedirs(_current_project, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # 记账失败不能影响主流程
        pass


def _cost_of_record(r: dict, prices: dict) -> float:
    """单条 billing record → cost (USD)。按模型 type 分派。"""
    model = r.get("model", "")
    spec  = prices.get(model)
    if not isinstance(spec, dict):
        return 0.0
    t = spec.get("type", "")
    if t == "per_image":
        n = int(r.get("images", 0) or 0)
        return round(n * float(spec.get("per_image_usd", 0.0)), 6)
    if t == "per_token_io":
        pt = int(r.get("prompt_tokens", 0) or 0)
        ct = int(r.get("completion_tokens", 0) or 0)
        cost = (pt * float(spec.get("input_usd_per_m", 0.0))
                + ct * float(spec.get("output_usd_per_m", 0.0))) / 1_000_000
        return round(cost, 6)
    if t == "per_token_video":
        tok = int(r.get("total_tokens", 0) or 0)
        has_video = bool(r.get("has_video_input", True))   # legacy 默认 True
        rate = (spec.get("with_video_usd_per_m") if has_video
                else spec.get("without_video_usd_per_m")) or 0.0
        return round(tok * float(rate) / 1_000_000, 6)
    return 0.0


def summarize(work_dir: str) -> dict:
    """聚合 billing.jsonl，返回总计 + 各 clip 明细。"""
    totals: dict = {
        "seedream": {"calls": 0, "images": 0,
                     "output_tokens": 0, "total_tokens": 0,
                     "models": {}, "cost_usd": 0.0},
        "vlm":      {"calls": 0, "prompt_tokens": 0,
                     "completion_tokens": 0, "total_tokens": 0,
                     "models": {}, "cost_usd": 0.0},
        "seedance": {"calls": 0, "duration_seconds": 0,
                     "completion_tokens": 0, "total_tokens": 0,
                     "with_video_tokens": 0, "without_video_tokens": 0,
                     "with_video_calls": 0, "without_video_calls": 0,
                     "models": {}, "cost_usd": 0.0},
    }
    by_clip: dict = {}
    records = 0
    path = os.path.join(work_dir, BILLING_FILE)
    prices = load_prices()

    if not os.path.exists(path):
        return {"totals": totals, "records": 0, "by_clip": by_clip,
                "grand_total_tokens": 0, "grand_total_usd": 0.0,
                "prices_used": prices}

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            records += 1
            svc   = r.get("service", "")
            cid   = r.get("clip_id")
            model = r.get("model", "")
            cost  = _cost_of_record(r, prices)

            if svc == "vlm":
                t = totals["vlm"]
                t["calls"]             += 1
                t["prompt_tokens"]     += int(r.get("prompt_tokens", 0) or 0)
                t["completion_tokens"] += int(r.get("completion_tokens", 0) or 0)
                t["total_tokens"]      += int(r.get("total_tokens", 0) or 0)
                t["cost_usd"]          += cost
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1
            elif svc == "seedream":
                t = totals["seedream"]
                t["calls"]         += 1
                t["images"]        += int(r.get("images", 1) or 1)
                t["output_tokens"] += int(r.get("output_tokens", 0) or 0)
                t["total_tokens"]  += int(r.get("total_tokens", 0) or 0)
                t["cost_usd"]      += cost
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1
            elif svc == "seedance":
                t = totals["seedance"]
                t["calls"]             += 1
                t["duration_seconds"]  += int(r.get("duration_s", 0) or 0)
                t["completion_tokens"] += int(r.get("completion_tokens", 0) or 0)
                t["total_tokens"]      += int(r.get("total_tokens", 0) or 0)
                t["cost_usd"]          += cost
                tok = int(r.get("total_tokens", 0) or 0)
                if bool(r.get("has_video_input", True)):
                    t["with_video_tokens"] += tok
                    t["with_video_calls"]  += 1
                else:
                    t["without_video_tokens"] += tok
                    t["without_video_calls"]  += 1
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1

            if cid is not None:
                k = str(cid)
                bc = by_clip.setdefault(k, {
                    "vlm_calls": 0,      "vlm_tokens": 0,      "vlm_cost_usd": 0.0,
                    "seedream_calls": 0, "seedream_images": 0, "seedream_tokens": 0, "seedream_cost_usd": 0.0,
                    "seedance_calls": 0, "seedance_tokens": 0, "seedance_duration_s": 0, "seedance_cost_usd": 0.0,
                })
                if svc == "vlm":
                    bc["vlm_calls"]    += 1
                    bc["vlm_tokens"]   += int(r.get("total_tokens", 0) or 0)
                    bc["vlm_cost_usd"] += cost
                elif svc == "seedream":
                    bc["seedream_calls"]    += 1
                    bc["seedream_images"]   += int(r.get("images", 1) or 1)
                    bc["seedream_tokens"]   += int(r.get("total_tokens", 0) or 0)
                    bc["seedream_cost_usd"] += cost
                elif svc == "seedance":
                    bc["seedance_calls"]      += 1
                    bc["seedance_tokens"]     += int(r.get("total_tokens", 0) or 0)
                    bc["seedance_duration_s"] += int(r.get("duration_s", 0) or 0)
                    bc["seedance_cost_usd"]   += cost

    for k in ("seedream", "vlm", "seedance"):
        totals[k]["cost_usd"] = round(totals[k]["cost_usd"], 4)
    for bc in by_clip.values():
        for k in ("vlm_cost_usd", "seedream_cost_usd", "seedance_cost_usd"):
            bc[k] = round(bc[k], 4)

    grand_total = (totals["seedream"]["total_tokens"]
                   + totals["vlm"]["total_tokens"]
                   + totals["seedance"]["total_tokens"])
    grand_usd = round(totals["seedream"]["cost_usd"]
                      + totals["vlm"]["cost_usd"]
                      + totals["seedance"]["cost_usd"], 4)

    return {"totals": totals, "records": records, "by_clip": by_clip,
            "grand_total_tokens": grand_total,
            "grand_total_usd":    grand_usd,
            "prices_used":        prices}


def cost_usd(model: str, tokens: int, prices: Optional[dict] = None) -> float:
    """Deprecated 兼容入口：粗略按 total_tokens 估一个值（不区分输入模态）。

    新代码应该用 _cost_of_record() 走完整逻辑。
    """
    p = (prices or load_prices()).get(model)
    if not isinstance(p, dict):
        return 0.0
    t = p.get("type", "")
    if t == "per_token_video":
        return round(int(tokens) * float(p.get("with_video_usd_per_m", 0.0)) / 1_000_000, 6)
    if t == "per_token_io":
        return round(int(tokens) * float(p.get("output_usd_per_m", 0.0)) / 1_000_000, 6)
    if t == "per_image":
        # 没有 image 数信息，无法换算
        return 0.0
    return 0.0
