from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import pytest

from ccparser.evidence import Glyph, Word
from ccparser.fx import (
    _contains_cue,
    _percentage_explains_amount,
    extract_foreign_exchange,
)
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import EvidenceReference
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner


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


def _rtl_glyphs(text: str, right: float, y: float) -> tuple[Glyph, ...]:
    return tuple(
        Glyph(
            char=char,
            bbox=(right - index - 0.8, y, right - index, y + 10.0),
            origin=(right - index - 0.8, y + 9.0),
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
    rate_header: str = "Conversion date Exchange rate",
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
        rate_header,
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


def _multiline_rate_cell(
    column: int,
    rates: tuple[str, ...],
    *,
    y: float,
    date_fragment: str = "26.0",
) -> Cell:
    x0 = float(column * 50)
    date_y = y + len(rates) * 10.0
    return Cell(
        page_number=1,
        bbox=(x0, y, x0 + 40.0, date_y + 10.0),
        text=f"exchange rate {' '.join(rates)} converted on {date_fragment}",
        glyphs=(
            *(
                glyph
                for index, rate in enumerate(rates)
                for glyph in _glyphs(rate, x0, y + index * 10.0)
            ),
            *_glyphs(date_fragment, x0, date_y),
        ),
        confidence=1.0,
    )


def _last_line_atom_ids(cell: Cell, ledger: EvidenceLedger) -> frozenset[int]:
    last_y = max(glyph.bbox[1] for glyph in cell.glyphs)
    return frozenset(
        atom_id
        for atom_id in ledger.atoms_for_cell(cell)
        if ledger.atoms[atom_id].bbox[1] == last_y
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


def _projected_positioned_cell(
    logical_text: str,
    physical_text: str,
    x0: float,
    y: float,
    band: int,
    *,
    word_fragments: tuple[str, ...] = (),
) -> Cell:
    cursor = 0
    words: list[Word] = []
    for fragment in word_fragments:
        start = physical_text.index(fragment, cursor)
        cursor = start + len(fragment)
        words.append(
            Word(
                text=fragment,
                bbox=(x0 + start, y, x0 + cursor, y + 10.0),
                source="digital",
                confidence=1.0,
            )
        )
    return Cell(
        page_number=1,
        bbox=(x0, y, x0 + len(physical_text), y + 10.0),
        text=logical_text,
        glyphs=_glyphs(physical_text, x0, y),
        words=tuple(words),
        confidence=1.0,
        diagnostics=(f"projected_header_band:{band}",),
    )


def _coherent_projected_fx_rows() -> tuple[Row, tuple[Row, ...]]:
    base_row = _base_row_without_fx_values()
    rate_left_physical = "exchange rate 2.97"
    rate_left = _projected_positioned_cell(
        "20 exchange rate",
        rate_left_physical,
        50.0,
        40.0,
        2,
        word_fragments=("2.", "97"),
    )
    rate_right = _projected_positioned_cell(
        "2.97",
        "20",
        rate_left.bbox[2] + 0.2,
        40.0,
        3,
        word_fragments=("20",),
    )
    percentage = _projected_positioned_cell(
        "3.00% foreign-currency fee",
        "foreign-currency fee 3.00%",
        50.0,
        50.0,
        2,
        word_fragments=("3.", "00"),
    )
    gross = _projected_positioned_cell(
        "reduced fee ILS 0.89; discount follows",
        "ILS 0.89; reduced fee discount follows",
        50.0,
        60.0,
        3,
        word_fragments=("0.", "89"),
    )
    discount = _projected_positioned_cell(
        "reference ILS 0.20",
        "ILS 0.20 reference",
        50.0,
        70.0,
        3,
        word_fragments=("0.", "20"),
    )
    ancillary = _projected_positioned_cell(
        "AB12 reference",
        "reference AB12",
        50.0,
        80.0,
        3,
    )
    return base_row, tuple(
        _bounded_continuation(*row_cells)
        for row_cells in (
            (rate_left, rate_right),
            (percentage,),
            (gross,),
            (discount,),
            (ancillary,),
        )
    )


def _single_band_projected_fx_rows() -> tuple[Row, tuple[Row, ...]]:
    base_row = _base_row_without_fx_values()
    rate = _projected_positioned_cell(
        "marker 2.9720 exchange rate",
        "exchange rate marker 2.9720",
        50.0,
        40.0,
        2,
    )
    percentage = _projected_positioned_cell(
        "marker 3.00% foreign-currency fee",
        "foreign-currency fee marker 3.00%",
        50.0,
        50.0,
        3,
    )
    gross = _projected_positioned_cell(
        "marker fee amount ILS 0.89; discount follows",
        "ILS 0.89; marker fee amount discount follows",
        50.0,
        60.0,
        3,
    )
    discount = _projected_positioned_cell(
        "marker discount ILS 0.20",
        "ILS 0.20 marker discount",
        50.0,
        70.0,
        3,
    )
    return base_row, tuple(
        _bounded_continuation(cell) for cell in (rate, percentage, gross, discount)
    )


def _compact_projected_fx_rows() -> tuple[Row, tuple[Row, ...]]:
    base_row = _base_row_without_fx_values()
    rate = _projected_positioned_cell(
        "fx 2.9720",
        "2.9720 fx",
        100.0,
        40.0,
        3,
    )
    percentage = _projected_positioned_cell(
        "fx 3.00%",
        "3.00% fx",
        100.0,
        50.0,
        3,
    )
    gross = _projected_positioned_cell(
        "note ILS 0.89",
        "ILS 0.89 note",
        50.0,
        50.0,
        2,
    )
    discount = _projected_positioned_cell(
        "discount ILS 0.20",
        "ILS 0.20 discount",
        50.0,
        60.0,
        2,
    )
    identifier_label = _bounded_continuation(
        _projected_positioned_cell(
            "reference label:",
            ":label reference",
            100.0,
            70.0,
            3,
        ),
        _projected_positioned_cell(
            "identifier",
            "identifier",
            50.0,
            70.0,
            2,
        ),
    )
    identifier_value = _bounded_continuation(
        _projected_positioned_cell("XX-1234", "XX-1234", 100.0, 80.0, 3)
    )
    return base_row, (
        _bounded_continuation(rate),
        _bounded_continuation(percentage, gross),
        _bounded_continuation(discount),
        identifier_label,
        identifier_value,
    )


def _expanded_fx_rows_with_projected_identifier_evidence() -> tuple[Row, tuple[Row, ...]]:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    percentage_row = mutable_rows[1]
    mutable_rows[1] = _bounded_continuation(
        *percentage_row.cells,
        _projected_positioned_cell("reference", "reference", 0.0, 50.0, 0),
    )
    discount_row = mutable_rows[3]
    mutable_rows[3] = _bounded_continuation(
        *discount_row.cells,
        _projected_positioned_cell("7", "7", 0.0, 70.0, 0),
    )
    split_identifier = _bounded_continuation(
        _projected_positioned_cell(
            "reference 12-",
            "12- reference",
            50.0,
            80.0,
            2,
        ),
        _projected_positioned_cell("34", "34", 100.0, 80.0, 3),
    )
    return base_row, (*mutable_rows, split_identifier)


def _expanded_fx_rows_with_metadata_percentage() -> tuple[Row, tuple[Row, ...]]:
    base_row, continuation_rows = _expanded_fx_rows_with_projected_identifier_evidence()
    mutable_rows = list(continuation_rows)
    percentage_row = mutable_rows[1]
    mutable_rows[1] = _bounded_continuation(
        *percentage_row.cells[:-1],
        _projected_positioned_cell(
            "card reference metadata label",
            "metadata label card reference",
            0.0,
            50.0,
            0,
        ),
    )
    gross_row = mutable_rows[2]
    mutable_rows[2] = _bounded_continuation(
        *gross_row.cells,
        _projected_positioned_cell(
            "metadata detail value",
            "detail value metadata",
            0.0,
            60.0,
            0,
        ),
    )
    mutable_rows[3] = _bounded_continuation(
        _projected_positioned_cell(
            "marker discount ILS 0.30",
            "ILS 0.30 marker discount",
            50.0,
            70.0,
            3,
        ),
        _projected_positioned_cell(
            "metadata: annotation detail 1%",
            "annotation detail metadata: 1%",
            0.0,
            70.0,
            0,
        ),
    )
    identifier_row = mutable_rows[4]
    mutable_rows[4] = _bounded_continuation(
        *identifier_row.cells,
        _projected_positioned_cell(
            "secondary metadata value",
            "metadata value secondary",
            0.0,
            80.0,
            0,
        ),
    )
    return base_row, tuple(mutable_rows)


def _region_with_unknown_first_band(
    base_row: Row,
    *,
    header_text: str = "Card reference metadata",
) -> TableRegion:
    region = _region(base_row, fee_header="Auxiliary amount")
    columns = list(region.table_schema.columns)
    header_cell = _cell(header_text, 0, 10.0)
    columns[0] = columns[0].model_copy(
        update={"role": ColumnRole.UNKNOWN, "source_cells": (header_cell,)}
    )
    header_cells = list(region.table_schema.header_cells)
    header_cells[0] = header_cell
    schema = region.table_schema.model_copy(
        update={"columns": tuple(columns), "header_cells": tuple(header_cells)}
    )
    row_cells = list(region.header.cells)
    row_cells[0] = header_cell
    header = region.header.model_copy(update={"cells": tuple(row_cells)})
    return region.model_copy(update={"header": header, "table_schema": schema})


def _shift_single_cell_row(row: Row, offset: float) -> Row:
    cell = row.cells[0]
    shifted = cell.model_copy(
        update={
            "bbox": (
                cell.bbox[0],
                cell.bbox[1] + offset,
                cell.bbox[2],
                cell.bbox[3] + offset,
            ),
            "glyphs": tuple(
                glyph.model_copy(
                    update={
                        "bbox": (
                            glyph.bbox[0],
                            glyph.bbox[1] + offset,
                            glyph.bbox[2],
                            glyph.bbox[3] + offset,
                        ),
                        "origin": (glyph.origin[0], glyph.origin[1] + offset),
                    }
                )
                for glyph in cell.glyphs
            ),
            "words": tuple(
                word.model_copy(
                    update={
                        "bbox": (
                            word.bbox[0],
                            word.bbox[1] + offset,
                            word.bbox[2],
                            word.bbox[3] + offset,
                        )
                    }
                )
                for word in cell.words
            ),
        }
    )
    return _bounded_continuation(shifted)


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


def test_table_rate_uses_lossless_residual_when_one_positioned_source_omits_it() -> None:
    source_row = _foreign_row()
    date_text = "22/06/26"
    rate_text = "2.9660"
    rate_cell = Cell(
        page_number=1,
        bbox=(90.0, 30.0, 140.0, 40.0),
        text=f"{date_text} {rate_text}",
        glyphs=(*_glyphs(date_text, 92.0, 30.0), *_glyphs(rate_text, 115.0, 30.0)),
        confidence=1.0,
    )
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])
    ledger = EvidenceLedger.from_rows((row,))
    date_atom_ids = ledger.fragmented_date_candidates(rate_cell)[0].atom_ids

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=date_atom_ids,
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal(rate_text)
    assert extraction.diagnostics == ()
    rate_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.EXCHANGE_RATE
    )
    assert rate_claim.atom_ids.isdisjoint(date_atom_ids)


@pytest.mark.parametrize("date_text", ("22/06/26", "Converted on 22/06/26"))
def test_fully_date_owned_cell_is_omitted_from_mixed_rate_column(date_text: str) -> None:
    source_row = _foreign_row()
    date_cell = _positioned_cell(date_text, date_text, 100.0, 30.0)
    rate_cell = _positioned_cell("2.9660", "2.9660", 120.0, 30.0)
    row = _row(
        *source_row.cells[:2],
        date_cell,
        rate_cell,
        *source_row.cells[3:],
    )
    ledger = EvidenceLedger.from_rows((row,))
    date_atom_ids = ledger.fragmented_date_candidates(date_cell)[0].atom_ids

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=date_atom_ids,
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "fee_text",
    ("exchange rate ILS 0.29", "discount ILS 0.29", "gross fee ILS 0.29"),
)
def test_table_fee_rejects_conflicting_cell_semantics(fee_text: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_table_rate_rejects_conflicting_fee_semantics() -> None:
    source_row = _foreign_row()
    rate_cell = _positioned_cell("fee amount 2.9430", "fee amount 2.9430", 100.0, 30.0)
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is None
    assert extraction.details.net_fee is not None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_table_rate_rejects_conflicting_logical_and_positioned_values() -> None:
    source_row = _foreign_row()
    rate_cell = _positioned_cell("2.9660", "3.0010", 100.0, 30.0)
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_table_rate_accepts_reordered_equivalent_numeric_annotations() -> None:
    source_row = _foreign_row()
    rate_cell = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 50.0),
        text="26.0 converted at exchange rate 2.9660",
        glyphs=(
            *_glyphs("exchange rate 2.9660", 100.0, 30.0),
            *_glyphs("26.0", 100.0, 40.0),
        ),
        confidence=1.0,
    )
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=_last_line_atom_ids(rate_cell, ledger),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "annotation",
    ("merchant", "INR", "₹", "EUR"),
)
def test_table_rate_rejects_invalid_context(annotation: str) -> None:
    source_row = _foreign_row()
    rate_text = f"exchange rate {annotation} 2.9660"
    rate_cell = _positioned_cell(rate_text, rate_text, 100.0, 30.0)
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_prefixed_hebrew_clitic_rate_cue_recovers_table_rate_with_evidence() -> None:
    row = _foreign_row()
    rate_cell = row.cells[2]
    region = _region(
        row,
        fee_header="Auxiliary amount",
        rate_header="תאריך המרה בשער המרה",
    )

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=region,
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.details.exchange_rate.evidence == (
        EvidenceReference(
            page_number=rate_cell.page_number,
            bbox=rate_cell.bbox,
            raw_text=rate_cell.text,
        ),
    )
    assert any(claim.owner is SemanticOwner.EXCHANGE_RATE for claim in extraction.claims)
    assert extraction.diagnostics == ()


def test_table_rate_excludes_only_accepted_conversion_date_atoms() -> None:
    source_row = _foreign_row()
    rate_cell = _multiline_rate_cell(2, ("2.9660",), y=30.0)
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])
    ledger = EvidenceLedger.from_rows((row,))
    excluded_atom_ids = _last_line_atom_ids(rate_cell, ledger)

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=excluded_atom_ids,
    )

    assert excluded_atom_ids
    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    rate_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.EXCHANGE_RATE
    )
    assert rate_claim.atom_ids.isdisjoint(excluded_atom_ids)
    assert extraction.diagnostics == ()


