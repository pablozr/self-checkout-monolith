import asyncio
import json
from typing import Any

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from core.config.config import REDIS_SSE_ADMIN_ORDERS_CHANNEL
from core.logger.logger import logger


class SSEManager:
    def __init__(self) -> None:
        self.pubsub: PubSub | None = None
        self.listener_task: asyncio.Task[None] | None = None
        # Each connected admin SSE client receives its own in-memory queue.
        self.admin_clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self.lock = asyncio.Lock()
        self.running = False

    async def connect(self, redis_client: redis.Redis) -> None:
        if self.running:
            return

        # Single Redis subscription feeds all local SSE clients.
        self.pubsub = redis_client.pubsub()
        await self.pubsub.subscribe(REDIS_SSE_ADMIN_ORDERS_CHANNEL)

        self.running = True
        self.listener_task = asyncio.create_task(
            self._listen_loop(),
            name="sse-admin-listener",
        )

        logger.info(
            "SSE manager connected and subscribed to channel: %s",
            REDIS_SSE_ADMIN_ORDERS_CHANNEL,
        )

    async def disconnect(self) -> None:
        if not self.running:
            return

        self.running = False

        if self.listener_task is not None:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
            finally:
                self.listener_task = None

        if self.pubsub is not None:
            try:
                await self.pubsub.unsubscribe(REDIS_SSE_ADMIN_ORDERS_CHANNEL)
            except Exception as e:
                logger.exception(e)

            try:
                await self.pubsub.aclose()
            except Exception as e:
                logger.exception(e)
            finally:
                self.pubsub = None

        async with self.lock:
            self.admin_clients.clear()

        logger.info("SSE manager disconnected")

    async def subscribe_admin(self) -> asyncio.Queue[dict[str, Any]]:
        # Bounded queue to protect memory if client reads slower than publish rate.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        async with self.lock:
            self.admin_clients.add(queue)
        return queue

    async def unsubscribe_admin(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self.lock:
            self.admin_clients.discard(queue)

    async def _listen_loop(self) -> None:
        if self.pubsub is None:
            return

        try:
            while self.running:
                try:
                    # Poll Pub/Sub with timeout so cancellation and shutdown stay responsive.
                    message = await self.pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if not message:
                        continue

                    channel = message.get("channel")
                    if channel != REDIS_SSE_ADMIN_ORDERS_CHANNEL:
                        continue

                    payload = self._parse_payload(message.get("data"))
                    if payload is None:
                        continue

                    # Broadcast parsed payload to all connected admin client queues.
                    await self._fanout_admin(payload)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(e)

        except asyncio.CancelledError:
            logger.info("SSE admin listener cancelled")
            raise

    @staticmethod
    def _parse_payload(raw_data: Any) -> dict[str, Any] | None:
        try:
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            if not isinstance(raw_data, str):
                logger.error("Invalid SSE payload type: %s", type(raw_data).__name__)
                return None

            payload = json.loads(raw_data)
            if not isinstance(payload, dict):
                logger.error("Invalid SSE payload: expected object")
                return None

            event = payload.get("event")
            data = payload.get("data")
            if not isinstance(event, str) or not isinstance(data, dict):
                logger.error("Invalid SSE payload fields: event/data")
                return None

            return payload

        except Exception as e:
            logger.exception(e)
            return None

    async def _fanout_admin(self, payload: dict[str, Any]) -> None:
        async with self.lock:
            queues = list(self.admin_clients)

        if not queues:
            return

        for queue in queues:
            try:
                if queue.full():
                    # Drop oldest event for this client to keep newest state flowing.
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

                queue.put_nowait(payload)
            except Exception as e:
                logger.exception(e)


sse_manager = SSEManager()
