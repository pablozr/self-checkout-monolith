import asyncpg
from fastapi import Depends, HTTPException

from core.postgresql.postgresql import postgresql
from dependencies.session import validate_session
from schemas.cart import CartSessionContext
from schemas.checkout import CheckoutContextData
from services.checkout import checkout_service


async def validate_checkout_context(
    session_context: CartSessionContext = Depends(validate_session),
    conn: asyncpg.Connection = Depends(postgresql.get_db),
) -> CheckoutContextData:
    checkout_response = await checkout_service.build_checkout_context(conn, session_context)
    if not checkout_response["status"]:
        raise HTTPException(status_code=400, detail=checkout_response["message"])

    return checkout_response["data"]["checkout"]
