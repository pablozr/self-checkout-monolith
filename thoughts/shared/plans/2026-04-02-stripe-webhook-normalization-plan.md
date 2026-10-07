# Stripe Webhook Normalization Implementation Plan

**Goal:** Fix the Stripe webhook runtime bug by normalizing verified Stripe SDK event objects into plain JSON-native Python structures before persistence, while preserving the current transaction boundary, duplicate-event dedupe, and post-commit SSE publication behavior.

**Architecture:** Keep the existing route and service orchestration shape: verify, register, dispatch, then publish. Design requires a single normalization boundary immediately after `stripe.Webhook.construct_event(...)`; I am implementing that as a recursive service-local normalizer in `services/stripe/webhook_service.py` because it centralizes Stripe-SDK handling once and keeps `_register_event`, `_parse_checkout_data`, and `_dispatch_event` on their existing dict-based contract. The transaction remains exactly where it is now: dedupe insert plus domain updates inside one `async with conn.transaction():` block, with SSE still published only after commit.

**Design:** `thoughts/shared/designs/2026-04-02-stripe-webhook-normalization-design.md`

**Project pattern lookup:** `mindmodel_lookup` was run for architecture, components, error handling, testing, and naming. This repo has no `.mindmodel/` directory, so the plan follows the established codebase patterns found directly in `services/stripe/webhook_service.py`, `routes/webhooks/router.py`, and the existing pytest files.

---

## Dependency Graph

```text
Batch 1 (parallel): 1.1 [production normalization boundary + service regression tests]
Batch 2 (parallel): 2.1 [integration regression burst tests - depends on 1.1]
Batch 3 (sequential verification): 3.1 [full suite + real webhook load reruns - depends on 1.1, 2.1]
```

---

## Execution Sequence

1. Add normalization at the Stripe service boundary and update unit/service tests first.
2. Expand the webhook burst integration test to cover both duplicate-event and unique-event success paths with normalized Stripe-shaped inputs.
3. Run targeted pytest files, then the full pytest suite, then rerun the documented real HTTP webhook load tests in duplicate and unique modes.

---

## Batch 1: Service normalization fix (parallel - 1 implementer)

This batch establishes the production fix and its TDD coverage. Start by writing the new failing tests in `tests/services/stripe/test_webhook_service.py`, verify they fail against the current implementation, then update `services/stripe/webhook_service.py` and rerun the same test file until green.

### Task 1.1: Normalize Stripe SDK events before persistence and dispatch
**File:** `services/stripe/webhook_service.py`
**Test:** `tests/services/stripe/test_webhook_service.py`
**Depends:** none

**Implementation decisions:**
- Design requires normalization immediately after webhook verification. Implement it as a private recursive helper in the same service file to avoid introducing an unnecessary abstraction layer.
- Prefer `to_dict_recursive()` when available on Stripe SDK objects, then recursively convert nested dict-like/list-like values into plain `dict`/`list`/primitive JSON values.
- Reject unsupported non-JSON-native values with `TypeError`; `handle_event` already converts unexpected exceptions into the existing generic internal-error envelope, so error semantics stay aligned with the design.
- Keep `_register_event` using `json.dumps(...)`, but make it operate only on already-normalized `dict[str, Any]` payloads.
- Keep route behavior unchanged; the service remains the normalization boundary.

