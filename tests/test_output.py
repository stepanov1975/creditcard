from __future__ import annotations

import csv
import gc
import io
import json
import os
import stat
import traceback
import unicodedata
import weakref
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import BinaryIO, cast

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
    canonical_json_bytes,
    transactions_csv_bytes,
    write_batch_outputs,
    write_canonical_batch_json_stream,
    write_csv_atomic,
    write_json_atomic,
    write_output_pair_atomic,
    write_streaming_batch_outputs,
    write_transactions_csv_stream,
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
        description='Café, "שָׁלוֹם"\nsecond line',
        merchant="Café",
        category=TransactionCategory.PURCHASE,
        ambiguities=("ambiguous_date", "ambiguous_currency", "ambiguous_date"),
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
    transaction = transaction.model_copy(update={"description": 'Cafe\u0301, "שָׁלוֹם"\nsecond line'})
    group = ReconciliationGroup(
        group_id="group-0001",
        currency="ILS",
        printed_total=Decimal("1234.5000"),
        calculated_total=Decimal("1234.5000"),
        difference=Decimal("0.0000"),
        transaction_ids=(transaction.transaction_id,),
        status=Status.RECONCILED,
        diagnostics=("group_diagnostic",),
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


def _batch_with_empty_statement() -> BatchResult:
    batch = _batch()
    empty_statement = StatementResult(
        status=Status.UNSUPPORTED,
        transactions=(),
        groups=(),
        diagnostics=("empty_diagnostic",),
        source_name="empty.pdf",
        source_sha256="b" * 64,
        statement_id="b" * 64,
    )
    return batch.model_copy(update={"statements": (*batch.statements, empty_statement)})


def _non_statement_batch() -> BatchResult:
    return BatchResult(
        status=Status.NOT_STATEMENT,
        statements=(
            StatementResult(
                status=Status.NOT_STATEMENT,
                transactions=(),
                groups=(),
                diagnostics=("not_a_statement",),
                source_name="non-statement.pdf",
                source_sha256="c" * 64,
                statement_id="c" * 64,
            ),
        ),
        diagnostics=("documents_not_reconciled:1",),
    )


def _multiple_group_carriage_return_batch() -> BatchResult:
    transactions = (
        Transaction(
            transaction_id="transaction-1",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("1.25"),
            billing_currency="ILS",
            reconciliation_group_ids=("group-1",),
            description="first\rmerchant",
            category=TransactionCategory.PURCHASE,
        ),
        Transaction(
            transaction_id="transaction-2",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("2.50"),
            billing_currency="ILS",
            reconciliation_group_ids=("group-2",),
            description="second\r\nmerchant",
            category=TransactionCategory.PURCHASE,
        ),
    )
    groups = tuple(
        ReconciliationGroup(
            group_id=f"group-{index}",
            currency="ILS",
            printed_total=transaction.billed_amount,
            calculated_total=transaction.billed_amount,
            difference=Decimal("0"),
            transaction_ids=(transaction.transaction_id,),
            status=Status.RECONCILED,
        )
        for index, transaction in enumerate(transactions, start=1)
    )
    statement = StatementResult(
        status=Status.RECONCILED,
        transactions=transactions,
        groups=groups,
        source_name="multiple.pdf",
        source_sha256="d" * 64,
        statement_id="e" * 64,
    )
    return BatchResult(
        status=Status.RECONCILED,
        statements=(statement,),
        diagnostics=("batch_diagnostic",),
    )


_LOCKED_PRE_STREAMING_CSV_BYTES = (
    b"\xef\xbb\xbf"
    + (
        "source,source_sha256,statement_id,group_id,transaction_id,transaction_date,"
        "posting_date,conversion_date,description,category,kind,billed_amount,"
        "billing_currency,original_amount,original_currency,installment_current,"
        "installment_total,status,ambiguity_codes,diagnostic_codes,source_page,source_bbox,"
        "exchange_rate,exchange_rate_source_page,exchange_rate_source_bbox,"
        "foreign_currency_fee_percentage,foreign_currency_fee_percentage_source_page,"
        "foreign_currency_fee_percentage_source_bbox,gross_foreign_currency_fee,"
        "gross_foreign_currency_fee_currency,gross_foreign_currency_fee_source_page,"
        "gross_foreign_currency_fee_source_bbox,foreign_currency_fee_discount,"
        "foreign_currency_fee_discount_currency,foreign_currency_fee_discount_source_page,"
        "foreign_currency_fee_discount_source_bbox,net_foreign_currency_fee,"
        "net_foreign_currency_fee_currency,net_foreign_currency_fee_derivation,"
        "net_foreign_currency_fee_source_page,net_foreign_currency_fee_source_bbox,merchant\r\n"
        "nested/statement.pdf,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,group-0001,"
        "group-0001-p001-r0001,2026-01-02,,2026-01-03,"
        '"Café, ""שָׁלוֹם""\nsecond line",purchase,charge,1234.5,ILS,10.2,USD,2,3,'
        "reconciled,ambiguous_date|ambiguous_currency,"
        "batch_diagnostic|statement_diagnostic|group_diagnostic,1,"
        '"1:10.25,20.5,30.75,40",2.943,1,"1:40,50,70,60",3,1,"1:40,60,70,70",'
        '0.88,ILS,1,"1:40,60,70,70",0.59,ILS,1,"1:40,70,70,80",0.29,ILS,'
        'gross_fee_minus_discount,1,"1:40,60,70,70;1:40,70,70,80",Café\r\n'
        "empty.pdf,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb,"
        ",,,,,,,,,,,,,,unsupported,,batch_diagnostic|empty_diagnostic,"
        ",,,,,,,,,,,,,,,,,,,,,\r\n"
    ).encode()
)

_LOCKED_CSV_HEADER_BYTES = _LOCKED_PRE_STREAMING_CSV_BYTES.split(b"\r\n", 1)[0] + b"\r\n"
_LOCKED_NON_STATEMENT_CSV_BYTES = (
    _LOCKED_CSV_HEADER_BYTES
    + b"non-statement.pdf,cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc,"
    b"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc,,,,,,,,,,,,,,,"
    b"not_statement,,documents_not_reconciled:1|not_a_statement,,,,,,,,,,,,,,,,,,,,,,\r\n"
)
_LOCKED_CARRIAGE_RETURN_CSV_BYTES = (
    _LOCKED_CSV_HEADER_BYTES
    + b"multiple.pdf,dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd,"
    b"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee,group-1,"
    b'transaction-1,,,,"first\rmerchant",purchase,charge,1.25,ILS,,,,,reconciled,,'
    b"batch_diagnostic,,,,,,,,,,,,,,,,,,,,,,\r\n"
    b"multiple.pdf,dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd,"
    b"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee,group-2,"
    b'transaction-2,,,,"second\r\nmerchant",purchase,charge,2.5,ILS,,,,,reconciled,,'
    b"batch_diagnostic,,,,,,,,,,,,,,,,,,,,,,\r\n"
)


def _all_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(text for item in value.values() for text in _all_strings(item))
    if isinstance(value, list):
        return tuple(text for item in value for text in _all_strings(item))
    return ()


@pytest.mark.parametrize(
    "batch",
    (
        _batch(),
        BatchResult(status=Status.UNSUPPORTED, statements=(), diagnostics=("no_pdf_files",)),
        _non_statement_batch(),
        BatchResult(
            status=Status.UNSUPPORTED,
            statements=(
                StatementResult(
                    status=Status.UNSUPPORTED,
                    transactions=(),
                    groups=(),
                    diagnostics=("unsupported_layout",),
                ),
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
        BatchResult(
            status=Status.UNRECONCILED,
            statements=(
                StatementResult(status=Status.RECONCILED, transactions=(), groups=()),
                StatementResult(status=Status.UNRECONCILED, transactions=(), groups=()),
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
        _multiple_group_carriage_return_batch(),
    ),
)
def test_streaming_json_matches_complete_batch_bytes(batch: BatchResult) -> None:
    json_stream = io.BytesIO()

    write_canonical_batch_json_stream(
        json_stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )

    assert json_stream.getvalue() == canonical_json_bytes(batch)


def test_streaming_csv_matches_locked_pre_streaming_byte_oracle() -> None:
    batch = _batch_with_empty_statement()
    stream = io.BytesIO()

    write_transactions_csv_stream(
        stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )

    assert stream.getvalue() == _LOCKED_PRE_STREAMING_CSV_BYTES
    assert transactions_csv_bytes(batch) == _LOCKED_PRE_STREAMING_CSV_BYTES


def test_streaming_csv_preserves_carriage_returns_against_locked_byte_oracle() -> None:
    batch = _multiple_group_carriage_return_batch()
    stream = io.BytesIO()

    write_transactions_csv_stream(
        stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )

    assert stream.getvalue() == _LOCKED_CARRIAGE_RETURN_CSV_BYTES


def test_streaming_non_statement_csv_matches_locked_byte_oracle() -> None:
    batch = _non_statement_batch()
    stream = io.BytesIO()

    write_transactions_csv_stream(
        stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )

    assert stream.getvalue() == _LOCKED_NON_STATEMENT_CSV_BYTES


def _statements_requiring_release_before_next() -> Iterator[StatementResult]:
    transaction = Transaction(
        transaction_id="transaction-0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
    )
    group = ReconciliationGroup(
        group_id="group-0001",
        currency="ILS",
        printed_total=Decimal("1.00"),
        calculated_total=Decimal("1.00"),
        difference=Decimal("0.00"),
        transaction_ids=(transaction.transaction_id,),
        status=Status.RECONCILED,
    )
    statement = StatementResult(
        status=Status.RECONCILED,
        transactions=(transaction,),
        groups=(group,),
    )
    references = {
        "statement": weakref.ref(statement),
        "transaction": weakref.ref(transaction),
        "group": weakref.ref(group),
    }
    yield statement
    del statement, transaction, group
    gc.collect()
    retained = tuple(name for name, reference in references.items() if reference() is not None)
    assert not retained, f"prior statement graph retained while requesting next: {retained}"
    yield StatementResult(status=Status.RECONCILED, transactions=(), groups=())


def test_streaming_json_releases_statement_before_requesting_next() -> None:
    write_canonical_batch_json_stream(
        io.BytesIO(),
        status=Status.RECONCILED,
        diagnostics=(),
        statements=_statements_requiring_release_before_next(),
    )


def test_streaming_csv_releases_statement_graph_before_requesting_next() -> None:
    write_transactions_csv_stream(
        io.BytesIO(),
        status=Status.RECONCILED,
        diagnostics=(),
        statements=_statements_requiring_release_before_next(),
    )


def test_canonical_json_is_stable_nfc_decimal_safe_and_has_one_newline() -> None:
    batch = _batch()
    input_description = batch.statements[0].transactions[0].description

    first = canonical_json_bytes(batch)
    second = canonical_json_bytes(batch)
    payload = json.loads(first)

    assert first == second
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert first.decode("utf-8").startswith('{"diagnostics"')
    transaction = payload["statements"][0]["transactions"][0]
    assert input_description is not None
    assert not unicodedata.is_normalized("NFC", input_description)
    assert transaction["description"] == 'Café, "שָׁלוֹם"\nsecond line'
    assert transaction["ambiguities"] == [
        "ambiguous_date",
        "ambiguous_currency",
        "ambiguous_date",
    ]
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


def test_canonical_json_value_bytes_owns_the_closed_value_grammar() -> None:
    decomposed = "Cafe\u0301"
    composed = "Caf\u00e9"

    encoded = output_module._canonical_json_value_bytes(
        {decomposed: (True, 1, 2.5, decomposed), composed: "last"}
    )

    assert encoded == '{"Caf\u00e9":"last"}\n'.encode()


def test_transactions_csv_has_bom_fixed_columns_quoting_money_and_provenance() -> None:
    content = transactions_csv_bytes(_batch())

    assert content.startswith(b"\xef\xbb\xbf")
    rows = tuple(csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline="")))

    assert tuple(rows[0]) == (
        "source",
        "source_sha256",
        "statement_id",
        "group_id",
        "transaction_id",
        "transaction_date",
        "posting_date",
        "conversion_date",
        "description",
        "category",
        "kind",
        "billed_amount",
        "billing_currency",
        "original_amount",
        "original_currency",
        "installment_current",
        "installment_total",
        "status",
        "ambiguity_codes",
        "diagnostic_codes",
        "source_page",
        "source_bbox",
        "exchange_rate",
        "exchange_rate_source_page",
        "exchange_rate_source_bbox",
        "foreign_currency_fee_percentage",
        "foreign_currency_fee_percentage_source_page",
        "foreign_currency_fee_percentage_source_bbox",
        "gross_foreign_currency_fee",
        "gross_foreign_currency_fee_currency",
        "gross_foreign_currency_fee_source_page",
        "gross_foreign_currency_fee_source_bbox",
        "foreign_currency_fee_discount",
        "foreign_currency_fee_discount_currency",
        "foreign_currency_fee_discount_source_page",
        "foreign_currency_fee_discount_source_bbox",
        "net_foreign_currency_fee",
        "net_foreign_currency_fee_currency",
        "net_foreign_currency_fee_derivation",
        "net_foreign_currency_fee_source_page",
        "net_foreign_currency_fee_source_bbox",
        "merchant",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "nested/statement.pdf"
    assert row["statement_id"] == "a" * 64
    assert row["group_id"] == "group-0001"
    assert row["billed_amount"] == "1234.5"
    assert row["original_amount"] == "10.2"
    assert row["conversion_date"] == "2026-01-03"
    assert row["description"] == 'Café, "שָׁלוֹם"\nsecond line'
    assert row["merchant"] == "Café"
    assert row["ambiguity_codes"] == "ambiguous_date|ambiguous_currency"
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
    assert row["diagnostic_codes"] == "batch_diagnostic|statement_diagnostic|group_diagnostic"


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

    def fail_csv_render(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("private serialization detail")

    monkeypatch.setattr(output_module, "write_transactions_csv_stream", fail_csv_render)

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


def _pair_bytes(output_dir: Path) -> tuple[bytes | None, bytes | None]:
    json_path = output_dir / "results.json"
    csv_path = output_dir / "transactions.csv"
    return (
        json_path.read_bytes() if json_path.exists() else None,
        csv_path.read_bytes() if csv_path.exists() else None,
    )


def _seed_pair_state(output_dir: Path, prior_state: str) -> tuple[bytes | None, bytes | None]:
    output_dir.mkdir()
    if prior_state in {"json", "both"}:
        (output_dir / "results.json").write_bytes(b"old json\n")
    if prior_state in {"csv", "both"}:
        (output_dir / "transactions.csv").write_bytes(b"old csv\r\n")
    return _pair_bytes(output_dir)


def _assert_no_pair_artifacts(output_dir: Path) -> None:
    assert not tuple(output_dir.glob(".*.tmp"))
    assert not tuple(output_dir.glob(".*.backup"))


def test_streaming_pair_writer_matches_batch_outputs(tmp_path: Path) -> None:
    batch = _batch()
    expected_dir = tmp_path / "expected"
    streamed_dir = tmp_path / "streamed"
    calls = 0

    def statements() -> Iterator[StatementResult]:
        nonlocal calls
        calls += 1
        yield from batch.statements

    write_batch_outputs(expected_dir, batch)
    write_streaming_batch_outputs(
        streamed_dir,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=statements,
    )

    assert calls == 2
    assert (streamed_dir / "results.json").read_bytes() == (
        expected_dir / "results.json"
    ).read_bytes()
    assert (streamed_dir / "transactions.csv").read_bytes() == (
        expected_dir / "transactions.csv"
    ).read_bytes()
    _assert_no_pair_artifacts(streamed_dir)


def test_streaming_pair_batch_adapter_avoids_byte_buffers_and_destination_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    _seed_pair_state(output_dir, "both")
    original_read_bytes = Path.read_bytes

    def reject_byte_buffer(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        raise AssertionError("unexpected whole-batch byte rendering")

    def reject_read_bytes(path: Path) -> bytes:
        raise AssertionError(f"unexpected corpus-sized read: {path.name}")

    monkeypatch.setattr(output_module, "canonical_json_bytes", reject_byte_buffer)
    monkeypatch.setattr(output_module, "transactions_csv_bytes", reject_byte_buffer)
    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)

    write_batch_outputs(output_dir, _batch())

    assert original_read_bytes(output_dir / "results.json").startswith(b'{"diagnostics"')
    assert original_read_bytes(output_dir / "transactions.csv").startswith(b"\xef\xbb\xbf")
    _assert_no_pair_artifacts(output_dir)


def test_streaming_pair_prerenders_and_fsyncs_both_restrictive_stages_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    _seed_pair_state(output_dir, "both")
    render_order: list[str] = []
    stage_modes: list[int] = []
    regular_fsyncs = 0
    directory_fsyncs = 0
    first_replace = True
    original_fsync = os.fsync
    original_replace = os.replace

    def render(label: str, content: bytes) -> Callable[[BinaryIO], None]:
        def render_content(stream: BinaryIO) -> None:
            render_order.append(label)
            stage_modes.append(stat.S_IMODE(os.fstat(stream.fileno()).st_mode))
            stream.write(content)

        return render_content

    def observe_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs, regular_fsyncs
        metadata = os.fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            regular_fsyncs += 1
        elif stat.S_ISDIR(metadata.st_mode):
            directory_fsyncs += 1
        original_fsync(descriptor)

    def observe_replace(source: Path, destination: Path) -> None:
        nonlocal first_replace
        if first_replace:
            first_replace = False
            assert render_order == ["json", "csv"]
            assert regular_fsyncs == 2
            assert directory_fsyncs == 1
            for destination_name in ("results.json", "transactions.csv"):
                inspected_destination = output_dir / destination_name
                backups = tuple(output_dir.glob(f".{destination_name}.*.backup"))
                assert len(backups) == 1
                assert backups[0].stat().st_ino == inspected_destination.stat().st_ino
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "fsync", observe_fsync)
    monkeypatch.setattr(output_module.os, "replace", observe_replace)

    write_output_pair_atomic(
        output_dir,
        render_json=render("json", b"new json\n"),
        render_csv=render("csv", b"new csv\r\n"),
    )

    assert stage_modes == [0o600, 0o600]
    assert _pair_bytes(output_dir) == (b"new json\n", b"new csv\r\n")
    _assert_no_pair_artifacts(output_dir)


def test_streaming_pair_render_failure_does_not_mutate_destinations(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, "both")

    def render_json(stream: BinaryIO) -> None:
        stream.write(b"new json\n")

    def fail_csv_render(stream: BinaryIO) -> None:
        stream.write(b"partial csv")
        raise TypeError("private serialization detail")

    with pytest.raises(TypeError, match="serialization"):
        write_output_pair_atomic(
            output_dir,
            render_json=render_json,
            render_csv=fail_csv_render,
        )

    assert _pair_bytes(output_dir) == before
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "both"))
@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, SystemExit))
def test_streaming_pair_render_interruption_cleans_every_owned_path(
    tmp_path: Path,
    prior_state: str,
    interruption_type: type[BaseException],
) -> None:
    output_dir = tmp_path / "output"
    private_marker = b"private prior output marker"
    if prior_state == "both":
        _seed_pair_state(output_dir, prior_state)
        for filename in ("results.json", "transactions.csv"):
            (output_dir / filename).write_bytes(private_marker + filename.encode())
    before = _pair_bytes(output_dir)
    interruption = interruption_type("render interrupted")

    def interrupt_json_render(stream: BinaryIO) -> None:
        stream.write(b"private partial stage")
        raise interruption

    with pytest.raises(interruption_type) as caught:
        write_output_pair_atomic(
            output_dir,
            render_json=interrupt_json_render,
            render_csv=lambda stream: None,
        )

    assert caught.value is interruption
    assert _pair_bytes(output_dir) == before
    assert private_marker.decode() not in "".join(traceback.format_exception(caught.value))
    _assert_no_pair_artifacts(output_dir)
    if prior_state == "none":
        assert not output_dir.exists()


