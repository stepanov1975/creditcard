"""Assemble transaction-owned continuation chains without interpreting their fields."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from ccparser.discovery import StatementGroupDiscovery
from ccparser.geometry import center_inside
from ccparser.layout.columns import cells_in_column, proven_region_billed_amount_column
from ccparser.layout.models import Row, TableRegion
from ccparser.layout.row_tags import RowTag, has_row_tag
from ccparser.money import is_money_shaped, parse_amount
from ccparser.normalization_description import is_description_continuation


class RowOwnershipKind(StrEnum):
    """Disposition of a primary source row before financial normalization."""

    TRANSACTION = "transaction"
    PRINTED_TOTAL = "printed_total"
    UNOWNED_DETAIL = "unowned_detail"


@dataclass(frozen=True, slots=True)
class OwnedContinuation:
    """An attached row and the diagnostic recording its ownership."""

    row: Row

    @property
    def diagnostic(self) -> str:
        if has_row_tag(self.row, RowTag.SUBORDINATE_DETAIL):
            return "merged_subordinate_detail_continuation"
        if has_row_tag(self.row, RowTag.AUXILIARY_CONTINUATION):
            return "merged_auxiliary_continuation"
        return "merged_description_continuation"


@dataclass(frozen=True, slots=True)
class RowOwnership:
    """A primary row and its complete ordered continuation chain."""

    row: Row
    kind: RowOwnershipKind
    continuations: tuple[OwnedContinuation, ...] = ()

    @property
    def diagnostic(self) -> str | None:
        if self.kind is RowOwnershipKind.PRINTED_TOTAL:
            return "printed_total_row"
        if self.kind is RowOwnershipKind.UNOWNED_DETAIL:
            return "unowned_leading_subordinate_detail_continuation"
        return None


@dataclass(frozen=True, slots=True)
class RegionOwnership:
    """Source region and its unconsumed primary rows in reading order."""

    region: TableRegion
    rows: tuple[RowOwnership, ...]


def _is_printed_total_row(row: Row, group: StatementGroupDiscovery) -> bool:
    evidence = (
        group.printed_total.label_evidence,
        group.printed_total.value_evidence,
    )
    return all(
        item.page_number == row.page_number
        and any(center_inside(item.bbox, cell.bbox) for cell in row.cells)
        for item in evidence
    )


def _compatible_cross_page_region_geometry(
    previous: TableRegion,
    current: TableRegion,
) -> bool:
    previous_columns = previous.table_schema.columns
    current_columns = current.table_schema.columns
    return (
        current.page_number == previous.page_number + 1
        and len(previous_columns) == len(current_columns)
        and all(
            previous_column.role is current_column.role
            and abs(previous_column.relative_x0 - current_column.relative_x0) <= 0.05
            and abs(previous_column.relative_x1 - current_column.relative_x1) <= 0.05
            for previous_column, current_column in zip(
                previous_columns,
                current_columns,
                strict=True,
            )
        )
    )


def _assemble_region(region: TableRegion, group: StatementGroupDiscovery) -> RegionOwnership:
    rows = tuple(sorted(region.rows, key=lambda row: (row.bbox[1], row.bbox[0])))
    assembled: list[RowOwnership] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        index += 1
        if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL):
            assembled.append(RowOwnership(row, RowOwnershipKind.UNOWNED_DETAIL))
            continue
        if _is_printed_total_row(row, group):
            assembled.append(RowOwnership(row, RowOwnershipKind.PRINTED_TOTAL))
            continue
        continuations: list[OwnedContinuation] = []
        previous = row
        while index < len(rows) and is_description_continuation(rows[index], previous, region):
            previous = rows[index]
            continuations.append(OwnedContinuation(previous))
            index += 1
        assembled.append(RowOwnership(row, RowOwnershipKind.TRANSACTION, tuple(continuations)))
    return RegionOwnership(region, tuple(assembled))


def _attach_cross_page_details(
    previous: RegionOwnership,
    current: RegionOwnership,
    group: StatementGroupDiscovery,
) -> tuple[RegionOwnership, RegionOwnership]:
    if not _compatible_cross_page_region_geometry(previous.region, current.region):
        return previous, current
    # Check the source rows, including tags on rows consumed by a same-page
    # chain. Assembly must not hide a non-prefix tag and enable a new handoff.
    source_rows = tuple(sorted(current.region.rows, key=lambda row: (row.bbox[1], row.bbox[0])))
    source_leading = tuple(
        row for row in source_rows if has_row_tag(row, RowTag.LEADING_SUBORDINATE_DETAIL)
    )
    if not source_leading or source_rows[: len(source_leading)] != source_leading:
        return previous, current
    leading = tuple(item for item in current.rows if item.kind is RowOwnershipKind.UNOWNED_DETAIL)
    if not leading or current.rows[: len(leading)] != leading:
        return previous, current
    following = current.rows[len(leading) :]
    if not following:
        return previous, current
    candidates = tuple(
        index
        for index, item in enumerate(previous.rows)
        if item.kind is not RowOwnershipKind.PRINTED_TOTAL
    )
    if not candidates:
        return previous, current
    owner_index = candidates[-1]
    owner = previous.rows[owner_index]
    previous_column = proven_region_billed_amount_column(previous.region)
    current_column = proven_region_billed_amount_column(current.region)
    if previous_column is None or current_column is None:
        return previous, current
    previous_cells = cells_in_column(owner.row.cells, previous_column)
    following_cells = cells_in_column(following[0].row.cells, current_column)
    billed = (
        parse_amount(previous_cells[0].text, currency_hint=group.printed_total.currency)
        if len(previous_cells) == 1
        else None
    )
    if (
        len(previous_cells) != 1
        or not is_money_shaped(previous_cells[0].text)
        or billed is None
        or billed.amount in {None, Decimal("0")}
        or len(following_cells) != 1
        or not is_money_shaped(following_cells[0].text)
    ):
        return previous, current
    attached = tuple(
        OwnedContinuation(
            item.row.model_copy(
                update={
                    "diagnostics": tuple(
                        "subordinate_detail_continuation"
                        if diagnostic == "leading_subordinate_detail_continuation"
                        else diagnostic
                        for diagnostic in item.row.diagnostics
                    ),
                }
            )
        )
        for item in leading
    )
    owned = replace(owner, continuations=(*owner.continuations, *attached))
    return (
        replace(
            previous, rows=(*previous.rows[:owner_index], owned, *previous.rows[owner_index + 1 :])
        ),
        replace(current, rows=following),
    )


def assemble_continuation_ownership(group: StatementGroupDiscovery) -> tuple[RegionOwnership, ...]:
    """Assign same-page chains and proven cross-page details once, without mutating evidence.

    Regions and primary rows retain reading order. Attached leading details appear
    only with their transaction owner; totals and unowned details remain explicit.
    Each continuation carries its publication diagnostic, including retagged copies
    of cross-page details. Financial acceptance remains the caller's responsibility.
    """

    regions = sorted(
        group.table_regions,
        key=lambda region: (
            region.page_number,
            region.bbox[1],
            region.bbox[0],
        ),
    )
    assembled = [_assemble_region(region, group) for region in regions]
    for index in range(1, len(assembled)):
        assembled[index - 1], assembled[index] = _attach_cross_page_details(
            assembled[index - 1],
            assembled[index],
            group,
        )
    return tuple(assembled)


__all__ = [
    "OwnedContinuation",
    "RegionOwnership",
    "RowOwnership",
    "RowOwnershipKind",
    "assemble_continuation_ownership",
]
