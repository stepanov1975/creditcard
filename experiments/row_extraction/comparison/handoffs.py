"""Orchestrate the closed baseline/four-lane handoff validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
)
from experiments.row_extraction.metrics import MetricReport

from .artifact_validation import (
    read_jsonl,
    read_model,
    validate_artifact_file,
    validate_identity,
    validate_inventories,
)
from .errors import ValidationErrorSummary
from .factory_replay import validate_factory_replay
from .handoff_contracts import (
    BASELINE_IDS,
    EXPERIMENT_IDS,
    VALIDATION_ERROR_TYPE,
    VALIDATION_ERROR_VERSION,
    VALIDATION_MEASUREMENT_TYPE,
    VALIDATION_MEASUREMENT_VERSION,
    VALIDATION_METRIC_TYPE,
    VALIDATION_METRIC_VERSION,
    ArtifactFile,
    BaselineHandoff,
    ComparisonManifest,
    FrozenArmFactoryLoader,
    FrozenArmInput,
    FrozenRunInputs,
    HandoffBinding,
    HandoffError,
    LaneHandoff,
    RowIdentity,
    RowKey,
    ValidatedArmBinding,
    ValidatedHandoffs,
    ValidationEvidence,
)
from .measurement_validation import validate_measurements
from .metric_integrity import validate_metric_report
from .result_catalog import STOP_REASON_BY_LANE, LaneId

_GIT_SHA_LENGTH = 40
_RUNTIME_TYPE = "row-runtime-manifest"
_RUNTIME_VERSION = "row-runtime-manifest-v1"
_SPLIT_TYPE = "row-split-manifest"
_SPLIT_VERSION = "row-extraction-split-v1"


def _row_key(value: FrozenRow | RowPrediction | RowIdentity) -> RowKey:
    return value.document_id, value.row_id


def _unique_row_keys(
    values: tuple[FrozenRow, ...] | tuple[RowPrediction, ...] | tuple[RowIdentity, ...],
    message: str,
) -> frozenset[RowKey]:
    keys = tuple(_row_key(value) for value in values)
    if not keys or len(keys) != len(set(keys)):
        raise HandoffError(message)
    return frozenset(keys)


def _closed_keys(values: Mapping[str, object], expected: frozenset[str]) -> None:
    keys = set(values)
    if expected - keys:
        raise HandoffError("missing required experiment handoff")
    if keys - expected:
        raise HandoffError("unknown experiment handoff")


def _validate_manifest_identities(manifest: ComparisonManifest) -> None:
    validate_identity(manifest.bundle_identity, "bundle")
    validate_identity(
        manifest.split_identity,
        "split",
        artifact_type=_SPLIT_TYPE,
        version=_SPLIT_VERSION,
    )
    validate_identity(manifest.label_identity, "label")
    validate_identity(
        manifest.runtime_identity,
        "runtime",
        artifact_type=_RUNTIME_TYPE,
        version=_RUNTIME_VERSION,
    )
    validate_artifact_file(
        manifest.validation_rows,
        "validation row",
        artifact_type="jsonl",
        version="canonical-jsonl-v1",
    )
    validate_artifact_file(
        manifest.locked_row_ids,
        "locked row identity",
        artifact_type="jsonl",
        version="canonical-jsonl-v1",
    )


def _validate_handoff_identities(handoff: HandoffBinding) -> None:
    validate_identity(handoff.bundle_identity, "bundle")
    validate_identity(
        handoff.split_identity,
        "split",
        artifact_type=_SPLIT_TYPE,
        version=_SPLIT_VERSION,
    )
    validate_identity(handoff.label_identity, "label")
    validate_identity(
        handoff.runtime_identity,
        "runtime",
        artifact_type=_RUNTIME_TYPE,
        version=_RUNTIME_VERSION,
    )
    validate_artifact_file(
        handoff.validation_predictions,
        "validation prediction",
        artifact_type="jsonl",
        version="canonical-jsonl-v1",
    )
    validate_artifact_file(
        handoff.validation_metrics,
        "validation metric",
        artifact_type=VALIDATION_METRIC_TYPE,
        version=VALIDATION_METRIC_VERSION,
    )
    if len(handoff.validation_measurements) not in {1, 2}:
        raise HandoffError("validation measurement set is invalid")
    for measurement in handoff.validation_measurements:
        validate_artifact_file(
            measurement,
            "validation measurement",
            artifact_type=VALIDATION_MEASUREMENT_TYPE,
            version=VALIDATION_MEASUREMENT_VERSION,
        )
    if handoff.validation_error_summary is not None:
        validate_artifact_file(
            handoff.validation_error_summary,
            "validation error summary",
            artifact_type=VALIDATION_ERROR_TYPE,
            version=VALIDATION_ERROR_VERSION,
        )
    frozen_arm = getattr(handoff, "frozen_arm", None)
    if frozen_arm is not None:
        validate_artifact_file(frozen_arm.arm_manifest, "frozen arm manifest")


def _validate_binding(
    manifest: ComparisonManifest,
    handoff: HandoffBinding,
    key: str,
) -> None:
    if handoff.experiment_id != key:
        raise HandoffError("experiment handoff identity mismatch")
    if (
        handoff.foundation_sha != manifest.foundation_sha
        or handoff.bundle_identity != manifest.bundle_identity
        or handoff.split_identity != manifest.split_identity
        or handoff.label_identity != manifest.label_identity
    ):
        raise HandoffError("foundation handoff identity mismatch")
    if not handoff.config_id.strip():
        raise HandoffError("configuration handoff identity mismatch")


def _validate_disposition(lane: LaneHandoff) -> None:
    if not isinstance(lane.disposition, LaneDisposition):
        raise HandoffError("invalid lane disposition")
    if lane.disposition is LaneDisposition.FROZEN_ELIGIBLE:
        if lane.stop_reason is not None or lane.frozen_arm is None:
            raise HandoffError("eligible lane requires frozen run inputs")
    elif lane.disposition is LaneDisposition.VALIDATION_STOPPED:
        if lane.frozen_arm is not None:
            raise HandoffError("stopped lane cannot have run inputs")
        if lane.stop_reason != STOP_REASON_BY_LANE[cast(LaneId, lane.experiment_id)]:
            raise HandoffError("stopped lane reason mismatch")
    else:
        raise HandoffError("invalid lane disposition")
    if lane.validation_error_summary is None:
        raise HandoffError("lane validation error summary is missing")


def _validate_predictions(
    handoff: HandoffBinding,
    expected_keys: frozenset[RowKey],
) -> None:
    predictions = read_jsonl(
        handoff.validation_predictions,
        RowPrediction,
        "validation prediction",
    )
    keys = _unique_row_keys(predictions, "validation prediction row universe mismatch")
    if keys != expected_keys:
        raise HandoffError("validation prediction row universe mismatch")
    if any(
        prediction.experiment_id != handoff.experiment_id
        or prediction.config_id != handoff.config_id
        for prediction in predictions
    ):
        raise HandoffError("validation prediction identity mismatch")


def _validated_evidence(
    handoff: HandoffBinding,
    rows_identity: ArtifactIdentity,
    expected_row_count: int,
    stop_reason: str | None,
) -> ValidationEvidence:
    metrics = read_model(
        handoff.validation_metrics,
        MetricReport,
        "validation metric",
    )
    validate_metric_report(metrics, expected_row_count)
    measurements = validate_measurements(handoff, rows_identity, expected_row_count)
    error_file = handoff.validation_error_summary
    error_summary = (
        read_model(error_file, ValidationErrorSummary, "validation error summary")
        if error_file is not None
        else None
    )
    if error_summary is not None and error_summary.row_count != expected_row_count:
        raise HandoffError("validation error summary row count mismatch")
    return ValidationEvidence(
        predictions_path=handoff.validation_predictions.path,
        predictions_identity=handoff.validation_predictions.identity,
        metrics_path=handoff.validation_metrics.path,
        metrics_identity=handoff.validation_metrics.identity,
        metrics=metrics,
        measurement_paths=tuple(value.path for value in handoff.validation_measurements),
        measurement_identities=tuple(value.identity for value in handoff.validation_measurements),
        measurements=measurements,
        error_summary_path=error_file.path if error_file is not None else None,
        error_summary_identity=error_file.identity if error_file is not None else None,
        error_summary=error_summary,
        stop_reason=stop_reason,
    )


def _arm_binding(handoff: BaselineHandoff | LaneHandoff) -> ValidatedArmBinding:
    frozen_arm = handoff.frozen_arm
    return ValidatedArmBinding(
        experiment_id=handoff.experiment_id,
        config_id=handoff.config_id,
        runtime_identity=handoff.runtime_identity,
        model_inventory=handoff.model_inventory.identity,
        dependency_inventory=handoff.dependency_inventory.identity,
        arm_manifest=(frozen_arm.arm_manifest.identity if frozen_arm is not None else None),
    )


def validate_handoffs(manifest: ComparisonManifest) -> ValidatedHandoffs:
    """Validate all controls and four dispositions before locked predictions exist."""

    if len(manifest.foundation_sha) != _GIT_SHA_LENGTH or any(
        character not in "0123456789abcdef" for character in manifest.foundation_sha
    ):
        raise HandoffError("invalid foundation identity")
    _closed_keys(manifest.baselines, BASELINE_IDS)
    _closed_keys(manifest.lanes, EXPERIMENT_IDS)
    if any(not isinstance(handoff, BaselineHandoff) for handoff in manifest.baselines.values()):
        raise HandoffError("invalid baseline handoff type")
    if any(not isinstance(handoff, LaneHandoff) for handoff in manifest.lanes.values()):
        raise HandoffError("invalid lane handoff type")
    _validate_manifest_identities(manifest)

    rows = read_jsonl(manifest.validation_rows, FrozenRow, "validation row")
    if any(row.split is not DatasetSplit.VALIDATION for row in rows):
        raise HandoffError("validation row split mismatch")
    validation_keys = _unique_row_keys(rows, "invalid validation row universe")
    locked_rows = read_jsonl(manifest.locked_row_ids, RowIdentity, "locked row identity")
    locked_keys = _unique_row_keys(locked_rows, "invalid locked row identity universe")
    if not {value[0] for value in validation_keys}.isdisjoint(value[0] for value in locked_keys):
        raise HandoffError("validation and locked document universes overlap")

    run_inputs: dict[str, FrozenRunInputs] = {}
    prediction_paths: dict[str, Path] = {}
    dispositions: dict[str, LaneDisposition] = {}
    bindings: dict[str, ValidatedArmBinding] = {}
    evidence: dict[str, ValidationEvidence] = {}
    handoffs: tuple[tuple[str, BaselineHandoff | LaneHandoff], ...] = (
        *tuple(sorted(manifest.baselines.items())),
        *tuple(sorted(manifest.lanes.items())),
    )
    for key, handoff in handoffs:
        _validate_handoff_identities(handoff)
        _validate_binding(manifest, handoff, key)
        stop_reason: str | None = None
        if isinstance(handoff, LaneHandoff):
            _validate_disposition(handoff)
            dispositions[key] = handoff.disposition
            stop_reason = handoff.stop_reason
        validate_inventories(handoff)
        _validate_predictions(handoff, validation_keys)
        evidence[key] = _validated_evidence(
            handoff,
            manifest.validation_rows.identity,
            len(rows),
            stop_reason,
        )
        prediction_paths[key] = handoff.validation_predictions.path
        bindings[key] = _arm_binding(handoff)
        if handoff.frozen_arm is not None:
            run_inputs[key] = validate_factory_replay(
                handoff,
                rows,
                manifest.validation_rows.identity,
                handoff.validation_predictions.identity,
            )

    return ValidatedHandoffs(
        foundation_sha=manifest.foundation_sha,
        dispositions=MappingProxyType(dispositions),
        run_inputs=MappingProxyType(run_inputs),
        validation_predictions=MappingProxyType(prediction_paths),
        arm_bindings=MappingProxyType(bindings),
        validation_evidence=MappingProxyType(evidence),
        locked_row_ids=locked_keys,
    )


__all__ = [
    "BASELINE_IDS",
    "EXPERIMENT_IDS",
    "ArtifactFile",
    "BaselineHandoff",
    "ComparisonManifest",
    "FrozenArmFactoryLoader",
    "FrozenArmInput",
    "FrozenRunInputs",
    "HandoffBinding",
    "HandoffError",
    "LaneHandoff",
    "RowIdentity",
    "ValidatedArmBinding",
    "ValidatedHandoffs",
    "ValidationEvidence",
    "validate_handoffs",
]
