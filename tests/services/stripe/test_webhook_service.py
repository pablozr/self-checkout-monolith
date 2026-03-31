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
