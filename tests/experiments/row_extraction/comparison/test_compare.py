from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.comparison.compare import (
    ComparisonError,
    ExperimentResult,
    LockedArmResult,
    LockedResultSet,
    ResultBasis,
    build_comparison,
    compare_handoffs,
    pareto_front,
)
from experiments.row_extraction.comparison.errors import (
    ErrorCategory,
    ErrorCategoryCount,
    ValidationErrorSummary,
    classify_error,
)
from experiments.row_extraction.comparison.handoff_contracts import (
    EXPERIMENT_IDS,
    FrozenRunInputs,
    ValidatedArmBinding,
    ValidatedHandoffs,
    ValidationEvidence,
)
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    Decision,
    FieldProposal,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.metrics import score_predictions
from experiments.row_extraction.runner import MeasuredArmFactory, RunMeasurements
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row

_RESULT_IDS = (
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
    "row-ocr",
    "row-profiles",
    "row-text",
    "row-vision",
)
_STOP_REASONS = {
    "row-ocr": "ocr_stage_validation_failed",
    "row-profiles": "no_profile_candidate_met_validation_gate",
    "row-text": "no_text_candidate_met_validation_gate",
    "row-vision": "no_pixel_gain",
}


def _artifact(
    label: str,
    *,
    artifact_type: str = "synthetic",
    version: str = "synthetic-v1",
) -> ArtifactIdentity:
    payload = label.encode("ascii")
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        version=version,
        byte_size=len(payload),
    )


def _rows() -> tuple[FrozenRow, ...]:
    return (
        frozen_row(
            document_id="a" * 64,
            row_id="row-a",
            split=DatasetSplit.TEST,
            atoms=(evidence_atom(atom_id="atom-a", text="SYNTHETIC A"),),
        ),
        frozen_row(
            document_id="b" * 64,
            row_id="row-b",
            split=DatasetSplit.TEST,
            atoms=(evidence_atom(atom_id="atom-b", text="SYNTHETIC B"),),
        ),
    )


def _gold(rows: tuple[FrozenRow, ...]) -> tuple[GoldRow, ...]:
    return tuple(
        GoldRow(
            document_id=row.document_id,
            row_id=row.row_id,
            row_type=RowType.PRIMARY_TRANSACTION,
            fields=(
                GoldField(
                    role=FieldRole.DESCRIPTION,
                    canonical_value=row.atoms[0].text,
                    atom_ids=(row.atoms[0].atom_id,),
                ),
            ),
        )
        for row in rows
    )


def _predictions(
    rows: tuple[FrozenRow, ...],
    experiment_id: str,
    *,
    wrong_last: bool = False,
) -> tuple[RowPrediction, ...]:
    predictions: list[RowPrediction] = []
    for index, row in enumerate(rows):
        wrong = wrong_last and index == len(rows) - 1
        predictions.append(
            RowPrediction(
                experiment_id=experiment_id,
                config_id=f"{experiment_id}-config",
                document_id=row.document_id,
                row_id=row.row_id,
                predicted_type=RowType.PRIMARY_TRANSACTION,
                evidence_atoms=row.atoms,
                proposals=()
                if wrong
                else (
                    FieldProposal(
                        role=FieldRole.DESCRIPTION,
                        atom_ids=(row.atoms[0].atom_id,),
                        raw_score=1.0,
                    ),
                ),
                exact_row_confidence=0.8 if wrong else 0.9,
                decision=Decision.ACCEPT,
                reasons=("synthetic",),
            )
        )
    return tuple(predictions)


def _row_sequence_identity(path: Path) -> ArtifactIdentity:
    payload = path.read_bytes()
    return ArtifactIdentity(
        artifact_type="frozen-row-sequence",
        sha256=hashlib.sha256(payload).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(payload),
    )


