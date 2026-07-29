"""Validate the closed baseline/four-lane handoff before locked comparison."""

from __future__ import annotations

import hashlib
import math
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Never, Protocol

from pydantic import BaseModel, Field, ValidationError

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
    _FrozenModel,
)
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import (
    MeasuredArmFactory,
    ResourceInventory,
    ResourceInventoryEntry,
    RunMeasurements,
)

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

_STOP_REASONS = {
    "row-ocr": "ocr_stage_validation_failed",
    "row-profiles": "no_profile_candidate_met_validation_gate",
    "row-text": "no_text_candidate_met_validation_gate",
    "row-vision": "no_pixel_gain",
}
_GIT_SHA_LENGTH = 40


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
    ) -> MeasuredArmFactory: ...


@dataclass(frozen=True)
class FrozenArmInput:
    """Loadable frozen configuration; stopped lanes never contain one."""

    arm_manifest: ArtifactFile
    factory_loader: FrozenArmFactoryLoader


@dataclass(frozen=True)
class BaselineHandoff:
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
    validation_measurements: ArtifactFile
    frozen_arm: FrozenArmInput


@dataclass(frozen=True)
class LaneHandoff:
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
    validation_measurements: ArtifactFile
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
class ValidatedHandoffs:
    foundation_sha: str
    dispositions: Mapping[str, LaneDisposition]
    run_inputs: Mapping[str, FrozenRunInputs]
    validation_predictions: Mapping[str, Path]
    locked_row_ids: frozenset[RowKey]


type _Handoff = BaselineHandoff | LaneHandoff


def _fail(message: str) -> Never:
    raise HandoffError(message)


def _validated_identity(identity: ArtifactIdentity, message: str) -> ArtifactIdentity:
    try:
        return ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail(message)


def _file_content(artifact: ArtifactFile, message: str) -> bytes:
    try:
        expected = _validated_identity(artifact.identity, message)
        before = artifact.path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or artifact.path.is_symlink():
            _fail(message)
        digest = hashlib.sha256()
        content = bytearray()
        with artifact.path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                content.extend(block)
        after = artifact.path.stat(follow_symlinks=False)
    except HandoffError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        _fail(message)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if not stable or expected.byte_size != len(content) or expected.sha256 != digest.hexdigest():
        _fail(message)
    return bytes(content)


def _read_model[Model: BaseModel](
    artifact: ArtifactFile,
    model: type[Model],
    message: str,
) -> Model:
    content = _file_content(artifact, message)
    try:
        return model.model_validate_json(content)
    except (TypeError, ValidationError, ValueError):
        _fail(message)


def _read_jsonl[Model: BaseModel](
    artifact: ArtifactFile,
    model: type[Model],
    message: str,
) -> tuple[Model, ...]:
    content = _file_content(artifact, message)
    try:
        return tuple(model.model_validate_json(line) for line in content.splitlines())
    except (TypeError, ValidationError, ValueError):
        _fail(message)


def _row_key(value: FrozenRow | RowPrediction | RowIdentity) -> RowKey:
    return value.document_id, value.row_id


def _unique_row_keys(
    values: tuple[FrozenRow, ...] | tuple[RowPrediction, ...] | tuple[RowIdentity, ...],
    message: str,
) -> frozenset[RowKey]:
    keys = tuple(_row_key(value) for value in values)
    if not keys or len(keys) != len(set(keys)):
        _fail(message)
    return frozenset(keys)


def _verify_resource_entry(entry: ResourceInventoryEntry, message: str) -> None:
    try:
        before = entry.resolved_path.stat(follow_symlinks=False)
        if entry.resolved_path.is_symlink() or not stat.S_ISREG(before.st_mode):
            _fail(message)
        digest = hashlib.sha256()
        byte_size = 0
        with entry.resolved_path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                byte_size += len(block)
        after = entry.resolved_path.stat(follow_symlinks=False)
    except HandoffError:
        raise
    except OSError:
        _fail(message)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or entry.device != after.st_dev
        or entry.inode != after.st_ino
        or entry.byte_size != byte_size
        or entry.sha256 != digest.hexdigest()
    ):
        _fail(message)


