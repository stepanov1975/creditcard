from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, fields
from datetime import date

import pytest

from ccparser.discovery import DiscoveredDateYearContext
from ccparser.evidence import Glyph, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.normalization_semantics import (
    SemanticValidation,
    _stable_unknown_columns,
    assignment_diagnostics,
    role_contract_diagnostics,
    validate_transaction_semantics,
)
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner


def _word(text: str, x0: float, x1: float, y: float = 30.0) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="digital",
        confidence=1.0,
    )


def _glyph(char: str, x0: float, y: float = 30.0) -> Glyph:
    return Glyph(
        char=char,
        bbox=(x0, y, x0 + 0.8, y + 10.0),
        origin=(x0, y + 9.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=1.0,
    )


def _cell(
    text: str,
    column: int,
    *,
    y: float = 30.0,
    confidence: float = 1.0,
    bbox: tuple[float, float, float, float] | None = None,
    words: tuple[Word, ...] = (),
    glyphs: tuple[Glyph, ...] = (),
) -> Cell:
    return Cell(
        page_number=1,
        bbox=bbox or (column * 50.0, y, column * 50.0 + 40.0, y + 10.0),
        text=text,
        words=words,
        glyphs=glyphs,
        confidence=confidence,
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
    column_diagnostics: Mapping[int, tuple[str, ...]] | None = None,
) -> TableRegion:
    header_texts = headers or tuple(role.value for role in roles)
    header_cells = tuple(_cell(text, index, y=10.0) for index, text in enumerate(header_texts))
    diagnostics = column_diagnostics or {}
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
            diagnostics=diagnostics.get(index, ()),
        )
        for index, role in enumerate(roles)
    )
    header = _row(*header_cells)
    schema = TableSchema(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, 200.0),
        columns=columns,
        header_cells=header_cells,
        sample_cells=tuple(cell for row in rows for cell in row.cells),
        confidence=1.0,
    )
    return TableRegion(
        page_number=1,
        bbox=(0.0, 10.0, len(roles) * 50.0 - 10.0, max(row.bbox[3] for row in rows)),
        header=header,
        rows=rows,
        table_schema=schema,
        confidence=1.0,
    )


def _validate(
    *,
    rows: Sequence[Row],
    region: TableRegion,
    ledger: EvidenceLedger,
    amount_cell: Cell,
    initial_claims: Sequence[EvidenceClaim] = (),
    billing_currency: str = "ILS",
    original_currency: str | None = None,
    description: str | None = None,
    transaction_date: date | None = None,
    posting_date: date | None = None,
    conversion_date: date | None = None,
    year_context: DiscoveredDateYearContext | None = None,
    date_column_kinds: Mapping[int, str] | None = None,
) -> SemanticValidation:
    return validate_transaction_semantics(
        rows=rows,
        region=region,
        ledger=ledger,
        initial_claims=initial_claims,
        amount_cell=amount_cell,
        billing_currency=billing_currency,
        original_currency=original_currency,
        description=description,
        transaction_date=transaction_date,
        posting_date=posting_date,
        conversion_date=conversion_date,
        year_context=year_context,
        date_column_kinds=date_column_kinds or {},
    )


def test_semantic_validation_is_frozen_slotted_value() -> None:
    validation = SemanticValidation(claims=(), diagnostics=())

    assert tuple(field.name for field in fields(validation)) == ("claims", "diagnostics")
    assert SemanticValidation.__slots__ == ("claims", "diagnostics")
    with pytest.raises(FrozenInstanceError):
        validation.diagnostics = ("changed",)


