from typing import Any, TypeGuard, TypedDict

from pydantic import BaseModel, Field


class CartAddItemRequest(BaseModel):
    product_id: int = Field(alias="productId", gt=0)
    quantity: int = Field(gt=0, le=100)

    model_config = {"populate_by_name": True}


class CartUpdateItemRequest(BaseModel):
    quantity: int = Field(gt=0, le=100)


class CartItemData(TypedDict):
    productId: int
    name: str
    quantity: int
    unitPrice: float
    lineTotal: float


class CartData(TypedDict):
    tableId: int
    items: list[CartItemData]
    subtotal: float
    createdAt: str


class CartSessionContext(TypedDict):
    token: str
    session: CartData


class CartServiceData(TypedDict, total=False):
    sessionToken: str
    cart: CartData


class CartServiceResponse(TypedDict):
    status: bool
    message: str
    data: CartServiceData


def is_cart_data(value: Any) -> TypeGuard[CartData]:
    if not isinstance(value, dict):
        return False

    table_id = value.get("tableId")
    items = value.get("items")
    subtotal = value.get("subtotal")
    created_at = value.get("createdAt")

    if not isinstance(table_id, int):
        return False
    if not isinstance(items, list):
        return False
    if not isinstance(subtotal, (int, float)):
        return False
    if not isinstance(created_at, str):
        return False

    for item in items:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("productId"), int):
            return False
        if not isinstance(item.get("name"), str):
            return False
        if not isinstance(item.get("quantity"), int):
            return False
        if not isinstance(item.get("unitPrice"), (int, float)):
            return False
        if not isinstance(item.get("lineTotal"), (int, float)):
            return False

    return True
