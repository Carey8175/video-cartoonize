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

SEEDANCE_MODEL_ALIASES = {
    "standard": "dreamina-seedance-2-0-260128",
    "fast":     "dreamina-seedance-2-0-fast-260128",
}


def _build_final_prompt(clip, prompts_map: dict, preamble: str) -> str:
    """构造 Seedance final prompt（preamble + image hint + timeline）。"""
    from video_cartoonize.core import build_image_order_hint
    base = prompts_map.get(clip.clip_id, preamble)
    hint = build_image_order_hint(len(clip.subshot_cartoon_urls))
    if hint and "\n\n" in base:
        head, tail = base.split("\n\n", 1)
        return f"{head}\n\n{hint}\n\n{tail}"
    elif hint:
        return f"{base}\n\n{hint}"
    return base




def _resolve_seedance_model(alias_or_id: str) -> str:
    """把 'standard'/'fast'/原 ID 都正规化成真实 endpoint ID。"""
    a = (alias_or_id or "standard").strip().lower()
    if a in SEEDANCE_MODEL_ALIASES:
        return SEEDANCE_MODEL_ALIASES[a]
    return alias_or_id   # 已经是完整 ID，直接用


def cmd_init(args: argparse.Namespace) -> int:
    """初始化工作目录，写入 state.json。"""
    from video_cartoonize import state as st
    from video_cartoonize.styles import STYLES

    input_video = os.path.abspath(args.input)
    if not os.path.isfile(input_video):
        raise SystemExit(f"输入视频不存在: {input_video}")

    work_dir = os.path.abspath(args.work_dir or f"output_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(work_dir, exist_ok=True)

    seedance_model = _resolve_seedance_model(getattr(args, "seedance_model", "standard"))

    from video_cartoonize.state import CURRENT_SCHEMA_VERSION
    s = {
        "version":    CURRENT_SCHEMA_VERSION,
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
            "seedream_image_size": "auto",
            "analyse_fps":         4,
            "seedance_model":      seedance_model,
            "seedance_resolution": args.resolution,
            "max_retries":         2,
            "poll_interval":       10,
            # ⚠ 不写 api_key 到 state.json。运行时通过 ARK_API_KEY 环境变量
            # 或 ~/.config/video-cartoonize/ark_api_key.txt 读取。
        },
        "clips":           [],
        "prompts":         {},
        "clip_asset_urls": {},
        "final_video":     "",
    }
    st.save(work_dir, s)
    _out({"status": "ok", "work_dir": work_dir, "input_video": s["input_video"],
          "style": args.style, "seedance_model": seedance_model})
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
    if not raw_paths:
        # PySceneDetect found no cuts (or _adjust_scenes filtered all of them
        # out — short/static clips). Fall back to treating the whole video as
        # one clip so the rest of the pipeline can still run.
        import shutil as _sh
        os.makedirs(clips_dir, exist_ok=True)
        src = s["input_video"]
        name = os.path.basename(src).rsplit(".", 1)[0]
        single = os.path.join(clips_dir, f"{name}-Clip-001.mp4")
        _sh.copy2(src, single)
        raw_paths = [single]
        print("[Split] no scenes detected — falling back to single-clip mode")
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


def cmd_identify(args: argparse.Namespace) -> int:
    """Phase 2a-opt — 人物识别：检测主角/配角，写入 state.json characters 字段。

    依赖 InsightFace (buffalo_l)，首次运行会自动下载 ~300MB 模型。
    keyframes 步骤之前或之后均可运行；char-refs 必须在 identify 之后。
    """
    from video_cartoonize import state as st
    from video_cartoonize.character import identify_characters, map_keyframes_to_characters

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    clips    = st.clips_from_state(s)

    video_path = s.get("input_video", "")
    if not video_path or not os.path.exists(video_path):
        _out({"status": "error",
              "message": f"input_video '{video_path}' not found — re-run cartoonize init"})
        return 1

    from video_cartoonize.character import (
        SAMPLE_FPS, CLUSTER_THRESHOLD, MIN_DET_SCORE,
        PROTAGONIST_FREQ_DEFAULT, SUPPORTING_FREQ_DEFAULT, MATCH_THRESHOLD,
    )

    fps             = getattr(args, "fps",              SAMPLE_FPS)
    cl_thresh       = getattr(args, "cluster_threshold", CLUSTER_THRESHOLD)
    det_score       = getattr(args, "min_det_score",    MIN_DET_SCORE)
    prot_freq       = getattr(args, "protagonist_freq", PROTAGONIST_FREQ_DEFAULT)
    supp_freq       = getattr(args, "supporting_freq",  SUPPORTING_FREQ_DEFAULT)
    match_thresh    = getattr(args, "match_threshold",  MATCH_THRESHOLD)

    # Step 1: identify characters from raw video
    characters = identify_characters(
        video_path=video_path,
        work_dir=work_dir,
        fps=fps,
        cluster_threshold=cl_thresh,
        min_det_score=det_score,
        protagonist_freq=prot_freq,
        supporting_freq=supp_freq,
    )

    # Step 2: map each keyframe to matched characters (runs only if keyframes exist)
    char_kf_map = {}
    any_keyframes = any(cl.subshot_frame_paths for cl in clips)
    if any_keyframes:
        char_kf_map = map_keyframes_to_characters(
            work_dir=work_dir,
            characters=characters,
            clips=clips,
            min_det_score=det_score,
            match_threshold=match_thresh,
        )
    else:
        print("[Identify] No keyframes extracted yet — run 'cartoonize keyframes' "
              "then re-run 'cartoonize identify' to get char_keyframe_map")

    # Persist to state
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        s2["characters"]        = characters
        s2["char_keyframe_map"] = char_kf_map
        st.save(work_dir, s2)

    n_prot = sum(1 for c in characters if c["role"] == "protagonist")
    n_supp = sum(1 for c in characters if c["role"] == "supporting")
    _out({
        "status":          "ok",
        "protagonists":    n_prot,
        "supporting":      n_supp,
        "total_chars":     len(characters),
        "kf_mapped_clips": len(char_kf_map),
        "characters":      [
            {"char_id": c["char_id"], "role": c["role"],
             "freq": c["freq"], "face_ref": c["face_ref"]}
            for c in characters
        ],
    })
    return 0


def cmd_char_refs(args: argparse.Namespace) -> int:
    """Phase 2a-opt — 生成动漫角色参考图：对每个主角/配角的真人脸 Seedream I2I。

    必须在 identify 之后运行（需要 state.json characters 字段）。
    生成结果写入 work_dir/characters/char_NN_anime.jpg 并更新 state.json。
    之后 cartoon 阶段会自动把角色动漫 ref 注入对应 keyframe 的 Seedream 调用。
    """
    from video_cartoonize import state as st
    from video_cartoonize.styles import get_style
    from video_cartoonize.character import generate_anime_refs

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)

    characters = s.get("characters", [])
    if not characters:
        _out({"status": "error",
              "message": "No characters found — run 'cartoonize identify' first"})
        return 1

    n_targets = sum(1 for c in characters
                    if c["role"] in ("protagonist", "supporting"))
    if n_targets == 0:
        _out({"status": "ok", "message": "No protagonists or supporting found",
              "generated": 0})
        return 0

    cfg_d  = s["config"]
    style  = get_style(cfg_d["style_id"],
                       user_ref_paths=cfg_d.get("ref_images") or None)

    updated = generate_anime_refs(
        work_dir=work_dir,
        characters=characters,
        style=style,
        api_key=cfg.api_key,
        model=cfg.seedream_model,
        size=cfg.seedream_image_size,
    )

    with st.lock(work_dir):
        s2 = st.require(work_dir)
        s2["characters"] = updated
        st.save(work_dir, s2)

    n_ok = sum(1 for c in updated if c.get("anime_ref"))
    _out({
        "status":    "ok",
        "generated": n_ok,
        "total":     len(updated),
        "characters": [
            {"char_id": c["char_id"], "role": c["role"],
             "anime_ref": c.get("anime_ref")}
            for c in updated
        ],
    })
    return 0


