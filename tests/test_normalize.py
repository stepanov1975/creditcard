from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ccparser.discovery import (
    DateTokenStyle,
    DiscoveredDateYearContext,
    DiscoveredPrintedTotal,
    DocumentClassification,
    StatementDiscovery,
    StatementGroupDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, ExtractionQuality, PageEvidence, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import EvidenceReference, Status, TransactionCategory, TransactionKind
from ccparser.normalize import normalize_statement, parse_amount


def _cell(text: str, column: int, y: float, *, page: int = 1) -> Cell:
    x0 = float(column * 50)
    return Cell(
        page_number=page,
        bbox=(x0, y, x0 + 40.0, y + 10.0),
        text=text,
        confidence=1.0,
    )


def _word(
    text: str,
    x0: float,
    x1: float,
    y: float,
    *,
    source: str = "digital",
    confidence: float = 1.0,
) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source=source,
        confidence=confidence,
    )


def _row(*cells: Cell) -> Row:
    return Row(
        page_number=cells[0].page_number,
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


def _discovery(
    region: TableRegion,
    total: str,
    currency: str,
    *,
    year_context: int | None = None,
    year_context_style: DateTokenStyle = DateTokenStyle.DAY_FIRST_SLASH,
) -> StatementDiscovery:
    total_evidence = EvidenceReference(
        page_number=1,
        bbox=(100.0, 210.0, 140.0, 220.0),
        raw_text=total,
    )
    discovered_total = DiscoveredPrintedTotal(
        amount_text=total,
        currency=currency,
        label_evidence=EvidenceReference(
            page_number=1,
            bbox=(50.0, 210.0, 90.0, 220.0),
            raw_text="Total",
        ),
        value_evidence=total_evidence,
        confidence=1.0,
    )
    group = StatementGroupDiscovery(
        group_id="group-0001",
        table_regions=(region,),
        printed_total=discovered_total,
        confidence=1.0,
    )
    return StatementDiscovery(
        classification=DocumentClassification.STATEMENT,
        groups=(group,),
        table_regions=(region,),
        date_year_context=(
            DiscoveredDateYearContext(
                year=year_context,
                style=year_context_style,
                evidence=(
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 230.0, 80.0, 240.0),
                        raw_text=f"Statement date 15/01/{year_context}",
                    ),
                ),
                confidence=1.0,
            )
            if year_context is not None
            else None
        ),
        confidence=1.0,
        reason_codes=("transaction_table_with_compatible_total",),
    )


@pytest.mark.parametrize(
    ("raw", "hint", "expected", "currency"),
    (
        ("$1,234.56", None, Decimal("1234.56"), "USD"),
        ("1.234,56 EUR", None, Decimal("1234.56"), "EUR"),
        ("₪ 1 234,56-", None, Decimal("-1234.56"), "ILS"),
        ("(£2,50)", None, Decimal("-2.50"), "GBP"),
        ("100.00 credit", "USD", Decimal("-100.00"), "USD"),
        ("100.00 זיכוי", "ILS", Decimal("-100.00"), "ILS"),
        ("10.00 ש״ח", None, Decimal("10.00"), "ILS"),
        ("{10.00", None, Decimal("10.00"), "ILS"),
    ),
)
def test_parse_amount_supports_structurally_unambiguous_formats_and_credit_markers(
    raw: str,
    hint: str | None,
    expected: Decimal,
    currency: str,
) -> None:
    result = parse_amount(raw, currency_hint=hint)

    assert result.amount == expected
    assert result.currency == currency
    assert result.diagnostics == ()
    assert result.confidence >= 0.9


@pytest.mark.parametrize(
    ("raw", "hint", "reason"),
    (
        ("1,234", "ILS", "ambiguous_decimal_separator"),
        ("10.00 USD EUR", None, "conflicting_currency"),
        ("-10.00 charge", "ILS", "conflicting_sign_marker"),
        ("12 apples", "ILS", "invalid_amount_text"),
        ("10.00 USD", "EUR", "currency_hint_conflict"),
        ("--10.00", "ILS", "invalid_sign_syntax"),
        ("-+10.00", "ILS", "invalid_sign_syntax"),
        ("10.00--", "ILS", "invalid_sign_syntax"),
        ("1-0.00", "ILS", "invalid_sign_syntax"),
        ("10.00 trailing text", "ILS", "invalid_amount_text"),
    ),
)
def test_parse_amount_rejects_ambiguous_sign_separator_currency_or_text(
    raw: str,
    hint: str | None,
    reason: str,
) -> None:
    result = parse_amount(raw, currency_hint=hint)

    assert result.amount is None
    assert reason in result.diagnostics


@pytest.mark.parametrize("raw", ("-10.00", "10.00-", "(10.00)"))
def test_parse_amount_preserves_each_single_negative_sign_form(raw: str) -> None:
    result = parse_amount(raw, currency_hint="ILS")

    assert result.amount == Decimal("-10.00")
    assert result.diagnostics == ()


