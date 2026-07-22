from __future__ import annotations

import pytest

from ccparser.layout.models import Row
from ccparser.layout.row_tags import (
    RowTag,
    has_row_tag,
    is_structural_continuation,
    row_tags,
)


def _row(*diagnostics: str) -> Row:
    return Row(
        page_number=1,
        bbox=(0.0, 0.0, 10.0, 10.0),
        cells=(),
        confidence=1.0,
        diagnostics=diagnostics,
    )


def test_row_tag_has_exact_closed_vocabulary() -> None:
    assert {tag.value for tag in RowTag} == {
        "description_continuation",
        "subordinate_detail_continuation",
        "subordinate_auxiliary_continuation",
        "leading_subordinate_detail_continuation",
        "foreign_conversion_detail_block",
        "bounded_card_identifier_detail_block",
        "bounded_hebrew_note_detail",
    }


def test_row_tags_maps_only_exact_legacy_structural_diagnostics() -> None:
    row = _row(
        "subordinate_detail_continuation",
        "subordinate_auxiliary_continuation",
        "leading_subordinate_detail_continuation",
        "foreign_conversion_detail_block",
        "bounded_card_identifier_detail_block",
        "bounded_hebrew_note_detail",
    )

    assert row_tags(row) == frozenset(
        {
            RowTag.SUBORDINATE_DETAIL,
            RowTag.AUXILIARY_CONTINUATION,
            RowTag.LEADING_SUBORDINATE_DETAIL,
            RowTag.FOREIGN_CONVERSION_DETAIL,
            RowTag.CARD_IDENTIFIER_DETAIL,
            RowTag.HEBREW_NOTE_DETAIL,
        }
    )


def test_row_tags_deduplicates_repeated_diagnostics() -> None:
    row = _row(
        "subordinate_detail_continuation",
        "subordinate_detail_continuation",
    )

    assert row_tags(row) == frozenset({RowTag.SUBORDINATE_DETAIL})


def test_row_tags_ignore_unrelated_continuation_diagnostics() -> None:
    row = _row(
        "description_continuation",
        "continuation",
        "not_a_continuation",
        "ambiguous_description_continuation",
        "continuation_rows:2",
        "unrelated_diagnostic",
    )

    assert row_tags(row) == frozenset()


def test_has_row_tag_uses_exact_legacy_mapping() -> None:
    row = _row("subordinate_detail_continuation", "not_a_continuation")

    assert has_row_tag(row, RowTag.SUBORDINATE_DETAIL)
    assert not has_row_tag(row, RowTag.DESCRIPTION_CONTINUATION)


@pytest.mark.parametrize(
    "diagnostic",
    (
        "subordinate_detail_continuation",
        "subordinate_auxiliary_continuation",
        "leading_subordinate_detail_continuation",
    ),
)
def test_is_structural_continuation_accepts_only_legacy_continuation_tags(
    diagnostic: str,
) -> None:
    assert is_structural_continuation(_row(diagnostic))


@pytest.mark.parametrize(
    "diagnostic",
    (
        "description_continuation",
        "foreign_conversion_detail_block",
        "bounded_card_identifier_detail_block",
        "bounded_hebrew_note_detail",
        "not_a_continuation",
    ),
)
def test_is_structural_continuation_rejects_other_row_tags_and_diagnostics(
    diagnostic: str,
) -> None:
    assert not is_structural_continuation(_row(diagnostic))
