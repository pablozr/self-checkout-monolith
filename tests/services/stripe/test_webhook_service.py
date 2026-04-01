from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import services.stripe.webhook_service as webhook_service


class _DummyTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyConn:
    def transaction(self):
        return _DummyTransaction()


def _build_checkout_completed_object(**overrides):
    obj = {
        "id": "cs_test_123",
        "payment_intent": "pi_test_123",
        "payment_status": "paid",
        "amount_total": 1250,
        "metadata": {
            "orderId": "10",
            "paymentId": "20",
            "tableId": "3",
            "sessionToken": "session-token",
        },
    }
    obj.update(overrides)
    return obj


@pytest.mark.asyncio
async def test_handle_event_duplicate_event_returns_already_processed(monkeypatch):
    event = {
        "id": "evt_123",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }
    dispatch_called = False

    def fake_construct_event(payload, signature, secret):
        return event

    async def fake_register_event(conn, event_id, event_type, obj):
        return False

    async def fake_dispatch_event(conn, event_type, obj):
        nonlocal dispatch_called
        dispatch_called = True
        return None

    monkeypatch.setattr(
        webhook_service.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )
    monkeypatch.setattr(webhook_service, "_register_event", fake_register_event)
    monkeypatch.setattr(webhook_service, "_dispatch_event", fake_dispatch_event)

    response = await webhook_service.handle_event(
        conn=_DummyConn(),
        redis_client=object(),
        payload=b"{}",
        signature="sig_header",
    )

    assert response["status"] is True
    assert response["message"] == "Event already processed"
    assert dispatch_called is False


@pytest.mark.asyncio
async def test_handle_event_invalid_signature_returns_error(monkeypatch):
    class FakeSignatureVerificationError(Exception):
        pass

    def fake_construct_event(payload, signature, secret):
        raise FakeSignatureVerificationError("invalid")

    monkeypatch.setattr(
        webhook_service.stripe.error,
        "SignatureVerificationError",
        FakeSignatureVerificationError,
    )
    monkeypatch.setattr(
        webhook_service.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )

    response = await webhook_service.handle_event(
        conn=_DummyConn(),
        redis_client=object(),
        payload=b"{}",
        signature="bad_signature",
    )

    assert response["status"] is False
    assert response["message"] == "Invalid signature"


@pytest.mark.asyncio
async def test_handle_event_publishes_sse_after_successful_dispatch(monkeypatch):
    event = {
        "id": "evt_456",
        "type": "checkout.session.completed",
        "data": {"object": _build_checkout_completed_object()},
    }
    redis_client = object()
    publish_admin_order_event = AsyncMock()

    def fake_construct_event(payload, signature, secret):
        return event

    async def fake_register_event(conn, event_id, event_type, obj):
        return True

    async def fake_dispatch_event(conn, event_type, obj):
        return {
            "type": "order_paid",
            "data": {"orderId": 10, "paymentId": 20, "tableId": 3},
        }

    monkeypatch.setattr(webhook_service.stripe.Webhook, "construct_event", fake_construct_event)
    monkeypatch.setattr(webhook_service, "_register_event", fake_register_event)
    monkeypatch.setattr(webhook_service, "_dispatch_event", fake_dispatch_event)
    monkeypatch.setattr(webhook_service.sse_service, "publish_admin_order_event", publish_admin_order_event)

    response = await webhook_service.handle_event(
        conn=_DummyConn(),
        redis_client=redis_client,
        payload=b"{}",
        signature="sig_header",
    )

    assert response["status"] is True
    assert response["message"] == "Event processed successfully"
    publish_admin_order_event.assert_awaited_once_with(
        redis_client,
        "order_paid",
        {"orderId": 10, "paymentId": 20, "tableId": 3},
    )


@pytest.mark.asyncio
async def test_dispatch_event_raises_when_payment_status_transition_is_invalid(monkeypatch):
    conn = AsyncMock()
    obj = _build_checkout_completed_object()

    monkeypatch.setattr(
        webhook_service,
        "_validate_checkout_against_db",
        AsyncMock(
            return_value={
                "payment_status": "pending",
                "order_status": "pending",
            }
        ),
    )
    monkeypatch.setattr(webhook_service.payment_service, "update_payment_status", AsyncMock(return_value=False))

    with pytest.raises(ValueError, match="Payment status transition not allowed"):
        await webhook_service._dispatch_event(conn, "checkout.session.completed", obj)


@pytest.mark.asyncio
async def test_dispatch_event_ignores_failure_for_already_paid_order(monkeypatch):
    conn = AsyncMock()
    obj = _build_checkout_completed_object(payment_status="unpaid")
    update_payment_status = AsyncMock()
    update_order_status = AsyncMock()

    monkeypatch.setattr(
        webhook_service,
        "_validate_checkout_against_db",
        AsyncMock(
            return_value={
                "payment_status": "paid",
                "order_status": "paid",
            }
        ),
    )
    monkeypatch.setattr(webhook_service.payment_service, "update_payment_status", update_payment_status)
    monkeypatch.setattr(webhook_service.order_service, "update_order_status", update_order_status)

    response = await webhook_service._dispatch_event(conn, "checkout.session.async_payment_failed", obj)

    assert response is None
    update_payment_status.assert_not_awaited()
    update_order_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_checkout_against_db_rejects_amount_mismatch():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "order_id": 10,
            "table_id": 3,
            "order_total": Decimal("12.50"),
            "order_status": "pending",
            "payment_id": 20,
            "payment_order_id": 10,
            "payment_status": "pending",
            "payment_amount": Decimal("10.00"),
            "checkout_session_id": "cs_test_123",
        }
    )
    data = webhook_service.CheckoutCompletedData(
        order_id=10,
        payment_id=20,
        table_id=3,
        session_token="session-token",
        checkout_session_id="cs_test_123",
        payment_intent_id="pi_test_123",
        amount_total=1250,
    )

    with pytest.raises(ValueError, match="amount_total mismatch"):
        await webhook_service._validate_checkout_against_db(conn, data)