def _read_inventory(
    artifact: ArtifactFile,
    category: Literal["model", "dependency"],
) -> ResourceInventory:
    message = f"invalid {category} inventory"
    content = _file_content(artifact, message)
    try:
        inventory = ResourceInventory.model_validate_json(content)
    except (TypeError, ValidationError, ValueError):
        _fail(message)
    canonical = _canonical_json_value_content(inventory.model_dump(mode="json")) + b"\n"
    expected_entries = tuple(
        sorted(
            inventory.entries,
            key=lambda entry: (
                entry.category,
                str(entry.resolved_path),
                entry.sha256,
            ),
        )
    )
    if (
        artifact.identity.artifact_type != "resource-inventory"
        or artifact.identity.version != "row-resource-inventory-v1"
        or content != canonical
        or inventory.entries != expected_entries
        or any(entry.category != category for entry in inventory.entries)
        or (category == "dependency" and not inventory.entries)
    ):
        _fail(message)
    for entry in inventory.entries:
        _verify_resource_entry(entry, message)
    return inventory


def _validate_inventories(handoff: _Handoff) -> None:
    if (
        handoff.model_inventory.path == handoff.dependency_inventory.path
        or handoff.model_inventory.identity == handoff.dependency_inventory.identity
    ):
        _fail("model and dependency inventories overlap")
    model = _read_inventory(handoff.model_inventory, "model")
    dependency = _read_inventory(handoff.dependency_inventory, "dependency")
    model_paths = {entry.resolved_path for entry in model.entries}
    dependency_paths = {entry.resolved_path for entry in dependency.entries}
    model_inodes = {(entry.device, entry.inode) for entry in model.entries}
    dependency_inodes = {(entry.device, entry.inode) for entry in dependency.entries}
    if not model_paths.isdisjoint(dependency_paths) or not model_inodes.isdisjoint(
        dependency_inodes
    ):
        _fail("model and dependency inventories overlap")


def _validate_binding(manifest: ComparisonManifest, handoff: _Handoff, key: str) -> None:
    if handoff.experiment_id != key:
        _fail("experiment handoff identity mismatch")
    if (
        handoff.foundation_sha != manifest.foundation_sha
        or handoff.bundle_identity != manifest.bundle_identity
        or handoff.split_identity != manifest.split_identity
        or handoff.label_identity != manifest.label_identity
    ):
        _fail("foundation handoff identity mismatch")
    if handoff.runtime_identity != manifest.runtime_identity:
        _fail("runtime handoff identity mismatch")
    if not handoff.config_id.strip():
        _fail("configuration handoff identity mismatch")


def _validate_disposition(lane: LaneHandoff) -> None:
    if lane.disposition is LaneDisposition.FROZEN_ELIGIBLE:
        if lane.stop_reason is not None or lane.frozen_arm is None:
            _fail("eligible lane requires frozen run inputs")
        return
    if lane.frozen_arm is not None:
        _fail("stopped lane cannot have run inputs")
    if lane.stop_reason != _STOP_REASONS[lane.experiment_id]:
        _fail("stopped lane reason mismatch")


