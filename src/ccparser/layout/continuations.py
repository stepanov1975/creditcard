"""Typed return contract for bounded continuation recognition."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum

from ccparser.layout.models import Row
from ccparser.layout.row_tags import RowTag


class ContinuationKind(StrEnum):
    """Closed vocabulary for scanner continuation behavior."""

    DESCRIPTION = "description"
    LEADING_DETAIL = "leading_detail"
    CARD_IDENTIFIER_BLOCK = "card_identifier_block"
    CARD_IDENTIFIER_TAIL = "card_identifier_tail"
    FOREIGN_CONVERSION_BLOCK = "foreign_conversion_block"
    HEBREW_NOTE = "hebrew_note"
    AUXILIARY_FRAGMENT = "auxiliary_fragment"
    MARKED_DETAIL = "marked_detail"


class DetailContinuationPolicy(StrEnum):
    """Whether applying a match preserves eligibility for another detail."""

    PRESERVE = "preserve"
    DISALLOW = "disallow"


_ROW_TAGS_BY_KIND: dict[ContinuationKind, frozenset[RowTag]] = {
    ContinuationKind.DESCRIPTION: frozenset({RowTag.DESCRIPTION_CONTINUATION}),
    ContinuationKind.LEADING_DETAIL: frozenset({RowTag.LEADING_SUBORDINATE_DETAIL}),
    ContinuationKind.CARD_IDENTIFIER_BLOCK: frozenset(
        {
            RowTag.SUBORDINATE_DETAIL,
            RowTag.CARD_IDENTIFIER_DETAIL,
        }
    ),
    ContinuationKind.CARD_IDENTIFIER_TAIL: frozenset({RowTag.SUBORDINATE_DETAIL}),
    ContinuationKind.FOREIGN_CONVERSION_BLOCK: frozenset(
        {
            RowTag.SUBORDINATE_DETAIL,
            RowTag.FOREIGN_CONVERSION_DETAIL,
        }
    ),
    ContinuationKind.HEBREW_NOTE: frozenset(
        {
            RowTag.SUBORDINATE_DETAIL,
            RowTag.HEBREW_NOTE_DETAIL,
        }
    ),
    ContinuationKind.AUXILIARY_FRAGMENT: frozenset({RowTag.AUXILIARY_CONTINUATION}),
    ContinuationKind.MARKED_DETAIL: frozenset({RowTag.SUBORDINATE_DETAIL}),
}


@dataclass(frozen=True, slots=True)
class ContinuationMatch:
    """A nonempty continuation match and its exact scanner effects."""

    rows: tuple[Row, ...]
    consumed_through: int
    kind: ContinuationKind
    detail_policy: DetailContinuationPolicy
    skipped_outside_rows: int = 0
    start_index: InitVar[int] = field(kw_only=True)

    def __post_init__(self, start_index: int) -> None:
        """Validate match bounds using the origin index without storing it."""

        if not self.rows:
            raise ValueError("continuation match rows must be nonempty")
        if self.skipped_outside_rows < 0:
            raise ValueError("skipped outside row count must be nonnegative")
        if self.consumed_through < start_index:
            raise ValueError("continuation match cannot consume before its start index")

    @property
    def row_tags(self) -> frozenset[RowTag]:
        """Return the exact compatibility tags implied by the continuation kind."""

        return _ROW_TAGS_BY_KIND[self.kind]


def single_row_match(
    row: Row,
    *,
    start_index: int,
    kind: ContinuationKind,
    detail_policy: DetailContinuationPolicy,
) -> ContinuationMatch:
    """Build a match that consumes exactly one source row."""

    return ContinuationMatch(
        rows=(row,),
        consumed_through=start_index,
        kind=kind,
        detail_policy=detail_policy,
        start_index=start_index,
    )


__all__ = [
    "ContinuationKind",
    "ContinuationMatch",
    "DetailContinuationPolicy",
    "single_row_match",
]
