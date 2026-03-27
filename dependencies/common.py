from fastapi import Header, HTTPException


async def get_idempotency_key(
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> str:
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency key is required")
    return idempotency_key
