"""Semantic and structural transaction-table region detection."""

from __future__ import annotations

import statistics
import unicodedata
from collections.abc import Sequence

from ccparser.evidence.models import BBox, PageEvidence
from ccparser.layout.columns import infer_column_roles
from ccparser.layout.models import ColumnRole, Row, TableRegion, TableSchema
from ccparser.layout.rows import cluster_rows

_TOTAL_MARKERS = frozenset(
    {
        "grand total",
        "subtotal",
        "total",
        "סהכ",
        "סך הכל",
        "סכום כולל",
    }
)


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2


def _union_bbox(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _normalized_marker(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in normalized).split())


def _is_total_row(row: Row) -> bool:
    return any(
        normalized == marker or normalized.startswith(marker + " ")
        for cell in row.cells
        for normalized in (_normalized_marker(cell.text),)
        for marker in _TOTAL_MARKERS
    )


def _literal_header_role_count(row: Row) -> int:
    if len(row.cells) < 2:
        return 0
    schema = infer_column_roles(row.cells, ())
    return sum(
        column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
        for column in schema.columns
    )


def _plausible_header(schema: TableSchema) -> bool:
    header_roles = {
        column.role
        for column in schema.columns
        if column.role is not ColumnRole.UNKNOWN and "role_evidence:header" in column.diagnostics
    }
    amount_role = bool(header_roles & {ColumnRole.AMOUNT, ColumnRole.ORIGINAL_AMOUNT})
    context_role = bool(
        header_roles & {ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.CURRENCY}
    )
    return len(schema.columns) >= 2 and len(header_roles) >= 2 and amount_role and context_role


def _structural_gap(previous: Row, current: Row, observed: Sequence[Row]) -> bool:
    typical_height = statistics.median(_height(row.bbox) for row in observed)
    gap = max(0.0, current.bbox[1] - previous.bbox[3])
    return gap > typical_height * 2.5


def _row_alignment(row: Row, schema: TableSchema) -> float:
    matched_columns: set[int] = set()
    for cell in row.cells:
        center = _center_x(cell.bbox)
        candidates = tuple(
            column
            for column in schema.columns
            if column.bbox[0] - (column.bbox[2] - column.bbox[0]) * 0.15
            <= center
            <= column.bbox[2] + (column.bbox[2] - column.bbox[0]) * 0.15
        )
        if candidates:
            nearest = min(
                candidates,
                key=lambda column: abs(center - _center_x(column.bbox)),
            )
            matched_columns.add(nearest.index)
    return len(matched_columns) / len(schema.columns) if schema.columns else 0.0


def _preview_rows(rows: Sequence[Row], header_index: int) -> tuple[Row, ...]:
    preview: list[Row] = []
    previous = rows[header_index]
    for row in rows[header_index + 1 :]:
        if len(preview) >= 3:
            break
        if _is_total_row(row) or _structural_gap(previous, row, (rows[header_index], *preview)):
            break
        if _literal_header_role_count(row) >= 2:
            break
        preview.append(row)
        previous = row
    return tuple(preview)


def _candidate_schema(rows: Sequence[Row], header_index: int) -> TableSchema:
    header = rows[header_index]
    preview = _preview_rows(rows, header_index)
    samples = tuple(cell for row in preview for cell in row.cells)
    return infer_column_roles(header.cells, samples)


def _detect_from_header(rows: Sequence[Row], header_index: int) -> tuple[TableRegion | None, int]:
    header = rows[header_index]
    schema = _candidate_schema(rows, header_index)
    if not _plausible_header(schema):
        return None, header_index + 1

    accepted: list[Row] = []
    stop_reason: str | None = None
    stop_index = len(rows)
    previous = header
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 1):
        if _is_total_row(row):
            stop_reason = "stopped_at_total"
            stop_index = index
            break
        if _structural_gap(previous, row, (header, *accepted)):
            stop_reason = "stopped_at_structural_gap"
            stop_index = index
            break
        if _literal_header_role_count(row) >= 2:
            stop_reason = "stopped_at_new_header"
            stop_index = index
            break
        alignment = _row_alignment(row, schema)
        minimum_alignment = max(2 / len(schema.columns), 0.6)
        if alignment < minimum_alignment:
            stop_reason = "stopped_at_structure_change"
            stop_index = index
            break
        accepted.append(row)
        previous = row

    if len(accepted) < 2:
        return None, header_index + 1

    sample_cells = tuple(cell for row in accepted for cell in row.cells)
    final_schema = infer_column_roles(header.cells, sample_cells)
    bbox = _union_bbox((header.bbox, *(row.bbox for row in accepted)))
    alignments = tuple(_row_alignment(row, final_schema) for row in accepted)
    diagnostics = [f"repeated_rows:{len(accepted)}"]
    if stop_reason is not None:
        diagnostics.append(stop_reason)
    diagnostics.extend(f"schema:{diagnostic}" for diagnostic in final_schema.diagnostics)
    confidence = statistics.mean(
        (
            final_schema.confidence,
            statistics.mean(row.confidence for row in accepted),
            statistics.mean(alignments),
        )
    )
    region = TableRegion(
        page_number=header.page_number,
        bbox=bbox,
        header=header,
        rows=tuple(accepted),
        table_schema=final_schema,
        confidence=confidence,
        diagnostics=tuple(diagnostics),
    )
    return region, stop_index


def detect_table_regions(page_evidence: PageEvidence) -> tuple[TableRegion, ...]:
    """Detect plausible repeated transaction tables without document identity rules."""

    rows = cluster_rows(page_evidence.words, page_evidence.page_number)
    regions: list[TableRegion] = []
    index = 0
    while index < len(rows):
        region, next_index = _detect_from_header(rows, index)
        if region is not None:
            regions.append(region)
        index = max(next_index, index + 1)
    return tuple(regions)
