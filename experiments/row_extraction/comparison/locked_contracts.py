"""Data contracts shared by locked-comparison validation seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from experiments.row_extraction.comparison.errors import ErrorAssignment
from experiments.row_extraction.contracts import ArtifactIdentity, FrozenRow, GoldRow, RowPrediction
from experiments.row_extraction.runner import PreparationMeasurements, RunMeasurements

from .result_catalog import ResultId

type RowKey = tuple[str, str]

PREPARATION_MEASUREMENT_TYPE = "row-extraction-locked-preparation-measurement"
PREPARATION_MEASUREMENT_VERSION = "row-extraction-locked-preparation-measurement-v1"


class ComparisonError(ValueError):
    """A result set cannot enter the aggregate comparison."""


@dataclass(frozen=True)
class LockedPreparationResult:
    """Identity-bound outputs from one page-baseline preparation."""

    cache_root: Path
    arm_manifest_path: Path
    arm_manifest_identity: ArtifactIdentity
    measurements_path: Path
    measurements_identity: ArtifactIdentity
    measurements: PreparationMeasurements
    resource_inventory_path: Path
    resource_inventory_identity: ArtifactIdentity


@dataclass(frozen=True)
class LockedArmResult:
    """Two identity-bound measured runs and reviewed errors for one arm."""

    experiment_id: ResultId
    config_id: str
    predictions_path: Path
    predictions_identity: ArtifactIdentity
    resource_inventory_path: Path
    cache_root: Path
    measurements: RunMeasurements
    repeat_predictions_path: Path
    repeat_predictions_identity: ArtifactIdentity
    repeat_resource_inventory_path: Path
    repeat_cache_root: Path
    repeat_measurements: RunMeasurements
    error_assignments_path: Path
    error_assignments_identity: ArtifactIdentity
    preparation: LockedPreparationResult | None = None
    repeat_preparation: LockedPreparationResult | None = None


@dataclass(frozen=True)
class LockedResultSet:
    """Identity-bound locked rows and the exact expected arm result mapping."""

    rows_path: Path
    row_sequence_identity: ArtifactIdentity
    results: Mapping[str, LockedArmResult]


@dataclass(frozen=True)
class LockedComparisonInputs:
    expected_locked: tuple[str, ...]
    rows: tuple[FrozenRow, ...]
    row_keys: tuple[RowKey, ...]
    indexed_gold: Mapping[RowKey, GoldRow]
    ordered_gold: tuple[GoldRow, ...]


@dataclass(frozen=True)
class ValidatedLockedArm:
    """Parsed artifacts and reconstructed measurements safe for reporting."""

    predictions: tuple[RowPrediction, ...]
    assignments: tuple[ErrorAssignment, ...]
    measurements: RunMeasurements
    repeat_measurements: RunMeasurements


def fail(message: str) -> Never:
    raise ComparisonError(message)


__all__ = [
    "PREPARATION_MEASUREMENT_TYPE",
    "PREPARATION_MEASUREMENT_VERSION",
    "ComparisonError",
    "LockedArmResult",
    "LockedComparisonInputs",
    "LockedPreparationResult",
    "LockedResultSet",
    "RowKey",
    "ValidatedLockedArm",
    "fail",
]
