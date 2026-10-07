"""
Integração real: Postgres (`stripe_events` UNIQUE), Redis Pub/Sub e fila do SSE manager.

Requisitos:
  - `docker compose up -d` (postgres, redis, …)
  - `.env` com `STRIPE_WEBHOOK_SECRET` alinhado ao ambiente
  - `schema.sql` aplicado na base (`DB_NAME` no `.env`, ex.: `restaurant_db`)

Correr só estes testes:

  set INTEGRATION_TESTS=1
  pytest tests/integration/test_docker_live.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import asyncpg
import pytest
import redis.asyncio as redis_lib

from core.config.config import REDIS_SSE_ADMIN_ORDERS_CHANNEL, settings
from core.redis.redis import redis_cache
from core.sse.sse_manager import sse_manager
from services.stripe import webhook_service
from tests.integration.docker_live_helpers import (
    build_checkout_completed_event,
    cleanup_integration_rows,
    integration_dsn,
    integration_enabled,
    seed_pending_order_with_payment,
    stripe_signature,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
async def pg_pool():
    if not integration_enabled():
        pytest.skip(
            "Integração desligada: INTEGRATION_TESTS=1 e STRIPE_WEBHOOK_SECRET no .env",
        )
    try:
        pool = await asyncpg.create_pool(
            dsn=integration_dsn(),
            min_size=2,
            max_size=30,
        )
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres indisponível ({exc!s})")
    try:
        yield pool
    finally:
        await pool.close()


async def _redis_client():
    client = redis_lib.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )
    await client.ping()
    return client


@pytest.fixture
async def redis_client():
    if not integration_enabled():
        pytest.skip(
            "Integração desligada: INTEGRATION_TESTS=1 e STRIPE_WEBHOOK_SECRET no .env",
        )
    try:
        client = await _redis_client()
    except Exception as exc:
        pytest.skip(f"Redis indisponível ({exc!s})")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def redis_sse_stack():
    if not integration_enabled():
        pytest.skip(
            "Integração desligada: INTEGRATION_TESTS=1 e STRIPE_WEBHOOK_SECRET no .env",
        )
    await sse_manager.disconnect()
    try:
        await redis_cache.disconnect()
    except Exception:
        pass
    try:
        await redis_cache.connect()
    except Exception as exc:
        pytest.skip(f"Redis indisponível ({exc!s})")
    await sse_manager.connect(redis_cache.redis)
    try:
        yield redis_cache.redis
    finally:
        await sse_manager.disconnect()
        await redis_cache.disconnect()


def _event_body(ctx: dict, event_id: str) -> bytes:
    payload = build_checkout_completed_event(
        event_id=event_id,
        order_id=ctx["order_id"],
        payment_id=ctx["payment_id"],
        table_id=ctx["table_id"],
        checkout_session_id=ctx["checkout_session_id"],
    )
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def _collect_channel_messages(pubsub, *, seconds: float, order_id: int) -> list[dict]:
    deadline = time.monotonic() + seconds
    out: list[dict] = []
    while time.monotonic() < deadline:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.25)
        if not msg or msg.get("type") != "message":
            continue
        data = json.loads(msg["data"])
        if data.get("event") == "order_paid" and data.get("data", {}).get("orderId") == order_id:
            out.append(data)
    return out


async def test_webhook_dedupe_sequential_unique_constraint(pg_pool, redis_client):
    event_id = f"evt_live_seq_{uuid.uuid4().hex}"
    async with pg_pool.acquire() as conn:
        ctx = await seed_pending_order_with_payment(conn)
    body = _event_body(ctx, event_id)
    sig = stripe_signature(body, settings.STRIPE_WEBHOOK_SECRET)

    try:
        async with pg_pool.acquire() as conn:
            r1 = await webhook_service.handle_event(conn, redis_client, body, sig)
            r2 = await webhook_service.handle_event(conn, redis_client, body, sig)

            assert r1["status"] is True
            assert r1["message"] == "Event processed successfully"
            assert r2["status"] is True
            assert r2["message"] == "Event already processed"

            n = await conn.fetchval(
                "SELECT COUNT(*) FROM stripe_events WHERE event_id = $1",
                event_id,
            )
            assert n == 1

            row = await conn.fetchrow(
                "SELECT status FROM orders WHERE id = $1",
                ctx["order_id"],
            )
            assert row["status"] == "paid"
    finally:
        async with pg_pool.acquire() as conn:
            await cleanup_integration_rows(
                conn,
                event_ids=[event_id],
                order_id=ctx["order_id"],
                table_pk=ctx["table_pk"],
            )


async def test_webhook_concurrent_same_event_id_single_publish(pg_pool, redis_client):
    event_id = f"evt_live_conc_{uuid.uuid4().hex}"
    async with pg_pool.acquire() as conn:
        ctx = await seed_pending_order_with_payment(conn)
    body = _event_body(ctx, event_id)
    sig = stripe_signature(body, settings.STRIPE_WEBHOOK_SECRET)

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(REDIS_SSE_ADMIN_ORDERS_CHANNEL)
    for _ in range(30):
        m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if m is None:
            break

    async def one_webhook():
        async with pg_pool.acquire() as c:
            return await webhook_service.handle_event(c, redis_client, body, sig)

    try:
        n = 25
        results = await asyncio.gather(*[one_webhook() for _ in range(n)])

        success = sum(1 for r in results if r.get("message") == "Event processed successfully")
        dup = sum(1 for r in results if r.get("message") == "Event already processed")
        assert success == 1
        assert dup == n - 1

        paid_msgs = await _collect_channel_messages(
            pubsub,
            seconds=5.0,
            order_id=ctx["order_id"],
        )
        assert len(paid_msgs) == 1
    finally:
        await pubsub.unsubscribe(REDIS_SSE_ADMIN_ORDERS_CHANNEL)
        await pubsub.aclose()
        async with pg_pool.acquire() as conn:
            await cleanup_integration_rows(
                conn,
                event_ids=[event_id],
                order_id=ctx["order_id"],
                table_pk=ctx["table_pk"],
            )


async def test_sse_manager_queue_receives_webhook_fanout(pg_pool, redis_sse_stack):
    redis_client = redis_sse_stack
    event_id = f"evt_live_sse_{uuid.uuid4().hex}"
    async with pg_pool.acquire() as conn:
        ctx = await seed_pending_order_with_payment(conn)
    body = _event_body(ctx, event_id)
    sig = stripe_signature(body, settings.STRIPE_WEBHOOK_SECRET)

    queue = await sse_manager.subscribe_admin()
    await asyncio.sleep(0.15)

    try:
        async with pg_pool.acquire() as conn:
            result = await webhook_service.handle_event(conn, redis_client, body, sig)
        assert result["message"] == "Event processed successfully"

        payload = await asyncio.wait_for(queue.get(), timeout=10.0)
        assert payload["event"] == "order_paid"
        assert payload["data"] == {
            "orderId": ctx["order_id"],
            "paymentId": ctx["payment_id"],
            "tableId": ctx["table_id"],
        }
    finally:
        await sse_manager.unsubscribe_admin(queue)
        async with pg_pool.acquire() as conn:
            await cleanup_integration_rows(
                conn,
                event_ids=[event_id],
                order_id=ctx["order_id"],
                table_pk=ctx["table_pk"],
            )
