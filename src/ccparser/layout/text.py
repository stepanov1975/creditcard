"""Unicode- and coordinate-aware logical text reconstruction."""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Sequence

from ccparser.evidence.models import BBox, Glyph, PageEvidence, Word


def _width(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0])


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _inside_bbox(candidate: BBox, container: BBox) -> bool:
    center_x = _center_x(candidate)
    center_y = _center_y(candidate)
    return container[0] <= center_x <= container[2] and container[1] <= center_y <= container[3]


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _strong_direction(text: str) -> str | None:
    rtl = sum(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)
    ltr = sum(unicodedata.bidirectional(char) == "L" for char in text)
    if rtl > ltr:
        return "rtl"
    if ltr > rtl:
        return "ltr"
    if any(unicodedata.bidirectional(char) in {"EN", "AN"} for char in text):
        return "ltr"
    return None


def _dominant_direction(texts: Sequence[str]) -> str:
    text = "".join(texts)
    rtl = sum(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)
    ltr = sum(unicodedata.bidirectional(char) == "L" for char in text)
    return "rtl" if rtl > ltr else "ltr"


def _vertical_overlap(first: BBox, second: BBox) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    smaller_height = min(_height(first), _height(second))
    return overlap / smaller_height if smaller_height else 0.0


def _cluster_lines[T: (Glyph, Word)](items: Sequence[T]) -> list[list[T]]:
    lines: list[list[T]] = []
    for item in sorted(items, key=lambda value: (_center_y(value.bbox), value.bbox[0])):
        best_line: list[T] | None = None
        best_distance = float("inf")
        for line in lines:
            line_bbox = _union_bbox(tuple(value.bbox for value in line))
            distance = abs(_center_y(item.bbox) - _center_y(line_bbox))
            tolerance = 0.45 * max(_height(item.bbox), _height(line_bbox))
            if (
                _vertical_overlap(item.bbox, line_bbox) >= 0.3 or distance <= tolerance
            ) and distance < best_distance:
                best_line = line
                best_distance = distance
        if best_line is None:
            lines.append([item])
        else:
            best_line.append(item)
    return sorted(lines, key=lambda line: _union_bbox(tuple(item.bbox for item in line))[1])


def _union_bbox(boxes: tuple[BBox, ...]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _glyph_groups(line: Sequence[Glyph]) -> list[list[Glyph]]:
    visible = sorted((glyph for glyph in line if not glyph.char.isspace()), key=lambda g: g.bbox[0])
    if not visible:
        return []
    typical_height = statistics.median(_height(glyph.bbox) for glyph in visible)
    groups: list[list[Glyph]] = [[visible[0]]]
    last_direction = _strong_direction(visible[0].char)
    for glyph in visible[1:]:
        previous = groups[-1][-1]
        gap = glyph.bbox[0] - previous.bbox[2]
        direction = _strong_direction(glyph.char)
        direction_changed = (
            direction is not None and last_direction is not None and direction != last_direction
        )
        if gap > typical_height * 0.4 or direction_changed:
            groups.append([glyph])
            last_direction = direction
        else:
            groups[-1].append(glyph)
            if direction is not None:
                last_direction = direction
    return groups


def _ordered_glyph_text(group: Sequence[Glyph], direction: str) -> str:
    bases = tuple(
        glyph
        for glyph in group
        if not glyph.char or any(unicodedata.combining(char) == 0 for char in glyph.char)
    )
    combining = tuple(glyph for glyph in group if glyph not in bases)
    if not bases:
        return "".join(
            glyph.char
            for glyph in sorted(
                combining,
                key=lambda glyph: _center_x(glyph.bbox),
                reverse=direction == "rtl",
            )
        )

    attached: dict[int, list[Glyph]] = {index: [] for index in range(len(bases))}
    for mark in combining:
        nearest_index = min(
            range(len(bases)),
            key=lambda index: abs(_center_x(mark.bbox) - _center_x(bases[index].bbox)),
        )
        attached[nearest_index].append(mark)
    units = tuple(
        (
            _center_x(base.bbox),
            base.char
            + "".join(
                mark.char
                for mark in sorted(
                    attached[index],
                    key=lambda glyph: (
                        unicodedata.combining(glyph.char[0]),
                        _center_x(glyph.bbox),
                    ),
                )
            ),
        )
        for index, base in enumerate(bases)
    )
    return "".join(
        text for _, text in sorted(units, key=lambda unit: unit[0], reverse=direction == "rtl")
    )


def _text_from_glyphs(glyphs: Sequence[Glyph]) -> str:
    rendered_lines: list[str] = []
    for line in _cluster_lines(glyphs):
        groups = _glyph_groups(line)
        rendered_groups: list[tuple[float, str]] = []
        for group in groups:
            direction = _strong_direction("".join(glyph.char for glyph in group)) or "ltr"
            text = _normalized(_ordered_glyph_text(group, direction))
            if text:
                rendered_groups.append(
                    (statistics.mean(_center_x(glyph.bbox) for glyph in group), text)
                )
        dominant = _dominant_direction(tuple(text for _, text in rendered_groups))
        rendered_groups.sort(key=lambda item: item[0], reverse=dominant == "rtl")
        line_text = _normalized(" ".join(text for _, text in rendered_groups))
        if line_text:
            rendered_lines.append(line_text)
    return _normalized(" ".join(rendered_lines))


def _intersection_over_union(first: BBox, second: BBox) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = _width(first) * _height(first) + _width(second) * _height(second) - intersection
    return intersection / union if union else 0.0


def _deduplicated_words(words: Sequence[Word]) -> tuple[Word, ...]:
    selected: list[Word] = []
    ordered = sorted(
        words,
        key=lambda word: (
            -word.confidence,
            word.source != "digital",
            word.bbox,
            _normalized(word.text),
        ),
    )
    for word in ordered:
        if any(
            _normalized(existing.text) == _normalized(word.text)
            and _intersection_over_union(existing.bbox, word.bbox) >= 0.7
            for existing in selected
        ):
            continue
        selected.append(word)
    return tuple(selected)


def _text_from_words(words: Sequence[Word]) -> str:
    rendered_lines: list[str] = []
    for line in _cluster_lines(_deduplicated_words(words)):
        dominant = _dominant_direction(tuple(word.text for word in line))
        ordered = sorted(line, key=lambda word: _center_x(word.bbox), reverse=dominant == "rtl")
        line_text = _normalized(" ".join(word.text for word in ordered))
        if line_text:
            rendered_lines.append(line_text)
    return _normalized(" ".join(rendered_lines))


def logical_text_for_bbox(page_evidence: PageEvidence, bbox: BBox) -> str:
    """Return logical NFC text for positioned evidence whose centers are in ``bbox``."""

    glyphs = tuple(glyph for glyph in page_evidence.glyphs if _inside_bbox(glyph.bbox, bbox))
    if glyphs:
        return _text_from_glyphs(glyphs)
    words = tuple(word for word in page_evidence.words if _inside_bbox(word.bbox, bbox))
    return _text_from_words(words)