def _measurement(
    experiment_id: str,
    row_identity: ArtifactIdentity,
    prediction_identity: ArtifactIdentity,
    binding: ValidatedArmBinding,
    *,
    split: DatasetSplit,
    repeat: bool = False,
    duration_offset: int = 0,
) -> RunMeasurements:
    arm_manifest = binding.arm_manifest or _artifact(f"{experiment_id}-validation-arm")
    return RunMeasurements(
        experiment_id=experiment_id,
        config_id=binding.config_id,
        row_sequence_identity=row_identity,
        split=split,
        cache_policy="new-empty-v1",
        resource_basis=(
            "materialized-adapter" if experiment_id == "accepted-baseline" else "end-to-end-method"
        ),
        arm_manifest_identity=arm_manifest,
        row_count=2,
        total_ns=200 + duration_offset,
        p50_ns=90 + duration_offset,
        p95_ns=110 + duration_offset,
        preparation_ns=30 + duration_offset,
        end_to_end_ns=230 + duration_offset,
        cold_start_ns=40 + duration_offset,
        throughput_rows_per_second=Decimal("8.5"),
        peak_rss_bytes=1_024 + duration_offset,
        model_bytes=0 if experiment_id == "accepted-baseline" else 64,
        dependency_bytes=2_048,
        cache_bytes=32,
        subprocess_count=1,
        worker_count=1,
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=binding.runtime_identity,
        model_inventory_identity=binding.model_inventory,
        dependency_inventory_identity=binding.dependency_inventory,
        resource_inventory_identity=_artifact(
            f"{experiment_id}-resources-{'repeat' if repeat else 'first'}",
            artifact_type="resource-inventory",
            version="row-resource-inventory-v1",
        ),
        predictions_sha256=prediction_identity.sha256,
    )


def _error_summary(
    gold: tuple[GoldRow, ...], predictions: tuple[RowPrediction, ...]
) -> ValidationErrorSummary:
    assignments = tuple(
        classify_error(label, prediction)
        for label, prediction in zip(gold, predictions, strict=True)
    )
    return ValidationErrorSummary(
        version="row-comparison-error-summary-v1",
        row_count=len(gold),
        primary_counts=tuple(
            ErrorCategoryCount(
                category=category,
                count=sum(assignment.primary is category for assignment in assignments),
            )
            for category in ErrorCategory
        ),
        secondary_counts=tuple(
            ErrorCategoryCount(
                category=category,
                count=sum(category in assignment.secondary for assignment in assignments),
            )
            for category in ErrorCategory
        ),
    )


def _unused_loader(
    rows: tuple[FrozenRow, ...],
    row_sequence_identity: ArtifactIdentity,
    cache_root: Path,
) -> MeasuredArmFactory:
    del rows, row_sequence_identity, cache_root
    raise AssertionError("comparison must not replay a frozen arm")


