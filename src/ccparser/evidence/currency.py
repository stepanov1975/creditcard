"""Geometry for detecting custom-font currency glyph candidates."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from ccparser.evidence.models import Glyph, Word

CURRENCY_OCR_SYMBOLS = frozenset("₪$€£")


def _center_x(item: Glyph | Word) -> float:
    return (item.bbox[0] + item.bbox[2]) / 2


def _center_y(item: Glyph | Word) -> float:
    return (item.bbox[1] + item.bbox[3]) / 2


def _height(item: Glyph | Word) -> float:
    return max(0.0, item.bbox[3] - item.bbox[1])


def _width(item: Glyph | Word) -> float:
    return max(0.0, item.bbox[2] - item.bbox[0])


def _inside(glyph: Glyph, word: Word) -> bool:
    return (
        word.bbox[0] <= _center_x(glyph) <= word.bbox[2]
        and word.bbox[1] <= _center_y(glyph) <= word.bbox[3]
    )


def custom_currency_glyph_candidates(
    glyphs: Sequence[Glyph],
    words: Sequence[Word],
) -> tuple[Glyph, ...]:
    """Return wide custom-font digits immediately prefixing a normal numeric run."""

    digital_words = tuple(
        sorted(
            (word for word in words if word.source == "digital"),
            key=lambda word: (word.bbox[1], word.bbox[0], word.text),
        )
    )
    candidates: list[Glyph] = []
    for word in digital_words:
        following_words = tuple(
            candidate
            for candidate in digital_words
            if candidate is not word
            and candidate.bbox[0] >= word.bbox[2]
            and abs(_center_y(word) - _center_y(candidate))
            <= max(_height(word), _height(candidate)) * 0.2
        )
        if not following_words:
            continue
        following = min(
            following_words,
            key=lambda candidate: (candidate.bbox[0] - word.bbox[2], candidate.bbox),
        )
        if (
            len(word.text) != 1
            or not word.text.isdigit()
            or not following.text.isdigit()
            or abs(_center_y(word) - _center_y(following))
            > max(_height(word), _height(following)) * 0.2
            or following.bbox[0] - word.bbox[2] > max(_height(word), _height(following)) * 0.1
        ):
            continue
        word_glyphs = tuple(glyph for glyph in glyphs if _inside(glyph, word))
        following_glyphs = tuple(glyph for glyph in glyphs if _inside(glyph, following))
        if (
            len(word_glyphs) != 1
            or not following_glyphs
            or any(not glyph.char.isdigit() for glyph in following_glyphs)
        ):
            continue
        candidate = word_glyphs[0]
        following_width = statistics.median(_width(glyph) for glyph in following_glyphs)
        if (
            following_width > 0
            and candidate.font not in {glyph.font for glyph in following_glyphs}
            and _width(candidate) >= following_width * 1.2
        ):
            candidates.append(candidate)
    return tuple(candidates)
