"""Geometry-bounded foreign-exchange value extraction."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.models import (
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ForeignExchangeDetails,
)
from ccparser.money import canonical_currency, currencies_in_text
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner


@dataclass(frozen=True, slots=True)
class ForeignExchangeExtraction:
    """Structured FX values plus exact evidence ownership and diagnostics."""

    details: ForeignExchangeDetails | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _TableFxValues:
    exchange_rate: ExtractedDecimal | None = None
    net_fee: ExtractedMoney | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()


_RATE_HEADER_CUES = (
    "conversion rate",
    "exchange rate",
    "representative rate",
    "שער המרה",
    "שער ההמרה",
    "שער יציג",
    "שער",
)
_FEE_HEADER_CUES = (
    "commission",
    "fee",
    "surcharge",
    "עמלה",
    "עמלת",
)


def _center_x(cell: Cell) -> float:
    return (cell.bbox[0] + cell.bbox[2]) / 2


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return tuple(cell for cell in row.cells if column.bbox[0] <= _center_x(cell) <= column.bbox[2])


def _normalized_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _header_phrase(column: ColumnSpec) -> str:
    return _normalized_phrase(" ".join(cell.text for cell in column.source_cells))


def _contains_cue(phrase: str, cues: Iterable[str]) -> bool:
    return any(_normalized_phrase(cue) in phrase for cue in cues)


def _is_fee_column(column: ColumnSpec) -> bool:
    return column.role is ColumnRole.AUXILIARY_AMOUNT and _contains_cue(
        _header_phrase(column), _FEE_HEADER_CUES
    )


def _is_rate_column(column: ColumnSpec) -> bool:
    return column.role is ColumnRole.EXCHANGE_RATE or (
        column.role is ColumnRole.CONVERSION_DATE
        and _contains_cue(_header_phrase(column), _RATE_HEADER_CUES)
    )


def _field_evidence(cells: Iterable[Cell]) -> tuple[EvidenceReference, ...]:
    references = (
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for cell in cells
    )
    return tuple(dict.fromkeys(references))


def _date_atom_ids(cell: Cell, ledger: EvidenceLedger) -> frozenset[int]:
    return frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(cell)
        for atom_id in candidate.atom_ids
    )


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _one_positive_decimal(
    atom_ids: Iterable[int], ledger: EvidenceLedger
) -> tuple[Decimal, frozenset[int]] | None:
    candidates = ledger.positioned_decimal_candidates(atom_ids)
    parsed = tuple(
        (value, candidate.atom_ids)
        for candidate in candidates
        if (value := _decimal(candidate.text)) is not None and value > 0
    )
    return parsed[0] if len(parsed) == 1 else None


def _one_money(
    cell: Cell,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    currencies = currencies_in_text(cell.text)
    if len(currencies) != 1 or currencies[0] != canonical_currency(expected_currency):
        return None
    parsed = _one_positive_decimal(ledger.atoms_for_cell(cell), ledger)
    if parsed is None:
        return None
    amount, atom_ids = parsed
    return amount, currencies[0], atom_ids


def _table_fx_values(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    billing_currency: str,
) -> _TableFxValues:
    claims: list[EvidenceClaim] = []
    diagnostics: list[str] = []
    exchange_rate: ExtractedDecimal | None = None
    net_fee: ExtractedMoney | None = None

    rate_columns = tuple(
        column for column in region.table_schema.columns if _is_rate_column(column)
    )
    rate_cells = tuple(cell for column in rate_columns for cell in _cells_for_column(row, column))
    if rate_cells:
        rate_candidates = tuple(
            (value, atom_ids, cell)
            for cell in rate_cells
            if (
                parsed_rate := _one_positive_decimal(
                    ledger.atoms_for_cell(cell) - _date_atom_ids(cell, ledger), ledger
                )
            )
            is not None
            for value, atom_ids in (parsed_rate,)
        )
        if len(rate_candidates) == 1:
            value, atom_ids, cell = rate_candidates[0]
            exchange_rate = ExtractedDecimal(
                value=value,
                evidence=_field_evidence((cell,)),
            )
            claims.append(EvidenceClaim(SemanticOwner.EXCHANGE_RATE, atom_ids))
        else:
            diagnostics.append("unparsed_exchange_rate_candidate")

    fee_columns = tuple(column for column in region.table_schema.columns if _is_fee_column(column))
    fee_cells = tuple(cell for column in fee_columns for cell in _cells_for_column(row, column))
    if fee_cells:
        fee_candidates = tuple(
            (amount, currency, atom_ids, cell)
            for cell in fee_cells
            if (parsed_money := _one_money(cell, ledger, billing_currency)) is not None
            for amount, currency, atom_ids in (parsed_money,)
        )
        if len(fee_candidates) == 1:
            amount, currency, atom_ids, cell = fee_candidates[0]
            net_fee = ExtractedMoney(
                amount=amount,
                currency=currency,
                evidence=_field_evidence((cell,)),
            )
            claims.append(EvidenceClaim(SemanticOwner.NET_FX_FEE, atom_ids))
        else:
            diagnostics.append("unparsed_foreign_currency_fee_candidate")

    return _TableFxValues(
        exchange_rate=exchange_rate,
        net_fee=net_fee,
        claims=tuple(claims),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def _finish_extraction(values: _TableFxValues) -> ForeignExchangeExtraction:
    details = (
        ForeignExchangeDetails(
            exchange_rate=values.exchange_rate,
            net_fee=values.net_fee,
        )
        if values.exchange_rate is not None or values.net_fee is not None
        else None
    )
    return ForeignExchangeExtraction(
        details=details,
        claims=values.claims,
        diagnostics=values.diagnostics,
    )


def extract_foreign_exchange(
    *,
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    original_currency: str | None,
    billing_currency: str,
    conversion_date: date | None,
) -> ForeignExchangeExtraction:
    """Extract unambiguous FX values from one proven foreign transaction row."""

    del conversion_date
    if original_currency is None or original_currency == billing_currency or not rows:
        return ForeignExchangeExtraction()
    return _finish_extraction(_table_fx_values(rows[0], region, ledger, billing_currency))


__all__ = ["ForeignExchangeExtraction", "extract_foreign_exchange"]