```python
# COMPLETE test code - tests/services/stripe/test_webhook_service.py
from collections.abc import Mapping
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


class _FakeStripeObject(Mapping):
    def __init__(self, payload):
        self._payload = payload

    def __getitem__(self, key):
        return self._payload[key]

    def __iter__(self):
        return iter(self._payload)

    def __len__(self):
        return len(self._payload)

    def to_dict_recursive(self):
        return self._payload


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
async def test_handle_event_normalizes_stripe_objects_before_persistence_and_dispatch(monkeypatch):
    event = _FakeStripeObject(
        {
            "id": "evt_nested_123",
            "type": "checkout.session.completed",
            "data": {
                "object": _FakeStripeObject(
                    {
                        "id": "cs_nested_123",
                        "payment_intent": "pi_nested_123",
                        "payment_status": "paid",
                        "amount_total": 1250,
                        "metadata": {
                            "orderId": "10",
                            "paymentId": "20",
                            "tableId": "3",
                            "sessionToken": "session-token",
                        },
                        "line_items": [
                            _FakeStripeObject(
                                {
                                    "id": "li_1",
                                    "price": _FakeStripeObject({"id": "price_1", "unit_amount": 1250}),
                                }
                            )
                        ],
                    }
                ),
            },
        }
    )
    captured = {}

    def fake_construct_event(payload, signature, secret):
        return event

    async def fake_register_event(conn, event_id, event_type, obj):
        captured["register"] = {
            "event_id": event_id,
            "event_type": event_type,
            "obj": obj,
        }
        return True

    async def fake_dispatch_event(conn, event_type, obj):
        captured["dispatch"] = {
            "event_type": event_type,
            "obj": obj,
        }
        return None

    monkeypatch.setattr(webhook_service.stripe.Webhook, "construct_event", fake_construct_event)
    monkeypatch.setattr(webhook_service, "_register_event", fake_register_event)
    monkeypatch.setattr(webhook_service, "_dispatch_event", fake_dispatch_event)

    response = await webhook_service.handle_event(
        conn=_DummyConn(),
        redis_client=object(),
        payload=b"{}",
        signature="sig_header",
    )

    assert response["status"] is True
    register_obj = captured["register"]["obj"]
    dispatch_obj = captured["dispatch"]["obj"]
    assert isinstance(register_obj, dict)
    assert isinstance(dispatch_obj, dict)
    assert register_obj == dispatch_obj
    assert register_obj["line_items"][0]["price"] == {"id": "price_1", "unit_amount": 1250}

    # Must stay JSON serializable all the way down.
    import json

    json.dumps(register_obj)


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
```

