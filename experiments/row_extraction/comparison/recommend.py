"""Closed evidence gate for row-extraction production recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from experiments.row_extraction.comparison.cascade import CascadePolicy
from experiments.row_extraction.comparison.compare import (
    ComparisonReport,
    ExperimentResult,
    ResultBasis,
    build_comparison,
)
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FieldRole,
    LaneDisposition,
    RowType,
)

_EXPERIMENT_IDS = frozenset({"row-ocr", "row-profiles", "row-text", "row-vision"})
_COMPARISON_IDENTITY_TYPE = "row-extraction-comparison-report"
_MEASUREMENT_IDENTITY_TYPE = "row-extraction-locked-measurement"
_ROW_SEQUENCE_IDENTITY_TYPE = "row-extraction-locked-row-sequence"
_POLICY_IDENTITY_TYPE = "row-extraction-cascade-policy"
_CASCADE_ID = "row-cascade"


class StopReasonCode(StrEnum):
    """The four predeclared validation-stop reasons."""

    OCR_STAGE_VALIDATION_FAILED = "ocr_stage_validation_failed"
    NO_PROFILE_CANDIDATE_MET_VALIDATION_GATE = "no_profile_candidate_met_validation_gate"
    NO_TEXT_CANDIDATE_MET_VALIDATION_GATE = "no_text_candidate_met_validation_gate"
    NO_PIXEL_GAIN = "no_pixel_gain"


class MeasurementLimitationCode(StrEnum):
    """Privacy-safe limitations that may accompany aggregate measurements."""

    OCR_ERROR_UNAVAILABLE = "ocr_error_unavailable"
    RESOURCE_BASIS_NOT_COMPARABLE = "resource_basis_not_comparable"
    LOW_PROTECTED_SLICE_SUPPORT = "low_protected_slice_support"


class RecommendationReasonCode(StrEnum):
    """Closed reasons for the recommendation decision."""

    NO_ELIGIBLE_POSITIVE_LOCKED_GAIN = "no_eligible_positive_locked_gain"
    REQUIRED_FIELD_REGRESSION = "required_field_regression"
    UNSUPPORTED_EVIDENCE = "unsupported_evidence"
    ACCEPTED_FIELD_HALLUCINATION = "accepted_field_hallucination"
    HIGHER_FALSE_ACCEPT_RISK = "higher_false_accept_risk"
    NONDETERMINISM = "nondeterminism"
    PROTECTED_SLICE_REGRESSION = "protected_slice_regression"
    NO_UNIQUE_PARETO_WINNER = "no_unique_pareto_winner"
    POSITIVE_LOCKED_PAIRED_EFFECT = "positive_locked_paired_effect"
    PARETO_WINNER = "pareto_winner"
    SAFETY_GATES_PASSED = "safety_gates_passed"


class RecommendationKind(StrEnum):
    """The only two outcomes authorized by the experiment program."""

    NO_PRODUCTION_CHANGE = "no_production_change"
    DESIGN_INTEGRATION = "design_integration"


def _stop_reason_code(value: str | None) -> StopReasonCode:
    if value is None:
        raise ValueError("comparison has no closed validation stop reason")
    try:
        return StopReasonCode(value)
    except ValueError:
        raise ValueError("comparison has no closed validation stop reason") from None


@dataclass(frozen=True)
class MeasuredCandidateSummary:
    """Privacy-safe candidate measurements not already present in the comparison."""

    candidate_id: str
    measurement_identity: ArtifactIdentity
    row_sequence_identity: ArtifactIdentity
    paired_row_exact_effect: Decimal
    paired_row_exact_low: Decimal
    paired_row_exact_high: Decimal
    required_field_regressions: tuple[FieldRole, ...]
    accepted_unsupported_fields: int
    false_accept_risk_delta: Decimal
    comparable_coverage: bool
    protected_row_type_regressions: tuple[RowType, ...]
    abstained_rows: int
    limitations: tuple[MeasurementLimitationCode, ...]

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate identity is required")
        if self.measurement_identity.artifact_type != _MEASUREMENT_IDENTITY_TYPE:
            raise ValueError("candidate requires a locked measurement identity")
        if self.row_sequence_identity.artifact_type != _ROW_SEQUENCE_IDENTITY_TYPE:
            raise ValueError("candidate requires a locked row-sequence identity")
        decimals = (
            self.paired_row_exact_effect,
            self.paired_row_exact_low,
            self.paired_row_exact_high,
            self.false_accept_risk_delta,
        )
        if any(not value.is_finite() for value in decimals):
            raise ValueError("candidate measurements must be finite")
        if self.paired_row_exact_low > self.paired_row_exact_effect:
            raise ValueError("paired interval does not contain its effect")
        if self.paired_row_exact_effect > self.paired_row_exact_high:
            raise ValueError("paired interval does not contain its effect")
        if self.accepted_unsupported_fields < 0 or self.abstained_rows < 0:
            raise ValueError("candidate safety counts must be nonnegative")
        if len(self.required_field_regressions) != len(set(self.required_field_regressions)):
            raise ValueError("required-field regressions must be unique")
        if len(self.protected_row_type_regressions) != len(
            set(self.protected_row_type_regressions)
        ):
            raise ValueError("protected row-type regressions must be unique")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("measurement limitation codes must be unique")
        if any(not isinstance(role, FieldRole) for role in self.required_field_regressions):
            raise ValueError("required-field regressions require closed roles")
        if any(
            not isinstance(row_type, RowType) for row_type in self.protected_row_type_regressions
        ):
            raise ValueError("protected regressions require closed row types")
        if any(not isinstance(code, MeasurementLimitationCode) for code in self.limitations):
            raise ValueError("candidate requires closed measurement limitation codes")


@dataclass(frozen=True)
class MeasuredRecommendationReport:
    """Locked comparison plus measurements bound to its exact candidate identities."""

    comparison: ComparisonReport
    comparison_identity: ArtifactIdentity
    locked_row_sequence_identity: ArtifactIdentity
    candidates: tuple[MeasuredCandidateSummary, ...]
    cascade_policy: CascadePolicy | None = None
    cascade_policy_identity: ArtifactIdentity | None = None
    cascade_result: ExperimentResult | None = None

    def __post_init__(self) -> None:
        if self.comparison_identity.artifact_type != _COMPARISON_IDENTITY_TYPE:
            raise ValueError("recommendation requires a locked comparison identity")
        if self.locked_row_sequence_identity.artifact_type != _ROW_SEQUENCE_IDENTITY_TYPE:
            raise ValueError("recommendation requires a locked row-sequence identity")
        rebuilt = build_comparison(tuple(self.comparison.results))
        if rebuilt != self.comparison:
            raise ValueError("recommendation comparison is not canonical")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("recommendation candidate identities must be unique")
        if any(
            candidate.row_sequence_identity != self.locked_row_sequence_identity
            for candidate in self.candidates
        ):
            raise ValueError("candidate lacks the common locked row-sequence identity")

        results = {result.experiment_id: result for result in self.comparison.results}
        baseline_row_count = results["accepted-baseline"].row_count
        if any(
            result.row_count != baseline_row_count
            for result in self.comparison.results
            if result.result_basis is ResultBasis.LOCKED_TEST
        ):
            raise ValueError("comparison results lack a common locked row count")
        for result in self.comparison.results:
            if result.disposition is LaneDisposition.VALIDATION_STOPPED:
                _stop_reason_code(result.stop_reason)

        for candidate_id in candidate_ids:
            if candidate_id == _CASCADE_ID:
                continue
            candidate_result = results.get(candidate_id)
            if (
                candidate_id not in _EXPERIMENT_IDS
                or candidate_result is None
                or candidate_result.disposition is not LaneDisposition.FROZEN_ELIGIBLE
                or candidate_result.result_basis is not ResultBasis.LOCKED_TEST
            ):
                raise ValueError("candidate has no eligible locked comparison result")

        has_cascade = _CASCADE_ID in candidate_ids
        cascade_values = (
            self.cascade_policy,
            self.cascade_policy_identity,
            self.cascade_result,
        )
        if has_cascade and any(value is None for value in cascade_values):
            raise ValueError("cascade candidate requires frozen policy and locked result")
        if not has_cascade and any(value is not None for value in cascade_values):
            raise ValueError("unbound cascade inputs are forbidden")
        if not has_cascade:
            return

        assert self.cascade_policy is not None
        assert self.cascade_policy_identity is not None
        assert self.cascade_result is not None
        if self.cascade_policy_identity.artifact_type != _POLICY_IDENTITY_TYPE:
            raise ValueError("cascade candidate requires a frozen policy identity")
        validated_cascade = ExperimentResult.model_validate(
            self.cascade_result.model_dump(mode="python")
        )
        if (
            validated_cascade.experiment_id != _CASCADE_ID
            or validated_cascade.result_basis is not ResultBasis.LOCKED_TEST
            or validated_cascade.resource_basis != "end-to-end-method"
        ):
            raise ValueError("cascade candidate requires an end-to-end locked result")
        if validated_cascade.row_count != baseline_row_count:
            raise ValueError("cascade result lacks the common locked row count")
        baseline = results["accepted-baseline"]
        if not self.cascade_policy.rules and (
            validated_cascade.exact_rows > baseline.exact_rows
            or validated_cascade.merchant_exact_rows > baseline.merchant_exact_rows
        ):
            raise ValueError("empty cascade cannot claim incremental gain")
        component_ids = {
            arm_id
            for rule in self.cascade_policy.rules
            for arm_id in (rule.arm_id, *rule.requires_agreement)
        }
        for component_id in component_ids:
            component = results.get(component_id)
            if (
                component is not None
                and component.disposition is LaneDisposition.VALIDATION_STOPPED
            ):
                raise ValueError("stopped lane cannot enter cascade recommendation")
            if (
                component_id not in _EXPERIMENT_IDS
                or component is None
                or component.disposition is not LaneDisposition.FROZEN_ELIGIBLE
                or component.result_basis is not ResultBasis.LOCKED_TEST
            ):
                raise ValueError("cascade component has no eligible locked result")
        if self.candidates_by_id[_CASCADE_ID].abstained_rows > validated_cascade.row_count:
            raise ValueError("candidate abstention count exceeds locked row count")

    @property
    def candidates_by_id(self) -> dict[str, MeasuredCandidateSummary]:
        return {candidate.candidate_id: candidate for candidate in self.candidates}


@dataclass(frozen=True)
class RecommendationLimitation:
    """One component-scoped limitation with a closed code."""

    component_id: str
    code: StopReasonCode | MeasurementLimitationCode


@dataclass(frozen=True)
class RecommendationEvidence:
    """Structured privacy-safe evidence retained with the decision."""

    candidate_id: str
    measurement_identity: ArtifactIdentity
    row_sequence_identity: ArtifactIdentity
    paired_row_exact_effect: Decimal
    paired_row_exact_low: Decimal
    paired_row_exact_high: Decimal
    row_exact_gain: int
    merchant_exact_gain: int
    omissions: int
    hallucinations: int
    accepted_rows: int
    abstained_rows: int
    accepted_unsupported_fields: int
    required_field_regressions: tuple[FieldRole, ...]
    false_accept_risk_delta: Decimal
    protected_row_type_regressions: tuple[RowType, ...]
    p95_ns: int
    peak_rss_bytes: int
    model_bytes: int
    dependency_bytes: int
    deterministic: bool


@dataclass(frozen=True)
class Recommendation:
    """A measured no-change decision or authority to design an integration."""

    comparison_identity: ArtifactIdentity
    locked_row_sequence_identity: ArtifactIdentity
    kind: RecommendationKind
    selected_ids: tuple[str, ...]
    reasons: tuple[RecommendationReasonCode, ...]
    limitations: tuple[RecommendationLimitation, ...]
    evidence: tuple[RecommendationEvidence, ...]


def _result_by_id(report: MeasuredRecommendationReport) -> dict[str, ExperimentResult]:
    results = {result.experiment_id: result for result in report.comparison.results}
    if report.cascade_result is not None:
        results[_CASCADE_ID] = report.cascade_result
    return results


def _resource_pareto_ids(results: dict[str, ExperimentResult]) -> frozenset[str]:
    candidates = tuple(
        result
        for result in results.values()
        if result.result_basis is ResultBasis.LOCKED_TEST
        and result.resource_basis == "end-to-end-method"
        and result.deterministic
    )

    def axes(result: ExperimentResult) -> tuple[int, ...]:
        return (
            result.exact_rows,
            result.merchant_exact_rows,
            -result.omissions,
            -result.hallucinations,
            -(result.p95_ns or 0),
            -(result.peak_rss_bytes or 0),
            -(result.model_bytes or 0),
        )

    def dominates(first: ExperimentResult, second: ExperimentResult) -> bool:
        first_axes = axes(first)
        second_axes = axes(second)
        return all(
            left >= right for left, right in zip(first_axes, second_axes, strict=True)
        ) and any(left > right for left, right in zip(first_axes, second_axes, strict=True))

    return frozenset(
        candidate.experiment_id
        for candidate in candidates
        if not any(
            other.experiment_id != candidate.experiment_id and dominates(other, candidate)
            for other in candidates
        )
    )


def _limitations(report: MeasuredRecommendationReport) -> tuple[RecommendationLimitation, ...]:
    stopped = tuple(
        RecommendationLimitation(
            component_id=result.experiment_id,
            code=_stop_reason_code(result.stop_reason),
        )
        for result in report.comparison.results
        if result.disposition is LaneDisposition.VALIDATION_STOPPED
    )
    measured = tuple(
        RecommendationLimitation(component_id=candidate.candidate_id, code=code)
        for candidate in report.candidates
        for code in candidate.limitations
    )
    return (*stopped, *measured)


def _evidence(
    summary: MeasuredCandidateSummary,
    result: ExperimentResult,
    baseline: ExperimentResult,
) -> RecommendationEvidence:
    resources = (
        result.p95_ns,
        result.peak_rss_bytes,
        result.model_bytes,
        result.dependency_bytes,
    )
    if any(value is None for value in resources):
        raise ValueError("recommendation candidate lacks locked resources")
    p95_ns, peak_rss_bytes, model_bytes, dependency_bytes = resources
    assert p95_ns is not None
    assert peak_rss_bytes is not None
    assert model_bytes is not None
    assert dependency_bytes is not None
    if summary.abstained_rows > result.row_count:
        raise ValueError("candidate abstention count exceeds locked row count")
    return RecommendationEvidence(
        candidate_id=summary.candidate_id,
        measurement_identity=summary.measurement_identity,
        row_sequence_identity=summary.row_sequence_identity,
        paired_row_exact_effect=summary.paired_row_exact_effect,
        paired_row_exact_low=summary.paired_row_exact_low,
        paired_row_exact_high=summary.paired_row_exact_high,
        row_exact_gain=result.exact_rows - baseline.exact_rows,
        merchant_exact_gain=result.merchant_exact_rows - baseline.merchant_exact_rows,
        omissions=result.omissions,
        hallucinations=result.hallucinations,
        accepted_rows=result.accepted_rows,
        abstained_rows=summary.abstained_rows,
        accepted_unsupported_fields=summary.accepted_unsupported_fields,
        required_field_regressions=summary.required_field_regressions,
        false_accept_risk_delta=summary.false_accept_risk_delta,
        protected_row_type_regressions=summary.protected_row_type_regressions,
        p95_ns=p95_ns,
        peak_rss_bytes=peak_rss_bytes,
        model_bytes=model_bytes,
        dependency_bytes=dependency_bytes,
        deterministic=result.deterministic,
    )


def _safety_failures(
    summary: MeasuredCandidateSummary,
    result: ExperimentResult,
) -> tuple[RecommendationReasonCode, ...]:
    failures: list[RecommendationReasonCode] = []
    if summary.required_field_regressions:
        failures.append(RecommendationReasonCode.REQUIRED_FIELD_REGRESSION)
    if summary.accepted_unsupported_fields:
        failures.append(RecommendationReasonCode.UNSUPPORTED_EVIDENCE)
    if result.hallucinations:
        failures.append(RecommendationReasonCode.ACCEPTED_FIELD_HALLUCINATION)
    if summary.comparable_coverage and summary.false_accept_risk_delta > 0:
        failures.append(RecommendationReasonCode.HIGHER_FALSE_ACCEPT_RISK)
    if not result.deterministic:
        failures.append(RecommendationReasonCode.NONDETERMINISM)
    if summary.protected_row_type_regressions:
        failures.append(RecommendationReasonCode.PROTECTED_SLICE_REGRESSION)
    return tuple(failures)


def _positive_locked_effect(
    summary: MeasuredCandidateSummary,
    result: ExperimentResult,
    baseline: ExperimentResult,
    pareto_ids: frozenset[str],
) -> bool:
    return (
        summary.candidate_id in pareto_ids
        and summary.paired_row_exact_effect > 0
        and summary.paired_row_exact_low > 0
        and result.exact_rows > baseline.exact_rows
    )


def _decision(
    report: MeasuredRecommendationReport,
    *,
    kind: RecommendationKind,
    selected_ids: tuple[str, ...],
    reasons: tuple[RecommendationReasonCode, ...],
    evidence: tuple[RecommendationEvidence, ...],
) -> Recommendation:
    return Recommendation(
        comparison_identity=report.comparison_identity,
        locked_row_sequence_identity=report.locked_row_sequence_identity,
        kind=kind,
        selected_ids=selected_ids,
        reasons=reasons,
        limitations=_limitations(report),
        evidence=evidence,
    )


def recommend(report: MeasuredRecommendationReport) -> Recommendation:
    """Authorize design work only after a unique safe positive locked result."""

    results = _result_by_id(report)
    baseline = results["accepted-baseline"]
    evidence = tuple(
        _evidence(candidate, results[candidate.candidate_id], baseline)
        for candidate in report.candidates
    )
    failures = tuple(
        dict.fromkeys(
            failure
            for candidate in report.candidates
            for failure in _safety_failures(candidate, results[candidate.candidate_id])
        )
    )
    if failures:
        return _decision(
            report,
            kind=RecommendationKind.NO_PRODUCTION_CHANGE,
            selected_ids=(),
            reasons=failures,
            evidence=evidence,
        )

    pareto_ids = _resource_pareto_ids(results)
    positive = tuple(
        candidate
        for candidate in report.candidates
        if _positive_locked_effect(
            candidate,
            results[candidate.candidate_id],
            baseline,
            pareto_ids,
        )
    )
    if not positive:
        return _decision(
            report,
            kind=RecommendationKind.NO_PRODUCTION_CHANGE,
            selected_ids=(),
            reasons=(RecommendationReasonCode.NO_ELIGIBLE_POSITIVE_LOCKED_GAIN,),
            evidence=evidence,
        )
    if len(positive) != 1:
        return _decision(
            report,
            kind=RecommendationKind.NO_PRODUCTION_CHANGE,
            selected_ids=(),
            reasons=(RecommendationReasonCode.NO_UNIQUE_PARETO_WINNER,),
            evidence=evidence,
        )

    selected = positive[0]
    return _decision(
        report,
        kind=RecommendationKind.DESIGN_INTEGRATION,
        selected_ids=(selected.candidate_id,),
        reasons=(
            RecommendationReasonCode.POSITIVE_LOCKED_PAIRED_EFFECT,
            RecommendationReasonCode.PARETO_WINNER,
            RecommendationReasonCode.SAFETY_GATES_PASSED,
        ),
        evidence=evidence,
    )


__all__ = [
    "MeasuredCandidateSummary",
    "MeasuredRecommendationReport",
    "MeasurementLimitationCode",
    "Recommendation",
    "RecommendationEvidence",
    "RecommendationKind",
    "RecommendationLimitation",
    "RecommendationReasonCode",
    "StopReasonCode",
    "recommend",
]
