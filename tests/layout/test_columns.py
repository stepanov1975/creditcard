from __future__ import annotations

import pytest

from ccparser.evidence import VectorRule, Word
from ccparser.layout.columns import infer_column_bands, infer_column_roles
from ccparser.layout.models import Cell, ColumnRole, Row


def _cell(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    page_number: int = 1,
) -> Cell:
    word = Word(text=text, bbox=bbox, source="digital", confidence=1.0)
    return Cell(
        page_number=page_number,
        bbox=bbox,
        text=text,
        words=(word,),
        confidence=1.0,
    )


def _row(y: float, cells: tuple[Cell, ...]) -> Row:
    return Row(
        page_number=1,
        bbox=(
            min(cell.bbox[0] for cell in cells),
            y,
            max(cell.bbox[2] for cell in cells),
            y + 10.0,
        ),
        cells=cells,
        words=tuple(word for cell in cells for word in cell.words),
        confidence=1.0,
    )


def _transform_row(row: Row, factor: float, shift: float) -> Row:
    transformed_cells = tuple(
        cell.model_copy(
            update={
                "bbox": (
                    cell.bbox[0] * factor + shift,
                    cell.bbox[1] * factor,
                    cell.bbox[2] * factor + shift,
                    cell.bbox[3] * factor,
                )
            }
        )
        for cell in row.cells
    )
    return row.model_copy(
        update={
            "bbox": (
                row.bbox[0] * factor + shift,
                row.bbox[1] * factor,
                row.bbox[2] * factor + shift,
                row.bbox[3] * factor,
            ),
            "cells": transformed_cells,
        }
    )


def test_infer_column_bands_finds_repeated_bands_in_scale_independent_coordinates() -> None:
    rows = (
        _row(
            10.0,
            (
                _cell("Date", (10.0, 10.0, 30.0, 20.0)),
                _cell("Description", (45.0, 10.0, 78.0, 20.0)),
                _cell("Amount", (91.0, 10.0, 111.0, 20.0)),
            ),
        ),
        _row(
            30.0,
            (
                _cell("01/02", (11.0, 30.0, 31.0, 40.0)),
                _cell("Market", (47.0, 30.0, 75.0, 40.0)),
                _cell("12.34", (90.0, 30.0, 110.0, 40.0)),
            ),
        ),
    )

    columns = infer_column_bands(rows)
    transformed = infer_column_bands(
        tuple(_transform_row(row, factor=2.25, shift=37.0) for row in rows)
    )

    assert len(columns) == 3
    assert tuple(len(column.source_cells) for column in columns) == (2, 2, 2)
    assert tuple(column.relative_x0 for column in transformed) == pytest.approx(
        tuple(column.relative_x0 for column in columns)
    )
    assert tuple(column.relative_x1 for column in transformed) == pytest.approx(
        tuple(column.relative_x1 for column in columns)
    )
    assert all(column.confidence == 1.0 for column in columns)


def test_infer_column_bands_uses_vertical_vector_separators_as_relative_boundaries() -> None:
    rows = (
        _row(
            10.0,
            (
                _cell("Left", (10.0, 10.0, 35.0, 20.0)),
                _cell("Right", (60.0, 10.0, 100.0, 20.0)),
            ),
        ),
        _row(
            30.0,
            (
                _cell("A", (12.0, 30.0, 32.0, 40.0)),
                _cell("B", (62.0, 30.0, 98.0, 40.0)),
            ),
        ),
    )
    separator = VectorRule(bbox=(48.0, 5.0, 48.0, 45.0), width=0.5)

    columns = infer_column_bands(rows, (separator,))

    assert tuple(column.bbox for column in columns) == (
        (10.0, 10.0, 48.0, 40.0),
        (48.0, 10.0, 100.0, 40.0),
    )
    assert all("vector_separator_support" in column.diagnostics for column in columns)


