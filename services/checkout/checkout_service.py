from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any

import asyncpg

from core.config.config import (
    CHECKOUT_IDEMPOTENCY_TTL_SECONDS,
)
from core.logger.logger import logger
from schemas.cart import CartSessionContext
from schemas.checkout import CheckoutContextData, CheckoutItemData
from services.cache import cache_service
from services.cart import cart_service
from services.idempotency import idempotency_service
from services.payment import payment_service


def _error_response(message: str) -> dict[str, Any]:
    return {"status": False, "message": message, "data": {}}


async def build_checkout_context(
    conn: asyncpg.Connection,
    session_context: CartSessionContext,
) -> dict[str, Any]:
    try:
        cart = session_context["session"]
        token = session_context["token"]
        table_id = cart["tableId"]
        cart_items = cart["items"]

        if not cart_items:
            return _error_response("Cart is empty")

        for item in cart_items:
            if item["quantity"] <= 0:
                return _error_response(f"Invalid quantity for product {item['productId']}")

        table_row = await conn.fetchrow(
            """
            SELECT 1
            FROM tables
            WHERE id = $1 AND is_active = TRUE
            """,
            table_id,
        )
        if not table_row:
            return _error_response("Table not found or inactive")

        product_ids = [item["productId"] for item in cart_items]
        quantities = [item["quantity"] for item in cart_items]

        product_rows = await conn.fetch(
            """
            SELECT
                p.id,
                p.name,
                p.price,
                p.is_active,
                p.is_available,
                ci.quantity
            FROM unnest($1::int[], $2::int[]) AS ci(product_id, quantity)
            JOIN products p ON p.id = ci.product_id
            """,
            product_ids,
            quantities,
        )

        if len(product_rows) != len(cart_items):
            found_ids = {row["id"] for row in product_rows}
            missing = [pid for pid in product_ids if pid not in found_ids]
            return _error_response(f"Product(s) not found: {missing}")

        validated_items: list[CheckoutItemData] = []
        subtotal = Decimal("0.00")

        for row in product_rows:
            if not row["is_active"] or not row["is_available"]:
                return _error_response(f"Product {row['id']} unavailable")

            unit_price = Decimal(str(row["price"]))
            quantity = row["quantity"]
            line_total = (unit_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            subtotal = (subtotal + line_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            validated_items.append(
                {
                    "productId": row["id"],
                    "name": row["name"],
                    "quantity": quantity,
                    "unitPrice": float(unit_price),
                    "lineTotal": float(line_total),
                }
            )

        checkout_context: CheckoutContextData = {
            "sessionToken": token,
            "tableId": table_id,
            "items": validated_items,
            "subtotal": float(subtotal),
            "total": float(subtotal),
        }

        return {
            "status": True,
            "message": "Checkout context validated successfully",
            "data": {"checkout": checkout_context},
        }

    except Exception as e:
        logger.exception(e)
        return _error_response("Internal server error")


async def confirm_checkout(
    conn: asyncpg.Connection,
    redis_client,
    checkout_context: CheckoutContextData,
    idempotency_key: str,
) -> dict[str, Any]:
    # Keep this in outer scope so failure handlers can clean it up.
    redis_key = None

    try:
        session_token = checkout_context["sessionToken"]
        redis_key = idempotency_service.build_checkout_idempotency_key(
            idempotency_key,
            session_token,
        )
        request_hash = idempotency_service.build_request_hash(checkout_context)

        # Fast path: key already processed, so replay deterministic response.
        existing_response_raw = await cache_service.get_by_key(redis_key, redis_client)
        if isinstance(existing_response_raw, dict):
            existing_response = existing_response_raw
            existing_hash = existing_response.get("requestHash")

            if existing_hash and existing_hash != request_hash:
                return _error_response(
                    "Idempotency key already used with a different payload"
                )

            return idempotency_service.build_replay_response(existing_response)

        # Acquire idempotency lock using NX to avoid duplicate processing.
        processing_payload = {
            "key": idempotency_key,
            "state": "processing",
            "requestHash": request_hash,
        }

        created = await redis_client.set(
            redis_key,
            json.dumps(processing_payload),
            ex=CHECKOUT_IDEMPOTENCY_TTL_SECONDS,
            nx=True,
        )

        # Lost race for the same key; replay stored result when available.
        if not created:
            concurrent_response_raw = await cache_service.get_by_key(redis_key, redis_client)

            if isinstance(concurrent_response_raw, dict):
                concurrent_response = concurrent_response_raw
                existing_hash = concurrent_response.get("requestHash")

                if existing_hash and existing_hash != request_hash:
                    return _error_response(
                        "Idempotency key already used with a different payload"
                    )

                return idempotency_service.build_replay_response(concurrent_response)

            return _error_response("Checkout request already in progress")

        # Create order aggregate atomically before touching payment provider.
        async with conn.transaction():
            order_row = await conn.fetchrow(
                """
                INSERT INTO orders (table_id, subtotal, total, status)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                checkout_context["tableId"],
                checkout_context["subtotal"],
                checkout_context["total"],
                "pending",
            )
            if not order_row:
                return _error_response("Failed to create order")

            order_id = order_row["id"]

            order_items_params = [
                (
                    order_id,
                    item["productId"],
                    item["name"],
                    item["quantity"],
                    item["unitPrice"],
                    item["lineTotal"],
                )
                for item in checkout_context["items"]
            ]

            await conn.executemany(
                """
                INSERT INTO order_items (
                    order_id,
                    product_id,
                    name,
                    quantity,
                    unit_price,
                    line_total
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                order_items_params,
            )

            payment_row = await conn.fetchrow(
                """
                INSERT INTO payments (order_id, amount, status)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                order_id,
                checkout_context["total"],
                "pending",
            )
            if not payment_row:
                return _error_response("Failed to create payment")

            payment_id = payment_row["id"]

        # Gateway call happens after order persistence.
        gateway_result = await payment_service.process_checkout_payment(checkout_context)
        payment_state = gateway_result["state"]
        order_state = "confirmed" if payment_state == "approved" else "pending"

        # Persist final payment/order states.
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE payments
                SET status = $1
                WHERE id = $2
                """,
                payment_state,
                payment_id,
            )

            await conn.execute(
                """
                UPDATE orders
                SET status = $1
                WHERE id = $2
                """,
                order_state,
                order_id,
            )

        if payment_state == "approved":
            await cart_service.clear_cart_by_session_token(redis_client, session_token)

        # Persist replay payload for future retries with same idempotency key.
        service_response = {
            "status": True,
            "message": (
                "Checkout confirmed"
                if payment_state == "approved"
                else "Checkout created with pending payment"
            ),
            "data": {
                "orderId": order_id,
                "paymentId": payment_id,
                "paymentStatus": payment_state,
            },
        }

        final_payload = {
            "key": idempotency_key,
            "state": "succeeded",
            "requestHash": request_hash,
            "orderId": order_id,
            "paymentId": payment_id,
            "serviceResponse": service_response,
        }

        await idempotency_service.save_payload(redis_client, redis_key, final_payload)

        return service_response

    except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
        # Release processing key so caller can retry after schema fix.
        if redis_key:
            await redis_client.delete(redis_key)

        return _error_response(
            "Checkout tables are not configured in database schema"
        )

    except Exception as e:
        logger.exception(e)

        # Release processing key on unexpected failures.
        if redis_key:
            await redis_client.delete(redis_key)

        return _error_response("Internal server error")
