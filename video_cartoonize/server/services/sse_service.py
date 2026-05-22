"""SSE Service — Redis Pub/Sub → Server-Sent Events。

每个 project 对应一个 Redis channel，所有订阅了该 project 的 SSE 连接
都会收到同一份事件（跨进程、跨 worker 都能广播）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds


def _channel(project_id: str) -> str:
    return f"cartoonize:events:{project_id}"


async def publish(redis, project_id: str, payload: dict[str, Any]) -> None:
    """向 project channel 发布一条事件。"""
    try:
        await redis.publish(_channel(project_id), json.dumps(payload, default=str))
    except Exception:
        logger.exception("Failed to publish SSE event for project %s", project_id)


async def subscribe(redis, project_id: str) -> AsyncIterator[str]:
    """订阅 project channel，yield SSE 格式字符串（含 heartbeat）。

    调用方直接 `async for chunk in subscribe(...): yield chunk`。
    """
    channel = _channel(project_id)
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(channel)

        heartbeat_task = asyncio.create_task(_heartbeat_loop(project_id))

        while True:
            try:
                # 非阻塞读，timeout 后继续循环（heartbeat 由独立 task 发）
                msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
            except asyncio.TimeoutError:
                # yield heartbeat
                yield f"event: heartbeat\ndata: {{}}\n\n"
                continue
            except asyncio.CancelledError:
                break

            if msg and msg["type"] == "message":
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    payload = json.loads(data)
                    event_type = payload.get("type", "message")
                    event_data = json.dumps(payload.get("data", payload))
                    yield f"event: {event_type}\ndata: {event_data}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {data}\n\n"

    finally:
        heartbeat_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def _heartbeat_loop(project_id: str) -> None:
    """每 30s 发一次 heartbeat，防 nginx 超时断连（仅占位，实际 heartbeat 在 subscribe yield）。"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
