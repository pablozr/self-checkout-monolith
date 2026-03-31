import asyncpg

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from services.stripe import webhook_service

router = APIRouter()


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    conn: asyncpg.Connection = Depends(postgresql.get_db),
    redis_client=Depends(redis_cache.get_redis),
):
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    response = await webhook_service.handle_event(
        conn=conn,
        redis_client=redis_client,
        payload=payload,
        signature=signature,
    )

    if not response["status"]:
        message = response["message"]
        status_code = 500 if message in {
            "Stripe webhook secret is not configured",
            "Error processing event",
        } else 400
        return JSONResponse(status_code=status_code, content={"detail": message})

    return JSONResponse(
        status_code=200,
        content={"message": response["message"], "data": response["data"]},
    )
