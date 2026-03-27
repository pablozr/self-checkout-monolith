import asyncpg
from fastapi import APIRouter, Depends

from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from dependencies import session
from dependencies.rate_limit import CART_MUTATION_RATE_LIMIT_DEPS
from functions.utils.utils import default_response
from schemas.cart import CartAddItemRequest, CartSessionContext, CartUpdateItemRequest
from services.cart import cart_service

router = APIRouter()


@router.get("")
async def get_cart(
    session_context: CartSessionContext = Depends(session.validate_session),
):
    return await default_response(cart_service.get_cart, [session_context])


@router.post("/items", dependencies=CART_MUTATION_RATE_LIMIT_DEPS)
async def add_item(
    data: CartAddItemRequest,
    session_context: CartSessionContext = Depends(session.validate_session),
    conn: asyncpg.Connection = Depends(postgresql.get_db),
    redis_client=Depends(redis_cache.get_redis),
):
    return await default_response(
        cart_service.add_item,
        [conn, redis_client, session_context, data.product_id, data.quantity],
    )


@router.put("/items/{product_id}", dependencies=CART_MUTATION_RATE_LIMIT_DEPS)
async def update_item_quantity(
    product_id: int,
    data: CartUpdateItemRequest,
    session_context: CartSessionContext = Depends(session.validate_session),
    redis_client=Depends(redis_cache.get_redis),
):
    return await default_response(
        cart_service.update_item_quantity,
        [redis_client, session_context, product_id, data.quantity],
    )


@router.delete("/items/{product_id}", dependencies=CART_MUTATION_RATE_LIMIT_DEPS)
async def remove_item(
    product_id: int,
    session_context: CartSessionContext = Depends(session.validate_session),
    redis_client=Depends(redis_cache.get_redis),
):
    return await default_response(
        cart_service.remove_item,
        [redis_client, session_context, product_id],
    )


@router.delete("", dependencies=CART_MUTATION_RATE_LIMIT_DEPS)
async def clear_cart(
    session_context: CartSessionContext = Depends(session.validate_session),
    redis_client=Depends(redis_cache.get_redis),
):
    return await default_response(cart_service.clear_cart, [redis_client, session_context])
