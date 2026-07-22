"""Pure monetary parsing and geometry-driven transaction normalization."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from ccparser.date_tokens import SHORT_DATE_TOKEN_PATTERNS
from ccparser.discovery import (
    DiscoveredDateYearContext,
    StatementDiscovery,
    StatementGroupDiscovery,
)
from ccparser.fx import extract_foreign_exchange
from ccparser.geometry import BBox
from ccparser.geometry import (
    bbox_center_x as _center_x,
)
from ccparser.geometry import (
    center_inside as _bbox_center_inside,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    is_location_identifier,
    isolated_date_token,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag, is_structural_continuation
from ccparser.models import (
    EvidenceReference,
    PrintedTotal,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.money import (
    AmountParseResult,
    canonical_currency,
    currencies_in_text,
    is_currency_shaped,
    is_money_shaped,
    parse_amount,
)
from ccparser.normalization_dates import (
    _cross_cell_date_source_cells,
    _has_proven_unanchored_short_date,
    _header_kind,
    _matching_date_atom_ids,
    _parsed_cross_cell_conversion_evidence,
    _proven_unanchored_short_date_style,
    _structural_date_column_kinds,
    contains_date_cue,
    extract_conversion_date,
    extract_dates,
    is_date_shaped,
)
from ccparser.normalization_description import (
    extract_description,
    is_description_continuation,
)
from ccparser.normalization_fields import (
    FieldDisposition,
    extract_billed_fields,
    extract_installment_fields,
    is_installment_shaped,
)
from ccparser.original_amount import (
    extract_original_amount,
    original_currency_spilled_into_location,
)
from ccparser.reconcile import ReconciliationOutcome, reconciliation_outcome
from ccparser.semantic_evidence import (
    EvidenceClaim,
    EvidenceLedger,
    SemanticOwner,
)
from ccparser.text_tokens import contains_token_sequence, normalize_text, phrase_tokens


class _ImmutableNormalizationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RowNormalizationResult(_ImmutableNormalizationModel):
    """One source-row outcome with raw local evidence and explicit diagnostics."""

    page_number: int = Field(gt=0)
    bbox: BBox
    raw_text: str
    evidence: tuple[EvidenceReference, ...]
    transaction: Transaction | None = None
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementNormalization(_ImmutableNormalizationModel):
    """Normalized transactions, totals, and exact reconciliation outcome."""

    discovery: StatementDiscovery
    transactions: tuple[Transaction, ...]
    printed_totals: tuple[PrintedTotal, ...]
    row_results: tuple[RowNormalizationResult, ...]
    reconciliation: ReconciliationOutcome
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RowNormalizationAttempt:
    """One internal row result paired with its explicit emission disposition."""

    result: RowNormalizationResult
    disposition: FieldDisposition


@dataclass(slots=True)
class _RowNormalizationContext:
    """Stable row provenance and ordered diagnostics for result construction."""

    rows: tuple[Row, ...]
    evidence: tuple[EvidenceReference, ...]
    raw_text: str
    diagnostics: list[str]

    @property
    def row(self) -> Row:
        return self.rows[0]

    def rejected_attempt(
        self,
        *,
        diagnostics: tuple[str, ...] | None = None,
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            confidence=0.0,
            diagnostics=tuple(self.diagnostics) if diagnostics is None else diagnostics,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.REJECT_ROW)

    def ignored_attempt(
        self,
        *,
        confidence: float,
        diagnostics: tuple[str, ...],
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            confidence=confidence,
            diagnostics=diagnostics,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.IGNORE_ROW)

    def completed_attempt(
        self,
        *,
        transaction: Transaction,
        confidence: float,
    ) -> _RowNormalizationAttempt:
        result = RowNormalizationResult(
            page_number=self.row.page_number,
            bbox=self.row.bbox,
            raw_text=self.raw_text,
            evidence=self.evidence,
            transaction=transaction,
            confidence=confidence,
            diagnostics=transaction.ambiguities,
        )
        return _RowNormalizationAttempt(result, FieldDisposition.ACCEPT)


_CATEGORY_VOCABULARY: tuple[tuple[TransactionCategory, tuple[str, ...]], ...] = (
    (TransactionCategory.REFUND, ("credit", "refund", "זיכוי", "החזר")),
    (TransactionCategory.INTEREST, ("interest", "ריבית")),
    (TransactionCategory.FEE, ("commission", "fee", "עמלה", "דמי")),
    (TransactionCategory.ADJUSTMENT, ("adjustment", "correction", "התאמה", "תיקון")),
    (TransactionCategory.PURCHASE, ("purchase", "purchased", "רכישה", "קנייה", "עסקה")),
)
_EMBEDDED_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)[-+]?(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:[.,]\d{1,2})?(?!\d)"
)
_EMBEDDED_INSTALLMENT_PATTERN = re.compile(r"(?<!\d)\d{1,3}\s*/\s*\d{1,3}(?!\d)")
_EMBEDDED_AMOUNT_CUES = (
    "original amount",
    "transaction amount",
    "foreign amount",
    "exchange rate",
    "conversion rate",
    "fx",
    "סכום במקור",
    "סכום עסקה",
    "שער המרה",
    "מט ח",
)
_EMBEDDED_DATE_CUES = (
    "conversion date",
    "date of conversion",
    "exchange date",
    "converted",
    "conversion",
    "תאריך המרה",
    "תאריך ההמרה",
    "המרה",
)
_EMBEDDED_INSTALLMENT_CUES = ("installment", "payment number", "תשלום", "תשלומים")
_CARD_IDENTIFIER_PATTERN = re.compile(r"^\d{4,10}$")
_CARD_IDENTIFIER_MARKERS = ("card id", "card identifier", "מזהה כרטיס")
_EXPLICIT_CATEGORY_HEADER_MARKERS = frozenset(
    {"category", "transaction type", "סוג עסקה", "סוג העסקה"}
)
_EXPLICIT_ANCILLARY_HEADER_MARKERS = frozenset(
    {
        "industry",
        "transaction detail",
        "card presented",
        "notes",
        "remarks",
        "eligibility",
        "ענף",
        "פירוט",
        "כרטיס הוצג",
        "הערה",
        "הערות",
        "הזכאות",
    }
)


def _normalized_text(text: str) -> str:
    return normalize_text(text)


def _normalized_phrase(text: str) -> str:
    return " ".join(phrase_tokens(text))


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    return contains_token_sequence(text, markers)


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def _role_cells(row: Row, region: TableRegion, role: ColumnRole) -> tuple[Cell, ...]:
    return tuple(
        cell for column in _role_columns(region, role) for cell in _cells_for_column(row, column)
    )


def _proven_billed_amount_column(region: TableRegion) -> ColumnSpec | None:
    transaction_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    return proven_billed_amount_column(region.table_schema, transaction_rows)


def _is_relevant_cell(cell: Cell) -> bool:
    text = _normalized_text(cell.text)
    return (
        is_money_shaped(text)
        or is_currency_shaped(text)
        or is_date_shaped(text)
        or is_installment_shaped(text)
        or (bool(currencies_in_text(text)) and any(char.isdigit() for char in text))
        or (
            _contains_marker(text, _EMBEDDED_AMOUNT_CUES)
            and _EMBEDDED_AMOUNT_PATTERN.search(text) is not None
        )
        or (_contains_marker(text, _EMBEDDED_DATE_CUES) and contains_date_cue(text))
        or (
            _contains_marker(text, _EMBEDDED_INSTALLMENT_CUES)
            and _EMBEDDED_INSTALLMENT_PATTERN.search(text) is not None
        )
    )


def _is_safe_card_identifier_cell(row: Row, cell: Cell) -> bool:
    identifiers = tuple(
        candidate
        for candidate in row.cells
        if _CARD_IDENTIFIER_PATTERN.fullmatch(_normalized_text(candidate.text)) is not None
    )
    return (
        len(identifiers) == 1
        and identifiers[0] is cell
        and _contains_marker(
            " ".join(candidate.text for candidate in row.cells),
            _CARD_IDENTIFIER_MARKERS,
        )
    )


def _is_isolated_ocr_edge_artifact_cell(
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
) -> bool:
    columns = region.table_schema.columns
    header_cells = tuple(
        candidate
        for candidate in region.table_schema.header_cells
        if candidate in column.source_cells
    )
    relevant_column_cells = tuple(
        candidate
        for candidate_row in region.rows
        for candidate in _cells_for_column(candidate_row, column)
        if _is_relevant_cell(candidate)
    )
    header_is_bounded_ocr_artifact = (
        len(header_cells) == 1
        and bool(header_cells[0].words)
        and all(word.source == "ocr" for word in header_cells[0].words)
        and not any(char.isdigit() for char in header_cells[0].text)
        and sum(char.isalpha() for char in header_cells[0].text) <= 5
    )
    return (
        column.role is ColumnRole.UNKNOWN
        and column.index
        in {min(item.index for item in columns), max(item.index for item in columns)}
        and len(header_cells) == 1
        and (
            not any(char.isalnum() for char in header_cells[0].text)
            or header_is_bounded_ocr_artifact
        )
        and bool(cell.words)
        and all(word.source == "ocr" for word in cell.words)
        and sum(char.isalnum() for char in cell.text) <= 1
        and relevant_column_cells == (cell,)
    )


def _assignment_diagnostics(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    explicit_ancillary_unknowns = _explicit_ancillary_unknown_columns(region)
    explicit_category_unknowns = _explicit_category_unknown_columns(region)
    cross_cell_date_sources = _cross_cell_date_source_cells(row, region, ledger)
    for cell in row.cells:
        columns = tuple(
            column
            for column in region.table_schema.columns
            if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        )
        relevant = _is_relevant_cell(cell)
        if len(columns) != 1:
            diagnostics.append("unmatched_cell" if not columns else "multiply_assigned_cell")
            if relevant:
                diagnostics.append("unresolved_relevant_cell")
            continue
        column = columns[0]
        safe_card_identifier = column.role is ColumnRole.UNKNOWN and _is_safe_card_identifier_cell(
            row, cell
        )
        safe_ancillary_unknown = (
            column.role is ColumnRole.UNKNOWN
            and column.index in explicit_ancillary_unknowns | explicit_category_unknowns
            and not relevant
        )
        deferred_semantic_candidate = column.role is ColumnRole.UNKNOWN and (
            bool(ledger.fragmented_date_candidates(cell)) or cell in cross_cell_date_sources
        )
        safe_edge_artifact = _is_isolated_ocr_edge_artifact_cell(cell, column, region)
        safe_location_identifier = column.role is ColumnRole.LOCATION and (
            is_location_identifier(cell.text)
            or original_currency_spilled_into_location(cell, region) is not None
        )
        has_alternative = any(
            value == "ambiguous_role" or value.startswith("alternative_role:")
            for value in column.diagnostics
        )
        if (
            relevant
            and column.role is ColumnRole.UNKNOWN
            and not safe_card_identifier
            and not safe_ancillary_unknown
            and not deferred_semantic_candidate
            and not safe_edge_artifact
        ):
            diagnostics.append(f"column:{column.index}:role_unknown")
        if relevant and column.role is ColumnRole.LOCATION and not safe_location_identifier:
            diagnostics.append(f"column:{column.index}:unexpected_location_value")
        if (
            relevant
            and has_alternative
            and not safe_card_identifier
            and not safe_ancillary_unknown
            and not deferred_semantic_candidate
            and not safe_edge_artifact
        ):
            diagnostics.extend(
                f"column:{column.index}:{value}"
                for value in column.diagnostics
                if value == "ambiguous_role" or value.startswith("alternative_role:")
            )
        if relevant and (
            (
                column.role is ColumnRole.UNKNOWN
                and not safe_card_identifier
                and not safe_ancillary_unknown
                and not deferred_semantic_candidate
                and not safe_edge_artifact
            )
            or (
                has_alternative
                and not safe_card_identifier
                and not safe_ancillary_unknown
                and not deferred_semantic_candidate
                and not safe_edge_artifact
            )
            or (column.role is ColumnRole.LOCATION and not safe_location_identifier)
        ):
            diagnostics.append("unresolved_relevant_cell")
    return tuple(dict.fromkeys(diagnostics))


def _role_contract_diagnostics(region: TableRegion) -> tuple[str, ...]:
    role_columns: dict[ColumnRole, tuple[ColumnSpec, ...]] = {
        role: _role_columns(region, role) for role in ColumnRole if role is not ColumnRole.UNKNOWN
    }
    diagnostics: list[str] = []
    maximums = {
        ColumnRole.DATE: 2,
        ColumnRole.CONVERSION_DATE: 1,
        ColumnRole.DESCRIPTION: 1,
        ColumnRole.LOCATION: 1,
        ColumnRole.AMOUNT: 1,
        ColumnRole.ORIGINAL_AMOUNT: 1,
        ColumnRole.CURRENCY: 1,
        ColumnRole.BILLING_CURRENCY: 1,
        ColumnRole.ORIGINAL_CURRENCY: 1,
        ColumnRole.INSTALLMENT: 1,
    }
    for role, maximum in maximums.items():
        if len(role_columns[role]) > maximum and not (
            role is ColumnRole.AMOUNT and _proven_billed_amount_column(region) is not None
        ):
            diagnostics.append(f"unsupported_role_cardinality:{role.value}")
    if role_columns[ColumnRole.ORIGINAL_CURRENCY] and not role_columns[ColumnRole.ORIGINAL_AMOUNT]:
        diagnostics.append("original_currency_without_original_amount")
    return tuple(diagnostics)


def _row_evidence(rows: Sequence[Row]) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)
        for row in rows
        for cell in row.cells
    )


def _row_text(rows: Sequence[Row]) -> str:
    return _normalized_text(" ".join(cell.text for row in rows for cell in row.cells))


def _category(description: str | None, has_installment: bool) -> TransactionCategory:
    if has_installment:
        return TransactionCategory.INSTALLMENT
    normalized = description or ""
    for category, markers in _CATEGORY_VOCABULARY:
        if _contains_marker(normalized, markers):
            return category
    return TransactionCategory.UNKNOWN


def _category_sign_contradiction(category: TransactionCategory, kind: TransactionKind) -> bool:
    if category is TransactionCategory.REFUND:
        return kind is not TransactionKind.CREDIT
    if category in {
        TransactionCategory.PURCHASE,
        TransactionCategory.FEE,
        TransactionCategory.INTEREST,
        TransactionCategory.INSTALLMENT,
    }:
        return kind is not TransactionKind.CHARGE
    return False


def _explicit_category(
    row: Row,
    region: TableRegion,
) -> tuple[TransactionCategory, tuple[str, ...]]:
    columns = tuple(
        column
        for column in _role_columns(region, ColumnRole.UNKNOWN)
        if column.index in _explicit_category_unknown_columns(region)
    )
    if len(columns) > 1:
        return TransactionCategory.UNKNOWN, ("multiple_category_columns",)
    if not columns:
        return TransactionCategory.UNKNOWN, ()
    cells = _cells_for_column(row, columns[0])
    if len(cells) > 1:
        return TransactionCategory.UNKNOWN, ("multiple_category_cells",)
    if not cells:
        return TransactionCategory.UNKNOWN, ()
    return _category(cells[0].text, False), ()


def _resolved_category(
    description: str | None,
    has_installment: bool,
    row: Row,
    region: TableRegion,
) -> tuple[TransactionCategory, tuple[str, ...]]:
    description_category = _category(description, has_installment)
    explicit_category, diagnostics = _explicit_category(row, region)
    if (
        description_category is not TransactionCategory.UNKNOWN
        and explicit_category is not TransactionCategory.UNKNOWN
        and description_category is not explicit_category
    ):
        return description_category, (*diagnostics, "conflicting_category_semantics")
    if description_category is not TransactionCategory.UNKNOWN:
        return description_category, diagnostics
    return explicit_category, diagnostics


def _column_header_text(region: TableRegion, column: ColumnSpec) -> str:
    header_cells = tuple(
        cell
        for cell in region.table_schema.header_cells
        if cell in column.source_cells or column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
    )
    return _normalized_text(" ".join(cell.text for cell in header_cells))


def _explicit_ancillary_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in _role_columns(region, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_ANCILLARY_HEADER_MARKERS,
        )
    )


def _explicit_category_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in _role_columns(region, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_CATEGORY_HEADER_MARKERS,
        )
    )


def _stable_unknown_columns(region: TableRegion) -> frozenset[int]:
    stable: set[int] = set()
    base_rows = tuple(row for row in region.rows if not is_structural_continuation(row))
    for column in _role_columns(region, ColumnRole.UNKNOWN):
        header_text = _column_header_text(region, column)
        values = tuple(
            cell
            for row in base_rows
            for cell in _cells_for_column(row, column)
            if any(char.isalnum() for char in cell.text)
        )
        if not header_text or not any(char.isalnum() for char in header_text) or len(values) < 2:
            continue
        profiles: dict[str, int] = {}
        for cell in values:
            text = _normalized_text(cell.text)
            profile = (
                "money"
                if is_money_shaped(text)
                else "date"
                if isolated_date_token(text) is not None
                else "numeric"
                if all(char.isdigit() or char.isspace() for char in text)
                else "alphabetic"
                if any(char.isalpha() for char in text) and not any(char.isdigit() for char in text)
                else "mixed"
            )
            profiles[profile] = profiles.get(profile, 0) + 1
        if max(profiles.values()) * 2 >= len(values):
            stable.add(column.index)
    return frozenset(stable)


def _add_remaining_claim(
    claims: list[EvidenceClaim],
    owner: SemanticOwner,
    atom_ids: Iterable[int],
) -> None:
    already_claimed = frozenset(atom_id for claim in claims for atom_id in claim.atom_ids)
    remaining = frozenset(atom_ids) - already_claimed
    if remaining:
        claims.append(EvidenceClaim(owner, remaining))


def _financial_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    *,
    currency_hint: str | None,
) -> frozenset[int]:
    parsed = parse_amount(cell.text, currency_hint=currency_hint)
    cell_atom_ids = ledger.atoms_for_cell(cell)
    if parsed.amount is not None and parsed.currency is not None:
        return cell_atom_ids
    return frozenset(
        atom_id
        for atom_id in cell_atom_ids
        if not any(char.isalpha() for char in ledger.atoms[atom_id].text)
        or canonical_currency(ledger.atoms[atom_id].text) is not None
    )


def _semantic_claims_and_diagnostics(
    *,
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    initial_claims: Sequence[EvidenceClaim],
    amount_cell: Cell,
    billing_currency: str,
    original_currency: str | None,
    description: str | None,
    transaction_date: date | None,
    posting_date: date | None,
    conversion_date: date | None,
    year_context: DiscoveredDateYearContext | None,
    date_column_kinds: Mapping[int, str],
) -> tuple[tuple[EvidenceClaim, ...], tuple[str, ...]]:
    claims = list(initial_claims)
    _add_remaining_claim(
        claims,
        SemanticOwner.BILLED_VALUE,
        ledger.atoms_for_cell(amount_cell),
    )

    stable_unknowns = _stable_unknown_columns(region)
    explicit_ancillary_unknowns = _explicit_ancillary_unknown_columns(region)
    explicit_category_unknowns = _explicit_category_unknown_columns(region)
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    description_index = description_columns[0].index if len(description_columns) == 1 else None
    boundary_atom_ids: set[int] = set()

    for row in rows:
        row_has_safe_card_identifier = any(
            _is_safe_card_identifier_cell(row, cell) for cell in row.cells
        )
        is_detail_continuation = any(
            has_row_tag(row, tag)
            for tag in (
                RowTag.SUBORDINATE_DETAIL,
                RowTag.AUXILIARY_CONTINUATION,
                RowTag.HEBREW_NOTE_DETAIL,
            )
        )
        cross_cell_conversion_atom_ids = frozenset(
            atom_id
            for candidate_date, evidence in _parsed_cross_cell_conversion_evidence(
                row,
                region,
                ledger,
                year_context,
                transaction_date,
            )
            if original_currency is not None
            and original_currency != billing_currency
            and candidate_date == conversion_date
            for atom_id in evidence.atom_ids
        )
        for cell in row.cells:
            columns = tuple(
                column
                for column in region.table_schema.columns
                if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
            )
            if len(columns) != 1:
                continue
            column = columns[0]
            cell_ids = ledger.atoms_for_cell(cell)
            if is_detail_continuation:
                _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                continue
            if cross_cell_date_ids := cell_ids & cross_cell_conversion_atom_ids:
                _add_remaining_claim(
                    claims,
                    SemanticOwner.CONVERSION_DATE,
                    cross_cell_date_ids,
                )
                _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                continue
            if column.role is ColumnRole.DATE:
                kind = _header_kind(column) or date_column_kinds.get(column.index)
                expected = posting_date if kind == "posting" else transaction_date
                owner = (
                    SemanticOwner.POSTING_DATE
                    if kind == "posting"
                    else SemanticOwner.TRANSACTION_DATE
                )
                matched_date_ids = _matching_date_atom_ids(
                    ledger,
                    cell,
                    expected,
                    year_context,
                )
                _add_remaining_claim(claims, owner, matched_date_ids)
                if expected is not None:
                    _add_remaining_claim(
                        claims,
                        owner,
                        (
                            atom_id
                            for atom_id in cell_ids
                            if not any(char.isalpha() for char in ledger.atoms[atom_id].text)
                        ),
                    )
                elif (
                    year_context is None
                    and (style := _proven_unanchored_short_date_style(region, column)) is not None
                    and _has_proven_unanchored_short_date(cell, style)
                ):
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                boundary_atom_ids.update(
                    atom_id
                    for atom_id in cell_ids
                    if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                )
            elif column.role is ColumnRole.CONVERSION_DATE:
                _add_remaining_claim(
                    claims,
                    SemanticOwner.CONVERSION_DATE,
                    _matching_date_atom_ids(ledger, cell, conversion_date, year_context),
                )
                _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
            elif column.role in {
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
                ColumnRole.CURRENCY,
            }:
                _add_remaining_claim(claims, SemanticOwner.BILLED_VALUE, cell_ids)
            elif column.role in {
                ColumnRole.ORIGINAL_AMOUNT,
                ColumnRole.ORIGINAL_CURRENCY,
            }:
                if description is not None:
                    description_phrase = _normalized_phrase(description)
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.DESCRIPTION,
                        (
                            atom_id
                            for atom_id in cell_ids
                            if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                            and (atom_phrase := _normalized_phrase(ledger.atoms[atom_id].text))
                            and (
                                atom_phrase in description_phrase
                                or description_phrase in atom_phrase
                            )
                        ),
                    )
                _add_remaining_claim(
                    claims,
                    SemanticOwner.ORIGINAL_VALUE,
                    _financial_atom_ids(
                        ledger,
                        cell,
                        currency_hint=original_currency,
                    ),
                )
                if description_index is not None and abs(column.index - description_index) == 1:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.LAYOUT_NOISE,
                        (
                            atom_id
                            for atom_id in cell_ids
                            if (atom := ledger.atoms[atom_id]).glyph is not None
                            and (atom.bbox[0] < column.bbox[0] or atom.bbox[2] > column.bbox[2])
                        ),
                    )
                    boundary_atom_ids.update(
                        atom_id
                        for atom_id in cell_ids
                        if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                    )
            elif column.role is ColumnRole.INSTALLMENT:
                _add_remaining_claim(claims, SemanticOwner.INSTALLMENT, cell_ids)
            elif column.role is ColumnRole.LOCATION:
                safe_location = (
                    not _is_relevant_cell(cell)
                    or is_location_identifier(cell.text)
                    or original_currency_spilled_into_location(cell, region) is not None
                )
                if safe_location:
                    _add_remaining_claim(claims, SemanticOwner.LOCATION, cell_ids)
            elif column.role in {
                ColumnRole.AUXILIARY_AMOUNT,
                ColumnRole.EXCHANGE_RATE,
            }:
                _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
            elif column.role is ColumnRole.UNKNOWN:
                conversion_candidates = ledger.fragmented_date_candidates(cell)
                is_foreign_conversion_evidence = (
                    original_currency is not None
                    and original_currency != billing_currency
                    and bool(conversion_candidates)
                )
                if is_foreign_conversion_evidence:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.CONVERSION_DATE,
                        _matching_date_atom_ids(
                            ledger,
                            cell,
                            conversion_date,
                            year_context,
                        ),
                    )
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif _is_isolated_ocr_edge_artifact_cell(cell, column, region):
                    _add_remaining_claim(claims, SemanticOwner.LAYOUT_NOISE, cell_ids)
                elif column.index in stable_unknowns or row_has_safe_card_identifier:
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif column.index in explicit_category_unknowns and not _is_relevant_cell(cell):
                    _add_remaining_claim(claims, SemanticOwner.CATEGORY, cell_ids)
                elif column.index in explicit_ancillary_unknowns and not _is_relevant_cell(cell):
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif description_index is not None and abs(column.index - description_index) == 1:
                    boundary_atom_ids.update(
                        atom_id
                        for atom_id in cell_ids
                        if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                    )
            elif column.role is ColumnRole.DESCRIPTION:
                if transaction_date is not None:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.LAYOUT_NOISE,
                        (
                            atom_id
                            for atom_id in cell_ids
                            if any(char.isdigit() for char in ledger.atoms[atom_id].text)
                            and not any(char.isalpha() for char in ledger.atoms[atom_id].text)
                        ),
                    )
                date_columns = _role_columns(region, ColumnRole.DATE)
                if year_context is None and len(date_columns) == 1:
                    unanchored_style = _proven_unanchored_short_date_style(
                        region,
                        date_columns[0],
                    )
                    if unanchored_style is not None:
                        _add_remaining_claim(
                            claims,
                            SemanticOwner.ANCILLARY,
                            (
                                atom_id
                                for atom_id in cell_ids
                                if SHORT_DATE_TOKEN_PATTERNS[unanchored_style].fullmatch(
                                    _normalized_text(ledger.atoms[atom_id].text)
                                )
                                is not None
                            ),
                        )

    validation = ledger.validate_claims(claims)
    diagnostics = list(validation.diagnostics)
    unresolved = frozenset(
        atom_id
        for atom_id in validation.unclaimed_atom_ids
        if ledger.atoms[atom_id].confidence >= 0.8
    )
    if unresolved & boundary_atom_ids:
        diagnostics.append("unconsumed_description_boundary_text")
    if unresolved - boundary_atom_ids:
        diagnostics.append("unconsumed_transaction_semantic_text")
    return tuple(claims), tuple(dict.fromkeys(diagnostics))


def _normalize_row(
    *,
    row: Row,
    continuation_rows: Sequence[Row],
    region: TableRegion,
    group: StatementGroupDiscovery,
    year_context: DiscoveredDateYearContext | None,
    date_column_kinds: Mapping[int, str],
    transaction_id: str,
) -> _RowNormalizationAttempt:
    rows = (row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)
    context = _RowNormalizationContext(
        rows=rows,
        evidence=_row_evidence(rows),
        raw_text=_row_text(rows),
        diagnostics=list(_assignment_diagnostics(row, region, ledger)),
    )
    diagnostics = context.diagnostics
    role_contract_diagnostics = _role_contract_diagnostics(region)
    diagnostics.extend(role_contract_diagnostics)
    if role_contract_diagnostics:
        return context.rejected_attempt()

    billed = extract_billed_fields(
        row=row,
        region=region,
        printed_currency=group.printed_total.currency,
    )
    if billed.disposition is FieldDisposition.REJECT_ROW:
        if billed.amount_cell is not None:
            return context.rejected_attempt(diagnostics=billed.diagnostics)
        diagnostics.extend(billed.diagnostics)
        return context.rejected_attempt()
    if billed.disposition is FieldDisposition.IGNORE_ROW:
        return context.ignored_attempt(
            confidence=billed.confidence,
            diagnostics=billed.diagnostics,
        )
    if billed.amount is None or billed.currency is None or billed.amount_cell is None:
        raise RuntimeError("accepted billed fields must contain complete source values")

    description_extraction = extract_description(rows, region, year_context, ledger)
    description = description_extraction.value
    semantic_claims = list(description_extraction.claims)
    diagnostics.extend(description_extraction.diagnostics)
    date_extraction = extract_dates(row, region, year_context, date_column_kinds)
    transaction_date = date_extraction.transaction_date
    posting_date = date_extraction.posting_date
    conversion_date = date_extraction.conversion_date
    unresolved_conversion_cells = date_extraction.unresolved_conversion_cells
    diagnostics.extend(date_extraction.diagnostics)

    original_extraction = extract_original_amount(
        row=row,
        continuation_rows=continuation_rows,
        region=region,
        ledger=ledger,
        billed=billed,
        description=description,
        initial_claims=semantic_claims,
    )
    original_amount = original_extraction.amount
    original_currency = original_extraction.currency
    description = original_extraction.description
    semantic_claims.extend(original_extraction.claims)
    diagnostics.extend(original_extraction.diagnostics)

    conversion_extraction = extract_conversion_date(
        row,
        region,
        ledger,
        year_context,
        original_currency=original_currency,
        billing_currency=billed.currency,
        transaction_date=transaction_date,
        existing_conversion_date=conversion_date,
    )
    diagnostics.extend(conversion_extraction.diagnostics)
    if conversion_date is None:
        conversion_date = conversion_extraction.value
    elif conversion_extraction.value is not None and conversion_extraction.value != conversion_date:
        diagnostics.append("conflicting_conversion_date_evidence")
    if any(cell not in conversion_extraction.source_cells for cell in unresolved_conversion_cells):
        diagnostics.append("invalid_conversion_date")

    foreign_exchange_extraction = extract_foreign_exchange(
        rows=rows,
        region=region,
        ledger=ledger,
        original_currency=original_currency,
        billing_currency=billed.currency,
    )
    semantic_claims.extend(foreign_exchange_extraction.claims)
    diagnostics.extend(foreign_exchange_extraction.diagnostics)

    installment = extract_installment_fields(row=row, region=region)
    diagnostics.extend(installment.diagnostics)
    installment_current = installment.current
    installment_total = installment.total

    _, semantic_diagnostics = _semantic_claims_and_diagnostics(
        rows=rows,
        region=region,
        ledger=ledger,
        initial_claims=semantic_claims,
        amount_cell=billed.amount_cell,
        billing_currency=billed.currency,
        original_currency=original_currency,
        description=description,
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        year_context=year_context,
        date_column_kinds=date_column_kinds,
    )
    diagnostics.extend(semantic_diagnostics)

    kind = TransactionKind.CREDIT if billed.amount < 0 else TransactionKind.CHARGE
    category, category_diagnostics = _resolved_category(
        description,
        installment_current is not None,
        row,
        region,
    )
    diagnostics.extend(category_diagnostics)
    if _category_sign_contradiction(category, kind):
        diagnostics.append("category_sign_contradiction")
    transaction = Transaction(
        transaction_id=transaction_id,
        kind=kind,
        billed_amount=billed.amount,
        billing_currency=billed.currency,
        reconciliation_group_ids=(group.group_id,),
        ambiguities=tuple(dict.fromkeys(diagnostics)),
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        description=description,
        category=category,
        original_amount=original_amount,
        original_currency=original_currency,
        foreign_exchange=foreign_exchange_extraction.details,
        installment_current=installment_current,
        installment_total=installment_total,
        evidence=context.evidence,
    )
    confidence_values = [row.confidence, billed.confidence]
    confidence_values.extend(continuation.confidence for continuation in continuation_rows)
    return context.completed_attempt(
        transaction=transaction,
        confidence=statistics.mean(confidence_values),
    )


def _printed_total(group: StatementGroupDiscovery) -> tuple[PrintedTotal | None, tuple[str, ...]]:
    parsed = parse_amount(
        group.printed_total.amount_text,
        currency_hint=group.printed_total.currency,
    )
    if parsed.amount is None or parsed.currency is None:
        return None, tuple(f"printed_total:{diagnostic}" for diagnostic in parsed.diagnostics)
    return (
        PrintedTotal(group_id=group.group_id, amount=parsed.amount, currency=parsed.currency),
        (),
    )


def _is_printed_total_row(row: Row, group: StatementGroupDiscovery) -> bool:
    evidence = (
        group.printed_total.label_evidence,
        group.printed_total.value_evidence,
    )
    return all(
        item.page_number == row.page_number
        and any(_bbox_center_inside(item.bbox, cell.bbox) for cell in row.cells)
        for item in evidence
    )


def _compatible_cross_page_region_geometry(
    previous: TableRegion,
    current: TableRegion,
) -> bool:
    previous_columns = previous.table_schema.columns
    current_columns = current.table_schema.columns
    return (
        current.page_number == previous.page_number + 1
        and len(previous_columns) == len(current_columns)
        and all(
            previous_column.role is current_column.role
            and abs(previous_column.relative_x0 - current_column.relative_x0) <= 0.05
            and abs(previous_column.relative_x1 - current_column.relative_x1) <= 0.05
            for previous_column, current_column in zip(
                previous_columns,
                current_columns,
                strict=True,
            )
        )
    )


def _cross_page_leading_detail_handoffs(
    regions: Sequence[TableRegion],
    group: StatementGroupDiscovery,
) -> tuple[dict[int, tuple[Row, ...]], frozenset[int]]:
    handoffs: dict[int, tuple[Row, ...]] = {}
    owned_leading_rows: set[int] = set()
    for previous_region, current_region in pairwise(regions):
        if not _compatible_cross_page_region_geometry(previous_region, current_region):
            continue
        current_rows = tuple(
            sorted(current_region.rows, key=lambda item: (item.bbox[1], item.bbox[0]))
        )
        leading_rows = tuple(
            row for row in current_rows if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL)
        )
        if not leading_rows or current_rows[: len(leading_rows)] != leading_rows:
            continue
        following_rows = current_rows[len(leading_rows) :]
        if not following_rows:
            continue
        previous_rows = tuple(
            sorted(previous_region.rows, key=lambda item: (item.bbox[1], item.bbox[0]))
        )
        previous_base_rows: list[Row] = []
        previous_index = 0
        while previous_index < len(previous_rows):
            previous_row = previous_rows[previous_index]
            if _is_printed_total_row(previous_row, group):
                previous_index += 1
                continue
            previous_base_rows.append(previous_row)
            continuation_index = previous_index + 1
            continuation_previous = previous_row
            while continuation_index < len(previous_rows) and is_description_continuation(
                previous_rows[continuation_index],
                continuation_previous,
                previous_region,
            ):
                continuation_previous = previous_rows[continuation_index]
                continuation_index += 1
            previous_index = continuation_index
        if not previous_base_rows:
            continue
        previous_row = previous_base_rows[-1]
        following_row = following_rows[0]
        previous_billed_column = _proven_billed_amount_column(previous_region)
        current_billed_column = _proven_billed_amount_column(current_region)
        if previous_billed_column is None or current_billed_column is None:
            continue
        previous_billed_cells = _cells_for_column(previous_row, previous_billed_column)
        following_billed_cells = _cells_for_column(following_row, current_billed_column)
        previous_billed = (
            parse_amount(
                previous_billed_cells[0].text,
                currency_hint=group.printed_total.currency,
            )
            if len(previous_billed_cells) == 1
            else None
        )
        if (
            len(previous_billed_cells) != 1
            or not is_money_shaped(previous_billed_cells[0].text)
            or previous_billed is None
            or previous_billed.amount in {None, Decimal("0")}
            or len(following_billed_cells) != 1
            or not is_money_shaped(following_billed_cells[0].text)
        ):
            continue
        handoffs[id(previous_row)] = tuple(
            row.model_copy(
                update={
                    "diagnostics": tuple(
                        "subordinate_detail_continuation"
                        if diagnostic == "leading_subordinate_detail_continuation"
                        else diagnostic
                        for diagnostic in row.diagnostics
                    )
                }
            )
            for row in leading_rows
        )
        owned_leading_rows.update(id(row) for row in leading_rows)
    return handoffs, frozenset(owned_leading_rows)


def normalize_statement(discovery: StatementDiscovery) -> StatementNormalization:
    """Normalize discovered current-cycle rows and reconcile exact printed totals."""

    transactions: list[Transaction] = []
    totals: list[PrintedTotal] = []
    row_results: list[RowNormalizationResult] = []
    diagnostics: list[str] = list(discovery.diagnostics)
    rows_not_emitted = 0
    for group in discovery.groups:
        total, total_diagnostics = _printed_total(group)
        diagnostics.extend(total_diagnostics)
        if total is not None:
            totals.append(total)
        row_ordinal = 0
        ordered_regions = tuple(
            sorted(
                group.table_regions,
                key=lambda item: (item.page_number, item.bbox[1], item.bbox[0]),
            )
        )
        cross_page_handoffs, owned_leading_rows = _cross_page_leading_detail_handoffs(
            ordered_regions,
            group,
        )
        for region in ordered_regions:
            date_column_kinds = _structural_date_column_kinds(
                region,
                discovery.date_year_context,
            )
            rows = tuple(sorted(region.rows, key=lambda item: (item.bbox[1], item.bbox[0])))
            index = 0
            while index < len(rows):
                row = rows[index]
                if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL):
                    if id(row) in owned_leading_rows:
                        index += 1
                        continue
                    row_ordinal += 1
                    row_results.append(
                        RowNormalizationResult(
                            page_number=row.page_number,
                            bbox=row.bbox,
                            raw_text=_row_text((row,)),
                            evidence=_row_evidence((row,)),
                            confidence=row.confidence,
                            diagnostics=("unowned_leading_subordinate_detail_continuation",),
                        )
                    )
                    rows_not_emitted += 1
                    index += 1
                    continue
                row_ordinal += 1
                if _is_printed_total_row(row, group):
                    row_results.append(
                        RowNormalizationResult(
                            page_number=row.page_number,
                            bbox=row.bbox,
                            raw_text=_row_text((row,)),
                            evidence=_row_evidence((row,)),
                            confidence=row.confidence,
                            diagnostics=("printed_total_row",),
                        )
                    )
                    index += 1
                    continue
                continuations: list[Row] = []
                continuation_index = index + 1
                previous = row
                while continuation_index < len(rows) and is_description_continuation(
                    rows[continuation_index], previous, region
                ):
                    continuations.append(rows[continuation_index])
                    previous = rows[continuation_index]
                    continuation_index += 1
                continuations.extend(cross_page_handoffs.get(id(row), ()))
                transaction_id = f"{group.group_id}-p{row.page_number:03d}-r{row_ordinal:04d}"
                attempt = _normalize_row(
                    row=row,
                    continuation_rows=continuations,
                    region=region,
                    group=group,
                    year_context=discovery.date_year_context,
                    date_column_kinds=date_column_kinds,
                    transaction_id=transaction_id,
                )
                row_result = attempt.result
                row_results.append(row_result)
                if row_result.transaction is None:
                    if attempt.disposition is FieldDisposition.REJECT_ROW:
                        rows_not_emitted += 1
                else:
                    transactions.append(row_result.transaction)
                for continuation in continuations:
                    row_ordinal += 1
                    continuation_diagnostic = (
                        "merged_subordinate_detail_continuation"
                        if has_row_tag(continuation, RowTag.SUBORDINATE_DETAIL)
                        else "merged_auxiliary_continuation"
                        if has_row_tag(continuation, RowTag.AUXILIARY_CONTINUATION)
                        else "merged_description_continuation"
                    )
                    row_results.append(
                        RowNormalizationResult(
                            page_number=continuation.page_number,
                            bbox=continuation.bbox,
                            raw_text=_row_text((continuation,)),
                            evidence=_row_evidence((continuation,)),
                            confidence=continuation.confidence,
                            diagnostics=(continuation_diagnostic,),
                        )
                    )
                index = continuation_index
    if rows_not_emitted:
        diagnostics.append(f"rows_not_emitted:{rows_not_emitted}")
    reconciliation = reconciliation_outcome(transactions, totals)
    if diagnostics:
        reconciliation = reconciliation.model_copy(
            update={
                "status": Status.UNRECONCILED,
                "diagnostics": tuple(dict.fromkeys((*reconciliation.diagnostics, *diagnostics))),
            }
        )
    confidence_values = tuple(result.confidence for result in row_results)
    confidence = statistics.mean(confidence_values) if confidence_values else 0.0
    return StatementNormalization(
        discovery=discovery,
        transactions=tuple(transactions),
        printed_totals=tuple(totals),
        row_results=tuple(row_results),
        reconciliation=reconciliation,
        confidence=confidence,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


__all__ = [
    "AmountParseResult",
    "RowNormalizationResult",
    "StatementNormalization",
    "normalize_statement",
    "parse_amount",
]