def test_table_rate_does_not_preemptively_exclude_unaccepted_date_candidates(
    monkeypatch,
) -> None:
    row = _foreign_row("32/06/26 2.9660")
    ledger = EvidenceLedger.from_rows((row,))
    rate_cell = row.cells[2]
    invalid_date_ids = frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(rate_cell)
        for atom_id in candidate.atom_ids
    )
    observed_rate_inputs: list[frozenset[int]] = []
    original = EvidenceLedger.positioned_decimal_candidates

    def observe_candidates(
        self: EvidenceLedger,
        atom_ids,
        *,
        max_fraction_digits: int = 6,
    ):
        selected = frozenset(atom_ids)
        if self is ledger and selected <= ledger.atoms_for_cell(rate_cell):
            observed_rate_inputs.append(selected)
        return original(self, selected, max_fraction_digits=max_fraction_digits)

    monkeypatch.setattr(EvidenceLedger, "positioned_decimal_candidates", observe_candidates)

    extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert invalid_date_ids
    assert any(invalid_date_ids <= selected for selected in observed_rate_inputs)


def test_continuation_rate_excludes_only_accepted_conversion_date_atoms() -> None:
    base_row = _base_row_without_fx_values()
    rate_cell = _multiline_rate_cell(1, ("2.9430",), y=40.0)
    continuation = _bounded_continuation(rate_cell)
    rows = (base_row, continuation)
    ledger = EvidenceLedger.from_rows(rows)
    excluded_atom_ids = _last_line_atom_ids(rate_cell, ledger)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=excluded_atom_ids,
    )

    assert excluded_atom_ids
    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9430")
    rate_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.EXCHANGE_RATE
    )
    assert rate_claim.atom_ids.isdisjoint(excluded_atom_ids)
    assert extraction.diagnostics == ()


def test_excluding_conversion_date_atoms_preserves_multiple_rate_ambiguity() -> None:
    source_row = _foreign_row()
    rate_cell = _multiline_rate_cell(2, ("2.9660", "3.0010"), y=30.0)
    row = _row(*source_row.cells[:2], rate_cell, *source_row.cells[3:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=_last_line_atom_ids(rate_cell, ledger),
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_explicit_zero_table_fee_is_evidenced_without_ambiguity() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("₪0.00", "₪0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.00")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.details.net_fee.evidence == (
        EvidenceReference(page_number=1, bbox=fee_cell.bbox, raw_text=fee_cell.text),
    )
    zero_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))
        if candidate.text == "0.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, zero_atom_ids),)
    assert extraction.diagnostics == ()


def test_currencyless_zero_table_fee_uses_proven_billing_currency_and_exact_evidence() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00", "0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.00")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.details.net_fee.evidence == (
        EvidenceReference(page_number=1, bbox=fee_cell.bbox, raw_text=fee_cell.text),
    )
    zero_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))
        if candidate.text == "0.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, zero_atom_ids),)
    assert extraction.diagnostics == ()


def test_currencyless_nonzero_table_fee_uses_proven_billing_currency() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.01", "0.01", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.01")
    assert extraction.details.net_fee.currency == "ILS"
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "fee_header",
    (
        "Foreign-currency service processing fee",
        "frais de service fee",
        "עמלת שירות מורחב",
    ),
)
def test_typed_fee_header_allows_benign_unfamiliar_label_tokens(fee_header: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.29", "0.29", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header=fee_header),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.details.net_fee.currency == "ILS"
    fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))
        if candidate.text == "0.29"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, fee_atom_ids),)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize("net_label", ("net fee", "net amount", "reduced fee"))
def test_explicit_net_source_is_valid_inside_typed_table_fee_column(net_label: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(
        f"{net_label} ILS 0.37",
        f"{net_label} ILS 0.37",
        50.0,
        30.0,
    )
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))
        if candidate.text == "0.37"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, fee_atom_ids),)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("continuation_amount", "expected_amount", "expected_diagnostics"),
    (
        ("0.37", Decimal("0.37"), ()),
        ("0.38", None, ("inconsistent_foreign_currency_fee_derivation",)),
    ),
)
def test_table_and_continuation_net_sources_merge_or_conflict(
    continuation_amount: str,
    expected_amount: Decimal | None,
    expected_diagnostics: tuple[str, ...],
) -> None:
    source_row = _foreign_row()
    table_fee_cell = _positioned_cell(
        "net fee ILS 0.37",
        "net fee ILS 0.37",
        50.0,
        30.0,
    )
    row = _row(source_row.cells[0], table_fee_cell, *source_row.cells[2:])
    continuation_cell = _positioned_cell(
        f"net commission ILS {continuation_amount}",
        f"net commission ILS {continuation_amount}",
        50.0,
        40.0,
    )
    rows = (row, _bounded_continuation(continuation_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    if expected_amount is None:
        assert extraction.details.net_fee is None
        assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    else:
        assert extraction.details.net_fee is not None
        assert extraction.details.net_fee.amount == expected_amount
        net_claim = next(
            claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
        )
        assert ledger.atoms_for_cell(table_fee_cell) & net_claim.atom_ids
        assert ledger.atoms_for_cell(continuation_cell) & net_claim.atom_ids
    assert extraction.diagnostics == expected_diagnostics


@pytest.mark.parametrize(
    "fee_header",
    ("Gross fee", "Fee discount", "Exchange rate fee"),
)
def test_non_net_fee_header_semantics_are_not_coerced_to_net(fee_header: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.37", "0.37", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header=fee_header),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_table_net_fee_rejects_conflicting_logical_and_positioned_amounts() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.37", "0.38", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Net fee"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_table_net_fee_rejects_conflicting_semantic_renderings() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(
        "discount ILS 0.37",
        "reduced ILS 0.37",
        50.0,
        30.0,
    )
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_currencyless_nonzero_table_fee_inherits_matching_header_currency() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("1.25", "1.25", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Foreign-currency fee ILS"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("1.25")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.details.net_fee.evidence == (
        EvidenceReference(page_number=1, bbox=fee_cell.bbox, raw_text=fee_cell.text),
    )
    fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))
        if candidate.text == "1.25"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, fee_atom_ids),)
    assert extraction.diagnostics == ()


