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
from ccparser.geometry import center_inside as _bbox_center_inside
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    isolated_date_token,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import cell_has_ocr_evidence, logical_text_for_evidence
from ccparser.money import is_money_shaped
from ccparser.normalization_fields import is_installment_shaped
from ccparser.semantic_evidence import EvidenceLedger
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


def is_date_shaped(text: str) -> bool:
    """Return whether text is exactly one supported three-component date shape."""

    return _DATE_PATTERN.fullmatch(normalize_text(text)) is not None


def contains_date_cue(text: str) -> bool:
    """Return whether text contains the compact date cue used by semantic auditing."""

    return _DATE_CUE_PATTERN.search(normalize_text(text)) is not None


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def parse_date(
    text: str,
    year_context: DiscoveredDateYearContext | None = None,
) -> tuple[date | None, str | None]:
    normalized = normalize_text(text)
    full_date_matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
    if len(full_date_matches) > 1:
        return None, "ambiguous_date_tokens"
    isolated_token = isolated_date_token(normalized)
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
        short_matches = tuple(SHORT_DATE_TOKEN_PATTERNS[year_context.style].finditer(normalized))
        if len(short_matches) == 1:
            short_match = short_matches[0]
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


def _parse_ocr_contaminated_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    if year_context is None or not cell_has_ocr_evidence(cell):
        return None, "invalid_date"
    normalized = normalize_text(cell.text)
    matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
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
        if (parsed_date := parse_date(candidate, year_context)[0]) is not None
    }
    return (next(iter(repaired)), None) if len(repaired) == 1 else (None, "invalid_date")


def _parse_cell_date(
    cell: Cell,
    year_context: DiscoveredDateYearContext | None,
) -> tuple[date | None, str | None]:
    parsed = parse_date(cell.text, year_context)
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
    word_candidates = tuple(
        candidate
        for word in cell.words
        if (candidate := parse_date(word.text, year_context))[0] is not None
        and candidate[1] is None
    )
    return word_candidates[0] if len(word_candidates) == 1 else parsed


def _short_date_tokens(cell: Cell) -> tuple[str, ...]:
    tokens: list[str] = []
    for text in (cell.text, *(word.text for word in cell.words)):
        normalized = normalize_text(text)
        tokens.extend(match.group(0) for match in _DATE_TOKEN_PATTERN.finditer(normalized))
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
            clipped_date, clipped_diagnostic = parse_date(
                logical_text_for_evidence(clipped_glyphs, ()),
                year_context,
            )
            if clipped_date is not None and clipped_diagnostic is None:
                candidates[clipped_date] = (clipped_date, None)
        normalized = normalize_text(cell.text)
        matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
        if len(matches) != 1:
            continue
        match = matches[0]
        if cell_center < column_center and match.end() != len(normalized):
            continue
        if cell_center > column_center and match.start() != 0:
            continue
        parsed_date, diagnostic = parse_date(match.group(0), year_context)
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
        or parse_date(base_text, year_context)[0] is not None
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
        parsed_date, diagnostic = parse_date(candidate_text, year_context)
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
    remaining = tuple(glyph for glyph in assigned_cell.glyphs if glyph not in outside)
    if not remaining:
        return None, "invalid_date"
    parsed_date, diagnostic = parse_date(
        logical_text_for_evidence(remaining, ()),
        year_context,
    )
    return (
        (parsed_date, None)
        if parsed_date is not None and diagnostic is None
        else (None, "invalid_date")
    )


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


def _boundary_date_description_split(
    cell: Cell,
    date_column: ColumnSpec,
    description_column: ColumnSpec,
    year_context: DiscoveredDateYearContext | None,
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
    matches = tuple(_DATE_TOKEN_PATTERN.finditer(normalized))
    if len(matches) != 1:
        return None
    match = matches[0]
    parsed_date, _ = _parse_cell_date(cell, year_context)
    residual = normalize_text(normalized[: match.start()] + normalized[match.end() :])
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
            )
        )
        for parsed_date, residual in (split,)
    )
    unique = {
        (candidate[0].bbox, candidate[1], candidate[2]): candidate for candidate in candidates
    }
    return tuple(unique.values())


