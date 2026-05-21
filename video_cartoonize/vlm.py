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
    "You are a strict visual style classifier. "
    "You always reply with a single valid JSON object and nothing else."
)

_VERIFY_USER = (
    "Look at the video and decide if its visual style is fully animated "
    "(anime / cartoon / manga / manhwa / manhua / Pixar-3D / hand-drawn "
    "illustration). Real-life live-action footage, photorealistic CGI, or "
    "any real-person face/skin/hair must be classified as NOT animated.\n\n"
    "Reply with a single JSON object on one line, exactly this schema:\n"
    '{"is_anime": true|false, "reason": "one short sentence"}\n\n'
    "Strict rules:\n"
    "- Output ONLY the JSON object. No markdown fences, no preamble, no "
    "trailing text, no 'LINE 1:' prefix.\n"
    "- is_anime must be a JSON boolean (true / false), not a string.\n"
    "- reason is a short English sentence (≤ 25 words)."
)


def _parse_verify(raw: str) -> tuple[bool, str]:
    """解析 VLM 返回的 JSON {is_anime, reason}，带兜底。"""
    import re

    text = raw.strip()

    # 1) 直接 json.loads
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "is_anime" in obj:
            return bool(obj["is_anime"]), str(obj.get("reason", ""))[:300]
    except Exception:
        pass

    # 2) 抽出第一个 {...} 再 loads（应对模型加了 ```json 围栏或前后多余字符）
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "is_anime" in obj:
                return bool(obj["is_anime"]), str(obj.get("reason", ""))[:300]
        except Exception:
            pass

    # 3) 兜底：在文本里找 true/false 或 anime/real-life 关键词
    flat = text.lower()
    if "\"is_anime\"" in flat and "true" in flat.split("is_anime", 1)[1][:30]:
        return True, text[:300]
    if "\"is_anime\"" in flat and "false" in flat.split("is_anime", 1)[1][:30]:
        return False, text[:300]

    animated_kw = ("anime", "cartoon", "animated", "illustrat", "manhwa",
                   "manga", "manhua", "pixar")
    real_kw     = ("real-life", "live-action", "photoreal", "real person", "real face")
    passed = (any(k in flat for k in animated_kw)
              and not any(k in flat for k in real_kw))
    return passed, text[:300]


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
