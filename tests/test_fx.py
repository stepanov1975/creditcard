from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from ccparser.evidence import Glyph
from ccparser.fx import _contains_cue, extract_foreign_exchange
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.semantic_evidence import EvidenceLedger, SemanticOwner


def _glyphs(text: str, x0: float, y: float) -> tuple[Glyph, ...]:
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


def _cell(
    text: str,
    column: int,
    y: float,
    *,
    glyphs: tuple[Glyph, ...] = (),
) -> Cell:
    x0 = float(column * 50)
    return Cell(
        page_number=1,
        bbox=(x0, y, x0 + 40.0, y + 10.0),
        text=text,
        glyphs=glyphs,
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
    row: Row,
    *,
    fee_header: str = "Foreign-currency fee",
) -> TableRegion:
    roles = (
        ColumnRole.AMOUNT,
        ColumnRole.AUXILIARY_AMOUNT,
        ColumnRole.CONVERSION_DATE,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.DESCRIPTION,
        ColumnRole.DATE,
    )
    header_texts = (
        "Amount charged",
        fee_header,
        "Conversion date Exchange rate",
        "Original amount",
        "Merchant",
        "Transaction date",
    )
    headers = tuple(_cell(text, index, 10.0) for index, text in enumerate(header_texts))
    columns = tuple(
        ColumnSpec(
            index=index,
            page_number=1,
            bbox=(index * 50.0, 10.0, index * 50.0 + 40.0, 100.0),
            relative_x0=index / len(roles),
            relative_x1=(index + 1) / len(roles),
            role=role,
            source_cells=(headers[index],),
            confidence=1.0,
        )
        for index, role in enumerate(roles)
    )
    header = _row(*headers)
    schema = TableSchema(
        page_number=1,
        bbox=(0.0, 10.0, 290.0, 100.0),
        columns=columns,
        header_cells=headers,
        sample_cells=row.cells,
        confidence=1.0,
    )
    return TableRegion(
        page_number=1,
        bbox=schema.bbox,
        header=header,
        rows=(row,),
        table_schema=schema,
        confidence=1.0,
    )


def _foreign_row(rate_text: str = "22/06/26 2.9660") -> Row:
    return _row(
        _cell("₪170.57", 0, 30.0),
        _cell("3₪ 1.69", 1, 30.0, glyphs=_glyphs("3₪ 1.69", 50.0, 30.0)),
        _cell(rate_text, 2, 30.0, glyphs=_glyphs(rate_text, 100.0, 30.0)),
        _cell("$56.94", 3, 30.0),
        _cell("Merchant", 4, 30.0),
        _cell("19/06/26", 5, 30.0),
    )


def _base_row_without_fx_values() -> Row:
    return _row(
        _cell("₪29.72", 0, 30.0),
        _cell("$10.00", 3, 30.0),
        _cell("Merchant", 4, 30.0),
        _cell("07/06/26", 5, 30.0),
    )


def _positioned_cell(text: str, physical_text: str, x0: float, y: float) -> Cell:
    glyphs = _glyphs(physical_text, x0, y)
    return Cell(
        page_number=1,
        bbox=(x0, y, glyphs[-1].bbox[2], y + 10.0),
        text=text,
        glyphs=glyphs,
        confidence=1.0,
    )


def _bounded_continuation(*cells: Cell) -> Row:
    return _row(*cells).model_copy(
        update={
            "diagnostics": (
                "subordinate_detail_continuation",
                "foreign_conversion_detail_block",
            )
        }
    )


def _continuation_rows(
    *,
    rate_text: str = "2.9430",
    gross_fee: str = "0.88",
    discount: str = "0.59",
    bounded: bool = True,
) -> tuple[Row, ...]:
    rate_prefix = "exchange rate "
    first_rate = f"{rate_prefix}{rate_text[:4]}"
    remaining_rate = rate_text[4:]
    first_rate_cell = _positioned_cell(first_rate, first_rate, 50.0, 40.0)
    rate_tail_x = first_rate_cell.bbox[2] + 0.2
    rate_row = _row(
        first_rate_cell,
        _positioned_cell(remaining_rate, remaining_rate, rate_tail_x, 40.0),
    )
    percentage_row = _row(
        _positioned_cell(
            "foreign-currency fee 3.00%",
            "foreign-currency fee 3.00%",
            50.0,
            50.0,
        )
    )
    gross_row = _row(
        _positioned_cell(
            f"fee amount ILS {gross_fee}; discount follows",
            f"fee amount ILS {gross_fee}; discount follows",
            50.0,
            60.0,
        )
    )
    discount_row = _row(
        _positioned_cell(
            f"discount ILS {discount}",
            f"discount ILS {discount}",
            50.0,
            70.0,
        )
    )
    rows = (rate_row, percentage_row, gross_row, discount_row)
    return tuple(_bounded_continuation(*row.cells) for row in rows) if bounded else rows


def test_extract_foreign_exchange_from_semantic_table_columns() -> None:
    row = _foreign_row()
    region = _region(row)

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=region,
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("1.69")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.details.gross_fee is None
    assert extraction.details.fee_discount is None
    assert extraction.diagnostics == ()
    assert {claim.owner for claim in extraction.claims} == {
        SemanticOwner.EXCHANGE_RATE,
        SemanticOwner.NET_FX_FEE,
    }
    assert extraction.details.exchange_rate.evidence
    assert extraction.details.net_fee.evidence


def test_extract_foreign_exchange_ignores_same_currency_row() -> None:
    row = _foreign_row()

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="ILS",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ()


def test_auxiliary_amount_requires_explicit_fee_header() -> None:
    row = _foreign_row()

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ()


