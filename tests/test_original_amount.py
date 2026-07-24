from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass
from datetime import date
from decimal import Decimal, localcontext

import pytest

import ccparser.normalize as normalize_module
import ccparser.original_amount as original_amount_module
from ccparser.discovery import (
    DiscoveredDateYearContext,
    DiscoveredPrintedTotal,
    StatementGroupDiscovery,
)
from ccparser.evidence import Glyph, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
    EvidenceReference,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.normalization_dates import DateColumnKind
from ccparser.normalization_fields import BilledFields, FieldDisposition, extract_billed_fields
from ccparser.normalization_semantics import SemanticValidation
from ccparser.normalize import RowNormalizationResult, _normalize_row
from ccparser.original_amount import OriginalAmountExtraction, extract_original_amount
from ccparser.semantic_evidence import (
    EvidenceClaim,
    EvidenceLedger,
    SemanticOwner,
)


def _cell(
    text: str,
    column: int,
    *,
    y: float = 30.0,
    bbox: tuple[float, float, float, float] | None = None,
    words: tuple[Word, ...] = (),
    glyphs: tuple[Glyph, ...] = (),
    confidence: float = 1.0,
) -> Cell:
    x0 = float(column * 50)
    return Cell(
        page_number=1,
        bbox=bbox or (x0, y, x0 + 40.0, y + 10.0),
        text=text,
        words=words,
        glyphs=glyphs,
        confidence=confidence,
    )


def _word(
    text: str,
    x0: float,
    x1: float,
    *,
    y: float = 30.0,
    source: str = "digital",
    confidence: float = 1.0,
) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source=source,
        confidence=confidence,
    )


def _glyphs(text: str, x0: float, *, y: float = 30.0) -> tuple[Glyph, ...]:
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


def _row(*cells: Cell, diagnostics: tuple[str, ...] = ()) -> Row:
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
        diagnostics=diagnostics,
    )


def test_unique_row_money_pair_requires_one_distinct_amount_and_currency() -> None:
    row = _row(
        _cell(
            "USD 30.00",
            1,
            words=(
                _word("USD", 52.0, 62.0),
                _word("30.00", 64.0, 78.0),
            ),
        ),
        _cell(
            "30.00",
            2,
            words=(_word("30.00", 102.0, 116.0),),
        ),
    )

    assert original_amount_module._unique_row_money_pair(row) == (
        Decimal("30.00"),
        "USD",
    )


def _region(
    roles: tuple[ColumnRole, ...],
    rows: tuple[Row, ...],
    *,
    headers: tuple[str, ...] | None = None,
) -> TableRegion:
    header_texts = headers or tuple(role.value for role in roles)
    header_cells = tuple(_cell(text, index, y=10.0) for index, text in enumerate(header_texts))
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


def _group(region: TableRegion, *, currency: str = "ILS") -> StatementGroupDiscovery:
    total_evidence = EvidenceReference(
        page_number=1,
        bbox=(100.0, 210.0, 140.0, 220.0),
        raw_text="10.00",
    )
    return StatementGroupDiscovery(
        group_id="group-0001",
        table_regions=(region,),
        printed_total=DiscoveredPrintedTotal(
            amount_text="10.00",
            currency=currency,
            label_evidence=EvidenceReference(
                page_number=1,
                bbox=(50.0, 210.0, 90.0, 220.0),
                raw_text="Total",
            ),
            value_evidence=total_evidence,
            confidence=1.0,
        ),
        confidence=1.0,
    )


def _evidence(rows: tuple[Row, ...]) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(
            page_number=cell.page_number,
            bbox=cell.bbox,
            raw_text=cell.text,
        )
        for row in rows
        for cell in row.cells
    )


