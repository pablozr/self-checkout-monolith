from typing import Any


def success_response(message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": True, "message": message, "data": data or {}}


def error_response(message: str) -> dict[str, Any]:
    return {"status": False, "message": message, "data": {}}
