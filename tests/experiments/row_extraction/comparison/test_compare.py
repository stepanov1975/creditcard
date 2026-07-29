from __future__ import annotations

import pytest

from experiments.row_extraction.comparison.compare import (
    ExperimentResult,
    ResultBasis,
    build_comparison,
)
from experiments.row_extraction.contracts import LaneDisposition


def _result(
    experiment_id: str,
    *,
    basis: ResultBasis,
    disposition: LaneDisposition | None,
    exact_rows: int = 0,
    merchant_exact_rows: int = 0,
    omissions: int = 0,
    hallucinations: int = 0,
    resource_basis: str | None = "end-to-end-method",
) -> ExperimentResult:
    stopped = disposition is LaneDisposition.VALIDATION_STOPPED
    return ExperimentResult(
        experiment_id=experiment_id,
        result_basis=basis,
        disposition=disposition,
        stop_reason="validation_stop" if stopped else None,
        row_count=10,
        exact_rows=exact_rows,
        merchant_exact_rows=merchant_exact_rows,
        omissions=omissions,
        hallucinations=hallucinations,
        accepted_rows=exact_rows,
        p95_ns=None if stopped else 100,
        peak_rss_bytes=None if stopped else 1024,
        model_bytes=None if stopped else 0,
        dependency_bytes=None if stopped else 2048,
        deterministic=True,
        resource_basis=None if stopped else resource_basis,
    )


def _complete_results() -> tuple[ExperimentResult, ...]:
    return (
        _result(
            "accepted-baseline",
            basis=ResultBasis.LOCKED_TEST,
            disposition=None,
            exact_rows=3,
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
        ),
        _result(
            "row-profiles",
            basis=ResultBasis.LOCKED_TEST,
            disposition=LaneDisposition.FROZEN_ELIGIBLE,
        ),
        _result(
            "row-text",
            basis=ResultBasis.VALIDATION_STOP,
            disposition=LaneDisposition.VALIDATION_STOPPED,
        ),
        _result(
            "row-vision",
            basis=ResultBasis.VALIDATION_STOP,
            disposition=LaneDisposition.VALIDATION_STOPPED,
        ),
    )


def test_comparison_requires_every_metric_family_and_result_id() -> None:
    report = build_comparison(_complete_results())

    assert report.experiment_ids == (
        "accepted-baseline",
        "conditional-page-ocr",
        "forced-page-ocr",
        "row-ocr",
        "row-profiles",
        "row-text",
        "row-vision",
    )
    assert report.required_metric_families == (
        "row_exact",
        "merchant",
        "typed_fields",
        "omission_hallucination",
        "ocr_error",
        "calibration_abstention",
        "resources_determinism",
        "row_type_errors",
    )
    assert "row-ocr" not in report.locked_experiment_ids
    assert "row-ocr" in report.validation_stopped_ids


def test_comparison_rejects_missing_or_duplicate_result() -> None:
    complete = _complete_results()

    with pytest.raises(ValueError, match="comparison requires exactly seven result IDs"):
        build_comparison(complete[:-1])
    with pytest.raises(ValueError, match="comparison requires exactly seven result IDs"):
        build_comparison((*complete[:-1], complete[0]))


def test_stopped_lane_cannot_claim_locked_results_or_resources() -> None:
    complete = list(_complete_results())
    complete[3] = complete[3].model_copy(
        update={
            "result_basis": ResultBasis.LOCKED_TEST,
            "p95_ns": 10,
            "resource_basis": "end-to-end-method",
        }
    )

    with pytest.raises(ValueError, match="stopped result must remain validation-only"):
        build_comparison(tuple(complete))


def test_pareto_excludes_materialized_adapter_and_validation_stops() -> None:
    report = build_comparison(_complete_results())

    assert "accepted-baseline" not in report.resource_pareto_ids
    assert "row-vision" not in report.resource_pareto_ids
    assert set(report.resource_pareto_ids) <= {
        "conditional-page-ocr",
        "forced-page-ocr",
        "row-profiles",
    }
