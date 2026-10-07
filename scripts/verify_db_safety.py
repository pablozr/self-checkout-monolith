import asyncio
import os
from dataclasses import dataclass
from typing import Mapping

import asyncpg


@dataclass(frozen=True)
class Invariant:
    key: str
    description: str
    sql: str


REQUIRED_INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        key="idx_orders_table_id",
        description="orders must have idx_orders_table_id",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'orders'
                  AND indexname = 'idx_orders_table_id'
            )
        """,
    ),
    Invariant(
        key="idx_orders_created_at",
        description="orders must have idx_orders_created_at",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'orders'
                  AND indexname = 'idx_orders_created_at'
            )
        """,
    ),
    Invariant(
        key="idx_orders_status_created_at",
        description="orders must have idx_orders_status_created_at",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'orders'
                  AND indexname = 'idx_orders_status_created_at'
            )
        """,
    ),
    Invariant(
        key="ux_payments_order_id",
        description="payments must have ux_payments_order_id",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'payments'
                  AND indexname = 'ux_payments_order_id'
            )
        """,
    ),
    Invariant(
        key="idx_payments_status_created_at",
        description="payments must have idx_payments_status_created_at",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'payments'
                  AND indexname = 'idx_payments_status_created_at'
            )
        """,
    ),
    Invariant(
        key="ux_payments_checkout_session_id",
        description="payments must have unique checkout_session_id index",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'payments'
                  AND indexname = 'ux_payments_checkout_session_id'
            )
        """,
    ),
    Invariant(
        key="ux_payments_provider_payment_id",
        description="payments must have unique provider_payment_id index",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'payments'
                  AND indexname = 'ux_payments_provider_payment_id'
            )
        """,
    ),
    Invariant(
        key="idx_stripe_events_event_type_created_at",
        description="stripe_events must have idx_stripe_events_event_type_created_at",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = 'stripe_events'
                  AND indexname = 'idx_stripe_events_event_type_created_at'
            )
        """,
    ),
    Invariant(
        key="payments_order_fk",
        description="payments.order_id must reference orders.id",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_class rt ON rt.oid = c.confrelid
                WHERE t.relname = 'payments'
                  AND rt.relname = 'orders'
                  AND c.contype = 'f'
                  AND EXISTS (
                      SELECT 1
                      FROM unnest(c.conkey) AS key(attnum)
                      JOIN pg_attribute a
                        ON a.attrelid = t.oid
                       AND a.attnum = key.attnum
                      WHERE a.attname = 'order_id'
                  )
            )
        """,
    ),
    Invariant(
        key="payments_status_check",
        description="payments.status must enforce allowed values",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'payments'
                  AND c.contype = 'c'
                  AND pg_get_constraintdef(c.oid) ILIKE '%status%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%pending%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%requires_action%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%paid%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%failed%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%canceled%'
            )
        """,
    ),
    Invariant(
        key="orders_status_check",
        description="orders.status must enforce allowed values",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'orders'
                  AND c.contype = 'c'
                  AND pg_get_constraintdef(c.oid) ILIKE '%status%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%pending%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%paid%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%payment_failed%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%canceled%'
            )
        """,
    ),
    Invariant(
        key="payments_provider_stripe_only_check",
        description="payments.provider must only allow stripe",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'payments'
                  AND c.contype = 'c'
                  AND pg_get_constraintdef(c.oid) ILIKE '%provider%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%stripe%'
            )
        """,
    ),
    Invariant(
        key="payments_optional_identifiers_non_empty_check",
        description=(
            "payments optional identifiers must be non-empty when provided"
        ),
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'payments'
                  AND c.contype = 'c'
                  AND pg_get_constraintdef(c.oid) ILIKE '%checkout_session_id%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%provider_payment_id%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%<> ''''%'
            )
        """,
    ),
    Invariant(
        key="stripe_events_event_id_unique",
        description="stripe_events.event_id must be unique",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'stripe_events'
                  AND c.contype = 'u'
                  AND EXISTS (
                      SELECT 1
                      FROM unnest(c.conkey) AS key(attnum)
                      JOIN pg_attribute a
                        ON a.attrelid = t.oid
                       AND a.attnum = key.attnum
                      WHERE a.attname = 'event_id'
                  )
            )
        """,
    ),
    Invariant(
        key="stripe_events_identifiers_non_empty_check",
        description="stripe_events identifiers must be non-empty",
        sql="""
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'stripe_events'
                  AND c.contype = 'c'
                  AND pg_get_constraintdef(c.oid) ILIKE '%event_id%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%event_type%'
                  AND pg_get_constraintdef(c.oid) ILIKE '%<> ''''%'
            )
        """,
    ),
)


def build_dsn_from_env(env: Mapping[str, str]) -> str:
    host = env["DB_HOST"]
    port = env.get("DB_PORT", "5432")
    user = env["DB_USER"]
    password = env["DB_PASSWORD"]
    database = env["DB_NAME"]
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def collect_failures(results_by_key: dict[str, bool], invariants: tuple[Invariant, ...]) -> list[str]:
    failures: list[str] = []
    for invariant in invariants:
        if not results_by_key.get(invariant.key, False):
            failures.append(f"{invariant.key}: {invariant.description}")
    return failures


async def run_invariant_checks(conn: asyncpg.Connection, invariants: tuple[Invariant, ...]) -> list[str]:
    results_by_key: dict[str, bool] = {}
    for invariant in invariants:
        result = await conn.fetchval(invariant.sql)
        results_by_key[invariant.key] = bool(result)
    return collect_failures(results_by_key, invariants)


async def verify_live_db() -> int:
    dsn = build_dsn_from_env(os.environ)
    conn = await asyncpg.connect(dsn=dsn)
    try:
        failures = await run_invariant_checks(conn=conn, invariants=REQUIRED_INVARIANTS)
    finally:
        await conn.close()

    if failures:
        print("DB safety verification failed:")
        for item in failures:
            print(f"- {item}")
        return 1

    print(f"DB safety verification passed ({len(REQUIRED_INVARIANTS)} checks).")
    return 0


def main() -> int:
    return asyncio.run(verify_live_db())


if __name__ == "__main__":
    raise SystemExit(main())
