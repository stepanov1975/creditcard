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
from ccparser.layout.models import Cell, TableRegion
from ccparser.models import (
    BatchResult,
    DiscoveryMetadataSummary,
    EvidenceReference,
    PrintedTotalSummary,
    RowNormalizationSummary,
    StatementDiscoverySummary,
    StatementResult,
    Status,
    TableRegionSummary,
)
from ccparser.normalize import StatementNormalization, normalize_statement
from ccparser.output import write_batch_outputs

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


def _cell_evidence(cell: Cell) -> EvidenceReference:
    return EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)


def _table_region_summary(region: TableRegion) -> TableRegionSummary:
    columns = region.table_schema.columns
    diagnostics = tuple(
        dict.fromkeys(
            (
                *region.diagnostics,
                *region.table_schema.diagnostics,
                *(value for column in columns for value in column.diagnostics),
                *region.header.diagnostics,
            )
        )
    )
    return TableRegionSummary(
        page_number=region.page_number,
        bbox=region.bbox,
        header_evidence=tuple(_cell_evidence(cell) for cell in region.header.cells),
        column_roles=tuple(column.role.value for column in columns),
        row_count=len(region.rows),
        confidence=region.confidence,
        diagnostics=diagnostics,
    )


def _discovery_summary(discovery: StatementDiscovery) -> StatementDiscoverySummary:
    metadata_values = (
        discovery.issuer,
        discovery.account_number,
        discovery.card_number,
        discovery.statement_date,
    )
    metadata = tuple(
        DiscoveryMetadataSummary(
            field_name=value.field_name,
            value=value.value,
            evidence=value.evidence,
            confidence=value.confidence,
            diagnostics=value.diagnostics,
        )
        for value in metadata_values
        if value is not None
    )
    printed_totals = tuple(
        PrintedTotalSummary(
            group_id=group.group_id,
            amount_text=group.printed_total.amount_text,
            currency=group.printed_total.currency,
            label_evidence=group.printed_total.label_evidence,
            value_evidence=group.printed_total.value_evidence,
            confidence=group.printed_total.confidence,
            diagnostics=tuple(
                dict.fromkeys((*group.diagnostics, *group.printed_total.diagnostics))
            ),
        )
        for group in discovery.groups
    )
    return StatementDiscoverySummary(
        classification=discovery.classification.value,
        metadata=metadata,
        table_regions=tuple(_table_region_summary(region) for region in discovery.table_regions),
        printed_totals=printed_totals,
        confidence=discovery.confidence,
        reason_codes=discovery.reason_codes,
        diagnostics=discovery.diagnostics,
    )


def _row_summaries(
    normalization: StatementNormalization,
) -> tuple[RowNormalizationSummary, ...]:
    return tuple(
        RowNormalizationSummary(
            page_number=row.page_number,
            bbox=row.bbox,
            raw_text=row.raw_text,
            evidence=row.evidence,
            transaction=row.transaction,
            confidence=row.confidence,
            diagnostics=row.diagnostics,
        )
        for row in normalization.row_results
    )


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
        discovery_summary = _discovery_summary(discovery)
        if discovery.classification is DocumentClassification.NOT_STATEMENT:
            return StatementResult(
                status=Status.NOT_STATEMENT,
                transactions=(),
                groups=(),
                diagnostics=discovery_diagnostics,
                source_name=source.name,
                source_sha256=evidence.source_sha256,
                statement_id=evidence.source_sha256,
                discovery=discovery_summary,
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
                discovery=discovery_summary,
            )
        normalization = normalize(discovery)
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
        return StatementResult(
            status=status,
            transactions=normalization.transactions,
            groups=normalized_result.groups,
            diagnostics=diagnostics,
            source_name=source.name,
            source_sha256=evidence.source_sha256,
            statement_id=evidence.source_sha256,
            discovery=discovery_summary,
            row_results=_row_summaries(normalization),
            normalization_confidence=normalization.confidence,
            normalization_diagnostics=normalization.diagnostics,
        )
    except ParserInputError:
        raise ParserInputError("input PDF processing failed") from None
    except Exception:
        raise ParserRuntimeError("statement processing failed") from None


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

    def raise_walk_error(error: OSError) -> None:
        raise error

    for root_value, directory_names, file_names in os.walk(
        input_dir,
        followlinks=False,
        onerror=raise_walk_error,
    ):
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


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_relative_to(first, second) or _is_relative_to(second, first)


def _validate_path_topology(input_dir: Path, output_dir: Path, cache_dir: Path) -> None:
    output_contains_input = _is_relative_to(input_dir, output_dir)
    cache_contains_input = _is_relative_to(input_dir, cache_dir)
    if output_contains_input or cache_contains_input or _paths_overlap(output_dir, cache_dir):
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
    except (OSError, TypeError, ValueError):
        raise ParserInputError("input or output path cannot be inspected") from None
    try:
        resolved_input = input_path.resolve(strict=True)
        resolved_output = output_path.resolve(strict=False)
        resolved_cache = Path(cache_dir or default_cache_directory()).resolve(strict=False)
        _validate_path_topology(resolved_input, resolved_output, resolved_cache)
        sources = _iter_pdf_files(resolved_input, (resolved_output, resolved_cache))
    except ParserInputError:
        raise
    except OSError:
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
        write_batch_outputs(output_path, batch)
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
