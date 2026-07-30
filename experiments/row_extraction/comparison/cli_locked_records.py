"""Durable contracts and canonical I/O for completed locked outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never, Self

from pydantic import Field, ValidationError, model_validator

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel
from experiments.row_extraction.runner import PreparationMeasurements

from .cli_execution_support import MeasuredLockedRun
from .cli_locked import LockedInputs
from .cli_manifest import LockedComparisonCliManifestV1, PinnedArtifact
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    stable_regular_bytes,
    write_bytes_exclusive,
)
from .cli_state import write_identified_model as write_locked_model
from .locked_contracts import (
    PREPARATION_MEASUREMENT_TYPE,
    PREPARATION_MEASUREMENT_VERSION,
)
from .reporting import ComparisonReport
from .result_catalog import ResultId

LOCKED_RESULT_IDS: tuple[ResultId, ...] = (
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
    "row-profiles",
)


class LockedComparisonStageError(ValueError):
    """The locked outputs cannot form the fixed seven-result comparison."""


def fail_locked_stage(message: str) -> Never:
    raise LockedComparisonStageError(message)


class LockedPreparationRecordV1(_FrozenModel):
    cache_root: Path
    arm_manifest: PinnedArtifact
    measurements_artifact: PinnedArtifact
    measurements: PreparationMeasurements
    resource_inventory_path: Path
    resource_inventory_identity: ArtifactIdentity


class LockedRunRecordV1(_FrozenModel):
    experiment_id: ResultId
    config_id: str = Field(min_length=1)
    predictions: PinnedArtifact
    measurements: PinnedArtifact
    resource_inventory_path: Path
    resource_inventory_identity: ArtifactIdentity
    cache_root: Path
    preparation: LockedPreparationRecordV1 | None


class LockedArmRecordV1(_FrozenModel):
    experiment_id: ResultId
    first: LockedRunRecordV1
    repeat: LockedRunRecordV1
    error_assignments: PinnedArtifact

    @model_validator(mode="after")
    def same_arm_distinct_outputs(self) -> Self:
        if (
            self.first.experiment_id != self.experiment_id
            or self.repeat.experiment_id != self.experiment_id
            or self.first.config_id != self.repeat.config_id
            or self.first.predictions.identity != self.repeat.predictions.identity
            or self.first.predictions.path == self.repeat.predictions.path
            or self.first.measurements.path == self.repeat.measurements.path
            or self.first.resource_inventory_path == self.repeat.resource_inventory_path
            or self.first.cache_root == self.repeat.cache_root
        ):
            raise ValueError("locked arm record is inconsistent")
        page = self.experiment_id in {"conditional-page-ocr", "forced-page-ocr"}
        if page != (self.first.preparation is not None) or page != (
            self.repeat.preparation is not None
        ):
            raise ValueError("locked page evidence membership mismatch")
        return self


class LockedArtifactsManifestV1(_FrozenModel):
    version: Literal["row-comparison-locked-artifacts-v1"]
    row_sequence_identity: ArtifactIdentity
    arms: tuple[LockedArmRecordV1, ...]

    @model_validator(mode="after")
    def exact_schedule(self) -> Self:
        if tuple(value.experiment_id for value in self.arms) != LOCKED_RESULT_IDS:
            raise ValueError("locked result schedule mismatch")
        return self


class LockedCompletionReceiptV1(_FrozenModel):
    version: Literal["row-comparison-locked-completion-v1"]
    comparison_manifest_identity: ArtifactIdentity
    validation_receipt_identity: ArtifactIdentity
    cascade_policy_identity: ArtifactIdentity
    locked_artifacts_identity: ArtifactIdentity
    comparison_report_identity: ArtifactIdentity
    row_sequence_identity: ArtifactIdentity
    locked_result_ids: tuple[ResultId, ...]
    validation_stopped_ids: tuple[ResultId, ...]
    run_count: Literal[8]
    page_preparation_count: Literal[4]
    deterministic_result_count: Literal[4]
    test_accessed: Literal[True]


@dataclass(frozen=True)
class LockedProducts:
    cli: LockedComparisonCliManifestV1
    locked_inputs: LockedInputs
    artifacts: LockedArtifactsManifestV1
    artifacts_identity: ArtifactIdentity
    report: ComparisonReport
    report_identity: ArtifactIdentity
    receipt: LockedCompletionReceiptV1
    receipt_identity: ArtifactIdentity


def write_locked_jsonl(
    path: Path,
    values: tuple[_FrozenModel, ...],
    *,
    artifact_type: str = "jsonl",
) -> ArtifactIdentity:
    payload = b"".join(_canonical_record_bytes(value) for value in values)
    write_bytes_exclusive(path, payload)
    return identity_for_bytes(payload, artifact_type=artifact_type, version="canonical-jsonl-v1")


def read_locked_model[Model: _FrozenModel](
    path: Path,
    model: type[Model],
    message: str,
) -> Model:
    try:
        payload = stable_regular_bytes(path, message)
        value = model.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        fail_locked_stage(message)
    if payload != canonical_model_bytes(value):
        fail_locked_stage(message)
    return value


def read_locked_identity(path: Path, message: str) -> ArtifactIdentity:
    return read_locked_model(path, ArtifactIdentity, message)


def identified_run(value: MeasuredLockedRun) -> LockedRunRecordV1:
    measurement_payload = canonical_model_bytes(value.measurements)
    measurement_identity = identity_for_bytes(
        measurement_payload,
        artifact_type="row-extraction-locked-measurement",
        version="row-extraction-locked-measurement-v1",
    )
    if (
        stable_regular_bytes(
            value.paths.measurements,
            "locked measurement publication changed",
        )
        != measurement_payload
    ):
        fail_locked_stage("locked measurement publication changed")
    page = value.preparation
    preparation = None
    if page is not None:
        paths = value.paths
        if (
            page.measurements is None
            or paths.preparation_cache is None
            or paths.preparation_measurements is None
            or paths.preparation_resource_inventory is None
        ):
            fail_locked_stage("locked preparation record is incomplete")
        preparation_payload = canonical_model_bytes(page.measurements)
        preparation_identity = identity_for_bytes(
            preparation_payload,
            artifact_type=PREPARATION_MEASUREMENT_TYPE,
            version=PREPARATION_MEASUREMENT_VERSION,
        )
        if (
            stable_regular_bytes(
                paths.preparation_measurements,
                "locked preparation measurement changed",
            )
            != preparation_payload
        ):
            fail_locked_stage("locked preparation measurement changed")
        preparation = LockedPreparationRecordV1(
            cache_root=paths.preparation_cache,
            arm_manifest=PinnedArtifact(
                path=page.evidence_path,
                identity=page.evidence_identity,
            ),
            measurements_artifact=PinnedArtifact(
                path=paths.preparation_measurements,
                identity=preparation_identity,
            ),
            measurements=page.measurements,
            resource_inventory_path=paths.preparation_resource_inventory,
            resource_inventory_identity=page.measurements.resource_inventory_identity,
        )
    return LockedRunRecordV1(
        experiment_id=value.experiment_id,
        config_id=value.config_id,
        predictions=PinnedArtifact(
            path=value.paths.predictions,
            identity=value.predictions_identity,
        ),
        measurements=PinnedArtifact(
            path=value.paths.measurements,
            identity=measurement_identity,
        ),
        resource_inventory_path=value.paths.resource_inventory,
        resource_inventory_identity=value.measurements.resource_inventory_identity,
        cache_root=value.paths.run_cache,
        preparation=preparation,
    )


__all__ = [
    "LOCKED_RESULT_IDS",
    "LockedArtifactsManifestV1",
    "LockedComparisonStageError",
    "LockedCompletionReceiptV1",
    "LockedPreparationRecordV1",
    "LockedProducts",
    "fail_locked_stage",
    "identified_run",
    "read_locked_identity",
    "read_locked_model",
    "write_locked_jsonl",
    "write_locked_model",
]
