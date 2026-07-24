from __future__ import annotations

from ccparser.layout.continuations import (
    ContinuationKind,
    ContinuationMatch,
    DetailContinuationPolicy,
    single_row_match,
)
from ccparser.layout.models import Row
from ccparser.layout.regions import _RegionScanCounters, _RegionScanState


def _row(index: int) -> Row:
    y0 = float(index * 10)
    return Row(
        page_number=1,
        bbox=(0.0, y0, 10.0, y0 + 8.0),
        cells=(),
        confidence=1.0,
    )


def _state() -> _RegionScanState:
    return _RegionScanState(
        previous=_row(0),
        consumed_through=0,
        stop_index=20,
    )


def test_accept_description_preserves_eligibility_and_applies_skipped_rows() -> None:
    state = _state()
    description = _row(1)
    match = ContinuationMatch(
        rows=(description,),
        consumed_through=3,
        kind=ContinuationKind.DESCRIPTION,
        detail_policy=DetailContinuationPolicy.PRESERVE,
        skipped_outside_rows=2,
        start_index=1,
    )
    state.detail_continuation_allowed = True

    state.accept_description(match)

    assert state.accepted == [description]
    assert state.regular_rows == []
    assert state.previous is description
    assert state.consumed_through == 3
    assert state.detail_continuation_allowed
    assert state.counters == _RegionScanCounters(
        continuation_count=1,
        ignored_outside_band_count=2,
    )


def test_ignore_increments_only_the_named_counter_and_preserves_previous() -> None:
    state = _state()
    previous = state.previous

    state.ignore("outside_band")

    assert state.counters == _RegionScanCounters(ignored_outside_band_count=1)
    assert state.previous is previous
    assert state.accepted == []
    assert state.regular_rows == []


def test_accept_regular_updates_both_row_sets_and_allows_one_detail() -> None:
    state = _state()
    regular = _row(1)
    detail = _row(2)

    state.accept_regular(regular)

    assert state.accepted == [regular]
    assert state.regular_rows == [regular]
    assert state.previous is regular
    assert state.detail_continuation_allowed

    state.accept_continuation(
        single_row_match(
            detail,
            start_index=2,
            kind=ContinuationKind.MARKED_DETAIL,
            detail_policy=DetailContinuationPolicy.DISALLOW,
        )
    )

    assert state.accepted == [regular, detail]
    assert state.regular_rows == [regular]
    assert not state.detail_continuation_allowed


def test_accept_detail_consumes_through_match_and_uses_its_last_row_as_previous() -> None:
    state = _state()
    first_detail = _row(2)
    last_detail = _row(3)
    match = ContinuationMatch(
        rows=(first_detail, last_detail),
        consumed_through=4,
        kind=ContinuationKind.CARD_IDENTIFIER_BLOCK,
        detail_policy=DetailContinuationPolicy.DISALLOW,
        skipped_outside_rows=1,
        start_index=2,
    )
    state.detail_continuation_allowed = True

    state.accept_continuation(match)

    assert state.accepted == [first_detail, last_detail]
    assert state.regular_rows == []
    assert state.previous is last_detail
    assert state.consumed_through == 4
    assert not state.detail_continuation_allowed
    assert state.counters == _RegionScanCounters(
        detail_continuation_count=2,
        ignored_outside_band_count=1,
    )


def test_stop_records_only_the_first_reason_and_index() -> None:
    state = _state()

    state.stop("stopped_at_total", 7)
    state.stop("stopped_at_new_header", 9)

    assert state.stop_reason == "stopped_at_total"
    assert state.stop_index == 7


def test_counter_diagnostics_keep_fixed_order_across_transition_order() -> None:
    state = _state()
    state.ignore("spilled_currency", count=2)
    state.accept_description(
        single_row_match(
            _row(1),
            start_index=1,
            kind=ContinuationKind.DESCRIPTION,
            detail_policy=DetailContinuationPolicy.PRESERVE,
        )
    )
    state.ignore("overlaid_ocr")
    state.ignore("preamble", count=3, previous=_row(2))
    state.ignore("outside_band", count=4)
    state.accept_ambiguous(_row(3))
    state.accept_continuation(
        single_row_match(
            _row(4),
            start_index=4,
            kind=ContinuationKind.AUXILIARY_FRAGMENT,
            detail_policy=DetailContinuationPolicy.DISALLOW,
        )
    )
    state.accept_continuation(
        ContinuationMatch(
            rows=(_row(5), _row(6)),
            consumed_through=6,
            kind=ContinuationKind.CARD_IDENTIFIER_BLOCK,
            detail_policy=DetailContinuationPolicy.DISALLOW,
            start_index=5,
        )
    )

    assert state.counter_diagnostics() == (
        "continuation_rows:1",
        "detail_continuation_rows:2",
        "auxiliary_continuation_rows:1",
        "ignored_outside_band_rows:4",
        "ignored_preamble_rows:3",
        "ignored_overlaid_ocr_rows:1",
        "ignored_spilled_currency_fragment_rows:2",
        "ambiguous_leading_rows:1",
    )
