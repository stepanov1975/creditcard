from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, fields
from datetime import date

import pytest

import ccparser.normalization_semantics as normalization_semantics
from ccparser.date_tokens import DateTokenStyle
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.evidence import Glyph, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import EvidenceReference
from ccparser.normalization_dates import DateColumnKind
from ccparser.normalization_semantics import (
    SemanticValidation,
    assignment_diagnostics,
    role_contract_diagnostics,
    validate_transaction_semantics,
)
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner


def test_normalization_semantics_exports_exact_public_contract() -> None:
    assert normalization_semantics.__all__ == [
        "SemanticValidation",
        "assignment_diagnostics",
        "explicit_category_unknown_columns",
        "role_contract_diagnostics",
        "validate_transaction_semantics",
    ]


def test_assignment_diagnostics_names_each_unresolved_decision_once() -> None:
    source = inspect.getsource(normalization_semantics.assignment_diagnostics)

    assert "common_safe =" in source
    assert "unresolved_unknown =" in source
    assert "unresolved_alternative =" in source
    assert "unresolved_location =" in source


def test_semantic_claim_accumulator_preserves_incoming_claims_and_read_only_views() -> None:
    incoming = (
        EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({1, 2})),
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({2, 99})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset()),
    )

    accumulator = normalization_semantics._SemanticClaimAccumulator(incoming)

    assert accumulator.claims == incoming
    assert all(
        actual is expected for actual, expected in zip(accumulator.claims, incoming, strict=True)
    )
    assert accumulator.claimed_atom_ids == frozenset({1, 2, 99})
    assert isinstance(accumulator.claims, tuple)
    assert isinstance(accumulator.claimed_atom_ids, frozenset)
    with pytest.raises(AttributeError):
        accumulator.claims = ()
    with pytest.raises(AttributeError):
        accumulator.claimed_atom_ids = frozenset()


def test_semantic_claim_accumulator_appends_only_incremental_remaining_ids() -> None:
    accumulator = normalization_semantics._SemanticClaimAccumulator(
        (EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({1, 2})),)
    )

    accumulator.append_remaining(SemanticOwner.BILLED_VALUE, (2, 3, 4))
    accumulator.append_remaining(SemanticOwner.ANCILLARY, (3, 4, 5))
    accumulator.append_remaining(SemanticOwner.ANCILLARY, (1, 2, 3, 4, 5))

    assert accumulator.claims == (
        EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({1, 2})),
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({3, 4})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({5})),
    )
    assert accumulator.claimed_atom_ids == frozenset({1, 2, 3, 4, 5})


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


