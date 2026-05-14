#!/usr/bin/env python3
"""
cartoonize — 单步执行，由 agent 驱动的视频卡通化流水线。

子命令（每次只执行一步）:
  init        初始化项目，写入 state.json
  split       Phase 1: 场景切分 + 像素缩放
  keyframes   Phase 2a: 子镜头关键帧提取
  cartoon     Phase 2b: Seedream I2I 卡通化
  vlm         Phase 3: VLM 场景分析，生成 Seedance prompt
  upload      Phase 4: TOS 上传 + Assets API 注册
  submit      Phase 5a: 批量提交 Seedance 任务
  poll        Phase 5b: 轮询所有任务状态（一次性，不阻塞）
  mux         Phase 6: 下载 + 合并原始音轨
  merge       Phase 7: 拼接最终视频
  status      查看当前状态
  styles      列出风格预设
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from video_cartoonize.settings import ARK_KEY_FILE


# ══════════════════════════════════════════════════════════════════════════════
# 凭证
# ══════════════════════════════════════════════════════════════════════════════

def _find_key(cli_key: str = "") -> str:
    if cli_key:
        return cli_key
    env = os.environ.get("ARK_API_KEY", "")
    if env:
        return env
    if ARK_KEY_FILE.exists():
        k = ARK_KEY_FILE.read_text().strip()
        if k:
            return k
    return ""


def _resolve_key(cli_key: str = "") -> str:
    key = _find_key(cli_key)
    if key:
        return key
    raise SystemExit(
        "未找到 ARK API Key。\n"
        "请设置 ARK_API_KEY 环境变量、传入 --api-key，或写入：\n"
        f"  {ARK_KEY_FILE}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 子命令实现
# ══════════════════════════════════════════════════════════════════════════════

def cmd_init(args: argparse.Namespace) -> int:
    """初始化工作目录，写入 state.json。"""
    from video_cartoonize import state as st
    from video_cartoonize.styles import STYLES

    input_video = os.path.abspath(args.input)
    if not os.path.isfile(input_video):
        raise SystemExit(f"输入视频不存在: {input_video}")

    work_dir = os.path.abspath(args.work_dir or f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(work_dir, exist_ok=True)

    s = {
        "version":    1,
        "work_dir":   work_dir,
        "input_video": input_video,
        "started_at": datetime.now().isoformat(),
        "config": {
            "style_id":            args.style,
            "ref_images":          list(args.ref_images) if args.ref_images else [],
            "ratio":               getattr(args, "ratio", None),
            "scene_threshold":     args.scene_threshold,
            "subshot_threshold":   args.subshot_threshold,
            "seedream_model":      "seedream-5-0-260128",
            "seedream_image_size": "1440x2560",
            "analyse_fps":         4,
            "seedance_model":      "dreamina-seedance-2-0-260128",
            "seedance_resolution": args.resolution,
            "max_retries":         2,
            "poll_interval":       10,
            "api_key":             _find_key(getattr(args, "api_key", "")),
        },
        "clips":           [],
        "prompts":         {},
        "clip_asset_urls": {},
        "final_video":     "",
    }
    st.save(work_dir, s)
    _out({"status": "ok", "work_dir": work_dir, "input_video": s["input_video"],
          "style": args.style})
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    """Phase 1 — 场景切分 + 像素缩放。"""
    from video_cartoonize import state as st
    from video_cartoonize.video_utils import split_video, resize_video
    from video_cartoonize.models import ClipInfo

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)

    clips_dir   = os.path.join(work_dir, "clips")
    resized_dir = os.path.join(work_dir, "resized")
    os.makedirs(resized_dir, exist_ok=True)

    raw_paths = split_video(s["input_video"], clips_dir, cfg)
    clips: List[ClipInfo] = []
    for i, raw in enumerate(raw_paths):
        dst = os.path.join(resized_dir, os.path.basename(raw))
        resize_video(raw, dst, cfg.pixel_limit)
        clips.append(ClipInfo(clip_id=i, raw_path=raw, resized_path=dst))

    st.clips_to_state(s, clips)
    st.save(work_dir, s)
    _out({"status": "ok", "clips": len(clips),
          "paths": [c.resized_path for c in clips]})
    return 0


def cmd_keyframes(args: argparse.Namespace) -> int:
    """Phase 2a — 提取子镜头关键帧。"""
    from video_cartoonize import state as st
    from video_cartoonize.scene_describe import extract_keyframes

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    clips    = st.clips_from_state(s)
    kf_dir   = os.path.join(work_dir, "keyframes")

    summary = []
    for clip in clips:
        clip.subshot_frame_paths = extract_keyframes(
            clip.resized_path, kf_dir, clip.clip_id,
            threshold=cfg.subshot_threshold,
        )
        summary.append({"clip_id": clip.clip_id,
                         "keyframes": len(clip.subshot_frame_paths),
                         "paths": clip.subshot_frame_paths})

    st.clips_to_state(s, clips)
    st.save(work_dir, s)
    _out({"status": "ok", "clips": summary})
    return 0


def cmd_cartoon(args: argparse.Namespace) -> int:
    """Phase 2b — Seedream I2I 卡通化关键帧（--clip-id 指定单个 clip）。"""
    from video_cartoonize import state as st
    from video_cartoonize.scene_describe import cartoonize_subshot_frames
    from video_cartoonize.styles import get_style

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)
    c        = s["config"]
    style    = get_style(c["style_id"], user_ref_paths=c.get("ref_images") or None)
    cart_dir = os.path.join(work_dir, "cartoons")

    clip_id  = getattr(args, "clip_id", None)
    targets  = [cl for cl in clips if clip_id is None or cl.clip_id == clip_id]

    summary = []
    for clip in targets:
        clip.subshot_cartoon_paths = cartoonize_subshot_frames(
            frame_paths=clip.subshot_frame_paths,
            out_dir=cart_dir,
            style=style,
            api_key=cfg.api_key,
            clip_id=clip.clip_id,
            model=cfg.seedream_model,
            size=cfg.seedream_image_size,
            max_workers=5,
        )
        summary.append({"clip_id": clip.clip_id,
                         "cartoons": len(clip.subshot_cartoon_paths),
                         "paths": clip.subshot_cartoon_paths})

    # 加锁，重读 + 增量合并（并发安全）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        st.merge_clips(s2, targets)
        st.save(work_dir, s2)
    _out({"status": "ok", "clips": summary})
    return 0


def cmd_vlm(args: argparse.Namespace) -> int:
    """Phase 3 — VLM 场景分析，生成 Seedance prompt（--clip-id 指定单个 clip）。"""
    from video_cartoonize import state as st
    from video_cartoonize.styles import get_style
    from video_cartoonize.core import build_preamble
    from video_cartoonize.vlm import analyse_clip

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)
    style    = get_style(s["config"]["style_id"])
    preamble = build_preamble(style.description)

    clip_id  = getattr(args, "clip_id", None)
    targets  = [cl for cl in clips if clip_id is None or cl.clip_id == clip_id]

    new_prompts: Dict[int, str] = {}
    for clip in targets:
        try:
            script = analyse_clip(clip.resized_path,
                                  api_key=cfg.api_key,
                                  fps=cfg.analyse_fps,
                                  clip_id=clip.clip_id)
            lines = script.split("\n")
            try:
                idx = next(i for i, l in enumerate(lines) if "## CLIP PROMPT" in l)
                timeline = "\n".join(lines[idx + 1:]).strip()
            except StopIteration:
                timeline = script.strip()
            new_prompts[clip.clip_id] = f"{preamble}\n\n{timeline}"
        except Exception as e:
            print(f"[VLM] clip_{clip.clip_id:02d} ✗ {e}", file=sys.stderr)
            new_prompts[clip.clip_id] = preamble

    # 加锁，重读 + 合并已有 prompts（并发安全）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        merged = {int(k): v for k, v in s2.get("prompts", {}).items()}
        merged.update(new_prompts)
        s2["prompts"] = {str(k): v for k, v in merged.items()}
        st.save(work_dir, s2)
    _out({"status": "ok",
          "prompts": {str(cid): f"{p[:80]}…" for cid, p in new_prompts.items()}})
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    """Phase 4 — TOS 上传 + Assets API 注册（--clip-id 指定单个 clip）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from video_cartoonize import state as st
    from video_cartoonize.assets_setup import get_or_create_group, upload_assets
    from video_cartoonize.tos_client import upload_file

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    clips    = st.clips_from_state(s)

    clip_id  = getattr(args, "clip_id", None)
    targets  = [cl for cl in clips if clip_id is None or cl.clip_id == clip_id]

    date_tag = datetime.now().strftime("%Y%m%d")
    group_id = s.get("asset_group_id") or get_or_create_group(f"cartoonize-{date_tag}")
    s["asset_group_id"] = group_id  # 复用同一个 group

    # 并行 TOS 上传
    upload_jobs: List[tuple] = []
    for clip in targets:
        upload_jobs.append((f"clip_{clip.clip_id:02d}", clip.resized_path))
        for j, p in enumerate(clip.subshot_cartoon_paths):
            upload_jobs.append((f"kf_{clip.clip_id:02d}_{j:02d}", p))

    tos_urls: Dict[str, str] = {}

    def do_tos(label: str, path: str):
        return label, upload_file(path, expires=86400)["url"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(do_tos, lbl, p): lbl for lbl, p in upload_jobs}
        for fut in as_completed(futures):
            try:
                label, url = fut.result()
                tos_urls[label] = url
            except Exception as e:
                print(f"[TOS] ✗ {e}", file=sys.stderr)

    # Assets 注册
    items = []
    for clip in targets:
        k = f"clip_{clip.clip_id:02d}"
        if k in tos_urls:
            items.append((k, "Video", tos_urls[k], k))
        for j in range(len(clip.subshot_cartoon_paths)):
            k = f"kf_{clip.clip_id:02d}_{j:02d}"
            if k in tos_urls:
                items.append((k, "Image", tos_urls[k], k))

    asset_urls = upload_assets(group_id, items, max_workers=7)

    # 计算本次新增的 asset URL（per-clip）
    new_clip_asset_urls: Dict[int, str] = {}
    for clip in targets:
        vid_key = f"clip_{clip.clip_id:02d}"
        if vid_key in asset_urls:
            new_clip_asset_urls[clip.clip_id] = asset_urls[vid_key]
        clip.subshot_cartoon_urls = [
            asset_urls[f"kf_{clip.clip_id:02d}_{j:02d}"]
            for j in range(len(clip.subshot_cartoon_paths))
            if f"kf_{clip.clip_id:02d}_{j:02d}" in asset_urls
        ]

    # 加锁，重读 + 增量合并（并发安全）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        st.merge_clips(s2, targets)
        existing = {int(k): v for k, v in s2.get("clip_asset_urls", {}).items()}
        existing.update(new_clip_asset_urls)
        s2["clip_asset_urls"] = {str(k): v for k, v in existing.items()}
        s2["asset_group_id"]  = group_id
        st.save(work_dir, s2)
    _out({"status": "ok", "group_id": group_id,
          "tos_uploaded": len(tos_urls), "assets_active": len(asset_urls),
          "clip_ids": [cl.clip_id for cl in targets]})
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    """Phase 5a — 提交 Seedance 任务（--clip-id 指定单个 clip）。"""
    from video_cartoonize import state as st
    from video_cartoonize.styles import get_style
    from video_cartoonize.core import build_preamble, detect_ratio, submit_clip

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)
    prompts  = {int(k): v for k, v in s.get("prompts", {}).items()}
    clip_asset_urls = {int(k): v for k, v in s.get("clip_asset_urls", {}).items()}

    clip_id  = getattr(args, "clip_id", None)
    targets  = [cl for cl in clips if clip_id is None or cl.clip_id == clip_id]

    ratio = s["config"].get("ratio") or detect_ratio(clips[0].resized_path)
    style = get_style(s["config"]["style_id"])
    preamble = build_preamble(style.description)

    submitted = []
    for clip in targets:
        if clip.task_id:  # 已提交过，跳过
            submitted.append({"clip_id": clip.clip_id, "task_id": clip.task_id, "skipped": True})
            continue
        vid_url = clip_asset_urls.get(clip.clip_id, "")
        if not vid_url:
            print(f"[submit] clip_{clip.clip_id:02d}: no asset URL, skip", file=sys.stderr)
            clip.status = "failed"
            continue
        prompt = prompts.get(clip.clip_id, preamble)
        task_id = submit_clip(cfg.api_key, clip, vid_url, prompt, ratio, cfg)
        if task_id:
            clip.task_id = task_id
            submitted.append({"clip_id": clip.clip_id, "task_id": task_id})
        else:
            clip.status = "failed"

    # 加锁，重读 + 增量合并（并发安全）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        st.merge_clips(s2, targets)
        st.save(work_dir, s2)
    _out({"status": "ok", "ratio": ratio, "submitted": submitted})
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    """Phase 5b — 查询所有任务状态（一次性，不阻塞）。

    退出码:
      0  全部已终结（success 或 failed）
      1  仍有任务运行中
    """
    from video_cartoonize import state as st
    from video_cartoonize.core import poll_task
    from video_cartoonize.ark_client import STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)

    results = []
    still_running = 0

    for clip in clips:
        if not clip.task_id or clip.status in ("success", "failed"):
            results.append({"clip_id": clip.clip_id,
                             "status": clip.status,
                             "task_id": clip.task_id or "-"})
            continue
        try:
            r = poll_task(cfg.api_key, clip.task_id)
        except Exception as e:
            results.append({"clip_id": clip.clip_id, "status": "poll_error",
                             "error": str(e)})
            still_running += 1
            continue

        api_status = r.get("status", "")
        if api_status == STATUS_SUCCEEDED:
            clip.output_url = (r.get("content") or {}).get("video_url", "")
            clip.status     = "success"
            # 记账（在 success 时拿到真实 usage tokens）
            from video_cartoonize import billing as _bl
            usage = r.get("usage") or {}
            _bl.record(
                "seedance",
                clip_id=clip.clip_id,
                model=r.get("model", ""),
                duration_s=int(r.get("duration", 0) or 0),
                resolution=r.get("resolution", ""),
                ratio=r.get("ratio", ""),
                task_id=clip.task_id,
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0),
            )
        elif api_status in (STATUS_FAILED, STATUS_CANCELLED):
            err = r.get("error") or {}
            clip.status = "failed"
        else:
            still_running += 1

        results.append({"clip_id": clip.clip_id, "status": clip.status,
                         "api_status": api_status, "task_id": clip.task_id})

    st.clips_to_state(s, clips)
    st.save(work_dir, s)

    _out({"status": "ok" if still_running == 0 else "running",
          "still_running": still_running,
          "clips": results})
    return 0 if still_running == 0 else 1


