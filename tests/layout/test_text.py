from __future__ import annotations

from ccparser.evidence import ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.layout.text import logical_text_for_bbox, logical_text_for_evidence


def _quality(*, glyph_count: int, word_count: int) -> ExtractionQuality:
    return ExtractionQuality(
        character_count=glyph_count,
        usable_character_count=glyph_count,
        word_count=word_count,
        replacement_character_ratio=0.0,
        control_character_ratio=0.0,
        image_area_ratio=0.0,
        requires_ocr=False,
    )


def _glyph(char: str, x: float, y: float = 10.0) -> Glyph:
    return Glyph(
        char=char,
        bbox=(x, y, x + 4.0, y + 10.0),
        origin=(x, y + 9.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=1.0,
    )


def _rtl_glyphs(text: str, right: float, y: float) -> tuple[Glyph, ...]:
    return tuple(_glyph(char, right - index * 4.0 - 3.0, y) for index, char in enumerate(text))


def test_logical_text_orders_each_script_run_and_rtl_word_groups_from_geometry() -> None:
    glyphs = (
        _glyph("B", 15.0),
        _glyph("ם", 60.0),
        _glyph("A", 10.0),
        _glyph("\u05d5", 65.0),
        _glyph("C", 20.0),
        _glyph("ל", 70.0),
        _glyph("ש", 75.0),
    )
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=glyphs,
        quality=_quality(glyph_count=len(glyphs), word_count=0),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 90.0, 30.0)) == "שלום ABC"


def test_logical_text_uses_numeric_ltr_run_inside_dominant_hebrew_cell() -> None:
    glyphs = (
        _glyph("2", 30.0),
        _glyph("ם", 70.0),
        _glyph("1", 25.0),
        _glyph("\u05d5", 75.0),
        _glyph(".", 35.0),
        _glyph("ל", 80.0),
        _glyph("5", 40.0),
        _glyph("ש", 85.0),
    )
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=glyphs,
        quality=_quality(glyph_count=len(glyphs), word_count=0),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 100.0, 30.0)) == "שלום 12.5"