def _expected_result(
    *,
    row: Row,
    continuation_rows: tuple[Row, ...] = (),
    billed_amount: Decimal,
    diagnostics: tuple[str, ...],
    description: str | None,
    original_amount: Decimal | None,
    original_currency: str | None,
    confidence: float = 0.975,
    transaction_date: date = date(2026, 2, 1),
) -> RowNormalizationResult:
    rows = (row, *continuation_rows)
    evidence = _evidence(rows)
    transaction = Transaction(
        transaction_id="matrix-tx",
        kind=(TransactionKind.CREDIT if billed_amount < 0 else TransactionKind.CHARGE),
        billed_amount=billed_amount,
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        ambiguities=diagnostics,
        transaction_date=transaction_date,
        description=description,
        category=TransactionCategory.UNKNOWN,
        original_amount=original_amount,
        original_currency=original_currency,
        evidence=evidence,
    )
    return RowNormalizationResult(
        page_number=1,
        bbox=row.bbox,
        raw_text=" ".join(
            " ".join(cell.text for candidate in rows for cell in candidate.cells).split()
        ),
        evidence=evidence,
        transaction=transaction,
        confidence=confidence,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True, slots=True)
class _StructuralCase:
    roles: tuple[ColumnRole, ...]
    row: Row
    diagnostics: tuple[str, ...]
    billed_amount: Decimal
    original_amount: Decimal | None
    original_currency: str | None
    description: str | None = "Merchant"
    disposition: FieldDisposition = FieldDisposition.ACCEPT


_DATE = _cell("01/02/2026", 0)
_DESCRIPTION = _cell("Merchant", 1)


