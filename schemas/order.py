from typing import TypedDict


class OrderItemInsert(TypedDict):
    order_id: int
    product_id: int
    name: str
    quantity: int
    unit_price: float
    line_total: float
