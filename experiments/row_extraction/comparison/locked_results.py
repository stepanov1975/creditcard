"""Identity and measurement validation for locked comparison artifacts."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never, cast

from pydantic import ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.comparison.errors import ErrorAssignment
from experiments.row_extraction.comparison.handoff_contracts import (
    BASELINE_IDS,
    EXPERIMENT_IDS,
    FrozenRunInputs,
    ValidatedArmBinding,
    ValidatedHandoffs,
)
from experiments.row_extraction.comparison.reporting import (
    BASELINE_IDS as REPORT_BASELINE_IDS,
)
from experiments.row_extraction.comparison.reporting import RESULT_IDS
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    GoldRow,
    LaneDisposition,
    RowPrediction,
)
from experiments.row_extraction.runner import RunMeasurements

_STOP_REASONS = {
    "row-ocr": "ocr_stage_validation_failed",
    "row-profiles": "no_profile_candidate_met_validation_gate",
    "row-text": "no_text_candidate_met_validation_gate",
    "row-vision": "no_pixel_gain",
}
_ROW_SEQUENCE_TYPE = "frozen-row-sequence"
_JSONL_TYPE = "jsonl"
_JSONL_VERSION = "canonical-jsonl-v1"

type _Record = FrozenRow | RowPrediction | ErrorAssignment
type RowKey = tuple[str, str]


class ComparisonError(ValueError):
    """A result set cannot enter the aggregate comparison."""


@dataclass(frozen=True)
class LockedArmResult:
    """Two measured prediction runs plus reviewed error assignments for one arm."""

    experiment_id: str
    config_id: str
    predictions_path: Path
    predictions_identity: ArtifactIdentity
    measurements: RunMeasurements
    repeat_predictions_path: Path
    repeat_predictions_identity: ArtifactIdentity
    repeat_measurements: RunMeasurements
    error_assignments_path: Path
    error_assignments_identity: ArtifactIdentity


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


def fail(message: str) -> Never:
    raise ComparisonError(message)


def _validated_identity(
    identity: ArtifactIdentity,
    *,
    artifact_type: str,
    version: str,
    message: str,
) -> ArtifactIdentity:
    try:
        validated = ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        fail(message)
    if validated.artifact_type != artifact_type or validated.version != version:
        fail(message)
    return validated


def _read_verified_jsonl[Record: _Record](
    path: Path,
    identity: ArtifactIdentity,
    model: type[Record],
    *,
    artifact_type: str,
    message: str,
) -> tuple[Record, ...]:
    expected = _validated_identity(
        identity,
        artifact_type=artifact_type,
        version=_JSONL_VERSION,
        message=message,
    )
    digest = hashlib.sha256()
    byte_size = 0
    records: list[Record] = []
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            fail(message)
        with path.open("rb") as source:
            for line in source:
                digest.update(line)
                byte_size += len(line)
                record = model.model_validate_json(line)
                if line != _canonical_record_bytes(record):
                    fail(message)
                records.append(cast(Record, record))
        after = path.stat(follow_symlinks=False)
    except ComparisonError:
        raise
    except (AttributeError, OSError, TypeError, ValidationError, ValueError):
        fail(message)
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
    if not stable or byte_size != expected.byte_size or digest.hexdigest() != expected.sha256:
        fail(message)
    return tuple(records)


def row_key(value: FrozenRow | GoldRow | RowPrediction) -> RowKey:
    return value.document_id, value.row_id


def _index_gold(gold: Sequence[GoldRow]) -> dict[RowKey, GoldRow]:
    indexed: dict[RowKey, GoldRow] = {}
    try:
        for value in gold:
            validated = GoldRow.model_validate(value.model_dump(mode="python"))
            key = row_key(validated)
            if key in indexed:
                fail("invalid locked gold input")
            indexed[key] = validated
    except ComparisonError:
        raise
    except (AttributeError, TypeError, ValidationError, ValueError):
        fail("invalid locked gold input")
    return indexed


def _validate_run_input(
    run_input: FrozenRunInputs,
    binding: ValidatedArmBinding,
) -> None:
    if (
        binding.arm_manifest is None
        or run_input.experiment_id != binding.experiment_id
        or run_input.config_id != binding.config_id
        or run_input.arm_manifest != binding.arm_manifest
        or run_input.runtime_identity != binding.runtime_identity
        or run_input.model_inventory != binding.model_inventory
        or run_input.dependency_inventory != binding.dependency_inventory
        or run_input.worker_count != 1
    ):
        fail("validated run-input binding mismatch")


def _expected_locked(handoffs: ValidatedHandoffs) -> tuple[str, ...]:
    expected_ids = set(RESULT_IDS)
    if (
        set(BASELINE_IDS) != set(REPORT_BASELINE_IDS)
        or set(EXPERIMENT_IDS) != expected_ids - set(REPORT_BASELINE_IDS)
        or set(handoffs.dispositions) != set(EXPERIMENT_IDS)
        or set(handoffs.arm_bindings) != expected_ids
        or set(handoffs.validation_evidence) != expected_ids
    ):
        fail("validated handoff membership mismatch")
    expected = set(BASELINE_IDS)
    for experiment_id in EXPERIMENT_IDS:
        disposition = handoffs.dispositions[experiment_id]
        binding = handoffs.arm_bindings[experiment_id]
        evidence = handoffs.validation_evidence[experiment_id]
        if disposition is LaneDisposition.FROZEN_ELIGIBLE:
            expected.add(experiment_id)
            if binding.arm_manifest is None or evidence.stop_reason is not None:
                fail("eligible handoff binding mismatch")
        elif (
            disposition is not LaneDisposition.VALIDATION_STOPPED
            or binding.arm_manifest is not None
            or evidence.stop_reason != _STOP_REASONS[experiment_id]
            or evidence.error_summary is None
        ):
            fail("stopped handoff binding mismatch")
    if set(handoffs.run_inputs) != expected:
        fail("validated run-input membership mismatch")
    for experiment_id in RESULT_IDS:
        binding = handoffs.arm_bindings[experiment_id]
        evidence = handoffs.validation_evidence[experiment_id]
        if (
            binding.experiment_id != experiment_id
            or not binding.config_id.strip()
            or (experiment_id in BASELINE_IDS and evidence.stop_reason is not None)
        ):
            fail("validated arm binding mismatch")
        if experiment_id in expected:
            _validate_run_input(handoffs.run_inputs[experiment_id], binding)
    return tuple(experiment_id for experiment_id in RESULT_IDS if experiment_id in expected)


def read_locked_rows(locked_results: LockedResultSet) -> tuple[FrozenRow, ...]:
    return _read_verified_jsonl(
        locked_results.rows_path,
        locked_results.row_sequence_identity,
        FrozenRow,
        artifact_type=_ROW_SEQUENCE_TYPE,
        message="locked row-sequence identity mismatch",
    )


def validate_locked_inputs(
    handoffs: ValidatedHandoffs,
    locked_results: LockedResultSet,
    gold: Sequence[GoldRow],
) -> LockedComparisonInputs:
    expected_locked = _expected_locked(handoffs)
    if set(locked_results.results) != set(expected_locked):
        fail("locked result membership mismatch")
    rows = read_locked_rows(locked_results)
    row_keys = tuple(row_key(row) for row in rows)
    if (
        not rows
        or len(row_keys) != len(set(row_keys))
        or any(row.split is not DatasetSplit.TEST for row in rows)
        or frozenset(row_keys) != handoffs.locked_row_ids
    ):
        fail("locked row-sequence identity mismatch")
    indexed_gold = _index_gold(gold)
    if set(indexed_gold) != set(row_keys):
        fail("locked gold identity mismatch")
    return LockedComparisonInputs(
        expected_locked=expected_locked,
        rows=rows,
        row_keys=row_keys,
        indexed_gold=indexed_gold,
        ordered_gold=tuple(indexed_gold[key] for key in row_keys),
    )


def _validate_measurement(
    measurements: RunMeasurements,
    *,
    result: LockedArmResult,
    binding: ValidatedArmBinding,
    run_input: FrozenRunInputs,
    row_identity: ArtifactIdentity,
    row_count: int,
    predictions_identity: ArtifactIdentity,
) -> None:
    expected_basis: Literal["end-to-end-method", "materialized-adapter"] = (
        "materialized-adapter"
        if result.experiment_id == "accepted-baseline"
        else "end-to-end-method"
    )
    if (
        binding.arm_manifest is None
        or measurements.experiment_id != result.experiment_id
        or measurements.config_id != result.config_id
        or measurements.row_sequence_identity != row_identity
        or measurements.split is not DatasetSplit.TEST
        or measurements.row_count != row_count
        or measurements.resource_basis != expected_basis
        or measurements.arm_manifest_identity != binding.arm_manifest
        or measurements.arm_manifest_identity != run_input.arm_manifest
        or measurements.runtime_identity != binding.runtime_identity
        or measurements.runtime_identity != run_input.runtime_identity
        or measurements.model_inventory_identity != binding.model_inventory
        or measurements.model_inventory_identity != run_input.model_inventory
        or measurements.dependency_inventory_identity != binding.dependency_inventory
        or measurements.dependency_inventory_identity != run_input.dependency_inventory
        or measurements.model_inventory_identity == measurements.dependency_inventory_identity
        or measurements.resource_inventory_identity.artifact_type != "resource-inventory"
        or measurements.resource_inventory_identity.version != "row-resource-inventory-v1"
        or measurements.worker_count != 1
        or measurements.predictions_sha256 != predictions_identity.sha256
    ):
        fail("locked measurement binding mismatch")


def validate_locked_arm(
    result: LockedArmResult,
    *,
    handoffs: ValidatedHandoffs,
    locked_results: LockedResultSet,
    row_count: int,
) -> tuple[tuple[RowPrediction, ...], tuple[ErrorAssignment, ...]]:
    binding = handoffs.arm_bindings[result.experiment_id]
    run_input = handoffs.run_inputs[result.experiment_id]
    if result.experiment_id != binding.experiment_id or result.config_id != binding.config_id:
        fail("locked result binding mismatch")
    if (
        len(
            {
                result.predictions_path,
                result.repeat_predictions_path,
                result.error_assignments_path,
            }
        )
        != 3
    ):
        fail("locked result paths must be distinct")
    predictions = _read_verified_jsonl(
        result.predictions_path,
        result.predictions_identity,
        RowPrediction,
        artifact_type=_JSONL_TYPE,
        message="locked prediction identity mismatch",
    )
    repeats = _read_verified_jsonl(
        result.repeat_predictions_path,
        result.repeat_predictions_identity,
        RowPrediction,
        artifact_type=_JSONL_TYPE,
        message="locked repeat prediction identity mismatch",
    )
    assignments = _read_verified_jsonl(
        result.error_assignments_path,
        result.error_assignments_identity,
        ErrorAssignment,
        artifact_type=_JSONL_TYPE,
        message="locked error-assignment identity mismatch",
    )
    if result.predictions_identity != result.repeat_predictions_identity or predictions != repeats:
        fail("locked repeat prediction identity mismatch")
    _validate_measurement(
        result.measurements,
        result=result,
        binding=binding,
        run_input=run_input,
        row_identity=locked_results.row_sequence_identity,
        row_count=row_count,
        predictions_identity=result.predictions_identity,
    )
    _validate_measurement(
        result.repeat_measurements,
        result=result,
        binding=binding,
        run_input=run_input,
        row_identity=locked_results.row_sequence_identity,
        row_count=row_count,
        predictions_identity=result.repeat_predictions_identity,
    )
    if (
        result.measurements.resource_inventory_identity
        == result.repeat_measurements.resource_inventory_identity
    ):
        fail("locked repeats require independent resource inventories")
    return predictions, assignments


__all__ = [
    "ComparisonError",
    "LockedArmResult",
    "LockedComparisonInputs",
    "LockedResultSet",
    "fail",
    "read_locked_rows",
    "row_key",
    "validate_locked_arm",
    "validate_locked_inputs",
]
