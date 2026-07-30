"""Typed locked-run outputs and deterministic artifact checks."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from pydantic import BaseModel, ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit, RowPrediction
from experiments.row_extraction.runner import PreparationMeasurements, ResourceSpec, RunMeasurements

from .cli_schedule import LockedRunPaths
from .cli_state import canonical_model_bytes, identity_for_bytes, write_bytes_exclusive
from .handoff_contracts import FrozenRunInputs
from .result_catalog import ResultId


class LockedExecutionError(ValueError):
    """The shared locked execution departed from its frozen schedule."""


def fail_execution(message: str) -> Never:
    raise LockedExecutionError(message)


@dataclass(frozen=True)
class PreparedPage:
    evidence_path: Path
    evidence_identity: ArtifactIdentity
    measurements: PreparationMeasurements | None


@dataclass(frozen=True)
class MeasuredLockedRun:
    experiment_id: ResultId
    config_id: str
    paths: LockedRunPaths
    predictions_identity: ArtifactIdentity
    measurements: RunMeasurements
    preparation: PreparedPage | None


def stable_bytes(path: Path, message: str) -> bytes:
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            fail_execution(message)
        payload = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except LockedExecutionError:
        raise
    except OSError:
        fail_execution(message)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        fail_execution(message)
    return payload


def read_output_model[Model: BaseModel](
    path: Path,
    model: type[Model],
    message: str,
) -> Model:
    payload = stable_bytes(path, message)
    try:
        value = model.model_validate_json(payload)
    except (ValidationError, ValueError):
        fail_execution(message)
    if payload != canonical_model_bytes(value):
        fail_execution(message)
    return value


def prediction_identity(path: Path) -> ArtifactIdentity:
    payload = stable_bytes(path, "locked predictions are invalid")
    try:
        values = tuple(RowPrediction.model_validate_json(line) for line in payload.splitlines())
    except (ValidationError, ValueError):
        fail_execution("locked predictions are invalid")
    if not values or payload != b"".join(_canonical_record_bytes(value) for value in values):
        fail_execution("locked predictions are invalid")
    return identity_for_bytes(payload, artifact_type="jsonl", version="canonical-jsonl-v1")


def assert_preparation_repeat(first: PreparedPage, second: PreparedPage) -> None:
    """Require two independently prepared page-evidence streams to be byte-identical."""

    message = "page evidence repeat mismatch"
    if (
        first.evidence_path == second.evidence_path
        or first.evidence_identity != second.evidence_identity
    ):
        fail_execution(message)
    first_payload = stable_bytes(first.evidence_path, message)
    second_payload = stable_bytes(second.evidence_path, message)
    actual = identity_for_bytes(
        first_payload,
        artifact_type=first.evidence_identity.artifact_type,
        version=first.evidence_identity.version,
    )
    if first_payload != second_payload or actual != first.evidence_identity:
        fail_execution(message)


def runtime_path(paths: LockedRunPaths) -> Path:
    return paths.run_root / "runtime-identity.json"


def write_runtime(paths: LockedRunPaths, run_input: FrozenRunInputs) -> Path:
    output = runtime_path(paths)
    write_bytes_exclusive(output, canonical_model_bytes(run_input.runtime_identity))
    return output


def assert_static_spec(
    spec: ResourceSpec,
    run_input: FrozenRunInputs,
    paths: LockedRunPaths,
) -> None:
    if (
        spec.experiment_id != run_input.experiment_id
        or spec.config_id != run_input.config_id
        or spec.runtime_identity != run_input.runtime_identity
        or spec.model_inventory_identity != run_input.model_inventory
        or spec.dependency_inventory_identity != run_input.dependency_inventory
        or spec.row_sequence_identity.artifact_type != "frozen-row-sequence"
        or spec.row_sequence_identity.version != "canonical-jsonl-v1"
        or spec.split is not DatasetSplit.TEST
        or spec.worker_count != 1
        or spec.cache_policy != "new-empty-v1"
        or spec.cache_root != paths.run_cache
        or spec.resource_inventory_output != paths.resource_inventory
    ):
        fail_execution("locked run specification binding mismatch")


__all__ = [
    "LockedExecutionError",
    "MeasuredLockedRun",
    "PreparedPage",
    "assert_preparation_repeat",
    "assert_static_spec",
    "fail_execution",
    "prediction_identity",
    "read_output_model",
    "runtime_path",
    "write_runtime",
]
