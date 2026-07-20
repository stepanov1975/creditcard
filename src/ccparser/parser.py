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
    StatementGroupDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, Glyph, TesseractOcr, Word, extract_pdf
from ccparser.evidence.provider import OcrProvider
from ccparser.layout.models import Cell, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
    BatchResult,
    DiscoveryCellSummary,
    DiscoveryColumnSummary,
    DiscoveryDateYearContextSummary,
    DiscoveryGlyphSummary,
    DiscoveryMetadataSummary,
    DiscoveryRowSummary,
    DiscoveryTableSchemaSummary,
    DiscoveryWordSummary,
    EvidenceReference,
    PrintedTotalSummary,
    RejectedTotalCandidateSummary,
    RowNormalizationSummary,
    StatementDiscoverySummary,
    StatementGroupDiscoverySummary,
    StatementResult,
    Status,
    TableRegionSummary,
)
from ccparser.money import parse_amount
from ccparser.normalize import StatementNormalization, normalize_statement
from ccparser.ocr_repair import repair_table_numeric_ocr
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


def _glyph_summary(glyph: Glyph) -> DiscoveryGlyphSummary:
    return DiscoveryGlyphSummary(
        char=glyph.char,
        bbox=glyph.bbox,
        origin=glyph.origin,
        font=glyph.font,
        size=glyph.size,
        source=glyph.source,
        confidence=glyph.confidence,
    )


def _word_summary(word: Word) -> DiscoveryWordSummary:
    return DiscoveryWordSummary(
        text=word.text,
        bbox=word.bbox,
        source=word.source,
        confidence=word.confidence,
    )


def _cell_summary(cell: Cell) -> DiscoveryCellSummary:
    return DiscoveryCellSummary(
        page_number=cell.page_number,
        bbox=cell.bbox,
        text=cell.text,
        glyphs=tuple(_glyph_summary(glyph) for glyph in cell.glyphs),
        words=tuple(_word_summary(word) for word in cell.words),
        confidence=cell.confidence,
        diagnostics=cell.diagnostics,
    )


def _row_summary(row: Row) -> DiscoveryRowSummary:
    return DiscoveryRowSummary(
        page_number=row.page_number,
        bbox=row.bbox,
        cells=tuple(_cell_summary(cell) for cell in row.cells),
        words=tuple(_word_summary(word) for word in row.words),
        confidence=row.confidence,
        diagnostics=row.diagnostics,
    )


def _column_summary(column: ColumnSpec) -> DiscoveryColumnSummary:
    return DiscoveryColumnSummary(
        index=column.index,
        page_number=column.page_number,
        bbox=column.bbox,
        relative_x0=column.relative_x0,
        relative_x1=column.relative_x1,
        role=column.role.value,
        source_cells=tuple(_cell_summary(cell) for cell in column.source_cells),
        confidence=column.confidence,
        diagnostics=column.diagnostics,
    )


def _table_schema_summary(schema: TableSchema) -> DiscoveryTableSchemaSummary:
    return DiscoveryTableSchemaSummary(
        page_number=schema.page_number,
        bbox=schema.bbox,
        columns=tuple(_column_summary(column) for column in schema.columns),
        header_cells=tuple(_cell_summary(cell) for cell in schema.header_cells),
        sample_cells=tuple(_cell_summary(cell) for cell in schema.sample_cells),
        confidence=schema.confidence,
        diagnostics=schema.diagnostics,
    )


def _table_region_summary(region: TableRegion) -> TableRegionSummary:
    columns = region.table_schema.columns
    return TableRegionSummary(
        page_number=region.page_number,
        bbox=region.bbox,
        header_evidence=tuple(_cell_evidence(cell) for cell in region.header.cells),
        column_roles=tuple(column.role.value for column in columns),
        row_count=len(region.rows),
        header=_row_summary(region.header),
        rows=tuple(_row_summary(row) for row in region.rows),
        table_schema=_table_schema_summary(region.table_schema),
        confidence=region.confidence,
        diagnostics=region.diagnostics,
    )


def _printed_total_summary(group: StatementGroupDiscovery) -> PrintedTotalSummary:
    total = group.printed_total
    return PrintedTotalSummary(
        group_id=group.group_id,
        amount_text=total.amount_text,
        currency=total.currency,
        label_evidence=total.label_evidence,
        value_evidence=total.value_evidence,
        confidence=total.confidence,
        diagnostics=total.diagnostics,
    )


def _group_summary(group: StatementGroupDiscovery) -> StatementGroupDiscoverySummary:
    return StatementGroupDiscoverySummary(
        group_id=group.group_id,
        table_regions=tuple(_table_region_summary(region) for region in group.table_regions),
        printed_total=_printed_total_summary(group),
        confidence=group.confidence,
        diagnostics=group.diagnostics,
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
    groups = tuple(_group_summary(group) for group in discovery.groups)
    date_year_context = discovery.date_year_context
    return StatementDiscoverySummary(
        classification=discovery.classification.value,
        metadata=metadata,
        date_year_context=(
            DiscoveryDateYearContextSummary(
                year=date_year_context.year,
                year_by_suffix=(
                    date_year_context.year_by_suffix
                    or (
                        ((date_year_context.year % 100, date_year_context.year),)
                        if date_year_context.year is not None
                        else ()
                    )
                ),
                style=date_year_context.style.value,
                evidence=date_year_context.evidence,
                metadata_evidence=date_year_context.metadata_evidence,
                confidence=date_year_context.confidence,
                diagnostics=date_year_context.diagnostics,
            )
            if date_year_context is not None
            else None
        ),
        rejected_total_candidates=tuple(
            RejectedTotalCandidateSummary(
                evidence=candidate.evidence,
                confidence=candidate.confidence,
                diagnostics=candidate.diagnostics,
            )
            for candidate in discovery.rejected_total_candidates
        ),
        groups=groups,
        table_regions=tuple(_table_region_summary(region) for region in discovery.table_regions),
        printed_totals=tuple(group.printed_total for group in groups),
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
                discovery=_discovery_summary(discovery),
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
                discovery=_discovery_summary(discovery),
            )
        normalization = normalize(discovery)
        normalized_result = normalization.reconciliation
        if not _is_exact_unambiguous(
            normalization,
            normalized_result,
        ) and any(page.quality.requires_ocr for page in evidence.pages):
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
                    repaired_result = repaired_normalization.reconciliation
                    if _is_exact_unambiguous(repaired_normalization, repaired_result):
                        evidence = repaired_evidence
                        discovery = repaired_discovery
                        discovery_diagnostics = _diagnostics(discovery)
                        normalization = repaired_normalization
                        normalized_result = repaired_result
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
            discovery=_discovery_summary(discovery),
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
    except Exception:
        raise ParserInputError("input or output path cannot be inspected") from None
    try:
        resolved_input = input_path.resolve(strict=True)
        resolved_output = output_path.resolve(strict=False)
    except Exception:
        raise ParserInputError("input directory cannot be inspected") from None
    try:
        selected_cache = Path(cache_dir) if cache_dir is not None else default_cache_directory()
        resolved_cache = selected_cache.resolve(strict=False)
    except Exception:
        if cache_dir is None:
            raise ParserRuntimeError("default cache directory resolution failed") from None
        raise ParserInputError("cache directory cannot be inspected") from None
    try:
        _validate_path_topology(resolved_input, resolved_output, resolved_cache)
        sources = _iter_pdf_files(resolved_input, (resolved_output, resolved_cache))
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
