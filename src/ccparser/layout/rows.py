"""Relative-geometry row and cell clustering."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from itertools import combinations

from ccparser.evidence.models import Word
from ccparser.geometry import (
    BBox,
    bbox_center_y,
    bbox_height,
    union_bbox,
    vertical_overlap,
)
from ccparser.layout.models import Cell, Row
from ccparser.layout.text import _dominant_direction
from ccparser.layout.word_dedup import deduplicate_words

MAX_LINE_HEIGHT_RATIO = 2.5


def _height_compatible(word: Word, line: Sequence[Word]) -> bool:
    word_height = bbox_height(word.bbox)
    typical_height = statistics.median(bbox_height(item.bbox) for item in line)
    smaller_height = min(word_height, typical_height)
    larger_height = max(word_height, typical_height)
    return smaller_height > 0 and larger_height / smaller_height <= MAX_LINE_HEIGHT_RATIO


def _line_reference_bbox(line: Sequence[Word]) -> BBox:
    center = statistics.median(bbox_center_y(item.bbox) for item in line)
    typical_height = statistics.median(bbox_height(item.bbox) for item in line)
    return (
        min(item.bbox[0] for item in line),
        center - typical_height / 2,
        max(item.bbox[2] for item in line),
        center + typical_height / 2,
    )


def _ordered_cells_from_stored_direction(
    row: Row,
    cells: Sequence[Cell],
) -> tuple[Cell, ...]:
    direction = next(
        (
            diagnostic.removeprefix("dominant_direction:")
            for diagnostic in row.diagnostics
            if diagnostic.startswith("dominant_direction:")
        ),
        "ltr",
    )
    return tuple(sorted(cells, key=lambda cell: cell.bbox[0], reverse=direction == "rtl"))


def _cluster_word_lines(words: Sequence[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for word in sorted(
        words, key=lambda value: (bbox_center_y(value.bbox), value.bbox[0], value.text)
    ):
        best: list[Word] | None = None
        best_distance = float("inf")
        for line in lines:
            line_bbox = _line_reference_bbox(line)
            distance = abs(bbox_center_y(word.bbox) - bbox_center_y(line_bbox))
            tolerance = 0.6 * max(bbox_height(word.bbox), bbox_height(line_bbox))
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
    return sorted(lines, key=lambda line: union_bbox(word.bbox for word in line)[1])


def _vertical_coherence(words: Sequence[Word]) -> float:
    if len(words) < 2:
        return 1.0
    pairwise_overlap = statistics.mean(
        vertical_overlap(first.bbox, second.bbox) for first, second in combinations(words, 2)
    )
    typical_height = statistics.median(bbox_height(word.bbox) for word in words)
    if typical_height <= 0:
        return 0.0
    centers = tuple(bbox_center_y(word.bbox) for word in words)
    median_center = statistics.median(centers)
    center_coherence = statistics.median(
        max(0.0, 1.0 - abs(center - median_center) / typical_height) for center in centers
    )
    return min(pairwise_overlap, center_coherence)


def _words_to_cells(words: Sequence[Word], page_number: int) -> tuple[Cell, ...]:
    ordered = sorted(words, key=lambda word: (word.bbox[0], word.bbox[1], word.text))
    typical_height = statistics.median(bbox_height(word.bbox) for word in ordered)
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
        bbox = union_bbox(word.bbox for word in group)
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
    for line in _cluster_word_lines(deduplicate_words(words, text_key=lambda text: text)):
        geometric_words = tuple(
            sorted(line, key=lambda word: (word.bbox[0], word.bbox[1], word.text))
        )
        bbox = union_bbox(word.bbox for word in geometric_words)
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
