from __future__ import annotations

import csv
import inspect
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

import ccparser.money as money_module
import ccparser.text_tokens as text_tokens_module
from ccparser.discovery import (
    DateTokenStyle,
    DiscoveredDateYearContext,
    DiscoveredPrintedTotal,
    DocumentClassification,
    StatementDiscovery,
    StatementGroupDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.layout import Cell, ColumnRole, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.money import canonical_currency, currencies_in_text
from ccparser.normalization_dates import parsed_cross_cell_conversion_evidence
from ccparser.normalization_fields import FieldDisposition
from ccparser.normalization_semantics import explicit_category_unknown_columns
from ccparser.normalize import (
    RowNormalizationResult,
    _normalize_row,
    _RowNormalizationAttempt,
    normalize_statement,
    parse_amount,
)
from ccparser.output import transactions_csv_bytes
from ccparser.semantic_evidence import EvidenceLedger


@contextmanager
def _cleared_lexical_caches() -> Iterator[None]:
    clear_lexical_cache = getattr(money_module._parse_lexical, "cache_clear", lambda: None)
    clear_phrase_cache = text_tokens_module._cached_phrase_tokens.cache_clear
    clear_lexical_cache()
    clear_phrase_cache()
    try:
        yield
    finally:
        clear_lexical_cache()
        clear_phrase_cache()


def test_normalize_row_assembles_diagnostic_phases_without_retroactive_insertion() -> None:
    source = inspect.getsource(_normalize_row)

    assert "assignment_diagnostic_index" not in source
    assert "conversion_resolution_diagnostics" in source
    assert "diagnostics[" not in source


def _cell(
    text: str,
    column: int,
    y: float,
    *,
    page: int = 1,
    glyphs: tuple[Glyph, ...] = (),
) -> Cell:
    x0 = float(column * 50)
    return Cell(
        page_number=page,
        bbox=(x0, y, x0 + 40.0, y + 10.0),
        text=text,
        glyphs=glyphs,
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


def test_explicit_category_columns_union_source_and_centered_header_evidence() -> None:
    centered = _cell("Transaction", 0, 10.0)
    source = _cell("type", 1, 10.0)
    row = _row(_cell("value", 0, 30.0))
    region = _region((ColumnRole.UNKNOWN,), (row,))
    column = region.table_schema.columns[0].model_copy(update={"source_cells": (source,)})
    region = region.model_copy(
        update={
            "table_schema": region.table_schema.model_copy(
                update={"columns": (column,), "header_cells": (centered, source)}
            )
        }
    )

    assert explicit_category_unknown_columns(region) == frozenset({0})


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


def _expected_evidence(row: Row) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(
            page_number=cell.page_number,
            bbox=cell.bbox,
            raw_text=cell.text,
        )
        for cell in row.cells
    )


def _expected_unemitted_row(
    row: Row,
    diagnostics: tuple[str, ...],
    *,
    confidence: float = 0.0,
) -> RowNormalizationResult:
    return RowNormalizationResult(
        page_number=row.page_number,
        bbox=row.bbox,
        raw_text=" ".join(cell.text for cell in row.cells),
        evidence=_expected_evidence(row),
        confidence=confidence,
        diagnostics=diagnostics,
    )


@pytest.mark.parametrize(
    ("roles", "row", "diagnostics", "confidence"),
    (
        pytest.param(
            (ColumnRole.DATE, ColumnRole.DESCRIPTION),
            _row(_cell("01/02/2026", 0, 30.0), _cell("Merchant", 1, 30.0)),
            ("unknown_amount_column",),
            0.0,
            id="missing-amount-column",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("ILS 11.00", 3, 30.0),
            ),
            ("unsupported_role_cardinality:amount",),
            0.0,
            id="duplicate-amount-columns",
        ),
        pytest.param(
            (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("01/02/2026", 0, 30.0), _cell("Merchant", 1, 30.0)),
            ("missing_amount_cell",),
            0.0,
            id="missing-amount-cell",
        ),
        pytest.param(
            (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("ILS 11.00", 2, 30.0),
            ),
            ("multiple_amount_cells",),
            0.0,
            id="duplicate-amount-cells",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.ORIGINAL_AMOUNT,
                ColumnRole.CURRENCY,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("USD 3.00", 2, 30.0),
                _cell("ILS", 3, 30.0),
                _cell("ILS 10.00", 4, 30.0),
            ),
            ("ambiguous_generic_currency_association",),
            0.0,
            id="generic-currency-with-original-amount",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.CURRENCY,
                ColumnRole.BILLING_CURRENCY,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS", 2, 30.0),
                _cell("ILS", 3, 30.0),
                _cell("ILS 10.00", 4, 30.0),
            ),
            ("ambiguous_generic_currency_association",),
            0.0,
            id="generic-currency-with-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
            ),
            ("missing_currency_cell",),
            0.0,
            id="missing-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("ILS", 3, 30.0),
                _cell("ILS", 3, 30.0),
            ),
            ("multiple_currency_cells",),
            0.0,
            id="duplicate-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("XYZ", 3, 30.0),
            ),
            ("unknown_billing_currency",),
            0.0,
            id="unknown-billing-currency",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.BILLING_CURRENCY,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("USD", 3, 30.0),
            ),
            ("billing_currency_conflict",),
            0.0,
            id="billing-currency-conflicts-with-group",
        ),
        pytest.param(
            (
                ColumnRole.UNKNOWN,
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("99.00", 0, 30.0),
                _cell("01/02/2026", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("12 apples", 3, 30.0),
            ),
            ("invalid_amount_text",),
            0.0,
            id="unparseable-billed-amount",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.ORIGINAL_CURRENCY,
                ColumnRole.AMOUNT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("USD", 2, 30.0),
                _cell("ILS 10.00", 3, 30.0),
            ),
            ("original_currency_without_original_amount",),
            0.0,
            id="role-contract-rejection",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.ORIGINAL_AMOUNT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Card fee", 1, 30.0),
                _cell("ILS 0.00", 2, 30.0).model_copy(update={"confidence": 0.73}),
                _cell("ILS 22.29", 3, 30.0),
            ),
            ("noncontributing_zero_billed_row",),
            0.73,
            id="zero-billed-amount",
        ),
    ),
)
def test_row_normalization_early_returns_preserve_complete_public_result(
    roles: tuple[ColumnRole, ...],
    row: Row,
    diagnostics: tuple[str, ...],
    confidence: float,
) -> None:
    region = _region(roles, (row,))

    normalized = normalize_statement(_discovery(region, "ILS 10.00", "ILS"))

    assert normalized.row_results == (
        _expected_unemitted_row(row, diagnostics, confidence=confidence),
    )


def _expected_installment_row(
    row: Row,
    diagnostics: tuple[str, ...],
    installment: tuple[int, int] | None,
) -> RowNormalizationResult:
    evidence = _expected_evidence(row)
    current, total = installment if installment is not None else (None, None)
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("10.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        ambiguities=diagnostics,
        transaction_date=date(2026, 2, 1),
        merchant="Merchant",
        description="Merchant",
        category=(
            TransactionCategory.INSTALLMENT
            if installment is not None
            else TransactionCategory.UNKNOWN
        ),
        installment_current=current,
        installment_total=total,
        evidence=evidence,
    )
    return RowNormalizationResult(
        page_number=row.page_number,
        bbox=row.bbox,
        raw_text=" ".join(cell.text for cell in row.cells),
        evidence=evidence,
        transaction=transaction,
        confidence=1.0,
        diagnostics=diagnostics,
    )


@pytest.mark.parametrize(
    ("roles", "row", "diagnostics", "installment", "rejected"),
    (
        pytest.param(
            (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
            ),
            (),
            None,
            False,
            id="absent",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("1/6", 3, 30.0),
                _cell("2/6", 4, 30.0),
            ),
            ("unsupported_role_cardinality:installment",),
            None,
            True,
            id="duplicate-columns",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
            ),
            ("missing_installment_cell",),
            None,
            False,
            id="missing-cell",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("1/6", 3, 30.0),
                _cell("2/6", 3, 30.0),
            ),
            ("multiple_installment_cells",),
            None,
            False,
            id="multiple-cells",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("two of six", 3, 30.0),
            ),
            ("invalid_installment",),
            None,
            False,
            id="malformed",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("2/6", 3, 30.0),
            ),
            (),
            (2, 6),
            False,
            id="valid",
        ),
        pytest.param(
            (
                ColumnRole.DATE,
                ColumnRole.DESCRIPTION,
                ColumnRole.AMOUNT,
                ColumnRole.INSTALLMENT,
            ),
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("ILS 10.00", 2, 30.0),
                _cell("7/6", 3, 30.0),
            ),
            ("invalid_installment",),
            None,
            False,
            id="current-greater-than-total",
        ),
    ),
)
def test_installment_shapes_preserve_complete_public_row_result(
    roles: tuple[ColumnRole, ...],
    row: Row,
    diagnostics: tuple[str, ...],
    installment: tuple[int, int] | None,
    rejected: bool,
) -> None:
    region = _region(roles, (row,))

    normalized = normalize_statement(_discovery(region, "ILS 10.00", "ILS"))

    expected = (
        _expected_unemitted_row(row, diagnostics)
        if rejected
        else _expected_installment_row(row, diagnostics, installment)
    )
    assert normalized.row_results == (expected,)


@pytest.mark.parametrize(
    ("roles", "row", "expected_disposition"),
    (
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("Merchant", 0, 30.0), _cell("ILS 10.00", 1, 30.0)),
            FieldDisposition.ACCEPT,
            id="accepted",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION,),
            _row(_cell("Merchant", 0, 30.0)),
            FieldDisposition.REJECT_ROW,
            id="rejected",
        ),
        pytest.param(
            (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
            _row(_cell("Card fee", 0, 30.0), _cell("ILS 0.00", 1, 30.0)),
            FieldDisposition.IGNORE_ROW,
            id="ignored",
        ),
    ),
)
def test_private_row_attempt_types_public_result_disposition(
    roles: tuple[ColumnRole, ...],
    row: Row,
    expected_disposition: FieldDisposition,
) -> None:
    region = _region(roles, (row,))
    discovery = _discovery(region, "ILS 10.00", "ILS")

    attempt = _normalize_row(
        row=row,
        continuation_rows=(),
        region=region,
        group=discovery.groups[0],
        year_context=None,
        date_column_kinds={},
        transaction_id="group-0001-p001-r0001",
    )

    assert isinstance(attempt, _RowNormalizationAttempt)
    assert attempt.disposition is expected_disposition
    assert attempt.result == normalize_statement(discovery).row_results[0]


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
        ("EU19.98", None, Decimal("19.98"), "EUR"),
        ("GB47.94", None, Decimal("47.94"), "GBP"),
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


def test_monetary_lexical_cache_reuses_text_and_separates_currency_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "987654321.09"
    calls: list[str] = []
    original = money_module._canonical_number

    def counting_canonical_number(text: str) -> tuple[str | None, str | None]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(money_module, "_canonical_number", counting_canonical_number)
    with _cleared_lexical_caches():
        usd_first = money_module.parse_amount(raw, currency_hint="USD")
        usd_second = money_module.parse_amount(raw, currency_hint="USD")
        eur_first = money_module.parse_amount(raw, currency_hint="EUR")
        eur_second = money_module.parse_amount(raw, currency_hint="EUR")

        assert (usd_first.amount, usd_first.currency) == (Decimal(raw), "USD")
        assert usd_second == usd_first
        assert (eur_first.amount, eur_first.currency) == (Decimal(raw), "EUR")
        assert eur_second == eur_first
        assert calls == [raw, raw]


def test_monetary_lexical_cache_is_bounded_and_evicts_least_recently_used_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshed_raw = "9999999991.01"
    evicted_raw = "9999999992.02"
    calls: list[str] = []
    original = money_module._canonical_number

    def counting_canonical_number(text: str) -> tuple[str | None, str | None]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(money_module, "_canonical_number", counting_canonical_number)
    cache = money_module._parse_lexical
    assert hasattr(cache, "cache_clear")
    with _cleared_lexical_caches():
        refreshed_first = money_module.parse_amount(refreshed_raw, currency_hint="USD")
        evicted_first = money_module.parse_amount(evicted_raw, currency_hint="USD")
        for index in range(4_094):
            money_module.parse_amount(f"{index}.00", currency_hint="USD")

        refreshed_second = money_module.parse_amount(refreshed_raw, currency_hint="USD")
        money_module.parse_amount("9999999993.03", currency_hint="USD")
        refreshed_third = money_module.parse_amount(refreshed_raw, currency_hint="USD")
        evicted_second = money_module.parse_amount(evicted_raw, currency_hint="USD")

        assert (refreshed_first.amount, refreshed_first.currency) == (
            Decimal(refreshed_raw),
            "USD",
        )
        assert refreshed_second == refreshed_first
        assert refreshed_third == refreshed_first
        assert (evicted_first.amount, evicted_first.currency) == (
            Decimal(evicted_raw),
            "USD",
        )
        assert evicted_second == evicted_first
        assert (
            cache.cache_parameters()["maxsize"],
            cache.cache_info().currsize,
            calls.count(refreshed_raw),
            calls.count(evicted_raw),
        ) == (4_096, 4_096, 1, 2)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("בזיכוי ILS 100.00", Decimal("-100.00")),
        ("בחיוב ILS 100.00", Decimal("100.00")),
    ),
)
def test_parse_amount_removes_the_same_hebrew_clitic_markers_it_detects(
    raw: str,
    expected: Decimal,
) -> None:
    result = parse_amount(raw)

    assert result.amount == expected
    assert result.currency == "ILS"
    assert result.diagnostics == ()