def test_semantic_validation_claims_every_owner_in_exact_atom_and_claim_order() -> None:
    description = _cell(
        "Merchant 2026",
        2,
        words=(_word("Merchant", 102.0, 120.0), _word("2026", 125.0, 135.0)),
    )
    cells = (
        _cell("01/02/2026", 0),
        _cell("03/02/2026", 1),
        description,
        _cell("London", 3),
        _cell("2/6", 4),
        _cell("USD 3.00", 5),
        _cell("02/02/2026", 6),
        _cell("Memo", 7),
        _cell("Refund", 8),
        _cell("ILS 10.00", 9),
        _cell("Processor", 10),
        _cell("Rate", 11),
        _cell("Percent", 12),
        _cell("Gross", 13),
        _cell("Discount", 14),
        _cell("Net", 15),
    )
    row = _row(*cells)
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.INSTALLMENT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AUXILIARY_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
            *(ColumnRole.AUXILIARY_AMOUNT for _ in range(6)),
        ),
        (row,),
        headers=(
            "Transaction date",
            "Posting date",
            "Description",
            "Location",
            "Installment",
            "Original amount",
            "Conversion date",
            "Note",
            "Category",
            "Billed amount",
            "Processor",
            "Rate",
            "Fee percentage",
            "Gross fee",
            "Discount",
            "Net fee",
        ),
    )
    ledger = EvidenceLedger.from_rows((row,))
    assert tuple(atom.text for atom in ledger.atoms) == (
        "01/02/2026",
        "03/02/2026",
        "Merchant",
        "2026",
        "London",
        "2/6",
        "USD 3.00",
        "02/02/2026",
        "Memo",
        "Refund",
        "ILS 10.00",
        "Processor",
        "Rate",
        "Percent",
        "Gross",
        "Discount",
        "Net",
    )
    initial_claims = (
        EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({2})),
        EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, frozenset({11})),
        EvidenceClaim(SemanticOwner.EXCHANGE_RATE, frozenset({12})),
        EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, frozenset({13})),
        EvidenceClaim(SemanticOwner.GROSS_FX_FEE, frozenset({14})),
        EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, frozenset({15})),
        EvidenceClaim(SemanticOwner.NET_FX_FEE, frozenset({16})),
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=initial_claims,
        amount_cell=cells[9],
        original_currency="USD",
        description="Merchant",
        transaction_date=date(2026, 2, 1),
        posting_date=date(2026, 2, 3),
        conversion_date=date(2026, 2, 2),
    )

    assert validation.claims == (
        *initial_claims,
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({10})),
        EvidenceClaim(SemanticOwner.TRANSACTION_DATE, frozenset({0})),
        EvidenceClaim(SemanticOwner.POSTING_DATE, frozenset({1})),
        EvidenceClaim(SemanticOwner.LAYOUT_NOISE, frozenset({3})),
        EvidenceClaim(SemanticOwner.LOCATION, frozenset({4})),
        EvidenceClaim(SemanticOwner.INSTALLMENT, frozenset({5})),
        EvidenceClaim(SemanticOwner.ORIGINAL_VALUE, frozenset({6})),
        EvidenceClaim(SemanticOwner.CONVERSION_DATE, frozenset({7})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({8})),
        EvidenceClaim(SemanticOwner.CATEGORY, frozenset({9})),
    )
    assert {claim.owner for claim in validation.claims} == set(SemanticOwner)
    assert ledger.validate_claims(validation.claims).unclaimed_atom_ids == frozenset()
    assert validation.diagnostics == ()


def test_semantic_validation_splits_boundary_and_general_high_confidence_atoms() -> None:
    date_cell = _cell(
        "01/02/2026 Lost",
        0,
        words=(_word("01/02/2026", 2.0, 20.0), _word("Lost", 24.0, 35.0)),
    )
    high_unknown = _cell("Mystery", 1)
    low_unknown = _cell("Faint", 2, confidence=0.79)
    amount_cell = _cell("ILS 10.00", 3)
    row = _row(date_cell, high_unknown, low_unknown, amount_cell)
    region = _region(
        (ColumnRole.DATE, ColumnRole.UNKNOWN, ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("Transaction date", "?", "?", "Billed amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount_cell,
        transaction_date=date(2026, 2, 1),
    )
    unclaimed = ledger.validate_claims(validation.claims).unclaimed_atom_ids
    high_confidence_unclaimed = frozenset(
        atom_id for atom_id in unclaimed if ledger.atoms[atom_id].confidence >= 0.8
    )

    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({4})),
        EvidenceClaim(SemanticOwner.TRANSACTION_DATE, frozenset({0})),
    )
    assert ledger.atoms_for_cell(date_cell) == frozenset({0, 1})
    assert unclaimed == frozenset({1, 2, 3})
    assert high_confidence_unclaimed == frozenset({1, 2})
    assert validation.diagnostics == (
        "unconsumed_description_boundary_text",
        "unconsumed_transaction_semantic_text",
    )


def test_proven_unanchored_short_date_is_claimed_as_ancillary_evidence() -> None:
    first = _row(_cell("13/03/26", 0), _cell("10.00", 1))
    second = _row(
        _cell("20/03/26", 0, y=50.0),
        _cell("20.00", 1, y=50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.AMOUNT),
        (first, second),
        headers=("Date", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((first,))

    validation = _validate(
        rows=(first,),
        region=region,
        ledger=ledger,
        amount_cell=first.cells[1],
    )

    assert tuple(atom.text for atom in ledger.atoms) == ("13/03/26", "10.00")
    assert validation == SemanticValidation(
        claims=(
            EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({1})),
            EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({0})),
        ),
        diagnostics=(),
    )