```python
# COMPLETE implementation - services/stripe/webhook_service.py
import json
from decimal import Decimal
from typing import Any

import asyncpg
import redis.asyncio as redis
import stripe

from core.config.config import settings
from core.logger.logger import logger
from schemas.checkout import CheckoutCompletedData
from services.order import order_service
from services.payment import payment_service
from services.shared.money import normalize_amount
from services.shared.response import error_response, success_response
from services.sse import sse_service


def _normalize_stripe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(key): _normalize_stripe_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_normalize_stripe_value(item) for item in value]

    to_dict_recursive = getattr(value, "to_dict_recursive", None)
    if callable(to_dict_recursive):
        return _normalize_stripe_value(to_dict_recursive())

    items = getattr(value, "items", None)
    if callable(items):
        return {str(key): _normalize_stripe_value(item) for key, item in items()}

    raise TypeError(f"Unsupported Stripe value type for normalization: {type(value)!r}")


async def handle_event(
    conn: asyncpg.Connection,
    redis_client: redis.Redis,
    payload: bytes,
    signature: str,
) -> dict[str, Any]:
    try:
        raw_event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
        )
        event = _normalize_stripe_value(raw_event)

        if not isinstance(event, dict):
            raise ValueError("Stripe event payload is not an object")

        event_id = str(event["id"])
        event_type = str(event["type"])
        obj = event["data"]["object"]

        if not isinstance(obj, dict):
            raise ValueError("Stripe event data.object is not an object")

        async with conn.transaction():
            created = await _register_event(conn, event_id, event_type, obj)
            if not created:
                return success_response("Event already processed")

            domain_event = await _dispatch_event(conn, event_type, obj)

        if domain_event is not None:
            await sse_service.publish_admin_order_event(
                redis_client,
                domain_event["type"],
                domain_event["data"],
            )

        return success_response("Event processed successfully")
    except stripe.error.SignatureVerificationError as e:
        logger.warning(e)
        return error_response("Invalid signature")
    except ValueError as e:
        logger.error(e)
        return error_response(str(e))
    except Exception as e:
        logger.exception(e)
        return error_response("Error processing event")


async def _register_event(
    conn: asyncpg.Connection,
    event_id: str,
    event_type: str,
    obj: dict[str, Any],
) -> bool:
    row = await conn.fetchrow(
        """
        INSERT INTO stripe_events (event_id, event_type, event_object)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (event_id) DO NOTHING
        RETURNING id
        """,
        event_id,
        event_type,
        json.dumps(obj),
    )

    return row is not None


def _parse_checkout_data(obj: dict[str, Any]) -> CheckoutCompletedData:
    metadata = obj.get("metadata", {}) or {}

    try:
        order_id = int(metadata["orderId"])
        payment_id = int(metadata["paymentId"])
        table_id = int(metadata["tableId"])
        session_token = str(metadata["sessionToken"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("Missing or invalid metadata in Stripe event") from e

    checkout_session_id = str(obj.get("id") or "").strip()
    if not checkout_session_id:
        raise ValueError("Missing checkout session id in Stripe event")

    payment_intent_raw = obj.get("payment_intent")
    payment_intent_id = str(payment_intent_raw).strip() if payment_intent_raw else None

    amount_total_raw = obj.get("amount_total")
    amount_total: int | None = None
    if amount_total_raw is not None:
        try:
            amount_total = int(amount_total_raw)
        except (TypeError, ValueError) as e:
            raise ValueError("Invalid amount_total in Stripe event") from e

    return CheckoutCompletedData(
        order_id=order_id,
        payment_id=payment_id,
        table_id=table_id,
        session_token=session_token,
        checkout_session_id=checkout_session_id,
        payment_intent_id=payment_intent_id,
        amount_total=amount_total,
    )


async def _validate_checkout_against_db(
    conn: asyncpg.Connection,
    data: CheckoutCompletedData,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT o.id                  AS order_id,
               o.table_id            AS table_id,
               o.total               AS order_total,
               o.status              AS order_status,
               p.id                  AS payment_id,
               p.order_id            AS payment_order_id,
               p.status              AS payment_status,
               p.amount              AS payment_amount,
               p.checkout_session_id AS checkout_session_id
        FROM orders o
                 JOIN payments p ON p.order_id = o.id
        WHERE o.id = $1
          AND p.id = $2
        FOR UPDATE OF o, p
        """,
        data.order_id,
        data.payment_id,
    )

    if not row:
        raise ValueError("Order/payment not found")

    if row["table_id"] != data.table_id:
        raise ValueError("table_id mismatch")

    if row["payment_order_id"] != data.order_id:
        raise ValueError("payment.order_id mismatch")

    existing_checkout_session_id = row["checkout_session_id"]
    if existing_checkout_session_id and existing_checkout_session_id != data.checkout_session_id:
        raise ValueError("checkout_session_id mismatch")

    if data.amount_total is not None:
        stripe_total = normalize_amount(Decimal(data.amount_total) / Decimal("100"))
        order_total = normalize_amount(Decimal(str(row["order_total"])))
        payment_amount = normalize_amount(Decimal(str(row["payment_amount"])))
        if stripe_total != order_total or stripe_total != payment_amount:
            raise ValueError("amount_total mismatch")

    return {**row}


async def _dispatch_event(
    conn: asyncpg.Connection,
    event_type: str,
    obj: dict[str, Any],
) -> dict[str, Any] | None:
    if event_type in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        if event_type == "checkout.session.completed" and obj.get("payment_status") != "paid":
            logger.info("Ignoring checkout.session.completed with non-paid status")
            return None

        data = _parse_checkout_data(obj)
        validated = await _validate_checkout_against_db(conn, data)

        if validated["payment_status"] == "paid" and validated["order_status"] == "paid":
            return None

        payment_updated = await payment_service.update_payment_status(
            conn,
            data,
            "paid",
            ("pending", "requires_action"),
        )
        if not payment_updated:
            raise ValueError("Payment status transition not allowed")

        order_updated = await order_service.update_order_status(
            conn,
            data.order_id,
            "paid",
            ("pending",),
        )
        if not order_updated and validated["order_status"] != "paid":
            raise ValueError("Order status transition not allowed")

        return {
            "type": "order_paid",
            "data": {
                "orderId": data.order_id,
                "paymentId": data.payment_id,
                "tableId": data.table_id,
            },
        }

    if event_type in {
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    }:
        data = _parse_checkout_data(obj)
        validated = await _validate_checkout_against_db(conn, data)

        if validated["payment_status"] == "failed" and validated["order_status"] == "payment_failed":
            return None

        if validated["payment_status"] == "paid" or validated["order_status"] == "paid":
            logger.warning("Ignoring failure event for already paid order")
            return None

        payment_updated = await payment_service.update_payment_status(
            conn,
            data,
            "failed",
            ("pending", "requires_action"),
        )
        if not payment_updated:
            raise ValueError("Payment failure transition not allowed")

        order_updated = await order_service.update_order_status(
            conn,
            data.order_id,
            "payment_failed",
            ("pending",),
        )
        if not order_updated and validated["order_status"] != "payment_failed":
            raise ValueError("Order failure transition not allowed")

        return {
            "type": "order_payment_failed",
            "data": {
                "orderId": data.order_id,
                "paymentId": data.payment_id,
                "tableId": data.table_id,
            },
        }

    logger.info(f"Ignoring unsupported Stripe event type: {event_type}")
    return None
```