@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, SystemExit))
def test_streaming_pair_render_interruption_survives_stage_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption_type: type[BaseException],
) -> None:
    output_dir = tmp_path / "output"
    original_named_temporary_file = output_module.tempfile.NamedTemporaryFile
    interruption = interruption_type("render interrupted")

    class CloseFailingTemporary:
        def __init__(self, wrapped: BinaryIO) -> None:
            self._wrapped = wrapped

        def __enter__(self) -> BinaryIO:
            return self._wrapped

        def __exit__(self, *args: object) -> None:
            del args
            self._wrapped.close()
            raise OSError("secondary stage close detail")

    def close_failing_temporary(*args: object, **kwargs: object) -> CloseFailingTemporary:
        temporary = original_named_temporary_file(*args, **kwargs)
        return CloseFailingTemporary(cast(BinaryIO, temporary))

    def interrupt_json_render(stream: BinaryIO) -> None:
        stream.write(b"private partial stage")
        raise interruption

    monkeypatch.setattr(
        output_module.tempfile,
        "NamedTemporaryFile",
        close_failing_temporary,
    )

    with pytest.raises(interruption_type) as caught:
        write_output_pair_atomic(
            output_dir,
            render_json=interrupt_json_render,
            render_csv=lambda stream: None,
        )

    assert caught.value is interruption
    assert not output_dir.exists()


