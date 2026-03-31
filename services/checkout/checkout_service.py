from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import asyncpg

from core.logger.logger import logger
from schemas.cart import CartSessionContext
from schemas.checkout import CheckoutContextData, CheckoutItemData
from services.idempotency import idempotency_service
from services.payment import payment_service
from services.order import order_service


def _error_response(message: str) -> dict[str, Any]:
    return {"status": False, "message": message, "data": {}}


async def _handle_error(
        redis_client,
        redis_key: str | None,
        idempotency_service,
        idempotency_key: str,
        request_hash: str | None,
        order_id: int | None,
        payment_id: int | None,
        error_message: str,
) -> dict[str, Any]:
    response = _error_response(error_message)

    if redis_key and request_hash and order_id and payment_id:
        await idempotency_service.save_payload(
            redis_client,
            redis_key,
            {
                "key": idempotency_key,
                "state": "failed",
                "requestHash": request_hash,
                "orderId": order_id,
                "paymentId": payment_id,
                "serviceResponse": response,
            }
        )
        return response
    # Release processing key on unexpected failures.

    if redis_key:
        await redis_client.delete(redis_key)

    return response


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
            WHERE id = $1
              AND is_active = TRUE
            """,
            table_id,
        )
        if not table_row:
            return _error_response("Table not found or inactive")

        product_ids = [item["productId"] for item in cart_items]
        quantities = [item["quantity"] for item in cart_items]

        product_rows = await conn.fetch(
            """
            SELECT p.id,
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


async def start_stripe_checkout(
        conn: asyncpg.Connection,
        redis_client,
        checkout_context: CheckoutContextData,
        idempotency_key: str,
) -> dict[str, Any]:
    # Keep this in outer scope so failure handlers can clean it up.
    redis_key = None
    order_id = None
    payment_id = None
    request_hash = None

    try:
        redis_key, request_hash, replay_response = await idempotency_service.initialize_checkout_request(
            redis_client=redis_client,
            checkout_context=checkout_context,
            idempotency_key=idempotency_key,
        )
        if replay_response is not None:
            return replay_response

        # Create order aggregate atomically before touching payment provider.
        async with conn.transaction():
            order_id = await order_service.create_order_with_items(
                conn=conn,
                table_id=checkout_context["tableId"],
                subtotal=checkout_context["subtotal"],
                total=checkout_context["total"],
                status="pending",
                items=checkout_context["items"],
            )

            payment_id = await payment_service.create_payment(
                conn=conn,
                order_id=order_id,
                amount=checkout_context["total"],
                status="pending",
            )

        if order_id is None or payment_id is None:
            raise ValueError("Failed to initialize checkout records")

        stripe_response = await payment_service.start_stripe_checkout_session(
            checkout_context=checkout_context,
            order_id=order_id,
            payment_id=payment_id,
            idempotency_key=idempotency_key,
        )

        if not stripe_response["status"]:
            await conn.execute(
                "UPDATE payments SET status = $1 WHERE id = $2",
                "failed",
                payment_id,
            )

            service_response = _error_response(stripe_response["message"])
            await idempotency_service.save_payload(
                redis_client,
                redis_key, {
                    "key": idempotency_key,
                    "state": "failed",
                    "requestHash": request_hash,
                    "orderId": order_id,
                    "paymentId": payment_id,
                    "serviceResponse": service_response,
                }
            )
            return service_response

        stripe_data = stripe_response["data"]

        await conn.execute(
            "UPDATE payments SET status = $1, checkoutSessionId = $2, checkoutUrl = $3 WHERE id = $4",
            "requires_action",
            stripe_data["checkoutSessionId"],
            stripe_data["checkoutUrl"],
            payment_id,
        )

        service_response = {
            "status": True,
            "message": "Stripe checkout in progress",
            "data": {
                "checkoutUrl": stripe_data["checkoutUrl"]
            }
        }

        await idempotency_service.save_payload(
            redis_client,
            redis_key,
            {
                "key": idempotency_key,
                "state": "completed",
                "requestHash": request_hash,
                "orderId": order_id,
                "paymentId": payment_id,
                "serviceResponse": service_response,
            }
        )

        return service_response
    except ValueError as e:
        logger.error(e)
        return await _handle_error(
            redis_client,
            redis_key,
            idempotency_service,
            idempotency_key,
            request_hash,
            order_id,
            payment_id,
            str(e),
        )
    except Exception as e:
        logger.error(e)

        return await _handle_error(
            redis_client,
            redis_key,
            idempotency_service,
            idempotency_key,
            request_hash,
            order_id,
            payment_id,
            "Internal server error",
        )