def extract_dates(
    row: Row,
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    structural_kinds: Mapping[int, DateColumnKind],
) -> DateExtraction:
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
                boundary_splits = boundary_date_description_splits(
                    row,
                    region,
                    year_context,
                )
                if len(columns) == 1 and len(boundary_splits) == 1:
                    split_cell, split_date, _ = boundary_splits[0]
                    split_diagnostic = (
                        None
                        if split_date is not None
                        or has_proven_unanchored_short_date(split_cell, unanchored_style)
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
        if has_proven_unanchored_short_date(cells[0], unanchored_style):
            parsed_date, date_diagnostic = None, None
        else:
            parsed_date, date_diagnostic = _parse_cell_date(cells[0], year_context)
        if date_diagnostic == "invalid_date":
            parsed_date, date_diagnostic = _parse_date_without_duplicated_boundary_glyphs(
                row,
                column,
                cells[0],
                year_context,
            )
        if (
            date_diagnostic == "invalid_date"
            and (
                completion := adjacent_boundary_date_completion(
                    row,
                    column,
                    cells[0],
                    year_context,
                )
            )
            is not None
        ):
            parsed_date, _, _ = completion
            date_diagnostic = None
        if date_diagnostic == "invalid_date":
            parsed_date, date_diagnostic = _parse_overlapping_boundary_date(
                row,
                column,
                cells[0],
                year_context,
            )
        if date_diagnostic is not None:
            boundary_splits = boundary_date_description_splits(
                row,
                region,
                year_context,
            )
            if len(columns) == 1 and len(boundary_splits) == 1:
                parsed_date = boundary_splits[0][1]
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
        if normalize_text(cell.text)
    ]
    if len(conversion_columns) == 1:
        conversion_cells = _cells_for_column(row, conversion_columns[0])
        if len(conversion_cells) == 1:
            parsed_conversion_date, conversion_diagnostic = _parse_cell_date(
                conversion_cells[0], year_context
            )
            if conversion_diagnostic == "invalid_date":
                parsed_conversion_date, conversion_diagnostic = (
                    _parse_date_without_duplicated_boundary_glyphs(
                        row,
                        conversion_columns[0],
                        conversion_cells[0],
                        year_context,
                    )
                )
            if conversion_diagnostic == "invalid_date":
                parsed_conversion_date, conversion_diagnostic = _parse_overlapping_boundary_date(
                    row,
                    conversion_columns[0],
                    conversion_cells[0],
                    year_context,
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
    return any(_DATE_CUE_PATTERN.search("".join(source.split())) is not None for source in sources)


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
) -> tuple[tuple[str, int | None], ...]:
    characters: list[tuple[str, int | None]] = []
    previous_id: int | None = None
    for atom_id in line:
        atom = ledger.atoms[atom_id]
        if previous_id is not None:
            previous = ledger.atoms[previous_id]
            gap = atom.bbox[0] - previous.bbox[2]
            if gap > min(_height(previous.bbox), _height(atom.bbox)) * 0.6:
                characters.append(("\x00", None))
        characters.extend((char, atom_id) for char in atom.text)
        previous_id = atom_id
    return tuple(characters)


def _vertically_aligned(first: BBox, second: BBox) -> bool:
    return vertical_overlap(first, second) >= 0.8


def cross_cell_date_tokens(
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
        shared_boundary = (left_column.bbox[2] + right_column.bbox[0]) / 2
        for left_line in _physical_atom_lines(ledger, left_cell):
            left_line_bbox = _atom_ids_bbox(ledger, left_line)
            left_characters = _line_characters(ledger, left_line)
            for right_line in _physical_atom_lines(ledger, right_cell):
                right_line_bbox = _atom_ids_bbox(ledger, right_line)
                if not _vertically_aligned(left_line_bbox, right_line_bbox):
                    continue
                right_characters = _line_characters(ledger, right_line)
                characters = (*left_characters, *right_characters)
                combined = "".join(char for char, _ in characters)
                boundary = len(left_characters)
                for match in _DATE_TOKEN_PATTERN.finditer(combined):
                    if not match.start() < boundary < match.end():
                        continue
                    matched = characters[match.start() : match.end()]
                    atom_ids = frozenset(
                        atom_id
                        for char, atom_id in matched
                        if atom_id is not None and (char.isdigit() or char in "./-")
                    )
                    left_ids = atom_ids & ledger.atoms_for_cell(left_cell)
                    right_ids = atom_ids & ledger.atoms_for_cell(right_cell)
                    if not left_ids or not right_ids:
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
        cell for evidence in cross_cell_date_tokens(row, region, ledger) for cell in evidence.cells
    )


def parsed_cross_cell_conversion_evidence(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
    year_context: DiscoveredDateYearContext | None,
    transaction_date: date | None,
) -> tuple[tuple[date, CrossCellDateEvidence], ...]:
    if transaction_date is None:
        return ()
    parsed: list[tuple[date, CrossCellDateEvidence]] = []
    for evidence in cross_cell_date_tokens(row, region, ledger):
        value = _parse_date_near_anchor(evidence.text, year_context, transaction_date)
        if value is not None and abs((value - transaction_date).days) <= 31:
            parsed.append((value, evidence))
    return tuple(parsed)


