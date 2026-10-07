"""Helpers para testes de integração contra Postgres/Redis (Docker local)."""

from __future__ import annotations

import hashlib
import hmac
import os
import random
import time
import uuid
from decimal import Decimal
from typing import Any

import asyncpg

from core.config.config import settings


def stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    signed_at = timestamp or int(time.time())
    signed_payload = f"{signed_at}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_at},v1={digest}"


def build_checkout_completed_event(
    *,
    event_id: str,
    order_id: int,
    payment_id: int,
    table_id: int,
    checkout_session_id: str,
    session_token: str = "docker-live-test",
    amount_total_cents: int = 1250,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": checkout_session_id,
                "object": "checkout.session",
                "payment_status": "paid",
                "metadata": {
                    "orderId": str(order_id),
                    "paymentId": str(payment_id),
                    "tableId": str(table_id),
                    "sessionToken": session_token,
                },
                "amount_total": amount_total_cents,
                "payment_intent": f"pi_int_{uuid.uuid4().hex[:16]}",
            }
        },
    }


async def seed_pending_order_with_payment(conn: asyncpg.Connection) -> dict[str, Any]:
    uid = uuid.uuid4().hex[:12]
    table_number = random.randint(2_000_000, 9_999_999)
    table_row = await conn.fetchrow(
        "INSERT INTO tables (number) VALUES ($1) RETURNING id",
        table_number,
    )
    table_pk = int(table_row["id"])
    order_row = await conn.fetchrow(
        """
        INSERT INTO orders (table_id, subtotal, total, status)
        VALUES ($1, $2::numeric, $2::numeric, 'pending')
        RETURNING id, table_id
        """,
        table_pk,
        Decimal("12.50"),
    )
    order_id = int(order_row["id"])
    table_fk = int(order_row["table_id"])
    checkout_session_id = f"cs_live_{uid}"
    pay_row = await conn.fetchrow(
        """
        INSERT INTO payments (order_id, amount, status, checkout_session_id)
        VALUES ($1, $2::numeric, 'pending', $3)
        RETURNING id
        """,
        order_id,
        Decimal("12.50"),
        checkout_session_id,
    )
    payment_id = int(pay_row["id"])
    return {
        "table_pk": table_pk,
        "order_id": order_id,
        "payment_id": payment_id,
        "table_id": table_fk,
        "checkout_session_id": checkout_session_id,
    }


async def cleanup_integration_rows(
    conn: asyncpg.Connection,
    *,
    event_ids: list[str],
    order_id: int,
    table_pk: int,
) -> None:
    for eid in event_ids:
        await conn.execute("DELETE FROM stripe_events WHERE event_id = $1", eid)
    await conn.execute("DELETE FROM orders WHERE id = $1", order_id)
    await conn.execute("DELETE FROM tables WHERE id = $1", table_pk)


def integration_dsn() -> str:
    return (
        f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    )


def integration_enabled() -> bool:
    if os.environ.get("INTEGRATION_TESTS", "").lower() not in ("1", "true", "yes"):
        return False
    return bool(str(settings.STRIPE_WEBHOOK_SECRET or "").strip())
