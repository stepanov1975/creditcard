"""Typed date parsing, recovery, classification, and semantic extraction."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import pairwise

from ccparser.date_tokens import (
    MAX_CONTEXT_YEAR,
    MIN_CONTEXT_YEAR,
    SHORT_DATE_TOKEN_PATTERNS,
    DateTokenStyle,
    has_date_numeric_run_boundaries,
    has_date_token_boundaries,
)
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.evidence.models import Glyph
from ccparser.geometry import (
    BBox,
    bbox_center_y,
    horizontal_overlap,
    union_bbox,
    vertical_overlap,
)
from ccparser.geometry import bbox_center_x as _center_x
from ccparser.geometry import bbox_height as _height
from ccparser.geometry import bbox_width as _width
from ccparser.geometry import center_inside as _bbox_center_inside
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    isolated_date_token,
    proven_billed_amount_column,
    source_or_center_cells,
)
from ccparser.layout.marker_bands import (
    is_visible_vertical_layout_marker,
    proven_ocr_marker_word_partition,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import cell_has_ocr_evidence, logical_text_for_evidence
from ccparser.money import currencies_in_text, is_money_shaped
from ccparser.normalization_fields import is_installment_shaped
from ccparser.semantic_evidence import EvidenceAtom, EvidenceLedger
from ccparser.text_tokens import contains_token_sequence, normalize_text, phrase_tokens


class DateColumnKind(StrEnum):
    """Supported semantic roles for transaction-table date columns."""

    TRANSACTION = "transaction"
    POSTING = "posting"


@dataclass(frozen=True, slots=True)
class DateExtraction:
    """Transaction, posting, and conversion dates extracted from explicit columns."""

    transaction_date: date | None
    posting_date: date | None
    conversion_date: date | None
    diagnostics: tuple[str, ...]
    unresolved_conversion_cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class ConversionDateExtraction:
    """A conversion date inferred from semantic evidence and its exact sources."""

    value: date | None
    diagnostics: tuple[str, ...]
    source_cells: frozenset[Cell]
    source_atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class CrossCellDateEvidence:
    text: str
    cells: frozenset[Cell]
    atom_ids: frozenset[int]


_DATE_PATTERN = re.compile(r"^(\d{1,4})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{1,4})$")
_DATE_TOKEN_PATTERN = re.compile(
    r"(?<!\d)\d{1,4}\s*(?P<separator>[./-])\s*\d{1,2}\s*"
    r"(?P=separator)\s*\d{1,4}(?!\d)"
)
_DATE_CUE_PATTERN = re.compile(r"(?<!\d)\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?!\d)")
_MIN_DATE_DESCRIPTION_CELL_OVERLAP = 0.08
_EXPLICIT_CONVERSION_DATE_CUES = (
    "converted on",
    "conversion date",
    "date of conversion",
    "תאריך המרה",
    "תאריך ההמרה",
    "הומר בתאריך",
)
_GENERIC_CONVERSION_CUES = (
    "converted at",
    "converted to",
    "conversion detail",
)
_CONVERSION_DATE_CUES = (*_EXPLICIT_CONVERSION_DATE_CUES, *_GENERIC_CONVERSION_CUES)
_INDIVISIBLE_DATE_CONTEXT_TOKENS = frozenset(
    token
    for cue in _CONVERSION_DATE_CUES
    for token in phrase_tokens(cue, ignore_acronym_quotes=True)
)
_CONVERSION_RATE_CUES = (
    "conversion rate",
    "exchange rate",
    "representative rate",
    "שער המרה",
    "שער ההמרה",
    "שער יציג",
    "שער",
)
_RATE_DECIMAL_PATTERN = re.compile(r"(?<!\d)\d+[.,]\d+(?!\d)")
_LOCAL_DATE_STYLES = {
    "/": (DateTokenStyle.DAY_FIRST_SLASH, DateTokenStyle.YEAR_FIRST_SLASH),
    ".": (DateTokenStyle.DAY_FIRST_DOT, DateTokenStyle.YEAR_FIRST_DOT),
    "-": (DateTokenStyle.DAY_FIRST_DASH, DateTokenStyle.YEAR_FIRST_DASH),
}


def _has_conversion_date_cue(text: str) -> bool:
    return contains_token_sequence(
        text,
        _CONVERSION_DATE_CUES,
        allow_hebrew_clitic_prefix=True,
    )


def _has_explicit_conversion_date_cue(text: str) -> bool:
    return contains_token_sequence(
        text,
        _EXPLICIT_CONVERSION_DATE_CUES,
        allow_hebrew_clitic_prefix=True,
    )


def _column_header_text(column: ColumnSpec, region: TableRegion) -> str:
    return " ".join(
        header.text for header in source_or_center_cells(region.table_schema.header_cells, column)
    )


def _cell_source_texts(cell: Cell) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            text
            for text in (cell.text, logical_text_for_evidence(cell.glyphs, cell.words))
            if normalize_text(text)
        )
    )


def is_typed_conversion_source(
    column: ColumnSpec,
    cell: Cell,
    region: TableRegion,
) -> bool:
    """Return whether schema or cell evidence types ``cell`` as a conversion date source."""

    if column.role is ColumnRole.CONVERSION_DATE:
        return True
    if column.role is not ColumnRole.UNKNOWN:
        return False
    return _has_conversion_date_cue(_column_header_text(column, region)) or any(
        _has_conversion_date_cue(source_text) for source_text in _cell_source_texts(cell)
    )


def _is_required_conversion_date_source(
    column: ColumnSpec,
    cell: Cell,
    region: TableRegion,
) -> bool:
    if column.role is ColumnRole.CONVERSION_DATE:
        return True
    header_text = _column_header_text(column, region)
    return _has_conversion_date_cue(header_text) or any(
        _has_explicit_conversion_date_cue(source_text) for source_text in _cell_source_texts(cell)
    )


def _has_nonempty_source_content(cell: Cell) -> bool:
    return bool(_cell_source_texts(cell))


def _is_explicit_non_date_rate_source(
    column: ColumnSpec,
    cell: Cell,
    region: TableRegion,
) -> bool:
    source_texts = _cell_source_texts(cell)
    if any(contains_date_cue(source_text) for source_text in source_texts) or (
        _has_fragmented_date_cue(cell)
    ):
        return False
    if any(
        contains_token_sequence(
            source_text,
            _CONVERSION_RATE_CUES,
            allow_hebrew_clitic_prefix=True,
        )
        for source_text in source_texts
    ):
        return True
    header_text = _column_header_text(column, region)
    return contains_token_sequence(
        header_text,
        _CONVERSION_RATE_CUES,
        allow_hebrew_clitic_prefix=True,
    ) and any(
        _RATE_DECIMAL_PATTERN.search(normalize_text(source_text)) is not None
        for source_text in source_texts
    )


def is_date_shaped(text: str) -> bool:
    """Return whether text is exactly one supported three-component date shape."""

    return _DATE_PATTERN.fullmatch(normalize_text(text)) is not None


def contains_date_cue(text: str) -> bool:
    """Return whether text contains the compact date cue used by semantic auditing."""

    normalized = normalize_text(text)
    return any(
        has_date_token_boundaries(normalized, match.start(), match.end())
        for match in _DATE_CUE_PATTERN.finditer(normalized)
    )


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def _parse_date(
    text: str,
    year_context: DiscoveredDateYearContext | None = None,
) -> tuple[date | None, str | None]:
    for index, char in enumerate(text):
        if char != "\u200b" or index == 0 or index == len(text) - 1:
            continue
        left = text[index - 1]
        right = text[index + 1]
        date_chars = "./-"
        if (left.isdigit() and (right.isdigit() or right in date_chars)) or (
            right.isdigit() and left in date_chars
        ):
            return None, "invalid_date"
    normalized = normalize_text(text)
    full_date_matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_token_boundaries(normalized, match.start(), match.end())
    )
    if len(full_date_matches) > 1:
        return None, "ambiguous_date_tokens"
    if len(full_date_matches) == 1:
        full_match = full_date_matches[0]
        full_residual = normalize_text(
            normalized[: full_match.start()] + normalized[full_match.end() :]
        )
        if full_residual and not _has_safe_date_parse_residual(full_residual):
            return None, "invalid_date"
    isolated_token = isolated_date_token(normalized)
    if isolated_token is not None:
        isolated_start = normalized.find(isolated_token)
        if not has_date_token_boundaries(
            normalized,
            isolated_start,
            isolated_start + len(isolated_token),
        ):
            isolated_token = None
    if isolated_token is not None:
        normalized = isolated_token
    elif len(full_date_matches) == 1:
        boundary_match = full_date_matches[0]
        residual = normalized[: boundary_match.start()] + normalized[boundary_match.end() :]
        residual_chars = tuple(char for char in residual if not char.isspace())
        if (
            (boundary_match.start() == 0 or boundary_match.end() == len(normalized))
            and residual_chars
            and any(char.isalpha() for char in residual_chars)
            and all(
                char.isalpha() or unicodedata.category(char)[0] in {"M", "P"}
                for char in residual_chars
            )
        ):
            normalized = boundary_match.group(0)
    if year_context is not None:
        short_matches = tuple(
            match
            for match in SHORT_DATE_TOKEN_PATTERNS[year_context.style].finditer(normalized)
            if has_date_token_boundaries(normalized, match.start(), match.end())
        )
        if len(short_matches) == 1:
            short_match = short_matches[0]
            residual = normalize_text(
                normalized[: short_match.start()] + normalized[short_match.end() :]
            )
            if residual and not _has_safe_indivisible_date_context(residual):
                return None, "invalid_date"
            suffix = int(short_match.group("year"))
            year_mapping = dict(year_context.year_by_suffix)
            if not year_mapping and year_context.year is not None:
                year_mapping[year_context.year % 100] = year_context.year
            resolved_year = year_mapping.get(suffix)
            if resolved_year is None:
                return None, "date_year_context_mismatch"
            try:
                return date(
                    resolved_year,
                    int(short_match.group("month")),
                    int(short_match.group("day")),
                ), None
            except ValueError:
                return None, "invalid_date"
        if len(short_matches) > 1:
            return None, "ambiguous_date_tokens"
    match = _DATE_PATTERN.fullmatch(normalized)
    if match is None:
        if is_installment_shaped(normalized):
            return None, "ambiguous_date_or_installment"
        return None, "invalid_date"
    first, _, second, third = match.groups()
    if len(first) == 4:
        year, month, day = int(first), int(second), int(third)
    elif len(third) == 4:
        day, month, year = int(first), int(second), int(third)
    else:
        return None, "invalid_date"
    try:
        return date(year, month, day), None
    except ValueError:
        return None, "invalid_date"


def _parse_ocr_contaminated_date_text(
    text: str,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if year_context is None:
        return None, "invalid_date"
    normalized = normalize_text(text)
    matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_token_boundaries(normalized, match.start(), match.end())
    )
    if len(matches) != 1:
        return None, "invalid_date"
    match = _DATE_PATTERN.fullmatch(matches[0].group(0))
    if match is None:
        return None, "invalid_date"
    first, separator, second, third = match.groups()
    candidates: list[str] = []
    if year_context.style in {
        DateTokenStyle.DAY_FIRST_SLASH,
        DateTokenStyle.DAY_FIRST_DOT,
        DateTokenStyle.DAY_FIRST_DASH,
    }:
        if len(first) == 4:
            candidates.append(f"{first[-2:]}{separator}{second}{separator}{third}")
        if len(third) == 4:
            candidates.append(f"{first}{separator}{second}{separator}{third[:2]}")
    repaired = {
        parsed_date
        for candidate in candidates
        if (parsed_date := _parse_date(candidate, year_context)[0]) is not None
    }
    return (next(iter(repaired)), None) if len(repaired) == 1 else (None, "invalid_date")


def _parse_ocr_contaminated_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if not cell_has_ocr_evidence(cell):
        return None, "invalid_date"
    return _parse_ocr_contaminated_date_text(cell.text, year_context)


def _parse_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    parsed = _parse_date(cell.text, year_context)
    parsed_year_out_of_range = (
        parsed[0] is not None
        and cell_has_ocr_evidence(cell)
        and not MIN_CONTEXT_YEAR <= parsed[0].year <= MAX_CONTEXT_YEAR
    )
    if parsed_year_out_of_range or parsed[1] == "invalid_date":
        repaired = _parse_ocr_contaminated_cell_date(cell, year_context)
        if repaired[0] is not None:
            return repaired
    if parsed_year_out_of_range:
        return None, "invalid_date"
    if parsed[1] != "invalid_date":
        return parsed
    return parsed


def _short_date_tokens(cell: Cell) -> tuple[str, ...]:
    tokens: list[str] = []
    for text in (cell.text, *(word.text for word in cell.words)):
        normalized = normalize_text(text)
        tokens.extend(
            match.group(0)
            for match in _DATE_TOKEN_PATTERN.finditer(normalized)
            if has_date_token_boundaries(normalized, match.start(), match.end())
        )
    return tuple(dict.fromkeys(tokens))


def _valid_short_date_token_for_style(
    token: str,
    style: DateTokenStyle,
) -> re.Match[str] | None:
    match = SHORT_DATE_TOKEN_PATTERNS[style].fullmatch(normalize_text(token))
    if match is None:
        return None
    try:
        date(2000, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None
    return match


def proven_unanchored_short_date_style(
    region: TableRegion,
    column: ColumnSpec,
) -> DateTokenStyle | None:
    eligible_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    amount_column = proven_billed_amount_column(region.table_schema, eligible_rows)
    if amount_column is None:
        return None
    transaction_rows = tuple(
        row
        for row in region.rows
        if len(_cells_for_column(row, amount_column)) == 1
        and is_money_shaped(_cells_for_column(row, amount_column)[0].text)
    )
    if len(transaction_rows) < 2:
        return None
    tokens_by_row: list[str] = []
    for row in transaction_rows:
        tokens = tuple(
            dict.fromkeys(
                token
                for cell in row.cells
                if horizontal_overlap(cell.bbox, column.bbox) > 0
                for token in _short_date_tokens(cell)
            )
        )
        if len(tokens) != 1:
            return None
        tokens_by_row.append(tokens[0])
    candidates: list[DateTokenStyle] = []
    for style in DateTokenStyle:
        matches = tuple(_valid_short_date_token_for_style(token, style) for token in tokens_by_row)
        if any(match is None for match in matches):
            continue
        suffixes = {int(match.group("year")) for match in matches if match is not None}
        if len(suffixes) == 1:
            candidates.append(style)
    return candidates[0] if len(candidates) == 1 else None


def has_proven_unanchored_short_date(
    cell: Cell,
    style: DateTokenStyle | None,
) -> bool:
    if style is None:
        return False
    tokens = _short_date_tokens(cell)
    return len(tokens) == 1 and _valid_short_date_token_for_style(tokens[0], style) is not None


def _parse_overlapping_boundary_date(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    column_width = column.bbox[2] - column.bbox[0]
    if column_width <= 0:
        return None, "invalid_date"
    column_center = _center_x(column.bbox)
    candidates: dict[date, tuple[date, None]] = {}
    for cell in row.cells:
        if cell is assigned_cell:
            continue
        overlap = horizontal_overlap(cell.bbox, column.bbox)
        if overlap / column_width < 0.8:
            continue
        cell_center = _center_x(cell.bbox)
        if column.bbox[0] <= cell_center <= column.bbox[2]:
            continue
        clipped_glyphs = tuple(
            glyph
            for glyph in cell.glyphs
            if column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        if clipped_glyphs:
            clipped_date, clipped_diagnostic = _parse_date(
                logical_text_for_evidence(clipped_glyphs, ()),
                year_context,
            )
            if clipped_date is not None and clipped_diagnostic is None:
                candidates[clipped_date] = (clipped_date, None)
        normalized = normalize_text(cell.text)
        matches = tuple(
            match
            for match in _DATE_TOKEN_PATTERN.finditer(normalized)
            if has_date_numeric_run_boundaries(normalized, match.start(), match.end())
        )
        if len(matches) != 1:
            continue
        match = matches[0]
        if cell_center < column_center and match.end() != len(normalized):
            continue
        if cell_center > column_center and match.start() != 0:
            continue
        parsed_date, diagnostic = _parse_date(match.group(0), year_context)
        if parsed_date is not None and diagnostic is None:
            candidates[parsed_date] = (parsed_date, None)
    return next(iter(candidates.values())) if len(candidates) == 1 else (None, "invalid_date")


def _glyph_identity(glyph: Glyph) -> tuple[object, ...]:
    return (
        glyph.char,
        glyph.bbox,
        glyph.origin,
        glyph.font,
        glyph.size,
        glyph.source,
        glyph.confidence,
    )


type BoundaryDateCompletion = tuple[date, Cell, Glyph]


def adjacent_boundary_date_completion(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> BoundaryDateCompletion | None:
    base_glyphs = tuple(glyph for glyph in assigned_cell.glyphs if not glyph.char.isspace())
    if not base_glyphs:
        return None
    base_text = logical_text_for_evidence(base_glyphs, ())
    if (
        normalize_text(base_text) != normalize_text(assigned_cell.text)
        or _parse_date(base_text, year_context)[0] is not None
    ):
        return None
    sources = {glyph.source for glyph in base_glyphs}
    if len(sources) != 1:
        return None
    typical_width = statistics.median(
        max(0.0, glyph.bbox[2] - glyph.bbox[0]) for glyph in base_glyphs
    )
    if typical_width <= 0:
        return None
    base_left = min(glyph.bbox[0] for glyph in base_glyphs)
    base_right = max(glyph.bbox[2] for glyph in base_glyphs)
    candidates: list[BoundaryDateCompletion] = []
    for cell in row.cells:
        if cell is assigned_cell or column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]:
            continue
        clipped = tuple(
            glyph
            for glyph in cell.glyphs
            if not glyph.char.isspace()
            and column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        if len(clipped) != 1:
            continue
        glyph = clipped[0]
        if not glyph.char.isdigit() or glyph.source not in sources:
            continue
        if vertical_overlap(assigned_cell.bbox, glyph.bbox) < 0.8:
            continue
        adjacency_tolerance = typical_width * 0.35
        if glyph.bbox[0] >= base_right - adjacency_tolerance:
            gap = max(0.0, glyph.bbox[0] - base_right)
        elif glyph.bbox[2] <= base_left + adjacency_tolerance:
            gap = max(0.0, base_left - glyph.bbox[2])
        else:
            continue
        if gap > adjacency_tolerance:
            continue
        candidate_text = logical_text_for_evidence((*base_glyphs, glyph), ())
        parsed_date, diagnostic = _parse_date(candidate_text, year_context)
        if parsed_date is not None and diagnostic is None:
            candidates.append((parsed_date, cell, glyph))
    return candidates[0] if len(candidates) == 1 else None


def _outside_glyphs_have_lossless_word_backing(
    outside: Sequence[Glyph],
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
) -> bool:
    words = tuple(
        word
        for cell in row.cells
        if cell is not assigned_cell
        and not column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        for word in cell.words
    )
    assigned: list[list[Glyph]] = [[] for _ in words]
    for glyph in outside:
        owners = tuple(
            index for index, word in enumerate(words) if _bbox_center_inside(glyph.bbox, word.bbox)
        )
        if len(owners) != 1:
            return False
        assigned[owners[0]].append(glyph)
    return bool(words) and all(
        not glyphs
        or normalize_text(word.text).casefold()
        == normalize_text(logical_text_for_evidence(tuple(glyphs), (word,))).casefold()
        for word, glyphs in zip(words, assigned, strict=True)
    )


def _parse_date_without_duplicated_boundary_glyphs(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if not assigned_cell.glyphs:
        return None, "invalid_date"
    outside = tuple(
        glyph
        for glyph in assigned_cell.glyphs
        if not column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
    )
    if not outside:
        return None, "invalid_date"
    outside_sides = {
        "left" if _center_x(glyph.bbox) < column.bbox[0] else "right" for glyph in outside
    }
    if len(outside_sides) != 1:
        return None, "invalid_date"
    duplicated_evidence = {
        _glyph_identity(glyph)
        for cell in row.cells
        if cell is not assigned_cell
        and not column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        for glyph in cell.glyphs
    }
    has_exact_duplicate_glyphs = bool(duplicated_evidence) and all(
        _glyph_identity(glyph) in duplicated_evidence for glyph in outside
    )
    if not has_exact_duplicate_glyphs and not _outside_glyphs_have_lossless_word_backing(
        outside,
        row,
        column,
        assigned_cell,
    ):
        return None, "invalid_date"
    if _character_signature(assigned_cell.text) != _character_signature(
        logical_text_for_evidence(assigned_cell.glyphs, ())
    ):
        return None, "invalid_date"
    remaining = tuple(glyph for glyph in assigned_cell.glyphs if glyph not in outside)
    if not remaining:
        return None, "invalid_date"
    remaining_text = logical_text_for_evidence(remaining, ())
    if _ordered_compact_text(remaining_text) not in _ordered_compact_text(assigned_cell.text):
        return None, "invalid_date"
    logical_residual = _remove_ordered_compact_fragment(assigned_cell.text, remaining_text)
    if logical_residual is None or _material_numeric_sequence(
        logical_residual
    ) != _material_numeric_sequence(logical_text_for_evidence(outside, ())):
        return None, "invalid_date"
    parsed_date, diagnostic = _parse_date(remaining_text, year_context)
    return (
        (parsed_date, None)
        if parsed_date is not None and diagnostic is None
        else (None, "invalid_date")
    )


def _glyph_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    glyphs: Iterable[Glyph],
) -> frozenset[int]:
    identities = {_glyph_identity(glyph) for glyph in glyphs}
    return frozenset(
        atom_id
        for atom_id in ledger.atoms_for_cell(cell)
        if (glyph := ledger.atoms[atom_id].glyph) is not None
        and _glyph_identity(glyph) in identities
    )


def _overlapping_boundary_date_atom_ids(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    expected: date,
) -> frozenset[int]:
    column_width = column.bbox[2] - column.bbox[0]
    if column_width <= 0:
        return frozenset()
    column_center = _center_x(column.bbox)
    recovered: set[int] = set()
    for cell in row.cells:
        if cell is assigned_cell:
            continue
        overlap = horizontal_overlap(cell.bbox, column.bbox)
        if overlap / column_width < 0.8:
            continue
        cell_center = _center_x(cell.bbox)
        if column.bbox[0] <= cell_center <= column.bbox[2]:
            continue
        clipped_glyphs = tuple(
            glyph
            for glyph in cell.glyphs
            if column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        if (
            clipped_glyphs
            and _parse_date(
                logical_text_for_evidence(clipped_glyphs, ()),
                year_context,
            )[0]
            == expected
        ):
            recovered.update(_glyph_atom_ids(ledger, cell, clipped_glyphs))
        normalized = normalize_text(cell.text)
        matches = tuple(
            match
            for match in _DATE_TOKEN_PATTERN.finditer(normalized)
            if has_date_numeric_run_boundaries(normalized, match.start(), match.end())
        )
        if len(matches) != 1:
            continue
        match = matches[0]
        if cell_center < column_center and match.end() != len(normalized):
            continue
        if cell_center > column_center and match.start() != 0:
            continue
        matching_ids = matching_date_atom_ids(ledger, cell, expected, year_context)
        recovered.update(matching_ids)
    return frozenset(recovered)


def _parse_text_only_full_year_boundary_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> date | None:
    if cell.glyphs or cell.words:
        return None
    normalized = normalize_text(cell.text)
    boundary_matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_numeric_run_boundaries(normalized, match.start(), match.end())
        and (match.start() == 0 or match.end() == len(normalized))
        if (shape := _DATE_PATTERN.fullmatch(match.group(0))) is not None
        and (len(shape.group(1)) == 4 or len(shape.group(4)) == 4)
    )
    if len(boundary_matches) != 1:
        return None
    boundary_match = boundary_matches[0]
    residual = normalize_text(
        normalized[: boundary_match.start()] + normalized[boundary_match.end() :]
    )
    if residual and not _has_safe_date_parse_residual(residual):
        return None
    parsed_date, diagnostic = _parse_date(boundary_match.group(0), year_context)
    return parsed_date if diagnostic is None else None


def _bounded_logical_date_match(cell: Cell, candidate_text: str) -> re.Match[str] | None:
    candidate_compact = "".join(normalize_text(candidate_text).split())
    normalized = normalize_text(cell.text)
    matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_token_boundaries(normalized, match.start(), match.end())
    )
    if len(matches) != 1 or "".join(matches[0].group(0).split()) != candidate_compact:
        return None
    return matches[0]


def _bounded_logical_date_residual(cell: Cell) -> str | None:
    normalized = normalize_text(cell.text)
    matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_token_boundaries(normalized, match.start(), match.end())
    )
    if len(matches) != 1:
        return None
    match = matches[0]
    residual = _ordered_compact_text(normalized[: match.start()] + normalized[match.end() :])
    return residual or None


_BIDI_FORMAT_CONTROL_CLASSES = frozenset(
    {
        "AL",
        "FSI",
        "L",
        "LRE",
        "LRI",
        "LRO",
        "PDF",
        "PDI",
        "R",
        "RLE",
        "RLI",
        "RLO",
    }
)


def _compact_source_text(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFC", text) if not char.isspace())


def _has_invisible_source_characters(text: str) -> bool:
    return any(unicodedata.category(char) == "Cf" for char in text)


def _approved_bidi_format_signature(text: str) -> tuple[str, ...] | None:
    signature: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        if unicodedata.category(char) != "Cf":
            continue
        if unicodedata.bidirectional(char) not in _BIDI_FORMAT_CONTROL_CLASSES:
            return None
        signature.append(char)
    return tuple(signature)


def _is_nonmaterial_layout_marker_text(text: str) -> bool:
    if _approved_bidi_format_signature(text) is None:
        return False
    visible_run = "".join(
        char for char in _compact_source_text(text) if unicodedata.category(char) != "Cf"
    )
    return is_visible_vertical_layout_marker(visible_run)


def _same_line_x_order_atoms(
    ledger: EvidenceLedger,
    atom_ids: Iterable[int],
) -> tuple[EvidenceAtom, ...]:
    selected = frozenset(atom_ids)
    return tuple(
        sorted(
            (atom for atom in ledger.atoms if atom.atom_id in selected),
            key=lambda atom: (
                atom.page_number,
                atom.bbox[0],
                atom.bbox[2],
                bbox_center_y(atom.bbox),
                atom.atom_id,
            ),
        )
    )


def _raw_atom_text(atom: EvidenceAtom) -> str:
    if atom.glyph is not None:
        return atom.glyph.char
    if atom.word is not None:
        return atom.word.text
    return atom.text


def _same_line_x_order_atom_text(
    ledger: EvidenceLedger,
    atom_ids: Iterable[int],
    *,
    raw: bool = False,
) -> str:
    atoms = _same_line_x_order_atoms(ledger, atom_ids)
    return "".join(_raw_atom_text(atom) if raw else atom.text for atom in atoms)


def _remove_exact_compact_fragment(text: str, fragment: str) -> str | None:
    compact_text = _compact_source_text(text)
    compact_fragment = _compact_source_text(fragment)
    if not compact_fragment or compact_text.count(compact_fragment) != 1:
        return None
    start = compact_text.index(compact_fragment)
    return compact_text[:start] + compact_text[start + len(compact_fragment) :]


def _atom_evidence_source(atom: EvidenceAtom) -> str | None:
    glyph = atom.glyph
    if glyph is not None:
        return glyph.source
    word = atom.word
    return word.source if word is not None else None


def _invalid_boundary_digit_supercandidate_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> frozenset[int]:
    """Return one ordinary edge digit that only enlarges an exact date Word."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
    if not candidate_atoms or any(atom.glyph is None for atom in candidate_atoms):
        return frozenset()
    candidate_glyphs = tuple(atom.glyph for atom in candidate_atoms if atom.glyph is not None)
    candidate_digit_atoms = tuple(
        sorted(
            (atom for atom in candidate_atoms if atom.text.isdigit()),
            key=lambda atom: _center_x(atom.bbox),
        )
    )
    if not candidate_digit_atoms:
        return frozenset()
    candidate_bbox = union_bbox(tuple(atom.bbox for atom in candidate_atoms))
    qualifying: set[frozenset[int]] = set()
    for source_text, source_atom_ids in _positioned_date_sources(ledger, cell):
        if not candidate_atom_ids < source_atom_ids:
            continue
        if _DATE_PATTERN.fullmatch(normalize_text(source_text)) is None or _ordered_compact_text(
            _ordered_atom_text(ledger, source_atom_ids)
        ) != _ordered_compact_text(source_text):
            continue
        for extra_atom_id in source_atom_ids - candidate_atom_ids:
            extra_ids = frozenset((extra_atom_id,))
            extra_atom = ledger.atoms[extra_atom_id]
            extra_glyph = extra_atom.glyph
            if (
                extra_glyph is None
                or len(extra_atom.text) != 1
                or not extra_atom.text.isdigit()
                or extra_glyph.source != "digital"
            ):
                continue
            if extra_atom.bbox[2] <= candidate_bbox[0]:
                edge_atom = candidate_digit_atoms[0]
                gap = candidate_bbox[0] - extra_atom.bbox[2]
            elif candidate_bbox[2] <= extra_atom.bbox[0]:
                edge_atom = candidate_digit_atoms[-1]
                gap = extra_atom.bbox[0] - candidate_bbox[2]
            else:
                continue
            edge_glyph = edge_atom.glyph
            height = min(_height(candidate_bbox), _height(extra_atom.bbox))
            edge_width = _width(edge_atom.bbox)
            if (
                edge_glyph is None
                or extra_atom.text != edge_atom.text
                or extra_glyph.font != edge_glyph.font
                or extra_glyph.size != edge_glyph.size
                or height <= 0
                or not height * 0.1 < gap <= height * 0.25
                or vertical_overlap(candidate_bbox, extra_atom.bbox) < 0.95
                or edge_width <= 0
                or not edge_width * 0.8 <= _width(extra_atom.bbox) <= edge_width * 1.2
                or any(glyph.source != "digital" for glyph in candidate_glyphs)
            ):
                continue
            exact_extra_words = tuple(
                word
                for word in cell.words
                if word.source == "digital"
                and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == extra_ids
                and _ordered_compact_text(word.text) == _ordered_compact_text(extra_atom.text)
            )
            if len(exact_extra_words) == 1:
                qualifying.add(extra_ids)
    return next(iter(qualifying)) if len(qualifying) == 1 else frozenset()


