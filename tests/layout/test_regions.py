from __future__ import annotations

import pytest

from ccparser.evidence import ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.layout.models import ColumnRole
from ccparser.layout.regions import detect_table_regions


def _word(text: str, x0: float, x1: float, y: float) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="digital",
        confidence=1.0,
    )


def _page(words: tuple[Word, ...], glyphs: tuple[Glyph, ...] = ()) -> PageEvidence:
    return PageEvidence(
        page_number=1,
        width=130.0,
        height=180.0,
        glyphs=glyphs,
        words=words,
        quality=ExtractionQuality(
            character_count=len(glyphs),
            usable_character_count=len(glyphs),
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )


def _rtl_glyphs(text: str, right: float, y: float) -> tuple[Glyph, ...]:
    glyphs: list[Glyph] = []
    cursor = right
    for token in text.split():
        for char in token:
            glyphs.append(
                Glyph(
                    char=char,
                    bbox=(cursor - 2.0, y, cursor, y + 10.0),
                    origin=(cursor, y + 9.0),
                    font="SyntheticHebrew",
                    size=10.0,
                    source="digital",
                    confidence=1.0,
                )
            )
            cursor -= 3.0
        cursor -= 6.0
    return tuple(glyphs)


def _header(y: float) -> tuple[Word, ...]:
    return (
        _word("Date", 0.0, 22.0, y),
        _word("Description", 35.0, 72.0, y),
        _word("Amount", 92.0, 120.0, y),
    )


def _data(y: float, date: str, description: str, amount: str) -> tuple[Word, ...]:
    return (
        _word(date, 0.0, 22.0, y),
        _word(description, 35.0, 72.0, y),
        _word(amount, 92.0, 120.0, y),
    )


def test_detect_table_regions_requires_header_and_repeated_rows_and_stops_at_total() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "12.40"),
            *_data(50.0, "03/02/2026", "Cafe", "18.60"),
            _word("Total", 45.0, 72.0, 70.0),
            _word("31.00", 92.0, 120.0, 70.0),
            _word("Footer", 10.0, 40.0, 90.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    region = regions[0]
    assert len(region.rows) == 2
    assert region.bbox == (0.0, 10.0, 120.0, 60.0)
    assert tuple(column.role for column in region.table_schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )
    assert "stopped_at_total" in region.diagnostics
    assert "repeated_rows:2" in region.diagnostics


@pytest.mark.parametrize("marker", ('סה"כ', "סה״כ"))
def test_detect_table_regions_stops_at_quoted_hebrew_total_acronym(marker: str) -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "12.40"),
            *_data(50.0, "03/02/2026", "Cafe", "18.60"),
            _word(marker, 45.0, 72.0, 70.0),
            _word("31.00", 92.0, 120.0, 70.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_total" in regions[0].diagnostics
    assert all(marker not in cell.text for row in regions[0].rows for cell in row.cells)


def test_detect_table_regions_stops_at_new_header_and_detects_next_table() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            *_header(70.0),
            *_data(90.0, "03/02/2026", "Gamma", "30.00"),
            *_data(110.0, "04/02/2026", "Delta", "40.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 2
    assert "stopped_at_new_header" in regions[0].diagnostics
    assert tuple(region.header.bbox[1] for region in regions) == (10.0, 70.0)


def test_detect_table_regions_stops_at_height_relative_structural_gap() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            *_data(110.0, "03/02/2026", "Distant", "30.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structural_gap" in regions[0].diagnostics


def test_detect_table_regions_retains_unknown_columns_when_header_is_still_plausible() -> None:
    words = (
        _word("Date", 0.0, 22.0, 10.0),
        _word("Reference", 35.0, 70.0, 10.0),
        _word("Amount", 92.0, 120.0, 10.0),
        *_data(30.0, "01/02/2026", "A7X9", "10.00"),
        *_data(50.0, "02/02/2026", "B8Y0", "20.00"),
    )

    regions = detect_table_regions(_page(words))

    assert len(regions) == 1
    assert tuple(column.role for column in regions[0].table_schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.UNKNOWN,
        ColumnRole.AMOUNT,
    )
    assert "schema:ambiguous_columns:1" in regions[0].diagnostics


def test_detect_table_regions_rejects_prose_and_single_unrepeated_row() -> None:
    prose = _page(
        (
            _word("This", 0.0, 20.0, 10.0),
            _word("is", 24.0, 32.0, 10.0),
            _word("prose", 36.0, 60.0, 10.0),
            _word("Another", 0.0, 30.0, 30.0),
            _word("line", 34.0, 52.0, 30.0),
        )
    )
    single_row = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Only", "10.00"),
        )
    )

    assert detect_table_regions(prose) == ()
    assert detect_table_regions(single_row) == ()


def test_detect_table_regions_does_not_match_date_inside_update_header() -> None:
    page = _page(
        (
            _word("Update", 0.0, 30.0, 10.0),
            _word("Amount", 92.0, 120.0, 10.0),
            _word("Active", 0.0, 30.0, 30.0),
            _word("10.00", 92.0, 120.0, 30.0),
            _word("Pending", 0.0, 30.0, 50.0),
            _word("20.00", 92.0, 120.0, 50.0),
        )
    )

    assert detect_table_regions(page) == ()


def test_detect_table_regions_rebuilds_backwards_hebrew_words_from_glyph_geometry() -> None:
    words = (
        _word("ךיראת", 90.0, 120.0, 10.0),
        _word("קסע תיב", 40.0, 75.0, 10.0),
        _word("םוכס", 0.0, 25.0, 10.0),
        _word("01/02/2026", 90.0, 120.0, 30.0),
        _word("חנות", 40.0, 75.0, 30.0),
        _word("10.00", 0.0, 25.0, 30.0),
        _word("02/02/2026", 90.0, 120.0, 50.0),
        _word("קפה", 40.0, 75.0, 50.0),
        _word("20.00", 0.0, 25.0, 50.0),
    )
    glyphs = (
        *_rtl_glyphs("סכום", 23.0, 10.0),
        *_rtl_glyphs("בית עסק", 73.0, 10.0),
        *_rtl_glyphs("תאריך", 118.0, 10.0),
    )

    regions = detect_table_regions(_page(words, tuple(reversed(glyphs))))

    assert len(regions) == 1
    assert tuple(cell.text for cell in regions[0].header.cells) == (
        "תאריך",
        "בית עסק",
        "סכום",
    )
    assert all(cell.glyphs for cell in regions[0].header.cells)
