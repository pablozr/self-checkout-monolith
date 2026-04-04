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

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, stripe.StripeObject):
        return _normalize_stripe_value(value.to_dict())

    if isinstance(value, dict):
        return {str(key): _normalize_stripe_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_normalize_stripe_value(item) for item in value]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _normalize_stripe_value(to_dict())

    items = getattr(value, "items", None)
    if callable(items):
        return {str(key): _normalize_stripe_value(item) for key, item in items()}

    return str(value)


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
        json.dumps(obj, default=vars),
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