@pytest.mark.parametrize(
    "case",
    (
        pytest.param(
            _StructuralCase(
                roles=(ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
                row=_row(_DATE, _DESCRIPTION, _cell("10.00", 2)),
                diagnostics=(),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="no-original-column",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("USD 3.00", 2),
                    _cell("EUR 4.00", 3),
                    _cell("10.00", 4),
                ),
                diagnostics=("unsupported_role_cardinality:original_amount",),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="duplicate-original-columns",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("3.00", 2),
                    _cell("USD", 3),
                    _cell("EUR", 4),
                    _cell("10.00", 5),
                ),
                diagnostics=("unsupported_role_cardinality:original_currency",),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
                disposition=FieldDisposition.REJECT_ROW,
            ),
            id="duplicate-original-currency-columns",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.AMOUNT,
                ),
                row=_row(_DATE, _DESCRIPTION, _cell("10.00", 3)),
                diagnostics=("missing_original_amount_cell",),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="missing-original-cell",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("USD 3.00", 2),
                    _cell("EUR 4.00", 2),
                    _cell("10.00", 3),
                ),
                diagnostics=("multiple_original_amount_cells",),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="multiple-original-cells",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.AMOUNT,
                ),
                row=_row(_DATE, _DESCRIPTION, _cell("-2.00", 3)),
                diagnostics=(),
                billed_amount=Decimal("-2.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="negative-adjustment-without-original-cell",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("USD", 3),
                    _cell("-2.00", 4),
                ),
                diagnostics=("missing_original_amount_cell",),
                billed_amount=Decimal("-2.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="negative-adjustment-with-original-currency-column",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("3.00", 2),
                    _cell("USD", 3),
                    _cell("10.00", 4),
                ),
                diagnostics=(),
                billed_amount=Decimal("10.00"),
                original_amount=Decimal("3.00"),
                original_currency="USD",
            ),
            id="explicit-original-currency",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("3.00", 2),
                    _cell("10.00", 4),
                ),
                diagnostics=(
                    "missing_original_currency_cell",
                    "original_amount:unknown_currency",
                ),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="missing-original-currency-cell",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("3.00", 2),
                    _cell("USD", 3),
                    _cell("EUR", 3),
                    _cell("10.00", 4),
                ),
                diagnostics=(
                    "multiple_original_currency_cells",
                    "original_amount:unknown_currency",
                ),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="multiple-original-currency-cells",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.ORIGINAL_CURRENCY,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("3.00", 2),
                    _cell("XYZ", 3),
                    _cell("10.00", 4),
                ),
                diagnostics=(
                    "unknown_original_currency",
                    "original_amount:unknown_currency",
                    "unconsumed_transaction_semantic_text",
                ),
                billed_amount=Decimal("10.00"),
                original_amount=None,
                original_currency=None,
            ),
            id="unknown-explicit-original-currency",
        ),
        pytest.param(
            _StructuralCase(
                roles=(
                    ColumnRole.DATE,
                    ColumnRole.DESCRIPTION,
                    ColumnRole.ORIGINAL_AMOUNT,
                    ColumnRole.AMOUNT,
                ),
                row=_row(
                    _DATE,
                    _DESCRIPTION,
                    _cell("10.00", 2),
                    _cell("10.00", 3),
                ),
                diagnostics=(),
                billed_amount=Decimal("10.00"),
                original_amount=Decimal("10.00"),
                original_currency="ILS",
            ),
            id="implicit-domestic-original-currency",
        ),
    ),
)
def test_original_amount_structural_and_currency_matrix_preserves_complete_row_result(
    case: _StructuralCase,
) -> None:
    region = _region(case.roles, (case.row,))

    attempt = _normalize_row(
        row=case.row,
        continuation_rows=(),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.disposition is case.disposition
    if case.disposition is FieldDisposition.REJECT_ROW:
        assert attempt.result == RowNormalizationResult(
            page_number=1,
            bbox=case.row.bbox,
            raw_text=" ".join(cell.text for cell in case.row.cells),
            evidence=_evidence((case.row,)),
            confidence=0.0,
            diagnostics=case.diagnostics,
        )
    else:
        assert attempt.result == _expected_result(
            row=case.row,
            billed_amount=case.billed_amount,
            diagnostics=case.diagnostics,
            description=case.description,
            original_amount=case.original_amount,
            original_currency=case.original_currency,
        )


def test_implicit_original_currency_proof_ignores_active_decimal_context() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    billed_cell = _cell("123457.00", 3)
    row = _row(
        _DATE,
        _DESCRIPTION,
        _cell("123456.00", 2),
        billed_cell,
    )
    region = _region(roles, (row,))
    billed = extract_billed_fields(row=row, region=region, printed_currency="ILS")
    assert billed.disposition is FieldDisposition.ACCEPT

    with localcontext() as context:
        context.prec = 5
        extraction = extract_original_amount(
            row=row,
            continuation_rows=(),
            region=region,
            ledger=EvidenceLedger.from_rows((row,)),
            billed=billed,
            description="Merchant",
            initial_claims=(),
        )

    assert extraction == OriginalAmountExtraction(
        amount=None,
        currency=None,
        description="Merchant",
        claims=(),
        diagnostics=("original_amount:unknown_currency",),
    )


@pytest.mark.parametrize("conflicting", (False, True))
def test_location_currency_spill_matrix(conflicting: bool) -> None:
    first_location = _cell(
        "$ 1234567890",
        3,
        bbox=(150.0, 30.0, 190.0, 40.0),
        words=(_word("$", 150.0, 153.0), _word("1234567890", 154.0, 180.0)),
    )
    second_location = _cell(
        "EUR LONDON",
        3,
        bbox=(150.0, 30.0, 190.0, 40.0),
        words=(_word("EUR", 150.0, 160.0), _word("LONDON", 161.0, 180.0)),
    )
    locations = (first_location, second_location) if conflicting else (first_location,)
    row = _row(_DATE, _DESCRIPTION, _cell("3.00", 2), *locations, _cell("10.00", 4))
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.LOCATION,
        ColumnRole.AMOUNT,
    )
    region = _region(roles, (row,))

    attempt = _normalize_row(
        row=row,
        continuation_rows=(),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=row,
        billed_amount=Decimal("10.00"),
        diagnostics=("original_amount:unknown_currency",) if conflicting else (),
        description="Merchant",
        original_amount=None if conflicting else Decimal("3.00"),
        original_currency=None if conflicting else "USD",
    )