@pytest.mark.parametrize("collision", ("דזיכוי", "ובזיכוי"))
def test_parse_amount_does_not_remove_non_clitic_marker_collision(collision: str) -> None:
    result = parse_amount(f"100.00 {collision}", currency_hint="ILS")

    assert result.amount is None
    assert result.diagnostics == ("invalid_amount_text",)


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


def test_parse_amount_ignores_directional_marks_but_preserves_raw_text() -> None:
    raw = "USD\u200e 12.34"

    result = parse_amount(raw)

    assert result.amount == Decimal("12.34")
    assert result.currency == "USD"
    assert result.diagnostics == ()
    assert result.raw_text == raw


def test_currency_detection_does_not_join_across_invisible_operator() -> None:
    assert canonical_currency("U\u2062SD") is None
    assert currencies_in_text("U\u2062SD") == ()


def test_normalize_statement_emits_authoritative_purchase_and_refund_and_reconciles() -> None:
    from ccparser.reconcile import ReconciliationOutcome

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

    assert isinstance(result.reconciliation, ReconciliationOutcome)
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


@pytest.mark.parametrize(
    ("location", "expected_merchant"),
    (("IRELAND", "Merchant ל IRELAND"), ("RUS", "Merchant ל RUS")),
)
def test_normalize_statement_handles_location_without_guessing(
    location: str, expected_merchant: str
) -> None:
    merchant = _cell("Merchant ל", 2, 30.0).model_copy(update={"bbox": (60.0, 30.0, 140.0, 40.0)})
    continuation = _cell(location, 1, 41.0).model_copy(update={"bbox": (60.0, 41.0, 88.0, 51.0)})
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
                _cell("$3.00", 1, 30.0),
                merchant,
                _cell("10.00", 3, 30.0),
            ),
            _row(continuation),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].merchant == expected_merchant
    assert result.transactions[0].description == f"Merchant ל {location}"
    assert result.row_results[1].diagnostics == ("merged_description_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_preserves_owned_multiword_merchant_continuation() -> None:
    merchant = _cell("Merchant ל", 2, 30.0).model_copy(update={"bbox": (60.0, 30.0, 140.0, 40.0)})
    continuation = _cell("SECOND LINE", 1, 41.0).model_copy(
        update={"bbox": (60.0, 41.0, 108.0, 51.0)}
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
                _cell("$3.00", 1, 30.0),
                merchant,
                _cell("10.00", 3, 30.0),
            ),
            _row(continuation),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.merchant == "Merchant ל SECOND LINE"
    assert transaction.description == "Merchant ל SECOND LINE"
    assert not transaction.ambiguities
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_preserves_split_cells_in_merchant_continuation() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
            ),
            _row(
                _cell("WEST", 1, 41.0).model_copy(update={"bbox": (50.0, 41.0, 62.0, 51.0)}),
                _cell("123456", 1, 41.0).model_copy(update={"bbox": (75.0, 41.0, 90.0, 51.0)}),
            ),
            _row(
                _cell("02/02/2026", 0, 65.0),
                _cell("Next merchant", 1, 65.0),
                _cell("20.00", 2, 65.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert tuple(transaction.merchant for transaction in result.transactions) == (
        "Merchant WEST 123456",
        "Next merchant",
    )
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_rejects_leading_detail_without_a_proven_previous_owner() -> None:
    leading = _row(
        _cell("conversion detail", 1, 30.0),
        _cell("$3.00 note", 2, 30.0),
    ).model_copy(update={"diagnostics": ("leading_subordinate_detail_continuation",)})
    transaction = _row(
        _cell("01/02/2026", 0, 50.0),
        _cell("Market", 1, 50.0),
        _cell("$4.00", 2, 50.0),
        _cell("12.40", 3, 50.0),
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (leading, transaction),
    )

    result = normalize_statement(_discovery(region, "12.40", "ILS"))

    assert result.reconciliation.status is Status.UNRECONCILED
    assert len(result.transactions) == 1
    assert len(result.row_results) == 2
    assert result.row_results[0].transaction is None
    assert result.row_results[0].diagnostics == ("unowned_leading_subordinate_detail_continuation",)
    assert result.diagnostics == ("rows_not_emitted:1",)


def _cross_page_detail_discovery(*, wrapped: bool) -> StatementDiscovery:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    previous_transaction = _row(
        _cell("31/01/2026", 0, 30.0),
        _cell("Previous", 1, 30.0),
        _cell("$3.00", 2, 30.0),
        _cell("10.00", 3, 30.0),
    )
    wrapped_rows = (
        (
            _row(_cell("REFERENCE", 1, 41.0)),
            _row(_cell("SECOND LINE", 1, 52.0)),
        )
        if wrapped
        else ()
    )
    previous_region = _region(roles, (previous_transaction, *wrapped_rows))
    leading = _row(
        _cell("conversion detail", 1, 30.0, page=2),
        _cell("USD 3.00", 2, 30.0, page=2),
    ).model_copy(update={"diagnostics": ("leading_subordinate_detail_continuation",)})
    next_transaction = _row(
        _cell("01/02/2026", 0, 50.0, page=2),
        _cell("Next", 1, 50.0, page=2),
        _cell("$4.00", 2, 50.0, page=2),
        _cell("12.40", 3, 50.0, page=2),
    )
    next_region = _region(roles, (leading, next_transaction)).model_copy(update={"page_number": 2})
    discovery = _discovery(previous_region, "22.40", "ILS")
    group = discovery.groups[0].model_copy(update={"table_regions": (previous_region, next_region)})
    discovery = discovery.model_copy(
        update={
            "groups": (group,),
            "table_regions": (previous_region, next_region),
        }
    )

    return discovery


@pytest.mark.parametrize("wrapped", [False, True])
def test_normalize_statement_attaches_cross_page_leading_detail_to_previous_transaction(
    wrapped: bool,
) -> None:
    discovery = _cross_page_detail_discovery(wrapped=wrapped)
    result = normalize_statement(discovery)

    assert result.reconciliation.status is Status.RECONCILED
    assert tuple(transaction.merchant for transaction in result.transactions) == (
        "Previous REFERENCE SECOND LINE" if wrapped else "Previous",
        "Next",
    )
    assert tuple(transaction.transaction_id for transaction in result.transactions) == (
        "group-0001-p001-r0001",
        "group-0001-p002-r0005" if wrapped else "group-0001-p002-r0003",
    )
    assert tuple(evidence.raw_text for evidence in result.transactions[0].evidence) == (
        "31/01/2026",
        "Previous",
        "$3.00",
        "10.00",
        *(("REFERENCE", "SECOND LINE") if wrapped else ()),
        "conversion detail",
        "USD 3.00",
    )
    assert any(
        evidence.page_number == 2 and evidence.raw_text == "USD 3.00"
        for evidence in result.transactions[0].evidence
    )
    assert all(evidence.raw_text != "USD 3.00" for evidence in result.transactions[1].evidence)
    assert tuple(row_result.diagnostics for row_result in result.row_results) == (
        (),
        *(("merged_description_continuation",),) * (2 if wrapped else 0),
        ("merged_subordinate_detail_continuation",),
        (),
    )


def test_continuation_ownership_assembles_wrapped_chain_and_cross_page_detail() -> None:
    from ccparser.normalization_continuations import assemble_continuation_ownership

    discovery = _cross_page_detail_discovery(wrapped=True)
    group = discovery.groups[0]
    before = group.model_dump()

    regions = assemble_continuation_ownership(group)

    assert tuple(len(region.rows) for region in regions) == (1, 1)
    previous = regions[0].rows[0]
    following = regions[1].rows[0]
    assert previous.row.cells[1].text == "Previous"
    assert following.row.cells[1].text == "Next"
    assert following.continuations == ()
    assert tuple(item.row.cells[0].text for item in previous.continuations) == (
        "REFERENCE",
        "SECOND LINE",
        "conversion detail",
    )
    assert tuple(item.diagnostic for item in previous.continuations) == (
        "merged_description_continuation",
        "merged_description_continuation",
        "merged_subordinate_detail_continuation",
    )
    assert previous.continuations[-1].row.diagnostics == ("subordinate_detail_continuation",)
    assert previous.continuations[-1].row.page_number == 2
    assert group.model_dump() == before


def test_continuation_ownership_rejects_handoff_when_leading_tags_are_not_a_prefix() -> None:
    from ccparser.normalization_continuations import assemble_continuation_ownership

    discovery = _cross_page_detail_discovery(wrapped=True)
    group = discovery.groups[0]
    previous, current = group.table_regions
    late_detail = _row(_cell("TAIL", 1, 61.0, page=2)).model_copy(
        update={"diagnostics": ("leading_subordinate_detail_continuation",)}
    )
    current = current.model_copy(update={"rows": (*current.rows, late_detail)})
    group = group.model_copy(update={"table_regions": (previous, current)})

    regions = assemble_continuation_ownership(group)

    assert tuple(len(region.rows) for region in regions) == (1, 2)
    assert len(regions[0].rows[0].continuations) == 2
    assert regions[1].rows[0].diagnostic == "unowned_leading_subordinate_detail_continuation"


def test_normalize_statement_does_not_attach_leading_detail_to_zero_billed_row() -> None:
    roles = (
        ColumnRole.DATE,
        ColumnRole.DESCRIPTION,
        ColumnRole.ORIGINAL_AMOUNT,
        ColumnRole.AMOUNT,
    )
    zero_billed = _row(
        _cell("31/01/2026", 0, 30.0),
        _cell("Zero", 1, 30.0),
        _cell("$0.00", 2, 30.0),
        _cell("0.00", 3, 30.0),
    )
    previous_region = _region(roles, (zero_billed,))
    leading = _row(
        _cell("conversion detail", 1, 30.0, page=2),
        _cell("USD 3.00", 2, 30.0, page=2),
    ).model_copy(update={"diagnostics": ("leading_subordinate_detail_continuation",)})
    next_transaction = _row(
        _cell("01/02/2026", 0, 50.0, page=2),
        _cell("Next", 1, 50.0, page=2),
        _cell("$4.00", 2, 50.0, page=2),
        _cell("12.40", 3, 50.0, page=2),
    )
    next_region = _region(roles, (leading, next_transaction)).model_copy(update={"page_number": 2})
    discovery = _discovery(previous_region, "12.40", "ILS")
    group = discovery.groups[0].model_copy(update={"table_regions": (previous_region, next_region)})
    discovery = discovery.model_copy(
        update={
            "groups": (group,),
            "table_regions": (previous_region, next_region),
        }
    )

    result = normalize_statement(discovery)

    assert result.reconciliation.status is Status.UNRECONCILED
    assert len(result.transactions) == 1
    assert any(
        row_result.diagnostics == ("unowned_leading_subordinate_detail_continuation",)
        for row_result in result.row_results
    )
    assert result.diagnostics == ("rows_not_emitted:1",)


def test_normalize_statement_merges_continuation_covered_by_split_merchant_cells() -> None:
    original = _cell("$10.00 MERCHANT", 1, 30.0).model_copy(
        update={
            "bbox": (50.0, 30.0, 110.0, 40.0),
            "words": (
                _word("$10.00", 50.0, 70.0, 30.0),
                _word("MERCHANT", 75.0, 105.0, 30.0),
            ),
        }
    )
    name = _cell("NAME", 2, 30.0).model_copy(
        update={
            "bbox": (110.0, 30.0, 140.0, 40.0),
            "words": (_word("NAME", 110.0, 140.0, 30.0),),
        }
    )
    continuation = _cell("CITY", 1, 41.0).model_copy(
        update={
            "bbox": (70.0, 41.0, 120.0, 51.0),
            "words": (_word("CITY", 70.0, 120.0, 41.0),),
        }
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("40.00", 0, 30.0),
                original,
                name,
                _cell("01/02/2026", 3, 30.0),
            ),
            _row(continuation),
        ),
    )

    result = normalize_statement(_discovery(region, "40.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].description == "MERCHANT NAME CITY"
    assert result.transactions[0].original_amount == Decimal("10.00")
    assert result.row_results[1].diagnostics == ("merged_description_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("text", "bbox"),
    (
        ("IRELAND", (10.0, 41.0, 38.0, 51.0)),
        ("5.00", (60.0, 41.0, 88.0, 51.0)),
        ("02/02/2026", (60.0, 41.0, 88.0, 51.0)),
    ),
)
def test_normalize_statement_rejects_unproven_boundary_continuation(
    text: str,
    bbox: tuple[float, float, float, float],
) -> None:
    merchant = _cell("Merchant", 2, 30.0).model_copy(update={"bbox": (60.0, 30.0, 140.0, 40.0)})
    candidate = _cell(text, 1, 41.0).model_copy(update={"bbox": bbox})
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
                _cell("$3.00", 1, 30.0),
                merchant,
                _cell("10.00", 3, 30.0),
            ),
            _row(candidate),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].description == "Merchant"
    assert result.row_results[1].transaction is None
    assert "rows_not_emitted:1" in result.diagnostics


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