def _handoffs(
    tmp_path: Path,
    rows: tuple[FrozenRow, ...],
    gold: tuple[GoldRow, ...],
    row_identity: ArtifactIdentity,
    *,
    stopped: frozenset[str] = frozenset(),
) -> ValidatedHandoffs:
    dispositions = {
        experiment_id: (
            LaneDisposition.VALIDATION_STOPPED
            if experiment_id in stopped
            else LaneDisposition.FROZEN_ELIGIBLE
        )
        for experiment_id in EXPERIMENT_IDS
    }
    bindings: dict[str, ValidatedArmBinding] = {}
    evidence: dict[str, ValidationEvidence] = {}
    run_inputs: dict[str, FrozenRunInputs] = {}
    validation_predictions: dict[str, Path] = {}
    for experiment_id in _RESULT_IDS:
        is_stopped = experiment_id in stopped
        binding = ValidatedArmBinding(
            experiment_id=experiment_id,
            config_id=f"{experiment_id}-config",
            runtime_identity=_artifact(f"{experiment_id}-runtime"),
            model_inventory=_artifact(
                f"{experiment_id}-model",
                artifact_type="resource-inventory",
                version="row-resource-inventory-v1",
            ),
            dependency_inventory=_artifact(
                f"{experiment_id}-dependencies",
                artifact_type="resource-inventory",
                version="row-resource-inventory-v1",
            ),
            arm_manifest=None if is_stopped else _artifact(f"{experiment_id}-arm"),
        )
        bindings[experiment_id] = binding
        predictions = _predictions(
            rows,
            experiment_id,
            wrong_last=experiment_id == "row-vision",
        )
        prediction_path = tmp_path / f"{experiment_id}-validation-predictions.jsonl"
        prediction_identity = write_jsonl(prediction_path, predictions)
        validation_predictions[experiment_id] = prediction_path
        metrics = score_predictions(rows, gold, predictions)
        summary = _error_summary(gold, predictions)
        evidence[experiment_id] = ValidationEvidence(
            predictions_path=prediction_path,
            predictions_identity=prediction_identity,
            metrics_path=tmp_path / f"{experiment_id}-validation-metrics.json",
            metrics_identity=_artifact(
                f"{experiment_id}-validation-metrics",
                artifact_type="row-comparison-validation-metrics",
                version="row-comparison-validation-metrics-v1",
            ),
            metrics=metrics,
            measurement_paths=(tmp_path / f"{experiment_id}-validation-measurements.json",),
            measurement_identities=(
                _artifact(
                    f"{experiment_id}-validation-measurements",
                    artifact_type="row-comparison-validation-measurements",
                    version="row-comparison-validation-measurements-v1",
                ),
            ),
            measurements=(
                _measurement(
                    experiment_id,
                    row_identity,
                    prediction_identity,
                    binding,
                    split=DatasetSplit.VALIDATION,
                ),
            ),
            error_summary_path=tmp_path / f"{experiment_id}-validation-errors.json",
            error_summary_identity=_artifact(
                f"{experiment_id}-validation-errors",
                artifact_type="row-comparison-error-summary",
                version="row-comparison-error-summary-v1",
            ),
            error_summary=summary,
            stop_reason=_STOP_REASONS.get(experiment_id) if is_stopped else None,
        )
        if not is_stopped:
            assert binding.arm_manifest is not None
            run_inputs[experiment_id] = FrozenRunInputs(
                experiment_id=experiment_id,
                config_id=binding.config_id,
                arm_manifest=binding.arm_manifest,
                runtime_identity=binding.runtime_identity,
                model_inventory=binding.model_inventory,
                dependency_inventory=binding.dependency_inventory,
                worker_count=1,
                factory_loader=_unused_loader,
                arm_manifest_path=tmp_path / f"{experiment_id}-arm.json",
                model_inventory_path=tmp_path / f"{experiment_id}-model.json",
                dependency_inventory_path=tmp_path / f"{experiment_id}-dependency.json",
            )
    return ValidatedHandoffs(
        foundation_sha="1" * 40,
        dispositions=dispositions,
        run_inputs=run_inputs,
        validation_predictions=validation_predictions,
        arm_bindings=bindings,
        validation_evidence=evidence,
        locked_row_ids=frozenset((row.document_id, row.row_id) for row in rows),
    )


def _locked_results(
    tmp_path: Path,
    rows: tuple[FrozenRow, ...],
    gold: tuple[GoldRow, ...],
    row_identity: ArtifactIdentity,
    handoffs: ValidatedHandoffs,
) -> LockedResultSet:
    results: dict[str, LockedArmResult] = {}
    for offset, experiment_id in enumerate(_RESULT_IDS):
        if handoffs.dispositions.get(experiment_id) is LaneDisposition.VALIDATION_STOPPED:
            continue
        binding = handoffs.arm_bindings[experiment_id]
        predictions = _predictions(
            rows,
            experiment_id,
            wrong_last=experiment_id == "row-vision",
        )
        prediction_path = tmp_path / f"{experiment_id}-predictions.jsonl"
        prediction_identity = write_jsonl(prediction_path, predictions)
        repeat_path = tmp_path / f"{experiment_id}-repeat-predictions.jsonl"
        repeat_identity = write_jsonl(repeat_path, predictions)
        assignments = tuple(
            classify_error(label, prediction)
            for label, prediction in zip(gold, predictions, strict=True)
        )
        error_path = tmp_path / f"{experiment_id}-errors.jsonl"
        error_identity = write_jsonl(error_path, assignments)
        duration_offset = -20 if experiment_id == "row-vision" else offset
        results[experiment_id] = LockedArmResult(
            experiment_id=experiment_id,
            config_id=binding.config_id,
            predictions_path=prediction_path,
            predictions_identity=prediction_identity,
            measurements=_measurement(
                experiment_id,
                row_identity,
                prediction_identity,
                binding,
                split=DatasetSplit.TEST,
                duration_offset=duration_offset,
            ),
            repeat_predictions_path=repeat_path,
            repeat_predictions_identity=repeat_identity,
            repeat_measurements=_measurement(
                experiment_id,
                row_identity,
                repeat_identity,
                binding,
                split=DatasetSplit.TEST,
                repeat=True,
                duration_offset=duration_offset,
            ),
            error_assignments_path=error_path,
            error_assignments_identity=error_identity,
        )
    rows_path = tmp_path / "locked-rows.jsonl"
    write_jsonl(rows_path, rows)
    return LockedResultSet(
        rows_path=rows_path,
        row_sequence_identity=row_identity,
        results=results,
    )


