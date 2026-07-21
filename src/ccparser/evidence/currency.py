"""Geometry for detecting custom-font currency glyph candidates."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from ccparser.evidence.models import Glyph, Word
from ccparser.geometry import bbox_center_y, bbox_height, bbox_width, center_inside

CURRENCY_OCR_SYMBOLS = frozenset("₪$€£")


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
            and abs(bbox_center_y(word.bbox) - bbox_center_y(candidate.bbox))
            <= max(bbox_height(word.bbox), bbox_height(candidate.bbox)) * 0.2
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
            or abs(bbox_center_y(word.bbox) - bbox_center_y(following.bbox))
            > max(bbox_height(word.bbox), bbox_height(following.bbox)) * 0.2
            or following.bbox[0] - word.bbox[2]
            > max(bbox_height(word.bbox), bbox_height(following.bbox)) * 0.1
        ):
            continue
        word_glyphs = tuple(glyph for glyph in glyphs if center_inside(glyph.bbox, word.bbox))
        following_glyphs = tuple(
            glyph for glyph in glyphs if center_inside(glyph.bbox, following.bbox)
        )
        if (
            len(word_glyphs) != 1
            or not following_glyphs
            or any(not glyph.char.isdigit() for glyph in following_glyphs)
        ):
            continue
        candidate = word_glyphs[0]
        following_width = statistics.median(bbox_width(glyph.bbox) for glyph in following_glyphs)
        if (
            following_width > 0
            and candidate.font not in {glyph.font for glyph in following_glyphs}
            and bbox_width(candidate.bbox) >= following_width * 1.2
        ):
            candidates.append(candidate)
    return tuple(candidates)
