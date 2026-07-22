"""End-to-end local statement parsing orchestration."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from ccparser.discovery import (
    DocumentClassification,
    StatementDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, TesseractOcr, extract_pdf
from ccparser.evidence.provider import OcrProvider
from ccparser.models import (
    BatchResult,
    StatementResult,
    Status,
)
from ccparser.money import parse_amount
from ccparser.normalize import StatementNormalization, normalize_statement
from ccparser.ocr_repair import repair_table_numeric_ocr
from ccparser.output import write_batch_outputs
from ccparser.paths import (
    DirectoryRootPolicy,
    is_relative_to,
    iter_regular_pdf_files,
    normalize_directory_root,
    paths_overlap,
)
from ccparser.summary import discovery_summary, row_summaries

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
) -> bool:
    outcome = normalization.reconciliation
    return (
        outcome.status is Status.RECONCILED
        and bool(outcome.groups)
        and not normalization.diagnostics
        and not outcome.diagnostics
        and all(not transaction.ambiguities for transaction in normalization.transactions)
        and all(
            group.status is Status.RECONCILED and group.difference == 0 and not group.diagnostics
            for group in outcome.groups
        )
    )


def _numeric_ocr_repair_inputs(
    discovery: StatementDiscovery,
) -> tuple[tuple[str, ...], tuple[Decimal, ...]]:
    currency_hints = tuple(group.printed_total.currency for group in discovery.groups)
    expected_totals = tuple(
        parsed.amount
        for group in discovery.groups
        if (
            parsed := parse_amount(
                group.printed_total.amount_text,
                currency_hint=group.printed_total.currency,
            )
        ).amount
        is not None
    )
    return currency_hints, expected_totals


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
    try:
        source = Path(path)
        if not source.exists() or not source.is_file():
            raise ParserInputError("input PDF must be an existing regular file")
    except ParserInputError:
        raise
    except (OSError, TypeError, ValueError):
        raise ParserInputError("input PDF cannot be inspected") from None
    try:
        provider = (
            ocr_provider
            if ocr_provider is not None
            else TesseractOcr(cache_dir or default_cache_directory())
        )
        extract = extractor or extract_pdf
        discover = discoverer or discover_statement
        normalize = normalizer or normalize_statement
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
                discovery=discovery_summary(discovery),
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
                discovery=discovery_summary(discovery),
            )
        normalization = normalize(discovery)
        if not _is_exact_unambiguous(normalization) and any(
            page.quality.requires_ocr for page in evidence.pages
        ):
            currency_hints, expected_totals = _numeric_ocr_repair_inputs(discovery)
            repaired_evidence = repair_table_numeric_ocr(
                evidence,
                source.read_bytes(),
                provider,
                currency_hints=currency_hints,
                expected_totals=expected_totals,
            )
            if repaired_evidence != evidence:
                repaired_discovery = discover(repaired_evidence)
                if repaired_discovery.classification is DocumentClassification.STATEMENT:
                    repaired_normalization = normalize(repaired_discovery)
                    if _is_exact_unambiguous(repaired_normalization):
                        evidence = repaired_evidence
                        discovery = repaired_discovery
                        discovery_diagnostics = _diagnostics(discovery)
                        normalization = repaired_normalization
        status = Status.RECONCILED if _is_exact_unambiguous(normalization) else Status.UNRECONCILED
        reconciliation = normalization.reconciliation
        diagnostics = tuple(
            dict.fromkeys(
                (
                    *discovery_diagnostics,
                    *normalization.diagnostics,
                    *reconciliation.diagnostics,
                )
            )
        )
        return StatementResult(
            status=status,
            transactions=normalization.transactions,
            groups=reconciliation.groups,
            diagnostics=diagnostics,
            source_name=source.name,
            source_sha256=evidence.source_sha256,
            statement_id=evidence.source_sha256,
            discovery=discovery_summary(discovery),
            row_results=row_summaries(normalization),
            normalization_confidence=normalization.confidence,
            normalization_diagnostics=normalization.diagnostics,
        )
    except ParserInputError:
        raise ParserInputError("input PDF processing failed") from None
    except Exception:
        raise ParserRuntimeError("statement processing failed") from None


def _validate_path_topology(input_dir: Path, output_dir: Path, cache_dir: Path) -> None:
    output_contains_input = is_relative_to(input_dir, output_dir)
    cache_contains_input = is_relative_to(input_dir, cache_dir)
    if output_contains_input or cache_contains_input or paths_overlap(output_dir, cache_dir):
        raise ParserInputError("input, output, and cache path topology is unsafe")


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
    directory_root_policy: DirectoryRootPolicy = DirectoryRootPolicy.RESOLVE,
) -> BatchResult:
    """Recursively parse PDF files and atomically write deterministic aggregate output."""

    if jobs is not None and (isinstance(jobs, bool) or not isinstance(jobs, int) or jobs <= 0):
        raise ParserInputError("jobs must be a positive integer")
    try:
        input_path = Path(path)
        if not input_path.exists() or not input_path.is_dir():
            raise ParserInputError("input must be an existing directory")
        output_path = Path(output_dir)
        if output_path.exists() and not output_path.is_dir():
            raise ParserInputError("output directory must be a directory")
    except ParserInputError:
        raise
    except Exception:
        raise ParserInputError("input or output path cannot be inspected") from None
    try:
        resolved_input = normalize_directory_root(
            input_path,
            policy=directory_root_policy,
            strict=True,
        )
        resolved_output = normalize_directory_root(
            output_path,
            policy=directory_root_policy,
            strict=False,
        )
    except Exception:
        raise ParserInputError("input directory cannot be inspected") from None
    try:
        selected_cache = Path(cache_dir) if cache_dir is not None else default_cache_directory()
        resolved_cache = normalize_directory_root(
            selected_cache,
            policy=directory_root_policy,
            strict=False,
        )
    except Exception:
        if cache_dir is None:
            raise ParserRuntimeError("default cache directory resolution failed") from None
        raise ParserInputError("cache directory cannot be inspected") from None
    try:
        _validate_path_topology(resolved_input, resolved_output, resolved_cache)

        def raise_walk_error(error: OSError) -> None:
            raise error

        sources = iter_regular_pdf_files(
            resolved_input,
            excluded_roots=(resolved_output, resolved_cache),
            on_error=raise_walk_error,
            root_policy=directory_root_policy,
        )
    except ParserInputError:
        raise
    except Exception:
        raise ParserInputError("input directory cannot be inspected") from None

    if not sources:
        batch = BatchResult(
            status=Status.UNSUPPORTED,
            statements=(),
            diagnostics=("no_pdf_files",),
        )
    else:
        parse = statement_parser or parse_statement

        def parse_source(source: Path) -> StatementResult:
            result = parse(source, strict, cache_dir=resolved_cache)
            relative_name = source.relative_to(resolved_input).as_posix()
            return result.model_copy(update={"source_name": relative_name})

        requested_workers = jobs if jobs is not None else (os.cpu_count() or 1)
        worker_count = min(MAX_WORKERS, requested_workers, len(sources))
        try:
            if worker_count == 1:
                statements = tuple(parse_source(source) for source in sources)
            else:
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    statements = tuple(executor.map(parse_source, sources))
        except ParserInputError:
            raise ParserInputError("directory input processing failed") from None
        except Exception:
            raise ParserRuntimeError("directory statement processing failed") from None
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
        write_batch_outputs(resolved_output, batch)
    except Exception:
        raise ParserRuntimeError("output writing failed") from None
    return batch


__all__ = [
    "ParserError",
    "ParserInputError",
    "ParserRuntimeError",
    "default_cache_directory",
    "parse_directory",
    "parse_statement",
]