def _case(
    tmp_path: Path,
    *,
    stopped: frozenset[str] = frozenset(),
) -> tuple[
    ValidatedHandoffs,
    LockedResultSet,
    tuple[GoldRow, ...],
]:
    rows = _rows()
    rows_path = tmp_path / "identity-rows.jsonl"
    write_jsonl(rows_path, rows)
    row_identity = _row_sequence_identity(rows_path)
    gold = _gold(rows)
    handoffs = _handoffs(
        tmp_path,
        rows,
        gold,
        row_identity,
        stopped=stopped,
    )
    locked = _locked_results(tmp_path, rows, gold, row_identity, handoffs)
    return handoffs, locked, gold


def test_comparison_requires_every_metric_family_and_lane(tmp_path: Path) -> None:
    handoffs, locked, gold = _case(tmp_path)

    report = compare_handoffs(handoffs, locked, gold)

    assert report.experiment_ids == _RESULT_IDS
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
    by_id = {result.experiment_id: result for result in report.results}
    accepted = by_id["accepted-baseline"]
    vision = by_id["row-vision"]
    assert accepted.result_basis is ResultBasis.LOCKED_TEST
    assert accepted.metric_report is not None
    assert accepted.metric_report.exact_rows == 2
    assert tuple(accepted.metric_report.fields) == tuple(FieldRole)
    assert accepted.metric_report.risk_coverage[-1].coverage == Decimal(1)
    assert accepted.measurements == locked.results["accepted-baseline"].measurements
    assert accepted.repeat_measurements == locked.results["accepted-baseline"].repeat_measurements
    assert (
        accepted.repeat_predictions_identity
        == locked.results["accepted-baseline"].repeat_predictions_identity
    )
    assert accepted.measurements.preparation_ns == 30
    assert accepted.measurements.total_ns == 200
    assert accepted.measurements.end_to_end_ns == 230
    assert accepted.measurements.cold_start_ns == 40
    assert accepted.measurements.p50_ns == 90
    assert accepted.measurements.p95_ns == 110
    assert accepted.measurements.throughput_rows_per_second == Decimal("8.5")
    assert accepted.measurements.cache_bytes == 32
    assert accepted.measurements.subprocess_count == 1
    assert accepted.measurements.worker_count == 1
    assert accepted.measurements.measurement_protocol == "row-resource-measurement-v1"
    assert accepted.resource_basis == "materialized-adapter"
    assert accepted.experiment_id not in report.resource_pareto_ids
    assert vision.metric_report is not None
    assert vision.metric_report.fields[FieldRole.DESCRIPTION].omissions == 1
    assert vision.metric_report.fields[FieldRole.DESCRIPTION].hallucinations == 0
    assert vision.paired_row_exact_interval is not None
    assert vision.paired_row_exact_interval.effect == Decimal("-0.5")
    assert tuple(count.category for count in vision.primary_error_counts) == tuple(ErrorCategory)
    assert sum(count.count for count in vision.primary_error_counts) == 1


def test_stopped_lane_retains_validation_metrics_errors_and_reason_without_locked_claims(
    tmp_path: Path,
) -> None:
    handoffs, locked, gold = _case(tmp_path, stopped=frozenset({"row-vision"}))

    report = compare_handoffs(handoffs, locked, gold)

    stopped = {result.experiment_id: result for result in report.results}["row-vision"]
    validation = handoffs.validation_evidence["row-vision"]
    assert validation.error_summary is not None
    assert stopped.result_basis is ResultBasis.VALIDATION_STOP
    assert stopped.stop_reason == "no_pixel_gain"
    assert stopped.metric_report == validation.metrics
    assert stopped.primary_error_counts == validation.error_summary.primary_counts
    assert stopped.secondary_error_counts == validation.error_summary.secondary_counts
    assert stopped.error_assignments_identity == validation.error_summary_identity
    assert stopped.paired_row_exact_interval is None
    assert stopped.measurements is None
    assert stopped.repeat_measurements is None
    assert stopped.deterministic is False
    assert stopped.resource_basis is None
    assert stopped.experiment_id not in report.locked_experiment_ids
    assert stopped.experiment_id not in report.resource_pareto_ids


