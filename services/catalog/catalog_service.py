import asyncpg
from core.config.config import PRODUCT_CACHE_TTL_SECONDS, REDIS_PRODUCT_PREFIX
from core.logger.logger import logger
from schemas.product import product_from_row, ProductData
from services.cache import cache_service


async def list_active_products(conn: asyncpg.Connection) -> dict:
    try:
        rows = await conn.fetch(
            """
            SELECT id, name, description, price, is_available
            FROM products
            WHERE is_active = TRUE AND is_available = TRUE
            ORDER BY id ASC
            """
        )

        products = [product_from_row(row) for row in rows]

        return {
            "status": True,
            "message": "Catalog retrieved successfully",
            "data": {"products": products},
        }
    except Exception as e:
        logger.exception(e)
        return {"status": False, "message": "Internal server error", "data": {}}


async def get_product_by_id(conn: asyncpg.Connection, product_id: int, redis_client) -> dict:
    try:
        cache_key = f"{REDIS_PRODUCT_PREFIX}:{product_id}"
        cached = await cache_service.get_by_key(cache_key, redis_client)

        if cached:
            if not cached.get("isAvailable", False):
                return {"status": False, "message": "Product unavailable", "data": {}}
            return {
                "status": True,
                "message": "Product retrieved successfully",
                "data": {"product": cached},
            }

        row = await conn.fetchrow(
            """
            SELECT id, name, description, price, is_available
            FROM products
            WHERE id = $1 AND is_active = TRUE
            """,
            product_id,
        )

        if not row:
            return {"status": False, "message": "Product not found", "data": {}}

        product = product_from_row(row)

        await cache_service.set_by_key(
            cache_key,
            PRODUCT_CACHE_TTL_SECONDS,
            {**product},
            redis_client,
        )

        if not product["isAvailable"]:
            return {"status": False, "message": "Product unavailable", "data": {}}

        return {
            "status": True,
            "message": "Product retrieved successfully",
            "data": {"product": product},
        }
    except Exception as e:
        logger.exception(e)
        return {"status": False, "message": "Internal server error", "data": {}}
