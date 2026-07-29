from __future__ import annotations

import json
from decimal import Decimal

import pytest

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FieldRole,
    RowType,
)
from experiments.row_extraction.metrics import (
    CalibrationBin,
    ConfusionCell,
    FieldMetric,
    MetricReport,
    RiskCoveragePoint,
    RiskTargetCoverage,
    RowTypeMetric,
)
from experiments.row_extraction.report import (
    ReportContext,
    ReportContractError,
    privacy_safe_report,
)
from experiments.row_extraction.runner import RunMeasurements


def _identity(character: str, artifact_type: str = "synthetic") -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=character * 64,
        version="synthetic-v1",
        byte_size=17,
    )


def _field_metric() -> FieldMetric:
    return FieldMetric(
        role=FieldRole.DESCRIPTION,
        eligible_rows=2,
        exact_matches=1,
        normalized_matches=2,
        omissions=0,
        hallucinations=0,
        exact_rate=Decimal("0.5"),
        normalized_rate=Decimal("1"),
        omission_rate=Decimal("0"),
        hallucination_rate=Decimal("0"),
    )


def _metric_report() -> MetricReport:
    return MetricReport(
        row_count=2,
        exact_rows=1,
        exact_row_rate=Decimal("0.5"),
        row_type_correct=2,
        row_type_accuracy=Decimal("1"),
        row_type_macro_f1=Decimal("1"),
        row_types=(
            RowTypeMetric(
                row_type=RowType.PRIMARY_TRANSACTION,
                precision=Decimal("1"),
                recall=Decimal("1"),
                f1=Decimal("1"),
                support=2,
            ),
        ),
        row_type_confusion=(
            ConfusionCell(
                gold=RowType.PRIMARY_TRANSACTION,
                predicted=RowType.PRIMARY_TRANSACTION,
                count=2,
            ),
        ),
        fields={FieldRole.DESCRIPTION: _field_metric()},
        accepted_rows=1,
        abstained_rows=1,
        rejected_rows=0,
        ignored_rows=0,
        unsupported_evidence=0,
        ownership_collisions=0,
        ocr_cer=Decimal("0.1"),
        ocr_wer=Decimal("0.2"),
        calibration_bins=(
            CalibrationBin(
                lower=Decimal("0"),
                upper=Decimal("0.1"),
                count=1,
                mean_confidence=Decimal("0.05"),
                empirical_accuracy=Decimal("0"),
            ),
        ),
        brier_score=Decimal("0.25"),
        log_loss=Decimal("0.3"),
        expected_calibration_error=Decimal("0.05"),
        risk_coverage=(
            RiskCoveragePoint(
                threshold=Decimal("0.8"),
                coverage=Decimal("0.5"),
                selective_risk=Decimal("0"),
                accepted_rows=1,
            ),
        ),
        area_under_risk_coverage=Decimal("0.1"),
        coverage_at_risk=(
            RiskTargetCoverage(
                target_risk=Decimal("0.01"),
                coverage=Decimal("0.5"),
            ),
        ),
    )


def _run(**updates: object) -> RunMeasurements:
    values: dict[str, object] = {
        "experiment_id": "synthetic-arm",
        "config_id": "synthetic-config",
        "row_sequence_identity": _identity("1", "frozen-row-sequence"),
        "split": DatasetSplit.VALIDATION,
        "cache_policy": "new-empty-v1",
        "resource_basis": "end-to-end-method",
        "arm_manifest_identity": _identity("2"),
        "row_count": 2,
        "total_ns": 200,
        "p50_ns": 80,
        "p95_ns": 120,
        "preparation_ns": 100,
        "end_to_end_ns": 300,
        "cold_start_ns": 90,
        "throughput_rows_per_second": Decimal("10000000"),
        "peak_rss_bytes": 1024,
        "model_bytes": 11,
        "dependency_bytes": 22,
        "cache_bytes": 33,
        "subprocess_count": 4,
        "worker_count": 1,
        "measurement_protocol": "row-resource-measurement-v1",
        "runtime_identity": _identity("3"),
        "model_inventory_identity": _identity("4", "resource-inventory"),
        "dependency_inventory_identity": _identity("5", "resource-inventory"),
        "resource_inventory_identity": _identity("6", "resource-inventory"),
        "predictions_sha256": "7" * 64,
    }
    values.update(updates)
    return RunMeasurements.model_validate(values)


