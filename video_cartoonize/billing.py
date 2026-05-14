"""项目级别用量记账：Seedream / VLM / Seedance 每次 API 调用都追加一行 JSONL。

设计：
- 每个 work_dir 下一个 billing.jsonl（append-only，并发安全）
- 通过模块级 _current_project 在 CLI 入口设置当前项目，无需把 work_dir
  穿透到每个 API 调用点
- 用 cartoonize billing 命令聚合统计
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Optional

BILLING_FILE = "billing.jsonl"

# 当前项目的工作目录（CLI 入口设置）
_current_project: Optional[str] = None


def set_project(work_dir: Optional[str]) -> None:
    """设置当前 billing 写入的目录。传 None 关闭记账。"""
    global _current_project
    _current_project = os.path.abspath(work_dir) if work_dir else None


def current_project() -> Optional[str]:
    return _current_project


def record(service: str, **fields: Any) -> None:
    """追加一条用量记录。

    service: "seedream" / "vlm" / "seedance"
    fields:  任意键值（clip_id / model / tokens / duration_s 等）
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


def summarize(work_dir: str) -> dict:
    """聚合 billing.jsonl，返回总计 + 各 clip 明细。"""
    path = os.path.join(work_dir, BILLING_FILE)
    totals: dict = {
        "seedream": {"calls": 0, "images": 0,
                     "output_tokens": 0, "total_tokens": 0, "models": {}},
        "vlm":      {"calls": 0, "prompt_tokens": 0,
                     "completion_tokens": 0, "total_tokens": 0, "models": {}},
        "seedance": {"calls": 0, "duration_seconds": 0,
                     "completion_tokens": 0, "total_tokens": 0, "models": {}},
    }
    by_clip: dict = {}
    records = 0

    if not os.path.exists(path):
        return {"totals": totals, "records": 0, "by_clip": by_clip, "grand_total_tokens": 0}

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

            if svc == "vlm":
                t = totals["vlm"]
                t["calls"]              += 1
                t["prompt_tokens"]      += int(r.get("prompt_tokens", 0) or 0)
                t["completion_tokens"]  += int(r.get("completion_tokens", 0) or 0)
                t["total_tokens"]       += int(r.get("total_tokens", 0) or 0)
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1
            elif svc == "seedream":
                t = totals["seedream"]
                t["calls"]         += 1
                t["images"]        += int(r.get("images", 1) or 1)
                t["output_tokens"] += int(r.get("output_tokens", 0) or 0)
                t["total_tokens"]  += int(r.get("total_tokens", 0) or 0)
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1
            elif svc == "seedance":
                t = totals["seedance"]
                t["calls"]             += 1
                t["duration_seconds"]  += int(r.get("duration_s", 0) or 0)
                t["completion_tokens"] += int(r.get("completion_tokens", 0) or 0)
                t["total_tokens"]      += int(r.get("total_tokens", 0) or 0)
                if model:
                    t["models"][model] = t["models"].get(model, 0) + 1

            if cid is not None:
                k = str(cid)
                bc = by_clip.setdefault(k, {
                    "vlm_calls": 0, "vlm_tokens": 0,
                    "seedream_calls": 0, "seedream_tokens": 0,
                    "seedance_calls": 0, "seedance_tokens": 0,
                    "seedance_duration_s": 0,
                })
                if svc == "vlm":
                    bc["vlm_calls"]  += 1
                    bc["vlm_tokens"] += int(r.get("total_tokens", 0) or 0)
                elif svc == "seedream":
                    bc["seedream_calls"]  += 1
                    bc["seedream_tokens"] += int(r.get("total_tokens", 0) or 0)
                elif svc == "seedance":
                    bc["seedance_calls"]      += 1
                    bc["seedance_tokens"]     += int(r.get("total_tokens", 0) or 0)
                    bc["seedance_duration_s"] += int(r.get("duration_s", 0) or 0)

    grand_total = (totals["seedream"]["total_tokens"]
                   + totals["vlm"]["total_tokens"]
                   + totals["seedance"]["total_tokens"])
    return {"totals": totals, "records": records, "by_clip": by_clip,
            "grand_total_tokens": grand_total}
