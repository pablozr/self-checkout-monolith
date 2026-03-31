from typing import Any

import asyncpg

from schemas.checkout import CheckoutContextData


async def create_payment(
    conn: asyncpg.Connection,
    order_id: int,
    amount: float,
    status: str,
) -> int:
    query = """
            INSERT INTO payments (order_id, amount, status)
            VALUES ($1, $2, $3)
            RETURNING id
            """

    payment_id = await conn.fetchval(query, order_id, amount, status)
    if payment_id is None:
        raise ValueError("Failed to create payment")

    return int(payment_id)


async def start_stripe_checkout_session(
    checkout_context: CheckoutContextData,
    order_id: int,
    payment_id: int,
    idempotency_key: str,
) -> dict[str, Any]:
    _ = checkout_context, order_id, payment_id, idempotency_key
    return {
        "status": False,
        "message": "Stripe checkout session is not implemented",
        "data": {},
    }
