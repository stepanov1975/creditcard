from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from ccparser.decimal_math import (
    exact_difference,
    exact_sum,
    finite_decimal,
    is_exact_multiple,
    plain_decimal_string,
)


def test_exact_arithmetic_ignores_active_decimal_context() -> None:
    large = Decimal("123456789012345678901234567890.12")
    with localcontext() as context:
        context.prec = 5
        assert exact_sum((large, Decimal("0.01"))) == Decimal("123456789012345678901234567890.13")
        assert exact_difference(large, Decimal("0.01")) == Decimal(
            "123456789012345678901234567890.11"
        )


def test_decimal_helpers_validate_and_format_without_rounding() -> None:
    assert finite_decimal(Decimal("-0")) == Decimal("-0")
    assert plain_decimal_string(Decimal("100.1200")) == "100.12"
    assert plain_decimal_string(Decimal("-0.00")) == "0"
    assert is_exact_multiple(Decimal("100.125"), Decimal("0.001"))
    assert not is_exact_multiple(Decimal("100.125"), Decimal("0.01"))
    with pytest.raises(ValueError, match="finite"):
        finite_decimal(Decimal("NaN"))
    with pytest.raises(ValueError, match="positive"):
        is_exact_multiple(Decimal("1"), Decimal("0"))
