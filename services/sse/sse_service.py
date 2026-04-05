from datetime import datetime, timezone
import json
from typing import Any

import redis.asyncio as redis

from core.config.config import REDIS_SSE_ADMIN_ORDERS_CHANNEL


async def publish_admin_order_event(
    redis_client: redis.Redis,
    event: str,
    data: dict[str, Any],
) -> None:
    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }

    # Publish to shared channel consumed by SSEManager listener.
    await redis_client.publish(
        REDIS_SSE_ADMIN_ORDERS_CHANNEL,
        json.dumps(payload, default=str),
    )