def test_comparison_rejects_missing_unknown_and_stopped_locked_results(
    tmp_path: Path,
) -> None:
    handoffs, locked, gold = _case(tmp_path, stopped=frozenset({"row-vision"}))
    missing = dict(locked.results)
    missing.pop("row-ocr")
    unknown = dict(locked.results)
    unknown["unknown"] = next(iter(unknown.values()))
    stopped = dict(locked.results)
    stopped["row-vision"] = next(iter(stopped.values()))

    for results in (missing, unknown, stopped):
        with pytest.raises(ComparisonError, match="locked result membership mismatch"):
            compare_handoffs(handoffs, replace(locked, results=results), gold)


def test_comparison_rejects_prediction_repeat_and_error_identity_failures(
    tmp_path: Path,
) -> None:
    handoffs, locked, gold = _case(tmp_path)
    original = locked.results["row-ocr"]
    replacements = (
        replace(
            original,
            predictions_identity=_artifact(
                "wrong-predictions",
                artifact_type="jsonl",
                version="canonical-jsonl-v1",
            ),
        ),
        replace(
            original,
            repeat_predictions_identity=_artifact(
                "different-repeat",
                artifact_type="jsonl",
                version="canonical-jsonl-v1",
            ),
        ),
        replace(
            original,
            error_assignments_identity=_artifact(
                "wrong-errors",
                artifact_type="jsonl",
                version="canonical-jsonl-v1",
            ),
        ),
    )

    for replacement in replacements:
        results = dict(locked.results)
        results["row-ocr"] = replacement
        with pytest.raises(ComparisonError, match="identity"):
            compare_handoffs(handoffs, replace(locked, results=results), gold)


def test_comparison_rejects_measurement_binding_and_reused_resource_inventory(
    tmp_path: Path,
) -> None:
    handoffs, locked, gold = _case(tmp_path)
    original = locked.results["row-ocr"]
    wrong_runtime = replace(
        original,
        measurements=original.measurements.model_copy(
            update={"runtime_identity": _artifact("wrong-runtime")}
        ),
    )
    reused_resources = replace(
        original,
        repeat_measurements=original.repeat_measurements.model_copy(
            update={
                "resource_inventory_identity": original.measurements.resource_inventory_identity
            }
        ),
    )
    wrong_resource_type = replace(
        original,
        measurements=original.measurements.model_copy(
            update={"resource_inventory_identity": _artifact("wrong-resource-type")}
        ),
    )

    for replacement, message in (
        (wrong_runtime, "measurement binding mismatch"),
        (reused_resources, "independent resource inventories"),
        (wrong_resource_type, "measurement binding mismatch"),
    ):
        results = dict(locked.results)
        results["row-ocr"] = replacement
        with pytest.raises(ComparisonError, match=message):
            compare_handoffs(handoffs, replace(locked, results=results), gold)


def test_comparison_rejects_stop_reason_on_baseline_evidence(tmp_path: Path) -> None:
    handoffs, locked, gold = _case(tmp_path)
    evidence = dict(handoffs.validation_evidence)
    evidence["accepted-baseline"] = replace(
        evidence["accepted-baseline"], stop_reason="no_pixel_gain"
    )

    with pytest.raises(ComparisonError, match="validated arm binding mismatch"):
        compare_handoffs(
            replace(handoffs, validation_evidence=evidence),
            locked,
            gold,
        )


def test_comparison_rejects_wrong_locked_row_sequence(tmp_path: Path) -> None:
    handoffs, locked, gold = _case(tmp_path)
    wrong_identity = _artifact(
        "wrong-rows",
        artifact_type="frozen-row-sequence",
        version="canonical-jsonl-v1",
    )

    with pytest.raises(ComparisonError, match="locked row-sequence identity"):
        compare_handoffs(
            handoffs,
            replace(locked, row_sequence_identity=wrong_identity),
            gold,
        )


