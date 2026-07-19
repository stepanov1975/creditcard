from __future__ import annotations

import pytest

from ccparser.evidence import ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.layout.columns import infer_column_roles
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableSchema
from ccparser.layout.regions import (
    _merge_header_rows,
    _merged_header_bands,
    _page_row_key,
    _projection_preserves_table_band_evidence,
    _split_compound_header_cell,
    _split_header_fragment,
    detect_table_regions,
    logical_rows,
)


def _word(text: str, x0: float, x1: float, y: float, *, height: float = 10.0) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + height),
        source="digital",
        confidence=1.0,
    )


def _page(
    words: tuple[Word, ...],
    glyphs: tuple[Glyph, ...] = (),
    *,
    width: float = 130.0,
) -> PageEvidence:
    return PageEvidence(
        page_number=1,
        width=width,
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


def _glyph(char: str, x: float, y: float) -> Glyph:
    return Glyph(
        char=char,
        bbox=(x, y, x + 1.0, y + 6.0),
        origin=(x, y + 5.0),
        font="Synthetic",
        size=6.0,
        source="digital",
        confidence=1.0,
    )


def _assert_lossless_split_provenance(
    source: Cell,
    split_cells: tuple[Cell, ...],
) -> None:
    output_words = tuple(word for cell in split_cells for word in cell.words)
    output_glyphs = tuple(glyph for cell in split_cells for glyph in cell.glyphs)
    assert len(output_words) == len(source.words)
    assert len(output_glyphs) == len(source.glyphs)
    assert all(output_words.count(word) == 1 for word in source.words)
    assert all(output_glyphs.count(glyph) == 1 for glyph in source.glyphs)


def test_page_row_key_distinguishes_overlapping_rows_with_the_same_bbox() -> None:
    first_word = _word("Amount due", 30.0, 140.0, 135.0)
    second_word = _word("סכום כולל", 30.0, 140.0, 135.0)
    first = Row(
        page_number=1,
        bbox=first_word.bbox,
        cells=(
            Cell(
                page_number=1,
                bbox=first_word.bbox,
                text=first_word.text,
                words=(first_word,),
                confidence=1.0,
            ),
        ),
        words=(first_word,),
        confidence=1.0,
    )
    second = Row(
        page_number=1,
        bbox=second_word.bbox,
        cells=(
            Cell(
                page_number=1,
                bbox=second_word.bbox,
                text=second_word.text,
                words=(second_word,),
                confidence=1.0,
            ),
        ),
        words=(second_word,),
        confidence=1.0,
    )

    assert first.bbox == second.bbox
    assert _page_row_key(first) != _page_row_key(second)
    assert _page_row_key(first) == _page_row_key(first.model_copy())
    assert len(frozenset((_page_row_key(first), _page_row_key(second)))) == 2


def test_logical_rows_collects_page_width_glyphs_only_from_the_same_vertical_band() -> None:
    same_band_left = _glyph("$", 122.0, 22.0)
    same_band_right = _glyph("1", 124.0, 22.0)
    other_band = _glyph("9", 124.0, 62.0)

    rows = logical_rows(
        _page(
            (
                _word("First", 10.0, 30.0, 20.0),
                _word("Second", 10.0, 30.0, 60.0),
            ),
            (same_band_right, other_band, same_band_left),
        )
    )

    assert rows[0].glyphs == (same_band_left, same_band_right)
    assert other_band not in rows[0].glyphs
    assert rows[1].glyphs == (other_band,)


def test_logical_rows_assigns_overlapping_glyph_to_nearest_row_once() -> None:
    overlapping = Glyph(
        char="x",
        bbox=(2.0, 28.0, 3.0, 44.0),
        origin=(2.0, 42.0),
        font="Synthetic",
        size=16.0,
        source="digital",
        confidence=1.0,
    )
    rows = logical_rows(
        _page(
            (
                _word("First", 40.0, 70.0, 20.0),
                _word("Tall sidebar", 0.0, 30.0, 22.0, height=22.0),
                _word("Second", 40.0, 70.0, 35.0),
            ),
            (overlapping,),
        )
    )

    assert len(rows) == 2
    assert rows[0].glyphs == (overlapping,)
    assert overlapping not in rows[1].glyphs


def test_table_band_evidence_uses_schema_extent_beyond_narrow_header_text() -> None:
    billed_word = _word("₪10.00", 10.0, 25.0, 30.0)
    description_word = _word("Market", 40.0, 60.0, 30.0)
    sidebar_word = _word("Sidebar", 100.0, 120.0, 30.0)
    billed = Cell(
        page_number=1,
        bbox=billed_word.bbox,
        text=billed_word.text,
        words=(billed_word,),
        confidence=1.0,
    )
    description = Cell(
        page_number=1,
        bbox=description_word.bbox,
        text=description_word.text,
        words=(description_word,),
        confidence=1.0,
    )
    sidebar = Cell(
        page_number=1,
        bbox=sidebar_word.bbox,
        text=sidebar_word.text,
        words=(sidebar_word,),
        confidence=1.0,
    )
    header = Row(
        page_number=1,
        bbox=(30.0, 10.0, 60.0, 20.0),
        cells=(
            Cell(
                page_number=1,
                bbox=(30.0, 10.0, 60.0, 20.0),
                text="Billed amount",
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )
    schema = TableSchema(
        page_number=1,
        bbox=(10.0, 10.0, 60.0, 40.0),
        columns=(
            ColumnSpec(
                index=0,
                page_number=1,
                bbox=(10.0, 10.0, 60.0, 40.0),
                relative_x0=0.0,
                relative_x1=1.0,
                role=ColumnRole.AMOUNT,
                source_cells=header.cells,
                confidence=1.0,
            ),
        ),
        header_cells=header.cells,
        sample_cells=(billed, description),
        confidence=1.0,
    )
    source = Row(
        page_number=1,
        bbox=(10.0, 30.0, 120.0, 40.0),
        cells=(billed, description, sidebar),
        words=(billed_word, description_word, sidebar_word),
        confidence=1.0,
    )
    projected = source.model_copy(
        update={
            "bbox": (10.0, 30.0, 60.0, 40.0),
            "cells": (billed, description),
            "words": (billed_word, description_word),
        }
    )

    assert _projection_preserves_table_band_evidence(source, projected, header, schema) == 1


def test_logical_rows_canonicalizes_visual_order_rtl_word_from_lossless_glyphs() -> None:
    rows = logical_rows(
        _page(
            (_word("תיביר", 60.0, 82.0, 20.0),),
            _rtl_glyphs("ריבית", 80.0, 20.0),
        )
    )

    assert rows[0].cells[0].text == "ריבית"
    assert tuple(word.text for word in rows[0].cells[0].words) == ("ריבית",)
    assert tuple(word.text for word in rows[0].words) == ("ריבית",)


def test_logical_rows_does_not_rewrite_rtl_word_from_non_lossless_glyphs() -> None:
    rows = logical_rows(
        _page(
            (_word("תיביר", 60.0, 82.0, 20.0),),
            _rtl_glyphs("ריביו", 80.0, 20.0),
        )
    )

    assert tuple(word.text for word in rows[0].cells[0].words) == ("תיביר",)
    assert tuple(word.text for word in rows[0].words) == ("תיביר",)


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


def _wide_financial_header(y: float) -> tuple[Word, ...]:
    return (
        _word("Billed amount", 0.0, 10.0, y),
        _word("Exchange rate", 18.0, 28.0, y),
        _word("Conversion date", 36.0, 46.0, y),
        _word("Commission amount", 54.0, 64.0, y),
        _word("Original amount", 72.0, 82.0, y),
        _word("Description", 90.0, 100.0, y),
        _word("Date", 108.0, 120.0, y),
    )


def _foreign_table_header(y: float) -> tuple[Word, ...]:
    return (
        _word("Date", 0.0, 20.0, y),
        _word("Description", 30.0, 55.0, y),
        _word("Original amount", 65.0, 85.0, y),
        _word("Billed amount", 100.0, 125.0, y),
    )


def _foreign_data(
    y: float,
    date: str,
    description: str,
    original_amount: str,
    billed_amount: str,
) -> tuple[Word, ...]:
    return (
        _word(date, 0.0, 20.0, y),
        _word(description, 30.0, 55.0, y),
        _word(original_amount, 65.0, 85.0, y),
        _word(billed_amount, 100.0, 125.0, y),
    )


def _auxiliary_table_header(y: float) -> tuple[Word, ...]:
    return (
        _word("Date", 0.0, 20.0, y),
        _word("Description", 30.0, 55.0, y),
        _word("Detail", 65.0, 85.0, y),
        _word("Amount", 100.0, 125.0, y),
    )


def _auxiliary_data(
    y: float, date: str, description: str, detail: str, amount: str
) -> tuple[Word, ...]:
    return (
        _word(date, 0.0, 20.0, y),
        _word(description, 30.0, 55.0, y),
        _word(detail, 65.0, 85.0, y),
        _word(amount, 100.0, 125.0, y),
    )


def _wide_sparse_data(y: float, *, include_conversion_date: bool) -> tuple[Word, ...]:
    return (
        _word("12.40", 0.0, 10.0, y),
        *((_word("03/02/2026", 36.0, 46.0, y),) if include_conversion_date else ()),
        _word("Market", 90.0, 100.0, y),
        _word("01/02/2026", 108.0, 120.0, y),
    )


def _duplicate_amount_header(y: float, *, explicit_billed: bool) -> tuple[Word, ...]:
    return (
        _word("Billed amount" if explicit_billed else "Amount", 0.0, 8.0, y),
        _word("Commission amount", 16.0, 24.0, y),
        _word("Exchange rate", 32.0, 40.0, y),
        _word("Conversion date", 48.0, 56.0, y),
        _word("Amount", 64.0, 72.0, y),
        _word("Original amount", 80.0, 88.0, y),
        _word("Description", 96.0, 104.0, y),
        _word("Date", 112.0, 120.0, y),
    )


def _duplicate_amount_data(
    y: float,
    *,
    secondary_amount: str | None,
) -> tuple[Word, ...]:
    return (
        _word("12.40", 0.0, 8.0, y),
        _word("0.00", 16.0, 24.0, y),
        _word("3.7000", 32.0, 40.0, y),
        _word("03/02/2026", 48.0, 56.0, y),
        *((_word(secondary_amount, 64.0, 72.0, y),) if secondary_amount is not None else ()),
        _word("4.00", 80.0, 88.0, y),
        _word("Market", 96.0, 104.0, y),
        _word("01/02/2026", 112.0, 120.0, y),
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


def test_detect_table_regions_resumes_repeated_rows_after_total_with_inherited_schema() -> None:
    resumed_first = _data(90.0, "03/02/2026", "Gamma", "30.00")
    resumed_second = _data(110.0, "04/02/2026", "Delta", "40.00")
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *resumed_first,
            *resumed_second,
            _word("Total", 35.0, 72.0, 130.0),
            _word("70.00", 92.0, 120.0, 130.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 2
    first, resumed = regions
    assert resumed.header is first.header
    assert resumed.table_schema is first.table_schema
    assert resumed.bbox == (0.0, 90.0, 120.0, 120.0)
    assert resumed.bbox[1] > 80.0
    assert all("Subtotal" not in cell.text for row in resumed.rows for cell in row.cells)
    assert all(row not in first.rows for row in resumed.rows)
    assert any(
        word is resumed_first[0]
        for row in resumed.rows
        for cell in row.cells
        for word in cell.words
    )
    assert "inherited_schema_after_total" in resumed.diagnostics


def test_detect_table_regions_keeps_sequential_inherited_partitions_disjoint() -> None:
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            *_data(65.0, "03/02/2026", "Gamma", "30.00"),
            *_data(80.0, "04/02/2026", "Delta", "40.00"),
            _word("Subtotal", 35.0, 72.0, 95.0),
            _word("70.00", 92.0, 120.0, 95.0),
            *_data(110.0, "05/02/2026", "Epsilon", "50.00"),
            *_data(125.0, "06/02/2026", "Zeta", "60.00"),
            _word("Total", 35.0, 72.0, 140.0),
            _word("110.00", 92.0, 120.0, 140.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 3
    assert tuple(region.bbox[1] for region in regions) == (5.0, 65.0, 110.0)
    row_ids = [id(row) for region in regions for row in region.rows]
    assert len(row_ids) == len(set(row_ids))
    assert all(
        "Subtotal" not in cell.text
        for region in regions
        for row in region.rows
        for cell in row.cells
    )


def test_detect_table_regions_retries_inherited_schema_after_consecutive_totals() -> None:
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            _word("Total", 35.0, 72.0, 65.0),
            *_data(90.0, "03/02/2026", "Gamma", "30.00"),
            *_data(115.0, "04/02/2026", "Delta", "40.00"),
            *_data(140.0, "05/02/2026", "Epsilon", "50.00"),
        )
    )

    regions = detect_table_regions(page)

    assert tuple(len(region.rows) for region in regions) == (2, 3)
    assert regions[1].header is regions[0].header
    assert "inherited_schema_after_total" in regions[1].diagnostics
    assert "continued_to_page_end" in regions[1].diagnostics
    assert all(
        "Total" not in cell.text and "Subtotal" not in cell.text
        for region in regions
        for row in region.rows
        for cell in row.cells
    )


def test_detect_table_regions_retries_after_weak_partition_ends_at_later_total() -> None:
    weak_row = _data(80.0, "03/02/2026", "Only", "30.00")
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            _word("Total", 35.0, 72.0, 65.0),
            *weak_row,
            _word("Subtotal", 35.0, 72.0, 95.0),
            _word("30.00", 92.0, 120.0, 95.0),
            _word("Total", 35.0, 72.0, 110.0),
            *_data(125.0, "04/02/2026", "Gamma", "40.00"),
            *_data(145.0, "05/02/2026", "Delta", "50.00"),
            *_data(160.0, "06/02/2026", "Epsilon", "60.00"),
        )
    )

    regions = detect_table_regions(page)

    assert tuple(len(region.rows) for region in regions) == (2, 3)
    assert all(
        word is not weak_row[0]
        for region in regions
        for row in region.rows
        for cell in row.cells
        for word in cell.words
    )
    assert regions[1].bbox[1] == 125.0


def test_detect_table_regions_does_not_retry_without_a_later_total_boundary() -> None:
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            _word("Footer", 35.0, 72.0, 65.0),
            *_data(95.0, "03/02/2026", "Gamma", "30.00"),
            *_data(120.0, "04/02/2026", "Delta", "40.00"),
            *_data(145.0, "05/02/2026", "Epsilon", "50.00"),
        )
    )

    assert len(detect_table_regions(page)) == 1