VERIFY_MAX_ATTEMPTS = 3


def cmd_verify(args: argparse.Namespace) -> int:
    """Phase 5c — VLM 校验 Seedance 输出是否为动漫风格。

    对所有 status=success 且未通过校验的 clip 调用 VLM 判定。
    通过 → style_verified=True。
    不通过 → 清除 task_id/output_url，status 设回 pending（若 attempts<3 可重提交）。

    退出码：
      0  全部 success 的 clip 都通过校验
      1  仍有 clip 未通过（agent 需要重跑 submit → poll → verify）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from video_cartoonize import state as st
    from video_cartoonize.vlm import verify_anime_style

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)

    clip_id  = getattr(args, "clip_id", None)
    targets  = [
        cl for cl in clips
        if (clip_id is None or cl.clip_id == clip_id)
        and cl.status == "success"
        and not cl.style_verified
        and cl.output_url
    ]

    if not targets:
        _out({"status": "ok", "checked": 0, "passed": 0, "failed": 0,
              "message": "没有需要校验的 clip"})
        return 0

    def check(clip):
        try:
            passed, reason = verify_anime_style(clip.output_url, api_key=cfg.api_key,
                                                 clip_id=clip.clip_id)
            return clip, passed, reason, None
        except Exception as e:
            return clip, False, "", str(e)

    results: List[dict] = []
    pass_clips, fail_clips, error_clips = [], [], []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(check, cl) for cl in targets]
        for f in as_completed(futures):
            clip, passed, reason, err = f.result()
            clip.verify_attempts += 1
            clip.verify_reason = reason or (err or "")
            if err:
                error_clips.append(clip)
                results.append({"clip_id": clip.clip_id, "verdict": "error",
                                 "error": err, "attempts": clip.verify_attempts})
            elif passed:
                clip.style_verified = True
                pass_clips.append(clip)
                results.append({"clip_id": clip.clip_id, "verdict": "pass",
                                 "reason": reason, "attempts": clip.verify_attempts})
            else:
                fail_clips.append(clip)
                # 没到上限就清空 task_id / output_url，等待重提交
                if clip.verify_attempts < VERIFY_MAX_ATTEMPTS:
                    clip.task_id    = ""
                    clip.output_url = ""
                    clip.status     = "pending"
                results.append({"clip_id": clip.clip_id, "verdict": "fail",
                                 "reason": reason, "attempts": clip.verify_attempts,
                                 "will_retry": clip.verify_attempts < VERIFY_MAX_ATTEMPTS})

    # 加锁合并写回
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        st.merge_clips(s2, targets)
        st.save(work_dir, s2)

    retry_needed = sum(1 for cl in fail_clips if cl.verify_attempts < VERIFY_MAX_ATTEMPTS)
    _out({
        "status": "ok" if retry_needed == 0 else "retry_needed",
        "checked": len(targets),
        "passed":  len(pass_clips),
        "failed":  len(fail_clips),
        "errors":  len(error_clips),
        "retry_needed": retry_needed,
        "max_attempts": VERIFY_MAX_ATTEMPTS,
        "clips": results,
    })
    return 0 if retry_needed == 0 else 1


def cmd_mux(args: argparse.Namespace) -> int:
    """Phase 6 — 下载 Seedance 输出 + 合并原始音轨。"""
    from video_cartoonize import state as st
    from video_cartoonize.video_utils import download_url
    from video_cartoonize.core import mux_original_audio

    work_dir  = _work_dir(args)
    s         = st.require(work_dir)
    clips     = st.clips_from_state(s)
    cart_dir  = os.path.join(work_dir, "cartoonized")
    final_dir = os.path.join(work_dir, "final")
    os.makedirs(cart_dir,  exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    results = []
    for clip in clips:
        if clip.status != "success" or not clip.output_url:
            results.append({"clip_id": clip.clip_id, "status": clip.status})
            continue
        cart_path  = os.path.join(cart_dir,  f"clip_{clip.clip_id:02d}.mp4")
        final_path = os.path.join(final_dir, f"clip_{clip.clip_id:02d}.mp4")
        try:
            download_url(clip.output_url, cart_path)
        except Exception as e:
            clip.status = "failed"
            results.append({"clip_id": clip.clip_id, "status": "download_failed",
                             "error": str(e)})
            continue
        ok = mux_original_audio(cart_path, clip.resized_path, final_path)
        clip.output_path = final_path if ok else cart_path
        results.append({"clip_id": clip.clip_id, "status": "ok",
                         "output": clip.output_path})

    st.clips_to_state(s, clips)
    st.save(work_dir, s)
    _out({"status": "ok", "clips": results})
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Phase 7 — 拼接所有成功片段为最终视频。"""
    from video_cartoonize import state as st
    from video_cartoonize.video_utils import merge_clips

    work_dir   = _work_dir(args)
    s          = st.require(work_dir)
    clips      = st.clips_from_state(s)
    successful = [c for c in clips if c.status == "success" and c.output_path]

    if not successful:
        _out({"status": "error", "message": "没有成功的片段可合并"})
        return 1

    final_path = os.path.join(work_dir, "final_cartoonized.mp4")
    merge_clips([c.output_path for c in successful], final_path)

    s["final_video"] = final_path
    st.save(work_dir, s)
    _out({"status": "ok", "final_video": final_path,
          "merged_clips": len(successful), "total_clips": len(clips)})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """查看当前状态。"""
    from video_cartoonize import state as st

    work_dir = _work_dir(args)
    s        = st.load(work_dir)
    if not s:
        _out({"status": "error", "message": f"state.json not found in {work_dir}"})
        return 1

    clips = s.get("clips", [])
    _out({
        "work_dir":    work_dir,
        "input_video": s.get("input_video"),
        "started_at":  s.get("started_at"),
        "style":       s.get("config", {}).get("style_id"),
        "final_video": s.get("final_video") or None,
        "clips": [
            {"clip_id": d["clip_id"], "status": d.get("status"),
             "task_id": d.get("task_id") or None}
            for d in clips
        ],
        "prompts_ready": len(s.get("prompts", {})),
        "assets_ready":  len(s.get("clip_asset_urls", {})),
    })
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """检查全局安装后的运行环境。"""
    from video_cartoonize.settings import ARK_AK_SK_FILE, ARK_KEY_FILE, CONFIG_DIR, TOS_CREDS_FILE

    has_ak_sk = (
        bool(os.environ.get("ARK_AK") and os.environ.get("ARK_SK"))
        or ARK_AK_SK_FILE.exists()
        or bool(os.environ.get("TOS_ACCESS_KEY") and os.environ.get("TOS_SECRET_KEY"))
    )
    has_bucket = bool(os.environ.get("TOS_BUCKET")) or (
        TOS_CREDS_FILE.exists() and
        bool(json.loads(TOS_CREDS_FILE.read_text()).get("bucket") if TOS_CREDS_FILE.exists() else "")
    )

    checks = {
        "ffmpeg":      bool(shutil.which("ffmpeg")),
        "ffprobe":     bool(shutil.which("ffprobe")),
        "ark_api_key": bool(os.environ.get("ARK_API_KEY")) or ARK_KEY_FILE.exists(),
        "ark_ak_sk":   has_ak_sk,   # AK/SK（Assets API + TOS 共用）
        "tos_bucket":  has_bucket,  # 只需要 bucket 名
    }
    _out({
        "status": "ok" if all(checks.values()) else "missing",
        "config_dir": str(CONFIG_DIR),
        "checks": checks,
        "notes": {
            "ark_ak_sk":  "ARK AK/SK 与 TOS AK/SK 共用同一组密钥",
            "tos_endpoint": f"默认 tos-ap-southeast-1.volces.com（可在 {TOS_CREDS_FILE} 中覆盖）",
        },
        "credential_files": {
            "ark_api_key":    str(ARK_KEY_FILE),
            "ark_ak_sk":      str(ARK_AK_SK_FILE),
            "tos_credentials": str(TOS_CREDS_FILE),
        },
    })
    return 0 if all(checks.values()) else 1


