"""Fail-closed comparison for frozen row-extraction results and controls."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from experiments.row_extraction.comparison.errors import (
    ErrorAssignment,
    ErrorCategory,
    ErrorCategoryCount,
    classify_error,
)
from experiments.row_extraction.comparison.handoff_contracts import ValidatedHandoffs
from experiments.row_extraction.comparison.locked_results import (
    ComparisonError,
    LockedArmResult,
    LockedResultSet,
    fail,
    read_locked_rows,
    row_key,
    validate_locked_arm,
    validate_locked_inputs,
)
from experiments.row_extraction.comparison.reporting import (
    RESULT_IDS,
    ComparisonReport,
    ExperimentResult,
    ResultBasis,
    build_comparison,
    complete_error_counts,
    pareto_front,
    result_fields,
)
from experiments.row_extraction.comparison.statistics import paired_document_bootstrap
from experiments.row_extraction.contracts import (
    FrozenRow,
    GoldRow,
    LaneDisposition,
    OcrReference,
    RowPrediction,
)
from experiments.row_extraction.metrics import MetricReport, score_predictions
from experiments.row_extraction.runner import RunMeasurements

_BOOTSTRAP_SAMPLES = 1_000


def _error_counts(
    assignments: Sequence[ErrorAssignment],
) -> tuple[tuple[ErrorCategoryCount, ...], tuple[ErrorCategoryCount, ...]]:
    primary = tuple(
        ErrorCategoryCount(
            category=category,
            count=sum(value.primary is category for value in assignments),
        )
        for category in ErrorCategory
    )
    secondary = tuple(
        ErrorCategoryCount(
            category=category,
            count=sum(category in value.secondary for value in assignments),
        )
        for category in ErrorCategory
    )
    return primary, secondary


def _document_exact_contributions(
    rows: Sequence[FrozenRow],
    gold: Sequence[GoldRow],
    predictions: Sequence[RowPrediction],
) -> dict[str, Decimal]:
    documents = tuple(sorted({row.document_id for row in rows}))
    contributions: dict[str, Decimal] = {}
    for document_id in documents:
        document_rows = tuple(row for row in rows if row.document_id == document_id)
        document_gold = tuple(value for value in gold if value.document_id == document_id)
        document_predictions = tuple(
            value for value in predictions if value.document_id == document_id
        )
        report = score_predictions(document_rows, document_gold, document_predictions)
        contributions[document_id] = report.exact_row_rate
    return contributions


def _stopped_result(
    experiment_id: str,
    handoffs: ValidatedHandoffs,
) -> ExperimentResult:
    evidence = handoffs.validation_evidence[experiment_id]
    summary = evidence.error_summary
    if (
        summary is None
        or evidence.error_summary_identity is None
        or summary.row_count != evidence.metrics.row_count
        or not complete_error_counts(summary.primary_counts)
        or not complete_error_counts(summary.secondary_counts)
    ):
        fail("stopped validation error evidence mismatch")
    return ExperimentResult(
        experiment_id=experiment_id,
        result_basis=ResultBasis.VALIDATION_STOP,
        disposition=LaneDisposition.VALIDATION_STOPPED,
        stop_reason=evidence.stop_reason,
        p95_ns=None,
        peak_rss_bytes=None,
        model_bytes=None,
        dependency_bytes=None,
        deterministic=len(evidence.measurements) == 2,
        resource_basis=None,
        metric_report=evidence.metrics,
        measurements=None,
        repeat_measurements=None,
        paired_row_exact_interval=None,
        predictions_identity=evidence.predictions_identity,
        repeat_predictions_identity=None,
        error_assignments_identity=evidence.error_summary_identity,
        primary_error_counts=summary.primary_counts,
        secondary_error_counts=summary.secondary_counts,
        **result_fields(evidence.metrics),
    )


def _locked_result(
    experiment_id: str,
    *,
    handoffs: ValidatedHandoffs,
    locked_results: LockedResultSet,
    score_rows: tuple[FrozenRow, ...],
    gold: tuple[GoldRow, ...],
    predictions: tuple[RowPrediction, ...],
    assignments: tuple[ErrorAssignment, ...],
    measurements: RunMeasurements,
    repeat_measurements: RunMeasurements,
    metrics: MetricReport,
    interval_baseline: dict[str, Decimal],
) -> tuple[ExperimentResult, dict[str, Decimal]]:
    raw_result = locked_results.results[experiment_id]
    gold_by_key = {row_key(label): label for label in gold}
    expected_assignments = tuple(
        classify_error(gold_by_key[row_key(prediction)], prediction) for prediction in predictions
    )
    if assignments != expected_assignments or len(assignments) != metrics.row_count:
        fail("locked error-assignment identity mismatch")
    primary, secondary = _error_counts(assignments)
    contributions = _document_exact_contributions(score_rows, gold, predictions)
    baseline = contributions if experiment_id == "accepted-baseline" else interval_baseline
    if not baseline:
        fail("accepted baseline must be scored first")
    interval = paired_document_bootstrap(
        contributions,
        baseline,
        seed=f"{handoffs.foundation_sha}:{experiment_id}:row_exact",
        samples=_BOOTSTRAP_SAMPLES,
    )
    result = ExperimentResult(
        experiment_id=experiment_id,
        result_basis=ResultBasis.LOCKED_TEST,
        disposition=handoffs.dispositions.get(experiment_id),
        stop_reason=None,
        p95_ns=measurements.p95_ns,
        peak_rss_bytes=measurements.peak_rss_bytes,
        model_bytes=measurements.model_bytes,
        dependency_bytes=measurements.dependency_bytes,
        deterministic=True,
        resource_basis=measurements.resource_basis,
        metric_report=metrics,
        measurements=measurements,
        repeat_measurements=repeat_measurements,
        paired_row_exact_interval=interval,
        predictions_identity=raw_result.predictions_identity,
        repeat_predictions_identity=raw_result.repeat_predictions_identity,
        error_assignments_identity=raw_result.error_assignments_identity,
        primary_error_counts=primary,
        secondary_error_counts=secondary,
        **result_fields(metrics),
    )
    return result, baseline


def compare_handoffs(
    handoffs: ValidatedHandoffs,
    locked_results: LockedResultSet,
    gold: Sequence[GoldRow],
    ocr_references: Sequence[OcrReference] = (),
) -> ComparisonReport:
    """Verify, score, and compare the fixed seven-result experiment set."""

    inputs = validate_locked_inputs(handoffs, locked_results, gold)
    results: list[ExperimentResult] = []
    baseline_contributions: dict[str, Decimal] = {}
    for experiment_id in RESULT_IDS:
        if experiment_id not in inputs.expected_locked:
            results.append(_stopped_result(experiment_id, handoffs))
            continue
        raw_result = locked_results.results[experiment_id]
        if not isinstance(raw_result, LockedArmResult) or raw_result.experiment_id != experiment_id:
            fail("locked result binding mismatch")
        validated_arm = validate_locked_arm(
            raw_result,
            handoffs=handoffs,
            locked_results=locked_results,
            rows=inputs.rows,
        )
        predictions = validated_arm.predictions
        assignments = validated_arm.assignments
        # Reopen and validate the fixed row stream for every score operation.
        score_rows = read_locked_rows(locked_results)
        metrics = score_predictions(
            score_rows,
            inputs.ordered_gold,
            predictions,
            tuple(ocr_references),
        )
        result, baseline_contributions = _locked_result(
            experiment_id,
            handoffs=handoffs,
            locked_results=locked_results,
            score_rows=score_rows,
            gold=inputs.ordered_gold,
            predictions=predictions,
            assignments=assignments,
            measurements=validated_arm.measurements,
            repeat_measurements=validated_arm.repeat_measurements,
            metrics=metrics,
            interval_baseline=baseline_contributions,
        )
        results.append(result)
    return build_comparison(tuple(results))


__all__ = [
    "ComparisonError",
    "ComparisonReport",
    "ExperimentResult",
    "LockedArmResult",
    "LockedResultSet",
    "ResultBasis",
    "build_comparison",
    "compare_handoffs",
    "pareto_front",
]
