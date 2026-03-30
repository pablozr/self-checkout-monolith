from datetime import datetime, timedelta, timezone

import asyncpg
import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from core.config.config import settings
from core.logger.logger import logger
from services.user import user_service


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload.update({"exp": expire})

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_google_token(token: str) -> dict | None:
    try:
        return id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except Exception:
        return None


async def verify_token(
    token: str,
    conn: asyncpg.Connection,
    check_can_update: bool = False,
    expected_type: str = "auth",
) -> dict | bool | None:
    try:
        if token.startswith("Bearer "):
            token = token[7:]

        payload = decode_access_token(token)

        if payload.get("type") != expected_type:
            raise jwt.InvalidTokenError("Token type mismatch")

        if expected_type == "reset" and not check_can_update:
            if payload.get("canUpdate") is not False:
                raise jwt.InvalidTokenError("Invalid reset token stage")

        if not payload.get("userId"):
            raise jwt.InvalidTokenError("Invalid token payload")

        response = await user_service.get_one_user(conn, payload["userId"])

        if response["status"] is None or not response["status"]:
            raise jwt.InvalidSignatureError("User not found")

        if check_can_update:
            if payload.get("canUpdate"):
                return dict(response["data"]["user"])
            raise jwt.InvalidTokenError("User does not have update permissions")

        return dict(response["data"]["user"])

    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        return None
    except jwt.InvalidTokenError:
        logger.error("Invalid token")
        return False
