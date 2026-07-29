"""Fail-closed provenance validation for locked page preparations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from experiments.row_extraction.comparison.handoff_contracts import ValidatedArmBinding
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.runner import (
    PreparationMeasurements,
    ResourceInventory,
    RunMeasurements,
)

from .locked_artifacts import (
    VerifiedRegularFile,
    read_verified_model,
    verified_resource_inventory,
    verify_cache_inventory_root,
    verify_cache_root,
    verify_prepared_arm_manifest,
)
from .locked_contracts import (
    PREPARATION_MEASUREMENT_TYPE,
    PREPARATION_MEASUREMENT_VERSION,
    LockedArmResult,
    LockedPreparationResult,
    fail,
)
from .result_catalog import MANIFEST_POLICY_BY_RESULT


@dataclass(frozen=True)
class _VerifiedPreparation:
    cache_root: Path
    arm_manifest: VerifiedRegularFile
    measurements: VerifiedRegularFile
    resource_inventory: VerifiedRegularFile


def _revalidate_measurements(value: PreparationMeasurements) -> PreparationMeasurements:
    try:
        return PreparationMeasurements.model_validate(value.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        fail("locked preparation measurement mismatch")


def _validate_preparation(
    preparation: LockedPreparationResult,
    *,
    result: LockedArmResult,
    binding: ValidatedArmBinding,
    run_measurements: RunMeasurements,
    run_inventory: ResourceInventory,
    row_identity: ArtifactIdentity,
    row_count: int,
    expected_page_keys: frozenset[tuple[str, int]],
) -> _VerifiedPreparation:
    measurements = _revalidate_measurements(preparation.measurements)
    stored_measurements, measurement_file = read_verified_model(
        preparation.measurements_path,
        preparation.measurements_identity,
        PreparationMeasurements,
        artifact_type=PREPARATION_MEASUREMENT_TYPE,
        version=PREPARATION_MEASUREMENT_VERSION,
        message="locked preparation measurement identity mismatch",
    )
    if stored_measurements != measurements:
        fail("locked preparation measurement mismatch")
    if preparation.resource_inventory_identity != measurements.resource_inventory_identity:
        fail("locked preparation resource inventory mismatch")
    inventory, inventory_file = verified_resource_inventory(
        preparation.resource_inventory_path,
        preparation.resource_inventory_identity,
    )
    try:
        measured_inventory_path = measurements.resource_inventory_path.resolve(strict=True)
        declared_inventory_path = preparation.resource_inventory_path.resolve(strict=True)
    except OSError:
        fail("locked preparation resource inventory mismatch")
    if (
        measurements.experiment_id != result.experiment_id
        or measurements.config_id != result.config_id
        or measurements.row_sequence_identity != row_identity
        or measurements.row_count != row_count
        or measurements.split is not DatasetSplit.TEST
        or measurements.cache_policy != "new-empty-v1"
        or measurements.resource_basis != "end-to-end-method"
        or measurements.worker_count != 1
        or measurements.runtime_identity != binding.runtime_identity
        or measurements.arm_manifest_identity != preparation.arm_manifest_identity
        or measurements.arm_manifest_identity != run_measurements.arm_manifest_identity
        or measurements.resource_inventory_identity != preparation.resource_inventory_identity
        or measured_inventory_path != declared_inventory_path
        or measurements.preparation_ns != run_measurements.preparation_ns
        or measurements.peak_rss_bytes > run_measurements.peak_rss_bytes
        or measurements.subprocess_count > run_measurements.subprocess_count
    ):
        fail("locked preparation measurement mismatch")
    if any(entry not in run_inventory.entries for entry in inventory.entries):
        fail("locked preparation resource inventory mismatch")
    cache_root = verify_cache_root(preparation.cache_root)
    verify_cache_inventory_root(inventory, cache_root)
    arm_manifest = verify_prepared_arm_manifest(
        preparation.arm_manifest_path,
        preparation.arm_manifest_identity,
        inventory,
        experiment_id=result.experiment_id,
        config_id=result.config_id,
        runtime_identity=binding.runtime_identity,
        expected_page_keys=expected_page_keys,
    )
    if not arm_manifest.path.is_relative_to(cache_root):
        fail("preparation cache provenance mismatch")
    return _VerifiedPreparation(
        cache_root=cache_root,
        arm_manifest=arm_manifest,
        measurements=measurement_file,
        resource_inventory=inventory_file,
    )


def _require_distinct_files(
    first: VerifiedRegularFile,
    repeat: VerifiedRegularFile,
    *,
    message: str,
) -> None:
    if first.path == repeat.path or (first.device, first.inode) == (repeat.device, repeat.inode):
        fail(message)


def validate_preparation_pair(
    result: LockedArmResult,
    *,
    binding: ValidatedArmBinding,
    first_measurements: RunMeasurements,
    repeat_measurements: RunMeasurements,
    first_inventory: ResourceInventory,
    repeat_inventory: ResourceInventory,
    first_run_cache_root: Path,
    repeat_run_cache_root: Path,
    row_identity: ArtifactIdentity,
    row_count: int,
    expected_page_keys: frozenset[tuple[str, int]],
) -> None:
    """Validate page-only preparation membership, binding, and independence."""

    page = MANIFEST_POLICY_BY_RESULT[result.experiment_id] == "locked-page-preparation"
    if not page:
        if result.preparation is not None or result.repeat_preparation is not None:
            fail("non-page arm cannot carry preparation")
        return
    if result.preparation is None or result.repeat_preparation is None:
        fail("page arm requires two locked preparations")
    if first_measurements.arm_manifest_identity != repeat_measurements.arm_manifest_identity:
        fail("repeat prepared arm manifest mismatch")
    first_declared_root = verify_cache_root(result.preparation.cache_root)
    repeat_declared_root = verify_cache_root(result.repeat_preparation.cache_root)
    if (
        first_declared_root in (repeat_declared_root, first_run_cache_root)
        or repeat_declared_root == repeat_run_cache_root
    ):
        fail("locked repeats require independent preparation cache roots")
    first = _validate_preparation(
        result.preparation,
        result=result,
        binding=binding,
        run_measurements=first_measurements,
        run_inventory=first_inventory,
        row_identity=row_identity,
        row_count=row_count,
        expected_page_keys=expected_page_keys,
    )
    repeat = _validate_preparation(
        result.repeat_preparation,
        result=result,
        binding=binding,
        run_measurements=repeat_measurements,
        run_inventory=repeat_inventory,
        row_identity=row_identity,
        row_count=row_count,
        expected_page_keys=expected_page_keys,
    )
    if first.cache_root != first_declared_root or repeat.cache_root != repeat_declared_root:
        fail("preparation cache provenance mismatch")
    _require_distinct_files(
        first.arm_manifest,
        repeat.arm_manifest,
        message="locked repeats require independent prepared arm outputs",
    )
    _require_distinct_files(
        first.measurements,
        repeat.measurements,
        message="locked repeats require independent preparation measurement outputs",
    )
    _require_distinct_files(
        first.resource_inventory,
        repeat.resource_inventory,
        message="locked repeats require independent preparation resource outputs",
    )


__all__ = ["validate_preparation_pair"]
