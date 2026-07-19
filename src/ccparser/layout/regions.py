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
    contains_date_token,
    explicit_billed_amount_column,
    infer_column_roles,
    is_date_shaped,
    is_installment_shaped,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, Row, TableRegion, TableSchema
from ccparser.layout.rows import cluster_rows
from ccparser.layout.text import (
    canonical_words_for_layout,
    logical_text_for_bbox,
    logical_text_for_evidence,
    positioned_evidence_for_bbox,
)
from ccparser.money import currencies_in_text, is_currency_shaped, is_money_shaped

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
        "סה כ",
        "סה כ חיוב",
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
        "הערה",
        "המרה",
        "הומר",
        "שער המרה",
    }
)
_CARD_IDENTIFIER_DETAIL_MARKERS = frozenset(
    {"card id", "card identifier", "מזהה כרטיס"}
)
_POINT_COUNT_UNIT_MARKERS = frozenset({"point", "points", "נקודה", "נקודות"})
_TRANSACTION_CONTEXT_MARKERS = frozenset(
    {"transaction", "transactions", "עסקה", "העסקה", "עסקאות", "העסקאות"}
)
_POINT_COUNT_PATTERN = re.compile(r"^[+-]?(?:\d+|\d{1,3}(?:[,\s]\d{3})+)$")
_ACRONYM_QUOTES = frozenset({'"', "'", "\u2018", "\u2019", "\u201c", "\u201d", "\u05f3", "\u05f4"})
_ISOLATED_OCR_PUNCTUATION = frozenset({"|", "/", "\\", ":", ";", "~", "_"})
MAX_HEADER_PREAMBLE_ROWS = 4
MAX_AMBIGUOUS_LEADING_ROWS = 2
MAX_AMBIGUOUS_LEADING_PROOF_LOOKAHEAD = 4
MAX_OVERLAID_OCR_LOOKAHEAD_ROWS = 3
MAX_AUXILIARY_OUTSIDE_LOOKAHEAD_ROWS = 2
CARD_IDENTIFIER_MIN_DIGITS = 4
CARD_IDENTIFIER_MAX_DIGITS = 10
MAX_FOREIGN_CONVERSION_DETAIL_ROWS = 4
MIN_ISSUER_CONVERSION_DETAIL_ROWS = 4
MAX_ISSUER_CONVERSION_DETAIL_ROWS = 5

