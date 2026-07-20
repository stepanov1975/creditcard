"""Relative-geometry row and cell clustering."""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Sequence
from itertools import combinations

from ccparser.evidence.models import BBox, Word
from ccparser.layout.models import Cell, Row

MAX_LINE_HEIGHT_RATIO = 2.5


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _union_bbox(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _vertical_overlap(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    smaller_height = min(_height(first), _height(second))
    return overlap / smaller_height if smaller_height else 0.0


def _height_compatible(word: Word, line: Sequence[Word]) -> bool:
    word_height = _height(word.bbox)
    typical_height = statistics.median(_height(item.bbox) for item in line)
    smaller_height = min(word_height, typical_height)
    larger_height = max(word_height, typical_height)
    return smaller_height > 0 and larger_height / smaller_height <= MAX_LINE_HEIGHT_RATIO


def _line_reference_bbox(line: Sequence[Word]) -> BBox:
    center = statistics.median(_center_y(item.bbox) for item in line)
    typical_height = statistics.median(_height(item.bbox) for item in line)
    return (
        min(item.bbox[0] for item in line),
        center - typical_height / 2,
        max(item.bbox[2] for item in line),
        center + typical_height / 2,
    )


def _intersection_over_union(first: BBox, second: BBox) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    first_area = max(0.0, first[2] - first[0]) * _height(first)
    second_area = max(0.0, second[2] - second[0]) * _height(second)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _intersection_over_smaller(first: BBox, second: BBox) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    smaller = min(
        max(0.0, first[2] - first[0]) * _height(first),
        max(0.0, second[2] - second[0]) * _height(second),
    )
    return intersection / smaller if smaller else 0.0


def _deduplicated_words(words: Sequence[Word]) -> tuple[Word, ...]:
    selected: list[Word] = []
    for word in sorted(
        words,
        key=lambda value: (
            -value.confidence,
            value.source != "digital",
            value.bbox,
            value.text,
        ),
    ):
        if any(
            existing.text == word.text
            and (
                _intersection_over_union(existing.bbox, word.bbox) >= 0.7
                or _intersection_over_smaller(existing.bbox, word.bbox) >= 0.9
            )
            for existing in selected
        ):
            continue
        selected.append(word)
    return tuple(selected)


def _dominant_direction(texts: Sequence[str]) -> str:
    text = "".join(texts)
    rtl = sum(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)
    ltr = sum(unicodedata.bidirectional(char) == "L" for char in text)
    return "rtl" if rtl > ltr else "ltr"


def _cluster_word_lines(words: Sequence[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda value: (_center_y(value.bbox), value.bbox[0], value.text)):
        best: list[Word] | None = None
        best_distance = float("inf")
        for line in lines:
            line_bbox = _line_reference_bbox(line)
            distance = abs(_center_y(word.bbox) - _center_y(line_bbox))
            tolerance = 0.6 * max(_height(word.bbox), _height(line_bbox))
            if (
                _height_compatible(word, line)
                and distance <= tolerance
                and distance < best_distance
            ):
                best = line
                best_distance = distance
        if best is None:
            lines.append([word])
        else:
            best.append(word)
    return sorted(lines, key=lambda line: _union_bbox(tuple(word.bbox for word in line))[1])


def _vertical_coherence(words: Sequence[Word]) -> float:
    if len(words) < 2:
        return 1.0
    pairwise_overlap = statistics.mean(
        _vertical_overlap(first.bbox, second.bbox) for first, second in combinations(words, 2)
    )
    typical_height = statistics.median(_height(word.bbox) for word in words)
    if typical_height <= 0:
        return 0.0
    centers = tuple(_center_y(word.bbox) for word in words)
    center_coherence = max(0.0, 1.0 - (max(centers) - min(centers)) / typical_height)
    return min(pairwise_overlap, center_coherence)


def _words_to_cells(words: Sequence[Word], page_number: int) -> tuple[Cell, ...]:
    ordered = sorted(words, key=lambda word: (word.bbox[0], word.bbox[1], word.text))
    typical_height = statistics.median(_height(word.bbox) for word in ordered)
    groups: list[list[Word]] = [[ordered[0]]]
    for word in ordered[1:]:
        gap = word.bbox[0] - groups[-1][-1].bbox[2]
        if gap <= typical_height * 0.6:
            groups[-1].append(word)
        else:
            groups.append([word])

    cells: list[Cell] = []
    for group in groups:
        direction = _dominant_direction(tuple(word.text for word in group))
        logical_words = sorted(group, key=lambda word: word.bbox[0], reverse=direction == "rtl")
        bbox = _union_bbox(tuple(word.bbox for word in group))
        cells.append(
            Cell(
                page_number=page_number,
                bbox=bbox,
                text=" ".join(word.text for word in logical_words),
                words=tuple(logical_words),
                confidence=statistics.mean(word.confidence for word in group),
            )
        )
    row_direction = _dominant_direction(tuple(cell.text for cell in cells))
    return tuple(sorted(cells, key=lambda cell: cell.bbox[0], reverse=row_direction == "rtl"))


def cluster_rows(words: Sequence[Word], page_number: int) -> tuple[Row, ...]:
    """Cluster words using overlap and word-height-relative tolerances."""

    if page_number <= 0:
        raise ValueError("page_number must be positive")
    rows: list[Row] = []
    for line in _cluster_word_lines(_deduplicated_words(words)):
        geometric_words = tuple(
            sorted(line, key=lambda word: (word.bbox[0], word.bbox[1], word.text))
        )
        bbox = _union_bbox(tuple(word.bbox for word in geometric_words))
        cells = _words_to_cells(geometric_words, page_number)
        direction = _dominant_direction(tuple(cell.text for cell in cells))
        coherence = _vertical_coherence(geometric_words)
        rows.append(
            Row(
                page_number=page_number,
                bbox=bbox,
                cells=cells,
                words=geometric_words,
                confidence=min(
                    statistics.mean(word.confidence for word in geometric_words), coherence
                ),
                diagnostics=(f"dominant_direction:{direction}",),
            )
        )
    return tuple(rows)
