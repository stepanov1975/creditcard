"""Typed merchant-description extraction and continuation ownership."""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections.abc import Sequence
from itertools import pairwise

from ccparser.discovery import DiscoveredDateYearContext
from ccparser.geometry import (
    BBox,
    bbox_center_x,
    bbox_center_y,
    bbox_height,
    horizontal_overlap,
    union_bbox,
    vertical_overlap,
)
from ccparser.layout.columns import (
    cells_in_column,
    columns_for_role,
    isolated_date_token,
    proven_billed_amount_column,
)
from ccparser.layout.models import Cell, ColumnRole, ColumnSpec, Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.layout.text import _dominant_direction
from ccparser.money import is_currency_shaped, is_money_shaped
from ccparser.normalization_dates import (
    adjacent_boundary_date_completion,
    boundary_date_description_splits,
    positioned_date_description_residual_atom_ids,
)
from ccparser.normalization_fields import is_installment_shaped
from ccparser.semantic_evidence import (
    DescriptionExtraction,
    EvidenceAtomKind,
    EvidenceClaim,
    EvidenceCluster,
    EvidenceLedger,
    SemanticOwner,
)
from ccparser.text_tokens import normalize_text

_HEBREW_GERSHAYIM_PATTERN = re.compile(r'(?<=[\u0590-\u05ff])\s*"\s*(?=[\u0590-\u05ff])')
_SINGLE_RTL_PARENTHETICAL_PATTERN = re.compile(r"^[()]\s*([\u0590-\u05ff])$")
_NUMERIC_EDGE_WRAPPERS = "+-\N{MINUS SIGN}()"
_NUMERIC_BODY_SEPARATORS = frozenset(".,")


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
    overlap = horizontal_overlap(candidate, container)
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


def _has_bounded_processor_identifier_shape(text: str) -> bool:
    normalized = normalize_text(text)
    compact = "".join(normalized.split())
    separators = tuple(index for index, char in enumerate(compact) if not char.isdigit())
    return sum(char.isdigit() for char in compact) >= 6 and (
        not separators
        or (
            len(separators) == 1
            and 0 < separators[0] < len(compact) - 1
            and unicodedata.category(compact[separators[0]]) == "Pd"
        )
    )


def is_numeric_processor_reference(text: str) -> bool:
    """Return whether text has a bounded, non-financial processor-reference shape."""

    normalized = normalize_text(text)
    return (
        _has_bounded_processor_identifier_shape(normalized)
        and not _is_typed_non_description_text(normalized)
        and not _is_partial_calendar_date(normalized)
    )


def _is_partial_calendar_date(text: str) -> bool:
    compact = "".join(normalize_text(text).split())
    separators = tuple(index for index, char in enumerate(compact) if not char.isdigit())
    if len(separators) != 1:
        return False
    separator_index = separators[0]
    first, second = compact[:separator_index], compact[separator_index + 1 :]
    if len(first) == 4 and 1 <= len(second) <= 2:
        year_text, month_text = first, second
    elif len(second) == 4 and 1 <= len(first) <= 2:
        year_text, month_text = second, first
    else:
        return False
    return 1900 <= int(year_text) <= 2199 and 1 <= int(month_text) <= 12


def has_processor_reference_alignment(reference: BBox, primary: BBox) -> bool:
    """Return whether two boxes provide comparable same-line reference geometry."""

    reference_height = bbox_height(reference)
    primary_height = bbox_height(primary)
    if reference_height <= 0.0 or primary_height <= 0.0:
        return False
    return (
        min(reference_height, primary_height) / max(reference_height, primary_height) >= 0.65
        and vertical_overlap(reference, primary) >= 0.75
        and abs(bbox_center_y(reference) - bbox_center_y(primary))
        <= min(reference_height, primary_height) * 0.25
    )


def matching_positioned_cell_text(
    ledger: EvidenceLedger,
    cell: Cell,
) -> str | None:
    """Return exact logical cell text only when positioned atoms independently back it."""

    atom_ids = ledger.atoms_for_cell(cell)
    if not atom_ids or any(
        ledger.atoms[atom_id].kind is EvidenceAtomKind.CELL_TEXT for atom_id in atom_ids
    ):
        return None
    rendered = normalize_text(ledger.render(atom_ids))
    return rendered if rendered == normalize_text(cell.text) else None


def _is_short_unsigned_description_component(text: str) -> bool:
    compact = "".join(normalize_text(text).split())
    return compact.isdigit() and len(compact) < 6


def is_standalone_primary_description(text: str) -> bool:
    """Return whether one isolated cell can serve as the row's primary description."""

    normalized = normalize_text(text)
    compact = "".join(normalized.split())
    return _is_short_unsigned_description_component(normalized) or (
        bool(compact)
        and any(char.isalpha() for char in normalized)
        and not _is_typed_non_description_text(normalized)
        and not _has_bounded_processor_identifier_shape(normalized)
    )