type _PageRowKey = Row


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _width(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _vertical_overlap_ratio(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    smaller_height = min(_height(first), _height(second))
    return overlap / smaller_height if smaller_height else 0.0


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


def _merge_adjacent_description_header_cells(row: Row) -> Row:
    cells: list[Cell] = []
    index = 0
    while index < len(row.cells):
        first = row.cells[index]
        if index + 1 >= len(row.cells):
            cells.append(first)
            break
        second = row.cells[index + 1]
        first_scores = _header_scores(_header_evidence_texts((first,)))
        second_scores = _header_scores(_header_evidence_texts((second,)))
        combined_text = _normalized_marker(f"{first.text} {second.text}")
        combined_scores = _header_scores((combined_text,))
        independent_semantics = any(
            score >= 0.82 for score in (*first_scores.values(), *second_scores.values())
        )
        if (
            combined_scores.get(ColumnRole.DESCRIPTION) != 1.0
            or independent_semantics
        ):
            cells.append(first)
            index += 1
            continue
        sources = (first, second)
        cells.append(
            Cell(
                page_number=row.page_number,
                bbox=_union_bbox(tuple(source.bbox for source in sources)),
                text=" ".join(f"{first.text} {second.text}".split()),
                glyphs=tuple(glyph for source in sources for glyph in source.glyphs),
                words=tuple(word for source in sources for word in source.words),
                confidence=statistics.mean(source.confidence for source in sources),
                diagnostics=tuple(
                    dict.fromkeys(
                        (
                            *(value for source in sources for value in source.diagnostics),
                            "merged_compound_description_header",
                        )
                    )
                ),
            )
        )
        index += 2
    merged = tuple(cells)
    return row if merged == row.cells else row.model_copy(update={"cells": merged})


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
        header = _merge_adjacent_description_header_cells(
            _split_compound_header_row(rows[index])
        )
        fragments: list[Row] = []
        skipped_overlay_rows: list[Row] = []
        if _literal_header_role_count(header) >= 2:
            fragment_index = index + 1
            while fragment_index < len(rows) and len(fragments) < 2:
                candidate = rows[fragment_index]
                preceding = fragments[-1] if fragments else header
                if _is_header_fragment(preceding, candidate):
                    fragments.append(candidate)
                    fragment_index += 1
                    continue
                typical_height = statistics.median(_height(cell.bbox) for cell in header.cells)
                separable_overlay = (
                    not skipped_overlay_rows
                    and not _row_intersects_horizontal_band(candidate, header.bbox)
                    and candidate.bbox[1] <= header.bbox[3] + typical_height
                )
                if separable_overlay:
                    skipped_overlay_rows.append(candidate)
                    fragment_index += 1
                    continue
                break
        if fragments:
            merged.append(
                _merge_adjacent_description_header_cells(
                    _merge_header_rows(header, fragments)
                )
            )
            merged.extend(skipped_overlay_rows)
            index = fragment_index
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
    transaction_context = any(
        token in _TRANSACTION_CONTEXT_MARKERS
        for cell in schema.header_cells
        for token in _normalized_marker(cell.text).split()
    )
    return (
        len(schema.columns) >= 2
        and len(header_roles) >= 2
        and amount_role
        and (context_role or transaction_context)
    )


def _structural_gap(previous: Row, current: Row, observed: Sequence[Row]) -> bool:
    typical_height = statistics.median(_height(row.bbox) for row in observed)
    gap = max(0.0, current.bbox[1] - previous.bbox[3])
    return gap > typical_height * 2.5


def _detail_rows_are_adjacent(previous: Row, current: Row) -> bool:
    typical_height = statistics.median(
        _height(candidate.bbox) for candidate in (*previous.cells, *current.cells)
    )
    gap = max(0.0, current.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


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
    explicit_billed_column = explicit_billed_amount_column(
        schema.columns,
        schema.header_cells,
    )
    original_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    has_embedded_date_proof = (
        _transaction_shape_count(row) >= 2
        and explicit_billed_column is not None
        and len(original_columns) == 1
        and any(
            contains_date_token(value)
            for value in (*[cell.text for cell in row.cells], *[word.text for word in row.words])
        )
    )
    return (
        known_role_count >= 4
        and (_transaction_shape_count(row) >= 3 or has_embedded_date_proof)
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


def _semantic_header_horizontal_bounds(header: Row) -> tuple[float, float] | None:
    semantic_cells = tuple(
        cell
        for cell in header.cells
        if any(
            score >= 0.82
            for score in _header_scores(_header_evidence_texts((cell,))).values()
        )
    )
    if len(semantic_cells) < 2:
        return None
    return min(cell.bbox[0] for cell in semantic_cells), max(
        cell.bbox[2] for cell in semantic_cells
    )


def _representative_vertical_band(row: Row) -> tuple[float, float]:
    if not row.cells:
        return row.bbox[1], row.bbox[3]
    center = statistics.median((cell.bbox[1] + cell.bbox[3]) / 2 for cell in row.cells)
    typical_height = statistics.median(_height(cell.bbox) for cell in row.cells)
    return center - typical_height / 2, center + typical_height / 2


def _without_isolated_ocr_money_punctuation(cell: Cell) -> Cell:
    if is_money_shaped(cell.text) or not cell.words:
        return cell
    removed = tuple(
        word
        for word in cell.words
        if word.source == "ocr"
        and unicodedata.normalize("NFC", word.text).strip() in _ISOLATED_OCR_PUNCTUATION
    )
    if not removed:
        return cell
    kept = tuple(word for word in cell.words if word not in removed)
    candidate = logical_text_for_evidence((), kept)
    if not candidate or not is_money_shaped(candidate):
        return cell
    return cell.model_copy(
        update={
            "text": candidate,
            "diagnostics": tuple(
                dict.fromkeys(
                    (*cell.diagnostics, f"ignored_isolated_ocr_punctuation:{len(removed)}")
                )
            ),
        }
    )


def _project_row_to_header_bands(
    page_evidence: PageEvidence,
    row: Row,
    header: Row,
) -> Row:
    del page_evidence
    cells: list[Cell] = []
    header_bands = _header_band_bounds(header)
    if not header_bands:
        return row.model_copy(update={"cells": ()})
    semantic_bounds = _semantic_header_horizontal_bounds(header)
    table_left = semantic_bounds[0] if semantic_bounds else header_bands[0][0]
    table_right = semantic_bounds[1] if semantic_bounds else header_bands[-1][1]
    table_cells = tuple(
        cell
        for cell in row.cells
        if header_bands and table_left <= _center_x(cell.bbox) <= table_right
    )
    vertical_source = row.model_copy(update={"cells": table_cells}) if table_cells else row
    top, bottom = _representative_vertical_band(vertical_source)
    cell_words = tuple(word for cell in row.cells for word in cell.words)
    cell_glyphs = tuple(glyph for cell in row.cells for glyph in cell.glyphs)
    row_words = (*row.words, *(word for word in cell_words if word not in row.words))
    row_glyphs = (*row.glyphs, *(glyph for glyph in cell_glyphs if glyph not in row.glyphs))
    for index, (left, right) in enumerate(header_bands):
        glyphs = tuple(
            glyph
            for glyph in row_glyphs
            if left <= _center_x(glyph.bbox) <= right
            and top <= _center_y(glyph.bbox) <= bottom
        )
        words = tuple(
            word
            for word in row_words
            if left <= _center_x(word.bbox) <= right and top <= _center_y(word.bbox) <= bottom
        )
        text = logical_text_for_evidence(glyphs, words)
        if not text:
            continue
        evidence_boxes = tuple((*[glyph.bbox for glyph in glyphs], *[word.bbox for word in words]))
        confidence_values = tuple(
            (*[glyph.confidence for glyph in glyphs], *[word.confidence for word in words])
        )
        cells.append(
            _without_isolated_ocr_money_punctuation(
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
    tolerance = (column.bbox[2] - column.bbox[0]) * 0.25
    if not column.bbox[0] - tolerance <= center <= column.bbox[2] + tolerance:
        return False
    normalized_text = unicodedata.normalize("NFC", cell.text).strip()
    if not any(char.isalnum() for char in normalized_text):
        return False
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
    minimum_alignment = _minimum_row_alignment(schema)
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


def _has_proper_hebrew_note_marker(row: Row) -> bool:
    return any(
        normalized == "הערה" or normalized.startswith("הערה ")
        for cell in row.cells
        for normalized in (_normalized_marker(cell.text),)
    )


def _is_marked_detail_continuation(row: Row, previous: Row, schema: TableSchema) -> bool:
    if (
        len(row.cells) < 2
        or _is_total_row(row)
        or _literal_header_role_count(row) >= 2
        or not _has_subordinate_detail_marker(row)
        or any(is_date_shaped(cell.text) for cell in row.cells)
    ):
        return False
    amount_column = proven_billed_amount_column(schema, (previous,))
    if amount_column is None:
        return False
    if any(
        amount_column.bbox[0] <= _center_x(cell.bbox) <= amount_column.bbox[2] for cell in row.cells
    ):
        return False
    minimum_alignment = (
        min(2 / len(schema.columns), 1.0)
        if _has_proper_hebrew_note_marker(row)
        else max(2 / len(schema.columns), 0.5)
    )
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


def _projection_preserves_positioned_evidence(source: Row, projected: Row) -> bool:
    projected_words = tuple(word for cell in projected.cells for word in cell.words)
    source_glyphs = tuple(glyph for glyph in source.glyphs if not glyph.char.isspace())
    projected_glyphs = tuple(
        glyph for cell in projected.cells for glyph in cell.glyphs if not glyph.char.isspace()
    )
    words_preserved = len(source.words) == len(projected_words) and all(
        source.words.count(word) == projected_words.count(word) for word in source.words
    )
    glyphs_preserved = len(source_glyphs) == len(projected_glyphs) and all(
        source_glyphs.count(glyph) == projected_glyphs.count(glyph) for glyph in source_glyphs
    )
    return words_preserved and glyphs_preserved


def _projection_preserves_table_band_evidence(
    source: Row,
    projected: Row,
    header: Row,
    schema: TableSchema,
) -> int | None:
    if source.page_number != header.page_number or projected.page_number != header.page_number:
        return None
    if _projection_preserves_positioned_evidence(source, projected):
        return 0
    semantic_bounds = _semantic_header_horizontal_bounds(header)
    table_x0 = (
        semantic_bounds[0]
        if semantic_bounds is not None
        else min(column.bbox[0] for column in schema.columns)
    )
    table_x1 = (
        semantic_bounds[1]
        if semantic_bounds is not None
        else max(column.bbox[2] for column in schema.columns)
    )
    inside_cells = tuple(
        cell for cell in source.cells if table_x0 <= _center_x(cell.bbox) <= table_x1
    )
    outside_cells = tuple(cell for cell in source.cells if cell not in inside_cells)
    if not inside_cells:
        return None
    source_words = tuple(word for cell in inside_cells for word in cell.words)
    projected_words = tuple(word for cell in projected.cells for word in cell.words)
    source_glyphs = tuple(
        glyph for cell in inside_cells for glyph in cell.glyphs if not glyph.char.isspace()
    )
    projected_glyphs = tuple(
        glyph for cell in projected.cells for glyph in cell.glyphs if not glyph.char.isspace()
    )
    words_preserved = len(source_words) == len(projected_words) and all(
        source_words.count(word) == projected_words.count(word) for word in source_words
    )
    glyphs_preserved = len(source_glyphs) == len(projected_glyphs) and all(
        source_glyphs.count(glyph) == projected_glyphs.count(glyph) for glyph in source_glyphs
    )
    if not words_preserved or not glyphs_preserved:
        return None

    all_cell_words = tuple(word for cell in source.cells for word in cell.words)
    if len(source.words) != len(all_cell_words) or any(
        source.words.count(word) != all_cell_words.count(word) for word in source.words
    ):
        return None
    inside_cell_glyphs = tuple(
        glyph for cell in inside_cells for glyph in cell.glyphs if not glyph.char.isspace()
    )
    unassigned_glyphs = list(
        glyph for glyph in source.glyphs if not glyph.char.isspace()
    )
    for glyph in inside_cell_glyphs:
        if glyph not in unassigned_glyphs:
            return None
        unassigned_glyphs.remove(glyph)
    outside_cell_glyphs = tuple(
        glyph for cell in outside_cells for glyph in cell.glyphs if not glyph.char.isspace()
    )
    for glyph in outside_cell_glyphs:
        if glyph in unassigned_glyphs:
            unassigned_glyphs.remove(glyph)
    has_separable_outside_glyph_run = bool(unassigned_glyphs) and (
        all(
            _center_x(glyph.bbox) < table_x0 or _center_x(glyph.bbox) > table_x1
            for glyph in unassigned_glyphs
        )
        and sum(char.isalpha() for glyph in unassigned_glyphs for char in glyph.char) >= 4
        and not any(char.isdigit() for glyph in unassigned_glyphs for char in glyph.char)
    )
    if unassigned_glyphs and not has_separable_outside_glyph_run:
        return None
    excluded_count = len(outside_cells) + int(has_separable_outside_glyph_run)
    return excluded_count if excluded_count else None


def _is_auxiliary_identifier_detail(row: Row) -> bool:
    if len(row.cells) != 1:
        return False
    text = unicodedata.normalize("NFC", row.cells[0].text)
    return (
        any(char.isalpha() for char in text)
        and any(char.isdigit() for char in text)
        and not is_money_shaped(text)
        and not is_date_shaped(text)
        and not is_currency_shaped(text)
    )


def _is_short_numeric_auxiliary_identifier_detail(row: Row) -> bool:
    if len(row.cells) != 1:
        return False
    compact = "".join(row.cells[0].text.split())
    return re.fullmatch(r"\d{4,10}", compact) is not None


def _has_canonical_card_identifier_lead(row: Row) -> bool:
    tokens = _normalized_marker(" ".join(cell.text for cell in row.cells)).split()
    return "מזהה" in tokens or any(
        tokens[index : index + 2] == ["card", "identifier"]
        for index in range(len(tokens))
    )


def _has_canonical_card_identifier_tail(row: Row) -> bool:
    tokens = _normalized_marker(" ".join(cell.text for cell in row.cells)).split()
    has_card_marker = "card" in tokens or any(token.startswith("כרטיס") for token in tokens)
    identifiers = set(
        re.findall(
            rf"(?<!\d)\d{{{CARD_IDENTIFIER_MIN_DIGITS},{CARD_IDENTIFIER_MAX_DIGITS}}}(?!\d)",
            " ".join(cell.text for cell in row.cells),
        )
    )
    return has_card_marker and len(identifiers) == 1


def _has_distinct_original_and_billed_currencies(row: Row, schema: TableSchema) -> bool:
    original_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    billed_column = proven_billed_amount_column(schema, (row,))
    if len(original_columns) != 1 or billed_column is None:
        return False
    original_cells = tuple(
        cell
        for cell in row.cells
        if original_columns[0].bbox[0] <= _center_x(cell.bbox) <= original_columns[0].bbox[2]
    )
    billed_cells = tuple(
        cell
        for cell in row.cells
        if billed_column.bbox[0] <= _center_x(cell.bbox) <= billed_column.bbox[2]
    )
    if (
        len(original_cells) != 1
        or len(billed_cells) != 1
        or not is_money_shaped(original_cells[0].text)
        or not is_money_shaped(billed_cells[0].text)
    ):
        return False
    original_currencies = currencies_in_text(original_cells[0].text)
    billed_currencies = currencies_in_text(billed_cells[0].text)
    return (
        len(original_currencies) == 1
        and len(billed_currencies) == 1
        and original_currencies != billed_currencies
    )


def _foreign_conversion_detail_block(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
    previous: Row,
    observed: Sequence[Row],
) -> tuple[tuple[Row, ...], int, int] | None:
    billed_column = proven_billed_amount_column(schema, (previous,))
    original_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    if (
        billed_column is None
        or len(original_columns) != 1
        or original_columns[0].index == billed_column.index
    ):
        return None
    has_distinct_currencies = _has_distinct_original_and_billed_currencies(previous, schema)
    maximum_detail_rows = (
        MAX_FOREIGN_CONVERSION_DETAIL_ROWS
        if has_distinct_currencies
        else MAX_ISSUER_CONVERSION_DETAIL_ROWS
    )
    details: list[Row] = []
    has_exact_marker = False
    skipped_outside_rows = 0
    preceding = previous
    for index in range(start_index, len(rows)):
        source = rows[index]
        if not _row_intersects_horizontal_band(source, header.bbox):
            if (
                _is_total_row(source)
                or _literal_header_role_count(source) >= 2
                or _structural_gap(preceding, source, (*observed, *details))
                or not _detail_rows_are_adjacent(preceding, source)
                or skipped_outside_rows >= MAX_AUXILIARY_OUTSIDE_LOOKAHEAD_ROWS
            ):
                return None
            skipped_outside_rows += 1
            continue
        if (
            _is_total_row(source)
            or _literal_header_role_count(source) >= 2
            or _structural_gap(preceding, source, (*observed, *details))
            or not _detail_rows_are_adjacent(preceding, source)
        ):
            return None
        projected = _project_row_to_header_bands(page_evidence, source, header)
        if not projected.cells:
            return None
        alignment = _row_alignment(projected, schema)
        if _has_valid_billed_amount(projected, schema) and alignment >= _minimum_row_alignment(
            schema
        ):
            if (
                details
                and has_exact_marker
                and (has_distinct_currencies or len(details) >= MIN_ISSUER_CONVERSION_DETAIL_ROWS)
            ):
                return tuple(details), index - 1, skipped_outside_rows
            return None
        outside_table_band_count = _projection_preserves_table_band_evidence(
            source,
            projected,
            header,
            schema,
        )
        if outside_table_band_count is None:
            return None
        billed_cells = tuple(
            cell
            for cell in projected.cells
            if billed_column.bbox[0] <= _center_x(cell.bbox) <= billed_column.bbox[2]
        )
        allowed_fifth_identifier = (
            has_distinct_currencies
            and len(details) == MAX_FOREIGN_CONVERSION_DETAIL_ROWS
            and (
                _is_auxiliary_identifier_detail(projected)
                or _has_canonical_card_identifier_detail(projected)
                or _has_canonical_card_identifier_detail(source)
            )
        )
        allowed_wrapped_identifier_lead = False
        if (
            has_distinct_currencies
            and has_exact_marker
            and len(details) == MAX_FOREIGN_CONVERSION_DETAIL_ROWS
            and index + 1 < len(rows)
        ):
            identifier_source = rows[index + 1]
            identifier = _project_row_to_header_bands(
                page_evidence,
                identifier_source,
                header,
            )
            allowed_wrapped_identifier_lead = (
                _detail_rows_are_adjacent(source, identifier_source)
                and _projection_preserves_table_band_evidence(
                    identifier_source,
                    identifier,
                    header,
                    schema,
                )
                is not None
                and (
                    _is_short_numeric_auxiliary_identifier_detail(identifier)
                    or (
                        _has_canonical_card_identifier_lead(projected)
                        and _has_canonical_card_identifier_tail(identifier)
                    )
                )
            )
        allowed_wrapped_identifier_tail = (
            has_distinct_currencies
            and len(details) == MAX_FOREIGN_CONVERSION_DETAIL_ROWS + 1
            and (
                _is_short_numeric_auxiliary_identifier_detail(projected)
                or (
                    _has_canonical_card_identifier_lead(details[-1])
                    and _has_canonical_card_identifier_tail(projected)
                )
            )
        )
        if (
            (
                len(details) >= maximum_detail_rows
                and not allowed_fifth_identifier
                and not allowed_wrapped_identifier_lead
                and not allowed_wrapped_identifier_tail
            )
            or billed_cells
            or any(is_date_shaped(cell.text) for cell in projected.cells)
            or _transaction_shape_count(projected) > 1
            or alignment <= 0
        ):
            return None
        has_exact_marker = has_exact_marker or _has_subordinate_detail_marker(projected)
        projected = projected.model_copy(
            update={
                "diagnostics": tuple(
                    dict.fromkeys(
                        (
                            *projected.diagnostics,
                            "subordinate_detail_continuation",
                            "foreign_conversion_detail_block",
                            *(
                                (f"ignored_outside_table_band_cells:{outside_table_band_count}",)
                                if outside_table_band_count
                                else ()
                            ),
                        )
                    )
                )
            }
        )
        details.append(projected)
        preceding = projected
    return None


def _bounded_auxiliary_fragment(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
    previous: Row,
) -> Row | None:
    if (
        start_index + 1 >= len(rows)
        or not _has_valid_billed_amount(previous, schema)
        or _row_alignment(previous, schema) < _minimum_row_alignment(schema)
    ):
        return None
    source = rows[start_index]
    following_index = start_index + 1
    skipped_outside_rows = 0
    while (
        following_index < len(rows)
        and not _row_intersects_horizontal_band(rows[following_index], header.bbox)
    ):
        candidate = rows[following_index]
        if (
            _is_total_row(candidate)
            or _literal_header_role_count(candidate) >= 2
            or skipped_outside_rows >= MAX_AUXILIARY_OUTSIDE_LOOKAHEAD_ROWS
        ):
            return None
        skipped_outside_rows += 1
        following_index += 1
    if following_index >= len(rows):
        return None
    following_source = rows[following_index]
    if (
        not _row_intersects_horizontal_band(source, header.bbox)
        or _is_total_row(source)
        or _literal_header_role_count(source) >= 2
        or not _detail_rows_are_adjacent(previous, source)
        or not _row_intersects_horizontal_band(following_source, header.bbox)
        or _is_total_row(following_source)
        or _literal_header_role_count(following_source) >= 2
        or not _detail_rows_are_adjacent(source, following_source)
    ):
        return None
    projected = _project_row_to_header_bands(page_evidence, source, header)
    outside_table_band_count = _projection_preserves_table_band_evidence(
        source,
        projected,
        header,
        schema,
    )
    if (
        not 1 <= len(projected.cells) <= 2
        or not (source.words or any(not glyph.char.isspace() for glyph in source.glyphs))
        or outside_table_band_count is None
        or _transaction_shape_count(projected) != 0
        or _has_subordinate_detail_marker(projected)
    ):
        return None
    matching_columns = tuple(
        tuple(
            column
            for column in schema.columns
            if column.bbox[0] <= _center_x(cell.bbox) <= column.bbox[2]
        )
        for cell in projected.cells
    )
    if (
        any(len(columns) != 1 for columns in matching_columns)
        or any(
            columns[0].role not in {ColumnRole.UNKNOWN, ColumnRole.DESCRIPTION}
            for columns in matching_columns
        )
        or not any(columns[0].role is ColumnRole.UNKNOWN for columns in matching_columns)
    ):
        return None
    following = _project_row_to_header_bands(page_evidence, following_source, header)
    if (
        not following.cells
        or not _has_valid_billed_amount(following, schema)
        or _row_alignment(following, schema) < _minimum_row_alignment(schema)
        or _transaction_shape_count(following) < 2
    ):
        return None
    return projected.model_copy(
        update={
            "diagnostics": tuple(
                dict.fromkeys(
                    (
                        *projected.diagnostics,
                        "subordinate_auxiliary_continuation",
                        *(
                            (f"ignored_outside_table_band_cells:{outside_table_band_count}",)
                            if outside_table_band_count
                            else ()
                        ),
                    )
                )
            )
        }
    )


def _has_canonical_card_identifier_detail(row: Row) -> bool:
    normalized = _normalized_marker(" ".join(cell.text for cell in row.cells))
    tokens = normalized.split()
    compact = "".join(tokens)
    has_marker = any(
        any(
            tokens[index : index + len(marker.split())] == marker.split()
            for index in range(len(tokens))
        )
        or (
            any("\u0590" <= char <= "\u05ff" for char in marker)
            and marker.replace(" ", "") in compact
        )
        for marker in _CARD_IDENTIFIER_DETAIL_MARKERS
    )
    if not has_marker:
        return False
    identifiers = set(
        re.findall(
            rf"(?<!\d)\d{{{CARD_IDENTIFIER_MIN_DIGITS},{CARD_IDENTIFIER_MAX_DIGITS}}}(?!\d)",
            " ".join(cell.text for cell in row.cells),
        )
    )
    return len(identifiers) == 1


def _bounded_card_identifier_detail_block(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
    previous: Row,
) -> tuple[tuple[Row, Row], int] | None:
    if (
        start_index + 2 >= len(rows)
        or not _has_valid_billed_amount(previous, schema)
        or _row_alignment(previous, schema) < _minimum_row_alignment(schema)
    ):
        return None
    sources = (rows[start_index], rows[start_index + 1])
    following_source = rows[start_index + 2]
    if (
        any(not _row_intersects_horizontal_band(source, header.bbox) for source in sources)
        or not _row_intersects_horizontal_band(following_source, header.bbox)
        or any(_is_total_row(source) for source in (*sources, following_source))
        or any(_literal_header_role_count(source) >= 2 for source in (*sources, following_source))
        or not _detail_rows_are_adjacent(previous, sources[0])
        or not _detail_rows_are_adjacent(sources[0], sources[1])
        or not _detail_rows_are_adjacent(sources[1], following_source)
    ):
        return None
    details = tuple(
        _project_row_to_header_bands(page_evidence, source, header) for source in sources
    )
    excluded_counts = tuple(
        _projection_preserves_table_band_evidence(source, detail, header, schema)
        for source, detail in zip(sources, details, strict=True)
    )
    if (
        any(not detail.cells for detail in details)
        or any(count is None for count in excluded_counts)
        or any(any(is_date_shaped(cell.text) for cell in detail.cells) for detail in details)
        or _transaction_shape_count(details[0]) != 0
        or _transaction_shape_count(details[1]) > 1
        or any(_has_valid_billed_amount(detail, schema) for detail in details)
        or any(_row_alignment(detail, schema) <= 0 for detail in details)
        or not _has_canonical_card_identifier_detail(details[1])
    ):
        return None
    following = _project_row_to_header_bands(page_evidence, following_source, header)
    if (
        not following.cells
        or not _has_valid_billed_amount(following, schema)
        or _row_alignment(following, schema) < _minimum_row_alignment(schema)
        or _transaction_shape_count(following) < 2
    ):
        return None
    marked_details = tuple(
        detail.model_copy(
            update={
                "diagnostics": tuple(
                    dict.fromkeys(
                        (
                            *detail.diagnostics,
                            "subordinate_detail_continuation",
                            "bounded_card_identifier_detail_block",
                            *(
                                (f"ignored_outside_table_band_cells:{excluded_count}",)
                                if excluded_count
                                else ()
                            ),
                        )
                    )
                )
            }
        )
        for detail, excluded_count in zip(details, excluded_counts, strict=True)
    )
    return (marked_details[0], marked_details[1]), start_index + 1


def _bounded_hebrew_note_detail(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
    previous: Row,
) -> Row | None:
    if start_index + 1 >= len(rows):
        return None
    billed_column = proven_billed_amount_column(schema, (previous,))
    original_columns = tuple(
        column for column in schema.columns if column.role is ColumnRole.ORIGINAL_AMOUNT
    )
    if (
        billed_column is None
        or len(original_columns) != 1
        or original_columns[0].index == billed_column.index
    ):
        return None
    source = rows[start_index]
    following_source = rows[start_index + 1]
    if (
        _is_total_row(source)
        or _literal_header_role_count(source) >= 2
        or not _detail_rows_are_adjacent(previous, source)
        or not _row_intersects_horizontal_band(following_source, header.bbox)
        or _is_total_row(following_source)
        or _literal_header_role_count(following_source) >= 2
        or not _detail_rows_are_adjacent(source, following_source)
    ):
        return None
    projected = _project_row_to_header_bands(page_evidence, source, header)
    if (
        not projected.cells
        or not _has_proper_hebrew_note_marker(projected)
        or any(is_date_shaped(cell.text) for cell in projected.cells)
        or _transaction_shape_count(projected) > 1
        or _row_alignment(projected, schema) <= 0
        or _projection_preserves_table_band_evidence(source, projected, header, schema) is None
        or any(
            billed_column.bbox[0] <= _center_x(cell.bbox) <= billed_column.bbox[2]
            for cell in projected.cells
        )
    ):
        return None
    following = _project_row_to_header_bands(page_evidence, following_source, header)
    if (
        not following.cells
        or not _has_valid_billed_amount(following, schema)
        or _row_alignment(following, schema) < _minimum_row_alignment(schema)
    ):
        return None
    return projected.model_copy(
        update={
            "diagnostics": tuple(
                dict.fromkeys(
                    (
                        *projected.diagnostics,
                        "subordinate_detail_continuation",
                        "bounded_hebrew_note_detail",
                    )
                )
            )
        }
    )


def _bounded_overlaid_ocr_amount_artifact(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
) -> int | None:
    """Return the last noise-row index for a tall OCR artifact over a proven next row."""

    source = rows[start_index]
    amount_columns = tuple(column for column in schema.columns if column.role is ColumnRole.AMOUNT)
    if (
        len(source.cells) != 1
        or len(amount_columns) != 1
        or _is_total_row(source)
        or _literal_header_role_count(source) >= 2
        or _transaction_shape_count(source) != 0
        or not (
            amount_columns[0].bbox[0]
            <= _center_x(source.cells[0].bbox)
            <= amount_columns[0].bbox[2]
        )
    ):
        return None

    stop = min(len(rows), start_index + MAX_OVERLAID_OCR_LOOKAHEAD_ROWS + 1)
    for following_index in range(start_index + 1, stop):
        following_source = rows[following_index]
        if _is_total_row(following_source) or _literal_header_role_count(following_source) >= 2:
            return None
        following = _project_row_to_header_bands(page_evidence, following_source, header)
        if (
            following.cells
            and _has_valid_billed_amount(following, schema)
            and _transaction_shape_count(following) >= 2
            and _row_alignment(following, schema) >= _minimum_row_alignment(schema)
        ):
            return (
                following_index - 1
                if _vertical_overlap_ratio(source.bbox, following_source.bbox) >= 0.5
                else None
            )
        if any(char.isalnum() for cell in following_source.cells for char in cell.text):
            return None
    return None


def _ambiguous_billed_amount_row(row: Row, schema: TableSchema) -> bool:
    billed_column = explicit_billed_amount_column(schema.columns, schema.header_cells)
    if billed_column is None:
        amount_columns = tuple(
            column for column in schema.columns if column.role is ColumnRole.AMOUNT
        )
        billed_column = amount_columns[0] if len(amount_columns) == 1 else None
    if billed_column is None:
        return False
    billed_cells = tuple(
        cell
        for cell in row.cells
        if billed_column.bbox[0] <= _center_x(cell.bbox) <= billed_column.bbox[2]
    )
    transaction_shape_count = _transaction_shape_count(row)
    has_embedded_date_proof = transaction_shape_count >= 1 and any(
        contains_date_token(value)
        for value in (*[cell.text for cell in row.cells], *[word.text for word in row.words])
    )
    return (
        len(billed_cells) == 1
        and any(char.isdigit() for char in billed_cells[0].text)
        and not is_money_shaped(billed_cells[0].text)
        and (transaction_shape_count >= 2 or has_embedded_date_proof)
        and _row_alignment(row, schema) >= _minimum_row_alignment(schema)
    )


def _leading_ambiguity_is_proven_by_repetition(
    page_evidence: PageEvidence,
    rows: Sequence[Row],
    start_index: int,
    header: Row,
    schema: TableSchema,
) -> bool:
    projected = _project_row_to_header_bands(page_evidence, rows[start_index], header)
    if not _ambiguous_billed_amount_row(projected, schema):
        return False
    ambiguous_count = 1
    consecutive_valid_count = 0
    stop = min(len(rows), start_index + MAX_AMBIGUOUS_LEADING_PROOF_LOOKAHEAD + 1)
    for index in range(start_index + 1, stop):
        source = rows[index]
        if (
            not _row_intersects_horizontal_band(source, header.bbox)
            or _is_total_row(source)
            or _literal_header_role_count(source) >= 2
        ):
            return False
        candidate = _project_row_to_header_bands(page_evidence, source, header)
        if (
            _has_valid_billed_amount(candidate, schema)
            and _transaction_shape_count(candidate) >= 2
            and _row_alignment(candidate, schema) >= _minimum_row_alignment(schema)
        ):
            consecutive_valid_count += 1
            if consecutive_valid_count >= 2:
                return True
            continue
        if consecutive_valid_count or not _ambiguous_billed_amount_row(candidate, schema):
            return False
        ambiguous_count += 1
        if ambiguous_count > MAX_AMBIGUOUS_LEADING_ROWS:
            return False
    return False


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
        if _structural_gap(previous, row, (header, *accepted)):
            stop_reason = "stopped_at_structural_gap"
            stop_index = index
            break
        if _literal_header_role_count(row) >= 2:
            stop_reason = "stopped_at_new_header"
            stop_index = index
            break
        if _is_total_row(row):
            if _page_row_key(row) in proven_total_overlay_keys:
                continue
            stop_reason = "stopped_at_total"
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
        return (
            None,
            stop_index if stop_reason == "stopped_at_total" else total_index,
        )

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
    auxiliary_continuation_count = 0
    ignored_overlaid_ocr_count = 0
    ambiguous_leading_count = 0
    ignored_outside_band_count = 0
    ignored_preamble_count = 0
    stop_reason: str | None = None
    stop_index = len(rows)
    consumed_through = header_index
    previous = header
    detail_continuation_allowed = False
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 1):
        if index <= consumed_through:
            continue
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
        if detail_continuation_allowed:
            card_identifier_block = _bounded_card_identifier_detail_block(
                page_evidence,
                rows,
                index,
                header,
                schema,
                previous,
            )
            if card_identifier_block is not None:
                card_details, consumed_through = card_identifier_block
                accepted.extend(card_details)
                detail_continuation_count += len(card_details)
                detail_continuation_allowed = False
                previous = card_details[-1]
                continue
        if detail_continuation_allowed:
            detail_block = _foreign_conversion_detail_block(
                page_evidence,
                rows,
                index,
                header,
                schema,
                previous,
                (header, *accepted),
            )
            if detail_block is not None:
                details, consumed_through, skipped_outside_rows = detail_block
                accepted.extend(details)
                detail_continuation_count += len(details)
                ignored_outside_band_count += skipped_outside_rows
                detail_continuation_allowed = False
                previous = details[-1]
                continue
        if detail_continuation_allowed:
            note_detail = _bounded_hebrew_note_detail(
                page_evidence,
                rows,
                index,
                header,
                schema,
                previous,
            )
            if note_detail is not None:
                accepted.append(note_detail)
                detail_continuation_count += 1
                detail_continuation_allowed = False
                previous = note_detail
                continue
        if (
            detail_continuation_allowed
            and len(projected.cells) == 1
            and _has_subordinate_detail_marker(projected)
        ):
            stop_reason = "stopped_at_structure_change"
            stop_index = index
            break
        if detail_continuation_allowed:
            auxiliary_fragment = _bounded_auxiliary_fragment(
                page_evidence,
                rows,
                index,
                header,
                schema,
                previous,
            )
            if auxiliary_fragment is not None:
                accepted.append(auxiliary_fragment)
                auxiliary_continuation_count += 1
                detail_continuation_allowed = False
                previous = auxiliary_fragment
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
            overlaid_through = _bounded_overlaid_ocr_amount_artifact(
                page_evidence,
                rows,
                index,
                header,
                schema,
            )
            if overlaid_through is not None:
                consumed_through = overlaid_through
                ignored_overlaid_ocr_count += 1
                continue
        if not regular_rows and _leading_ambiguity_is_proven_by_repetition(
            page_evidence,
            rows,
            index,
            header,
            schema,
        ):
            projected = projected.model_copy(
                update={
                    "diagnostics": tuple(
                        dict.fromkeys((*projected.diagnostics, "ambiguous_leading_transaction"))
                    )
                }
            )
            accepted.append(projected)
            ambiguous_leading_count += 1
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
    if auxiliary_continuation_count:
        diagnostics.append(f"auxiliary_continuation_rows:{auxiliary_continuation_count}")
    if ignored_outside_band_count:
        diagnostics.append(f"ignored_outside_band_rows:{ignored_outside_band_count}")
    if ignored_preamble_count:
        diagnostics.append(f"ignored_preamble_rows:{ignored_preamble_count}")
    if ignored_overlaid_ocr_count:
        diagnostics.append(f"ignored_overlaid_ocr_rows:{ignored_overlaid_ocr_count}")
    if ambiguous_leading_count:
        diagnostics.append(f"ambiguous_leading_rows:{ambiguous_leading_count}")
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

    logical_page = page_evidence.model_copy(
        update={"words": canonical_words_for_layout(page_evidence)}
    )
    geometric_rows = cluster_rows(logical_page.words, logical_page.page_number)
    glyphs_by_row: list[list[Glyph]] = [[] for _ in geometric_rows]
    positioned_glyphs = tuple(
        sorted(
            (
                glyph
                for glyph in logical_page.glyphs
                if 0.0 <= _center_x(glyph.bbox) <= logical_page.width
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
    for glyph in positioned_glyphs:
        center_y = _center_y(glyph.bbox)
        candidate_indices = tuple(
            index
            for index, row in enumerate(geometric_rows)
            if row.bbox[1] <= center_y <= row.bbox[3]
        )
        if candidate_indices:
            owner = min(
                candidate_indices,
                key=lambda index: (
                    abs(center_y - _center_y(geometric_rows[index].bbox)),
                    index,
                ),
            )
            glyphs_by_row[owner].append(glyph)
    logical_rows: list[Row] = []
    for row_index, row in enumerate(geometric_rows):
        logical_cells = []
        for cell in row.cells:
            glyphs, words = positioned_evidence_for_bbox(logical_page, cell.bbox)
            logical_cells.append(
                cell.model_copy(
                    update={
                        "text": logical_text_for_bbox(logical_page, cell.bbox) or cell.text,
                        "glyphs": glyphs,
                        "words": words,
                    }
                )
            )
        row_glyphs = tuple(glyphs_by_row[row_index])
        logical_rows.append(
            row.model_copy(
                update={
                    "cells": tuple(logical_cells),
                    "glyphs": row_glyphs,
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
                if (
                    inherited_next_index > next_index
                    and inherited_next_index < len(rows)
                    and _is_total_row(rows[inherited_next_index])
                ):
                    next_index = inherited_next_index
                    continue
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
