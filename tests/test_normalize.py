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