**Verify:**
- `pytest tests/services/stripe/test_webhook_service.py -q`
- Specifically confirm the new normalization test fails before implementation, then passes after implementation.

**Commit:** `fix(stripe): normalize webhook payloads before persistence`

---

## Batch 2: Integration regression coverage (parallel - 1 implementer)

This batch extends the existing burst-style webhook integration test so the runtime bug stays fixed under concurrency. It intentionally keeps dedupe and success-path semantics exactly as they are today.

### Task 2.1: Cover duplicate and unique webhook bursts with normalized Stripe-shaped inputs
**File:** `tests/integration/test_webhook_peak.py`
**Test:** none (this file is the integration regression suite)
**Depends:** 1.1

**Implementation decisions:**
- Keep using dependency overrides and monkeypatching instead of introducing a heavier DB fixture, because the purpose here is orchestration and concurrent semantics.
- Add a lightweight fake Stripe object with `to_dict_recursive()` so the integration suite exercises the exact normalization boundary added in Batch 1.
- Preserve the existing duplicate-event assertion (`1 processed + N-1 already processed`) and add a unique-event burst assertion that all requests return 200/process successfully, proving the serialization bug is gone under concurrent unique events.

```python
# COMPLETE test code - tests/integration/test_webhook_peak.py
import asyncio
from collections import Counter
from collections.abc import Mapping
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


class _FakeStripeObject(Mapping):
    def __init__(self, payload):
        self._payload = payload

    def __getitem__(self, key):
        return self._payload[key]

    def __iter__(self):
        return iter(self._payload)

    def __len__(self):
        return len(self._payload)

    def to_dict_recursive(self):
        return self._payload


def _build_stripe_event(event_id: str, checkout_session_id: str) -> _FakeStripeObject:
    return _FakeStripeObject(
        {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": _FakeStripeObject(
                    {
                        "id": checkout_session_id,
                        "payment_status": "paid",
                        "payment_intent": f"pi_{checkout_session_id}",
                        "amount_total": 1250,
                        "metadata": {
                            "orderId": "10",
                            "paymentId": "20",
                            "tableId": "3",
                            "sessionToken": "session-token",
                        },
                    }
                )
            },
        }
    )


@pytest.mark.asyncio
async def test_webhook_peak_burst_dedupes_event_and_publishes_once(monkeypatch):
    conn = _DummyConn()
    redis_client = object()
    seen_event_ids = set()
    register_lock = asyncio.Lock()
    publish_admin_order_event = AsyncMock()

    def fake_construct_event(payload, signature, secret):
        return _build_stripe_event("evt_peak_1", "cs_peak")

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


@pytest.mark.asyncio
async def test_webhook_peak_burst_unique_events_all_succeed(monkeypatch):
    conn = _DummyConn()
    redis_client = object()
    publish_admin_order_event = AsyncMock()
    event_counter = 0
    counter_lock = asyncio.Lock()

    def fake_construct_event(payload, signature, secret):
        return _build_stripe_event("evt_template", "cs_template")

    async def fake_register_event(conn, event_id, event_type, obj):
        return True

    async def fake_dispatch_event(conn, event_type, obj):
        nonlocal event_counter
        async with counter_lock:
            event_counter += 1
            current = event_counter
        await asyncio.sleep(0.02)
        return {
            "type": "order_paid",
            "data": {"orderId": current, "paymentId": current, "tableId": 3},
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
                    headers={"Stripe-Signature": f"sig_unique_{index}"},
                )
                for index in range(25)
            ])
    finally:
        app.dependency_overrides.clear()

    counts = Counter(response.status_code for response in responses)
    assert counts[200] == 25

    messages = Counter(response.json()["message"] for response in responses)
    assert messages == Counter({"Event processed successfully": 25})
    assert publish_admin_order_event.await_count == 25
```