def _validate_measurements(
    handoff: _Handoff,
    rows_identity: ArtifactIdentity,
    expected_row_count: int,
    predictions_identity: ArtifactIdentity,
) -> None:
    metrics = _read_model(
        handoff.validation_metrics,
        MetricReport,
        "invalid validation metric artifact",
    )
    measurements = _read_model(
        handoff.validation_measurements,
        RunMeasurements,
        "invalid validation measurement artifact",
    )
    expected_arm_manifest = (
        handoff.frozen_arm.arm_manifest.identity if handoff.frozen_arm is not None else None
    )
    if metrics.row_count != expected_row_count:
        _fail("validation metrics are incomplete")
    if (
        measurements.experiment_id != handoff.experiment_id
        or measurements.config_id != handoff.config_id
        or measurements.row_sequence_identity != rows_identity
        or measurements.row_count != expected_row_count
        or measurements.split is not DatasetSplit.VALIDATION
        or measurements.runtime_identity != handoff.runtime_identity
        or measurements.model_inventory_identity != handoff.model_inventory.identity
        or measurements.dependency_inventory_identity != handoff.dependency_inventory.identity
        or measurements.worker_count != 1
        or measurements.predictions_sha256 != predictions_identity.sha256
        or (
            expected_arm_manifest is not None
            and measurements.arm_manifest_identity != expected_arm_manifest
        )
    ):
        _fail("validation measurement binding mismatch")


def _factory_property(factory: object, name: str) -> object:
    try:
        return getattr(factory, name)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _fail("frozen factory identity mismatch")


def _validate_factory(
    handoff: _Handoff,
    rows: tuple[FrozenRow, ...],
    rows_identity: ArtifactIdentity,
    prediction_identity: ArtifactIdentity,
) -> FrozenRunInputs:
    frozen_arm = handoff.frozen_arm
    if frozen_arm is None:
        _fail("eligible lane requires frozen run inputs")
    _file_content(frozen_arm.arm_manifest, "invalid frozen arm manifest")
    try:
        factory = frozen_arm.factory_loader(rows, rows_identity)
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail("frozen factory loader failed")
    resource_basis = (
        "materialized-adapter"
        if handoff.experiment_id == "accepted-baseline"
        else "end-to-end-method"
    )
    actual = (
        _factory_property(factory, "experiment_id"),
        _factory_property(factory, "config_id"),
        _factory_property(factory, "row_sequence_identity"),
        _factory_property(factory, "expected_row_count"),
        _factory_property(factory, "split"),
        _factory_property(factory, "arm_manifest_identity"),
        _factory_property(factory, "runtime_identity"),
        _factory_property(factory, "model_inventory_identity"),
        _factory_property(factory, "dependency_inventory_identity"),
        _factory_property(factory, "worker_count"),
        _factory_property(factory, "resource_basis"),
    )
    expected = (
        handoff.experiment_id,
        handoff.config_id,
        rows_identity,
        len(rows),
        DatasetSplit.VALIDATION,
        frozen_arm.arm_manifest.identity,
        handoff.runtime_identity,
        handoff.model_inventory.identity,
        handoff.dependency_inventory.identity,
        1,
        resource_basis,
    )
    if actual != expected:
        _fail("frozen factory identity mismatch")
    try:
        arm = factory.build()
        digest = hashlib.sha256()
        byte_size = 0
        replay_keys: list[RowKey] = []
        for row in rows:
            prediction = RowPrediction.model_validate(arm.predict(row).model_dump(mode="python"))
            if (
                prediction.experiment_id != handoff.experiment_id
                or prediction.config_id != handoff.config_id
            ):
                _fail("validation prediction replay mismatch")
            replay_keys.append(_row_key(prediction))
            content = _canonical_record_bytes(prediction)
            digest.update(content)
            byte_size += len(content)
    except HandoffError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValidationError, ValueError):
        _fail("validation prediction replay mismatch")
    if (
        len(replay_keys) != len(set(replay_keys))
        or digest.hexdigest() != prediction_identity.sha256
        or byte_size != prediction_identity.byte_size
    ):
        _fail("validation prediction replay mismatch")
    return FrozenRunInputs(
        arm_manifest=frozen_arm.arm_manifest.identity,
        runtime_identity=handoff.runtime_identity,
        model_inventory=handoff.model_inventory.identity,
        dependency_inventory=handoff.dependency_inventory.identity,
        worker_count=1,
        factory_loader=frozen_arm.factory_loader,
        arm_manifest_path=frozen_arm.arm_manifest.path,
        model_inventory_path=handoff.model_inventory.path,
        dependency_inventory_path=handoff.dependency_inventory.path,
    )