def test_infer_column_roles_combines_hebrew_headers_and_value_profiles() -> None:
    headers = (
        _cell("תאריך", (0.0, 10.0, 20.0, 20.0)),
        _cell("בית עסק", (30.0, 10.0, 60.0, 20.0)),
        _cell("מטבע", (70.0, 10.0, 82.0, 20.0)),
        _cell("סכום חיוב", (90.0, 10.0, 120.0, 20.0)),
    )
    samples = (
        _cell("01/02/2026", (0.0, 30.0, 20.0, 40.0)),
        _cell("חנות", (30.0, 30.0, 60.0, 40.0)),
        _cell("ILS", (70.0, 30.0, 82.0, 40.0)),
        _cell("123.45", (90.0, 30.0, 120.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.CURRENCY,
        ColumnRole.AMOUNT,
    )
    assert schema.diagnostics == ()
    assert schema.header_cells == headers
    assert schema.sample_cells == samples


def test_infer_column_roles_uses_profiles_but_retains_ambiguous_unknown_column() -> None:
    headers = (
        _cell("When", (0.0, 10.0, 20.0, 20.0)),
        _cell("Currency", (30.0, 10.0, 50.0, 20.0)),
        _cell("Part", (60.0, 10.0, 80.0, 20.0)),
        _cell("Reference", (90.0, 10.0, 120.0, 20.0)),
    )
    samples = (
        _cell("2026-03-04", (0.0, 30.0, 20.0, 40.0)),
        _cell("EUR", (30.0, 30.0, 50.0, 40.0)),
        _cell("14/24", (60.0, 30.0, 80.0, 40.0)),
        _cell("A7X9", (90.0, 30.0, 120.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.CURRENCY,
        ColumnRole.INSTALLMENT,
        ColumnRole.UNKNOWN,
    )
    assert "ambiguous_columns:3" in schema.diagnostics


def test_infer_column_roles_distinguishes_original_and_billed_amount_headers() -> None:
    headers = (
        _cell("Original amount", (0.0, 10.0, 40.0, 20.0)),
        _cell("Amount charged", (60.0, 10.0, 100.0, 20.0)),
    )
    samples = (
        _cell("20.00", (0.0, 30.0, 40.0, 40.0)),
        _cell("75.10", (60.0, 30.0, 100.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )


def test_infer_column_roles_marks_generic_amount_between_explicit_amount_roles_as_auxiliary() -> (
    None
):
    headers = (
        _cell("Billed amount", (0.0, 10.0, 30.0, 20.0)),
        _cell("Amount", (40.0, 10.0, 70.0, 20.0)),
        _cell("Original amount", (80.0, 10.0, 110.0, 20.0)),
    )
    samples = (
        _cell("25.00", (0.0, 30.0, 30.0, 40.0)),
        _cell("100.00", (40.0, 30.0, 70.0, 40.0)),
        _cell("30.00", (80.0, 30.0, 110.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role.value for column in schema.columns) == (
        "amount",
        "auxiliary_amount",
        "original_amount",
    )


def test_short_slash_value_remains_ambiguous_when_date_and_installment_are_plausible() -> None:
    schema = infer_column_roles(
        (_cell("Reference", (0.0, 10.0, 30.0, 20.0)),),
        (_cell("2/12", (0.0, 30.0, 30.0, 40.0)),),
    )

    assert schema.columns[0].role is ColumnRole.UNKNOWN
    assert "ambiguous_role" in schema.columns[0].diagnostics


@pytest.mark.parametrize(
    ("header", "expected"),
    (("Date", ColumnRole.DATE), ("Installment", ColumnRole.INSTALLMENT)),
)
def test_exact_header_disambiguates_short_date_or_installment(
    header: str, expected: ColumnRole
) -> None:
    schema = infer_column_roles(
        (_cell(header, (0.0, 10.0, 30.0, 20.0)),),
        (_cell("2/12", (0.0, 30.0, 30.0, 40.0)),),
    )

    assert schema.columns[0].role is expected
    assert any(
        diagnostic.startswith("alternative_role:") for diagnostic in schema.columns[0].diagnostics
    )


@pytest.mark.parametrize("value", ("0/12", "32/13/2026", "31/02/2026"))
def test_date_profile_rejects_out_of_range_numeric_components(value: str) -> None:
    schema = infer_column_roles(
        (_cell("Reference", (0.0, 10.0, 30.0, 20.0)),),
        (_cell(value, (0.0, 30.0, 30.0, 40.0)),),
    )

    assert schema.columns[0].role is ColumnRole.UNKNOWN


@pytest.mark.parametrize("symbol", ("$", "€", "£", "₪"))
def test_currency_profile_recognizes_standalone_symbols(symbol: str) -> None:
    schema = infer_column_roles(
        (_cell("Reference", (0.0, 10.0, 30.0, 20.0)),),
        (_cell(symbol, (0.0, 30.0, 30.0, 40.0)),),
    )

    assert schema.columns[0].role is ColumnRole.CURRENCY


def test_header_phrase_matches_contiguous_tokens_inside_longer_heading() -> None:
    schema = infer_column_roles(
        (_cell("Transaction date (local time)", (0.0, 10.0, 50.0, 20.0)),),
        (_cell("01/02/2026", (0.0, 30.0, 50.0, 40.0)),),
    )

    assert schema.columns[0].role is ColumnRole.DATE
    assert "role_evidence:header" in schema.columns[0].diagnostics


def test_currency_headers_distinguish_billing_from_original_transaction_currency() -> None:
    headers = (
        _cell("Transaction currency", (0.0, 10.0, 40.0, 20.0)),
        _cell("Billing currency", (60.0, 10.0, 100.0, 20.0)),
    )
    samples = (
        _cell("USD", (0.0, 30.0, 40.0, 40.0)),
        _cell("ILS", (60.0, 30.0, 100.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.ORIGINAL_CURRENCY,
        ColumnRole.BILLING_CURRENCY,
    )


def test_infer_column_roles_keeps_shifted_samples_in_header_anchored_bands() -> None:
    headers = (
        _cell("Date", (0.0, 10.0, 20.0, 20.0)),
        _cell("Description", (40.0, 10.0, 70.0, 20.0)),
        _cell("Amount", (90.0, 10.0, 110.0, 20.0)),
    )
    samples = (
        _cell("01/02/2026", (0.0, 30.0, 20.0, 40.0)),
        _cell("Market", (40.0, 30.0, 70.0, 40.0)),
        _cell("12.00", (78.0, 30.0, 82.0, 40.0)),
        _cell("02/02/2026", (0.0, 50.0, 20.0, 60.0)),
        _cell("Cafe", (40.0, 50.0, 70.0, 60.0)),
        _cell("18.00", (118.0, 50.0, 122.0, 60.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert len(schema.columns) == 3
    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )
    assert all("header_anchor_support" in column.diagnostics for column in schema.columns)


def test_infer_column_roles_recognizes_compact_definite_hebrew_headers() -> None:
    headers = (
        _cell("שםביתהעסק", (0.0, 10.0, 30.0, 20.0)),
        _cell("סכוםהעסקה", (40.0, 10.0, 70.0, 20.0)),
        _cell("סכוםהחיוב", (80.0, 10.0, 110.0, 20.0)),
    )
    samples = (
        _cell("Market", (0.0, 30.0, 30.0, 40.0)),
        _cell("USD 5.00", (40.0, 30.0, 70.0, 40.0)),
        _cell("ILS 18.00", (80.0, 30.0, 110.0, 40.0)),
    )

    schema = infer_column_roles(headers, samples)

    assert tuple(column.role for column in schema.columns) == (
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )


def test_infer_column_roles_composes_original_modifier_with_generic_amount_header() -> None:
    schema = infer_column_roles(
        (_cell("סכום מקורי", (0.0, 10.0, 40.0, 20.0)),),
        (_cell("25.00", (0.0, 30.0, 40.0, 40.0)),),
    )

    assert schema.columns[0].role is ColumnRole.ORIGINAL_AMOUNT


@pytest.mark.parametrize(
    "header",
    ("Exchange rate", "Exchange rate used for billing", "שערההמרה", "שערהמרהלדולר"),
)
def test_infer_column_roles_keeps_exchange_rate_numeric_profile_nonfinancial(
    header: str,
) -> None:
    schema = infer_column_roles(
        (_cell(header, (0.0, 10.0, 40.0, 20.0)),),
        (
            _cell("0.00", (0.0, 30.0, 40.0, 40.0)),
            _cell("3.72", (0.0, 50.0, 40.0, 60.0)),
        ),
    )

    assert schema.columns[0].role is ColumnRole.EXCHANGE_RATE
    assert not any(
        diagnostic.startswith("alternative_role:") for diagnostic in schema.columns[0].diagnostics
    )


@pytest.mark.parametrize(
    ("logical_text", "word_texts"),
    (
        ("הרמהךיראת", ("הרמהךיראת",)),
        ("ךיראתהרמה", ("המרה", "תאריך")),
    ),
)
def test_infer_column_roles_recovers_compact_reversed_conversion_date_headers(
    logical_text: str,
    word_texts: tuple[str, ...],
) -> None:
    words = tuple(
        Word(
            text=text,
            bbox=(0.0, 10.0 + index * 6.0, 40.0, 15.0 + index * 6.0),
            source="digital",
            confidence=1.0,
        )
        for index, text in enumerate(word_texts)
    )
    header = Cell(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 28.0),
        text=logical_text,
        words=words,
        confidence=1.0,
    )

    schema = infer_column_roles(
        (header,),
        (
            _cell("01/02/2026", (0.0, 30.0, 40.0, 40.0)),
            _cell("03/02/2026", (0.0, 50.0, 40.0, 60.0)),
        ),
    )

    assert schema.columns[0].role is ColumnRole.CONVERSION_DATE
    assert "role_evidence:header" in schema.columns[0].diagnostics
    assert not any(
        diagnostic.startswith("alternative_role:") for diagnostic in schema.columns[0].diagnostics
    )
