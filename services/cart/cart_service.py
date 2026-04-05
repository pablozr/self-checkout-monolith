import secrets
from datetime import datetime, timezone

from typing import Any, cast

import asyncpg

from core.config.config import ANON_SESSION_TTL_SECONDS, REDIS_SESSION_PREFIX
from core.logger.logger import logger
from schemas.cart import (
    CartData,
    CartItemData,
    CartSessionContext,
)
from schemas.product import ProductData
from services.cache import cache_service
from services.catalog import catalog_service
from services.shared.response import error_response


def _recalculate_subtotal(items: list[CartItemData]) -> float:
    subtotal = sum(float(item["lineTotal"]) for item in items)
    return round(subtotal, 2)


async def bootstrap_session(
    redis_client,
    table_id: int,
    session_context: CartSessionContext | None,
) -> dict[str, Any]:
    try:
        if session_context:
            existing_token = session_context["token"]
            existing = session_context["session"]
            if existing.get("tableId") == table_id:
                return {
                    "status": True,
                    "message": "Session loaded successfully",
                    "data": {
                        "sessionToken": existing_token,
                        "cart": existing,
                    },
                }

        token = secrets.token_urlsafe(32)
        payload: CartData = {
            "tableId": table_id,
            "items": [],
            "subtotal": 0.0,
            "createdAt": str(datetime.now(timezone.utc)),
        }

        await cache_service.set_by_key(
            f"{REDIS_SESSION_PREFIX}:{token}",
            ANON_SESSION_TTL_SECONDS,
            {**payload},
            redis_client,
        )

        return {
            "status": True,
            "message": "Session created successfully",
            "data": {"sessionToken": token, "cart": payload},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")


async def get_cart(session_context: CartSessionContext) -> dict[str, Any]:
    try:
        session = session_context["session"]

        return {
            "status": True,
            "message": "Cart retrieved successfully",
            "data": {"cart": session},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")


async def add_item(
    conn: asyncpg.Connection,
    redis_client,
    session_context: CartSessionContext,
    product_id: int,
    quantity: int,
) -> dict[str, Any]:
    try:
        token = session_context["token"]
        session = session_context["session"]

        product_response = await catalog_service.get_product_by_id(
            conn, product_id, redis_client
        )
        if not product_response["status"]:
            return error_response(product_response["message"])

        product = cast(ProductData, product_response["data"]["product"])
        items = session["items"]

        existing_item = next(
            (item for item in items if item["productId"] == product_id),
            None,
        )

        if existing_item:
            existing_item["quantity"] += quantity
            existing_item["lineTotal"] = round(
                existing_item["quantity"] * existing_item["unitPrice"], 2
            )
        else:
            unit_price = float(product["unitPrice"])
            items.append(
                {
                    "productId": product["productId"],
                    "name": product["name"],
                    "quantity": quantity,
                    "unitPrice": unit_price,
                    "lineTotal": round(unit_price * quantity, 2),
                }
            )

        session["items"] = items
        session["subtotal"] = _recalculate_subtotal(items)

        await cache_service.set_by_key(
            f"{REDIS_SESSION_PREFIX}:{token}",
            ANON_SESSION_TTL_SECONDS,
            {**session},
            redis_client,
        )

        return {
            "status": True,
            "message": "Item added to cart",
            "data": {"cart": session},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")


async def update_item_quantity(
    redis_client,
    session_context: CartSessionContext,
    product_id: int,
    quantity: int,
) -> dict[str, Any]:
    try:
        token = session_context["token"]
        session = session_context["session"]

        items = session["items"]
        item = next((i for i in items if i["productId"] == product_id), None)
        if not item:
            return error_response("Item not found in cart")

        item["quantity"] = quantity
        item["lineTotal"] = round(item["unitPrice"] * quantity, 2)
        session["subtotal"] = _recalculate_subtotal(items)

        await cache_service.set_by_key(
            f"{REDIS_SESSION_PREFIX}:{token}",
            ANON_SESSION_TTL_SECONDS,
            {**session},
            redis_client,
        )

        return {
            "status": True,
            "message": "Cart item updated successfully",
            "data": {"cart": session},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")


async def remove_item(
    redis_client,
    session_context: CartSessionContext,
    product_id: int,
) -> dict[str, Any]:
    try:
        token = session_context["token"]
        session = session_context["session"]

        items = session["items"]
        new_items = [item for item in items if item["productId"] != product_id]

        if len(new_items) == len(items):
            return error_response("Item not found in cart")

        session["items"] = new_items
        session["subtotal"] = _recalculate_subtotal(new_items)

        await cache_service.set_by_key(
            f"{REDIS_SESSION_PREFIX}:{token}",
            ANON_SESSION_TTL_SECONDS,
            {**session},
            redis_client,
        )

        return {
            "status": True,
            "message": "Item removed from cart",
            "data": {"cart": session},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")


async def clear_cart(redis_client, session_context: CartSessionContext) -> dict[str, Any]:
    try:
        token = session_context["token"]
        session = session_context["session"]

        session["items"] = []
        session["subtotal"] = 0.0

        await cache_service.set_by_key(
            f"{REDIS_SESSION_PREFIX}:{token}",
            ANON_SESSION_TTL_SECONDS,
            {**session},
            redis_client,
        )

        return {
            "status": True,
            "message": "Cart cleared successfully",
            "data": {"cart": session},
        }
    except Exception as e:
        logger.exception(e)
        return error_response("Internal server error")