def test_normalize_statement_emits_authoritative_purchase_and_refund_and_reconciles() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(_cell("01/02/2026", 0, 30.0), _cell("Market", 1, 30.0), _cell("10.00", 2, 30.0)),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Customer refund", 1, 50.0),
                _cell("5.00 credit", 2, 50.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "5.00", "ILS"))

    assert tuple(transaction.transaction_id for transaction in result.transactions) == (
        "group-0001-p001-r0001",
        "group-0001-p001-r0002",
    )
    purchase, refund = result.transactions
    assert purchase.kind is TransactionKind.CHARGE
    assert purchase.category is TransactionCategory.UNKNOWN
    assert purchase.billed_amount == Decimal("10.00")
    assert purchase.transaction_date == date(2026, 2, 1)
    assert refund.kind is TransactionKind.CREDIT
    assert refund.category is TransactionCategory.REFUND
    assert refund.billed_amount == Decimal("-5.00")
    assert all(transaction.billing_currency == "ILS" for transaction in result.transactions)
    assert result.reconciliation.status is Status.RECONCILED
    assert result.reconciliation.groups[0].difference == Decimal("0.00")


def test_normalize_statement_parses_date_with_one_standalone_letter() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026 ל", 0, 30.0),
                _cell("Market", 1, 30.0),
                _cell("10.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions[0].transaction_date == date(2026, 2, 1)
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_preserves_foreign_installment_and_wrapped_description() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
        ColumnRole.INSTALLMENT,
    )
    region = _region(
        roles,
        (
            _row(
                _cell("2026-02-01", 0, 30.0),
                _cell("Monthly", 1, 30.0),
                _cell("USD 3.00", 2, 30.0),
                _cell("ILS 11.00", 3, 30.0),
                _cell("2/6", 4, 30.0),
            ),
            _row(_cell("installment plan", 1, 41.0)),
        ),
    )

    result = normalize_statement(_discovery(region, "ILS 11.00", "ILS"))

    assert len(result.transactions) == 1
    transaction = result.transactions[0]
    assert transaction.description == "Monthly installment plan"
    assert transaction.category is TransactionCategory.INSTALLMENT
    assert transaction.original_amount == Decimal("3.00")
    assert transaction.original_currency == "USD"
    assert (transaction.installment_current, transaction.installment_total) == (2, 6)
    assert len(transaction.evidence) == 6
    assert result.row_results[1].diagnostics == ("merged_description_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_recovers_money_before_geometrically_adjacent_description_spill() -> (
    None
):
    original_cell = _cell("$3.00MERCHANT", 1, 30.0).model_copy(
        update={
            "words": (
                _word("$", 55.0, 58.0, 30.0),
                _word("3.00", 59.0, 70.0, 30.0),
                _word("MERCHANT", 80.0, 89.0, 30.0),
            )
        }
    )
    description_cell = _cell("DETAILS", 2, 30.0).model_copy(
        update={"words": (_word("DETAILS", 91.0, 110.0, 30.0),)}
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                original_cell,
                description_cell,
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount == Decimal("3.00")
    assert transaction.original_currency == "USD"
    assert transaction.description == "MERCHANT DETAILS"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("raw", "amount_word", "currency_word"),
    (
        ("-2.56$ MERCHANT", "-2.56", "$"),
        ("-28.22GBP MERCHANT", "-28.22", "GBP"),
    ),
)
def test_normalize_statement_rejects_prefix_only_original_money_word_subset(
    raw: str,
    amount_word: str,
    currency_word: str,
) -> None:
    original_cell = _cell(raw, 1, 30.0).model_copy(
        update={
            "words": (
                _word(amount_word, 52.0, 65.0, 30.0),
                _word(currency_word, 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0),
            )
        }
    )
    description_cell = _cell("MERCHANT DETAILS", 2, 30.0).model_copy(
        update={"words": (_word("MERCHANT DETAILS", 102.0, 138.0, 30.0),)}
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                original_cell,
                description_cell,
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    first = normalize_statement(_discovery(region, "10.00", "ILS"))
    second = normalize_statement(_discovery(region, "10.00", "ILS"))

    transaction = first.transactions[0]
    assert transaction.original_amount is None
    assert transaction.original_currency is None
    assert transaction.description == "MERCHANT DETAILS"
    assert "original_amount:invalid_amount_text" in transaction.ambiguities
    assert first.reconciliation.status is Status.UNRECONCILED
    assert first == second


@pytest.mark.parametrize(
    ("original_words", "description_words"),
    (
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 80.0, 30.0),
                _word("MERCHANT", 82.0, 88.0, 30.0),
            ),
            (_word("MERCHANT", 102.0, 138.0, 30.0),),
        ),
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT.", 74.0, 88.0, 30.0),
            ),
            (_word("MERCHANT DETAILS", 102.0, 138.0, 30.0),),
        ),
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0),
            ),
            (_word("MERCHANT DETAILS", 102.0, 138.0, 30.0),),
        ),
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 80.0, 30.0),
                _word("DETAILS", 82.0, 88.0, 30.0),
            ),
            (
                _word("DETAILS", 102.0, 110.0, 30.0),
                _word("MERCHANT", 112.0, 126.0, 30.0),
            ),
        ),
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0),
            ),
            (_word("MERCHANT", 74.0, 88.0, 30.0),),
        ),
        (
            (
                _word("-2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0, confidence=0.9),
            ),
            (_word("MERCHANT", 74.0, 88.0, 30.0),),
        ),
    ),
)
def test_original_money_subset_rejects_nonidentical_or_overlapping_residual_provenance(
    original_words: tuple[Word, ...],
    description_words: tuple[Word, ...],
) -> None:
    original_text = " ".join(word.text for word in original_words)
    description_text = " ".join(word.text for word in description_words)
    original_cell = _cell(original_text, 1, 30.0).model_copy(update={"words": original_words})
    description_cell = _cell(description_text, 2, 30.0).model_copy(
        update={"words": description_words}
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                original_cell,
                description_cell,
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount is None
    assert transaction.original_currency is None
    assert "original_amount:invalid_amount_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize(
    ("raw", "word_specs", "description"),
    (
        ("-2.56$ MERCHANT", (), "MERCHANT DETAILS"),
        (
            "-2.56GB MERCHANT",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("GB", 66.0, 70.0, "digital"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "-2.56$ 3.00 MERCHANT",
            (
                ("-2.56", 52.0, 60.0, "digital"),
                ("$", 61.0, 64.0, "digital"),
                ("3.00", 65.0, 72.0, "digital"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "-2.56$ MERCHANT",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "ocr"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "-2.56$ HIDDEN",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("HIDDEN", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "-2.56$ AM",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("AM", 74.0, 88.0, "digital"),
            ),
            "AMZN DETAILS",
        ),
        (
            "-2.56$ CHANT",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("CHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "-2.56$ STORE24",
            (
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("STORE24", 74.0, 88.0, "digital"),
            ),
            "STORE24 DETAILS",
        ),
        (
            "MERCHANT -2.56$",
            (
                ("MERCHANT", 42.0, 49.0, "digital"),
                ("-2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "--2.56$ MERCHANT",
            (
                ("--2.56", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "1,234$ MERCHANT",
            (
                ("1,234", 52.0, 65.0, "digital"),
                ("$", 66.0, 70.0, "digital"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
        (
            "2.56$ GBP MERCHANT",
            (
                ("2.56", 52.0, 60.0, "digital"),
                ("$", 61.0, 64.0, "digital"),
                ("GBP", 65.0, 72.0, "digital"),
                ("MERCHANT", 74.0, 88.0, "digital"),
            ),
            "MERCHANT DETAILS",
        ),
    ),
)
def test_normalize_statement_rejects_unsafe_original_money_word_subset(
    raw: str,
    word_specs: tuple[tuple[str, float, float, str], ...],
    description: str,
) -> None:
    original_cell = _cell(raw, 1, 30.0).model_copy(
        update={
            "words": tuple(
                _word(text, x0, x1, 30.0, source=source) for text, x0, x1, source in word_specs
            )
        }
    )
    description_cell = _cell(description, 2, 30.0).model_copy(
        update={"words": (_word(description, 102.0, 138.0, 30.0),)}
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                original_cell,
                description_cell,
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount is None
    assert transaction.original_currency is None
    assert "original_amount:invalid_amount_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize("duplicated_role", (ColumnRole.ORIGINAL_AMOUNT, ColumnRole.DESCRIPTION))
def test_original_money_word_subset_requires_unique_semantic_columns(
    duplicated_role: ColumnRole,
) -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.ORIGINAL_AMOUNT,
        duplicated_role,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
    )
    original_cell = _cell("2.56$ MERCHANT", 1, 30.0).model_copy(
        update={
            "words": (
                _word("2.56", 52.0, 65.0, 30.0),
                _word("$", 66.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0),
            )
        }
    )
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                original_cell,
                _cell("OTHER", 2, 30.0),
                _cell("MERCHANT DETAILS", 3, 30.0),
                _cell("10.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert (
        f"unsupported_role_cardinality:{duplicated_role.value}" in result.row_results[0].diagnostics
    )


def test_normalize_statement_merges_proven_multicell_subordinate_detail_rows() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.UNKNOWN,
        ColumnRole.EXCHANGE_RATE,
        ColumnRole.AMOUNT,
    )
    first_detail = _row(
        _cell("Fee detail", 1, 41.0),
        _cell("Exchange rate", 2, 41.0),
    ).model_copy(update={"diagnostics": ("subordinate_detail_continuation",)})
    second_detail = _row(
        _cell("עמלה", 1, 71.0),
        _cell("שער המרה", 2, 71.0),
    ).model_copy(update={"diagnostics": ("subordinate_detail_continuation",)})
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Market", 1, 30.0),
                _cell("3.72", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            first_detail,
            _row(
                _cell("02/02/2026", 0, 60.0),
                _cell("Cafe", 1, 60.0),
                _cell("3.74", 2, 60.0),
                _cell("20.00", 3, 60.0),
            ),
            second_detail,
        ),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert len(result.transactions) == 2
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert result.row_results[1].diagnostics == ("merged_subordinate_detail_continuation",)
    assert result.row_results[3].diagnostics == ("merged_subordinate_detail_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_merges_consecutive_subordinate_detail_block() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    details = tuple(
        _row(_cell(first, 1, y), _cell(second, 2, y)).model_copy(
            update={"diagnostics": ("subordinate_detail_continuation",)}
        )
        for y, first, second in (
            (41.0, "converted at issuer rate", "conversion note"),
            (52.0, "Fee", "discount applied"),
            (63.0, "special", "arrangement"),
        )
    )
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Foreign shop", 1, 30.0),
                _cell("$3.00", 2, 30.0),
                _cell("₪11.00", 3, 30.0),
            ),
            *details,
            _row(
                _cell("02/02/2026", 0, 74.0),
                _cell("Cafe", 1, 74.0),
                _cell("₪20.00", 2, 74.0),
                _cell("₪20.00", 3, 74.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "31.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "Foreign shop",
        "Cafe",
    )
    assert all(
        result.row_results[index].diagnostics == ("merged_subordinate_detail_continuation",)
        for index in (1, 2, 3)
    )
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_merges_auxiliary_fragment_without_changing_description() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.UNKNOWN,
        ColumnRole.AMOUNT,
    )
    auxiliary = _row(_cell("continued", 2, 41.0)).model_copy(
        update={"diagnostics": ("subordinate_auxiliary_continuation",)}
    )
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Hotel", 1, 30.0),
                _cell("Travel", 2, 30.0),
                _cell("₪20.00", 3, 30.0),
            ),
            auxiliary,
            _row(
                _cell("02/02/2026", 0, 52.0),
                _cell("Cafe", 1, 52.0),
                _cell("Food", 2, 52.0),
                _cell("₪10.00", 3, 52.0),
            ),
        ),
        headers=("Date", "Description", "Detail", "Amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "Hotel",
        "Cafe",
    )
    assert result.row_results[1].diagnostics == ("merged_auxiliary_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_merges_nonmoney_detail_in_empty_secondary_amount_band() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
        ColumnRole.AMOUNT,
        ColumnRole.ORIGINAL_AMOUNT,
    )
    detail = _row(
        _cell("Fee detail", 1, 41.0),
        _cell("Conversion note", 3, 41.0),
    ).model_copy(update={"diagnostics": ("subordinate_detail_continuation",)})
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Market", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("USD 3.00", 4, 30.0),
            ),
            detail,
        ),
        headers=("Date", "Description", "Billed amount", "Amount", "Original amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    transaction = result.transactions[0]
    assert transaction.description == "Market"
    assert transaction.category is TransactionCategory.UNKNOWN
    assert tuple(reference.raw_text for reference in transaction.evidence) == (
        "01/02/2026",
        "Market",
        "10.00",
        "USD 3.00",
        "Fee detail",
        "Conversion note",
    )
    assert tuple(reference.raw_text for reference in result.row_results[1].evidence) == (
        "Fee detail",
        "Conversion note",
    )
    assert result.row_results[1].diagnostics == ("merged_subordinate_detail_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_ignores_marked_detail_money_when_proving_billed_column() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
        ColumnRole.AMOUNT,
        ColumnRole.ORIGINAL_AMOUNT,
    )
    detail = _row(
        _cell("Fee", 1, 41.0),
        _cell("0.50", 3, 41.0),
    ).model_copy(update={"diagnostics": ("subordinate_detail_continuation",)})
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Market", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("USD 3.00", 4, 30.0),
            ),
            detail,
            _row(
                _cell("02/02/2026", 0, 52.0),
                _cell("Cafe", 1, 52.0),
                _cell("20.00", 2, 52.0),
                _cell("USD 6.00", 4, 52.0),
            ),
        ),
        headers=("Date", "Description", "Billed amount", "Amount", "Original amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert tuple(transaction.billed_amount for transaction in result.transactions) == (
        Decimal("10.00"),
        Decimal("20.00"),
    )
    assert result.row_results[1].diagnostics == ("merged_subordinate_detail_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("description", "expected"),
    (
        ("Regular merchant", TransactionCategory.UNKNOWN),
        ("Purchase at merchant", TransactionCategory.PURCHASE),
        ("Service fee", TransactionCategory.FEE),
        ("ריבית חודשית", TransactionCategory.INTEREST),
        ("Account adjustment", TransactionCategory.ADJUSTMENT),
        ("החזר", TransactionCategory.REFUND),
    ),
)
def test_normalize_statement_uses_general_category_vocabulary(
    description: str,
    expected: TransactionCategory,
) -> None:
    amount = "1.00 credit" if expected is TransactionCategory.REFUND else "1.00"
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(_cell("01/02/2026", 0, 30.0), _cell(description, 1, 30.0), _cell(amount, 2, 30.0)),),
    )
    total = "-1.00" if expected is TransactionCategory.REFUND else "1.00"

    result = normalize_statement(_discovery(region, total, "ILS"))

    assert result.transactions[0].category is expected


def test_normalize_statement_keeps_critical_and_noncritical_row_ambiguities_explicit() -> None:
    roles = (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT)
    region = _region(
        roles,
        (
            _row(
                _cell("31/02/2026", 0, 30.0),
                _cell("Invalid date", 1, 30.0),
                _cell("2.00", 2, 30.0),
            ),
            _row(
                _cell("01/02/2026", 0, 50.0),
                _cell("Duplicate amount", 1, 50.0),
                _cell("1.00", 2, 50.0),
                Cell(
                    page_number=1,
                    bbox=(102.0, 50.0, 138.0, 60.0),
                    text="3.00",
                    confidence=1.0,
                ),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "2.00", "ILS"))

    assert len(result.transactions) == 1
    assert "invalid_transaction_date" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED
    assert result.row_results[1].transaction is None
    assert "multiple_amount_cells" in result.row_results[1].diagnostics
    assert "rows_not_emitted:1" in result.diagnostics


def test_normalize_statement_does_not_choose_between_generic_amount_columns() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
                _cell("16.00", 3, 30.0),
                _cell("USD 5.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    assert result.transactions == ()
    assert result.row_results[0].transaction is None
    assert "unsupported_role_cardinality:amount" in result.row_results[0].diagnostics
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_uses_explicit_billed_column_when_secondary_is_empty() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.AMOUNT,
        ColumnRole.AMOUNT,
        ColumnRole.ORIGINAL_AMOUNT,
    )
    region = _region(
        roles,
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
                _cell("USD 5.00", 4, 30.0),
            ),
        ),
        headers=("Date", "Description", "Billed amount", "Amount", "Original amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].billed_amount == Decimal("4.00")
    assert result.row_results[0].transaction is not None
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_distinguishes_labeled_transaction_and_posting_dates() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("03/02/2026", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("Transaction date", "Posting date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.posting_date == date(2026, 2, 3)
    assert transaction.conversion_date is None
    assert transaction.ambiguities == ()


def test_normalize_statement_distinguishes_hebrew_purchase_and_billing_dates() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("03/02/2026", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("תאריך רכישה", "תאריך חיוב", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.posting_date == date(2026, 2, 3)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_completes_one_generic_date_from_labeled_posting_date() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("03/02/2026", 0, 30.0),
                _cell("01/02/2026", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("Posting date", "Date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.posting_date == date(2026, 2, 3)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_preserves_conversion_date_as_ancillary_evidence() -> None:
    region = _region(
        (
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("03/02/26", 0, 30.0),
                _cell("01/02/26", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("תאריךהמרה", "תאריך", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.conversion_date == date(2026, 2, 3)
    assert transaction.posting_date is None
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_uses_proven_year_for_each_short_date_suffix() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("31/12/25", 0, 30.0),
                _cell("First", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
            _row(
                _cell("01/01/26", 0, 50.0),
                _cell("Second", 1, 50.0),
                _cell("4.00", 2, 50.0),
            ),
        ),
    )
    discovery = _discovery(region, "8.00", "ILS").model_copy(
        update={
            "date_year_context": DiscoveredDateYearContext(
                year=None,
                year_by_suffix=((25, 2025), (26, 2026)),
                style=DateTokenStyle.DAY_FIRST_SLASH,
                evidence=(
                    EvidenceReference(
                        page_number=1,
                        bbox=(0.0, 230.0, 80.0, 240.0),
                        raw_text="31/12/2025",
                    ),
                    EvidenceReference(
                        page_number=1,
                        bbox=(80.0, 230.0, 160.0, 240.0),
                        raw_text="01/01/2026",
                    ),
                ),
                confidence=1.0,
            )
        }
    )

    result = normalize_statement(discovery)

    assert tuple(transaction.transaction_date for transaction in result.transactions) == (
        date(2025, 12, 31),
        date(2026, 1, 1),
    )
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_extracts_one_context_matched_short_date_token_from_compound_cell() -> (
    None
):
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("17 01/02/26", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.ambiguities == ()
    assert transaction.evidence[0].raw_text == "17 01/02/26"


def test_normalize_statement_falls_back_to_positioned_words_for_invalid_glyph_date() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text="01/02/266",
        words=(
            _word("01/02/26", 0.0, 28.0, 30.0),
            _word("6", 30.0, 34.0, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                date_cell,
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.ambiguities == ()
    assert transaction.evidence[0].raw_text == "01/02/266"


def test_normalize_statement_recovers_date_from_overlapping_boundary_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        words=(_word("MERCHANT01/02/2026", 0.0, 100.0, 30.0),),
        confidence=1.0,
    )
    damaged_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 0/1 2/2 0 2 6",
        confidence=1.0,
    )
    amount = Cell(
        page_number=1,
        bbox=(120.0, 30.0, 160.0, 40.0),
        text="4.00",
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(compound, damaged_date, amount),),
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

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_rejects_date_from_barely_overlapping_boundary_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 62.0, 40.0),
        text="MERCHANT01/02/2026",
        words=(_word("MERCHANT01/02/2026", 0.0, 62.0, 30.0),),
        confidence=1.0,
    )
    damaged_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 0/1 2/2 0 2 6",
        confidence=1.0,
    )
    amount = Cell(
        page_number=1,
        bbox=(120.0, 30.0, 160.0, 40.0),
        text="4.00",
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(compound, damaged_date, amount),),
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

    transaction = normalize_statement(_discovery(region, "4.00", "ILS")).transactions[0]

    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities


def test_normalize_statement_extracts_unique_full_date_at_alphabetic_cell_boundary() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("MERCHANT01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.ambiguities == ()
    assert transaction.evidence[0].raw_text == "MERCHANT01/02/2026"


def test_normalize_statement_rejects_compound_short_and_full_date_tokens() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/26 03/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "transaction_date:ambiguous_date_tokens" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_keeps_tied_generic_compound_date_roles_ambiguous() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("17 01/02/26", 0, 30.0),
                _cell("03/02/26 א", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert transaction.posting_date is None
    assert "unresolved_date_column_roles" in transaction.ambiguities


def test_normalize_statement_proves_complete_transaction_and_optional_later_posting_dates() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("03/02/26 א", 0, 30.0),
                _cell("01/02/26 ב", 1, 30.0),
                _cell("First", 2, 30.0),
                _cell("2.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/26 ג", 1, 50.0),
                _cell("Second", 2, 50.0),
                _cell("2.00", 3, 50.0),
            ),
            _row(
                _cell("06/02/26 ד", 0, 70.0),
                _cell("04/02/26 ה", 1, 70.0),
                _cell("Third", 2, 70.0),
                _cell("2.00", 3, 70.0),
            ),
        ),
        headers=("Date", "Date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "6.00", "ILS", year_context=2026))

    assert tuple(transaction.transaction_date for transaction in result.transactions) == (
        date(2026, 2, 1),
        date(2026, 2, 2),
        date(2026, 2, 4),
    )
    assert tuple(transaction.posting_date for transaction in result.transactions) == (
        date(2026, 2, 3),
        None,
        date(2026, 2, 6),
    )
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert all(row.transaction is not None for row in result.row_results)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_proves_consistently_earlier_generic_transaction_dates() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("03/02/26", 0, 30.0),
                _cell("01/02/26", 1, 30.0),
                _cell("First", 2, 30.0),
                _cell("2.00", 3, 30.0),
            ),
            _row(
                _cell("04/02/26", 0, 50.0),
                _cell("04/02/26", 1, 50.0),
                _cell("Second", 2, 50.0),
                _cell("2.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    assert tuple(transaction.transaction_date for transaction in result.transactions) == (
        date(2026, 2, 1),
        date(2026, 2, 4),
    )
    assert tuple(transaction.posting_date for transaction in result.transactions) == (
        date(2026, 2, 3),
        date(2026, 2, 4),
    )
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_does_not_infer_generic_date_roles_when_ordering_conflicts() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("03/02/26", 0, 30.0),
                _cell("01/02/26", 1, 30.0),
                _cell("First", 2, 30.0),
                _cell("2.00", 3, 30.0),
            ),
            _row(
                _cell("04/02/26", 0, 50.0),
                _cell("06/02/26", 1, 50.0),
                _cell("Second", 2, 50.0),
                _cell("2.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Date", "Description", "Amount"),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    assert len(result.transactions) == 2
    assert all(
        "unresolved_date_column_roles" in transaction.ambiguities
        for transaction in result.transactions
    )
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_rejects_short_date_when_context_year_suffix_differs() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("17 01/02/25", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "transaction_date:date_year_context_mismatch" in transaction.ambiguities


def test_normalize_statement_marks_reconciliation_unreconciled_when_a_row_is_not_emitted() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Clean", 1, 30.0),
                _cell("2.00", 2, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Ambiguous", 1, 50.0),
                _cell("1.00", 2, 50.0),
                Cell(
                    page_number=1,
                    bbox=(102.0, 50.0, 138.0, 60.0),
                    text="3.00",
                    confidence=1.0,
                ),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "2.00", "ILS"))

    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED
    assert "rows_not_emitted:1" in result.reconciliation.diagnostics


def test_unknown_band_with_second_money_cell_blocks_emission_and_reconciliation() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("99.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "unresolved_relevant_cell" in result.row_results[0].diagnostics
    assert result.reconciliation.status is Status.UNRECONCILED


def test_unknown_text_band_is_retained_as_evidence_without_financial_ambiguity() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("Retail category", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].ambiguities == ()
    assert len(result.transactions[0].evidence) == 4
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize("header", ("City", "Location", "עיר"))
def test_location_text_and_plain_identifier_are_preserved_as_evidence(
    header: str,
) -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("First merchant", 1, 30.0),
                _cell("London", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Second merchant", 1, 50.0),
                _cell("1234567890", 2, 50.0),
                _cell("20.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Description", header, "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "First merchant",
        "Second merchant",
    )
    assert tuple(transaction.evidence[2].raw_text for transaction in result.transactions) == (
        "London",
        "1234567890",
    )
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    "value",
    (
        "99.00",
        "1,234.56",
        "-99.00",
        "₪99.00",
        "-1234567890",
        "1,234,567,890",
        "₪1234567890",
        "01/02/2026",
        "1/3",
    ),
)
def test_location_band_rejects_financial_date_and_installment_shapes(value: str) -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell(value, 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", "City", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "unresolved_relevant_cell" in result.row_results[0].diagnostics
    assert result.reconciliation.status is Status.UNRECONCILED


def test_plain_identifier_in_unknown_header_remains_fatal() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("1234567890", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", "Reference", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "unresolved_relevant_cell" in result.row_results[0].diagnostics


def test_location_identifier_does_not_override_missing_billed_cell() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("1234567890", 2, 30.0),
            ),
        ),
        headers=("Date", "Description", "City", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "missing_amount_cell" in result.row_results[0].diagnostics


def test_location_identifier_does_not_override_multiple_billed_cells() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("1234567890", 2, 30.0),
                _cell("10.00", 3, 30.0),
                _cell("11.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", "City", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "multiple_amount_cells" in result.row_results[0].diagnostics


def test_location_identifier_does_not_override_alignment_conflict() -> None:
    unmatched_identifier = Cell(
        page_number=1,
        bbox=(195.0, 30.0, 215.0, 40.0),
        text="1234567890",
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("London", 2, 30.0),
                _cell("10.00", 3, 30.0),
                unmatched_identifier,
            ),
        ),
        headers=("Date", "Description", "City", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "unmatched_cell" in result.row_results[0].diagnostics
    assert "unresolved_relevant_cell" in result.row_results[0].diagnostics


def test_repeated_equal_original_values_inherit_proven_billing_currency() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("First", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Second", 1, 50.0),
                _cell("20.00", 2, 50.0),
                _cell("20.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert tuple(transaction.original_amount for transaction in result.transactions) == (
        Decimal("10.00"),
        Decimal("20.00"),
    )
    assert all(transaction.original_currency == "ILS" for transaction in result.transactions)
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert result.reconciliation.status is Status.RECONCILED


def test_unsigned_original_credit_values_inherit_proven_billing_currency() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Purchase", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Credit", 1, 50.0),
                _cell("20.00", 2, 50.0),
                _cell("-20.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "-10.00", "ILS"))

    assert tuple(transaction.original_amount for transaction in result.transactions) == (
        Decimal("10.00"),
        Decimal("20.00"),
    )
    assert all(transaction.original_currency == "ILS" for transaction in result.transactions)
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert result.reconciliation.status is Status.RECONCILED


def test_one_malformed_original_value_does_not_hide_repeated_currency_proof() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("First", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Malformed", 1, 50.0),
                _cell("1,23.45", 2, 50.0),
                _cell("123.45", 3, 50.0),
            ),
            _row(
                _cell("03/02/2026", 0, 70.0),
                _cell("Third", 1, 70.0),
                _cell("20.00", 2, 70.0),
                _cell("20.00", 3, 70.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "153.45", "ILS"))

    assert result.transactions[0].original_currency == "ILS"
    assert result.transactions[2].original_currency == "ILS"
    assert "original_amount:unknown_currency" not in result.transactions[1].ambiguities
    assert "original_amount:invalid_grouping_separator" in result.transactions[1].ambiguities


def test_mixed_original_values_do_not_inherit_billing_currency() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Equal", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Different", 1, 50.0),
                _cell("3.00", 2, 50.0),
                _cell("20.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert all(transaction.original_amount is None for transaction in result.transactions)
    assert all(transaction.original_currency is None for transaction in result.transactions)
    assert all(
        "original_amount:unknown_currency" in transaction.ambiguities
        for transaction in result.transactions
    )
    assert result.reconciliation.status is Status.UNRECONCILED


def test_distinct_original_and_billing_currency_columns_normalize_foreign_purchase() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
            ColumnRole.BILLING_CURRENCY,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Purchase abroad", 1, 30.0),
                _cell("3.00", 2, 30.0),
                _cell("USD", 3, 30.0),
                _cell("11.00", 4, 30.0),
                _cell("ILS", 5, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "11.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount == Decimal("3.00")
    assert transaction.original_currency == "USD"
    assert transaction.billed_amount == Decimal("11.00")
    assert transaction.billing_currency == "ILS"
    assert result.reconciliation.status is Status.RECONCILED


def test_generic_currency_with_original_and_billed_amounts_blocks_emission() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CURRENCY,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("3.00", 2, 30.0),
                _cell("USD", 3, 30.0),
                _cell("11.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "11.00", "ILS"))

    assert result.transactions == ()
    assert "ambiguous_generic_currency_association" in result.row_results[0].diagnostics


def test_original_currency_without_original_amount_blocks_emission() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Foreign merchant", 1, 30.0),
                _cell("USD", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions == ()
    assert "original_currency_without_original_amount" in result.row_results[0].diagnostics
    assert result.reconciliation.status is Status.UNRECONCILED


def test_refund_category_with_positive_billed_sign_is_authoritative_but_ambiguous() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Customer refund", 1, 30.0),
                _cell("5.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "5.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.kind is TransactionKind.CHARGE
    assert transaction.category is TransactionCategory.REFUND
    assert "category_sign_contradiction" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_page_evidence_discovery_and_normalization_merge_wrapped_merchant() -> None:
    def word(text: str, x0: float, x1: float, y: float) -> Word:
        return Word(text=text, bbox=(x0, y, x1, y + 10.0), source="digital", confidence=1.0)

    words = (
        word("Date", 0.0, 22.0, 10.0),
        word("Description", 35.0, 72.0, 10.0),
        word("Amount", 92.0, 120.0, 10.0),
        word("01/02/2026", 0.0, 22.0, 30.0),
        word("Long merchant", 35.0, 72.0, 30.0),
        word("₪10.00", 92.0, 120.0, 30.0),
        word("continued name", 35.0, 72.0, 41.0),
        word("02/02/2026", 0.0, 22.0, 60.0),
        word("Cafe", 35.0, 72.0, 60.0),
        word("₪20.00", 92.0, 120.0, 60.0),
        word("Total", 35.0, 72.0, 80.0),
        word("₪30.00", 92.0, 120.0, 80.0),
    )
    page = PageEvidence(
        page_number=1,
        width=130.0,
        height=120.0,
        words=words,
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )
    discovery = discover_statement(DocumentEvidence(source_sha256="b" * 64, pages=(page,)))

    result = normalize_statement(discovery)

    assert len(result.transactions) == 2
    assert result.transactions[0].description == "Long merchant continued name"
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize("continuation", ("Store 24", "7 Eleven"))
def test_page_evidence_keeps_digit_bearing_merchant_continuation(
    continuation: str,
) -> None:
    def word(text: str, x0: float, x1: float, y: float) -> Word:
        return Word(text=text, bbox=(x0, y, x1, y + 10.0), source="digital", confidence=1.0)

    words = (
        word("Date", 0.0, 22.0, 10.0),
        word("Description", 35.0, 72.0, 10.0),
        word("Amount", 92.0, 120.0, 10.0),
        word("01/02/2026", 0.0, 22.0, 30.0),
        word("Long merchant", 35.0, 72.0, 30.0),
        word("₪10.00", 92.0, 120.0, 30.0),
        word(continuation, 35.0, 72.0, 41.0),
        word("02/02/2026", 0.0, 22.0, 60.0),
        word("Cafe", 35.0, 72.0, 60.0),
        word("₪20.00", 92.0, 120.0, 60.0),
        word("Total", 35.0, 72.0, 80.0),
        word("₪30.00", 92.0, 120.0, 80.0),
    )
    page = PageEvidence(
        page_number=1,
        width=130.0,
        height=120.0,
        words=words,
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )

    discovery = discover_statement(DocumentEvidence(source_sha256="d" * 64, pages=(page,)))
    result = normalize_statement(discovery)

    assert len(result.transactions) == 2
    assert result.transactions[0].description == f"Long merchant {continuation}"
    assert result.transactions[1].description == "Cafe"
    assert result.reconciliation.status is Status.RECONCILED


def test_inferred_specific_foreign_purchase_headers_reconcile_end_to_end() -> None:
    def word(text: str, x0: float, x1: float, y: float) -> Word:
        return Word(text=text, bbox=(x0, y, x1, y + 10.0), source="digital", confidence=1.0)

    words = (
        word("Date", 0.0, 35.0, 10.0),
        word("Description", 50.0, 105.0, 10.0),
        word("Transaction amount", 120.0, 180.0, 10.0),
        word("Transaction currency", 195.0, 245.0, 10.0),
        word("Billed amount", 260.0, 305.0, 10.0),
        word("Billing currency", 320.0, 365.0, 10.0),
        word("01/02/2026", 0.0, 35.0, 30.0),
        word("Purchase abroad", 50.0, 105.0, 30.0),
        word("3.00", 120.0, 180.0, 30.0),
        word("USD", 195.0, 245.0, 30.0),
        word("11.00", 260.0, 305.0, 30.0),
        word("ILS", 320.0, 365.0, 30.0),
        word("02/02/2026", 0.0, 35.0, 50.0),
        word("Foreign cafe", 50.0, 105.0, 50.0),
        word("4.00", 120.0, 180.0, 50.0),
        word("USD", 195.0, 245.0, 50.0),
        word("14.00", 260.0, 305.0, 50.0),
        word("ILS", 320.0, 365.0, 50.0),
        word("Total", 50.0, 105.0, 70.0),
        word("₪25.00", 260.0, 305.0, 70.0),
    )
    page = PageEvidence(
        page_number=1,
        width=380.0,
        height=100.0,
        words=words,
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )

    discovery = discover_statement(DocumentEvidence(source_sha256="c" * 64, pages=(page,)))
    result = normalize_statement(discovery)

    assert tuple(
        column.role for column in discovery.groups[0].table_regions[0].table_schema.columns
    ) == (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.ORIGINAL_CURRENCY,
        ColumnRole.AMOUNT,
        ColumnRole.BILLING_CURRENCY,
    )
    assert len(result.transactions) == 2
    assert result.transactions[0].original_amount == Decimal("3.00")
    assert result.transactions[0].original_currency == "USD"
    assert result.transactions[0].billed_amount == Decimal("11.00")
    assert result.transactions[0].billing_currency == "ILS"
    assert result.reconciliation.status is Status.RECONCILED
