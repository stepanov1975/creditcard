"""Typed structural row tags derived from exact legacy diagnostics."""

from __future__ import annotations

from enum import StrEnum

from ccparser.layout.models import Row


class RowTag(StrEnum):
    """Closed vocabulary for internal structural row state."""

    DESCRIPTION_CONTINUATION = "description_continuation"
    SUBORDINATE_DETAIL = "subordinate_detail_continuation"
    AUXILIARY_CONTINUATION = "subordinate_auxiliary_continuation"
    LEADING_SUBORDINATE_DETAIL = "leading_subordinate_detail_continuation"
    FOREIGN_CONVERSION_DETAIL = "foreign_conversion_detail_block"
    CARD_IDENTIFIER_DETAIL = "bounded_card_identifier_detail_block"
    HEBREW_NOTE_DETAIL = "bounded_hebrew_note_detail"


_LEGACY_DIAGNOSTIC_TAGS: dict[str, RowTag] = {
    "merchant_prefix_continuation": RowTag.DESCRIPTION_CONTINUATION,
    "subordinate_detail_continuation": RowTag.SUBORDINATE_DETAIL,
    "subordinate_auxiliary_continuation": RowTag.AUXILIARY_CONTINUATION,
    "leading_subordinate_detail_continuation": RowTag.LEADING_SUBORDINATE_DETAIL,
    "foreign_conversion_detail_block": RowTag.FOREIGN_CONVERSION_DETAIL,
    "bounded_card_identifier_detail_block": RowTag.CARD_IDENTIFIER_DETAIL,
    "bounded_hebrew_note_detail": RowTag.HEBREW_NOTE_DETAIL,
}
_STRUCTURAL_CONTINUATION_TAGS = frozenset(
    {
        RowTag.SUBORDINATE_DETAIL,
        RowTag.AUXILIARY_CONTINUATION,
        RowTag.LEADING_SUBORDINATE_DETAIL,
    }
)


def row_tags(row: Row) -> frozenset[RowTag]:
    """Return tags for exact recognized legacy diagnostics on ``row``."""

    return frozenset(
        tag
        for diagnostic in row.diagnostics
        if (tag := _LEGACY_DIAGNOSTIC_TAGS.get(diagnostic)) is not None
    )


def has_row_tag(row: Row, tag: RowTag) -> bool:
    """Return whether ``row`` has exactly the requested structural tag."""

    return tag in row_tags(row)


def is_structural_continuation(row: Row) -> bool:
    """Return whether ``row`` has one of the three legacy continuation tags."""

    return not row_tags(row).isdisjoint(_STRUCTURAL_CONTINUATION_TAGS)


__all__ = ["RowTag", "has_row_tag", "is_structural_continuation", "row_tags"]
