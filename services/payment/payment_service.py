from decimal import Decimal
from typing import Any

import asyncpg

from schemas.checkout import CheckoutContextData
from services.stripe import stripe_service
from services.shared.money import normalize_amount


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
