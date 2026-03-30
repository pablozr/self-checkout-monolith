from typing import cast

from fastapi import Depends, HTTPException, Request

from core.config.config import (
    ANON_SESSION_TTL_SECONDS,
    COOKIE_ANON_SESSION,
    REDIS_SESSION_PREFIX,
)
from core.redis.redis import redis_cache
from schemas.cart import CartData, CartSessionContext, is_cart_data
from services.cache import cache_service


async def _load_session_context(request: Request, redis_client) -> CartSessionContext | None:
    token = request.cookies.get(COOKIE_ANON_SESSION)
    if not token:
        return None

    key = f"{REDIS_SESSION_PREFIX}:{token}"
    session = await cache_service.get_by_key(key, redis_client)
    if not is_cart_data(session):
        return None

    cart_session = cast(CartData, session)
    await redis_client.expire(key, ANON_SESSION_TTL_SECONDS)

    context: CartSessionContext = {"token": token, "session": cart_session}
    return context


async def validate_session(
    request: Request,
    redis_client=Depends(redis_cache.get_redis),
) -> CartSessionContext:
    session_context = await _load_session_context(request, redis_client)
    if not session_context:
        raise HTTPException(status_code=401, detail="Session not found")

    return session_context


async def get_optional_session_context(
    request: Request,
    redis_client=Depends(redis_cache.get_redis),
) -> CartSessionContext | None:
    return await _load_session_context(request, redis_client)
