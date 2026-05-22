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
    """校验用户输入的 ARK API key；key 不持久化。"""
    ark_result = await _verify_ark(req.ark_api_key)
    return CredentialVerifyResponse(ark=ark_result)


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