def _validate_predictions(
    handoff: _Handoff,
    expected_keys: frozenset[RowKey],
) -> tuple[RowPrediction, ...]:
    predictions = _read_jsonl(
        handoff.validation_predictions,
        RowPrediction,
        "invalid validation prediction artifact",
    )
    keys = _unique_row_keys(predictions, "validation prediction row universe mismatch")
    if keys != expected_keys:
        _fail("validation prediction row universe mismatch")
    if any(
        prediction.experiment_id != handoff.experiment_id
        or prediction.config_id != handoff.config_id
        for prediction in predictions
    ) or any(
        prediction.exact_row_confidence is not None
        and not math.isfinite(prediction.exact_row_confidence)
        for prediction in predictions
    ):
        _fail("validation prediction identity mismatch")
    return predictions


def _closed_keys(
    values: Mapping[str, object],
    expected: frozenset[str],
) -> None:
    keys = set(values)
    missing = expected - keys
    unknown = keys - expected
    if missing:
        _fail("missing required experiment handoff")
    if unknown:
        _fail("unknown experiment handoff")


def validate_handoffs(manifest: ComparisonManifest) -> ValidatedHandoffs:
    """Validate all controls and four dispositions before any locked predictions exist."""

    if len(manifest.foundation_sha) != _GIT_SHA_LENGTH or any(
        character not in "0123456789abcdef" for character in manifest.foundation_sha
    ):
        _fail("invalid foundation identity")
    _closed_keys(manifest.baselines, BASELINE_IDS)
    _closed_keys(manifest.lanes, EXPERIMENT_IDS)
    if any(not isinstance(handoff, BaselineHandoff) for handoff in manifest.baselines.values()):
        _fail("invalid baseline handoff type")
    if any(not isinstance(handoff, LaneHandoff) for handoff in manifest.lanes.values()):
        _fail("invalid lane handoff type")

    rows = _read_jsonl(
        manifest.validation_rows,
        FrozenRow,
        "invalid validation row artifact",
    )
    if any(row.split is not DatasetSplit.VALIDATION for row in rows):
        _fail("validation row split mismatch")
    validation_keys = _unique_row_keys(rows, "invalid validation row universe")
    locked_rows = _read_jsonl(
        manifest.locked_row_ids,
        RowIdentity,
        "invalid locked row identity artifact",
    )
    locked_keys = _unique_row_keys(locked_rows, "invalid locked row identity universe")
    validation_documents = {document_id for document_id, _ in validation_keys}
    locked_documents = {document_id for document_id, _ in locked_keys}
    if not validation_documents.isdisjoint(locked_documents):
        _fail("validation and locked document universes overlap")

    run_inputs: dict[str, FrozenRunInputs] = {}
    prediction_paths: dict[str, Path] = {}
    dispositions: dict[str, LaneDisposition] = {}
    handoffs: tuple[tuple[str, _Handoff], ...] = (
        *tuple(sorted(manifest.baselines.items())),
        *tuple(sorted(manifest.lanes.items())),
    )
    for key, handoff in handoffs:
        _validate_binding(manifest, handoff, key)
        if isinstance(handoff, LaneHandoff):
            _validate_disposition(handoff)
            dispositions[key] = handoff.disposition
        _validate_inventories(handoff)
        _validate_predictions(handoff, validation_keys)
        _validate_measurements(
            handoff,
            manifest.validation_rows.identity,
            len(rows),
            handoff.validation_predictions.identity,
        )
        prediction_paths[key] = handoff.validation_predictions.path
        if handoff.frozen_arm is not None:
            run_inputs[key] = _validate_factory(
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
    "HandoffError",
    "LaneHandoff",
    "RowIdentity",
    "ValidatedHandoffs",
    "validate_handoffs",
]