def _glyphs(text: str, x0: float, *, font: str = "Synthetic") -> tuple[Glyph, ...]:
    return tuple(
        Glyph(
            char=char,
            bbox=(x0 + index, 30.0, x0 + index + 0.8, 40.0),
            origin=(x0 + index, 39.0),
            font=font,
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(text)
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
    date_column_kinds: Mapping[int, DateColumnKind] | None = None,
    accepted_conversion_date_atom_ids: frozenset[int] = frozenset(),
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
        accepted_conversion_date_atom_ids=accepted_conversion_date_atom_ids,
    )


def test_semantic_validation_is_frozen_slotted_value() -> None:
    validation = SemanticValidation(claims=(), diagnostics=())

    assert tuple(field.name for field in fields(validation)) == ("claims", "diagnostics")
    assert SemanticValidation.__slots__ == ("claims", "diagnostics")
    with pytest.raises(FrozenInstanceError):
        validation.diagnostics = ("changed",)


def test_semantic_validation_claims_every_owner_in_exact_atom_and_claim_order() -> None:
    transaction_date_cell = _cell(
        "01/02/2026 |",
        0,
        words=(
            _word("01/02/2026", 2.0, 20.0),
            Word(
                text="|",
                bbox=(25.0, 30.0, 29.0, 40.0),
                source="digital",
                confidence=0.4,
            ),
        ),
    )
    description = _cell(
        "Merchant 2026",
        2,
        words=(_word("Merchant", 102.0, 120.0), _word("2026", 125.0, 135.0)),
    )
    cells = (
        transaction_date_cell,
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
        "|",
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
        EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({3, 4})),
        EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, frozenset({12})),
        EvidenceClaim(SemanticOwner.EXCHANGE_RATE, frozenset({13})),
        EvidenceClaim(SemanticOwner.FX_FEE_PERCENTAGE, frozenset({14})),
        EvidenceClaim(SemanticOwner.GROSS_FX_FEE, frozenset({15})),
        EvidenceClaim(SemanticOwner.FX_FEE_DISCOUNT, frozenset({16})),
        EvidenceClaim(SemanticOwner.NET_FX_FEE, frozenset({17})),
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=initial_claims,
        amount_cell=cells[9],
        original_currency="USD",
        description="Merchant 2026",
        transaction_date=date(2026, 2, 1),
        posting_date=date(2026, 2, 3),
        conversion_date=date(2026, 2, 2),
    )

    assert validation.claims == (
        *initial_claims,
        EvidenceClaim(SemanticOwner.BILLED_VALUE, frozenset({11})),
        EvidenceClaim(SemanticOwner.TRANSACTION_DATE, frozenset({0})),
        EvidenceClaim(SemanticOwner.LAYOUT_NOISE, frozenset({1})),
        EvidenceClaim(SemanticOwner.POSTING_DATE, frozenset({2})),
        EvidenceClaim(SemanticOwner.LOCATION, frozenset({5})),
        EvidenceClaim(SemanticOwner.INSTALLMENT, frozenset({6})),
        EvidenceClaim(SemanticOwner.ORIGINAL_VALUE, frozenset({7})),
        EvidenceClaim(SemanticOwner.CONVERSION_DATE, frozenset({8})),
        EvidenceClaim(SemanticOwner.ANCILLARY, frozenset({9})),
        EvidenceClaim(SemanticOwner.CATEGORY, frozenset({10})),
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


def test_semantic_validation_claims_separate_date_marker_as_layout_noise() -> None:
    date_cell = _cell(
        "25/07/26 |",
        0,
        words=(
            _word("25/07/26", 0.0, 18.0),
            Word(
                text="|",
                bbox=(25.0, 30.0, 29.0, 40.0),
                source="digital",
                confidence=0.4,
            ),
        ),
    )
    amount_cell = _cell("10.00", 1)
    row = _row(date_cell, amount_cell)
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount_cell,
        transaction_date=date(2026, 7, 25),
        year_context=DiscoveredDateYearContext(
            style=DateTokenStyle.DAY_FIRST_SLASH,
            year=2026,
            year_by_suffix=((26, 2026),),
            evidence=(
                EvidenceReference(
                    page_number=1,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    raw_text="year",
                ),
            ),
            confidence=1.0,
        ),
    )

    assert (
        EvidenceClaim(
            SemanticOwner.TRANSACTION_DATE,
            frozenset((atom_id_by_text["25/07/26"],)),
        )
        in validation.claims
    )
    assert (
        EvidenceClaim(
            SemanticOwner.LAYOUT_NOISE,
            frozenset((atom_id_by_text["|"],)),
        )
        in validation.claims
    )
    assert validation.diagnostics == ()