def test_currencyless_zero_table_fee_requires_one_non_percentage_decimal() -> None:
    source_row = _foreign_row()
    first_value_glyphs = _glyphs("0.00", 50.0, 30.0)
    second_value_glyphs = _glyphs("0.00", 65.0, 30.0)
    fee_cell = Cell(
        page_number=1,
        bbox=(50.0, 30.0, second_value_glyphs[-1].bbox[2], 40.0),
        text="0.00 0.00",
        glyphs=(*first_value_glyphs, *second_value_glyphs),
        confidence=1.0,
    )
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    ledger = EvidenceLedger.from_rows((row,))

    assert len(ledger.positioned_decimal_candidates(ledger.atoms_for_cell(fee_cell))) == 2

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_percent_bound_currencyless_zero_table_fee_remains_unparsed() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00%", "0.00%", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_other_currency_zero_table_fee_remains_unparsed() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("USD 0.00", "USD 0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "fee_text",
    (
        "₹0.29",
        "¥0.29",
        "₽0.29",
        "INR 0.29",
        "CNY 0.29",
        "- INR 0.29",
        "INR ILS 0.29",
        "₹ ILS 0.29",
        "Indian rupee ILS 0.29",
        "元 ILS 0.29",
    ),
)
def test_unsupported_currency_table_fee_remains_unparsed(fee_text: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "fee_header",
    (
        "Foreign fee INR",
        "Foreign fee ₹",
        "inr fee",
        "Inr fee",
        "cny commission",
        "Indian rupee fee",
        "renminbi fee",
        "元 fee",
        "USDINR fee",
        "INRUSD fee",
    ),
)
def test_unsupported_header_currency_table_fee_remains_unparsed(fee_header: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.29", "0.29", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header=fee_header),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "physical_text",
    (
        "credit ILS 0.29",
        "בזיכוי ILS 0.29",
        "USD 0.29",
        "₹ 0.29",
        "INR 0.29",
        "rupee ILS 0.29",
        "yuan ILS 0.29",
        "renminbi ILS 0.29",
        "franc ILS 0.29",
        "krona ILS 0.29",
    ),
)
def test_table_fee_requires_compatible_logical_and_positioned_context(
    physical_text: str,
) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("ILS 0.29", physical_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_table_fee_accepts_directionally_reconstructed_rtl_context() -> None:
    source_row = _foreign_row()
    amount_glyphs = _glyphs("0.29", 50.0, 30.0)
    currency_glyphs = _glyphs("ILS", 60.0, 30.0)
    fee_glyphs = _rtl_glyphs("עמלה", 80.0, 30.0)
    fee_cell = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 80.0, 40.0),
        text="עמלה ILS 0.29",
        glyphs=(*amount_glyphs, *currency_glyphs, *fee_glyphs),
        confidence=1.0,
    )
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("fee_text", "word_source", "expected_amount"),
    (
        ("1₪234", "ocr", Decimal("1234")),
        ("1{234", "ocr", Decimal("1234")),
        ("1{234", "digital", None),
    ),
)
def test_table_fee_preserves_one_indivisible_rtl_currency_word(
    fee_text: str,
    word_source: str,
    expected_amount: Decimal | None,
) -> None:
    source_row = _foreign_row()
    fee_cell = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 90.0, 40.0),
        text=fee_text,
        words=(
            Word(
                text=fee_text,
                bbox=(50.0, 30.0, 90.0, 40.0),
                source=word_source,
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )
    row = _row(
        _cell("₪2000.00", 0, 30.0),
        fee_cell,
        *source_row.cells[2:],
    )

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert (
        extraction.details.net_fee.amount if extraction.details.net_fee is not None else None
    ) == expected_amount
    assert extraction.diagnostics == (
        () if expected_amount is not None else ("unparsed_foreign_currency_fee_candidate",)
    )


@pytest.mark.parametrize(
    ("second_text", "second_source", "expected_amount"),
    (
        ("56.78", "ocr", Decimal("1234")),
        ("₪5678", "ocr", Decimal("1234")),
        ("₪1234", "ocr", None),
        ("5₪678", "ocr", None),
        ("₪5678", "digital", None),
    ),
)
def test_repeated_ocr_currency_words_require_one_rendered_variable_fee_anchor(
    second_text: str,
    second_source: str,
    expected_amount: Decimal | None,
) -> None:
    def fee_cell(text: str, y: float, source: str, confidence: float) -> Cell:
        return Cell(
            page_number=1,
            bbox=(50.0, y, 90.0, y + 10.0),
            text=text,
            words=(
                Word(
                    text=text,
                    bbox=(50.0, y, 90.0, y + 10.0),
                    source=source,
                    confidence=confidence,
                ),
            ),
            confidence=confidence,
        )

    first_source = _foreign_row()
    second_source_row = _foreign_row()
    first_fee = fee_cell("1₪234", 30.0, "ocr", 0.55)
    second_fee = fee_cell(second_text, 50.0, second_source, 0.65)
    first_row = _row(first_source.cells[0], first_fee, *first_source.cells[2:])
    second_row = _row(
        second_source_row.cells[0],
        second_fee,
        *second_source_row.cells[2:],
    )
    region = _region(first_row).model_copy(update={"rows": (first_row, second_row)})

    extraction = extract_foreign_exchange(
        rows=(first_row,),
        region=region,
        ledger=EvidenceLedger.from_rows((first_row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert (
        extraction.details.net_fee.amount if extraction.details.net_fee is not None else None
    ) == expected_amount
    assert extraction.diagnostics == (
        () if expected_amount is not None else ("unparsed_foreign_currency_fee_candidate",)
    )


def test_conflicting_currency_zero_table_fee_remains_unparsed() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("ILS USD 0.00", "ILS USD 0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_currencyless_zero_table_fee_rejects_conflicting_header_currency() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00", "0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Foreign-currency fee USD"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_currencyless_zero_ignores_other_rows_in_column_header_sources() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00", "0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    region = _region(row)
    other_row_sample = _cell("USD 1.00", 1, 50.0)
    columns = tuple(
        column.model_copy(update={"source_cells": (*column.source_cells, other_row_sample)})
        if column.role is ColumnRole.AUXILIARY_AMOUNT
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
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.00")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.diagnostics == ()


def test_body_source_sample_cannot_supply_missing_fee_header_semantics() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00", "0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])
    region = _region(row, fee_header="Auxiliary amount")
    columns = tuple(
        column.model_copy(update={"source_cells": (fee_cell,)})
        if column.role is ColumnRole.AUXILIARY_AMOUNT
        else column
        for column in region.table_schema.columns
    )
    fee_source_sample = fee_cell.model_copy(update={"text": "Foreign-currency fee"})
    columns = tuple(
        column.model_copy(update={"source_cells": (fee_source_sample,)})
        if column.role is ColumnRole.AUXILIARY_AMOUNT
        else column
        for column in columns
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
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert "unparsed_foreign_currency_fee_candidate" not in extraction.diagnostics


def test_body_source_sample_cannot_supply_missing_rate_header_semantics() -> None:
    row = _foreign_row()
    region = _region(row, rate_header="Conversion date")
    rate_source_sample = row.cells[2].model_copy(update={"text": "Exchange rate"})
    columns = tuple(
        column.model_copy(update={"source_cells": (rate_source_sample,)})
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
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is None
    assert "unparsed_exchange_rate_candidate" not in extraction.diagnostics


def test_currencyless_zero_requires_explicit_fee_header() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("0.00", "0.00", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" not in extraction.diagnostics


def test_zero_exchange_rate_remains_unparsed() -> None:
    row = _foreign_row("22/06/26 0.0000")

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "rate_text",
    (
        "22/06/26 -2.9660 3.0010",
        "22/06/26 0.0000 2.9430",
        "22/06/26 1 and 2.9430",
    ),
)
def test_invalid_or_integer_table_rate_competes_with_valid_decimal(
    rate_text: str,
) -> None:
    row = _foreign_row(rate_text)

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize("rate", ("2.943", "0.943"))
def test_three_decimal_table_exchange_rate_is_preserved(rate: str) -> None:
    row = _foreign_row(f"22/06/26 {rate}")

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal(rate)
    assert extraction.diagnostics == ()


def test_three_decimal_continuation_exchange_rate_is_preserved() -> None:
    base_row = _base_row_without_fx_values()
    rate_row = _bounded_continuation(_positioned_cell("exchange rate 2.943", "2.943", 50.0, 40.0))
    rows = (base_row, rate_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.943")
    assert extraction.diagnostics == ()


def test_three_fraction_digit_table_fee_remains_ambiguous() -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell("ILS 1,234", "ILS 1,234", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_repeated_bound_currency_annotation_preserves_variable_table_fee() -> None:
    first_source = _foreign_row()
    second_source = _foreign_row()
    first_fee = _positioned_cell("3₪ 1.69", "3 ₪ 1.69", 50.0, 30.0)
    second_fee = _positioned_cell("3₪ 0.29", "3 ₪ 0.29", 50.0, 40.0)
    first_row = _row(first_source.cells[0], first_fee, *first_source.cells[2:])
    second_row = _row(second_source.cells[0], second_fee, *second_source.cells[2:])
    region = _region(first_row).model_copy(update={"rows": (first_row, second_row)})

    extraction = extract_foreign_exchange(
        rows=(first_row,),
        region=region,
        ledger=EvidenceLedger.from_rows((first_row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("1.69")
    assert extraction.diagnostics == ()


def test_repeated_bound_currency_annotation_allows_logical_whitespace() -> None:
    first_source = _foreign_row()
    second_source = _foreign_row()
    first_fee = _positioned_cell("3 ₪ 1.69", "3 ₪ 1.69", 50.0, 30.0)
    second_fee = _positioned_cell("3 ₪ 0.29", "3 ₪ 0.29", 50.0, 40.0)
    first_row = _row(first_source.cells[0], first_fee, *first_source.cells[2:])
    second_row = _row(second_source.cells[0], second_fee, *second_source.cells[2:])
    region = _region(first_row).model_copy(update={"rows": (first_row, second_row)})

    extraction = extract_foreign_exchange(
        rows=(first_row,),
        region=region,
        ledger=EvidenceLedger.from_rows((first_row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("1.69")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("first_text", "first_physical", "second_text", "second_physical"),
    (
        ("₪ 3 1.69", "₪ 3 1.69", "₪ 3 0.29", "₪ 3 0.29"),
        ("3 X ₪ 1.69", "3 X ₪ 1.69", "3 X ₪ 0.29", "3 X ₪ 0.29"),
        ("3 ₪ 1.69", "3 ₪ 1.68", "3 ₪ 0.29", "3 ₪ 0.28"),
        ("3 ₪ 1.69 2.00", "3 ₪ 1.69 2.00", "3 ₪ 0.29 2.00", "3 ₪ 0.29 2.00"),
    ),
    ids=("reordered", "extra-character", "source-mismatch", "competing-decimal"),
)
def test_repeated_bound_currency_annotation_rejects_non_whitespace_changes(
    first_text: str,
    first_physical: str,
    second_text: str,
    second_physical: str,
) -> None:
    first_source = _foreign_row()
    second_source = _foreign_row()
    first_fee = _positioned_cell(first_text, first_physical, 50.0, 30.0)
    second_fee = _positioned_cell(second_text, second_physical, 50.0, 40.0)
    first_row = _row(first_source.cells[0], first_fee, *first_source.cells[2:])
    second_row = _row(second_source.cells[0], second_fee, *second_source.cells[2:])
    region = _region(first_row).model_copy(update={"rows": (first_row, second_row)})

    extraction = extract_foreign_exchange(
        rows=(first_row,),
        region=region,
        ledger=EvidenceLedger.from_rows((first_row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_repeated_bound_currency_annotation_requires_variable_table_fee() -> None:
    first_source = _foreign_row()
    second_source = _foreign_row()
    first_fee = _positioned_cell("3₪ 1.69", "3 ₪ 1.69", 50.0, 30.0)
    second_fee = _positioned_cell("3₪ 1.69", "3 ₪ 1.69", 50.0, 40.0)
    first_row = _row(first_source.cells[0], first_fee, *first_source.cells[2:])
    second_row = _row(second_source.cells[0], second_fee, *second_source.cells[2:])
    region = _region(first_row).model_copy(update={"rows": (first_row, second_row)})

    extraction = extract_foreign_exchange(
        rows=(first_row,),
        region=region,
        ledger=EvidenceLedger.from_rows((first_row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "fee_text",
    (
        "ILS 1,234 0.29",
        "ILS 1.234 and 0.29",
        "ILS -0.29 0.10",
        "ILS 1 and 0.29",
        "ILS 0 and 0.29",
        "1 ILS 0.29",
        "1 ₪ 0.29",
        "3 ₪ 1.69",
    ),
)
def test_invalid_or_integer_table_fee_competes_with_valid_decimal(fee_text: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize("rate_text", ("22/06/26 -2.9660", "22/06/26 2.9660%"))
def test_signed_or_percent_typed_table_rate_remains_unparsed(rate_text: str) -> None:
    row = _foreign_row(rate_text)

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "sign",
    ("-", "\N{MINUS SIGN}", "\N{EN DASH}", "\N{EM DASH}"),
)
def test_sign_before_currency_continuation_rate_remains_unparsed(sign: str) -> None:
    base_row = _base_row_without_fx_values()
    rate_row = _bounded_continuation(
        _positioned_cell(
            f"exchange rate {sign}ILS 2.9430",
            f"{sign}ILS 2.9430",
            50.0,
            40.0,
        )
    )
    rows = (base_row, rate_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.EXCHANGE_RATE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "currency",
    (
        "₹",
        "INR ",
        "Inr ",
        "inr ",
        "₹INR ",
        "INR₹ ",
        "USD/ILS ",
        "USDILS ",
        "usdils ",
        "USD ILS ",
    ),
)
def test_sign_before_unsupported_currency_continuation_rate_remains_unparsed(
    currency: str,
) -> None:
    base_row = _base_row_without_fx_values()
    rate_row = _bounded_continuation(
        _positioned_cell(
            f"exchange rate -{currency}2.9430",
            f"-{currency}2.9430",
            50.0,
            40.0,
        )
    )
    rows = (base_row, rate_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.EXCHANGE_RATE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "sign",
    ("-", "+", "\N{MINUS SIGN}", "\N{EN DASH}", "\N{EM DASH}"),
)
def test_signed_table_fee_remains_unparsed(sign: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(f"ILS {sign}0.29", f"ILS {sign}0.29", 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "fee_text",
    (
        "-ILS 0.29",
        "\N{MINUS SIGN}ILS 0.29",
        "\N{EN DASH}ILS 0.29",
        "-\N{NEW SHEQEL SIGN} 0.29",
    ),
)
def test_sign_before_currency_table_fee_remains_unparsed(fee_text: str) -> None:
    source_row = _foreign_row()
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "currency_words",
    (
        (("ILS", 52.0, 60.0),),
        (("I", 52.0, 54.0), ("LS", 54.0, 60.0)),
        (("IL", 52.0, 56.0), ("S", 56.0, 60.0)),
    ),
)
def test_split_word_sign_before_currency_table_fee_remains_unparsed(
    currency_words: tuple[tuple[str, float, float], ...],
) -> None:
    source_row = _foreign_row()
    fee_cell = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 65.0, 40.0),
        text="- ILS 0.29",
        words=(
            Word(text="-", bbox=(50.0, 30.0, 52.0, 40.0), source="digital", confidence=1.0),
            *(
                Word(
                    text=text,
                    bbox=(x0, 30.0, x1, 40.0),
                    source="digital",
                    confidence=1.0,
                )
                for text, x0, x1 in currency_words
            ),
            Word(
                text="0.29",
                bbox=(60.0, 30.0, 68.0, 40.0),
                source="digital",
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "marker",
    ("credit", "refund", "credited", "זיכוי", "בזיכוי", "כזיכוי", "בהחזר"),
)
def test_credit_marked_table_fee_remains_unparsed(marker: str) -> None:
    source_row = _foreign_row()
    fee_text = f"ILS 0.29 {marker}"
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "marker",
    ("credit", "refund", "זיכוי", "בזיכוי", "כזיכוי", "בהחזר"),
)
def test_credit_marked_currencyless_table_fee_remains_unparsed(marker: str) -> None:
    source_row = _foreign_row()
    fee_text = f"0.29 {marker}"
    fee_cell = _positioned_cell(fee_text, fee_text, 50.0, 30.0)
    row = _row(source_row.cells[0], fee_cell, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_extract_foreign_exchange_does_not_require_conversion_date() -> None:
    row = _foreign_row()
    region = _region(row)
    ledger = EvidenceLedger.from_rows((row,))

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=region,
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")


def test_extract_foreign_exchange_ignores_same_currency_row() -> None:
    row = _foreign_row()

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="ILS",
        billing_currency="ILS",
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
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert "unparsed_foreign_currency_fee_candidate" not in extraction.diagnostics
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)


def test_corporate_date_header_does_not_make_conversion_date_an_exchange_rate() -> None:
    assert not _contains_cue("corporate date", ("rate",))

    row = _foreign_row()
    region = _region(row, rate_header="Corporate date")

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=region,
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
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
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_one_valid_table_rate_cannot_mask_an_unreadable_rate_cell() -> None:
    source_row = _foreign_row("2.9660")
    unreadable_rate = _positioned_cell("unreadable", "unreadable", 115.0, 30.0)
    row = _row(*source_row.cells[:3], unreadable_rate, *source_row.cells[3:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_one_valid_table_fee_cannot_mask_an_unreadable_fee_cell() -> None:
    source_row = _foreign_row()
    unreadable_fee = _positioned_cell("unreadable", "unreadable", 65.0, 30.0)
    row = _row(*source_row.cells[:2], unreadable_fee, *source_row.cells[2:])

    extraction = extract_foreign_exchange(
        rows=(row,),
        region=_region(row),
        ledger=EvidenceLedger.from_rows((row,)),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


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
    )

    assert extraction.details is None
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)
    assert extraction.claims == ()


def test_ambiguous_table_fee_is_not_repopulated_from_continuation() -> None:
    source_row = _foreign_row()
    unreadable_fee = _positioned_cell("unreadable", "unreadable", 65.0, 30.0)
    row = _row(*source_row.cells[:2], unreadable_fee, *source_row.cells[2:])
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 1.69", "reduced fee ILS 1.69", 50.0, 50.0)
    )
    rows = (row, percentage_row, reduced_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


def test_ambiguous_continuation_fee_invalidates_table_net_fee() -> None:
    row = _foreign_row()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    first_reduced = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "ILS 0.29", 50.0, 50.0)
    )
    second_reduced = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.10", "ILS 0.10", 50.0, 60.0)
    )
    rows = (row, percentage_row, first_reduced, second_reduced)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


def test_ambiguous_continuation_gross_fee_does_not_invalidate_table_net_fee() -> None:
    row = _foreign_row()
    malformed_gross = _bounded_continuation(
        _positioned_cell(
            "fee amount ILS 0.88 and 0.90",
            "ILS 0.88 and 0.90",
            50.0,
            40.0,
        )
    )
    rows = (row, malformed_gross)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("1.69")
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


def test_equal_table_and_continuation_rates_merge_evidence_and_claims() -> None:
    row = _foreign_row("2.9660")
    continuation_cell = _positioned_cell("exchange rate 2.9660", "2.9660", 50.0, 40.0)
    continuation = _bounded_continuation(continuation_cell)
    rows = (row, continuation)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9660")
    assert extraction.details.exchange_rate.evidence == (
        EvidenceReference(page_number=1, bbox=row.cells[2].bbox, raw_text=row.cells[2].text),
        EvidenceReference(
            page_number=1,
            bbox=continuation_cell.bbox,
            raw_text=continuation_cell.text,
        ),
    )
    rate_claims = tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.EXCHANGE_RATE
    )
    assert len(rate_claims) == 1
    assert rate_claims[0].atom_ids == (
        ledger.atoms_for_cell(row.cells[2]) | ledger.atoms_for_cell(continuation_cell)
    )
    assert extraction.diagnostics == ()


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


def test_standalone_reduced_fee_is_an_explicit_net_fee_source() -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        "reduced fee ILS 0.37",
        "reduced fee ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    assert extraction.details.net_fee.currency == "ILS"
    net_fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(net_fee_cell))
        if candidate.text == "0.37"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, net_fee_atom_ids),)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize("net_label", ("net fee", "net amount"))
def test_standalone_literal_net_source_is_explicit(net_label: str) -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        f"{net_label} ILS 0.37",
        f"{net_label} ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    net_fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(net_fee_cell))
        if candidate.text == "0.37"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, net_fee_atom_ids),)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "net_label",
    (
        "net commission",
        "net surcharge",
        "fee net",
        "net foreign-currency fee",
        "עמלה נטו",
    ),
)
def test_net_modifier_and_fee_noun_compose_in_either_order(net_label: str) -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        f"{net_label} ILS 0.37",
        f"{net_label} ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize("reduced_modifier", ("reduced", "מופחתת"))
def test_bounded_reduced_modifier_alone_types_net_fee(reduced_modifier: str) -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        f"{reduced_modifier} ILS 0.37",
        f"{reduced_modifier} ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "source_text",
    (
        "reduced discount ILS 0.10",
        "discount reduced ILS 0.10",
        "הנחה מופחתת ILS 0.10",
        "reduced discount amount ILS 0.10",
        "net discount amount ILS 0.10",
        "discount net amount ILS 0.10",
    ),
)
def test_reduced_discount_collision_does_not_type_net_fee(source_text: str) -> None:
    base_row = _base_row_without_fx_values()
    collision_row = _bounded_continuation(_positioned_cell(source_text, source_text, 50.0, 40.0))
    rows = (base_row, collision_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize("net_modifier", ("net", "נטו"))
def test_bare_net_modifier_without_fee_noun_remains_ambiguous(net_modifier: str) -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        f"{net_modifier} ILS 0.37",
        f"{net_modifier} ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_unreadable_literal_net_source_remains_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        "net fee ILS unreadable",
        "net fee ILS unreadable",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_positioned_reduced_fee_cue_types_logical_money_source() -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        "ILS 0.37",
        "reduced fee ILS 0.37",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.37")
    assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("logical_text", "positioned_text"),
    (
        ("net ILS 0.37", "fee ILS 0.37"),
        ("נטו ILS 0.37", "עמלה ILS 0.37"),
    ),
)
def test_net_semantics_cannot_be_composed_across_alternative_renderings(
    logical_text: str,
    positioned_text: str,
) -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        logical_text,
        positioned_text,
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_continuation_net_fee_rejects_conflicting_rendered_amounts() -> None:
    base_row = _base_row_without_fx_values()
    net_fee_cell = _positioned_cell(
        "net fee ILS 0.37",
        "net fee ILS 0.38",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_continuation_rate_rejects_conflicting_rendered_values() -> None:
    base_row = _base_row_without_fx_values()
    rate_cell = _positioned_cell(
        "exchange rate 2.9430",
        "exchange rate 2.9660",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(rate_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "annotation",
    ("merchant", "INR", "₹", "EUR"),
)
def test_continuation_rate_rejects_invalid_context(annotation: str) -> None:
    base_row = _base_row_without_fx_values()
    rate_text = f"exchange rate {annotation} 2.9430"
    rows = (
        base_row,
        _bounded_continuation(_positioned_cell(rate_text, rate_text, 50.0, 40.0)),
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


def test_continuation_rate_accepts_original_and_billing_currency_context() -> None:
    base_row = _base_row_without_fx_values()
    rate_text = "exchange rate USD/ILS 2.9430"
    rows = (
        base_row,
        _bounded_continuation(_positioned_cell(rate_text, rate_text, 50.0, 40.0)),
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9430")
    assert extraction.diagnostics == ()


def test_fee_percentage_rejects_conflicting_rendered_values() -> None:
    base_row = _base_row_without_fx_values()
    percentage_cell = _positioned_cell(
        "foreign-currency fee 3.00%",
        "foreign-currency fee 2.50%",
        50.0,
        40.0,
    )
    rows = (base_row, _bounded_continuation(percentage_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


@pytest.mark.parametrize(
    "annotation",
    ("merchant", "reference", "INR", "₹", "EUR"),
)
def test_fee_percentage_rejects_invalid_context(annotation: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_text = f"foreign-currency fee {annotation} 3.00%"
    rows = (
        base_row,
        _bounded_continuation(_positioned_cell(percentage_text, percentage_text, 50.0, 40.0)),
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_fee_percentage_accepts_original_and_billing_currency_context() -> None:
    base_row = _base_row_without_fx_values()
    percentage_text = "foreign-currency fee USD/ILS 3.00%"
    rows = (
        base_row,
        _bounded_continuation(_positioned_cell(percentage_text, percentage_text, 50.0, 40.0)),
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.diagnostics == ()


def test_gross_fee_rejects_conflicting_rendered_values() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    gross_cell = _positioned_cell(
        "fee amount ILS 0.88",
        "fee amount ILS 0.90",
        50.0,
        50.0,
    )
    rows = (base_row, percentage_row, _bounded_continuation(gross_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.gross_fee is None
    assert all(claim.owner is not SemanticOwner.GROSS_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_fee_discount_rejects_conflicting_rendered_values() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    gross_row = _bounded_continuation(
        _positioned_cell(
            "fee amount ILS 0.88; discount follows",
            "fee amount ILS 0.88; discount follows",
            50.0,
            50.0,
        )
    )
    discount_cell = _positioned_cell(
        "discount ILS 0.59",
        "discount ILS 0.60",
        50.0,
        60.0,
    )
    rows = (
        base_row,
        percentage_row,
        gross_row,
        _bounded_continuation(discount_cell),
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_DISCOUNT for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_discount_candidate",)


@pytest.mark.parametrize(
    ("second_amount", "expected_amount", "expected_diagnostics"),
    (
        ("0.37", Decimal("0.37"), ()),
        ("0.38", None, ("unparsed_foreign_currency_fee_candidate",)),
    ),
)
def test_repeated_literal_net_sources_are_merged_or_rejected(
    second_amount: str,
    expected_amount: Decimal | None,
    expected_diagnostics: tuple[str, ...],
) -> None:
    base_row = _base_row_without_fx_values()
    first_cell = _positioned_cell("net fee ILS 0.37", "net fee ILS 0.37", 50.0, 40.0)
    second_cell = _positioned_cell(
        f"net amount ILS {second_amount}",
        f"net amount ILS {second_amount}",
        50.0,
        50.0,
    )
    rows = (
        base_row,
        _bounded_continuation(first_cell),
        _bounded_continuation(second_cell),
    )
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    if expected_amount is None:
        assert extraction.details is None
        assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    else:
        assert extraction.details is not None
        assert extraction.details.net_fee is not None
        assert extraction.details.net_fee.amount == expected_amount
        net_claim = next(
            claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
        )
        assert ledger.atoms_for_cell(first_cell) & net_claim.atom_ids
        assert ledger.atoms_for_cell(second_cell) & net_claim.atom_ids
    assert extraction.diagnostics == expected_diagnostics


def test_equivalent_reduced_fee_source_merges_with_derived_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows()
    net_fee_cell = _positioned_cell(
        "reduced fee ILS 0.29",
        "reduced fee ILS 0.29",
        50.0,
        80.0,
    )
    rows = (base_row, *continuation_rows, _bounded_continuation(net_fee_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.gross_fee is not None
    assert details.fee_discount is not None
    assert details.net_fee is not None
    assert details.net_fee.amount == Decimal("0.29")
    assert details.net_fee.currency == "ILS"
    assert details.net_fee.derivation == "printed"
    assert (
        EvidenceReference(
            page_number=1,
            bbox=net_fee_cell.bbox,
            raw_text=net_fee_cell.text,
        )
        in details.net_fee.evidence
    )
    net_fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(net_fee_cell))
        if candidate.text == "0.29"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, net_fee_atom_ids),)
    assert extraction.diagnostics == ()


def test_conflicting_reduced_fee_source_invalidates_derived_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows()
    net_fee_cell = _positioned_cell(
        "reduced fee ILS 0.30",
        "reduced fee ILS 0.30",
        50.0,
        80.0,
    )
    rows = (base_row, *continuation_rows, _bounded_continuation(net_fee_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    net_fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(net_fee_cell))
        if candidate.text == "0.30"
    )
    claimed_atom_ids = frozenset(
        atom_id for claim in extraction.claims for atom_id in claim.atom_ids
    )
    assert net_fee_atom_ids.isdisjoint(claimed_atom_ids)
    assert extraction.diagnostics == ("inconsistent_foreign_currency_fee_derivation",)


@pytest.mark.parametrize(
    ("direct_amount", "expected_amount", "expected_diagnostics"),
    (
        ("0.29", Decimal("0.29"), ()),
        ("0.30", None, ("inconsistent_foreign_currency_fee_derivation",)),
    ),
)
def test_direct_net_before_typed_derivation_merges_or_conflicts(
    direct_amount: str,
    expected_amount: Decimal | None,
    expected_diagnostics: tuple[str, ...],
) -> None:
    base_row = _base_row_without_fx_values()
    direct_cell = _positioned_cell(
        f"reduced fee ILS {direct_amount}",
        f"reduced fee ILS {direct_amount}",
        50.0,
        35.0,
    )
    continuation_rows = _continuation_rows()
    rows = (
        base_row,
        _bounded_continuation(direct_cell),
        *continuation_rows,
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    if expected_amount is None:
        assert extraction.details.net_fee is None
        assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    else:
        assert extraction.details.net_fee is not None
        assert extraction.details.net_fee.amount == expected_amount
        assert any(claim.owner is SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == expected_diagnostics


def test_invalid_typed_derivation_invalidates_independently_printed_net() -> None:
    base_row = _base_row_without_fx_values()
    direct_cell = _positioned_cell(
        "reduced fee ILS 0.10",
        "reduced fee ILS 0.10",
        50.0,
        35.0,
    )
    continuation_rows = _continuation_rows(gross_fee="0.50", discount="0.59")
    rows = (
        base_row,
        _bounded_continuation(direct_cell),
        *continuation_rows,
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("inconsistent_foreign_currency_fee_derivation",)


@pytest.mark.parametrize(
    ("gross_amount", "expected_net", "expected_diagnostics"),
    (
        ("0.30", Decimal("0.29"), ()),
        ("0.29", Decimal("0.29"), ()),
        ("0.10", None, ("inconsistent_foreign_currency_fee_derivation",)),
    ),
)
def test_printed_net_cannot_exceed_gross_fee(
    gross_amount: str,
    expected_net: Decimal | None,
    expected_diagnostics: tuple[str, ...],
) -> None:
    base_row = _base_row_without_fx_values()
    gross_row = _bounded_continuation(
        _positioned_cell(
            f"gross fee ILS {gross_amount}",
            f"gross fee ILS {gross_amount}",
            50.0,
            40.0,
        )
    )
    net_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 50.0)
    )
    rows = (base_row, gross_row, net_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    if expected_net is None:
        assert extraction.details.net_fee is None
        assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    else:
        assert extraction.details.net_fee is not None
        assert extraction.details.net_fee.amount == expected_net
    assert extraction.diagnostics == expected_diagnostics


def test_table_net_cannot_exceed_continuation_gross_fee() -> None:
    row = _foreign_row()
    gross_row = _bounded_continuation(
        _positioned_cell("gross fee ILS 1.00", "gross fee ILS 1.00", 50.0, 40.0)
    )
    rows = (row, gross_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("inconsistent_foreign_currency_fee_derivation",)


@pytest.mark.parametrize("unowned_first", (False, True))
def test_unowned_bounded_money_invalidates_direct_net_in_any_order(
    unowned_first: bool,
) -> None:
    base_row = _base_row_without_fx_values()
    unowned_y, direct_y = (40.0, 50.0) if unowned_first else (50.0, 40.0)
    unowned_row = _bounded_continuation(_positioned_cell("ILS 0.10", "ILS 0.10", 50.0, unowned_y))
    direct_net_row = _bounded_continuation(
        _positioned_cell("net fee ILS 0.37", "net fee ILS 0.37", 50.0, direct_y)
    )
    detail_rows = (unowned_row, direct_net_row) if unowned_first else (direct_net_row, unowned_row)
    rows = (base_row, *detail_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "source_text",
    ("ILS 0.10", "reference ILS 0.10", "ILS 1", "0.10", "2.9430"),
)
def test_unowned_bounded_money_without_net_is_diagnosed(source_text: str) -> None:
    base_row = _base_row_without_fx_values()
    unowned_row = _bounded_continuation(_positioned_cell(source_text, source_text, 50.0, 40.0))
    rows = (base_row, unowned_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize("source_text", ("reference 1", "merchant 2.9430"))
def test_unrelated_numeric_bounded_detail_without_currency_is_nonblocking(
    source_text: str,
) -> None:
    base_row = _base_row_without_fx_values()
    unrelated_row = _bounded_continuation(_positioned_cell(source_text, source_text, 50.0, 40.0))
    rows = (base_row, unrelated_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ()


@pytest.mark.parametrize("source_text", ("3.00%", "ILS 3.00%"))
def test_unowned_bounded_percentage_is_diagnosed(source_text: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(_positioned_cell(source_text, source_text, 50.0, 40.0))
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


@pytest.mark.parametrize("source_text", ("reference 3.00%", "merchant 3.00%"))
def test_unrelated_bounded_percentage_is_nonblocking(source_text: str) -> None:
    base_row = _base_row_without_fx_values()
    unrelated_row = _bounded_continuation(_positioned_cell(source_text, source_text, 50.0, 40.0))
    rows = (base_row, unrelated_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ()


def test_fee_cue_types_bounded_percentage() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(_positioned_cell("fee 3.00%", "fee 3.00%", 50.0, 40.0))
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("percentage_text", "expect_percentage", "expected_diagnostics"),
    (
        (
            "foreign-currency fee 3.00% ILS 0.88",
            True,
            ("unparsed_foreign_currency_fee_candidate",),
        ),
        (
            "foreign-currency fee 3.00% reference ILS 0.10",
            False,
            (
                "unparsed_foreign_currency_fee_percentage_candidate",
                "unparsed_foreign_currency_fee_candidate",
            ),
        ),
    ),
)
def test_unclaimed_money_on_percentage_row_invalidates_direct_net(
    percentage_text: str,
    expect_percentage: bool,
    expected_diagnostics: tuple[str, ...],
) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(percentage_text, percentage_text, 50.0, 40.0)
    )
    direct_net_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 50.0)
    )
    rows = (base_row, percentage_row, direct_net_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    if expect_percentage:
        assert extraction.details is not None
        assert extraction.details.fee_percentage is not None
        assert extraction.details.net_fee is None
    else:
        assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == expected_diagnostics


def test_direct_net_does_not_silently_clear_pending_discount() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00%",
            "foreign-currency fee 3.00%",
            50.0,
            40.0,
        )
    )
    gross_row = _bounded_continuation(
        _positioned_cell(
            "fee amount ILS 0.88; discount follows",
            "fee amount ILS 0.88; discount follows",
            50.0,
            50.0,
        )
    )
    direct_net_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, gross_row, direct_net_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_discount_candidate",)


def test_bare_decimal_in_pending_gross_slot_remains_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00%",
            "foreign-currency fee 3.00%",
            50.0,
            40.0,
        )
    )
    bare_amount_row = _bounded_continuation(_positioned_cell("0.88", "0.88", 50.0, 50.0))
    direct_net_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, bare_amount_row, direct_net_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_reference_integer_in_pending_gross_slot_remains_nonmonetary() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00%",
            "foreign-currency fee 3.00%",
            50.0,
            40.0,
        )
    )
    reference_row = _bounded_continuation(
        _positioned_cell("reference 1", "reference 1", 50.0, 50.0)
    )
    direct_net_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, reference_row, direct_net_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
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


def test_cross_field_arithmetic_proves_one_coherent_positioned_fx_layer() -> None:
    base_row, continuation_rows = _coherent_projected_fx_rows()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.89")
    assert extraction.details.fee_discount is not None
    assert extraction.details.fee_discount.amount == Decimal("0.20")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_positioned_fx_proof_finalizer_owns_values_and_ordered_claims() -> None:
    import ccparser.fx as fx_module

    rate_evidence = (EvidenceReference(page_number=1, bbox=(0, 10, 10, 20), raw_text="rate"),)
    percentage_evidence = (
        EvidenceReference(page_number=1, bbox=(0, 20, 10, 30), raw_text="percentage"),
    )
    gross_evidence = (EvidenceReference(page_number=1, bbox=(0, 30, 10, 40), raw_text="gross"),)
    discount_evidence = (
        EvidenceReference(page_number=1, bbox=(0, 40, 10, 50), raw_text="discount"),
    )
    proof = fx_module._PositionedFxProof(
        exchange_rate=fx_module._PositionedDecimalProof(
            value=Decimal("2.9720"),
            evidence=rate_evidence,
            atom_ids=frozenset((1,)),
        ),
        fee_percentage=fx_module._PositionedDecimalProof(
            value=Decimal("3.00"),
            evidence=percentage_evidence,
            atom_ids=frozenset((2,)),
        ),
        gross_fee=fx_module._PositionedMoneyProof(
            amount=Decimal("0.89"),
            currency="ILS",
            evidence=gross_evidence,
            atom_ids=frozenset((3,)),
        ),
        fee_discount=fx_module._PositionedMoneyProof(
            amount=Decimal("0.20"),
            currency="ILS",
            evidence=discount_evidence,
            atom_ids=frozenset((4,)),
        ),
        discount_percentage_atom_ids=frozenset((5,)),
        ancillary_claim=EvidenceClaim(SemanticOwner.ANCILLARY, frozenset((6,))),
    )

    values = fx_module._finalize_positioned_fx_proof(
        proof,
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert values is not None
    assert values.exchange_rate is not None
    assert values.exchange_rate.value == Decimal("2.9720")
    assert values.fee_percentage is not None
    assert values.fee_percentage.value == Decimal("3.00")
    assert values.gross_fee is not None
    assert values.fee_discount is not None
    assert values.net_fee is not None
    assert values.net_fee.amount == Decimal("0.69")
    assert values.net_fee.evidence == (*gross_evidence, *discount_evidence)
    assert values.claims == (
        EvidenceClaim(SemanticOwner.EXCHANGE_RATE, frozenset((1,))),
        EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, frozenset((2,))),
        EvidenceClaim(SemanticOwner.GROSS_FX_FEE, frozenset((3,))),
        EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, frozenset((4, 5))),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset((6,))),
    )
    with pytest.raises(FrozenInstanceError):
        proof.ancillary_claim = None


def test_cross_field_arithmetic_proves_compact_positioned_fx_layer() -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    rows = (base_row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.89")
    assert extraction.details.fee_discount is not None
    assert extraction.details.fee_discount.amount == Decimal("0.20")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.details.net_fee.derivation == "gross_fee_minus_discount"
    assert extraction.diagnostics == ()
    assert {claim.owner for claim in extraction.claims} == {
        SemanticOwner.EXCHANGE_RATE,
        SemanticOwner.FX_FEE_PERCENTAGE,
        SemanticOwner.GROSS_FX_FEE,
        SemanticOwner.FX_FEE_DISCOUNT,
    }
    assert ledger.validate_claims(extraction.claims).diagnostics == ()


def test_expanded_fx_layer_separates_projected_identifier_evidence() -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_projected_identifier_evidence()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.fee_discount.amount == Decimal("0.20")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_expanded_fx_layer_binds_corroborating_percentage_to_discount() -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    rows = (base_row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region_with_unknown_first_band(base_row),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.fee_discount.amount == Decimal("0.30")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.59")
    assert extraction.diagnostics == ()
    discount_percentage_cell = continuation_rows[3].cells[-1]
    discount_percentage = ledger.positioned_percentage_candidates(
        ledger.atoms_for_cell(discount_percentage_cell)
    )
    assert len(discount_percentage) == 1
    discount_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_DISCOUNT
    )
    assert discount_percentage[0].semantic_atom_ids <= discount_claim.atom_ids
    ancillary_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.ANCILLARY
    )
    metadata_atom_ids = frozenset(
        atom_id
        for row in continuation_rows
        for cell in row.cells
        if "projected_header_band:0" in cell.diagnostics
        for atom_id in ledger.atoms_for_cell(cell)
    )
    assert ancillary_claim.atom_ids == (
        metadata_atom_ids - discount_percentage[0].semantic_atom_ids
    )


@pytest.mark.parametrize(
    ("percentage", "basis", "amount", "expected"),
    (
        ("1", "100.00", "0.49", False),
        ("1", "100.00", "0.50", True),
        ("1", "100.00", "1.50", True),
        ("1", "100.00", "1.51", False),
        ("20", "100.00", "20.60", False),
    ),
)
def test_percentage_amount_proof_uses_displayed_precision_intervals(
    percentage: str,
    basis: str,
    amount: str,
    expected: bool,
) -> None:
    assert (
        _percentage_explains_amount(
            Decimal(percentage),
            Decimal(basis),
            Decimal(amount),
        )
        is expected
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "unbound_integer",
        "excess_percentage",
        "competing_currency",
        "competing_number",
        "financial_cue",
        "untrusted_glyph",
        "detached_marker",
    ),
)
def test_expanded_fx_layer_requires_exact_projected_percent_annotation(
    mutation: str,
) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_projected_identifier_evidence()
    mutable_rows = list(continuation_rows)
    percentage_row = mutable_rows[1]
    mutable_rows[1] = _bounded_continuation(
        *percentage_row.cells[:-1],
        _projected_positioned_cell("annotation", "annotation", 0.0, 50.0, 0),
    )
    source = {
        "unbound_integer": "annotation 7",
        "excess_percentage": "annotation 101%",
        "competing_currency": "annotation EUR 7%",
        "competing_number": "annotation 7% 8",
        "financial_cue": "fee 7%",
        "untrusted_glyph": "annotation 7%",
        "detached_marker": "annotation 7%",
    }[mutation]
    annotation = _projected_positioned_cell(source, source, 0.0, 70.0, 0)
    if mutation == "untrusted_glyph":
        glyphs = tuple(
            glyph.model_copy(update={"confidence": 0.4}) if glyph.char.isdigit() else glyph
            for glyph in annotation.glyphs
        )
        annotation = annotation.model_copy(update={"glyphs": glyphs})
    elif mutation == "detached_marker":
        glyphs = tuple(
            glyph.model_copy(
                update={
                    "bbox": (
                        glyph.bbox[0] + 20.0,
                        glyph.bbox[1],
                        glyph.bbox[2] + 20.0,
                        glyph.bbox[3],
                    ),
                    "origin": (glyph.origin[0] + 20.0, glyph.origin[1]),
                }
            )
            if glyph.char == "%"
            else glyph
            for glyph in annotation.glyphs
        )
        annotation = annotation.model_copy(update={"glyphs": glyphs})
    discount_row = mutable_rows[3]
    mutable_rows[3] = _bounded_continuation(*discount_row.cells[:-1], annotation)
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "source",
    (
        "VAT 1%",
        "interest 1%",
        "markup 1%",
        "discount 1%",
        "fee 1%",
        "metadata annotation detail -1%",
        "metadata annotation detail (1%)",
        "metadata annotation detail 1%-",
        "metadata annotation detail 1.0%",
        "metadata annotation detail 01%",
        "metadata annotation detail 0%",
        "metadata annotation detail 101%",
        "metadata annotation detail 1% 8",
        "metadata: annotation: detail 1%",
        "metadata annotation detail 2%",
        "metadata annotation detail 3%",
        "V:AT 1%",
        "f:\u2063ee 1%",
        "disc:ount 1%",
        "U:SD 1%",
        "f:\u200bee 1%",
        "V:\u200bAT 1%",
        "U:\u200bSD 1%",
        "f-ee 1%",
        "V::AT 1%",
        "U_SD 1%",
        "\uff36\uff21\uff34 1%",
        "\uff35\uff33\uff24 1%",
        "\uff46\uff45\uff45 1%",
        "metadata annotation detail 1\uff05",
        "metadata annotation detail 1\u066a",
        "metadata annotation detail 1\ufe6a",
    ),
)
def test_projected_metadata_percentage_rejects_competing_semantics(source: str) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    mutable_rows = list(continuation_rows)
    discount_row = mutable_rows[3]
    mutable_rows[3] = _bounded_continuation(
        *discount_row.cells[:-1],
        _projected_positioned_cell(source, source, 0.0, 70.0, 0),
    )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region_with_unknown_first_band(base_row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "header",
    (
        "VAT",
        "Interest rate",
        "Markup",
        "USD",
        "f\u200bee",
        "V\u200bAT",
        "U\u200bSD",
        "f-ee",
        "V::AT",
        "U_SD",
    ),
)
def test_projected_discount_percentage_rejects_competing_header_semantics(
    header: str,
) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region_with_unknown_first_band(base_row, header_text=header),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "source",
    ("V::AT detail", "f\u200bee detail", "U-SD detail"),
)
def test_projected_discount_percentage_rejects_competing_metadata_cell(
    source: str,
) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    mutable_rows = list(continuation_rows)
    gross_row = mutable_rows[2]
    mutable_rows[2] = _bounded_continuation(
        *gross_row.cells[:-1],
        _projected_positioned_cell(source, source, 0.0, 60.0, 0),
    )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region_with_unknown_first_band(base_row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize("row_index", (0, 1, 2, 3))
@pytest.mark.parametrize("marker", ("\uff05", "\u066a", "\ufe6a"))
def test_expanded_fx_layer_rejects_unsupported_percent_in_component_band(
    row_index: int,
    marker: str,
) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    mutable_rows = list(continuation_rows)
    row = mutable_rows[row_index]
    component = row.cells[0]
    band_diagnostic = next(
        diagnostic
        for diagnostic in component.diagnostics
        if diagnostic.startswith("projected_header_band:")
    )
    band = int(band_diagnostic.removeprefix("projected_header_band:"))
    physical_text = "".join(glyph.char for glyph in component.glyphs)
    replaced = _projected_positioned_cell(
        f"{component.text} {marker}",
        f"{physical_text} {marker}",
        component.bbox[0],
        component.bbox[1],
        band,
    )
    mutable_rows[row_index] = _bounded_continuation(replaced, *row.cells[1:])
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region_with_unknown_first_band(base_row),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_anchor",
        "duplicate_anchor",
        "missing_corroborator",
        "extra_numeric",
        "typed_band",
        "rendering_disagreement",
    ),
)
def test_projected_metadata_percentage_requires_complete_band_proof(mutation: str) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_metadata_percentage()
    mutable_rows = list(continuation_rows)
    region = _region_with_unknown_first_band(base_row)
    if mutation == "missing_anchor":
        percentage_row = mutable_rows[1]
        mutable_rows[1] = _bounded_continuation(
            *percentage_row.cells[:-1],
            _projected_positioned_cell(
                "metadata label value",
                "metadata value label",
                0.0,
                50.0,
                0,
            ),
        )
    elif mutation == "duplicate_anchor":
        gross_row = mutable_rows[2]
        mutable_rows[2] = _bounded_continuation(
            *gross_row.cells[:-1],
            _projected_positioned_cell(
                "card reference secondary label",
                "secondary label card reference",
                0.0,
                60.0,
                0,
            ),
        )
    elif mutation == "missing_corroborator":
        identifier_row = mutable_rows[4]
        mutable_rows[4] = _bounded_continuation(*identifier_row.cells[:-1])
    elif mutation == "extra_numeric":
        gross_row = mutable_rows[2]
        mutable_rows[2] = _bounded_continuation(
            *gross_row.cells[:-1],
            _projected_positioned_cell(
                "metadata detail 8",
                "detail metadata 8",
                0.0,
                60.0,
                0,
            ),
        )
    elif mutation == "typed_band":
        region = _region(base_row, fee_header="Auxiliary amount")
    else:
        discount_row = mutable_rows[3]
        positioned = discount_row.cells[-1]
        mutable_rows[3] = _bounded_continuation(
            *discount_row.cells[:-1],
            positioned.model_copy(update={"text": "metadata annotation detail 8%"}),
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=region,
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_identifier_label",
        "decimal_identifier_value",
        "financial_label",
        "nonadjacent_split_identifier",
        "unprojected_identifier_value",
    ),
)
def test_expanded_fx_layer_requires_exact_projected_identifier_proof(mutation: str) -> None:
    base_row, continuation_rows = _expanded_fx_rows_with_projected_identifier_evidence()
    mutable_rows = list(continuation_rows)
    if mutation == "missing_identifier_label":
        mutable_rows[1] = _bounded_continuation(*mutable_rows[1].cells[:-1])
    elif mutation in {"decimal_identifier_value", "unprojected_identifier_value"}:
        discount_row = mutable_rows[3]
        value = _projected_positioned_cell(
            "0.7" if mutation == "decimal_identifier_value" else "7",
            "0.7" if mutation == "decimal_identifier_value" else "7",
            0.0,
            70.0,
            0,
        )
        if mutation == "unprojected_identifier_value":
            value = value.model_copy(update={"diagnostics": ()})
        mutable_rows[3] = _bounded_continuation(*discount_row.cells[:-1], value)
    elif mutation == "financial_label":
        percentage_row = mutable_rows[1]
        mutable_rows[1] = _bounded_continuation(
            *percentage_row.cells[:-1],
            _projected_positioned_cell("fee", "fee", 0.0, 50.0, 0),
        )
    else:
        identifier_row = mutable_rows[4]
        second = identifier_row.cells[1].model_copy(
            update={"diagnostics": ("projected_header_band:4",)}
        )
        mutable_rows[4] = identifier_row.model_copy(
            update={"cells": (identifier_row.cells[0], second)}
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    details = extraction.details
    assert details is None or details.net_fee is None
    assert extraction.diagnostics


def test_compact_positioned_fx_layer_allows_proven_nonfinancial_annotation() -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    annotation = _bounded_continuation(
        _projected_positioned_cell(
            "general USD (note):",
            ":(note) USD general",
            100.0,
            70.0,
            3,
        )
    )
    rows = (base_row, *continuation_rows[:3], annotation)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_compact_positioned_fx_layer_infers_aligned_currencyless_gross_fee() -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    percentage_row = mutable_rows[1]
    mutable_rows[1] = _bounded_continuation(
        percentage_row.cells[0],
        _projected_positioned_cell(
            "note 0.89",
            "0.89 note",
            50.0,
            50.0,
            2,
        ),
    )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.89")
    assert extraction.details.gross_fee.currency == "ILS"
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_compact_positioned_fx_layer_accepts_matching_combined_component_word() -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    combined_row = mutable_rows[1]
    percentage, gross = combined_row.cells
    combined_word = Word(
        text="3.00% ILS 0.89",
        bbox=(gross.bbox[0], 50.0, percentage.bbox[2], 60.0),
        source="digital",
        confidence=1.0,
    )
    gross = gross.model_copy(update={"words": (*gross.words, combined_word)})
    mutable_rows[1] = combined_row.model_copy(update={"cells": (percentage, gross)})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_compact_positioned_fx_layer_ignores_nonnumeric_spanning_word() -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    combined_row = mutable_rows[1]
    percentage, gross = combined_row.cells
    annotation_word = Word(
        text="annotation",
        bbox=gross.bbox,
        source="digital",
        confidence=1.0,
    )
    gross = gross.model_copy(update={"words": (*gross.words, annotation_word)})
    mutable_rows[1] = combined_row.model_copy(update={"cells": (percentage, gross)})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "mutation",
    (
        "rate_arithmetic",
        "gross_arithmetic",
        "discount_exceeds_gross",
        "extra_rate_number",
        "nonadjacent_bands",
        "missing_discount_cue",
        "unlabeled_identifier_value",
        "conflicting_currency",
        "overlapping_component_evidence",
        "same_percentage_and_money_band",
        "rendering_mismatch",
    ),
)
def test_compact_positioned_fx_layer_requires_complete_exact_proof(mutation: str) -> None:
    base_row, continuation_rows = _compact_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    billed_amount = Decimal("29.72")
    if mutation == "rate_arithmetic":
        billed_amount = Decimal("50.00")
    elif mutation == "gross_arithmetic":
        percentage_row = mutable_rows[1]
        mutable_rows[1] = _bounded_continuation(
            percentage_row.cells[0],
            _projected_positioned_cell(
                "note ILS 1.50",
                "ILS 1.50 note",
                50.0,
                50.0,
                2,
            ),
        )
    elif mutation == "discount_exceeds_gross":
        mutable_rows[2] = _bounded_continuation(
            _projected_positioned_cell(
                "discount ILS 0.99",
                "ILS 0.99 discount",
                50.0,
                60.0,
                2,
            )
        )
    elif mutation == "extra_rate_number":
        mutable_rows[0] = _bounded_continuation(
            _projected_positioned_cell(
                "fx 7 2.9720",
                "2.9720 7 fx",
                100.0,
                40.0,
                3,
            )
        )
    elif mutation == "nonadjacent_bands":
        for index in (1, 2):
            row = mutable_rows[index]
            cells = tuple(
                cell.model_copy(update={"diagnostics": ("projected_header_band:1",)})
                if "projected_header_band:2" in cell.diagnostics
                else cell
                for cell in row.cells
            )
            mutable_rows[index] = row.model_copy(update={"cells": cells})
    elif mutation == "missing_discount_cue":
        mutable_rows[2] = _bounded_continuation(
            _projected_positioned_cell(
                "note ILS 0.20",
                "ILS 0.20 note",
                50.0,
                60.0,
                2,
            )
        )
    elif mutation == "unlabeled_identifier_value":
        mutable_rows.pop(3)
    elif mutation == "conflicting_currency":
        percentage_row = mutable_rows[1]
        mutable_rows[1] = _bounded_continuation(
            percentage_row.cells[0],
            _projected_positioned_cell(
                "note EUR 0.89",
                "EUR 0.89 note",
                50.0,
                50.0,
                2,
            ),
        )
    elif mutation == "overlapping_component_evidence":
        mutable_rows[2] = _shift_single_cell_row(mutable_rows[2], -5.0)
    elif mutation == "same_percentage_and_money_band":
        for index in (1, 2):
            row = mutable_rows[index]
            cells = tuple(
                cell.model_copy(update={"diagnostics": ("projected_header_band:3",)})
                for cell in row.cells
            )
            mutable_rows[index] = row.model_copy(update={"cells": cells})
    else:
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0].model_copy(update={"text": "fx 8.9720"})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=billed_amount,
    )

    details = extraction.details
    assert details is None or not all(
        value is not None
        for value in (
            details.exchange_rate,
            details.fee_percentage,
            details.gross_fee,
            details.fee_discount,
            details.net_fee,
        )
    )
    assert extraction.diagnostics


def test_split_positioned_rate_accepts_matching_full_span_digital_word() -> None:
    base_row, continuation_rows = _coherent_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    rate_row = mutable_rows[0]
    first = rate_row.cells[0]
    rate_start = len("exchange rate ")
    full_span = Word(
        text="2.9720",
        bbox=(first.bbox[0] + rate_start, 40.0, rate_row.cells[1].bbox[2], 50.0),
        source="digital",
        confidence=1.0,
    )
    first = first.model_copy(update={"words": (*first.words, full_span)})
    mutable_rows[0] = rate_row.model_copy(update={"cells": (first, *rate_row.cells[1:])})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_atomic_positioned_fx_block_accepts_one_exact_projected_band_per_component() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.89")
    assert extraction.details.fee_discount is not None
    assert extraction.details.fee_discount.amount == Decimal("0.20")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_atomic_positioned_fx_block_accepts_fee_band_aligned_with_rate_band() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    for index in (2, 3):
        row = mutable_rows[index]
        cell = row.cells[0].model_copy(update={"diagnostics": ("projected_header_band:2",)})
        mutable_rows[index] = row.model_copy(update={"cells": (cell,)})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "component",
    ("percentage_with_plain_decimal", "gross_with_percentage"),
)
def test_atomic_positioned_fx_block_rejects_unclaimed_row_numeric_evidence(
    component: str,
) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    if component == "percentage_with_plain_decimal":
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                "marker 7 3.00% foreign-currency fee",
                "foreign-currency fee marker 3.00% 7",
                50.0,
                50.0,
                3,
            )
        )
    else:
        mutable_rows[2] = _bounded_continuation(
            _projected_positioned_cell(
                "marker 5% fee amount ILS 0.89; discount follows",
                "ILS 0.89; marker fee amount discount follows 5%",
                50.0,
                60.0,
                3,
            )
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.exchange_rate is None
    assert extraction.diagnostics


def test_atomic_positioned_fx_block_rejects_vertical_gap_between_component_rows() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    rate_row, percentage_row, gross_row, discount_row = continuation_rows
    shifted_gross = _shift_single_cell_row(gross_row, 30.0)
    shifted_discount = _shift_single_cell_row(discount_row, 30.0)
    rows = (
        base_row,
        rate_row,
        percentage_row,
        shifted_gross,
        shifted_discount,
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize("precision", (2, 28))
def test_atomic_positioned_fx_arithmetic_is_independent_of_decimal_context(
    precision: int,
) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    rows = (base_row, *continuation_rows)

    with localcontext() as context:
        context.prec = precision
        extraction = extract_foreign_exchange(
            rows=rows,
            region=_region(base_row, fee_header="Auxiliary amount"),
            ledger=EvidenceLedger.from_rows(rows),
            original_currency="USD",
            billing_currency="ILS",
            original_amount=Decimal("10.00"),
            billed_amount=Decimal("31.23"),
        )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "mutation",
    (
        "rate_cue_low_confidence",
        "percentage_marker_low_confidence",
        "currency_low_confidence",
        "conflicting_rate_currency",
        "unsupported_rate_currency",
        "remote_extra_percentage",
        "extra_date_evidence",
    ),
)
def test_atomic_positioned_fx_block_requires_exact_semantic_source_evidence(
    mutation: str,
) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    if mutation in {
        "rate_cue_low_confidence",
        "percentage_marker_low_confidence",
        "currency_low_confidence",
    }:
        row_index = {
            "rate_cue_low_confidence": 0,
            "percentage_marker_low_confidence": 1,
            "currency_low_confidence": 2,
        }[mutation]
        row = mutable_rows[row_index]
        cell = row.cells[0]
        glyph_index = (
            next(index for index, glyph in enumerate(cell.glyphs) if glyph.char == "%")
            if mutation == "percentage_marker_low_confidence"
            else 0
        )
        glyphs = (
            *cell.glyphs[:glyph_index],
            cell.glyphs[glyph_index].model_copy(update={"confidence": 0.4}),
            *cell.glyphs[glyph_index + 1 :],
        )
        cell = cell.model_copy(update={"glyphs": glyphs})
        mutable_rows[row_index] = row.model_copy(update={"cells": (cell,)})
    elif mutation in {"conflicting_rate_currency", "unsupported_rate_currency"}:
        currency = "EUR" if mutation == "conflicting_rate_currency" else "JOD"
        mutable_rows[0] = _bounded_continuation(
            _projected_positioned_cell(
                f"marker {currency} 2.9720 exchange rate",
                f"exchange rate {currency} marker 2.9720",
                50.0,
                40.0,
                2,
            )
        )
    elif mutation == "remote_extra_percentage":
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                "marker % 3.00% foreign-currency fee",
                "foreign-currency fee % marker 3.00%",
                50.0,
                50.0,
                3,
            )
        )
    else:
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                "marker 12/07/2026 3.00% foreign-currency fee",
                "foreign-currency fee marker 3.00% 12/07/2026",
                50.0,
                50.0,
                3,
            )
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize("component", ("rate", "percentage", "discount"))
def test_atomic_positioned_fx_block_rejects_incompatible_component_cues(
    component: str,
) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    if component == "rate":
        mutable_rows[0] = _bounded_continuation(
            _projected_positioned_cell(
                "marker discount 2.9720 exchange rate",
                "exchange rate marker discount 2.9720",
                50.0,
                40.0,
                2,
            )
        )
    elif component == "percentage":
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                "marker discount 3.00% foreign-currency fee",
                "foreign-currency fee marker discount 3.00%",
                50.0,
                50.0,
                3,
            )
        )
    else:
        mutable_rows[3] = _bounded_continuation(
            _projected_positioned_cell(
                "marker gross fee discount ILS 0.20",
                "ILS 0.20 marker gross fee discount",
                50.0,
                70.0,
                3,
            )
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize("component", ("rate", "percentage", "discount"))
def test_split_positioned_fx_block_rejects_incompatible_component_cues(
    component: str,
) -> None:
    base_row, continuation_rows = _coherent_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    if component == "rate":
        left = _projected_positioned_cell(
            "20 exchange rate discount",
            "exchange rate discount 2.97",
            50.0,
            40.0,
            2,
            word_fragments=("2.", "97"),
        )
        right = _projected_positioned_cell(
            "2.97",
            "20",
            left.bbox[2] + 0.2,
            40.0,
            3,
            word_fragments=("20",),
        )
        mutable_rows[0] = _bounded_continuation(left, right)
    elif component == "percentage":
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                "discount 3.00% foreign-currency fee",
                "foreign-currency fee discount 3.00%",
                50.0,
                50.0,
                2,
                word_fragments=("3.", "00"),
            )
        )
    else:
        mutable_rows[3] = _bounded_continuation(
            _projected_positioned_cell(
                "reference gross fee discount ILS 0.20",
                "ILS 0.20 reference gross fee discount",
                50.0,
                70.0,
                3,
                word_fragments=("0.", "20"),
            )
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.exchange_rate is None
    assert extraction.diagnostics


@pytest.mark.parametrize("geometry", ("single", "split"))
@pytest.mark.parametrize(
    "mutation",
    (
        "source_confidence",
        "remote_numeric",
        "conflicting_currency",
        "unsupported_currency",
        "row_gap",
        "row_overlap",
        "page_jump",
        "rendering_mismatch",
        "arithmetic_mismatch",
    ),
)
def test_positioned_fx_atomic_rescue_invariant_matrix(
    geometry: str,
    mutation: str,
) -> None:
    base_row, continuation_rows = (
        _single_band_projected_fx_rows() if geometry == "single" else _coherent_projected_fx_rows()
    )
    mutable_rows = list(continuation_rows)
    billed_amount = Decimal("29.72")
    if mutation == "source_confidence":
        percentage_row = mutable_rows[1]
        percentage = percentage_row.cells[0]
        marker_index = next(
            index for index, glyph in enumerate(percentage.glyphs) if glyph.char == "%"
        )
        glyphs = (
            *percentage.glyphs[:marker_index],
            percentage.glyphs[marker_index].model_copy(update={"confidence": 0.4}),
            *percentage.glyphs[marker_index + 1 :],
        )
        percentage = percentage.model_copy(update={"glyphs": glyphs})
        mutable_rows[1] = percentage_row.model_copy(update={"cells": (percentage,)})
    elif mutation in {"remote_numeric", "conflicting_currency", "unsupported_currency"}:
        token = {
            "remote_numeric": "7",
            "conflicting_currency": "EUR",
            "unsupported_currency": "JOD",
        }[mutation]
        band = 3 if geometry == "single" else 2
        mutable_rows[1] = _bounded_continuation(
            _projected_positioned_cell(
                f"marker {token} 3.00% foreign-currency fee",
                f"foreign-currency fee marker 3.00% {token}",
                50.0,
                50.0,
                band,
            )
        )
    elif mutation == "row_gap":
        mutable_rows[2] = _shift_single_cell_row(mutable_rows[2], 30.0)
        mutable_rows[3] = _shift_single_cell_row(mutable_rows[3], 30.0)
    elif mutation == "row_overlap":
        mutable_rows[1] = _shift_single_cell_row(mutable_rows[1], -5.0)
    elif mutation == "page_jump":
        for index in (2, 3):
            row = mutable_rows[index]
            cell = row.cells[0].model_copy(update={"page_number": 2})
            mutable_rows[index] = row.model_copy(update={"page_number": 2, "cells": (cell,)})
    elif mutation == "rendering_mismatch":
        percentage_row = mutable_rows[1]
        percentage = percentage_row.cells[0].model_copy(
            update={"text": "marker 8.00% foreign-currency fee"}
        )
        mutable_rows[1] = percentage_row.model_copy(update={"cells": (percentage,)})
    else:
        billed_amount = Decimal("50.00")
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=billed_amount,
    )

    assert extraction.diagnostics


