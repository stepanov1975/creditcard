from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.normalization_fields import (
    BilledFields,
    FieldDisposition,
    InstallmentFields,
    extract_billed_fields,
    extract_installment_fields,
    is_installment_shaped,
)


def _cell(
    text: str,
    column: int,
    *,
    confidence: float = 1.0,
) -> Cell:
    x0 = float(column * 50)
    return Cell(
        page_number=1,
        bbox=(x0, 30.0, x0 + 40.0, 40.0),
        text=text,
        confidence=confidence,
    )


def _row(*cells: Cell) -> Row:
    return Row(
        page_number=1,
        bbox=(
            min(cell.bbox[0] for cell in cells),
            min(cell.bbox[1] for cell in cells),
            max(cell.bbox[2] for cell in cells),
            max(cell.bbox[3] for cell in cells),
        ),
        cells=cells,
        confidence=1.0,
    )


def _region(roles: tuple[ColumnRole, ...], row: Row) -> TableRegion:
    headers = tuple(_cell(role.value, index) for index, role in enumerate(roles))
    columns = tuple(
        ColumnSpec(
            index=index,
            page_number=1,
            bbox=(index * 50.0, 10.0, index * 50.0 + 40.0, 200.0),
            relative_x0=index / len(roles),
            relative_x1=(index + 1) / len(roles),
            role=role,
            source_cells=(headers[index],),
            confidence=1.0,
        )
        for index, role in enumerate(roles)
    )
    header = _row(*headers)
    schema = TableSchema(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, 200.0),
        columns=columns,
        header_cells=headers,
        sample_cells=row.cells,
        confidence=1.0,
    )
    return TableRegion(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, row.bbox[3]),
        header=header,
        rows=(row,),
        table_schema=schema,
        confidence=1.0,
    )


def test_field_outcome_models_are_typed_frozen_and_slotted() -> None:
    billed = BilledFields(
        amount=None,
        currency=None,
        amount_cell=None,
        confidence=0.0,
        diagnostics=("unknown_amount_column",),
        disposition=FieldDisposition.REJECT_ROW,
    )
    installment = InstallmentFields(current=None, total=None, diagnostics=())

    assert tuple(FieldDisposition) == (
        FieldDisposition.ACCEPT,
        FieldDisposition.REJECT_ROW,
        FieldDisposition.IGNORE_ROW,
    )
    assert tuple(BilledFields.__slots__) == (
        "amount",
        "currency",
        "amount_cell",
        "confidence",
        "diagnostics",
        "disposition",
    )
    assert tuple(InstallmentFields.__slots__) == ("current", "total", "diagnostics")
    with pytest.raises(FrozenInstanceError):
        billed.amount = Decimal("1.00")
    with pytest.raises(FrozenInstanceError):
        installment.current = 1


_UNPARSEABLE_AMOUNT_CELL = _cell("12 apples", 1)
_UNPARSEABLE_AMOUNT_ROW = _row(_cell("Merchant", 0), _UNPARSEABLE_AMOUNT_CELL)


