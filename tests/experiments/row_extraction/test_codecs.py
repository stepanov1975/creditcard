from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from experiments.row_extraction.codecs import read_jsonl, write_jsonl
from experiments.row_extraction.contracts import FrozenRow
from tests.experiments.row_extraction.factories import frozen_row


class _CanonicalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, int]
    label: str


class _FloatRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float


def test_jsonl_round_trip_is_byte_deterministic(tmp_path: Path) -> None:
    row = frozen_row()
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    first_identity = write_jsonl(first, (row,))
    second_identity = write_jsonl(second, (row,))

    assert first_identity.sha256 == second_identity.sha256
    assert first.read_bytes() == second.read_bytes()
    assert tuple(read_jsonl(first, FrozenRow)) == (row,)


def test_write_jsonl_uses_canonical_nfc_sorted_json_with_one_newline(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "canonical.jsonl"
    record = _CanonicalRecord(values={"z": 2, "a": 1}, label="Cafe\u0301")
    expected = '{"label":"Caf\u00e9","values":{"a":1,"z":2}}\n'.encode()

    identity = write_jsonl(destination, (record,))

    assert destination.read_bytes() == expected
    assert identity.sha256 == hashlib.sha256(expected).hexdigest()
    assert identity.byte_size == len(expected)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_write_jsonl_rejects_nonfinite_numbers(tmp_path: Path, value: float) -> None:
    destination = tmp_path / "nonfinite.jsonl"

    with pytest.raises(ValueError, match="numeric values must be finite"):
        write_jsonl(destination, (_FloatRecord(value=value),))

    assert not destination.exists()


def test_read_jsonl_validates_only_the_line_requested(tmp_path: Path) -> None:
    source = tmp_path / "records.jsonl"
    source.write_bytes(
        b'{"label":"first","values":{"a":1}}\n{"label":"second","values":{"a":"invalid"}}\n'
    )

    records = read_jsonl(source, _CanonicalRecord)

    assert next(records) == _CanonicalRecord(label="first", values={"a": 1})
    with pytest.raises(ValidationError):
        next(records)


def test_write_jsonl_does_not_replace_destination_after_iterator_failure(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "records.jsonl"
    destination.write_bytes(b"original\n")

    def failing_records() -> Iterator[BaseModel]:
        yield _CanonicalRecord(label="first", values={"a": 1})
        raise RuntimeError("synthetic iterator failure")

    with pytest.raises(RuntimeError, match="synthetic iterator failure"):
        write_jsonl(destination, failing_records())

    assert destination.read_bytes() == b"original\n"
