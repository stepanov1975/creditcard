"""Fixed-set handoff, row, and gold membership validation."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from experiments.row_extraction.comparison.handoff_contracts import (
    BASELINE_IDS as HANDOFF_BASELINE_IDS,
)
from experiments.row_extraction.comparison.handoff_contracts import (
    EXPERIMENT_IDS as HANDOFF_EXPERIMENT_IDS,
)
from experiments.row_extraction.comparison.handoff_contracts import (
    FrozenRunInputs,
    ValidatedArmBinding,
    ValidatedHandoffs,
)
from experiments.row_extraction.contracts import (
    DatasetSplit,
    FrozenRow,
    GoldRow,
    LaneDisposition,
    RowPrediction,
)

from .locked_artifacts import read_verified_jsonl
from .locked_contracts import (
    ComparisonError,
    LockedComparisonInputs,
    LockedResultSet,
    RowKey,
    fail,
)
from .result_catalog import BASELINE_ID_SET, LANE_ID_SET, RESULT_IDS, STOP_REASON_BY_LANE


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


def _validate_run_input(run_input: FrozenRunInputs, binding: ValidatedArmBinding) -> None:
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
        set(HANDOFF_BASELINE_IDS) != set(BASELINE_ID_SET)
        or set(HANDOFF_EXPERIMENT_IDS) != set(LANE_ID_SET)
        or set(handoffs.dispositions) != set(LANE_ID_SET)
        or set(handoffs.arm_bindings) != expected_ids
        or set(handoffs.validation_evidence) != expected_ids
    ):
        fail("validated handoff membership mismatch")
    expected: set[str] = set(BASELINE_ID_SET)
    for lane_id in LANE_ID_SET:
        disposition = handoffs.dispositions[lane_id]
        binding = handoffs.arm_bindings[lane_id]
        evidence = handoffs.validation_evidence[lane_id]
        if disposition is LaneDisposition.FROZEN_ELIGIBLE:
            expected.add(lane_id)
            if binding.arm_manifest is None or evidence.stop_reason is not None:
                fail("eligible handoff binding mismatch")
        elif (
            disposition is not LaneDisposition.VALIDATION_STOPPED
            or binding.arm_manifest is not None
            or evidence.stop_reason != STOP_REASON_BY_LANE[lane_id]
            or evidence.error_summary is None
        ):
            fail("stopped handoff binding mismatch")
    if set(handoffs.run_inputs) != expected:
        fail("validated run-input membership mismatch")
    for result_id in RESULT_IDS:
        binding = handoffs.arm_bindings[result_id]
        evidence = handoffs.validation_evidence[result_id]
        if (
            binding.experiment_id != result_id
            or not binding.config_id.strip()
            or (result_id in BASELINE_ID_SET and evidence.stop_reason is not None)
        ):
            fail("validated arm binding mismatch")
        if result_id in expected:
            _validate_run_input(handoffs.run_inputs[result_id], binding)
    return tuple(result_id for result_id in RESULT_IDS if result_id in expected)


def read_locked_rows(locked_results: LockedResultSet) -> tuple[FrozenRow, ...]:
    return read_verified_jsonl(
        locked_results.rows_path,
        locked_results.row_sequence_identity,
        FrozenRow,
        artifact_type="frozen-row-sequence",
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


__all__ = ["read_locked_rows", "row_key", "validate_locked_inputs"]