def cmd_install_skill(args: argparse.Namespace) -> int:
    """把 skill/ 目录整体复制到 ~/.claude/skills/video-cartoonize/。"""
    # skill/ 文件夹与本文件同级（在包内）
    src_skill_dir = Path(__file__).parent / "skill"
    if not src_skill_dir.is_dir():
        _out({"status": "error", "message": f"skill/ directory not found: {src_skill_dir}"})
        return 1

    override   = getattr(args, "skills_dir", "") or os.environ.get("CLAUDE_SKILLS_DIR", "")
    skills_dir = Path(override or "~/.claude/skills").expanduser()
    dest_dir   = skills_dir / "video-cartoonize"

    # 整个 skill/ → dest_dir（覆盖已有文件）
    shutil.copytree(str(src_skill_dir), str(dest_dir), dirs_exist_ok=True)

    installed = [str(p.relative_to(dest_dir)) for p in dest_dir.rglob("*") if p.is_file()]
    _out({"status": "ok", "dest": str(dest_dir), "files": installed})
    print(f"✓ Skill installed → {dest_dir}", file=sys.stderr)
    return 0


def cmd_billing(args: argparse.Namespace) -> int:
    """聚合并显示项目的 Seedream / VLM / Seedance 用量。"""
    from video_cartoonize import billing as bl

    work_dir = _work_dir(args)
    summary  = bl.summarize(work_dir)

    if getattr(args, "json", False):
        _out(summary)
        return 0

    totals = summary["totals"]
    sd, v, dn = totals["seedream"], totals["vlm"], totals["seedance"]

    print(f"工作目录: {work_dir}")
    print(f"总记录数: {summary['records']}")
    print(f"总 token 数: {summary.get('grand_total_tokens', 0):,}")
    print()
    print("Seedream (图片生成)")
    print(f"  调用次数:        {sd['calls']}")
    print(f"  生成图片数:      {sd['images']}")
    print(f"  output_tokens:   {sd['output_tokens']:>10,}")
    print(f"  total_tokens:    {sd['total_tokens']:>10,}")
    if sd['models']:
        print(f"  模型:            {sd['models']}")
    print()
    print("VLM (Seed 2.0 Lite 视频分析 + 风格校验)")
    print(f"  调用次数:        {v['calls']}")
    print(f"  prompt_tokens:   {v['prompt_tokens']:>10,}")
    print(f"  completion_tok:  {v['completion_tokens']:>10,}")
    print(f"  total_tokens:    {v['total_tokens']:>10,}")
    if v['models']:
        print(f"  模型:            {v['models']}")
    print()
    print("Seedance (视频生成)")
    print(f"  succeeded:       {dn['calls']}")
    print(f"  累计输出秒数:    {dn['duration_seconds']} s")
    print(f"  completion_tok:  {dn['completion_tokens']:>10,}")
    print(f"  total_tokens:    {dn['total_tokens']:>10,}")
    if dn['models']:
        print(f"  模型:            {dn['models']}")

    if getattr(args, "by_clip", False) and summary["by_clip"]:
        print()
        print("Per-clip 明细:")
        for cid in sorted(summary["by_clip"].keys(), key=lambda x: int(x)):
            bc = summary["by_clip"][cid]
            print(f"  clip_{int(cid):02d}: "
                  f"sdr={bc['seedream_calls']}/{bc['seedream_tokens']}tok  "
                  f"vlm={bc['vlm_calls']}/{bc['vlm_tokens']}tok  "
                  f"sdn={bc['seedance_calls']}/{bc['seedance_duration_s']}s/{bc['seedance_tokens']}tok")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    """显示 CLI 版本、Python 版本、安装位置。"""
    import platform

    try:
        from importlib.metadata import version as _pkg_version
        pkg_ver = _pkg_version("video-cartoonize")
    except Exception:
        pkg_ver = "unknown"

    pkg_path = Path(__file__).parent
    venv_bin = Path(sys.executable).parent

    _out({
        "cartoonize":  pkg_ver,
        "python":      platform.python_version(),
        "platform":    f"{platform.system()} {platform.machine()}",
        "package_dir": str(pkg_path),
        "venv":        str(venv_bin.parent),
    })
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _out(data: dict) -> None:
    """输出 JSON 结果（agent 读取用）。"""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _work_dir(args: argparse.Namespace) -> str:
    wd = getattr(args, "work_dir", None) or "."
    return os.path.abspath(wd)


