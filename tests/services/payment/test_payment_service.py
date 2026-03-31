from unittest.mock import AsyncMock

import pytest

from schemas.checkout import CheckoutCompletedData
from services.payment.payment_service import update_payment_status


def _build_checkout_completed_data() -> CheckoutCompletedData:
    return CheckoutCompletedData(
        order_id=10,
        payment_id=20,
        table_id=3,
        session_token="session-token",
        checkout_session_id="cs_test_123",
        payment_intent_id="pi_test_123",
        amount_total=5000,
    )


@pytest.mark.asyncio
async def test_update_payment_status_returns_true_when_row_is_returned() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 20})
    data = _build_checkout_completed_data()

    result = await update_payment_status(conn, data=data, status="paid")

    assert result is True


@pytest.mark.asyncio
async def test_update_payment_status_returns_false_when_no_row_is_returned() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    data = _build_checkout_completed_data()

    result = await update_payment_status(conn, data=data, status="paid")

    assert result is False


@pytest.mark.asyncio
async def test_update_payment_status_sends_expected_ids_and_list_statuses_in_fetchrow_args() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": 20})
    data = _build_checkout_completed_data()
    allowed_current_statuses = ("pending", "requires_action")

    await update_payment_status(
        conn,
        data=data,
        status="paid",
        allowed_current_statuses=allowed_current_statuses,
    )

    (
        _,
        _new_status,
        payment_intent_id_arg,
        checkout_session_id_arg,
        payment_id_arg,
        order_id_arg,
        statuses_arg,
    ) = conn.fetchrow.await_args.args

    assert payment_intent_id_arg == data.payment_intent_id
    assert checkout_session_id_arg == data.checkout_session_id
    assert payment_id_arg == data.payment_id
    assert order_id_arg == data.order_id
    assert isinstance(statuses_arg, list)
    assert statuses_arg == ["pending", "requires_action"]