def _context(**updates: object) -> ReportContext:
    values: dict[str, object] = {
        "experiment_id": "synthetic-arm",
        "config_id": "synthetic-config",
        "measurement_protocol": "row-resource-measurement-v1",
        "runtime_identity": _identity("3"),
        "python_version": "3.13.5",
        "public_runtime_versions": (("pymupdf", "1.26.3"), ("tesseract", "5.5.0")),
    }
    values.update(updates)
    return ReportContext.model_validate(values)


def test_privacy_safe_report_contains_complete_aggregate_metrics_and_resources() -> None:
    report = privacy_safe_report(_metric_report(), _run(), _context())

    assert report["experiment_id"] == "synthetic-arm"
    assert report["config_id"] == "synthetic-config"
    assert report["split"] == "validation"
    assert report["resource_basis"] == "end-to-end-method"
    assert report["cache_policy"] == "new-empty-v1"
    assert report["metrics"] == _metric_report().model_dump(mode="json")
    assert report["resources"] == {
        "preparation_ns": 100,
        "total_ns": 200,
        "end_to_end_ns": 300,
        "cold_start_ns": 90,
        "p50_ns": 80,
        "p95_ns": 120,
        "throughput_rows_per_second": "10000000",
        "peak_rss_bytes": 1024,
        "model_bytes": 11,
        "dependency_bytes": 22,
        "cache_bytes": 33,
        "subprocess_count": 4,
        "worker_count": 1,
    }
    assert report["runtime"] == {
        "python_version": "3.13.5",
        "public_versions": {"pymupdf": "1.26.3", "tesseract": "5.5.0"},
    }


def test_privacy_safe_report_excludes_all_private_identities_and_values() -> None:
    report = privacy_safe_report(_metric_report(), _run(), _context())
    serialized = json.dumps(report, sort_keys=True)

    for private_value in (
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
        "5" * 64,
        "6" * 64,
        "7" * 64,
        "row_id",
        "document_id",
        "source_pdf",
        "canonical_value",
        "atom_id",
        "sha256",
        "path",
    ):
        assert private_value not in serialized


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("run", "experiment_id", "other"),
        ("run", "config_id", "other"),
        ("context", "runtime_identity", _identity("8")),
    ),
)
def test_privacy_safe_report_rejects_identity_mismatches_without_values(
    target: str,
    field: str,
    value: object,
) -> None:
    run = _run()
    context = _context()
    if target == "run":
        run = run.model_copy(update={field: value})
    else:
        context = context.model_copy(update={field: value})

    with pytest.raises(ReportContractError, match=r"^report context mismatch$") as raised:
        privacy_safe_report(_metric_report(), run, context)

    assert raised.value.__cause__ is None


def test_privacy_safe_report_revalidates_forged_context_without_leaking_values() -> None:
    context = _context().model_copy(
        update={
            "public_runtime_versions": (
                ("private-runtime-name", "private-version-one"),
                ("private-runtime-name", "private-version-two"),
            )
        }
    )

    with pytest.raises(ReportContractError, match=r"^invalid report input$") as raised:
        privacy_safe_report(_metric_report(), _run(), context)

    assert raised.value.__cause__ is None
    assert "private" not in str(raised.value)


@pytest.mark.parametrize(
    "versions",
    (
        (("tesseract", "5"), ("pymupdf", "1")),
        (("tesseract", "5"), ("tesseract", "6")),
        (("", "5"),),
        (("tesseract", ""),),
        ((" tesseract", "5"),),
        (("tesseract", "5 "),),
    ),
)
def test_report_context_requires_sorted_unique_public_runtime_versions(
    versions: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError):
        _context(public_runtime_versions=versions)


def test_report_context_requires_canonical_python_version() -> None:
    with pytest.raises(ValueError):
        _context(python_version=" 3.13.5")


def test_report_requires_matching_metric_and_run_row_counts() -> None:
    with pytest.raises(ReportContractError, match=r"^report row count mismatch$"):
        privacy_safe_report(_metric_report(), _run(row_count=3), _context())
