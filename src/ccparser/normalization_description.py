"""Typed merchant-description extraction and continuation ownership."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence
from itertools import pairwise

from ccparser.discovery import DiscoveredDateYearContext
from ccparser.geometry import BBox, bbox_center_x, bbox_center_y, bbox_height
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    isolated_date_token,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.money import is_currency_shaped, is_money_shaped
from ccparser.normalization_dates import (
    _adjacent_boundary_date_completion,
    _horizontal_overlap,
    boundary_date_description_splits,
)
from ccparser.normalization_fields import is_installment_shaped
from ccparser.semantic_evidence import (
    DescriptionExtraction,
    EvidenceClaim,
    EvidenceCluster,
    EvidenceLedger,
    SemanticOwner,
)
from ccparser.text_tokens import normalize_text, phrase_tokens

_HEBREW_GERSHAYIM_PATTERN = re.compile(r'(?<=[\u0590-\u05ff])\s*"\s*(?=[\u0590-\u05ff])')
_SINGLE_RTL_PARENTHETICAL_PATTERN = re.compile(r"^[()]\s*([\u0590-\u05ff])$")


def _cells_for_column(row: Row, column: ColumnSpec) -> tuple[Cell, ...]:
    return cells_in_column(row.cells, column)


def _role_columns(region: TableRegion, role: ColumnRole) -> tuple[ColumnSpec, ...]:
    return columns_for_role(region.table_schema, role)


def _role_cells(row: Row, region: TableRegion, role: ColumnRole) -> tuple[Cell, ...]:
    return tuple(
        cell for column in _role_columns(region, role) for cell in _cells_for_column(row, column)
    )


def _horizontal_coverage(candidate: BBox, container: BBox) -> float:
    width = candidate[2] - candidate[0]
    if width <= 0:
        return 0.0
    overlap = max(0.0, min(candidate[2], container[2]) - max(candidate[0], container[0]))
    return overlap / width


def _is_boundary_description_continuation(
    row: Row,
    previous: Row,
    region: TableRegion,
) -> bool:
    if len(row.cells) != 1 or row.page_number != previous.page_number:
        return False
    cell = row.cells[0]
    text = normalize_text(cell.text)
    if (
        not any(char.isalpha() for char in text)
        or is_money_shaped(text)
        or is_currency_shaped(text)
        or isolated_date_token(text) is not None
        or is_installment_shaped(text)
    ):
        return False
    eligible_rows = tuple(
        candidate
        for candidate in region.rows
        if not has_row_tag(candidate, RowTag.SUBORDINATE_DETAIL)
    )
    billed_column = proven_billed_amount_column(region.table_schema, eligible_rows)
    if billed_column is None:
        return False
    billed_cells = _cells_for_column(previous, billed_column)
    if len(billed_cells) != 1 or not is_money_shaped(billed_cells[0].text):
        return False
    merchant_cells = tuple(
        candidate
        for candidate in previous.cells
        if any(char.isalpha() for char in candidate.text)
        and not is_money_shaped(candidate.text)
        and not is_currency_shaped(candidate.text)
        and isolated_date_token(candidate.text) is None
    )
    ordered_merchant_cells = tuple(sorted(merchant_cells, key=lambda candidate: candidate.bbox[0]))
    typical_merchant_height = (
        statistics.median(bbox_height(candidate.bbox) for candidate in ordered_merchant_cells)
        if ordered_merchant_cells
        else 0.0
    )
    contiguous_merchant_span = len(ordered_merchant_cells) >= 2 and all(
        following.bbox[0] - preceding.bbox[2] <= typical_merchant_height * 0.6
        for preceding, following in pairwise(ordered_merchant_cells)
    )
    merchant_span = (
        (
            ordered_merchant_cells[0].bbox[0],
            min(candidate.bbox[1] for candidate in ordered_merchant_cells),
            ordered_merchant_cells[-1].bbox[2],
            max(candidate.bbox[3] for candidate in ordered_merchant_cells),
        )
        if contiguous_merchant_span
        else None
    )
    if not (
        any(_horizontal_coverage(cell.bbox, candidate.bbox) >= 0.9 for candidate in merchant_cells)
        or (merchant_span is not None and _horizontal_coverage(cell.bbox, merchant_span) >= 0.9)
    ):
        return False
    typical_height = statistics.median(
        bbox_height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def is_description_continuation(row: Row, previous: Row, region: TableRegion) -> bool:
    """Return whether a row remains owned by the preceding transaction description."""

    eligible_rows = tuple(
        candidate
        for candidate in region.rows
        if not has_row_tag(candidate, RowTag.SUBORDINATE_DETAIL)
    )
    billed_column = proven_billed_amount_column(region.table_schema, eligible_rows)
    if has_row_tag(row, RowTag.AUXILIARY_CONTINUATION):
        if billed_column is None or any(
            has_row_tag(previous, tag)
            for tag in (RowTag.AUXILIARY_CONTINUATION, RowTag.SUBORDINATE_DETAIL)
        ):
            return False
        billed_cells = _cells_for_column(previous, billed_column)
        if (
            len(billed_cells) != 1
            or not is_money_shaped(billed_cells[0].text)
            or _cells_for_column(row, billed_column)
        ):
            return False
        typical_height = statistics.median(
            bbox_height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
        )
        gap = max(0.0, row.bbox[1] - previous.bbox[3])
        return gap <= typical_height * 1.5
    if has_row_tag(row, RowTag.SUBORDINATE_DETAIL):
        if billed_column is None:
            return False
        if not has_row_tag(previous, RowTag.SUBORDINATE_DETAIL):
            billed_cells = _cells_for_column(previous, billed_column)
            if len(billed_cells) != 1 or not is_money_shaped(billed_cells[0].text):
                return False
        if _cells_for_column(row, billed_column):
            return False
        typical_height = statistics.median(
            bbox_height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
        )
        gap = max(0.0, row.bbox[1] - previous.bbox[3])
        return gap <= typical_height * 1.5
    if _is_boundary_description_continuation(row, previous, region):
        return True
    description_cells = _role_cells(row, region, ColumnRole.DESCRIPTION)
    has_transaction_fields = any(
        _role_cells(row, region, role)
        for role in (
            ColumnRole.DATE,
            ColumnRole.CONVERSION_DATE,
            ColumnRole.AMOUNT,
            ColumnRole.ORIGINAL_AMOUNT,
            ColumnRole.INSTALLMENT,
        )
    )
    if len(description_cells) != 1 or has_transaction_fields:
        return False
    typical_height = statistics.median(
        bbox_height(candidate.bbox) for candidate in (*previous.cells, *row.cells)
    )
    gap = max(0.0, row.bbox[1] - previous.bbox[3])
    return gap <= typical_height * 1.5


def _text_direction(text: str) -> str:
    rtl = sum(unicodedata.bidirectional(char) in {"R", "AL"} for char in text)
    ltr = sum(unicodedata.bidirectional(char) == "L" for char in text)
    return "rtl" if rtl > ltr else "ltr"


def _cluster_lines(clusters: Sequence[EvidenceCluster]) -> tuple[tuple[EvidenceCluster, ...], ...]:
    lines: list[list[EvidenceCluster]] = []
    for cluster in sorted(clusters, key=lambda item: (item.bbox[1], item.bbox[0])):
        center_y = bbox_center_y(cluster.bbox)
        matching = next(
            (
                line
                for line in lines
                if abs(center_y - bbox_center_y(line[0].bbox))
                <= min(bbox_height(cluster.bbox), bbox_height(line[0].bbox)) * 0.5
            ),
            None,
        )
        if matching is None:
            lines.append([cluster])
        else:
            matching.append(cluster)
    return tuple(tuple(sorted(line, key=lambda item: item.bbox[0])) for line in lines)


def _primary_description_cluster(
    clusters: Sequence[EvidenceCluster],
) -> EvidenceCluster:
    direction = _text_direction(" ".join(cluster.text for cluster in clusters))
    return (
        max(clusters, key=lambda cluster: cluster.bbox[2])
        if direction == "rtl"
        else min(clusters, key=lambda cluster: cluster.bbox[0])
    )


def _cluster_signature(cluster: EvidenceCluster) -> str:
    return " ".join(phrase_tokens(cluster.text))


def _alphabetic_span_signatures(text: str) -> frozenset[str]:
    spans: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isalpha():
            current.append(char)
        elif current:
            spans.append("".join(current))
            current = []
    if current:
        spans.append("".join(current))
    return frozenset(signature for span in spans if (signature := " ".join(phrase_tokens(span))))


def _corroborated_processor_reference_signatures(region: TableRegion) -> frozenset[str]:
    counts: dict[str, int] = {}
    for row in region.rows:
        row_ledger = EvidenceLedger.from_rows((row,))
        description_cells = frozenset(_role_cells(row, region, ColumnRole.DESCRIPTION))
        external_signatures = frozenset(
            signature
            for cell in row.cells
            if cell not in description_cells
            for source_text in (cell.text, *(word.text for word in cell.words))
            for signature in _alphabetic_span_signatures(source_text)
        )
        row_signatures: set[str] = set()
        for cell in description_cells:
            for line in _cluster_lines(row_ledger.clusters_for_cell(cell)):
                if len(line) < 2:
                    continue
                primary = _primary_description_cluster(line)
                row_signatures.update(
                    signature
                    for cluster in line
                    if cluster is not primary
                    and normalize_text(cluster.text).startswith((".", "@"))
                    and (signature := _cluster_signature(cluster)) in external_signatures
                )
        for signature in row_signatures:
            counts[signature] = counts.get(signature, 0) + 1
    return frozenset(signature for signature, count in counts.items() if count >= 2)


def _is_numeric_processor_cluster(cluster: EvidenceCluster) -> bool:
    compact = "".join(cluster.text.split())
    return len(compact) >= 6 and compact.isdigit()


def _is_processor_reference_cluster(
    cluster: EvidenceCluster,
    corroborated_signatures: frozenset[str],
) -> bool:
    normalized = normalize_text(cluster.text)
    return _is_numeric_processor_cluster(cluster) or (
        normalized.startswith((".", "@"))
        and any(char.isalpha() for char in normalized)
        and _cluster_signature(cluster) in corroborated_signatures
    )


def _selected_description_cell_atoms(
    ledger: EvidenceLedger,
    cell: Cell,
    corroborated_signatures: frozenset[str],
) -> tuple[frozenset[int], frozenset[int]]:
    selected: set[int] = set()
    processor: set[int] = set()
    for line in _cluster_lines(ledger.clusters_for_cell(cell)):
        if not line:
            continue
        primary = _primary_description_cluster(line)
        selected.update(primary.atom_ids)
        for cluster in line:
            if cluster is primary:
                continue
            if _is_processor_reference_cluster(cluster, corroborated_signatures):
                processor.update(cluster.atom_ids)
            else:
                selected.update(cluster.atom_ids)
    return frozenset(selected), frozenset(processor)


def _has_competing_description_clusters(
    ledger: EvidenceLedger,
    cells: Sequence[Cell],
    corroborated_signatures: frozenset[str],
) -> bool:
    for cell in cells:
        for line in _cluster_lines(ledger.clusters_for_cell(cell)):
            candidates = tuple(
                cluster
                for cluster in line
                if any(char.isalpha() for char in cluster.text)
                and not _is_processor_reference_cluster(
                    cluster,
                    corroborated_signatures,
                )
            )
            if len(candidates) > 1:
                return True
    return False


def _adjacent_unknown_description_atoms(
    row: Row,
    region: TableRegion,
    ledger: EvidenceLedger,
) -> tuple[frozenset[int], frozenset[int]]:
    description_columns = _role_columns(region, ColumnRole.DESCRIPTION)
    if len(description_columns) != 1:
        return frozenset(), frozenset()
    description_column = description_columns[0]
    description_cells = _cells_for_column(row, description_column)
    if len(description_cells) != 1:
        return frozenset(), frozenset()
    description_cell = description_cells[0]
    selected: set[int] = set()
    ancillary: set[int] = set()
    for column in region.table_schema.columns:
        if (
            column.role is not ColumnRole.UNKNOWN
            or abs(column.index - description_column.index) != 1
        ):
            continue
        for cell in _cells_for_column(row, column):
            lines = _cluster_lines(ledger.clusters_for_cell(cell))
            if len(lines) != 1 or len(lines[0]) < 2:
                continue
            clusters = lines[0]
            cell_is_left = bbox_center_x(cell.bbox) < bbox_center_x(description_cell.bbox)
            boundary_cluster = (
                max(clusters, key=lambda cluster: cluster.bbox[2])
                if cell_is_left
                else min(clusters, key=lambda cluster: cluster.bbox[0])
            )
            gap = (
                description_cell.bbox[0] - boundary_cluster.bbox[2]
                if cell_is_left
                else boundary_cluster.bbox[0] - description_cell.bbox[2]
            )
            tolerance = min(bbox_height(cell.bbox), bbox_height(description_cell.bbox))
            if -tolerance * 0.2 <= gap <= tolerance * 0.6:
                selected.update(boundary_cluster.atom_ids)
                ancillary.update(
                    atom_id
                    for cluster in clusters
                    if cluster is not boundary_cluster
                    for atom_id in cluster.atom_ids
                )
    return frozenset(selected), frozenset(ancillary)


def _merchant_punctuation(text: str) -> str:
    normalized = _HEBREW_GERSHAYIM_PATTERN.sub("״", normalize_text(text))
    compact = normalized.replace(" ", "")
    marker = _SINGLE_RTL_PARENTHETICAL_PATTERN.fullmatch(compact)
    return f"({marker.group(1)})" if marker is not None else normalized


def _description(
    rows: Sequence[Row],
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    ledger: EvidenceLedger,
) -> DescriptionExtraction:
    processor_signatures = _corroborated_processor_reference_signatures(region)
    claims: list[EvidenceClaim] = []
    texts: list[str] = []
    diagnostics: list[str] = []
    eligible_rows = tuple(row for row in rows if not has_row_tag(row, RowTag.SUBORDINATE_DETAIL))
    previous_row: Row | None = None
    for index, row in enumerate(eligible_rows):
        row_cells = _role_cells(row, region, ColumnRole.DESCRIPTION)
        if has_row_tag(row, RowTag.AUXILIARY_CONTINUATION):
            row_cells = tuple(
                cell
                for cell in row_cells
                if _horizontal_overlap(
                    cell.bbox, _role_columns(region, ColumnRole.DESCRIPTION)[0].bbox
                )
                > 0
            )
        elif (
            not row_cells
            and index > 0
            and previous_row is not None
            and _is_boundary_description_continuation(row, previous_row, region)
        ):
            row_cells = row.cells
        selected_ids: set[int] = set()
        processor_ids: set[int] = set()
        fallback_texts: list[str] = []
        if index > 0 and _has_competing_description_clusters(
            ledger,
            row_cells,
            processor_signatures,
        ):
            diagnostics.append("ambiguous_description_continuation")
        for cell in row_cells:
            selected, processor = _selected_description_cell_atoms(
                ledger,
                cell,
                processor_signatures,
            )
            selected_ids.update(selected)
            processor_ids.update(processor)

        date_columns = _role_columns(region, ColumnRole.DATE)
        if len(date_columns) == 1:
            date_cells = _cells_for_column(row, date_columns[0])
            if (
                len(date_cells) == 1
                and (
                    completion := _adjacent_boundary_date_completion(
                        row,
                        date_columns[0],
                        date_cells[0],
                        year_context,
                    )
                )
                is not None
            ):
                _, source_cell, boundary_glyph = completion
                selected_ids.difference_update(
                    atom.atom_id
                    for atom in ledger.atoms
                    if atom.atom_id in ledger.atoms_for_cell(source_cell)
                    and atom.glyph == boundary_glyph
                )

        splits = boundary_date_description_splits(row, region, year_context)
        if len(splits) == 1:
            split_cell, _, residual_text = splits[0]
            split_ids = ledger.atoms_for_cell(split_cell)
            selected_ids.difference_update(split_ids)
            residual_ids = frozenset(
                atom.atom_id
                for atom in ledger.atoms
                if atom.atom_id in split_ids
                and any(char.isalpha() for char in atom.text)
                and not any(char.isdigit() for char in atom.text)
            )
            if residual_ids:
                selected_ids.update(residual_ids)
            else:
                fallback_texts.append(residual_text)
                claims.append(EvidenceClaim(SemanticOwner.DESCRIPTION, split_ids))
        if index == 0:
            adjacent_ids, ancillary_ids = _adjacent_unknown_description_atoms(
                row,
                region,
                ledger,
            )
            selected_ids.update(adjacent_ids)
            if ancillary_ids:
                claims.append(EvidenceClaim(SemanticOwner.ANCILLARY, ancillary_ids))
        rendered = _merchant_punctuation(ledger.render(selected_ids)) if selected_ids else ""
        row_text = normalize_text(" ".join((*fallback_texts, rendered)))
        if row_text:
            texts.append(_merchant_punctuation(row_text))
        if selected_ids:
            claims.append(EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset(selected_ids)))
        if processor_ids:
            claims.append(
                EvidenceClaim(SemanticOwner.PROCESSOR_REFERENCE, frozenset(processor_ids))
            )
        previous_row = row

    if not texts:
        diagnostics.append("missing_description_cell")
        return DescriptionExtraction(None, tuple(claims), tuple(diagnostics))
    return DescriptionExtraction(
        normalize_text(" ".join(_merchant_punctuation(text) for text in texts)),
        tuple(claims),
        tuple(diagnostics),
    )


extract_description = _description
