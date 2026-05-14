"""统一异常类型。所有业务错误都继承自 CartoonizeError。"""
from __future__ import annotations


class CartoonizeError(Exception):
    """所有本包业务异常的基类。"""


class CredentialError(CartoonizeError):
    """凭证缺失或无效（ARK key / AK-SK / TOS bucket）。"""


class StateError(CartoonizeError):
    """state.json 缺失、损坏或版本不兼容。"""


class APIError(CartoonizeError):
    """上游 API 错误（Seedance / Seedream / VLM / Assets）。"""

    def __init__(self, message: str, *, service: str = "", status: int | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.service   = service
        self.status    = status
        self.retryable = retryable


class FFmpegError(CartoonizeError):
    """ffmpeg / ffprobe 执行失败或超时。"""


class AssetUploadError(CartoonizeError):
    """TOS 上传或 Assets API 注册失败。"""
