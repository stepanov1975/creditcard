"""Defensive run-measurement and independent-path validation."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from experiments.row_extraction.comparison.handoff_contracts import (
    FrozenRunInputs,
    ValidatedArmBinding,
)
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.runner import RunMeasurements

from .locked_artifacts import (
    verify_cache_root,
    verify_prepared_arm_manifest,
    verify_resource_inventory,
)
from .locked_contracts import LockedArmResult, fail
from .result_catalog import MANIFEST_POLICY_BY_RESULT


def _revalidate(measurements: RunMeasurements) -> RunMeasurements:
    try:
        validated = RunMeasurements.model_validate(measurements.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        fail("invalid locked measurement")
    if (
        validated.cache_policy != "new-empty-v1"
        or validated.measurement_protocol != "row-resource-measurement-v1"
    ):
        fail("invalid locked measurement")
    return validated


def _validate_measurement(
    measurements: RunMeasurements,
    *,
    result: LockedArmResult,
    binding: ValidatedArmBinding,
    run_input: FrozenRunInputs,
    row_identity: ArtifactIdentity,
    row_count: int,
    predictions_identity: ArtifactIdentity,
) -> RunMeasurements:
    validated = _revalidate(measurements)
    expected_basis: Literal["end-to-end-method", "materialized-adapter"] = (
        "materialized-adapter"
        if result.experiment_id == "accepted-baseline"
        else "end-to-end-method"
    )
    if (
        binding.arm_manifest is None
        or validated.experiment_id != result.experiment_id
        or validated.config_id != result.config_id
        or validated.row_sequence_identity != row_identity
        or validated.split is not DatasetSplit.TEST
        or validated.row_count != row_count
        or validated.resource_basis != expected_basis
        or validated.runtime_identity != binding.runtime_identity
        or validated.runtime_identity != run_input.runtime_identity
        or validated.model_inventory_identity != binding.model_inventory
        or validated.model_inventory_identity != run_input.model_inventory
        or validated.dependency_inventory_identity != binding.dependency_inventory
        or validated.dependency_inventory_identity != run_input.dependency_inventory
        or validated.model_inventory_identity == validated.dependency_inventory_identity
        or validated.resource_inventory_identity.artifact_type != "resource-inventory"
        or validated.resource_inventory_identity.version != "row-resource-inventory-v1"
        or validated.worker_count != 1
        or validated.predictions_sha256 != predictions_identity.sha256
    ):
        fail("locked measurement binding mismatch")
    manifest_policy = MANIFEST_POLICY_BY_RESULT[result.experiment_id]
    if manifest_policy == "fixed" and (
        validated.arm_manifest_identity != binding.arm_manifest
        or validated.arm_manifest_identity != run_input.arm_manifest
    ):
        fail("locked measurement binding mismatch")
    if manifest_policy == "locked-materialized-input" and (
        validated.arm_manifest_identity != predictions_identity
        or validated.arm_manifest_identity == binding.arm_manifest
        or validated.arm_manifest_identity.artifact_type != "jsonl"
        or validated.arm_manifest_identity.version != "canonical-jsonl-v1"
    ):
        fail("locked materialized manifest binding mismatch")
    if manifest_policy == "locked-page-preparation" and (
        validated.arm_manifest_identity == binding.arm_manifest
        or validated.arm_manifest_identity.artifact_type != "jsonl"
        or validated.arm_manifest_identity.version != "canonical-jsonl-v1"
    ):
        fail("prepared arm manifest binding mismatch")
    return validated


def validate_measurement_pair(
    result: LockedArmResult,
    *,
    binding: ValidatedArmBinding,
    run_input: FrozenRunInputs,
    row_identity: ArtifactIdentity,
    row_count: int,
    expected_page_keys: frozenset[tuple[str, int]],
) -> tuple[RunMeasurements, RunMeasurements]:
    """Validate measured values, inventory bytes, and distinct run paths."""

    first = _validate_measurement(
        result.measurements,
        result=result,
        binding=binding,
        run_input=run_input,
        row_identity=row_identity,
        row_count=row_count,
        predictions_identity=result.predictions_identity,
    )
    repeat = _validate_measurement(
        result.repeat_measurements,
        result=result,
        binding=binding,
        run_input=run_input,
        row_identity=row_identity,
        row_count=row_count,
        predictions_identity=result.repeat_predictions_identity,
    )
    if result.resource_inventory_path == result.repeat_resource_inventory_path:
        fail("locked repeats require independent resource outputs")
    first_root = verify_cache_root(result.cache_root)
    repeat_root = verify_cache_root(result.repeat_cache_root)
    if first_root == repeat_root:
        fail("locked repeats require independent cache roots")
    first_inventory = verify_resource_inventory(
        result.resource_inventory_path,
        first.resource_inventory_identity,
    )
    repeat_inventory = verify_resource_inventory(
        result.repeat_resource_inventory_path,
        repeat.resource_inventory_identity,
    )
    try:
        first_output = result.resource_inventory_path.resolve(strict=True)
        repeat_output = result.repeat_resource_inventory_path.resolve(strict=True)
        first_metadata = first_output.stat()
        repeat_metadata = repeat_output.stat()
    except OSError:
        fail("resource inventory identity mismatch")
    if first_output == repeat_output or (
        first_metadata.st_dev,
        first_metadata.st_ino,
    ) == (repeat_metadata.st_dev, repeat_metadata.st_ino):
        fail("locked repeats require independent resource outputs")
    if MANIFEST_POLICY_BY_RESULT[result.experiment_id] == "locked-page-preparation":
        if first.arm_manifest_identity != repeat.arm_manifest_identity:
            fail("repeat prepared arm manifest mismatch")
        first_manifest = verify_prepared_arm_manifest(
            first.arm_manifest_identity,
            first_inventory,
            experiment_id=result.experiment_id,
            config_id=result.config_id,
            runtime_identity=binding.runtime_identity,
            expected_page_keys=expected_page_keys,
        )
        repeat_manifest = verify_prepared_arm_manifest(
            repeat.arm_manifest_identity,
            repeat_inventory,
            experiment_id=result.experiment_id,
            config_id=result.config_id,
            runtime_identity=binding.runtime_identity,
            expected_page_keys=expected_page_keys,
        )
        if first_manifest == repeat_manifest:
            fail("prepared arm manifests require independent outputs")
    return first, repeat


__all__ = ["validate_measurement_pair"]
