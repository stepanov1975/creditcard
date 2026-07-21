from __future__ import annotations

import csv
import io
import json
import unicodedata
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

import ccparser.output as output_module
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ForeignExchangeDetails,
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
    write_batch_outputs,
    write_csv_atomic,
    write_json_atomic,
)


def _batch() -> BatchResult:
    rate_evidence = EvidenceReference(
        page_number=1,
        bbox=(40.0, 50.0, 70.0, 60.0),
        raw_text="exchange rate 2.9430",
    )
    fee_evidence = EvidenceReference(
        page_number=1,
        bbox=(40.0, 60.0, 70.0, 70.0),
        raw_text="fee ILS 0.88 at 3.00 percent",
    )
    discount_evidence = EvidenceReference(
        page_number=1,
        bbox=(40.0, 70.0, 70.0, 80.0),
        raw_text="discount ILS 0.59",
    )
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1234.5000"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        transaction_date=date(2026, 1, 2),
        conversion_date=date(2026, 1, 3),
        description='Cafe, "שָׁלוֹם"\nsecond line',
        category=TransactionCategory.PURCHASE,
        original_amount=Decimal("10.200"),
        original_currency="USD",
        installment_current=2,
        installment_total=3,
        foreign_exchange=ForeignExchangeDetails(
            exchange_rate=ExtractedDecimal(
                value=Decimal("2.9430"),
                evidence=(rate_evidence,),
            ),
            fee_percentage=ExtractedDecimal(
                value=Decimal("3.00"),
                evidence=(fee_evidence,),
            ),
            gross_fee=ExtractedMoney(
                amount=Decimal("0.88"),
                currency="ILS",
                evidence=(fee_evidence,),
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("0.59"),
                currency="ILS",
                evidence=(discount_evidence,),
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("0.29"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
                derivation="gross_fee_minus_discount",
            ),
        ),
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
    assert transaction["conversion_date"] == "2026-01-03"
    foreign_exchange = transaction["foreign_exchange"]
    assert foreign_exchange["exchange_rate"]["value"] == "2.943"
    assert foreign_exchange["fee_percentage"]["value"] == "3"
    assert foreign_exchange["gross_fee"]["amount"] == "0.88"
    assert foreign_exchange["fee_discount"]["amount"] == "0.59"
    assert foreign_exchange["net_fee"]["amount"] == "0.29"
    assert foreign_exchange["net_fee"]["derivation"] == "gross_fee_minus_discount"
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
    assert row["conversion_date"] == "2026-01-03"
    assert row["description"] == 'Cafe, "שָׁלוֹם"\nsecond line'
    assert row["exchange_rate"] == "2.943"
    assert row["foreign_currency_fee_percentage"] == "3"
    assert row["gross_foreign_currency_fee"] == "0.88"
    assert row["gross_foreign_currency_fee_currency"] == "ILS"
    assert row["foreign_currency_fee_discount"] == "0.59"
    assert row["net_foreign_currency_fee"] == "0.29"
    assert row["net_foreign_currency_fee_derivation"] == "gross_fee_minus_discount"
    assert row["exchange_rate_source_page"] == "1"
    assert row["exchange_rate_source_bbox"] == "1:40,50,70,60"
    assert row["source_page"] == "1"
    assert row["source_bbox"] == "1:10.25,20.5,30.75,40"
    assert row["diagnostic_codes"] == "batch_diagnostic|statement_diagnostic"


def test_transactions_csv_formats_large_and_signed_zero_values_without_rounding() -> None:
    batch = _batch()
    statement = batch.statements[0]
    transaction = statement.transactions[0].model_copy(
        update={
            "billed_amount": Decimal("123456789012345678901234567890.1200"),
            "original_amount": Decimal("-0.00"),
        }
    )
    batch = batch.model_copy(
        update={"statements": (statement.model_copy(update={"transactions": (transaction,)}),)}
    )

    with localcontext() as context:
        context.prec = 5
        rows = tuple(
            csv.DictReader(
                io.StringIO(
                    transactions_csv_bytes(batch).decode("utf-8-sig"),
                    newline="",
                )
            )
        )

    assert rows[0]["billed_amount"] == "123456789012345678901234567890.12"
    assert rows[0]["original_amount"] == "0"


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
    assert rows[0]["exchange_rate"] == ""
    assert rows[0]["net_foreign_currency_fee"] == ""


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
    evidence = EvidenceReference.model_construct(
        page_number=1,
        bbox=(float("nan"), 0.0, 1.0, 1.0),
        raw_text="synthetic",
    )
    transaction = Transaction(
        transaction_id="transaction-0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        evidence=(evidence,),
    )
    statement = StatementResult.model_construct(
        status=Status.UNRECONCILED,
        transactions=(transaction,),
        groups=(),
        diagnostics=(),
    )
    batch = BatchResult.model_construct(
        status=Status.UNRECONCILED,
        statements=(statement,),
        diagnostics=(),
    )

    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes(batch)
    with pytest.raises(ValueError, match="finite"):
        transactions_csv_bytes(batch)


@pytest.mark.parametrize("nonfinite", ("NaN", "Infinity", "-Infinity"))
def test_json_and_csv_defensively_reject_constructed_nonfinite_money(nonfinite: str) -> None:
    transaction = Transaction.model_construct(
        transaction_id="transaction-0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal(nonfinite),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
    )
    statement = StatementResult.model_construct(
        status=Status.UNRECONCILED,
        transactions=(transaction,),
        groups=(),
        diagnostics=(),
    )
    batch = BatchResult.model_construct(
        status=Status.UNRECONCILED,
        statements=(statement,),
        diagnostics=(),
    )

    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes(batch)
    with pytest.raises(ValueError, match="finite"):
        transactions_csv_bytes(batch)


@pytest.mark.parametrize("has_existing_pair", (False, True))
def test_batch_pair_writer_rolls_back_second_publish_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    has_existing_pair: bool,
) -> None:
    output_dir = tmp_path / "output"
    json_path = output_dir / "results.json"
    csv_path = output_dir / "transactions.csv"
    if has_existing_pair:
        output_dir.mkdir()
        json_path.write_bytes(b"old json bytes\n")
        csv_path.write_bytes(b"old csv bytes\r\n")
    old_json = json_path.read_bytes() if has_existing_pair else None
    old_csv = csv_path.read_bytes() if has_existing_pair else None
    original_replace = output_module.os.replace
    failed = False

    def fail_first_csv_publish(source: Path, destination: Path) -> None:
        nonlocal failed
        if Path(destination).name == "transactions.csv" and not failed:
            failed = True
            raise OSError("private second publish detail")
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "replace", fail_first_csv_publish)

    with pytest.raises(OSError, match="second publish"):
        write_batch_outputs(output_dir, _batch())

    assert (json_path.read_bytes() if json_path.exists() else None) == old_json
    assert (csv_path.read_bytes() if csv_path.exists() else None) == old_csv
    assert not tuple(output_dir.glob(".*.tmp"))


def test_batch_pair_writer_prerenders_both_before_output_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"

    def fail_csv_render(batch: BatchResult) -> bytes:
        del batch
        raise TypeError("private serialization detail")

    monkeypatch.setattr(output_module, "transactions_csv_bytes", fail_csv_render)

    with pytest.raises(TypeError, match="serialization"):
        write_batch_outputs(output_dir, _batch())

    assert not output_dir.exists()


def test_batch_pair_writer_rolls_back_fsync_failure_after_second_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    json_path = output_dir / "results.json"
    csv_path = output_dir / "transactions.csv"
    json_path.write_bytes(b"old json\n")
    csv_path.write_bytes(b"old csv\r\n")
    old_pair = (json_path.read_bytes(), csv_path.read_bytes())
    original_fsync = output_module.os.fsync
    calls = 0

    def fail_second_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("private second fsync detail")
        original_fsync(descriptor)

    monkeypatch.setattr(output_module.os, "fsync", fail_second_directory_fsync)

    with pytest.raises(OSError, match="second fsync"):
        write_batch_outputs(output_dir, _batch())

    assert (json_path.read_bytes(), csv_path.read_bytes()) == old_pair
