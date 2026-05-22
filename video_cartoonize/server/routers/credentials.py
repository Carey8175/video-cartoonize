"""POST /api/credentials/verify"""
from __future__ import annotations

import httpx
from fastapi import APIRouter

from video_cartoonize.server.schemas.job import (
    CredentialResult,
    CredentialVerifyRequest,
    CredentialVerifyResponse,
)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

ARK_VERIFY_URL = "https://ark.ap-southeast-1.bytepluses.com/api/v3/models"


@router.post("/verify", response_model=CredentialVerifyResponse)
async def verify_credentials(req: CredentialVerifyRequest):
    """校验 ARK API key（必填）和 TOS AK/SK（可选）。

    HTTP 始终返回 200；有效性在 response body 字段里区分。
    key 不持久化，仅在本次请求内存中使用。
    """
    # ── ARK API key ───────────────────────────────────────────────────────────
    ark_result = await _verify_ark(req.ark_api_key)

    # ── TOS AK/SK（可选）────────────────────────────────────────────────────
    tos_result = None
    if req.tos_ak and req.tos_sk:
        tos_result = await _verify_tos(req.tos_ak, req.tos_sk)

    return CredentialVerifyResponse(ark=ark_result, tos=tos_result)


async def _verify_ark(api_key: str) -> CredentialResult:
    """调 ARK /models 端点，只检查 HTTP 状态码。"""
    if not api_key:
        return CredentialResult(valid=False, error="ARK API key is empty")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                ARK_VERIFY_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            return CredentialResult(valid=True)
        return CredentialResult(valid=False, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        return CredentialResult(valid=False, error=str(e))


async def _verify_tos(ak: str, sk: str) -> CredentialResult:
    """用 TOS SDK 做一次轻量 list_objects 检查权限。"""
    try:
        import tos  # type: ignore

        client = tos.TosClientV2(
            ak=ak, sk=sk,
            endpoint="tos-ap-southeast-1.bytepluses.com",
            region="ap-southeast-1",
        )
        # 只列 1 个对象，不关心结果，只关心是否 403
        bucket = "cartoonize-assets"  # 可通过 settings 配置
        client.list_objects_type2(bucket, max_keys=1)
        return CredentialResult(valid=True)
    except Exception as e:
        err = str(e)
        # TOS SDK 对 403 会抛包含 "InvalidAccessKeyId" 等字样的异常
        return CredentialResult(valid=False, error=err[:300])
