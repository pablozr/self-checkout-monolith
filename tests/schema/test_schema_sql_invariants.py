from pathlib import Path
import re


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema.sql"


def _read_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _normalize_schema(schema: str) -> str:
    return re.sub(r"\s+", " ", schema).strip()


def test_payments_provider_is_explicitly_stripe_only() -> None:
    schema = _normalize_schema(_read_schema())

    assert re.search(
        r"provider\s+VARCHAR\(50\)\s+NOT\s+NULL\s+DEFAULT\s+'stripe'\s+CHECK\s*\(provider\s*=\s*'stripe'\)",
        schema,
    )


def test_payments_enforces_one_payment_per_order() -> None:
    schema = _normalize_schema(_read_schema())

    assert re.search(r"CREATE\s+UNIQUE\s+INDEX\s+ux_payments_order_id\s+ON\s+payments\s*\(order_id\)", schema)
    assert not re.search(r"CREATE\s+INDEX\s+idx_payments_order_id\s+ON\s+payments\s*\(order_id\)", schema)
    assert not re.search(
        r"CREATE\s+INDEX\s+idx_payments_order_id_status\s+ON\s+payments\s*\(order_id\s*,\s*status\)",
        schema,
    )


def test_schema_has_hot_path_indexes_for_orders_payments_and_stripe_events() -> None:
    schema = _normalize_schema(_read_schema())

    assert re.search(r"CREATE\s+INDEX\s+idx_orders_created_at\s+ON\s+orders\s*\(created_at\s+DESC\)", schema)
    assert re.search(
        r"CREATE\s+INDEX\s+idx_stripe_events_event_type_created_at\s+ON\s+stripe_events\s*\(event_type\s*,\s*created_at\s+DESC\)",
        schema,
    )


def test_identifier_non_empty_checks_exist_for_payment_and_stripe_event_ids() -> None:
    schema = _normalize_schema(_read_schema())

    assert re.search(
        r"checkout_session_id\s+VARCHAR\(255\)\s+CHECK\s*\(checkout_session_id\s+IS\s+NULL\s+OR\s+BTRIM\(checkout_session_id\)\s*<>\s*''\)",
        schema,
    )
    assert re.search(
        r"provider_payment_id\s+VARCHAR\(255\)\s+CHECK\s*\(provider_payment_id\s+IS\s+NULL\s+OR\s+BTRIM\(provider_payment_id\)\s*<>\s*''\)",
        schema,
    )
    assert re.search(r"event_id\s+VARCHAR\(255\)\s+NOT\s+NULL\s+UNIQUE\s+CHECK\s*\(BTRIM\(event_id\)\s*<>\s*''\)", schema)
    assert re.search(r"event_type\s+VARCHAR\(255\)\s+NOT\s+NULL\s+CHECK\s*\(BTRIM\(event_type\)\s*<>\s*''\)", schema)


def test_existing_core_indexes_are_preserved() -> None:
    schema = _normalize_schema(_read_schema())

    assert re.search(
        r"CREATE\s+INDEX\s+idx_orders_status_created_at\s+ON\s+orders\s*\(status\s*,\s*created_at\s+DESC\)",
        schema,
    )
    assert re.search(
        r"CREATE\s+INDEX\s+idx_payments_status_created_at\s+ON\s+payments\s*\(status\s*,\s*created_at\s+DESC\)",
        schema,
    )
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+ux_payments_checkout_session_id\s+ON\s+payments\s*\(checkout_session_id\)",
        schema,
    )
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+ux_payments_provider_payment_id\s+ON\s+payments\s*\(provider_payment_id\)",
        schema,
    )
