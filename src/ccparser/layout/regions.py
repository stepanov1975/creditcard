"""Semantic and structural transaction-table region detection."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence
from itertools import pairwise

from ccparser.evidence.models import BBox, Glyph, PageEvidence, Word
from ccparser.layout.columns import (
    _header_evidence_texts,
    _header_scores,
    explicit_billed_amount_column,
    infer_column_roles,
    is_date_shaped,
    is_installment_shaped,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, Row, TableRegion, TableSchema
from ccparser.layout.rows import cluster_rows
from ccparser.layout.text import (
    logical_text_for_bbox,
    logical_text_for_evidence,
    positioned_evidence_for_bbox,
)
from ccparser.money import is_currency_shaped, is_money_shaped

_TOTAL_MARKERS = frozenset(
    {
        "amount due",
        "billing total",
        "grand total",
        "statement total",
        "subtotal",
        "total",
        "total amount",
        "total billed",
        "סהכ",
        "סך הכל",
        "סךהכל",
        "סכום כולל",
        "סכוםכולל",
        "סכום לחיוב",
        "סכוםלחיוב",
    }
)
_SUBORDINATE_DETAIL_MARKERS = frozenset(
    {
        "commission",
        "conversion rate",
        "exchange rate",
        "fee",
        "surcharge",
        "עמלה",
        "המרה",
        "שער המרה",
    }
)
_POINT_COUNT_UNIT_MARKERS = frozenset({"point", "points", "נקודה", "נקודות"})
_POINT_COUNT_PATTERN = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:[,\s]\d{3})+)$")
_ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})
MAX_HEADER_PREAMBLE_ROWS = 4

type _PageRowKey = Row


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _width(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _union_bbox(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _normalized_marker(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    canonical: list[str] = []
    for index, char in enumerate(normalized):
        between_letters = (
            0 < index < len(normalized) - 1
            and normalized[index - 1].isalpha()
            and normalized[index + 1].isalpha()
        )
        if char in _ACRONYM_QUOTES and between_letters:
            continue
        canonical.append(char if char.isalnum() else " ")
    return " ".join("".join(canonical).split())


def _is_total_row(row: Row) -> bool:
    return any(
        normalized == marker
        or normalized.startswith(marker + " ")
        or (
            any("\u0590" <= char <= "\u05ff" for char in marker)
            and any(token.startswith(marker.replace(" ", "")) for token in normalized.split())
        )
        for cell in row.cells
        for normalized in (_normalized_marker(cell.text),)
        for marker in _TOTAL_MARKERS
    )


def _literal_header_role_count(row: Row) -> int:
    if len(row.cells) < 2:
        return 0
    schema = infer_column_roles(row.cells, ())
    return sum(
        column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
        for column in schema.columns
    )


def _transaction_shape_count(row: Row) -> int:
    return sum(
        is_date_shaped(cell.text)
        or is_installment_shaped(cell.text)
        or is_money_shaped(cell.text)
        or is_currency_shaped(cell.text)
        for cell in row.cells
    )


def _header_fragment_alignment(header: Row, fragment: Row) -> float:
    matched = 0
    for cell in fragment.cells:
        center = _center_x(cell.bbox)
        if any(
            candidate.bbox[0] - _width(candidate.bbox) * 0.2
            <= center
            <= candidate.bbox[2] + _width(candidate.bbox) * 0.2
            for candidate in header.cells
        ):
            matched += 1
    return matched / len(fragment.cells) if fragment.cells else 0.0


def _is_header_fragment(header: Row, fragment: Row) -> bool:
    if not fragment.cells or _is_total_row(fragment) or _transaction_shape_count(fragment):
        return False
    typical_height = statistics.median(
        _height(cell.bbox) for cell in (*header.cells, *fragment.cells)
    )
    gap = max(0.0, fragment.bbox[1] - header.bbox[3])
    return gap <= typical_height and _header_fragment_alignment(header, fragment) >= 0.6


def _merged_header_cell(cell: Cell, fragments: Sequence[Cell]) -> Cell:
    if not fragments:
        return cell
    ordered_fragments = tuple(sorted(fragments, key=lambda item: (item.bbox[1], item.bbox[0])))
    sources = (cell, *ordered_fragments)
    return cell.model_copy(
        update={
            "bbox": _union_bbox(tuple(source.bbox for source in sources)),
            "text": " ".join(source.text for source in sources),
            "glyphs": tuple(glyph for source in sources for glyph in source.glyphs),
            "words": tuple(word for source in sources for word in source.words),
            "confidence": statistics.mean(source.confidence for source in sources),
            "diagnostics": tuple(
                dict.fromkeys(
                    (
                        *(value for source in sources for value in source.diagnostics),
                        "merged_header_fragment",
                    )
                )
            ),
        }
    )


def _split_header_fragment(
    fragment: Cell,
    header_cells: Sequence[Cell],
) -> tuple[tuple[int, Cell], ...]:
    if (not fragment.words and not fragment.glyphs) or len(header_cells) < 2:
        return ()

    def nearest_header_index(bbox: BBox) -> int:
        center = _center_x(bbox)
        return min(
            range(len(header_cells)),
            key=lambda index: abs(center - _center_x(header_cells[index].bbox)),
        )

    words_by_header: dict[int, list[Word]] = {}
    for word in fragment.words:
        words_by_header.setdefault(nearest_header_index(word.bbox), []).append(word)

    glyphs_by_header: dict[int, list[Glyph]] = {}
    for glyph in fragment.glyphs:
        glyphs_by_header.setdefault(nearest_header_index(glyph.bbox), []).append(glyph)
    assigned_indexes = tuple(sorted(set(words_by_header) | set(glyphs_by_header)))
    if len(assigned_indexes) < 2:
        return ()

    split_fragments: list[tuple[int, Cell]] = []
    for index in assigned_indexes:
        words = words_by_header.get(index, [])
        glyphs = glyphs_by_header.get(index, [])
        evidence_boxes = tuple((*[word.bbox for word in words], *[glyph.bbox for glyph in glyphs]))
        confidence_values = tuple(
            (*[word.confidence for word in words], *[glyph.confidence for glyph in glyphs])
        )
        split_fragments.append(
            (
                index,
                Cell(
                    page_number=fragment.page_number,
                    bbox=_union_bbox(evidence_boxes),
                    text=logical_text_for_evidence(glyphs, words),
                    glyphs=tuple(glyphs),
                    words=tuple(words),
                    confidence=statistics.mean(confidence_values),
                    diagnostics=tuple(
                        dict.fromkeys((*fragment.diagnostics, "split_header_fragment"))
                    ),
                ),
            )
        )
    return tuple(split_fragments)


_AMOUNT_HEADER_ROLES = frozenset(
    {
        ColumnRole.AMOUNT,
        ColumnRole.AUXILIARY_AMOUNT,
        ColumnRole.ORIGINAL_AMOUNT,
    }
)


def _strong_amount_header_role(cell: Cell) -> ColumnRole | None:
    scores = _header_scores(_header_evidence_texts((cell,)))
    roles = tuple(
        role for role, score in scores.items() if role in _AMOUNT_HEADER_ROLES and score >= 0.82
    )
    return roles[0] if len(roles) == 1 else None


def _split_compound_header_cell(cell: Cell) -> tuple[Cell, Cell] | None:
    if len(cell.words) < 2:
        return None
    ordered_words = tuple(sorted(cell.words, key=lambda word: (word.bbox[0] + word.bbox[2]) / 2))
    width = _width(cell.bbox)
    if width <= 0:
        return None
    candidate_partitions = sorted(
        range(1, len(ordered_words)),
        key=lambda index: ordered_words[index].bbox[0] - ordered_words[index - 1].bbox[2],
        reverse=True,
    )
    for partition in candidate_partitions:
        gap = ordered_words[partition].bbox[0] - ordered_words[partition - 1].bbox[2]
        if gap / width < 0.05:
            continue
        left_words = ordered_words[:partition]
        right_words = ordered_words[partition:]
        boundary = (ordered_words[partition - 1].bbox[2] + ordered_words[partition].bbox[0]) / 2
        glyph_groups = (
            tuple(glyph for glyph in cell.glyphs if _center_x(glyph.bbox) < boundary),
            tuple(glyph for glyph in cell.glyphs if _center_x(glyph.bbox) >= boundary),
        )
        split_cells = []
        for words, glyphs in zip((left_words, right_words), glyph_groups, strict=True):
            evidence_boxes = tuple(
                (*[word.bbox for word in words], *[glyph.bbox for glyph in glyphs])
            )
            confidence_values = tuple(
                (
                    *[word.confidence for word in words],
                    *[glyph.confidence for glyph in glyphs],
                )
            )
            split_cells.append(
                Cell(
                    page_number=cell.page_number,
                    bbox=_union_bbox(evidence_boxes),
                    text=logical_text_for_evidence(glyphs, words),
                    glyphs=glyphs,
                    words=words,
                    confidence=statistics.mean(confidence_values),
                    diagnostics=tuple(
                        dict.fromkeys((*cell.diagnostics, "split_compound_header_cell"))
                    ),
                )
            )
        first, second = split_cells
        if (
            _strong_amount_header_role(first) is not None
            and _strong_amount_header_role(second) is not None
        ):
            return first, second
    return None


def _split_compound_header_row(row: Row) -> Row:
    cells = tuple(
        split_cell
        for cell in row.cells
        for split_cell in (_split_compound_header_cell(cell) or (cell,))
    )
    if cells == row.cells:
        return row
    direction = next(
        (
            diagnostic.removeprefix("dominant_direction:")
            for diagnostic in row.diagnostics
            if diagnostic.startswith("dominant_direction:")
        ),
        "ltr",
    )
    return row.model_copy(
        update={
            "cells": tuple(sorted(cells, key=lambda cell: cell.bbox[0], reverse=direction == "rtl"))
        }
    )


def _merge_header_rows(header: Row, fragments: Sequence[Row]) -> Row:
    fragment_cells = tuple(cell for row in fragments for cell in row.cells)
    assignments: dict[int, list[Cell]] = {index: [] for index in range(len(header.cells))}
    unmatched: list[Cell] = []
    for fragment_cell in fragment_cells:
        split_fragments = _split_header_fragment(fragment_cell, header.cells)
        if split_fragments:
            for index, split_fragment in split_fragments:
                assignments[index].append(split_fragment)
            continue
        center = _center_x(fragment_cell.bbox)
        candidates = tuple(
            (index, candidate)
            for index, candidate in enumerate(header.cells)
            if candidate.bbox[0] - _width(candidate.bbox) * 0.2
            <= center
            <= candidate.bbox[2] + _width(candidate.bbox) * 0.2
        )
        if not candidates:
            unmatched.append(fragment_cell)
            continue
        index, _ = min(
            candidates,
            key=lambda item: abs(center - _center_x(item[1].bbox)),
        )
        assignments[index].append(fragment_cell)
    cells = [
        _merged_header_cell(cell, assignments[index]) for index, cell in enumerate(header.cells)
    ]
    cells.extend(unmatched)
    direction = next(
        (
            diagnostic.removeprefix("dominant_direction:")
            for diagnostic in header.diagnostics
            if diagnostic.startswith("dominant_direction:")
        ),
        "ltr",
    )
    ordered_cells = tuple(sorted(cells, key=lambda cell: cell.bbox[0], reverse=direction == "rtl"))
    sources = (header, *fragments)
    return header.model_copy(
        update={
            "bbox": _union_bbox(tuple(row.bbox for row in sources)),
            "cells": ordered_cells,
            "words": tuple(word for row in sources for word in row.words),
            "confidence": statistics.mean(row.confidence for row in sources),
            "diagnostics": tuple(
                dict.fromkeys(
                    (
                        *(value for row in sources for value in row.diagnostics),
                        f"header_rows:{len(sources)}",
                    )
                )
            ),
        }
    )


def _merged_header_bands(rows: Sequence[Row]) -> tuple[Row, ...]:
    merged: list[Row] = []
    index = 0
    while index < len(rows):
        header = _split_compound_header_row(rows[index])
        fragments: list[Row] = []
        if _literal_header_role_count(header) >= 2:
            fragment_index = index + 1
            while fragment_index < len(rows) and len(fragments) < 2:
                candidate = rows[fragment_index]
                preceding = fragments[-1] if fragments else header
                if not _is_header_fragment(preceding, candidate):
                    break
                fragments.append(candidate)
                fragment_index += 1
        if fragments:
            merged.append(_merge_header_rows(header, fragments))
            index += len(fragments) + 1
        else:
            merged.append(header)
            index += 1
    return tuple(merged)


def _plausible_header(schema: TableSchema) -> bool:
    header_roles = {
        column.role
        for column in schema.columns
        if column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
    }
    amount_role = bool(header_roles & {ColumnRole.AMOUNT, ColumnRole.ORIGINAL_AMOUNT})
    context_role = bool(
        header_roles
        & {
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.CURRENCY,
            ColumnRole.BILLING_CURRENCY,
            ColumnRole.ORIGINAL_CURRENCY,
        }
    )
    return len(schema.columns) >= 2 and len(header_roles) >= 2 and amount_role and context_role


def _structural_gap(previous: Row, current: Row, observed: Sequence[Row]) -> bool:
    typical_height = statistics.median(_height(row.bbox) for row in observed)
    gap = max(0.0, current.bbox[1] - previous.bbox[3])
    return gap > typical_height * 2.5


def _row_alignment(row: Row, schema: TableSchema) -> float:
    matched_columns: set[int] = set()
    for cell in row.cells:
        center = _center_x(cell.bbox)
        candidates = tuple(
            column
            for column in schema.columns
            if column.bbox[0] - (column.bbox[2] - column.bbox[0]) * 0.15
            <= center
            <= column.bbox[2] + (column.bbox[2] - column.bbox[0]) * 0.15
        )
        if candidates:
            nearest = min(
                candidates,
                key=lambda column: abs(center - _center_x(column.bbox)),
            )
            matched_columns.add(nearest.index)
    return len(matched_columns) / len(schema.columns) if schema.columns else 0.0


def _minimum_row_alignment(schema: TableSchema) -> float:
    if not schema.columns:
        return 1.0
    minimum_columns = min(3, len(schema.columns))
    return max(minimum_columns / len(schema.columns), 0.5)


def _has_strong_single_row_evidence(
    rows: Sequence[Row],
    schema: TableSchema,
    stop_reason: str | None,
) -> bool:
    if len(rows) != 1 or stop_reason != "stopped_at_total":
        return False
    known_role_count = sum(column.role is not ColumnRole.UNKNOWN for column in schema.columns)
    row = rows[0]
    return (
        known_role_count >= 4
        and _transaction_shape_count(row) >= 3
        and _row_alignment(row, schema) >= max(_minimum_row_alignment(schema), 0.75)
    )


def _row_intersects_horizontal_band(row: Row, bbox: BBox) -> bool:
    return any(bbox[0] <= _center_x(cell.bbox) <= bbox[2] for cell in row.cells)


def _header_band_bounds(header: Row) -> tuple[tuple[float, float], ...]:
    cells = tuple(sorted(header.cells, key=lambda cell: _center_x(cell.bbox)))
    if not cells:
        return ()
    if len(cells) == 1:
        return ((header.bbox[0], header.bbox[2]),)
    centers = tuple(_center_x(cell.bbox) for cell in cells)
    boundaries = [centers[0] - (centers[1] - centers[0]) / 2]
    boundaries.extend((first + second) / 2 for first, second in pairwise(centers))
    boundaries.append(centers[-1] + (centers[-1] - centers[-2]) / 2)
    return tuple(pairwise(boundaries))


def _representative_vertical_band(row: Row) -> tuple[float, float]:
    if not row.cells:
        return row.bbox[1], row.bbox[3]
    center = statistics.median((cell.bbox[1] + cell.bbox[3]) / 2 for cell in row.cells)
    typical_height = statistics.median(_height(cell.bbox) for cell in row.cells)
    return center - typical_height / 2, center + typical_height / 2


def _project_row_to_header_bands(
    page_evidence: PageEvidence,
    row: Row,
    header: Row,
) -> Row:
    cells: list[Cell] = []
    top, bottom = _representative_vertical_band(row)
    for index, (left, right) in enumerate(_header_band_bounds(header)):
        band_bbox = (left, top, right, bottom)
        glyphs, words = positioned_evidence_for_bbox(page_evidence, band_bbox)
        text = logical_text_for_bbox(page_evidence, band_bbox)
        if not text:
            continue
        evidence_boxes = tuple((*[glyph.bbox for glyph in glyphs], *[word.bbox for word in words]))
        confidence_values = tuple(
            (*[glyph.confidence for glyph in glyphs], *[word.confidence for word in words])
        )
        cells.append(
            Cell(
                page_number=row.page_number,
                bbox=_union_bbox(evidence_boxes),
                text=text,
                glyphs=glyphs,
                words=words,
                confidence=(
                    statistics.mean(confidence_values) if confidence_values else row.confidence
                ),
                diagnostics=(f"projected_header_band:{index}",),
            )
        )
    direction = next(
        (
            diagnostic.removeprefix("dominant_direction:")
            for diagnostic in row.diagnostics
            if diagnostic.startswith("dominant_direction:")
        ),
        "ltr",
    )
    ordered_cells = tuple(sorted(cells, key=lambda cell: cell.bbox[0], reverse=direction == "rtl"))
    return row.model_copy(update={"cells": ordered_cells})


def _preview_rows(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    header_index: int,
) -> tuple[Row, ...]:
    preview: list[Row] = []
    preamble_count = 0
    previous = rows[header_index]
    for row in rows[header_index + 1 :]:
        if len(preview) >= 3:
            break
        if not _row_intersects_horizontal_band(row, rows[header_index].bbox):
            continue
        if _is_total_row(row) or _structural_gap(previous, row, (rows[header_index], *preview)):
            break
        if _literal_header_role_count(row) >= 2:
            break
        projected = _project_row_to_header_bands(page_evidence, row, rows[header_index])
        if projected.cells:
            if not preview and _transaction_shape_count(projected) == 0:
                if preamble_count >= MAX_HEADER_PREAMBLE_ROWS:
                    break
                preamble_count += 1
                previous = projected
                continue
            preview.append(projected)
            previous = projected
    return tuple(preview)


def _is_description_continuation(row: Row, previous: Row, schema: TableSchema) -> bool:
    if len(row.cells) != 1 or _is_total_row(row) or _literal_header_role_count(row) >= 2:
        return False
    description_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.DESCRIPTION
    )
    if len(description_columns) != 1:
        return False
    cell = row.cells[0]
    column = description_columns[0]
    center = _center_x(cell.bbox)
    tolerance = (column.bbox[2] - column.bbox[0]) * 0.15
    if not column.bbox[0] - tolerance <= center <= column.bbox[2] + tolerance:
        return False
    normalized_text = unicodedata.normalize("NFC", cell.text).strip()
    numeric_only = bool(normalized_text) and all(
        char.isdigit() or char.isspace() for char in normalized_text
    )
    if (
        is_date_shaped(normalized_text)
        or is_installment_shaped(normalized_text)
        or is_money_shaped(normalized_text)
        or is_currency_shaped(cell.text)
        or numeric_only
    ):
        return False
    minimum_alignment = max(2 / len(schema.columns), 0.6)
    if _row_alignment(previous, schema) < minimum_alignment:
        return False
    typical_height = statistics.median(
        _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def _has_subordinate_detail_marker(row: Row) -> bool:
    for cell in row.cells:
        normalized = _normalized_marker(cell.text)
        tokens = normalized.split()
        compact = "".join(tokens)
        for marker in _SUBORDINATE_DETAIL_MARKERS:
            marker_tokens = marker.split()
            if any(
                tokens[index : index + len(marker_tokens)] == marker_tokens
                for index in range(len(tokens))
            ):
                return True
            if (
                any("\u0590" <= char <= "\u05ff" for char in marker)
                and marker.replace(" ", "") in compact
            ):
                return True
    return False


def _is_marked_detail_continuation(row: Row, previous: Row, schema: TableSchema) -> bool:
    if (
        len(row.cells) < 2
        or _is_total_row(row)
        or _literal_header_role_count(row) >= 2
        or not _has_subordinate_detail_marker(row)
        or any(is_date_shaped(cell.text) for cell in row.cells)
    ):
        return False
    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    amount_column = (
        amount_columns[0]
        if len(amount_columns) == 1
        else explicit_billed_amount_column(schema.columns, schema.header_cells)
    )
    if amount_column is None:
        return False
    if any(
        amount_column.bbox[0] <= _center_x(cell.bbox) <= amount_column.bbox[2] for cell in row.cells
    ):
        return False
    secondary_amount_columns = tuple(
        column for column in amount_columns if column is not amount_column
    )
    if any(
        is_money_shaped(cell.text)
        for column in secondary_amount_columns
        for cell in row.cells
        if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
    ):
        return False
    minimum_alignment = max(2 / len(schema.columns), 0.6)
    if _row_alignment(row, schema) < minimum_alignment:
        return False
    typical_height = statistics.median(
        _height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def _has_valid_billed_amount(row: Row, schema: TableSchema) -> bool:
    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    amount_column = (
        amount_columns[0]
        if len(amount_columns) == 1
        else explicit_billed_amount_column(schema.columns, schema.header_cells)
    )
    if amount_column is None:
        return False
    amount_cells = tuple(
        cell
        for cell in row.cells
        if amount_column.bbox[0] <= _center_x(cell.bbox) <= amount_column.bbox[2]
    )
    secondary_amount_columns = tuple(
        column for column in amount_columns if column is not amount_column
    )
    secondary_cells = tuple(
        cell
        for column in secondary_amount_columns
        for cell in row.cells
        if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
    )
    return len(amount_cells) == 1 and is_money_shaped(amount_cells[0].text) and not secondary_cells


def _is_points_count_ledger_row(row: Row) -> bool:
    normalized_cells = tuple(_normalized_marker(cell.text) for cell in row.cells)
    has_exact_points_unit = any(
        normalized in _POINT_COUNT_UNIT_MARKERS for normalized in normalized_cells
    )
    money_cells = tuple(cell for cell in row.cells if is_money_shaped(cell.text))
    return (
        has_exact_points_unit
        and bool(money_cells)
        and all(
            _POINT_COUNT_PATTERN.fullmatch(cell.text.strip()) is not None for cell in money_cells
        )
    )


def _inherited_region_after_total(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    total_index: int,
    source_region: TableRegion,
    proven_total_overlay_keys: frozenset[_PageRowKey] = frozenset(),
) -> tuple[TableRegion | None, int]:
    """Resume only a strongly shaped section under real prior header evidence."""

    header = source_region.header
    schema = source_region.table_schema
    accepted: list[Row] = []
    regular_rows: list[Row] = []
    continuation_count = 0
    detail_continuation_count = 0
    ignored_outside_band_count = 0
    stop_reason: str | None = None
    stop_index = len(rows)
    previous = rows[total_index]
    detail_continuation_allowed = False
    for index, row in enumerate(rows[total_index + 1 :], start=total_index + 1):
        if not _row_intersects_horizontal_band(row, header.bbox):
            ignored_outside_band_count += 1
            continue
        if _is_total_row(row):
            if _page_row_key(row) in proven_total_overlay_keys:
                continue
            stop_reason = "stopped_at_total"
            stop_index = index
            break
        if _structural_gap(previous, row, (header, *accepted)):
            stop_reason = "stopped_at_structural_gap"
            stop_index = index
            break
        if _literal_header_role_count(row) >= 2:
            stop_reason = "stopped_at_new_header"
            stop_index = index
            break
        projected = _project_row_to_header_bands(page_evidence, row, header)
        if not projected.cells:
            ignored_outside_band_count += 1
            continue
        if regular_rows and _is_description_continuation(projected, previous, schema):
            accepted.append(projected)
            continuation_count += 1
            previous = projected
            continue
        if detail_continuation_allowed and _is_marked_detail_continuation(
            projected, previous, schema
        ):
            projected = projected.model_copy(
                update={
                    "diagnostics": tuple(
                        dict.fromkeys((*projected.diagnostics, "subordinate_detail_continuation"))
                    )
                }
            )
            accepted.append(projected)
            detail_continuation_count += 1
            detail_continuation_allowed = False
            previous = projected
            continue
        if (
            _is_points_count_ledger_row(projected)
            or _transaction_shape_count(projected) < 2
            or not _has_valid_billed_amount(projected, schema)
            or _row_alignment(projected, schema) < _minimum_row_alignment(schema)
        ):
            stop_reason = "stopped_at_structure_change"
            stop_index = index
            break
        accepted.append(projected)
        regular_rows.append(projected)
        detail_continuation_allowed = True
        previous = projected

    strong_single_row = _has_strong_single_row_evidence(regular_rows, schema, stop_reason)
    repeated_rows_with_total = len(regular_rows) >= 2 and stop_reason == "stopped_at_total"
    continued_to_page_end = (
        len(regular_rows) >= 2
        and stop_reason is None
        and accepted[-1].bbox[3] >= page_evidence.height * 0.75
    )
    if not (strong_single_row or repeated_rows_with_total or continued_to_page_end):
        return None, total_index + 1

    alignments = tuple(_row_alignment(row, schema) for row in regular_rows)
    billed_amount_column = proven_billed_amount_column(schema, accepted)
    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    diagnostics = [
        f"repeated_rows:{len(regular_rows)}",
        "inherited_schema_after_total",
        "row_only_region_bbox",
    ]
    if len(amount_columns) > 1 and billed_amount_column is not None:
        diagnostics.append("secondary_amount_bands_empty")
    if strong_single_row:
        diagnostics.append("single_row_strong_evidence")
    if continuation_count:
        diagnostics.append(f"continuation_rows:{continuation_count}")
    if detail_continuation_count:
        diagnostics.append(f"detail_continuation_rows:{detail_continuation_count}")
    if ignored_outside_band_count:
        diagnostics.append(f"ignored_outside_band_rows:{ignored_outside_band_count}")
    diagnostics.append("continued_to_page_end" if continued_to_page_end else "stopped_at_total")
    return (
        TableRegion(
            page_number=header.page_number,
            bbox=_union_bbox(tuple(row.bbox for row in accepted)),
            header=header,
            rows=tuple(accepted),
            table_schema=schema,
            confidence=statistics.mean(
                (
                    schema.confidence,
                    statistics.mean(row.confidence for row in accepted),
                    statistics.mean(alignments),
                )
            ),
            diagnostics=tuple(diagnostics),
        ),
        stop_index,
    )


def _candidate_schema(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    header_index: int,
) -> TableSchema:
    header = rows[header_index]
    preview = _preview_rows(page_evidence, rows, header_index)
    samples = tuple(cell for row in preview for cell in row.cells)
    return infer_column_roles(header.cells, samples)


def _detect_from_header(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    header_index: int,
) -> tuple[TableRegion | None, int]:
    header = rows[header_index]
    schema = _candidate_schema(page_evidence, rows, header_index)
    if not _plausible_header(schema):
        return None, header_index + 1

    accepted: list[Row] = []
    regular_rows: list[Row] = []
    continuation_count = 0
    detail_continuation_count = 0
    ignored_outside_band_count = 0
    ignored_preamble_count = 0
    stop_reason: str | None = None
    stop_index = len(rows)
    previous = header
    detail_continuation_allowed = False
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 1):
        if not _row_intersects_horizontal_band(row, header.bbox):
            ignored_outside_band_count += 1
            continue
        if _is_total_row(row):
            stop_reason = "stopped_at_total"
            stop_index = index
            break
        if _structural_gap(previous, row, (header, *accepted)):
            stop_reason = "stopped_at_structural_gap"
            stop_index = index
            break
        if _literal_header_role_count(row) >= 2:
            stop_reason = "stopped_at_new_header"
            stop_index = index
            break
        projected = _project_row_to_header_bands(page_evidence, row, header)
        if not projected.cells:
            ignored_outside_band_count += 1
            continue
        if not regular_rows and _transaction_shape_count(projected) == 0:
            if ignored_preamble_count >= MAX_HEADER_PREAMBLE_ROWS:
                stop_reason = "stopped_at_structure_change"
                stop_index = index
                break
            ignored_preamble_count += 1
            previous = projected
            continue
        if _is_description_continuation(projected, previous, schema):
            accepted.append(projected)
            continuation_count += 1
            previous = projected
            continue
        if detail_continuation_allowed and _is_marked_detail_continuation(
            projected, previous, schema
        ):
            projected = projected.model_copy(
                update={
                    "diagnostics": tuple(
                        dict.fromkeys((*projected.diagnostics, "subordinate_detail_continuation"))
                    )
                }
            )
            accepted.append(projected)
            detail_continuation_count += 1
            detail_continuation_allowed = False
            previous = projected
            continue
        if not _has_valid_billed_amount(projected, schema):
            stop_reason = "stopped_at_structure_change"
            stop_index = index
            break
        alignment = _row_alignment(projected, schema)
        minimum_alignment = _minimum_row_alignment(schema)
        if alignment < minimum_alignment:
            stop_reason = "stopped_at_structure_change"
            stop_index = index
            break
        accepted.append(projected)
        regular_rows.append(projected)
        detail_continuation_allowed = True
        previous = projected

    strong_single_row = _has_strong_single_row_evidence(regular_rows, schema, stop_reason)
    if len(regular_rows) < 2 and not strong_single_row:
        return None, header_index + 1

    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    billed_amount_column = proven_billed_amount_column(schema, accepted)

    sample_cells = tuple(cell for row in regular_rows for cell in row.cells)
    final_schema = infer_column_roles(header.cells, sample_cells)
    bbox = _union_bbox((header.bbox, *(row.bbox for row in accepted)))
    alignments = tuple(_row_alignment(row, final_schema) for row in regular_rows)
    diagnostics = [f"repeated_rows:{len(regular_rows)}"]
    if len(amount_columns) > 1 and billed_amount_column is not None:
        diagnostics.append("secondary_amount_bands_empty")
    if strong_single_row:
        diagnostics.append("single_row_strong_evidence")
    diagnostics.extend(value for value in header.diagnostics if value.startswith("header_rows:"))
    if continuation_count:
        diagnostics.append(f"continuation_rows:{continuation_count}")
    if detail_continuation_count:
        diagnostics.append(f"detail_continuation_rows:{detail_continuation_count}")
    if ignored_outside_band_count:
        diagnostics.append(f"ignored_outside_band_rows:{ignored_outside_band_count}")
    if ignored_preamble_count:
        diagnostics.append(f"ignored_preamble_rows:{ignored_preamble_count}")
    if stop_reason is not None:
        diagnostics.append(stop_reason)
    diagnostics.extend(f"schema:{diagnostic}" for diagnostic in final_schema.diagnostics)
    confidence = statistics.mean(
        (
            final_schema.confidence,
            statistics.mean(row.confidence for row in accepted),
            statistics.mean(alignments),
        )
    )
    region = TableRegion(
        page_number=header.page_number,
        bbox=bbox,
        header=header,
        rows=tuple(accepted),
        table_schema=final_schema,
        confidence=confidence,
        diagnostics=tuple(diagnostics),
    )
    return region, stop_index


def logical_rows(page_evidence: PageEvidence) -> tuple[Row, ...]:
    """Return every page row with glyph-corrected logical cell text and provenance."""

    geometric_rows = cluster_rows(page_evidence.words, page_evidence.page_number)
    logical_rows: list[Row] = []
    for row in geometric_rows:
        logical_cells = []
        for cell in row.cells:
            glyphs, words = positioned_evidence_for_bbox(page_evidence, cell.bbox)
            logical_cells.append(
                cell.model_copy(
                    update={
                        "text": logical_text_for_bbox(page_evidence, cell.bbox) or cell.text,
                        "glyphs": glyphs,
                        "words": words,
                    }
                )
            )
        row_glyphs = tuple(
            sorted(
                (
                    glyph
                    for glyph in page_evidence.glyphs
                    if 0.0 <= _center_x(glyph.bbox) <= page_evidence.width
                    and row.bbox[1] <= _center_y(glyph.bbox) <= row.bbox[3]
                ),
                key=lambda glyph: (
                    glyph.bbox[1],
                    glyph.bbox[0],
                    glyph.origin,
                    glyph.char,
                    glyph.font,
                    glyph.source,
                ),
            )
        )
        _, row_words = positioned_evidence_for_bbox(page_evidence, row.bbox)
        logical_rows.append(
            row.model_copy(
                update={
                    "cells": tuple(logical_cells),
                    "glyphs": row_glyphs,
                    "words": row_words,
                }
            )
        )
    return tuple(logical_rows)


def _page_row_key(row: Row) -> _PageRowKey:
    return row


def _detect_table_regions_from_rows(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    proven_total_overlay_keys: frozenset[_PageRowKey] = frozenset(),
) -> tuple[TableRegion, ...]:
    regions: list[TableRegion] = []
    index = 0
    while index < len(rows):
        region, next_index = _detect_from_header(page_evidence, rows, index)
        if region is None:
            index = max(next_index, index + 1)
            continue
        regions.append(region)
        inherited_source = region
        while "stopped_at_total" in inherited_source.diagnostics and next_index < len(rows):
            inherited, inherited_next_index = _inherited_region_after_total(
                page_evidence,
                rows,
                next_index,
                inherited_source,
                proven_total_overlay_keys,
            )
            if inherited is None:
                next_index += 1
                break
            regions.append(inherited)
            inherited_source = inherited
            next_index = inherited_next_index
        index = max(next_index, index + 1)
    return tuple(regions)


def detect_table_regions(page_evidence: PageEvidence) -> tuple[TableRegion, ...]:
    """Detect plausible repeated transaction tables without document identity rules."""

    return _detect_table_regions_from_rows(
        page_evidence,
        _merged_header_bands(logical_rows(page_evidence)),
    )
