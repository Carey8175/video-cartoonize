"""BytePlus ModelArk Seedance 2.0 API client.

Replaces the old cookies-based jimeng.jianying.com client with the official
BytePlus ModelArk REST API. Authentication is via Bearer token (ARK_API_KEY).

Endpoints used:
    POST   /api/v3/contents/generations/tasks            create a task
    GET    /api/v3/contents/generations/tasks/{task_id}  retrieve a task
    GET    /api/v3/contents/generations/tasks            list tasks
    DELETE /api/v3/contents/generations/tasks/{task_id}  cancel/delete

Docs:
    https://docs.byteplus.com/en/docs/ModelArk/2291680  (Seedance 2.0)
    https://docs.byteplus.com/en/docs/ModelArk/1520757  (Create task)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterable
from urllib import error, request

from video_cartoonize.settings import ARK_KEY_FILE


LOGGER = logging.getLogger(__name__)

# --- Endpoint & model defaults --------------------------------------------------

DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_MODEL = "dreamina-seedance-2-0-260128"
FAST_MODEL = "dreamina-seedance-2-0-fast-260128"

# --- Status enums ---------------------------------------------------------------

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_RUNNING = "running"
STATUS_QUEUED = "queued"
STATUS_PENDING = "pending"

TERMINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED}


# --- API key resolution ---------------------------------------------------------

def load_api_key(api_key: str | None = None) -> str:
    """Resolve the ARK API key from explicit arg, env var, or local file.

    Lookup order:
        1. The `api_key` argument
        2. `ARK_API_KEY` environment variable
        3. `~/.config/video-cartoonize/ark_api_key.txt` (one line, no quotes)

    Raises:
        RuntimeError if no key can be found.
    """
    if api_key and api_key.strip():
        return api_key.strip()

    env_key = os.getenv("ARK_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    if ARK_KEY_FILE.exists():
        text = ARK_KEY_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text

    raise RuntimeError(
        "ARK_API_KEY not found. Provide one of:\n"
        "  - api_key= argument\n"
        "  - ARK_API_KEY environment variable\n"
        f"  - {ARK_KEY_FILE} (single line)"
    )


# --- Low-level HTTP -------------------------------------------------------------

def _request_json(
    url: str,
    *,
    method: str,
    api_key: str,
    payload: dict | None = None,
    timeout: int = 60,
    label: str = "request",
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body_bytes = (
        json.dumps(payload).encode("utf-8") if payload is not None else None
    )
    req = request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            response_body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"{label} failed [HTTP {exc.code}]: {err_body}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{label} failed: {exc}") from exc

    if not response_body:
        return {}
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        LOGGER.debug("%s returned non-JSON body: %s", label, response_body[:200])
        raise RuntimeError(
            f"{label} returned non-JSON body: {response_body[:200]}"
        ) from exc


# --- Request body builder -------------------------------------------------------

def _add_url_items(
    content: list[dict],
    urls: Iterable[str] | None,
    *,
    type_key: str,
    url_key: str,
    role: str,
) -> None:
    if not urls:
        return
    for url in urls:
        if not url:
            continue
        content.append({
            "type": type_key,
            url_key: {"url": url},
            "role": role,
        })


def build_content(
    prompt: str,
    image_urls: Iterable[str] | None = None,
    video_urls: Iterable[str] | None = None,
    audio_urls: Iterable[str] | None = None,
) -> list[dict]:
    """Construct the `content` array for the create-task request body."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    _add_url_items(
        content, image_urls,
        type_key="image_url", url_key="image_url", role="reference_image",
    )
    _add_url_items(
        content, video_urls,
        type_key="video_url", url_key="video_url", role="reference_video",
    )
    _add_url_items(
        content, audio_urls,
        type_key="audio_url", url_key="audio_url", role="reference_audio",
    )
    return content


# --- Public API -----------------------------------------------------------------

def create_task(
    *,
    api_key: str,
    prompt: str,
    image_urls: Iterable[str] | None = None,
    video_urls: Iterable[str] | None = None,
    audio_urls: Iterable[str] | None = None,
    model: str = DEFAULT_MODEL,
    ratio: str = "16:9",
    duration: int = 5,
    resolution: str = "720p",
    generate_audio: bool = False,
    watermark: bool = False,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Submit a video generation task.

    Returns the raw API response; the task id is in the `id` field.
    """
    payload = {
        "model": model,
        "content": build_content(prompt, image_urls, video_urls, audio_urls),
        "ratio": ratio,
        "duration": duration,
        "resolution": resolution,
        "generate_audio": generate_audio,
        "watermark": watermark,
    }
    return _request_json(
        f"{base_url}/contents/generations/tasks",
        method="POST",
        api_key=api_key,
        payload=payload,
        label="create_task",
    )


def get_task(
    *,
    api_key: str,
    task_id: str,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Retrieve task status. Returns the full task object."""
    return _request_json(
        f"{base_url}/contents/generations/tasks/{task_id}",
        method="GET",
        api_key=api_key,
        label="get_task",
    )


def list_tasks(
    *,
    api_key: str,
    page_num: int = 1,
    page_size: int = 10,
    status: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """List tasks. `status` filters by terminal/non-terminal state."""
    qs = f"page_num={page_num}&page_size={page_size}"
    if status:
        qs += f"&filter.status={status}"
    return _request_json(
        f"{base_url}/contents/generations/tasks?{qs}",
        method="GET",
        api_key=api_key,
        label="list_tasks",
    )


def cancel_task(
    *,
    api_key: str,
    task_id: str,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Cancel or delete a task."""
    return _request_json(
        f"{base_url}/contents/generations/tasks/{task_id}",
        method="DELETE",
        api_key=api_key,
        label="cancel_task",
    )


def extract_task_id(submission: dict[str, Any]) -> str | None:
    """Extract the task id from a create_task response."""
    return submission.get("id") or submission.get("task_id")