**Verify:**
- `pytest tests/integration/test_webhook_peak.py -q`

**Commit:** `test(stripe): add webhook peak normalization regressions`

---

## Batch 3: Final verification and load reruns (sequential)

This batch is not a code change. It is the required execution pass after Batches 1 and 2 land.

### Task 3.1: Re-run automated and real webhook verification
**File:** none
**Test:** none
**Depends:** 1.1, 2.1

**Verification sequence:**

1. Targeted service regression:
   - `pytest tests/services/stripe/test_webhook_service.py -q`
2. Targeted integration regression:
   - `pytest tests/integration/test_webhook_peak.py -q`
3. Full automated regression suite:
   - `pytest -q`
4. Real HTTP webhook load reruns against a running API using a real webhook payload template and configured secret:
   - Duplicate-event dedupe rerun:
     - `python scripts/load_test.py webhook --base-url http://127.0.0.1:8000 --payload-file webhook.json --webhook-secret whsec_xxx --requests 25 --concurrency 10 --event-id-mode same`
   - Unique-event success rerun:
     - `python scripts/load_test.py webhook --base-url http://127.0.0.1:8000 --payload-file webhook.json --webhook-secret whsec_xxx --requests 25 --concurrency 10 --event-id-mode unique`
   - Post-fix throughput follow-up requested by the design's open question:
     - `python scripts/load_test.py webhook --base-url http://127.0.0.1:8000 --payload-file webhook.json --webhook-secret whsec_xxx --requests 100 --concurrency 25 --event-id-mode unique`
5. Operational log review after the load runs:
   - Check API logs for missing `json.dumps(...)` serialization failures and any new fallback `Error processing event` exceptions.

**Expected outcomes:**
- Duplicate load run returns one `Event processed successfully` and the remaining responses as `Event already processed`.
- Unique load run no longer returns 500 for valid events that previously failed on `stripe_events.event_object` persistence.
- SSE publication count matches committed successful unique events and remains post-transaction.

---

## Risks and Guardrails

- **Do not move the transaction.** The dedupe insert and domain update flow must remain inside the same `conn.transaction()` block.
- **Do not move SSE publication into the transaction.** It must remain after commit exactly as it is today.
- **Do not weaken dedupe.** Keep `ON CONFLICT (event_id) DO NOTHING` and return the current duplicate success envelope.
- **Do not use lossy fallback serialization.** No `default=str`, no blanket stringification of nested provider objects.
- **Do not spread Stripe-object handling into downstream helpers.** `_parse_checkout_data` and `_dispatch_event` should continue to receive plain dictionaries only.

---

## Done Criteria

- `services/stripe/webhook_service.py` normalizes Stripe SDK objects immediately after verification.
- `stripe_events.event_object` persistence succeeds with normalized JSON-serializable payloads.
- Existing duplicate-event behavior and transaction boundaries remain unchanged.
- SSE still publishes only after a successful commit.
- `tests/services/stripe/test_webhook_service.py` and `tests/integration/test_webhook_peak.py` both cover normalized Stripe-shaped inputs.
- `pytest -q` passes.
- All three webhook load commands above are rerun and the unique-event run no longer fails with serialization-driven 500s.