def _date_description_custom_font_marker_case(
    *,
    marker_font: str = "SyntheticIcon",
    marker_width: float = 1.6,
    marker_x: float = 64.7,
    marker_word: bool = True,
) -> tuple[
    Row,
    TableRegion,
    Cell,
    Cell,
    EvidenceLedger,
    frozenset[int],
    frozenset[int],
]:
    merchant_glyphs = tuple(_glyph(char, 22.0 - index) for index, char in enumerate("בית"))
    date_glyphs = _glyphs("25/07/26", 55.0)
    marker_glyph = Glyph(
        char="6",
        bbox=(marker_x, 30.0, marker_x + marker_width, 40.0),
        origin=(marker_x, 39.0),
        font=marker_font,
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    words = [
        _word("בית", 20.0, 22.8),
        _word("25/07/26", 55.0, 62.8),
    ]
    if marker_word:
        words.append(_word("6", marker_x, marker_x + marker_width))
    date_cell = _cell(
        "25/07/266 בית",
        1,
        bbox=(20.0, 30.0, 90.0, 40.0),
        glyphs=(*merchant_glyphs, *date_glyphs, marker_glyph),
        words=tuple(words),
    )
    amount_cell = _cell("10.00", 2)
    row = _row(date_cell, amount_cell)
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    description_ids = frozenset(
        atom.atom_id for atom in ledger.atoms if atom.glyph in merchant_glyphs
    )
    marker_ids = frozenset(atom.atom_id for atom in ledger.atoms if atom.glyph == marker_glyph)
    return (
        row,
        region,
        date_cell,
        amount_cell,
        ledger,
        description_ids,
        marker_ids,
    )


def _short_year_context() -> DiscoveredDateYearContext:
    return DiscoveredDateYearContext(
        style=DateTokenStyle.DAY_FIRST_SLASH,
        year=2026,
        year_by_suffix=((26, 2026),),
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
                raw_text="year",
            ),
        ),
        confidence=1.0,
    )


def test_semantic_validation_claims_date_boundary_custom_font_digit_as_layout_noise() -> None:
    row, region, _, amount, ledger, description_ids, marker_ids = (
        _date_description_custom_font_marker_case()
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(EvidenceClaim(SemanticOwner.DESCRIPTION, description_ids),),
        amount_cell=amount,
        description="בית",
        transaction_date=date(2026, 7, 25),
        year_context=_short_year_context(),
    )

    assert EvidenceClaim(SemanticOwner.LAYOUT_NOISE, marker_ids) in validation.claims
    assert marker_ids.isdisjoint(ledger.validate_claims(validation.claims).unclaimed_atom_ids)
    assert validation.diagnostics == ()


@pytest.mark.parametrize(
    ("marker_font", "marker_width", "marker_x", "marker_word"),
    (
        ("Synthetic", 1.6, 64.7, True),
        ("SyntheticIcon", 0.8, 64.7, True),
        ("SyntheticIcon", 1.6, 70.0, True),
        ("SyntheticIcon", 1.6, 64.7, False),
    ),
    ids=("same-font", "ordinary-width", "not-adjacent", "missing-word"),
)
def test_semantic_validation_leaves_unproven_date_boundary_digit_unclaimed(
    marker_font: str,
    marker_width: float,
    marker_x: float,
    marker_word: bool,
) -> None:
    row, region, _, amount, ledger, description_ids, marker_ids = (
        _date_description_custom_font_marker_case(
            marker_font=marker_font,
            marker_width=marker_width,
            marker_x=marker_x,
            marker_word=marker_word,
        )
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(EvidenceClaim(SemanticOwner.DESCRIPTION, description_ids),),
        amount_cell=amount,
        description="בית",
        transaction_date=date(2026, 7, 25),
        year_context=_short_year_context(),
    )

    assert all(claim.atom_ids.isdisjoint(marker_ids) for claim in validation.claims)
    assert marker_ids <= ledger.validate_claims(validation.claims).unclaimed_atom_ids


def test_semantic_validation_does_not_claim_marker_for_unaccepted_physical_date() -> None:
    row, region, _, amount, ledger, description_ids, marker_ids = (
        _date_description_custom_font_marker_case()
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(EvidenceClaim(SemanticOwner.DESCRIPTION, description_ids),),
        amount_cell=amount,
        description="בית",
        transaction_date=date(2026, 7, 24),
        year_context=_short_year_context(),
    )

    assert all(claim.atom_ids.isdisjoint(marker_ids) for claim in validation.claims)
    assert marker_ids <= ledger.validate_claims(validation.claims).unclaimed_atom_ids