def test_detect_table_regions_lets_new_header_own_rows_after_consecutive_totals() -> None:
    second_header = _header(80.0)
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            _word("Total", 35.0, 72.0, 65.0),
            *second_header,
            *_data(100.0, "03/02/2026", "Gamma", "30.00"),
            *_data(120.0, "04/02/2026", "Delta", "40.00"),
            _word("Total", 35.0, 72.0, 140.0),
            _word("70.00", 92.0, 120.0, 140.0),
        )
    )

    regions = detect_table_regions(page)

    assert tuple(len(region.rows) for region in regions) == (2, 2)
    assert any(word is second_header[0] for cell in regions[1].header.cells for word in cell.words)
    assert "inherited_schema_after_total" not in regions[1].diagnostics


def test_total_amount_replacement_header_owns_reordered_rows() -> None:
    replacement_header = (
        _word("Description", 0.0, 22.0, 65.0),
        _word("Total amount", 35.0, 72.0, 65.0),
        _word("Date", 92.0, 120.0, 65.0),
    )
    first_replacement_row = (
        _word("Gamma", 0.0, 22.0, 85.0),
        _word("30.00", 35.0, 72.0, 85.0),
        _word("03/02/2026", 92.0, 120.0, 85.0),
    )
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            *replacement_header,
            *first_replacement_row,
            _word("Delta", 0.0, 22.0, 105.0),
            _word("40.00", 35.0, 72.0, 105.0),
            _word("04/02/2026", 92.0, 120.0, 105.0),
            _word("Total", 0.0, 22.0, 125.0),
            _word("70.00", 35.0, 72.0, 125.0),
        )
    )

    regions = detect_table_regions(page)

    assert tuple(len(region.rows) for region in regions) == (2, 2)
    assert tuple(column.role for column in regions[1].table_schema.columns) == (
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
        ColumnRole.DATE,
    )
    assert any(
        word is replacement_header[0] for cell in regions[1].header.cells for word in cell.words
    )
    assert any(
        word is first_replacement_row[0]
        for row in regions[1].rows
        for cell in row.cells
        for word in cell.words
    )
    assert "inherited_schema_after_total" not in regions[1].diagnostics