def test_atomic_positioned_fx_block_rejects_overlapping_component_rows() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    rate_row, percentage_row, gross_row, discount_row = continuation_rows
    rows = (
        base_row,
        rate_row,
        _shift_single_cell_row(percentage_row, -5.0),
        gross_row,
        discount_row,
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


def test_atomic_positioned_fx_block_allows_overlapping_logical_row_boxes() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    expanded_rows: list[Row] = []
    for row in continuation_rows:
        cell = row.cells[0]
        expanded_cell = cell.model_copy(
            update={"bbox": (cell.bbox[0], cell.bbox[1], cell.bbox[2], cell.bbox[3] + 2.0)}
        )
        expanded_rows.append(
            row.model_copy(
                update={
                    "bbox": (
                        row.bbox[0],
                        row.bbox[1],
                        row.bbox[2],
                        row.bbox[3] + 2.0,
                    ),
                    "cells": (expanded_cell,),
                }
            )
        )
    rows = (base_row, *expanded_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


def test_atomic_positioned_fx_block_rejects_percent_mode_competing_word() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    percentage_row = mutable_rows[1]
    percentage = percentage_row.cells[0]
    start = "foreign-currency fee marker 3.00%".index("3.00")
    competing = Word(
        text="9.00",
        bbox=(
            percentage.bbox[0] + start,
            50.0,
            percentage.bbox[0] + start + 4.0,
            60.0,
        ),
        source="digital",
        confidence=1.0,
    )
    percentage = percentage.model_copy(update={"words": (competing,)})
    mutable_rows[1] = percentage_row.model_copy(update={"cells": (percentage,)})
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


@pytest.mark.parametrize(
    "mutation",
    (
        "mismatching_full_span_word",
        "non_lossless_second_rendering",
        "nonadjacent_rate_band",
        "same_rate_and_fee_band",
        "gross_discount_band_mismatch",
        "third_fee_band",
        "nonunique_projected_band",
        "unprojected_component",
        "non_digital_backing",
        "extra_money_row",
        "repeated_sequence",
        "rate_arithmetic_mismatch",
        "gross_arithmetic_mismatch",
    ),
)
def test_atomic_positioned_fx_block_requires_complete_exact_proof(mutation: str) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    billed_amount = Decimal("29.72")
    if mutation == "mismatching_full_span_word":
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0]
        start = "exchange rate marker 2.9720".index("2.9720")
        competing = Word(
            text="9.9990",
            bbox=(rate.bbox[0] + start, 40.0, rate.bbox[0] + start + 6.0, 50.0),
            source="digital",
            confidence=1.0,
        )
        rate = rate.model_copy(update={"words": (*rate.words, competing)})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    elif mutation == "non_lossless_second_rendering":
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0].model_copy(update={"text": "marker 8.9720 exchange rate"})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    elif mutation == "nonadjacent_rate_band":
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0].model_copy(update={"diagnostics": ("projected_header_band:1",)})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    elif mutation == "same_rate_and_fee_band":
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0].model_copy(update={"diagnostics": ("projected_header_band:3",)})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    elif mutation == "gross_discount_band_mismatch":
        discount_row = mutable_rows[3]
        discount = discount_row.cells[0].model_copy(
            update={"diagnostics": ("projected_header_band:4",)}
        )
        mutable_rows[3] = discount_row.model_copy(update={"cells": (discount,)})
    elif mutation == "third_fee_band":
        for index in (2, 3):
            row = mutable_rows[index]
            cell = row.cells[0].model_copy(update={"diagnostics": ("projected_header_band:4",)})
            mutable_rows[index] = row.model_copy(update={"cells": (cell,)})
    elif mutation == "nonunique_projected_band":
        percentage_row = mutable_rows[1]
        percentage = percentage_row.cells[0].model_copy(
            update={
                "diagnostics": (
                    "projected_header_band:3",
                    "projected_header_band:4",
                )
            }
        )
        mutable_rows[1] = percentage_row.model_copy(update={"cells": (percentage,)})
    elif mutation == "unprojected_component":
        gross_row = mutable_rows[2]
        gross = gross_row.cells[0].model_copy(update={"diagnostics": ()})
        mutable_rows[2] = gross_row.model_copy(update={"cells": (gross,)})
    elif mutation == "non_digital_backing":
        rate_row = mutable_rows[0]
        rate = rate_row.cells[0]
        rate_start = "exchange rate marker 2.9720".index("2.9720")
        glyphs = (
            *rate.glyphs[:rate_start],
            rate.glyphs[rate_start].model_copy(update={"source": "ocr"}),
            *rate.glyphs[rate_start + 1 :],
        )
        rate = rate.model_copy(update={"glyphs": glyphs})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate,)})
    elif mutation == "extra_money_row":
        mutable_rows.append(
            _bounded_continuation(
                _projected_positioned_cell(
                    "marker ILS 0.10",
                    "ILS 0.10 marker",
                    50.0,
                    80.0,
                    3,
                )
            )
        )
    elif mutation == "repeated_sequence":
        mutable_rows.extend(continuation_rows)
    elif mutation == "rate_arithmetic_mismatch":
        billed_amount = Decimal("50.00")
    else:
        mutable_rows[2] = _bounded_continuation(
            _projected_positioned_cell(
                "marker fee amount ILS 0.20; discount follows",
                "ILS 0.20; marker fee amount discount follows",
                50.0,
                60.0,
                3,
            )
        )
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=billed_amount,
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


