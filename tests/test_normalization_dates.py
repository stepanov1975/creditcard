from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from typing import Literal

import pytest

import ccparser.normalization_dates as normalization_dates
from ccparser.date_tokens import DateTokenStyle
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.evidence import Glyph, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import EvidenceReference
from ccparser.normalization_dates import (
    ConversionDateExtraction,
    DateColumnKind,
    DateExtraction,
    extract_conversion_date,
    extract_dates,
    nonmaterial_date_layout_atom_ids,
    parsed_cross_cell_conversion_evidence,
    structural_date_column_kinds,
)
from ccparser.semantic_evidence import EvidenceLedger


def test_normalization_dates_exports_exact_public_contract() -> None:
    assert normalization_dates.__all__ == [
        "BoundaryDateCompletion",
        "ConversionDateExtraction",
        "CrossCellDateEvidence",
        "DateColumnKind",
        "DateExtraction",
        "accepted_conversion_date_atom_ids",
        "adjacent_boundary_date_completion",
        "boundary_date_description_splits",
        "contains_date_cue",
        "cross_cell_date_source_cells",
        "date_column_header_kind",
        "extract_conversion_date",
        "extract_dates",
        "has_proven_unanchored_short_date",
        "is_date_shaped",
        "is_typed_conversion_source",
        "matches_positioned_date_description_residual",
        "matching_date_atom_ids",
        "nonmaterial_date_layout_atom_ids",
        "parsed_cross_cell_conversion_evidence",
        "positioned_date_description_residual_atom_ids",
        "proven_assigned_date_evidence",
        "proven_conversion_rate_residual_atom_ids",
        "proven_date_description_layout_marker_atom_ids",
        "proven_unanchored_short_date_style",
        "structural_date_column_kinds",
    ]


def test_date_extractors_are_real_public_definitions() -> None:
    assert extract_dates.__name__ == "extract_dates"
    assert extract_conversion_date.__name__ == "extract_conversion_date"


def _cell(
    text: str,
    column: int,
    y: float = 30.0,
    *,
    glyphs: tuple[Glyph, ...] = (),
    words: tuple[Word, ...] = (),
) -> Cell:
    x0 = column * 50.0
    return Cell(
        page_number=1,
        bbox=(x0, y, x0 + 40.0, y + 10.0),
        text=text,
        glyphs=glyphs,
        words=words,
        confidence=1.0,
    )


def _glyphs(text: str, x0: float, y: float = 30.0) -> tuple[Glyph, ...]:
    return tuple(
        Glyph(
            char=char,
            bbox=(x0 + index, y, x0 + index + 0.8, y + 10.0),
            origin=(x0 + index, y + 9.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(text)
    )


def _word(
    text: str,
    x0: float,
    x1: float,
    y: float = 30.0,
    *,
    source: str = "digital",
) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source=source,
        confidence=1.0,
    )


def _row(*cells: Cell) -> Row:
    return Row(
        page_number=1,
        bbox=(
            min(cell.bbox[0] for cell in cells),
            min(cell.bbox[1] for cell in cells),
            max(cell.bbox[2] for cell in cells),
            max(cell.bbox[3] for cell in cells),
        ),
        cells=cells,
        confidence=1.0,
    )


def _region(
    roles: tuple[ColumnRole, ...],
    rows: tuple[Row, ...],
    *,
    headers: tuple[str, ...] | None = None,
) -> TableRegion:
    header_texts = headers or tuple(role.value for role in roles)
    header_cells = tuple(_cell(text, index, 10.0) for index, text in enumerate(header_texts))
    columns = tuple(
        ColumnSpec(
            index=index,
            page_number=1,
            bbox=(index * 50.0, 10.0, index * 50.0 + 40.0, 200.0),
            relative_x0=index / len(roles),
            relative_x1=(index + 1) / len(roles),
            role=role,
            source_cells=(header_cells[index],),
            confidence=1.0,
        )
        for index, role in enumerate(roles)
    )
    header = _row(*header_cells)
    return TableRegion(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, max(row.bbox[3] for row in rows)),
        header=header,
        rows=rows,
        table_schema=TableSchema(
            page_number=1,
            bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, 200.0),
            columns=columns,
            header_cells=header_cells,
            sample_cells=tuple(cell for row in rows for cell in row.cells),
            confidence=1.0,
        ),
        confidence=1.0,
    )


def _year_context(style: DateTokenStyle, year: int = 2026) -> DiscoveredDateYearContext:
    return DiscoveredDateYearContext(
        year=year,
        style=style,
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 40.0, 10.0),
                raw_text=f"statement date {year}",
            ),
        ),
        confidence=1.0,
    )