def test_semantic_validation_leaves_separate_date_numeric_residual_unclaimed() -> None:
    date_cell = _cell(
        "6",
        0,
        words=(_word("25/07/26", 0.0, 18.0), _word("6", 25.0, 29.0)),
    )
    amount_cell = _cell("10.00", 1)
    row = _row(date_cell, amount_cell)
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}
    year_context = DiscoveredDateYearContext(
        style=DateTokenStyle.DAY_FIRST_SLASH,
        year=2026,
        year_by_suffix=((26, 2026),),
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
                raw_text="year",
            ),
        ),
        confidence=1.0,
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount_cell,
        transaction_date=date(2026, 7, 25),
        year_context=year_context,
    )

    assert (
        EvidenceClaim(
            SemanticOwner.TRANSACTION_DATE,
            frozenset((atom_id_by_text["25/07/26"],)),
        )
        in validation.claims
    )
    numeric_residual_id = atom_id_by_text["6"]
    assert all(numeric_residual_id not in claim.atom_ids for claim in validation.claims)
    assert numeric_residual_id in ledger.validate_claims(validation.claims).unclaimed_atom_ids
    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


def test_semantic_validation_does_not_hide_integer_word_beside_exact_logical_date() -> None:
    date_cell = _cell(
        "25/07/2026",
        0,
        words=(_word("25/07/2026", 0.0, 18.0), _word("6", 25.0, 29.0)),
    )
    amount_cell = _cell("10.00", 1)
    row = _row(date_cell, amount_cell)
    region = _region((ColumnRole.DATE, ColumnRole.AMOUNT), (row,))
    ledger = EvidenceLedger.from_rows((row,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount_cell,
        transaction_date=date(2026, 7, 25),
    )

    numeric_residual_id = atom_id_by_text["6"]
    assert all(numeric_residual_id not in claim.atom_ids for claim in validation.claims)
    assert numeric_residual_id in ledger.validate_claims(validation.claims).unclaimed_atom_ids
    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


def test_semantic_validation_leaves_untyped_description_integer_unclaimed() -> None:
    date_cell = _cell("25/07/2026", 0)
    description_cell = _cell(
        "Merchant 42",
        1,
        words=(_word("Merchant", 52.0, 68.0), _word("42", 72.0, 78.0)),
    )
    amount_cell = _cell("10.00", 2)
    row = _row(date_cell, description_cell, amount_cell)
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount_cell,
        initial_claims=(
            EvidenceClaim(
                SemanticOwner.DESCRIPTION,
                frozenset((atom_id_by_text["Merchant"],)),
            ),
        ),
        description="Merchant",
        transaction_date=date(2026, 7, 25),
    )

    numeric_residual_id = atom_id_by_text["42"]
    assert all(numeric_residual_id not in claim.atom_ids for claim in validation.claims)
    assert numeric_residual_id in ledger.validate_claims(validation.claims).unclaimed_atom_ids
    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


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


def test_semantic_validation_distinguishes_unknown_columns_despite_unrelated_diagnostic() -> None:
    first = _row(_cell("Retail", 0), _cell("Alpha1", 1), _cell("10.00", 2)).model_copy(
        update={"diagnostics": ("not_a_continuation",)}
    )
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


def test_calendar_invalid_fragmented_date_in_explicit_ancillary_column_is_ancillary() -> None:
    invalid_text = "31/02/2026"
    ancillary = _cell(
        invalid_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(invalid_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(ancillary, amount)
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("Card presented", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert ledger.fragmented_date_candidates(ancillary)
    assert assignment_diagnostics(row, region, ledger) == ()

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
    )

    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, ledger.atoms_for_cell(amount)),
        EvidenceClaim(SemanticOwner.ANCILLARY, ledger.atoms_for_cell(ancillary)),
    )
    assert validation.diagnostics == ()


