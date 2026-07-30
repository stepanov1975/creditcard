from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from experiments.row_extraction.comparison.cli_cascade import evaluate_cascade_locked_stage
from experiments.row_extraction.comparison.cli_cascade_products import read_cascade_products
from experiments.row_extraction.comparison.cli_compare import compare_locked_stage
from experiments.row_extraction.comparison.cli_locked import LockedInputs
from experiments.row_extraction.comparison.cli_locked_products import read_locked_products
from experiments.row_extraction.comparison.cli_manifest import LockedComparisonCliManifestV1
from experiments.row_extraction.comparison.cli_prelock import (
    select_cascade_validation_stage,
    validate_handoffs_stage,
)
from experiments.row_extraction.comparison.cli_recommend import recommend_stage
from experiments.row_extraction.comparison.cli_recommend_products import (
    read_recommendation_products,
)
from experiments.row_extraction.comparison.handoff_contracts import ValidatedHandoffs
from experiments.row_extraction.comparison.profile_loader import ProfileLaneAdapter
from experiments.row_extraction.contracts import DatasetSplit

from .cli_stage_backend import SyntheticBackend
from .cli_stage_case import SyntheticCase


def _corrupt_then_restore(path: Path, operation: Callable[[], object]) -> None:
    payload = path.read_bytes()
    path.write_bytes(payload + b"corrupt")
    try:
        with pytest.raises(ValueError):
            operation()
    finally:
        path.write_bytes(payload)


def _symlink_then_restore(path: Path, operation: Callable[[], object]) -> None:
    backup = path.with_name(f"{path.name}.regular-backup")
    path.rename(backup)
    path.symlink_to(backup.name)
    try:
        with pytest.raises(ValueError):
            operation()
    finally:
        path.unlink()
        backup.rename(path)


