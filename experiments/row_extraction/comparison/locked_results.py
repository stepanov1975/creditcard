"""Orchestrate fail-closed validation of one locked comparison arm."""

from __future__ import annotations

from experiments.row_extraction.comparison.errors import ErrorAssignment
from experiments.row_extraction.comparison.handoff_contracts import ValidatedHandoffs
from experiments.row_extraction.contracts import FrozenRow, RowPrediction

from .locked_artifacts import read_verified_jsonl
from .locked_contracts import (
    ComparisonError,
    LockedArmResult,
    LockedComparisonInputs,
    LockedPreparationResult,
    LockedResultSet,
    ValidatedLockedArm,
    fail,
)
from .locked_measurements import validate_measurement_pair
from .locked_membership import read_locked_rows, row_key, validate_locked_inputs


def validate_locked_arm(
    result: LockedArmResult,
    *,
    handoffs: ValidatedHandoffs,
    locked_results: LockedResultSet,
    rows: tuple[FrozenRow, ...],
) -> ValidatedLockedArm:
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
    predictions = read_verified_jsonl(
        result.predictions_path,
        result.predictions_identity,
        RowPrediction,
        artifact_type="jsonl",
        message="locked prediction identity mismatch",
    )
    repeats = read_verified_jsonl(
        result.repeat_predictions_path,
        result.repeat_predictions_identity,
        RowPrediction,
        artifact_type="jsonl",
        message="locked repeat prediction identity mismatch",
    )
    assignments = read_verified_jsonl(
        result.error_assignments_path,
        result.error_assignments_identity,
        ErrorAssignment,
        artifact_type="jsonl",
        message="locked error-assignment identity mismatch",
    )
    if result.predictions_identity != result.repeat_predictions_identity or predictions != repeats:
        fail("locked repeat prediction identity mismatch")
    if any(
        prediction.experiment_id != result.experiment_id or prediction.config_id != result.config_id
        for prediction in (*predictions, *repeats)
    ):
        fail("locked prediction binding mismatch")
    expected_row_keys = tuple((row.document_id, row.row_id) for row in rows)
    if any(
        tuple((prediction.document_id, prediction.row_id) for prediction in values)
        != expected_row_keys
        for values in (predictions, repeats)
    ):
        fail("locked prediction row membership mismatch")
    measurements, repeat_measurements = validate_measurement_pair(
        result,
        binding=binding,
        run_input=run_input,
        row_identity=locked_results.row_sequence_identity,
        row_count=len(rows),
        expected_page_keys=frozenset((row.document_id, row.page_number) for row in rows),
    )
    return ValidatedLockedArm(
        predictions=predictions,
        assignments=assignments,
        measurements=measurements,
        repeat_measurements=repeat_measurements,
    )


__all__ = [
    "ComparisonError",
    "LockedArmResult",
    "LockedComparisonInputs",
    "LockedPreparationResult",
    "LockedResultSet",
    "fail",
    "read_locked_rows",
    "row_key",
    "validate_locked_arm",
    "validate_locked_inputs",
]
