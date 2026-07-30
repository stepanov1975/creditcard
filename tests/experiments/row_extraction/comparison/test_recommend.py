from dataclasses import replace
from decimal import Decimal

import pytest

from experiments.row_extraction.comparison.cascade import CascadePolicy, CascadeRule
from experiments.row_extraction.comparison.compare import (
    ComparisonReport,
    ExperimentResult,
    ResultBasis,
    build_comparison,
)
from experiments.row_extraction.comparison.recommend import (
    MeasuredCandidateSummary,
    MeasuredRecommendationReport,
    MeasurementLimitationCode,
    RecommendationKind,
    RecommendationReasonCode,
    StopReasonCode,
    recommend,
)
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FieldRole,
    LaneDisposition,
    RowType,
)


def _identity(artifact_type: str, marker: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=marker * 64,
        version=(
            "canonical-jsonl-v1" if artifact_type == "frozen-row-sequence" else "synthetic-v1"
        ),
        byte_size=100,
    )


def _result(
    experiment_id: str,
    *,
    basis: ResultBasis,
    disposition: LaneDisposition | None,
    exact_rows: int = 0,
    merchant_exact_rows: int = 0,
    omissions: int = 0,
    hallucinations: int = 0,
    deterministic: bool = True,
    stop_reason: str | None = None,
    resource_basis: str | None = "end-to-end-method",
    row_count: int = 10,
) -> ExperimentResult:
    stopped = disposition is LaneDisposition.VALIDATION_STOPPED
    return ExperimentResult(
        experiment_id=experiment_id,
        result_basis=basis,
        disposition=disposition,
        stop_reason=stop_reason,
        row_count=row_count,
        exact_rows=exact_rows,
        merchant_exact_rows=merchant_exact_rows,
        omissions=omissions,
        hallucinations=hallucinations,
        accepted_rows=exact_rows,
        p95_ns=None if stopped else 100,
        peak_rss_bytes=None if stopped else 1024,
        model_bytes=None if stopped else 0,
        dependency_bytes=None if stopped else 2048,
        deterministic=deterministic,
        resource_basis=None if stopped else resource_basis,
    )


def _comparison(
    *,
    profile_exact: int = 3,
    profile_merchant: int = 2,
    profile_hallucinations: int = 0,
    profile_deterministic: bool = True,
    profile_row_count: int = 10,
    ocr_stop_reason: str = StopReasonCode.OCR_STAGE_VALIDATION_FAILED,
) -> ComparisonReport:
    return build_comparison(
        (
            _result(
                "accepted-baseline",
                basis=ResultBasis.LOCKED_TEST,
                disposition=None,
                exact_rows=3,
                merchant_exact_rows=2,
                resource_basis="materialized-adapter",
            ),
            _result(
                "conditional-page-ocr",
                basis=ResultBasis.LOCKED_TEST,
                disposition=None,
            ),
            _result(
                "forced-page-ocr",
                basis=ResultBasis.LOCKED_TEST,
                disposition=None,
            ),
            _result(
                "row-ocr",
                basis=ResultBasis.VALIDATION_STOP,
                disposition=LaneDisposition.VALIDATION_STOPPED,
                stop_reason=ocr_stop_reason,
            ),
            _result(
                "row-profiles",
                basis=ResultBasis.LOCKED_TEST,
                disposition=LaneDisposition.FROZEN_ELIGIBLE,
                exact_rows=profile_exact,
                merchant_exact_rows=profile_merchant,
                hallucinations=profile_hallucinations,
                deterministic=profile_deterministic,
                row_count=profile_row_count,
            ),
            _result(
                "row-text",
                basis=ResultBasis.VALIDATION_STOP,
                disposition=LaneDisposition.VALIDATION_STOPPED,
                stop_reason=StopReasonCode.NO_TEXT_CANDIDATE_MET_VALIDATION_GATE,
            ),
            _result(
                "row-vision",
                basis=ResultBasis.VALIDATION_STOP,
                disposition=LaneDisposition.VALIDATION_STOPPED,
                stop_reason=StopReasonCode.NO_PIXEL_GAIN,
            ),
        )
    )