def _swap_inode_during_read(
    path: Path,
    operation: Callable[[], object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = Path.read_bytes
    swapped = False

    def swapping_read(value: Path) -> bytes:
        nonlocal swapped
        payload = original_read(value)
        if value == path and not swapped:
            swapped = True
            backup = path.with_name(f"{path.name}.inode-backup")
            path.rename(backup)
            path.write_bytes(payload)
            backup.unlink()
        return payload

    monkeypatch.setattr(Path, "read_bytes", swapping_read)
    try:
        with pytest.raises(ValueError):
            operation()
    finally:
        monkeypatch.setattr(Path, "read_bytes", original_read)


def exercise_synthetic_controller_progression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = SyntheticCase(tmp_path)
    backend: SyntheticBackend | None = None

    def backend_factory(
        _cli: LockedComparisonCliManifestV1,
        locked: LockedInputs,
        handoffs: ValidatedHandoffs,
        _profile_adapter: ProfileLaneAdapter,
    ) -> SyntheticBackend:
        nonlocal backend
        backend = SyntheticBackend(case, locked, handoffs)
        return backend

    deferred = {
        case.manifest.locked_inputs.rows.path,
        case.manifest.locked_inputs.gold.path,
        case.manifest.locked_inputs.accepted_predictions.path,
        case.manifest.locked_inputs.accepted_predictions_identity_file.path,
    }
    deferred_reads: list[Path] = []
    original_read = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        if path in deferred:
            deferred_reads.append(path)
            raise AssertionError("pre-lock stage read deferred input")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    validate_result = validate_handoffs_stage(
        case.manifest_path,
        normalizer=case.normalizer,
        profile_loader=case.profile_loader,
    )
    policy_result = select_cascade_validation_stage(case.manifest_path)
    assert deferred_reads == []
    assert validate_result["command"] == "validate-handoffs"
    assert policy_result["command"] == "select-cascade-validation"
    monkeypatch.setattr(Path, "read_bytes", original_read)

    with pytest.raises(ValueError):
        validate_handoffs_stage(
            case.manifest_path,
            normalizer=case.normalizer,
            profile_loader=case.profile_loader,
        )
    with pytest.raises(ValueError):
        select_cascade_validation_stage(case.manifest_path)

    _corrupt_then_restore(
        case.manifest.workspace_root / "prelock" / "normalized-program.json",
        lambda: compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        ),
    )
    _corrupt_then_restore(
        case.manifest.workspace_root / "prelock" / "validation-receipt.json",
        lambda: compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        ),
    )
    _corrupt_then_restore(
        case.manifest.workspace_root / "prelock" / "policy" / "cascade-envelope.json",
        lambda: compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        ),
    )
    _corrupt_then_restore(
        case.manifest.workspace_root / "prelock" / "policy" / "cascade-policy.json",
        lambda: compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        ),
    )
    comparison_result = compare_locked_stage(
        case.manifest_path,
        profile_loader=case.profile_loader,
        backend_factory=backend_factory,
    )
    assert comparison_result["command"] == "compare-locked"
    assert backend is not None
    assert (backend.run_count, backend.preparation_count) == (8, 4)
    with pytest.raises(ValueError):
        compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        )

    locked_root = case.manifest.workspace_root / "locked"
    locked_mutations = (
        locked_root / "start-receipt.json",
        locked_root / "locked-artifacts.json",
        locked_root / "comparison-report.json",
        locked_root / "completion-receipt.json",
        locked_root / "arms" / "accepted-baseline" / "run-1" / "predictions.jsonl",
        locked_root / "arms" / "accepted-baseline" / "run-1" / "measurements.json",
        locked_root / "arms" / "accepted-baseline" / "run-1" / "resource-inventory.json",
        locked_root / "analysis" / "accepted-baseline-error-assignments.jsonl",
        locked_root
        / "arms"
        / "conditional-page-ocr"
        / "run-1"
        / "preparation-cache"
        / "page-evidence.jsonl",
        locked_root / "arms" / "conditional-page-ocr" / "run-1" / "preparation-measurements.json",
        locked_root
        / "arms"
        / "conditional-page-ocr"
        / "run-1"
        / "preparation-resource-inventory.json",
    )
    for path in locked_mutations:
        _corrupt_then_restore(
            path,
            lambda: evaluate_cascade_locked_stage(case.manifest_path),
        )
    generated_locked_products = (
        locked_root / "start-receipt.json",
        locked_root / "locked-artifacts.json",
        locked_root / "locked-artifacts.json.identity",
        locked_root / "comparison-report.json",
        locked_root / "comparison-report.json.identity",
        locked_root / "completion-receipt.json",
        locked_root / "completion-receipt.json.identity",
    )
    for path in generated_locked_products:
        _symlink_then_restore(path, lambda: read_locked_products(case.manifest_path))
    _swap_inode_during_read(
        locked_root / "locked-artifacts.json",
        lambda: read_locked_products(case.manifest_path),
        monkeypatch,
    )
    cascade_result = evaluate_cascade_locked_stage(case.manifest_path)
    assert cascade_result == {
        "candidate_policy_count": 0,
        "command": "evaluate-cascade-locked",
        "complete": True,
        "extraction_run_count": 0,
    }
    assert backend.run_count == 8
    cascade_root = case.manifest.workspace_root / "locked" / "cascade"
    assert (cascade_root / "predictions.jsonl").read_bytes() == (
        cascade_root / "repeat-predictions.jsonl"
    ).read_bytes()
    with pytest.raises(ValueError):
        evaluate_cascade_locked_stage(case.manifest_path)

    for name in ("evaluation.json", "completion-receipt.json"):
        _corrupt_then_restore(
            cascade_root / name,
            lambda: recommend_stage(case.manifest_path),
        )
    for name in (
        "evaluation.json",
        "evaluation.json.identity",
        "completion-receipt.json",
        "completion-receipt.json.identity",
    ):
        _symlink_then_restore(
            cascade_root / name,
            lambda: read_cascade_products(case.manifest_path),
        )
    recommendation_result = recommend_stage(case.manifest_path)
    assert recommendation_result["candidate_count"] == 1
    assert recommendation_result["cascade_candidate_count"] == 0
    with pytest.raises(ValueError):
        recommend_stage(case.manifest_path)

    recommendation_root = case.manifest.workspace_root / "locked" / "recommendation"
    products = read_recommendation_products(case.manifest_path)
    assert products.recommendation.candidate_ids == ("row-profiles",)
    for name in ("recommendation.json", "completion-receipt.json"):
        _corrupt_then_restore(
            recommendation_root / name,
            lambda: read_recommendation_products(case.manifest_path),
        )
    for name in (
        "recommendation.json",
        "recommendation.json.identity",
        "completion-receipt.json",
        "completion-receipt.json.identity",
    ):
        _symlink_then_restore(
            recommendation_root / name,
            lambda: read_recommendation_products(case.manifest_path),
        )


def exercise_locked_split_manifest_rejection(tmp_path: Path) -> None:
    case = SyntheticCase(tmp_path, locked_split=DatasetSplit.VALIDATION)
    backend_started = False

    def backend_factory(
        _cli: LockedComparisonCliManifestV1,
        locked: LockedInputs,
        handoffs: ValidatedHandoffs,
        _profile_adapter: ProfileLaneAdapter,
    ) -> SyntheticBackend:
        nonlocal backend_started
        backend_started = True
        return SyntheticBackend(case, locked, handoffs)

    validate_handoffs_stage(
        case.manifest_path,
        normalizer=case.normalizer,
        profile_loader=case.profile_loader,
    )
    select_cascade_validation_stage(case.manifest_path)

    with pytest.raises(ValueError):
        compare_locked_stage(
            case.manifest_path,
            profile_loader=case.profile_loader,
            backend_factory=backend_factory,
        )

    assert (case.manifest.workspace_root / "locked" / "start-receipt.json").is_file()
    assert backend_started is False
