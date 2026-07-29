"""Closed structural and arithmetic invariants for shared validation metrics."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from experiments.row_extraction.contracts import FieldRole, RowType
from experiments.row_extraction.metrics import MetricReport

from .handoff_contracts import HandoffError

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_CALIBRATION_BIN_COUNT = 10
_RISK_TARGETS = (Decimal("0.001"), Decimal("0.005"), Decimal("0.01"))


def _fail() -> None:
    raise HandoffError("validation metrics are incomplete or incoherent")


def _ratio(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    with localcontext(_CONTEXT):
        return Decimal(numerator) / Decimal(denominator)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(_CONTEXT):
        return sum(values, start=Decimal(0)) / Decimal(len(values))


def _unit_interval(value: Decimal) -> bool:
    return value.is_finite() and Decimal(0) <= value <= Decimal(1)


def _validate_row_types(report: MetricReport) -> None:
    if tuple(metric.row_type for metric in report.row_types) != tuple(RowType):
        _fail()
    expected_cells = {(gold, predicted) for gold in RowType for predicted in RowType}
    observed_cells = {(cell.gold, cell.predicted) for cell in report.row_type_confusion}
    if len(report.row_type_confusion) != len(expected_cells) or observed_cells != expected_cells:
        _fail()
    counts = {(cell.gold, cell.predicted): cell.count for cell in report.row_type_confusion}
    if sum(counts.values()) != report.row_count:
        _fail()
    correct = sum(counts[(row_type, row_type)] for row_type in RowType)
    if correct != report.row_type_correct:
        _fail()
    for metric in report.row_types:
        true_positive = counts[(metric.row_type, metric.row_type)]
        predicted = sum(counts[(gold, metric.row_type)] for gold in RowType)
        support = sum(counts[(metric.row_type, predicted_type)] for predicted_type in RowType)
        if (
            metric.support != support
            or metric.precision != _ratio(true_positive, predicted)
            or metric.recall != _ratio(true_positive, support)
            or metric.f1 != _ratio(2 * true_positive, predicted + support)
        ):
            _fail()
    if report.row_type_macro_f1 != _mean(tuple(metric.f1 for metric in report.row_types)):
        _fail()


def _validate_fields(report: MetricReport) -> None:
    if set(report.fields) != set(FieldRole):
        _fail()
    for role in FieldRole:
        metric = report.fields[role]
        if (
            metric.role is not role
            or metric.eligible_rows > report.row_count
            or metric.exact_matches > metric.eligible_rows
            or metric.normalized_matches > metric.eligible_rows
            or metric.normalized_matches < metric.exact_matches
            or metric.omissions > metric.eligible_rows
            or metric.hallucinations > report.row_count
            or metric.exact_matches + metric.omissions > metric.eligible_rows
            or metric.exact_rate != _ratio(metric.exact_matches, metric.eligible_rows)
            or metric.normalized_rate != _ratio(metric.normalized_matches, metric.eligible_rows)
            or metric.omission_rate != _ratio(metric.omissions, metric.eligible_rows)
            or metric.hallucination_rate != _ratio(metric.hallucinations, report.row_count)
        ):
            _fail()


def _validate_calibration(report: MetricReport) -> None:
    if len(report.calibration_bins) != _CALIBRATION_BIN_COUNT:
        _fail()
    confidence_rows = 0
    for index, bin_ in enumerate(report.calibration_bins):
        if bin_.lower != _ratio(index, _CALIBRATION_BIN_COUNT) or bin_.upper != _ratio(
            index + 1, _CALIBRATION_BIN_COUNT
        ):
            _fail()
        confidence_rows += bin_.count
        if bin_.count == 0:
            if bin_.mean_confidence is not None or bin_.empirical_accuracy is not None:
                _fail()
        elif (
            bin_.mean_confidence is None
            or bin_.empirical_accuracy is None
            or not _unit_interval(bin_.mean_confidence)
            or not _unit_interval(bin_.empirical_accuracy)
        ):
            _fail()
    if confidence_rows > report.row_count:
        _fail()
    calibration_values = (
        report.brier_score,
        report.log_loss,
        report.expected_calibration_error,
    )
    if confidence_rows == 0:
        if any(value is not None for value in calibration_values):
            _fail()
    elif (
        report.brier_score is None
        or report.log_loss is None
        or report.expected_calibration_error is None
        or not _unit_interval(report.brier_score)
        or not report.log_loss.is_finite()
        or report.log_loss < 0
        or not _unit_interval(report.expected_calibration_error)
    ):
        _fail()


def _validate_selective_risk(report: MetricReport) -> None:
    previous_accepted = 0
    previous_threshold: Decimal | None = None
    for point in report.risk_coverage:
        if (
            not _unit_interval(point.threshold)
            or not _unit_interval(point.coverage)
            or not _unit_interval(point.selective_risk)
            or point.accepted_rows <= previous_accepted
            or point.accepted_rows > report.accepted_rows
            or point.coverage != _ratio(point.accepted_rows, report.row_count)
            or (previous_threshold is not None and point.threshold >= previous_threshold)
        ):
            _fail()
        previous_accepted = point.accepted_rows
        previous_threshold = point.threshold
    if report.risk_coverage:
        if report.area_under_risk_coverage is None or not _unit_interval(
            report.area_under_risk_coverage
        ):
            _fail()
    elif report.area_under_risk_coverage is not None:
        _fail()
    if tuple(value.target_risk for value in report.coverage_at_risk) != _RISK_TARGETS or any(
        not _unit_interval(value.coverage) for value in report.coverage_at_risk
    ):
        _fail()


def validate_metric_report(report: MetricReport, expected_row_count: int) -> None:
    """Reject incomplete or internally impossible shared metric reports."""

    decision_total = (
        report.accepted_rows + report.abstained_rows + report.rejected_rows + report.ignored_rows
    )
    if (
        report.row_count != expected_row_count
        or report.exact_rows > report.row_count
        or report.row_type_correct > report.row_count
        or report.exact_row_rate != _ratio(report.exact_rows, report.row_count)
        or report.row_type_accuracy != _ratio(report.row_type_correct, report.row_count)
        or decision_total != report.row_count
    ):
        _fail()
    _validate_row_types(report)
    _validate_fields(report)
    _validate_calibration(report)
    _validate_selective_risk(report)
    for value in (report.ocr_cer, report.ocr_wer):
        if value is not None and (not value.is_finite() or value < 0):
            _fail()


__all__ = ["validate_metric_report"]