def test_atomic_positioned_fx_block_accepts_alpha_flanked_po_identifier_row() -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    identifier = _bounded_continuation(
        _projected_positioned_cell(
            "reference AB:CD12",
            "AB:CD12 reference",
            50.0,
            80.0,
            3,
        )
    )
    rows = (base_row, *continuation_rows, identifier)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9720")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.69")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    ("logical_text", "physical_text"),
    (
        ("reference AB1:2CD", "AB1:2CD reference"),
        ("reference :ABCD12", ":ABCD12 reference"),
        ("reference AB-CD12", "AB-CD12 reference"),
        ("label AB:CD12", "AB:CD12 label"),
        ("reference AB:CD12 1.20", "AB:CD12 1.20 reference"),
        ("reference AB:CD12 12/07/2026", "AB:CD12 12/07/2026 reference"),
        ("reference AB:CD12 1/3", "AB:CD12 1/3 reference"),
        ("reference AB:CD13", "AB:CD12 reference"),
    ),
)
def test_atomic_positioned_fx_block_rejects_unproven_punctuated_identifier_row(
    logical_text: str,
    physical_text: str,
) -> None:
    base_row, continuation_rows = _single_band_projected_fx_rows()
    identifier = _bounded_continuation(
        _projected_positioned_cell(
            logical_text,
            physical_text,
            50.0,
            80.0,
            3,
        )
    )
    rows = (base_row, *continuation_rows, identifier)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


