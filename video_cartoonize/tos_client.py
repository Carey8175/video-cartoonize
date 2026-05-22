"""BytePlus TOS upload helper used by the single-step CLI."""
from __future__ import annotations

import datetime as _dt
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any

import tos

from video_cartoonize.settings import TOS_CREDS_FILE

# TOS 默认值（BytePlus 国际站，ap-southeast-1）
_DEFAULT_ENDPOINT = "tos-ap-southeast-1.bytepluses.com"
_DEFAULT_REGION   = "ap-southeast-1"


def load_credentials() -> dict[str, Any]:
    """加载 TOS 凭证。

    优先级（由高到低）：
      1. 环境变量 TOS_ACCESS_KEY / TOS_SECRET_KEY / TOS_ENDPOINT / TOS_REGION / TOS_BUCKET
      2. tos_credentials.json
      3. endpoint / region 使用内置默认值
    """
    # 读 tos_credentials.json（可只含 bucket）
    creds: dict[str, Any] = {}
    if TOS_CREDS_FILE.exists():
        creds.update(json.loads(TOS_CREDS_FILE.read_text(encoding="utf-8")))

    # 环境变量覆盖
    env_map = {
        "access_key": "TOS_ACCESS_KEY",
        "secret_key": "TOS_SECRET_KEY",
        "endpoint":   "TOS_ENDPOINT",
        "region":     "TOS_REGION",
        "bucket":     "TOS_BUCKET",
    }
    for field, env_name in env_map.items():
        if os.environ.get(env_name):
            creds[field] = os.environ[env_name]

    # endpoint / region 使用默认值
    creds.setdefault("endpoint", _DEFAULT_ENDPOINT)
    creds.setdefault("region",   _DEFAULT_REGION)

    # 只有 bucket 是真正必填的
    missing = [k for k in ("access_key", "secret_key", "bucket") if not creds.get(k)]
    if missing:
        raise RuntimeError(
            "缺少 TOS 凭证: " + ", ".join(missing) + "\n"
            f"请在 {TOS_CREDS_FILE} 中填写 access_key / secret_key / bucket。\n"
            "或设置环境变量 TOS_ACCESS_KEY / TOS_SECRET_KEY / TOS_BUCKET。"
        )
    return creds


def build_object_key(file_path: Path, override: str | None = None) -> str:
    if override:
        return override
    today = _dt.date.today().strftime("%Y/%m/%d")
    suffix = uuid.uuid4().hex[:8]
    return f"uploads/{today}/{suffix}_{file_path.name}"


def upload_file(
    file_path: str,
    *,
    key: str | None = None,
    bucket: str | None = None,
    expires: int = 86400,
    public: bool = False,
    content_type: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))

    creds = load_credentials()
    bucket_name = bucket or creds["bucket"]
    object_key = build_object_key(path, key)
    mime = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    client = tos.TosClientV2(
        ak=creds["access_key"],
        sk=creds["secret_key"],
        endpoint=creds["endpoint"],
        region=creds["region"],
    )
    client.upload_file(
        bucket=bucket_name,
        key=object_key,
        file_path=str(path),
        task_num=4,
        enable_checkpoint=True,
        content_type=mime,
    )

    if public:
        url = f"https://{bucket_name}.{creds['endpoint']}/{object_key}"
        expires_at = None
    else:
        signed = client.pre_signed_url(
            http_method=tos.HttpMethodType.Http_Method_Get,
            bucket=bucket_name,
            key=object_key,
            expires=expires,
        )
        url = signed.signed_url
        expires_at = (
            _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=expires)
        ).isoformat()

    return {
        "bucket": bucket_name,
        "key": object_key,
        "url": url,
        "expires_at": expires_at,
        "size_bytes": path.stat().st_size,
        "content_type": mime,
    }
