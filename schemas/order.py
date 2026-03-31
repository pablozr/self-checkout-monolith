from decimal import Decimal
from typing import TypedDict


class OrderItemInsert(TypedDict):
    order_id: int
    product_id: int
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