def test_potentially_valid_date_in_explicit_ancillary_column_is_ancillary() -> None:
    candidate_text = "03.04.26"
    candidate = _cell(
        candidate_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(candidate_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(candidate, amount)
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=("Transaction detail", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))
    year_context = DiscoveredDateYearContext(
        year=2026,
        style=DateTokenStyle.DAY_FIRST_SLASH,
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(0.0, 0.0, 10.0, 10.0),
                raw_text="statement date evidence",
            ),
        ),
        confidence=1.0,
    )

    assert assignment_diagnostics(row, region, ledger, year_context=year_context) == ()

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
        year_context=year_context,
    )

    assert validation.claims == (
        EvidenceClaim(SemanticOwner.BILLED_VALUE, ledger.atoms_for_cell(amount)),
        EvidenceClaim(SemanticOwner.ANCILLARY, ledger.atoms_for_cell(candidate)),
    )
    assert validation.diagnostics == ()


@pytest.mark.parametrize(
    "header",
    ("Reference", "Conversion date", "Foreign-currency fee"),
)
def test_potentially_valid_unknown_date_stays_strict_without_ancillary_header(
    header: str,
) -> None:
    candidate_text = "03.04.26"
    candidate = _cell(
        candidate_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(candidate_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(candidate, amount)
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row,),
        headers=(header, "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
    )

    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


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


def _adjacent_unknown_processor_reference_case(
    reference_text: str = "123-456",
    *,
    description_text: str = "Merchant",
    reference_column: int = 1,
    reference_y: float = 30.0,
    reference_height: float = 10.0,
    source_reference_text: str | None = None,
    reference_header: str = "Unknown",
) -> tuple[Row, TableRegion, EvidenceLedger, Cell, Cell, tuple[Cell, ...]]:
    description = _cell(
        description_text,
        0,
        words=(_word(description_text, 0.0, 40.0),),
    )
    reference = _cell(
        reference_text,
        reference_column,
        y=reference_y,
        bbox=(
            reference_column * 50.0,
            reference_y,
            reference_column * 50.0 + 40.0,
            reference_y + reference_height,
        ),
        words=()
        if source_reference_text is not None
        else (
            Word(
                text=reference_text,
                bbox=(
                    reference_column * 50.0,
                    reference_y,
                    reference_column * 50.0 + 40.0,
                    reference_y + reference_height,
                ),
                source="ocr",
                confidence=0.97,
            ),
        ),
        glyphs=()
        if source_reference_text is None
        else _glyphs(source_reference_text, reference_column * 50.0),
    )
    references = (reference,)
    amount_column = max(reference_column + 1, 2)
    amount = _cell("10.00", amount_column)
    row = _row(description, *references, amount)
    roles = tuple(
        ColumnRole.DESCRIPTION
        if index == 0
        else ColumnRole.AMOUNT
        if index == amount_column
        else ColumnRole.UNKNOWN
        for index in range(amount_column + 1)
    )
    headers = tuple(
        "Description"
        if index == 0
        else "Amount"
        if index == amount_column
        else reference_header
        if index == reference_column
        else "Unknown"
        for index in range(amount_column + 1)
    )
    region = _region(roles, (row,), headers=headers)
    ledger = EvidenceLedger.from_rows((row,))
    return row, region, ledger, description, amount, references


def test_adjacent_unknown_processor_reference_has_exact_semantic_owner() -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case()
    )
    initial = (EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),)

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=initial,
        amount_cell=amount,
        description="Merchant",
    )

    assert (
        EvidenceClaim(
            SemanticOwner.PROCESSOR_REFERENCE,
            ledger.atoms_for_cell(references[0]),
        )
        in validation.claims
    )
    assert validation.diagnostics == ()


def test_adjacent_unknown_processor_reference_accepts_short_numeric_primary() -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case(description_text="12")
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="12",
    )

    assert (
        EvidenceClaim(
            SemanticOwner.PROCESSOR_REFERENCE,
            ledger.atoms_for_cell(references[0]),
        )
        in validation.claims
    )
    assert validation.diagnostics == ()