def cmd_cartoon(args: argparse.Namespace) -> int:
    """Phase 2b — Seedream I2I 卡通化关键帧（--clip-id 指定单个 clip）。"""
    from video_cartoonize import state as st
    from video_cartoonize.scene_describe import cartoonize_subshot_frames
    from video_cartoonize.styles import get_style
    from video_cartoonize.character import resolve_keyframe_char_refs

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

    # 0.14.10+: per-frame character refs (if identify + char-refs were run)
    characters        = s.get("characters", [])
    char_keyframe_map = s.get("char_keyframe_map", {})
    has_char_refs     = any(c.get("anime_ref") for c in characters)
    if has_char_refs:
        print(f"[Cartoon] Character consistency mode: "
              f"{sum(1 for c in characters if c.get('anime_ref'))} anime refs available")

    summary = []
    for clip in targets:
        # Build extra_refs_per_frame from character mapping
        extra_refs: Optional[List[List[str]]] = None
        if has_char_refs and characters:
            extra_refs = [
                resolve_keyframe_char_refs(
                    clip.clip_id, kf_idx,
                    characters, char_keyframe_map,
                )
                for kf_idx in range(len(clip.subshot_frame_paths))
            ]
            n_with_refs = sum(1 for r in extra_refs if r)
            if n_with_refs:
                print(f"[Cartoon] clip {clip.clip_id:02d}: "
                      f"{n_with_refs}/{len(clip.subshot_frame_paths)} keyframes have char refs")

        clip.subshot_cartoon_paths = cartoonize_subshot_frames(
            frame_paths=clip.subshot_frame_paths,
            out_dir=cart_dir,
            style=style,
            api_key=cfg.api_key,
            clip_id=clip.clip_id,
            model=cfg.seedream_model,
            size=cfg.seedream_image_size,
            max_workers=5,
            extra_refs_per_frame=extra_refs,
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
    cfg_dict = s["config"]
    style    = get_style(cfg_dict["style_id"], user_ref_paths=cfg_dict.get("ref_images") or None)
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
    per_clip_cartoon_urls: Dict[int, list] = {}
    incomplete: list = []
    for clip in targets:
        vid_key = f"clip_{clip.clip_id:02d}"
        if vid_key in asset_urls:
            new_clip_asset_urls[clip.clip_id] = asset_urls[vid_key]

        cartoon_urls = [
            asset_urls[f"kf_{clip.clip_id:02d}_{j:02d}"]
            for j in range(len(clip.subshot_cartoon_paths))
            if f"kf_{clip.clip_id:02d}_{j:02d}" in asset_urls
        ]
        per_clip_cartoon_urls[clip.clip_id] = cartoon_urls

        # 完整性校验: 视频 + 所有 cartoon 帧都必须有 asset URL
        expected = 1 + len(clip.subshot_cartoon_paths)
        actual   = (1 if vid_key in asset_urls else 0) + len(cartoon_urls)
        if actual < expected:
            incomplete.append({
                "clip_id":         clip.clip_id,
                "expected_assets": expected,
                "actual_assets":   actual,
                "video_asset_ok":  vid_key in asset_urls,
                "cartoon_assets":  f"{len(cartoon_urls)}/{len(clip.subshot_cartoon_paths)}",
            })

    # 任何 clip 的 asset 不完整就 fail-fast（exit 非 0），不写 state
    if incomplete:
        _out({
            "status": "error",
            "error_type": "AssetUploadError",
            "message": "asset registration incomplete for some clips",
            "incomplete": incomplete,
            "group_id": group_id,
            "tos_uploaded": len(tos_urls),
            "assets_active": len(asset_urls),
        })
        return 1

    # 加锁，字段级合并（并发安全；只动我们关心的字段）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        for clip in targets:
            st.merge_clip_fields(s2, clip.clip_id,
                                 subshot_cartoon_urls=per_clip_cartoon_urls[clip.clip_id])
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
    from video_cartoonize.core import build_preamble, build_image_order_hint, detect_ratio, submit_clip

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
    cfg_dict = s["config"]
    style = get_style(cfg_dict["style_id"], user_ref_paths=cfg_dict.get("ref_images") or None)
    preamble = build_preamble(style.description)

    dry_run = bool(getattr(args, "dry_run", False))

    submitted   = []
    preview     = []   # dry-run 时填充
    missing_url = []   # 缺 asset URL 的 clip（致命错）
    for clip in targets:
        if clip.task_id and not dry_run:  # 已提交过，跳过（dry-run 时显示完整 prompt）
            submitted.append({"clip_id": clip.clip_id, "task_id": clip.task_id, "skipped": True})
            continue
        vid_url = clip_asset_urls.get(clip.clip_id, "")
        if not vid_url:
            # 缺 video asset URL = 上游 upload 没成功，agent 必须知道
            missing_url.append({
                "clip_id":      clip.clip_id,
                "n_images":     len(clip.subshot_cartoon_urls),
                "has_paths":    bool(clip.subshot_cartoon_paths),
            })
            continue

        # ── 第 3 次重试（verify_attempts >= 2）改为 image-only 模式 ─────
        # 前两次失败说明原视频内容在污染输出，第三次甩掉原视频，
        # 只用 cartoon key frames + timeline prompt 生成。
        use_ref_video = clip.verify_attempts < 2
        mode = "image-only" if not use_ref_video else "video+image"

        # 构造 Seedance final prompt（preamble + image hint + timeline）
        prompt = _build_final_prompt(clip, prompts, preamble)

        if dry_run:
            preview.append({
                "clip_id":         clip.clip_id,
                "mode":            mode,
                "use_ref_video":   use_ref_video,
                "video_asset":     vid_url if use_ref_video else None,
                "n_images":        len(clip.subshot_cartoon_urls),
                "ratio":           ratio,
                "resolution":      cfg.seedance_resolution,
                "model":           cfg.seedance_model,
                "prompt_chars":    len(prompt),
                "prompt_preview":  prompt[:500] + ("..." if len(prompt) > 500 else ""),
            })
            continue

        task_id = submit_clip(cfg.api_key, clip, vid_url, prompt, ratio, cfg,
                              use_reference_video=use_ref_video)
        if task_id:
            clip.task_id = task_id
            submitted.append({"clip_id": clip.clip_id, "task_id": task_id,
                              "attempt": clip.verify_attempts + 1, "mode": mode})
        else:
            clip.status = "failed"

    if dry_run:
        _out({"status": "dry_run", "ratio": ratio, "preview": preview,
              "note": "no Seedance task was actually submitted"})
        return 0

    # 缺 asset URL = 致命错（上游 upload 没成功），不能静默
    if missing_url:
        _out({
            "status": "error",
            "error_type": "MissingAssetURL",
            "message": "some clips have no video asset URL — run `cartoonize upload --clip-id N` first",
            "missing_url": missing_url,
            "submitted": submitted,  # 已成功提交的也报告一下
        })
        return 1

    # 加锁，只更新 task_id / status 字段（避免覆盖其他进程写的 cartoon_urls 等）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        for clip in targets:
            if not clip.task_id and clip.status != "failed":
                continue
            st.merge_clip_fields(s2, clip.clip_id,
                                 task_id=clip.task_id, status=clip.status)
        st.save(work_dir, s2)
    _out({"status": "ok", "ratio": ratio, "submitted": submitted})
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """★ Agent 主入口：对单个 clip 一站式跑 cartoon + vlm + upload + submit。

    内部:
      1. cartoon + vlm 并行（独立输入，互不依赖）
      2. upload（TOS + Assets API）
      3. submit（Seedance 任务）

    返回（成功时）:
      {"status": "ok", "clip_id": N, "task_id": "cgt-...",
       "mode": "video+image"|"image-only",
       "phases": {cartoon, vlm, upload, submit ⇒ ok|err}}
    """
    import threading
    import time as _time
    from video_cartoonize.logsetup import log_clip_event
    from video_cartoonize import state as _st
    global _SUPPRESS_OUT, _captured_out

    clip_id  = args.clip_id
    work_dir = _work_dir(args)
    started_at = datetime.now().isoformat(timespec="seconds")
    t0 = _time.time()

    # 读 clip 当前状态作详细启动日志
    _s_before = _st.load(work_dir) or {}
    _clip_before = next(
        (c for c in _s_before.get("clips", []) if c.get("clip_id") == clip_id), {}
    )
    log_clip_event(
        work_dir, clip_id, "run.start",
        project_path=work_dir,
        started_at=started_at,
        resized_path=_clip_before.get("resized_path"),
        n_keyframes_existing=len(_clip_before.get("subshot_frame_paths", [])),
        n_cartoons_existing=len(_clip_before.get("subshot_cartoon_paths", [])),
        n_cartoon_urls_existing=len(_clip_before.get("subshot_cartoon_urls", [])),
        existing_task_id=_clip_before.get("task_id", ""),
        verify_attempts=_clip_before.get("verify_attempts", 0),
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    # 抑制子命令的 _out 输出，最后聚合
    _captured_out.clear()
    _SUPPRESS_OUT = True
    phases: dict = {}

    def _run_phase(name: str, fn) -> int:
        snapshot = len(_captured_out)
        rc = fn(args)
        # 取该 phase 期间最后一次 _out
        new_outs = _captured_out[snapshot:]
        last = new_outs[-1] if new_outs else None
        phases[name] = {
            "rc":     rc,
            "status": (last or {}).get("status", "?"),
            "summary": last,
        }
        return rc

    try:
        # 1) cartoon + vlm 并行
        cartoon_rc = [0]
        vlm_rc     = [0]
        snap_c = len(_captured_out)
        snap_v = len(_captured_out)

        def _cartoon():
            cartoon_rc[0] = cmd_cartoon(args)
        def _vlm():
            vlm_rc[0] = cmd_vlm(args)

        t_phase_start = _time.time()
        t_c = threading.Thread(target=_cartoon)
        t_v = threading.Thread(target=_vlm)
        t_c.start(); t_v.start()
        t_c.join();  t_v.join()

        # 汇总 cartoon 和 vlm phase（按 captured_out 顺序无法精准分，
        # 用 max(snap_c, snap_v) 之后的输出聚合）
        cartoon_out = [o for o in _captured_out[snap_c:] if "clips" in o and o.get("clips") and isinstance(o["clips"], list) and (o["clips"][0].get("cartoons") if o["clips"] else None) is not None]
        vlm_out     = [o for o in _captured_out[snap_v:] if "prompts" in o]
        phases["cartoon"] = {"rc": cartoon_rc[0],
                             "summary": cartoon_out[-1] if cartoon_out else None}
        phases["vlm"]     = {"rc": vlm_rc[0],
                             "summary": vlm_out[-1] if vlm_out else None}

        # 详细日志：保留完整子命令 JSON 结果
        log_clip_event(work_dir, clip_id, "run.cartoon_vlm_done",
                       cartoon_rc=cartoon_rc[0], vlm_rc=vlm_rc[0],
                       duration_s=round(_time.time() - t_phase_start, 1),
                       cartoon_result=phases["cartoon"]["summary"],
                       vlm_result=phases["vlm"]["summary"])

        if cartoon_rc[0] != 0:
            err = next((o for o in _captured_out[snap_c:] if o.get("status") == "error"), None)
            log_clip_event(work_dir, clip_id, "run.error", stage="cartoon", error=err)
            _SUPPRESS_OUT = False
            _out({"status": "error", "stage": "cartoon", "clip_id": clip_id,
                  "error": err, "phases": phases})
            return cartoon_rc[0]
        if vlm_rc[0] != 0:
            err = next((o for o in _captured_out[snap_v:] if o.get("status") == "error"), None)
            log_clip_event(work_dir, clip_id, "run.error", stage="vlm", error=err)
            _SUPPRESS_OUT = False
            _out({"status": "error", "stage": "vlm", "clip_id": clip_id,
                  "error": err, "phases": phases})
            return vlm_rc[0]

        # 2) upload
        t_phase_start = _time.time()
        rc = _run_phase("upload", cmd_upload)
        log_clip_event(work_dir, clip_id, "run.upload_done", rc=rc,
                       duration_s=round(_time.time() - t_phase_start, 1),
                       result=phases["upload"]["summary"])
        if rc != 0:
            err = phases["upload"].get("summary")
            log_clip_event(work_dir, clip_id, "run.error", stage="upload", error=err)
            _SUPPRESS_OUT = False
            _out({"status": "error", "stage": "upload", "clip_id": clip_id,
                  "error": err, "phases": phases})
            return rc

        # 3) submit
        t_phase_start = _time.time()
        rc = _run_phase("submit", cmd_submit)
        log_clip_event(work_dir, clip_id, "run.submit_done", rc=rc,
                       duration_s=round(_time.time() - t_phase_start, 1),
                       result=phases["submit"]["summary"])
        if rc != 0:
            err = phases["submit"].get("summary")
            log_clip_event(work_dir, clip_id, "run.error", stage="submit", error=err)
            _SUPPRESS_OUT = False
            _out({"status": "error", "stage": "submit", "clip_id": clip_id,
                  "error": err, "phases": phases})
            return rc

        submit_out = phases["submit"].get("summary") or {}
        if submit_out.get("status") == "dry_run":
            log_clip_event(work_dir, clip_id, "run.dry_run")
            _SUPPRESS_OUT = False
            _out({"status": "dry_run", "clip_id": clip_id,
                  "preview": submit_out.get("preview"), "phases": phases})
            return 0

        submitted = (submit_out.get("submitted") or [])
        first = submitted[0] if submitted else {}
        task_id = first.get("task_id", "")
        mode    = first.get("mode", "")
        log_clip_event(
            work_dir, clip_id, "run.end",
            task_id=task_id,
            mode=mode,
            attempt=first.get("attempt"),
            ratio=submit_out.get("ratio"),
            total_duration_s=round(_time.time() - t0, 1),
            started_at=started_at,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            phases_summary={
                k: {"rc": v.get("rc"), "status": v.get("status")}
                for k, v in phases.items()
            },
        )

        _SUPPRESS_OUT = False
        _out({
            "status":  "ok",
            "clip_id": clip_id,
            "task_id": task_id,
            "mode":    mode,
            "started_at":  started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "phases":  phases,
        })
        return 0
    finally:
        _SUPPRESS_OUT = False
        _captured_out.clear()


VERIFY_MAX_ATTEMPTS = 3

# ── 自动重试时新增关键帧的策略阈值 ──────────────────────────────────────────────
# 尝试 2：相邻关键帧时间差 > FLOOR_GAP_SEC 就等距补齐（追加，不重画已有的）
RETRY_FLOOR_GAP_SEC = 3.0
# 尝试 3：把关键帧总数补齐到 UNIFORM_TARGET（追加到最大间隙的中点，重复直到达标）
RETRY_UNIFORM_TARGET = 10


def _parse_keyframe_timestamp(path: str) -> Optional[float]:
    """从关键帧文件名解析时间戳。约定: `<stem>_subNN_t<sec>.jpg`。"""
    import re
    m = re.search(r"_t(\d+(?:\.\d+)?)\.jpg$", os.path.basename(path))
    return float(m.group(1)) if m else None


def _compute_topup_timestamps_floor(
    existing_ts: List[float], duration: float, max_gap: float = RETRY_FLOOR_GAP_SEC,
) -> List[float]:
    """尝试 2 的时间戳规划：相邻间隔 > max_gap 时，等距补齐。

    `existing_ts` + duration（视作末尾哨兵）切成区间；每段间隔 > max_gap 时，
    插入 `floor(gap / max_gap)` 个等距点。返回**仅新增**的时间戳列表（已排序）。
    若 existing_ts 为空，从 [0, duration] 整段算。
    """
    if duration <= 0:
        return []
    boundaries = sorted(existing_ts) if existing_ts else [0.0]
    extras: List[float] = []
    for i, b in enumerate(boundaries):
        nxt = boundaries[i + 1] if i + 1 < len(boundaries) else duration
        gap = nxt - b
        if gap > max_gap:
            n_extra = int(gap // max_gap)
            step    = gap / (n_extra + 1)
            for k in range(1, n_extra + 1):
                t = round(b + k * step, 2)
                # 避免和已有时间戳几乎重合
                if all(abs(t - et) > 0.3 for et in existing_ts):
                    extras.append(t)
    return sorted(set(extras))


def _compute_topup_timestamps_uniform(
    existing_ts: List[float], duration: float, target_total: int = RETRY_UNIFORM_TARGET,
) -> List[float]:
    """尝试 3 的时间戳规划：贪心 farthest-point，把总数补齐到 target_total。

    每轮在当前所有点（含 0 / duration 边界 + 已选点）的最大间隙中点插一个新点，
    重复 `target_total - len(existing_ts)` 次。返回仅新增的时间戳（已排序）。
    """
    if duration <= 0 or target_total <= len(existing_ts):
        return []
    need = target_total - len(existing_ts)
    pts  = sorted(set([0.0] + list(existing_ts) + [duration]))
    extras: List[float] = []
    for _ in range(need):
        best_i = max(range(len(pts) - 1), key=lambda i: pts[i + 1] - pts[i])
        mid    = round((pts[best_i] + pts[best_i + 1]) / 2, 2)
        extras.append(mid)
        pts.append(mid)
        pts.sort()
    return sorted(extras)


def _upload_new_cartoons_only(
    clip_id: int,
    new_cartoon_paths: List[str],
    start_index: int,
    work_dir: str,
    s: dict,
) -> List[str]:
    """TOS + Assets register for new cartoon files only (no video re-upload).

    Reuses the existing `asset_group_id` from state.json. Returns asset URLs
    ordered by index, or `[]` if any asset failed to register (caller bails
    rather than partially appending).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from video_cartoonize.assets_setup import get_or_create_group, upload_assets
    from video_cartoonize.tos_client import upload_file
    date_tag = datetime.now().strftime("%Y%m%d")
    group_id = s.get("asset_group_id") or get_or_create_group(f"cartoonize-{date_tag}")

    labels  = [f"kf_{clip_id:02d}_{start_index + j:02d}" for j in range(len(new_cartoon_paths))]
    tos_urls: Dict[str, str] = {}

    def do_tos(label: str, path: str):
        return label, upload_file(path, expires=86400)["url"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(do_tos, lbl, p): lbl
            for lbl, p in zip(labels, new_cartoon_paths)
        }
        for fut in as_completed(futures):
            try:
                label, url = fut.result()
                tos_urls[label] = url
            except Exception as e:
                print(f"[TOS retry] ✗ {e}", file=sys.stderr)

    items = [(lbl, "Image", tos_urls[lbl], lbl) for lbl in tos_urls]
    asset_urls = upload_assets(group_id, items, max_workers=7)

    # Ordered output; bail if anything missing (fail-fast like cmd_upload)
    ordered: List[str] = []
    for lbl in labels:
        if lbl not in asset_urls:
            return []
        ordered.append(asset_urls[lbl])
    return ordered


def _regenerate_clip_for_retry(clip, work_dir: str, s: dict, cfg, strategy: str) -> bool:
    """Append-only 关键帧扩充。已有 cartoons 和 asset URLs 不动。

    strategy:
      'with_floor' — 尝试 2：3s 时间保底，补齐间隔
      'uniform10'  — 尝试 3：farthest-point 补齐到 10 张总数

    Returns True 若至少新增了一张关键帧并完成上传。
    """
    from video_cartoonize import state as _st
    from video_cartoonize.sub_shot_detect import _extract_at_timestamps, _probe_duration
    from video_cartoonize.scene_describe import cartoonize_extra_subshot_frames
    from video_cartoonize.styles import get_style

    duration = _probe_duration(clip.resized_path)
    if duration <= 0:
        return False

    existing_n  = len(clip.subshot_frame_paths)
    existing_ts = sorted([
        t for t in (_parse_keyframe_timestamp(p) for p in clip.subshot_frame_paths)
        if t is not None
    ])
    # 若解析不出（不是本 CLI 抽的帧），退化为 0..duration 均匀填充入参
    if len(existing_ts) != existing_n:
        existing_ts = [round(duration * (i + 0.5) / max(existing_n, 1), 2)
                       for i in range(existing_n)]

    if strategy == "with_floor":
        new_ts = _compute_topup_timestamps_floor(existing_ts, duration, max_gap=RETRY_FLOOR_GAP_SEC)
    elif strategy == "uniform10":
        new_ts = _compute_topup_timestamps_uniform(existing_ts, duration, target_total=RETRY_UNIFORM_TARGET)
    else:
        return False

    if not new_ts:
        return False  # 已经足够，不用补

    kf_dir   = os.path.join(work_dir, "keyframes", f"clip_{clip.clip_id:02d}")
    cart_dir = os.path.join(work_dir, "cartoons")

    new_pairs = _extract_at_timestamps(clip.resized_path, kf_dir, new_ts)
    if not new_pairs:
        return False
    new_frame_paths = [p for _, p in new_pairs]

    cfg_dict = s["config"]
    style    = get_style(cfg_dict["style_id"], user_ref_paths=cfg_dict.get("ref_images") or None)
    new_cartoon_paths = cartoonize_extra_subshot_frames(
        new_frame_paths=new_frame_paths,
        out_dir=cart_dir,
        style=style,
        api_key=cfg.api_key,
        clip_id=clip.clip_id,
        start_index=existing_n,
        model=cfg.seedream_model,
        size=cfg.seedream_image_size,
    )
    if not new_cartoon_paths:
        return False

    # 上传仅新增的 cartoon 到 TOS + Assets（视频已注册过，跳过）
    new_cartoon_urls = _upload_new_cartoons_only(
        clip.clip_id, new_cartoon_paths, existing_n, work_dir, s,
    )
    if not new_cartoon_urls:
        return False

    combined_frame_paths   = list(clip.subshot_frame_paths)   + new_frame_paths
    combined_cartoon_paths = list(clip.subshot_cartoon_paths) + new_cartoon_paths
    combined_cartoon_urls  = list(clip.subshot_cartoon_urls)  + new_cartoon_urls

    with _st.lock(work_dir):
        s2 = _st.require(work_dir)
        _st.merge_clip_fields(
            s2, clip.clip_id,
            subshot_frame_paths=combined_frame_paths,
            subshot_cartoon_paths=combined_cartoon_paths,
            subshot_cartoon_urls=combined_cartoon_urls,
        )
        _st.save(work_dir, s2)

    # Sync local clip view so subsequent submit_clip sees the new image refs
    clip.subshot_frame_paths   = combined_frame_paths
    clip.subshot_cartoon_paths = combined_cartoon_paths
    clip.subshot_cartoon_urls  = combined_cartoon_urls
    return True


def cmd_poll(args: argparse.Namespace) -> int:
    """Phase 5b/5c 一站式 — 查询 Seedance + 自动 VLM 风格校验 + 自动重试调度。

    单 clip 模式 (--clip-id N) 是 agent 唯一需要的查询命令：

        cartoonize run --clip-id N    # 启动
        while True:
            res = cartoonize poll --clip-id N
            case exit code:
                0 = done       → 拿 res.video_url 接 mux/merge
                1 = running    → sleep 30s 再 poll
                                  (CLI 内部已自动 resubmit/重试 verify 失败的 clip)

    内部状态机:
        1. 查 Seedance 状态
        2. 若 SUCCEEDED → 自动 verify_anime_style
            pass → status=done, style_verified=true
            fail 且 attempts < 3 → 内部 resubmit Seedance（第3次自动 image-only），
                                 拿新 task_id，返回 running（不让 agent 操心）
            fail 且 attempts >= 3 → status=done, style_verified=false（兜底视频）
        3. 若 FAILED/CANCELLED → status=done, error=...

    无 --clip-id (全量模式): 仅查询不 verify（向后兼容旧调用）。
    """
    from video_cartoonize import state as st
    from video_cartoonize.core import poll_task
    from video_cartoonize.ark_client import STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED
    from video_cartoonize.vlm import verify_anime_style
    from video_cartoonize.logsetup import log_clip_event

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    cfg      = st.cfg_from_state(s)
    cfg.api_key = _resolve_key(cfg.api_key)
    clips    = st.clips_from_state(s)

    clip_id  = getattr(args, "clip_id", None)
    targets  = [cl for cl in clips if clip_id is None or cl.clip_id == clip_id]

    # ── 单 clip 模式: agent 主入口，含 verify 集成 ──────────────────
    if clip_id is not None:
        if not targets:
            _out({"status": "error", "error_type": "ClipNotFound",
                  "clip_id": clip_id})
            return 1

        clip = targets[0]

        log_clip_event(
            work_dir, clip_id, "poll.check",
            task_id=clip.task_id,
            verify_attempts=clip.verify_attempts,
            style_verified=clip.style_verified,
            status=clip.status,
            output_url=clip.output_url,
            n_cartoon_urls=len(clip.subshot_cartoon_urls),
            attempts_history=clip.attempts,
        )

        # ① 已经完成的 clip：直接报 done（含兜底/通过）
        if clip.style_verified:
            _out({"status": "done", "clip_id": clip.clip_id,
                  "video_url": clip.output_url,
                  "style_verified": True,
                  "verify_attempts": clip.verify_attempts})
            return 0
        if clip.verify_attempts >= VERIFY_MAX_ATTEMPTS and clip.output_url:
            _out({"status": "done", "clip_id": clip.clip_id,
                  "video_url": clip.output_url,
                  "style_verified": False,
                  "verify_attempts": clip.verify_attempts,
                  "note": "verify exhausted, using fallback"})
            return 0

        # ② 没 task_id → agent 顺序错了（应该先 cartoonize run --clip-id N 启动）
        if not clip.task_id:
            _out({"status": "error", "clip_id": clip.clip_id,
                  "error_type": "NoTaskId",
                  "message": "clip 还未提交 Seedance，请先 cartoonize run --clip-id N"})
            return 1

        # ③ poll Seedance
        try:
            r = poll_task(cfg.api_key, clip.task_id)
        except Exception as e:
            _out({"status": "running", "clip_id": clip.clip_id,
                  "task_id": clip.task_id, "poll_error": str(e)})
            return 1

        api_status = r.get("status", "")

        # 仍在跑
        if api_status not in (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED):
            log_clip_event(
                work_dir, clip_id, "poll.running",
                task_id=clip.task_id,
                api_status=api_status,
                created_at=r.get("created_at"),
                updated_at=r.get("updated_at"),
            )
            _out({"status": "running", "clip_id": clip.clip_id,
                  "task_id": clip.task_id, "api_status": api_status})
            return 1

        # Seedance 自己失败（API 错误，不是风格问题）
        if api_status in (STATUS_FAILED, STATUS_CANCELLED):
            err = r.get("error") or {}
            err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
            clip.status = "failed"
            with st.lock(work_dir):
                s2 = st.require(work_dir)
                st.merge_clip_fields(s2, clip.clip_id, status="failed")
                st.save(work_dir, s2)
            log_clip_event(
                work_dir, clip_id, "poll.seedance_failed",
                api_status=api_status,
                error=err_msg,
                task_id=clip.task_id,
                raw_response=r,                      # 完整 API 响应
            )
            _out({"status": "done", "clip_id": clip.clip_id,
                  "video_url": "", "seedance_status": api_status,
                  "error": err_msg, "note": "Seedance task failed (not style)"})
            return 0

        # Seedance 成功 → 拿 video_url 并记账
        video_url = (r.get("content") or {}).get("video_url", "")
        clip.output_url = video_url
        clip.status     = "success"
        from video_cartoonize import billing as _bl
        usage = r.get("usage") or {}
        # has_video_input 与 submit 时一致（submit 规则: verify_attempts < 2）
        # poll 在 verify 自增 verify_attempts 之前发生，所以这里读出的值就是提交时的值
        has_video_input = clip.verify_attempts < 2
        _bl.record(
            "seedance",
            clip_id=clip.clip_id,
            model=r.get("model", ""),
            duration_s=int(r.get("duration", 0) or 0),
            resolution=r.get("resolution", ""),
            ratio=r.get("ratio", ""),
            task_id=clip.task_id,
            has_video_input=has_video_input,
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )

        # ④ 自动 VLM 风格校验
        try:
            passed, reason = verify_anime_style(video_url, api_key=cfg.api_key,
                                                clip_id=clip.clip_id)
        except Exception as e:
            passed, reason = False, f"verify error: {e}"

        clip.verify_attempts += 1
        clip.verify_reason   = reason
        clip.attempts.append({
            "task_id":    clip.task_id,
            "output_url": video_url,
            "verdict":    "pass" if passed else "fail",
            "reason":     reason,
        })

        if passed:
            clip.style_verified = True
            with st.lock(work_dir):
                s2 = st.require(work_dir)
                st.merge_clip_fields(s2, clip.clip_id,
                                     output_url=video_url, status="success",
                                     style_verified=True,
                                     verify_attempts=clip.verify_attempts,
                                     verify_reason=reason,
                                     attempts=clip.attempts)
                st.save(work_dir, s2)
            log_clip_event(
                work_dir, clip_id, "poll.verify_pass",
                video_url=video_url,
                attempts=clip.verify_attempts,
                reason=reason,                       # 完整 reason，不截断
                task_id=clip.task_id,
                seedance_usage=usage,
                seedance_duration=r.get("duration"),
                seedance_resolution=r.get("resolution"),
                seedance_ratio=r.get("ratio"),
                seedance_model=r.get("model"),
            )
            _out({"status": "done", "clip_id": clip.clip_id,
                  "video_url": video_url,
                  "style_verified": True,
                  "verify_attempts": clip.verify_attempts,
                  "reason": reason})
            return 0

        # verify 失败
        if clip.verify_attempts < VERIFY_MAX_ATTEMPTS:
            # CLI 内部自动 resubmit Seedance，不打扰 agent
            # 第 3 次（verify_attempts==2 之后）自动切 image-only 模式
            from video_cartoonize.core import submit_clip, build_preamble, detect_ratio
            from video_cartoonize.styles import get_style

            clip_asset_urls = {int(k): v for k, v in s.get("clip_asset_urls", {}).items()}
            vid_url = clip_asset_urls.get(clip.clip_id, "")
            if not vid_url:
                # 没 video asset 完全无法重试，标兜底 done
                with st.lock(work_dir):
                    s2 = st.require(work_dir)
                    st.merge_clip_fields(s2, clip.clip_id,
                                         output_url=video_url, status="success",
                                         style_verified=False,
                                         verify_attempts=clip.verify_attempts,
                                         verify_reason=reason,
                                         attempts=clip.attempts)
                    st.save(work_dir, s2)
                _out({"status": "done", "clip_id": clip.clip_id,
                      "video_url": video_url, "style_verified": False,
                      "note": "no video asset URL for resubmit, fallback"})
                return 0

            prompts_map = {int(k): v for k, v in s.get("prompts", {}).items()}
            ratio = s["config"].get("ratio") or detect_ratio(clip.resized_path)
            cfg_dict = s["config"]
            style = get_style(cfg_dict["style_id"], user_ref_paths=cfg_dict.get("ref_images") or None)
            preamble = build_preamble(style.description)

            # ── Attempt-aware keyframe top-up (append-only, 不重画已有 cartoons) ──
            # 尝试 2 (verify_attempts==1): 3s 时间保底，补齐间隔
            # 尝试 3 (verify_attempts==2): 把关键帧总数补到 10
            regen_strategy = None
            if clip.verify_attempts == 1:
                regen_strategy = "with_floor"
            elif clip.verify_attempts == 2:
                regen_strategy = "uniform10"
            if regen_strategy:
                n_kf_before = len(clip.subshot_cartoon_paths)
                regen_err: Optional[str] = None
                try:
                    regen_ok = _regenerate_clip_for_retry(
                        clip, work_dir, s, cfg, regen_strategy,
                    )
                except Exception as e:
                    # 关键容错：Seedream / TOS / Assets / ffmpeg 任一环节抛异常
                    # 都不应该让 poll 整体崩溃；fallthrough 用已有关键帧继续提交，
                    # 等下一次 verify 失败再试。
                    regen_ok  = False
                    regen_err = f"{type(e).__name__}: {e}"
                log_clip_event(
                    work_dir, clip_id, "poll.retry_keyframe_topup",
                    attempt=clip.verify_attempts + 1,
                    strategy=regen_strategy,
                    success=regen_ok,
                    error=regen_err,
                    n_keyframes_before=n_kf_before,
                    n_keyframes_after=len(clip.subshot_cartoon_paths),
                )
                if regen_ok:
                    # 重读 state 以拿到 upload 写入的新 asset URLs（局部已同步过 clip
                    # 对象，但显式 reload 防止其他字段过期）
                    s = st.require(work_dir)

            prompt = _build_final_prompt(clip, prompts_map, preamble)
            use_ref = clip.verify_attempts < 2   # 第 3 次（attempts==2 -> use_ref=False）
            mode = "image-only" if not use_ref else "video+image"

            new_task_id = submit_clip(cfg.api_key, clip, vid_url, prompt, ratio, cfg,
                                       use_reference_video=use_ref)
            if not new_task_id:
                # resubmit 失败：当兜底 done
                with st.lock(work_dir):
                    s2 = st.require(work_dir)
                    st.merge_clip_fields(s2, clip.clip_id,
                                         output_url=video_url, status="success",
                                         style_verified=False,
                                         verify_attempts=clip.verify_attempts,
                                         verify_reason=reason,
                                         attempts=clip.attempts)
                    st.save(work_dir, s2)
                _out({"status": "done", "clip_id": clip.clip_id,
                      "video_url": video_url, "style_verified": False,
                      "note": "internal resubmit failed, fallback to last attempt"})
                return 0

            # 更新 task_id，保留旧 output_url 作兜底
            clip.task_id = new_task_id
            with st.lock(work_dir):
                s2 = st.require(work_dir)
                st.merge_clip_fields(s2, clip.clip_id,
                                     task_id=new_task_id, status="pending",
                                     output_url=video_url,  # 旧视频先留着
                                     style_verified=False,
                                     verify_attempts=clip.verify_attempts,
                                     verify_reason=reason,
                                     attempts=clip.attempts)
                st.save(work_dir, s2)
            log_clip_event(
                work_dir, clip_id, "poll.verify_fail_resubmit",
                attempts=clip.verify_attempts,
                max_attempts=VERIFY_MAX_ATTEMPTS,
                mode=mode,
                use_reference_video=use_ref,
                new_task_id=new_task_id,
                old_task_id=clip.attempts[-1].get("task_id") if clip.attempts else "",
                reason=reason,                       # 完整 reason
                video_asset=vid_url,
                n_image_assets=len(clip.subshot_cartoon_urls),
                prompt_len=len(prompt),
                prompt=prompt,                       # 完整 prompt
                ratio=ratio,
                resolution=cfg.seedance_resolution,
                seedance_model=cfg.seedance_model,
                last_failed_video_url=video_url,
            )
            _out({"status": "running", "clip_id": clip.clip_id,
                  "task_id": new_task_id, "mode": mode,
                  "verify_attempts": clip.verify_attempts,
                  "max_attempts": VERIFY_MAX_ATTEMPTS,
                  "auto_resubmitted": True,
                  "last_verify_fail_reason": reason})
            return 1
        else:
            # 用完 3 次：用兜底视频
            with st.lock(work_dir):
                s2 = st.require(work_dir)
                st.merge_clip_fields(s2, clip.clip_id,
                                     output_url=video_url, status="success",
                                     style_verified=False,
                                     verify_attempts=clip.verify_attempts,
                                     verify_reason=reason,
                                     attempts=clip.attempts)
                st.save(work_dir, s2)
            log_clip_event(
                work_dir, clip_id, "poll.fallback",
                attempts=clip.verify_attempts,
                video_url=video_url,
                reason=reason,                       # 完整 reason
                all_attempts=clip.attempts,           # 完整历次 attempts 记录
                note="verify exhausted, using last attempt as fallback",
            )
            _out({"status": "done", "clip_id": clip.clip_id,
                  "video_url": video_url,
                  "style_verified": False,
                  "verify_attempts": clip.verify_attempts,
                  "note": "verify exhausted, using last attempt as fallback",
                  "reason": reason})
            return 0

    # ── 全量模式 (无 --clip-id): 旧行为，只查不 verify ───────────────
    # 注意：billing.record 在这里也要写——0.14.5 之前只有单 clip 模式记账，
    # 全量模式的 9 个 clip 第一次 succeeded 时全漏掉了 Seedance 计费。
    from video_cartoonize import billing as _bl
    results = []
    still_running = 0
    seen_success: set = set()  # 同一次 poll 内防重复（succeeded 状态多次 poll 都是同一条 task）

    for clip in targets:
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
            # 仅在该 task_id 此前未在本进程内记过账时写入（同一 task 多次 poll
            # 不重复计费；跨进程的去重交给上游 agent 的"看到 done 就停 poll"约定）
            if clip.status != "success" and clip.task_id not in seen_success:
                seen_success.add(clip.task_id)
                usage = r.get("usage") or {}
                # has_video_input 与 submit 时一致（submit 规则: verify_attempts < 2）
                has_video_input = clip.verify_attempts < 2
                _bl.record(
                    "seedance",
                    clip_id=clip.clip_id,
                    model=r.get("model", ""),
                    duration_s=int(r.get("duration", 0) or 0),
                    resolution=r.get("resolution", ""),
                    ratio=r.get("ratio", ""),
                    task_id=clip.task_id,
                    has_video_input=has_video_input,
                    completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                    total_tokens=int(usage.get("total_tokens", 0) or 0),
                )
            clip.status = "success"
        elif api_status in (STATUS_FAILED, STATUS_CANCELLED):
            clip.status = "failed"
        else:
            still_running += 1

        results.append({"clip_id": clip.clip_id, "status": clip.status,
                         "api_status": api_status, "task_id": clip.task_id})

    # 加锁字段级合并（避免覆盖其他进程写的字段）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        for clip in targets:
            st.merge_clip_fields(s2, clip.clip_id,
                                 output_url=clip.output_url, status=clip.status)
        st.save(work_dir, s2)

    _out({"status": "ok" if still_running == 0 else "running",
          "still_running": still_running,
          "clips": results})
    return 0 if still_running == 0 else 1


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
        # 区分"没东西可干"和"全过"。caller 不应该把"empty"当成"all passed"
        _out({"status": "empty", "checked": 0, "passed": 0, "failed": 0,
              "message": "没有需要校验的 clip（status=success 且未通过校验且有 output_url 的 clip 为 0）"})
        return 0   # exit 0 但 status=empty，调用方应该检查 status 字段

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

            # 不论成败，每次校验都归档当前的 task_id + output_url
            verdict_label = "error" if err else ("pass" if passed else "fail")
            clip.attempts.append({
                "task_id":    clip.task_id,
                "output_url": clip.output_url,
                "verdict":    verdict_label,
                "reason":     reason or (err or ""),
            })

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
                # 没到上限就清空 task_id 让 submit 重提；
                # 但保留 output_url 供 mux fallback 使用（不让生成的视频丢失）
                if clip.verify_attempts < VERIFY_MAX_ATTEMPTS:
                    clip.task_id = ""
                    clip.status  = "pending"
                    # ⚠ 故意保留 clip.output_url，作为兜底视频
                results.append({"clip_id": clip.clip_id, "verdict": "fail",
                                 "reason": reason, "attempts": clip.verify_attempts,
                                 "will_retry": clip.verify_attempts < VERIFY_MAX_ATTEMPTS,
                                 "archived_url": clip.output_url})

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
    from video_cartoonize.logsetup import log_clip_event

    work_dir  = _work_dir(args)
    s         = st.require(work_dir)
    clips     = st.clips_from_state(s)
    cart_dir  = os.path.join(work_dir, "cartoonized")
    final_dir = os.path.join(work_dir, "final")
    os.makedirs(cart_dir,  exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    clip_id = getattr(args, "clip_id", None)
    targets = [c for c in clips if clip_id is None or c.clip_id == clip_id]
    if clip_id is not None and not targets:
        _out({"status": "error", "error_type": "ClipNotFound", "clip_id": clip_id})
        return 1

    results = []
    for clip in targets:
        if clip.status != "success" or not clip.output_url:
            results.append({"clip_id": clip.clip_id, "status": clip.status})
            continue
        cart_path  = os.path.join(cart_dir,  f"clip_{clip.clip_id:02d}.mp4")
        final_path = os.path.join(final_dir, f"clip_{clip.clip_id:02d}.mp4")
        try:
            download_url(clip.output_url, cart_path)
            log_clip_event(
                work_dir, clip.clip_id, "mux.download",
                video_url=clip.output_url,
                local_path=cart_path,
                file_size_bytes=os.path.getsize(cart_path) if os.path.exists(cart_path) else 0,
                resized_path=clip.resized_path,
            )
        except Exception as e:
            clip.status = "failed"
            log_clip_event(work_dir, clip.clip_id, "mux.error",
                           stage="download", error=str(e))
            results.append({"clip_id": clip.clip_id, "status": "download_failed",
                             "error": str(e)})
            continue
        ok = mux_original_audio(cart_path, clip.resized_path, final_path)
        clip.output_path = final_path if ok else cart_path
        log_clip_event(
            work_dir, clip.clip_id,
            "mux.muxed" if ok else "mux.mux_failed",
            output=clip.output_path,
            cartoonized_path=cart_path,
            resized_audio_source=clip.resized_path,
            final_size_bytes=os.path.getsize(clip.output_path) if os.path.exists(clip.output_path) else 0,
        )
        results.append({"clip_id": clip.clip_id, "status": "ok",
                         "output": clip.output_path})

    # 字段级合并：只写本次 mux 的目标 clip 的 output_path / status，避免覆盖
    # 其它 clip 在并行管线中刚写入的字段（单 clip 模式下尤其重要）
    with st.lock(work_dir):
        s2 = st.require(work_dir)
        for clip in targets:
            st.merge_clip_fields(
                s2, clip.clip_id,
                output_path=clip.output_path,
                status=clip.status,
            )
        st.save(work_dir, s2)
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

    has_ark_ak_sk = bool(os.environ.get("ARK_AK") and os.environ.get("ARK_SK")) or ARK_AK_SK_FILE.exists()
    has_tos_ak_sk = bool(os.environ.get("TOS_ACCESS_KEY") and os.environ.get("TOS_SECRET_KEY"))
    has_bucket = bool(os.environ.get("TOS_BUCKET")) or (
        TOS_CREDS_FILE.exists() and
        bool(json.loads(TOS_CREDS_FILE.read_text()).get("bucket") if TOS_CREDS_FILE.exists() else "")
    )

    checks = {
        "ffmpeg":      bool(shutil.which("ffmpeg")),
        "ffprobe":     bool(shutil.which("ffprobe")),
        "ark_api_key": bool(os.environ.get("ARK_API_KEY")) or ARK_KEY_FILE.exists(),
        "ark_ak_sk":   has_ark_ak_sk,
        "tos_ak_sk":   has_tos_ak_sk,
        "tos_bucket":  has_bucket,
    }
    _out({
        "status": "ok" if all(checks.values()) else "missing",
        "config_dir": str(CONFIG_DIR),
        "checks": checks,
        "notes": {
            "ark_ak_sk":  "ARK AK/SK 用于 ModelArk Assets API，由前端请求 Header 注入或本地配置提供",
            "tos_ak_sk":  "TOS AK/SK/Bucket 是后端部署配置项，使用 TOS_ACCESS_KEY / TOS_SECRET_KEY / TOS_BUCKET",
            "tos_endpoint": f"默认 tos-ap-southeast-1.bytepluses.com（可在 {TOS_CREDS_FILE} 中覆盖）",
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
    print(f"总成本: ${summary.get('grand_total_usd', 0):.4f} USD  "
          f"(BytePlus 官方价；可在 ~/.config/video-cartoonize/prices.json 覆盖)")
    print()
    print("Seedream (图片生成 · 按张计价 $0.035/张)")
    print(f"  调用次数:        {sd['calls']}")
    print(f"  生成图片数:      {sd['images']} 张")
    print(f"  成本:            ${sd.get('cost_usd', 0):>9.4f}")
    if sd['models']:
        print(f"  模型:            {sd['models']}")
    print()
    print("VLM (Seed 2.0 Lite · input $0.25/M + output $0.50/M)")
    print(f"  调用次数:        {v['calls']}")
    print(f"  prompt_tokens:   {v['prompt_tokens']:>10,}")
    print(f"  completion_tok:  {v['completion_tokens']:>10,}")
    print(f"  成本:            ${v.get('cost_usd', 0):>9.4f}")
    if v['models']:
        print(f"  模型:            {v['models']}")
    print()
    print("Seedance (视频生成 · 按 token，with-video / without-video 不同价)")
    print(f"  succeeded:       {dn['calls']}  (with-video={dn.get('with_video_calls', 0)}, "
          f"without-video={dn.get('without_video_calls', 0)})")
    print(f"  with-video toks: {dn.get('with_video_tokens', 0):>10,}")
    print(f"  no-video  toks:  {dn.get('without_video_tokens', 0):>10,}")
    print(f"  total_tokens:    {dn['total_tokens']:>10,}  "
          f"(≈ {dn['duration_seconds']} s 输出视频)")
    print(f"  成本:            ${dn.get('cost_usd', 0):>9.4f}")
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


def cmd_logs(args: argparse.Namespace) -> int:
    """显示指定 clip 的事件日志（来自 <work_dir>/logs/clip_NN.jsonl）。"""
    work_dir = _work_dir(args)
    clip_id  = args.clip_id
    log_path = os.path.join(work_dir, "logs", f"clip_{clip_id:02d}.jsonl")
    if not os.path.exists(log_path):
        _out({"status": "error", "error_type": "NoLog",
              "message": f"日志文件不存在: {log_path}"})
        return 1

    events = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue

    if getattr(args, "json", False):
        _out({"status": "ok", "clip_id": clip_id,
              "log_path": log_path, "events": events})
        return 0

    print(f"日志: {log_path}  ({len(events)} 个事件)")
    print("─" * 70)
    for e in events:
        ts = e.get("ts", "")
        ev = e.get("event", "?")
        extras = {k: v for k, v in e.items() if k not in ("ts", "event")}
        extras_str = " ".join(f"{k}={v}" for k, v in extras.items() if v not in (None, ""))
        print(f"{ts}  {ev:<26}  {extras_str[:160]}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    """基于现有用量预估整个项目的成本（含未完成 clip 的预期成本）。

    思路:
    - 已完成的部分：直接从 billing.jsonl 读真实 token
    - 未完成的部分：用已完成 clip 的平均值估算
      估算公式: 剩余 clip 数 × (已完成 clip 平均成本)
    """
    from video_cartoonize import state as st, billing as bl

    work_dir = _work_dir(args)
    s        = st.require(work_dir)
    summary  = bl.summarize(work_dir)
    clips    = s.get("clips", [])

    total_clips     = len(clips)
    submitted_clips = sum(1 for c in clips if c.get("task_id"))
    done_clips      = sum(1 for c in clips if c.get("status") == "success")
    by_clip         = summary.get("by_clip", {})
    completed_with_billing = len(by_clip)

    actual_usd = summary.get("grand_total_usd", 0.0)

    # 估算剩余 clip 的预期成本 = 已完成 clip 的平均 USD
    avg_per_clip_usd = 0.0
    if completed_with_billing > 0:
        # 用每个 clip 自己的 token + 价目表换算
        prices = bl.load_prices()
        # 简化：用 grand_total / completed_with_billing
        avg_per_clip_usd = actual_usd / completed_with_billing if completed_with_billing else 0.0

    remaining_clips = total_clips - completed_with_billing
    projected_remaining_usd = round(remaining_clips * avg_per_clip_usd, 4)
    projected_total_usd = round(actual_usd + projected_remaining_usd, 4)

    if getattr(args, "json", False):
        _out({
            "actual_usd":          round(actual_usd, 4),
            "projected_total_usd": projected_total_usd,
            "projected_remaining_usd": projected_remaining_usd,
            "avg_per_clip_usd":    round(avg_per_clip_usd, 4),
            "total_clips":         total_clips,
            "done_clips":          done_clips,
            "submitted_clips":     submitted_clips,
            "completed_with_billing": completed_with_billing,
        })
        return 0

    print(f"工作目录: {work_dir}")
    print(f"总 clip 数:         {total_clips}")
    print(f"已提交:             {submitted_clips}")
    print(f"已成功:             {done_clips}")
    print(f"已有 billing 记录:  {completed_with_billing}")
    print()
    print(f"已发生成本（基于真实 token）:     ${actual_usd:>9.4f} USD")
    if avg_per_clip_usd > 0:
        print(f"每个 clip 平均成本:               ${avg_per_clip_usd:>9.4f} USD")
        print(f"预计剩余成本（{remaining_clips} clip × 平均）: ${projected_remaining_usd:>9.4f} USD")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"项目总成本估算:                   ${projected_total_usd:>9.4f} USD")
    else:
        print("（尚无 billing 记录，无法估算）")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """从远端重跑 install.sh，把 cartoonize 升级到指定分支/tag。"""
    import shlex
    import subprocess

    ref   = args.ref  or os.environ.get("VIDEO_CARTOONIZE_REF",  "main")
    repo  = args.repo or os.environ.get("VIDEO_CARTOONIZE_REPO", "Carey8175/video-cartoonize")
    token = os.environ.get("GITHUB_TOKEN", "")

    url = f"https://raw.githubusercontent.com/{repo}/{ref}/install.sh"
    if token:
        curl = f"curl -fsSL -H 'Authorization: token {token}' {shlex.quote(url)}"
    else:
        curl = f"curl -fsSL {shlex.quote(url)}"

    # install.sh 自己也读这些环境变量
    env = os.environ.copy()
    env["VIDEO_CARTOONIZE_REF"]  = ref
    env["VIDEO_CARTOONIZE_REPO"] = repo

    print(f"[update] fetching {repo}@{ref}", file=sys.stderr)
    proc = subprocess.run(["bash", "-c", f"{curl} | bash"], env=env)
    if proc.returncode == 0:
        print(f"[update] ✓ done. Run: cartoonize version", file=sys.stderr)
    else:
        print(f"[update] ✗ failed (exit {proc.returncode})", file=sys.stderr)
        if not token:
            print(f"[update]   if {repo} is private, export GITHUB_TOKEN=<pat> first",
                  file=sys.stderr)
    return proc.returncode


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

# cmd_run 把它置 True 时，子命令的 _out 输出不会真打到 stdout，
# 而是被 _captured_out 收集，让 cmd_run 最后输出一个聚合 JSON。
_SUPPRESS_OUT     = False
_captured_out: List[dict] = []


def _out(data: dict) -> None:
    """输出 JSON 结果（agent 读取用）。"""
    if _SUPPRESS_OUT:
        _captured_out.append(data)
        return
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
    # 全局选项（在所有子命令前/后均可）
    root.add_argument("-v", "--verbose", action="store_true",
                      help="详细日志（DEBUG 级别，stderr）")
    root.add_argument("-q", "--quiet", action="store_true",
                      help="安静模式（WARNING 以上才输出，stderr）")
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

    # Seedance 模型选择
    p.add_argument(
        "--seedance-model", default="standard",
        help="Seedance 模型：'standard' (dreamina-seedance-2-0-260128)、"
             "'fast' (dreamina-seedance-2-0-fast-260128)、"
             "或自定义 endpoint ID。默认: standard",
    )

    # split / keyframes / merge — 全量，无 --clip-id
    for name, help_text in [
        ("split",     "Phase 1: 场景切分 + 缩放"),
        ("keyframes", "Phase 2a: 关键帧提取"),
        ("merge",     "Phase 7: 拼接最终视频"),
    ]:
        _add_work_dir(sub.add_parser(name, help=help_text))

    # identify — 人物识别（主角/配角/路人）
    p = sub.add_parser(
        "identify",
        help="Phase 2a-opt: 人物识别（InsightFace）→ 主角/配角/路人分类 + keyframe 角色映射",
    )
    _add_work_dir(p)
    p.add_argument("--fps",              type=float, default=0.5,
                   help="采样帧率（default 0.5，降低可加速但可能漏检）")
    p.add_argument("--cluster-threshold", type=float, default=0.55,
                   help="InsightFace 聚类余弦距离阈值（default 0.55，越低越严格）")
    p.add_argument("--min-det-score",    type=float, default=0.72,
                   help="人脸检测最低置信度（default 0.72，过滤侧脸/模糊帧）")
    p.add_argument("--protagonist-freq", type=float, default=0.10,
                   help="主角频率下限（default 0.10 = 出现在 ≥10%% 帧里）")
    p.add_argument("--supporting-freq",  type=float, default=0.04,
                   help="配角频率下限（default 0.04）")
    p.add_argument("--match-threshold",  type=float, default=0.50,
                   help="keyframe 角色匹配余弦距离阈值（default 0.50）")

    # char-refs — 生成角色动漫参考图
    p = sub.add_parser(
        "char-refs",
        help="Phase 2a-opt: Seedream I2I 生成主角/配角动漫参考图（需先 identify）",
    )
    _add_work_dir(p)

    # mux — 支持 --clip-id：单 clip 重 mux 不影响其它已 mux 的 clip
    p = sub.add_parser("mux", help="Phase 6: 下载 + 音轨合并")
    _add_work_dir(p)
    p.add_argument("--clip-id", type=int, default=None, metavar="N",
                   help="只 mux 指定 clip（重生成单 clip 后用）；不填则处理全部 status=success 的 clip")

    # run — ★ Agent 主入口：一站式处理单 clip（cartoon+vlm 并行 → upload → submit）
    p = sub.add_parser("run",
        help="★ Agent 主入口: 对单个 clip 一站式跑 cartoon+vlm+upload+submit，返回 task_id")
    _add_work_dir(p)
    p.add_argument("--clip-id", type=int, required=True, metavar="N",
                   help="必填: 要处理的 clip 编号")
    p.add_argument("--dry-run", action="store_true",
                   help="不实际提交 Seedance，只显示将提交的 prompt 和参数")

    # cartoon / vlm / upload / submit / verify — 单步命令，调试/手动用
    for name, help_text in [
        ("cartoon", "Phase 2b 单步: Seedream 卡通化"),
        ("vlm",     "Phase 3 单步: VLM 场景分析"),
        ("upload",  "Phase 4 单步: TOS + Assets 上传"),
        ("submit",  "Phase 5a 单步: 提交 Seedance 任务"),
        ("verify",  "Phase 5c: VLM 校验生成视频是否动漫风格"),
    ]:
        p = sub.add_parser(name, help=help_text)
        _add_work_dir(p)
        p.add_argument("--clip-id", type=int, default=None, metavar="N",
                       help="只处理指定 clip（不填则处理全部，agent 不应该用全量）")
        if name == "submit":
            p.add_argument("--dry-run", action="store_true",
                           help="只显示将提交的 prompt 和参数，不实际调用 Seedance")

    # poll
    p = sub.add_parser("poll", help="Phase 5b: 查询 Seedance 任务状态（exit 0=完成，1=仍运行中）")
    _add_work_dir(p)
    p.add_argument("--clip-id", type=int, default=None, metavar="N",
                   help="只查指定 clip（per-clip 流水线用，不填则查全部）")

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

    # update
    p = sub.add_parser("update", help="升级 cartoonize 到最新版本（远端重跑 install.sh）")
    p.add_argument("--ref",  default=None, metavar="REF",
                   help="分支/tag/commit（默认 main，或 $VIDEO_CARTOONIZE_REF）")
    p.add_argument("--repo", default=None, metavar="OWNER/NAME",
                   help="GitHub repo（默认 Carey8175/video-cartoonize，或 $VIDEO_CARTOONIZE_REPO）")

    # billing
    p = sub.add_parser("billing", help="显示项目 Seedream/VLM/Seedance 用量汇总（含 USD 成本）")
    _add_work_dir(p)
    p.add_argument("--by-clip", action="store_true", help="同时显示每个 clip 的明细")
    p.add_argument("--json", action="store_true", help="输出原始 JSON（而非格式化文本）")

    # logs
    p = sub.add_parser("logs", help="显示某 clip 的事件日志")
    _add_work_dir(p)
    p.add_argument("--clip-id", type=int, required=True, metavar="N",
                   help="要查看日志的 clip 编号")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")

    # estimate
    p = sub.add_parser("estimate", help="基于已发生的成本预估项目总成本")
    _add_work_dir(p)
    p.add_argument("--json", action="store_true", help="输出原始 JSON")

    # serve — Console API server
    p = sub.add_parser("serve", help="启动 Cartoonize Console API server")
    p.add_argument("--host",       default="127.0.0.1", help="绑定地址（默认 127.0.0.1）")
    p.add_argument("--port",       type=int, default=7317, help="端口（默认 7317）")
    p.add_argument("--work-root",  default=None, help="project work_dir 的根目录（默认 ~/cartoonize）")
    p.add_argument("--db",         default=None, metavar="DATABASE_URL", help="数据库 URL（默认 SQLite）")
    p.add_argument("--redis",      default=None, metavar="REDIS_URL",    help="Redis URL（默认 redis://localhost:6379/0）")
    p.add_argument("--no-redis",   action="store_true", help="禁用 Redis（降级为无 SSE 广播模式）")
    p.add_argument("--reload",     action="store_true", help="开发模式：文件变更自动重载")

    return root


def cmd_serve(args) -> int:
    """启动 FastAPI + Uvicorn server。"""
    import os
    # 把 CLI 参数写入环境变量，供 pydantic-settings 读取
    if args.work_root:
        os.environ["WORK_ROOT"] = args.work_root
    if args.db:
        os.environ["DATABASE_URL"] = args.db
    if args.redis:
        os.environ["REDIS_URL"] = args.redis
    if getattr(args, "no_redis", False):
        os.environ["REDIS_ENABLED"] = "false"

    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "uvicorn not installed. Run: pip install 'video-cartoonize[server]'"
        )

    uvicorn.run(
        "video_cartoonize.server.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=getattr(args, "reload", False),
        log_level="info",
    )
    return 0


def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    # logging 全局初始化（INFO 走 stderr，stdout 留给 JSON）
    from video_cartoonize.logsetup import setup_logging
    setup_logging(verbose=getattr(args, "verbose", False),
                  quiet=getattr(args, "quiet", False))

    # 设置当前项目，所有 API 调用的 billing 都写到这里
    from video_cartoonize import billing as _billing
    if hasattr(args, "work_dir") and args.work_dir:
        _billing.set_project(args.work_dir)

    dispatch = {
        "init":      cmd_init,
        "split":     cmd_split,
        "keyframes": cmd_keyframes,
        "identify":  cmd_identify,
        "char-refs": cmd_char_refs,
        "cartoon":   cmd_cartoon,
        "vlm":       cmd_vlm,
        "upload":    cmd_upload,
        "submit":    cmd_submit,
        "run":       cmd_run,
        "poll":      cmd_poll,
        "verify":    cmd_verify,
        "mux":       cmd_mux,
        "merge":     cmd_merge,
        "status":    cmd_status,
        "doctor":        cmd_doctor,
        "install-skill": cmd_install_skill,
        "version":       cmd_version,
        "update":        cmd_update,
        "billing":       cmd_billing,
        "estimate":      cmd_estimate,
        "logs":          cmd_logs,
    }

    if args.cmd == "styles":
        from video_cartoonize.styles import list_styles
        print(list_styles())
        return 0

    if args.cmd == "serve":
        return cmd_serve(args)

    fn = dispatch.get(args.cmd)
    if fn is None:
        parser.print_help()
        return 1

    # 统一捕获业务异常，让 stdout 始终是合法 JSON
    from video_cartoonize.errors import CartoonizeError
    try:
        return fn(args)
    except CartoonizeError as e:
        # 业务异常 → 错误 JSON 走 stdout（agent 能解析），日志走 stderr
        err_type = type(e).__name__
        _out({"status": "error", "error_type": err_type, "message": str(e)})
        print(f"\n❌ {err_type}: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _out({"status": "interrupted", "message": "interrupted by user"})
        return 130


if __name__ == "__main__":
    sys.exit(main())