def test_normalize_statement_recovers_money_when_spill_has_only_glyph_text() -> None:
    original_cell = _cell("$3.00MER", 1, 30.0).model_copy(
        update={
            "bbox": (50.0, 30.0, 105.0, 40.0),
            "words": (
                _word("$", 55.0, 58.0, 30.0),
                _word("3.00", 59.0, 70.0, 30.0),
            ),
        }
    )
    description_cell = _cell("CHANT DETAILS", 2, 30.0).model_copy(
        update={
            "bbox": (90.0, 30.0, 140.0, 40.0),
            "words": (
                _word("MERCHANT", 90.0, 115.0, 30.0),
                _word("DETAILS", 120.0, 140.0, 30.0),
            ),
        }
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
    assert transaction.description == "MER CHANT DETAILS"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("location_text", "location_value", "location_bbox"),
    (
        ("$ 1234567890", "1234567890", (50.0, 30.0, 90.0, 40.0)),
        ("$ MERCHANT/CITY", "MERCHANT/CITY", (50.0, 30.0, 90.0, 40.0)),
        ("$ MERCHANT/CITY I", "MERCHANT/CITY", (50.0, 30.0, 105.0, 40.0)),
    ),
)
def test_normalize_statement_recovers_currency_spilled_into_adjacent_location(
    location_text: str,
    location_value: str,
    location_bbox: tuple[float, float, float, float],
) -> None:
    location = _cell(location_text, 2, 30.0).model_copy(
        update={
            "bbox": location_bbox,
            "words": (
                _word("$", 50.0, 53.0, 30.0),
                _word(location_value, 54.0, 80.0, 30.0),
            ),
        }
    )
    region = _region(
        (
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.LOCATION,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("10.18", 0, 30.0),
                location,
                _cell("Merchant", 2, 30.0),
                _cell("01/02/2026", 3, 30.0),
                _cell("40.60", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "40.60", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].original_amount == Decimal("10.18")
    assert result.transactions[0].original_currency == "USD"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_uses_exact_amount_word_between_boundary_glyphs() -> None:
    original = _cell("A 60.00 0", 1, 30.0).model_copy(
        update={
            "bbox": (48.0, 30.0, 92.0, 40.0),
            "words": (_word("60.00", 60.0, 80.0, 30.0),),
            "glyphs": (
                Glyph(
                    char="0",
                    bbox=(48.0, 30.0, 52.0, 40.0),
                    origin=(48.0, 39.0),
                    font="Synthetic",
                    size=10.0,
                    source="digital",
                    confidence=1.0,
                ),
                *_glyphs("60.00", 60.0, 30.0),
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
        }
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("60.00", 0, 30.0),
                original,
                _cell("Merchant", 2, 30.0),
                _cell("01/02/2026", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "60.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].original_amount == Decimal("60.00")
    assert result.transactions[0].original_currency == "ILS"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_uses_exact_money_words_before_boundary_glyph() -> None:
    original = _cell("60.00 ₪ A", 1, 30.0).model_copy(
        update={
            "bbox": (60.0, 30.0, 92.0, 40.0),
            "words": (
                _word("60.00", 60.0, 80.0, 30.0),
                _word("₪", 81.0, 85.0, 30.0),
            ),
            "glyphs": (
                *_glyphs("60.00", 60.0, 30.0),
                *_glyphs("₪", 81.0, 30.0),
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
        }
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("60.00", 0, 30.0),
                original,
                _cell("Merchant", 2, 30.0),
                _cell("01/02/2026", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "60.00", "ILS"))

    assert result.transactions[0].original_amount == Decimal("60.00")
    assert result.transactions[0].original_currency == "ILS"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_recovers_money_before_description_band_spill() -> None:
    original_cell = _cell("$3.00MERCHANT", 1, 30.0).model_copy(
        update={
            "bbox": (50.0, 30.0, 108.0, 40.0),
            "words": (
                _word("$", 55.0, 58.0, 30.0),
                _word("3.00", 59.0, 70.0, 30.0),
                _word("MERCHANT", 85.0, 108.0, 30.0),
            ),
        }
    )
    description_cell = _cell("DETAILS", 2, 30.0).model_copy(
        update={"words": (_word("DETAILS", 130.0, 138.0, 30.0),)}
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


@pytest.mark.parametrize(("note_amount", "is_corroborated"), (("3.00", True), ("4.00", False)))
def test_normalize_statement_uses_bounded_note_to_corroborate_distant_original_spill(
    note_amount: str,
    is_corroborated: bool,
) -> None:
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
        update={"words": (_word("DETAILS", 125.0, 138.0, 30.0),)}
    )
    note_currency = _cell("USD", 2, 41.0).model_copy(
        update={
            "bbox": (105.0, 41.0, 115.0, 51.0),
            "words": (_word("USD", 105.0, 115.0, 41.0),),
        }
    )
    note_value = _cell(note_amount, 2, 41.0).model_copy(
        update={
            "bbox": (118.0, 41.0, 132.0, 51.0),
            "words": (_word(note_amount, 118.0, 132.0, 41.0),),
        }
    )
    note = _row(note_currency, note_value).model_copy(
        update={
            "diagnostics": (
                "subordinate_detail_continuation",
                "bounded_hebrew_note_detail",
            )
        }
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
            note,
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))
    transaction = result.transactions[0]

    if is_corroborated:
        assert transaction.original_amount == Decimal("3.00")
        assert transaction.original_currency == "USD"
        assert transaction.description == "MERCHANT DETAILS"
        assert transaction.ambiguities == ()
        assert result.reconciliation.status is Status.RECONCILED
    else:
        assert transaction.original_amount is None
        assert transaction.original_currency is None
        assert transaction.description == "DETAILS"
        assert "original_amount:invalid_amount_text" in transaction.ambiguities
        assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize("has_aligned_wrapped_line", (True, False))
def test_original_amount_spill_uses_shared_wrapped_description_origin(
    has_aligned_wrapped_line: bool,
) -> None:
    original = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 99.0, 40.0),
        text="₪14.90 GOOGLE",
        words=(
            _word("₪", 52.0, 56.0, 30.0),
            _word("14.90", 58.0, 72.0, 30.0),
            _word("GOOGLE", 80.0, 99.0, 30.0),
        ),
        confidence=1.0,
    )
    wrapped_x0 = 80.0 if has_aligned_wrapped_line else 88.0
    description = Cell(
        page_number=1,
        bbox=(80.0, 30.0, 140.0, 48.0),
        text="VIDEO SERVICE",
        words=(
            _word("VIDEO", 108.0, 132.0, 30.0),
            _word("SERVICE", wrapped_x0, 120.0, 38.0),
        ),
        confidence=1.0,
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
                original,
                description,
                _cell("14.90", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "14.90", "ILS"))

    transaction = result.transactions[0]
    if has_aligned_wrapped_line:
        assert transaction.original_amount == Decimal("14.90")
        assert transaction.original_currency == "ILS"
        assert transaction.description == "GOOGLE VIDEO SERVICE"
        assert transaction.ambiguities == ()
        assert result.reconciliation.status is Status.RECONCILED
    else:
        assert transaction.original_amount is None
        assert transaction.original_currency is None
        assert transaction.description == "VIDEO SERVICE"
        assert "original_amount:invalid_amount_text" in transaction.ambiguities
        assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize("has_same_line_adjacency", (True, False))
def test_original_amount_spill_uses_line_aware_description_adjacency(
    has_same_line_adjacency: bool,
) -> None:
    original = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 99.0, 48.0),
        text="₪14.90 GOOGLE IRELAND",
        words=(
            _word("₪", 52.0, 56.0, 30.0),
            _word("14.90", 58.0, 68.0, 30.0),
            _word("GOOGLE", 70.0, 90.0, 30.0),
            _word("IRELAND", 70.0, 99.0, 38.0),
        ),
        confidence=1.0,
    )
    description_x0 = 92.0 if has_same_line_adjacency else 98.0
    description = Cell(
        page_number=1,
        bbox=(92.0, 30.0, 140.0, 48.0),
        text="CLOUD EMEA",
        words=(
            _word("CLOUD", description_x0, 116.0, 30.0),
            _word("EMEA", 118.0, 138.0, 30.0),
        ),
        confidence=1.0,
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
                original,
                description,
                _cell("14.90", 3, 30.0),
            ),
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "14.90", "ILS"))

    transaction = result.transactions[0]
    if has_same_line_adjacency:
        assert transaction.original_amount == Decimal("14.90")
        assert transaction.original_currency == "ILS"
        assert transaction.description == "GOOGLE IRELAND CLOUD EMEA"
        assert transaction.ambiguities == ()
        assert result.reconciliation.status is Status.RECONCILED
    else:
        assert transaction.original_amount is None
        assert transaction.original_currency is None
        assert transaction.description == "CLOUD EMEA"
        assert "original_amount:invalid_amount_text" in transaction.ambiguities
        assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_uses_exact_subordinate_detail_to_recover_ocr_original_amount() -> None:
    original = _cell("$ 3000 MERCHANT 30.00", 1, 30.0).model_copy(
        update={
            "words": (
                _word("$", 52.0, 55.0, 30.0, source="ocr"),
                _word("3000", 56.0, 66.0, 30.0, source="ocr"),
                _word("MERCHANT", 67.0, 82.0, 30.0, source="ocr"),
                _word("30.00", 83.0, 96.0, 30.0, source="ocr"),
            )
        }
    )
    detail = _row(
        _cell("USD", 1, 41.0).model_copy(
            update={"words": (_word("USD", 55.0, 65.0, 41.0, source="ocr"),)}
        ),
        _cell("30.00", 2, 41.0).model_copy(
            update={"words": (_word("30.00", 105.0, 120.0, 41.0, source="ocr"),)}
        ),
    ).model_copy(update={"diagnostics": ("subordinate_detail_continuation",)})
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
                original,
                _cell("MERCHANT", 2, 30.0),
                _cell("100.00", 3, 30.0),
            ),
            detail,
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "100.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount == Decimal("30.00")
    assert transaction.original_currency == "USD"
    assert transaction.ambiguities == ()
    assert result.row_results[1].diagnostics == ("merged_subordinate_detail_continuation",)
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("detail_amount", "detail_diagnostic", "word_source"),
    (
        ("31.00", "subordinate_detail_continuation", "ocr"),
        ("30.00", "", "ocr"),
        ("30.00", "subordinate_detail_continuation", "digital"),
    ),
)
def test_subordinate_detail_original_recovery_requires_matching_associated_ocr_evidence(
    detail_amount: str,
    detail_diagnostic: str,
    word_source: str,
) -> None:
    original = _cell("$ 3000 MERCHANT 30.00", 1, 30.0).model_copy(
        update={
            "words": (
                _word("$", 52.0, 55.0, 30.0, source=word_source),
                _word("3000", 56.0, 66.0, 30.0, source=word_source),
                _word("MERCHANT", 67.0, 82.0, 30.0, source=word_source),
                _word("30.00", 83.0, 96.0, 30.0, source=word_source),
            )
        }
    )
    detail = _row(
        _cell("USD", 1, 41.0).model_copy(
            update={"words": (_word("USD", 55.0, 65.0, 41.0, source="ocr"),)}
        ),
        _cell(detail_amount, 2, 41.0).model_copy(
            update={"words": (_word(detail_amount, 105.0, 120.0, 41.0, source="ocr"),)}
        ),
    ).model_copy(update={"diagnostics": ((detail_diagnostic,) if detail_diagnostic else ())})
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
                original,
                _cell("MERCHANT", 2, 30.0),
                _cell("100.00", 3, 30.0),
            ),
            detail,
        ),
        headers=("Date", "Original amount", "Description", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "100.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.original_amount is None
    assert transaction.original_currency is None
    assert "original_amount:invalid_amount_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_recovers_money_before_exact_distant_description_duplicate() -> None:
    original_cell = _cell("$3.00MERCHANT", 1, 30.0).model_copy(
        update={
            "words": (
                _word("$", 55.0, 58.0, 30.0),
                _word("3.00", 59.0, 70.0, 30.0),
                _word("MERCHANT", 74.0, 88.0, 30.0),
            )
        }
    )
    description_cell = _cell("MERCHANT", 2, 30.0).model_copy(
        update={"words": (_word("MERCHANT", 120.0, 138.0, 30.0),)}
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
    assert transaction.description == "MERCHANT"
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
        ColumnRole.DESCRIPTION,
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


def test_separated_description_continuation_clusters_preserve_owned_field() -> None:
    continuation_cell = _cell("ALPHA BETA", 1, 41.0).model_copy(
        update={
            "words": (
                _word("ALPHA", 50.0, 60.0, 41.0),
                _word("BETA", 80.0, 90.0, 41.0),
            )
        }
    )
    continuation = _row(continuation_cell).model_copy(
        update={"diagnostics": ("subordinate_auxiliary_continuation",)}
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
            ),
            continuation,
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].merchant == "Merchant ALPHA BETA"
    assert not result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
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


def test_normalize_statement_accepts_exact_card_identifier_in_unknown_column() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("Google Pay מזהה כרטיס", 2, 30.0),
                _cell("9313", 3, 30.0),
                _cell("10.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.row_results[0].diagnostics == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_ignores_isolated_short_ocr_artifact_in_punctuation_edge_column() -> (
    None
):
    artifact_word = _word("2", 0.0, 40.0, 30.0, source="ocr")
    artifact_cell = _cell("2", 0, 30.0).model_copy(update={"words": (artifact_word,)})
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                artifact_cell,
                _cell("10.00", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("01/02/2026", 3, 30.0),
            ),
            _row(
                _cell("20.00", 1, 50.0),
                _cell("Cafe", 2, 50.0),
                _cell("02/02/2026", 3, 50.0),
            ),
        ),
        headers=("|", "Amount", "Description", "Date"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert len(result.transactions) == 2
    assert result.row_results[0].diagnostics == ()
    assert result.diagnostics == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_ignores_unique_edge_artifact_under_short_ocr_header() -> None:
    artifact_word = _word("5", 0.0, 40.0, 30.0, source="ocr")
    artifact_cell = _cell("5", 0, 30.0).model_copy(update={"words": (artifact_word,)})
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                artifact_cell,
                _cell("10.00", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("01/02/2026", 3, 30.0),
            ),
            _row(
                _cell("20.00", 1, 50.0),
                _cell("Cafe", 2, 50.0),
                _cell("02/02/2026", 3, 50.0),
            ),
        ),
        headers=("Noise", "Amount", "Description", "Date"),
    )
    ocr_header_word = _word("Noise", 0.0, 40.0, 10.0, source="ocr")
    ocr_header = region.table_schema.header_cells[0].model_copy(
        update={"words": (ocr_header_word,)}
    )
    columns = (
        region.table_schema.columns[0].model_copy(update={"source_cells": (ocr_header,)}),
        *region.table_schema.columns[1:],
    )
    region = region.model_copy(
        update={
            "table_schema": region.table_schema.model_copy(
                update={
                    "columns": columns,
                    "header_cells": (ocr_header, *region.table_schema.header_cells[1:]),
                }
            )
        }
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert len(result.transactions) == 2
    assert result.row_results[0].diagnostics == ()
    assert result.diagnostics == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_retains_visually_reversed_card_identifier_as_ambiguous() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("Google Pay כרטיס מזהה", 2, 30.0),
                _cell("9313", 3, 30.0),
                _cell("10.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert "unresolved_relevant_cell" in result.transactions[0].ambiguities
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


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


def test_normalize_statement_resolves_currency_alternative_from_accepted_conversion_date() -> None:
    conversion_text = "03/02/26"
    conversion_date = _cell(
        conversion_text,
        0,
        30.0,
        glyphs=_glyphs(conversion_text, 0.0, 30.0),
    )
    region = _region(
        (
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                conversion_date,
                _cell("01/02/26", 1, 30.0),
                _cell("Merchant", 2, 30.0),
                _cell("4.00", 3, 30.0),
            ),
        ),
        headers=("Conversion date", "Date", "Description", "Amount"),
    )
    conversion_column = region.table_schema.columns[0].model_copy(
        update={"diagnostics": ("alternative_role:currency",)}
    )
    region = region.model_copy(
        update={
            "table_schema": region.table_schema.model_copy(
                update={
                    "columns": (conversion_column, *region.table_schema.columns[1:]),
                }
            )
        }
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date == date(2026, 2, 3)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_composite_conversion_date_and_rate_keep_disjoint_semantic_ownership() -> None:
    conversion_text = "03/02/26 2.9430"
    conversion_cell = _cell(
        conversion_text,
        0,
        30.0,
        glyphs=_glyphs(conversion_text, 0.0, 30.0),
    )
    region = _region(
        (
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                conversion_cell,
                _cell("01/02/26", 1, 30.0),
                _cell("Foreign purchase", 2, 30.0),
                _cell("10.00", 3, 30.0),
                _cell("USD", 4, 30.0),
                _cell("29.43", 5, 30.0),
            ),
        ),
        headers=(
            "Conversion date Exchange rate",
            "Date",
            "Description",
            "Original amount",
            "Original currency",
            "Amount",
        ),
    )
    conversion_column = region.table_schema.columns[0].model_copy(
        update={"diagnostics": ("alternative_role:currency",)}
    )
    region = region.model_copy(
        update={
            "table_schema": region.table_schema.model_copy(
                update={"columns": (conversion_column, *region.table_schema.columns[1:])}
            )
        }
    )

    result = normalize_statement(_discovery(region, "29.43", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date == date(2026, 2, 3)
    assert transaction.foreign_exchange is not None
    assert transaction.foreign_exchange.exchange_rate is not None
    assert transaction.foreign_exchange.exchange_rate.value == Decimal("2.9430")
    assert "column:0:alternative_role:currency" not in transaction.ambiguities
    assert "conflicting_semantic_evidence_claim" not in transaction.ambiguities
    assert "unconsumed_transaction_semantic_text" not in transaction.ambiguities
    assert result.reconciliation.status is Status.RECONCILED


def test_unreadable_explicit_conversion_date_prevents_strict_success() -> None:
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("$5.15", 1, 30.0),
                _cell("Unreadable", 2, 30.0),
                _cell("Foreign merchant", 3, 30.0),
                _cell("24/06/2026", 4, 30.0),
            ),
        ),
        headers=(
            "Amount",
            "Original amount",
            "Conversion date",
            "Merchant",
            "Date",
        ),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date is None
    assert "invalid_conversion_date" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


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


def test_normalize_statement_rejects_short_date_with_untyped_integer_residual() -> None:
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
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities
    assert transaction.evidence[0].raw_text == "17 01/02/26"


@pytest.mark.parametrize(
    "raw_text",
    ("01/02/2026 17", "01/02/2026 2.9430", "USD01/02/2026"),
)
def test_normalize_statement_rejects_full_year_date_with_material_residual(
    raw_text: str,
) -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell(raw_text, 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert any(ambiguity.startswith("unconsumed_") for ambiguity in transaction.ambiguities)
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_preserves_numeric_reference_inside_merchant_field() -> None:
    row = _row(
        _cell("01/02/2026", 0, 30.0),
        _cell("Merchant", 1, 30.0),
        _cell("123456", 2, 30.0),
        _cell("4.00", 3, 30.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (row,),
    )
    columns = tuple(
        column.model_copy(update={"bbox": bbox})
        for column, bbox in zip(
            region.table_schema.columns,
            (
                (0.0, 10.0, 44.0, 200.0),
                (45.0, 10.0, 145.0, 200.0),
                (146.0, 10.0, 200.0, 200.0),
            ),
            strict=True,
        )
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.description == "Merchant 123456"
    assert transaction.merchant == "Merchant 123456"
    assert not transaction.ambiguities
    assert result.reconciliation.status is Status.RECONCILED

    statement = StatementResult(
        status=result.reconciliation.status,
        transactions=result.transactions,
        groups=result.reconciliation.groups,
        source_name="synthetic.pdf",
        source_sha256="a" * 64,
        statement_id="a" * 64,
    )
    batch = BatchResult(status=statement.status, statements=(statement,))
    csv_rows = tuple(
        csv.DictReader(io.StringIO(transactions_csv_bytes(batch).decode("utf-8-sig"), newline=""))
    )
    assert csv_rows[0]["merchant"] == "Merchant 123456"
    assert statement.model_dump(mode="json")["transactions"][0]["merchant"] == "Merchant 123456"


def test_normalize_statement_rejects_positioned_date_with_untyped_integer_word() -> None:
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
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities
    assert transaction.evidence[0].raw_text == "01/02/266"


def test_normalize_statement_rejects_logical_date_without_positioned_token_boundary() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text="ref 25/06/26",
        glyphs=_glyphs("ref25/06/26", 0.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(date_cell, _cell("Merchant", 1, 30.0), _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_rejects_conflicting_logical_and_word_dates() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text="25/06/26",
        words=(_word("26/06/26", 0.0, 30.0, 30.0),),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(date_cell, _cell("Merchant", 1, 30.0), _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_rejects_conflicting_conversion_date_representations() -> None:
    conversion_cell = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 40.0),
        text="25/06/26",
        glyphs=_glyphs("26/06/26", 100.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("$5.15", 1, 30.0),
                conversion_cell,
                _cell("Foreign merchant", 3, 30.0),
                _cell("24/06/26", 4, 30.0),
            ),
        ),
        headers=("Amount", "Original", "Conversion date", "Merchant", "Date"),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date is None
    assert "invalid_conversion_date" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_completes_date_from_one_adjacent_boundary_digit() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(51.0, 30.0, 60.0, 40.0),
        text="26/01/202",
        glyphs=_glyphs("26/01/202", 51.0, 30.0),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 78.0, 40.0),
        text="2 סוחר",
        glyphs=(*_glyphs("רחוס", 0.0, 30.0), *_glyphs("2", 60.0, 30.0)),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description_cell, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2022))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2022, 1, 26)
    assert transaction.description == "סוחר"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_rejects_nonadjacent_boundary_date_digit() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(51.0, 30.0, 60.0, 40.0),
        text="26/01/202",
        glyphs=_glyphs("26/01/202", 51.0, 30.0),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 78.0, 40.0),
        text="2 סוחר",
        glyphs=(*_glyphs("רחוס", 0.0, 30.0), *_glyphs("2", 65.0, 30.0)),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description_cell, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2022))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert "invalid_transaction_date" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize(
    ("raw_date", "expected"),
    (
        ("2716/01/26", date(2026, 1, 16)),
        ("02/02/2685", date(2026, 2, 2)),
    ),
)
def test_normalize_statement_repairs_bounded_ocr_digits_fused_to_date(
    raw_date: str,
    expected: date,
) -> None:
    date_word = _word(raw_date, 0.0, 40.0, 30.0, source="ocr")
    date_cell = Cell(
        page_number=1,
        bbox=date_word.bbox,
        text=raw_date,
        words=(date_word,),
        confidence=0.8,
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
    assert transaction.transaction_date == expected
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_rejects_indivisible_ocr_date_and_description() -> None:
    compound_word = _word("2701/02/26 Merchant", 20.0, 90.0, 30.0, source="ocr")
    compound = Cell(
        page_number=1,
        bbox=compound_word.bbox,
        text=compound_word.text,
        words=(compound_word,),
        confidence=0.8,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(compound, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert transaction.description == "Merchant"
    assert transaction.ambiguities == ("missing_date_cell",)
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_rejects_indivisible_ocr_date_between_description_fragments() -> None:
    compound_word = _word(
        "First 7828/01/26 Merchant",
        20.0,
        90.0,
        30.0,
        source="ocr",
    )
    compound = Cell(
        page_number=1,
        bbox=compound_word.bbox,
        text=compound_word.text,
        words=(compound_word,),
        confidence=0.8,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(compound, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert transaction.description == "First Merchant"
    assert transaction.ambiguities == ("missing_date_cell",)
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_keeps_invalid_date_when_boundary_ocr_word_is_indivisible() -> None:
    artifact = _cell("₪", 0, 30.0)
    compound_word = _word("First 7828/01/26 Merchant", 20.0, 90.0, 30.0, source="ocr")
    compound = Cell(
        page_number=1,
        bbox=compound_word.bbox,
        text=compound_word.text,
        words=(compound_word,),
        confidence=0.8,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(artifact, compound, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date is None
    assert transaction.description == "First Merchant"
    assert transaction.ambiguities == (
        "invalid_transaction_date",
        "transaction_date:invalid_date",
    )
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_recovers_description_spilled_into_ocr_date_band() -> None:
    date_word = _word("01/02/26", 0.0, 30.0, 30.0, source="ocr")
    merchant_word = _word("Merchant", 32.0, 70.0, 30.0, source="ocr")
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 70.0, 40.0),
        text="01/02/26 Merchant",
        words=(date_word, merchant_word),
        confidence=0.8,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(compound, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 2, 1)
    assert transaction.description == "Merchant"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_recovers_leading_merchant_word_from_digital_date_cell() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="26/06/26 דלק",
        words=(
            _word("דלק", 39.8, 47.0, 30.0),
            _word("26/06/26", 50.0, 82.0, 30.0),
        ),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 35.0, 40.0),
        text="מנטה עוקף חדרה",
        words=(
            _word("חדרה", 0.0, 10.0, 30.0),
            _word("עוקף", 12.0, 22.0, 30.0),
            _word("מנטה", 24.0, 34.0, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description_cell, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    assert result.transactions[0].description == "דלק מנטה עוקף חדרה"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_recovers_description_beside_separate_date_layout_marker() -> None:
    marker = Glyph(
        char="6",
        bbox=(64.7, 30.0, 66.3, 40.0),
        origin=(64.7, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    spilled_description = "Fuel"
    spilled_glyphs = _glyphs(spilled_description, 39.8, 30.0)
    date_glyphs = _glyphs("26/06/26", 55.0, 30.0)
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="6 26/06/26 Fuel",
        glyphs=(*spilled_glyphs, *date_glyphs, marker),
        words=(
            _word(spilled_description, 39.8, 43.8, 30.0),
            _word("26/06/26", 55.0, 62.8, 30.0),
            _word("6", 64.7, 66.3, 30.0),
        ),
        confidence=1.0,
    )
    description = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 35.0, 40.0),
        text="Station",
        glyphs=_glyphs("Station", 5.0, 30.0),
        words=(_word("Station", 5.0, 11.8, 30.0),),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2026, 6, 26)
    assert transaction.description == "Station Fuel"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_preserves_punctuation_in_date_boundary_description() -> None:
    marker = Glyph(
        char="6",
        bbox=(64.7, 30.0, 66.3, 40.0),
        origin=(64.7, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    spilled_description = "Fuel-Market"
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text=f"6 26/06/26 {spilled_description}",
        glyphs=(
            *_glyphs(spilled_description, 39.8, 30.0),
            *_glyphs("26/06/26", 55.0, 30.0),
            marker,
        ),
        words=(
            _word(spilled_description, 39.8, 50.8, 30.0),
            _word("26/06/26", 55.0, 62.8, 30.0),
            _word("6", 64.7, 66.3, 30.0),
        ),
        confidence=1.0,
    )
    description = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 35.0, 40.0),
        text="Station",
        glyphs=_glyphs("Station", 5.0, 30.0),
        words=(_word("Station", 5.0, 11.8, 30.0),),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.description == "Station Fuel-Market"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_claims_marker_beside_reordered_rtl_spill() -> None:
    marker = Glyph(
        char="6",
        bbox=(64.7, 30.0, 66.3, 40.0),
        origin=(64.7, 39.0),
        font="SyntheticIcon",
        size=10.0,
        source="digital",
        confidence=1.0,
    )
    date_cell = Cell(
        page_number=1,
        bbox=(39.8, 30.0, 90.0, 40.0),
        text="6 26/06/26 א ב",
        glyphs=(*_glyphs("אב", 39.8, 30.0), *_glyphs("26/06/26", 55.0, 30.0), marker),
        words=(
            _word("בא", 39.8, 41.8, 30.0),
            _word("26/06/26", 55.0, 62.8, 30.0),
            _word("6", 64.7, 66.3, 30.0),
        ),
        confidence=1.0,
    )
    description = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 35.0, 40.0),
        text="Station",
        glyphs=_glyphs("Station", 5.0, 30.0),
        words=(_word("Station", 5.0, 11.8, 30.0),),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.description == "Station בא"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_recovers_adjacent_suffix_without_category_text() -> None:
    category_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 50.0, 40.0),
        text='בע " מ תקשורת',
        words=(
            _word("תקשורת", 2.0, 20.0, 30.0),
            _word("מ", 35.0, 39.0, 30.0),
            _word('"', 39.0, 42.0, 30.0),
            _word("בע", 42.0, 50.1, 30.0),
        ),
        confidence=1.0,
    )
    description_cell = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 100.0, 40.0),
        text="חברת פרטנר תקשורת",
        words=(
            _word("תקשורת", 50.0, 66.0, 30.0),
            _word("פרטנר", 68.0, 83.0, 30.0),
            _word("חברת", 85.0, 99.0, 30.0),
        ),
        confidence=1.0,
    )
    suffix = Cell(
        page_number=1,
        bbox=(80.0, 41.0, 90.0, 51.0),
        text=")ה",
        words=(_word("ה", 81.0, 86.0, 41.0), _word(")", 86.0, 89.0, 41.0)),
        confidence=1.0,
    )
    category_continuation = Cell(
        page_number=1,
        bbox=(10.0, 41.0, 20.0, 51.0),
        text="ומח",
        words=(_word("ומח", 10.0, 20.0, 41.0),),
        confidence=1.0,
    )
    continuation = _row(suffix, category_continuation).model_copy(
        update={"diagnostics": ("subordinate_auxiliary_continuation",)}
    )
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                category_cell,
                description_cell,
                _cell("24/06/2026", 2, 30.0),
                _cell("140.59", 3, 30.0),
            ),
            continuation,
        ),
        headers=("Category", "Merchant", "Transaction date", "Amount"),
    )

    result = normalize_statement(_discovery(region, "140.59", "ILS"))

    assert result.transactions[0].description == "חברת פרטנר תקשורת בע״מ (ה)"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_restores_description_space_from_positioned_evidence() -> None:
    visible = "BACKBLAZE INC"
    description = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 90.0, 40.0),
        text="BACKBLAZEINC",
        glyphs=_glyphs(visible, 50.0, 30.0),
        words=(
            _word("BACKBLAZE", 50.0, 58.8, 30.0),
            _word("INC", 60.0, 62.8, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (_row(_cell("24/06/2026", 0, 30.0), description, _cell("15.49", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS"))

    assert result.transactions[0].description == "BACKBLAZE INC"
    assert result.transactions[0].ambiguities == ()


def test_normalize_statement_preserves_distant_numeric_reference_inside_field() -> None:
    original = Cell(
        page_number=1,
        bbox=(50.0, 30.0, 100.0, 40.0),
        text="$56.94PAYPAL",
        words=(
            _word("$", 50.0, 54.0, 30.0),
            _word("56.94", 55.0, 70.0, 30.0),
            _word("PAYPAL", 76.0, 98.0, 30.0),
        ),
        confidence=1.0,
    )
    description = Cell(
        page_number=1,
        bbox=(98.0, 30.0, 149.0, 40.0),
        text="*PRIVATEIN 4029357",
        words=(
            _word("*PRIVATEIN", 100.0, 125.0, 30.0),
            _word("4029357", 138.0, 149.0, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("170.57", 0, 30.0),
                original,
                description,
                _cell("19/06/2026", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "170.57", "ILS"))

    assert result.transactions[0].description == "PAYPAL *PRIVATEIN 4029357"
    assert result.transactions[0].merchant == "PAYPAL *PRIVATEIN 4029357"
    assert not result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize("glyph_backed", (False, True))
def test_normalize_statement_preserves_repeated_reference_with_row_evidence(
    glyph_backed: bool,
) -> None:
    rows: list[Row] = []
    for y, raw_date in ((30.0, "20/06/2026"), (50.0, "25/06/2026")):
        original = Cell(
            page_number=1,
            bbox=(50.0, y, 100.0, y + 10.0),
            text="$100.00OPENAI",
            words=(
                _word("$", 50.0, 54.0, y),
                _word("100.00", 55.0, 73.0, y),
                _word("OPENAI", 76.0, 98.0, y),
            ),
            glyphs=_glyphs("$100.00OPENAI", 50.0, y) if glyph_backed else (),
            confidence=1.0,
        )
        description = Cell(
            page_number=1,
            bbox=(98.0, y, 149.0, y + 10.0),
            text="*CHATGPTS .OPENAI",
            words=(
                _word("*CHATGPT", 100.0, 125.0, y),
                _word("S", 126.0, 130.0, y),
                _word(".", 141.0, 143.0, y),
                _word("OPENAI", 143.0, 149.0, y),
            ),
            confidence=1.0,
        )
        rows.append(
            _row(
                _cell("10.00", 0, y),
                original,
                description,
                _cell(raw_date, 3, y),
            )
        )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        tuple(rows),
    )

    result = normalize_statement(_discovery(region, "20.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "OPENAI *CHATGPT S . OPENAI",
        "OPENAI *CHATGPT S . OPENAI",
    )
    assert all(not transaction.ambiguities for transaction in result.transactions)


@pytest.mark.parametrize("suffix", (".HEALTH", "@HEALTH"))
def test_normalize_statement_preserves_uncorroborated_punctuation_prefixed_merchant_suffix(
    suffix: str,
) -> None:
    rows = tuple(
        _row(
            _cell(raw_date, 0, y),
            Cell(
                page_number=1,
                bbox=(50.0, y, 99.0, y + 10.0),
                text=f"INSURER {suffix}",
                words=(
                    _word("INSURER", 50.0, 68.0, y),
                    _word(suffix, 84.0, 99.0, y),
                ),
                confidence=1.0,
            ),
            _cell("10.00", 2, y),
        )
        for raw_date, y in (("20/06/2026", 30.0), ("25/06/2026", 50.0))
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
    )

    result = normalize_statement(_discovery(region, "20.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        f"INSURER {suffix}",
        f"INSURER {suffix}",
    )
    assert all(not transaction.ambiguities for transaction in result.transactions)


def test_normalize_statement_preserves_repeated_alphabetic_merchant_suffix() -> None:
    rows = tuple(
        _row(
            _cell(raw_date, 0, y),
            Cell(
                page_number=1,
                bbox=(50.0, y, 99.0, y + 10.0),
                text="INSURER LIFE HEALTH",
                words=(
                    _word("INSURER", 50.0, 64.0, y),
                    _word("LIFE", 78.0, 84.0, y),
                    _word("HEALTH", 85.0, 99.0, y),
                ),
                confidence=1.0,
            ),
            _cell("10.00", 2, y),
        )
        for raw_date, y in (("20/06/2026", 30.0), ("25/06/2026", 50.0))
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
    )

    result = normalize_statement(_discovery(region, "20.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "INSURER LIFE HEALTH",
        "INSURER LIFE HEALTH",
    )
    assert all(not transaction.ambiguities for transaction in result.transactions)


def test_normalize_statement_preserves_repeated_hyphenated_numeric_merchant_cluster() -> None:
    rows = tuple(
        _row(
            _cell(raw_date, 0, y),
            Cell(
                page_number=1,
                bbox=(50.0, y, 99.0, y + 10.0),
                text="STORE 42 912-184",
                words=(
                    _word("STORE", 50.0, 68.0, y),
                    _word("42", 70.0, 76.0, y),
                    _word("912-184", 90.0, 99.0, y),
                ),
                confidence=1.0,
            ),
            _cell("10.00", 2, y),
        )
        for raw_date, y in (("20/06/2026", 30.0), ("25/06/2026", 50.0))
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
    )

    result = normalize_statement(_discovery(region, "20.00", "ILS"))

    assert tuple(transaction.description for transaction in result.transactions) == (
        "STORE 42 912-184",
        "STORE 42 912-184",
    )


@pytest.mark.parametrize(
    ("logical_text", "physical_text", "expected"),
    (
        (". ב 8/0 6/2 6 - לא", "אל8/06/26 -ב .", date(2026, 6, 8)),
        (". ב 2 5/0 6/2 6 - לא", "אל25/06/26 -ב .", date(2026, 6, 25)),
    ),
)
def test_normalize_statement_recovers_fragmented_conversion_date_from_foreign_row(
    logical_text: str,
    physical_text: str,
    expected: date,
) -> None:
    conversion_evidence = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 40.0),
        text=logical_text,
        glyphs=_glyphs(physical_text, 100.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("$5.15", 1, 30.0),
                conversion_evidence,
                _cell("Foreign merchant", 3, 30.0),
                _cell("24/06/2026", 4, 30.0),
            ),
        ),
        headers=("Amount", "Original", "Conversion detail", "Merchant", "Date"),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    assert result.transactions[0].conversion_date == expected
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def _split_conversion_date_region(
    *,
    left_date_fragment: str = "26/0",
    right_date_fragment: str = "6/21",
    left_glyph_x: float | None = None,
    right_glyph_y: float = 30.0,
    transaction_date_text: str = "24/06/2021",
    right_role: ColumnRole = ColumnRole.UNKNOWN,
    left_context: str = "converted to ILS",
) -> TableRegion:
    left_physical = f"{left_context} {left_date_fragment}"
    positioned_left_x = 145.0 - len(left_physical) if left_glyph_x is None else left_glyph_x
    left_fragment = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 145.0, 60.0),
        text=f"{left_date_fragment} converted to ILS",
        glyphs=_glyphs(left_physical, positioned_left_x, 30.0),
        confidence=1.0,
    )
    right_fragment = Cell(
        page_number=1,
        bbox=(145.0, 30.0, 190.0, 60.0),
        text=f"Country . on {right_date_fragment}",
        glyphs=_glyphs(f"{right_date_fragment} - on . Country", 145.2, right_glyph_y),
        confidence=1.0,
    )
    return _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            right_role,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("19.63", 0, 30.0),
                _cell("$5.99", 1, 30.0),
                left_fragment,
                right_fragment,
                _cell("Foreign merchant", 4, 30.0),
                _cell(transaction_date_text, 5, 30.0),
            ),
        ),
        headers=(
            "Amount",
            "Original amount",
            "Card presented",
            "Transaction detail",
            "Merchant",
            "Date",
        ),
    )


def _equivalent_conversion_date_rate_region() -> TableRegion:
    same_cell = _cell(
        "Converted on 26.06.21",
        2,
        30.0,
        glyphs=_glyphs("Converted on 26.06.21", 100.0, 30.0),
    )
    boundary = 195.0
    left_cell = Cell(
        page_number=1,
        bbox=(150.0, 30.0, boundary, 60.0),
        text="26.0 converted at rate 2.9660",
        glyphs=(
            *_glyphs("exchange rate 2.9660", 150.0, 30.0),
            *_glyphs("26.0", boundary - len("26.0"), 50.0),
        ),
        confidence=1.0,
    )
    right_cell = Cell(
        page_number=1,
        bbox=(boundary, 30.0, 240.0, 60.0),
        text="Country on 6.21",
        glyphs=_glyphs("6.21", boundary + 0.2, 50.0),
        confidence=1.0,
    )
    row = _row(
        _cell("19.63", 0, 30.0),
        _cell("$5.99", 1, 30.0),
        same_cell,
        left_cell,
        right_cell,
        _cell("Synthetic merchant", 5, 30.0),
        _cell("24.06.2021", 6, 30.0),
    )
    return _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (row,),
        headers=(
            "Amount",
            "Original amount",
            "Conversion detail",
            "Conversion date Exchange rate",
            "Conversion detail",
            "Merchant",
            "Date",
        ),
    )


def test_normalize_statement_recovers_conversion_date_split_across_adjacent_unknown_cells() -> None:
    region = _split_conversion_date_region()

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))

    assert result.transactions[0].conversion_date == date(2021, 6, 26)
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_equivalent_conversion_sources_keep_date_and_rate_claims_disjoint() -> None:
    region = _equivalent_conversion_date_rate_region()

    result = normalize_statement(
        _discovery(
            region,
            "19.63",
            "ILS",
            year_context=2021,
            year_context_style=DateTokenStyle.DAY_FIRST_DOT,
        )
    )

    transaction = result.transactions[0]
    assert transaction.conversion_date == date(2021, 6, 26)
    assert transaction.foreign_exchange is not None
    assert transaction.foreign_exchange.exchange_rate is not None
    assert transaction.foreign_exchange.exchange_rate.value == Decimal("2.9660")
    assert transaction.ambiguities == ()
    assert not {
        "invalid_conversion_date",
        "unparsed_conversion_date_candidate",
        "unparsed_exchange_rate_candidate",
        "unconsumed_transaction_semantic_text",
    } & set(transaction.ambiguities)
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("left_glyph_x", "right_glyph_y"),
    ((100.0, 30.0), (None, 50.0)),
)
def test_normalize_statement_rejects_cross_cell_date_fragments_without_geometric_adjacency(
    left_glyph_x: float | None,
    right_glyph_y: float,
) -> None:
    region = _split_conversion_date_region(
        left_glyph_x=left_glyph_x,
        right_glyph_y=right_glyph_y,
    )

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))

    assert result.transactions[0].conversion_date is None
    assert result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize("transaction_date_text", ("24/06/2021", "Unreadable"))
