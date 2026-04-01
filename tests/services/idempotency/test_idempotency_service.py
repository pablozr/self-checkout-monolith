import asyncio
from decimal import Decimal

import pytest

from core.config.config import CHECKOUT_IDEMPOTENCY_TTL_SECONDS
from schemas.checkout import CheckoutContextData
from services.idempotency import idempotency_service


class FakeRedis:
    def __init__(self, set_result):
        self.set_result = set_result
        self.set_calls = []

    async def set(self, key, value, ex=None, nx=None):
        self.set_calls.append(
            {
                "key": key,
                "value": value,
                "ex": ex,
                "nx": nx,
            }
        )
        return self.set_result


class FakeConcurrentRedis:
    def __init__(self):
        self.store = {}
        self.lock = asyncio.Lock()

    async def set(self, key, value, ex=None, nx=None):
        async with self.lock:
            if nx and key in self.store:
                return False

            self.store[key] = value
            return True


def build_checkout_context(total: str = "12.50") -> CheckoutContextData:
    decimal_total = Decimal(total)
    return {
        "sessionToken": "session-123",
        "tableId": 10,
        "items": [
            {
                "productId": 1,
                "name": "Burger",
                "quantity": 1,
                "unitPrice": decimal_total,
                "lineTotal": decimal_total,
            }
        ],
        "subtotal": decimal_total,
        "total": decimal_total,
    }


@pytest.mark.asyncio
async def test_initialize_checkout_request_replays_when_same_hash_with_service_response(monkeypatch):
    checkout_context = build_checkout_context()
    expected_hash = idempotency_service.build_request_hash(checkout_context)
    service_response = {"status": True, "message": "already-processed", "data": {"checkout": 1}}

    async def fake_get_by_key(_key, _redis_client):
        return {
            "state": "completed",
            "requestHash": expected_hash,
            "serviceResponse": service_response,
        }

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    redis = FakeRedis(set_result=True)
    redis_key, request_hash, replay = await idempotency_service.initialize_checkout_request(
        redis,
        checkout_context,
        "idem-1",
    )

    assert redis_key.endswith(":session-123:idem-1")
    assert request_hash == expected_hash
    assert replay == service_response
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_initialize_checkout_request_errors_when_same_key_has_different_hash(monkeypatch):
    checkout_context = build_checkout_context()

    async def fake_get_by_key(_key, _redis_client):
        return {
            "state": "completed",
            "requestHash": "different-hash",
            "serviceResponse": {"status": True, "message": "old", "data": {}},
        }

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    redis = FakeRedis(set_result=True)
    _, _, replay = await idempotency_service.initialize_checkout_request(
        redis,
        checkout_context,
        "idem-2",
    )

    assert replay == {
        "status": False,
        "message": "Idempotency key already used with a different payload",
        "data": {},
    }
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_initialize_checkout_request_returns_new_request_when_lock_created(monkeypatch):
    checkout_context = build_checkout_context()

    async def fake_get_by_key(_key, _redis_client):
        return False

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    redis = FakeRedis(set_result=True)
    redis_key, request_hash, replay = await idempotency_service.initialize_checkout_request(
        redis,
        checkout_context,
        "idem-3",
    )

    assert redis_key.endswith(":session-123:idem-3")
    assert request_hash == idempotency_service.build_request_hash(checkout_context)
    assert replay is None
    assert len(redis.set_calls) == 1
    assert redis.set_calls[0]["key"] == redis_key
    assert redis.set_calls[0]["ex"] == CHECKOUT_IDEMPOTENCY_TTL_SECONDS
    assert redis.set_calls[0]["nx"] is True


@pytest.mark.asyncio
async def test_initialize_checkout_request_errors_when_lock_exists_without_reusable_payload(monkeypatch):
    checkout_context = build_checkout_context()
    cache_reads = [False, False]

    async def fake_get_by_key(_key, _redis_client):
        return cache_reads.pop(0)

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    redis = FakeRedis(set_result=False)
    _, _, replay = await idempotency_service.initialize_checkout_request(
        redis,
        checkout_context,
        "idem-4",
    )

    assert replay == {
        "status": False,
        "message": "Checkout request already in progress",
        "data": {},
    }
    assert len(redis.set_calls) == 1
    assert cache_reads == []


@pytest.mark.asyncio
async def test_initialize_checkout_request_returns_in_progress_for_concurrent_duplicate(monkeypatch):
    checkout_context = build_checkout_context()
    redis = FakeConcurrentRedis()

    async def fake_get_by_key(key, _redis_client):
        payload = redis.store.get(key)
        if payload is None:
            return False
        return idempotency_service.json.loads(payload)

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    first, second = await asyncio.gather(
        idempotency_service.initialize_checkout_request(redis, checkout_context, "idem-race"),
        idempotency_service.initialize_checkout_request(redis, checkout_context, "idem-race"),
    )

    replays = [first[2], second[2]]
    assert sum(replay is None for replay in replays) == 1
    assert sum(replay == {
        "status": False,
        "message": "Checkout request already in progress",
        "data": {},
    } for replay in replays) == 1


@pytest.mark.asyncio
async def test_initialize_checkout_request_handles_burst_on_same_key(monkeypatch):
    checkout_context = build_checkout_context()
    redis = FakeConcurrentRedis()

    async def fake_get_by_key(key, _redis_client):
        payload = redis.store.get(key)
        if payload is None:
            return False
        return idempotency_service.json.loads(payload)

    monkeypatch.setattr(idempotency_service.cache_service, "get_by_key", fake_get_by_key)

    results = await asyncio.gather(*[
        idempotency_service.initialize_checkout_request(redis, checkout_context, "idem-burst")
        for _ in range(50)
    ])

    replays = [result[2] for result in results]
    assert sum(replay is None for replay in replays) == 1
    assert sum(
        replay == {
            "status": False,
            "message": "Checkout request already in progress",
            "data": {},
        }
        for replay in replays
    ) == 49