@pytest.mark.parametrize(
    ("damaged_text", "billed_text", "expected_amount"),
    (
        pytest.param(
            "1,601,00",
            "1,601.00",
            Decimal("1601.00"),
            id="two-decimal-scale",
        ),
        pytest.param("1,601,", "1601", Decimal("1601"), id="integer-scale"),
        pytest.param(
            "1,60,1",
            "160.1",
            Decimal("160.1"),
            id="one-decimal-positive-scale",
        ),
    ),
)
def test_ocr_original_amount_is_corroborated_by_exact_billed_value(
    damaged_text: str,
    billed_text: str,
    expected_amount: Decimal,
) -> None:
    damaged_original = _cell(
        damaged_text,
        2,
        y=50.0,
        bbox=(100.0, 50.0, 140.0, 60.0),
        words=(
            _word(
                damaged_text,
                100.0,
                140.0,
                y=50.0,
                source="ocr",
                confidence=0.8,
            ),
        ),
        confidence=0.8,
    )
    target = _row(
        _cell("02/02/2026", 0, y=50.0),
        _cell("OCR damaged", 1, y=50.0),
        damaged_original,
        _cell(billed_text, 3, y=50.0),
    )
    rows = (
        _row(
            _DATE,
            _DESCRIPTION,
            _cell("10.00", 2),
            _cell("10.00", 3),
        ),
        target,
        _row(
            _cell("03/02/2026", 0, y=70.0),
            _cell("Third", 1, y=70.0),
            _cell("20.00", 2, y=70.0),
            _cell("20.00", 3, y=70.0),
        ),
    )
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    region = _region(
        roles,
        rows,
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    attempt = _normalize_row(
        row=target,
        continuation_rows=(),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=target,
        billed_amount=expected_amount,
        diagnostics=(),
        description="OCR damaged",
        original_amount=expected_amount,
        original_currency="ILS",
        transaction_date=date(2026, 2, 2),
    )


def test_subordinate_detail_recovers_exact_ocr_original_amount() -> None:
    original = _cell(
        "$ 3000 MERCHANT 30.00",
        1,
        words=(
            _word("$", 52.0, 55.0, source="ocr"),
            _word("3000", 56.0, 66.0, source="ocr"),
            _word("MERCHANT", 67.0, 82.0, source="ocr"),
            _word("30.00", 83.0, 96.0, source="ocr"),
        ),
    )
    detail = _row(
        _cell(
            "USD",
            1,
            y=41.0,
            words=(_word("USD", 55.0, 65.0, y=41.0, source="ocr"),),
        ),
        _cell(
            "30.00",
            2,
            y=41.0,
            words=(_word("30.00", 105.0, 120.0, y=41.0, source="ocr"),),
        ),
        diagnostics=("subordinate_detail_continuation",),
    )
    row = _row(
        _DATE,
        original,
        _cell("MERCHANT", 2),
        _cell("100.00", 3),
    )
    roles = (
        ColumnRole.DATE,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )
    region = _region(
        roles,
        (row, detail),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    attempt = _normalize_row(
        row=row,
        continuation_rows=(detail,),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=row,
        continuation_rows=(detail,),
        billed_amount=Decimal("100.00"),
        diagnostics=(),
        description="MERCHANT",
        original_amount=Decimal("30.00"),
        original_currency="USD",
        confidence=0.9833333333333333,
    )


def test_exact_money_word_between_boundary_glyphs_recovers_original_amount() -> None:
    original = _cell(
        "A 60.00 0",
        1,
        bbox=(48.0, 30.0, 92.0, 40.0),
        words=(_word("60.00", 60.0, 80.0),),
        glyphs=(
            Glyph(
                char="0",
                bbox=(48.0, 30.0, 52.0, 40.0),
                origin=(48.0, 39.0),
                font="Synthetic",
                size=10.0,
                source="digital",
                confidence=1.0,
            ),
            *_glyphs("60.00", 60.0),
            Glyph(
                char="A",
                bbox=(88.0, 30.0, 92.0, 40.0),
                origin=(88.0, 39.0),
                font="Synthetic",
                size=10.0,
                source="digital",
                confidence=1.0,
            ),
        ),
    )
    row = _row(
        _cell("60.00", 0),
        original,
        _cell("Merchant", 2),
        _cell("01/02/2026", 3),
    )
    roles = (
        ColumnRole.AMOUNT,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.DESCRIPTION,
        ColumnRole.DATE,
    )
    region = _region(roles, (row,))

    attempt = _normalize_row(
        row=row,
        continuation_rows=(),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=row,
        billed_amount=Decimal("60.00"),
        diagnostics=(),
        description="Merchant",
        original_amount=Decimal("60.00"),
        original_currency="ILS",
    )


def test_unparseable_original_amount_preserves_ordered_parse_and_semantic_diagnostics() -> None:
    row = _row(
        _DATE,
        _DESCRIPTION,
        _cell("not money", 2),
        _cell("10.00", 3),
    )
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    region = _region(roles, (row,))

    attempt = _normalize_row(
        row=row,
        continuation_rows=(),
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=row,
        billed_amount=Decimal("10.00"),
        diagnostics=(
            "original_amount:unknown_currency",
            "original_amount:invalid_amount_text",
            "unconsumed_description_boundary_text",
        ),
        description="Merchant",
        original_amount=None,
        original_currency=None,
    )


@dataclass(frozen=True, slots=True)
class _SpillExpectation:
    amount: Decimal | None
    currency: str | None
    description: str | None
    diagnostics: tuple[str, ...]
    description_claims: tuple[EvidenceClaim, ...]
    confidence: float = 0.975


def _spill_setup(
    variant: str,
) -> tuple[Row, tuple[Row, ...], TableRegion, _SpillExpectation]:
    continuation_rows: tuple[Row, ...] = ()
    if variant == "left-extension":
        description = _cell(
            "DETAILS",
            1,
            words=(_word("DETAILS", 70.0, 90.0),),
        )
        original = _cell(
            "MERCHANT USD 3.00",
            2,
            bbox=(92.0, 30.0, 140.0, 40.0),
            words=(
                _word("MERCHANT", 92.0, 108.0),
                _word("USD", 110.0, 120.0),
                _word("3.00", 122.0, 138.0),
            ),
        )
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        )
        row = _row(_DATE, description, original, _cell("10.00", 3))
        expectation = _SpillExpectation(
            Decimal("3.00"),
            "USD",
            "DETAILS MERCHANT",
            (),
            (
                EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({1})),
                EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({2})),
            ),
        )
    else:
        conflict = variant == "conflicting-candidates"
        original_words = (
            _word("$", 55.0, 58.0),
            _word("3.00", 59.0, 70.0),
            *((_word("USD", 72.0, 78.0),) if conflict else ()),
            _word("MERCHANT", 80.0, 89.0),
        )
        original = _cell(
            "$3.00 USD MERCHANT" if conflict else "$3.00 MERCHANT",
            1,
            words=original_words,
        )
        description_text = "MERCHANT" if variant == "already-present" else "DETAILS"
        if variant == "replacement":
            description_text = " "
        description_x0 = 125.0 if variant in {"already-present", "bounded-note"} else 91.0
        description = _cell(
            description_text,
            2,
            words=(
                _word(
                    "DETAILS" if variant == "replacement" else description_text,
                    description_x0,
                    138.0,
                ),
            ),
        )
        roles = (
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        )
        row = _row(_DATE, original, description, _cell("10.00", 3))
        spill_atom = 4 if conflict else 3
        description_atom = 5 if conflict else 4
        claims = (
            *(
                ()
                if variant == "replacement"
                else (EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({description_atom})),)
            ),
            *(
                ()
                if conflict
                else (EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset({spill_atom})),)
            ),
        )
        if variant == "bounded-note":
            continuation_rows = (
                _row(
                    _cell(
                        "USD",
                        2,
                        y=41.0,
                        bbox=(105.0, 41.0, 115.0, 51.0),
                        words=(_word("USD", 105.0, 115.0, y=41.0),),
                    ),
                    _cell(
                        "3.00",
                        2,
                        y=41.0,
                        bbox=(118.0, 41.0, 132.0, 51.0),
                        words=(_word("3.00", 118.0, 132.0, y=41.0),),
                    ),
                    diagnostics=(
                        "subordinate_detail_continuation",
                        "bounded_hebrew_note_detail",
                    ),
                ),
            )
        expectation = _SpillExpectation(
            None if conflict else Decimal("3.00"),
            None if conflict else "USD",
            (
                "DETAILS"
                if conflict
                else "MERCHANT"
                if variant in {"already-present", "replacement"}
                else "MERCHANT DETAILS"
            ),
            (
                (
                    "original_amount:invalid_amount_text",
                    "unconsumed_description_boundary_text",
                )
                if conflict
                else ("missing_description_cell",)
                if variant == "replacement"
                else ()
            ),
            claims,
            0.9833333333333333 if continuation_rows else 0.975,
        )
    region = _region(
        roles,
        (row, *continuation_rows),
        headers=("Date", *(role.value for role in roles[1:])),
    )
    return row, continuation_rows, region, expectation