def _custom_font_digit_layout_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> frozenset[int]:
    """Return one wide custom-font digit that is positioned as a date-side icon."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    residual_ids = cell_atom_ids - candidate_atom_ids
    boundary_digit_ids = _invalid_boundary_digit_supercandidate_atom_ids(
        ledger,
        cell,
        candidate_atom_ids,
    )
    marker_ids = residual_ids - boundary_digit_ids
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
    marker_atoms = tuple(ledger.atoms[atom_id] for atom_id in marker_ids)
    if (
        not candidate_atoms
        or len(marker_atoms) != 1
        or any(atom.glyph is None for atom in candidate_atoms)
        or marker_atoms[0].glyph is None
    ):
        return frozenset()
    candidate_glyphs = tuple(atom.glyph for atom in candidate_atoms if atom.glyph is not None)
    residual_glyph = marker_atoms[0].glyph
    residual_text = residual_glyph.char
    positioned_sources = _positioned_date_sources(ledger, cell)
    matching_sources = tuple(
        text for text, atom_ids in positioned_sources if atom_ids == candidate_atom_ids
    )
    if (
        len(matching_sources) != 1
        or _DATE_PATTERN.fullmatch(normalize_text(matching_sources[0])) is None
        or len(residual_text) != 1
        or not residual_text.isdigit()
        or residual_glyph.source != "digital"
        or any(glyph.source != "digital" for glyph in candidate_glyphs)
        or residual_glyph.font in {glyph.font for glyph in candidate_glyphs}
    ):
        return frozenset()
    candidate_digit_widths = tuple(
        _width(glyph.bbox) for glyph in candidate_glyphs if glyph.char.isdigit()
    )
    if (
        not candidate_digit_widths
        or min(candidate_digit_widths) <= 0
        or _width(residual_glyph.bbox) < statistics.median(candidate_digit_widths) * 1.2
    ):
        return frozenset()
    exact_date_words = tuple(
        word
        for word in cell.words
        if word.source == "digital"
        and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == candidate_atom_ids
        and _ordered_compact_text(word.text)
        == _ordered_compact_text(_ordered_atom_text(ledger, candidate_atom_ids))
    )
    exact_residual_words = tuple(
        word
        for word in cell.words
        if word.source == "digital"
        and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == marker_ids
        and _ordered_compact_text(word.text) == residual_text
    )
    if len(exact_date_words) != 1 or len(exact_residual_words) != 1:
        return frozenset()
    candidate_bbox = union_bbox(tuple(atom.bbox for atom in candidate_atoms))
    residual_bbox = marker_atoms[0].bbox
    horizontal_gap = max(
        candidate_bbox[0] - residual_bbox[2],
        residual_bbox[0] - candidate_bbox[2],
        0.0,
    )
    height = min(_height(candidate_bbox), _height(residual_bbox))
    logical_residual = _remove_ordered_compact_fragment(cell.text, matching_sources[0])
    physical_text = _ordered_atom_text(ledger, cell_atom_ids)
    positioned_residual = _ordered_atom_text(ledger, residual_ids)
    boundary_is_opposite = True
    if boundary_digit_ids:
        boundary_bbox = union_bbox(
            tuple(ledger.atoms[atom_id].bbox for atom_id in boundary_digit_ids)
        )
        boundary_is_left = boundary_bbox[2] <= candidate_bbox[0]
        marker_is_left = residual_bbox[2] <= candidate_bbox[0]
        boundary_is_right = candidate_bbox[2] <= boundary_bbox[0]
        marker_is_right = candidate_bbox[2] <= residual_bbox[0]
        boundary_is_opposite = (boundary_is_left and marker_is_right) or (
            boundary_is_right and marker_is_left
        )
    if (
        height <= 0
        or not height * 0.1 < horizontal_gap <= height * 0.25
        or vertical_overlap(candidate_bbox, residual_bbox) < 0.95
        or not boundary_is_opposite
        or logical_residual != _ordered_compact_text(positioned_residual)
        or _character_signature(cell.text) != _character_signature(physical_text)
    ):
        return frozenset()
    return residual_ids


def nonmaterial_date_layout_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> frozenset[int]:
    """Return separately positioned, non-semantic marker atoms beside one date Word."""

    custom_font_digit_ids = _custom_font_digit_layout_atom_ids(
        ledger,
        cell,
        candidate_atom_ids,
    )
    if custom_font_digit_ids:
        return custom_font_digit_ids

    cell_atom_ids = ledger.atoms_for_cell(cell)
    positioned_date_sources = _positioned_date_sources(ledger, cell)
    if len(positioned_date_sources) != 1:
        return frozenset()
    positioned_date_text, positioned_date_atom_ids = positioned_date_sources[0]
    if positioned_date_atom_ids != candidate_atom_ids:
        return frozenset()
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
    residual_ids = cell_atom_ids - candidate_atom_ids
    residual_atoms = tuple(ledger.atoms[atom_id] for atom_id in residual_ids)
    positioned_residual_text = _same_line_x_order_atom_text(
        ledger,
        residual_ids,
        raw=True,
    )
    positioned_date_component = _same_line_x_order_atom_text(
        ledger,
        candidate_atom_ids,
        raw=True,
    )
    logical_date_residual = _remove_exact_compact_fragment(cell.text, positioned_date_text)
    logical_bidi_signature = (
        _approved_bidi_format_signature(logical_date_residual)
        if logical_date_residual is not None
        else None
    )
    positioned_bidi_signature = _approved_bidi_format_signature(positioned_residual_text)
    exact_word_date = (
        len(candidate_atoms) == 1
        and candidate_atoms[0].word is not None
        and _compact_source_text(positioned_date_component)
        == _compact_source_text(positioned_date_text)
    )
    exact_glyph_date = (
        bool(candidate_atoms)
        and all(atom.glyph is not None for atom in candidate_atoms)
        and _compact_source_text(positioned_date_component)
        == _compact_source_text(positioned_date_text)
    )
    evidence_sources = {_atom_evidence_source(atom) for atom in (*candidate_atoms, *residual_atoms)}
    if (
        not (exact_word_date or exact_glyph_date)
        or _DATE_PATTERN.fullmatch(normalize_text(positioned_date_text)) is None
        or _bounded_logical_date_match(cell, positioned_date_text) is None
        or not residual_atoms
        or not (
            all(atom.word is not None for atom in residual_atoms)
            or all(atom.glyph is not None for atom in residual_atoms)
        )
        or not _is_nonmaterial_layout_marker_text(positioned_residual_text)
        or logical_date_residual != _compact_source_text(positioned_residual_text)
        or logical_bidi_signature is None
        or positioned_bidi_signature is None
        or logical_bidi_signature != positioned_bidi_signature
        or any(_has_invisible_source_characters(_raw_atom_text(atom)) for atom in candidate_atoms)
        or len(evidence_sources) != 1
        or None in evidence_sources
    ):
        return frozenset()
    candidate_bbox = union_bbox(tuple(atom.bbox for atom in candidate_atoms))
    residual_bbox = union_bbox(tuple(atom.bbox for atom in residual_atoms))
    horizontal_gap = max(
        candidate_bbox[0] - residual_bbox[2],
        residual_bbox[0] - candidate_bbox[2],
        0.0,
    )
    date_confidence = min(atom.confidence for atom in candidate_atoms)
    if (
        horizontal_gap <= min(_height(candidate_bbox), _height(residual_bbox)) * 0.1
        or any(
            not _bbox_center_inside(atom.bbox, cell.bbox)
            for atom in (*candidate_atoms, *residual_atoms)
        )
        or any(
            vertical_overlap(candidate_bbox, atom.bbox) < 0.8 or atom.confidence >= date_confidence
            for atom in residual_atoms
        )
    ):
        return frozenset()
    return residual_ids


def _description_boundary_punctuation_atom_ids(
    row: Row,
    region: TableRegion,
    column: ColumnSpec,
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> frozenset[int]:
    """Return one punctuation glyph that geometrically belongs to a peer description band."""

    positioned_sources = _positioned_date_sources(ledger, cell)
    matching_sources = tuple(
        text for text, atom_ids in positioned_sources if atom_ids == candidate_atom_ids
    )
    cell_atom_ids = ledger.atoms_for_cell(cell)
    residual_ids = cell_atom_ids - candidate_atom_ids
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
    residual_atoms = tuple(ledger.atoms[atom_id] for atom_id in residual_ids)
    if (
        column.role is not ColumnRole.DATE
        or len(matching_sources) != 1
        or not candidate_atoms
        or len(residual_atoms) != 1
        or any(atom.glyph is None for atom in (*candidate_atoms, *residual_atoms))
    ):
        return frozenset()
    candidate_text = matching_sources[0]
    residual_atom = residual_atoms[0]
    residual_glyph = residual_atom.glyph
    if residual_glyph is None:
        return frozenset()
    residual_text = residual_glyph.char
    if (
        _DATE_PATTERN.fullmatch(normalize_text(candidate_text)) is None
        or _bounded_logical_date_match(cell, candidate_text) is None
        or len(residual_text) != 1
        or unicodedata.category(residual_text)[0] != "P"
        or {_atom_evidence_source(atom) for atom in (*candidate_atoms, residual_atom)}
        != {"digital"}
        or any(not _bbox_center_inside(atom.bbox, column.bbox) for atom in candidate_atoms)
        or _bbox_center_inside(residual_atom.bbox, column.bbox)
    ):
        return frozenset()
    columns_by_x = tuple(sorted(region.table_schema.columns, key=lambda item: item.bbox[0]))
    try:
        column_index = columns_by_x.index(column)
    except ValueError:
        return frozenset()
    peer_columns = tuple(
        peer
        for peer_index, peer in enumerate(columns_by_x)
        if abs(peer_index - column_index) == 1
        and peer.role is ColumnRole.DESCRIPTION
        and _bbox_center_inside(residual_atom.bbox, peer.bbox)
    )
    if len(peer_columns) != 1:
        return frozenset()
    candidate_bbox = union_bbox(tuple(atom.bbox for atom in candidate_atoms))
    horizontal_gap = max(
        candidate_bbox[0] - residual_atom.bbox[2],
        residual_atom.bbox[0] - candidate_bbox[2],
        0.0,
    )
    logical_residual = _remove_ordered_compact_fragment(cell.text, candidate_text)
    physical_text = _ordered_atom_text(ledger, cell_atom_ids)
    if (
        horizontal_gap <= min(_height(candidate_bbox), _height(residual_atom.bbox))
        or vertical_overlap(candidate_bbox, residual_atom.bbox) < 0.8
        or logical_residual != _ordered_compact_text(residual_text)
        or _character_signature(cell.text) != _character_signature(physical_text)
        or cell not in row.cells
    ):
        return frozenset()
    return residual_ids


def _ocr_marker_band_layout_atom_ids(
    region: TableRegion,
    column: ColumnSpec,
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> frozenset[int]:
    partition = proven_ocr_marker_word_partition(region, column, cell)
    if partition is None:
        return frozenset()
    date_word, marker_words = partition
    cell_atom_ids = ledger.atoms_for_cell(cell)
    date_ids = frozenset(
        atom_id for atom_id in cell_atom_ids if ledger.atoms[atom_id].word == date_word
    )
    marker_ids = frozenset(
        atom_id for atom_id in cell_atom_ids if ledger.atoms[atom_id].word in marker_words
    )
    if (
        date_ids != candidate_atom_ids
        or not marker_ids
        or marker_ids != cell_atom_ids - candidate_atom_ids
    ):
        return frozenset()
    return marker_ids


def _has_positioned_date_with_structural_residual(
    row: Row,
    region: TableRegion,
    column: ColumnSpec,
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> bool:
    if column.role is not ColumnRole.DATE:
        return False
    layout_ids = nonmaterial_date_layout_atom_ids(ledger, cell, candidate_atom_ids)
    if layout_ids:
        return all(
            _bbox_center_inside(ledger.atoms[atom_id].bbox, column.bbox)
            for atom_id in candidate_atom_ids | layout_ids
        )
    marker_band_ids = _ocr_marker_band_layout_atom_ids(
        region,
        column,
        ledger,
        cell,
        candidate_atom_ids,
    )
    if marker_band_ids:
        return all(
            _bbox_center_inside(ledger.atoms[atom_id].bbox, column.bbox)
            for atom_id in candidate_atom_ids | marker_band_ids
        )
    return bool(
        _description_boundary_punctuation_atom_ids(
            row,
            region,
            column,
            ledger,
            cell,
            candidate_atom_ids,
        )
    )


def _has_separate_positioned_conversion_rate_residual(
    ledger: EvidenceLedger,
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
    candidate_text: str,
    candidate_atom_ids: frozenset[int],
) -> bool:
    """Prove one conversion date and one independent exchange-rate decimal."""

    if column.role is not ColumnRole.CONVERSION_DATE or not contains_token_sequence(
        _column_header_text(column, region),
        _CONVERSION_RATE_CUES,
        allow_hebrew_clitic_prefix=True,
    ):
        return False
    cell_atom_ids = ledger.atoms_for_cell(cell)
    residual_ids = cell_atom_ids - candidate_atom_ids
    decimals = ledger.positioned_decimal_candidates(residual_ids)
    if (
        not candidate_atom_ids
        or len(decimals) != 1
        or decimals[0].atom_ids != residual_ids
        or currencies_in_text(cell.text)
        or "%" in cell.text
        or any(unicodedata.category(char) == "Sc" for char in cell.text)
        or _bounded_logical_date_match(cell, candidate_text) is None
        or _remove_ordered_compact_fragment(cell.text, candidate_text)
        != _ordered_compact_text(decimals[0].text)
        or _ordered_compact_text(_ordered_atom_text(ledger, residual_ids))
        != _ordered_compact_text(decimals[0].text)
        or not (
            _material_numeric_sequence(cell.text)
            == _material_numeric_sequence(_ordered_atom_text(ledger, cell_atom_ids))
            or (
                len(cell_atom_ids) == 2
                and all(ledger.atoms[atom_id].word is not None for atom_id in cell_atom_ids)
                and _character_signature(cell.text)
                == _character_signature(_ordered_atom_text(ledger, cell_atom_ids))
            )
        )
    ):
        return False
    date_bbox = union_bbox(tuple(ledger.atoms[atom_id].bbox for atom_id in candidate_atom_ids))
    rate_bbox = union_bbox(tuple(ledger.atoms[atom_id].bbox for atom_id in residual_ids))
    horizontal_gap = max(
        date_bbox[0] - rate_bbox[2],
        rate_bbox[0] - date_bbox[2],
        0.0,
    )
    return (
        horizontal_gap > min(_height(date_bbox), _height(rate_bbox)) * 0.1
        and vertical_overlap(date_bbox, rate_bbox) >= 0.8
        and all(
            _bbox_center_inside(ledger.atoms[atom_id].bbox, cell.bbox) for atom_id in cell_atom_ids
        )
        and any(
            all(
                _bbox_center_inside(ledger.atoms[atom_id].bbox, column.bbox)
                for atom_id in component_ids
            )
            for component_ids in (candidate_atom_ids, residual_ids)
        )
    )


def proven_conversion_rate_residual_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    column: ColumnSpec,
    region: TableRegion,
    accepted_date_atom_ids: frozenset[int],
) -> frozenset[int]:
    """Return the exact rate residual beside one already accepted conversion date."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    accepted_cell_ids = cell_atom_ids & accepted_date_atom_ids
    candidates = tuple(
        (candidate_text, candidate_atom_ids)
        for candidate_text, candidate_atom_ids in _positioned_date_sources(ledger, cell)
        if candidate_atom_ids == accepted_cell_ids
    )
    if len(candidates) != 1:
        return frozenset()
    candidate_text, candidate_atom_ids = candidates[0]
    if not _has_separate_positioned_conversion_rate_residual(
        ledger,
        cell,
        column,
        region,
        candidate_text,
        candidate_atom_ids,
    ):
        return frozenset()
    return cell_atom_ids - candidate_atom_ids


