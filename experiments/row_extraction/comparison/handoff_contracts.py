"""Typed values shared by central handoff validation components."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FrozenRow,
    LaneDisposition,
    _FrozenModel,
)
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import MeasuredArmFactory, RunMeasurements

from .errors import ValidationErrorSummary

type RowKey = tuple[str, str]

BASELINE_IDS = frozenset(
    {
        "accepted-baseline",
        "conditional-page-ocr",
        "forced-page-ocr",
    }
)
EXPERIMENT_IDS = frozenset(
    {
        "row-ocr",
        "row-profiles",
        "row-text",
        "row-vision",
    }
)

VALIDATION_METRIC_TYPE = "row-comparison-validation-metrics"
VALIDATION_METRIC_VERSION = "row-comparison-validation-metrics-v1"
VALIDATION_MEASUREMENT_TYPE = "row-comparison-validation-measurements"
VALIDATION_MEASUREMENT_VERSION = "row-comparison-validation-measurements-v1"
VALIDATION_ERROR_TYPE = "row-comparison-error-summary"
VALIDATION_ERROR_VERSION = "row-comparison-error-summary-v1"


class HandoffError(ValueError):
    """A handoff cannot enter the locked comparison without leaking values."""


class RowIdentity(_FrozenModel):
    """One opaque fixed-row identity without any label or field value."""

    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)


@dataclass(frozen=True)
class ArtifactFile:
    """A local artifact bound to its predeclared byte identity."""

    path: Path
    identity: ArtifactIdentity


class FrozenArmFactoryLoader(Protocol):
    """Rebuild a frozen arm for a supplied immutable row sequence."""

    def __call__(
        self,
        rows: tuple[FrozenRow, ...],
        row_sequence_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory: ...


@dataclass(frozen=True)
class FrozenArmInput:
    """Loadable frozen configuration; stopped lanes never contain one."""

    arm_manifest: ArtifactFile
    factory_loader: FrozenArmFactoryLoader
    validation_replay_cache_root: Path


@dataclass(frozen=True)
class HandoffBinding:
    """Identity and validation evidence common to every arm handoff."""

    experiment_id: str
    config_id: str
    foundation_sha: str
    bundle_identity: ArtifactIdentity
    split_identity: ArtifactIdentity
    label_identity: ArtifactIdentity
    runtime_identity: ArtifactIdentity
    model_inventory: ArtifactFile
    dependency_inventory: ArtifactFile
    validation_predictions: ArtifactFile
    validation_metrics: ArtifactFile
    validation_measurements: tuple[ArtifactFile, ...]
    validation_error_summary: ArtifactFile | None


@dataclass(frozen=True)
class BaselineHandoff(HandoffBinding):
    frozen_arm: FrozenArmInput


@dataclass(frozen=True)
class LaneHandoff(HandoffBinding):
    disposition: LaneDisposition
    stop_reason: str | None
    frozen_arm: FrozenArmInput | None


@dataclass(frozen=True)
class ComparisonManifest:
    """Normalized private inputs from lane-specific handoff adapters."""

    foundation_sha: str
    bundle_identity: ArtifactIdentity
    split_identity: ArtifactIdentity
    label_identity: ArtifactIdentity
    runtime_identity: ArtifactIdentity
    validation_rows: ArtifactFile
    locked_row_ids: ArtifactFile
    baselines: Mapping[str, BaselineHandoff]
    lanes: Mapping[str, LaneHandoff]


@dataclass(frozen=True)
class FrozenRunInputs:
    """Identity-bound inputs allowed to construct one locked arm."""

    experiment_id: str
    config_id: str
    arm_manifest: ArtifactIdentity
    runtime_identity: ArtifactIdentity
    model_inventory: ArtifactIdentity
    dependency_inventory: ArtifactIdentity
    worker_count: Literal[1]
    factory_loader: FrozenArmFactoryLoader
    arm_manifest_path: Path
    model_inventory_path: Path
    dependency_inventory_path: Path


@dataclass(frozen=True)
class ValidatedArmBinding:
    experiment_id: str
    config_id: str
    runtime_identity: ArtifactIdentity
    model_inventory: ArtifactIdentity
    dependency_inventory: ArtifactIdentity
    arm_manifest: ArtifactIdentity | None


@dataclass(frozen=True)
class ValidationEvidence:
    predictions_path: Path
    predictions_identity: ArtifactIdentity
    metrics_path: Path
    metrics_identity: ArtifactIdentity
    metrics: MetricReport
    measurement_paths: tuple[Path, ...]
    measurement_identities: tuple[ArtifactIdentity, ...]
    measurements: tuple[RunMeasurements, ...]
    error_summary_path: Path | None
    error_summary_identity: ArtifactIdentity | None
    error_summary: ValidationErrorSummary | None
    stop_reason: str | None


@dataclass(frozen=True)
class ValidatedHandoffs:
    foundation_sha: str
    dispositions: Mapping[str, LaneDisposition]
    run_inputs: Mapping[str, FrozenRunInputs]
    validation_predictions: Mapping[str, Path]
    arm_bindings: Mapping[str, ValidatedArmBinding]
    validation_evidence: Mapping[str, ValidationEvidence]
    locked_row_ids: frozenset[RowKey]


__all__ = [
    "BASELINE_IDS",
    "EXPERIMENT_IDS",
    "VALIDATION_ERROR_TYPE",
    "VALIDATION_ERROR_VERSION",
    "VALIDATION_MEASUREMENT_TYPE",
    "VALIDATION_MEASUREMENT_VERSION",
    "VALIDATION_METRIC_TYPE",
    "VALIDATION_METRIC_VERSION",
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
    "RowKey",
    "ValidatedArmBinding",
    "ValidatedHandoffs",
    "ValidationEvidence",
]
