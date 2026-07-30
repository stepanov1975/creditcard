"""Identity-bound reader for completed locked comparison products."""

from __future__ import annotations

from pathlib import Path

from .cli_locked import LockedStartReceiptV1, read_locked_inputs_after_start
from .cli_locked_records import (
    LockedArtifactsManifestV1,
    LockedCompletionReceiptV1,
    LockedProducts,
    fail_locked_stage,
    read_locked_identity,
    read_locked_model,
)
from .cli_manifest import PinnedArtifact
from .cli_prelock_verify import reverify_frozen_policy
from .cli_state import canonical_model_bytes, identity_for_bytes, verified_bytes
from .reporting import ComparisonReport


def read_locked_products(manifest_path: Path) -> LockedProducts:
    """Reverify the completed locked stage for cascade and recommendation consumers."""

    cli, _snapshot, receipt, receipt_identity, _source, _policy, policy_identity = (
        reverify_frozen_policy(manifest_path)
    )
    root = cli.workspace_root / "locked"
    start = read_locked_model(
        root / "start-receipt.json",
        LockedStartReceiptV1,
        "locked start receipt is invalid",
    )
    artifacts = read_locked_model(
        root / "locked-artifacts.json",
        LockedArtifactsManifestV1,
        "locked artifacts manifest is invalid",
    )
    artifacts_identity = read_locked_identity(
        root / "locked-artifacts.json.identity",
        "locked artifacts identity is invalid",
    )
    report = read_locked_model(
        root / "comparison-report.json",
        ComparisonReport,
        "comparison report is invalid",
    )
    report_identity = read_locked_identity(
        root / "comparison-report.json.identity",
        "comparison report identity is invalid",
    )
    completion = read_locked_model(
        root / "completion-receipt.json",
        LockedCompletionReceiptV1,
        "locked completion receipt is invalid",
    )
    completion_identity = read_locked_identity(
        root / "completion-receipt.json.identity",
        "locked completion identity is invalid",
    )
    expected = (
        identity_for_bytes(
            canonical_model_bytes(artifacts),
            artifact_type=artifacts_identity.artifact_type,
            version=artifacts_identity.version,
        ),
        identity_for_bytes(
            canonical_model_bytes(report),
            artifact_type=report_identity.artifact_type,
            version=report_identity.version,
        ),
        identity_for_bytes(
            canonical_model_bytes(completion),
            artifact_type=completion_identity.artifact_type,
            version=completion_identity.version,
        ),
    )
    if (
        start.comparison_manifest_identity != receipt.comparison_manifest_identity
        or start.validation_receipt_identity != receipt_identity
        or start.policy_identity != policy_identity
        or start.locked_row_ids_identity != cli.locked_row_ids.identity
        or expected != (artifacts_identity, report_identity, completion_identity)
        or completion.comparison_manifest_identity != receipt.comparison_manifest_identity
        or completion.validation_receipt_identity != receipt_identity
        or completion.cascade_policy_identity != policy_identity
        or completion.locked_artifacts_identity != artifacts_identity
        or completion.comparison_report_identity != report_identity
        or completion.row_sequence_identity != artifacts.row_sequence_identity
        or tuple(report.locked_experiment_ids) != completion.locked_result_ids
        or tuple(report.validation_stopped_ids) != completion.validation_stopped_ids
    ):
        fail_locked_stage("locked completion binding mismatch")
    locked = read_locked_inputs_after_start(cli)
    if locked.row_sequence_identity != artifacts.row_sequence_identity:
        fail_locked_stage("locked row sequence changed")
    for arm in artifacts.arms:
        verified_bytes(arm.first.predictions, "locked prediction changed")
        verified_bytes(arm.repeat.predictions, "locked prediction changed")
        verified_bytes(arm.first.measurements, "locked measurement changed")
        verified_bytes(arm.repeat.measurements, "locked measurement changed")
        verified_bytes(arm.error_assignments, "locked error assignments changed")
        for run in (arm.first, arm.repeat):
            verified_bytes(
                PinnedArtifact(
                    path=run.resource_inventory_path,
                    identity=run.resource_inventory_identity,
                ),
                "locked resource inventory changed",
            )
            if run.preparation is None:
                continue
            verified_bytes(run.preparation.arm_manifest, "locked page evidence changed")
            verified_bytes(
                run.preparation.measurements_artifact,
                "locked preparation measurement changed",
            )
            verified_bytes(
                PinnedArtifact(
                    path=run.preparation.resource_inventory_path,
                    identity=run.preparation.resource_inventory_identity,
                ),
                "locked preparation inventory changed",
            )
    return LockedProducts(
        cli=cli,
        locked_inputs=locked,
        artifacts=artifacts,
        artifacts_identity=artifacts_identity,
        report=report,
        report_identity=report_identity,
        receipt=completion,
        receipt_identity=completion_identity,
    )


__all__ = ["read_locked_products"]
