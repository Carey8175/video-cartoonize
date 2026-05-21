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

# 0.14.6+: 三维校验
#   characters_anime — 主体角色（人脸/身体/服装）是否为动漫风格
#   backgrounds_anime — 背景元素（墙、地板、家具、道具、天空、植物）是否为动漫风格
#   has_live_action — 是否存在任何真人/真实照片质感残留
# 全部要 characters_anime=true AND backgrounds_anime=true AND has_live_action=false 才算 pass。
# is_anime 字段保留作为汇总（向后兼容旧调用方），等价于三轴的逻辑 AND。
_VERIFY_USER = (
    "Look at the video and analyze its visual style across three independent axes. "
    "Fully animated means anime / cartoon / manga / manhwa / manhua / Pixar-3D / "
    "hand-drawn illustration with no photorealistic textures.\n\n"
    "Reply with a single JSON object on one line, EXACTLY this schema:\n"
    '{"characters_anime": true|false, '
    '"backgrounds_anime": true|false, '
    '"has_live_action": true|false, '
    '"is_anime": true|false, '
    '"reason": "one short sentence explaining the verdict"}\n\n'
    "Axis definitions:\n"
    "- characters_anime: every main human character (face, skin, hair, clothing) "
    "is rendered in cartoon style; no photorealistic skin texture, no real human "
    "facial features.\n"
    "- backgrounds_anime: every background element (walls, floor, ceiling, "
    "furniture, posters, props, sky, foliage, vehicles, ambient elements) is "
    "rendered in cartoon style; no photorealistic textures, no real-world "
    "photographic appearance.\n"
    "- has_live_action: any region of any frame contains live-action footage, "
    "real-person faces, photorealistic skin/hair, or unconverted real-world "
    "textures bleeding through.\n"
    "- is_anime: SET TO TRUE ONLY IF characters_anime=true AND backgrounds_anime=true "
    "AND has_live_action=false. Otherwise false.\n\n"
    "Strict rules:\n"
    "- Output ONLY the JSON object. No markdown fences, no preamble, no "
    "trailing text, no 'LINE 1:' prefix.\n"
    "- All boolean fields must be JSON booleans (true / false), not strings.\n"
    "- reason ≤ 30 words; if is_anime=false, name WHICH axis failed and where."
)


def _parse_verify(raw: str) -> tuple[bool, str]:
    """解析 VLM 返回的 JSON。

    0.14.6+ schema: {characters_anime, backgrounds_anime, has_live_action,
                     is_anime, reason}
    向后兼容旧 schema: {is_anime, reason}

    Returns (passed, reason)。passed=True 仅当三轴都达标（或旧 schema 的 is_anime=true）。
    """
    import re

    text = raw.strip()

    def _evaluate(obj: dict) -> tuple[bool, str] | None:
        """从解析出的 dict 里抽 verdict + reason。返回 None 表示 schema 不符。"""
        reason = str(obj.get("reason", ""))[:300]
        # 新 schema：三轴 + is_anime 汇总
        if "characters_anime" in obj and "backgrounds_anime" in obj:
            chars = bool(obj.get("characters_anime"))
            bgs   = bool(obj.get("backgrounds_anime"))
            live  = bool(obj.get("has_live_action", False))
            summary = bool(obj.get("is_anime", chars and bgs and not live))
            passed  = chars and bgs and (not live) and summary
            # 失败时把哪一轴失败追加进 reason，方便 retry 决策
            if not passed and reason:
                tags = []
                if not chars: tags.append("characters_not_anime")
                if not bgs:   tags.append("background_not_anime")
                if live:      tags.append("has_live_action")
                if tags:
                    reason = f"[{'/'.join(tags)}] {reason}"
                # else: 模型三轴都通过但 is_anime=false（自相矛盾），
                # 不加 tag prefix；以 summary 为准失败掉
            return passed, reason
        # 旧 schema：仅 is_anime
        if "is_anime" in obj:
            return bool(obj["is_anime"]), reason
        return None

    # 1) 直接 json.loads
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            res = _evaluate(obj)
            if res is not None:
                return res
    except Exception:
        pass

    # 2) 抽出第一个 {...} 再 loads（应对模型加了 ```json 围栏或前后多余字符）
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                res = _evaluate(obj)
                if res is not None:
                    return res
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
    real_kw     = ("real-life", "live-action", "photoreal", "real person",
                   "real face", "real background")
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