def test_semantic_validation_distinguishes_stable_and_unstable_unknown_columns() -> None:
    first = _row(_cell("Retail", 0), _cell("Alpha1", 1), _cell("10.00", 2))
    second = _row(
        _cell("Services", 0, y=50.0),
        _cell("01/02/2026", 1, y=50.0),
        _cell("20.00", 2, y=50.0),
    )
    third = _row(
        _cell("Travel", 0, y=70.0),
        _cell("Other", 1, y=70.0),
        _cell("30.00", 2, y=70.0),
    )
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (first, second, third),
        headers=("Band A", "Band B", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((first,))

    validation = _validate(
        rows=(first,),
        region=region,
        ledger=ledger,
        amount_cell=first.cells[2],
    )

    assert _stable_unknown_columns(region) == frozenset({0})
    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({2})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({0})),
    )
    assert ledger.validate_claims(validation.claims).unclaimed_atom_ids == frozenset({1})
    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


def test_explicit_category_and_ancillary_unknowns_have_distinct_claims() -> None:
    row = _row(_cell("Refund", 0), _cell("No card", 1), _cell("10.00", 2))
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("Category", "Notes", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=row.cells[2],
    )

    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({2})),
        EvidenceClaim(SemanticOwner.CATEGORY, frozenset({0})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({1})),
    )
    assert validation.diagnostics == ()


def test_safe_card_identifier_is_ancillary_without_assignment_or_semantic_noise() -> None:
    row = _row(
        _cell("123456", 0),
        _cell("Card ID purchase", 1),
        _cell("10.00", 2),
    )
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
        headers=("Reference", "Description", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))
    description_claim = EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({1}))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(description_claim,),
        amount_cell=row.cells[2],
        description="Card ID purchase",
    )

    assert assignment_diagnostics(row, region, ledger) == ()
    assert validation.claims == (
        description_claim,
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({2})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({0})),
    )
    assert validation.diagnostics == ()


def test_isolated_ocr_edge_artifact_is_layout_noise() -> None:
    artifact_word = Word(
        text="$",
        bbox=(0.0, 30.0, 8.0, 40.0),
        source="ocr",
        confidence=0.8,
    )
    artifact = _cell("$", 0, confidence=0.8, words=(artifact_word,))
    amount = _cell("10.00", 1)
    row = _row(artifact, amount)
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("?", "Amount"),
    )
    artifact_header = Cell(
        page_number=1,
        bbox=(0.0, 10.0, 40.0, 20.0),
        text="?",
        words=(
            Word(
                text="?",
                bbox=(0.0, 10.0, 8.0, 20.0),
                source="ocr",
                confidence=0.8,
            ),
        ),
        confidence=0.8,
    )
    columns = (
        region.table_schema.columns[0].model_copy(update={"source_cells": (artifact_header,)}),
        region.table_schema.columns[1],
    )
    region = region.model_copy(
        update={
            "table_schema": region.table_schema.model_copy(
                update={
                    "columns": columns,
                    "header_cells": (artifact_header, region.table_schema.header_cells[1]),
                }
            )
        }
    )
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
    )

    assert assignment_diagnostics(row, region, ledger) == ()
    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({1})),
        EvidenceClaim(SemanticOwner.LAYOUT_NOISE, frozenset({0})),
    )
    assert validation.diagnostics == ()


def test_fragmented_foreign_conversion_date_claims_exact_glyph_atoms() -> None:
    conversion_text = "8/06/26"
    conversion = _cell(
        conversion_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(conversion_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(conversion, amount)
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("Detail", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))
    candidates = ledger.fragmented_date_candidates(conversion)

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
        original_currency="USD",
        transaction_date=date(2026, 6, 1),
        conversion_date=date(2026, 6, 8),
    )

    assert tuple((candidate.text, candidate.atom_ids) for candidate in candidates) == (
        (conversion_text, frozenset(range(7))),
    )
    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({7})),
        EvidenceClaim(SemanticOwner.CONVERSION_DATE, frozenset(range(7))),
    )
    assert validation.diagnostics == ()


def test_semantic_validation_preserves_ledger_diagnostic_order_and_deduplication() -> None:
    mystery = _cell("Mystery", 0)
    amount = _cell("10.00", 1)
    row = _row(mystery, amount)
    region = _region((ColumnRole.UNKNOWN, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({99})),
            EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({99})),
            EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({0})),
            EvidenceClaim(SemanticOwner.CATEGORY, frozenset({0})),
        ),
        amount_cell=amount,
    )

    assert validation.diagnostics == (
        "unknown_semantic_evidence_atom",
        "conflicting_semantic_evidence_claim",
    )


