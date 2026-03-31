from decimal import Decimal
from typing import TypedDict


class CheckoutItemData(TypedDict):
    productId: int
    name: str
    quantity: int
    unitPrice: Decimal
    lineTotal: Decimal


class CheckoutContextData(TypedDict):
    sessionToken: str
    tableId: int
    items: list[CheckoutItemData]
    subtotal: Decimal
    total: Decimal
