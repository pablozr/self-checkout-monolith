from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel


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


class CheckoutCompletedData(BaseModel):
    order_id: int
    payment_id: int
    table_id: int
    session_token: str
    checkout_session_id: str
    payment_intent_id: str | None = None
    amount_total: int | None = None
