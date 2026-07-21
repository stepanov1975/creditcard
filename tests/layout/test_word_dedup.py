from __future__ import annotations

import math
import unicodedata

from ccparser.evidence import Word
from ccparser.geometry import BBox
from ccparser.layout.word_dedup import deduplicate_words


def _identity(text: str) -> str:
    return text


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _word(
    text: str = "Amount",
    bbox: BBox = (0.0, 0.0, 10.0, 10.0),
    *,
    source: str = "digital",
    confidence: float = 1.0,
) -> Word:
    return Word(
        text=text,
        bbox=bbox,
        source=source,
        confidence=confidence,
    )


def test_deduplicate_words_keeps_higher_confidence_exact_duplicate() -> None:
    lower_digital = _word(source="digital", confidence=0.8)
    higher_ocr = _word(source="ocr", confidence=0.9)

    selected = deduplicate_words(
        (lower_digital, higher_ocr),
        text_key=_identity,
    )

    assert selected == (higher_ocr,)


def test_deduplicate_words_prefers_digital_source_at_equal_confidence() -> None:
    ocr = _word(source="ocr", confidence=0.9)
    digital = _word(source="digital", confidence=0.9)

    selected = deduplicate_words((ocr, digital), text_key=_identity)

    assert selected == (digital,)


def test_deduplicate_words_preserves_input_order_when_sort_keys_tie() -> None:
    first = _word()
    second = _word()

    assert deduplicate_words((first, second), text_key=_identity)[0] is first
    assert deduplicate_words((second, first), text_key=_identity)[0] is second


def test_deduplicate_words_applies_the_supplied_text_key() -> None:
    decomposed = _word("Cafe\u0301")
    composed = _word("Caf\u00e9")

    identity_selected = deduplicate_words(
        (decomposed, composed),
        text_key=_identity,
    )
    nfc_selected = deduplicate_words(
        (decomposed, composed),
        text_key=_nfc,
    )

    assert len(identity_selected) == 2
    assert {word.text for word in identity_selected} == {"Caf\u00e9", "Cafe\u0301"}
    assert nfc_selected == (decomposed,)


def test_deduplicate_words_uses_inclusive_iou_threshold() -> None:
    first = _word(bbox=(0.0, 0.0, 17.0, 10.0))
    at_threshold = _word(bbox=(3.0, 0.0, 20.0, 10.0))
    below_threshold = _word(bbox=(math.nextafter(3.0, math.inf, steps=3), 0.0, 20.0, 10.0))

    assert deduplicate_words((first, at_threshold), text_key=_identity) == (first,)
    assert deduplicate_words((first, below_threshold), text_key=_identity) == (
        first,
        below_threshold,
    )


def test_deduplicate_words_uses_inclusive_overlap_over_smaller_threshold() -> None:
    smaller = _word(bbox=(0.0, 0.0, 10.0, 10.0))
    at_threshold = _word(bbox=(1.0, 0.0, 21.0, 10.0))
    below_threshold = _word(bbox=(math.nextafter(1.0, math.inf, steps=5), 0.0, 21.0, 10.0))

    assert deduplicate_words((smaller, at_threshold), text_key=_identity) == (smaller,)
    assert deduplicate_words((smaller, below_threshold), text_key=_identity) == (
        smaller,
        below_threshold,
    )


def test_deduplicate_words_preserves_repeated_nonoverlapping_words() -> None:
    left = _word(bbox=(0.0, 0.0, 10.0, 10.0))
    right = _word(bbox=(20.0, 0.0, 30.0, 10.0))

    selected = deduplicate_words((right, left), text_key=_identity)

    assert selected == (left, right)