def _parse_date_near_anchor(
    text: str,
    year_context: DiscoveredDateYearContext | None,
    anchor: date | None,
) -> date | None:
    parsed = parse_date(text, year_context)[0]
    if parsed is not None or anchor is None:
        return parsed
    if year_context is None:
        match = _DATE_PATTERN.fullmatch(normalize_text(text))
        if match is None:
            return None
        first, _, second, third = match.groups()
        candidates: set[date] = set()
        for year in range(anchor.year - 1, anchor.year + 2):
            if year % 100 == int(third):
                with suppress(ValueError):
                    candidates.add(date(year, int(second), int(first)))
            if year % 100 == int(first):
                with suppress(ValueError):
                    candidates.add(date(year, int(second), int(third)))
        nearby = tuple(
            candidate for candidate in candidates if abs((candidate - anchor).days) <= 31
        )
        return nearby[0] if len(nearby) == 1 else None
    local_years = tuple(
        year for year in range(anchor.year - 1, anchor.year + 2) if 1900 <= year <= 2100
    )
    local_context = year_context.model_copy(
        update={
            "year": None,
            "year_by_suffix": tuple(sorted((year % 100, year) for year in local_years)),
        }
    )
    parsed = parse_date(text, local_context)[0]
    if parsed is None or abs((parsed - anchor).days) > 31:
        return None
    return parsed


def matching_date_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    expected: date | None,
    year_context: DiscoveredDateYearContext | None,
) -> frozenset[int]:
    if expected is None:
        return frozenset()
    matching: set[int] = set()
    for candidate in ledger.fragmented_date_candidates(cell):
        if _parse_date_near_anchor(candidate.text, year_context, expected) == expected:
            matching.update(candidate.atom_ids)
    for atom_id in ledger.atoms_for_cell(cell):
        atom = ledger.atoms[atom_id]
        if _parse_date_near_anchor(atom.text, year_context, expected) == expected:
            matching.add(atom_id)
    if (
        not matching
        and not any(char.isalpha() for char in cell.text)
        and _parse_cell_date(cell, year_context)[0] == expected
    ):
        matching.update(ledger.atoms_for_cell(cell))
    return frozenset(matching)


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
        return ConversionDateExtraction(None, (), frozenset())

    candidate_cells = tuple(
        cell
        for column in region.table_schema.columns
        if column.role is ColumnRole.UNKNOWN
        or (column.role is ColumnRole.CONVERSION_DATE and existing_conversion_date is None)
        for cell in _cells_for_column(row, column)
    )
    candidates = tuple(
        (cell, candidate)
        for cell in candidate_cells
        for candidate in ledger.fragmented_date_candidates(cell)
    )
    raw_cross_cell_evidence = cross_cell_date_tokens(row, region, ledger)
    parsed_cross_cell_evidence = parsed_cross_cell_conversion_evidence(
        row,
        region,
        ledger,
        year_context,
        transaction_date,
    )
    if raw_cross_cell_evidence:
        if (
            not candidates
            and len(raw_cross_cell_evidence) == 1
            and len(parsed_cross_cell_evidence) == 1
        ):
            return ConversionDateExtraction(
                parsed_cross_cell_evidence[0][0],
                (),
                parsed_cross_cell_evidence[0][1].cells,
            )
        return ConversionDateExtraction(
            None,
            ("unparsed_conversion_date_candidate",),
            frozenset(),
        )
    if not candidates:
        has_date_cue = any(_has_fragmented_date_cue(cell) for cell in candidate_cells)
        return ConversionDateExtraction(
            None,
            ("unparsed_conversion_date_candidate",) if has_date_cue else (),
            frozenset(),
        )
    parsed = tuple(
        (
            cell,
            _parse_date_near_anchor(candidate.text, year_context, transaction_date),
        )
        for cell, candidate in candidates
    )
    if len(candidates) == 1 and parsed[0][1] is not None:
        return ConversionDateExtraction(parsed[0][1], (), frozenset((parsed[0][0],)))
    return ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
    )


__all__ = [
    "BoundaryDateCompletion",
    "ConversionDateExtraction",
    "CrossCellDateEvidence",
    "DateColumnKind",
    "DateExtraction",
    "adjacent_boundary_date_completion",
    "boundary_date_description_splits",
    "contains_date_cue",
    "cross_cell_date_source_cells",
    "cross_cell_date_tokens",
    "date_column_header_kind",
    "extract_conversion_date",
    "extract_dates",
    "has_proven_unanchored_short_date",
    "is_date_shaped",
    "matching_date_atom_ids",
    "parse_date",
    "parsed_cross_cell_conversion_evidence",
    "proven_unanchored_short_date_style",
    "structural_date_column_kinds",
]