@pytest.mark.parametrize(
    "variant",
    (
        "right-extension",
        "left-extension",
        "replacement",
        "already-present",
        "bounded-note",
        "conflicting-candidates",
    ),
)
def test_description_spill_matrix_preserves_result_direction_and_exact_claims(
    variant: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, continuation_rows, region, expected = _spill_setup(variant)
    captured_claims: list[tuple[EvidenceClaim, ...]] = []
    original_validation = normalize_module.validate_transaction_semantics

    def capture_claims(
        *,
        rows: Sequence[Row],
        region: TableRegion,
        ledger: EvidenceLedger,
        initial_claims: Sequence[EvidenceClaim],
        amount_cell: Cell,
        billing_currency: str,
        original_currency: str | None,
        description: str | None,
        transaction_date: date | None,
        posting_date: date | None,
        conversion_date: date | None,
        year_context: DiscoveredDateYearContext | None,
        date_column_kinds: Mapping[int, DateColumnKind],
        accepted_conversion_date_atom_ids: frozenset[int],
    ) -> SemanticValidation:
        captured_claims.append(tuple(initial_claims))
        return original_validation(
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
            date_column_kinds=date_column_kinds,
            accepted_conversion_date_atom_ids=accepted_conversion_date_atom_ids,
        )

    monkeypatch.setattr(normalize_module, "validate_transaction_semantics", capture_claims)
    attempt = _normalize_row(
        row=row,
        continuation_rows=continuation_rows,
        region=region,
        group=_group(region),
        year_context=None,
        date_column_kinds={},
        transaction_id="matrix-tx",
    )

    assert attempt.result == _expected_result(
        row=row,
        continuation_rows=continuation_rows,
        billed_amount=Decimal("10.00"),
        diagnostics=expected.diagnostics,
        description=expected.description,
        original_amount=expected.amount,
        original_currency=expected.currency,
        confidence=expected.confidence,
    )
    assert (
        tuple(claim for claim in captured_claims[0] if claim.owner is SemanticOwner.DESCRIPTION)
        == expected.description_claims
    )


def _direct_cardinality_case(
    variant: str,
) -> tuple[Row, TableRegion, BilledFields, tuple[str, ...]]:
    if variant == "duplicate-original-amount-columns":
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        )
        billed_cell = _cell("10.00", 4)
        row = _row(
            _DATE,
            _DESCRIPTION,
            _cell("USD 3.00", 2),
            _cell("EUR 4.00", 3),
            billed_cell,
        )
        billed_amount = Decimal("10.00")
        diagnostics = ("multiple_original_amount_columns",)
    elif variant == "duplicate-original-currency-columns":
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        )
        billed_cell = _cell("10.00", 5)
        row = _row(
            _DATE,
            _DESCRIPTION,
            _cell("3.00", 2),
            _cell("USD", 3),
            _cell("EUR", 4),
            billed_cell,
        )
        billed_amount = Decimal("10.00")
        diagnostics = (
            "multiple_original_currency_columns",
            "original_amount:unknown_currency",
        )
    elif variant == "missing-original-currency-cell":
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        )
        billed_cell = _cell("10.00", 4)
        row = _row(_DATE, _DESCRIPTION, _cell("3.00", 2), billed_cell)
        billed_amount = Decimal("10.00")
        diagnostics = (
            "missing_original_currency_cell",
            "original_amount:unknown_currency",
        )
    elif variant == "multiple-original-currency-cells":
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        )
        billed_cell = _cell("10.00", 4)
        row = _row(
            _DATE,
            _DESCRIPTION,
            _cell("3.00", 2),
            _cell("USD", 3),
            _cell("EUR", 3),
            billed_cell,
        )
        billed_amount = Decimal("10.00")
        diagnostics = (
            "multiple_original_currency_cells",
            "original_amount:unknown_currency",
        )
    else:
        assert variant == "negative-adjustment-with-original-currency-column"
        roles = (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        )
        billed_cell = _cell("-2.00", 4)
        row = _row(_DATE, _DESCRIPTION, _cell("USD", 3), billed_cell)
        billed_amount = Decimal("-2.00")
        diagnostics = ("missing_original_amount_cell",)
    region = _region(roles, (row,))
    billed = BilledFields(
        amount=billed_amount,
        currency="ILS",
        amount_cell=billed_cell,
        confidence=0.95,
        diagnostics=(),
        disposition=FieldDisposition.ACCEPT,
    )
    return row, region, billed, diagnostics


