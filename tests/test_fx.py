from __future__ import annotations

from datetime import date
from decimal import Decimal

from ccparser.evidence import Glyph
from ccparser.fx import extract_foreign_exchange
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
