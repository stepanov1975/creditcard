from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

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
    cross_cell_date_tokens,
    extract_conversion_date,
    extract_dates,
    parse_date,
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
        "adjacent_boundary_date_completion",
        "boundary_date_description_splits",
        "contains_date_cue",
        "cross_cell_date_source_cells",
        "cross_cell_date_tokens",
        "date_column_header_kind",
        "extract_conversion_date",
        "extract_dates",
        "has_proven_unanchored_short_date",
        "is_date_shaped",
        "matching_date_atom_ids",
        "parse_date",
        "parsed_cross_cell_conversion_evidence",
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


def test_date_result_models_are_frozen_and_slotted() -> None:
    date_result = DateExtraction(None, None, None, (), ())
    conversion_result = ConversionDateExtraction(None, (), frozenset())

    assert DateExtraction.__slots__ == (
        "transaction_date",
        "posting_date",
        "conversion_date",
        "diagnostics",
        "unresolved_conversion_cells",
    )
    assert ConversionDateExtraction.__slots__ == ("value", "diagnostics", "source_cells")
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

    assert parse_date(full_token) == (expected, None)
    assert parse_date(short_token, _year_context(style)) == (expected, None)


def test_parse_date_preserves_installment_ambiguity_diagnostic() -> None:
    assert parse_date("2/6") == (None, "ambiguous_date_or_installment")


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
        ("17 01/02/26", (), date(2026, 2, 1)),
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


def test_dates_recovers_overlapping_boundary_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        words=(_word("MERCHANT01/02/2026", 0.0, 100.0),),
        confidence=1.0,
    )
    damaged_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 0/1 2/2 0 2 6",
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
        _cell("13/03/26", 0, 30.0),
        _cell("First", 1, 30.0),
        _cell("2.00", 2, 30.0),
    )
    second = _row(
        _cell("20/03/26", 0, 50.0),
        _cell("Second", 1, 50.0),
        _cell("4.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (first, second),
    )

    assert extract_dates(first, region, None, {}) == DateExtraction(None, None, None, (), ())
    assert extract_dates(second, region, None, {}) == DateExtraction(None, None, None, (), ())


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
    )

    result = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
        _year_context(DateTokenStyle.DAY_FIRST_SLASH),
        original_currency="USD",
        billing_currency="ILS",
        transaction_date=date(2026, 6, 24),
        existing_conversion_date=None,
    )

    assert result == ConversionDateExtraction(date(2026, 6, 25), (), frozenset((conversion_cell,)))
    assert next(iter(result.source_cells)) is conversion_cell


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
    )


def test_semantic_conversion_date_preserves_cross_cell_sources() -> None:
    region, left, right = _cross_cell_region()
    row = region.rows[0]
    ledger = EvidenceLedger.from_rows((row,))

    evidence = cross_cell_date_tokens(row, region, ledger)
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

    assert len(evidence) == 1
    assert evidence[0].text == "26/06/21"
    assert evidence[0].cells == frozenset((left, right))
    assert result == ConversionDateExtraction(date(2021, 6, 26), (), frozenset((left, right)))
    assert any(source is left for source in result.source_cells)
    assert any(source is right for source in result.source_cells)


def test_semantic_conversion_date_exposes_conflict_with_explicit_date() -> None:
    region, left, right = _cross_cell_region(explicit_conversion_date="25/06/2021")
    row = region.rows[0]
    context = _year_context(DateTokenStyle.DAY_FIRST_SLASH, 2021)
    explicit = extract_dates(row, region, context, {})

    semantic = extract_conversion_date(
        row,
        region,
        EvidenceLedger.from_rows((row,)),
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
    assert semantic == ConversionDateExtraction(date(2021, 6, 26), (), frozenset((left, right)))
    assert semantic.value != explicit.conversion_date
