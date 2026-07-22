"""Typed billed-value and installment extraction outcomes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    proven_region_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.money import canonical_currency, parse_amount
from ccparser.text_tokens import normalize_text


class FieldDisposition(StrEnum):
    """Whether extracted fields emit, reject, or deliberately ignore a row."""

    ACCEPT = "accept"
    REJECT_ROW = "reject_row"
    IGNORE_ROW = "ignore_row"


@dataclass(frozen=True, slots=True)
class BilledFields:
    """The billed value and exact source outcome for one transaction row."""

    amount: Decimal | None
    currency: str | None
    amount_cell: Cell | None
    confidence: float
    diagnostics: tuple[str, ...]
    disposition: FieldDisposition


@dataclass(frozen=True, slots=True)
class InstallmentFields:
    """Parsed installment position with ordered diagnostics."""

    current: int | None
    total: int | None
    diagnostics: tuple[str, ...]


_INSTALLMENT_PATTERN = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def _role_cells(row: Row, region: TableRegion, role: ColumnRole) -> tuple[Cell, ...]:
    return tuple(
        cell for column in _role_columns(region, role) for cell in _cells_for_column(row, column)
    )


def _rejected_billed_fields(
    diagnostics: tuple[str, ...],
    *,
    amount_cell: Cell | None = None,
) -> BilledFields:
    return BilledFields(
        amount=None,
        currency=None,
        amount_cell=amount_cell,
        confidence=0.0,
        diagnostics=diagnostics,
        disposition=FieldDisposition.REJECT_ROW,
    )


def extract_billed_fields(
    *,
    row: Row,
    region: TableRegion,
    printed_currency: str,
) -> BilledFields:
    """Extract the sole billed amount against the group's printed currency."""

    amount_column = proven_region_billed_amount_column(region)
    if amount_column is None:
        amount_columns = _role_columns(region, ColumnRole.AMOUNT)
        diagnostic = "unknown_amount_column" if not amount_columns else "multiple_amount_columns"
        return _rejected_billed_fields((diagnostic,))

    amount_cells = _cells_for_column(row, amount_column)
    if len(amount_cells) != 1:
        diagnostic = "missing_amount_cell" if not amount_cells else "multiple_amount_cells"
        return _rejected_billed_fields((diagnostic,))

    diagnostics: list[str] = []
    currency_hint = printed_currency
    generic_currency_columns = _role_columns(region, ColumnRole.CURRENCY)
    original_columns = _role_columns(region, ColumnRole.ORIGINAL_AMOUNT)
    billing_currency_columns = _role_columns(region, ColumnRole.BILLING_CURRENCY)
    if generic_currency_columns and original_columns:
        diagnostics.append("ambiguous_generic_currency_association")
    if generic_currency_columns and billing_currency_columns:
        diagnostics.append("ambiguous_generic_currency_association")
    currency_role = ColumnRole.BILLING_CURRENCY if billing_currency_columns else ColumnRole.CURRENCY
    currency_cells = _role_cells(row, region, currency_role)
    if len(currency_cells) > 1:
        diagnostics.append("multiple_currency_cells")
    elif _role_columns(region, currency_role) and not currency_cells:
        diagnostics.append("missing_currency_cell")
    elif len(currency_cells) == 1:
        row_currency = canonical_currency(currency_cells[0].text)
        if row_currency is None:
            diagnostics.append("unknown_billing_currency")
        elif row_currency != currency_hint:
            diagnostics.append("billing_currency_conflict")
        else:
            currency_hint = row_currency
    if diagnostics:
        return _rejected_billed_fields(tuple(diagnostics))

    amount_cell = amount_cells[0]
    billed = parse_amount(amount_cell.text, currency_hint=currency_hint)
    if billed.amount is None or billed.currency is None:
        return _rejected_billed_fields(billed.diagnostics, amount_cell=amount_cell)
    if billed.amount == 0:
        return BilledFields(
            amount=billed.amount,
            currency=billed.currency,
            amount_cell=amount_cell,
            confidence=amount_cell.confidence,
            diagnostics=("noncontributing_zero_billed_row",),
            disposition=FieldDisposition.IGNORE_ROW,
        )
    return BilledFields(
        amount=billed.amount,
        currency=billed.currency,
        amount_cell=amount_cell,
        confidence=billed.confidence,
        diagnostics=(),
        disposition=FieldDisposition.ACCEPT,
    )


def is_installment_shaped(text: str) -> bool:
    """Return whether text is exactly a numeric current/total installment shape."""

    return _INSTALLMENT_PATTERN.fullmatch(normalize_text(text)) is not None


def _parse_installment(text: str) -> tuple[int, int] | None:
    match = _INSTALLMENT_PATTERN.fullmatch(normalize_text(text))
    if match is None:
        return None
    current, total = (int(value) for value in match.groups())
    if current < 1 or total < 1 or current > total:
        return None
    return current, total


def extract_installment_fields(*, row: Row, region: TableRegion) -> InstallmentFields:
    """Extract the optional sole installment cell without rejecting the row."""

    installment_columns = _role_columns(region, ColumnRole.INSTALLMENT)
    if len(installment_columns) > 1:
        return InstallmentFields(
            current=None,
            total=None,
            diagnostics=("multiple_installment_columns",),
        )
    if not installment_columns:
        return InstallmentFields(current=None, total=None, diagnostics=())

    installment_cells = _cells_for_column(row, installment_columns[0])
    if len(installment_cells) != 1:
        diagnostic = (
            "missing_installment_cell" if not installment_cells else "multiple_installment_cells"
        )
        return InstallmentFields(current=None, total=None, diagnostics=(diagnostic,))

    installment = _parse_installment(installment_cells[0].text)
    if installment is None:
        return InstallmentFields(
            current=None,
            total=None,
            diagnostics=("invalid_installment",),
        )
    current, total = installment
    return InstallmentFields(current=current, total=total, diagnostics=())


__all__ = [
    "BilledFields",
    "FieldDisposition",
    "InstallmentFields",
    "extract_billed_fields",
    "extract_installment_fields",
    "is_installment_shaped",
]
