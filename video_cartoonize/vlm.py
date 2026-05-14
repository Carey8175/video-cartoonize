"""Seed 2.0 Lite video analysis helper."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from video_cartoonize import billing
from video_cartoonize.ark_client import load_api_key
from video_cartoonize.tos_client import upload_file
from video_cartoonize.vlm_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

ARK_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_MODEL = "seed-2-0-lite-260228"


def _is_public_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def _call_seed_video(
    *,
    video_url: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    fps: float = 4,
    max_tokens: int = 4096,
    clip_id: int | None = None,
    purpose: str = "analyse",
) -> str:
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": video_url, "fps": fps}},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{ARK_BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Seed API HTTP {exc.code}: {body}") from exc

    # 记账：从 usage 字段提取 token
    usage = (data.get("usage") or {})
    billing.record(
        "vlm",
        clip_id=clip_id,
        model=model,
        purpose=purpose,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        total_tokens=int(usage.get("total_tokens", 0) or 0),
    )

    return data["choices"][0]["message"]["content"]


def analyse_clip(
    clip_path: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    fps: float = 4,
    lang: str = "en",
    clip_id: int | None = None,
) -> str:
    """Analyse one clip and return a per-beat timeline prompt."""
    resolved_key = load_api_key(api_key)
    if _is_public_url(clip_path):
        video_url = clip_path
    else:
        video_url = upload_file(clip_path, expires=86400)["url"]

    user_prompt = USER_PROMPT_TEMPLATE
    if lang == "zh":
        user_prompt += (
            "\n\nIMPORTANT: Write all output sections in Chinese, except the "
            "CLIP PROMPT which must stay in English."
        )

    return _call_seed_video(
        video_url=video_url,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        api_key=resolved_key,
        model=model,
        fps=fps,
        clip_id=clip_id,
        purpose="analyse",
    )


# ── 风格校验 ─────────────────────────────────────────────────────────────────

_VERIFY_SYSTEM = (
    "You are a strict visual style classifier."
)

_VERIFY_USER = (
    "Look at the video. Decide if it is rendered in an animated / cartoon / "
    "anime / manga / manhwa / manhua / Pixar-3D / hand-drawn illustration style "
    "(NOT real-life live-action footage or photorealistic CGI).\n\n"
    "Output format — STRICT:\n"
    "- The very first word of your response must be exactly YES or NO (uppercase, "
    "no quotes, no prefix like 'LINE 1:', no markdown).\n"
    "- After YES/NO, a newline, then one short sentence reason.\n"
    "- Nothing else.\n\n"
    "Rule: YES only if the ENTIRE video is unambiguously animated/cartoon. "
    "Any real-person face, photoreal skin/hair, or real-world textures = NO."
)


def _parse_verify(raw: str) -> tuple[bool, str]:
    """从 VLM 响应里抽出 YES/NO + 理由，鲁棒处理各种格式。"""
    import re

    # 去掉 markdown 包裹 / 引号 / "LINE X:" 前缀
    cleaned = []
    for ln in raw.splitlines():
        ln = ln.strip().strip("*").strip("`").strip('"').strip("'")
        ln = re.sub(r"^(line\s*\d+\s*[:.\-]|\d+\.\s*|verdict\s*[:.\-])\s*",
                    "", ln, flags=re.IGNORECASE).strip()
        if ln:
            cleaned.append(ln)

    flat = " ".join(cleaned).upper()
    # 在第一行或整体里搜 YES / NO 单词
    has_yes = bool(re.search(r"\bYES\b", flat))
    has_no  = bool(re.search(r"\bNO\b",  flat))

    # YES 和 NO 都出现时，取首个出现的（通常 verdict 在前）
    if has_yes and has_no:
        idx_yes = flat.find("YES")
        idx_no  = flat.find("NO")
        passed = idx_yes < idx_no
    elif has_yes:
        passed = True
    elif has_no:
        passed = False
    else:
        # 兜底语义关键词
        animated_kw = ("ANIME", "CARTOON", "ANIMATED", "ILLUSTRAT", "MANHWA",
                       "MANGA", "MANHUA", "PIXAR")
        real_kw     = ("REAL-LIFE", "LIVE-ACTION", "PHOTOREAL", "REAL PERSON",
                       "REAL FACE")
        passed = (any(k in flat for k in animated_kw)
                  and not any(k in flat for k in real_kw))

    # 找一行最像"理由"的（既不是单独 YES/NO，也不是空）
    reason = ""
    for ln in cleaned:
        if ln.upper() not in ("YES", "NO") and len(ln) > 3:
            reason = ln
            break
    if not reason and cleaned:
        reason = cleaned[-1]
    return passed, reason[:300]


def verify_anime_style(
    clip_path_or_url: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    fps: float = 2,
    clip_id: int | None = None,
) -> tuple[bool, str]:
    """让 VLM 判断视频是不是动漫/卡通风格。

    Returns (passed, reason)。passed=True 表示通过校验。
    """
    resolved_key = load_api_key(api_key)
    if _is_public_url(clip_path_or_url):
        video_url = clip_path_or_url
    else:
        video_url = upload_file(clip_path_or_url, expires=86400)["url"]

    raw = _call_seed_video(
        video_url=video_url,
        system_prompt=_VERIFY_SYSTEM,
        user_prompt=_VERIFY_USER,
        api_key=resolved_key,
        model=model,
        fps=fps,
        max_tokens=256,
        clip_id=clip_id,
        purpose="verify",
    )
    return _parse_verify(raw)