def test_pareto_uses_complete_accuracy_risk_and_phase_matched_resource_axes(
    tmp_path: Path,
) -> None:
    handoffs, locked, gold = _case(tmp_path)
    report = compare_handoffs(handoffs, locked, gold)
    by_id = {result.experiment_id: result for result in report.results}

    assert "accepted-baseline" not in pareto_front(report.results)
    assert "row-vision" in pareto_front(report.results)
    assert "conditional-page-ocr" in pareto_front(report.results)
    assert "row-ocr" not in pareto_front(report.results)
    assert by_id["row-vision"].selective_risk is not None
    assert by_id["row-ocr"].selective_risk is not None
    assert by_id["row-vision"].selective_risk > by_id["row-ocr"].selective_risk
    assert by_id["row-vision"].measurements is not None
    assert by_id["row-ocr"].measurements is not None
    assert (
        by_id["row-vision"].measurements.end_to_end_ns < by_id["row-ocr"].measurements.end_to_end_ns
    )


def _legacy_result(
    experiment_id: str,
    *,
    basis: ResultBasis,
    disposition: LaneDisposition | None,
    resource_basis: Literal["end-to-end-method", "materialized-adapter"] | None = (
        "end-to-end-method"
    ),
) -> ExperimentResult:
    stopped = disposition is LaneDisposition.VALIDATION_STOPPED
    return ExperimentResult(
        experiment_id=experiment_id,
        result_basis=basis,
        disposition=disposition,
        stop_reason="validation_stop" if stopped else None,
        row_count=10,
        exact_rows=3,
        merchant_exact_rows=2,
        omissions=1,
        hallucinations=0,
        accepted_rows=3,
        p95_ns=None if stopped else 100,
        peak_rss_bytes=None if stopped else 1_024,
        model_bytes=None if stopped else 0,
        dependency_bytes=None if stopped else 2_048,
        deterministic=True,
        resource_basis=None if stopped else resource_basis,
    )


def _legacy_results() -> tuple[ExperimentResult, ...]:
    return (
        _legacy_result(
            "accepted-baseline",
            basis=ResultBasis.LOCKED_TEST,
            disposition=None,
            resource_basis="materialized-adapter",
        ),
        _legacy_result("conditional-page-ocr", basis=ResultBasis.LOCKED_TEST, disposition=None),
        _legacy_result("forced-page-ocr", basis=ResultBasis.LOCKED_TEST, disposition=None),
        _legacy_result(
            "row-ocr",
            basis=ResultBasis.VALIDATION_STOP,
            disposition=LaneDisposition.VALIDATION_STOPPED,
        ),
        _legacy_result(
            "row-profiles",
            basis=ResultBasis.LOCKED_TEST,
            disposition=LaneDisposition.FROZEN_ELIGIBLE,
        ),
        _legacy_result(
            "row-text",
            basis=ResultBasis.VALIDATION_STOP,
            disposition=LaneDisposition.VALIDATION_STOPPED,
        ),
        _legacy_result(
            "row-vision",
            basis=ResultBasis.VALIDATION_STOP,
            disposition=LaneDisposition.VALIDATION_STOPPED,
        ),
    )


def test_build_comparison_remains_compatible_with_policy_projection() -> None:
    report = build_comparison(_legacy_results())

    assert report.experiment_ids == _RESULT_IDS
    assert report.validation_stopped_ids == ("row-ocr", "row-text", "row-vision")


def test_build_comparison_rejects_missing_or_duplicate_result() -> None:
    complete = _legacy_results()

    with pytest.raises(ValueError, match="comparison requires exactly seven result IDs"):
        build_comparison(complete[:-1])
    with pytest.raises(ValueError, match="comparison requires exactly seven result IDs"):
        build_comparison((*complete[:-1], complete[0]))


def test_stopped_result_cannot_claim_locked_resources() -> None:
    complete = list(_legacy_results())
    stopped = complete[3].model_dump(mode="python")
    stopped.update(
        {
            "result_basis": ResultBasis.LOCKED_TEST,
            "p95_ns": 10,
            "peak_rss_bytes": 20,
            "model_bytes": 0,
            "dependency_bytes": 30,
            "resource_basis": "end-to-end-method",
        }
    )

    with pytest.raises(ValueError, match="stopped result must remain validation-only"):
        ExperimentResult.model_validate(stopped)
