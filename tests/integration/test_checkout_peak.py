import asyncio
import json
from collections import Counter
from decimal import Decimal
from itertools import count

import httpx
import pytest

from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from dependencies import checkout as checkout_dependency
from main import app
from services.order import order_service
from services.payment import payment_service


class _DummyConn:
    def __init__(self):
        self.execute_calls = []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))

    def transaction(self):
        return _DummyTransaction()


class _DummyTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.lock = asyncio.Lock()

    async def get(self, key):
        async with self.lock:
            return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        async with self.lock:
            if nx and key in self.store:
                return False
            self.store[key] = value
            return True

    async def setex(self, key, ttl, value):
        async with self.lock:
            self.store[key] = value

    async def delete(self, key):
        async with self.lock:
            self.store.pop(key, None)


def _checkout_context() -> dict:
    amount = Decimal("12.50")
    return {
        "sessionToken": "session-peak",
        "tableId": 7,
        "items": [
            {
                "productId": 1,
                "name": "Burger",
                "quantity": 1,
                "unitPrice": amount,
                "lineTotal": amount,
            }
        ],
        "subtotal": amount,
        "total": amount,
    }


@pytest.mark.asyncio
async def test_checkout_peak_burst_same_key_allows_single_winner(monkeypatch):
    conn = _DummyConn()
    redis = _FakeRedis()
    order_ids = count(100)
    payment_ids = count(200)

    async def override_checkout_context():
        return _checkout_context()

    async def override_conn():
        return conn

    async def override_redis():
        return redis

    async def fake_create_order_with_items(**kwargs):
        return next(order_ids)

    async def fake_create_payment(**kwargs):
        return next(payment_ids)

    async def fake_start_checkout_session(**kwargs):
        await asyncio.sleep(0.05)
        return {
            "status": True,
            "message": "ok",
            "data": {
                "checkoutSessionId": "cs_peak",
                "checkoutUrl": "https://example.test/checkout/cs_peak",
            },
        }

    monkeypatch.setattr(order_service, "create_order_with_items", fake_create_order_with_items)
    monkeypatch.setattr(payment_service, "create_payment", fake_create_payment)
    monkeypatch.setattr(payment_service, "start_stripe_checkout_session", fake_start_checkout_session)

    app.dependency_overrides[checkout_dependency.validate_checkout_context] = override_checkout_context
    app.dependency_overrides[postgresql.get_db] = override_conn
    app.dependency_overrides[redis_cache.get_redis] = override_redis

    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            responses = await asyncio.gather(*[
                client.post("/checkout/stripe", headers={"Idempotency-Key": "idem-peak-1"})
                for _ in range(25)
            ])
    finally:
        app.dependency_overrides.clear()

    counts = Counter(response.status_code for response in responses)
    assert counts[200] == 1
    assert counts[400] == 24

    details = [response.json().get("detail") for response in responses if response.status_code == 400]
    assert details == ["Checkout request already in progress"] * 24

    success_payload = next(response.json() for response in responses if response.status_code == 200)
    assert success_payload == {
        "message": "Stripe checkout in progress",
        "data": {"checkoutUrl": "https://example.test/checkout/cs_peak"},
    }

    saved_payload = json.loads(next(iter(redis.store.values())))
    assert saved_payload["state"] == "completed"