def test_adjacent_unknown_processor_reference_rejects_typed_numeric_primary() -> None:
    row, region, ledger, description, amount, _ = _adjacent_unknown_processor_reference_case(
        description_text="10.00"
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="10.00",
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


@pytest.mark.parametrize("description_text", (".", "@", "#", "--", "()"))
def test_adjacent_unknown_processor_reference_rejects_punctuation_only_primary(
    description_text: str,
) -> None:
    row, region, ledger, description, amount, _ = _adjacent_unknown_processor_reference_case(
        description_text=description_text
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description=description_text,
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


def test_adjacent_unknown_processor_reference_requires_matching_positioned_source() -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case(source_reference_text="765-432")
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="Merchant",
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    reference_alphanumeric_ids = frozenset(
        atom_id
        for atom_id in ledger.atoms_for_cell(references[0])
        if any(char.isalnum() for char in ledger.atoms[atom_id].text)
    )
    assert (
        reference_alphanumeric_ids <= ledger.validate_claims(validation.claims).unclaimed_atom_ids
    )
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


def test_adjacent_unknown_processor_reference_rejects_tiny_superscript_geometry() -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case(
            reference_y=34.5,
            reference_height=1.0,
        )
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="Merchant",
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert (
        ledger.atoms_for_cell(references[0])
        <= ledger.validate_claims(validation.claims).unclaimed_atom_ids
    )
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


@pytest.mark.parametrize(
    ("header", "owner"),
    (
        ("Notes", SemanticOwner.ANCILLARY),
        ("Category", SemanticOwner.CATEGORY),
    ),
)
def test_explicit_unknown_header_ownership_precedes_processor_shape(
    header: str,
    owner: SemanticOwner,
) -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case(reference_header=header)
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="Merchant",
    )

    assert EvidenceClaim(owner, ledger.atoms_for_cell(references[0])) in validation.claims
    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert validation.diagnostics == ()


@pytest.mark.parametrize(
    ("reference_text", "reference_column", "reference_y"),
    (
        ("123-45", 1, 30.0),
        ("01-02-2026", 1, 30.0),
        ("2026-01", 1, 30.0),
        ("01-2026", 1, 30.0),
        ("123-456", 2, 30.0),
        ("123-456", 1, 45.0),
    ),
    ids=(
        "too-short",
        "full-date",
        "year-month",
        "month-year",
        "nonadjacent",
        "misaligned",
    ),
)
def test_unknown_numeric_text_without_exact_processor_geometry_stays_unclaimed(
    reference_text: str,
    reference_column: int,
    reference_y: float,
) -> None:
    row, region, ledger, description, amount, references = (
        _adjacent_unknown_processor_reference_case(
            reference_text,
            reference_column=reference_column,
            reference_y=reference_y,
        )
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="Merchant",
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert (
        ledger.atoms_for_cell(references[0])
        <= ledger.validate_claims(validation.claims).unclaimed_atom_ids
    )
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


def test_competing_adjacent_unknown_processor_references_stay_unclaimed() -> None:
    left = _cell(
        "123-456",
        0,
        words=(_word("123-456", 0.0, 40.0),),
    )
    description = _cell(
        "Merchant",
        1,
        words=(_word("Merchant", 50.0, 90.0),),
    )
    right = _cell(
        "765-432",
        2,
        words=(_word("765-432", 100.0, 140.0),),
    )
    amount = _cell("10.00", 3)
    row = _row(left, description, right, amount)
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (row,),
    )
    ledger = EvidenceLedger.from_rows((row,))

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(SemanticOwner.DESCRIPTION, ledger.atoms_for_cell(description)),
        ),
        amount_cell=amount,
        description="Merchant",
    )

    assert all(claim.owner is not SemanticOwner.PROCESSOR_REFERENCE for claim in validation.claims)
    assert (
        ledger.atoms_for_cell(left) | ledger.atoms_for_cell(right)
        <= ledger.validate_claims(validation.claims).unclaimed_atom_ids
    )
    assert "unconsumed_transaction_semantic_text" in validation.diagnostics


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
        headers=("Conversion detail", "Amount"),
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