def test_normalize_statement_rejects_cross_cell_conversion_date_without_near_anchor(
    transaction_date_text: str,
) -> None:
    region = _split_conversion_date_region(
        left_date_fragment="01/0",
        right_date_fragment="1/21",
        transaction_date_text=transaction_date_text,
    )

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))

    assert result.transactions[0].conversion_date is None
    assert result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_recovers_split_conversion_date_with_explicit_peer_role() -> None:
    region = _split_conversion_date_region(right_role=ColumnRole.CONVERSION_DATE)

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))

    assert result.transactions[0].conversion_date == date(2021, 6, 26)
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_cross_cell_conversion_date_rejects_unrepresented_numeric_atoms() -> None:
    region = _split_conversion_date_region(left_context="reference 999 converted to ILS")
    row = region.rows[0]
    ledger = EvidenceLedger.from_rows((row,))

    year_context = _discovery(region, "19.63", "ILS", year_context=2021).date_year_context
    assert year_context is not None
    parsed_evidence = parsed_cross_cell_conversion_evidence(
        row,
        region,
        ledger,
        year_context,
        date(2021, 6, 24),
    )

    assert parsed_evidence == ()


@pytest.mark.parametrize(
    ("explicit_date", "expected_status"),
    (("26/06/2021", Status.RECONCILED), ("25/06/2021", Status.UNRECONCILED)),
)
def test_split_conversion_date_is_audited_against_explicit_conversion_date(
    explicit_date: str,
    expected_status: Status,
) -> None:
    left_physical = "converted to ILS 26/0"
    left_fragment = Cell(
        page_number=1,
        bbox=(150.0, 30.0, 195.0, 60.0),
        text="26/0 converted to ILS",
        glyphs=_glyphs(left_physical, 195.0 - len(left_physical), 30.0),
        confidence=1.0,
    )
    right_fragment = Cell(
        page_number=1,
        bbox=(195.0, 30.0, 240.0, 60.0),
        text="Country . on 6/21",
        glyphs=_glyphs("6/21 - on . Country", 195.2, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("19.63", 0, 30.0),
                _cell("$5.99", 1, 30.0),
                _cell(explicit_date, 2, 30.0),
                left_fragment,
                right_fragment,
                _cell("Foreign merchant", 5, 30.0),
                _cell("24/06/2021", 6, 30.0),
            ),
        ),
        headers=(
            "Amount",
            "Original amount",
            "Conversion date",
            "Card presented",
            "Transaction detail",
            "Merchant",
            "Date",
        ),
    )

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))
    transaction = result.transactions[0]

    assert transaction.conversion_date == date.fromisoformat(
        "2021-06-26" if expected_status is Status.RECONCILED else "2021-06-25"
    )
    assert result.reconciliation.status is expected_status
    assert transaction.ambiguities == (
        (
            "conflicting_conversion_date_evidence",
            "unconsumed_transaction_semantic_text",
        )
        if expected_status is Status.UNRECONCILED
        else ()
    )


