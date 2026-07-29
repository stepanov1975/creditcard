"""Typed seven-result report and predeclared Pareto comparison axes."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self, TypedDict

from pydantic import Field, model_validator

from experiments.row_extraction.comparison.errors import (
    ErrorCategory,
    ErrorCategoryCount,
)
from experiments.row_extraction.comparison.statistics import PairedInterval
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FieldRole,
    LaneDisposition,
    _FrozenModel,
)
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import RunMeasurements

RESULT_IDS = (
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
    "row-ocr",
    "row-profiles",
    "row-text",
    "row-vision",
)
BASELINE_IDS = frozenset(RESULT_IDS[:3])
METRIC_FAMILIES = (
    "row_exact",
    "merchant",
    "typed_fields",
    "omission_hallucination",
    "ocr_error",
    "calibration_abstention",
    "resources_determinism",
    "row_type_errors",
)


class ResultFields(TypedDict):
    row_count: int
    exact_rows: int
    merchant_exact_rows: int
    omissions: int
    hallucinations: int
    accepted_rows: int
    wrong_required_fields: int
    coverage: Decimal
    selective_risk: Decimal | None


class ResultBasis(StrEnum):
    """Whether a result is a locked measurement or preserved validation evidence."""

    LOCKED_TEST = "locked_test"
    VALIDATION_STOP = "validation_stop"


def field_errors(metrics: MetricReport) -> int:
    return sum(metric.eligible_rows - metric.exact_matches for metric in metrics.fields.values())


def omissions(metrics: MetricReport) -> int:
    return sum(metric.omissions for metric in metrics.fields.values())


def hallucinations(metrics: MetricReport) -> int:
    return sum(metric.hallucinations for metric in metrics.fields.values())


def risk_endpoint(metrics: MetricReport) -> tuple[Decimal, Decimal | None]:
    if not metrics.risk_coverage:
        return Decimal(0), None
    endpoint = metrics.risk_coverage[-1]
    return endpoint.coverage, endpoint.selective_risk


def complete_error_counts(values: tuple[ErrorCategoryCount, ...]) -> bool:
    return tuple(value.category for value in values) == tuple(ErrorCategory)


def result_fields(metrics: MetricReport) -> ResultFields:
    coverage, risk = risk_endpoint(metrics)
    return {
        "row_count": metrics.row_count,
        "exact_rows": metrics.exact_rows,
        "merchant_exact_rows": metrics.fields[FieldRole.DESCRIPTION].exact_matches,
        "omissions": omissions(metrics),
        "hallucinations": hallucinations(metrics),
        "accepted_rows": metrics.accepted_rows,
        "wrong_required_fields": field_errors(metrics),
        "coverage": coverage,
        "selective_risk": risk,
    }


class ExperimentResult(_FrozenModel):
    """One complete metric/resource projection without a weighted score."""

    experiment_id: str = Field(min_length=1)
    result_basis: ResultBasis
    disposition: LaneDisposition | None
    stop_reason: str | None
    row_count: int = Field(gt=0)
    exact_rows: int = Field(ge=0)
    merchant_exact_rows: int = Field(ge=0)
    omissions: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    p95_ns: int | None = Field(default=None, gt=0)
    peak_rss_bytes: int | None = Field(default=None, gt=0)
    model_bytes: int | None = Field(default=None, ge=0)
    dependency_bytes: int | None = Field(default=None, gt=0)
    deterministic: bool
    resource_basis: Literal["end-to-end-method", "materialized-adapter"] | None
    metric_report: MetricReport | None = None
    measurements: RunMeasurements | None = None
    repeat_measurements: RunMeasurements | None = None
    paired_row_exact_interval: PairedInterval | None = None
    predictions_identity: ArtifactIdentity | None = None
    repeat_predictions_identity: ArtifactIdentity | None = None
    error_assignments_identity: ArtifactIdentity | None = None
    primary_error_counts: tuple[ErrorCategoryCount, ...] = ()
    secondary_error_counts: tuple[ErrorCategoryCount, ...] = ()
    wrong_required_fields: int = Field(default=0, ge=0)
    coverage: Decimal = Field(default=Decimal(0), ge=0, le=1)
    selective_risk: Decimal | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def coherent_basis(self) -> Self:
        stopped = self.disposition is LaneDisposition.VALIDATION_STOPPED
        resources = (
            self.p95_ns,
            self.peak_rss_bytes,
            self.model_bytes,
            self.dependency_bytes,
            self.resource_basis,
            self.measurements,
            self.repeat_measurements,
        )
        if stopped and (
            self.result_basis is not ResultBasis.VALIDATION_STOP
            or not self.stop_reason
            or any(value is not None for value in resources)
            or self.paired_row_exact_interval is not None
            or self.repeat_predictions_identity is not None
        ):
            raise ValueError("stopped result must remain validation-only")
        if not stopped and self.result_basis is ResultBasis.VALIDATION_STOP:
            raise ValueError("validation-stop result requires stopped disposition")
        if self.result_basis is ResultBasis.LOCKED_TEST and any(
            value is None
            for value in (
                self.p95_ns,
                self.peak_rss_bytes,
                self.model_bytes,
                self.dependency_bytes,
                self.resource_basis,
            )
        ):
            raise ValueError("locked result requires complete resource aggregates")
        if self.disposition is LaneDisposition.FROZEN_ELIGIBLE and self.stop_reason is not None:
            raise ValueError("eligible result cannot carry a stop reason")
        if self.exact_rows > self.row_count or self.accepted_rows > self.row_count:
            raise ValueError("result counts exceed row count")
        if bool(self.primary_error_counts) != bool(self.secondary_error_counts) or (
            self.primary_error_counts
            and (
                not complete_error_counts(self.primary_error_counts)
                or not complete_error_counts(self.secondary_error_counts)
            )
        ):
            raise ValueError("result error counts must contain the closed taxonomy")
        if self.metric_report is not None:
            coverage, risk = risk_endpoint(self.metric_report)
            expected = (
                self.metric_report.row_count,
                self.metric_report.exact_rows,
                self.metric_report.fields[FieldRole.DESCRIPTION].exact_matches,
                omissions(self.metric_report),
                hallucinations(self.metric_report),
                self.metric_report.accepted_rows,
                field_errors(self.metric_report),
                coverage,
                risk,
            )
            actual = (
                self.row_count,
                self.exact_rows,
                self.merchant_exact_rows,
                self.omissions,
                self.hallucinations,
                self.accepted_rows,
                self.wrong_required_fields,
                self.coverage,
                self.selective_risk,
            )
            if actual != expected or set(self.metric_report.fields) != set(FieldRole):
                raise ValueError("result summary does not preserve the complete metric report")
        if self.measurements is not None:
            measurement_projection = (
                self.measurements.p95_ns,
                self.measurements.peak_rss_bytes,
                self.measurements.model_bytes,
                self.measurements.dependency_bytes,
                self.measurements.resource_basis,
                self.measurements.row_count,
            )
            summary_projection = (
                self.p95_ns,
                self.peak_rss_bytes,
                self.model_bytes,
                self.dependency_bytes,
                self.resource_basis,
                self.row_count,
            )
            if measurement_projection != summary_projection:
                raise ValueError("result summary does not preserve run measurements")
        if self.repeat_measurements is not None and (
            self.measurements is None
            or self.repeat_measurements.row_count != self.row_count
            or self.repeat_measurements.resource_basis != self.resource_basis
        ):
            raise ValueError("result repeat does not preserve run measurements")
        return self


class ComparisonReport(_FrozenModel):
    """Ordered seven-result report with explicit locked/stopped/Pareto membership."""

    experiment_ids: tuple[str, ...]
    required_metric_families: tuple[str, ...]
    locked_experiment_ids: tuple[str, ...]
    validation_stopped_ids: tuple[str, ...]
    resource_pareto_ids: tuple[str, ...]
    results: tuple[ExperimentResult, ...]


def _pareto_axes(result: ExperimentResult) -> tuple[Decimal, ...] | None:
    metrics = result.metric_report
    measurements = result.measurements
    if (
        metrics is None
        or measurements is None
        or result.selective_risk is None
        or metrics.area_under_risk_coverage is None
        or len(metrics.coverage_at_risk) == 0
    ):
        return None
    return (
        Decimal(result.exact_rows),
        Decimal(result.merchant_exact_rows),
        -Decimal(result.wrong_required_fields),
        -Decimal(result.hallucinations),
        result.coverage,
        -result.selective_risk,
        -metrics.area_under_risk_coverage,
        *(point.coverage for point in metrics.coverage_at_risk),
        -Decimal(measurements.end_to_end_ns),
        -Decimal(measurements.peak_rss_bytes),
        -Decimal(measurements.model_bytes),
    )


def _dominates(first: ExperimentResult, second: ExperimentResult) -> bool:
    first_axes = _pareto_axes(first)
    second_axes = _pareto_axes(second)
    if first_axes is None or second_axes is None:
        return False
    return all(left >= right for left, right in zip(first_axes, second_axes, strict=True)) and any(
        left > right for left, right in zip(first_axes, second_axes, strict=True)
    )


def pareto_front(results: Sequence[ExperimentResult]) -> tuple[str, ...]:
    """Return the ordered end-to-end, deterministic, locked Pareto frontier."""

    candidate_ids = tuple(result.experiment_id for result in results)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Pareto inputs require unique experiment IDs")
    candidates = tuple(
        result
        for result in results
        if result.result_basis is ResultBasis.LOCKED_TEST
        and result.resource_basis == "end-to-end-method"
        and result.deterministic is True
        and _pareto_axes(result) is not None
    )
    return tuple(
        candidate.experiment_id
        for candidate in candidates
        if not any(
            other.experiment_id != candidate.experiment_id and _dominates(other, candidate)
            for other in candidates
        )
    )


def build_comparison(results: tuple[ExperimentResult, ...]) -> ComparisonReport:
    """Validate completeness and expose locked, stopped, and Pareto membership."""

    by_id = {result.experiment_id: result for result in results}
    if len(results) != len(RESULT_IDS) or set(by_id) != set(RESULT_IDS):
        raise ValueError("comparison requires exactly seven result IDs")
    ordered = tuple(by_id[experiment_id] for experiment_id in RESULT_IDS)
    for result in ordered:
        if result.experiment_id in BASELINE_IDS:
            if result.disposition is not None or result.result_basis is not ResultBasis.LOCKED_TEST:
                raise ValueError("baseline must be a locked control result")
        elif result.disposition is None:
            raise ValueError("experiment result requires a lane disposition")
    locked = tuple(
        result.experiment_id for result in ordered if result.result_basis is ResultBasis.LOCKED_TEST
    )
    stopped = tuple(
        result.experiment_id
        for result in ordered
        if result.result_basis is ResultBasis.VALIDATION_STOP
    )
    return ComparisonReport(
        experiment_ids=RESULT_IDS,
        required_metric_families=METRIC_FAMILIES,
        locked_experiment_ids=locked,
        validation_stopped_ids=stopped,
        resource_pareto_ids=pareto_front(ordered),
        results=ordered,
    )


__all__ = [
    "BASELINE_IDS",
    "METRIC_FAMILIES",
    "RESULT_IDS",
    "ComparisonReport",
    "ExperimentResult",
    "ResultBasis",
    "build_comparison",
    "complete_error_counts",
    "pareto_front",
    "result_fields",
]