def test_coffee_header_does_not_make_auxiliary_amount_an_fx_fee() -> None:
    row = _foreign_row()

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Coffee amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert "unparsed_foreign_currency_fee_candidate" not in extraction.diagnostics
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)


def test_corporate_date_header_does_not_make_conversion_date_an_exchange_rate() -> None:
    assert not _contains_cue("corporate date", ("rate",))

    row = _foreign_row()
    region = _region(row)
    columns = tuple(
        column.model_copy(
            update={
                "source_cells": (
                    column.source_cells[0].model_copy(update={"text": "Corporate date"}),
                )
            }
        )
        if column.role is ColumnRole.CONVERSION_DATE
        else column
        for column in region.table_schema.columns
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=region,
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is None
    assert "unparsed_exchange_rate_candidate" not in extraction.diagnostics
    assert all(claim.owner is not SemanticOwner.EXCHANGE_RATE for claim in extraction.claims)


def test_multiple_exchange_rate_candidates_remain_ambiguous() -> None:
    row = _foreign_row("22/06/26 2.9660 3.0010")

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_conflicting_table_and_continuation_rates_remain_ambiguous() -> None:
    row = _foreign_row()
    continuation = _bounded_continuation(
        _positioned_cell("exchange rate 2.9430", "2.9430", 50.0, 40.0)
    )
    rows = (row, continuation)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is None
    assert extraction.details.net_fee is not None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)
    assert all(claim.owner is not SemanticOwner.EXCHANGE_RATE for claim in extraction.claims)


def test_ambiguous_table_rate_is_not_repopulated_from_continuation() -> None:
    row = _foreign_row("22/06/26 2.9660 3.0010")
    continuation = _bounded_continuation(
        _positioned_cell("exchange rate 2.9430", "2.9430", 50.0, 40.0)
    )
    rows = (row, continuation)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 22),
    )

    assert extraction.details is None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)
    assert extraction.claims == ()


def test_later_rate_row_cannot_repopulate_repeated_continuation_rate() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = tuple(
        _bounded_continuation(_positioned_cell(f"exchange rate {value}", value, 50.0, y))
        for value, y in (("2.9430", 40.0), ("2.9660", 50.0), ("3.0010", 60.0))
    )
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)
    assert extraction.claims == ()


def test_extract_foreign_exchange_from_bounded_continuation_details() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.exchange_rate is not None
    assert details.exchange_rate.value == Decimal("2.9430")
    assert details.fee_percentage is not None
    assert details.fee_percentage.value == Decimal("3.00")
    assert details.gross_fee is not None
    assert details.gross_fee.amount == Decimal("0.88")
    assert details.fee_discount is not None
    assert details.fee_discount.amount == Decimal("0.59")
    assert details.net_fee is not None
    assert details.net_fee.amount == Decimal("0.29")
    assert details.net_fee.currency == "ILS"
    assert details.net_fee.derivation == "gross_fee_minus_discount"
    assert details.net_fee.evidence == tuple(
        dict.fromkeys((*details.gross_fee.evidence, *details.fee_discount.evidence))
    )
    assert extraction.diagnostics == ()


def test_fee_derivation_is_exact_under_low_decimal_precision() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows(
        gross_fee="123456789012345678901234567890.12",
        discount="0.01",
    )
    rows = (base_row, *continuation_rows)

    with localcontext() as context:
        context.prec = 5
        extraction = extract_foreign_exchange(
            rows=rows,
            region=_region(base_row, fee_header="Auxiliary amount"),
            ledger=EvidenceLedger.from_rows(rows),
            original_currency="USD",
            billing_currency="ILS",
            conversion_date=date(2026, 6, 8),
        )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("123456789012345678901234567890.11")
    assert extraction.diagnostics == ()


def test_percentage_then_discount_announcement_proves_gross_and_discount_sequence() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = (
        _bounded_continuation(_positioned_cell("exchange rate 2.9430", ".2.9430", 50.0, 40.0)),
        _bounded_continuation(_positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 50.0)),
        _bounded_continuation(
            _positioned_cell(
                "ILS 0.88; from this fee a discount is subtracted",
                "ILS 0.88; from this fee a discount is subtracted",
                50.0,
                60.0,
            )
        ),
        _bounded_continuation(
            _positioned_cell("ILS 0.59 under arrangement", "ILS 0.59", 50.0, 70.0)
        ),
    )
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.exchange_rate is not None
    assert details.exchange_rate.value == Decimal("2.9430")
    assert details.gross_fee is not None
    assert details.gross_fee.amount == Decimal("0.88")
    assert details.fee_discount is not None
    assert details.fee_discount.amount == Decimal("0.59")
    assert details.net_fee is not None
    assert details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ()


def test_zero_fee_percentage_is_preserved() -> None:
    base_row = _base_row_without_fx_values()
    percentage = _bounded_continuation(
        _positioned_cell("foreign-currency fee 0.00%", "0.00%", 50.0, 40.0)
    )
    rows = (base_row, percentage)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("0.00")
    assert extraction.diagnostics == ()


def test_ambiguous_explicit_continuation_rate_emits_diagnostic() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows(rate_text="2.9430 3.0010")
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_unbounded_numeric_notes_do_not_become_fx_values() -> None:
    base_row = _base_row_without_fx_values()
    note_rows = _continuation_rows(bounded=False)
    rows = (base_row, *note_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ()


def test_discount_larger_than_gross_fee_prevents_net_derivation() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows(gross_fee="0.50", discount="0.59")
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        conversion_date=date(2026, 6, 8),
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("inconsistent_foreign_currency_fee_derivation",)