def _candidate(
    *,
    candidate_id: str = "row-profiles",
    paired_effect: Decimal = Decimal("0"),
    paired_low: Decimal = Decimal("0"),
    required_field_regressions: tuple[FieldRole, ...] = (),
    accepted_unsupported_fields: int = 0,
    false_accept_risk_delta: Decimal = Decimal("0"),
    protected_row_type_regressions: tuple[RowType, ...] = (),
) -> MeasuredCandidateSummary:
    return MeasuredCandidateSummary(
        candidate_id=candidate_id,
        measurement_identity=_identity("row-extraction-locked-measurement", "b"),
        row_sequence_identity=_identity("frozen-row-sequence", "d"),
        paired_row_exact_effect=paired_effect,
        paired_row_exact_low=paired_low,
        paired_row_exact_high=paired_effect,
        required_field_regressions=required_field_regressions,
        accepted_unsupported_fields=accepted_unsupported_fields,
        false_accept_risk_delta=false_accept_risk_delta,
        comparable_coverage=True,
        protected_row_type_regressions=protected_row_type_regressions,
        abstained_rows=5,
        limitations=(MeasurementLimitationCode.OCR_ERROR_UNAVAILABLE,),
    )


def _report(
    comparison: ComparisonReport,
    *candidates: MeasuredCandidateSummary,
    cascade_policy: CascadePolicy | None = None,
    cascade_result: ExperimentResult | None = None,
) -> MeasuredRecommendationReport:
    return MeasuredRecommendationReport(
        comparison=comparison,
        comparison_identity=_identity("row-extraction-comparison-report", "a"),
        locked_row_sequence_identity=_identity("frozen-row-sequence", "d"),
        candidates=candidates,
        cascade_policy=cascade_policy,
        cascade_policy_identity=(
            _identity("row-extraction-cascade-policy", "c") if cascade_policy is not None else None
        ),
        cascade_result=cascade_result,
    )


def test_no_production_change_without_eligible_positive_locked_gain() -> None:
    result = recommend(_report(_comparison(), _candidate()))

    assert result.kind is RecommendationKind.NO_PRODUCTION_CHANGE
    assert result.selected_ids == ()
    assert result.reasons == (RecommendationReasonCode.NO_ELIGIBLE_POSITIVE_LOCKED_GAIN,)
    assert {limitation.code for limitation in result.limitations} >= {
        StopReasonCode.OCR_STAGE_VALIDATION_FAILED,
        StopReasonCode.NO_TEXT_CANDIDATE_MET_VALIDATION_GATE,
        StopReasonCode.NO_PIXEL_GAIN,
    }


def test_stopped_lane_cannot_be_bound_as_recommendation_candidate() -> None:
    stopped = _candidate(
        candidate_id="row-ocr",
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )

    with pytest.raises(ValueError, match="eligible locked comparison result"):
        _report(_comparison(), stopped)


def test_cascade_cannot_bind_stopped_policy_component() -> None:
    cascade = _candidate(
        candidate_id="row-cascade",
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )
    policy = CascadePolicy(
        version="cascade-v1",
        rules=(CascadeRule("row-ocr", Decimal("0.95")),),
    )
    cascade_result = _result(
        "row-cascade",
        basis=ResultBasis.LOCKED_TEST,
        disposition=None,
        exact_rows=5,
        merchant_exact_rows=4,
    )

    with pytest.raises(ValueError, match="stopped lane cannot enter cascade recommendation"):
        _report(
            _comparison(),
            cascade,
            cascade_policy=policy,
            cascade_result=cascade_result,
        )


def test_no_production_change_on_required_field_regression() -> None:
    unsafe = _candidate(
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
        required_field_regressions=(FieldRole.BILLED_AMOUNT,),
    )

    result = recommend(_report(_comparison(profile_exact=5), unsafe))

    assert result.kind is RecommendationKind.NO_PRODUCTION_CHANGE
    assert RecommendationReasonCode.REQUIRED_FIELD_REGRESSION in result.reasons


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        (
            {"accepted_unsupported_fields": 1},
            RecommendationReasonCode.UNSUPPORTED_EVIDENCE,
        ),
        (
            {"false_accept_risk_delta": Decimal("0.01")},
            RecommendationReasonCode.HIGHER_FALSE_ACCEPT_RISK,
        ),
        (
            {"protected_row_type_regressions": (RowType.PRIMARY_TRANSACTION,)},
            RecommendationReasonCode.PROTECTED_SLICE_REGRESSION,
        ),
    ),
)
def test_no_production_change_on_measured_safety_failure(
    changes: dict[str, object],
    reason: RecommendationReasonCode,
) -> None:
    measured = _candidate(
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )

    result = recommend(_report(_comparison(profile_exact=5), replace(measured, **changes)))

    assert result.kind is RecommendationKind.NO_PRODUCTION_CHANGE
    assert reason in result.reasons