def test_structural_gap_before_later_total_stops_inherited_schema_retry() -> None:
    page = _page(
        (
            *_header(5.0),
            *_data(20.0, "01/02/2026", "Alpha", "10.00"),
            *_data(35.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 50.0),
            _word("30.00", 92.0, 120.0, 50.0),
            *_data(65.0, "03/02/2026", "Only", "30.00"),
            _word("Total", 35.0, 72.0, 120.0),
            _word("30.00", 92.0, 120.0, 120.0),
            *_data(135.0, "04/02/2026", "Gamma", "40.00"),
            *_data(155.0, "05/02/2026", "Delta", "50.00"),
            *_data(170.0, "06/02/2026", "Epsilon", "60.00"),
        )
    )

    assert len(detect_table_regions(page)) == 1


def test_detect_table_regions_allows_inherited_rows_open_only_at_page_end() -> None:
    page_end = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *_data(100.0, "03/02/2026", "Gamma", "30.00"),
            *_data(120.0, "04/02/2026", "Delta", "40.00"),
            *_data(140.0, "05/02/2026", "Epsilon", "50.00"),
        )
    )
    mid_page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *_data(90.0, "03/02/2026", "Gamma", "30.00"),
            *_data(110.0, "04/02/2026", "Delta", "40.00"),
        )
    )

    page_end_regions = detect_table_regions(page_end)

    assert len(page_end_regions) == 2
    assert "continued_to_page_end" in page_end_regions[1].diagnostics
    assert len(detect_table_regions(mid_page)) == 1


def test_detect_table_regions_rejects_weak_single_inherited_row() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *_data(90.0, "03/02/2026", "Only", "30.00"),
            _word("Total", 35.0, 72.0, 110.0),
            _word("30.00", 92.0, 120.0, 110.0),
        )
    )

    assert len(detect_table_regions(page)) == 1


def test_detect_table_regions_accepts_strong_single_inherited_row_bounded_by_total() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            *_wide_sparse_data(30.0, include_conversion_date=True),
            *_wide_sparse_data(50.0, include_conversion_date=True),
            _word("Subtotal", 90.0, 100.0, 70.0),
            _word("24.80", 0.0, 10.0, 70.0),
            _word("12.40", 0.0, 10.0, 90.0),
            _word("3.70", 18.0, 28.0, 90.0),
            _word("03/02/2026", 36.0, 46.0, 90.0),
            _word("4.00", 72.0, 82.0, 90.0),
            _word("Market", 90.0, 100.0, 90.0),
            _word("01/02/2026", 108.0, 120.0, 90.0),
            _word("Total", 90.0, 100.0, 110.0),
            _word("12.40", 0.0, 10.0, 110.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 2
    assert len(regions[1].rows) == 1
    assert "single_row_strong_evidence" in regions[1].diagnostics


def test_detect_table_regions_rejects_inherited_rows_split_by_structural_gap() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *_data(90.0, "03/02/2026", "Gamma", "30.00"),
            *_data(150.0, "04/02/2026", "Distant", "40.00"),
            _word("Total", 35.0, 72.0, 170.0),
            _word("70.00", 92.0, 120.0, 170.0),
        )
    )

    assert len(detect_table_regions(page)) == 1


def test_detect_table_regions_does_not_inherit_points_ledger_rows() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "₪10.00"),
            *_data(50.0, "02/02/2026", "Beta", "₪20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("₪30.00", 92.0, 120.0, 70.0),
            *_data(90.0, "03/02/2026", "נקודה", "100"),
            *_data(110.0, "04/02/2026", "נקודה", "200"),
            _word("Total", 35.0, 72.0, 130.0),
            _word("₪300", 92.0, 120.0, 130.0),
        )
    )

    assert len(detect_table_regions(page)) == 1


def test_detect_table_regions_does_not_reject_point_named_monetary_merchants() -> None:
    page = _page(
        (
            _word("Date", 0.0, 22.0, 10.0),
            _word("Description", 35.0, 72.0, 10.0),
            _word("Billed amount (USD)", 92.0, 120.0, 10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10"),
            *_data(50.0, "02/02/2026", "Beta", "20"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("$30", 92.0, 120.0, 70.0),
            *_data(90.0, "03/02/2026", "Rewards points", "30"),
            *_data(110.0, "04/02/2026", "Loyalty points", "40"),
            _word("Total", 35.0, 72.0, 130.0),
            _word("$70", 92.0, 120.0, 130.0),
        )
    )

    assert len(detect_table_regions(page)) == 2


def test_detect_table_regions_lets_a_new_header_own_its_rows_after_total() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Alpha", "10.00"),
            *_data(50.0, "02/02/2026", "Beta", "20.00"),
            _word("Subtotal", 35.0, 72.0, 70.0),
            _word("30.00", 92.0, 120.0, 70.0),
            *_header(90.0),
            *_data(110.0, "03/02/2026", "Gamma", "30.00"),
            *_data(130.0, "04/02/2026", "Delta", "40.00"),
            _word("Total", 35.0, 72.0, 150.0),
            _word("70.00", 92.0, 120.0, 150.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 2
    assert regions[1].header.bbox[1] == 90.0
    assert "inherited_schema_after_total" not in regions[1].diagnostics


@pytest.mark.parametrize("marker", ('סה"כ', "סה״כ", "סה״כלתאריך", 'סה " כ חיוב'))
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


@pytest.mark.parametrize(
    "marker",
    ("Amount due", "Billing total", "Statement total", "סכום לחיוב"),
)
def test_detect_table_regions_stops_at_supported_statement_total_semantics(marker: str) -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "12.40"),
            *_data(50.0, "03/02/2026", "Cafe", "18.60"),
            _word(marker, 35.0, 72.0, 70.0),
            _word("31.00", 92.0, 120.0, 70.0),
        )
    )

    region = detect_table_regions(page)[0]

    assert "stopped_at_total" in region.diagnostics


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