def test_conflicting_positioned_fx_layer_requires_cross_field_arithmetic() -> None:
    base_row, continuation_rows = _coherent_projected_fx_rows()
    rows = (base_row, *continuation_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("50.00"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert "unparsed_exchange_rate_candidate" in extraction.diagnostics
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


@pytest.mark.parametrize(
    "mutation",
    (
        "different_character_multiset",
        "nonadjacent_rate_bands",
        "vertically_displaced_rate_fragments",
        "missing_word_coverage",
        "full_span_competing_word",
        "low_confidence_rate_cue",
        "remote_rate_percentage",
        "unprojected_component",
        "extra_money_row",
        "extra_percentage_row",
        "repeated_sequence",
    ),
)
def test_positioned_fx_layer_requires_lossless_complete_geometry(mutation: str) -> None:
    base_row, continuation_rows = _coherent_projected_fx_rows()
    mutable_rows = list(continuation_rows)
    if mutation == "different_character_multiset":
        rate_row = mutable_rows[0]
        first = rate_row.cells[0].model_copy(update={"text": "99 exchange rate"})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (first, *rate_row.cells[1:])})
    elif mutation == "nonadjacent_rate_bands":
        rate_row = mutable_rows[0]
        second = rate_row.cells[1].model_copy(update={"diagnostics": ("projected_header_band:4",)})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (rate_row.cells[0], second)})
    elif mutation == "vertically_displaced_rate_fragments":
        rate_row = mutable_rows[0]
        second = rate_row.cells[1]
        shifted = second.model_copy(
            update={
                "bbox": (
                    second.bbox[0],
                    second.bbox[1] + 4.0,
                    second.bbox[2],
                    second.bbox[3] + 4.0,
                ),
                "glyphs": tuple(
                    glyph.model_copy(
                        update={
                            "bbox": (
                                glyph.bbox[0],
                                glyph.bbox[1] + 4.0,
                                glyph.bbox[2],
                                glyph.bbox[3] + 4.0,
                            ),
                            "origin": (glyph.origin[0], glyph.origin[1] + 4.0),
                        }
                    )
                    for glyph in second.glyphs
                ),
                "words": tuple(
                    word.model_copy(
                        update={
                            "bbox": (
                                word.bbox[0],
                                word.bbox[1] + 4.0,
                                word.bbox[2],
                                word.bbox[3] + 4.0,
                            )
                        }
                    )
                    for word in second.words
                ),
            }
        )
        mutable_rows[0] = _bounded_continuation(rate_row.cells[0], shifted)
    elif mutation == "missing_word_coverage":
        rate_row = mutable_rows[0]
        first = rate_row.cells[0].model_copy(update={"words": rate_row.cells[0].words[:1]})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (first, *rate_row.cells[1:])})
    elif mutation == "full_span_competing_word":
        rate_row = mutable_rows[0]
        first = rate_row.cells[0]
        rate_start = len("exchange rate ")
        competing = Word(
            text="9.9990",
            bbox=(first.bbox[0] + rate_start, 40.0, rate_row.cells[1].bbox[2], 50.0),
            source="digital",
            confidence=1.0,
        )
        first = first.model_copy(update={"words": (*first.words, competing)})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (first, *rate_row.cells[1:])})
    elif mutation == "low_confidence_rate_cue":
        rate_row = mutable_rows[0]
        first = rate_row.cells[0]
        glyphs = (
            first.glyphs[0].model_copy(update={"confidence": 0.4}),
            *first.glyphs[1:],
        )
        first = first.model_copy(update={"glyphs": glyphs})
        mutable_rows[0] = rate_row.model_copy(update={"cells": (first, *rate_row.cells[1:])})
    elif mutation == "remote_rate_percentage":
        rate_row = mutable_rows[0]
        remote = _projected_positioned_cell("%", "%", 200.0, 40.0, 3)
        mutable_rows[0] = _bounded_continuation(*rate_row.cells, remote)
    elif mutation == "unprojected_component":
        gross_row = mutable_rows[2]
        gross = gross_row.cells[0].model_copy(update={"diagnostics": ()})
        mutable_rows[2] = gross_row.model_copy(update={"cells": (gross,)})
    elif mutation == "extra_money_row":
        mutable_rows.append(
            _bounded_continuation(
                _projected_positioned_cell(
                    "ILS 0.10",
                    "ILS 0.10",
                    50.0,
                    90.0,
                    3,
                    word_fragments=("0.", "10"),
                )
            )
        )
    elif mutation == "extra_percentage_row":
        mutable_rows.append(
            _bounded_continuation(
                _projected_positioned_cell(
                    "0.10%",
                    "0.10%",
                    50.0,
                    90.0,
                    3,
                    word_fragments=("0.", "10"),
                )
            )
        )
    else:
        mutable_rows.extend(continuation_rows[:4])
    rows = (base_row, *mutable_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        billed_amount=Decimal("29.72"),
    )

    assert extraction.details is None or extraction.details.net_fee is None
    assert extraction.diagnostics