@pytest.mark.parametrize(
    "variant",
    (
        "duplicate-original-amount-columns",
        "duplicate-original-currency-columns",
        "missing-original-currency-cell",
        "multiple-original-currency-cells",
        "negative-adjustment-with-original-currency-column",
    ),
)
def test_extract_original_amount_cardinality_contract_is_complete(variant: str) -> None:
    row, region, billed, diagnostics = _direct_cardinality_case(variant)

    extraction = extract_original_amount(
        row=row,
        continuation_rows=(),
        region=region,
        ledger=EvidenceLedger.from_rows((row,)),
        billed=billed,
        description="Existing description",
        initial_claims=(),
    )

    assert extraction == OriginalAmountExtraction(
        amount=None,
        currency=None,
        description="Existing description",
        claims=(),
        diagnostics=diagnostics,
    )


def test_original_amount_extraction_is_immutable_and_slotted() -> None:
    extraction = OriginalAmountExtraction(
        amount=None,
        currency=None,
        description=None,
        claims=(),
        diagnostics=(),
    )

    assert tuple(OriginalAmountExtraction.__slots__) == (
        "amount",
        "currency",
        "description",
        "claims",
        "diagnostics",
    )
    with pytest.raises(FrozenInstanceError):
        extraction.amount = Decimal("1.00")