@pytest.mark.parametrize(
    ("second_left", "second_right"),
    (("32/0", "6/21"), ("01/0", "1/21")),
)
def test_split_conversion_date_requires_one_raw_candidate_before_parsing(
    second_left: str,
    second_right: str,
) -> None:
    def fragment_cell(
        column: int,
        physical: str,
        *,
        align_right: bool,
    ) -> Cell:
        boundary = column * 50.0 + (45.0 if align_right else -5.0)
        x0 = boundary - len(physical) if align_right else boundary + 0.2
        return Cell(
            page_number=1,
            bbox=(column * 50.0, 30.0, column * 50.0 + 45.0, 60.0),
            text=physical,
            glyphs=_glyphs(physical, x0, 30.0),
            confidence=1.0,
        )

    first_left = "converted to ILS 26/0"
    first_right = "6/21 - Country"
    second_left_text = f"converted to ILS {second_left}"
    second_right_text = f"{second_right} - Country"
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("19.63", 0, 30.0),
                _cell("$5.99", 1, 30.0),
                fragment_cell(2, first_left, align_right=True),
                fragment_cell(3, first_right, align_right=False),
                fragment_cell(4, second_left_text, align_right=True),
                fragment_cell(5, second_right_text, align_right=False),
                _cell("Foreign merchant", 6, 30.0),
                _cell("24/06/2021", 7, 30.0),
            ),
        ),
        headers=(
            "Amount",
            "Original amount",
            "Detail A",
            "Detail B",
            "Detail C",
            "Detail D",
            "Merchant",
            "Date",
        ),
    )

    result = normalize_statement(_discovery(region, "19.63", "ILS", year_context=2021))

    assert result.transactions[0].conversion_date is None
    assert "unparsed_conversion_date_candidate" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize(
    "physical_text",
    ("8/06/26 9/06/26", "32/06/26", "25/06-26"),
)
def test_normalize_statement_marks_unresolved_conversion_date_candidate(
    physical_text: str,
) -> None:
    conversion_evidence = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 40.0),
        text=physical_text,
        glyphs=_glyphs(physical_text, 100.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("$5.15", 1, 30.0),
                conversion_evidence,
                _cell("Foreign merchant", 3, 30.0),
                _cell("24/06/2026", 4, 30.0),
            ),
        ),
        headers=("Amount", "Original", "Conversion detail", "Merchant", "Date"),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    assert result.transactions[0].conversion_date is None
    assert "unparsed_conversion_date_candidate" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_does_not_treat_unrelated_date_as_conversion_on_domestic_row() -> None:
    note = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 40.0),
        text="08/06/26",
        glyphs=_glyphs("08/06/26", 100.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("15.49", 1, 30.0),
                note,
                _cell("Domestic merchant", 3, 30.0),
                _cell("24/06/2026", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    assert result.transactions[0].conversion_date is None
    assert "unparsed_conversion_date_candidate" not in result.transactions[0].ambiguities


@pytest.mark.parametrize("statement_year", (None, 2023))
def test_conversion_date_uses_nearby_transaction_year_across_statement_year_boundary(
    statement_year: int | None,
) -> None:
    conversion_evidence = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 140.0, 40.0),
        text="Converted on 16/11/22",
        glyphs=_glyphs("Converted on 16/11/22", 100.0, 30.0),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("197.22", 0, 30.0),
                _cell("GBP 47.94", 1, 30.0),
                conversion_evidence,
                _cell("Foreign merchant", 3, 30.0),
                _cell("15/11/2022", 4, 30.0),
            ),
        ),
        headers=("Amount", "Original", "Conversion detail", "Merchant", "Date"),
    )

    result = normalize_statement(_discovery(region, "197.22", "ILS", year_context=statement_year))

    assert result.transactions[0].conversion_date == date(2022, 11, 16)
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("raw_dates", "descriptions"),
    (
        (("13/03/26", "20/03/26"), ("First", "Second")),
        (("26/03/13", "26/03/20"), ("First", "Second")),
    ),
)
def test_normalize_statement_preserves_proven_unanchored_short_dates_without_guessing_century(
    raw_dates: tuple[str, str],
    descriptions: tuple[str, str],
) -> None:
    rows = tuple(
        _row(
            Cell(
                page_number=1,
                bbox=(20.0, y, 90.0, y + 10.0),
                text=f"{raw_date} {description}",
                words=(
                    _word(raw_date, 20.0, 48.0, y, source="ocr"),
                    _word(description, 52.0, 90.0, y, source="ocr"),
                ),
                confidence=0.8,
            ),
            _cell(amount, 2, y),
        )
        for raw_date, description, amount, y in zip(
            raw_dates,
            descriptions,
            ("2.00", "4.00"),
            (30.0, 50.0),
            strict=True,
        )
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
    )

    result = normalize_statement(_discovery(region, "6.00", "ILS"))

    assert tuple(transaction.transaction_date for transaction in result.transactions) == (
        None,
        None,
    )
    assert tuple(transaction.description for transaction in result.transactions) == descriptions
    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert tuple(transaction.evidence[0].raw_text for transaction in result.transactions) == tuple(
        f"{raw_date} {description}"
        for raw_date, description in zip(raw_dates, descriptions, strict=True)
    )
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_keeps_unanchored_short_date_ordering_ambiguity_explicit() -> None:
    rows = tuple(
        _row(
            Cell(
                page_number=1,
                bbox=(20.0, y, 90.0, y + 10.0),
                text=f"{raw_date} {description}",
                words=(
                    _word(raw_date, 20.0, 48.0, y, source="ocr"),
                    _word(description, 52.0, 90.0, y, source="ocr"),
                ),
                confidence=0.8,
            ),
            _cell(amount, 2, y),
        )
        for raw_date, description, amount, y in (
            ("01/02/26", "First", "2.00", 30.0),
            ("01/03/26", "Second", "4.00", 50.0),
        )
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        rows,
    )

    result = normalize_statement(_discovery(region, "6.00", "ILS"))

    assert len(result.transactions) == 2
    assert tuple(transaction.description for transaction in result.transactions) == (
        "First",
        "Second",
    )
    assert all(
        "invalid_transaction_date" in transaction.ambiguities for transaction in result.transactions
    )
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_flags_permuted_overlapping_date_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        glyphs=(*_glyphs("MERCHANT", 0.0, 30.0), *_glyphs("01/02/2026", 60.0, 30.0)),
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
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_accepts_order_preserving_overlapping_date_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        glyphs=(*_glyphs("MERCHANT", 0.0, 30.0), *_glyphs("01/02/2026", 60.0, 30.0)),
        confidence=1.0,
    )
    assigned_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 1/0 2/2 0 2 6",
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(compound, assigned_date, _cell("4.00", 2, 30.0)),),
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


