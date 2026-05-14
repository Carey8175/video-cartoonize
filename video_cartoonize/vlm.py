"""Seed 2.0 Lite video analysis helper."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

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

    return data["choices"][0]["message"]["content"]


def analyse_clip(
    clip_path: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    fps: float = 4,
    lang: str = "en",
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
    )


# ── 风格校验 ─────────────────────────────────────────────────────────────────

_VERIFY_SYSTEM = (
    "You are a strict visual style classifier. "
    "Look at the video and decide whether it is rendered in an animated / "
    "cartoon / anime / manga / manhwa / manhua / Pixar-3D / illustration style "
    "(i.e. clearly NOT real-life live-action footage)."
)

_VERIFY_USER = (
    "Answer in this exact format, nothing else:\n"
    "LINE 1: 'YES' if the video is unambiguously animated/cartoon/anime style, "
    "else 'NO' if it still looks like real-life footage, photorealistic CGI, "
    "or mixed (real face + cartoon background, etc.).\n"
    "LINE 2: one short sentence explaining the call.\n"
    "Be strict: any real-person face = NO."
)


def verify_anime_style(
    clip_path_or_url: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    fps: float = 2,
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
    ).strip()

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    verdict = (lines[0] if lines else "").upper()
    reason  = lines[1] if len(lines) > 1 else raw[:200]
    passed = verdict.startswith("YES")
    return passed, reason