@pytest.mark.parametrize(
    "variant",
    (
        "right-extension",
        "left-extension",
        "replacement",
        "already-present",
        "bounded-note",
        "conflicting-candidates",
    ),
)
def test_extract_original_amount_returns_only_new_ordered_spill_claims(
    variant: str,
) -> None:
    row, continuation_rows, region, expected = _spill_setup(variant)
    rows = (row, *continuation_rows)
    ledger = EvidenceLedger.from_rows(rows)
    billed = extract_billed_fields(row=row, region=region, printed_currency="ILS")
    assert billed.disposition is FieldDisposition.ACCEPT
    base_description = (
        None
        if variant == "replacement"
        else ("MERCHANT" if variant == "already-present" else "DETAILS")
    )
    initial_claims = () if variant == "replacement" else expected.description_claims[:1]
    new_claims = () if variant == "conflicting-candidates" else (expected.description_claims[-1],)

    extraction = extract_original_amount(
        row=row,
        continuation_rows=continuation_rows,
        region=region,
        ledger=ledger,
        billed=billed,
        description=base_description,
        initial_claims=initial_claims,
    )

    assert extraction == OriginalAmountExtraction(
        amount=expected.amount,
        currency=expected.currency,
        description=expected.description,
        claims=new_claims,
        diagnostics=(
            ("original_amount:invalid_amount_text",) if variant == "conflicting-candidates" else ()
        ),
    )