def _is_typed_non_description_text(text: str) -> bool:
    normalized = normalize_text(text)
    compact = "".join(normalized.split())
    unwrapped = compact.strip(_NUMERIC_EDGE_WRAPPERS)
    has_numeric_edge_wrapper = (
        unwrapped != compact
        and bool(unwrapped)
        and any(char.isdigit() for char in unwrapped)
        and all(char.isdigit() or char in _NUMERIC_BODY_SEPARATORS for char in unwrapped)
    )
    return (
        is_money_shaped(normalized)
        or is_currency_shaped(normalized)
        or "%" in normalized
        or isolated_date_token(normalized) is not None
        or is_installment_shaped(normalized)
        or has_numeric_edge_wrapper
    )


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


def _render_selected_description(
    ledger: EvidenceLedger,
    cell: Cell,
    selected_ids: frozenset[int],
) -> str:
    cell_atom_ids = ledger.atoms_for_cell(cell)
    logical_word_text = normalize_text(" ".join(word.text for word in cell.words))
    if (
        selected_ids == cell_atom_ids
        and bool(cell.words)
        and all(word.source == "digital" for word in cell.words)
        and normalize_text(cell.text) == logical_word_text
    ):
        return normalize_text(cell.text)
    return ledger.render(selected_ids)


def _render_description_atoms(
    ledger: EvidenceLedger, cells: Sequence[Cell], selected_ids: frozenset[int]
) -> str:
    if len({ledger.atoms[atom_id].kind for atom_id in selected_ids}) <= 1:
        return ledger.render(selected_ids)

    # Ledger rendering prefers glyphs over words over fallback cell text. In a
    # field spanning cells with different evidence kinds, render each cell so
    # that this preference cannot silently discard another cell's text.
    remaining = set(selected_ids)
    fragments: list[EvidenceCluster] = []
    for cell in cells:
        cell_ids = ledger.atoms_for_cell(cell) & remaining
        if not cell_ids:
            continue
        remaining.difference_update(cell_ids)
        fragments.append(
            EvidenceCluster(
                union_bbox(ledger.atoms[atom_id].bbox for atom_id in cell_ids),
                cell_ids,
                _render_selected_description(ledger, cell, cell_ids),
            )
        )
    texts: list[str] = []
    for line in _cluster_lines(fragments):
        direction = _dominant_direction(tuple(fragment.text for fragment in line))
        ordered = reversed(line) if direction == "rtl" else line
        texts.extend(fragment.text for fragment in ordered)
    return normalize_text(" ".join(texts))


def derive_merchant(*, description: str | None) -> tuple[str | None, tuple[str, ...]]:
    """Publish the complete extracted field without inferring a business identity."""

    if description is None:
        return None, ()
    merchant = normalize_text(description)
    return (merchant or None), (() if merchant else ("missing_merchant",))


def extract_description(
    rows: Sequence[Row],
    region: TableRegion,
    year_context: DiscoveredDateYearContext | None,
    ledger: EvidenceLedger,
    *,
    excluded_atom_ids: frozenset[int] = frozenset(),
) -> DescriptionExtraction:
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
                if horizontal_overlap(
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
        fallback_texts: list[str] = []
        # The column establishes the field boundary. Token shape or repetition
        # cannot distinguish a merchant's name from reference text within it.
        for cell in row_cells:
            selected_ids.update(ledger.atoms_for_cell(cell))

        date_columns = _role_columns(region, ColumnRole.DATE)
        if len(date_columns) == 1:
            date_cells = _cells_for_column(row, date_columns[0])
            if (
                len(date_cells) == 1
                and (
                    completion := adjacent_boundary_date_completion(
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

        splits = boundary_date_description_splits(
            row,
            region,
            year_context,
            ledger=ledger,
        )
        if len(splits) == 1:
            split_cell, _, residual_text = splits[0]
            split_ids = ledger.atoms_for_cell(split_cell)
            selected_ids.difference_update(split_ids)
            residual_ids = positioned_date_description_residual_atom_ids(
                ledger=ledger,
                cell=split_cell,
                residual=residual_text,
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
        selected_ids.difference_update(excluded_atom_ids)
        selected_frozen = frozenset(selected_ids)
        complete_source_cells = tuple(
            cell for cell in row_cells if ledger.atoms_for_cell(cell) == selected_frozen
        )
        rendered = (
            _render_selected_description(ledger, complete_source_cells[0], selected_frozen)
            if len(complete_source_cells) == 1
            else _render_description_atoms(ledger, row.cells, selected_frozen)
        )
        rendered = _merchant_punctuation(rendered) if rendered else ""
        row_text = normalize_text(" ".join((*fallback_texts, rendered)))
        if row_text:
            texts.append(_merchant_punctuation(row_text))
        if selected_ids:
            claims.append(EvidenceClaim(SemanticOwner.DESCRIPTION, frozenset(selected_ids)))
        previous_row = row

    if not texts:
        diagnostics.append("missing_description_cell")
        return DescriptionExtraction(None, tuple(claims), tuple(diagnostics))
    return DescriptionExtraction(
        normalize_text(" ".join(_merchant_punctuation(text) for text in texts)),
        tuple(claims),
        tuple(diagnostics),
    )


__all__ = [
    "extract_description",
    "has_processor_reference_alignment",
    "is_description_continuation",
    "is_numeric_processor_reference",
    "is_standalone_primary_description",
    "matching_positioned_cell_text",
]