def test_unique_safe_winner_returns_structured_measured_evidence() -> None:
    measured = _candidate(
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )
    report = _report(
        _comparison(profile_exact=5, profile_merchant=4),
        measured,
    )

    result = recommend(report)

    assert result.kind is RecommendationKind.DESIGN_INTEGRATION
    assert result.selected_ids == ("row-profiles",)
    assert result.comparison_identity == report.comparison_identity
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.candidate_id == "row-profiles"
    assert evidence.row_exact_gain == 2
    assert evidence.merchant_exact_gain == 2
    assert evidence.paired_row_exact_low == Decimal("0.02")
    assert evidence.omissions == 0
    assert evidence.hallucinations == 0
    assert evidence.abstained_rows == 5
    assert evidence.p95_ns == 100
    assert evidence.peak_rss_bytes == 1024
    assert evidence.model_bytes == 0


def test_privacy_unsafe_stop_reason_is_rejected_before_output() -> None:
    comparison = _comparison(ocr_stop_reason="merchant value leaked")

    with pytest.raises(ValueError, match="closed validation stop reason"):
        _report(comparison, _candidate())


def test_privacy_unsafe_free_text_limitation_is_rejected() -> None:
    with pytest.raises(ValueError, match="closed measurement limitation"):
        replace(_candidate(), limitations=("merchant text leaked",))


@pytest.mark.parametrize(
    ("comparison", "reason"),
    (
        (
            _comparison(profile_exact=5, profile_hallucinations=1),
            RecommendationReasonCode.ACCEPTED_FIELD_HALLUCINATION,
        ),
        (
            _comparison(profile_exact=5, profile_deterministic=False),
            RecommendationReasonCode.NONDETERMINISM,
        ),
    ),
)
def test_result_bound_safety_failure_blocks_recommendation(
    comparison: ComparisonReport,
    reason: RecommendationReasonCode,
) -> None:
    measured = _candidate(
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )

    result = recommend(_report(comparison, measured))

    assert result.kind is RecommendationKind.NO_PRODUCTION_CHANGE
    assert reason in result.reasons


def test_lane_locked_row_count_must_match_accepted_baseline() -> None:
    with pytest.raises(ValueError, match="common locked row count"):
        _report(_comparison(profile_row_count=11), _candidate())


def test_cascade_locked_row_count_must_match_accepted_baseline() -> None:
    policy = CascadePolicy(
        version="cascade-v1",
        rules=(CascadeRule("row-profiles", Decimal("0.95")),),
    )
    cascade = _candidate(candidate_id="row-cascade")
    cascade_result = _result(
        "row-cascade",
        basis=ResultBasis.LOCKED_TEST,
        disposition=None,
        exact_rows=5,
        merchant_exact_rows=4,
        row_count=11,
    )

    with pytest.raises(ValueError, match="common locked row count"):
        _report(
            _comparison(),
            cascade,
            cascade_policy=policy,
            cascade_result=cascade_result,
        )


def test_empty_cascade_policy_cannot_claim_incremental_locked_gain() -> None:
    empty_policy = CascadePolicy(version="cascade-v1", rules=())
    cascade = _candidate(
        candidate_id="row-cascade",
        paired_effect=Decimal("0.10"),
        paired_low=Decimal("0.02"),
    )
    cascade_result = _result(
        "row-cascade",
        basis=ResultBasis.LOCKED_TEST,
        disposition=None,
        exact_rows=5,
        merchant_exact_rows=4,
    )

    with pytest.raises(ValueError, match="empty cascade cannot claim incremental gain"):
        _report(
            _comparison(),
            cascade,
            cascade_policy=empty_policy,
            cascade_result=cascade_result,
        )


def test_candidate_must_bind_common_locked_row_sequence_identity() -> None:
    mismatched = replace(
        _candidate(),
        row_sequence_identity=_identity("frozen-row-sequence", "e"),
    )

    with pytest.raises(ValueError, match="common locked row-sequence identity"):
        _report(_comparison(), mismatched)


def test_recommendation_accepts_the_canonical_runner_row_sequence_identity() -> None:
    identity = _identity("frozen-row-sequence", "d")
    candidate = replace(_candidate(), row_sequence_identity=identity)

    report = MeasuredRecommendationReport(
        comparison=_comparison(),
        comparison_identity=_identity("row-extraction-comparison-report", "a"),
        locked_row_sequence_identity=identity,
        candidates=(candidate,),
    )

    assert report.locked_row_sequence_identity == identity


def test_recommendation_rejects_wrong_runner_row_sequence_version() -> None:
    identity = _identity("frozen-row-sequence", "d").model_copy(update={"version": "wrong-version"})

    with pytest.raises(ValueError, match="locked row-sequence identity"):
        replace(_candidate(), row_sequence_identity=identity)
