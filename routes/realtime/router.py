import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from core.sse.sse_manager import sse_manager
from dependencies import auth

router = APIRouter()


@router.get("/orders")
async def stream_admin_orders(
    request: Request,
    _: dict = Depends(auth.require_admin_rank),
):
    queue = await sse_manager.subscribe_admin()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    event_name = str(payload.get("event", "message"))
                    data = json.dumps(payload, default=str)

                    yield f"event: {event_name}\ndata: {data}\n\n"

                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"

        finally:
            await sse_manager.unsubscribe_admin(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
