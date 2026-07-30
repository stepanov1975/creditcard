"""Evidence-bound recommendation stage for the sole eligible locked lane."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal, Never

from experiments.row_extraction.contracts import ArtifactIdentity, FieldRole, RowType, _FrozenModel

from .cli_cascade_products import read_cascade_products
from .cli_manifest import read_cli_manifest
from .cli_state import (
    create_stage,
    write_bytes_exclusive,
    write_identified_model,
)
from .recommend import (
    MeasuredCandidateSummary,
    MeasuredRecommendationReport,
    MeasurementLimitationCode,
    Recommendation,
    RecommendationKind,
    RecommendationReasonCode,
    recommend,
)
from .reporting import ExperimentResult
from .result_catalog import PRIMARY_REQUIRED_FIELD_ROLES


class RecommendationStageError(ValueError):
    """The locked evidence cannot support a closed recommendation record."""


def _fail(message: str) -> Never:
    raise RecommendationStageError(message)


class RecommendationEnvelopeV1(_FrozenModel):
    version: Literal["row-comparison-recommendation-v1"]
    candidate_ids: tuple[Literal["row-profiles"], ...]
    cascade_candidate_count: Literal[0]
    recommendation: Recommendation


class RecommendationCompletionReceiptV1(_FrozenModel):
    version: Literal["row-comparison-recommendation-completion-v1"]
    cascade_completion_identity: ArtifactIdentity
    comparison_identity: ArtifactIdentity
    recommendation_identity: ArtifactIdentity
    kind: RecommendationKind
    selected_ids: tuple[str, ...]
    reason_codes: tuple[RecommendationReasonCode, ...]
    candidate_ids: tuple[Literal["row-profiles"], ...]


def _result(report: tuple[ExperimentResult, ...], experiment_id: str) -> ExperimentResult:
    try:
        return next(value for value in report if value.experiment_id == experiment_id)
    except StopIteration:
        _fail("recommendation result membership mismatch")


def _required_regressions(
    baseline: ExperimentResult,
    candidate: ExperimentResult,
) -> tuple[FieldRole, ...]:
    if baseline.metric_report is None or candidate.metric_report is None:
        _fail("recommendation metric evidence is incomplete")
    return tuple(
        role
        for role in FieldRole
        if role in PRIMARY_REQUIRED_FIELD_ROLES
        and candidate.metric_report.fields[role].exact_matches
        < baseline.metric_report.fields[role].exact_matches
    )


def _protected_regressions(
    baseline: ExperimentResult,
    candidate: ExperimentResult,
) -> tuple[RowType, ...]:
    if baseline.metric_report is None or candidate.metric_report is None:
        _fail("recommendation metric evidence is incomplete")
    baseline_types = {value.row_type: value for value in baseline.metric_report.row_types}
    candidate_types = {value.row_type: value for value in candidate.metric_report.row_types}
    if set(baseline_types) != set(RowType) or set(candidate_types) != set(RowType):
        _fail("recommendation row-type evidence is incomplete")
    return tuple(
        row_type
        for row_type in RowType
        if baseline_types[row_type].support > 0
        and candidate_types[row_type].recall < baseline_types[row_type].recall
    )


def _risk_comparison(
    baseline: ExperimentResult,
    candidate: ExperimentResult,
) -> tuple[Decimal, bool]:
    if baseline.row_count != candidate.row_count or baseline.row_count <= 0:
        _fail("recommendation row universe mismatch")
    if (
        baseline.coverage != candidate.coverage
        or baseline.selective_risk is None
        or candidate.selective_risk is None
    ):
        return Decimal(0), False
    return candidate.selective_risk - baseline.selective_risk, True


def _candidate_summary(
    comparison: tuple[ExperimentResult, ...],
    *,
    measurement_identity: ArtifactIdentity,
    row_identity: ArtifactIdentity,
) -> MeasuredCandidateSummary:
    baseline = _result(comparison, "accepted-baseline")
    candidate = _result(comparison, "row-profiles")
    interval = candidate.paired_row_exact_interval
    metrics = candidate.metric_report
    if interval is None or metrics is None:
        _fail("eligible candidate lacks locked evidence")
    limitations: list[MeasurementLimitationCode] = []
    if metrics.ocr_cer is None or metrics.ocr_wer is None:
        limitations.append(MeasurementLimitationCode.OCR_ERROR_UNAVAILABLE)
    risk_delta, comparable_coverage = _risk_comparison(baseline, candidate)
    if not comparable_coverage:
        limitations.append(MeasurementLimitationCode.COVERAGE_NOT_COMPARABLE)
    return MeasuredCandidateSummary(
        candidate_id="row-profiles",
        measurement_identity=measurement_identity,
        row_sequence_identity=row_identity,
        paired_row_exact_effect=interval.effect,
        paired_row_exact_low=interval.low,
        paired_row_exact_high=interval.high,
        required_field_regressions=_required_regressions(baseline, candidate),
        accepted_unsupported_fields=metrics.unsupported_evidence,
        false_accept_risk_delta=risk_delta,
        comparable_coverage=comparable_coverage,
        protected_row_type_regressions=_protected_regressions(baseline, candidate),
        abstained_rows=metrics.abstained_rows,
        limitations=tuple(limitations),
    )


def _private_markdown(value: Recommendation) -> bytes:
    reasons = "\n".join(f"- {reason.value}" for reason in value.reasons)
    selected = ", ".join(value.selected_ids) if value.selected_ids else "none"
    return (
        "# Row-extraction recommendation\n\n"
        f"- decision: {value.kind.value}\n"
        f"- selected experiment IDs: {selected}\n"
        "- reasons:\n"
        f"{reasons}\n"
    ).encode()


def recommend_stage(manifest_path: Path) -> dict[str, object]:
    """Create the sole-candidate measured recommendation without adding cascade gain."""

    cli = read_cli_manifest(manifest_path)
    if (cli.workspace_root / "locked" / "recommendation").exists():
        _fail("recommendation stage already exists")
    products = read_cascade_products(manifest_path)
    root = create_stage(products.locked.cli.workspace_root / "locked", "recommendation")
    profile = next(
        value for value in products.locked.artifacts.arms if value.experiment_id == "row-profiles"
    )
    row_identity = products.locked.locked_inputs.row_sequence_identity
    candidate = _candidate_summary(
        products.locked.report.results,
        measurement_identity=profile.first.measurements.identity,
        row_identity=row_identity,
    )
    measured = MeasuredRecommendationReport(
        comparison=products.locked.report,
        comparison_identity=products.locked.report_identity,
        locked_row_sequence_identity=row_identity,
        candidates=(candidate,),
    )
    decision = recommend(measured)
    envelope = RecommendationEnvelopeV1(
        version="row-comparison-recommendation-v1",
        candidate_ids=("row-profiles",),
        cascade_candidate_count=0,
        recommendation=decision,
    )
    recommendation_identity = write_identified_model(
        root / "recommendation.json",
        envelope,
        artifact_type="row-extraction-recommendation",
        version="row-comparison-recommendation-v1",
    )
    write_bytes_exclusive(root / "recommendation.md", _private_markdown(decision))
    completion = RecommendationCompletionReceiptV1(
        version="row-comparison-recommendation-completion-v1",
        cascade_completion_identity=products.receipt_identity,
        comparison_identity=products.locked.report_identity,
        recommendation_identity=recommendation_identity,
        kind=decision.kind,
        selected_ids=decision.selected_ids,
        reason_codes=decision.reasons,
        candidate_ids=("row-profiles",),
    )
    write_identified_model(
        root / "completion-receipt.json",
        completion,
        artifact_type="row-comparison-recommendation-completion",
        version="row-comparison-recommendation-completion-v1",
    )
    return {
        "candidate_count": 1,
        "cascade_candidate_count": 0,
        "command": "recommend",
        "complete": True,
        "decision": decision.kind.value,
        "reason_codes": tuple(value.value for value in decision.reasons),
        "selected_ids": decision.selected_ids,
    }


__all__ = [
    "RecommendationCompletionReceiptV1",
    "RecommendationEnvelopeV1",
    "RecommendationStageError",
    "recommend_stage",
]