def test_pending_gross_with_reduced_fee_cue_records_direct_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    net_fee_cell = _positioned_cell(
        "עמלה מופחתת ILS 0.29",
        "עמלה מופחתת ILS 0.29",
        50.0,
        50.0,
    )
    net_fee_row = _bounded_continuation(net_fee_cell)
    trailing_note = _bounded_continuation(
        _positioned_cell("arrangement terms apply", "arrangement terms apply", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, net_fee_row, trailing_note)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.fee_percentage is not None
    assert details.fee_percentage.value == Decimal("3.00")
    assert details.gross_fee is None
    assert details.fee_discount is None
    assert details.net_fee is not None
    assert details.net_fee.amount == Decimal("0.29")
    assert details.net_fee.currency == "ILS"
    assert details.net_fee.evidence == (
        EvidenceReference(page_number=1, bbox=net_fee_cell.bbox, raw_text=net_fee_cell.text),
    )
    net_fee_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(net_fee_cell))
        if candidate.text == "0.29"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, net_fee_atom_ids),)
    assert all(
        claim.owner not in {SemanticOwner.GROSS_FX_FEE, SemanticOwner.FX_FEE_DISCOUNT}
        for claim in extraction.claims
    )
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ()


def test_pending_gross_with_english_reduced_fee_cue_records_direct_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    net_fee_cell = _positioned_cell(
        "reduced fee ILS 0.29",
        "reduced fee ILS 0.29",
        50.0,
        50.0,
    )
    rows = (base_row, percentage_row, _bounded_continuation(net_fee_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.details.net_fee.currency == "ILS"
    assert extraction.diagnostics == ()


@pytest.mark.parametrize(
    "sign",
    ("-", "+", "\N{MINUS SIGN}", "\N{EN DASH}", "\N{EM DASH}"),
)
def test_signed_fee_percentage_remains_unparsed(sign: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            f"foreign-currency fee {sign}3.00%",
            f"{sign}3.00%",
            50.0,
            40.0,
        )
    )
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


@pytest.mark.parametrize(
    "sign",
    ("-", "+", "\N{MINUS SIGN}", "\N{EN DASH}", "\N{EM DASH}"),
)
def test_sign_after_fee_percentage_remains_unparsed(sign: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            f"foreign-currency fee 3.00%{sign}",
            f"3.00%{sign}",
            50.0,
            40.0,
        )
    )
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_other_line_atom_does_not_hide_percentage_sign_wrapper() -> None:
    base_row = _base_row_without_fx_values()
    percentage_glyphs = _glyphs("3.00%-", 50.0, 40.0)
    unrelated_line_glyph = _glyphs("x", 54.5, 52.0)[0]
    percentage_cell = Cell(
        page_number=1,
        bbox=(50.0, 40.0, 56.0, 62.0),
        text="foreign-currency fee 3.00%-",
        glyphs=(*percentage_glyphs, unrelated_line_glyph),
        confidence=1.0,
    )
    percentage_row = _bounded_continuation(percentage_cell)
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_explicit_rate_row_does_not_satisfy_pending_gross_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    rate_row = _bounded_continuation(
        _positioned_cell("exchange rate ILS 2.9430", "ILS 2.9430", 50.0, 50.0)
    )
    rows = (base_row, percentage_row, rate_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9430")
    assert extraction.details.gross_fee is None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.GROSS_FX_FEE for claim in extraction.claims)
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ()


