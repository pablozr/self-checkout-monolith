import hashlib
import json
from decimal import Decimal
from typing import Any

from core.config.config import CHECKOUT_IDEMPOTENCY_TTL_SECONDS, REDIS_IDEMPOTENCY_PREFIX
from schemas.checkout import CheckoutContextData
from services.cache import cache_service


def build_checkout_idempotency_key(idempotency_key: str, session_token: str) -> str:
    return f"{REDIS_IDEMPOTENCY_PREFIX}:{session_token}:{idempotency_key}"


def _serialize_hash_payload(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")

    if isinstance(value, dict):
        return {key: _serialize_hash_payload(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_serialize_hash_payload(item) for item in value]

    return value


def build_request_hash(payload: CheckoutContextData) -> str:
    serialized_payload = _serialize_hash_payload(payload)
    serialized = json.dumps(serialized_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _error_response(message: str) -> dict[str, Any]:
    return {"status": False, "message": message, "data": {}}


def _resolve_replay_response(
    payload: dict[str, Any] | bool,
    request_hash: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    existing_hash = payload.get("requestHash")
    if existing_hash and existing_hash != request_hash:
        return _error_response("Idempotency key already used with a different payload")

    return build_replay_response(payload)


async def initialize_checkout_request(
    redis_client,
    checkout_context: CheckoutContextData,
    idempotency_key: str,
) -> tuple[str, str, dict[str, Any] | None]:
    request_hash = build_request_hash(checkout_context)
    redis_key = build_checkout_idempotency_key(
        idempotency_key,
        checkout_context["sessionToken"],
    )

    existing_response_raw = await cache_service.get_by_key(redis_key, redis_client)
    replay_response = _resolve_replay_response(existing_response_raw, request_hash)
    if replay_response is not None:
        return redis_key, request_hash, replay_response

    processing_payload = {
        "key": idempotency_key,
        "state": "processing",
        "requestHash": request_hash,
    }

    created = await redis_client.set(
        redis_key,
        json.dumps(processing_payload),
        ex=CHECKOUT_IDEMPOTENCY_TTL_SECONDS,
        nx=True,
    )

    if created:
        return redis_key, request_hash, None

    concurrent_response_raw = await cache_service.get_by_key(redis_key, redis_client)
    replay_response = _resolve_replay_response(concurrent_response_raw, request_hash)
    if replay_response is not None:
        return redis_key, request_hash, replay_response

    return (
        redis_key,
        request_hash,
        _error_response("Checkout request already in progress"),
    )


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
