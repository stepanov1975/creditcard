"""Canonical bounded-memory JSONL interchange for row experiments."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.contracts import ArtifactIdentity

_ARTIFACT_TYPE = "jsonl"
_FORMAT_VERSION = "canonical-jsonl-v1"


def _canonical_record_bytes(record: BaseModel) -> bytes:
    value = json.loads(record.model_dump_json())
    return _canonical_json_value_content(value) + b"\n"


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> ArtifactIdentity:
    """Atomically write and incrementally identify canonical JSONL records."""

    digest = hashlib.sha256()
    byte_size = 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for record in records:
                content = _canonical_record_bytes(record)
                temporary.write(content)
                digest.update(content)
                byte_size += len(content)
        assert temporary_path is not None
        temporary_path.replace(path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return ArtifactIdentity(
        artifact_type=_ARTIFACT_TYPE,
        sha256=digest.hexdigest(),
        version=_FORMAT_VERSION,
        byte_size=byte_size,
    )


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    """Validate and yield one JSONL record at a time."""

    with path.open("rb") as source:
        for line in source:
            yield model.model_validate_json(line)
