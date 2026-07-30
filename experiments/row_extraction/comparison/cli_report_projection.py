"""Privacy-safe aggregate projection for the private comparison report."""

from __future__ import annotations

from dataclasses import dataclass

from experiments.row_extraction.contracts import FieldRole

from .reporting import ComparisonReport, ResultBasis

type TableRow = tuple[object, ...]


def display_value(value: object | None) -> str:
    """Render absence explicitly without inventing a numeric value."""

    return "unavailable" if value is None else str(value)


@dataclass(frozen=True)
class ComparisonReportProjection:
    """Closed aggregate rows consumed by the Markdown renderer."""

    exact_rows: tuple[TableRow, ...]
    field_rows: tuple[TableRow, ...]
    decision_rows: tuple[TableRow, ...]
    ocr_rows: tuple[TableRow, ...]
    calibration_rows: tuple[TableRow, ...]
    bin_rows: tuple[TableRow, ...]
    risk_rows: tuple[TableRow, ...]
    target_rows: tuple[TableRow, ...]
    row_type_rows: tuple[TableRow, ...]
    confusion_rows: tuple[TableRow, ...]
    error_rows: tuple[TableRow, ...]
    interval_rows: tuple[TableRow, ...]
    resource_rows: tuple[TableRow, ...]
    footprint_rows: tuple[TableRow, ...]
    determinism_rows: tuple[TableRow, ...]
    pareto_rows: tuple[TableRow, ...]