def test_normalize_statement_rejects_composite_word_as_overlapping_date_evidence() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        words=(_word("MERCHANT01/02/2026", 0.0, 100.0, 30.0),),
        confidence=1.0,
    )
    assigned_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 0/1 2/2 0 2 6",
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(compound, assigned_date, _cell("4.00", 2, 30.0)),),
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


def test_normalize_statement_does_not_hide_unrelated_numeric_assigned_date_cell() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT01/02/2026",
        glyphs=(*_glyphs("MERCHANT", 0.0, 30.0), *_glyphs("01/02/2026", 60.0, 30.0)),
        confidence=1.0,
    )
    unrelated_numeric = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="42",
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
        (_row(compound, unrelated_numeric, amount),),
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
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_normalize_statement_assigns_overlapping_conversion_date_once() -> None:
    compound_text = "MERCHANT25/06/2026"
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text=compound_text,
        glyphs=_glyphs(compound_text, 52.0, 30.0),
        confidence=1.0,
    )
    damaged_conversion = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="2 5/0 6/2 0 2 6",
        confidence=1.0,
    )
    row = _row(
        compound,
        damaged_conversion,
        _cell("15.49", 2, 30.0),
        _cell("24/06/2026", 3, 30.0),
        _cell("$5.15", 4, 30.0),
    )
    region = _region(
        (
            ColumnRole.DESCRIPTION,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AMOUNT,
            ColumnRole.DATE,
            ColumnRole.ORIGINAL_AMOUNT,
        ),
        (row,),
    )
    columns = tuple(
        column.model_copy(update={"bbox": bbox})
        for column, bbox in zip(
            region.table_schema.columns,
            (
                (0.0, 10.0, 59.0, 200.0),
                (60.0, 10.0, 100.0, 200.0),
                (110.0, 10.0, 149.0, 200.0),
                (150.0, 10.0, 190.0, 200.0),
                (200.0, 10.0, 240.0, 200.0),
            ),
            strict=True,
        )
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date == date(2026, 6, 25)
    assert transaction.description == "MERCHANT"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_clips_semantic_conversion_date_from_description() -> None:
    conversion_detail = Cell(
        page_number=1,
        bbox=(100.0, 30.0, 149.0, 40.0),
        text="2.9660 25/06/26",
        words=(
            _word("2.9660", 100.0, 115.0, 30.0),
            _word("25/06/26", 141.0, 149.0, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.UNKNOWN,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("15.49", 0, 30.0),
                _cell("$5.15", 1, 30.0),
                conversion_detail,
                _cell("Merchant", 3, 30.0).model_copy(
                    update={"words": (_word("Merchant", 150.0, 190.0, 30.0),)}
                ),
                _cell("24/06/26", 4, 30.0),
            ),
        ),
        headers=("Amount", "Original", "Conversion date", "Merchant", "Date"),
    )

    result = normalize_statement(_discovery(region, "15.49", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.conversion_date == date(2026, 6, 25)
    assert transaction.description == "Merchant"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_flags_numeric_merchant_clipped_from_description() -> None:
    compound = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 100.0, 40.0),
        text="MERCHANT401/02/2026",
        glyphs=(*_glyphs("MERCHANT4", 0.0, 30.0), *_glyphs("01/02/2026", 60.0, 30.0)),
        words=(_word("MERCHANT401/02/2026", 0.0, 100.0, 30.0),),
        confidence=1.0,
    )
    damaged_date = Cell(
        page_number=1,
        bbox=(60.0, 30.0, 100.0, 40.0),
        text="0 0/1 2/2 0 2 6",
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(compound, damaged_date, _cell("4.00", 2, 30.0)),),
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
    assert transaction.description == "MERCHANT"
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


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


def test_normalize_statement_removes_glyph_proven_duplicate_date_prefix() -> None:
    duplicated_prefix = _glyphs("012", 46.0, 30.0)
    description = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 49.0, 40.0),
        text="MERCHANT 012",
        words=(_word("MERCHANT", 0.0, 35.0, 30.0), _word("012", 46.0, 49.0, 30.0)),
        confidence=1.0,
    )
    valid_date = "24/01/2022"
    date_cell = Cell(
        page_number=1,
        bbox=(46.0, 30.0, 90.0, 40.0),
        text=f"012{valid_date}",
        glyphs=(*duplicated_prefix, *_glyphs(valid_date, 51.0, 30.0)),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.DATE, ColumnRole.AMOUNT),
        (_row(description, date_cell, _cell("4.00", 2, 30.0)),),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2022, 1, 24)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


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


