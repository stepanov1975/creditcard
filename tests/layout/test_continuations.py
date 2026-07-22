from __future__ import annotations

from dataclasses import fields

import pytest

from ccparser.layout.continuations import (
    ContinuationKind,
    ContinuationMatch,
    DetailContinuationPolicy,
    single_row_match,
)
from ccparser.layout.models import Row
from ccparser.layout.row_tags import RowTag


def _row() -> Row:
    return Row(
        page_number=1,
        bbox=(0.0, 10.0, 20.0, 20.0),
        cells=(),
        confidence=1.0,
    )


def test_continuation_kind_has_exact_closed_vocabulary() -> None:
    assert {kind.value for kind in ContinuationKind} == {
        "description",
        "leading_detail",
        "card_identifier_block",
        "card_identifier_tail",
        "foreign_conversion_block",
        "hebrew_note",
        "auxiliary_fragment",
        "marked_detail",
    }


def test_detail_continuation_policy_has_exact_closed_vocabulary() -> None:
    assert {policy.value for policy in DetailContinuationPolicy} == {
        "preserve",
        "disallow",
    }


def test_continuation_match_stores_only_the_common_return_contract() -> None:
    rows = (_row(), _row().model_copy(update={"bbox": (0.0, 21.0, 20.0, 31.0)}))

    match = ContinuationMatch(
        rows=rows,
        consumed_through=8,
        kind=ContinuationKind.FOREIGN_CONVERSION_BLOCK,
        row_tags=frozenset(
            {
                RowTag.SUBORDINATE_DETAIL,
                RowTag.FOREIGN_CONVERSION_DETAIL,
            }
        ),
        detail_policy=DetailContinuationPolicy.DISALLOW,
        skipped_outside_rows=2,
        start_index=5,
    )

    assert tuple(field.name for field in fields(match)) == (
        "rows",
        "consumed_through",
        "kind",
        "row_tags",
        "detail_policy",
        "skipped_outside_rows",
    )
    assert match.rows == rows
    assert match.consumed_through == 8
    assert match.kind is ContinuationKind.FOREIGN_CONVERSION_BLOCK
    assert match.row_tags == frozenset(
        {
            RowTag.SUBORDINATE_DETAIL,
            RowTag.FOREIGN_CONVERSION_DETAIL,
        }
    )
    assert match.detail_policy is DetailContinuationPolicy.DISALLOW
    assert match.skipped_outside_rows == 2


@pytest.mark.parametrize(
    ("rows", "consumed_through", "skipped_outside_rows", "start_index"),
    (
        ((), 4, 0, 4),
        ((_row(),), 4, -1, 4),
        ((_row(),), 3, 0, 4),
    ),
)
def test_continuation_match_rejects_invalid_construction(
    rows: tuple[Row, ...],
    consumed_through: int,
    skipped_outside_rows: int,
    start_index: int,
) -> None:
    with pytest.raises(ValueError):
        ContinuationMatch(
            rows=rows,
            consumed_through=consumed_through,
            kind=ContinuationKind.MARKED_DETAIL,
            row_tags=frozenset({RowTag.SUBORDINATE_DETAIL}),
            detail_policy=DetailContinuationPolicy.DISALLOW,
            skipped_outside_rows=skipped_outside_rows,
            start_index=start_index,
        )


def test_single_row_match_builds_description_continuation() -> None:
    row = _row()

    match = single_row_match(
        row,
        start_index=7,
        kind=ContinuationKind.DESCRIPTION,
        row_tags=frozenset({RowTag.DESCRIPTION_CONTINUATION}),
        detail_policy=DetailContinuationPolicy.PRESERVE,
    )

    assert match == ContinuationMatch(
        rows=(row,),
        consumed_through=7,
        kind=ContinuationKind.DESCRIPTION,
        row_tags=frozenset({RowTag.DESCRIPTION_CONTINUATION}),
        detail_policy=DetailContinuationPolicy.PRESERVE,
        start_index=7,
    )


@pytest.mark.parametrize(
    ("kind", "row_tags"),
    (
        (
            ContinuationKind.LEADING_DETAIL,
            frozenset({RowTag.LEADING_SUBORDINATE_DETAIL}),
        ),
        (
            ContinuationKind.CARD_IDENTIFIER_BLOCK,
            frozenset(
                {
                    RowTag.SUBORDINATE_DETAIL,
                    RowTag.CARD_IDENTIFIER_DETAIL,
                }
            ),
        ),
        (
            ContinuationKind.CARD_IDENTIFIER_TAIL,
            frozenset({RowTag.SUBORDINATE_DETAIL}),
        ),
        (
            ContinuationKind.FOREIGN_CONVERSION_BLOCK,
            frozenset(
                {
                    RowTag.SUBORDINATE_DETAIL,
                    RowTag.FOREIGN_CONVERSION_DETAIL,
                }
            ),
        ),
        (
            ContinuationKind.HEBREW_NOTE,
            frozenset(
                {
                    RowTag.SUBORDINATE_DETAIL,
                    RowTag.HEBREW_NOTE_DETAIL,
                }
            ),
        ),
        (
            ContinuationKind.AUXILIARY_FRAGMENT,
            frozenset({RowTag.AUXILIARY_CONTINUATION}),
        ),
        (
            ContinuationKind.MARKED_DETAIL,
            frozenset({RowTag.SUBORDINATE_DETAIL}),
        ),
    ),
)
def test_bounded_detail_match_carries_exact_tags_and_disallows_more_detail(
    kind: ContinuationKind,
    row_tags: frozenset[RowTag],
) -> None:
    match = single_row_match(
        _row(),
        start_index=3,
        kind=kind,
        row_tags=row_tags,
        detail_policy=DetailContinuationPolicy.DISALLOW,
    )

    assert match.row_tags == row_tags
    assert match.detail_policy is DetailContinuationPolicy.DISALLOW
