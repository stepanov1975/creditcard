"""Geometry-bounded foreign-exchange value extraction."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from ccparser.decimal_math import exact_difference
from ccparser.layout.columns import cells_in_column
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.models import (
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ForeignExchangeDetails,
)
from ccparser.money import canonical_currency, currencies_in_text
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner
from ccparser.text_tokens import contains_token_sequence


@dataclass(frozen=True, slots=True)
class ForeignExchangeExtraction:
    """Structured FX values plus exact evidence ownership and diagnostics."""

    details: ForeignExchangeDetails | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FxValues:
    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
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
_GROSS_FEE_CUES = (
    "fee amount",
    "commission amount",
    "charged fee",
    "עמלה בסך",
    "עמלת מט ח בסך",
)
_DISCOUNT_CUES = (
    "discount",
    "הנחה",
    "מופחתת",
)
_BOUNDED_DETAIL_DIAGNOSTIC = "foreign_conversion_detail_block"


def _header_phrase(column: ColumnSpec) -> str:
    return " ".join(cell.text for cell in column.source_cells)


def _contains_cue(phrase: str, cues: Iterable[str]) -> bool:
    return contains_token_sequence(phrase, cues)


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


def _row_text(row: Row) -> str:
    return " ".join(cell.text for cell in row.cells)


def _row_evidence(row: Row) -> tuple[EvidenceReference, ...]:
    return _field_evidence(row.cells)


def _row_atom_ids(row: Row, ledger: EvidenceLedger) -> frozenset[int]:
    return frozenset(atom_id for cell in row.cells for atom_id in ledger.atoms_for_cell(cell))


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
    return _one_decimal(atom_ids, ledger, allow_zero=False)


def _one_decimal(
    atom_ids: Iterable[int],
    ledger: EvidenceLedger,
    *,
    allow_zero: bool,
) -> tuple[Decimal, frozenset[int]] | None:
    candidates = ledger.positioned_decimal_candidates(atom_ids)
    parsed = tuple(
        (value, candidate.atom_ids)
        for candidate in candidates
        if (value := _decimal(candidate.text)) is not None
        and (value >= 0 if allow_zero else value > 0)
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


def _one_row_money(
    row: Row,
    ledger: EvidenceLedger,
    expected_currency: str,
) -> tuple[Decimal, str, frozenset[int]] | None:
    currencies = currencies_in_text(_row_text(row))
    if len(currencies) != 1 or currencies[0] != canonical_currency(expected_currency):
        return None
    parsed = _one_positive_decimal(_row_atom_ids(row, ledger), ledger)
    if parsed is None:
        return None
    amount, atom_ids = parsed
    return amount, currencies[0], atom_ids


def _table_fx_values(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    billing_currency: str,
) -> _FxValues:
    claims: list[EvidenceClaim] = []
    diagnostics: list[str] = []
    exchange_rate: ExtractedDecimal | None = None
    net_fee: ExtractedMoney | None = None

    rate_columns = tuple(
        column for column in region.table_schema.columns if _is_rate_column(column)
    )
    rate_cells = tuple(
        cell for column in rate_columns for cell in cells_in_column(row.cells, column)
    )
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
    fee_cells = tuple(cell for column in fee_columns for cell in cells_in_column(row.cells, column))
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

    return _FxValues(
        exchange_rate=exchange_rate,
        net_fee=net_fee,
        claims=tuple(claims),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def _continuation_fx_values(
    rows: Sequence[Row],
    ledger: EvidenceLedger,
    billing_currency: str,
) -> _FxValues:
    claims: list[EvidenceClaim] = []
    diagnostics: list[str] = []
    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
    rate_seen = False
    rate_ambiguous = False
    percentage_seen = False
    percentage_ambiguous = False
    gross_seen = False
    gross_ambiguous = False
    discount_seen = False
    discount_ambiguous = False
    pending_gross = False
    pending_discount = False

    bounded_rows = tuple(row for row in rows if _BOUNDED_DETAIL_DIAGNOSTIC in row.diagnostics)
    for row in sorted(bounded_rows, key=lambda item: (item.page_number, item.bbox[1])):
        raw_text = _row_text(row)
        phrase = raw_text
        atom_ids = _row_atom_ids(row, ledger)
        evidence = _row_evidence(row)
        is_rate = _contains_cue(phrase, _RATE_HEADER_CUES)
        is_percentage = _contains_cue(phrase, _FEE_HEADER_CUES) and "%" in raw_text
        is_gross = _contains_cue(phrase, _GROSS_FEE_CUES) or (
            pending_gross
            and canonical_currency(billing_currency) in currencies_in_text(raw_text)
            and _one_positive_decimal(atom_ids, ledger) is not None
        )
        is_discount = _contains_cue(phrase, _DISCOUNT_CUES) and not is_gross

        if is_rate:
            parsed_rate = _one_positive_decimal(atom_ids, ledger)
            if rate_seen or parsed_rate is None:
                rate_ambiguous = True
                exchange_rate = None
                diagnostics.append("unparsed_exchange_rate_candidate")
            else:
                value, value_atom_ids = parsed_rate
                exchange_rate = ExtractedDecimal(value=value, evidence=evidence)
                claims.append(EvidenceClaim(SemanticOwner.EXCHANGE_RATE, value_atom_ids))
            rate_seen = True

        if is_percentage:
            parsed_percentage = _one_decimal(atom_ids, ledger, allow_zero=True)
            if percentage_seen or parsed_percentage is None:
                percentage_ambiguous = True
                fee_percentage = None
                diagnostics.append("unparsed_foreign_currency_fee_percentage_candidate")
            else:
                value, value_atom_ids = parsed_percentage
                fee_percentage = ExtractedDecimal(value=value, evidence=evidence)
                claims.append(EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, value_atom_ids))
                pending_gross = True
            percentage_seen = True

        if is_gross:
            parsed_gross = _one_row_money(row, ledger, billing_currency)
            if gross_seen or parsed_gross is None:
                gross_ambiguous = True
                gross_fee = None
                diagnostics.append("unparsed_foreign_currency_fee_candidate")
            else:
                amount, currency, value_atom_ids = parsed_gross
                gross_fee = ExtractedMoney(
                    amount=amount,
                    currency=currency,
                    evidence=evidence,
                )
                claims.append(EvidenceClaim(SemanticOwner.GROSS_FX_FEE, value_atom_ids))
            gross_seen = True
            pending_gross = False
            pending_discount = _contains_cue(phrase, _DISCOUNT_CUES)
            continue

        if is_discount or pending_discount:
            parsed_discount = _one_row_money(row, ledger, billing_currency)
            if discount_seen or parsed_discount is None:
                discount_ambiguous = True
                fee_discount = None
                diagnostics.append("unparsed_foreign_currency_fee_discount_candidate")
            else:
                amount, currency, value_atom_ids = parsed_discount
                fee_discount = ExtractedMoney(
                    amount=amount,
                    currency=currency,
                    evidence=evidence,
                )
                claims.append(EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, value_atom_ids))
            discount_seen = True
            pending_discount = False

    net_fee: ExtractedMoney | None = None
    if gross_fee is not None and fee_discount is not None:
        amount = exact_difference(gross_fee.amount, fee_discount.amount)
        if gross_fee.currency != fee_discount.currency or amount < 0:
            diagnostics.append("inconsistent_foreign_currency_fee_derivation")
        else:
            net_fee = ExtractedMoney(
                amount=amount,
                currency=gross_fee.currency,
                evidence=tuple(dict.fromkeys((*gross_fee.evidence, *fee_discount.evidence))),
                derivation="gross_fee_minus_discount",
            )

    ambiguous_owners = {
        owner
        for ambiguous, owner in (
            (rate_ambiguous, SemanticOwner.EXCHANGE_RATE),
            (percentage_ambiguous, SemanticOwner.FX_FEE_PERCENTAGE),
            (gross_ambiguous, SemanticOwner.GROSS_FX_FEE),
            (discount_ambiguous, SemanticOwner.FX_FEE_DISCOUNT),
        )
        if ambiguous
    }
    return _FxValues(
        exchange_rate=exchange_rate,
        fee_percentage=fee_percentage,
        gross_fee=gross_fee,
        fee_discount=fee_discount,
        net_fee=net_fee,
        claims=tuple(claim for claim in claims if claim.owner not in ambiguous_owners),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def _merge_values(table: _FxValues, continuation: _FxValues) -> _FxValues:
    rate_ambiguous = "unparsed_exchange_rate_candidate" in {
        *table.diagnostics,
        *continuation.diagnostics,
    }
    rate_conflict = (
        table.exchange_rate is not None
        and continuation.exchange_rate is not None
        and table.exchange_rate.value != continuation.exchange_rate.value
    )
    net_fee_conflict = (
        table.net_fee is not None
        and continuation.net_fee is not None
        and (
            table.net_fee.amount != continuation.net_fee.amount
            or table.net_fee.currency != continuation.net_fee.currency
        )
    )
    blocked_owners = {
        owner
        for conflict, owner in (
            (rate_ambiguous or rate_conflict, SemanticOwner.EXCHANGE_RATE),
            (net_fee_conflict, SemanticOwner.NET_FX_FEE),
        )
        if conflict
    }
    diagnostics = [*table.diagnostics, *continuation.diagnostics]
    if rate_conflict:
        diagnostics.append("unparsed_exchange_rate_candidate")
    if net_fee_conflict:
        diagnostics.append("inconsistent_foreign_currency_fee_derivation")
    return _FxValues(
        exchange_rate=(
            None
            if rate_ambiguous or rate_conflict
            else table.exchange_rate or continuation.exchange_rate
        ),
        fee_percentage=continuation.fee_percentage,
        gross_fee=continuation.gross_fee,
        fee_discount=continuation.fee_discount,
        net_fee=None if net_fee_conflict else table.net_fee or continuation.net_fee,
        claims=tuple(
            claim
            for claim in (*table.claims, *continuation.claims)
            if claim.owner not in blocked_owners
        ),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def _finish_extraction(values: _FxValues) -> ForeignExchangeExtraction:
    details = (
        ForeignExchangeDetails(
            exchange_rate=values.exchange_rate,
            fee_percentage=values.fee_percentage,
            gross_fee=values.gross_fee,
            fee_discount=values.fee_discount,
            net_fee=values.net_fee,
        )
        if any(
            value is not None
            for value in (
                values.exchange_rate,
                values.fee_percentage,
                values.gross_fee,
                values.fee_discount,
                values.net_fee,
            )
        )
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
    table_values = _table_fx_values(rows[0], region, ledger, billing_currency)
    continuation_values = _continuation_fx_values(rows[1:], ledger, billing_currency)
    return _finish_extraction(_merge_values(table_values, continuation_values))


__all__ = ["ForeignExchangeExtraction", "extract_foreign_exchange"]
