from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from schemas.checkout import CheckoutContextData
from services.checkout import checkout_service


class _DummyTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_checkout_context() -> CheckoutContextData:
    amount = Decimal("12.50")
    return {
        "sessionToken": "session-123",
        "tableId": 10,
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
async def test_start_stripe_checkout_returns_replay_without_touching_db_or_provider(monkeypatch):
    conn = AsyncMock()
    redis_client = AsyncMock()
    checkout_context = _build_checkout_context()
    replay_response = {
        "status": False,
        "message": "Checkout request already in progress",
        "data": {},
    }

    async def fake_initialize_checkout_request(**_kwargs):
        return "redis-key", "hash", replay_response

    create_order_with_items = AsyncMock()
    create_payment = AsyncMock()
    start_checkout_session = AsyncMock()

    monkeypatch.setattr(
        checkout_service.idempotency_service,
        "initialize_checkout_request",
        fake_initialize_checkout_request,
    )
    monkeypatch.setattr(checkout_service.order_service, "create_order_with_items", create_order_with_items)
    monkeypatch.setattr(checkout_service.payment_service, "create_payment", create_payment)
    monkeypatch.setattr(checkout_service.stripe_service, "initiate_checkout_session", start_checkout_session)

    response = await checkout_service.start_stripe_checkout(
        conn=conn,
        redis_client=redis_client,
        checkout_context=checkout_context,
        idempotency_key="idem-1",
    )

    assert response == replay_response
    create_order_with_items.assert_not_awaited()
    create_payment.assert_not_awaited()
    start_checkout_session.assert_not_awaited()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_stripe_checkout_marks_payment_failed_and_saves_failed_payload_when_provider_fails(monkeypatch):
    conn = SimpleNamespace(
        transaction=lambda: _DummyTransaction(),
        execute=AsyncMock(),
    )
    redis_client = AsyncMock()
    checkout_context = _build_checkout_context()

    initialize_checkout_request = AsyncMock(return_value=("redis-key", "hash", None))
    create_order_with_items = AsyncMock(return_value=101)
    create_payment = AsyncMock(return_value=202)
    start_checkout_session = AsyncMock(
        return_value={
            "status": False,
            "message": "stripe-down",
            "data": {},
        }
    )
    save_payload = AsyncMock()

    monkeypatch.setattr(checkout_service.idempotency_service, "initialize_checkout_request", initialize_checkout_request)
    monkeypatch.setattr(checkout_service.order_service, "create_order_with_items", create_order_with_items)
    monkeypatch.setattr(checkout_service.payment_service, "create_payment", create_payment)
    monkeypatch.setattr(checkout_service.stripe_service, "initiate_checkout_session", start_checkout_session)
    monkeypatch.setattr(checkout_service.idempotency_service, "save_payload", save_payload)

    response = await checkout_service.start_stripe_checkout(
        conn=conn,
        redis_client=redis_client,
        checkout_context=checkout_context,
        idempotency_key="idem-2",
    )

    assert response == {"status": False, "message": "stripe-down", "data": {}}
    conn.execute.assert_awaited_once_with(
        "UPDATE payments SET status = $1 WHERE id = $2",
        "failed",
        202,
    )
    save_payload.assert_awaited_once()
    payload = save_payload.await_args_list[0].args[2]
    assert payload["state"] == "failed"
    assert payload["orderId"] == 101
    assert payload["paymentId"] == 202
    assert payload["serviceResponse"] == response
