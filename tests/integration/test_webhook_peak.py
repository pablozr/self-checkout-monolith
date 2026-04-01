import asyncio
from collections import Counter
from unittest.mock import AsyncMock

import httpx
import pytest

from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from main import app
from services.stripe import webhook_service


class _DummyTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyConn:
    def transaction(self):
        return _DummyTransaction()


@pytest.mark.asyncio
async def test_webhook_peak_burst_dedupes_event_and_publishes_once(monkeypatch):
    conn = _DummyConn()
    redis_client = object()
    seen_event_ids = set()
    register_lock = asyncio.Lock()
    publish_admin_order_event = AsyncMock()

    def fake_construct_event(payload, signature, secret):
        return {
            "id": "evt_peak_1",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_peak"}},
        }

    async def fake_register_event(conn, event_id, event_type, obj):
        async with register_lock:
            if event_id in seen_event_ids:
                return False
            seen_event_ids.add(event_id)
            return True

    async def fake_dispatch_event(conn, event_type, obj):
        await asyncio.sleep(0.05)
        return {
            "type": "order_paid",
            "data": {"orderId": 10, "paymentId": 20, "tableId": 3},
        }

    async def override_conn():
        return conn

    async def override_redis():
        return redis_client

    monkeypatch.setattr(webhook_service.stripe.Webhook, "construct_event", fake_construct_event)
    monkeypatch.setattr(webhook_service, "_register_event", fake_register_event)
    monkeypatch.setattr(webhook_service, "_dispatch_event", fake_dispatch_event)
    monkeypatch.setattr(webhook_service.sse_service, "publish_admin_order_event", publish_admin_order_event)

    app.dependency_overrides[postgresql.get_db] = override_conn
    app.dependency_overrides[redis_cache.get_redis] = override_redis

    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            responses = await asyncio.gather(*[
                client.post(
                    "/webhooks/stripe",
                    content=b"{}",
                    headers={"Stripe-Signature": "sig_peak"},
                )
                for _ in range(25)
            ])
    finally:
        app.dependency_overrides.clear()

    counts = Counter(response.status_code for response in responses)
    assert counts[200] == 25

    messages = Counter(response.json()["message"] for response in responses)
    assert messages["Event processed successfully"] == 1
    assert messages["Event already processed"] == 24
    publish_admin_order_event.assert_awaited_once_with(
        redis_client,
        "order_paid",
        {"orderId": 10, "paymentId": 20, "tableId": 3},
    )
