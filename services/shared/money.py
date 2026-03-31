from decimal import Decimal, ROUND_HALF_UP

_MONEY_SCALE = Decimal("0.01")


def normalize_amount(amount: Decimal) -> Decimal:
    return amount.quantize(_MONEY_SCALE, rounding=ROUND_HALF_UP)


def to_minor_units(amount: Decimal) -> int:
    normalized_amount = normalize_amount(amount)
    return int((normalized_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
