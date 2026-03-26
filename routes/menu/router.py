import asyncpg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.config.config import ANON_SESSION_TTL_SECONDS, COOKIE_ANON_SESSION
from core.postgresql.postgresql import postgresql
from core.redis.redis import redis_cache
from core.security import session
from core.security.rate_limit import MENU_BOOTSTRAP_RATE_LIMIT_DEPS
from schemas.cart import CartSessionContext
from services.cart import cart_service
from services.catalog import catalog_service
from services.table import table_service

router = APIRouter()


@router.get("/", dependencies=MENU_BOOTSTRAP_RATE_LIMIT_DEPS)
async def load_menu(
    table: int = Query(gt=0),
    session_context: CartSessionContext | None = Depends(
        session.get_optional_session_context
    ),
    conn: asyncpg.Connection = Depends(postgresql.get_db),
    redis_client=Depends(redis_cache.get_redis),
):
    table_response = await table_service.get_active_table_by_number(conn, table)
    if not table_response["status"]:
        return JSONResponse(status_code=400, content={"detail": table_response["message"]})

    session_response = await cart_service.bootstrap_session(
        redis_client,
        table_response["data"]["table"]["tableId"],
        session_context,
    )
    if not session_response["status"]:
        return JSONResponse(
            status_code=400, content={"detail": session_response["message"]}
        )

    catalog_response = await catalog_service.list_active_products(conn)
    if not catalog_response["status"]:
        return JSONResponse(
            status_code=400, content={"detail": catalog_response["message"]}
        )

    response = JSONResponse(
        status_code=200,
        content={
            "message": "Menu loaded successfully",
            "data": {
                "table": table_response["data"]["table"],
                "products": catalog_response["data"]["products"],
                "cart": session_response["data"]["cart"],
            },
        },
    )
    response.set_cookie(
        key=COOKIE_ANON_SESSION,
        value=session_response["data"]["sessionToken"],
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=ANON_SESSION_TTL_SECONDS,
    )
    return response