def test_normalize_statement_extracts_boundary_date_after_punctuated_merchant() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("MERCHANT S.A.30/06/2025", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2025, 6, 30)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


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


def test_normalize_statement_rejects_untyped_integer_before_date_year_resolution() -> None:
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
    assert "transaction_date:invalid_date" in transaction.ambiguities
    assert "unconsumed_transaction_semantic_text" in transaction.ambiguities


def test_normalize_statement_accepts_explicit_full_date_outside_short_date_context() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("31/12/2025", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("4.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "4.00", "ILS", year_context=2026))

    transaction = result.transactions[0]
    assert transaction.transaction_date == date(2025, 12, 31)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_accepts_ocr_full_date_outside_short_date_context() -> None:
    date_word = _word("31/12/2025", 0.0, 40.0, 30.0, source="ocr")
    date_cell = Cell(
        page_number=1,
        bbox=date_word.bbox,
        text=date_word.text,
        words=(date_word,),
        confidence=0.8,
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
    assert transaction.transaction_date == date(2025, 12, 31)
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


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


def test_normalize_statement_excludes_printed_total_row_retained_in_region() -> None:
    transaction = _row(
        _cell("01/02/2026", 0, 30.0),
        _cell("Clean", 1, 30.0),
        _cell("2.00", 2, 30.0),
    )
    total_row = _row(
        _cell("Total", 1, 50.0),
        _cell("2.00", 2, 50.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (transaction, total_row),
    )
    discovery = _discovery(region, "2.00", "ILS")
    group = discovery.groups[0]
    printed_total = group.printed_total.model_copy(
        update={
            "label_evidence": EvidenceReference(
                page_number=1,
                bbox=total_row.cells[0].bbox,
                raw_text="Total",
            ),
            "value_evidence": EvidenceReference(
                page_number=1,
                bbox=total_row.cells[1].bbox,
                raw_text="2.00",
            ),
        }
    )
    discovery = discovery.model_copy(
        update={"groups": (group.model_copy(update={"printed_total": printed_total}),)}
    )

    result = normalize_statement(discovery)

    assert len(result.transactions) == 1
    assert result.row_results[1].diagnostics == ("printed_total_row",)
    assert "rows_not_emitted:1" not in result.diagnostics
    assert result.reconciliation.status is Status.RECONCILED


def test_normalize_statement_does_not_exclude_tall_row_near_printed_total() -> None:
    transaction = _row(
        Cell(
            page_number=1,
            bbox=(0.0, 30.0, 40.0, 55.0),
            text="01/02/2026",
            confidence=1.0,
        ),
        _cell("Clean", 1, 30.0),
        _cell("2.00", 2, 30.0),
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (transaction,),
    )
    discovery = _discovery(region, "2.00", "ILS")
    group = discovery.groups[0]
    printed_total = group.printed_total.model_copy(
        update={
            "label_evidence": EvidenceReference(
                page_number=1,
                bbox=(50.0, 45.0, 90.0, 55.0),
                raw_text="Total",
            ),
            "value_evidence": EvidenceReference(
                page_number=1,
                bbox=(100.0, 45.0, 140.0, 55.0),
                raw_text="2.00",
            ),
        }
    )
    discovery = discovery.model_copy(
        update={"groups": (group.model_copy(update={"printed_total": printed_total}),)}
    )

    result = normalize_statement(discovery)

    assert len(result.transactions) == 1
    assert result.row_results[0].diagnostics == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_unknown_band_with_second_money_cell_retains_billed_row_as_ambiguous() -> None:
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

    assert len(result.transactions) == 1
    assert "unresolved_relevant_cell" in result.transactions[0].ambiguities
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_zero_billed_row_is_retained_as_noncontributing_evidence() -> None:
    region = _region(
        (
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.DESCRIPTION,
            ColumnRole.DATE,
        ),
        (
            _row(
                _cell("5133776", 0, 30.0),
                _cell("ILS 0.00", 1, 30.0),
                _cell("ILS 22.29", 2, 30.0),
                _cell("Card fee", 3, 30.0),
                _cell("01/02/2026", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "ILS 0.00", "ILS"))

    assert result.transactions == ()
    assert result.row_results[0].diagnostics == ("noncontributing_zero_billed_row",)
    assert result.diagnostics == ()
    assert result.reconciliation.status is Status.RECONCILED
    assert result.reconciliation.groups[0].difference == Decimal("0.00")


def test_singleton_unknown_text_band_is_retained_with_semantic_ambiguity() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("London", 2, 30.0),
                _cell("Retail category", 3, 30.0),
                _cell("10.00", 4, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert len(result.transactions[0].evidence) == 5
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_repeated_header_backed_unknown_text_band_is_ancillary() -> None:
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
                _cell("First merchant", 1, 30.0),
                _cell("Retail", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
            _row(
                _cell("02/02/2026", 0, 50.0),
                _cell("Second merchant", 1, 50.0),
                _cell("Services", 2, 50.0),
                _cell("20.00", 3, 50.0),
            ),
        ),
        headers=("Date", "Description", "Category", "Amount"),
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert all(not transaction.ambiguities for transaction in result.transactions)
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("headers", "values"),
    (
        (
            ("Category", "Transaction detail", "Card presented", "Notes"),
            ("Retail", "Foreign refund", "No", "Subject to terms"),
        ),
        (
            ("ענף", "פירוט", "כרטיס הוצג", "הערות"),
            ("קמעונאות", "זיכוי חוץ", "לא", "כפוף לתקנון"),
        ),
        (
            ("Category", "Transaction detail", "Card presented", "Eligibility terms"),
            ("Retail", "Foreign refund", "No", "Previous month benefit"),
        ),
        (
            ("ענף", "פירוט", "כרטיס הוצג", "הזכאות חושבה לפי החיוב"),
            ("קמעונאות", "זיכוי חוץ", "לא", "שלך מחודש קודם"),
        ),
    ),
)
def test_explicit_singleton_ancillary_headers_are_claimed(
    headers: tuple[str, str, str, str],
    values: tuple[str, str, str, str],
) -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                *(_cell(value, index, 30.0) for index, value in enumerate(values, start=2)),
                _cell("10.00", 6, 30.0),
            ),
        ),
        headers=("Date", "Description", *headers, "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].description == "Merchant"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize("header", ("Transaction detail", "Card presented"))
def test_calendar_invalid_fragmented_date_in_explicit_ancillary_band_is_claimed(
    header: str,
) -> None:
    invalid_text = "31/02/26"
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/26", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell(
                    invalid_text,
                    2,
                    30.0,
                    glyphs=_glyphs(invalid_text, 100.0, 30.0),
                ),
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", header, "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS", year_context=2026))

    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("header", "value"),
    (
        ("Transaction detail", "USD 12.34"),
        ("Transaction detail", "Original amount: USD 12.34"),
        ("Transaction detail", "Original amount: 12.34"),
        ("Transaction detail", "FX USD 12.34"),
        ("Transaction detail", "Converted 03/04/2026"),
        ("Transaction detail", "Installment 1/3"),
        ("Notes", "03/04/2026"),
        ("Card presented", "1/3"),
    ),
)
def test_explicit_ancillary_header_cannot_hide_typed_semantic_evidence(
    header: str,
    value: str,
) -> None:
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
                _cell(value, 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", header, "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


@pytest.mark.parametrize(
    ("amount", "printed_total", "expected_kind", "expected_status"),
    (
        ("10.00", "10.00", TransactionKind.CHARGE, Status.UNRECONCILED),
        ("-10.00", "-10.00", TransactionKind.CREDIT, Status.RECONCILED),
    ),
)
def test_explicit_category_header_contributes_supported_category_semantics(
    amount: str,
    printed_total: str,
    expected_kind: TransactionKind,
    expected_status: Status,
) -> None:
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
                _cell("Refund", 2, 30.0),
                _cell(amount, 3, 30.0),
            ),
        ),
        headers=("Date", "Description", "Category", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, printed_total, "ILS"))
    transaction = result.transactions[0]

    assert transaction.category is TransactionCategory.REFUND
    assert transaction.kind is expected_kind
    assert result.reconciliation.status is expected_status
    assert ("category_sign_contradiction" in transaction.ambiguities) is (
        expected_status is Status.UNRECONCILED
    )


def test_repeated_unknown_profile_requires_an_alphanumeric_header() -> None:
    rows = (
        _row(
            _cell("01/02/2026", 0, 30.0),
            _cell("First merchant", 1, 30.0),
            _cell("London", 2, 30.0),
            _cell("Retail", 3, 30.0),
            _cell("10.00", 4, 30.0),
        ),
        _row(
            _cell("02/02/2026", 0, 50.0),
            _cell("Second merchant", 1, 50.0),
            _cell("Paris", 2, 50.0),
            _cell("Services", 3, 50.0),
            _cell("20.00", 4, 50.0),
        ),
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.LOCATION,
            ColumnRole.UNKNOWN,
            ColumnRole.AMOUNT,
        ),
        rows,
        headers=("Date", "Description", "City", "|", "Amount"),
    )
    unknown_column = region.table_schema.columns[3].model_copy(
        update={
            "source_cells": (
                region.table_schema.header_cells[3],
                rows[0].cells[3],
                rows[1].cells[3],
            )
        }
    )
    columns = (
        *region.table_schema.columns[:3],
        unknown_column,
        region.table_schema.columns[4],
    )
    region = region.model_copy(
        update={"table_schema": region.table_schema.model_copy(update={"columns": columns})}
    )

    result = normalize_statement(_discovery(region, "30.00", "ILS"))

    assert all(
        "unconsumed_transaction_semantic_text" in transaction.ambiguities
        for transaction in result.transactions
    )
    assert result.reconciliation.status is Status.UNRECONCILED


