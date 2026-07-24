"""Lossless table-wide separation of repeated OCR pictogram bands."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ccparser.evidence.models import Glyph, Word
from ccparser.geometry import BBox, vertical_overlap
from ccparser.geometry import bbox_center_x as _center_x
from ccparser.geometry import bbox_height as _height
from ccparser.geometry import bbox_width as _width
from ccparser.geometry import union_bbox as _union_bbox
from ccparser.layout.columns import cells_in_column, isolated_date_token
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.layout.row_tags import is_structural_continuation
from ccparser.layout.rows import _ordered_cells_from_stored_direction
from ccparser.layout.text import logical_text_for_evidence
from ccparser.money import canonical_currency, is_currency_shaped, is_money_shaped
from ccparser.text_tokens import normalize_text

OCR_MARKER_BAND_DIAGNOSTIC = "stable_headerless_ocr_marker_band"

_MINIMUM_SUPPORTING_ROWS = 3
_MINIMUM_SUPPORT_FRACTION_DENOMINATOR = 3
_MINIMUM_CONFUSED_OCR_SUPPORTING_ROWS = 9
_MINIMUM_CONFUSED_OCR_LABELS = 6
_MINIMUM_CONFUSED_OCR_PROFILES = 5
_MAXIMUM_CONFUSED_OCR_LABEL_LENGTH = 2
_MAXIMUM_LOW_OCR_CONFIDENCE = 0.5
_MINIMUM_OCR_CONFIDENCE_SPREAD = 0.4
_MAXIMUM_CENTER_DEVIATION_HEIGHT_RATIO = 0.5
_MINIMUM_MARKER_DATE_VERTICAL_OVERLAP = 0.75
_NUMERIC_LABEL_PATTERN = re.compile(r"^[+\N{MINUS SIGN}-]?\d[\d\s.,]*$")
_PERCENTAGE_LABEL_PATTERN = re.compile(r"^[+\N{MINUS SIGN}-]?(?:\d+(?:[.,]\d+)?)\s*%$")
_VERTICAL_LAYOUT_MARKER_NAME = re.compile(r"(?:FULLWIDTH )?VERTICAL (?:LINE|BAR)")
_SEMANTIC_VERTICAL_MARKER_NAME_PARTS = frozenset(
    {
        "COMPARISON",
        "DIVIDES",
        "DIVISIBILITY",
        "EQUALITY",
        "OPERATOR",
        "PARALLEL",
        "RELATION",
    }
)


class _MarkerSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class _RecognitionProfile(StrEnum):
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    MONEY = "money"
    NUMERIC = "numeric"
    ALPHABETIC = "alphabetic"
    MIXED = "mixed"
    SYMBOL = "symbol"


@dataclass(frozen=True, slots=True)
class _MarkerDateCellEvidence:
    row: Row
    source: Cell
    date_word: Word
    marker_words: tuple[Word, ...]
    marker_bbox: BBox
    date_bbox: BBox
    label: str


@dataclass(frozen=True, slots=True)
class _CellSplit:
    row: Row
    source: Cell
    date_word: Word
    marker_words: tuple[Word, ...]
    marker_bbox: BBox
    date_bbox: BBox
    side: _MarkerSide
    label: str


@dataclass(frozen=True, slots=True)
class _BandSplit:
    column: ColumnSpec
    cells: tuple[_CellSplit, ...]
    boundary: float
    side: _MarkerSide
    eligible_row_count: int


def is_ocr_marker_band_column(column: ColumnSpec) -> bool:
    """Return whether layout proved a headerless ancillary OCR marker band."""

    return column.role is ColumnRole.UNKNOWN and OCR_MARKER_BAND_DIAGNOSTIC in column.diagnostics


def is_proven_ocr_marker_cell(
    cell: Cell,
    column: ColumnSpec,
    *,
    row: Row | None = None,
) -> bool:
    """Return whether ``cell`` is an individually proven occupant of a marker band."""

    return is_ocr_marker_band_column(column) and (
        cell in column.source_cells
        or (row is not None and _matches_existing_cross_profile_marker_column(cell, column, row))
    )


def _is_exact_date_word(word: Word) -> bool:
    text = unicodedata.normalize("NFC", word.text).strip()
    return isolated_date_token(text) == text


def _recognition_profile(text: str) -> _RecognitionProfile:
    normalized = normalize_text(text)
    if _PERCENTAGE_LABEL_PATTERN.fullmatch(normalized) is not None:
        return _RecognitionProfile.PERCENTAGE
    if canonical_currency(normalized) is not None or is_currency_shaped(normalized):
        return _RecognitionProfile.CURRENCY
    if is_money_shaped(normalized):
        return _RecognitionProfile.MONEY
    if _NUMERIC_LABEL_PATTERN.fullmatch(normalized) is not None:
        return _RecognitionProfile.NUMERIC
    has_letter = any(char.isalpha() for char in normalized)
    has_digit = any(char.isdigit() for char in normalized)
    if has_letter and not has_digit:
        return _RecognitionProfile.ALPHABETIC
    if has_letter or has_digit:
        return _RecognitionProfile.MIXED
    return _RecognitionProfile.SYMBOL


def is_visible_vertical_layout_marker(visible_run: str) -> bool:
    """Return whether a prepared visible run is a non-semantic vertical marker."""

    if not 1 <= len(visible_run) <= 2 or len(set(visible_run)) != 1:
        return False
    char = visible_run[0]
    name = unicodedata.name(char, "")
    return (
        unicodedata.category(char) == "Sm"
        and _VERTICAL_LAYOUT_MARKER_NAME.fullmatch(name) is not None
        and not any(part in name for part in _SEMANTIC_VERTICAL_MARKER_NAME_PARTS)
    )


def _is_nonmaterial_layout_marker_text(text: str) -> bool:
    visible_run = "".join(char for char in unicodedata.normalize("NFC", text) if not char.isspace())
    return is_visible_vertical_layout_marker(visible_run)


def _marker_date_cell_evidence(row: Row, cell: Cell) -> _MarkerDateCellEvidence | None:
    date_words = tuple(word for word in cell.words if _is_exact_date_word(word))
    if len(date_words) != 1:
        return None
    date_word = date_words[0]
    marker_words = tuple(word for word in cell.words if word is not date_word)
    if not marker_words or any(word.source != "ocr" for word in marker_words):
        return None
    marker_bbox = _union_bbox(word.bbox for word in marker_words)
    if vertical_overlap(marker_bbox, date_word.bbox) < _MINIMUM_MARKER_DATE_VERTICAL_OVERLAP:
        return None
    label = logical_text_for_evidence((), marker_words)
    if not normalize_text(label) or isolated_date_token(label) is not None:
        return None
    return _MarkerDateCellEvidence(
        row=row,
        source=cell,
        date_word=date_word,
        marker_words=marker_words,
        marker_bbox=marker_bbox,
        date_bbox=date_word.bbox,
        label=label,
    )


def _strict_cell_split(evidence: _MarkerDateCellEvidence) -> _CellSplit | None:
    if any(
        max(evidence.marker_bbox[0], glyph.bbox[0]) < min(evidence.marker_bbox[2], glyph.bbox[2])
        and max(evidence.marker_bbox[1], glyph.bbox[1])
        < min(evidence.marker_bbox[3], glyph.bbox[3])
        for glyph in evidence.source.glyphs
        if not glyph.char.isspace()
    ):
        return None
    if evidence.marker_bbox[2] < evidence.date_bbox[0]:
        side = _MarkerSide.LEFT
    elif evidence.date_bbox[2] < evidence.marker_bbox[0]:
        side = _MarkerSide.RIGHT
    else:
        return None
    return _CellSplit(
        row=evidence.row,
        source=evidence.source,
        date_word=evidence.date_word,
        marker_words=evidence.marker_words,
        marker_bbox=evidence.marker_bbox,
        date_bbox=evidence.date_bbox,
        side=side,
        label=evidence.label,
    )


def _cell_split(row: Row, cell: Cell) -> _CellSplit | None:
    evidence = _marker_date_cell_evidence(row, cell)
    return _strict_cell_split(evidence) if evidence is not None else None


def _has_multiple_positioned_dates(cell: Cell) -> bool:
    return sum(_is_exact_date_word(word) for word in cell.words) > 1


def _cross_profile_recognition_support_is_proven(
    labels: Sequence[str],
    confidences: Sequence[float],
) -> bool:
    label_counts = Counter(normalize_text(label) for label in labels)
    compact_labels = tuple("".join(normalize_text(label).split()) for label in labels)
    profiles = {_recognition_profile(label) for label in labels}
    return (
        len(labels) >= _MINIMUM_CONFUSED_OCR_SUPPORTING_ROWS
        and len(label_counts) >= _MINIMUM_CONFUSED_OCR_LABELS
        and max(label_counts.values()) * 2 < len(labels)
        and len(profiles) >= _MINIMUM_CONFUSED_OCR_PROFILES
        and all(1 <= len(label) <= _MAXIMUM_CONFUSED_OCR_LABEL_LENGTH for label in compact_labels)
        and bool(confidences)
        and min(confidences) <= _MAXIMUM_LOW_OCR_CONFIDENCE
        and max(confidences) - min(confidences) >= _MINIMUM_OCR_CONFIDENCE_SPREAD
    )


def _recognitions_are_heterogeneous(cells: Sequence[_CellSplit]) -> bool:
    label_counts = Counter(normalize_text(cell.label) for cell in cells)
    count = len(cells)
    labels_are_nondominant = len(label_counts) >= 3 and max(label_counts.values()) * 2 < count
    if not labels_are_nondominant:
        return False
    if all(_is_nonmaterial_layout_marker_text(cell.label) for cell in cells):
        return True
    confidences = tuple(word.confidence for cell in cells for word in cell.marker_words)
    return all(
        cell.date_word.source == "ocr"
        and len(cell.marker_words) == 1
        and cell.marker_words[0].source == "ocr"
        for cell in cells
    ) and _cross_profile_recognition_support_is_proven(
        tuple(cell.label for cell in cells),
        confidences,
    )


def _stable_marker_centers(cells: Sequence[_CellSplit]) -> bool:
    centers = tuple(_center_x(cell.marker_bbox) for cell in cells)
    typical_height = statistics.median(_height(cell.marker_bbox) for cell in cells)
    center = statistics.median(centers)
    return typical_height > 0 and max(abs(value - center) for value in centers) <= (
        typical_height * _MAXIMUM_CENTER_DEVIATION_HEIGHT_RATIO
    )


def _marker_interval(column: ColumnSpec, boundary: float, side: _MarkerSide) -> BBox:
    if side is _MarkerSide.LEFT:
        return (column.bbox[0], column.bbox[1], boundary, column.bbox[3])
    return (boundary, column.bbox[1], column.bbox[2], column.bbox[3])


def _header_evidence_boxes(region: TableRegion) -> tuple[BBox, ...]:
    boxes: list[BBox] = []
    for cell in region.table_schema.header_cells:
        positioned = tuple(
            (*[word.bbox for word in cell.words], *[glyph.bbox for glyph in cell.glyphs])
        )
        boxes.extend(positioned or (cell.bbox,))
    return tuple(boxes)


def _headerless_marker_interval(region: TableRegion, interval: BBox) -> bool:
    return not any(
        interval[0] <= _center_x(box) <= interval[2] for box in _header_evidence_boxes(region)
    )


def _marker_occupies_explicit_peer_column(
    region: TableRegion,
    date_column: ColumnSpec,
    cells: Sequence[_CellSplit],
) -> bool:
    return any(
        peer is not date_column
        and peer.role is not ColumnRole.UNKNOWN
        and peer.bbox[0] <= _center_x(cell.marker_bbox) <= peer.bbox[2]
        for peer in region.table_schema.columns
        for cell in cells
    )


def _detect_band(region: TableRegion, column: ColumnSpec) -> _BandSplit | None:
    eligible_rows = tuple(row for row in region.rows if not is_structural_continuation(row))
    date_cells = tuple(cell for row in eligible_rows for cell in cells_in_column(row.cells, column))
    if any(_has_multiple_positioned_dates(cell) for cell in date_cells):
        return None
    candidates = tuple(
        split
        for row in eligible_rows
        if len(cells_in_column(row.cells, column)) == 1
        if (split := _cell_split(row, cells_in_column(row.cells, column)[0])) is not None
    )
    if (
        len(candidates) < _MINIMUM_SUPPORTING_ROWS
        or len(candidates) * _MINIMUM_SUPPORT_FRACTION_DENOMINATOR < len(eligible_rows)
        or len({candidate.side for candidate in candidates}) != 1
        or not _stable_marker_centers(candidates)
        or not _recognitions_are_heterogeneous(candidates)
    ):
        return None
    side = candidates[0].side
    if side is _MarkerSide.LEFT:
        marker_edge = max(candidate.marker_bbox[2] for candidate in candidates)
        date_edge = min(candidate.date_bbox[0] for candidate in candidates)
    else:
        marker_edge = min(candidate.marker_bbox[0] for candidate in candidates)
        date_edge = max(candidate.date_bbox[2] for candidate in candidates)
    if (side is _MarkerSide.LEFT and marker_edge >= date_edge) or (
        side is _MarkerSide.RIGHT and date_edge >= marker_edge
    ):
        return None
    boundary = (marker_edge + date_edge) / 2
    interval = _marker_interval(column, boundary, side)
    if not _headerless_marker_interval(region, interval) or _marker_occupies_explicit_peer_column(
        region, column, candidates
    ):
        return None
    return _BandSplit(
        column=column,
        cells=candidates,
        boundary=boundary,
        side=side,
        eligible_row_count=len(eligible_rows),
    )


def _band_uses_cross_profile_ocr_confusion(band: _BandSplit) -> bool:
    return not all(_is_nonmaterial_layout_marker_text(cell.label) for cell in band.cells)


def _band_occupant_split(
    band: _BandSplit,
    row: Row,
    cell: Cell,
) -> _CellSplit | None:
    evidence = _marker_date_cell_evidence(row, cell)
    if evidence is None:
        return None
    direct = _strict_cell_split(evidence)
    if direct is not None and direct.side is band.side:
        return direct
    marker_center = _center_x(evidence.marker_bbox)
    date_center = _center_x(evidence.date_bbox)
    marker_is_left = marker_center < band.boundary
    date_is_left = date_center < band.boundary
    if marker_is_left == date_is_left or marker_is_left != (band.side is _MarkerSide.LEFT):
        return None
    support_centers = tuple(_center_x(candidate.marker_bbox) for candidate in band.cells)
    typical_height = statistics.median(_height(candidate.marker_bbox) for candidate in band.cells)
    if typical_height <= 0 or abs(marker_center - statistics.median(support_centers)) > (
        typical_height * _MAXIMUM_CENTER_DEVIATION_HEIGHT_RATIO
    ):
        return None
    normalized_label = normalize_text(evidence.label)
    if _band_uses_cross_profile_ocr_confusion(band):
        compact = "".join(normalized_label.split())
        support_profiles = {_recognition_profile(candidate.label) for candidate in band.cells}
        if (
            evidence.date_word.source != "ocr"
            or len(evidence.marker_words) != 1
            or not 1 <= len(compact) <= _MAXIMUM_CONFUSED_OCR_LABEL_LENGTH
            or _recognition_profile(evidence.label) not in support_profiles
        ):
            return None
    elif not _is_nonmaterial_layout_marker_text(evidence.label):
        return None
    return _CellSplit(
        row=evidence.row,
        source=evidence.source,
        date_word=evidence.date_word,
        marker_words=evidence.marker_words,
        marker_bbox=evidence.marker_bbox,
        date_bbox=evidence.date_bbox,
        side=band.side,
        label=evidence.label,
    )


def proven_ocr_marker_word_partition(
    region: TableRegion,
    date_column: ColumnSpec,
    cell: Cell,
) -> tuple[Word, tuple[Word, ...]] | None:
    """Return an exact date/marker Word partition proved across the whole table."""

    band = _detect_band(region, date_column)
    if band is None:
        return None
    identity_rows = tuple(row for row in region.rows if any(item is cell for item in row.cells))
    candidate_rows = identity_rows or tuple(row for row in region.rows if cell in row.cells)
    if len(candidate_rows) != 1:
        return None
    row = candidate_rows[0]
    assigned = cells_in_column(row.cells, date_column)
    if len(assigned) != 1 or assigned[0] != cell:
        return None
    split = _band_occupant_split(band, row, cell)
    return (split.date_word, split.marker_words) if split is not None else None


def _glyphs_on_side(
    glyphs: Iterable[Glyph],
    boundary: float,
    side: _MarkerSide,
) -> tuple[Glyph, ...]:
    return tuple(
        glyph
        for glyph in glyphs
        if (_center_x(glyph.bbox) < boundary) == (side is _MarkerSide.LEFT)
    )


def _split_cell(cell: _CellSplit, boundary: float) -> tuple[Cell, Cell]:
    marker_glyphs = _glyphs_on_side(cell.source.glyphs, boundary, cell.side)
    date_glyphs = tuple(glyph for glyph in cell.source.glyphs if glyph not in marker_glyphs)

    def build(words: tuple[Word, ...], glyphs: tuple[Glyph, ...]) -> Cell:
        boxes = tuple((*[word.bbox for word in words], *[glyph.bbox for glyph in glyphs]))
        confidence_values = tuple(
            (*[word.confidence for word in words], *[glyph.confidence for glyph in glyphs])
        )
        return Cell(
            page_number=cell.source.page_number,
            bbox=_union_bbox(boxes),
            text=logical_text_for_evidence(glyphs, words),
            glyphs=glyphs,
            words=words,
            confidence=statistics.mean(confidence_values),
            diagnostics=tuple(
                dict.fromkeys((*cell.source.diagnostics, "split_repeated_ocr_marker_band"))
            ),
        )

    marker = build(cell.marker_words, marker_glyphs)
    date_cell = build((cell.date_word,), date_glyphs)
    return marker, date_cell


def _replacement_cells(
    region: TableRegion,
    band: _BandSplit,
) -> tuple[tuple[Cell, Cell, Cell], ...]:
    occupants = tuple(
        split
        for row in region.rows
        if not is_structural_continuation(row)
        if len(cells_in_column(row.cells, band.column)) == 1
        if (
            split := _band_occupant_split(
                band,
                row,
                cells_in_column(row.cells, band.column)[0],
            )
        )
        is not None
    )
    return tuple((split.source, *_split_cell(split, band.boundary)) for split in occupants)


def _replacement_for(
    cell: Cell,
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> tuple[Cell, Cell] | None:
    return next(
        ((marker, date_cell) for source, marker, date_cell in replacements if source == cell),
        None,
    )


def _split_row(
    row: Row,
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> Row:
    cells = tuple(
        replacement_cell
        for cell in row.cells
        for replacement_cell in (_replacement_for(cell, replacements) or (cell,))
    )
    if cells == row.cells:
        return row
    return row.model_copy(
        update={
            "cells": _ordered_cells_from_stored_direction(row, cells),
            "diagnostics": tuple(
                dict.fromkeys((*row.diagnostics, "split_repeated_ocr_marker_band"))
            ),
        }
    )


def _replace_sample_cells(
    cells: Sequence[Cell],
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> tuple[Cell, ...]:
    return tuple(
        replacement_cell
        for cell in cells
        for replacement_cell in (_replacement_for(cell, replacements) or (cell,))
    )


def _relative_x(value: float, schema: TableSchema) -> float:
    width = _width(schema.bbox)
    return (value - schema.bbox[0]) / width if width else 0.0


def _date_source_cells(
    band: _BandSplit,
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> tuple[Cell, ...]:
    sources: list[Cell] = []
    for cell in band.column.source_cells:
        replacement = _replacement_for(cell, replacements)
        if replacement is not None:
            sources.append(replacement[1])
            continue
        center = _center_x(cell.bbox)
        on_marker_side = (band.side is _MarkerSide.LEFT and center < band.boundary) or (
            band.side is _MarkerSide.RIGHT and center > band.boundary
        )
        if not on_marker_side:
            sources.append(cell)
    return tuple(sources)


def _bbox_is_horizontally_contained(inner: BBox, outer: BBox) -> bool:
    return outer[0] <= inner[0] and inner[2] <= outer[2]


def _bbox_is_contained(inner: BBox, outer: BBox) -> bool:
    return (
        _bbox_is_horizontally_contained(inner, outer)
        and outer[1] <= inner[1]
        and inner[3] <= outer[3]
    )


def _is_vertically_aligned_with_row_peer(
    cell: Cell,
    row: Row,
    marker_interval: BBox,
) -> bool:
    positioned: tuple[Word | Glyph, ...] = (*cell.words, *cell.glyphs)
    return bool(positioned) and any(
        peer is not cell
        and not _bbox_is_horizontally_contained(peer.bbox, marker_interval)
        and vertical_overlap(cell.bbox, peer.bbox) >= _MINIMUM_MARKER_DATE_VERTICAL_OVERLAP
        and all(
            vertical_overlap(item.bbox, peer.bbox) >= _MINIMUM_MARKER_DATE_VERTICAL_OVERLAP
            for item in positioned
        )
        for peer in row.cells
    )


def _value_is_within_support(value: float, support: Sequence[float]) -> bool:
    return bool(support) and min(support) <= value <= max(support)


def _bbox_dimensions_match_support(candidate: BBox, support: Sequence[BBox]) -> bool:
    return _value_is_within_support(
        _width(candidate),
        tuple(_width(box) for box in support),
    ) and _value_is_within_support(
        _height(candidate),
        tuple(_height(box) for box in support),
    )


def _bbox_center_matches_support(candidate: BBox, support: Sequence[BBox]) -> bool:
    if not support:
        return False
    typical_height = statistics.median(_height(box) for box in support)
    center = statistics.median(_center_x(box) for box in support)
    return (
        typical_height > 0
        and max(abs(_center_x(box) - center) for box in (*support, candidate))
        <= typical_height * _MAXIMUM_CENTER_DEVIATION_HEIGHT_RATIO
    )


def _matches_repeated_cross_profile_recognition(
    cell: Cell,
    labels: Sequence[str],
    confidences: Sequence[float],
    cell_boxes: Sequence[BBox],
    word_boxes: Sequence[BBox],
) -> bool:
    if not (
        len(labels) == len(confidences) == len(cell_boxes) == len(word_boxes)
        and _cross_profile_recognition_support_is_proven(labels, confidences)
    ):
        return False
    compact = "".join(normalize_text(cell.text).split())
    normalized_label = normalize_text(cell.text)
    same_label_indexes = tuple(
        index for index, label in enumerate(labels) if normalize_text(label) == normalized_label
    )
    if len(same_label_indexes) < 2:
        return False
    same_label_cell_boxes = tuple(cell_boxes[index] for index in same_label_indexes)
    same_label_word_boxes = tuple(word_boxes[index] for index in same_label_indexes)
    return (
        1 <= len(compact) <= _MAXIMUM_CONFUSED_OCR_LABEL_LENGTH
        and _value_is_within_support(cell.words[0].confidence, confidences)
        and _bbox_dimensions_match_support(cell.bbox, same_label_cell_boxes)
        and _bbox_dimensions_match_support(cell.words[0].bbox, same_label_word_boxes)
        and _bbox_center_matches_support(cell.bbox, cell_boxes)
        and _bbox_center_matches_support(cell.words[0].bbox, word_boxes)
    )


def _has_composite_financial_evidence(cell: Cell) -> bool:
    if len(cell.words) + len(cell.glyphs) <= 1:
        return False
    source_texts = tuple(word.text for word in cell.words)
    combined = logical_text_for_evidence(cell.glyphs, cell.words)
    return any(
        _recognition_profile(text)
        in {
            _RecognitionProfile.CURRENCY,
            _RecognitionProfile.PERCENTAGE,
            _RecognitionProfile.MONEY,
            _RecognitionProfile.NUMERIC,
        }
        for text in (*source_texts, combined)
    )


def _matches_existing_cross_profile_marker_column(
    cell: Cell,
    column: ColumnSpec,
    row: Row,
) -> bool:
    if (
        len(cell.words) != 1
        or cell.glyphs
        or cell.words[0].source != "ocr"
        or normalize_text(cell.text) != normalize_text(cell.words[0].text)
        or not _bbox_is_contained(cell.bbox, column.bbox)
        or not _bbox_is_contained(cell.words[0].bbox, column.bbox)
        or not _is_vertically_aligned_with_row_peer(cell, row, column.bbox)
        or _has_composite_financial_evidence(cell)
    ):
        return False
    support = column.source_cells
    if not support or any(
        len(source.words) != 1
        or source.glyphs
        or source.words[0].source != "ocr"
        or normalize_text(source.text) != normalize_text(source.words[0].text)
        or not _bbox_is_contained(source.bbox, column.bbox)
        or not _bbox_is_contained(source.words[0].bbox, column.bbox)
        for source in support
    ):
        return False
    labels = tuple(source.text for source in support)
    confidences = tuple(source.words[0].confidence for source in support)
    return _matches_repeated_cross_profile_recognition(
        cell,
        labels,
        confidences,
        tuple(source.bbox for source in support),
        tuple(source.words[0].bbox for source in support),
    )


def _matches_cross_profile_ocr_band(cell: Cell, band: _BandSplit) -> bool:
    if (
        not _band_uses_cross_profile_ocr_confusion(band)
        or len(cell.words) != 1
        or cell.glyphs
        or cell.words[0].source != "ocr"
        or normalize_text(cell.text) != normalize_text(cell.words[0].text)
        or any(len(candidate.marker_words) != 1 for candidate in band.cells)
    ):
        return False
    return _matches_repeated_cross_profile_recognition(
        cell,
        tuple(candidate.label for candidate in band.cells),
        tuple(candidate.marker_words[0].confidence for candidate in band.cells),
        tuple(candidate.marker_bbox for candidate in band.cells),
        tuple(candidate.marker_words[0].bbox for candidate in band.cells),
    )


def _is_independently_proven_marker_source(
    cell: Cell,
    interval: BBox,
    band: _BandSplit,
    row: Row,
) -> bool:
    positioned: tuple[Word | Glyph, ...] = (*cell.words, *cell.glyphs)
    return (
        bool(positioned)
        and _bbox_is_contained(cell.bbox, interval)
        and all(_bbox_is_contained(item.bbox, interval) for item in positioned)
        and _is_vertically_aligned_with_row_peer(cell, row, interval)
        and all(item.source == "ocr" for item in positioned)
        and not _has_composite_financial_evidence(cell)
        and (
            _is_nonmaterial_layout_marker_text(logical_text_for_evidence(cell.glyphs, cell.words))
            or _matches_cross_profile_ocr_band(cell, band)
        )
    )


def _standalone_marker_sources(
    region: TableRegion,
    band: _BandSplit,
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> tuple[Cell, ...]:
    replaced_sources = frozenset(source for source, _, _ in replacements)
    interval = _marker_interval(band.column, band.boundary, band.side)
    return tuple(
        cell
        for row in region.rows
        if not is_structural_continuation(row)
        for cell in row.cells
        if cell not in replaced_sources
        if _is_independently_proven_marker_source(cell, interval, band, row)
    )


def _split_columns(
    region: TableRegion,
    band: _BandSplit,
    replacements: Sequence[tuple[Cell, Cell, Cell]],
) -> tuple[ColumnSpec, ...]:
    schema = region.table_schema
    marker_sources = (
        *(marker for _, marker, _ in replacements),
        *_standalone_marker_sources(region, band, replacements),
    )
    date_sources = _date_source_cells(band, replacements)
    if band.side is _MarkerSide.LEFT:
        marker_bbox = (
            band.column.bbox[0],
            band.column.bbox[1],
            band.boundary,
            band.column.bbox[3],
        )
        date_bbox = (
            band.boundary,
            band.column.bbox[1],
            band.column.bbox[2],
            band.column.bbox[3],
        )
    else:
        date_bbox = (
            band.column.bbox[0],
            band.column.bbox[1],
            band.boundary,
            band.column.bbox[3],
        )
        marker_bbox = (
            band.boundary,
            band.column.bbox[1],
            band.column.bbox[2],
            band.column.bbox[3],
        )
    date_column = band.column.model_copy(
        update={
            "bbox": date_bbox,
            "relative_x0": _relative_x(date_bbox[0], schema),
            "relative_x1": _relative_x(date_bbox[2], schema),
            "source_cells": date_sources,
            "diagnostics": tuple(
                dict.fromkeys((*band.column.diagnostics, "separated_ocr_marker_band"))
            ),
        }
    )
    support = len(band.cells) / band.eligible_row_count
    marker_column = ColumnSpec(
        index=band.column.index,
        page_number=band.column.page_number,
        bbox=marker_bbox,
        relative_x0=_relative_x(marker_bbox[0], schema),
        relative_x1=_relative_x(marker_bbox[2], schema),
        role=ColumnRole.UNKNOWN,
        source_cells=marker_sources,
        confidence=support,
        diagnostics=(
            OCR_MARKER_BAND_DIAGNOSTIC,
            "headerless_column",
            "ocr_only_source",
            "heterogeneous_recognition_labels",
            f"repeated_row_support:{len(band.cells)}/{band.eligible_row_count}",
        ),
    )
    expanded: list[ColumnSpec] = []
    for column in schema.columns:
        if column is band.column:
            expanded.extend(
                (marker_column, date_column)
                if band.side is _MarkerSide.LEFT
                else (date_column, marker_column)
            )
        else:
            expanded.append(column)
    return tuple(
        column.model_copy(update={"index": index}) for index, column in enumerate(expanded)
    )


def _schema_diagnostics(columns: Sequence[ColumnSpec], schema: TableSchema) -> tuple[str, ...]:
    diagnostics = tuple(
        diagnostic
        for diagnostic in schema.diagnostics
        if not diagnostic.startswith("ambiguous_columns:")
    )
    ambiguous_indexes = tuple(
        column.index
        for column in columns
        if column.role is ColumnRole.UNKNOWN and not is_ocr_marker_band_column(column)
    )
    return tuple(
        dict.fromkeys(
            (
                *diagnostics,
                *(
                    ("ambiguous_columns:" + ",".join(map(str, ambiguous_indexes)),)
                    if ambiguous_indexes
                    else ()
                ),
                "separated_ocr_marker_band",
            )
        )
    )


def separate_repeated_ocr_marker_band(region: TableRegion) -> TableRegion:
    """Split one proven headerless OCR pictogram band from its DATE column."""

    bands = tuple(
        band
        for column in region.table_schema.columns
        if column.role is ColumnRole.DATE
        if (band := _detect_band(region, column)) is not None
    )
    if len(bands) != 1:
        return region
    band = bands[0]
    replacements = _replacement_cells(region, band)
    rows = tuple(_split_row(row, replacements) for row in region.rows)
    columns = _split_columns(region, band, replacements)
    sample_cells = _replace_sample_cells(region.table_schema.sample_cells, replacements)
    schema = region.table_schema.model_copy(
        update={
            "columns": columns,
            "sample_cells": sample_cells,
            "diagnostics": _schema_diagnostics(columns, region.table_schema),
        }
    )
    region_diagnostics = tuple(
        diagnostic
        for diagnostic in region.diagnostics
        if not diagnostic.startswith("schema:ambiguous_columns:")
    )
    return region.model_copy(
        update={
            "rows": rows,
            "table_schema": schema,
            "diagnostics": tuple(
                dict.fromkeys(
                    (
                        *region_diagnostics,
                        *(
                            f"schema:{diagnostic}"
                            for diagnostic in schema.diagnostics
                            if diagnostic.startswith("ambiguous_columns:")
                        ),
                        "separated_ocr_marker_band",
                    )
                )
            ),
        }
    )


__all__ = [
    "OCR_MARKER_BAND_DIAGNOSTIC",
    "is_ocr_marker_band_column",
    "is_proven_ocr_marker_cell",
    "proven_ocr_marker_word_partition",
    "separate_repeated_ocr_marker_band",
]
