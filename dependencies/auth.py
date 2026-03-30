import asyncpg
from fastapi import Depends, HTTPException, Request

from core.config.config import (
    COOKIE_AUTH,
    COOKIE_AUTH_RESET,
    ROLE_RANK_BY_NAME,
)
from core.logger.logger import logger
from core.postgresql.postgresql import postgresql
from core.security.security import verify_token


async def validate_token(
    request: Request,
    conn: asyncpg.Connection,
    check_can_update: bool = False,
    reset_cookie: bool = False,
    expected_type: str = "auth",
) -> dict:
    try:
        cookie_key = COOKIE_AUTH if not reset_cookie else COOKIE_AUTH_RESET
        token = request.cookies.get(cookie_key)

        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user = await verify_token(
            token,
            conn=conn,
            check_can_update=check_can_update,
            expected_type=expected_type,
        )

        if user is None:
            raise HTTPException(status_code=401, detail="Token has expired")

        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        request.state.token = token

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=401, detail="Invalid token")


async def validate_token_to_update_password(
    request: Request, conn: asyncpg.Connection = Depends(postgresql.get_db)
) -> dict:
    return await validate_token(
        request,
        conn,
        check_can_update=True,
        reset_cookie=True,
        expected_type="reset",
    )


async def validate_token_to_validate_code(
    request: Request, conn: asyncpg.Connection = Depends(postgresql.get_db)
) -> dict:
    return await validate_token(
        request,
        conn,
        check_can_update=False,
        reset_cookie=True,
        expected_type="reset",
    )


async def validate_token_wrapper(
    request: Request, conn: asyncpg.Connection = Depends(postgresql.get_db)
) -> dict:
    return await validate_token(request, conn)


def require_minimum_rank(minimum_rank: int):
    async def dependency(user: dict = Depends(validate_token_wrapper)) -> dict:
        rank = ROLE_RANK_BY_NAME.get(user.get("role", "").upper(), 0)

        if rank < minimum_rank:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return dependency


def require_admin_rank():
    return require_minimum_rank(2)
