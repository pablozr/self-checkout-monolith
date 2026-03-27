import hashlib
import json
from typing import Any

from core.config.config import CHECKOUT_IDEMPOTENCY_TTL_SECONDS, REDIS_IDEMPOTENCY_PREFIX
from services.cache import cache_service


def build_checkout_idempotency_key(idempotency_key: str, session_token: str) -> str:
    return f"{REDIS_IDEMPOTENCY_PREFIX}:{session_token}:{idempotency_key}"


def build_request_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def save_payload(redis_client, redis_key: str, payload: dict[str, Any]) -> None:
    await cache_service.set_by_key(
        redis_key,
        CHECKOUT_IDEMPOTENCY_TTL_SECONDS,
        payload,
        redis_client,
    )


def build_replay_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("serviceResponse")
    if isinstance(response, dict):
        return response

    return {
        "status": True,
        "message": "Idempotency key already processed",
        "data": {"idempotency": payload},
    }
