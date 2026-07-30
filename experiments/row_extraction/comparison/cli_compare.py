"""Exactly-once locked comparison execution and report assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from experiments.row_extraction.contracts import GoldRow, RowPrediction

from .cli_execution import SharedLockedBackend
from .cli_execution_support import MeasuredLockedRun, PreparedPage
from .cli_locked import LockedInputs, start_and_read_locked_inputs
from .cli_locked_records import (
    LOCKED_RESULT_IDS,
    LockedArmRecordV1,
    LockedArtifactsManifestV1,
    LockedComparisonStageError,
    LockedCompletionReceiptV1,
    fail_locked_stage,
    identified_run,
    write_locked_jsonl,
    write_locked_model,
)
from .cli_manifest import LockedComparisonCliManifestV1, PinnedArtifact
from .cli_prelock_verify import reverify_frozen_policy
from .cli_report_markdown import render_comparison_markdown
from .cli_restore import restore_validated_handoffs
from .cli_schedule import LockedScheduleBackend, execute_locked_schedule
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    verified_bytes,
    verify_git_checkout,
    write_bytes_exclusive,
)
from .compare import LockedArmResult, LockedResultSet, compare_handoffs
from .errors import classify_error
from .handoff_contracts import ValidatedHandoffs
from .locked_artifacts import read_verified_jsonl
from .locked_contracts import (
    PREPARATION_MEASUREMENT_TYPE,
    PREPARATION_MEASUREMENT_VERSION,
    LockedPreparationResult,
)
from .profile_loader import ProfileLaneAdapter, ProfileLaneLoader, load_profile_lane
from .profile_source import reverify_profile_snapshot
from .result_catalog import ResultId


class BackendFactory(Protocol):
    """Construct the one backend accepted by the fixed locked schedule."""

    def __call__(
        self,
        cli: LockedComparisonCliManifestV1,
        locked: LockedInputs,
        handoffs: ValidatedHandoffs,
        profile_adapter: ProfileLaneAdapter,
    ) -> LockedScheduleBackend[PreparedPage, MeasuredLockedRun]: ...


def _error_assignments(
    root: Path,
    run: MeasuredLockedRun,
    locked_rows: int,
    gold_records: tuple[GoldRow, ...],
) -> PinnedArtifact:
    predictions = read_verified_jsonl(
        run.paths.predictions,
        run.predictions_identity,
        RowPrediction,
        artifact_type="jsonl",
        message="locked predictions changed before error analysis",
    )
    try:
        gold = {(value.document_id, value.row_id): value for value in gold_records}
        assignments = tuple(
            classify_error(gold[(value.document_id, value.row_id)], value) for value in predictions
        )
    except (AttributeError, KeyError, TypeError):
        fail_locked_stage("locked error assignment membership mismatch")
    if len(assignments) != locked_rows:
        fail_locked_stage("locked error assignment membership mismatch")
    output = root / f"{run.experiment_id}-error-assignments.jsonl"
    identity = write_locked_jsonl(output, assignments)
    return PinnedArtifact(path=output, identity=identity)


def _preparation_result(run: MeasuredLockedRun) -> LockedPreparationResult | None:
    page = run.preparation
    paths = run.paths
    if page is None:
        return None
    if (
        page.measurements is None
        or paths.preparation_cache is None
        or paths.preparation_measurements is None
        or paths.preparation_resource_inventory is None
    ):
        fail_locked_stage("locked preparation result is incomplete")
    measurement_identity = identity_for_bytes(
        canonical_model_bytes(page.measurements),
        artifact_type=PREPARATION_MEASUREMENT_TYPE,
        version=PREPARATION_MEASUREMENT_VERSION,
    )
    return LockedPreparationResult(
        cache_root=paths.preparation_cache,
        arm_manifest_path=page.evidence_path,
        arm_manifest_identity=page.evidence_identity,
        measurements_path=paths.preparation_measurements,
        measurements_identity=measurement_identity,
        measurements=page.measurements,
        resource_inventory_path=paths.preparation_resource_inventory,
        resource_inventory_identity=page.measurements.resource_inventory_identity,
    )


def _arm_result(
    pair: tuple[MeasuredLockedRun, MeasuredLockedRun],
    errors: PinnedArtifact,
) -> LockedArmResult:
    first, repeat = pair
    return LockedArmResult(
        experiment_id=first.experiment_id,
        config_id=first.config_id,
        predictions_path=first.paths.predictions,
        predictions_identity=first.predictions_identity,
        resource_inventory_path=first.paths.resource_inventory,
        cache_root=first.paths.run_cache,
        measurements=first.measurements,
        repeat_predictions_path=repeat.paths.predictions,
        repeat_predictions_identity=repeat.predictions_identity,
        repeat_resource_inventory_path=repeat.paths.resource_inventory,
        repeat_cache_root=repeat.paths.run_cache,
        repeat_measurements=repeat.measurements,
        error_assignments_path=errors.path,
        error_assignments_identity=errors.identity,
        preparation=_preparation_result(first),
        repeat_preparation=_preparation_result(repeat),
    )


def compare_locked_stage(
    manifest_path: Path,
    *,
    profile_loader: ProfileLaneLoader = load_profile_lane,
    backend_factory: BackendFactory = SharedLockedBackend,
) -> dict[str, object]:
    """Execute, score, and record the exclusive eight-run locked comparison."""

    cli, snapshot, receipt, receipt_identity, _source, _policy, policy_identity = (
        reverify_frozen_policy(manifest_path)
    )
    profile_root = cli.workspace_root / "prelock" / "profile-source"
    profile_adapter = profile_loader(
        cli.profiles_source,
        profile_root,
        cli.lanes["row-profiles"].raw_handoff,
        cli.lanes["row-profiles"].artifacts,
    )
    handoffs = restore_validated_handoffs(cli, snapshot, profile_adapter)
    locked_root, locked = start_and_read_locked_inputs(
        cli,
        comparison_manifest_identity=receipt.comparison_manifest_identity,
        validation_receipt_identity=receipt_identity,
        policy_identity=policy_identity,
    )
    pairs = execute_locked_schedule(
        locked_root / "arms",
        backend_factory(cli, locked, handoffs, profile_adapter),
    )
    if tuple(pairs) != LOCKED_RESULT_IDS:
        fail_locked_stage("locked execution schedule is incomplete")
    analysis_root = locked_root / "analysis"
    try:
        analysis_root.mkdir(mode=0o700)
    except OSError:
        fail_locked_stage("locked analysis stage creation failed")
    errors = {
        experiment_id: _error_assignments(
            analysis_root,
            pair[0],
            len(locked.rows),
            locked.gold,
        )
        for experiment_id, pair in pairs.items()
    }
    raw_results: dict[str, LockedArmResult] = {
        experiment_id: _arm_result(pair, errors[experiment_id])
        for experiment_id, pair in pairs.items()
    }
    report = compare_handoffs(
        handoffs,
        LockedResultSet(
            rows_path=cli.locked_inputs.rows.path,
            row_sequence_identity=locked.row_sequence_identity,
            results=raw_results,
        ),
        locked.gold,
        locked.ocr_references,
    )
    artifacts = LockedArtifactsManifestV1(
        version="row-comparison-locked-artifacts-v1",
        row_sequence_identity=locked.row_sequence_identity,
        arms=tuple(
            LockedArmRecordV1(
                experiment_id=experiment_id,
                first=identified_run(pairs[experiment_id][0]),
                repeat=identified_run(pairs[experiment_id][1]),
                error_assignments=errors[experiment_id],
            )
            for experiment_id in LOCKED_RESULT_IDS
        ),
    )
    artifacts_identity = write_locked_model(
        locked_root / "locked-artifacts.json",
        artifacts,
        artifact_type="row-comparison-locked-artifacts",
        version="row-comparison-locked-artifacts-v1",
    )
    report_identity = write_locked_model(
        locked_root / "comparison-report.json",
        report,
        artifact_type="row-extraction-comparison-report",
        version="row-extraction-comparison-report-v1",
    )
    write_bytes_exclusive(locked_root / "comparison-report.md", render_comparison_markdown(report))
    verify_git_checkout(cli.comparison_checkout)
    reverify_profile_snapshot(cli.profiles_source, profile_root)
    deferred = (
        cli.locked_inputs.rows,
        cli.locked_inputs.gold,
        cli.locked_inputs.accepted_predictions,
        cli.locked_inputs.accepted_predictions_identity_file,
    )
    for artifact in deferred:
        verified_bytes(artifact, "locked input changed during execution")
    if cli.locked_inputs.optional_ocr_references is not None:
        verified_bytes(
            cli.locked_inputs.optional_ocr_references,
            "locked input changed during execution",
        )
    completion = LockedCompletionReceiptV1(
        version="row-comparison-locked-completion-v1",
        comparison_manifest_identity=receipt.comparison_manifest_identity,
        validation_receipt_identity=receipt_identity,
        cascade_policy_identity=policy_identity,
        locked_artifacts_identity=artifacts_identity,
        comparison_report_identity=report_identity,
        row_sequence_identity=locked.row_sequence_identity,
        locked_result_ids=cast(tuple[ResultId, ...], report.locked_experiment_ids),
        validation_stopped_ids=cast(tuple[ResultId, ...], report.validation_stopped_ids),
        run_count=8,
        page_preparation_count=4,
        deterministic_result_count=4,
        test_accessed=True,
    )
    write_locked_model(
        locked_root / "completion-receipt.json",
        completion,
        artifact_type="row-comparison-locked-completion",
        version="row-comparison-locked-completion-v1",
    )
    return {
        "command": "compare-locked",
        "complete": True,
        "deterministic_result_count": 4,
        "locked_result_count": 4,
        "stopped_result_count": 3,
    }


__all__ = [
    "LockedComparisonStageError",
    "compare_locked_stage",
]