def test_streaming_pair_render_failure_retries_stage_cleanup_and_preserves_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, "both")
    original_unlink = Path.unlink
    failed = False

    def fail_first_stage_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal failed
        if path.suffix == ".tmp" and not failed:
            failed = True
            raise OSError("secondary stage cleanup detail")
        original_unlink(path, missing_ok=missing_ok)

    def render_json(stream: BinaryIO) -> None:
        stream.write(b"new json\n")

    def fail_csv_render(stream: BinaryIO) -> None:
        stream.write(b"partial csv")
        raise TypeError("primary serialization detail")

    monkeypatch.setattr(Path, "unlink", fail_first_stage_unlink)

    with pytest.raises(TypeError, match="primary serialization"):
        write_output_pair_atomic(
            output_dir,
            render_json=render_json,
            render_csv=fail_csv_render,
        )

    assert _pair_bytes(output_dir) == before
    _assert_no_pair_artifacts(output_dir)


def test_streaming_pair_render_failure_is_not_masked_by_stage_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    original_named_temporary_file = output_module.tempfile.NamedTemporaryFile

    class CloseFailingTemporary:
        def __init__(self, wrapped: BinaryIO) -> None:
            self._wrapped = wrapped

        def __enter__(self) -> BinaryIO:
            return self._wrapped

        def __exit__(self, *args: object) -> None:
            del args
            self._wrapped.close()
            raise OSError("secondary stage close detail")

    def close_failing_temporary(*args: object, **kwargs: object) -> CloseFailingTemporary:
        temporary = original_named_temporary_file(*args, **kwargs)
        return CloseFailingTemporary(cast(BinaryIO, temporary))

    def fail_json_render(stream: BinaryIO) -> None:
        stream.write(b"partial json")
        raise TypeError("primary serialization detail")

    monkeypatch.setattr(
        output_module.tempfile,
        "NamedTemporaryFile",
        close_failing_temporary,
    )

    with pytest.raises(TypeError, match="primary serialization"):
        write_output_pair_atomic(
            output_dir,
            render_json=fail_json_render,
            render_csv=lambda stream: None,
        )

    assert not output_dir.exists()


