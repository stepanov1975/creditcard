from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext

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


@pytest.mark.parametrize("trap_invalid_operation", (False, True), ids=("untrapped", "trapped"))
@pytest.mark.parametrize(
    "unit",
    (
        pytest.param(Decimal("NaN"), id="quiet-nan"),
        pytest.param(Decimal("sNaN"), id="signaling-nan"),
        pytest.param(Decimal("Infinity"), id="positive-infinity"),
        pytest.param(Decimal("-Infinity"), id="negative-infinity"),
    ),
)
def test_is_exact_multiple_rejects_nonfinite_units_without_decimal_signals(
    unit: Decimal,
    trap_invalid_operation: bool,
) -> None:
    with localcontext() as context:
        context.traps[InvalidOperation] = trap_invalid_operation
        context.clear_flags()
        with pytest.raises(ValueError, match=r"^financial values must be finite$"):
            is_exact_multiple(Decimal("1"), unit)
        assert not context.flags[InvalidOperation]


@pytest.mark.parametrize("trap_invalid_operation", (False, True), ids=("untrapped", "trapped"))
@pytest.mark.parametrize(
    "value",
    (
        pytest.param(Decimal("NaN"), id="quiet-nan"),
        pytest.param(Decimal("sNaN"), id="signaling-nan"),
        pytest.param(Decimal("Infinity"), id="positive-infinity"),
        pytest.param(Decimal("-Infinity"), id="negative-infinity"),
    ),
)
def test_is_exact_multiple_validates_value_before_unit_positivity(
    value: Decimal,
    trap_invalid_operation: bool,
) -> None:
    with localcontext() as context:
        context.traps[InvalidOperation] = trap_invalid_operation
        context.clear_flags()
        with pytest.raises(ValueError, match=r"^financial values must be finite$"):
            is_exact_multiple(value, Decimal("-1"))
        assert not context.flags[InvalidOperation]


@pytest.mark.parametrize(
    ("unit", "expected"),
    (
        pytest.param(Decimal("0.25"), True, id="positive"),
        pytest.param(Decimal("-0.25"), None, id="negative"),
        pytest.param(Decimal("+0"), None, id="positive-zero"),
        pytest.param(Decimal("-0"), None, id="negative-zero"),
    ),
)
def test_is_exact_multiple_checks_the_exact_unit_coefficient(
    unit: Decimal,
    expected: bool | None,
) -> None:
    if expected is None:
        with pytest.raises(ValueError, match=r"^minor unit must be positive$"):
            is_exact_multiple(Decimal("1"), unit)
    else:
        assert is_exact_multiple(Decimal("1"), unit) is expected