def test_boundary_date_description_split_accepts_exact_reordered_rtl_word() -> None:
    marker = Glyph(
        char="6",
        bbox=(64.7, 30.0, 66.3, 40.0),
        origin=(64.7, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="6 26/06/26 א ב",
        glyphs=(*_glyphs("אב", 39.8), *_glyphs("26/06/26", 55.0), marker),
        words=(
            _word("בא", 39.8, 41.8),
            _word("26/06/26", 55.0, 62.8),
            _word("6", 64.7, 66.3),
        ),
        confidence=1.0,
    )
    row = _row(_cell("Merchant", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    assert normalization_dates.boundary_date_description_splits(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        ledger=EvidenceLedger.from_rows((row,)),
    ) == ((date_cell, None, "א ב"),)


def test_date_extraction_uses_reordered_rtl_boundary_fallback() -> None:
    marker = Glyph(
        char="6",
        bbox=(64.7, 30.0, 66.3, 40.0),
        origin=(64.7, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 70.0, 40.0),
        text="6 26/06/26 א ב",
        glyphs=(*_glyphs("אב", 39.8), *_glyphs("26/06/26", 55.0), marker),
        words=(
            _word("בא", 39.8, 41.8),
            _word("26/06/26", 55.0, 62.8),
            _word("6", 64.7, 66.3),
        ),
        confidence=1.0,
    )
    row = _row(_cell("Merchant", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    extraction = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
        ledger=EvidenceLedger.from_rows((row,)),
    )

    assert extraction.transaction_date == date(2026, 6, 26)
    assert extraction.diagnostics == ()


def test_date_extraction_rejects_boundary_date_outside_date_column() -> None:
    marker = Glyph(
        char="6",
        bbox=(49.3, 30.0, 50.9, 40.0),
        origin=(49.3, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        text="6 26/06/26 Fuel",
        glyphs=(*_glyphs("Fuel", 30.0), *_glyphs("26/06/26", 40.0), marker),
        words=(
            _word("Fuel", 30.0, 33.8),
            _word("26/06/26", 40.0, 47.8),
            _word("6", 49.3, 50.9),
        ),
        confidence=1.0,
    )
    row = _row(_cell("Station", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    extraction = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
        ledger=EvidenceLedger.from_rows((row,)),
    )

    assert extraction.transaction_date is None
    assert "invalid_transaction_date" in extraction.diagnostics


@pytest.mark.parametrize(
    ("marker_font", "marker_width", "marker_x", "marker_word_text"),
    (
        ("Synthetic", 1.6, 64.7, "6"),
        ("SyntheticIcon", 0.8, 64.7, "6"),
        ("SyntheticIcon", 1.6, 70.0, "6"),
        ("SyntheticIcon", 1.6, 64.7, None),
        ("SyntheticIcon", 1.6, 64.7, "7"),
    ),
    ids=("same-font", "ordinary-width", "far-marker", "missing-word", "mismatched-word"),
)
def test_boundary_date_description_split_rejects_unproven_separate_marker(
    marker_font: str,
    marker_width: float,
    marker_x: float,
    marker_word_text: str | None,
) -> None:
    marker = Glyph(
        char="6",
        bbox=(marker_x, 30.0, marker_x + marker_width, 40.0),
        origin=(marker_x, 39.0),
        font=marker_font,
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    words = [
        _word("Fuel", 39.8, 43.8),
        _word("26/06/26", 55.0, 62.8),
    ]
    if marker_word_text is not None:
        words.append(_word(marker_word_text, marker_x, marker_x + marker_width))
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="6 26/06/26 Fuel",
        glyphs=(*_glyphs("Fuel", 39.8), *_glyphs("26/06/26", 55.0), marker),
        words=tuple(words),
        confidence=1.0,
    )
    row = _row(_cell("Station", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    assert (
        normalization_dates.boundary_date_description_splits(
            row,
            region,
            _year_context(DateTokenStyle.DAY_FIRST_SLASH),
            ledger=EvidenceLedger.from_rows((row,)),
        )
        == ()
    )


def test_boundary_date_description_split_rejects_competing_numeric_residual() -> None:
    marker_glyphs = tuple(
        Glyph(
            char=char,
            bbox=(x0, 30.0, x1, 40.0),
            origin=(x0, 39.0),
            font="SyntheticIcon",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for char, x0, x1 in (("6", 64.7, 66.3), ("7", 68.0, 69.6))
    )
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="7 6 26/06/26 Fuel",
        glyphs=(
            *_glyphs("Fuel", 39.8),
            *_glyphs("26/06/26", 55.0),
            *marker_glyphs,
        ),
        words=(
            _word("Fuel", 39.8, 43.8),
            _word("26/06/26", 55.0, 62.8),
            _word("6", 64.7, 66.3),
            _word("7", 68.0, 69.6),
        ),
        confidence=1.0,
    )
    row = _row(_cell("Station", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    assert (
        normalization_dates.boundary_date_description_splits(
            row,
            region,
            _year_context(DateTokenStyle.DAY_FIRST_SLASH),
            ledger=EvidenceLedger.from_rows((row,)),
        )
        == ()
    )


def _cross_cell_region(
    *,
    explicit_conversion_date: str | None = None,
) -> tuple[TableRegion, Cell, Cell]:
    left_column = 3 if explicit_conversion_date is not None else 2
    boundary = left_column * 50.0 + 45.0
    left_physical = "converted to ILS 26/0"
    left = Cell(
        page_number=1,
        bbox=(left_column * 50.0, 30.0, boundary, 60.0),
        text="26/0 converted to ILS",
        glyphs=_glyphs(left_physical, boundary - len(left_physical)),
        confidence=1.0,
    )
    right_column = left_column + 1
    right = Cell(
        page_number=1,
        bbox=(boundary, 30.0, right_column * 50.0 + 40.0, 60.0),
        text="Country . on 6/21",
        glyphs=_glyphs("6/21 - on . Country", boundary + 0.2),
        confidence=1.0,
    )
    roles = [ColumnRole.AMOUNT, ColumnRole.ORIGINAL_AMOUNT]
    cells = [_cell("19.63", 0), _cell("$5.99", 1)]
    if explicit_conversion_date is not None:
        roles.append(ColumnRole.CONVERSION_DATE)
        cells.append(_cell(explicit_conversion_date, 2))
    roles.extend(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        )
    )
    cells.extend(
        (
            left,
            right,
            _cell("Foreign merchant", right_column + 1),
            _cell("24/06/2021", right_column + 2),
        )
    )
    row = _row(*cells)
    return _region(tuple(roles), (row,)), left, right


def _equivalent_date_rate_region(
    *,
    same_date: str = "26.06.21",
    left_date_fragment: str = "26.0",
    right_date_fragment: str = "6.21",
) -> tuple[TableRegion, Cell, Cell, Cell]:
    same_cell = _cell(
        f"Converted on {same_date}",
        2,
        glyphs=_glyphs(f"Converted on {same_date}", 100.0),
    )
    boundary = 195.0
    left_cell = Cell(
        page_number=1,
        bbox=(150.0, 30.0, boundary, 60.0),
        text=f"{left_date_fragment} converted at rate 2.9660",
        glyphs=(
            *_glyphs("exchange rate 2.9660", 150.0, 30.0),
            *_glyphs(
                left_date_fragment,
                boundary - len(left_date_fragment),
                50.0,
            ),
        ),
        confidence=1.0,
    )
    right_cell = Cell(
        page_number=1,
        bbox=(boundary, 30.0, 240.0, 60.0),
        text=f"Country on {right_date_fragment}",
        glyphs=_glyphs(right_date_fragment, boundary + 0.2, 50.0),
        confidence=1.0,
    )
    row = _row(
        _cell("19.63", 0),
        _cell("$5.99", 1),
        same_cell,
        left_cell,
        right_cell,
        _cell("Synthetic merchant", 5),
        _cell("24.06.2021", 6),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion date Exchange rate",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )
    return region, same_cell, left_cell, right_cell


def test_date_result_models_are_frozen_and_slotted() -> None:
    date_result = DateExtraction(None, None, None, (), ())
    conversion_result = ConversionDateExtraction(None, (), frozenset(), frozenset())

    assert DateExtraction.__slots__ == (
        "transaction_date",
        "posting_date",
        "conversion_date",
        "diagnostics",
        "unresolved_conversion_cells",
    )
    assert ConversionDateExtraction.__slots__ == (
        "value",
        "diagnostics",
        "source_cells",
        "source_atom_ids",
    )
    assert not hasattr(date_result, "__dict__")
    assert not hasattr(conversion_result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        date_result.transaction_date = date(2026, 1, 1)
    with pytest.raises(FrozenInstanceError):
        conversion_result.value = date(2026, 1, 1)


def test_date_column_kinds_are_closed_and_preserve_structural_mapping_order() -> None:
    assert hasattr(normalization_dates, "DateColumnKind")
    date_column_kind = normalization_dates.DateColumnKind
    assert tuple(date_column_kind) == (
        date_column_kind.TRANSACTION,
        date_column_kind.POSTING,
    )
    assert tuple(kind.value for kind in date_column_kind) == ("transaction", "posting")

    first = _row(
        _cell("03/02/26", 0, 30.0),
        _cell("01/02/26", 1, 30.0),
        _cell("First", 2, 30.0),
        _cell("2.00", 3, 30.0),
    )
    second = _row(
        _cell("04/02/26", 0, 50.0),
        _cell("04/02/26", 1, 50.0),
        _cell("Second", 2, 50.0),
        _cell("2.00", 3, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Date", "Description", "Amount"),
    )

    kinds = normalization_dates.structural_date_column_kinds(
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
    )

    assert tuple(kinds.items()) == (
        (1, date_column_kind.TRANSACTION),
        (0, date_column_kind.POSTING),
    )
    assert all(type(kind) is date_column_kind for kind in kinds.values())


@pytest.mark.parametrize(
    ("style", "full_token", "short_token"),
    (
        (DateTokenStyle.DAY_FIRST_SLASH, "24/06/2026", "24/06/26"),
        (DateTokenStyle.DAY_FIRST_DOT, "24.06.2026", "24.06.26"),
        (DateTokenStyle.DAY_FIRST_DASH, "24-06-2026", "24-06-26"),
        (DateTokenStyle.YEAR_FIRST_SLASH, "2026/06/24", "26/06/24"),
        (DateTokenStyle.YEAR_FIRST_DOT, "2026.06.24", "26.06.24"),
        (DateTokenStyle.YEAR_FIRST_DASH, "2026-06-24", "26-06-24"),
    ),
)
def test_parse_date_preserves_all_full_and_short_styles(
    style: DateTokenStyle,
    full_token: str,
    short_token: str,
) -> None:
    expected = date(2026, 6, 24)
    full_row = _row(_cell(full_token, 0), _cell("10.00", 1))
    short_row = _row(_cell(short_token, 0), _cell("10.00", 1))
    full_region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (full_row,))
    short_region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (short_row,))

    assert extract_dates(full_row, full_region, None, {}) == DateExtraction(
        expected,
        None,
        None,
        (),
        (),
    )
    assert extract_dates(short_row, short_region, _year_context(style), {}) == DateExtraction(
        expected,
        None,
        None,
        (),
        (),
    )


def test_parse_date_preserves_installment_ambiguity_diagnostic() -> None:
    row = _row(_cell("2/6", 0), _cell("10.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    assert extract_dates(row, region, None, {}) == DateExtraction(
        None,
        None,
        None,
        (
            "invalid_transaction_date",
            "transaction_date:ambiguous_date_or_installment",
        ),
        (),
    )


def test_dates_returns_exact_five_legacy_values() -> None:
    row = _row(
        _cell("24/06/2026", 0),
        _cell("25/06/2026", 1),
        _cell("26/06/2026", 2),
        _cell("10.00", 3),
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DATE,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AMOUNT,
        ),
        (row,),
        headers=("Transaction date", "Posting date", "Conversion date", "Amount"),
    )

    assert extract_dates(row, region, None, {}) == DateExtraction(
        transaction_date=date(2026, 6, 24),
        posting_date=date(2026, 6, 25),
        conversion_date=date(2026, 6, 26),
        diagnostics=(),
        unresolved_conversion_cells=(),
    )


@pytest.mark.parametrize(
    ("raw_text", "words", "expected"),
    (
        (
            "24 / 06 / 26",
            (_word("24 / 06 / 26", 0.0, 40.0, source="ocr"),),
            date(2026, 6, 24),
        ),
        (
            "2716/01/26",
            (_word("2716/01/26", 0.0, 40.0, source="ocr"),),
            date(2026, 1, 16),
        ),
    ),
)
def test_dates_preserves_ocr_spaced_and_contaminated_cell_recovery(
    raw_text: str,
    words: tuple[Word, ...],
    expected: date,
) -> None:
    row = _row(_cell(raw_text, 0, words=words), _cell("10.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(expected, None, None, (), ())


@pytest.mark.parametrize(
    ("logical_text", "word_text"),
    (
        ("25/07/26\u200e", "25/07/26"),
        ("25/07/26", "25/07/26\u200e"),
        ("25/07/26\u200e", "25/07/26\u200e"),
    ),
)
def test_dates_ignore_directional_mark_representation_asymmetry(
    logical_text: str,
    word_text: str,
) -> None:
    row = _row(
        _cell(
            logical_text,
            0,
            words=(_word(word_text, 0.0, 40.0, source="ocr"),),
        ),
        _cell("10.00", 1),
    )
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize("raw_text", ("2\u200b5/07/26", "2\u20625/07/26"))
def test_dates_do_not_join_digits_across_invisible_semantic_boundary(raw_text: str) -> None:
    row = _row(_cell(raw_text, 0), _cell("10.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_preserves_invalid_diagnostic_order_and_unresolved_cell_identity() -> None:
    invalid_conversion = _cell("Unreadable", 1)
    row = _row(_cell("31/02/2026", 0), invalid_conversion, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(row, region, None, {})

    assert result == DateExtraction(
        transaction_date=None,
        posting_date=None,
        conversion_date=None,
        diagnostics=("invalid_transaction_date", "transaction_date:invalid_date"),
        unresolved_conversion_cells=(invalid_conversion,),
    )
    assert result.unresolved_conversion_cells[0] is invalid_conversion


@pytest.mark.parametrize(
    "raw_text",
    ("ref25/06/26x", "1.25/06/26", "25/06/26.1"),
)
def test_explicit_conversion_date_requires_complete_token_boundaries(raw_text: str) -> None:
    conversion_cell = _cell(raw_text, 1)
    row = _row(_cell("24/06/2026", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(
        transaction_date=date(2026, 6, 24),
        posting_date=None,
        conversion_date=None,
        diagnostics=(),
        unresolved_conversion_cells=(conversion_cell,),
    )


def test_explicit_conversion_date_rejects_inconsistent_word_fallback() -> None:
    conversion_cell = _cell(
        "ref25/06/26x",
        1,
        words=(_word("25/06/26", 50.0, 80.0),),
    )
    row = _row(_cell("24/06/2026", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_explicit_conversion_date_accepts_separate_positioned_exchange_rate() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(
        conversion_text,
        1,
        glyphs=_glyphs(conversion_text, 50.0),
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
        ledger=ledger,
    )
    accepted_ids = normalization_dates.accepted_conversion_date_atom_ids(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        explicit_conversion_date=result.conversion_date,
        semantic_extraction=ConversionDateExtraction(None, (), frozenset(), frozenset()),
    )
    date_ids = frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(conversion_cell)
        if candidate.text == "03/02/26"
        for atom_id in candidate.atom_ids
    )
    rate_ids = ledger.atoms_for_cell(conversion_cell) - date_ids

    assert result.conversion_date == date(2026, 2, 3)
    assert result.unresolved_conversion_cells == ()
    assert accepted_ids == date_ids
    assert accepted_ids.isdisjoint(rate_ids)
    assert len(ledger.positioned_decimal_candidates(rate_ids)) == 1


def test_explicit_conversion_date_accepts_two_exact_rtl_reordered_words() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(
        conversion_text,
        1,
        words=(
            _word("2.9430", 52.0, 62.0),
            _word("03/02/26", 72.0, 88.0),
        ),
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date == date(2026, 2, 3)
    assert result.unresolved_conversion_cells == ()


def test_typed_conversion_date_preserves_proven_unanchored_token_evidence() -> None:
    conversion_text = "14/03/26 2.9430"
    conversion_cell = _cell(
        conversion_text,
        1,
        words=(
            _word("2.9430", 52.0, 62.0),
            _word("14/03/26", 72.0, 88.0),
        ),
    )
    first = _row(
        _cell("13/03/26", 0, words=(_word("13/03/26", 0.0, 40.0),)),
        conversion_cell,
        _cell("10.00", 2),
    )
    second = _row(
        _cell(
            "20/03/26",
            0,
            50.0,
            words=(_word("20/03/26", 0.0, 40.0, 50.0),),
        ),
        _cell("20.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((first,))
    date_ids = ledger.fragmented_date_candidates(conversion_cell)[0].atom_ids

    extraction = extract_conversion_date(
        first,
        region,
        ledger,
        None,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=None,
        existing_conversion_date=None,
    )
    accepted_ids = normalization_dates.accepted_conversion_date_atom_ids(
        first,
        region,
        ledger,
        None,
        explicit_conversion_date=None,
        semantic_extraction=extraction,
    )

    assert extraction == ConversionDateExtraction(
        None,
        (),
        frozenset((conversion_cell,)),
        date_ids,
    )
    assert accepted_ids == date_ids


def test_typed_conversion_date_rejects_unanchored_token_in_another_style() -> None:
    conversion_text = "03.14.26 2.9430"
    conversion_cell = _cell(
        conversion_text,
        1,
        words=(
            _word("2.9430", 52.0, 62.0),
            _word("03.14.26", 72.0, 88.0),
        ),
    )
    first = _row(
        _cell("13/03/26", 0, words=(_word("13/03/26", 0.0, 40.0),)),
        conversion_cell,
        _cell("10.00", 2),
    )
    second = _row(
        _cell(
            "20/03/26",
            0,
            50.0,
            words=(_word("20/03/26", 0.0, 40.0, 50.0),),
        ),
        _cell("20.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    extraction = extract_conversion_date(
        first,
        region,
        EvidenceLedger.from_rows((first,)),
        None,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=None,
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_explicit_conversion_date_accepts_rate_spilling_beyond_header_band() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(conversion_text, 1).model_copy(
        update={
            "bbox": (50.0, 30.0, 100.0, 40.0),
            "glyphs": (*_glyphs("03/02/26", 50.0), *_glyphs("2.9430", 92.0)),
        }
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date == date(2026, 2, 3)
    assert result.unresolved_conversion_cells == ()


def test_explicit_conversion_date_accepts_date_spilling_beyond_header_band() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(conversion_text, 1).model_copy(
        update={
            "bbox": (40.0, 30.0, 100.0, 40.0),
            "glyphs": (*_glyphs("03/02/26", 42.0), *_glyphs("2.9430", 82.0)),
        }
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date == date(2026, 2, 3)
    assert result.unresolved_conversion_cells == ()


def test_explicit_conversion_date_rejects_both_components_outside_header_band() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(conversion_text, 1).model_copy(
        update={
            "bbox": (20.0, 30.0, 130.0, 40.0),
            "glyphs": (*_glyphs("03/02/26", 22.0), *_glyphs("2.9430", 112.0)),
        }
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_explicit_conversion_date_rejects_untyped_adjacent_decimal() -> None:
    conversion_text = "03/02/26 999.99"
    conversion_cell = _cell(
        conversion_text,
        1,
        glyphs=_glyphs(conversion_text, 50.0),
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_ordinary_transaction_date_rejects_separate_exchange_rate_residual() -> None:
    raw_text = "03/02/26 2.9430"
    date_cell = _cell(raw_text, 0, glyphs=_glyphs(raw_text, 0.0))
    row = _row(date_cell, _cell("10.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("residual", ("USD", "$", "2.9%", "2.9430 3.0120"))
def test_explicit_conversion_date_rejects_nonexclusive_rate_residual(residual: str) -> None:
    logical_text = f"03/02/26 {residual}"
    conversion_cell = _cell(
        logical_text,
        1,
        glyphs=_glyphs(logical_text, 50.0),
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_explicit_conversion_date_rejects_logical_physical_rate_mismatch() -> None:
    conversion_cell = _cell(
        "03/02/26 2.9430",
        1,
        glyphs=_glyphs("03/02/26 2.9440", 50.0),
    )
    row = _row(_cell("01/02/26", 0), conversion_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_rate_only_explicit_conversion_column_is_not_an_unresolved_date_source() -> None:
    rate_cell = _cell("2.9660", 1)
    row = _row(_cell("24/06/2026", 0), rate_cell, _cell("10.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(
        transaction_date=date(2026, 6, 24),
        posting_date=None,
        conversion_date=None,
        diagnostics=(),
        unresolved_conversion_cells=(),
    )


def test_mixed_date_rate_column_parses_date_and_ignores_rate_as_date_source() -> None:
    conversion_cell = _cell("25/06/26", 1)
    rate_cell = _cell("2.9660", 1)
    row = _row(
        _cell("24/06/2026", 0),
        conversion_cell,
        rate_cell,
        _cell("10.00", 2),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date Exchange rate", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(
        transaction_date=date(2026, 6, 24),
        posting_date=None,
        conversion_date=date(2026, 6, 25),
        diagnostics=(),
        unresolved_conversion_cells=(),
    )


def test_dates_recovers_exact_glyph_backed_overlapping_boundary_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        glyphs=(*_glyphs("MERCHANT", 0.0), *_glyphs("01/02/2026", 60.0)),
        confidence=1.0,
    )
    damaged_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 1/0 2/2 0 2 6",
        confidence=1.0,
    )
    row = _row(compound, damaged_date, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )
    columns = tuple(
        column.model_copy(update={"bbox": bbox})
        for column, bbox in zip(
            region.table_schema.columns,
            (
                (0.0, 10.0, 59.0, 200.0),
                (60.0, 10.0, 100.0, 200.0),
                (110.0, 10.0, 160.0, 200.0),
            ),
            strict=True,
        )
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    assert extract_dates(row, region, None, {}) == DateExtraction(
        date(2026, 2, 1), None, None, (), ()
    )


def test_conversion_date_overlap_recovery_preserves_exact_atom_ids() -> None:
    compound_text = "MERCHANT25/06/2026"
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text=compound_text,
        glyphs=_glyphs(compound_text, 52.0),
        confidence=1.0,
    )
    damaged_conversion = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="2 5/0 6/2 0 2 6",
        confidence=1.0,
    )
    row = _row(
        compound,
        damaged_conversion,
        _cell("4.00", 2),
        _cell("24/06/2026", 3),
    )
    region = _region(
        (
            ColumnRole.DESCRIPTION,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AMOUNT,
            ColumnRole.DATE,
        ),
        (row,),
    )
    columns = tuple(
        column.model_copy(update={"bbox": bbox})
        for column, bbox in zip(
            region.table_schema.columns,
            (
                (0.0, 10.0, 59.0, 200.0),
                (60.0, 10.0, 100.0, 200.0),
                (110.0, 10.0, 160.0, 200.0),
                (150.0, 10.0, 190.0, 200.0),
            ),
            strict=True,
        )
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )
    ledger = EvidenceLedger.from_rows((row,))
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2026)

    extraction = extract_dates(row, region, context, {}, ledger=ledger)
    accepted = normalization_dates.accepted_conversion_date_atom_ids(
        row,
        region,
        ledger,
        context,
        explicit_conversion_date=extraction.conversion_date,
        semantic_extraction=ConversionDateExtraction(None, (), frozenset(), frozenset()),
    )

    assert extraction.conversion_date == date(2026, 6, 25)
    assert extraction.unresolved_conversion_cells == ()
    assert accepted
    assert accepted <= ledger.atoms_for_cell(compound)


def test_dates_completes_one_adjacent_boundary_glyph() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(51.0, 30.0, 60.0, 40.0),
        text="26/01/202",
        glyphs=_glyphs("26/01/202", 51.0),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 78.0, 40.0),
        text="2 merchant",
        glyphs=(*_glyphs("merchant", 0.0), *_glyphs("2", 60.0)),
        confidence=1.0,
    )
    row = _row(description_cell, date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )

    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2022),
        {},
    ) == DateExtraction(
        transaction_date=date(2022, 1, 26),
        posting_date=None,
        conversion_date=None,
        diagnostics=(),
        unresolved_conversion_cells=(),
    )


def test_conversion_date_completes_one_adjacent_boundary_glyph() -> None:
    conversion_cell = Cell(
        page_number=1,
        bbox=(51.0, 30.0, 60.0, 40.0),
        text="25/06/202",
        glyphs=_glyphs("25/06/202", 51.0),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 78.0, 40.0),
        text="6 merchant",
        glyphs=(*_glyphs("merchant", 0.0), *_glyphs("6", 60.0)),
        confidence=1.0,
    )
    row = _row(
        description_cell,
        conversion_cell,
        _cell("4.00", 2),
        _cell("24/06/2026", 3),
    )
    region = _region(
        (
            ColumnRole.DESCRIPTION,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AMOUNT,
            ColumnRole.DATE,
        ),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2026),
        {},
        ledger=ledger,
    )

    assert extraction == DateExtraction(
        transaction_date=date(2026, 6, 24),
        posting_date=None,
        conversion_date=date(2026, 6, 25),
        diagnostics=(),
        unresolved_conversion_cells=(),
    )
    accepted = normalization_dates.accepted_conversion_date_atom_ids(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2026),
        explicit_conversion_date=extraction.conversion_date,
        semantic_extraction=ConversionDateExtraction(None, (), frozenset(), frozenset()),
    )
    assert accepted
    assert accepted & ledger.atoms_for_cell(conversion_cell)
    assert accepted & ledger.atoms_for_cell(description_cell)


def test_dates_recovers_supported_date_description_boundary_split() -> None:
    compound = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        text="01/02/26 Merchant",
        words=(
            _word("01/02/26", 20.0, 48.0, source="ocr"),
            _word("Merchant", 52.0, 90.0, source="ocr"),
        ),
        confidence=0.8,
    )
    row = _row(compound, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 2, 1), None, None, (), ())


def test_dates_rejects_boundary_split_without_positioned_date_boundary() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 70.0, 40.0),
        text="Merchant 25/06/26",
        glyphs=_glyphs("Merchant25/06/26", 0.0),
        confidence=1.0,
    )
    row = _row(compound, _cell("Merchant", 1), _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_preserves_invalid_diagnostic_for_unparsed_boundary_split() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 70.0, 40.0),
        text="Merchant25/06/26",
        glyphs=_glyphs("Merchant25/06/26", 0.0),
        confidence=1.0,
    )
    row = _row(compound, _cell("Merchant", 1), _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_resolves_joined_logical_boundary_from_separated_glyph_source() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 70.0, 40.0),
        text="Merchant25/06/26",
        glyphs=_glyphs("Merchant 25/06/26", 0.0),
        confidence=1.0,
    )
    row = _row(compound, _cell("Merchant", 1), _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 6, 25), None, None, (), ())


def test_dates_rejects_permuted_joined_boundary_glyph_source() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 70.0, 40.0),
        text="Merchant12/03/26",
        glyphs=_glyphs("Merchant 21/03/26", 0.0),
        confidence=1.0,
    )
    row = _row(compound, _cell("Merchant", 1), _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("logical_text", "physical_boundary_text", "physical_date_text"),
    (
        ("Merchant12/03/26", "Merchant", "21/03/26"),
        ("Merchant21/03/2612/03/26", "Merchant", "21/03/26"),
        ("Merchant21/03/26123", "Merchant", "21/03/26"),
        ("Merchant21/03/26REF123", "Merchant", "21/03/26"),
        ("Merchant21/03/26x", "Merchant", "21/03/26"),
        ("Merchant21/03/26REF123", "Merchant", "21/03/26REF321"),
        ("MerchantREF12321/03/26", "MerchantREF321", "21/03/26"),
    ),
)
def test_dates_rejects_incompatible_date_after_duplicate_boundary_glyphs(
    logical_text: str,
    physical_boundary_text: str,
    physical_date_text: str,
) -> None:
    duplicated_description = _glyphs(physical_boundary_text, 30.0)
    description = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 59.0, 40.0),
        text=physical_boundary_text,
        glyphs=duplicated_description,
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(30.0, 30.0, 100.0, 40.0),
        text=logical_text,
        glyphs=(*duplicated_description, *_glyphs(physical_date_text, 61.0)),
        confidence=1.0,
    )
    row = _row(description, date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )
    columns = tuple(
        column.model_copy(update={"bbox": bbox})
        for column, bbox in zip(
            region.table_schema.columns,
            (
                (0.0, 10.0, 59.0, 200.0),
                (60.0, 10.0, 100.0, 200.0),
                (110.0, 10.0, 149.0, 200.0),
            ),
            strict=True,
        )
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_boundary_split_with_second_positioned_date() -> None:
    compound = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 100.0, 40.0),
        text="Merchant 25/06/26",
        glyphs=_glyphs("Merchant 25/06/26 26/06/26", 20.0),
        confidence=1.0,
    )
    row = _row(compound, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "missing_date_cell" in result.diagnostics


def test_dates_rejects_positioned_date_with_alphabetic_logical_residual() -> None:
    date_cell = _cell(
        "ref25/07/26x",
        0,
        words=(
            _word("ref", 0.0, 3.0),
            _word("25/07/26", 10.0, 30.0),
            _word("x", 35.0, 36.0),
        ),
    )
    row = _row(date_cell, _cell("Merchant", 1), _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_accepts_exact_positioned_date_word_when_glyph_spacing_is_fragmented() -> None:
    raw_date = "25/07/26"
    glyphs = tuple(
        Glyph(
            char=char,
            bbox=(index * 8.0, 30.0, index * 8.0 + 0.8, 40.0),
            origin=(index * 8.0, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(raw_date)
    )
    date_cell = _cell(
        raw_date,
        0,
        glyphs=glyphs,
        words=(_word(raw_date, 0.0, 65.0),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())


def test_dates_rejects_permuted_glyphs_behind_exact_date_word() -> None:
    logical_date = "12/03/26"
    physical_date = "21/03/26"
    glyphs = tuple(
        Glyph(
            char=char,
            bbox=(index * 8.0, 30.0, index * 8.0 + 0.8, 40.0),
            origin=(index * 8.0, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(physical_date)
    )
    date_cell = _cell(
        logical_date,
        0,
        glyphs=glyphs,
        words=(_word(logical_date, 0.0, 65.0),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "logical_text",
    (
        "25/07/26 order 123",
        "ref 123 25/07/26",
        "25/07/26 2.9430",
        "25/07/26 $",
    ),
)
def test_dates_rejects_unpositioned_logical_residual(
    logical_text: str,
) -> None:
    date_cell = _cell(
        logical_text,
        0,
        glyphs=_glyphs("25/07/26", 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "physical_text",
    (
        "25/07/26 order 123",
        "ref 123 25/07/26",
        "25/07/26 2.9430",
        "25/07/26 $",
    ),
)
def test_dates_rejects_unrepresented_physical_residual(
    physical_text: str,
) -> None:
    date_cell = _cell(
        "25/07/26",
        0,
        glyphs=_glyphs(physical_text, 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("logical_text", "physical_text"),
    (
        ("25/07/26 ref 123", "25/07/26 ref 321"),
        ("25/07/26 2.9430", "25/07/26 2.9340"),
        ("25/07/26 2.9430", "25/07/26 294.30"),
    ),
)
def test_dates_rejects_permuted_positioned_numeric_residual(
    logical_text: str,
    physical_text: str,
) -> None:
    date_cell = _cell(
        logical_text,
        0,
        glyphs=_glyphs(physical_text, 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_full_cell_ocr_word_with_untyped_integer_residual() -> None:
    date_cell = _cell(
        "17 01/02/26",
        0,
        words=(_word("17 01/02/26", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_accepts_indivisible_ocr_date_with_one_punctuation_character() -> None:
    date_cell = _cell(
        "25/07/26,",
        0,
        words=(_word("25/07/26,", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())


def test_dates_rejects_indivisible_ocr_date_with_punctuation_run() -> None:
    date_cell = _cell(
        "25/07/26,,",
        0,
        words=(_word("25/07/26,,", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_indivisible_ocr_reference_residual() -> None:
    date_cell = _cell(
        "25/07/26 order ABC",
        0,
        words=(_word("25/07/26 order ABC", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_indivisible_ocr_currency_residual() -> None:
    date_cell = _cell(
        "25/07/26 ₪",
        0,
        words=(_word("25/07/26 ₪", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_indivisible_ocr_installment_residual() -> None:
    date_cell = _cell(
        "3/5 25/07/26",
        0,
        words=(_word("3/5 25/07/26", 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "raw_text",
    (
        "25/07/26 order 123",
        "25/07/26 2.9430",
        "25/07/26 $",
        "25/07/26 USD",
        "25/07/26 3/5",
        "17 01/02/26",
    ),
)
def test_dates_rejects_text_only_short_date_with_material_residual(
    raw_text: str,
) -> None:
    row = _row(_cell(raw_text, 0), _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "raw_text",
    (
        "01/02/2026 17",
        "17 01/02/2026",
        "01/02/2026 2.9430",
        "01/02/2026 3/5",
        "01/02/2026 EUR 12.34",
        "USD01/02/2026",
        "01/02/2026$",
    ),
)
def test_dates_rejects_text_only_full_year_date_with_material_residual(
    raw_text: str,
) -> None:
    row = _row(_cell(raw_text, 0), _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("residual", ("#123", "№ 123", "123-456"))
def test_dates_rejects_indivisible_ocr_numeric_reference_residual(
    residual: str,
) -> None:
    raw_text = f"25/07/26 {residual}"
    date_cell = _cell(
        raw_text,
        0,
        words=(_word(raw_text, 0.0, 40.0, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_boundary_date_rejects_indivisible_ocr_description_residual() -> None:
    compound = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        text="25/07/26 Merchant",
        words=(_word("25/07/26 Merchant", 20.0, 90.0, source="ocr"),),
        confidence=0.8,
    )
    row = _row(compound, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "missing_date_cell" in result.diagnostics


def test_boundary_date_rejects_indivisible_ocr_repaired_date_and_description() -> None:
    compound = Cell(
        page_number=1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        text="2716/01/26 Merchant",
        words=(_word("2716/01/26 Merchant", 20.0, 90.0, source="ocr"),),
        confidence=0.8,
    )
    row = _row(compound, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "missing_date_cell" in result.diagnostics


def test_dates_accepts_signature_preserving_hebrew_glyph_reordering() -> None:
    date_cell = _cell(
        ". ב 2 5/0 7/2 6 - לא",
        0,
        glyphs=_glyphs("אל25/07/26 -ב .", 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize("physical_text", ("אב21/03/26", "21/03/26אב"))
def test_dates_rejects_permuted_date_with_hebrew_glyph_reordering(
    physical_text: str,
) -> None:
    date_cell = _cell(
        "אב12/03/26",
        0,
        glyphs=_glyphs(physical_text, 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_accepts_lossless_full_date_glyph_reordering() -> None:
    date_cell = _cell(
        "2 5/0 7/2 6",
        0,
        glyphs=_glyphs("25/07/26", 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())


def test_dates_rejects_permuted_full_date_glyph_reordering() -> None:
    date_cell = _cell(
        "2 1/0 3/2 6",
        0,
        glyphs=_glyphs("12/03/26", 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_signature_preserving_separated_numeric_glyph_residual() -> None:
    date_cell = _cell(
        "625/07/26",
        0,
        glyphs=(*_glyphs("25/07/26", 0.0), *_glyphs("6", 20.0)),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_separated_glyph_date_with_decimal_logical_residual() -> None:
    date_cell = _cell(
        "1.25/07/26",
        0,
        glyphs=(*_glyphs("25/07/26", 0.0), *_glyphs("1.", 20.0)),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_permuted_date_with_separated_numeric_glyph_residual() -> None:
    date_cell = _cell(
        "612/03/26",
        0,
        glyphs=(*_glyphs("21/03/26", 0.0), *_glyphs("6", 20.0)),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_ordered_date_with_separated_numeric_word_residual() -> None:
    date_cell = _cell(
        "625/07/26",
        0,
        words=(
            _word("25/07/26", 0.0, 18.0),
            _word("6", 30.0, 32.0),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("logical_text", "residual_words"),
    (("6", ("6",)), ("6 7", ("6", "7"))),
)
def test_dates_reject_exact_date_word_when_logical_text_is_only_numeric_residual(
    logical_text: str,
    residual_words: tuple[str, ...],
) -> None:
    date_cell = _cell(
        logical_text,
        0,
        words=(
            _word("25/07/26", 0.0, 18.0, source="ocr"),
            *tuple(
                _word(text, 25.0 + index * 6.0, 29.0 + index * 6.0, source="ocr")
                for index, text in enumerate(residual_words)
            ),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("logical_residual", ("1.", "x", "2.9430"))
def test_dates_reject_exact_date_word_when_logical_residual_is_semantic(
    logical_residual: str,
) -> None:
    date_cell = _cell(
        logical_residual,
        0,
        words=(
            _word("25/07/26", 0.0, 18.0, source="ocr"),
            _word(logical_residual, 25.0, 35.0, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def _positioned_date_marker_case(
    logical_text: str,
    marker_text: str,
    *,
    positioned_date: str = "25/07/26",
    date_bbox: tuple[float, float, float, float] = (0.0, 30.0, 18.0, 40.0),
    marker_bbox: tuple[float, float, float, float] = (25.0, 30.0, 29.0, 40.0),
    cell_bbox: tuple[float, float, float, float] = (0.0, 30.0, 40.0, 40.0),
    date_confidence: float = 1.0,
    marker_confidence: float = 0.5,
    date_source: Literal["digital", "ocr"] = "ocr",
    marker_source: Literal["digital", "ocr"] = "ocr",
) -> tuple[Cell, Row, TableRegion, EvidenceLedger]:
    date_cell = Cell(
        page_number=1,
        bbox=cell_bbox,
        text=logical_text,
        words=(
            Word(
                text=positioned_date,
                bbox=date_bbox,
                source=date_source,
                confidence=date_confidence,
            ),
            Word(
                text=marker_text,
                bbox=marker_bbox,
                source=marker_source,
                confidence=marker_confidence,
            ),
        ),
        confidence=1.0,
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    return date_cell, row, region, EvidenceLedger.from_rows((row,))


def _word_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    word_index: int,
) -> frozenset[int]:
    return ledger.atoms_in_bbox(
        ledger.atoms_for_cell(cell),
        cell.words[word_index].bbox,
    )


def _glyph_atom_ids(
    ledger: EvidenceLedger,
    cell: Cell,
    glyphs: tuple[Glyph, ...],
) -> frozenset[int]:
    return frozenset(
        atom_id for atom_id in ledger.atoms_for_cell(cell) if ledger.atoms[atom_id].glyph in glyphs
    )


def test_dates_accept_single_punctuation_glyph_leaking_into_description_band() -> None:
    date_glyphs = _glyphs("25/07/26", 55.0)
    boundary_glyph = Glyph(
        char="/",
        bbox=(35.0, 30.0, 36.0, 40.0),
        origin=(35.0, 39.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(35.0, 30.0, 90.0, 40.0),
        text="/ 25/07/26",
        glyphs=(boundary_glyph, *date_glyphs),
        confidence=1.0,
    )
    row = _row(_cell("Merchant", 0), date_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    expected_date_ids = _glyph_atom_ids(ledger, date_cell, date_glyphs)
    expected_layout_ids = _glyph_atom_ids(ledger, date_cell, (boundary_glyph,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())
    assert normalization_dates.proven_assigned_date_evidence(
        row,
        region,
        region.table_schema.columns[1],
        date_cell,
        ledger,
        date(2026, 7, 25),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
    ) == (expected_date_ids, expected_layout_ids)


@pytest.mark.parametrize(
    ("roles", "boundary_x", "date_x", "cell_bbox"),
    (
        (
            (ColumnRole.DATE, ColumnRole.AMOUNT),
            55.0,
            0.0,
            (0.0, 30.0, 60.0, 40.0),
        ),
        (
            (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
            75.0,
            55.0,
            (50.0, 30.0, 90.0, 40.0),
        ),
    ),
    ids=("amount-band", "inside-date-band"),
)
def test_dates_reject_punctuation_without_description_boundary_leakage(
    roles: tuple[ColumnRole, ...],
    boundary_x: float,
    date_x: float,
    cell_bbox: tuple[float, float, float, float],
) -> None:
    date_glyphs = _glyphs("25/07/26", date_x)
    boundary_glyph = Glyph(
        char="/",
        bbox=(boundary_x, 30.0, boundary_x + 1.0, 40.0),
        origin=(boundary_x, 39.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=cell_bbox,
        text="25/07/26 /",
        glyphs=(*date_glyphs, boundary_glyph),
        confidence=1.0,
    )
    cells = (
        (date_cell, _cell("4.00", 1))
        if len(roles) == 2
        else (_cell("Merchant", 0), date_cell, _cell("4.00", 2))
    )
    row = _row(*cells)
    region = _region(roles, (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def _custom_font_digit_marker_case(
    *,
    marker_font: str = "SyntheticIcon",
    marker_width: float = 1.6,
    marker_x: float = 9.6,
) -> tuple[Cell, Row, TableRegion, EvidenceLedger, tuple[Glyph, ...], Glyph]:
    date_glyphs = _glyphs("25/07/26", 0.0)
    marker_glyph = Glyph(
        char="6",
        bbox=(marker_x, 30.0, marker_x + marker_width, 40.0),
        origin=(marker_x, 39.0),
        font=marker_font,
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = _cell(
        "25/07/266",
        0,
        glyphs=(*date_glyphs, marker_glyph),
        words=(
            _word("25/07/26", 0.0, 8.2),
            _word("6", marker_x, marker_x + marker_width),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    return date_cell, row, region, EvidenceLedger.from_rows((row,)), date_glyphs, marker_glyph


def test_dates_accept_exact_custom_font_digit_marker_beside_date_word() -> None:
    date_cell, row, region, ledger, date_glyphs, marker_glyph = _custom_font_digit_marker_case()
    expected_date_ids = _glyph_atom_ids(ledger, date_cell, date_glyphs)
    expected_layout_ids = _glyph_atom_ids(ledger, date_cell, (marker_glyph,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())
    assert normalization_dates.proven_assigned_date_evidence(
        row,
        region,
        region.table_schema.columns[0],
        date_cell,
        ledger,
        date(2026, 7, 25),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
    ) == (expected_date_ids, expected_layout_ids)


@pytest.mark.parametrize(
    ("marker_font", "marker_width", "marker_x"),
    (
        ("Synthetic", 1.6, 9.6),
        ("SyntheticIcon", 0.8, 9.6),
        ("SyntheticIcon", 1.6, 20.0),
    ),
    ids=("same-font", "ordinary-width", "not-adjacent"),
)
def test_dates_reject_digit_without_custom_font_marker_proof(
    marker_font: str,
    marker_width: float,
    marker_x: float,
) -> None:
    _, row, region, _, _, _ = _custom_font_digit_marker_case(
        marker_font=marker_font,
        marker_width=marker_width,
        marker_x=marker_x,
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def _paired_boundary_and_custom_digit_marker_case(
    *,
    boundary_text: str = "2",
    boundary_font: str = "Synthetic",
) -> tuple[
    Cell,
    Row,
    TableRegion,
    EvidenceLedger,
    tuple[Glyph, ...],
    tuple[Glyph, Glyph],
]:
    date_glyphs = _glyphs("25/07/26", 5.0)
    boundary_glyph = Glyph(
        char=boundary_text,
        bbox=(2.2, 30.0, 3.0, 40.0),
        origin=(2.2, 39.0),
        font=boundary_font,
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    marker_glyph = Glyph(
        char="4",
        bbox=(15.2, 30.0, 16.8, 40.0),
        origin=(15.2, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = _cell(
        f"{boundary_text}25/07/264",
        0,
        glyphs=(boundary_glyph, *date_glyphs, marker_glyph),
        words=(
            _word(boundary_text, 2.2, 3.0),
            _word("25/07/26", 5.0, 13.2),
            _word("4", 15.2, 16.8),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    return (
        date_cell,
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        date_glyphs,
        (boundary_glyph, marker_glyph),
    )


def test_dates_compose_invalid_boundary_digit_and_custom_font_marker_proofs() -> None:
    date_cell, row, region, ledger, date_glyphs, layout_glyphs = (
        _paired_boundary_and_custom_digit_marker_case()
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result == DateExtraction(date(2026, 7, 25), None, None, (), ())
    assert normalization_dates.proven_assigned_date_evidence(
        row,
        region,
        region.table_schema.columns[0],
        date_cell,
        ledger,
        date(2026, 7, 25),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
    ) == (
        _glyph_atom_ids(ledger, date_cell, date_glyphs),
        _glyph_atom_ids(ledger, date_cell, layout_glyphs),
    )


@pytest.mark.parametrize(
    ("boundary_text", "boundary_font"),
    (("3", "Synthetic"), ("2", "SyntheticOther")),
    ids=("different-boundary-digit", "different-boundary-font"),
)
def test_dates_reject_unproven_boundary_digit_beside_custom_font_marker(
    boundary_text: str,
    boundary_font: str,
) -> None:
    _, row, region, _, _, _ = _paired_boundary_and_custom_digit_marker_case(
        boundary_text=boundary_text,
        boundary_font=boundary_font,
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


_PROVEN_VERTICAL_LAYOUT_MARKERS = ("|", "\uff5c", "||", "\uff5c\uff5c")
_APPROVED_BIDI_FORMAT_CONTROLS = (
    "\u200e",  # L
    "\u200f",  # R
    "\u061c",  # AL
    "\u202a",  # LRE
    "\u202b",  # RLE
    "\u202d",  # LRO
    "\u202e",  # RLO
    "\u202c",  # PDF
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
)


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_accept_lossless_date_with_separate_nonmaterial_layout_marker(
    layout_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
    )

    assert nonmaterial_date_layout_atom_ids(
        ledger,
        date_cell,
        _word_atom_ids(ledger, date_cell, 0),
    ) == _word_atom_ids(ledger, date_cell, 1)
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize("layout_marker", ("|", "\uff5c"))
def test_dates_accept_equivalent_exact_glyph_layout_marker_evidence(
    layout_marker: str,
) -> None:
    date_glyphs = _glyphs("25/07/26", 0.0)
    marker_glyph = Glyph(
        char=layout_marker,
        bbox=(25.0, 30.0, 29.0, 40.0),
        origin=(25.0, 39.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=0.5,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text=f"25/07/26 {layout_marker}",
        glyphs=(*date_glyphs, marker_glyph),
        confidence=1.0,
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    candidates = ledger.fragmented_date_candidates(date_cell)

    assert len(candidates) == 1
    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            candidates[0].atom_ids,
        )
        == ledger.atoms_for_cell(date_cell) - candidates[0].atom_ids
    )
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize("bidi_format_control", _APPROVED_BIDI_FORMAT_CONTROLS)
@pytest.mark.parametrize("control_first", (True, False))
def test_dates_accept_vertical_marker_with_exact_bidi_format_signature(
    bidi_format_control: str,
    control_first: bool,
) -> None:
    marker_text = f"{bidi_format_control}|" if control_first else f"|{bidi_format_control}"
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {marker_text}",
        marker_text,
    )

    assert nonmaterial_date_layout_atom_ids(
        ledger,
        date_cell,
        _word_atom_ids(ledger, date_cell, 0),
    ) == _word_atom_ids(ledger, date_cell, 1)
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


def test_dates_accept_glyph_vertical_marker_with_exact_bidi_format_signature() -> None:
    bidi_format_control = "\u200e"
    marker_text = f"{bidi_format_control}|"
    date_glyphs = _glyphs("25/07/26", 0.0)
    marker_glyphs = tuple(
        Glyph(
            char=char,
            bbox=(25.0 + index, 30.0, 25.8 + index, 40.0),
            origin=(25.0 + index, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=0.5,
        )
        for index, char in enumerate(marker_text)
    )
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text=f"25/07/26 {marker_text}",
        glyphs=(*date_glyphs, *marker_glyphs),
        confidence=1.0,
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    candidates = ledger.fragmented_date_candidates(date_cell)

    assert len(candidates) == 1
    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            candidates[0].atom_ids,
        )
        == ledger.atoms_for_cell(date_cell) - candidates[0].atom_ids
    )
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize(
    "semantic_marker",
    (
        "$",
        "\u20aa",
        "%",
        "\u2030",
        "\u2031",
        "+",
        "-",
        "\u2212",
        "*",
        "\u00d7",
        "<",
        ">",
        "=",
        "\u00b1",
        "\u2213",
        "\u2260",
        "\u2264",
        "\u2265",
        "\u00f7",
        "\u2295",
        "\u2190",
        "\u2192",
        "!",
        "?",
        "\u00a9",
        "(",
        ")",
        "[",
        "]",
        "\u2605",
        "\u2062",
        "\u2223",
        "\u2225",
        "\u2980",
        "\u2aee",
        "\u2af2",
    ),
)
def test_dates_reject_lossless_date_with_separate_semantic_marker(
    semantic_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {semantic_marker}",
        semantic_marker,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "layout_marker",
    ("|\uff5c", "\uff5c|", "|*", "|||", "\uff5c\uff5c\uff5c"),
)
def test_dates_reject_mixed_or_overlong_vertical_layout_marker_run(
    layout_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "layout_marker",
    (
        "\u200b|",
        "|\u200b",
        "\u00ad|",
        "|\u00ad",
        "\u200c|",
        "|\u200d",
        "\u2060|",
        "|\ufeff",
        "\u2062|",
        "|\u2063",
        "\u2064|",
    ),
)
def test_dates_reject_vertical_marker_with_bn_or_semantic_invisible_character(
    layout_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("logical_marker", "positioned_marker"),
    (
        ("\u200e|", "|"),
        ("|", "\u200e|"),
        ("\u200e|", "\u200f|"),
        ("\u200e\u200f|", "\u200e|"),
    ),
)
def test_dates_reject_mismatched_bidi_format_control_signature(
    logical_marker: str,
    positioned_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {logical_marker}",
        positioned_marker,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("logical_marker", "positioned_marker"),
    (
        ("\u200b|", "|"),
        ("|\u00ad", "|"),
        ("|", "\u200b|"),
        ("|", "|\u00ad"),
    ),
)
def test_dates_reject_invisible_marker_representation_asymmetry(
    logical_marker: str,
    positioned_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {logical_marker}",
        positioned_marker,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("invisible", ("\u200b", "\u00ad", "\u200c", "\u2062"))
@pytest.mark.parametrize("invisible_first", (False, True))
def test_dates_reject_vertical_glyph_marker_with_attached_invisible_character(
    invisible: str,
    invisible_first: bool,
) -> None:
    date_glyphs = _glyphs("25/07/26", 0.0)
    marker_text = f"{invisible}|" if invisible_first else f"|{invisible}"
    marker_glyphs = tuple(
        Glyph(
            char=char,
            bbox=(25.0 + index, 30.0, 25.8 + index, 40.0),
            origin=(25.0 + index, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=0.5,
        )
        for index, char in enumerate(marker_text)
    )
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text=f"25/07/26 {marker_text}",
        glyphs=(*date_glyphs, *marker_glyphs),
        confidence=1.0,
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    candidates = ledger.fragmented_date_candidates(date_cell)

    assert len(candidates) == 1
    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            candidates[0].atom_ids,
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "semantic_residual",
    ("reference", "2.9430", "| reference", "reference |", "| 6"),
)
def test_nonmaterial_date_layout_rejects_semantic_residual(
    semantic_residual: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {semantic_residual}",
        semantic_residual,
    )
    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_nonmaterial_date_layout_helper_does_not_claim_numeric_layout_residual() -> None:
    date_cell, _, _, ledger = _positioned_date_marker_case("25/07/26 6", "6")

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )


def test_dates_reject_nonmaterial_marker_when_logical_and_physical_residuals_differ() -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case("25/07/26 |", "\uff5c")

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_reject_nonmaterial_marker_beside_permuted_positioned_date() -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        "12/03/26 |",
        "|",
        positioned_date="21/03/26",
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_reject_marker_only_logical_text_with_unrepresented_positioned_date() -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case("|", "|")

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_accept_marker_and_date_side_order_disagreement(layout_marker: str) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"{layout_marker} 25/07/26",
        layout_marker,
    )

    assert nonmaterial_date_layout_atom_ids(
        ledger,
        date_cell,
        _word_atom_ids(ledger, date_cell, 0),
    ) == _word_atom_ids(ledger, date_cell, 1)
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_accept_marker_with_near_y_jitter(layout_marker: str) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
        marker_bbox=(25.0, 29.8, 29.0, 39.8),
        cell_bbox=(0.0, 29.8, 40.0, 40.0),
    )

    assert nonmaterial_date_layout_atom_ids(
        ledger,
        date_cell,
        _word_atom_ids(ledger, date_cell, 0),
    ) == _word_atom_ids(ledger, date_cell, 1)
    assert extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    ) == DateExtraction(date(2026, 7, 25), None, None, (), ())


def test_dates_reject_near_y_jitter_when_residual_components_disagree() -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        "25/07/26 |",
        "\uff5c",
        marker_bbox=(25.0, 29.8, 29.0, 39.8),
        cell_bbox=(0.0, 29.8, 40.0, 40.0),
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_reject_nonmaterial_marker_with_equal_confidence(
    layout_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
        marker_confidence=1.0,
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_reject_nonmaterial_marker_with_mismatched_source(
    layout_marker: str,
) -> None:
    date_cell, row, region, ledger = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
        date_source="digital",
        marker_source="ocr",
    )

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )
    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )
    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    ("date_bbox", "marker_bbox", "cell_bbox", "date_confidence", "marker_confidence"),
    (
        ((0.0, 30.0, 18.0, 40.0), (18.5, 30.0, 22.5, 40.0), (0.0, 30.0, 40.0, 40.0), 1.0, 0.5),
        ((0.0, 30.0, 18.0, 40.0), (25.0, 33.0, 29.0, 43.0), (0.0, 30.0, 40.0, 43.0), 1.0, 0.5),
        ((0.0, 30.0, 18.0, 40.0), (45.0, 30.0, 49.0, 40.0), (0.0, 30.0, 49.0, 40.0), 1.0, 0.5),
        ((-10.0, 30.0, 8.0, 40.0), (25.0, 30.0, 29.0, 40.0), (0.0, 30.0, 40.0, 40.0), 1.0, 0.5),
        ((0.0, 30.0, 18.0, 40.0), (25.0, 30.0, 29.0, 40.0), (0.0, 30.0, 40.0, 40.0), 0.8, 1.0),
    ),
    ids=(
        "touching",
        "misaligned",
        "residual-outside-column",
        "date-outside-cell-and-column",
        "higher-confidence",
    ),
)
@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_reject_nonmaterial_marker_without_strict_positioned_geometry(
    layout_marker: str,
    date_bbox: tuple[float, float, float, float],
    marker_bbox: tuple[float, float, float, float],
    cell_bbox: tuple[float, float, float, float],
    date_confidence: float,
    marker_confidence: float,
) -> None:
    _, row, region, _ = _positioned_date_marker_case(
        f"25/07/26 {layout_marker}",
        layout_marker,
        date_bbox=date_bbox,
        marker_bbox=marker_bbox,
        cell_bbox=cell_bbox,
        date_confidence=date_confidence,
        marker_confidence=marker_confidence,
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_reject_nonmaterial_marker_beside_multiple_positioned_dates() -> None:
    date_cell = _cell(
        "25/07/26 26/07/26 |",
        0,
        words=(
            _word("25/07/26", 0.0, 12.0, source="ocr"),
            _word("26/07/26", 14.0, 26.0, source="ocr"),
            _word("|", 30.0, 34.0, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    ledger = EvidenceLedger.from_rows((row,))

    assert (
        nonmaterial_date_layout_atom_ids(
            ledger,
            date_cell,
            _word_atom_ids(ledger, date_cell, 0),
        )
        == frozenset()
    )


@pytest.mark.parametrize("layout_marker", _PROVEN_VERTICAL_LAYOUT_MARKERS)
def test_dates_reject_marker_only_logical_text_beside_exact_date_word(
    layout_marker: str,
) -> None:
    date_cell = _cell(
        layout_marker,
        0,
        words=(
            _word("25/07/26", 0.0, 18.0, source="ocr"),
            _word(layout_marker, 25.0, 29.0, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


@pytest.mark.parametrize(
    "semantic_marker",
    ("$", "₪", "%", "+", "-", "<", ">", "!", "?", "©", "\u2031", "\u2062"),
)
def test_dates_reject_material_or_invisible_semantic_marker_beside_date_word(
    semantic_marker: str,
) -> None:
    date_cell = _cell(
        semantic_marker,
        0,
        words=(
            _word("25/07/26", 0.0, 18.0, source="ocr"),
            _word(semantic_marker, 25.0, 29.0, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_permuted_date_with_separated_numeric_word_residual() -> None:
    date_cell = _cell(
        "612/03/26",
        0,
        words=(
            _word("21/03/26", 0.0, 18.0),
            _word("6", 30.0, 32.0),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_date_with_separated_decimal_word_residual() -> None:
    date_cell = _cell(
        "1.25/07/26",
        0,
        words=(
            _word("1.", 0.0, 4.0),
            _word("25/07/26", 10.0, 28.0),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_digit_word_contamination_around_exact_nested_date_word() -> None:
    physical_text = "625/07/26"
    date_cell = _cell(
        physical_text,
        0,
        glyphs=(*_glyphs("6", 0.0), *_glyphs("25/07/26", 3.0)),
        words=(
            _word("6", 0.0, 0.8, source="ocr"),
            _word("25/07/26", 3.0, 11.8, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_keep_nested_candidate_strict_when_digit_word_touches_date_run() -> None:
    physical_text = "625/07/26"
    date_cell = _cell(
        physical_text,
        0,
        glyphs=_glyphs(physical_text, 0.0),
        words=(
            _word("6", 0.0, 0.8, source="ocr"),
            _word("25/07/26", 1.0, 9.8, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_keep_nested_candidate_strict_when_extra_digit_is_not_a_separate_word() -> None:
    physical_text = "625/07/26"
    date_cell = _cell(
        physical_text,
        0,
        glyphs=_glyphs(physical_text, 0.0),
        words=(_word(physical_text, 0.0, 9.8, source="ocr"),),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_keep_nested_candidate_strict_when_extra_word_text_mismatches_glyph() -> None:
    physical_text = "725/07/26"
    date_cell = _cell(
        physical_text,
        0,
        glyphs=_glyphs(physical_text, 0.0),
        words=(
            _word("6", 0.0, 0.8, source="ocr"),
            _word("25/07/26", 1.0, 9.8, source="ocr"),
        ),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_dates_rejects_matching_logical_date_with_second_positioned_date() -> None:
    date_cell = _cell(
        "25/07/26",
        0,
        glyphs=_glyphs("25/07/26 26/07/26", 0.0),
    )
    row = _row(date_cell, _cell("4.00", 1))
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_explicit_conversion_date_rejects_positioned_date_with_alphabetic_residual() -> None:
    conversion_cell = _cell(
        "ref25/07/26x",
        1,
        words=(
            _word("ref", 50.0, 53.0),
            _word("25/07/26", 60.0, 80.0),
            _word("x", 85.0, 86.0),
        ),
    )
    row = _row(_cell("24/07/26", 0), conversion_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_explicit_conversion_date_rejects_second_positioned_date() -> None:
    conversion_cell = _cell(
        "25/07/26",
        1,
        glyphs=_glyphs("25/07/26 26/07/26", 50.0),
    )
    row = _row(_cell("24/07/26", 0), conversion_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_explicit_conversion_date_rejects_permuted_exact_word_backing() -> None:
    glyphs = tuple(
        Glyph(
            char=char,
            bbox=(50.0 + index * 8.0, 30.0, 50.8 + index * 8.0, 40.0),
            origin=(50.0 + index * 8.0, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate("21/03/26")
    )
    conversion_cell = _cell(
        "12/03/26",
        1,
        glyphs=glyphs,
        words=(_word("12/03/26", 50.0, 115.0),),
    )
    row = _row(_cell("11/03/26", 0), conversion_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_dates_uses_structurally_inferred_transaction_and_posting_order() -> None:
    first = _row(
        _cell("03/02/26", 0, 30.0),
        _cell("01/02/26", 1, 30.0),
        _cell("First", 2, 30.0),
        _cell("2.00", 3, 30.0),
    )
    second = _row(
        _cell("04/02/26", 0, 50.0),
        _cell("04/02/26", 1, 50.0),
        _cell("Second", 2, 50.0),
        _cell("2.00", 3, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Date", "Description", "Amount"),
    )
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH)

    kinds = structural_date_column_kinds(region, context)

    assert kinds == {
        0: DateColumnKind.POSTING,
        1: DateColumnKind.TRANSACTION,
    }
    assert extract_dates(first, region, context, kinds) == DateExtraction(
        transaction_date=date(2026, 2, 1),
        posting_date=date(2026, 2, 3),
        conversion_date=None,
        diagnostics=(),
        unresolved_conversion_cells=(),
    )


def test_dates_preserves_unresolved_roles_when_inferred_order_conflicts() -> None:
    first = _row(
        _cell("03/02/26", 0, 30.0),
        _cell("01/02/26", 1, 30.0),
        _cell("First", 2, 30.0),
        _cell("2.00", 3, 30.0),
    )
    second = _row(
        _cell("04/02/26", 0, 50.0),
        _cell("06/02/26", 1, 50.0),
        _cell("Second", 2, 50.0),
        _cell("2.00", 3, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Date", "Description", "Amount"),
    )
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH)

    kinds = structural_date_column_kinds(region, context)

    assert kinds == {}
    assert extract_dates(first, region, context, kinds) == DateExtraction(
        transaction_date=None,
        posting_date=None,
        conversion_date=None,
        diagnostics=("unresolved_date_column_roles",),
        unresolved_conversion_cells=(),
    )


def test_dates_preserves_proven_unanchored_short_tokens_without_year_guessing() -> None:
    first = _row(
        _cell("13/03/26", 0, 30.0, words=(_word("13/03/26", 0.0, 40.0, 30.0),)),
        _cell("First", 1, 30.0),
        _cell("2.00", 2, 30.0),
    )
    second = _row(
        _cell("20/03/26", 0, 50.0, words=(_word("20/03/26", 0.0, 40.0, 50.0),)),
        _cell("Second", 1, 50.0),
        _cell("4.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
    )

    assert extract_dates(first, region, None, {}) == DateExtraction(None, None, None, (), ())
    assert extract_dates(second, region, None, {}) == DateExtraction(None, None, None, (), ())


@pytest.mark.parametrize("physical_text", ("14/03/26", None))
def test_dates_rejects_unanchored_short_date_without_exact_positioned_backing(
    physical_text: str | None,
) -> None:
    first_date = _cell(
        "13/03/26",
        0,
        30.0,
        glyphs=_glyphs(physical_text, 0.0, 30.0) if physical_text is not None else (),
    )
    first = _row(first_date, _cell("First", 1, 30.0), _cell("2.00", 2, 30.0))
    second = _row(
        _cell("20/03/26", 0, 50.0, glyphs=_glyphs("20/03/26", 0.0, 50.0)),
        _cell("Second", 1, 50.0),
        _cell("4.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
    )

    result = extract_dates(first, region, None, {})

    assert result.transaction_date is None
    assert "invalid_transaction_date" in result.diagnostics


def test_semantic_conversion_date_preserves_embedded_source_cell_identity() -> None:
    conversion_cell = _cell(
        "Converted on 25/06/26",
        2,
        glyphs=_glyphs("Converted on 25/06/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/06/2026", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original amount", "Conversion detail", "Merchant", "Date"),
    )
    ledger = EvidenceLedger.from_rows((row,))
    source_atom_ids = ledger.fragmented_date_candidates(conversion_cell)[0].atom_ids

    result = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        date(2026, 6, 25),
        (),
        frozenset((conversion_cell,)),
        source_atom_ids,
    )
    assert next(iter(result.source_cells)) is conversion_cell


def test_semantic_conversion_date_uses_exact_word_over_fragmented_glyph_spacing() -> None:
    raw_date = "25/07/26"
    glyphs = tuple(
        Glyph(
            char=char,
            bbox=(100.0 + index * 8.0, 30.0, 100.8 + index * 8.0, 40.0),
            origin=(100.0 + index * 8.0, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(raw_date)
    )
    conversion_cell = _cell(
        f"converted on {raw_date}",
        2,
        glyphs=glyphs,
        words=(_word(raw_date, 100.0, 165.0),),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result.value == date(2026, 7, 25)
    assert result.diagnostics == ()
    assert result.source_atom_ids


def test_semantic_conversion_date_rejects_permuted_exact_word_backing() -> None:
    glyphs = tuple(
        Glyph(
            char=char,
            bbox=(100.0 + index * 8.0, 30.0, 100.8 + index * 8.0, 40.0),
            origin=(100.0 + index * 8.0, 39.0),
            font="Synthetic",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate("21/03/26")
    )
    conversion_cell = _cell(
        "converted on 12/03/26",
        2,
        glyphs=glyphs,
        words=(_word("12/03/26", 100.0, 165.0),),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("11/03/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 3, 11),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_semantic_conversion_date_rejects_unpositioned_reference_residual() -> None:
    conversion_cell = _cell(
        "converted on 25/07/26 order 123",
        2,
        glyphs=_glyphs("25/07/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_explicit_conversion_date_rejects_unrepresented_physical_currency() -> None:
    conversion_cell = _cell(
        "25/07/26",
        1,
        glyphs=_glyphs("25/07/26 $", 50.0),
    )
    row = _row(_cell("24/07/26", 0), conversion_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_semantic_conversion_date_uses_exact_full_cell_ocr_word() -> None:
    conversion_cell = _cell(
        "converted on 25/07/26",
        2,
        words=(_word("converted on 25/07/26", 100.0, 140.0, source="ocr"),),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result.value == date(2026, 7, 25)
    assert result.diagnostics == ()
    assert result.source_atom_ids == EvidenceLedger.from_rows((row,)).atoms_for_cell(
        conversion_cell
    )


def test_semantic_conversion_date_rejects_indivisible_ocr_reference_residual() -> None:
    conversion_cell = _cell(
        "converted on 25/07/26 order ABC",
        2,
        words=(_word("converted on 25/07/26 order ABC", 100.0, 140.0, source="ocr"),),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_semantic_conversion_date_rejects_indivisible_ocr_currency_residual() -> None:
    conversion_cell = _cell(
        "converted on 25/07/26 $",
        2,
        words=(_word("converted on 25/07/26 $", 100.0, 140.0, source="ocr"),),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_explicit_conversion_date_rejects_indivisible_ocr_reference_residual() -> None:
    conversion_cell = _cell(
        "25/07/26 order ABC",
        1,
        words=(_word("25/07/26 order ABC", 50.0, 90.0, source="ocr"),),
    )
    row = _row(_cell("24/07/26", 0), conversion_cell, _cell("4.00", 2))
    region = _region(
        (ColumnRole.DATE, ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        headers=("Date", "Conversion date", "Amount"),
    )

    result = extract_dates(
        row,
        region,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        {},
    )

    assert result.conversion_date is None
    assert result.unresolved_conversion_cells == (conversion_cell,)


def test_conversion_date_cue_cannot_be_composed_across_alternative_renderings() -> None:
    conversion_cell = _cell(
        "25/07/26 converted",
        2,
        glyphs=_glyphs("on 25/07/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(None, (), frozenset(), frozenset())


def test_semantic_conversion_date_rejects_positioned_date_with_alphabetic_residual() -> None:
    conversion_cell = _cell(
        "ref25/07/26x",
        2,
        words=(
            _word("ref", 100.0, 103.0),
            _word("25/07/26", 110.0, 130.0),
            _word("x", 135.0, 136.0),
        ),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Conversion date", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


@pytest.mark.parametrize(
    ("logical_text", "physical_text"),
    (
        ("converted at 25/07/26", "converted at 26/07/26"),
        ("converted at ref25/07/26x", "converted at 25/07/26"),
    ),
)
def test_generic_semantic_conversion_source_rejects_representation_conflict(
    logical_text: str,
    physical_text: str,
) -> None:
    conversion_cell = _cell(
        logical_text,
        2,
        glyphs=_glyphs(physical_text, 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/07/26", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original", "Detail", "Merchant", "Date"),
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 7, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_semantic_conversion_date_preserves_ordered_invalid_diagnostic() -> None:
    conversion_cell = _cell(
        "8/06/26 9/06/26",
        2,
        glyphs=_glyphs("8/06/26 9/06/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/06/2026", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original amount", "Conversion detail", "Merchant", "Date"),
    )

    assert extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    ) == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_valid_semantic_conversion_date_cannot_mask_unreadable_cued_source() -> None:
    valid_cell = _cell(
        "Converted on 25/06/26",
        2,
        glyphs=_glyphs("Converted on 25/06/26", 100.0),
    )
    unreadable_cell = _cell(
        "Converted on unreadable",
        3,
        glyphs=_glyphs("Converted on unreadable", 150.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        valid_cell,
        unreadable_cell,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
    )

    extraction = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_valid_conversion_date_cannot_mask_unreadable_header_typed_source() -> None:
    valid_cell = _cell(
        "25/06/26",
        2,
        glyphs=_glyphs("25/06/26", 100.0),
    )
    unreadable_cell = _cell(
        "unreadable",
        3,
        glyphs=_glyphs("unreadable", 150.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        valid_cell,
        unreadable_cell,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )

    extraction = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


@pytest.mark.parametrize(
    "rate_text",
    (
        "exchange rate 2.9660",
        "exchange rate unreadable",
        "converted at exchange rate 2.9660",
    ),
)
def test_valid_conversion_date_is_not_blocked_by_explicit_rate_source(
    rate_text: str,
) -> None:
    valid_cell = _cell(
        "25/06/26",
        2,
        glyphs=_glyphs("25/06/26", 100.0),
    )
    rate_cell = _cell(
        rate_text,
        3,
        glyphs=_glyphs(rate_text, 150.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        valid_cell,
        rate_cell,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        date(2026, 6, 25),
        (),
        frozenset((valid_cell,)),
        ledger.fragmented_date_candidates(valid_cell)[0].atom_ids,
    )


@pytest.mark.parametrize(
    "metadata_text",
    (
        "converted to ILS",
        "converted at 2.9660",
        "converted to ILS 2.9660",
        "conversion detail ILS",
    ),
)
def test_generic_conversion_metadata_does_not_become_unreadable_date_source(
    metadata_text: str,
) -> None:
    valid_cell = _cell(
        "Converted on 25/06/26",
        2,
        glyphs=_glyphs("Converted on 25/06/26", 100.0),
    )
    metadata_cell = _cell(
        metadata_text,
        3,
        glyphs=_glyphs(metadata_text, 150.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        valid_cell,
        metadata_cell,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original amount", "Detail", "Detail", "Merchant", "Date"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        date(2026, 6, 25),
        (),
        frozenset((valid_cell,)),
        ledger.fragmented_date_candidates(valid_cell)[0].atom_ids,
    )


@pytest.mark.parametrize(
    ("rate_header", "rate_text"),
    (
        ("Conversion detail Exchange rate", "2.9660"),
        ("Conversion date Exchange rate", "rate 2.9660"),
        ("Conversion date Exchange rate", "representative 2.9660"),
    ),
)
def test_rate_typed_header_with_decimal_does_not_block_valid_conversion_date(
    rate_header: str,
    rate_text: str,
) -> None:
    valid_cell = _cell(
        "Converted on 25/06/26",
        2,
        glyphs=_glyphs("Converted on 25/06/26", 100.0),
    )
    rate_cell = _cell(rate_text, 3, glyphs=_glyphs(rate_text, 150.0))
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        valid_cell,
        rate_cell,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            rate_header,
            "Merchant",
            "Date",
        ),
    )
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        date(2026, 6, 25),
        (),
        frozenset((valid_cell,)),
        ledger.fragmented_date_candidates(valid_cell)[0].atom_ids,
    )


def test_conversion_date_uses_authoritative_header_source_outside_column_band() -> None:
    conversion_cell = _cell(
        "25/06/26",
        2,
        glyphs=_glyphs("25/06/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/06/2026", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original amount", "Conversion detail", "Merchant", "Date"),
    )
    header_cells = list(region.table_schema.header_cells)
    source_header = header_cells[2].model_copy(update={"bbox": (500.0, 10.0, 540.0, 20.0)})
    header_cells[2] = source_header
    columns = list(region.table_schema.columns)
    columns[2] = columns[2].model_copy(update={"source_cells": (source_header,)})
    schema = region.table_schema.model_copy(
        update={"columns": tuple(columns), "header_cells": tuple(header_cells)}
    )
    header = region.header.model_copy(update={"cells": tuple(header_cells)})
    region = region.model_copy(update={"header": header, "table_schema": schema})
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        date(2026, 6, 25),
        (),
        frozenset((conversion_cell,)),
        ledger.fragmented_date_candidates(conversion_cell)[0].atom_ids,
    )


@pytest.mark.parametrize("reference_text", ("Reference 25/06/26", "Order dated 25/06/26"))
def test_untyped_unknown_date_does_not_become_conversion_evidence(
    reference_text: str,
) -> None:
    reference_cell = _cell(
        reference_text,
        2,
        glyphs=_glyphs(reference_text, 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        reference_cell,
        _cell("Foreign merchant", 3),
        _cell("24/06/2026", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=("Amount", "Original amount", "Reference", "Merchant", "Date"),
    )

    extraction = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(None, (), frozenset(), frozenset())


def test_conversion_date_uses_unique_nearby_orientation_when_statement_style_disagrees() -> None:
    conversion_cell = _cell(
        "25/06/26",
        2,
        glyphs=_glyphs("25/06/26", 100.0),
    )
    row = _row(
        _cell("15.49", 0),
        _cell("$5.15", 1),
        conversion_cell,
        _cell("Foreign merchant", 3),
        _cell("24/06/2026", 4),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
    )

    extraction = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.YEAR_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction.value == date(2026, 6, 25)
    assert extraction.diagnostics == ()
    assert extraction.source_atom_ids


def test_semantic_conversion_date_preserves_cross_cell_sources() -> None:
    region, left, right = _cross_cell_region()
    row = region.rows[0]
    ledger = EvidenceLedger.from_rows((row,))

    result = extract_conversion_date(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2021),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2021, 6, 24),
        existing_conversion_date=None,
    )
    cross_cell_evidence = parsed_cross_cell_conversion_evidence(
        row,
        region,
        ledger,
        _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2021),
        date(2021, 6, 24),
    )[0][1]

    assert result == ConversionDateExtraction(
        date(2021, 6, 26),
        (),
        frozenset((left, right)),
        cross_cell_evidence.atom_ids,
    )
    assert any(source is left for source in result.source_cells)
    assert any(source is right for source in result.source_cells)


@pytest.mark.parametrize(
    ("left_logical_fragment", "right_logical_fragment", "left_physical"),
    (
        ("12/0", "3/26", "converted to ILS 21/0"),
        ("21/0", "4/26", "converted to ILS 21/0"),
        ("21/0 12/0", "3/26", "converted to ILS 21/0"),
        ("REF123 21/0", "3/26", "converted to ILS 21/0"),
        ("21/0", "3/26 4/26", "converted to ILS 21/0"),
        ("REF123 21/0", "3/26", "REF321 converted to ILS 21/0"),
    ),
)
def test_cross_cell_conversion_date_rejects_permuted_physical_fragment(
    left_logical_fragment: str,
    right_logical_fragment: str,
    left_physical: str,
) -> None:
    boundary = 145.0
    left = Cell(
        page_number=1,
        bbox=(100.0, 30.0, boundary, 60.0),
        text=f"{left_logical_fragment} converted to ILS",
        glyphs=_glyphs(left_physical, boundary - len(left_physical), 30.0),
        confidence=1.0,
    )
    right = Cell(
        page_number=1,
        bbox=(boundary, 30.0, 190.0, 60.0),
        text=f"Country on {right_logical_fragment}",
        glyphs=_glyphs("3/26 - on Country", boundary + 0.2, 30.0),
        confidence=1.0,
    )
    row = _row(
        _cell("19.63", 0),
        _cell("$5.99", 1),
        left,
        right,
        _cell("Foreign merchant", 4),
        _cell("11/03/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )
    ledger = EvidenceLedger.from_rows((row,))
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH)

    assert (
        parsed_cross_cell_conversion_evidence(
            row,
            region,
            ledger,
            context,
            date(2026, 3, 11),
        )
        == ()
    )
    assert extract_conversion_date(
        row,
        region,
        ledger,
        context,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 3, 11),
        existing_conversion_date=None,
    ) == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


@pytest.mark.parametrize(
    ("left_text", "right_text"),
    (
        ("ref25/", "06/26"),
        ("25/", "06/26x"),
        ("1.25/", "06/26"),
        ("25/", "06/26.1"),
    ),
)
def test_cross_cell_conversion_date_requires_alphanumeric_token_boundaries(
    left_text: str,
    right_text: str,
) -> None:
    boundary = 145.0
    left = Cell(
        page_number=1,
        bbox=(100.0, 30.0, boundary, 60.0),
        text=left_text,
        glyphs=_glyphs(left_text, boundary - len(left_text)),
        confidence=1.0,
    )
    right = Cell(
        page_number=1,
        bbox=(boundary, 30.0, 190.0, 60.0),
        text=right_text,
        glyphs=_glyphs(right_text, boundary + 0.2),
        confidence=1.0,
    )
    row = _row(
        _cell("19.63", 0),
        _cell("$5.99", 1),
        left,
        right,
        _cell("Foreign merchant", 4),
        _cell("24/06/2026", 5),
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )
    ledger = EvidenceLedger.from_rows((row,))
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH)

    assert (
        parsed_cross_cell_conversion_evidence(
            row,
            region,
            ledger,
            context,
            date(2026, 6, 24),
        )
        == ()
    )
    assert extract_conversion_date(
        row,
        region,
        ledger,
        context,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    ) == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )


def test_semantic_conversion_date_exposes_conflict_with_explicit_date() -> None:
    region, left, right = _cross_cell_region(explicit_conversion_date="25/06/2021")
    row = region.rows[0]
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2021)
    explicit = extract_dates(row, region, context, {})

    ledger = EvidenceLedger.from_rows((row,))
    semantic = extract_conversion_date(
        row,
        region,
        ledger,
        context,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=explicit.transaction_date,
        existing_conversion_date=explicit.conversion_date,
    )

    assert explicit == DateExtraction(
        transaction_date=date(2021, 6, 24),
        posting_date=None,
        conversion_date=date(2021, 6, 25),
        diagnostics=(),
        unresolved_conversion_cells=(),
    )
    cross_cell_evidence = parsed_cross_cell_conversion_evidence(
        row,
        region,
        ledger,
        context,
        explicit.transaction_date,
    )[0][1]
    assert semantic == ConversionDateExtraction(
        date(2021, 6, 26),
        (),
        frozenset((left, right)),
        cross_cell_evidence.atom_ids,
    )
    assert semantic.value != explicit.conversion_date

    accepted_atom_ids = normalization_dates.accepted_conversion_date_atom_ids(
        row,
        region,
        ledger,
        context,
        explicit_conversion_date=explicit.conversion_date,
        semantic_extraction=semantic,
    )
    explicit_cell = next(
        cell
        for column in region.table_schema.columns
        if column.role is ColumnRole.CONVERSION_DATE
        for cell in row.cells
        if column.bbox[0] <= (cell.bbox[0] + cell.bbox[2]) / 2 <= column.bbox[2]
    )
    explicit_atom_ids = normalization_dates.matching_date_atom_ids(
        ledger,
        explicit_cell,
        explicit.conversion_date,
        context,
    )

    assert accepted_atom_ids == explicit_atom_ids
    assert accepted_atom_ids
    assert accepted_atom_ids.isdisjoint(semantic.source_atom_ids)


def test_equivalent_same_and_cross_cell_conversion_sources_merge_exact_evidence() -> None:
    region, same_cell, left_cell, right_cell = _equivalent_date_rate_region()
    row = region.rows[0]
    ledger = EvidenceLedger.from_rows((row,))
    context = _year_context(DateTokenStyle.DAY_FIRST_DOT, 2021)
    same_cell_atom_ids = ledger.fragmented_date_candidates(same_cell)[0].atom_ids
    cross_cell_atom_ids = parsed_cross_cell_conversion_evidence(
        row,
        region,
        ledger,
        context,
        date(2021, 6, 24),
    )[0][1].atom_ids

    extraction = extract_conversion_date(
        row,
        region,
        ledger,
        context,
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2021, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        date(2021, 6, 26),
        (),
        frozenset((same_cell, left_cell, right_cell)),
        same_cell_atom_ids | cross_cell_atom_ids,
    )


@pytest.mark.parametrize(
    ("left_date_fragment", "right_date_fragment"),
    (("32.0", "6.21"), ("25.0", "6.21")),
)
def test_valid_conversion_source_cannot_mask_invalid_or_conflicting_raw_source(
    left_date_fragment: str,
    right_date_fragment: str,
) -> None:
    region, _, _, _ = _equivalent_date_rate_region(
        left_date_fragment=left_date_fragment,
        right_date_fragment=right_date_fragment,
    )
    row = region.rows[0]

    extraction = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_DOT, 2021),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2021, 6, 24),
        existing_conversion_date=None,
    )

    assert extraction == ConversionDateExtraction(
        None,
        ("unparsed_conversion_date_candidate",),
        frozenset(),
        frozenset(),
    )