@pytest.mark.parametrize(
    ("roles", "row", "expected"),
    (
        pytest.param(
            (ColumnRole.DESCRIPTION,),
            _row(_cell("Merchant", 0)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("unknown_amount_column",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="missing-amount-column",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.AMOUNT),
            _row(_cell("Merchant", 0), _cell("ILS 10.00", 1), _cell("ILS 11.00", 2)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("multiple_amount_columns",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="duplicate-amount-columns",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("Merchant", 0)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("missing_amount_cell",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="missing-amount-cell",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("Merchant", 0), _cell("ILS 10.00", 1), _cell("ILS 11.00", 1)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("multiple_amount_cells",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="multiple-amount-cells",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.ORIGINAL_AMOUNT,
                ColumnRole.CURRENCY,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("Merchant", 0),
                _cell("USD 3.00", 1),
                _cell("ILS", 2),
                _cell("ILS 10.00", 3),
            ),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("ambiguous_generic_currency_association",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="generic-currency-with-original-amount",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.CURRENCY,
                ColumnRole.BILLING_CURRENCY,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("Merchant", 0),
                _cell("ILS", 1),
                _cell("ILS", 2),
                _cell("ILS 10.00", 3),
            ),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("ambiguous_generic_currency_association",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="generic-currency-with-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(_cell("Merchant", 0), _cell("10.00", 1)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("missing_currency_cell",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="missing-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(
                _cell("Merchant", 0),
                _cell("10.00", 1),
                _cell("ILS", 2),
                _cell("ILS", 2),
            ),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("multiple_currency_cells",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="multiple-billing-currency-cells",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(_cell("Merchant", 0), _cell("10.00", 1), _cell("XYZ", 2)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("unknown_billing_currency",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="unknown-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(_cell("Merchant", 0), _cell("10.00", 1), _cell("USD", 2)),
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=None,
                confidence=0.0,
                diagnostics=("billing_currency_conflict",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="billing-currency-conflict",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _UNPARSEABLE_AMOUNT_ROW,
            BilledFields(
                amount=None,
                currency=None,
                amount_cell=_UNPARSEABLE_AMOUNT_CELL,
                confidence=0.0,
                diagnostics=("invalid_amount_text",),
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="unparseable-billed-amount",
        ),
    ),
)
def test_extract_billed_fields_rejects_unproven_or_invalid_values(
    roles: tuple[ColumnRole, ...],
    row: Row,
    expected: BilledFields,
) -> None:
    result = extract_billed_fields(
        row=row,
        region=_region(roles, row),
        printed_currency="ILS",
    )

    assert result == expected


def test_extract_billed_fields_accepts_value_with_parser_confidence() -> None:
    amount_cell = _cell("10.00", 1, confidence=0.61)
    row = _row(_cell("Merchant", 0), amount_cell)

    result = extract_billed_fields(
        row=row,
        region=_region((ColumnRole.DESCRIPTION, ColumnRole.AMOUNT), row),
        printed_currency="ILS",
    )

    assert result == BilledFields(
        amount=Decimal("10.00"),
        currency="ILS",
        amount_cell=amount_cell,
        confidence=0.95,
        diagnostics=(),
        disposition=FieldDisposition.ACCEPT,
    )
    assert result.amount_cell is amount_cell


def test_extract_billed_fields_ignores_zero_with_cell_confidence() -> None:
    amount_cell = _cell("ILS 0.00", 1, confidence=0.73)
    row = _row(_cell("Merchant", 0), amount_cell)

    result = extract_billed_fields(
        row=row,
        region=_region((ColumnRole.DESCRIPTION, ColumnRole.AMOUNT), row),
        printed_currency="ILS",
    )

    assert result == BilledFields(
        amount=Decimal("0.00"),
        currency="ILS",
        amount_cell=amount_cell,
        confidence=0.73,
        diagnostics=("noncontributing_zero_billed_row",),
        disposition=FieldDisposition.IGNORE_ROW,
    )
    assert result.amount_cell is amount_cell


@pytest.mark.parametrize(
    ("roles", "row", "expected"),
    (
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("Merchant", 0), _cell("ILS 10.00", 1)),
            InstallmentFields(current=None, total=None, diagnostics=()),
            id="absent",
        ),
        pytest.param(
            (
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("Merchant", 0),
                _cell("ILS 10.00", 1),
                _cell("1/6", 2),
                _cell("2/6", 3),
            ),
            InstallmentFields(
                current=None,
                total=None,
                diagnostics=("multiple_installment_columns",),
            ),
            id="duplicate-columns",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.INSTALLMENT),
            _row(_cell("Merchant", 0), _cell("ILS 10.00", 1)),
            InstallmentFields(
                current=None,
                total=None,
                diagnostics=("missing_installment_cell",),
            ),
            id="missing-cell",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.INSTALLMENT),
            _row(
                _cell("Merchant", 0),
                _cell("ILS 10.00", 1),
                _cell("1/6", 2),
                _cell("2/6", 2),
            ),
            InstallmentFields(
                current=None,
                total=None,
                diagnostics=("multiple_installment_cells",),
            ),
            id="multiple-cells",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.INSTALLMENT),
            _row(
                _cell("Merchant", 0),
                _cell("ILS 10.00", 1),
                _cell("two of six", 2),
            ),
            InstallmentFields(current=None, total=None, diagnostics=("invalid_installment",)),
            id="malformed",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.INSTALLMENT),
            _row(
                _cell("Merchant", 0),
                _cell("ILS 10.00", 1),
                _cell("2/6", 2),
            ),
            InstallmentFields(current=2, total=6, diagnostics=()),
            id="valid",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT, ColumnRole.INSTALLMENT),
            _row(
                _cell("Merchant", 0),
                _cell("ILS 10.00", 1),
                _cell("7/6", 2),
            ),
            InstallmentFields(current=None, total=None, diagnostics=("invalid_installment",)),
            id="current-greater-than-total",
        ),
    ),
)
def test_extract_installment_fields_returns_complete_shape(
    roles: tuple[ColumnRole, ...],
    row: Row,
    expected: InstallmentFields,
) -> None:
    assert extract_installment_fields(row=row, region=_region(roles, row)) == expected


@pytest.mark.parametrize("text", ("2/6", " 2 / 6 ", "7/6", "0/6"))
def test_is_installment_shaped_recognizes_complete_numeric_shape(text: str) -> None:
    assert is_installment_shaped(text)


@pytest.mark.parametrize("text", ("two of six", "installment 2/6", "2/6 plan", "2-6"))
def test_is_installment_shaped_rejects_nonshape_text(text: str) -> None:
    assert not is_installment_shaped(text)
