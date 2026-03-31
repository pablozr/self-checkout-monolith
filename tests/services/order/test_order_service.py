from unittest.mock import AsyncMock

import pytest

from services.order.order_service import update_order_status


@pytest.mark.asyncio
async def test_update_order_status_returns_true_when_row_is_returned() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})

    result = await update_order_status(conn, order_id=10, new_status="confirmed")

    assert result is True


@pytest.mark.asyncio
async def test_update_order_status_returns_false_when_no_row_is_returned() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    result = await update_order_status(conn, order_id=10, new_status="confirmed")

    assert result is False


@pytest.mark.asyncio
async def test_update_order_status_converts_allowed_statuses_to_list_in_fetchrow_args() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 10})
    allowed_current_statuses = ("pending", "paid")

    await update_order_status(
        conn,
        order_id=10,
        new_status="confirmed",
        allowed_current_statuses=allowed_current_statuses,
    )

    _, _, _, statuses_arg = conn.fetchrow.await_args.args
    assert isinstance(statuses_arg, list)
    assert statuses_arg == ["pending", "paid"]