def test_untyped_unknown_foreign_date_remains_unclaimed_and_ambiguous() -> None:
    reference_text = "Reference 25/06/26"
    reference = _cell(
        reference_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(reference_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(reference, amount)
    second_row = _row(
        _cell("Reference 26/06/26", 0, y=50.0),
        _cell("20.00", 1, y=50.0),
    )
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row, second_row),
        headers=("Reference", "Amount"),
    )
    ledger = EvidenceLedger.from_rows((row,))
    reference_atom_ids = ledger.atoms_for_cell(reference)
    meaningful_reference_atom_ids = frozenset(
        atom_id
        for atom_id in reference_atom_ids
        if any(char.isalnum() for char in ledger.atoms[atom_id].text)
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        amount_cell=amount,
        original_currency="USD",
        transaction_date=date(2026, 6, 24),
        conversion_date=None,
    )

    assert assignment_diagnostics(row, region, ledger) == (
        "column:0:role_unknown",
        "unresolved_relevant_cell",
    )
    assert all(
        claim.atom_ids.isdisjoint(reference_atom_ids)
        for claim in validation.claims
        if claim.owner in {SemanticOwner.CONVERSION_DATE, SemanticOwner.ANCILLARY}
    )
    assert (
        ledger.validate_claims(validation.claims).unclaimed_atom_ids
        >= meaningful_reference_atom_ids
    )
    assert validation.diagnostics == ("unconsumed_transaction_semantic_text",)


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


def test_assignment_accepts_relevant_value_in_proven_stable_ancillary_column() -> None:
    relevant_ancillary = _cell("USD reference 123", 0)
    row = _row(
        relevant_ancillary,
        _cell("Merchant Alpha", 1),
        _cell("10.00", 2),
    )
    rows = (
        row,
        _row(
            _cell("Not presented", 0, y=50.0),
            _cell("Merchant Beta", 1, y=50.0),
            _cell("20.00", 2, y=50.0),
        ),
        _row(
            _cell("Not presented", 0, y=70.0),
            _cell("Merchant Gamma", 1, y=70.0),
            _cell("30.00", 2, y=70.0),
        ),
    )
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
        headers=("Card presented", "Description", "Amount"),
        column_diagnostics={0: ("ambiguous_role",)},
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert assignment_diagnostics(row, region, ledger) == ()
    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(
            EvidenceClaim(
                SemanticOwner.DESCRIPTION,
                ledger.atoms_for_cell(row.cells[1]),
            ),
        ),
        amount_cell=row.cells[2],
        description="Merchant Alpha",
    )
    assert any(
        claim.owner is SemanticOwner.ANCILLARY
        and claim.atom_ids == ledger.atoms_for_cell(relevant_ancillary)
        for claim in validation.claims
    )
    assert validation.diagnostics == ()


@pytest.mark.parametrize(
    "missing_proof",
    ("explicit_ancillary_header", "stable_profile", "separate_description"),
)
def test_assignment_keeps_relevant_unknown_strict_without_complete_ancillary_proof(
    missing_proof: str,
) -> None:
    relevant_ancillary = _cell("USD reference 123", 0)
    row = _row(
        relevant_ancillary,
        _cell("Merchant Alpha", 1),
        _cell("10.00", 2),
    )
    second_value = "01/02/2026" if missing_proof == "stable_profile" else "Not presented"
    third_value = "99.00" if missing_proof == "stable_profile" else "Not presented"
    rows = (
        row,
        _row(
            _cell(second_value, 0, y=50.0),
            _cell("Merchant Beta", 1, y=50.0),
            _cell("20.00", 2, y=50.0),
        ),
        _row(
            _cell(third_value, 0, y=70.0),
            _cell("Merchant Gamma", 1, y=70.0),
            _cell("30.00", 2, y=70.0),
        ),
    )
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN
            if missing_proof == "separate_description"
            else ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        rows,
        headers=(
            "Reference" if missing_proof == "explicit_ancillary_header" else "Card presented",
            "Description",
            "Amount",
        ),
        column_diagnostics={0: ("ambiguous_role",)},
    )
    ledger = EvidenceLedger.from_rows((row,))

    assert assignment_diagnostics(row, region, ledger) == (
        "column:0:role_unknown",
        "column:0:ambiguous_role",
        "unresolved_relevant_cell",
    )


