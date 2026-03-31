import asyncpg

from fastapi import APIRouter, Depends

from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from dependencies import checkout, common
from functions.utils.utils import default_response
from schemas.checkout import CheckoutContextData
from services.checkout import checkout_service

router = APIRouter()


@router.post("/stripe")
async def start_stripe_checkout(
    checkout_context: CheckoutContextData = Depends(checkout.validate_checkout_context),
    idempotency_key: str = Depends(common.get_idempotency_key),
    conn: asyncpg.Connection = Depends(postgresql.get_db),
    redis_client=Depends(redis_cache.get_redis),
):
    return await default_response(
        checkout_service.start_stripe_checkout,
        [conn, redis_client, checkout_context, idempotency_key],
    )
