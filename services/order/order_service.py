from decimal import Decimal
from typing import Any, Sequence

import asyncpg

from schemas.checkout import CheckoutItemData
from schemas.order import OrderItemInsert


async def create_order(
    conn: asyncpg.Connection,
    table_id: int,
    subtotal: Decimal,
    total: Decimal,
    status: str,
) -> int:
    query = """
            INSERT INTO orders (table_id, subtotal, total, status)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """

    order_id = await conn.fetchval(query, table_id, subtotal, total, status)
    if order_id is None:
        raise ValueError("Failed to create order")

    return int(order_id)


async def create_order_items(
    conn: asyncpg.Connection,
    params: Sequence[OrderItemInsert],
) -> None:
    if not params:
        return

    query = """
            INSERT INTO order_items (order_id, product_id, name, quantity, unit_price, line_total)
            VALUES ($1, $2, $3, $4, $5, $6)
            """

    records = [
        (
            item["order_id"],
            item["product_id"],
            item["name"],
            item["quantity"],
            item["unit_price"],
            item["line_total"],
        )
        for item in params
    ]

    await conn.executemany(query, records)


async def create_order_with_items(
    conn: asyncpg.Connection,
    table_id: int,
    subtotal: Decimal,
    total: Decimal,
    status: str,
    items: Sequence[CheckoutItemData],
) -> int:
    if not items:
        raise ValueError("Order must include at least one item")

    order_id = await create_order(conn, table_id, subtotal, total, status)
    order_items_params: list[OrderItemInsert] = [
        {
            "order_id": order_id,
            "product_id": item["productId"],
            "name": item["name"],
            "quantity": item["quantity"],
            "unit_price": item["unitPrice"],
            "line_total": item["lineTotal"],
        }
        for item in items
    ]
    await create_order_items(conn, order_items_params)

    return order_id


async def get_comanda(conn: asyncpg.Connection, order_id: int) -> dict[str, Any]:
    query = """
            SELECT o.id, \
                   o.table_id, \
                   o.subtotal, \
                   o.total, \
                   o.status, \
                   o.created_at, \
                   COALESCE( \
                           json_agg( \
                                   json_build_object( \
                                           'id', oi.id, \
                                           'product_id', oi.product_id, \
                                           'name', oi.name, \
                                           'quantity', oi.quantity, \
                                           'unit_price', oi.unit_price, \
                                           'line_total', oi.line_total \
                                   ) \
                           ) FILTER(WHERE oi.id IS NOT NULL), \
                           '[]' ::json \
                   ) AS items
            FROM orders o
                     LEFT JOIN order_items oi ON oi.order_id = o.id
            WHERE o.id = $1
            GROUP BY o.id, o.table_id, o.subtotal, o.total, o.status, o.created_at \
            """

    row = await conn.fetchrow(query, order_id)
    if not row:
        return {"status": False, "message": "Error retrieving order", "data": {}}
    return {"status": True, "message": "Order retrieved successfully", "data": {**row}}


async def update_order_status(
    conn: asyncpg.Connection,
    order_id: int,
    new_status: str,
    allowed_current_statuses: tuple[str, ...] = ("pending",),
) -> bool:
    query = """
            UPDATE orders
            SET status = $1,
                updated_at = NOW()
            WHERE id = $2
              AND status = ANY($3::text[])
            RETURNING id
            """

    row = await conn.fetchrow(query, new_status, order_id, list(allowed_current_statuses))
    return row is not None
