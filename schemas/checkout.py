from typing import TypedDict


class CheckoutItemData(TypedDict):
    productId: int
    name: str
    quantity: int
    unitPrice: float
    lineTotal: float


class CheckoutContextData(TypedDict):
    sessionToken: str
    tableId: int
    items: list[CheckoutItemData]
    subtotal: float
    total: float