# ══════════════════════════════════════════════════════════════════════════════
# CLI 解析
# ══════════════════════════════════════════════════════════════════════════════

def _add_work_dir(p: argparse.ArgumentParser, required: bool = False) -> None:
    p.add_argument(
        "--work-dir", default=".", metavar="DIR",
        help="工作目录（包含 state.json，默认：当前目录）",
    )


def build_parser() -> argparse.ArgumentParser:
    from video_cartoonize.styles import STYLES, list_styles

    root = argparse.ArgumentParser(
        prog="cartoonize",
        description="单步执行，agent 驱动的视频卡通化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
步骤顺序: init → split → keyframes → cartoon → vlm → upload → submit → poll → mux → merge

示例:
  cartoonize init --input video.mp4 --style anime
  cartoonize split
  cartoonize keyframes
  cartoonize cartoon
  cartoonize vlm
  cartoonize upload
  cartoonize submit
  cartoonize poll          # 重复直到退出码 0
  cartoonize mux
  cartoonize merge
  cartoonize status
  cartoonize doctor
        """,
    )
    sub = root.add_subparsers(dest="cmd", required=True)

    # init
    p = sub.add_parser("init", help="初始化项目")
    p.add_argument("--input",    required=True,  metavar="VIDEO")
    p.add_argument("--work-dir", default="",     metavar="DIR",
                   help="工作目录（默认：output_YYYYMMDD_HHMMSS/）")
    p.add_argument("--style",    default="anime",
                   choices=list(STYLES.keys()) + ["custom"])
    p.add_argument("--ref-images", nargs="+", metavar="IMG")
    p.add_argument("--ratio", default=None,
                   choices=["16:9","9:16","1:1","4:3","3:4","21:9"])
    p.add_argument("--resolution", default="720p",
                   choices=["480p","720p","1080p"])
    p.add_argument("--api-key", default="", metavar="KEY")
    p.add_argument("--scene-threshold",   type=float, default=25.0)
    p.add_argument("--subshot-threshold", type=float, default=27.0)

    # split / keyframes / mux / merge — 全量，无 --clip-id
    for name, help_text in [
        ("split",     "Phase 1: 场景切分 + 缩放"),
        ("keyframes", "Phase 2a: 关键帧提取"),
        ("mux",       "Phase 6: 下载 + 音轨合并"),
        ("merge",     "Phase 7: 拼接最终视频"),
    ]:
        _add_work_dir(sub.add_parser(name, help=help_text))

    # cartoon / vlm / upload / submit / verify — 支持 --clip-id 单 clip 模式
    for name, help_text in [
        ("cartoon", "Phase 2b: Seedream 卡通化（--clip-id 指定单个 clip）"),
        ("vlm",     "Phase 3: VLM 场景分析（--clip-id 指定单个 clip）"),
        ("upload",  "Phase 4: TOS + Assets 上传（--clip-id 指定单个 clip）"),
        ("submit",  "Phase 5a: 提交 Seedance 任务（--clip-id 指定单个 clip）"),
        ("verify",  "Phase 5c: VLM 校验生成视频是否动漫风格（exit 0=全通过，1=需重试）"),
    ]:
        p = sub.add_parser(name, help=help_text)
        _add_work_dir(p)
        p.add_argument("--clip-id", type=int, default=None, metavar="N",
                       help="只处理指定 clip（不填则处理全部）")

    # poll
    p = sub.add_parser("poll", help="Phase 5b: 查询 Seedance 任务状态（exit 0=全完成，1=仍运行中）")
    _add_work_dir(p)

    # status
    _add_work_dir(sub.add_parser("status", help="查看当前状态"))

    # styles
    sub.add_parser("styles", help="列出所有风格预设")

    # doctor
    sub.add_parser("doctor", help="检查 ffmpeg 和云服务凭证")

    # install-skill
    p = sub.add_parser("install-skill", help="将 SKILL.md 安装到 ~/.claude/skills/video-cartoonize/")
    p.add_argument("--skills-dir", default="", metavar="DIR",
                   help="Claude skills 目录（默认：~/.claude/skills）")

    # version
    sub.add_parser("version", help="显示版本信息")

    # billing
    p = sub.add_parser("billing", help="显示项目 Seedream/VLM/Seedance 用量汇总")
    _add_work_dir(p)
    p.add_argument("--by-clip", action="store_true", help="同时显示每个 clip 的明细")
    p.add_argument("--json",    action="store_true", help="输出原始 JSON（而非格式化文本）")

    return root


def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    # 设置当前项目，所有 API 调用的 billing 都写到这里
    from video_cartoonize import billing as _billing
    if hasattr(args, "work_dir") and args.work_dir:
        _billing.set_project(args.work_dir)
    elif args.cmd == "init":
        # init 的 work_dir 是动态生成的，cmd_init 内部不需要 billing
        pass

    dispatch = {
        "init":      cmd_init,
        "split":     cmd_split,
        "keyframes": cmd_keyframes,
        "cartoon":   cmd_cartoon,
        "vlm":       cmd_vlm,
        "upload":    cmd_upload,
        "submit":    cmd_submit,
        "poll":      cmd_poll,
        "verify":    cmd_verify,
        "mux":       cmd_mux,
        "merge":     cmd_merge,
        "status":    cmd_status,
        "doctor":        cmd_doctor,
        "install-skill": cmd_install_skill,
        "version":       cmd_version,
        "billing":       cmd_billing,
    }

    if args.cmd == "styles":
        from video_cartoonize.styles import list_styles
        print(list_styles())
        return 0

    fn = dispatch.get(args.cmd)
    if fn is None:
        parser.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