def test_unrecovered_date_description_boundary_text_is_semantically_unconsumed() -> None:
    date_cell = Cell(
        page_number=1,
        bbox=(0.0, 30.0, 40.0, 40.0),
        text="01/02/2026 Lost",
        words=(
            _word("01/02/2026", 0.0, 20.0, 30.0),
            _word("Lost", 25.0, 35.0, 30.0),
        ),
        confidence=1.0,
    )
    region = _region(
        (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                date_cell,
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].description == "Merchant"
    assert "unconsumed_description_boundary_text" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


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

    assert len(result.transactions) == 1
    assert "unresolved_relevant_cell" in result.transactions[0].ambiguities
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_plain_identifier_in_singleton_unknown_header_remains_ambiguous() -> None:
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

    assert len(result.transactions) == 1
    assert "unresolved_relevant_cell" in result.transactions[0].ambiguities
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_missing_description_retains_billed_transaction_with_semantic_ambiguity() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("10.00", 2, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].billed_amount == Decimal("10.00")
    assert result.transactions[0].description is None
    assert "missing_description_cell" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


def test_missing_description_role_is_an_explicit_semantic_ambiguity() -> None:
    region = _region(
        (ColumnRole.DATE, ColumnRole.AMOUNT),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("10.00", 1, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].description is None
    assert "missing_description_cell" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


def test_missing_date_role_is_an_explicit_semantic_ambiguity() -> None:
    region = _region(
        (ColumnRole.DESCRIPTION, ColumnRole.AMOUNT),
        (
            _row(
                _cell("Merchant", 0, 30.0),
                _cell("10.00", 1, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_date is None
    assert "missing_date_cell" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


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

    assert len(result.transactions) == 1
    assert "unmatched_cell" in result.transactions[0].ambiguities
    assert "unresolved_relevant_cell" in result.transactions[0].ambiguities
    assert "unconsumed_transaction_semantic_text" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
    assert result.reconciliation.status is Status.UNRECONCILED


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


def test_single_equal_domestic_original_value_inherits_billing_currency() -> None:
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
                _cell("Merchant", 1, 30.0),
                _cell("10.00", 2, 30.0),
                _cell("10.00", 3, 30.0),
            ),
        ),
        headers=("Date", "Description", "Original amount", "Billed amount"),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions[0].original_amount == Decimal("10.00")
    assert result.transactions[0].original_currency == "ILS"
    assert result.transactions[0].ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


def test_single_equal_original_value_with_conversion_evidence_keeps_currency_unknown() -> None:
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.EXCHANGE_RATE,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.AMOUNT,
        ),
        (
            _row(
                _cell("01/02/2026", 0, 30.0),
                _cell("Merchant", 1, 30.0),
                _cell("1.0000", 2, 30.0),
                _cell("10.00", 3, 30.0),
                _cell("10.00", 4, 30.0),
            ),
        ),
        headers=(
            "Date",
            "Description",
            "Exchange rate",
            "Original amount",
            "Billed amount",
        ),
    )

    result = normalize_statement(_discovery(region, "10.00", "ILS"))

    assert result.transactions[0].original_amount is None
    assert result.transactions[0].original_currency is None
    assert "original_amount:unknown_currency" in result.transactions[0].ambiguities
    assert result.reconciliation.status is Status.UNRECONCILED


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


def test_ocr_original_amount_is_repaired_by_exact_same_currency_billed_value() -> None:
    damaged_word = _word("1,601,00", 100.0, 140.0, 50.0, source="ocr")
    damaged_original = Cell(
        page_number=1,
        bbox=damaged_word.bbox,
        text=damaged_word.text,
        words=(damaged_word,),
        confidence=0.8,
    )
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
                _cell("OCR damaged", 1, 50.0),
                damaged_original,
                _cell("1,601.00", 3, 50.0),
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

    result = normalize_statement(_discovery(region, "1,631.00", "ILS"))

    transaction = result.transactions[1]
    assert transaction.original_amount == Decimal("1601.00")
    assert transaction.original_currency == "ILS"
    assert transaction.ambiguities == ()
    assert result.reconciliation.status is Status.RECONCILED


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


def test_normalize_statement_preserves_structured_table_fx_values() -> None:
    row = _row(
        _cell("01/02/2026", 0, 30.0),
        _cell("Purchase abroad", 1, 30.0),
        _cell("3.00", 2, 30.0),
        _cell("USD", 3, 30.0),
        _cell("11.00", 4, 30.0),
        _cell("ILS 1.69", 5, 30.0, glyphs=_glyphs("ILS 1.69", 250.0, 30.0)),
        _cell("2.9660", 6, 30.0, glyphs=_glyphs("2.9660", 300.0, 30.0)),
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
            ColumnRole.AUXILIARY_AMOUNT,
            ColumnRole.EXCHANGE_RATE,
        ),
        (row,),
        headers=(
            "Date",
            "Description",
            "Original amount",
            "Original currency",
            "Billed amount",
            "Foreign-currency fee",
            "Exchange rate",
        ),
    )

    result = normalize_statement(_discovery(region, "11.00", "ILS"))

    transaction = result.transactions[0]
    assert transaction.foreign_exchange is not None
    assert transaction.foreign_exchange.exchange_rate is not None
    assert transaction.foreign_exchange.exchange_rate.value == Decimal("2.9660")
    assert transaction.foreign_exchange.net_fee is not None
    assert transaction.foreign_exchange.net_fee.amount == Decimal("1.69")
    assert "unconsumed_transaction_semantic_text" not in transaction.ambiguities
    assert result.reconciliation.status is Status.RECONCILED


def test_prefixed_hebrew_clitic_rate_cue_preserves_normalized_output_provenance() -> None:
    rate_cell = _cell(
        "02/02/2026 2.9660",
        5,
        30.0,
        glyphs=_glyphs("02/02/2026 2.9660", 250.0, 30.0),
    )
    row = _row(
        _cell("01/02/2026", 0, 30.0),
        _cell("Synthetic purchase", 1, 30.0),
        _cell("3.00", 2, 30.0),
        _cell("USD", 3, 30.0),
        _cell("11.00", 4, 30.0),
        rate_cell,
    )
    region = _region(
        (
            ColumnRole.DATE,
            ColumnRole.DESCRIPTION,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.ORIGINAL_CURRENCY,
            ColumnRole.AMOUNT,
            ColumnRole.CONVERSION_DATE,
        ),
        (row,),
        headers=(
            "Date",
            "Description",
            "Original amount",
            "Original currency",
            "Billed amount",
            "תאריך המרה בשער המרה",
        ),
    )

    normalized = normalize_statement(_discovery(region, "11.00", "ILS"))

    transaction = normalized.transactions[0]
    assert transaction.foreign_exchange is not None
    assert transaction.foreign_exchange.exchange_rate is not None
    assert transaction.foreign_exchange.exchange_rate.value == Decimal("2.9660")
    assert transaction.foreign_exchange.exchange_rate.evidence == (
        EvidenceReference(
            page_number=rate_cell.page_number,
            bbox=rate_cell.bbox,
            raw_text=rate_cell.text,
        ),
    )
    assert transaction.ambiguities == ()
    assert normalized.reconciliation.status is Status.RECONCILED

    statement = StatementResult(
        status=normalized.reconciliation.status,
        transactions=normalized.transactions,
        groups=normalized.reconciliation.groups,
        source_name="synthetic.pdf",
        source_sha256="a" * 64,
        statement_id="a" * 64,
    )
    batch = BatchResult(status=statement.status, statements=(statement,))
    csv_rows = tuple(
        csv.DictReader(io.StringIO(transactions_csv_bytes(batch).decode("utf-8-sig"), newline=""))
    )

    assert len(csv_rows) == 1
    assert csv_rows[0]["exchange_rate"] == "2.966"
    assert csv_rows[0]["exchange_rate_source_page"] == "1"
    assert csv_rows[0]["exchange_rate_source_bbox"] == "1:250,30,290,40"


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


def test_negative_billed_adjustment_may_omit_unprinted_original_amount() -> None:
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
                _cell("Statement adjustment", 1, 30.0),
                _cell("-2.00", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "-2.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].billed_amount == Decimal("-2.00")
    assert result.transactions[0].original_amount is None
    assert "missing_original_amount_cell" not in result.row_results[0].diagnostics
    assert result.reconciliation.status is Status.RECONCILED


def test_positive_billed_row_retains_missing_original_amount_as_ambiguity() -> None:
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
                _cell("Merchant", 1, 30.0),
                _cell("2.00", 3, 30.0),
            ),
        ),
    )

    result = normalize_statement(_discovery(region, "2.00", "ILS"))

    assert len(result.transactions) == 1
    assert result.transactions[0].billed_amount == Decimal("2.00")
    assert result.transactions[0].original_amount is None
    assert "missing_original_amount_cell" in result.transactions[0].ambiguities
    assert result.reconciliation.groups[0].difference == Decimal("0.00")
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


@pytest.mark.parametrize(
    "continuation", ("Store 24", "7 Eleven", "123456", "USD", "123.45", "12/03", "2/6")
)
@pytest.mark.parametrize("split_cells", (False, True))
@pytest.mark.parametrize("wrapped_lines", (1, 2))
def test_page_evidence_keeps_complete_merchant_continuation(
    continuation: str,
    split_cells: bool,
    wrapped_lines: int,
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
        word(continuation, 35.0, 45.0 if split_cells else 72.0, 41.0),
        *((word("TAIL", 55.0, 72.0, 41.0),) if split_cells else ()),
        *((word("SECOND", 35.0, 72.0, 52.0),) if wrapped_lines == 2 else ()),
        word("02/02/2026", 0.0, 22.0, 71.0),
        word("Cafe", 35.0, 72.0, 71.0),
        word("₪20.00", 92.0, 120.0, 71.0),
        word("Total", 35.0, 72.0, 91.0),
        word("₪30.00", 92.0, 120.0, 91.0),
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
    expected = f"Long merchant {continuation}" + (" TAIL" if split_cells else "")
    expected += " SECOND" if wrapped_lines == 2 else ""
    assert result.transactions[0].description == expected
    assert result.transactions[0].merchant == expected
    assert result.transactions[1].description == "Cafe"
    assert result.reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("separate_detail", "continuation"),
    (
        (True, "BRANCH 84"),
        (True, "123456"),
        (True, "12/03"),
        (True, "Fee Services"),
        (False, "Fee"),
    ),
)
@pytest.mark.parametrize("wrapped_lines", (1, 2))
def test_page_evidence_keeps_merchant_before_conversion_detail_block(
    separate_detail: bool,
    continuation: str,
    wrapped_lines: int,
) -> None:
    detail_y = 41.0 + 11.0 * wrapped_lines
    next_y = detail_y + 22.0
    words = (
        _word("Date", 0.0, 22.0, 10.0),
        _word("Description", 35.0, 90.0, 10.0),
        _word("Original amount", 110.0, 145.0, 10.0),
        _word("Billed amount", 165.0, 200.0, 10.0),
        _word("01/02/2026", 0.0, 22.0, 30.0),
        _word("North Shop", 35.0, 90.0, 30.0),
        _word("$3.00", 110.0, 145.0, 30.0),
        _word("₪11.00", 165.0, 200.0, 30.0),
        _word(continuation if separate_detail else "Fee", 40.0, 90.0, 41.0),
        *((_word("SECOND", 40.0, 90.0, 52.0),) if wrapped_lines == 2 else ()),
        _word(
            "Fee conversion explanation" if separate_detail else "conversion explanation",
            35.0,
            145.0 if separate_detail else 90.0,
            detail_y,
        ),
        _word("Note tail", 40.0, 90.0, detail_y + 11.0),
        _word("02/02/2026", 0.0, 22.0, next_y),
        _word("South Shop", 35.0, 90.0, next_y),
        _word("₪20.00", 110.0, 145.0, next_y),
        _word("₪20.00", 165.0, 200.0, next_y),
        _word("Total", 35.0, 90.0, next_y + 20.0),
        _word("₪31.00", 165.0, 200.0, next_y + 20.0),
    )
    page = PageEvidence(
        page_number=1,
        width=210.0,
        height=140.0,
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

    result = normalize_statement(
        discover_statement(DocumentEvidence(source_sha256="e" * 64, pages=(page,)))
    )

    expected = "North Shop"
    if separate_detail:
        expected += f" {continuation}" + (" SECOND" if wrapped_lines == 2 else "")
    assert tuple(transaction.merchant for transaction in result.transactions) == (
        expected,
        "South Shop",
    )
    assert result.transactions[0].original_amount == Decimal("3.00")
    assert result.transactions[0].billed_amount == Decimal("11.00")
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
