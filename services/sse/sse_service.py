from datetime import datetime, timezone
import json
from typing import Any

import redis.asyncio as redis

from core.config.config import REDIS_SSE_ADMIN_ORDERS_CHANNEL


def build_admin_order_event(event: str, data: dict[str, Any]) -> dict[str, Any]:
    # Canonical event envelope used by Redis Pub/Sub and SSE consumers.
    return {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


async def publish_admin_order_event(
    redis_client: redis.Redis,
    event: str,
    data: dict[str, Any],
) -> None:
    payload = build_admin_order_event(event, data)
    # Publish to shared channel consumed by SSEManager listener.
    await redis_client.publish(
        REDIS_SSE_ADMIN_ORDERS_CHANNEL,
        json.dumps(payload, default=str),
    )
