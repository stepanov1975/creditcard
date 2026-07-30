"""Rebuild callable-bearing validated handoffs from the pinned pre-lock snapshot."""

from __future__ import annotations

from types import MappingProxyType
from typing import Never

from pydantic import BaseModel, ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import LaneDisposition
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import RunMeasurements

from .cli_manifest import LockedComparisonCliManifestV1, PinnedArtifact
from .cli_normalize import (
    NormalizedArmSnapshot,
    NormalizedProgramSnapshot,
    baseline_factory_loader,
)
from .cli_state import read_pinned_model, verified_bytes
from .errors import ValidationErrorSummary
from .handoff_contracts import (
    FrozenRunInputs,
    RowIdentity,
    ValidatedArmBinding,
    ValidatedHandoffs,
    ValidationEvidence,
)
from .profile_loader import ProfileLaneAdapter
from .result_catalog import BASELINE_ID_SET, BASELINE_IDS, LANE_IDS


class RestoreError(ValueError):
    """The normalized pre-lock snapshot no longer proves its original bindings."""


def _fail(message: str) -> Never:
    raise RestoreError(message)


def _read_jsonl[Model: BaseModel](
    artifact: PinnedArtifact,
    model: type[Model],
    message: str,
) -> tuple[Model, ...]:
    payload = verified_bytes(artifact, message)
    try:
        records = tuple(
            model.model_validate_json(line) for line in payload.splitlines(keepends=True)
        )
    except (ValidationError, ValueError):
        _fail(message)
    if not records or payload != b"".join(_canonical_record_bytes(value) for value in records):
        _fail(message)
    return records


def _evidence(value: NormalizedArmSnapshot) -> ValidationEvidence:
    verified_bytes(value.validation_predictions, "validation prediction changed")
    metrics = read_pinned_model(value.validation_metrics, MetricReport, "validation metric changed")
    measurements = tuple(
        read_pinned_model(artifact, RunMeasurements, "validation measurement changed")
        for artifact in value.validation_measurements
    )
    error = read_pinned_model(
        value.validation_error_summary,
        ValidationErrorSummary,
        "validation error summary changed",
    )
    return ValidationEvidence(
        predictions_path=value.validation_predictions.path,
        predictions_identity=value.validation_predictions.identity,
        metrics_path=value.validation_metrics.path,
        metrics_identity=value.validation_metrics.identity,
        metrics=metrics,
        measurement_paths=tuple(artifact.path for artifact in value.validation_measurements),
        measurement_identities=tuple(
            artifact.identity for artifact in value.validation_measurements
        ),
        measurements=measurements,
        error_summary_path=value.validation_error_summary.path,
        error_summary_identity=value.validation_error_summary.identity,
        error_summary=error,
        stop_reason=value.stop_reason,
    )


def _run_input(
    value: NormalizedArmSnapshot,
    cli: LockedComparisonCliManifestV1,
    profile_adapter: ProfileLaneAdapter,
) -> FrozenRunInputs:
    arm_manifest = value.arm_manifest
    if arm_manifest is None:
        _fail("eligible arm manifest is missing")
    verified_bytes(arm_manifest, "eligible arm manifest changed")
    verified_bytes(value.model_inventory, "model inventory changed")
    verified_bytes(value.dependency_inventory, "dependency inventory changed")
    if value.experiment_id == "row-profiles":
        loader = profile_adapter.factory_loader
    else:
        try:
            loader = baseline_factory_loader(cli.baselines[value.experiment_id])
        except KeyError:
            _fail("unknown eligible arm")
    return FrozenRunInputs(
        experiment_id=value.experiment_id,
        config_id=value.config_id,
        arm_manifest=arm_manifest.identity,
        runtime_identity=value.runtime_identity,
        model_inventory=value.model_inventory.identity,
        dependency_inventory=value.dependency_inventory.identity,
        worker_count=1,
        factory_loader=loader,
        arm_manifest_path=arm_manifest.path,
        model_inventory_path=value.model_inventory.path,
        dependency_inventory_path=value.dependency_inventory.path,
    )


def restore_validated_handoffs(
    cli: LockedComparisonCliManifestV1,
    snapshot: NormalizedProgramSnapshot,
    profile_adapter: ProfileLaneAdapter,
) -> ValidatedHandoffs:
    """Reconstitute the core value without a second validation factory replay."""

    expected = (*BASELINE_IDS, *LANE_IDS)
    by_id = {value.experiment_id: value for value in snapshot.arms}
    if (
        tuple(value.experiment_id for value in snapshot.arms) != expected
        or set(by_id) != set(expected)
        or snapshot.foundation_sha != cli.foundation_sha
        or snapshot.bundle_identity != cli.expected_bundle_identity
        or snapshot.split_identity != cli.expected_split_identity
        or snapshot.label_identity != cli.expected_label_identity
        or snapshot.validation_rows != cli.validation_rows
        or snapshot.locked_row_ids != cli.locked_row_ids
    ):
        _fail("normalized program membership changed")
    locked = _read_jsonl(cli.locked_row_ids, RowIdentity, "locked row IDs changed")
    locked_keys = frozenset((value.document_id, value.row_id) for value in locked)
    if len(locked_keys) != len(locked):
        _fail("locked row IDs changed")

    dispositions = {experiment_id: by_id[experiment_id].disposition for experiment_id in LANE_IDS}
    if any(value is None for value in dispositions.values()):
        _fail("lane disposition is missing")
    run_inputs = {
        experiment_id: _run_input(value, cli, profile_adapter)
        for experiment_id, value in by_id.items()
        if experiment_id in BASELINE_ID_SET or value.disposition is LaneDisposition.FROZEN_ELIGIBLE
    }
    evidence = {experiment_id: _evidence(value) for experiment_id, value in by_id.items()}
    bindings = {
        experiment_id: ValidatedArmBinding(
            experiment_id=experiment_id,
            config_id=value.config_id,
            runtime_identity=value.runtime_identity,
            model_inventory=value.model_inventory.identity,
            dependency_inventory=value.dependency_inventory.identity,
            arm_manifest=(value.arm_manifest.identity if value.arm_manifest is not None else None),
        )
        for experiment_id, value in by_id.items()
    }
    return ValidatedHandoffs(
        foundation_sha=snapshot.foundation_sha,
        dispositions=MappingProxyType(
            {key: value for key, value in dispositions.items() if value is not None}
        ),
        run_inputs=MappingProxyType(run_inputs),
        validation_predictions=MappingProxyType(
            {key: value.validation_predictions.path for key, value in by_id.items()}
        ),
        arm_bindings=MappingProxyType(bindings),
        validation_evidence=MappingProxyType(evidence),
        locked_row_ids=locked_keys,
    )


__all__ = ["RestoreError", "restore_validated_handoffs"]