def _has_reordered_hebrew_positioned_representation(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> bool:
    candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
    residual_atoms = tuple(
        ledger.atoms[atom_id] for atom_id in ledger.atoms_for_cell(cell) - candidate_atom_ids
    )
    if (
        not candidate_atoms
        or not residual_atoms
        or any(atom.glyph is None for atom in (*candidate_atoms, *residual_atoms))
    ):
        return False
    logical_signature = tuple(
        sorted(char for char in normalize_text(cell.text) if not char.isspace())
    )
    physical_signature = tuple(
        sorted(char for glyph in cell.glyphs for char in glyph.char if not char.isspace())
    )
    residual_letters = tuple(
        char for atom in residual_atoms for char in atom.text if char.isalpha()
    )
    return (
        logical_signature == physical_signature
        and _ordered_compact_text(_ordered_atom_text(ledger, candidate_atom_ids))
        in _ordered_compact_text(cell.text)
        and bool(residual_letters)
        and all("\u0590" <= char <= "\u05ff" for char in residual_letters)
    )


def _character_signature(text: str) -> tuple[str, ...]:
    return tuple(sorted(char for char in normalize_text(text) if not char.isspace()))


def _digit_signature(text: str) -> tuple[str, ...]:
    return tuple(sorted(char for char in normalize_text(text) if char.isdigit()))


def _ordered_compact_text(text: str) -> str:
    return "".join(normalize_text(text).split())


def _ordered_atom_text(
    ledger: EvidenceLedger,
    atom_ids: Iterable[int],
) -> str:
    ordered_ids = sorted(
        atom_ids,
        key=lambda atom_id: (
            ledger.atoms[atom_id].page_number,
            bbox_center_y(ledger.atoms[atom_id].bbox),
            ledger.atoms[atom_id].bbox[0],
            ledger.atoms[atom_id].bbox[2],
            atom_id,
        ),
    )
    return "".join(ledger.atoms[atom_id].text for atom_id in ordered_ids)


def _material_numeric_sequence(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    currencies = currencies_in_text(normalized)
    has_numeric_material = (
        any(char.isdigit() for char in normalized)
        or bool(currencies)
        or "%" in normalized
        or any(unicodedata.category(char) == "Sc" for char in normalized)
    )
    if not has_numeric_material:
        return ()
    currency_markers = tuple(f"currency:{currency}" for currency in currencies)
    characters = tuple(
        char.casefold()
        for char in normalized
        if char.isdigit() or unicodedata.category(char)[0] in {"P", "S"}
    )
    return (*currency_markers, "\x00", *characters)


def _remove_ordered_compact_fragment(text: str, fragment: str) -> str | None:
    compact_text = _ordered_compact_text(text)
    compact_fragment = _ordered_compact_text(fragment)
    if not compact_fragment or compact_text.count(compact_fragment) != 1:
        return None
    start = compact_text.index(compact_fragment)
    return compact_text[:start] + compact_text[start + len(compact_fragment) :]


def _has_only_conversion_date_context(text: str) -> bool:
    normalized = normalize_text(text)
    compact = "".join(normalized.split())
    if not compact:
        return True
    if (
        any(char.isdigit() for char in normalized)
        or "%" in normalized
        or currencies_in_text(normalized)
        or any(unicodedata.category(char) == "Sc" for char in normalized)
        or is_installment_shaped(normalized)
        or is_money_shaped(normalized)
    ):
        return False
    tokens = phrase_tokens(normalized, ignore_acronym_quotes=True)
    return bool(tokens) and all(token in _INDIVISIBLE_DATE_CONTEXT_TOKENS for token in tokens)


def _has_compatible_bounded_date_representations(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_text: str,
    candidate_atom_ids: frozenset[int],
) -> bool:
    logical_match = _bounded_logical_date_match(cell, candidate_text)
    if logical_match is None:
        return False
    physical_text = _ordered_atom_text(ledger, ledger.atoms_for_cell(cell))
    normalized = normalize_text(cell.text)
    logical_residual = normalized[: logical_match.start()] + normalized[logical_match.end() :]
    physical_residual = _ordered_atom_text(
        ledger,
        ledger.atoms_for_cell(cell) - candidate_atom_ids,
    )
    if _character_signature(cell.text) == _character_signature(
        physical_text
    ) and _material_numeric_sequence(logical_residual) == _material_numeric_sequence(
        physical_residual
    ):
        return True
    return _has_only_conversion_date_context(
        logical_residual
    ) and _has_only_conversion_date_context(physical_residual)


def _has_lossless_full_positioned_date_representation(
    ledger: EvidenceLedger,
    cell: Cell,
    candidate_atom_ids: frozenset[int],
) -> bool:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    return candidate_atom_ids == cell_atom_ids and _ordered_compact_text(
        cell.text
    ) == _ordered_compact_text(_ordered_atom_text(ledger, cell_atom_ids))


def _has_lossless_overlapping_date_cell_representation(
    row: Row,
    column: ColumnSpec,
    assigned_cell: Cell,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    expected: date,
) -> bool:
    cell_atom_ids = ledger.atoms_for_cell(assigned_cell)
    assigned_text = _ordered_compact_text(assigned_cell.text)
    if (
        not cell_atom_ids
        or not assigned_text
        or assigned_text != _ordered_compact_text(_ordered_atom_text(ledger, cell_atom_ids))
    ):
        return False
    column_width = column.bbox[2] - column.bbox[0]
    if column_width <= 0:
        return False
    column_center = _center_x(column.bbox)
    candidate_texts: list[str] = []
    for cell in row.cells:
        if cell is assigned_cell or horizontal_overlap(cell.bbox, column.bbox) / column_width < 0.8:
            continue
        cell_center = _center_x(cell.bbox)
        if column.bbox[0] <= cell_center <= column.bbox[2]:
            continue
        clipped_glyphs = tuple(
            glyph
            for glyph in cell.glyphs
            if column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        clipped_text = logical_text_for_evidence(clipped_glyphs, ())
        if clipped_text and _parse_date(clipped_text, year_context)[0] == expected:
            candidate_texts.append(clipped_text)
        normalized = normalize_text(cell.text)
        for match in _DATE_TOKEN_PATTERN.finditer(normalized):
            if not has_date_numeric_run_boundaries(normalized, match.start(), match.end()):
                continue
            if cell_center < column_center and match.end() != len(normalized):
                continue
            if cell_center > column_center and match.start() != 0:
                continue
            if _parse_date(match.group(0), year_context)[0] == expected:
                candidate_texts.append(match.group(0))
    return any(
        _ordered_compact_text(candidate_text) == assigned_text for candidate_text in candidate_texts
    )


def _positioned_date_sources(
    ledger: EvidenceLedger,
    cell: Cell,
) -> tuple[tuple[str, frozenset[int]], ...]:
    sources = [
        (candidate.text, candidate.atom_ids)
        for candidate in ledger.fragmented_date_candidates(cell)
    ]
    cell_atom_ids = ledger.atoms_for_cell(cell)
    for word in cell.words:
        if _DATE_PATTERN.fullmatch(normalize_text(word.text)) is None:
            continue
        word_atom_ids = ledger.atoms_in_bbox(cell_atom_ids, word.bbox)
        if not word_atom_ids:
            continue
        atom_text = _ordered_atom_text(ledger, word_atom_ids)
        if _ordered_compact_text(atom_text) != _ordered_compact_text(word.text):
            continue
        sources.append((word.text, word_atom_ids))
    return tuple(
        {(normalize_text(text), atom_ids): (text, atom_ids) for text, atom_ids in sources}.values()
    )


def _without_invalid_digit_word_supercandidates(
    ledger: EvidenceLedger,
    cell: Cell,
    candidates: tuple[tuple[str, frozenset[int]], ...],
    year_context: DiscoveredDateYearContext | None,
) -> tuple[tuple[str, frozenset[int]], ...]:
    """Drop only invalid supersets caused by a separately backed digit Word."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    exact_word_sources = tuple(
        (candidate_text, candidate_atom_ids)
        for candidate_text, candidate_atom_ids in candidates
        if any(
            _DATE_PATTERN.fullmatch(normalize_text(word.text)) is not None
            and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == candidate_atom_ids
            and _ordered_compact_text(_ordered_atom_text(ledger, candidate_atom_ids))
            == _ordered_compact_text(word.text)
            for word in cell.words
        )
        and _parse_date(candidate_text, year_context)[0] is not None
    )

    def is_invalid_digit_supercandidate(
        candidate_text: str,
        candidate_atom_ids: frozenset[int],
    ) -> bool:
        if _parse_date(candidate_text, year_context)[0] is not None:
            return False
        for word_text, word_atom_ids in exact_word_sources:
            if not word_atom_ids < candidate_atom_ids:
                continue
            extra_atom_ids = candidate_atom_ids - word_atom_ids
            digit_word_ids = tuple(
                digit_atom_ids
                for word in cell.words
                if normalize_text(word.text).isdigit()
                if (digit_atom_ids := ledger.atoms_in_bbox(cell_atom_ids, word.bbox))
                if _ordered_compact_text(_ordered_atom_text(ledger, digit_atom_ids))
                == _ordered_compact_text(word.text)
            )
            represented_extra_ids = frozenset(
                atom_id
                for atom_ids in digit_word_ids
                if atom_ids and atom_ids <= extra_atom_ids
                for atom_id in atom_ids
            )
            if represented_extra_ids != extra_atom_ids:
                continue
            date_bbox = union_bbox(tuple(ledger.atoms[atom_id].bbox for atom_id in word_atom_ids))
            represented_components = tuple(
                atom_ids for atom_ids in digit_word_ids if atom_ids and atom_ids <= extra_atom_ids
            )
            if not represented_components or any(
                (
                    max(
                        date_bbox[0] - component_bbox[2],
                        component_bbox[0] - date_bbox[2],
                        0.0,
                    )
                    <= min(_height(date_bbox), _height(component_bbox)) * 0.1
                    or vertical_overlap(date_bbox, component_bbox) < 0.8
                )
                for component_ids in represented_components
                for component_bbox in (
                    union_bbox(tuple(ledger.atoms[atom_id].bbox for atom_id in component_ids)),
                )
            ):
                continue
            if _ordered_compact_text(
                _ordered_atom_text(ledger, candidate_atom_ids - extra_atom_ids)
            ) == _ordered_compact_text(word_text):
                return True
        return False

    return tuple(
        (candidate_text, candidate_atom_ids)
        for candidate_text, candidate_atom_ids in candidates
        if not is_invalid_digit_supercandidate(candidate_text, candidate_atom_ids)
    )


def _full_cell_ocr_word_date_source(
    ledger: EvidenceLedger,
    cell: Cell,
) -> tuple[str, frozenset[int], str] | None:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    word_atoms = tuple(
        ledger.atoms[atom_id] for atom_id in cell_atom_ids if ledger.atoms[atom_id].word is not None
    )
    normalized = normalize_text(cell.text)
    matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_token_boundaries(normalized, match.start(), match.end())
    )
    if (
        len(word_atoms) != 1
        or len(word_atoms) != len(cell_atom_ids)
        or word_atoms[0].word is None
        or word_atoms[0].word.source != "ocr"
        or normalize_text(word_atoms[0].text) != normalized
        or len(matches) != 1
    ):
        return None
    match = matches[0]
    residual = normalize_text(normalized[: match.start()] + normalized[match.end() :])
    return match.group(0), cell_atom_ids, residual


def _has_safe_indivisible_date_context(residual: str) -> bool:
    normalized = normalize_text(residual)
    compact = "".join(normalized.split())
    if (
        _RATE_DECIMAL_PATTERN.search(normalized) is not None
        or "%" in normalized
        or currencies_in_text(normalized)
        or any(unicodedata.category(char) == "Sc" for char in normalized)
        or is_installment_shaped(normalized)
        or is_money_shaped(normalized)
    ):
        return False
    tokens = phrase_tokens(normalized, ignore_acronym_quotes=True)
    if not compact:
        return True
    if len(compact) == 1 and unicodedata.category(compact)[0] == "P":
        return True
    return bool(tokens) and all(
        not token.isdigit() and token in _INDIVISIBLE_DATE_CONTEXT_TOKENS for token in tokens
    )


def _has_safe_date_parse_residual(residual: str) -> bool:
    normalized = normalize_text(residual)
    if not normalized:
        return True
    if (
        currencies_in_text(normalized)
        or any(unicodedata.category(char) == "Sc" for char in normalized)
        or "%" in normalized
        or _RATE_DECIMAL_PATTERN.search(normalized) is not None
        or is_installment_shaped(normalized)
    ):
        return False
    if _has_safe_indivisible_date_context(normalized):
        return True
    residual_chars = tuple(char for char in normalized if not char.isspace())
    return bool(residual_chars) and all(
        char.isalpha() or unicodedata.category(char)[0] in {"M", "P"} for char in residual_chars
    )


def _semantic_positioned_date_sources(
    ledger: EvidenceLedger,
    cell: Cell,
) -> tuple[tuple[str, frozenset[int]], ...]:
    sources = list(_positioned_date_sources(ledger, cell))
    full_cell_source = _full_cell_ocr_word_date_source(ledger, cell)
    if full_cell_source is not None and _has_safe_indivisible_date_context(full_cell_source[2]):
        sources.append(full_cell_source[:2])
    return tuple(
        {(normalize_text(text), atom_ids): (text, atom_ids) for text, atom_ids in sources}.values()
    )


def _exact_positioned_short_date_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
) -> frozenset[int]:
    logical_tokens = _short_date_tokens(cell)
    if len(logical_tokens) != 1:
        return frozenset()
    logical_token = logical_tokens[0]
    logical_compact = "".join(normalize_text(logical_token).split())
    sources = _positioned_date_sources(ledger, cell)
    if not sources or any(
        not any(
            _valid_short_date_token_for_style(source_text, candidate_style) is not None
            for candidate_style in DateTokenStyle
        )
        or "".join(normalize_text(source_text).split()) != logical_compact
        for source_text, _ in sources
    ):
        return frozenset()
    return frozenset(atom_id for _, source_atom_ids in sources for atom_id in source_atom_ids)


def _positioned_unanchored_short_date_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    style: DateTokenStyle | None,
) -> frozenset[int]:
    if not has_proven_unanchored_short_date(cell, style):
        return frozenset()
    return _exact_positioned_short_date_atom_ids(ledger, cell)


def _parse_assigned_column_date(
    row: Row,
    region: TableRegion,
    column: ColumnSpec,
    cell: Cell,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    *,
    require_positioned_backing: bool,
) -> tuple[date | None, str | None, frozenset[int]]:
    parsed_date, diagnostic = _parse_cell_date(cell, year_context)
    if parsed_date is not None and diagnostic is None:
        atom_ids = matching_date_atom_ids(ledger, cell, parsed_date, year_context)
        logical_residual = _bounded_logical_date_residual(cell)
        if (
            column.role is ColumnRole.DATE
            and (cell.glyphs or cell.words)
            and logical_residual is not None
        ):
            positioned_sources = _positioned_date_sources(ledger, cell)
            has_full_cell_backing = _has_full_cell_ocr_word_date_backing(
                ledger,
                cell,
                parsed_date,
                year_context,
            )
            has_separate_residual_backing = len(positioned_sources) == 1 and (
                _has_positioned_date_with_structural_residual(
                    row,
                    region,
                    column,
                    ledger,
                    cell,
                    positioned_sources[0][1],
                )
            )
            if not has_full_cell_backing and not has_separate_residual_backing:
                return None, "invalid_date", frozenset()
        if require_positioned_backing and (cell.glyphs or cell.words):
            if _has_conflicting_positioned_date_representation(
                cell,
                ledger,
                year_context,
                parsed_date,
            ):
                return None, "invalid_date", frozenset()
            if not atom_ids:
                if _has_full_cell_ocr_word_date_backing(
                    ledger,
                    cell,
                    parsed_date,
                    year_context,
                ):
                    atom_ids = ledger.atoms_for_cell(cell)
                else:
                    return None, "invalid_date", frozenset()
        return parsed_date, None, atom_ids
    if (
        diagnostic == "invalid_date"
        and column.role is ColumnRole.DATE
        and (boundary_date := _parse_text_only_full_year_boundary_date(cell, year_context))
        is not None
    ):
        atom_ids = ledger.atoms_for_cell(cell)
        if atom_ids:
            return boundary_date, None, atom_ids
    if diagnostic == "invalid_date":
        positioned_candidates = _without_invalid_digit_word_supercandidates(
            ledger,
            cell,
            _positioned_date_sources(ledger, cell),
            year_context,
        )
        if len(positioned_candidates) == 1:
            candidate_text, candidate_atom_ids = positioned_candidates[0]
            candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
            candidate_is_ocr = bool(candidate_atoms) and all(
                (atom.glyph is not None and atom.glyph.source == "ocr")
                or (atom.word is not None and atom.word.source == "ocr")
                for atom in candidate_atoms
            )
            positioned_date, positioned_diagnostic = _parse_date(
                candidate_text,
                year_context,
            )
            if positioned_diagnostic == "invalid_date" and candidate_is_ocr:
                positioned_date, positioned_diagnostic = _parse_ocr_contaminated_date_text(
                    candidate_text,
                    year_context,
                )
            if (
                positioned_date is not None
                and positioned_diagnostic is None
                and (
                    _has_positioned_date_with_structural_residual(
                        row,
                        region,
                        column,
                        ledger,
                        cell,
                        candidate_atom_ids,
                    )
                    or _has_separate_positioned_conversion_rate_residual(
                        ledger,
                        cell,
                        column,
                        region,
                        candidate_text,
                        candidate_atom_ids,
                    )
                    or _has_reordered_hebrew_positioned_representation(
                        ledger,
                        cell,
                        candidate_atom_ids,
                    )
                    or _has_lossless_full_positioned_date_representation(
                        ledger,
                        cell,
                        candidate_atom_ids,
                    )
                )
            ):
                return positioned_date, None, candidate_atom_ids
    if diagnostic == "invalid_date":
        parsed_date, diagnostic = _parse_date_without_duplicated_boundary_glyphs(
            row,
            column,
            cell,
            year_context,
        )
        if parsed_date is not None and diagnostic is None:
            remaining = tuple(
                glyph
                for glyph in cell.glyphs
                if column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
            )
            atom_ids = _glyph_atom_ids(ledger, cell, remaining)
            return (
                (parsed_date, None, atom_ids)
                if atom_ids or not require_positioned_backing
                else (None, "invalid_date", frozenset())
            )
    if diagnostic == "invalid_date":
        completion = adjacent_boundary_date_completion(
            row,
            column,
            cell,
            year_context,
        )
        if completion is not None:
            parsed_date, source_cell, source_glyph = completion
            atom_ids = _glyph_atom_ids(ledger, cell, cell.glyphs) | _glyph_atom_ids(
                ledger,
                source_cell,
                (source_glyph,),
            )
            return (
                (parsed_date, None, atom_ids)
                if atom_ids or not require_positioned_backing
                else (None, "invalid_date", frozenset())
            )
    if diagnostic == "invalid_date":
        parsed_date, diagnostic = _parse_overlapping_boundary_date(
            row,
            column,
            cell,
            year_context,
        )
        if parsed_date is not None and diagnostic is None:
            atom_ids = _overlapping_boundary_date_atom_ids(
                row,
                column,
                cell,
                ledger,
                year_context,
                parsed_date,
            )
            return (
                (parsed_date, None, atom_ids)
                if atom_ids or not require_positioned_backing
                else (None, "invalid_date", frozenset())
            )
    return parsed_date, diagnostic, frozenset()


def proven_assigned_date_evidence(
    row: Row,
    region: TableRegion,
    column: ColumnSpec,
    cell: Cell,
    ledger: EvidenceLedger,
    expected: date | None,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[frozenset[int], frozenset[int]]:
    """Return exact date and structural-residual atoms after strict date proof."""

    if expected is None or column.role is not ColumnRole.DATE:
        return frozenset(), frozenset()
    parsed, diagnostic, date_atom_ids = _parse_assigned_column_date(
        row,
        region,
        column,
        cell,
        ledger,
        year_context,
        require_positioned_backing=True,
    )
    if parsed != expected or diagnostic is not None:
        return frozenset(), frozenset()
    cell_atom_ids = ledger.atoms_for_cell(cell)
    matched_date_ids = matching_date_atom_ids(
        ledger,
        cell,
        expected,
        year_context,
    )
    layout_atom_ids = set(
        nonmaterial_date_layout_atom_ids(
            ledger,
            cell,
            matched_date_ids,
        )
    )
    layout_atom_ids.update(
        _ocr_marker_band_layout_atom_ids(
            region,
            column,
            ledger,
            cell,
            date_atom_ids,
        )
    )
    layout_atom_ids.update(
        _description_boundary_punctuation_atom_ids(
            row,
            region,
            column,
            ledger,
            cell,
            matched_date_ids,
        )
    )
    duplicated_date, duplicated_diagnostic = _parse_date_without_duplicated_boundary_glyphs(
        row,
        column,
        cell,
        year_context,
    )
    if duplicated_date == expected and duplicated_diagnostic is None:
        duplicated_glyphs = tuple(
            glyph
            for glyph in cell.glyphs
            if not column.bbox[0] <= _center_x(glyph.bbox) <= column.bbox[2]
        )
        layout_atom_ids.update(_glyph_atom_ids(ledger, cell, duplicated_glyphs))
    overlapping_date, overlapping_diagnostic = _parse_overlapping_boundary_date(
        row,
        column,
        cell,
        year_context,
    )
    if (
        overlapping_date == expected
        and overlapping_diagnostic is None
        and _overlapping_boundary_date_atom_ids(
            row,
            column,
            cell,
            ledger,
            year_context,
            expected,
        )
        and _has_lossless_overlapping_date_cell_representation(
            row,
            column,
            cell,
            ledger,
            year_context,
            expected,
        )
    ):
        layout_atom_ids.update(cell_atom_ids - date_atom_ids)
    return date_atom_ids, frozenset(layout_atom_ids)


def date_column_header_kind(column: ColumnSpec) -> DateColumnKind | None:
    header = " ".join(phrase_tokens(" ".join(cell.text for cell in column.source_cells)))
    if contains_token_sequence(header, ("posting date", "billing date", "תאריך חיוב")):
        return DateColumnKind.POSTING
    if contains_token_sequence(
        header,
        ("transaction date", "purchase date", "תאריך עסקה", "תאריך רכישה"),
    ):
        return DateColumnKind.TRANSACTION
    return None


def structural_date_column_kinds(
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
) -> dict[int, DateColumnKind]:
    columns = _role_columns(region, ColumnRole.DATE)
    if len(columns) != 2 or year_context is None:
        return {}
    header_kinds = tuple(date_column_header_kind(column) for column in columns)
    labeled_indexes = tuple(index for index, kind in enumerate(header_kinds) if kind is not None)
    if len(labeled_indexes) == 1:
        labeled_index = labeled_indexes[0]
        labeled_kind = header_kinds[labeled_index]
        return {
            columns[1 - labeled_index].index: (
                DateColumnKind.TRANSACTION
                if labeled_kind == DateColumnKind.POSTING
                else DateColumnKind.POSTING
            )
        }
    if labeled_indexes:
        return {}
    eligible_rows = tuple(
        row for row in region.rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    )
    amount_column = proven_billed_amount_column(region.table_schema, eligible_rows)
    if amount_column is None:
        return {}
    transaction_rows = tuple(
        row
        for row in region.rows
        if len(_cells_for_column(row, amount_column)) == 1
        and is_money_shaped(_cells_for_column(row, amount_column)[0].text)
    )
    if len(transaction_rows) < 2:
        return {}
    parsed_by_column: list[tuple[date | None, ...]] = []
    for column in columns:
        parsed_values: list[date | None] = []
        for row in transaction_rows:
            cells = _cells_for_column(row, column)
            if len(cells) > 1:
                return {}
            if not cells:
                parsed_values.append(None)
                continue
            parsed_date, diagnostic = _parse_cell_date(cells[0], year_context)
            if diagnostic is not None or parsed_date is None:
                return {}
            parsed_values.append(parsed_date)
        parsed_by_column.append(tuple(parsed_values))
    complete_indexes = tuple(
        index
        for index, values in enumerate(parsed_by_column)
        if all(value is not None for value in values)
    )
    if len(complete_indexes) == 2:
        first_values = tuple(value for value in parsed_by_column[0] if value is not None)
        second_values = tuple(value for value in parsed_by_column[1] if value is not None)
        ordered_candidates: list[tuple[int, int]] = []
        if all(
            first <= second for first, second in zip(first_values, second_values, strict=True)
        ) and any(
            first < second for first, second in zip(first_values, second_values, strict=True)
        ):
            ordered_candidates.append((0, 1))
        if all(
            second <= first for first, second in zip(first_values, second_values, strict=True)
        ) and any(
            second < first for first, second in zip(first_values, second_values, strict=True)
        ):
            ordered_candidates.append((1, 0))
        if len(ordered_candidates) != 1:
            return {}
        transaction_index, posting_index = ordered_candidates[0]
        return {
            columns[transaction_index].index: DateColumnKind.TRANSACTION,
            columns[posting_index].index: DateColumnKind.POSTING,
        }
    if len(complete_indexes) != 1:
        return {}
    transaction_index = complete_indexes[0]
    posting_index = 1 - transaction_index
    posting_values = parsed_by_column[posting_index]
    if all(value is not None for value in posting_values):
        return {}
    paired = tuple(
        (transaction_value, posting_value)
        for transaction_value, posting_value in zip(
            parsed_by_column[transaction_index], posting_values, strict=True
        )
        if transaction_value is not None and posting_value is not None
    )
    if len(paired) < 2:
        return {}
    if not all(transaction <= posting for transaction, posting in paired):
        return {}
    if not any(transaction < posting for transaction, posting in paired):
        return {}
    return {
        columns[transaction_index].index: DateColumnKind.TRANSACTION,
        columns[posting_index].index: DateColumnKind.POSTING,
    }


def proven_date_description_layout_marker_atom_ids(
    *,
    ledger: EvidenceLedger,
    cell: Cell,
    date_column: ColumnSpec,
    date_atom_ids: frozenset[int],
    description_atom_ids: frozenset[int],
    excluded_atom_ids: frozenset[int] = frozenset(),
) -> frozenset[int]:
    """Return one strictly proven custom-font digit between date and description."""

    cell_atom_ids = ledger.atoms_for_cell(cell)
    if (
        not date_atom_ids
        or not description_atom_ids
        or not date_atom_ids <= cell_atom_ids
        or not description_atom_ids <= cell_atom_ids
        or date_atom_ids & description_atom_ids
    ):
        return frozenset()
    marker_atom_ids = cell_atom_ids - date_atom_ids - description_atom_ids - excluded_atom_ids
    if len(marker_atom_ids) != 1:
        return frozenset()
    marker_atom = ledger.atoms[next(iter(marker_atom_ids))]
    date_atoms = tuple(ledger.atoms[atom_id] for atom_id in date_atom_ids)
    description_atoms = tuple(ledger.atoms[atom_id] for atom_id in description_atom_ids)
    if (
        marker_atom.glyph is None
        or marker_atom.glyph.source != "digital"
        or marker_atom.glyph.confidence != 1.0
        or len(marker_atom.glyph.char) != 1
        or not marker_atom.glyph.char.isdigit()
        or any(atom.glyph is None or atom.glyph.source != "digital" for atom in date_atoms)
        or any(atom.glyph is None or atom.glyph.source != "digital" for atom in description_atoms)
    ):
        return frozenset()
    date_glyphs = tuple(atom.glyph for atom in date_atoms if atom.glyph is not None)
    description_glyphs = tuple(atom.glyph for atom in description_atoms if atom.glyph is not None)
    if marker_atom.glyph.font in {glyph.font for glyph in (*date_glyphs, *description_glyphs)}:
        return frozenset()
    date_digit_widths = tuple(_width(glyph.bbox) for glyph in date_glyphs if glyph.char.isdigit())
    if (
        not date_digit_widths
        or min(date_digit_widths) <= 0.0
        or _width(marker_atom.bbox) < statistics.median(date_digit_widths) * 1.2
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
    date_height = min(_height(date_bbox), _height(marker_atom.bbox))
    description_height = min(
        _height(description_bbox),
        _height(marker_atom.bbox),
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
        or not date_column.bbox[0] <= _center_x(date_bbox) <= date_column.bbox[2]
        or not date_column.bbox[0] <= _center_x(marker_atom.bbox) <= date_column.bbox[2]
    ):
        return frozenset()
    return marker_atom_ids


def matches_positioned_date_description_residual(
    *,
    ledger: EvidenceLedger,
    cell: Cell,
    description_atom_ids: frozenset[int],
    residual: str,
) -> bool:
    """Return whether exact positioned text backs one date-boundary description."""

    normalized_residual = normalize_text(residual)
    rendered_description = normalize_text(ledger.render(description_atom_ids))
    if rendered_description == normalized_residual:
        return True
    compact_residual = "".join(normalized_residual.split())
    if (
        not compact_residual
        or not all(char.isalpha() and "\u0590" <= char <= "\u05ff" for char in compact_residual)
        or _character_signature(rendered_description) != _character_signature(normalized_residual)
    ):
        return False
    cell_atom_ids = ledger.atoms_for_cell(cell)
    exact_words = tuple(
        word
        for word in cell.words
        if word.source == "digital"
        and word.confidence == 1.0
        and normalize_text(word.text) == rendered_description
        and ledger.atoms_in_bbox(cell_atom_ids, word.bbox) == description_atom_ids
    )
    return len(exact_words) == 1


def positioned_date_description_residual_atom_ids(
    *,
    ledger: EvidenceLedger,
    cell: Cell,
    residual: str,
) -> frozenset[int]:
    """Return the exact positioned word band backing a description residual."""

    description_words = tuple(
        word
        for word in cell.words
        if any(char.isalpha() for char in word.text)
        and not any(char.isdigit() for char in word.text)
    )
    if not description_words:
        return frozenset()
    description_bbox = union_bbox(word.bbox for word in description_words)
    atom_ids = ledger.atoms_in_bbox(ledger.atoms_for_cell(cell), description_bbox)
    if not atom_ids or not matches_positioned_date_description_residual(
        ledger=ledger,
        cell=cell,
        description_atom_ids=atom_ids,
        residual=residual,
    ):
        return frozenset()
    return atom_ids


def _residual_without_separate_date_layout_marker(
    *,
    residual: str,
    matched_date_text: str,
    cell: Cell,
    date_column: ColumnSpec,
    ledger: EvidenceLedger | None,
) -> str | None:
    if ledger is None:
        return None
    numeric_indexes = tuple(index for index, char in enumerate(residual) if char.isdigit())
    if len(numeric_indexes) != 1:
        return None
    cell_atom_ids = ledger.atoms_for_cell(cell)
    date_words = tuple(
        word
        for word in cell.words
        if normalize_text(word.text) == normalize_text(matched_date_text)
    )
    if len(date_words) != 1:
        return None
    date_atom_ids = ledger.atoms_in_bbox(cell_atom_ids, date_words[0].bbox)
    numeric_index = numeric_indexes[0]
    stripped = normalize_text(residual[:numeric_index] + residual[numeric_index + 1 :])
    description_atom_ids = positioned_date_description_residual_atom_ids(
        ledger=ledger,
        cell=cell,
        residual=stripped,
    )
    marker_atom_ids = proven_date_description_layout_marker_atom_ids(
        ledger=ledger,
        cell=cell,
        date_column=date_column,
        date_atom_ids=date_atom_ids,
        description_atom_ids=description_atom_ids,
    )
    if len(marker_atom_ids) != 1:
        return None
    marker_atom = ledger.atoms[next(iter(marker_atom_ids))]
    if marker_atom.glyph is None or residual[numeric_index] != marker_atom.glyph.char:
        return None
    if (
        not stripped
        or any(char.isdigit() for char in stripped)
        or not matches_positioned_date_description_residual(
            ledger=ledger,
            cell=cell,
            description_atom_ids=description_atom_ids,
            residual=stripped,
        )
    ):
        return None
    return stripped


def _boundary_date_description_split(
    cell: Cell,
    date_column: ColumnSpec,
    description_column: ColumnSpec,
    year_context: DiscoveredDateYearContext | None,
    ledger: EvidenceLedger | None,
) -> tuple[date | None, str] | None:
    cell_width = max(0.0, cell.bbox[2] - cell.bbox[0])
    if (
        cell_width <= 0
        or horizontal_overlap(cell.bbox, date_column.bbox) <= 0
        or horizontal_overlap(cell.bbox, date_column.bbox) / cell_width
        < _MIN_DATE_DESCRIPTION_CELL_OVERLAP
    ):
        return None
    normalized = normalize_text(cell.text)
    matches = tuple(
        match
        for match in _DATE_TOKEN_PATTERN.finditer(normalized)
        if has_date_numeric_run_boundaries(normalized, match.start(), match.end())
    )
    if len(matches) != 1:
        return None
    match = matches[0]
    parsed_date, _ = _parse_cell_date(cell, year_context)
    residual = normalize_text(normalized[: match.start()] + normalized[match.end() :])
    if any(char.isdigit() for char in residual):
        proven_residual = _residual_without_separate_date_layout_marker(
            residual=residual,
            matched_date_text=match.group(),
            cell=cell,
            date_column=date_column,
            ledger=ledger,
        )
        if proven_residual is None:
            return None
        residual = proven_residual
    if (
        not residual
        or not any(char.isalpha() for char in residual)
        or any(char.isdigit() for char in residual)
    ):
        return None
    description_boundary = (
        description_column.bbox[2]
        if _center_x(description_column.bbox) < _center_x(date_column.bbox)
        else description_column.bbox[0]
    )
    residual_word_touches_boundary = any(
        any(char.isalpha() for char in word.text)
        and not any(char.isdigit() for char in word.text)
        and max(0.0, word.bbox[0] - description_boundary, description_boundary - word.bbox[2])
        <= _height(word.bbox) * 0.2
        for word in cell.words
    )
    if (
        horizontal_overlap(cell.bbox, description_column.bbox) / cell_width
        < _MIN_DATE_DESCRIPTION_CELL_OVERLAP
        and not residual_word_touches_boundary
    ):
        return None
    return parsed_date, residual


def boundary_date_description_splits(
    row: Row,
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    *,
    ledger: EvidenceLedger | None = None,
) -> tuple[tuple[Cell, date | None, str], ...]:
    """Return unique cells that combine a supported date with description text."""

    date_columns = _role_columns(region, ColumnRole.DATE)
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    if len(date_columns) != 1 or len(description_columns) != 1:
        return ()
    candidates = tuple(
        (cell, parsed_date, residual)
        for cell in row.cells
        if (
            split := _boundary_date_description_split(
                cell,
                date_columns[0],
                description_columns[0],
                year_context,
                ledger,
            )
        )
        for parsed_date, residual in (split,)
    )
    unique = {
        (candidate[0].bbox, candidate[1], candidate[2]): candidate for candidate in candidates
    }
    return tuple(unique.values())


def _backed_boundary_date_description_splits(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[tuple[Cell, date | None, str], ...]:
    backed_splits: list[tuple[Cell, date | None, str]] = []
    date_columns = _role_columns(region, ColumnRole.DATE)
    for cell, value, residual in boundary_date_description_splits(
        row,
        region,
        year_context,
        ledger=ledger,
    ):
        if value is None:
            sources = _positioned_date_sources(ledger, cell)
            if len(sources) > 1 and len(date_columns) == 1:
                description_atom_ids = positioned_date_description_residual_atom_ids(
                    ledger=ledger,
                    cell=cell,
                    residual=residual,
                )
                if description_atom_ids:
                    partitioned_sources = tuple(
                        source
                        for source in sources
                        if proven_date_description_layout_marker_atom_ids(
                            ledger=ledger,
                            cell=cell,
                            date_column=date_columns[0],
                            date_atom_ids=source[1],
                            description_atom_ids=description_atom_ids,
                        )
                    )
                    if len(partitioned_sources) == 1:
                        sources = partitioned_sources
            if len(sources) == 1:
                source_text, source_atom_ids = sources[0]
                cell_atom_ids = ledger.atoms_for_cell(cell)
                physical_text = _ordered_atom_text(ledger, cell_atom_ids)
                signature_matches = _character_signature(cell.text) == _character_signature(
                    physical_text
                ) and _ordered_compact_text(source_text) in _ordered_compact_text(cell.text)
                positioned_date, positioned_diagnostic = _parse_date(
                    source_text,
                    year_context,
                )
                source_atoms = tuple(ledger.atoms[atom_id] for atom_id in source_atom_ids)
                if (
                    positioned_diagnostic == "invalid_date"
                    and source_atoms
                    and all(
                        (atom.glyph is not None and atom.glyph.source == "ocr")
                        or (atom.word is not None and atom.word.source == "ocr")
                        for atom in source_atoms
                    )
                ):
                    positioned_date, positioned_diagnostic = _parse_ocr_contaminated_date_text(
                        source_text,
                        year_context,
                    )
                if (
                    signature_matches
                    and positioned_date is not None
                    and positioned_diagnostic is None
                ):
                    backed_splits.append((cell, positioned_date, residual))
                    continue
            if _exact_positioned_short_date_atom_ids(ledger, cell):
                backed_splits.append((cell, None, residual))
            continue
        backed = bool(matching_date_atom_ids(ledger, cell, value, year_context)) or (
            _has_full_cell_ocr_word_date_backing(
                ledger,
                cell,
                value,
                year_context,
            )
        )
        if backed and not _has_conflicting_positioned_date_representation(
            cell,
            ledger,
            year_context,
            value,
        ):
            backed_splits.append((cell, value, residual))
    return tuple(backed_splits)


def extract_dates(
    row: Row,
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    structural_kinds: Mapping[int, DateColumnKind],
    *,
    ledger: EvidenceLedger | None = None,
) -> DateExtraction:
    source_ledger = ledger or EvidenceLedger.from_rows((row,))
    columns = _role_columns(region, ColumnRole.DATE)
    diagnostics: list[str] = []
    if not columns:
        diagnostics.append("missing_date_cell")
    parsed: list[tuple[DateColumnKind | None, date | None, str | None]] = []
    for column in columns:
        cells = _cells_for_column(row, column)
        unanchored_style = (
            proven_unanchored_short_date_style(region, column) if year_context is None else None
        )
        if len(cells) != 1:
            if cells:
                diagnostics.append("multiple_date_cells")
            elif structural_kinds.get(column.index) != DateColumnKind.POSTING:
                boundary_splits = _backed_boundary_date_description_splits(
                    row,
                    region,
                    source_ledger,
                    year_context,
                )
                if len(columns) == 1 and len(boundary_splits) == 1:
                    split_cell, split_date, _ = boundary_splits[0]
                    split_diagnostic = (
                        None
                        if split_date is not None
                        or _positioned_unanchored_short_date_atom_ids(
                            source_ledger,
                            split_cell,
                            unanchored_style,
                        )
                        else "invalid_date"
                    )
                    parsed.append(
                        (
                            date_column_header_kind(column) or structural_kinds.get(column.index),
                            split_date,
                            split_diagnostic,
                        )
                    )
                else:
                    diagnostics.append("missing_date_cell")
            continue
        if _positioned_unanchored_short_date_atom_ids(
            source_ledger,
            cells[0],
            unanchored_style,
        ):
            parsed_date, date_diagnostic = None, None
        else:
            parsed_date, date_diagnostic, _ = _parse_assigned_column_date(
                row,
                region,
                column,
                cells[0],
                source_ledger,
                year_context,
                require_positioned_backing=True,
            )
        if date_diagnostic is not None:
            boundary_splits = _backed_boundary_date_description_splits(
                row,
                region,
                source_ledger,
                year_context,
            )
            if len(columns) == 1 and len(boundary_splits) == 1:
                split_cell, split_date, _ = boundary_splits[0]
                if split_date is not None or _positioned_unanchored_short_date_atom_ids(
                    source_ledger,
                    split_cell,
                    unanchored_style,
                ):
                    parsed_date = split_date
                    date_diagnostic = None
        parsed.append(
            (
                date_column_header_kind(column) or structural_kinds.get(column.index),
                parsed_date,
                date_diagnostic,
            )
        )
    transaction_date: date | None = None
    posting_date: date | None = None
    conversion_date: date | None = None
    if len(columns) == 1 and parsed:
        transaction_date = parsed[0][1]
        if parsed[0][2] is not None:
            diagnostics.extend(("invalid_transaction_date", f"transaction_date:{parsed[0][2]}"))
    elif len(columns) > 1:
        kinds = tuple(
            date_column_header_kind(column) or structural_kinds.get(column.index)
            for column in columns
        )
        if kinds.count(DateColumnKind.TRANSACTION) != 1 or kinds.count(DateColumnKind.POSTING) != 1:
            diagnostics.append("unresolved_date_column_roles")
        else:
            for kind, parsed_date, date_diagnostic in parsed:
                if kind == DateColumnKind.TRANSACTION:
                    transaction_date = parsed_date
                    if date_diagnostic is not None:
                        diagnostics.extend(
                            ("invalid_transaction_date", f"transaction_date:{date_diagnostic}")
                        )
                elif kind == DateColumnKind.POSTING:
                    posting_date = parsed_date
                    if date_diagnostic is not None:
                        diagnostics.extend(
                            ("invalid_posting_date", f"posting_date:{date_diagnostic}")
                        )
    conversion_columns = _role_columns(region, ColumnRole.CONVERSION_DATE)
    unresolved_conversion_cells = [
        cell
        for column in conversion_columns
        for cell in _cells_for_column(row, column)
        if normalize_text(cell.text) and not _is_explicit_non_date_rate_source(column, cell, region)
    ]
    if len(conversion_columns) == 1:
        conversion_cells = tuple(
            cell
            for cell in _cells_for_column(row, conversion_columns[0])
            if not _is_explicit_non_date_rate_source(
                conversion_columns[0],
                cell,
                region,
            )
        )
        if len(conversion_cells) == 1:
            parsed_conversion_date, conversion_diagnostic, _ = _parse_assigned_column_date(
                row,
                region,
                conversion_columns[0],
                conversion_cells[0],
                source_ledger,
                year_context,
                require_positioned_backing=True,
            )
            if conversion_diagnostic is None:
                conversion_date = parsed_conversion_date
                if conversion_cells[0] in unresolved_conversion_cells:
                    unresolved_conversion_cells.remove(conversion_cells[0])
    return DateExtraction(
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        diagnostics=tuple(diagnostics),
        unresolved_conversion_cells=tuple(unresolved_conversion_cells),
    )


def _has_fragmented_date_cue(cell: Cell) -> bool:
    physical = "".join(
        glyph.char
        for glyph in sorted(
            cell.glyphs,
            key=lambda glyph: (
                bbox_center_y(glyph.bbox),
                glyph.bbox[0],
                glyph.bbox[2],
            ),
        )
    )
    sources = (cell.text, physical) if physical else (cell.text,)
    return any(
        has_date_token_boundaries(compact, match.start(), match.end())
        for source in sources
        for compact in ("".join(source.split()),)
        for match in _DATE_CUE_PATTERN.finditer(compact)
    )


def _atom_ids_bbox(ledger: EvidenceLedger, atom_ids: Iterable[int]) -> BBox:
    atoms = tuple(ledger.atoms[atom_id] for atom_id in atom_ids)
    return union_bbox(atom.bbox for atom in atoms)


def _physical_atom_lines(
    ledger: EvidenceLedger,
    cell: Cell,
) -> tuple[tuple[int, ...], ...]:
    positioned = tuple(
        atom_id
        for atom_id in ledger.atoms_for_cell(cell)
        if ledger.atoms[atom_id].glyph is not None or ledger.atoms[atom_id].word is not None
    )
    lines: list[list[int]] = []
    for atom_id in sorted(
        positioned,
        key=lambda value: (
            bbox_center_y(ledger.atoms[value].bbox),
            ledger.atoms[value].bbox[0],
            ledger.atoms[value].bbox[2],
        ),
    ):
        atom = ledger.atoms[atom_id]
        center_y = bbox_center_y(atom.bbox)
        matching = next(
            (
                line
                for line in lines
                if abs(center_y - bbox_center_y(ledger.atoms[line[0]].bbox))
                <= min(_height(atom.bbox), _height(ledger.atoms[line[0]].bbox)) * 0.5
            ),
            None,
        )
        if matching is None:
            lines.append([atom_id])
        else:
            matching.append(atom_id)
    return tuple(
        tuple(sorted(line, key=lambda value: ledger.atoms[value].bbox[0])) for line in lines
    )


def _line_characters(
    ledger: EvidenceLedger,
    line: Sequence[int],
    cell: Cell,
) -> tuple[tuple[str, int | None], ...]:
    characters: list[tuple[str, int | None]] = []
    previous_id: int | None = None
    for atom_id in line:
        atom = ledger.atoms[atom_id]
        if previous_id is not None:
            previous = ledger.atoms[previous_id]
            gap = atom.bbox[0] - previous.bbox[2]
            has_physical_whitespace = any(
                glyph.char.isspace()
                and abs(bbox_center_y(glyph.bbox) - bbox_center_y(atom.bbox))
                <= min(_height(glyph.bbox), _height(atom.bbox)) * 0.5
                and previous.bbox[2] <= _center_x(glyph.bbox) <= atom.bbox[0]
                for glyph in cell.glyphs
            )
            if (
                gap > min(_height(previous.bbox), _height(atom.bbox)) * 0.6
                or has_physical_whitespace
            ):
                characters.append(("\x00", None))
        characters.extend((char, atom_id) for char in atom.text)
        previous_id = atom_id
    return tuple(characters)


def _vertically_aligned(first: BBox, second: BBox) -> bool:
    return vertical_overlap(first, second) >= 0.8


def _cross_cell_date_tokens(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> tuple[CrossCellDateEvidence, ...]:
    positioned_cells = tuple(
        sorted(
            (
                (column, cell)
                for column in region.table_schema.columns
                if column.role in {ColumnRole.CONVERSION_DATE, ColumnRole.UNKNOWN}
                for cell in _cells_for_column(row, column)
            ),
            key=lambda item: item[0].index,
        )
    )
    candidates: list[CrossCellDateEvidence] = []
    for (left_column, left_cell), (right_column, right_cell) in pairwise(positioned_cells):
        if right_column.index - left_column.index != 1:
            continue
        if not (
            is_typed_conversion_source(left_column, left_cell, region)
            or is_typed_conversion_source(right_column, right_cell, region)
        ):
            continue
        shared_boundary = (left_column.bbox[2] + right_column.bbox[0]) / 2
        for left_line in _physical_atom_lines(ledger, left_cell):
            left_line_bbox = _atom_ids_bbox(ledger, left_line)
            left_characters = _line_characters(ledger, left_line, left_cell)
            for right_line in _physical_atom_lines(ledger, right_cell):
                right_line_bbox = _atom_ids_bbox(ledger, right_line)
                if not _vertically_aligned(left_line_bbox, right_line_bbox):
                    continue
                right_characters = _line_characters(ledger, right_line, right_cell)
                characters = (*left_characters, *right_characters)
                combined = "".join(char for char, _ in characters)
                boundary = len(left_characters)
                for match in _DATE_TOKEN_PATTERN.finditer(combined):
                    if not match.start() < boundary < match.end():
                        continue
                    if not has_date_token_boundaries(
                        combined,
                        match.start(),
                        match.end(),
                    ):
                        continue
                    matched = characters[match.start() : match.end()]
                    atom_ids = frozenset(
                        atom_id
                        for char, atom_id in matched
                        if atom_id is not None and (char.isdigit() or char in "./-")
                    )
                    left_cell_ids = ledger.atoms_for_cell(left_cell)
                    right_cell_ids = ledger.atoms_for_cell(right_cell)
                    left_ids = atom_ids & left_cell_ids
                    right_ids = atom_ids & right_cell_ids
                    if not left_ids or not right_ids:
                        continue
                    left_fragment = "".join(
                        char
                        for char, atom_id in matched
                        if atom_id is not None and atom_id in left_ids
                    )
                    right_fragment = "".join(
                        char
                        for char, atom_id in matched
                        if atom_id is not None and atom_id in right_ids
                    )
                    left_logical_residual = _remove_ordered_compact_fragment(
                        left_cell.text,
                        left_fragment,
                    )
                    right_logical_residual = _remove_ordered_compact_fragment(
                        right_cell.text,
                        right_fragment,
                    )
                    if (
                        left_logical_residual is None
                        or right_logical_residual is None
                        or _digit_signature(left_cell.text)
                        != _digit_signature(_ordered_atom_text(ledger, left_cell_ids))
                        or _digit_signature(right_cell.text)
                        != _digit_signature(_ordered_atom_text(ledger, right_cell_ids))
                        or _material_numeric_sequence(left_logical_residual)
                        != _material_numeric_sequence(
                            _ordered_atom_text(ledger, left_cell_ids - left_ids)
                        )
                        or _material_numeric_sequence(right_logical_residual)
                        != _material_numeric_sequence(
                            _ordered_atom_text(ledger, right_cell_ids - right_ids)
                        )
                    ):
                        continue
                    left_bbox = _atom_ids_bbox(ledger, left_ids)
                    right_bbox = _atom_ids_bbox(ledger, right_ids)
                    tolerance = min(_height(left_bbox), _height(right_bbox)) * 0.6
                    gap = right_bbox[0] - left_bbox[2]
                    if (
                        tolerance <= 0
                        or not -tolerance * 0.2 <= gap <= tolerance
                        or abs(left_bbox[2] - shared_boundary) > tolerance
                        or abs(right_bbox[0] - shared_boundary) > tolerance
                    ):
                        continue
                    candidates.append(
                        CrossCellDateEvidence(
                            text=match.group(0),
                            cells=frozenset((left_cell, right_cell)),
                            atom_ids=atom_ids,
                        )
                    )
    return tuple(candidates)


def cross_cell_date_source_cells(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> frozenset[Cell]:
    return frozenset(
        cell for evidence in _cross_cell_date_tokens(row, region, ledger) for cell in evidence.cells
    )


def parsed_cross_cell_conversion_evidence(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    transaction_date: date | None,
) -> tuple[tuple[date, CrossCellDateEvidence], ...]:
    parsed: list[tuple[date, CrossCellDateEvidence]] = []
    for evidence in _cross_cell_date_tokens(row, region, ledger):
        value = _parse_cross_cell_conversion_date(
            evidence,
            year_context,
            transaction_date,
        )
        if value is not None:
            parsed.append((value, evidence))
    return tuple(parsed)


def _parse_cross_cell_conversion_date(
    evidence: CrossCellDateEvidence,
    year_context: DiscoveredDateYearContext | None,
    transaction_date: date | None,
) -> date | None:
    if transaction_date is None:
        return None
    value = _parse_date_near_anchor(evidence.text, year_context, transaction_date)
    if value is None or abs((value - transaction_date).days) > 31:
        return None
    return value


def _parse_date_near_anchor(
    text: str,
    year_context: DiscoveredDateYearContext | None,
    anchor: date | None,
) -> date | None:
    parsed = _parse_date(text, year_context)[0]
    if anchor is None:
        return parsed
    nearby_candidates = {
        parsed for parsed in (parsed,) if parsed is not None and abs((parsed - anchor).days) <= 31
    }
    if year_context is None:
        match = _DATE_PATTERN.fullmatch(normalize_text(text))
        if match is None:
            return next(iter(nearby_candidates)) if len(nearby_candidates) == 1 else None
        first, _, second, third = match.groups()
        for year in range(anchor.year - 1, anchor.year + 2):
            if year % 100 == int(third):
                with suppress(ValueError):
                    nearby_candidates.add(date(year, int(second), int(first)))
            if year % 100 == int(first):
                with suppress(ValueError):
                    nearby_candidates.add(date(year, int(second), int(third)))
        nearby_candidates = {
            candidate for candidate in nearby_candidates if abs((candidate - anchor).days) <= 31
        }
        return next(iter(nearby_candidates)) if len(nearby_candidates) == 1 else None
    local_years = tuple(
        year for year in range(anchor.year - 1, anchor.year + 2) if 1900 <= year <= 2100
    )
    match = _DATE_PATTERN.fullmatch(normalize_text(text))
    styles = _LOCAL_DATE_STYLES.get(match.group(2), ()) if match is not None else ()
    for style in styles:
        local_context = year_context.model_copy(
            update={
                "year": None,
                "year_by_suffix": tuple(sorted((year % 100, year) for year in local_years)),
                "style": style,
            }
        )
        local_parsed = _parse_date(text, local_context)[0]
        if local_parsed is not None and abs((local_parsed - anchor).days) <= 31:
            nearby_candidates.add(local_parsed)
    return next(iter(nearby_candidates)) if len(nearby_candidates) == 1 else None


def _has_full_cell_ocr_word_date_backing(
    ledger: EvidenceLedger,
    cell: Cell,
    expected: date,
    year_context: DiscoveredDateYearContext | None,
) -> bool:
    source = _full_cell_ocr_word_date_source(ledger, cell)
    if source is None or _parse_cell_date(cell, year_context)[0] != expected:
        return False
    source_text, _, residual = source
    return _has_safe_indivisible_date_context(residual) and (
        _parse_date(source_text, year_context)[0] == expected
        or _parse_ocr_contaminated_date_text(source_text, year_context)[0] == expected
    )


def matching_date_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    expected: date | None,
    year_context: DiscoveredDateYearContext | None,
) -> frozenset[int]:
    if expected is None:
        return frozenset()
    matching: set[int] = set()
    for candidate_text, candidate_atom_ids in _positioned_date_sources(ledger, cell):
        if _parse_date_near_anchor(candidate_text, year_context, expected) == expected:
            matching.update(candidate_atom_ids)
            continue
        candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
        if (
            candidate_atoms
            and all(
                (atom.glyph is not None and atom.glyph.source == "ocr")
                or (atom.word is not None and atom.word.source == "ocr")
                for atom in candidate_atoms
            )
            and _parse_ocr_contaminated_date_text(candidate_text, year_context)[0] == expected
        ):
            matching.update(candidate_atom_ids)
    cell_atom_ids = ledger.atoms_for_cell(cell)
    has_only_cell_text_evidence = bool(cell_atom_ids) and all(
        ledger.atoms[atom_id].glyph is None and ledger.atoms[atom_id].word is None
        for atom_id in cell_atom_ids
    )
    if (
        not matching
        and has_only_cell_text_evidence
        and not cell.glyphs
        and not cell.words
        and (
            _parse_cell_date(cell, year_context)[0] == expected
            or _parse_text_only_full_year_boundary_date(cell, year_context) == expected
        )
    ):
        matching.update(cell_atom_ids)
    return frozenset(matching)


def _has_conflicting_positioned_date_representation(
    cell: Cell,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    anchor: date | None,
) -> bool:
    logical_date = _parse_cell_date(cell, year_context)[0]
    candidates = _positioned_date_sources(ledger, cell)
    if not candidates:
        return False
    if len(candidates) == 1 and _bounded_logical_date_match(cell, candidates[0][0]) is not None:
        return not _has_compatible_bounded_date_representations(
            ledger,
            cell,
            candidates[0][0],
            candidates[0][1],
        )
    if logical_date is None:
        if len(candidates) != 1:
            return True
        candidate_text, candidate_atom_ids = candidates[0]
        return not (
            _bounded_logical_date_match(cell, candidate_text) is not None
            or _has_reordered_hebrew_positioned_representation(
                ledger,
                cell,
                candidate_atom_ids,
            )
            or _has_lossless_full_positioned_date_representation(
                ledger,
                cell,
                candidate_atom_ids,
            )
        )
    positioned_dates: list[date | None] = []
    for candidate_text, candidate_atom_ids in candidates:
        parsed_date = _parse_date_near_anchor(candidate_text, year_context, anchor)
        if parsed_date is None:
            candidate_atoms = tuple(ledger.atoms[atom_id] for atom_id in candidate_atom_ids)
            if candidate_atoms and all(
                (atom.glyph is not None and atom.glyph.source == "ocr")
                or (atom.word is not None and atom.word.source == "ocr")
                for atom in candidate_atoms
            ):
                repaired_date = _parse_ocr_contaminated_date_text(
                    candidate_text,
                    year_context,
                )[0]
                if repaired_date is not None and (
                    anchor is None or abs((repaired_date - anchor).days) <= 31
                ):
                    parsed_date = repaired_date
        positioned_dates.append(parsed_date)
    return any(value is None for value in positioned_dates) or set(positioned_dates) != {
        logical_date
    }


def accepted_conversion_date_atom_ids(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    *,
    explicit_conversion_date: date | None,
    semantic_extraction: ConversionDateExtraction,
) -> frozenset[int]:
    """Return only atom IDs backing the final accepted conversion date."""

    explicit_atom_ids = frozenset(
        atom_id
        for column in _role_columns(region, ColumnRole.CONVERSION_DATE)
        for cell in _cells_for_column(row, column)
        for parsed_date, _, parsed_atom_ids in (
            _parse_assigned_column_date(
                row,
                region,
                column,
                cell,
                ledger,
                year_context,
                require_positioned_backing=True,
            ),
        )
        if parsed_date == explicit_conversion_date
        for atom_id in parsed_atom_ids
    )
    if explicit_conversion_date is None:
        return (
            semantic_extraction.source_atom_ids
            if not semantic_extraction.diagnostics and semantic_extraction.source_cells
            else frozenset()
        )
    if semantic_extraction.value == explicit_conversion_date:
        return explicit_atom_ids | semantic_extraction.source_atom_ids
    return explicit_atom_ids


def _proven_unanchored_conversion_source(
    region: TableRegion,
    ledger: EvidenceLedger,
    candidate_sources: tuple[tuple[ColumnSpec, Cell], ...],
    same_cell_candidates: tuple[tuple[Cell, str, frozenset[int]], ...],
) -> tuple[Cell, frozenset[int]] | None:
    """Preserve a typed short-date token without inventing its calendar year."""

    date_columns = columns_for_role(region.table_schema, ColumnRole.DATE)
    styles = tuple(
        style
        for column in date_columns
        if (style := proven_unanchored_short_date_style(region, column)) is not None
    )
    if (
        len(date_columns) != 1
        or len(styles) != 1
        or len(candidate_sources) != 1
        or len(same_cell_candidates) != 1
    ):
        return None
    column, cell = candidate_sources[0]
    candidate_cell, candidate_text, candidate_atom_ids = same_cell_candidates[0]
    if (
        column.role is not ColumnRole.CONVERSION_DATE
        or candidate_cell is not cell
        or _valid_short_date_token_for_style(candidate_text, styles[0]) is None
        or not (
            _has_lossless_full_positioned_date_representation(
                ledger,
                cell,
                candidate_atom_ids,
            )
            or _has_separate_positioned_conversion_rate_residual(
                ledger,
                cell,
                column,
                region,
                candidate_text,
                candidate_atom_ids,
            )
        )
    ):
        return None
    return cell, candidate_atom_ids


def extract_conversion_date(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    *,
    original_currency: str | None,
    billing_currency: str,
    transaction_date: date | None,
    existing_conversion_date: date | None,
) -> ConversionDateExtraction:
    if original_currency is None or original_currency == billing_currency:
        return ConversionDateExtraction(None, (), frozenset(), frozenset())

    candidate_sources = tuple(
        (column, cell)
        for column in region.table_schema.columns
        if (
            column.role is ColumnRole.UNKNOWN
            and any(
                is_typed_conversion_source(column, cell, region)
                for cell in _cells_for_column(row, column)
            )
        )
        or (column.role is ColumnRole.CONVERSION_DATE and existing_conversion_date is None)
        for cell in _cells_for_column(row, column)
        if is_typed_conversion_source(column, cell, region)
    )
    candidate_cells = tuple(cell for _, cell in candidate_sources)
    same_cell_candidates = tuple(
        (cell, candidate_text, candidate_atom_ids)
        for cell in candidate_cells
        for candidate_text, candidate_atom_ids in _semantic_positioned_date_sources(ledger, cell)
    )
    raw_cross_cell_evidence = _cross_cell_date_tokens(row, region, ledger)
    represented_source_cells = {
        *(cell for cell, _, _ in same_cell_candidates),
        *(cell for evidence in raw_cross_cell_evidence for cell in evidence.cells),
    }
    has_unresolved_typed_source = any(
        _has_nonempty_source_content(cell)
        and (
            _has_conflicting_positioned_date_representation(
                cell,
                ledger,
                year_context,
                transaction_date,
            )
            or (
                cell not in represented_source_cells
                and _is_required_conversion_date_source(column, cell, region)
            )
        )
        and not _is_explicit_non_date_rate_source(column, cell, region)
        for column, cell in candidate_sources
    )
    parsed_sources = (
        *(
            (
                _parse_date_near_anchor(candidate_text, year_context, transaction_date),
                frozenset((cell,)),
                candidate_atom_ids,
            )
            for cell, candidate_text, candidate_atom_ids in same_cell_candidates
        ),
        *(
            (
                _parse_cross_cell_conversion_date(
                    evidence,
                    year_context,
                    transaction_date,
                ),
                evidence.cells,
                evidence.atom_ids,
            )
            for evidence in raw_cross_cell_evidence
        ),
    )
    if (
        year_context is None
        and transaction_date is None
        and not raw_cross_cell_evidence
        and not has_unresolved_typed_source
        and (
            unanchored_source := _proven_unanchored_conversion_source(
                region,
                ledger,
                candidate_sources,
                same_cell_candidates,
            )
        )
        is not None
    ):
        source_cell, source_atom_ids = unanchored_source
        return ConversionDateExtraction(
            None,
            (),
            frozenset((source_cell,)),
            source_atom_ids,
        )
    if not parsed_sources or has_unresolved_typed_source:
        has_date_cue = any(_has_fragmented_date_cue(cell) for cell in candidate_cells)
        return ConversionDateExtraction(
            None,
            ("unparsed_conversion_date_candidate",)
            if has_date_cue or has_unresolved_typed_source
            else (),
            frozenset(),
            frozenset(),
        )
    resolved: dict[date, tuple[set[Cell], set[int]]] = {}
    all_parsed = all(value is not None for value, _, _ in parsed_sources)
    for value, candidate_source_cells, candidate_source_atom_ids in parsed_sources:
        if value is None:
            continue
        cells, atom_ids = resolved.setdefault(value, (set(), set()))
        cells.update(candidate_source_cells)
        atom_ids.update(candidate_source_atom_ids)
    if all_parsed and len(resolved) == 1:
        value, (resolved_source_cells, resolved_source_atom_ids) = next(iter(resolved.items()))
        return ConversionDateExtraction(
            value,
            (),
            frozenset(resolved_source_cells),
            frozenset(resolved_source_atom_ids),
        )
    return ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


__all__ = [
    "BoundaryDateCompletion",
    "ConversionDateExtraction",
    "CrossCellDateEvidence",
    "DateColumnKind",
    "DateExtraction",
    "accepted_conversion_date_atom_ids",
    "adjacent_boundary_date_completion",
    "boundary_date_description_splits",
    "contains_date_cue",
    "cross_cell_date_source_cells",
    "date_column_header_kind",
    "extract_conversion_date",
    "extract_dates",
    "has_proven_unanchored_short_date",
    "is_date_shaped",
    "is_typed_conversion_source",
    "matches_positioned_date_description_residual",
    "matching_date_atom_ids",
    "nonmaterial_date_layout_atom_ids",
    "parsed_cross_cell_conversion_evidence",
    "positioned_date_description_residual_atom_ids",
    "proven_assigned_date_evidence",
    "proven_conversion_rate_residual_atom_ids",
    "proven_date_description_layout_marker_atom_ids",
    "proven_unanchored_short_date_style",
    "structural_date_column_kinds",
]