def test_streaming_pair_backup_validation_failure_cleans_owned_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, "both")
    original_stat = Path.stat
    failed = False

    def fail_first_backup_stat(
        path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        nonlocal failed
        if path.suffix == ".backup" and not failed:
            failed = True
            raise OSError("primary backup validation detail")
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", fail_first_backup_stat)

    with pytest.raises(OSError, match="backup validation"):
        write_streaming_batch_outputs(
            output_dir,
            status=_batch().status,
            diagnostics=_batch().diagnostics,
            statements=lambda: iter(_batch().statements),
        )

    assert _pair_bytes(output_dir) == before
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_streaming_pair_first_replace_failure_preserves_prior_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, prior_state)
    original_replace = os.replace
    failed = False

    def fail_json_replace(source: Path, destination: Path) -> None:
        nonlocal failed
        if Path(destination).name == "results.json" and not failed:
            failed = True
            raise OSError("private first replacement detail")
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "replace", fail_json_replace)
    batch = _batch()

    with pytest.raises(OSError, match="first replacement"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert _pair_bytes(output_dir) == before
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
@pytest.mark.parametrize("failed_destination", ("results.json", "transactions.csv"))
def test_streaming_pair_replace_then_raise_restores_every_prior_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
    failed_destination: str,
) -> None:
    output_dir = tmp_path / "output"
    private_marker = b"private prior output marker"
    _seed_pair_state(output_dir, prior_state)
    for filename in ("results.json", "transactions.csv"):
        destination = output_dir / filename
        if destination.exists():
            destination.write_bytes(private_marker + filename.encode())
    before = _pair_bytes(output_dir)
    original_replace = os.replace
    injected = OSError("publication replacement failed")
    failed = False

    def replace_then_raise(source: Path, destination: Path) -> None:
        nonlocal failed
        original_replace(source, destination)
        if Path(destination).name == failed_destination and not failed:
            failed = True
            raise injected

    monkeypatch.setattr(output_module.os, "replace", replace_then_raise)
    batch = _batch()

    with pytest.raises(OSError) as caught:
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert caught.value is injected
    assert failed
    assert _pair_bytes(output_dir) == before
    assert private_marker.decode() not in "".join(traceback.format_exception(caught.value))
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
@pytest.mark.parametrize("interruption_type", (KeyboardInterrupt, SystemExit))
def test_streaming_pair_between_replacements_interruption_restores_prior_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
    interruption_type: type[BaseException],
) -> None:
    output_dir = tmp_path / "output"
    private_marker = b"private prior output marker"
    _seed_pair_state(output_dir, prior_state)
    for filename in ("results.json", "transactions.csv"):
        destination = output_dir / filename
        if destination.exists():
            destination.write_bytes(private_marker + filename.encode())
    before = _pair_bytes(output_dir)
    original_replace = os.replace
    interruption = interruption_type("publication interrupted")
    interrupted = False

    def interrupt_before_csv_replace(source: Path, destination: Path) -> None:
        nonlocal interrupted
        if Path(destination).name == "transactions.csv" and not interrupted:
            interrupted = True
            raise interruption
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "replace", interrupt_before_csv_replace)
    batch = _batch()

    with pytest.raises(interruption_type) as caught:
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert caught.value is interruption
    assert interrupted
    assert _pair_bytes(output_dir) == before
    assert private_marker.decode() not in "".join(traceback.format_exception(caught.value))
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_streaming_pair_second_replace_failure_restores_prior_state_without_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, prior_state)
    original_read_bytes = Path.read_bytes
    original_replace = os.replace
    failed = False

    def reject_read_bytes(path: Path) -> bytes:
        raise AssertionError(f"unexpected corpus-sized read: {path.name}")

    def fail_csv_replace(source: Path, destination: Path) -> None:
        nonlocal failed
        if Path(destination).name == "transactions.csv" and not failed:
            failed = True
            raise OSError("private replacement detail")
        original_replace(source, destination)

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    monkeypatch.setattr(output_module.os, "replace", fail_csv_replace)
    batch = _batch()

    with pytest.raises(OSError, match="replacement"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert (
        original_read_bytes(output_dir / "results.json")
        if (output_dir / "results.json").exists()
        else None,
        original_read_bytes(output_dir / "transactions.csv")
        if (output_dir / "transactions.csv").exists()
        else None,
    ) == before
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_streaming_pair_publish_directory_fsync_failure_restores_prior_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, prior_state)
    original_fsync = os.fsync
    calls = 0

    def fail_publish_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("private publish fsync detail")
        original_fsync(descriptor)

    monkeypatch.setattr(output_module.os, "fsync", fail_publish_directory_fsync)
    batch = _batch()

    with pytest.raises(OSError, match="publish fsync"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert _pair_bytes(output_dir) == before
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_streaming_pair_rollback_attempts_both_restores_and_preserves_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    before = _seed_pair_state(output_dir, prior_state)
    original_fsync = os.fsync
    original_replace = os.replace
    original_unlink = Path.unlink
    fsync_calls = 0
    restore_attempts: list[str] = []
    failed = False

    def fail_publish_directory_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 4:
            raise OSError("primary publish fsync detail")
        original_fsync(descriptor)

    def fail_first_restore(source: Path, destination: Path) -> None:
        nonlocal failed
        if Path(source).suffix == ".backup":
            restore_attempts.append(Path(destination).name)
            if Path(destination).name == "results.json" and not failed:
                failed = True
                raise OSError("secondary rollback detail")
        original_replace(source, destination)

    def fail_first_absent_restore(path: Path, missing_ok: bool = False) -> None:
        nonlocal failed
        if path.name in {"results.json", "transactions.csv"}:
            restore_attempts.append(path.name)
            if path.name == "results.json" and not failed:
                failed = True
                raise OSError("secondary rollback detail")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(output_module.os, "fsync", fail_publish_directory_fsync)
    monkeypatch.setattr(output_module.os, "replace", fail_first_restore)
    monkeypatch.setattr(Path, "unlink", fail_first_absent_restore)
    batch = _batch()

    with pytest.raises(OSError, match="primary publish fsync"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert restore_attempts == ["results.json", "transactions.csv"]
    assert failed
    assert (
        (output_dir / "transactions.csv").read_bytes()
        if (output_dir / "transactions.csv").exists()
        else None
    ) == before[1]
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_streaming_pair_post_commit_cleanup_failure_keeps_new_pair_without_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    _seed_pair_state(output_dir, prior_state)
    batch = _batch()
    expected = (canonical_json_bytes(batch), transactions_csv_bytes(batch))
    original_fsync = os.fsync
    original_replace = os.replace
    fsync_calls = 0
    restore_attempts: list[str] = []

    def fail_cleanup_directory_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 5:
            raise OSError("private cleanup fsync detail")
        original_fsync(descriptor)

    def observe_replace(source: Path, destination: Path) -> None:
        if Path(source).suffix == ".backup":
            restore_attempts.append(Path(destination).name)
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "fsync", fail_cleanup_directory_fsync)
    monkeypatch.setattr(output_module.os, "replace", observe_replace)

    with pytest.raises(OSError, match="cleanup fsync"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert _pair_bytes(output_dir) == expected
    assert not restore_attempts
    _assert_no_pair_artifacts(output_dir)


def test_streaming_pair_commit_descriptor_close_failure_does_not_roll_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    _seed_pair_state(output_dir, "both")
    batch = _batch()
    expected = (canonical_json_bytes(batch), transactions_csv_bytes(batch))
    original_close = os.close
    close_calls = 0

    def fail_commit_descriptor_close(descriptor: int) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(descriptor)
        if close_calls == 2:
            raise OSError("private commit descriptor close detail")

    monkeypatch.setattr(output_module.os, "close", fail_commit_descriptor_close)

    with pytest.raises(OSError, match="commit descriptor close"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert _pair_bytes(output_dir) == expected
    _assert_no_pair_artifacts(output_dir)


def test_streaming_pair_post_commit_unlink_failure_retries_cleanup_without_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    _seed_pair_state(output_dir, "both")
    batch = _batch()
    expected = (canonical_json_bytes(batch), transactions_csv_bytes(batch))
    original_unlink = Path.unlink
    failed = False

    def fail_first_backup_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal failed
        if path.suffix == ".backup" and not failed:
            failed = True
            raise OSError("private cleanup unlink detail")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_first_backup_unlink)

    with pytest.raises(OSError, match="cleanup unlink"):
        write_streaming_batch_outputs(
            output_dir,
            status=batch.status,
            diagnostics=batch.diagnostics,
            statements=lambda: iter(batch.statements),
        )

    assert _pair_bytes(output_dir) == expected
    _assert_no_pair_artifacts(output_dir)


@pytest.mark.parametrize("destination_name", ("results.json", "transactions.csv"))
@pytest.mark.parametrize("destination_kind", ("symlink", "directory"))
def test_streaming_pair_rejects_non_regular_destination_without_following_it(
    tmp_path: Path,
    destination_name: str,
    destination_kind: str,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    destination = output_dir / destination_name
    target = tmp_path / "target-output"
    target.write_bytes(b"outside output\n")
    if destination_kind == "symlink":
        destination.symlink_to(target)
    else:
        destination.mkdir()

    def render_json(stream: BinaryIO) -> None:
        stream.write(b"new json\n")

    def render_csv(stream: BinaryIO) -> None:
        stream.write(b"new csv\r\n")

    with pytest.raises(OSError, match="regular file"):
        write_output_pair_atomic(
            output_dir,
            render_json=render_json,
            render_csv=render_csv,
        )

    assert target.read_bytes() == b"outside output\n"
    if destination_kind == "symlink":
        assert destination.is_symlink()
    else:
        assert destination.is_dir()
    other_name = "transactions.csv" if destination_name == "results.json" else "results.json"
    assert not (output_dir / other_name).exists()
    _assert_no_pair_artifacts(output_dir)
