import importlib.util
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_db_safety.py"
SPEC = importlib.util.spec_from_file_location("verify_db_safety", MODULE_PATH)
assert SPEC and SPEC.loader
verify_db_safety = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_db_safety)

Invariant = verify_db_safety.Invariant
build_dsn_from_env = verify_db_safety.build_dsn_from_env
collect_failures = verify_db_safety.collect_failures
run_invariant_checks = verify_db_safety.run_invariant_checks
verify_live_db = verify_db_safety.verify_live_db
REQUIRED_INVARIANTS = verify_db_safety.REQUIRED_INVARIANTS


def test_required_invariants_contains_phase_2_safety_keys() -> None:
    keys = {invariant.key for invariant in REQUIRED_INVARIANTS}

    assert {
        "idx_orders_table_id",
        "idx_orders_created_at",
        "idx_orders_status_created_at",
        "ux_payments_order_id",
        "idx_payments_status_created_at",
        "ux_payments_checkout_session_id",
        "ux_payments_provider_payment_id",
        "idx_stripe_events_event_type_created_at",
        "stripe_events_event_id_unique",
        "payments_order_fk",
        "payments_status_check",
        "orders_status_check",
        "payments_provider_stripe_only_check",
        "payments_optional_identifiers_non_empty_check",
        "stripe_events_identifiers_non_empty_check",
    }.issubset(keys)


def test_build_dsn_from_env_uses_db_vars_and_default_port() -> None:
    env = {
        "DB_HOST": "localhost",
        "DB_USER": "postgres",
        "DB_PASSWORD": "postgres",
        "DB_NAME": "self_checkout",
    }

    dsn = build_dsn_from_env(env)

    assert dsn == "postgresql://postgres:postgres@localhost:5432/self_checkout"


def test_collect_failures_returns_only_missing_or_false_invariants() -> None:
    invariants = (
        Invariant(
            key="idx_orders_table_id",
            description="orders must have idx_orders_table_id",
            sql="SELECT true",
        ),
        Invariant(
            key="ux_payments_checkout_session_id",
            description="payments must have unique checkout_session_id index",
            sql="SELECT true",
        ),
    )

    failures = collect_failures(
        results_by_key={
            "idx_orders_table_id": True,
            "ux_payments_checkout_session_id": False,
        },
        invariants=invariants,
    )

    assert failures == ["ux_payments_checkout_session_id: payments must have unique checkout_session_id index"]


@pytest.mark.asyncio
async def test_run_invariant_checks_runs_each_sql_and_reports_failures() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[True, False])
    invariants = (
        Invariant(key="ok_idx", description="first check", sql="SELECT true"),
        Invariant(key="missing_idx", description="second check", sql="SELECT false"),
    )

    failures = await run_invariant_checks(conn=conn, invariants=invariants)

    assert failures == ["missing_idx: second check"]
    assert conn.fetchval.await_count == 2


@pytest.mark.asyncio
async def test_verify_live_db_returns_zero_when_all_invariants_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()

    monkeypatch.setattr(verify_db_safety, "build_dsn_from_env", lambda _: "postgresql://test")
    monkeypatch.setattr(verify_db_safety.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(verify_db_safety, "run_invariant_checks", AsyncMock(return_value=[]))

    result = await verify_live_db()

    assert result == 0
    verify_db_safety.asyncpg.connect.assert_awaited_once_with(dsn="postgresql://test")
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_live_db_success_prints_success_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = AsyncMock()

    monkeypatch.setattr(verify_db_safety, "build_dsn_from_env", lambda _: "postgresql://test")
    monkeypatch.setattr(verify_db_safety.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(verify_db_safety, "run_invariant_checks", AsyncMock(return_value=[]))

    result = await verify_live_db()

    captured = capsys.readouterr()
    assert result == 0
    assert "DB safety verification passed" in captured.out


@pytest.mark.asyncio
async def test_verify_live_db_returns_one_when_any_invariant_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()

    monkeypatch.setattr(verify_db_safety, "build_dsn_from_env", lambda _: "postgresql://test")
    monkeypatch.setattr(verify_db_safety.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(
        verify_db_safety,
        "run_invariant_checks",
        AsyncMock(return_value=["payments_order_fk: payments.order_id must reference orders.id"]),
    )

    result = await verify_live_db()

    assert result == 1
    verify_db_safety.asyncpg.connect.assert_awaited_once_with(dsn="postgresql://test")
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_live_db_failure_prints_header_and_bullets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = AsyncMock()
    failures = [
        "payments_order_fk: payments.order_id must reference orders.id",
        "orders_status_check: orders.status must enforce allowed values",
    ]

    monkeypatch.setattr(verify_db_safety, "build_dsn_from_env", lambda _: "postgresql://test")
    monkeypatch.setattr(verify_db_safety.asyncpg, "connect", AsyncMock(return_value=conn))
    monkeypatch.setattr(verify_db_safety, "run_invariant_checks", AsyncMock(return_value=failures))

    result = await verify_live_db()

    captured = capsys.readouterr()
    assert result == 1
    assert "DB safety verification failed:" in captured.out
    assert "- payments_order_fk: payments.order_id must reference orders.id" in captured.out
    assert "- orders_status_check: orders.status must enforce allowed values" in captured.out


def test_main_returns_result_from_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_verify_live_db() -> int:
        return 0

    def fake_run(coro: object) -> int:
        assert asyncio.iscoroutine(coro)
        coro.close()
        return 7

    monkeypatch.setattr(verify_db_safety, "verify_live_db", fake_verify_live_db)
    monkeypatch.setattr(verify_db_safety.asyncio, "run", fake_run)

    assert verify_db_safety.main() == 7
