"""Typed transaction-evidence ownership and semantic validation."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from ccparser.date_tokens import FULL_DATE_TOKEN_PATTERNS, SHORT_DATE_TOKEN_PATTERNS
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.geometry import (
    bbox_center_x,
    bbox_height,
    bbox_width,
    union_bbox,
    vertical_overlap,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    has_stable_unknown_profile,
    is_location_identifier,
    original_currency_spilled_into_location,
    proven_billed_amount_column,
)
from ccparser.layout.marker_bands import is_proven_ocr_marker_cell
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import logical_text_for_evidence
from ccparser.money import (
    canonical_currency,
    currencies_in_text,
    is_currency_shaped,
    is_money_shaped,
    parse_amount,
)
from ccparser.normalization_dates import (
    DateColumnKind,
    boundary_date_description_splits,
    contains_date_cue,
    cross_cell_date_source_cells,
    date_column_header_kind,
    has_proven_unanchored_short_date,
    is_date_shaped,
    is_typed_conversion_source,
    matching_date_atom_ids,
    nonmaterial_date_layout_atom_ids,
    parsed_cross_cell_conversion_evidence,
    proven_assigned_date_evidence,
    proven_unanchored_short_date_style,
)
from ccparser.normalization_description import (
    has_processor_reference_alignment,
    is_numeric_processor_reference,
    is_standalone_primary_description,
    matching_positioned_cell_text,
)
from ccparser.semantic_evidence import (
    EvidenceClaim,
    EvidenceLedger,
    FragmentedDateCandidate,
    SemanticOwner,
)
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
_FINANCIAL_OR_DATE_HEADER_MARKERS = (
    "amount",
    "currency",
    "fee",
    "commission",
    "rate",
    "total",
    "date",
    "installment",
    "conversion",
    "סכום",
    "מטבע",
    "עמלה",
    "שער",
    "סה כ",
    "תאריך",
    "תשלום",
    "המרה",
)


def _contains_marker(text: str, markers: Iterable[str]) -> bool:
    return contains_token_sequence(text, markers)


def _has_non_date_semantic_evidence(cell: Cell) -> bool:
    text = normalize_text(cell.text)
    return (
        is_money_shaped(text)
        or is_currency_shaped(text)
        or _EMBEDDED_INSTALLMENT_PATTERN.fullmatch(text) is not None
        or (bool(currencies_in_text(text)) and any(char.isdigit() for char in text))
        or (
            _contains_marker(text, _EMBEDDED_AMOUNT_CUES)
            and _EMBEDDED_AMOUNT_PATTERN.search(text) is not None
        )
        or (
            _contains_marker(text, _EMBEDDED_INSTALLMENT_CUES)
            and _EMBEDDED_INSTALLMENT_PATTERN.search(text) is not None
        )
    )


def _is_relevant_cell(cell: Cell) -> bool:
    text = normalize_text(cell.text)
    return (
        _has_non_date_semantic_evidence(cell)
        or is_date_shaped(text)
        or (_contains_marker(text, _EMBEDDED_DATE_CUES) and contains_date_cue(text))
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


def _adjacent_unknown_processor_reference_cells(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> frozenset[Cell]:
    description_columns = columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)
    if len(description_columns) != 1:
        return frozenset()
    description_column = description_columns[0]
    description_cells = cells_in_column(row.cells, description_column)
    if len(description_cells) != 1:
        return frozenset()
    description_text = matching_positioned_cell_text(ledger, description_cells[0])
    if description_text is None or not is_standalone_primary_description(description_text):
        return frozenset()
    explicitly_owned_columns = _explicit_ancillary_unknown_columns(
        region
    ) | explicit_category_unknown_columns(region)
    candidates = tuple(
        cell
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if abs(column.index - description_column.index) == 1
        and column.index not in explicitly_owned_columns
        and not _contains_marker(
            _column_header_text(region, column),
            _FINANCIAL_OR_DATE_HEADER_MARKERS,
        )
        for cell in cells_in_column(row.cells, column)
        if (cell_text := matching_positioned_cell_text(ledger, cell)) is not None
        and is_numeric_processor_reference(cell_text)
        and has_processor_reference_alignment(cell.bbox, description_cells[0].bbox)
    )
    return frozenset(candidates) if len(candidates) == 1 else frozenset()


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


def _cell_has_currency_evidence(cell: Cell) -> bool:
    source_texts = tuple(
        dict.fromkeys(
            text
            for text in (
                cell.text,
                logical_text_for_evidence(cell.glyphs, cell.words),
                *(word.text for word in cell.words),
                *(glyph.char for glyph in cell.glyphs),
            )
            if normalize_text(text)
        )
    )
    return any(currencies_in_text(text) for text in source_texts)


def _conversion_date_fully_realizes_cell_role(
    cell: Cell,
    column: ColumnSpec,
    ledger: EvidenceLedger,
    accepted_conversion_date_atom_ids: frozenset[int],
) -> bool:
    if column.role is not ColumnRole.CONVERSION_DATE or _cell_has_currency_evidence(cell):
        return False
    accepted_cell_atom_ids = ledger.atoms_for_cell(cell) & accepted_conversion_date_atom_ids
    return any(
        candidate.atom_ids <= accepted_cell_atom_ids
        for candidate in ledger.fragmented_date_candidates(cell)
    )


def _explicit_ancillary_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_ANCILLARY_HEADER_MARKERS,
        )
    )


def _is_explicit_nonfinancial_ancillary_cell(
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
    ledger: EvidenceLedger,
    explicit_ancillary_columns: frozenset[int],
) -> bool:
    if (
        column.role is not ColumnRole.UNKNOWN
        or column.index not in explicit_ancillary_columns
        or _contains_marker(
            _column_header_text(region, column),
            _FINANCIAL_OR_DATE_HEADER_MARKERS,
        )
        or is_typed_conversion_source(column, cell, region)
    ):
        return False
    candidates = ledger.fragmented_date_candidates(cell)
    if len(candidates) > 1:
        return False
    date_atom_ids = frozenset(atom_id for candidate in candidates for atom_id in candidate.atom_ids)
    cell_atom_ids = ledger.atoms_for_cell(cell)
    if ledger.positioned_decimal_candidates(cell_atom_ids - date_atom_ids):
        return False
    source_texts = tuple(
        dict.fromkeys(
            filter(
                None,
                (
                    cell.text,
                    logical_text_for_evidence(cell.glyphs, cell.words),
                    *(word.text for word in cell.words),
                ),
            )
        )
    )
    if any(
        currencies_in_text(source)
        or "%" in source
        or any(unicodedata.category(char) == "Sc" for char in source)
        or (not candidates and _EMBEDDED_INSTALLMENT_PATTERN.search(source) is not None)
        or (
            _contains_marker(source, _EMBEDDED_AMOUNT_CUES)
            and _EMBEDDED_AMOUNT_PATTERN.search(source) is not None
        )
        for source in source_texts
    ):
        return False
    residual_ids = cell_atom_ids - date_atom_ids
    return not any(
        currencies_in_text(ledger.atoms[atom_id].text)
        or "%" in ledger.atoms[atom_id].text
        or any(unicodedata.category(char) == "Sc" for char in ledger.atoms[atom_id].text)
        for atom_id in residual_ids
    )


def _could_be_calendar_valid_fragmented_date(
    candidate: FragmentedDateCandidate,
    year_context: DiscoveredDateYearContext | None,
) -> bool:
    text = normalize_text(candidate.text)
    matched_supported_shape = False
    for pattern in FULL_DATE_TOKEN_PATTERNS.values():
        if (match := pattern.fullmatch(text)) is None:
            continue
        matched_supported_shape = True
        try:
            date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
        return True

    short_patterns = tuple(
        pattern
        for style, pattern in SHORT_DATE_TOKEN_PATTERNS.items()
        if year_context is None
        or style.value.startswith("year_first") == year_context.style.value.startswith("year_first")
    )
    for pattern in short_patterns:
        if (match := pattern.fullmatch(text)) is None:
            continue
        matched_supported_shape = True
        suffix = int(match.group("year"))
        proven_years = dict(year_context.year_by_suffix) if year_context is not None else {}
        if year_context is not None and year_context.year is not None:
            proven_years.setdefault(year_context.year % 100, year_context.year)
        validation_year = proven_years.get(suffix, 2000)
        try:
            date(
                validation_year,
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
        return True
    return not matched_supported_shape


def _is_invalid_untyped_ancillary_date_cell(
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
    candidates: Sequence[FragmentedDateCandidate],
    explicit_ancillary_unknowns: frozenset[int],
    year_context: DiscoveredDateYearContext | None,
) -> bool:
    return (
        column.role is ColumnRole.UNKNOWN
        and column.index in explicit_ancillary_unknowns
        and bool(candidates)
        and not any(
            _could_be_calendar_valid_fragmented_date(candidate, year_context)
            for candidate in candidates
        )
        and not is_typed_conversion_source(column, cell, region)
        and not _has_non_date_semantic_evidence(cell)
    )


def explicit_category_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if _contains_marker(
            _column_header_text(region, column),
            _EXPLICIT_CATEGORY_HEADER_MARKERS,
        )
    )


def _stable_unknown_columns(region: TableRegion) -> frozenset[int]:
    return frozenset(
        column.index
        for column in columns_for_role(region.table_schema, ColumnRole.UNKNOWN)
        if has_stable_unknown_profile(region, column)
    )


def _proven_stable_ancillary_unknown_columns(region: TableRegion) -> frozenset[int]:
    if len(columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)) != 1:
        return frozenset()
    return _stable_unknown_columns(region) & _explicit_ancillary_unknown_columns(region)


def assignment_diagnostics(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    *,
    accepted_conversion_date_atom_ids: frozenset[int] = frozenset(),
    year_context: DiscoveredDateYearContext | None = None,
) -> tuple[str, ...]:
    """Return ordered diagnostics for ambiguous cell-to-column assignments."""

    diagnostics: list[str] = []
    explicit_ancillary_unknowns = _explicit_ancillary_unknown_columns(region)
    explicit_category_unknowns = explicit_category_unknown_columns(region)
    proven_stable_ancillary_unknowns = _proven_stable_ancillary_unknown_columns(region)
    cross_cell_date_sources = cross_cell_date_source_cells(row, region, ledger)
    for cell in row.cells:
        columns = tuple(
            column
            for column in region.table_schema.columns
            if column.bbox[0] <= bbox_center_x(cell.bbox) <= column.bbox[2]
        )
        conversion_candidates = ledger.fragmented_date_candidates(cell)
        relevant = (
            _is_relevant_cell(cell)
            or bool(conversion_candidates)
            or cell in cross_cell_date_sources
        )
        if len(columns) != 1:
            diagnostics.append("unmatched_cell" if not columns else "multiply_assigned_cell")
            if relevant:
                diagnostics.append("unresolved_relevant_cell")
            continue
        column = columns[0]
        invalid_untyped_ancillary_date = _is_invalid_untyped_ancillary_date_cell(
            cell,
            column,
            region,
            conversion_candidates,
            explicit_ancillary_unknowns,
            year_context,
        )
        if invalid_untyped_ancillary_date and cell not in cross_cell_date_sources:
            relevant = False
        explicit_nonfinancial_ancillary = _is_explicit_nonfinancial_ancillary_cell(
            cell,
            column,
            region,
            ledger,
            explicit_ancillary_unknowns,
        )
        safe_card_identifier = column.role is ColumnRole.UNKNOWN and _is_safe_card_identifier_cell(
            row, cell
        )
        safe_ancillary_unknown = column.role is ColumnRole.UNKNOWN and (
            is_proven_ocr_marker_cell(cell, column)
            or explicit_nonfinancial_ancillary
            or column.index in proven_stable_ancillary_unknowns
            or (
                column.index in explicit_ancillary_unknowns | explicit_category_unknowns
                and not relevant
            )
        )
        deferred_semantic_candidate = column.role is ColumnRole.UNKNOWN and (
            (is_typed_conversion_source(column, cell, region) and bool(conversion_candidates))
            or cell in cross_cell_date_sources
            or (
                bool(conversion_candidates)
                and any(
                    candidate.atom_ids <= accepted_conversion_date_atom_ids
                    for candidate in conversion_candidates
                )
                and not _has_non_date_semantic_evidence(cell)
            )
        )
        safe_edge_artifact = _is_isolated_ocr_edge_artifact_cell(cell, column, region)
        safe_location_identifier = column.role is ColumnRole.LOCATION and (
            is_location_identifier(cell.text)
            or original_currency_spilled_into_location(cell, region) is not None
        )
        unresolved_role_diagnostics = tuple(
            value
            for value in column.diagnostics
            if value == "ambiguous_role" or value.startswith("alternative_role:")
            if not (
                value == "alternative_role:currency"
                and _conversion_date_fully_realizes_cell_role(
                    cell,
                    column,
                    ledger,
                    accepted_conversion_date_atom_ids,
                )
            )
        )
        has_alternative = bool(unresolved_role_diagnostics)
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
                f"column:{column.index}:{value}" for value in unresolved_role_diagnostics
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


def _date_description_boundary_layout_atom_ids(
    *,
    row: Row,
    region: TableRegion,
    column: ColumnSpec,
    cell: Cell,
    ledger: EvidenceLedger,
    claims: Sequence[EvidenceClaim],
    proven_date_atom_ids: frozenset[int],
    existing_layout_atom_ids: frozenset[int],
    year_context: DiscoveredDateYearContext | None,
) -> frozenset[int]:
    splits = tuple(
        split
        for split in boundary_date_description_splits(row, region, year_context)
        if split[0] is cell
    )
    if len(splits) != 1 or not proven_date_atom_ids:
        return frozenset()
    _, _, residual_text = splits[0]
    description_atom_ids = frozenset(
        atom_id
        for claim in claims
        if claim.owner is SemanticOwner.DESCRIPTION
        for atom_id in claim.atom_ids
        if atom_id in ledger.atoms_for_cell(cell)
    )
    if (
        not description_atom_ids
        or not any(char.isalpha() for char in residual_text)
        or any(char.isdigit() for char in residual_text)
        or normalize_text(ledger.render(description_atom_ids)) != normalize_text(residual_text)
    ):
        return frozenset()
    already_claimed = frozenset(atom_id for claim in claims for atom_id in claim.atom_ids)
    cell_atom_ids = ledger.atoms_for_cell(cell)
    marker_atom_ids = (
        cell_atom_ids - proven_date_atom_ids - existing_layout_atom_ids - already_claimed
    )
    if len(marker_atom_ids) != 1:
        return frozenset()
    marker_atom = ledger.atoms[next(iter(marker_atom_ids))]
    date_atoms = tuple(ledger.atoms[atom_id] for atom_id in proven_date_atom_ids)
    description_atoms = tuple(ledger.atoms[atom_id] for atom_id in description_atom_ids)
    if (
        marker_atom.glyph is None
        or marker_atom.glyph.source != "digital"
        or marker_atom.glyph.confidence != 1.0
        or len(marker_atom.glyph.char) != 1
        or not marker_atom.glyph.char.isdigit()
        or not date_atoms
        or not description_atoms
        or any(atom.glyph is None or atom.glyph.source != "digital" for atom in date_atoms)
        or any(atom.glyph is None or atom.glyph.source != "digital" for atom in description_atoms)
    ):
        return frozenset()
    date_glyphs = tuple(atom.glyph for atom in date_atoms if atom.glyph is not None)
    description_glyphs = tuple(atom.glyph for atom in description_atoms if atom.glyph is not None)
    if marker_atom.glyph.font in {glyph.font for glyph in (*date_glyphs, *description_glyphs)}:
        return frozenset()
    date_digit_widths = tuple(
        bbox_width(glyph.bbox) for glyph in date_glyphs if glyph.char.isdigit()
    )
    if (
        not date_digit_widths
        or min(date_digit_widths) <= 0.0
        or bbox_width(marker_atom.bbox) < statistics.median(date_digit_widths) * 1.2
    ):
        return frozenset()
    exact_marker_words = tuple(
        word
        for word in cell.words
        if word.source == "digital"
        and word.confidence == 1.0
        and normalize_text(word.text) == marker_atom.glyph.char
        and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == marker_atom_ids
    )
    if len(exact_marker_words) != 1:
        return frozenset()
    date_bbox = union_bbox(atom.bbox for atom in date_atoms)
    description_bbox = union_bbox(atom.bbox for atom in description_atoms)
    if description_bbox[2] <= date_bbox[0] and marker_atom.bbox[0] >= date_bbox[2]:
        date_gap = marker_atom.bbox[0] - date_bbox[2]
    elif date_bbox[2] <= description_bbox[0] and marker_atom.bbox[2] <= date_bbox[0]:
        date_gap = date_bbox[0] - marker_atom.bbox[2]
    else:
        return frozenset()
    date_height = min(bbox_height(date_bbox), bbox_height(marker_atom.bbox))
    description_height = min(
        bbox_height(description_bbox),
        bbox_height(marker_atom.bbox),
    )
    description_gap = max(
        description_bbox[0] - marker_atom.bbox[2],
        marker_atom.bbox[0] - description_bbox[2],
        0.0,
    )
    if (
        date_height <= 0.0
        or description_height <= 0.0
        or not date_height * 0.1 < date_gap <= date_height * 0.25
        or description_gap <= description_height * 0.1
        or vertical_overlap(date_bbox, marker_atom.bbox) < 0.8
        or vertical_overlap(description_bbox, marker_atom.bbox) < 0.8
        or not column.bbox[0] <= bbox_center_x(marker_atom.bbox) <= column.bbox[2]
    ):
        return frozenset()
    return marker_atom_ids


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
    date_column_kinds: Mapping[int, DateColumnKind],
    accepted_conversion_date_atom_ids: frozenset[int] = frozenset(),
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
    explicit_category_unknowns = explicit_category_unknown_columns(region)
    description_columns = columns_for_role(region.table_schema, ColumnRole.DESCRIPTION)
    description_index = description_columns[0].index if len(description_columns) == 1 else None
    boundary_atom_ids: set[int] = set()

    for row in rows:
        row_has_safe_card_identifier = any(
            _is_safe_card_identifier_cell(row, cell) for cell in row.cells
        )
        adjacent_unknown_processor_references = _adjacent_unknown_processor_reference_cells(
            row,
            region,
            ledger,
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
            for candidate_date, evidence in parsed_cross_cell_conversion_evidence(
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
                kind = date_column_header_kind(column) or date_column_kinds.get(column.index)
                expected = posting_date if kind == DateColumnKind.POSTING else transaction_date
                owner = (
                    SemanticOwner.POSTING_DATE
                    if kind == DateColumnKind.POSTING
                    else SemanticOwner.TRANSACTION_DATE
                )
                matched_date_ids = matching_date_atom_ids(
                    ledger,
                    cell,
                    expected,
                    year_context,
                )
                proven_date_ids, proven_layout_ids = proven_assigned_date_evidence(
                    row,
                    region,
                    column,
                    cell,
                    ledger,
                    expected,
                    year_context,
                )
                if expected is not None:
                    layout_noise_ids = (
                        nonmaterial_date_layout_atom_ids(ledger, cell, matched_date_ids)
                        | proven_layout_ids
                    )
                    layout_noise_ids |= _date_description_boundary_layout_atom_ids(
                        row=row,
                        region=region,
                        column=column,
                        cell=cell,
                        ledger=ledger,
                        claims=claims,
                        proven_date_atom_ids=proven_date_ids,
                        existing_layout_atom_ids=layout_noise_ids,
                        year_context=year_context,
                    )
                    _add_remaining_claim(
                        claims,
                        owner,
                        (matched_date_ids | proven_date_ids) - layout_noise_ids,
                    )
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.LAYOUT_NOISE,
                        layout_noise_ids,
                    )
                elif (
                    year_context is None
                    and (style := proven_unanchored_short_date_style(region, column)) is not None
                    and has_proven_unanchored_short_date(cell, style)
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
                    matching_date_atom_ids(ledger, cell, conversion_date, year_context),
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
                accepted_contextual_conversion = bool(conversion_candidates) and any(
                    candidate.atom_ids <= accepted_conversion_date_atom_ids
                    for candidate in conversion_candidates
                )
                valid_conversion_candidates = tuple(
                    candidate
                    for candidate in conversion_candidates
                    if _could_be_calendar_valid_fragmented_date(candidate, year_context)
                )
                invalid_untyped_ancillary_date = _is_invalid_untyped_ancillary_date_cell(
                    cell,
                    column,
                    region,
                    conversion_candidates,
                    explicit_ancillary_unknowns,
                    year_context,
                )
                explicit_nonfinancial_ancillary = _is_explicit_nonfinancial_ancillary_cell(
                    cell,
                    column,
                    region,
                    ledger,
                    explicit_ancillary_unknowns,
                )
                is_foreign_conversion_evidence = (
                    original_currency is not None
                    and original_currency != billing_currency
                    and is_typed_conversion_source(column, cell, region)
                    and bool(valid_conversion_candidates)
                )
                if cell in adjacent_unknown_processor_references:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.PROCESSOR_REFERENCE,
                        cell_ids,
                    )
                elif explicit_nonfinancial_ancillary:
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif accepted_contextual_conversion:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.CONVERSION_DATE,
                        cell_ids & accepted_conversion_date_atom_ids,
                    )
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif is_proven_ocr_marker_cell(cell, column):
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif is_foreign_conversion_evidence:
                    _add_remaining_claim(
                        claims,
                        SemanticOwner.CONVERSION_DATE,
                        matching_date_atom_ids(
                            ledger,
                            cell,
                            conversion_date,
                            year_context,
                        ),
                    )
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif conversion_candidates and not invalid_untyped_ancillary_date:
                    continue
                elif _is_isolated_ocr_edge_artifact_cell(cell, column, region):
                    _add_remaining_claim(claims, SemanticOwner.LAYOUT_NOISE, cell_ids)
                elif column.index in stable_unknowns or row_has_safe_card_identifier:
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif column.index in explicit_category_unknowns and not _is_relevant_cell(cell):
                    _add_remaining_claim(claims, SemanticOwner.CATEGORY, cell_ids)
                elif column.index in explicit_ancillary_unknowns and (
                    invalid_untyped_ancillary_date or not _is_relevant_cell(cell)
                ):
                    _add_remaining_claim(claims, SemanticOwner.ANCILLARY, cell_ids)
                elif description_index is not None and abs(column.index - description_index) == 1:
                    boundary_atom_ids.update(
                        atom_id
                        for atom_id in cell_ids
                        if any(char.isalpha() for char in ledger.atoms[atom_id].text)
                    )
            elif column.role is ColumnRole.DESCRIPTION:
                date_columns = columns_for_role(region.table_schema, ColumnRole.DATE)
                if year_context is None and len(date_columns) == 1:
                    unanchored_style = proven_unanchored_short_date_style(
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
    "explicit_category_unknown_columns",
    "role_contract_diagnostics",
    "validate_transaction_semantics",
]
