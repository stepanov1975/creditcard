from __future__ import annotations

import csv
import io
import json
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import ccparser.output as output_module
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.output import (
    CSV_COLUMNS,
    canonical_json_bytes,
    transactions_csv_bytes,
    write_csv_atomic,
    write_json_atomic,
)


def _batch() -> BatchResult:
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1234.5000"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        transaction_date=date(2026, 1, 2),
        description='Cafe, "שָׁלוֹם"\nsecond line',
        category=TransactionCategory.PURCHASE,
        original_amount=Decimal("10.200"),
        original_currency="USD",
        installment_current=2,
        installment_total=3,
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(10.25, 20.5, 30.75, 40.0),
                raw_text="\u05e9\u05b8\u05c1\u05dc\u05d5\u05b9\u05dd",
            ),
        ),
    )
    group = ReconciliationGroup(
        group_id="group-0001",
        currency="ILS",
        printed_total=Decimal("1234.5000"),
        calculated_total=Decimal("1234.5000"),
        difference=Decimal("0.0000"),
        transaction_ids=(transaction.transaction_id,),
        status=Status.RECONCILED,
    )
    statement = StatementResult(
        status=Status.RECONCILED,
        transactions=(transaction,),
        groups=(group,),
        diagnostics=("statement_diagnostic",),
        source_name="nested/statement.pdf",
        source_sha256="a" * 64,
        statement_id="a" * 64,
    )
    return BatchResult(
        status=Status.RECONCILED,
        statements=(statement,),
        diagnostics=("batch_diagnostic",),
    )


def _all_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(text for item in value.values() for text in _all_strings(item))
    if isinstance(value, list):
        return tuple(text for item in value for text in _all_strings(item))
    return ()


def test_canonical_json_is_stable_nfc_decimal_safe_and_has_one_newline() -> None:
    batch = _batch()

    first = canonical_json_bytes(batch)
    second = canonical_json_bytes(batch)
    payload = json.loads(first)

    assert first == second
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert first.decode("utf-8").startswith('{"diagnostics"')
    transaction = payload["statements"][0]["transactions"][0]
    assert transaction["billed_amount"] == "1234.5"
    assert transaction["original_amount"] == "10.2"
    assert transaction["transaction_date"] == "2026-01-02"
    assert all(unicodedata.is_normalized("NFC", text) for text in _all_strings(payload))


def test_transactions_csv_has_bom_fixed_columns_quoting_money_and_provenance() -> None:
    content = transactions_csv_bytes(_batch())

    assert content.startswith(b"\xef\xbb\xbf")
    rows = tuple(csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline="")))

    assert tuple(rows[0]) == CSV_COLUMNS
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "nested/statement.pdf"
    assert row["statement_id"] == "a" * 64
    assert row["group_id"] == "group-0001"
    assert row["billed_amount"] == "1234.5"
    assert row["original_amount"] == "10.2"
    assert row["description"] == 'Cafe, "שָׁלוֹם"\nsecond line'
    assert row["source_page"] == "1"
    assert row["source_bbox"] == "1:10.25,20.5,30.75,40"
    assert row["diagnostic_codes"] == "batch_diagnostic|statement_diagnostic"


@pytest.mark.parametrize(
    "batch",
    (
        BatchResult(
            status=Status.UNSUPPORTED,
            statements=(
                StatementResult(
                    status=Status.UNSUPPORTED,
                    transactions=(),
                    groups=(),
                    diagnostics=("unsupported_layout",),
                    source_name="unknown.pdf",
                    source_sha256="b" * 64,
                    statement_id="b" * 64,
                ),
            ),
            diagnostics=("batch_incomplete",),
        ),
        BatchResult(status=Status.UNSUPPORTED, statements=(), diagnostics=("no_pdf_files",)),
    ),
)
def test_transactions_csv_keeps_diagnostics_for_empty_results(batch: BatchResult) -> None:
    rows = tuple(
        csv.DictReader(io.StringIO(transactions_csv_bytes(batch).decode("utf-8-sig"), newline=""))
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "unsupported"
    assert rows[0]["diagnostic_codes"]


def test_atomic_writers_repeat_identically_and_do_not_replace_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "nested" / "results.json"
    csv_path = tmp_path / "nested" / "transactions.csv"
    batch = _batch()

    write_json_atomic(json_path, batch)
    write_csv_atomic(csv_path, batch)
    first_json = json_path.read_bytes()
    first_csv = csv_path.read_bytes()
    write_json_atomic(json_path, batch)
    write_csv_atomic(csv_path, batch)

    assert json_path.read_bytes() == first_json
    assert csv_path.read_bytes() == first_csv

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(output_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        write_json_atomic(json_path, BatchResult(status=Status.NOT_STATEMENT, statements=()))

    assert json_path.read_bytes() == first_json
    assert not tuple(json_path.parent.glob(".results.json.*.tmp"))


def test_canonical_json_rejects_non_finite_coordinates() -> None:
    transaction = Transaction(
        transaction_id="transaction-0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        evidence=(
            EvidenceReference(
                page_number=1,
                bbox=(float("nan"), 0.0, 1.0, 1.0),
                raw_text="synthetic",
            ),
        ),
    )
    batch = BatchResult(
        status=Status.UNRECONCILED,
        statements=(
            StatementResult(
                status=Status.UNRECONCILED,
                transactions=(transaction,),
                groups=(),
            ),
        ),
    )

    with pytest.raises(ValueError, match="range"):
        canonical_json_bytes(batch)
