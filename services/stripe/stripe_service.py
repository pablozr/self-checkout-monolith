import asyncio
from typing import Any

import stripe

from core.config.config import settings
from core.logger.logger import logger
from schemas.checkout import CheckoutContextData, CheckoutItemData
from services.shared.money import to_minor_units
from services.shared.response import error_response


def _build_line_items(
        items: list[CheckoutItemData],
        currency: str,
) -> list[dict[str, Any]]:
    line_items: list[dict[str, Any]] = []

    for item in items:
        if item["quantity"] <= 0:
            raise ValueError(f"Invalid quantity for product {item['productId']}")

        line_items.append(
            {
                "quantity": item["quantity"],
                "price_data": {
                    "currency": currency,
                    "unit_amount": to_minor_units(item["unitPrice"]),
                    "product_data": {"name": item["name"]},
                },
            }
        )

    return line_items


def _append_query(url: str, query: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def _build_urls(order_id: int, payment_id: int) -> tuple[str, str]:
    success_query = (
        f"session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}&payment_id={payment_id}"
    )
    cancel_query = f"order_id={order_id}&payment_id={payment_id}"

    success_url = _append_query(settings.STRIPE_CHECKOUT_SUCCESS_URL, success_query)
    cancel_url = _append_query(settings.STRIPE_CHECKOUT_CANCEL_URL, cancel_query)

    return success_url, cancel_url


def _create_checkout_session(
        params: dict[str, Any],
        idempotency_key: str,
) -> stripe.checkout.Session:
    client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    request_options = {"idempotency_key": idempotency_key} if idempotency_key else None

    return client.v1.checkout.sessions.create(
        params=params,
        options=request_options,
    )


async def initiate_checkout_session(
        checkout_context: CheckoutContextData,
        order_id: int,
        payment_id: int,
        idempotency_key: str,
) -> dict[str, Any]:
    try:
        if not settings.STRIPE_SECRET_KEY:
            return error_response("Stripe secret key is not configured")

        if not settings.STRIPE_CHECKOUT_SUCCESS_URL or not settings.STRIPE_CHECKOUT_CANCEL_URL:
            return error_response("Stripe checkout URLs are not configured")

        currency = settings.STRIPE_CURRENCY.strip().lower()
        if len(currency) != 3:
            return error_response("Invalid Stripe currency configuration")

        line_items = _build_line_items(checkout_context["items"], currency)
        if not line_items:
            return error_response("Cart is empty")

        success_url, cancel_url = _build_urls(order_id, payment_id)

        metadata = {
            "orderId": str(order_id),
            "paymentId": str(payment_id),
            "tableId": str(checkout_context["tableId"])
        }

        session_params: dict[str, Any] = {
            "mode": "payment",
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(order_id),
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
        }

        # Stripe's Python library does not support async, so we run the blocking call in a thread to avoid blocking the event loop.
        session = await asyncio.to_thread(
            _create_checkout_session,
            session_params,
            idempotency_key,
        )

        checkout_session_id = getattr(session, "id", None)
        checkout_url = getattr(session, "url", None)
        payment_intent_id = getattr(session, "payment_intent", None)

        if not checkout_session_id or not checkout_url:
            return error_response("Stripe returned an invalid checkout session")

        return {
            "status": True,
            "message": "Stripe checkout session created successfully",
            "data": {
                "checkoutSessionId": checkout_session_id,
                "checkoutUrl": checkout_url,
                "paymentIntentId": payment_intent_id,
            },
        }
    except stripe.StripeError as e:
        logger.exception(e)
        message = getattr(e, "user_message", None) or str(e)
        return error_response(message)
    except ValueError as e:
        logger.error(e)
        return error_response(str(e))
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")
