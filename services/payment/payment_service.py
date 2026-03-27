from typing import Any

from schemas.checkout import CheckoutContextData


async def process_checkout_payment(checkout_context: CheckoutContextData) -> dict[str, Any]:
    _ = checkout_context
    return {"state": "pending", "reference": None}
