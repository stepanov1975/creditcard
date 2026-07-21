"""Unicode- and coordinate-aware logical text reconstruction."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence

from ccparser.evidence.currency import (
    CURRENCY_OCR_SYMBOLS,
    custom_currency_glyph_candidates,
)
from ccparser.evidence.models import Glyph, PageEvidence, Word
from ccparser.geometry import (
    BBox,
    bbox_center_x,
    bbox_center_y,
    bbox_height,
    center_inside,
    intersection_over_smaller,
    intersection_over_union,
    union_bbox,
)

_VISUAL_TRAILING_SIGN_NUMBER_PATTERN = re.compile(r"^(?:\d{1,3}(?:[,.]\d{3})+|\d+)[,.]\d{2}$")


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


def _cluster_lines[T: (Glyph, Word)](items: Sequence[T]) -> list[list[T]]:
    lines: list[list[T]] = []
    for item in sorted(items, key=lambda value: (bbox_center_y(value.bbox), value.bbox[0])):
        best_line: list[T] | None = None
        best_distance = float("inf")
        for line in lines:
            line_bbox = union_bbox(value.bbox for value in line)
            distance = abs(bbox_center_y(item.bbox) - bbox_center_y(line_bbox))
            tolerance = 0.6 * max(bbox_height(item.bbox), bbox_height(line_bbox))
            if distance <= tolerance and distance < best_distance:
                best_line = line
                best_distance = distance
        if best_line is None:
            lines.append([item])
        else:
            best_line.append(item)
    return sorted(lines, key=lambda line: union_bbox(item.bbox for item in line)[1])


def _glyph_groups(line: Sequence[Glyph]) -> list[list[Glyph]]:
    visible = sorted((glyph for glyph in line if not glyph.char.isspace()), key=lambda g: g.bbox[0])
    if not visible:
        return []
    typical_height = statistics.median(bbox_height(glyph.bbox) for glyph in visible)
    groups: list[list[Glyph]] = [[visible[0]]]
    last_direction = _strong_direction(visible[0].char)
    for glyph in visible[1:]:
        previous = groups[-1][-1]
        gap = glyph.bbox[0] - previous.bbox[2]
        direction = _strong_direction(glyph.char)
        direction_changed = (
            direction is not None and last_direction is not None and direction != last_direction
        )
        currency_suffix_boundary = (
            any(char.isdigit() for char in glyph.char)
            and previous.char in CURRENCY_OCR_SYMBOLS
            and any(char.isdigit() for preceding in groups[-1][:-1] for char in preceding.char)
        )
        if gap > typical_height * 0.4 or direction_changed or currency_suffix_boundary:
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
                key=lambda glyph: bbox_center_x(glyph.bbox),
                reverse=direction == "rtl",
            )
        )

    attached: dict[int, list[Glyph]] = {index: [] for index in range(len(bases))}
    for mark in combining:
        nearest_index = min(
            range(len(bases)),
            key=lambda index: abs(bbox_center_x(mark.bbox) - bbox_center_x(bases[index].bbox)),
        )
        attached[nearest_index].append(mark)
    units = tuple(
        (
            bbox_center_x(base.bbox),
            base.char
            + "".join(
                mark.char
                for mark in sorted(
                    attached[index],
                    key=lambda glyph: (
                        unicodedata.combining(glyph.char[0]),
                        bbox_center_x(glyph.bbox),
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
                    (statistics.mean(bbox_center_x(glyph.bbox) for glyph in group), text)
                )
        dominant = _dominant_direction(tuple(text for _, text in rendered_groups))
        rendered_groups.sort(key=lambda item: item[0], reverse=dominant == "rtl")
        line_text = _normalized(" ".join(text for _, text in rendered_groups))
        if line_text:
            rendered_lines.append(line_text)
    return _normalized(" ".join(rendered_lines))


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
            and (
                intersection_over_union(existing.bbox, word.bbox) >= 0.7
                or intersection_over_smaller(existing.bbox, word.bbox) >= 0.9
            )
            for existing in selected
        ):
            continue
        selected.append(word)
    return tuple(selected)


def _positioned_glyph_groups(glyphs: Sequence[Glyph], bbox: BBox) -> tuple[Glyph, ...]:
    vertically_relevant = tuple(
        glyph for glyph in glyphs if bbox[1] <= bbox_center_y(glyph.bbox) <= bbox[3]
    )
    selected = tuple(
        glyph
        for line in _cluster_lines(vertically_relevant)
        for group in _glyph_groups(line)
        if center_inside(union_bbox(item.bbox for item in group), bbox)
        for glyph in group
    )
    return tuple(
        sorted(
            selected,
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


def _text_from_words(words: Sequence[Word]) -> str:
    rendered_lines: list[str] = []
    for line in _cluster_lines(_deduplicated_words(words)):
        dominant = _dominant_direction(tuple(word.text for word in line))
        ordered = sorted(line, key=lambda word: bbox_center_x(word.bbox), reverse=dominant == "rtl")
        line_text = _normalized(" ".join(word.text for word in ordered))
        if line_text:
            rendered_lines.append(line_text)
    return _normalized(" ".join(rendered_lines))


def _text_from_lossless_words(words: Sequence[Word]) -> str:
    """Order exact word-owned glyph text by directional runs."""

    rendered_lines: list[str] = []
    for line in _cluster_lines(_deduplicated_words(words)):
        physical = sorted(line, key=lambda word: bbox_center_x(word.bbox))
        base_direction = _dominant_direction(tuple(word.text for word in physical))
        runs: list[tuple[str, list[Word]]] = []
        for word in physical:
            direction = _strong_direction(word.text) or (runs[-1][0] if runs else base_direction)
            if runs and runs[-1][0] == direction:
                runs[-1][1].append(word)
            else:
                runs.append((direction, [word]))
        ordered_runs = runs if base_direction == "ltr" else list(reversed(runs))
        ordered_words = tuple(
            word
            for direction, run in ordered_runs
            for word in (reversed(run) if direction == "rtl" else run)
        )
        rendered_words: list[str] = []
        index = 0
        while index < len(ordered_words):
            word = ordered_words[index]
            if (
                index + 1 < len(ordered_words)
                and _VISUAL_TRAILING_SIGN_NUMBER_PATTERN.fullmatch(_normalized(word.text))
                is not None
                and _normalized(ordered_words[index + 1].text) in {"+", "-"}
            ):
                rendered_words.append(
                    _normalized(ordered_words[index + 1].text) + _normalized(word.text)
                )
                index += 2
                continue
            rendered_words.append(word.text)
            index += 1
        line_text = _normalized(" ".join(rendered_words))
        if line_text:
            rendered_lines.append(line_text)
    return _normalized(" ".join(rendered_lines))


def _ocr_corroborated_currency_glyphs(
    glyphs: Sequence[Glyph],
    words: Sequence[Word],
) -> tuple[Glyph, ...]:
    candidates = custom_currency_glyph_candidates(glyphs, words)
    if not candidates:
        return tuple(glyphs)
    replacements: dict[Glyph, str] = {}
    for candidate in candidates:
        center_x = bbox_center_x(candidate.bbox)
        center_y = bbox_center_y(candidate.bbox)
        symbols = tuple(
            word.text
            for word in words
            if word.source == "ocr"
            and word.text in CURRENCY_OCR_SYMBOLS
            and word.bbox[0] <= center_x <= word.bbox[2]
            and word.bbox[1] <= center_y <= word.bbox[3]
        )
        if len(symbols) == 1:
            replacements[candidate] = symbols[0]
    return tuple(
        glyph.model_copy(update={"char": replacements[glyph], "source": "ocr"})
        if glyph in replacements
        else glyph
        for glyph in glyphs
    )


def _character_signature(text: str) -> tuple[str, ...]:
    return tuple(sorted(char for char in _normalized(text) if not char.isspace()))


def _lossless_word_text(glyphs: Sequence[Glyph], words: Sequence[Word]) -> str | None:
    visible_glyphs = tuple(glyph for glyph in glyphs if not glyph.char.isspace())
    rtl_word_count = sum(_strong_direction(word.text) == "rtl" for word in words)
    if not visible_glyphs or not words or rtl_word_count < 2:
        return None
    assigned: list[list[Glyph]] = [[] for _ in words]
    for glyph in visible_glyphs:
        owners = tuple(
            index for index, word in enumerate(words) if center_inside(glyph.bbox, word.bbox)
        )
        if len(owners) != 1:
            return None
        assigned[owners[0]].append(glyph)
    canonical_words: list[Word] = []
    for word, word_glyphs in zip(words, assigned, strict=True):
        glyph_text = _text_from_glyphs(word_glyphs)
        if not glyph_text or _character_signature(glyph_text) != _character_signature(word.text):
            return None
        canonical_words.append(word.model_copy(update={"text": glyph_text}))
    candidate = _text_from_lossless_words(canonical_words)
    glyph_text = _text_from_glyphs(visible_glyphs)
    return (
        candidate if _character_signature(candidate) == _character_signature(glyph_text) else None
    )


def canonical_words_for_layout(page_evidence: PageEvidence) -> tuple[Word, ...]:
    """Canonicalize positioned RTL digital words only from lossless glyph geometry."""

    canonical: list[Word] = []
    for word in page_evidence.words:
        if word.source != "digital" or _strong_direction(word.text) != "rtl":
            canonical.append(word)
            continue
        glyphs = _positioned_glyph_groups(page_evidence.glyphs, word.bbox)
        glyph_text = _text_from_glyphs(glyphs) if glyphs else ""
        if (
            glyph_text
            and _strong_direction(glyph_text) == "rtl"
            and _character_signature(glyph_text) == _character_signature(word.text)
        ):
            canonical.append(word.model_copy(update={"text": glyph_text}))
        else:
            canonical.append(word)
    return tuple(canonical)


def positioned_evidence_for_bbox(
    page_evidence: PageEvidence, bbox: BBox
) -> tuple[tuple[Glyph, ...], tuple[Word, ...]]:
    """Return deterministic raw provenance whose centers fall inside ``bbox``."""

    glyphs = _positioned_glyph_groups(page_evidence.glyphs, bbox)
    words = tuple(
        sorted(
            _deduplicated_words(
                tuple(word for word in page_evidence.words if center_inside(word.bbox, bbox))
            ),
            key=lambda word: (word.bbox[1], word.bbox[0], word.text, word.source),
        )
    )
    return glyphs, words


def logical_text_for_bbox(page_evidence: PageEvidence, bbox: BBox) -> str:
    """Return logical NFC text for positioned evidence whose centers are in ``bbox``."""

    glyphs, words = positioned_evidence_for_bbox(page_evidence, bbox)
    return logical_text_for_evidence(glyphs, words)


def logical_text_for_evidence(
    glyphs: Sequence[Glyph],
    words: Sequence[Word],
) -> str:
    """Return logical NFC text derived from the exact supplied provenance."""

    if glyphs:
        canonical_glyphs = _ocr_corroborated_currency_glyphs(glyphs, words)
        return _lossless_word_text(canonical_glyphs, words) or _text_from_glyphs(canonical_glyphs)
    return _text_from_words(words)
