"""Typed transaction-evidence ownership and semantic validation."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ccparser.date_tokens import SHORT_DATE_TOKEN_PATTERNS
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.geometry import bbox_center_x
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    is_location_identifier,
    isolated_date_token,
    original_currency_spilled_into_location,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag, is_structural_continuation
from ccparser.money import (
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
    contains_date_cue,
    is_date_shaped,
)
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner
from ccparser.text_tokens import contains_token_sequence, normalize_text, phrase_tokens


@dataclass(frozen=True, slots=True)
class SemanticValidation:
    """Final evidence claims and ordered transaction-semantic diagnostics."""

    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]


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


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    return contains_token_sequence(text, markers)


def _is_relevant_cell(cell: Cell) -> bool:
    text = normalize_text(cell.text)
    return (
        is_money_shaped(text)
        or is_currency_shaped(text)
        or is_date_shaped(text)
        or _EMBEDDED_INSTALLMENT_PATTERN.fullmatch(text) is not None
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
        if _CARD_IDENTIFIER_PATTERN.fullmatch(normalize_text(candidate.text)) is not None
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
        for candidate in cells_in_column(candidate_row.cells, column)
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


def _column_header_text(region: TableRegion, column: ColumnSpec) -> str:
    header_cells = tuple(
        cell
        for cell in region.table_schema.header_cells
        if cell in column.source_cells
        or column.bbox[0] <= bbox_center_x(cell.bbox) <= column.bbox[2]
    )
    return normalize_text(" ".join(cell.text for cell in header_cells))


def _explicit_ancillary_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_ANCILLARY_HEADER_MARKERS,
        )
    )


def _explicit_category_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_CATEGORY_HEADER_MARKERS,
        )
    )


def _stable_unknown_columns(region: TableRegion) -> frozenset[int]:
    stable: set[int] = set()
    base_rows = tuple(row for row in region.rows if not is_structural_continuation(row))
    for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN):
        header_text = _column_header_text(region, column)
        values = tuple(
            cell
            for row in base_rows
            for cell in cells_in_column(row.cells, column)
            if any(char.isalnum() for char in cell.text)
        )
        if not header_text or not any(char.isalnum() for char in header_text) or len(values) < 2:
            continue
        profiles: dict[str, int] = {}
        for cell in values:
            text = normalize_text(cell.text)
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


def assignment_diagnostics(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> tuple[str, ...]:
    """Return ordered diagnostics for ambiguous cell-to-column assignments."""

    diagnostics: list[str] = []
    explicit_ancillary_unknowns = _explicit_ancillary_unknown_columns(region)
    explicit_category_unknowns = _explicit_category_unknown_columns(region)
    cross_cell_date_sources = _cross_cell_date_source_cells(row, region, ledger)
    for cell in row.cells:
        columns = tuple(
            column
            for column in region.table_schema.columns
            if column.bbox[0] <= bbox_center_x(cell.bbox) <= column.bbox[2]
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


def role_contract_diagnostics(region: TableRegion) -> tuple[str, ...]:
    """Return ordered diagnostics for unsupported semantic role cardinality."""

    role_columns: dict[ColumnRole, tuple[ColumnSpec, ...]] = {
        role: columns_for_role(region.table_schema, role)
        for role in ColumnRole
        if role is not ColumnRole.UNKNOWN
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
    transaction_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    billed_column = proven_billed_amount_column(region.table_schema, transaction_rows)
    for role, maximum in maximums.items():
        if len(role_columns[role]) > maximum and not (
            role is ColumnRole.AMOUNT and billed_column is not None
        ):
            diagnostics.append(f"unsupported_role_cardinality:{role.value}")
    if role_columns[ColumnRole.ORIGINAL_CURRENCY] and not role_columns[ColumnRole.ORIGINAL_AMOUNT]:
        diagnostics.append("original_currency_without_original_amount")
    return tuple(diagnostics)


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


def validate_transaction_semantics(
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
) -> SemanticValidation:
    """Complete transaction evidence ownership and return ordered diagnostics."""

    claims = list(initial_claims)
    _add_remaining_claim(
        claims,
        SemanticOwner.BILLED_VALUE,
        ledger.atoms_for_cell(amount_cell),
    )

    stable_unknowns = _stable_unknown_columns(region)
    explicit_ancillary_unknowns = _explicit_ancillary_unknown_columns(region)
    explicit_category_unknowns = _explicit_category_unknown_columns(region)
    description_columns = columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)
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
                if column.bbox[0] <= bbox_center_x(cell.bbox) <= column.bbox[2]
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
                    description_phrase = " ".join(phrase_tokens(description))
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.DESCRIPTION,
                        (
                            atom_id
                            for atom_id in cell_ids
                            if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                            and (atom_phrase := " ".join(phrase_tokens(ledger.atoms[atom_id].text)))
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
                date_columns = columns_for_role(region.table_schema, ColumnRole.DATE)
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
                                    normalize_text(ledger.atoms[atom_id].text)
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
    return SemanticValidation(
        claims=tuple(claims),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


__all__ = [
    "SemanticValidation",
    "assignment_diagnostics",
    "role_contract_diagnostics",
    "validate_transaction_semantics",
]
