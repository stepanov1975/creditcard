"""Typed validation-run binding for normalized handoff evidence."""

from __future__ import annotations

from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.runner import RunMeasurements

from .artifact_validation import read_model
from .handoff_contracts import HandoffBinding, HandoffError


def validate_measurements(
    handoff: HandoffBinding,
    rows_identity: ArtifactIdentity,
    expected_row_count: int,
) -> tuple[RunMeasurements, ...]:
    """Require one primary run and at most one fully bound deterministic repeat."""

    artifacts = handoff.validation_measurements
    if len(artifacts) not in {1, 2} or len({artifact.path for artifact in artifacts}) != len(
        artifacts
    ):
        raise HandoffError("validation measurement set is invalid")
    frozen_arm = getattr(handoff, "frozen_arm", None)
    expected_arm_manifest = frozen_arm.arm_manifest.identity if frozen_arm is not None else None
    measurements = tuple(
        read_model(artifact, RunMeasurements, "validation measurement") for artifact in artifacts
    )
    for measurement in measurements:
        if (
            measurement.experiment_id != handoff.experiment_id
            or measurement.config_id != handoff.config_id
            or measurement.row_sequence_identity != rows_identity
            or measurement.row_count != expected_row_count
            or measurement.split is not DatasetSplit.VALIDATION
            or measurement.runtime_identity != handoff.runtime_identity
            or measurement.model_inventory_identity != handoff.model_inventory.identity
            or measurement.dependency_inventory_identity != handoff.dependency_inventory.identity
            or measurement.worker_count != 1
            or measurement.predictions_sha256 != handoff.validation_predictions.identity.sha256
            or (
                expected_arm_manifest is not None
                and measurement.arm_manifest_identity != expected_arm_manifest
            )
        ):
            raise HandoffError("validation measurement binding mismatch")
    return measurements


__all__ = ["validate_measurements"]
