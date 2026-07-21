"""Explicit typed projection from parser evidence to public summary models."""

from __future__ import annotations

from ccparser.discovery import StatementDiscovery, StatementGroupDiscovery
from ccparser.evidence.models import Glyph, Word
from ccparser.layout.models import Cell, ColumnSpec, Row, TableRegion, TableSchema
from ccparser.models import (
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
    TableRegionSummary,
)
from ccparser.normalize import StatementNormalization


def _cell_evidence(cell: Cell) -> EvidenceReference:
    return EvidenceReference(page_number=cell.page_number, bbox=cell.bbox, raw_text=cell.text)


def glyph_summary(glyph: Glyph) -> DiscoveryGlyphSummary:
    """Project one positioned glyph to its dependency-neutral public summary."""

    return DiscoveryGlyphSummary(
        char=glyph.char,
        bbox=glyph.bbox,
        origin=glyph.origin,
        font=glyph.font,
        size=glyph.size,
        source=glyph.source,
        confidence=glyph.confidence,
    )


def word_summary(word: Word) -> DiscoveryWordSummary:
    """Project one positioned word to its dependency-neutral public summary."""

    return DiscoveryWordSummary(
        text=word.text,
        bbox=word.bbox,
        source=word.source,
        confidence=word.confidence,
    )


def cell_summary(cell: Cell) -> DiscoveryCellSummary:
    """Project one logical cell with all of its positioned provenance."""

    return DiscoveryCellSummary(
        page_number=cell.page_number,
        bbox=cell.bbox,
        text=cell.text,
        glyphs=tuple(glyph_summary(glyph) for glyph in cell.glyphs),
        words=tuple(word_summary(word) for word in cell.words),
        confidence=cell.confidence,
        diagnostics=cell.diagnostics,
    )


def row_summary(row: Row) -> DiscoveryRowSummary:
    """Project one logical row with its cells, words, and diagnostics."""

    return DiscoveryRowSummary(
        page_number=row.page_number,
        bbox=row.bbox,
        cells=tuple(cell_summary(cell) for cell in row.cells),
        words=tuple(word_summary(word) for word in row.words),
        confidence=row.confidence,
        diagnostics=row.diagnostics,
    )


def column_summary(column: ColumnSpec) -> DiscoveryColumnSummary:
    """Project one inferred semantic column and its supporting cells."""

    return DiscoveryColumnSummary(
        index=column.index,
        page_number=column.page_number,
        bbox=column.bbox,
        relative_x0=column.relative_x0,
        relative_x1=column.relative_x1,
        role=column.role.value,
        source_cells=tuple(cell_summary(cell) for cell in column.source_cells),
        confidence=column.confidence,
        diagnostics=column.diagnostics,
    )


def table_schema_summary(schema: TableSchema) -> DiscoveryTableSchemaSummary:
    """Project one complete inferred table schema."""

    return DiscoveryTableSchemaSummary(
        page_number=schema.page_number,
        bbox=schema.bbox,
        columns=tuple(column_summary(column) for column in schema.columns),
        header_cells=tuple(cell_summary(cell) for cell in schema.header_cells),
        sample_cells=tuple(cell_summary(cell) for cell in schema.sample_cells),
        confidence=schema.confidence,
        diagnostics=schema.diagnostics,
    )


def table_region_summary(region: TableRegion) -> TableRegionSummary:
    """Project one table region without changing its flat discovery ownership."""

    columns = region.table_schema.columns
    return TableRegionSummary(
        page_number=region.page_number,
        bbox=region.bbox,
        header_evidence=tuple(_cell_evidence(cell) for cell in region.header.cells),
        column_roles=tuple(column.role.value for column in columns),
        row_count=len(region.rows),
        header=row_summary(region.header),
        rows=tuple(row_summary(row) for row in region.rows),
        table_schema=table_schema_summary(region.table_schema),
        confidence=region.confidence,
        diagnostics=region.diagnostics,
    )


def printed_total_summary(group: StatementGroupDiscovery) -> PrintedTotalSummary:
    """Project the printed total owned by one discovery group."""

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


def group_summary(group: StatementGroupDiscovery) -> StatementGroupDiscoverySummary:
    """Project one discovered group and its exact region association."""

    return StatementGroupDiscoverySummary(
        group_id=group.group_id,
        table_regions=tuple(table_region_summary(region) for region in group.table_regions),
        printed_total=printed_total_summary(group),
        confidence=group.confidence,
        diagnostics=group.diagnostics,
    )


def discovery_summary(discovery: StatementDiscovery) -> StatementDiscoverySummary:
    """Project complete discovery state without deriving regions from groups."""

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
    groups = tuple(group_summary(group) for group in discovery.groups)
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
        table_regions=tuple(table_region_summary(region) for region in discovery.table_regions),
        printed_totals=tuple(group.printed_total for group in groups),
        confidence=discovery.confidence,
        reason_codes=discovery.reason_codes,
        diagnostics=discovery.diagnostics,
    )


def row_summaries(
    normalization: StatementNormalization,
) -> tuple[RowNormalizationSummary, ...]:
    """Project every accepted, rejected, or merged normalization row."""

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


__all__ = [
    "cell_summary",
    "column_summary",
    "discovery_summary",
    "glyph_summary",
    "group_summary",
    "printed_total_summary",
    "row_summaries",
    "row_summary",
    "table_region_summary",
    "table_schema_summary",
    "word_summary",
]