def project_comparison_report(report: ComparisonReport) -> ComparisonReportProjection:
    """Project every tracked aggregate without paths, hashes, or row contents."""

    rows: dict[str, list[TableRow]] = {
        name: []
        for name in (
            "exact",
            "field",
            "decision",
            "ocr",
            "calibration",
            "bin",
            "risk",
            "target",
            "row_type",
            "confusion",
            "error",
            "interval",
            "resource",
            "footprint",
            "determinism",
            "pareto",
        )
    }
    for result in report.results:
        metrics = result.metric_report
        if metrics is None:
            raise ValueError("comparison result lacks metric report")
        basis = result.result_basis.value
        merchant = metrics.fields[FieldRole.DESCRIPTION]
        rows["exact"].append(
            (
                result.experiment_id,
                basis,
                metrics.row_count,
                metrics.exact_rows,
                metrics.exact_row_rate,
                merchant.eligible_rows,
                merchant.exact_matches,
                merchant.exact_rate,
                merchant.normalized_matches,
                merchant.normalized_rate,
            )
        )
        rows["field"].extend(
            (
                result.experiment_id,
                basis,
                role.value,
                metric.eligible_rows,
                metric.exact_matches,
                metric.exact_rate,
                metric.normalized_matches,
                metric.normalized_rate,
                metric.omissions,
                metric.omission_rate,
                metric.hallucinations,
                metric.hallucination_rate,
            )
            for role, metric in metrics.fields.items()
        )
        rows["decision"].append(
            (
                result.experiment_id,
                basis,
                metrics.accepted_rows,
                metrics.abstained_rows,
                metrics.rejected_rows,
                metrics.ignored_rows,
                metrics.unsupported_evidence,
                metrics.ownership_collisions,
            )
        )
        rows["ocr"].append(
            (
                result.experiment_id,
                basis,
                display_value(metrics.ocr_cer),
                display_value(metrics.ocr_wer),
                "ocr_error_unavailable"
                if metrics.ocr_cer is None or metrics.ocr_wer is None
                else "available",
            )
        )
        rows["calibration"].append(
            (
                result.experiment_id,
                basis,
                display_value(metrics.brier_score),
                display_value(metrics.log_loss),
                display_value(metrics.expected_calibration_error),
                display_value(metrics.area_under_risk_coverage),
                result.coverage,
                display_value(result.selective_risk),
            )
        )
        rows["bin"].extend(
            (
                result.experiment_id,
                basis,
                value.lower,
                value.upper,
                value.count,
                display_value(value.mean_confidence),
                display_value(value.empirical_accuracy),
            )
            for value in metrics.calibration_bins
        )
        rows["risk"].extend(
            (
                result.experiment_id,
                basis,
                value.threshold,
                value.coverage,
                value.selective_risk,
                value.accepted_rows,
            )
            for value in metrics.risk_coverage
        )
        rows["target"].extend(
            (result.experiment_id, basis, value.target_risk, value.coverage)
            for value in metrics.coverage_at_risk
        )
        rows["row_type"].extend(
            (
                result.experiment_id,
                basis,
                value.row_type.value,
                value.precision,
                value.recall,
                value.f1,
                value.support,
            )
            for value in metrics.row_types
        )
        rows["confusion"].extend(
            (
                result.experiment_id,
                basis,
                value.gold.value,
                value.predicted.value,
                value.count,
            )
            for value in metrics.row_type_confusion
        )
        primary = {value.category: value.count for value in result.primary_error_counts}
        secondary = {value.category: value.count for value in result.secondary_error_counts}
        rows["error"].extend(
            (result.experiment_id, basis, category.value, primary[category], secondary[category])
            for category in primary
        )
        interval = result.paired_row_exact_interval
        rows["interval"].append(
            (
                result.experiment_id,
                "accepted-baseline",
                "row_exact",
                display_value(None if interval is None else interval.effect),
                display_value(None if interval is None else interval.low),
                display_value(None if interval is None else interval.high),
                display_value(None if interval is None else interval.samples),
                basis,
            )
        )
        measurement = result.measurements
        rows["resource"].append(
            (
                result.experiment_id,
                display_value(result.resource_basis),
                display_value(None if measurement is None else measurement.preparation_ns),
                display_value(None if measurement is None else measurement.total_ns),
                display_value(None if measurement is None else measurement.end_to_end_ns),
                display_value(None if measurement is None else measurement.cold_start_ns),
                display_value(None if measurement is None else measurement.p50_ns),
                display_value(None if measurement is None else measurement.p95_ns),
                display_value(
                    None if measurement is None else measurement.throughput_rows_per_second
                ),
                display_value(None if measurement is None else measurement.peak_rss_bytes),
            )
        )
        rows["footprint"].append(
            (
                result.experiment_id,
                display_value(result.resource_basis),
                display_value(None if measurement is None else measurement.model_bytes),
                display_value(None if measurement is None else measurement.dependency_bytes),
                display_value(None if measurement is None else measurement.cache_bytes),
                display_value(None if measurement is None else measurement.subprocess_count),
                display_value(None if measurement is None else measurement.worker_count),
                display_value(None if measurement is None else measurement.measurement_protocol),
            )
        )
        rows["determinism"].append(
            (
                result.experiment_id,
                result.deterministic,
                result.result_basis is ResultBasis.LOCKED_TEST,
                result.repeat_measurements is not None,
            )
        )
        rows["pareto"].append(
            (
                result.experiment_id,
                basis,
                result.deterministic,
                display_value(result.resource_basis),
                result.exact_rows,
                result.merchant_exact_rows,
                result.wrong_required_fields,
                result.hallucinations,
                result.coverage,
                display_value(result.selective_risk),
                display_value(None if measurement is None else measurement.end_to_end_ns),
                display_value(None if measurement is None else measurement.peak_rss_bytes),
                display_value(None if measurement is None else measurement.model_bytes),
                result.experiment_id in report.resource_pareto_ids,
            )
        )
    return ComparisonReportProjection(
        exact_rows=tuple(rows["exact"]),
        field_rows=tuple(rows["field"]),
        decision_rows=tuple(rows["decision"]),
        ocr_rows=tuple(rows["ocr"]),
        calibration_rows=tuple(rows["calibration"]),
        bin_rows=tuple(rows["bin"]),
        risk_rows=tuple(rows["risk"]),
        target_rows=tuple(rows["target"]),
        row_type_rows=tuple(rows["row_type"]),
        confusion_rows=tuple(rows["confusion"]),
        error_rows=tuple(rows["error"]),
        interval_rows=tuple(rows["interval"]),
        resource_rows=tuple(rows["resource"]),
        footprint_rows=tuple(rows["footprint"]),
        determinism_rows=tuple(rows["determinism"]),
        pareto_rows=tuple(rows["pareto"]),
    )


__all__ = [
    "ComparisonReportProjection",
    "TableRow",
    "display_value",
    "project_comparison_report",
]
