from decimal import Decimal
from typing import Any

import asyncpg

from schemas.checkout import CheckoutContextData, CheckoutCompletedData
from services.shared.money import normalize_amount
from services.stripe import stripe_service


async def create_payment(
    conn: asyncpg.Connection,
    order_id: int,
    amount: Decimal,
    status: str,
) -> int:
    query = """
            INSERT INTO payments (order_id, amount, status)
            VALUES ($1, $2, $3)
            RETURNING id
            """

    normalized_amount = normalize_amount(amount)
    payment_id = await conn.fetchval(query, order_id, normalized_amount, status)
    if payment_id is None:
        raise ValueError("Failed to create payment")

    return int(payment_id)


async def update_payment_status(
    conn: asyncpg.Connection,
    data: CheckoutCompletedData,
    status: str,
    allowed_current_statuses: tuple[str, ...] = ("pending", "requires_action"),
) -> bool:
    query = """
            UPDATE payments
            SET status = $1,
                provider_payment_id = COALESCE(provider_payment_id, $2),
                checkout_session_id = COALESCE(checkout_session_id, $3),
                updated_at = NOW()
            WHERE id = $4
              AND order_id = $5
              AND status = ANY($6::text[])
            RETURNING id
            """

    row = await conn.fetchrow(
        query,
        status,
        data.payment_intent_id,
        data.checkout_session_id,
        data.payment_id,
        data.order_id,
        list(allowed_current_statuses),
    )

    return row is not None


async def start_stripe_checkout_session(
    checkout_context: CheckoutContextData,
    order_id: int,
    payment_id: int,
    idempotency_key: str,
) -> dict[str, Any]:
    return await stripe_service.initiate_checkout_session(
        checkout_context=checkout_context,
        order_id=order_id,
        payment_id=payment_id,
        idempotency_key=idempotency_key,
    )
