"""Canonical JSON/CSV serialization and crash-safe atomic writers."""

from __future__ import annotations

import codecs
import csv
import io
import json
import math
import os as os
import tempfile as tempfile
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from ccparser._output_publication import (
    BinaryRenderer,
    write_output_pair_atomic,
)
from ccparser._output_publication import (
    write_bytes_atomic as _write_atomic,
)
from ccparser.decimal_math import plain_decimal_string
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type StatementResultFactory = Callable[[], Iterator[StatementResult]]

_BASE_CSV_COLUMNS = (
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
)
_FX_CSV_COLUMNS = (
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
)
CSV_COLUMNS = (*_BASE_CSV_COLUMNS, *_FX_CSV_COLUMNS)


class BinaryWriter(Protocol):
    def write(self, content: bytes, /) -> int: ...


def _normalized_json(value: object) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numeric values must be finite")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalized_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[unicodedata.normalize("NFC", key)] = _normalized_json(item)
        return normalized
    raise TypeError("unsupported canonical JSON value")


def _canonical_json_value_content(value: object) -> bytes:
    return json.dumps(
        _normalized_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json_value_bytes(value: object) -> bytes:
    """Encode one value from the package's closed canonical JSON grammar."""

    return _canonical_json_value_content(value) + b"\n"


def canonical_json_bytes(result: BaseModel) -> bytes:
    """Return stable canonical UTF-8 JSON with logical NFC text and one newline."""

    return _canonical_json_value_bytes(result.model_dump(mode="json"))


def write_canonical_batch_json_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None:
    destination.write(b'{"diagnostics":')
    destination.write(_canonical_json_value_content(diagnostics))
    destination.write(b',"statements":[')
    separator = b""
    statement_iterator = iter(statements)
    while True:
        try:
            statement = next(statement_iterator)
        except StopIteration:
            break
        destination.write(separator)
        destination.write(_canonical_json_value_content(statement.model_dump(mode="json")))
        separator = b","
        del statement
    destination.write(b'],"status":')
    destination.write(_canonical_json_value_content(status.value))
    destination.write(b"}\n")


def _optional_decimal_string(value: Decimal | None) -> str:
    return "" if value is None else plain_decimal_string(value)


def _date_string(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _codes(*groups: Iterable[str]) -> str:
    return "|".join(dict.fromkeys(value for group in groups for value in group))


def _coordinate(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("coordinates must be finite")
    return format(value, ".15g")


def _provenance(references: Iterable[EvidenceReference]) -> tuple[str, str]:
    evidence = tuple(references)
    pages = tuple(dict.fromkeys(reference.page_number for reference in evidence))
    boxes = tuple(
        f"{reference.page_number}:" + ",".join(_coordinate(value) for value in reference.bbox)
        for reference in evidence
    )
    return ";".join(str(page) for page in pages), ";".join(boxes)


def _fx_fields(transaction: Transaction) -> dict[str, str]:
    fields: dict[str, str] = dict.fromkeys(_FX_CSV_COLUMNS, "")
    details = transaction.foreign_exchange
    if details is None:
        return fields

    def add_decimal(prefix: str, extracted: ExtractedDecimal | None) -> None:
        if extracted is None:
            return
        pages, boxes = _provenance(extracted.evidence)
        fields[prefix] = _optional_decimal_string(extracted.value)
        fields[f"{prefix}_source_page"] = pages
        fields[f"{prefix}_source_bbox"] = boxes

    def add_money(prefix: str, extracted: ExtractedMoney | None) -> None:
        if extracted is None:
            return
        pages, boxes = _provenance(extracted.evidence)
        fields[prefix] = _optional_decimal_string(extracted.amount)
        fields[f"{prefix}_currency"] = extracted.currency
        fields[f"{prefix}_source_page"] = pages
        fields[f"{prefix}_source_bbox"] = boxes

    add_decimal("exchange_rate", details.exchange_rate)
    add_decimal("foreign_currency_fee_percentage", details.fee_percentage)
    add_money("gross_foreign_currency_fee", details.gross_fee)
    add_money("foreign_currency_fee_discount", details.fee_discount)
    add_money("net_foreign_currency_fee", details.net_fee)
    if details.net_fee is not None:
        fields["net_foreign_currency_fee_derivation"] = details.net_fee.derivation
    return fields


def _empty_row(
    *,
    status: str,
    diagnostics: str,
    statement: StatementResult | None = None,
) -> dict[str, str]:
    row = dict.fromkeys(CSV_COLUMNS, "")
    row.update(
        {
            "source": statement.source_name or "" if statement is not None else "",
            "source_sha256": statement.source_sha256 or "" if statement is not None else "",
            "statement_id": statement.statement_id or "" if statement is not None else "",
            "status": status,
            "diagnostic_codes": diagnostics,
        }
    )
    return row


def _transaction_row(
    batch_diagnostics: tuple[str, ...],
    statement: StatementResult,
    transaction: Transaction,
    groups: dict[str, ReconciliationGroup],
) -> dict[str, str]:
    group_id = (
        transaction.reconciliation_group_ids[0]
        if len(transaction.reconciliation_group_ids) == 1
        else ""
    )
    group = groups.get(group_id)
    pages, boxes = _provenance(transaction.evidence)
    return {
        "source": statement.source_name or "",
        "source_sha256": statement.source_sha256 or "",
        "statement_id": statement.statement_id or "",
        "group_id": group_id,
        "transaction_id": transaction.transaction_id,
        "transaction_date": _date_string(transaction.transaction_date),
        "posting_date": _date_string(transaction.posting_date),
        "conversion_date": _date_string(transaction.conversion_date),
        "description": unicodedata.normalize("NFC", transaction.description or ""),
        "category": transaction.category.value,
        "kind": transaction.kind.value,
        "billed_amount": _optional_decimal_string(transaction.billed_amount),
        "billing_currency": transaction.billing_currency,
        "original_amount": _optional_decimal_string(transaction.original_amount),
        "original_currency": transaction.original_currency or "",
        "installment_current": (
            str(transaction.installment_current)
            if transaction.installment_current is not None
            else ""
        ),
        "installment_total": (
            str(transaction.installment_total) if transaction.installment_total is not None else ""
        ),
        "status": statement.status.value,
        "ambiguity_codes": _codes(transaction.ambiguities),
        "diagnostic_codes": _codes(
            batch_diagnostics,
            statement.diagnostics,
            group.diagnostics if group is not None else (),
        ),
        "source_page": pages,
        "source_bbox": boxes,
        **_fx_fields(transaction),
    }


class _Utf8TextWriter:
    def __init__(self, destination: BinaryWriter) -> None:
        self._destination = destination

    def write(self, content: str, /) -> int:
        self._destination.write(content.encode("utf-8"))
        return len(content)


def _write_statement_csv_rows(
    writer: csv.DictWriter[str],
    batch_diagnostics: tuple[str, ...],
    statement: StatementResult,
) -> None:
    groups = {group.group_id: group for group in statement.groups}
    if statement.transactions:
        for transaction in statement.transactions:
            writer.writerow(_transaction_row(batch_diagnostics, statement, transaction, groups))
    else:
        writer.writerow(
            _empty_row(
                status=statement.status.value,
                diagnostics=_codes(batch_diagnostics, statement.diagnostics),
                statement=statement,
            )
        )


def write_transactions_csv_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None:
    destination.write(codecs.BOM_UTF8)
    writer = csv.DictWriter(
        _Utf8TextWriter(destination),
        fieldnames=CSV_COLUMNS,
        lineterminator="\r\n",
    )
    writer.writeheader()
    wrote_statement = False
    statement_iterator = iter(statements)
    while True:
        try:
            statement = next(statement_iterator)
        except StopIteration:
            break
        wrote_statement = True
        _write_statement_csv_rows(writer, diagnostics, statement)
        del statement
    if not wrote_statement:
        writer.writerow(_empty_row(status=status.value, diagnostics=_codes(diagnostics)))


def transactions_csv_bytes(batch: BatchResult) -> bytes:
    """Return a deterministic flat RFC-compatible transaction CSV with UTF-8 BOM."""

    stream = io.BytesIO()
    write_transactions_csv_stream(
        stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )
    return stream.getvalue()


def write_json_atomic(path: str | Path, result: BaseModel) -> None:
    """Atomically replace a canonical JSON destination."""

    _write_atomic(path, canonical_json_bytes(result))


def write_csv_atomic(path: str | Path, batch: BatchResult) -> None:
    """Atomically replace a canonical flat CSV destination."""

    _write_atomic(path, transactions_csv_bytes(batch))


def write_streaming_batch_outputs(
    output_dir: str | Path,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: StatementResultFactory,
) -> None:
    write_output_pair_atomic(
        output_dir,
        render_json=lambda stream: write_canonical_batch_json_stream(
            stream,
            status=status,
            diagnostics=diagnostics,
            statements=statements(),
        ),
        render_csv=lambda stream: write_transactions_csv_stream(
            stream,
            status=status,
            diagnostics=diagnostics,
            statements=statements(),
        ),
    )


def write_batch_outputs(output_dir: str | Path, batch: BatchResult) -> None:
    """Stream and publish a batch while preserving the public adapter."""

    write_streaming_batch_outputs(
        output_dir,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=lambda: iter(batch.statements),
    )


__all__ = [
    "CSV_COLUMNS",
    "BinaryRenderer",
    "BinaryWriter",
    "StatementResultFactory",
    "canonical_json_bytes",
    "transactions_csv_bytes",
    "write_batch_outputs",
    "write_canonical_batch_json_stream",
    "write_csv_atomic",
    "write_json_atomic",
    "write_output_pair_atomic",
    "write_streaming_batch_outputs",
    "write_transactions_csv_stream",
]