def test_assignment_diagnostics_resolve_currency_alternative_for_accepted_conversion_date() -> None:
    raw_date = "03/02/26"
    conversion_date = _cell(
        raw_date,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(raw_date)),
    )
    amount = _cell("10.00", 1)
    row = _row(conversion_date, amount)
    region = _region(
        (ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        column_diagnostics={0: ("alternative_role:currency",)},
    )
    ledger = EvidenceLedger.from_rows((row,))
    accepted_atom_ids = frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(conversion_date)
        for atom_id in candidate.atom_ids
    )

    assert accepted_atom_ids
    assert (
        assignment_diagnostics(
            row,
            region,
            ledger,
            accepted_conversion_date_atom_ids=accepted_atom_ids,
        )
        == ()
    )


def test_accepted_contextual_conversion_date_resolves_unknown_role_and_owns_residual() -> None:
    raw_date = "03/02/26"
    contextual = _cell(
        "Reference",
        0,
        glyphs=(
            *(_glyph(char, float(index)) for index, char in enumerate(raw_date)),
            *(_glyph(char, 20.0 + index) for index, char in enumerate("note")),
        ),
    )
    amount = _cell("10.00", 1)
    row = _row(contextual, amount)
    second_row = _row(_cell("Reference", 0, y=50.0), _cell("20.00", 1, y=50.0))
    region = _region(
        (ColumnRole.UNKNOWN, ColumnRole.AMOUNT),
        (row, second_row),
        headers=("Reference", "Amount"),
        column_diagnostics={0: ("ambiguous_role",)},
    )
    ledger = EvidenceLedger.from_rows((row,))
    accepted_atom_ids = ledger.fragmented_date_candidates(contextual)[0].atom_ids

    assert (
        assignment_diagnostics(
            row,
            region,
            ledger,
            accepted_conversion_date_atom_ids=accepted_atom_ids,
        )
        == ()
    )

    validation = _validate(
        rows=(row,),
        region=region,
        ledger=ledger,
        initial_claims=(EvidenceClaim(SemanticOwner.CONVERSION_DATE, accepted_atom_ids),),
        amount_cell=amount,
        original_currency="USD",
        conversion_date=date(2026, 2, 3),
        accepted_conversion_date_atom_ids=accepted_atom_ids,
    )

    assert validation.diagnostics == ()
    assert any(
        claim.owner is SemanticOwner.ANCILLARY
        and claim.atom_ids == ledger.atoms_for_cell(contextual) - accepted_atom_ids
        for claim in validation.claims
    )


@pytest.mark.parametrize(
    ("logical_text", "physical_text", "accepted"),
    (
        ("03/02/26 USD", "03/02/26 USD", True),
        ("03/02/26", "03/02/26 USD", True),
        ("31/02/26", "31/02/26", False),
    ),
)
def test_assignment_diagnostics_preserve_currency_alternative_without_pure_accepted_date(
    logical_text: str,
    physical_text: str,
    accepted: bool,
) -> None:
    conversion_date = _cell(
        logical_text,
        0,
        glyphs=tuple(_glyph(char, float(index)) for index, char in enumerate(physical_text)),
    )
    amount = _cell("10.00", 1)
    row = _row(conversion_date, amount)
    region = _region(
        (ColumnRole.CONVERSION_DATE, ColumnRole.AMOUNT),
        (row,),
        column_diagnostics={0: ("alternative_role:currency",)},
    )
    ledger = EvidenceLedger.from_rows((row,))
    accepted_atom_ids = (
        frozenset(
            atom_id
            for candidate in ledger.fragmented_date_candidates(conversion_date)
            for atom_id in candidate.atom_ids
        )
        if accepted
        else frozenset()
    )

    assert assignment_diagnostics(
        row,
        region,
        ledger,
        accepted_conversion_date_atom_ids=accepted_atom_ids,
    ) == (
        "column:0:alternative_role:currency",
        "unresolved_relevant_cell",
    )


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
