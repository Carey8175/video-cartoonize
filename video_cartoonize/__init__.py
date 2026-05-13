"""video-cartoonize — real-video → anime/cartoon pipeline."""
import ssl as _ssl

# ── 让 urllib 使用系统/Keychain 中的证书 ─────────────────────────────────────────
# Python 3.13 + OpenSSL 3 默认严格校验，公司内网的 MITM 根证书常被拒绝
# （"Basic Constraints of CA cert not marked critical"）。
# truststore 让 Python 直接用 macOS Keychain / Windows CertStore / Linux 系统 CA，
# IT 推送的公司根证书自然就能用。
#
# 优先级:
#   1. truststore  → 系统证书库（首选，能处理公司 MITM）
#   2. certifi     → Mozilla CA bundle（公网常规 HTTPS）
#   3. 系统默认    → 兜底
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    try:
        import certifi
        _orig_default = _ssl.create_default_context

        def _ctx_with_certifi(*args, **kwargs):
            kwargs.setdefault("cafile", certifi.where())
            return _orig_default(*args, **kwargs)

        _ssl._create_default_https_context = _ctx_with_certifi
    except ImportError:
        pass
