"""Shared package paths and credential helpers."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "video-cartoonize"
CONFIG_DIR = Path(os.environ.get("VIDEO_CARTOONIZE_CONFIG_DIR", "~/.config/video-cartoonize")).expanduser()
ARK_KEY_FILE = CONFIG_DIR / "ark_api_key.txt"
ARK_AK_SK_FILE = CONFIG_DIR / "ark_ak_sk.json"
TOS_CREDS_FILE = CONFIG_DIR / "tos_credentials.json"


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR
