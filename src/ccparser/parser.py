"""End-to-end local statement parsing orchestration."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from ccparser.discovery import (
    DocumentClassification,
    StatementDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, TesseractOcr, extract_pdf
from ccparser.evidence.provider import OcrProvider
from ccparser.models import BatchResult, StatementResult, Status
from ccparser.normalize import StatementNormalization, normalize_statement
from ccparser.output import write_csv_atomic, write_json_atomic

MAX_WORKERS = 32


class ParserError(RuntimeError):
    """Base class for privacy-safe parser boundary errors."""


class ParserInputError(ParserError):
    """The requested input cannot be inspected as a regular PDF file."""


class ParserRuntimeError(ParserError):
    """A local parser dependency or processing stage failed."""


class EvidenceExtractor(Protocol):
    def __call__(
        self,
        path: Path,
        ocr_provider: OcrProvider | None,
    ) -> DocumentEvidence: ...


class StatementDiscoverer(Protocol):
    def __call__(self, evidence: DocumentEvidence) -> StatementDiscovery: ...


class StatementNormalizer(Protocol):
    def __call__(self, discovery: StatementDiscovery) -> StatementNormalization: ...


class StatementParser(Protocol):
    def __call__(
        self,
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult: ...


def default_cache_directory() -> Path:
    """Return the process-local persistent OCR cache outside document trees."""

    return Path.home() / ".cache" / "ccparser" / "ocr"


def _diagnostics(discovery: StatementDiscovery) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*discovery.reason_codes, *discovery.diagnostics)))


def _is_exact_unambiguous(
    normalization: StatementNormalization,
    result: StatementResult,
) -> bool:
    return (
        result.status is Status.RECONCILED
        and bool(result.groups)
        and not normalization.diagnostics
        and not result.diagnostics
        and all(not transaction.ambiguities for transaction in result.transactions)
        and all(
            group.status is Status.RECONCILED and group.difference == 0 and not group.diagnostics
            for group in result.groups
        )
    )


def parse_statement(
    path: str | Path,
    strict: bool = False,
    *,
    cache_dir: str | Path | None = None,
    ocr_provider: OcrProvider | None = None,
    extractor: EvidenceExtractor | None = None,
    discoverer: StatementDiscoverer | None = None,
    normalizer: StatementNormalizer | None = None,
) -> StatementResult:
    """Parse one PDF locally and return a conservative, evidence-backed result."""

    del strict
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise ParserInputError("input PDF must be an existing regular file")
    provider = ocr_provider or TesseractOcr(cache_dir or default_cache_directory())
    extract = extractor or extract_pdf
    discover = discoverer or discover_statement
    normalize = normalizer or normalize_statement
    try:
        evidence = extract(source, provider)
        discovery = discover(evidence)
        discovery_diagnostics = _diagnostics(discovery)
        if discovery.classification is DocumentClassification.NOT_STATEMENT:
            return StatementResult(
                status=Status.NOT_STATEMENT,
                transactions=(),
                groups=(),
                diagnostics=discovery_diagnostics,
                source_name=source.name,
                source_sha256=evidence.source_sha256,
                statement_id=evidence.source_sha256,
            )
        if discovery.classification is DocumentClassification.AMBIGUOUS:
            return StatementResult(
                status=Status.UNSUPPORTED,
                transactions=(),
                groups=(),
                diagnostics=discovery_diagnostics,
                source_name=source.name,
                source_sha256=evidence.source_sha256,
                statement_id=evidence.source_sha256,
            )
        normalization = normalize(discovery)
    except ParserError:
        raise
    except Exception as error:
        raise ParserRuntimeError("statement processing failed") from error

    normalized_result = normalization.reconciliation
    status = (
        Status.RECONCILED
        if _is_exact_unambiguous(normalization, normalized_result)
        else Status.UNRECONCILED
    )
    diagnostics = tuple(
        dict.fromkeys(
            (
                *discovery_diagnostics,
                *normalization.diagnostics,
                *normalized_result.diagnostics,
            )
        )
    )
    return normalized_result.model_copy(
        update={
            "status": status,
            "diagnostics": diagnostics,
            "source_name": source.name,
            "source_sha256": evidence.source_sha256,
            "statement_id": evidence.source_sha256,
        }
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _iter_pdf_files(
    input_dir: Path,
    excluded_trees: tuple[Path, ...],
) -> tuple[Path, ...]:
    files: list[Path] = []
    for root_value, directory_names, file_names in os.walk(input_dir, followlinks=False):
        root = Path(root_value)
        retained_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory = root / directory_name
            resolved = directory.resolve(strict=False)
            if directory.is_symlink() or any(
                excluded != input_dir and _is_relative_to(resolved, excluded)
                for excluded in excluded_trees
            ):
                continue
            retained_directories.append(directory_name)
        directory_names[:] = retained_directories
        for file_name in sorted(file_names):
            source = root / file_name
            if source.suffix.casefold() != ".pdf" or source.is_symlink() or not source.is_file():
                continue
            resolved = source.resolve(strict=False)
            if any(
                excluded != input_dir and _is_relative_to(resolved, excluded)
                for excluded in excluded_trees
            ):
                continue
            files.append(source)
    return tuple(sorted(files, key=lambda source: source.relative_to(input_dir).as_posix()))


def _batch_status(statements: tuple[StatementResult, ...]) -> Status:
    statuses = tuple(statement.status for statement in statements)
    if statuses and all(status is Status.RECONCILED for status in statuses):
        return Status.RECONCILED
    if any(status is Status.UNRECONCILED for status in statuses):
        return Status.UNRECONCILED
    if statuses and all(status is Status.NOT_STATEMENT for status in statuses):
        return Status.NOT_STATEMENT
    return Status.UNSUPPORTED


def parse_directory(
    path: str | Path,
    output_dir: str | Path,
    strict: bool = False,
    jobs: int | None = None,
    *,
    cache_dir: str | Path | None = None,
    statement_parser: StatementParser | None = None,
) -> BatchResult:
    """Recursively parse PDF files and atomically write deterministic aggregate output."""

    if jobs is not None and (isinstance(jobs, bool) or not isinstance(jobs, int) or jobs <= 0):
        raise ParserInputError("jobs must be a positive integer")
    input_path = Path(path)
    if not input_path.exists() or not input_path.is_dir():
        raise ParserInputError("input must be an existing directory")
    output_path = Path(output_dir)
    if output_path.exists() and not output_path.is_dir():
        raise ParserInputError("output directory must be a directory")
    try:
        resolved_input = input_path.resolve(strict=True)
        resolved_output = output_path.resolve(strict=False)
        resolved_cache = Path(cache_dir or default_cache_directory()).resolve(strict=False)
        sources = _iter_pdf_files(resolved_input, (resolved_output, resolved_cache))
    except OSError as error:
        raise ParserInputError("input directory cannot be inspected") from error

    if not sources:
        batch = BatchResult(
            status=Status.UNSUPPORTED,
            statements=(),
            diagnostics=("no_pdf_files",),
        )
    else:
        parse = statement_parser or parse_statement

        def parse_source(source: Path) -> StatementResult:
            try:
                result = parse(source, strict, cache_dir=resolved_cache)
            except ParserError:
                raise
            except Exception as error:
                raise ParserRuntimeError("directory statement processing failed") from error
            relative_name = source.relative_to(resolved_input).as_posix()
            return result.model_copy(update={"source_name": relative_name})

        requested_workers = jobs if jobs is not None else (os.cpu_count() or 1)
        worker_count = min(MAX_WORKERS, requested_workers, len(sources))
        if worker_count == 1:
            statements = tuple(parse_source(source) for source in sources)
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                statements = tuple(executor.map(parse_source, sources))
        non_reconciled_count = sum(
            statement.status is not Status.RECONCILED for statement in statements
        )
        diagnostics = (
            (f"documents_not_reconciled:{non_reconciled_count}",) if non_reconciled_count else ()
        )
        batch = BatchResult(
            status=_batch_status(statements),
            statements=statements,
            diagnostics=diagnostics,
        )

    try:
        write_json_atomic(output_path / "results.json", batch)
        write_csv_atomic(output_path / "transactions.csv", batch)
    except OSError as error:
        raise ParserRuntimeError("output writing failed") from error
    return batch


__all__ = [
    "ParserError",
    "ParserInputError",
    "ParserRuntimeError",
    "default_cache_directory",
    "parse_directory",
    "parse_statement",
]