def test_explicit_rate_row_does_not_satisfy_pending_fee_discount() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    gross_row = _bounded_continuation(
        _positioned_cell(
            "fee amount ILS 0.88; discount follows",
            "ILS 0.88",
            50.0,
            50.0,
        )
    )
    rate_row = _bounded_continuation(
        _positioned_cell("exchange rate ILS 2.9430", "ILS 2.9430", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, gross_row, rate_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9430")
    assert extraction.details.fee_discount is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_DISCOUNT for claim in extraction.claims)
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_discount_candidate",)


@pytest.mark.parametrize(
    ("text", "fee_diagnostic"),
    (
        (
            "fee amount calculated at exchange rate ILS 2.9430",
            "unparsed_foreign_currency_fee_candidate",
        ),
        (
            "exchange rate discount ILS 2.9430",
            "unparsed_foreign_currency_fee_discount_candidate",
        ),
    ),
)
def test_colliding_rate_and_fee_cues_remain_ambiguous(
    text: str,
    fee_diagnostic: str,
) -> None:
    base_row = _base_row_without_fx_values()
    collision_row = _bounded_continuation(_positioned_cell(text, "ILS 2.9430", 50.0, 40.0))
    rows = (base_row, collision_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert "unparsed_exchange_rate_candidate" in extraction.diagnostics
    assert fee_diagnostic in extraction.diagnostics


@pytest.mark.parametrize(
    "rate_text",
    ("exchange rate -2.111 2.9430", "exchange rate 1 and 2.9430"),
)
def test_invalid_or_integer_continuation_rate_competes_with_valid_decimal(
    rate_text: str,
) -> None:
    base_row = _base_row_without_fx_values()
    rate_row = _bounded_continuation(_positioned_cell(rate_text, rate_text, 50.0, 40.0))
    rows = (base_row, rate_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_exchange_rate_candidate",)


@pytest.mark.parametrize(
    "percentage_text",
    (
        "foreign-currency fee 3.00% 2.50%",
        "foreign-currency fee -3.00% and 2.50%",
    ),
)
def test_multiple_typed_percentages_remain_ambiguous(percentage_text: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(percentage_text, percentage_text, 50.0, 40.0)
    )
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_word_backed_percentage_preserves_percent_binding() -> None:
    base_row = _base_row_without_fx_values()
    percentage_text = "foreign-currency fee 3.00%"
    words = (
        Word(
            text="foreign-currency",
            bbox=(50.0, 40.0, 65.0, 50.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="fee",
            bbox=(66.0, 40.0, 69.0, 50.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="3.00%",
            bbox=(70.0, 40.0, 76.0, 50.0),
            source="digital",
            confidence=1.0,
        ),
    )
    percentage_cell = Cell(
        page_number=1,
        bbox=(50.0, 40.0, 76.0, 50.0),
        text=percentage_text,
        words=words,
        confidence=1.0,
    )
    rows = (base_row, _bounded_continuation(percentage_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.diagnostics == ()


@pytest.mark.parametrize("backing", ("glyph", "word"))
def test_whole_number_percentage_claim_owns_number_and_marker(backing: str) -> None:
    base_row = _base_row_without_fx_values()
    if backing == "glyph":
        percentage_cell = _positioned_cell("foreign-currency fee 7%", "7%", 50.0, 40.0)
    else:
        percentage_cell = Cell(
            page_number=1,
            bbox=(50.0, 40.0, 78.0, 50.0),
            text="foreign-currency fee 7%",
            words=(
                Word(
                    text="foreign-currency",
                    bbox=(50.0, 40.0, 65.0, 50.0),
                    source="digital",
                    confidence=1.0,
                ),
                Word(
                    text="fee",
                    bbox=(66.0, 40.0, 69.0, 50.0),
                    source="digital",
                    confidence=1.0,
                ),
                Word(
                    text="7%",
                    bbox=(70.0, 40.0, 72.0, 50.0),
                    source="digital",
                    confidence=1.0,
                ),
            ),
            confidence=1.0,
        )
    rows = (base_row, _bounded_continuation(percentage_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("7")
    percentage_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    )
    percentage_atom_ids = ledger.atoms_for_cell(percentage_cell)
    marker_atom_ids = frozenset(
        atom_id for atom_id in percentage_atom_ids if "%" in ledger.atoms[atom_id].text
    )
    numeric_atom_ids = frozenset(
        atom_id
        for atom_id in percentage_atom_ids
        if any(char.isdigit() for char in ledger.atoms[atom_id].text)
    )
    assert marker_atom_ids
    assert numeric_atom_ids
    assert marker_atom_ids | numeric_atom_ids <= percentage_claim.atom_ids
    assert extraction.diagnostics == ()


def test_equivalent_glyph_and_word_percent_backing_counts_once() -> None:
    base_row = _base_row_without_fx_values()
    glyph_cell = _positioned_cell(
        "foreign-currency fee 3.00%",
        "3.00%",
        50.0,
        40.0,
    )
    word_cell = Cell(
        page_number=1,
        bbox=glyph_cell.bbox,
        text="3.00%",
        words=(
            Word(
                text="3.00%",
                bbox=glyph_cell.bbox,
                source="digital",
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )
    percentage_row = _bounded_continuation(glyph_cell, word_cell)
    rows = (base_row, percentage_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    percentage_claim = next(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    )
    assert any(ledger.atoms[atom_id].glyph is not None for atom_id in percentage_claim.atom_ids)
    assert any(ledger.atoms[atom_id].word is not None for atom_id in percentage_claim.atom_ids)
    assert extraction.diagnostics == ()


def test_word_backed_combined_currency_amount_preserves_money_ownership() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    words = (
        Word(
            text="reduced",
            bbox=(50.0, 50.0, 57.0, 60.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="fee",
            bbox=(58.0, 50.0, 61.0, 60.0),
            source="digital",
            confidence=1.0,
        ),
        Word(
            text="ILS0.29",
            bbox=(62.0, 50.0, 70.0, 60.0),
            source="digital",
            confidence=1.0,
        ),
    )
    reduced_cell = Cell(
        page_number=1,
        bbox=(50.0, 50.0, 70.0, 60.0),
        text="reduced fee ILS0.29",
        words=words,
        confidence=1.0,
    )
    rows = (base_row, percentage_row, _bounded_continuation(reduced_cell))
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    money_atom_id = next(atom.atom_id for atom in ledger.atoms if atom.text == "ILS0.29")
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.NET_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.NET_FX_FEE, frozenset((money_atom_id,))),)
    assert extraction.diagnostics == ()


def test_material_glyph_gaps_preserve_money_context_boundaries() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    parts = ("fee", "amount", "ILS", "0.88")
    cursor = 50.0
    glyph_runs: list[Glyph] = []
    for part in parts:
        glyph_runs.extend(_glyphs(part, cursor, 50.0))
        cursor += len(part) + 5.0
    gross_cell = Cell(
        page_number=1,
        bbox=(50.0, 50.0, cursor, 60.0),
        text="fee amount ILS 0.88",
        glyphs=tuple(glyph_runs),
        confidence=1.0,
    )
    rows = (base_row, percentage_row, _bounded_continuation(gross_cell))

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.88")
    assert extraction.diagnostics == ()


def test_later_integer_money_evidence_blocks_direct_reduced_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 50.0)
    )
    integer_followup = _bounded_continuation(_positioned_cell("ILS 1", "ILS 1", 50.0, 60.0))
    rows = (base_row, percentage_row, reduced_row, integer_followup)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


def test_later_word_integer_money_evidence_blocks_direct_reduced_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "ILS 0.29", 50.0, 50.0)
    )
    integer_cell = Cell(
        page_number=1,
        bbox=(50.0, 60.0, 60.0, 70.0),
        text="ILS 1",
        words=(
            Word(
                text="ILS",
                bbox=(50.0, 60.0, 54.0, 70.0),
                source="digital",
                confidence=1.0,
            ),
            Word(
                text="1",
                bbox=(55.0, 60.0, 56.0, 70.0),
                source="digital",
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )
    integer_followup = _bounded_continuation(integer_cell)
    rows = (base_row, percentage_row, reduced_row, integer_followup)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert "unparsed_foreign_currency_fee_candidate" in extraction.diagnostics


def test_accepted_conversion_date_does_not_block_direct_reduced_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "ILS 0.29", 50.0, 50.0)
    )
    conversion_cell = _positioned_cell(
        "converted to ILS 25/06/26",
        "25/06/26",
        50.0,
        60.0,
    )
    conversion_row = _bounded_continuation(conversion_cell)
    rows = (base_row, percentage_row, reduced_row, conversion_row)
    ledger = EvidenceLedger.from_rows(rows)
    conversion_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.fragmented_date_candidates(conversion_cell)
        if candidate.text == "25/06/26"
    )

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
        excluded_atom_ids=conversion_atom_ids,
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ()


def test_explicit_later_rate_does_not_block_direct_reduced_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "ILS 0.29", 50.0, 50.0)
    )
    rate_row = _bounded_continuation(
        _positioned_cell("exchange rate ILS 2.9430", "ILS 2.9430", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, reduced_row, rate_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.exchange_rate is not None
    assert extraction.details.exchange_rate.value == Decimal("2.9430")
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ()


def test_unrelated_later_integer_does_not_block_direct_reduced_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    reduced_row = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 50.0)
    )
    unrelated_reference = _bounded_continuation(
        _positioned_cell("arrangement reference 1", "arrangement reference 1", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, reduced_row, unrelated_reference)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is not None
    assert extraction.details.net_fee.amount == Decimal("0.29")
    assert extraction.diagnostics == ()


def test_discount_announcement_without_followup_does_not_become_direct_net_fee() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    announced_discount_row = _bounded_continuation(
        _positioned_cell(
            "ILS 0.88; from this fee a discount is subtracted",
            "ILS 0.88; from this fee a discount is subtracted",
            50.0,
            50.0,
        )
    )
    rows = (base_row, percentage_row, announced_discount_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.88")
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_discount_candidate",)


def test_reduced_pending_amount_preserves_later_ambiguous_discount_evidence() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    gross_cell = _positioned_cell(
        "עמלה מופחתת ILS 0.29",
        "עמלה מופחתת ILS 0.29",
        50.0,
        50.0,
    )
    gross_row = _bounded_continuation(gross_cell)
    ambiguous_discount_row = _bounded_continuation(
        _positioned_cell(
            "ILS 0.10 and 0.05",
            "ILS 0.10 and 0.05",
            50.0,
            60.0,
        )
    )
    rows = (base_row, percentage_row, gross_row, ambiguous_discount_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.gross_fee is None
    assert details.fee_discount is None
    assert details.net_fee is None
    assert all(
        claim.owner
        not in {
            SemanticOwner.GROSS_FX_FEE,
            SemanticOwner.FX_FEE_DISCOUNT,
            SemanticOwner.NET_FX_FEE,
        }
        for claim in extraction.claims
    )
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_repeated_reduced_results_remain_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    first_reduced = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "reduced fee ILS 0.29", 50.0, 50.0)
    )
    second_reduced = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.10", "reduced fee ILS 0.10", 50.0, 60.0)
    )
    rows = (base_row, percentage_row, first_reduced, second_reduced)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is None
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is None
    assert all(
        claim.owner
        not in {
            SemanticOwner.GROSS_FX_FEE,
            SemanticOwner.FX_FEE_DISCOUNT,
            SemanticOwner.NET_FX_FEE,
        }
        for claim in extraction.claims
    )
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


@pytest.mark.parametrize(
    "later_text",
    (
        "reduced fee ILS unreadable",
        "reduced fee ILS",
        "reduced fee USD 0.10",
        "reduced fee 0.10",
    ),
)
def test_later_reduced_result_source_invalidates_direct_net_fee(later_text: str) -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    first_reduced = _bounded_continuation(
        _positioned_cell("reduced fee ILS 0.29", "ILS 0.29", 50.0, 50.0)
    )
    later_reduced = _bounded_continuation(_positioned_cell(later_text, later_text, 50.0, 60.0))
    rows = (base_row, percentage_row, first_reduced, later_reduced)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_unreadable_reduced_result_source_remains_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    unreadable_reduced = _bounded_continuation(
        _positioned_cell(
            "reduced fee ILS unreadable",
            "reduced fee ILS unreadable",
            50.0,
            50.0,
        )
    )
    rows = (base_row, percentage_row, unreadable_reduced)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.net_fee is None
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_explicit_zero_pending_gross_fee_is_evidenced_without_ambiguity() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, 40.0)
    )
    gross_cell = _positioned_cell("ILS 0.00", "ILS 0.00", 50.0, 50.0)
    gross_row = _bounded_continuation(gross_cell)
    rows = (base_row, percentage_row, gross_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("0.00")
    assert extraction.details.gross_fee.currency == "ILS"
    assert extraction.details.gross_fee.evidence == (
        EvidenceReference(page_number=1, bbox=gross_cell.bbox, raw_text=gross_cell.text),
    )
    assert extraction.details.fee_discount is None
    assert extraction.details.net_fee is None
    zero_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(gross_cell))
        if candidate.text == "0.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.GROSS_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.GROSS_FX_FEE, zero_atom_ids),)
    assert extraction.diagnostics == ()


def test_pending_gross_does_not_consume_percent_bound_decimal() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00% ILS",
            "foreign-currency fee 3.00% ILS",
            50.0,
            40.0,
        )
    )
    percent_only_money_row = _bounded_continuation(
        _positioned_cell("ILS 0.00%", "ILS 0.00%", 50.0, 50.0)
    )
    rows = (base_row, percentage_row, percent_only_money_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert extraction.claims == ()
    assert all(claim.owner is not SemanticOwner.GROSS_FX_FEE for claim in extraction.claims)
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_pending_gross_uses_separate_unique_non_percentage_money_decimal() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00% ILS",
            "foreign-currency fee 3.00% ILS",
            50.0,
            40.0,
        )
    )
    gross_cell = _positioned_cell(
        "ILS 0.00% amount 1.25",
        "ILS 0.00% amount 1.25",
        50.0,
        50.0,
    )
    gross_row = _bounded_continuation(gross_cell)
    rows = (base_row, percentage_row, gross_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is None
    assert extraction.details.gross_fee is not None
    assert extraction.details.gross_fee.amount == Decimal("1.25")
    money_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(gross_cell))
        if candidate.text == "1.25"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.GROSS_FX_FEE
    ) == (EvidenceClaim(SemanticOwner.GROSS_FX_FEE, money_atom_ids),)
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_explicit_zero_continuation_discount_is_evidenced_and_net_is_derived() -> None:
    base_row = _base_row_without_fx_values()
    continuation_rows = _continuation_rows(discount="0.00")
    rows = (base_row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    details = extraction.details
    assert details.gross_fee is not None
    assert details.gross_fee.amount == Decimal("0.88")
    assert details.fee_discount is not None
    assert details.fee_discount.amount == Decimal("0.00")
    assert details.fee_discount.currency == "ILS"
    assert details.net_fee is not None
    assert details.net_fee.amount == Decimal("0.88")
    assert details.net_fee.currency == "ILS"
    assert details.net_fee.derivation == "gross_fee_minus_discount"
    assert details.net_fee.evidence == tuple(
        dict.fromkeys((*details.gross_fee.evidence, *details.fee_discount.evidence))
    )
    discount_cell = continuation_rows[-1].cells[0]
    zero_atom_ids = next(
        candidate.atom_ids
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(discount_cell))
        if candidate.text == "0.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_DISCOUNT
    ) == (EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, zero_atom_ids),)
    assert all(claim.owner is not SemanticOwner.NET_FX_FEE for claim in extraction.claims)
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
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("0.00")
    assert extraction.diagnostics == ()


def test_percentage_selects_percent_bound_decimal_when_money_is_on_same_row() -> None:
    base_row = _base_row_without_fx_values()
    percentage_cell = _positioned_cell(
        "foreign-currency fee 3.00% ILS 0.88",
        "foreign-currency fee 3.00% ILS 0.88",
        50.0,
        40.0,
    )
    percentage_row = _bounded_continuation(percentage_cell)
    rows = (base_row, percentage_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.details.fee_percentage.evidence == (
        EvidenceReference(
            page_number=1,
            bbox=percentage_cell.bbox,
            raw_text=percentage_cell.text,
        ),
    )
    percentage_atom_ids = next(
        candidate.semantic_atom_ids
        for candidate in ledger.positioned_percentage_candidates(
            ledger.atoms_for_cell(percentage_cell)
        )
        if candidate.text == "3.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    ) == (EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, percentage_atom_ids),)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_percentage_binding_is_safe_for_percent_before_decimal() -> None:
    base_row = _base_row_without_fx_values()
    percentage_cell = _positioned_cell(
        "foreign-currency fee %3.00 ILS 0.88",
        "foreign-currency fee %3.00 ILS 0.88",
        50.0,
        40.0,
    )
    percentage_row = _bounded_continuation(percentage_cell)
    rows = (base_row, percentage_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    percentage_atom_ids = next(
        candidate.semantic_atom_ids
        for candidate in ledger.positioned_percentage_candidates(
            ledger.atoms_for_cell(percentage_cell)
        )
        if candidate.text == "3.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    ) == (EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, percentage_atom_ids),)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_candidate",)


def test_percentage_ignores_additional_unbound_percent_marker() -> None:
    base_row = _base_row_without_fx_values()
    percentage_cell = _positioned_cell(
        "foreign-currency fee 3.00% note %",
        "foreign-currency fee 3.00% note %",
        50.0,
        40.0,
    )
    percentage_row = _bounded_continuation(percentage_cell)
    rows = (base_row, percentage_row)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    percentage_atom_ids = next(
        candidate.semantic_atom_ids
        for candidate in ledger.positioned_percentage_candidates(
            ledger.atoms_for_cell(percentage_cell)
        )
        if candidate.text == "3.00"
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    ) == (EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, percentage_atom_ids),)
    assert extraction.diagnostics == ()


def test_two_percent_bound_decimals_remain_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    percentage_row = _bounded_continuation(
        _positioned_cell(
            "foreign-currency fee 3.00% and 2.50%",
            "foreign-currency fee 3.00% and 2.50%",
            50.0,
            40.0,
        )
    )
    rows = (base_row, percentage_row)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


def test_repeated_identical_percentages_merge_provenance() -> None:
    base_row = _base_row_without_fx_values()
    percentage_cells = tuple(
        _positioned_cell("foreign-currency fee 3.00%", "3.00%", 50.0, y) for y in (40.0, 50.0)
    )
    percentage_rows = tuple(_bounded_continuation(cell) for cell in percentage_cells)
    rows = (base_row, *percentage_rows)
    ledger = EvidenceLedger.from_rows(rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=ledger,
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is not None
    assert extraction.details.fee_percentage is not None
    assert extraction.details.fee_percentage.value == Decimal("3.00")
    assert extraction.details.fee_percentage.evidence == tuple(
        EvidenceReference(page_number=1, bbox=cell.bbox, raw_text=cell.text)
        for cell in percentage_cells
    )
    percentage_atom_ids = frozenset().union(
        *(
            next(
                candidate.semantic_atom_ids
                for candidate in ledger.positioned_percentage_candidates(
                    ledger.atoms_for_cell(cell)
                )
                if candidate.text == "3.00"
            )
            for cell in percentage_cells
        )
    )
    assert tuple(
        claim for claim in extraction.claims if claim.owner is SemanticOwner.FX_FEE_PERCENTAGE
    ) == (EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, percentage_atom_ids),)
    assert ledger.validate_claims(extraction.claims).diagnostics == ()
    assert extraction.diagnostics == ()


def test_conflicting_repeated_percentages_remain_ambiguous() -> None:
    base_row = _base_row_without_fx_values()
    percentage_rows = tuple(
        _bounded_continuation(
            _positioned_cell(f"foreign-currency fee {value}%", f"{value}%", 50.0, y)
        )
        for value, y in (("3.00", 40.0), ("2.50", 50.0))
    )
    rows = (base_row, *percentage_rows)

    extraction = extract_foreign_exchange(
        rows=rows,
        region=_region(base_row, fee_header="Auxiliary amount"),
        ledger=EvidenceLedger.from_rows(rows),
        original_currency="USD",
        billing_currency="ILS",
    )

    assert extraction.details is None
    assert all(claim.owner is not SemanticOwner.FX_FEE_PERCENTAGE for claim in extraction.claims)
    assert extraction.diagnostics == ("unparsed_foreign_currency_fee_percentage_candidate",)


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
    )

    assert extraction.details is not None
    assert extraction.details.gross_fee is not None
    assert extraction.details.fee_discount is not None
    assert extraction.details.net_fee is None
    assert extraction.diagnostics == ("inconsistent_foreign_currency_fee_derivation",)