@pytest.mark.parametrize(
    ("roles", "row", "column_diagnostics", "expected"),
    (
        (
            (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
            _row(
                _cell("99.00", 0, bbox=(0.0, 30.0, 18.0, 40.0)),
                _cell("88.00", 0, bbox=(22.0, 30.0, 40.0, 40.0)),
                _cell("10.00", 1),
            ),
            {0: ("ambiguous_role", "alternative_role:amount", "unrelated")},
            (
                "column:0:role_unknown",
                "column:0:ambiguous_role",
                "column:0:alternative_role:amount",
                "unresolved_relevant_cell",
            ),
        ),
        (
            (ColumnRole.LOCATION, ColumnRole.AMOUNT),
            _row(_cell("99.00", 0), _cell("10.00", 1)),
            {},
            ("column:0:unexpected_location_value", "unresolved_relevant_cell"),
        ),
    ),
)
def test_assignment_diagnostics_preserve_order_and_deduplicate(
    roles: tuple[ColumnRole, ...],
    row: Row,
    column_diagnostics: Mapping[int, tuple[str, ...]],
    expected: tuple[str, ...],
) -> None:
    region = _region(roles, (row,), column_diagnostics=column_diagnostics)
    ledger = EvidenceLedger.from_rows((row,))

    assert assignment_diagnostics(row, region, ledger) == expected


def test_assignment_diagnostics_distinguish_unmatched_and_multiply_assigned_cells() -> None:
    unmatched_row = _row(_cell("99.00", 4))
    unmatched_region = _region((ColumnRole.AMOUNT,), (unmatched_row,))
    unmatched_ledger = EvidenceLedger.from_rows((unmatched_row,))

    overlap_cell = _cell("99.00", 0, bbox=(30.0, 30.0, 50.0, 40.0))
    overlap_row = _row(overlap_cell)
    overlap_region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (overlap_row,),
    )
    overlap_columns = (
        overlap_region.table_schema.columns[0].model_copy(
            update={"bbox": (0.0, 10.0, 60.0, 200.0)}
        ),
        overlap_region.table_schema.columns[1].model_copy(
            update={"bbox": (20.0, 10.0, 80.0, 200.0)}
        ),
    )
    overlap_region = overlap_region.model_copy(
        update={
            "table_schema": overlap_region.table_schema.model_copy(
                update={"columns": overlap_columns}
            )
        }
    )
    overlap_ledger = EvidenceLedger.from_rows((overlap_row,))

    assert assignment_diagnostics(unmatched_row, unmatched_region, unmatched_ledger) == (
        "unmatched_cell",
        "unresolved_relevant_cell",
    )
    assert assignment_diagnostics(overlap_row, overlap_region, overlap_ledger) == (
        "multiply_assigned_cell",
        "unresolved_relevant_cell",
    )


def test_role_contract_diagnostics_preserve_cardinality_order() -> None:
    roles = (
        *(ColumnRole.DATE for _ in range(3)),
        *(ColumnRole.CONVERSION_DATE for _ in range(2)),
        *(ColumnRole.DESCRIPTION for _ in range(2)),
        *(ColumnRole.LOCATION for _ in range(2)),
        *(ColumnRole.AMOUNT for _ in range(2)),
        *(ColumnRole.ORIGINAL_AMOUNT for _ in range(2)),
        *(ColumnRole.CURRENCY for _ in range(2)),
        *(ColumnRole.BILLING_CURRENCY for _ in range(2)),
        *(ColumnRole.ORIGINAL_CURRENCY for _ in range(2)),
        *(ColumnRole.INSTALLMENT for _ in range(2)),
    )
    row = _row(*(_cell("x", index) for index in range(len(roles))))
    region = _region(roles, (row,))

    assert role_contract_diagnostics(region) == (
        "unsupported_role_cardinality:date",
        "unsupported_role_cardinality:conversion_date",
        "unsupported_role_cardinality:description",
        "unsupported_role_cardinality:location",
        "unsupported_role_cardinality:amount",
        "unsupported_role_cardinality:original_amount",
        "unsupported_role_cardinality:currency",
        "unsupported_role_cardinality:billing_currency",
        "unsupported_role_cardinality:original_currency",
        "unsupported_role_cardinality:installment",
    )


def test_role_contract_diagnostic_orders_dependency_after_cardinality() -> None:
    row = _row(_cell("USD", 0), _cell("x", 1), _cell("y", 2))
    region = _region(
        (
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.DESCRIPTION,
            ColumnRole.DESCRIPTION,
        ),
        (row,),
    )

    assert role_contract_diagnostics(region) == (
        "unsupported_role_cardinality:description",
        "original_currency_without_original_amount",
    )
