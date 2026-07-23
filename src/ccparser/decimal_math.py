"""Context-independent exact arithmetic and formatting for financial Decimals."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("financial values must be finite")
    return value


def _integer_coefficient(value: Decimal) -> tuple[int, int]:
    finite_decimal(value)
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise ValueError("financial values must have a finite exponent")
    coefficient = 0
    for digit in parts.digits:
        coefficient = coefficient * 10 + digit
    return (-coefficient if parts.sign else coefficient), parts.exponent


def _from_coefficient(coefficient: int, exponent: int) -> Decimal:
    digits = Decimal(abs(coefficient)).as_tuple().digits
    return Decimal((int(coefficient < 0), digits, exponent))


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    parts = tuple(_integer_coefficient(value) for value in values)
    if not parts:
        return Decimal("0")
    common_exponent = min(exponent for _, exponent in parts)
    coefficient = sum(value * 10 ** (exponent - common_exponent) for value, exponent in parts)
    return _from_coefficient(coefficient, common_exponent)


def exact_difference(minuend: Decimal, subtrahend: Decimal) -> Decimal:
    return exact_sum((minuend, subtrahend.copy_negate()))


def exact_product(values: Iterable[Decimal]) -> Decimal:
    parts = tuple((value, *_integer_coefficient(value)) for value in values)
    coefficient = 1
    exponent = 0
    negative = False
    for source, value_coefficient, value_exponent in parts:
        coefficient *= value_coefficient
        exponent += value_exponent
        negative ^= source.is_signed()
    product = _from_coefficient(coefficient, exponent)
    return product.copy_negate() if coefficient == 0 and negative else product


def is_exact_multiple(value: Decimal, unit: Decimal) -> bool:
    value_coefficient, value_exponent = _integer_coefficient(value)
    unit_coefficient, unit_exponent = _integer_coefficient(unit)
    if unit_coefficient <= 0:
        raise ValueError("minor unit must be positive")
    common_exponent = min(value_exponent, unit_exponent)
    scaled_value: int = value_coefficient * 10 ** (value_exponent - common_exponent)
    scaled_unit: int = unit_coefficient * 10 ** (unit_exponent - common_exponent)
    return scaled_value % scaled_unit == 0


def plain_decimal_string(value: Decimal) -> str:
    finite_decimal(value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


__all__ = [
    "exact_difference",
    "exact_product",
    "exact_sum",
    "finite_decimal",
    "is_exact_multiple",
    "plain_decimal_string",
]
