"""Bounded-memory execution for one streamed corpus run."""

from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from ccparser._corpus_projection import StructuralProjection, project_statement_stream
from ccparser.corpus_spool import StatementSpool
from ccparser.models import StatementResult, Status
from ccparser.output import (
    write_canonical_batch_json_stream,
    write_streaming_batch_outputs,
    write_transactions_csv_stream,
)
from ccparser.parser import (
    BatchDisposition,
    StatementParser,
    convert_directory_statements,
    summarize_batch_statuses,
)
from ccparser.paths import DirectoryRootPolicy

type StatementResultFactory = Callable[[], Iterator[StatementResult]]
type NanosecondClock = Callable[[], int]
type AfterPublication = Callable[[], None]


@dataclass(frozen=True, slots=True)
class StreamingRunData:
    """Neutral result of streamed parsing, publication, and verification."""

    batch_status: Status
    elapsed_seconds: Decimal
    json_digest: str
    csv_digest: str
    structural_projection: StructuralProjection


@dataclass(frozen=True, slots=True)
class _StableEmittedFileIdentity:
    device: int
    inode: int
    size_bytes: int
    modified_ns: int


class _Sha256Writer:
    """Binary writer that retains only an incremental SHA-256 state."""

    def __init__(self) -> None:
        self._digest = sha256()

    def write(self, content: bytes, /) -> int:
        self._digest.update(content)
        return len(content)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _canonical_stream_digests(
    disposition: BatchDisposition,
    statements: StatementResultFactory,
) -> tuple[str, str]:
    json_writer = _Sha256Writer()
    write_canonical_batch_json_stream(
        json_writer,
        status=disposition.status,
        diagnostics=disposition.diagnostics,
        statements=statements(),
    )
    csv_writer = _Sha256Writer()
    write_transactions_csv_stream(
        csv_writer,
        status=disposition.status,
        diagnostics=disposition.diagnostics,
        statements=statements(),
    )
    return json_writer.hexdigest(), csv_writer.hexdigest()


_EMITTED_OUTPUT_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_EMITTED_OUTPUT_READ_SIZE = 1024 * 1024


def _stable_emitted_file_identity(
    file_stat: os.stat_result,
) -> _StableEmittedFileIdentity:
    return _StableEmittedFileIdentity(
        device=file_stat.st_dev,
        inode=file_stat.st_ino,
        size_bytes=file_stat.st_size,
        modified_ns=file_stat.st_mtime_ns,
    )


def _is_safe_emitted_file_stat(file_stat: os.stat_result, /) -> bool:
    return (
        stat.S_ISREG(file_stat.st_mode)
        and file_stat.st_uid == os.geteuid()
        and file_stat.st_nlink == 1
    )


def _require_file_digest(path: Path, expected_digest: str) -> None:
    file_descriptor = os.open(path, _EMITTED_OUTPUT_READ_FLAGS)
    try:
        before = os.fstat(file_descriptor)
        if not _is_safe_emitted_file_stat(before):
            raise RuntimeError("emitted output is unsafe")
        digest = sha256()
        while chunk := os.read(file_descriptor, _EMITTED_OUTPUT_READ_SIZE):
            digest.update(chunk)
        after = os.fstat(file_descriptor)
        named_after = os.stat(path, follow_symlinks=False)
        before_identity = _stable_emitted_file_identity(before)
        if (
            not _is_safe_emitted_file_stat(after)
            or not _is_safe_emitted_file_stat(named_after)
            or _stable_emitted_file_identity(after) != before_identity
            or _stable_emitted_file_identity(named_after) != before_identity
            or digest.hexdigest() != expected_digest
        ):
            raise RuntimeError("emitted output digest mismatch")
    finally:
        os.close(file_descriptor)


def execute_streaming_run(
    *,
    input_dir: Path,
    output_dir: Path,
    cache_dir: Path,
    strict: bool,
    jobs: int,
    directory_root_policy: DirectoryRootPolicy,
    statement_parser: StatementParser | None,
    monotonic_ns: NanosecondClock,
    after_publication: AfterPublication,
) -> StreamingRunData:
    """Parse, spool, publish, verify, and project one corpus run."""

    start_nanoseconds = monotonic_ns()
    with StatementSpool.create(output_dir) as spool:
        status_counts: Counter[Status] = Counter()

        def consume(ordinal: int, result: StatementResult, /) -> None:
            spool.append(ordinal, result)
            status_counts[result.status] += 1

        conversion = convert_directory_statements(
            input_dir,
            output_dir,
            strict,
            jobs,
            cache_dir=cache_dir,
            statement_parser=statement_parser,
            result_sink=consume,
            directory_root_policy=directory_root_policy,
        )
        spool.seal(conversion.source_count)
        disposition = summarize_batch_statuses(status_counts)
        if disposition.document_count != conversion.source_count:
            raise RuntimeError("statement sink count mismatch")
        write_streaming_batch_outputs(
            conversion.resolved_output_dir,
            status=disposition.status,
            diagnostics=disposition.diagnostics,
            statements=spool.iter_statements,
        )
        end_nanoseconds = monotonic_ns()
        after_publication()
        elapsed_nanoseconds = end_nanoseconds - start_nanoseconds
        if elapsed_nanoseconds < 0:
            raise RuntimeError("monotonic clock moved backwards")
        elapsed_seconds = Decimal(elapsed_nanoseconds) / Decimal(1_000_000_000)
        expected_json_digest, expected_csv_digest = _canonical_stream_digests(
            disposition,
            spool.iter_statements,
        )
        _require_file_digest(
            conversion.resolved_output_dir / "results.json",
            expected_json_digest,
        )
        _require_file_digest(
            conversion.resolved_output_dir / "transactions.csv",
            expected_csv_digest,
        )
        structural_projection = project_statement_stream(
            disposition.status,
            spool.iter_statements(),
        )

    return StreamingRunData(
        batch_status=disposition.status,
        elapsed_seconds=elapsed_seconds,
        json_digest=expected_json_digest,
        csv_digest=expected_csv_digest,
        structural_projection=structural_projection,
    )


__all__ = ["StreamingRunData", "execute_streaming_run"]
