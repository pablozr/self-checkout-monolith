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
    # One queue per connected admin client; SSE manager pushes events into it.
    queue = await sse_manager.subscribe_admin()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    # Wait for the next domain event routed through Redis -> SSEManager.
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    event_name = str(payload.get("event", "message"))
                    data = json.dumps(payload, default=str)

                    # SSE frame format: event name + serialized payload.
                    yield f"event: {event_name}\ndata: {data}\n\n"

                except asyncio.TimeoutError:
                    # Keep connection alive when there are no business events.
                    yield "event: ping\ndata: {}\n\n"

        finally:
            # Always remove disconnected client queue to avoid leaks.
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