def test_logical_text_uses_lossless_words_when_overlapping_glyphs_interleave() -> None:
    glyphs = (*_rtl_glyphs("שער", 40.0, 10.0), *_rtl_glyphs("המרה", 46.0, 16.0))
    words = (
        Word(
            text="שער",
            bbox=(29.0, 10.0, 41.0, 20.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="המרה",
            bbox=(31.0, 16.0, 47.0, 26.0),
            source="digital",
            confidence=1.0,
        ),
    )

    assert logical_text_for_evidence(glyphs, words) == "המרה שער"


def test_logical_text_keeps_numeric_punctuation_joined_from_glyph_geometry() -> None:
    glyphs = tuple(_glyph(char, 10.0 + index * 5.0) for index, char in enumerate("12.40"))
    words = (
        Word(
            text="12",
            bbox=(9.0, 9.0, 19.0, 21.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text=".",
            bbox=(19.0, 9.0, 24.0, 21.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="40",
            bbox=(24.0, 9.0, 35.0, 21.0),
            source="digital",
            confidence=1.0,
        ),
    )

    assert logical_text_for_evidence(glyphs, words) == "12.40"


def test_logical_text_uses_ocr_corroborated_custom_currency_glyph() -> None:
    glyphs = (
        _glyph("3", 10.0).model_copy(
            update={"bbox": (10.0, 10.0, 16.0, 20.0), "font": "CustomCurrency"}
        ),
        *(
            _glyph(char, 16.2 + index * 4.1).model_copy(update={"font": "Digits"})
            for index, char in enumerate("59.92")
        ),
    )
    words = (
        Word(text="3", bbox=(10.0, 10.0, 16.0, 20.0), source="digital", confidence=1.0),
        Word(text="59", bbox=(16.2, 10.0, 24.2, 20.0), source="digital", confidence=1.0),
        Word(text=".", bbox=(24.4, 10.0, 28.4, 20.0), source="digital", confidence=1.0),
        Word(text="92", bbox=(28.5, 10.0, 36.5, 20.0), source="digital", confidence=1.0),
        Word(text="€", bbox=(8.0, 8.0, 18.0, 22.0), source="ocr", confidence=0.2),
    )

    assert logical_text_for_evidence(glyphs, words) == "€59.92"


def test_logical_text_rejects_currency_ocr_without_custom_glyph_geometry() -> None:
    glyphs = tuple(_glyph(char, 10.0 + index * 4.1) for index, char in enumerate("359.92"))
    words = (Word(text="€", bbox=(8.0, 8.0, 16.0, 22.0), source="ocr", confidence=0.9),)

    assert logical_text_for_evidence(glyphs, words) == "359.92"


def test_logical_text_attaches_hebrew_combining_marks_to_their_positioned_base() -> None:
    glyphs = (
        _glyph("ל", 75.0),
        _glyph("\u05c1", 82.0),
        _glyph("ש", 80.0),
        _glyph("\u05b8", 81.0),
    )
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=glyphs,
        quality=_quality(glyph_count=len(glyphs), word_count=0),
    )

    assert logical_text_for_bbox(page, (60.0, 0.0, 90.0, 30.0)) == "שָׁל"


def test_logical_text_falls_back_to_deduplicated_positioned_words_and_normalizes() -> None:
    words = (
        Word(
            text="12.50",
            bbox=(15.0, 10.0, 35.0, 20.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="שָׁלוֹם",
            bbox=(60.0, 10.0, 90.0, 20.0),
            source="ocr",
            confidence=0.93,
        ),
        Word(
            text="שָׁלוֹם",
            bbox=(60.2, 10.0, 90.2, 20.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="outside",
            bbox=(110.0, 10.0, 140.0, 20.0),
            source="digital",
            confidence=1.0,
        ),
    )
    page = PageEvidence(
        page_number=1,
        width=150.0,
        height=100.0,
        words=words,
        quality=_quality(glyph_count=0, word_count=len(words)),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 100.0, 30.0)) == "שָׁלוֹם 12.50"


def test_logical_text_orders_lines_top_to_bottom_and_returns_empty_without_evidence() -> None:
    glyphs = (*(_glyph(char, 10.0 + index * 5.0, 10.0) for index, char in enumerate("Top")),)
    words = (
        Word(
            text="Bottom",
            bbox=(10.0, 40.0, 45.0, 50.0),
            source="digital",
            confidence=1.0,
        ),
    )
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=glyphs,
        words=words,
        quality=_quality(glyph_count=len(glyphs), word_count=len(words)),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 80.0, 30.0)) == "Top"
    assert logical_text_for_bbox(page, (80.0, 60.0, 100.0, 90.0)) == ""


def test_logical_text_assigns_numeric_glyph_groups_whole_across_a_bbox_boundary() -> None:
    first = tuple(_glyph(char, 10.0 + index * 5.0) for index, char in enumerate("12.40"))
    second = tuple(_glyph(char, 42.0 + index * 5.0) for index, char in enumerate("0.00"))
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=(*first, *second),
        quality=_quality(glyph_count=len(first) + len(second), word_count=0),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 46.0, 30.0)) == "12.40"
    assert logical_text_for_bbox(page, (46.0, 0.0, 80.0, 30.0)) == "0.00"


def test_logical_text_splits_touching_currency_suffix_amount_runs_at_boundary() -> None:
    first = tuple(_glyph(char, 10.0 + index * 4.0) for index, char in enumerate("10.00₪"))
    second = tuple(_glyph(char, 34.2 + index * 4.0) for index, char in enumerate("20.00₪"))
    page = PageEvidence(
        page_number=1,
        width=100.0,
        height=100.0,
        glyphs=(*first, *second),
        quality=_quality(glyph_count=len(first) + len(second), word_count=0),
    )

    assert logical_text_for_bbox(page, (0.0, 0.0, 34.1, 30.0)) == "10.00₪"
    assert logical_text_for_bbox(page, (34.1, 0.0, 80.0, 30.0)) == "20.00₪"