def test_detect_table_regions_accepts_strong_single_transaction_bounded_by_total() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            _word("12.40", 0.0, 10.0, 30.0),
            _word("3.70", 18.0, 28.0, 30.0),
            _word("03/02/2026", 36.0, 46.0, 30.0),
            _word("4.00", 72.0, 82.0, 30.0),
            _word("Market", 90.0, 100.0, 30.0),
            _word("01/02/2026", 108.0, 120.0, 30.0),
            _word("Total", 90.0, 100.0, 50.0),
            _word("12.40", 0.0, 10.0, 50.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 1
    assert "single_row_strong_evidence" in regions[0].diagnostics
    assert "stopped_at_total" in regions[0].diagnostics


def test_strong_single_transaction_accepts_date_joined_to_description() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            _word("Market01/02/2026", 0.0, 55.0, 30.0),
            _word("$3.00", 65.0, 85.0, 30.0),
            _word("₪11.00", 100.0, 125.0, 30.0),
            _word("Total", 30.0, 55.0, 50.0),
            _word("₪11.00", 100.0, 125.0, 50.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 1
    assert "single_row_strong_evidence" in regions[0].diagnostics


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


def test_detect_table_regions_retains_adjacent_description_continuation() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Long merchant", "10.00"),
            _word("continued name", 35.0, 72.0, 41.0),
            *_data(60.0, "02/02/2026", "Cafe", "20.00"),
            _word("Total", 45.0, 72.0, 80.0),
            _word("30.00", 92.0, 120.0, 80.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(tuple(cell.text for cell in row.cells) for row in regions[0].rows) == (
        ("01/02/2026", "Long merchant", "10.00"),
        ("continued name",),
        ("02/02/2026", "Cafe", "20.00"),
    )
    assert "repeated_rows:2" in regions[0].diagnostics
    assert "continuation_rows:1" in regions[0].diagnostics


def test_detect_table_regions_retains_one_marked_multicell_detail_after_each_transaction() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "10.00"),
            _word("Exchange rate", 0.0, 22.0, 41.0),
            _word("Fee 0.50", 35.0, 72.0, 41.0),
            *_data(60.0, "02/02/2026", "Cafe", "20.00"),
            _word("שער המרה", 0.0, 22.0, 71.0),
            _word("עמלה 0.25", 35.0, 72.0, 71.0),
            _word("Total", 45.0, 72.0, 90.0),
            _word("30.00", 92.0, 120.0, 90.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 4
    assert "repeated_rows:2" in regions[0].diagnostics
    assert "detail_continuation_rows:2" in regions[0].diagnostics


def test_marked_detail_may_populate_secondary_amount_when_billed_band_is_empty() -> None:
    page = _page(
        (
            *_duplicate_amount_header(10.0, explicit_billed=True),
            *_duplicate_amount_data(30.0, secondary_amount=None),
            _word("Rate", 32.0, 40.0, 41.0),
            _word("0.50", 64.0, 72.0, 41.0),
            _word("Discount", 80.0, 88.0, 41.0),
            _word("Fee", 96.0, 104.0, 41.0),
            *_duplicate_amount_data(52.0, secondary_amount=None),
            _word("Total", 96.0, 104.0, 72.0),
            _word("24.80", 0.0, 8.0, 72.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert "subordinate_detail_continuation" in regions[0].rows[1].diagnostics
    assert "detail_continuation_rows:1" in regions[0].diagnostics
    assert "stopped_at_total" in regions[0].diagnostics


def test_sparse_wide_table_retains_proper_hebrew_note_detail() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            *_wide_sparse_data(30.0, include_conversion_date=True),
            _word("USD", 18.0, 28.0, 41.0),
            _word("הערה", 90.0, 100.0, 41.0),
            *_wide_sparse_data(52.0, include_conversion_date=True),
            _word("USD", 18.0, 28.0, 63.0),
            _word("הערה", 90.0, 100.0, 63.0),
            _word("Total", 90.0, 100.0, 83.0),
            _word("24.80", 0.0, 10.0, 83.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 4
    assert all(
        "subordinate_detail_continuation" in row.diagnostics
        for row in (regions[0].rows[1], regions[0].rows[3])
    )
    assert "detail_continuation_rows:2" in regions[0].diagnostics


def test_sparse_wide_table_bridges_single_band_hebrew_note_before_next_row() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            *_wide_sparse_data(30.0, include_conversion_date=True),
            _word("הערה USD", 90.0, 100.0, 41.0),
            *_wide_sparse_data(52.0, include_conversion_date=True),
            _word("Total", 90.0, 100.0, 72.0),
            _word("24.80", 0.0, 10.0, 72.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert "subordinate_detail_continuation" in regions[0].rows[1].diagnostics
    assert "bounded_hebrew_note_detail" in regions[0].rows[1].diagnostics


def test_detect_table_regions_retains_bounded_foreign_conversion_detail_block() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("conversion note", 65.0, 85.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            _word("discount applied", 65.0, 85.0, 72.0),
            _word("special arrangement", 30.0, 55.0, 83.0),
            *_foreign_data(94.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
            _word("Total", 30.0, 55.0, 114.0),
            _word("41.00", 100.0, 125.0, 114.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 6
    assert all("subordinate_detail_continuation" in row.diagnostics for row in regions[0].rows[2:5])
    assert "detail_continuation_rows:3" in regions[0].diagnostics
    assert "stopped_at_total" in regions[0].diagnostics


def test_foreign_detail_block_accepts_proper_hebrew_converted_marker() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("הומר לפי שער יציג", 30.0, 75.0, 61.0),
            _word("עמלת עסקה", 30.0, 75.0, 72.0),
            _word("הנחה מיוחדת", 30.0, 75.0, 83.0),
            _word("הסדר מיוחד", 30.0, 75.0, 94.0),
            _word("כרטיס 8614", 30.0, 75.0, 105.0),
            *_foreign_data(116.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
            _word("unrelated sidebar", 150.0, 185.0, 116.0),
            _word("Total", 30.0, 55.0, 136.0),
            _word("41.00", 100.0, 125.0, 136.0),
        ),
        width=200.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 8
    assert all("subordinate_detail_continuation" in row.diagnostics for row in regions[0].rows[2:7])
    assert "detail_continuation_rows:5" in regions[0].diagnostics


def test_foreign_detail_block_requires_distinct_transaction_currencies() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Local shop", "₪11.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("conversion note", 65.0, 85.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            _word("discount applied", 65.0, 85.0, 72.0),
            *_foreign_data(83.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_issuer_detail_block_accepts_four_rows_without_distinct_currencies() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Local shop", "₪11.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("rate note", 65.0, 85.0, 61.0),
            _word("conversion note", 30.0, 55.0, 72.0),
            _word("Fee", 30.0, 55.0, 83.0),
            _word("discount applied", 65.0, 85.0, 83.0),
            _word("special arrangement", 30.0, 55.0, 94.0),
            *_foreign_data(105.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 7
    assert all("subordinate_detail_continuation" in row.diagnostics for row in regions[0].rows[2:6])
    assert "detail_continuation_rows:4" in regions[0].diagnostics


def test_issuer_detail_block_rejects_three_rows_without_distinct_currencies() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Local shop", "₪11.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("rate note", 65.0, 85.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            _word("discount applied", 65.0, 85.0, 72.0),
            _word("special arrangement", 30.0, 55.0, 83.0),
            *_foreign_data(94.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_issuer_detail_block_rejects_plain_single_amount_table() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "₪10.00"),
            *_data(50.0, "02/02/2026", "Shop", "₪11.00"),
            _word("shipping note", 35.0, 72.0, 61.0),
            _word("Fee", 35.0, 72.0, 72.0),
            _word("promotion", 35.0, 72.0, 83.0),
            _word("customer note", 35.0, 72.0, 94.0),
            *_data(105.0, "03/02/2026", "Cafe", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert "detail_continuation_rows:4" not in regions[0].diagnostics
    assert "continuation_rows:1" in regions[0].diagnostics
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_foreign_detail_block_requires_exact_subordinate_marker() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("conversion note", 65.0, 85.0, 61.0),
            _word("discount", 30.0, 55.0, 72.0),
            _word("special arrangement", 65.0, 85.0, 72.0),
            *_foreign_data(83.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_foreign_detail_block_is_limited_to_four_rows() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("converted", 30.0, 55.0, 61.0),
            _word("conversion note", 65.0, 85.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            _word("discount", 30.0, 55.0, 83.0),
            _word("special", 30.0, 55.0, 94.0),
            _word("fifth detail", 30.0, 55.0, 105.0),
            *_foreign_data(116.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_foreign_detail_block_accepts_fifth_identifier_and_separable_sidebar() -> None:
    sidebar = _word("unrelated sidebar", 150.0, 185.0, 83.0)
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            _word("discount applied", 30.0, 55.0, 83.0),
            sidebar,
            _word("special arrangement", 30.0, 55.0, 94.0),
            _word("card 8614", 30.0, 55.0, 105.0),
            *_foreign_data(116.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
            _word("Total", 30.0, 55.0, 136.0),
            _word("41.00", 100.0, 125.0, 136.0),
        ),
        width=200.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 8
    assert all("subordinate_detail_continuation" in row.diagnostics for row in regions[0].rows[2:7])
    assert "ignored_outside_table_band_cells:1" in regions[0].rows[4].diagnostics
    assert all(sidebar not in cell.words for row in regions[0].rows for cell in row.cells)
    assert "detail_continuation_rows:5" in regions[0].diagnostics
    assert "stopped_at_total" in regions[0].diagnostics


def test_foreign_detail_block_rejects_unprojected_nonspace_glyph() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("converted at issuer rate", 30.0, 55.0, 61.0),
            _word("conversion note", 65.0, 85.0, 61.0),
            _word("Fee", 30.0, 55.0, 72.0),
            *_foreign_data(83.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        ),
        glyphs=(_glyph("x", 160.0, 61.0),),
        width=200.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_exact_fee_marker_is_not_merged_into_foreign_merchant_description() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("Fee", 30.0, 55.0, 61.0),
            _word("special arrangement", 30.0, 55.0, 72.0),
            *_foreign_data(83.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 5
    assert all("subordinate_detail_continuation" in row.diagnostics for row in regions[0].rows[2:4])
    assert "continuation_rows:1" not in regions[0].diagnostics
    assert "detail_continuation_rows:2" in regions[0].diagnostics


def test_foreign_detail_block_uses_normalizer_gap_limit() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "₪10.00", "₪10.00"),
            *_foreign_data(50.0, "02/02/2026", "Foreign shop", "$3.00", "₪11.00"),
            _word("Fee", 30.0, 55.0, 61.0),
            _word("special arrangement", 30.0, 55.0, 87.0),
            *_foreign_data(98.0, "03/02/2026", "Cafe", "₪20.00", "₪20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_detect_table_regions_bridges_one_lossless_auxiliary_fragment() -> None:
    page = _page(
        (
            *_auxiliary_table_header(10.0),
            *_auxiliary_data(30.0, "01/02/2026", "Market", "Food", "₪10.00"),
            *_auxiliary_data(50.0, "02/02/2026", "Hotel", "Travel", "₪20.00"),
            _word("continued", 65.0, 85.0, 61.0),
            *_auxiliary_data(72.0, "03/02/2026", "Cafe", "Food", "₪30.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 4
    assert "subordinate_auxiliary_continuation" in regions[0].rows[2].diagnostics
    assert "auxiliary_continuation_rows:1" in regions[0].diagnostics


def test_detect_table_regions_bridges_split_lossless_auxiliary_fragment() -> None:
    page = _page(
        (
            *_auxiliary_table_header(10.0),
            *_auxiliary_data(30.0, "01/02/2026", "Market", "Food", "₪10.00"),
            *_auxiliary_data(50.0, "02/02/2026", "Hotel", "Travel", "₪20.00"),
            _word("fragment", 35.0, 50.0, 61.0),
            _word("continued", 65.0, 85.0, 61.0),
            *_auxiliary_data(72.0, "03/02/2026", "Cafe", "Food", "₪30.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 4
    assert len(regions[0].rows[2].cells) == 2
    assert "subordinate_auxiliary_continuation" in regions[0].rows[2].diagnostics
    assert "auxiliary_continuation_rows:1" in regions[0].diagnostics


def test_auxiliary_fragment_requires_immediately_following_transaction() -> None:
    page = _page(
        (
            *_auxiliary_table_header(10.0),
            *_auxiliary_data(30.0, "01/02/2026", "Market", "Food", "₪10.00"),
            *_auxiliary_data(50.0, "02/02/2026", "Hotel", "Travel", "₪20.00"),
            _word("first fragment", 65.0, 85.0, 61.0),
            _word("second fragment", 65.0, 85.0, 72.0),
            *_auxiliary_data(83.0, "03/02/2026", "Cafe", "Food", "₪30.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_auxiliary_fragment_rejects_unprojected_nonspace_glyph() -> None:
    page = _page(
        (
            *_auxiliary_table_header(10.0),
            *_auxiliary_data(30.0, "01/02/2026", "Market", "Food", "₪10.00"),
            *_auxiliary_data(50.0, "02/02/2026", "Hotel", "Travel", "₪20.00"),
            _word("continued", 65.0, 85.0, 61.0),
            *_auxiliary_data(72.0, "03/02/2026", "Cafe", "Food", "₪30.00"),
        ),
        glyphs=(_glyph("x", 160.0, 61.0),),
        width=200.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_detail_continuations_do_not_dilute_main_row_column_profiles() -> None:
    page = _page(
        (
            _word("Reference", 0.0, 22.0, 10.0),
            _word("Description", 35.0, 72.0, 10.0),
            _word("Amount", 92.0, 120.0, 10.0),
            *_data(30.0, "01/02/2026", "Market", "10.00"),
            _word("Exchange rate", 0.0, 22.0, 41.0),
            _word("Fee 0.50", 35.0, 72.0, 41.0),
            *_data(60.0, "02/02/2026", "Cafe", "20.00"),
            _word("שער המרה", 0.0, 22.0, 71.0),
            _word("עמלה 0.25", 35.0, 72.0, 71.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(column.role for column in regions[0].table_schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )
    assert len(regions[0].rows) == 4
    assert len(regions[0].table_schema.sample_cells) == 6


def test_description_continuation_does_not_make_one_transaction_row_a_table() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Only merchant", "10.00"),
            _word("continued name", 35.0, 72.0, 41.0),
            _word("Total", 45.0, 72.0, 60.0),
            _word("10.00", 92.0, 120.0, 60.0),
        )
    )

    assert detect_table_regions(page) == ()


def test_description_continuation_allows_bounded_adjacent_band_spill() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            *_wide_sparse_data(30.0, include_conversion_date=False),
            _word("4.00", 72.0, 82.0, 30.0),
            _word("continued merchant", 78.0, 88.0, 41.0),
            *_wide_sparse_data(60.0, include_conversion_date=False),
            _word("5.00", 72.0, 82.0, 60.0),
            _word("Total", 90.0, 100.0, 80.0),
            _word("24.80", 0.0, 10.0, 80.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert "continuation_rows:1" in regions[0].diagnostics


def test_detect_table_regions_merges_an_adjacent_two_line_header_band() -> None:
    page = _page(
        (
            _word("תאריך", 0.0, 22.0, 10.0),
            _word("שם בית עסק", 30.0, 55.0, 10.0),
            _word("סכום", 70.0, 90.0, 10.0),
            _word("סכום", 100.0, 120.0, 10.0),
            _word("עסקה", 0.0, 22.0, 17.5),
            _word("עסקה", 70.0, 90.0, 17.5),
            _word("חיוב", 100.0, 120.0, 17.5),
            _word("01/02/2026", 0.0, 22.0, 32.0),
            _word("Market", 30.0, 55.0, 32.0),
            _word("USD 4.00", 70.0, 90.0, 32.0),
            _word("ILS 14.00", 100.0, 120.0, 32.0),
            _word("02/02/2026", 0.0, 22.0, 47.0),
            _word("Cafe", 30.0, 55.0, 47.0),
            _word("USD 5.00", 70.0, 90.0, 47.0),
            _word("ILS 16.00", 100.0, 120.0, 47.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(cell.text for cell in regions[0].header.cells) == (
        "סכום חיוב",
        "סכום עסקה",
        "שם בית עסק",
        "תאריך עסקה",
    )
    assert len(regions[0].rows) == 2
    assert tuple(column.role for column in regions[0].table_schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    assert "header_rows:2" in regions[0].diagnostics


def test_merge_header_rows_splits_compound_fragment_evidence_between_bands() -> None:
    billed_word = _word("סכום", 0.0, 25.0, 10.0)
    fee_word = _word("סכום", 25.0, 50.0, 10.0)
    header = Row(
        page_number=1,
        bbox=(0.0, 10.0, 50.0, 20.0),
        cells=(
            Cell(
                page_number=1,
                bbox=billed_word.bbox,
                text=billed_word.text,
                words=(billed_word,),
                confidence=1.0,
            ),
            Cell(
                page_number=1,
                bbox=fee_word.bbox,
                text=fee_word.text,
                words=(fee_word,),
                confidence=1.0,
            ),
        ),
        words=(billed_word, fee_word),
        confidence=1.0,
    )
    billing_qualifier = _word("חיוב", 0.0, 25.0, 21.0)
    fee_qualifier = _word("עמלה", 25.0, 50.0, 21.0)
    fragment_cell = Cell(
        page_number=1,
        bbox=(0.0, 21.0, 50.0, 31.0),
        text="חיוב עמלה",
        words=(billing_qualifier, fee_qualifier),
        confidence=1.0,
    )
    fragment = Row(
        page_number=1,
        bbox=fragment_cell.bbox,
        cells=(fragment_cell,),
        words=fragment_cell.words,
        confidence=1.0,
    )

    merged = _merge_header_rows(header, (fragment,))

    assert tuple(cell.text for cell in merged.cells) == (
        "סכום חיוב",
        "סכום עמלה",
    )
    assert all("split_header_fragment" in cell.diagnostics for cell in merged.cells)


def test_merged_header_bands_skips_separable_tall_sidebar_overlay() -> None:
    rows = logical_rows(
        _page(
            (
                _word("Date", 0.0, 20.0, 10.0),
                _word("Description", 30.0, 55.0, 10.0),
                _word("Amount", 65.0, 85.0, 10.0),
                _word("Amount", 100.0, 125.0, 10.0),
                _word("Sidebar", 150.0, 180.0, 10.2, height=26.0),
                _word("Original", 65.0, 85.0, 17.2),
                _word("Billed", 100.0, 125.0, 17.2),
            ),
            width=190.0,
        )
    )

    merged = _merged_header_bands(rows)

    assert len(rows) == 3
    assert "header_rows:2" in merged[0].diagnostics
    assert {cell.text for cell in merged[0].cells} >= {
        "Amount Original",
        "Amount Billed",
    }
    assert merged[1].cells[0].text == "Sidebar"


def test_split_header_fragment_preserves_glyph_corrected_rtl_text_and_all_provenance() -> None:
    header_cells = (
        Cell(page_number=1, bbox=(0.0, 10.0, 55.0, 20.0), text="Left", confidence=1.0),
        Cell(page_number=1, bbox=(65.0, 10.0, 120.0, 20.0), text="Right", confidence=1.0),
    )
    words = (
        _word("בויח", 5.0, 30.0, 21.0),
        _word("הלמע", 90.0, 115.0, 21.0),
    )
    glyphs = (
        *_rtl_glyphs("חיוב", 28.0, 21.0),
        *_rtl_glyphs("סכום", 50.0, 21.0),
        *_rtl_glyphs("עמלה", 112.0, 21.0),
    )
    fragment = Cell(
        page_number=1,
        bbox=(5.0, 21.0, 115.0, 31.0),
        text="בויח הלמע",
        glyphs=glyphs,
        words=words,
        confidence=1.0,
    )

    indexed_splits = _split_header_fragment(fragment, header_cells)
    split_cells = tuple(cell for _, cell in indexed_splits)

    assert tuple(index for index, _ in indexed_splits) == (0, 1)
    assert tuple(cell.text for cell in split_cells) == ("סכום חיוב", "עמלה")
    _assert_lossless_split_provenance(fragment, split_cells)


def test_merged_header_bands_splits_two_strong_amount_phrases_in_one_base_cell() -> None:
    words = (
        _word("Amount", 0.0, 16.0, 10.0),
        _word("charged", 17.0, 32.0, 10.0),
        _word("Commission", 38.0, 54.0, 10.0),
        _word("amount", 55.0, 70.0, 10.0),
    )
    compound = Cell(
        page_number=1,
        bbox=(0.0, 10.0, 70.0, 20.0),
        text="Amount charged Commission amount",
        words=words,
        confidence=1.0,
    )
    header = Row(
        page_number=1,
        bbox=compound.bbox,
        cells=(compound,),
        words=words,
        confidence=1.0,
    )

    split_header = _merged_header_bands((header,))[0]

    assert tuple(cell.text for cell in split_header.cells) == (
        "Amount charged",
        "Commission amount",
    )
    assert tuple(cell.words for cell in split_header.cells) == (
        words[:2],
        words[2:],
    )
    assert all("split_compound_header_cell" in cell.diagnostics for cell in split_header.cells)
    schema = infer_column_roles(
        split_header.cells,
        (
            Cell(
                page_number=1,
                bbox=(0.0, 30.0, 32.0, 40.0),
                text="10.00",
                confidence=1.0,
            ),
            Cell(
                page_number=1,
                bbox=(38.0, 30.0, 70.0, 40.0),
                text="0.00",
                confidence=1.0,
            ),
        ),
    )
    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.AMOUNT,
        ColumnRole.AUXILIARY_AMOUNT,
    )


def test_split_compound_header_preserves_glyph_corrected_rtl_text_and_all_provenance() -> None:
    words = (
        _word("הלמע", 5.0, 19.0, 10.0),
        _word("םוכס", 25.0, 39.0, 10.0),
        _word("בויחל", 54.0, 71.0, 10.0),
        _word("םוכס", 80.0, 93.0, 10.0),
    )
    extra_glyph = Glyph(
        char="*",
        bbox=(-12.0, 10.0, -10.0, 20.0),
        origin=(-10.0, 19.0),
        font="SyntheticHebrew",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    glyphs = (
        extra_glyph,
        *_rtl_glyphs("עמלה", 18.0, 10.0),
        *_rtl_glyphs("סכום", 38.0, 10.0),
        *_rtl_glyphs("לחיוב", 70.0, 10.0),
        *_rtl_glyphs("סכום", 92.0, 10.0),
    )
    compound = Cell(
        page_number=1,
        bbox=(-12.0, 10.0, 93.0, 20.0),
        text="הלמע םוכס בויחל םוכס",
        glyphs=glyphs,
        words=words,
        confidence=1.0,
    )

    split = _split_compound_header_cell(compound)

    assert split is not None
    assert tuple(cell.text for cell in split) == ("סכום עמלה *", "סכום לחיוב")
    _assert_lossless_split_provenance(compound, split)


@pytest.mark.parametrize(
    "word_specs",
    (
        (("Amount", 0.0, 18.0), ("charged", 19.0, 37.0), ("today", 44.0, 60.0)),
        (("Amount", 0.0, 18.0), ("Reference", 26.0, 46.0), ("code", 47.0, 60.0)),
    ),
)
def test_merged_header_bands_does_not_split_one_sided_header_semantics(
    word_specs: tuple[tuple[str, float, float], ...],
) -> None:
    words = tuple(_word(text, x0, x1, 10.0) for text, x0, x1 in word_specs)
    compound = Cell(
        page_number=1,
        bbox=(0.0, 10.0, 60.0, 20.0),
        text=" ".join(word.text for word in words),
        words=words,
        confidence=1.0,
    )
    header = Row(
        page_number=1,
        bbox=compound.bbox,
        cells=(compound,),
        words=words,
        confidence=1.0,
    )

    retained = _merged_header_bands((header,))[0]

    assert retained.cells == (compound,)


def test_detect_table_regions_ignores_rows_entirely_outside_the_header_band() -> None:
    page = _page(
        (
            _word("Date", 30.0, 52.0, 10.0),
            _word("Description", 65.0, 92.0, 10.0),
            _word("Amount", 102.0, 128.0, 10.0),
            Word(
                text="side note",
                bbox=(0.0, 20.0, 20.0, 50.0),
                source="digital",
                confidence=1.0,
            ),
            _word("01/02/2026", 30.0, 52.0, 30.0),
            _word("Market", 65.0, 92.0, 30.0),
            _word("12.00", 102.0, 128.0, 30.0),
            Word(
                text="continued side note",
                bbox=(0.0, 40.0, 20.0, 70.0),
                source="digital",
                confidence=1.0,
            ),
            _word("02/02/2026", 30.0, 52.0, 50.0),
            _word("Cafe", 65.0, 92.0, 50.0),
            _word("18.00", 102.0, 128.0, 50.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(tuple(cell.text for cell in row.cells) for row in regions[0].rows) == (
        ("01/02/2026", "Market", "12.00"),
        ("02/02/2026", "Cafe", "18.00"),
    )
    assert any(
        diagnostic.startswith("ignored_outside_band_rows:") for diagnostic in regions[0].diagnostics
    )


def test_detect_table_regions_projects_compound_data_cells_to_header_bands() -> None:
    page = _page(
        (
            _word("Date", 0.0, 15.0, 10.0),
            _word("Description", 25.0, 55.0, 10.0),
            _word("Amount", 80.0, 110.0, 10.0),
            _word("01/02/2026", 0.0, 22.0, 30.0),
            _word("Market", 25.0, 55.0, 30.0),
            _word("12.00", 112.0, 122.0, 30.0),
            _word("02/02/2026", 0.0, 22.0, 50.0),
            _word("Cafe", 25.0, 55.0, 50.0),
            _word("18.00", 112.0, 122.0, 50.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(tuple(cell.text for cell in row.cells) for row in regions[0].rows) == (
        ("01/02/2026", "Market", "12.00"),
        ("02/02/2026", "Cafe", "18.00"),
    )
    assert tuple(column.role for column in regions[0].table_schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )


def test_header_band_projection_does_not_reimport_an_adjacent_dense_row() -> None:
    page = _page(
        (
            _word("Date", 30.0, 45.0, 0.5),
            _word("Description", 55.0, 70.0, 0.5),
            _word("Amount", 80.0, 100.0, 0.5),
            _word("01/01/2026", 30.0, 45.0, 20.5),
            _word("First", 55.0, 70.0, 20.5),
            _word("10.00", 80.0, 100.0, 20.5),
            _word("note-a", 0.0, 20.0, 23.8, height=13.0),
            _word("02/01/2026", 30.0, 45.0, 31.5),
            _word("Second", 55.0, 70.0, 31.5),
            _word("20.00", 80.0, 100.0, 31.5),
            _word("note-b", 0.0, 20.0, 34.8, height=13.0),
            _word("03/01/2026", 30.0, 45.0, 42.5),
            _word("Third", 55.0, 70.0, 42.5),
            _word("30.00", 80.0, 100.0, 42.5),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert [tuple(cell.text for cell in row.cells) for row in regions[0].rows] == [
        ("01/01/2026", "First", "10.00"),
        ("02/01/2026", "Second", "20.00"),
        ("03/01/2026", "Third", "30.00"),
    ]


def test_detect_table_regions_stops_at_aligned_footer_without_a_valid_amount() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "12.40"),
            *_data(50.0, "03/02/2026", "Cafe", "18.60"),
            _word("Summary", 0.0, 22.0, 70.0),
            _word("Cycle details", 35.0, 72.0, 70.0),
            _word("12.40 18.60", 92.0, 120.0, 70.0),
            _word("Reference", 0.0, 22.0, 90.0),
            _word("Informational footer", 35.0, 72.0, 90.0),
            _word("None", 92.0, 120.0, 90.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_detect_table_regions_skips_bounded_nonfinancial_preamble_before_data() -> None:
    page = _page(
        (
            *_header(10.0),
            _word("Account section", 35.0, 72.0, 35.0),
            _word("Cycle", 0.0, 22.0, 50.0),
            _word("Informational", 35.0, 72.0, 50.0),
            _word("Pending", 92.0, 120.0, 50.0),
            _word("Additional details", 35.0, 72.0, 65.0),
            *_data(80.0, "01/02/2026", "Market", "12.40"),
            *_data(100.0, "03/02/2026", "Cafe", "18.60"),
            _word("Total", 35.0, 72.0, 120.0),
            _word("31.00", 92.0, 120.0, 120.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "ignored_preamble_rows:3" in regions[0].diagnostics


def test_detect_table_regions_skips_bounded_overlaid_ocr_amount_artifacts() -> None:
    page = _page(
        (
            _word("|", 34.0, 35.0, 10.0),
            _word("Amount", 192.0, 229.0, 10.0),
            _word("Description", 332.0, 380.0, 10.0),
            _word("Date", 494.0, 531.0, 10.0),
            _word("WA", 240.0, 260.0, 12.5, height=30.0),
            _word("12.40", 198.0, 230.0, 30.0),
            _word("Market", 332.0, 380.0, 30.0),
            _word("01/02/2026", 494.0, 531.0, 30.0),
            _word("/", 240.0, 260.0, 42.5, height=30.0),
            _word("18.60", 198.0, 230.0, 60.0),
            _word("Cafe", 332.0, 380.0, 60.0),
            _word("03/02/2026", 494.0, 531.0, 60.0),
            _word("Total", 332.0, 380.0, 80.0),
            _word("31.00", 198.0, 230.0, 80.0),
        ),
        width=560.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(tuple(cell.text for cell in row.cells) for row in regions[0].rows) == (
        ("12.40", "Market", "01/02/2026"),
        ("18.60", "Cafe", "03/02/2026"),
    )
    assert "ignored_overlaid_ocr_rows:1" in regions[0].diagnostics


def test_detect_table_regions_does_not_skip_nonoverlaid_invalid_amount_text() -> None:
    page = _page(
        (
            *_header(10.0),
            *_data(30.0, "01/02/2026", "Market", "12.40"),
            *_data(50.0, "03/02/2026", "Cafe", "18.60"),
            _word("Pending", 92.0, 120.0, 70.0),
            *_data(100.0, "05/02/2026", "Hotel", "20.00"),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2
    assert "stopped_at_structure_change" in regions[0].diagnostics


def test_detect_table_regions_ignores_isolated_ocr_punctuation_in_amount_band() -> None:
    def ocr_word(text: str, x0: float, x1: float, y: float) -> Word:
        return _word(text, x0, x1, y).model_copy(update={"source": "ocr"})

    page = _page(
        (
            *_header(10.0),
            ocr_word("01/02/2026", 0.0, 22.0, 30.0),
            ocr_word("Market", 35.0, 72.0, 30.0),
            ocr_word("12.40", 92.0, 110.0, 30.0),
            ocr_word("/", 118.0, 120.0, 30.0),
            ocr_word("03/02/2026", 0.0, 22.0, 50.0),
            ocr_word("Cafe", 35.0, 72.0, 50.0),
            ocr_word("18.60", 92.0, 110.0, 50.0),
            ocr_word("|", 118.0, 120.0, 50.0),
            _word("Total", 35.0, 72.0, 70.0),
            _word("31.00", 92.0, 120.0, 70.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert tuple(row.cells[-1].text for row in regions[0].rows) == ("12.40", "18.60")
    assert all(
        "ignored_isolated_ocr_punctuation:1" in row.cells[-1].diagnostics for row in regions[0].rows
    )


def test_detect_table_regions_retains_bounded_ambiguous_rows_proven_by_repetition() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "$10.00", "₪10.00x"),
            *_foreign_data(50.0, "02/02/2026", "Cafe", "$20.00", "₪20.00x"),
            *_foreign_data(70.0, "03/02/2026", "Hotel", "$30.00", "₪30.00"),
            *_foreign_data(90.0, "04/02/2026", "Train", "$40.00", "₪40.00"),
            _word("Total", 30.0, 55.0, 110.0),
            _word("₪100.00", 100.0, 125.0, 110.0),
        ),
        width=130.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 4
    assert all("ambiguous_leading_transaction" in row.diagnostics for row in regions[0].rows[:2])
    assert "ambiguous_leading_rows:2" in regions[0].diagnostics


def test_detect_table_regions_rejects_unproven_ambiguous_leading_rows() -> None:
    page = _page(
        (
            *_foreign_table_header(10.0),
            *_foreign_data(30.0, "01/02/2026", "Market", "$10.00", "₪10.00x"),
            *_foreign_data(50.0, "02/02/2026", "Cafe", "$20.00", "₪20.00x"),
        ),
        width=130.0,
    )

    assert detect_table_regions(page) == ()


def test_detect_table_regions_uses_proper_transaction_header_context() -> None:
    page = _page(
        (
            _word("עסקה", 0.0, 20.0, 10.0),
            _word("סוג", 30.0, 50.0, 10.0),
            _word("Original amount", 65.0, 85.0, 10.0),
            _word("Billed amount", 100.0, 125.0, 10.0),
            _word("6", 0.0, 20.0, 30.0),
            _word("regular", 30.0, 50.0, 30.0),
            _word("$10.00", 65.0, 85.0, 30.0),
            _word("₪20.00", 100.0, 125.0, 30.0),
            _word("6", 0.0, 20.0, 50.0),
            _word("regular", 30.0, 50.0, 50.0),
            _word("$30.00", 65.0, 85.0, 50.0),
            _word("₪40.00", 100.0, 125.0, 50.0),
            _word("Total", 30.0, 50.0, 70.0),
            _word("₪60.00", 100.0, 125.0, 70.0),
        ),
        width=130.0,
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].rows) == 2


def test_detect_table_regions_rejects_dual_amount_summary_without_transaction_context() -> None:
    page = _page(
        (
            _word("Summary", 0.0, 20.0, 10.0),
            _word("Kind", 30.0, 50.0, 10.0),
            _word("Original amount", 65.0, 85.0, 10.0),
            _word("Billed amount", 100.0, 125.0, 10.0),
            _word("6", 0.0, 20.0, 30.0),
            _word("regular", 30.0, 50.0, 30.0),
            _word("$10.00", 65.0, 85.0, 30.0),
            _word("₪20.00", 100.0, 125.0, 30.0),
            _word("6", 0.0, 20.0, 50.0),
            _word("regular", 30.0, 50.0, 50.0),
            _word("$30.00", 65.0, 85.0, 50.0),
            _word("₪40.00", 100.0, 125.0, 50.0),
        ),
        width=130.0,
    )

    assert detect_table_regions(page) == ()


def test_detect_table_regions_accepts_repeated_sparse_rows_in_wide_financial_schema() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            _word("Current cycle", 90.0, 100.0, 31.0),
            *_wide_sparse_data(46.0, include_conversion_date=True),
            *_wide_sparse_data(66.0, include_conversion_date=True),
            _word("Total", 90.0, 100.0, 86.0),
            _word("24.80", 0.0, 10.0, 86.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert len(regions[0].table_schema.columns) == 7
    assert len(regions[0].rows) == 2
    assert "ignored_preamble_rows:1" in regions[0].diagnostics


def test_detect_table_regions_rejects_three_of_seven_column_near_miss() -> None:
    page = _page(
        (
            *_wide_financial_header(10.0),
            *_wide_sparse_data(40.0, include_conversion_date=False),
            *_wide_sparse_data(60.0, include_conversion_date=False),
        )
    )

    assert detect_table_regions(page) == ()


def test_detect_table_regions_uses_explicit_billed_column_when_secondary_is_empty() -> None:
    page = _page(
        (
            *_duplicate_amount_header(10.0, explicit_billed=True),
            *_duplicate_amount_data(40.0, secondary_amount=None),
            *_duplicate_amount_data(60.0, secondary_amount=None),
            _word("Total", 90.0, 100.0, 80.0),
            _word("24.80", 0.0, 10.0, 80.0),
        )
    )

    regions = detect_table_regions(page)

    assert len(regions) == 1
    assert (
        tuple(column.role for column in regions[0].table_schema.columns).count(ColumnRole.AMOUNT)
        == 2
    )
    assert "secondary_amount_bands_empty" in regions[0].diagnostics


def test_detect_table_regions_rejects_populated_secondary_amount_band() -> None:
    page = _page(
        (
            *_duplicate_amount_header(10.0, explicit_billed=True),
            *_duplicate_amount_data(40.0, secondary_amount="9.00"),
            *_duplicate_amount_data(60.0, secondary_amount="8.00"),
        )
    )

    assert detect_table_regions(page) == ()


def test_detect_table_regions_rejects_empty_secondary_without_explicit_billed_header() -> None:
    page = _page(
        (
            *_duplicate_amount_header(10.0, explicit_billed=False),
            *_duplicate_amount_data(40.0, secondary_amount=None),
            *_duplicate_amount_data(60.0, secondary_amount=None),
        )
    )

    assert detect_table_regions(page) == ()
