from typing import TypedDict

import asyncpg


class ProductData(TypedDict):
    productId: int
    name: str
    description: str
    unitPrice: float
    isAvailable: bool


def product_from_row(row: asyncpg.Record) -> ProductData:
    return {
        "productId": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "unitPrice": float(row["price"]),
        "isAvailable": row["is_available"],
    }
