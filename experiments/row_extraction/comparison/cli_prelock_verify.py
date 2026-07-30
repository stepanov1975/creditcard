"""Reverification boundary for completed pre-lock artifacts and frozen policy."""

from __future__ import annotations

from pathlib import Path

from experiments.row_extraction.contracts import ArtifactIdentity

from .cli_adapters import authenticate_lane
from .cli_manifest import LockedComparisonCliManifestV1, read_cli_manifest
from .cli_normalize import NormalizationReceipt, NormalizedProgramSnapshot
from .cli_prelock_contracts import (
    EmptyCascadePolicy,
    FrozenCascadeEnvelopeV1,
    fail_prelock,
    manifest_identity,
    read_canonical_model,
    read_identity,
)
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    require_private_root,
    verify_git_checkout,
)
from .profile_source import (
    ProfileSourceManifest,
    reverify_profile_snapshot,
    source_manifest_identity,
)


def reverify_prelock(
    manifest_path: Path,
) -> tuple[
    LockedComparisonCliManifestV1,
    NormalizedProgramSnapshot,
    NormalizationReceipt,
    ArtifactIdentity,
    ProfileSourceManifest,
]:
    cli = read_cli_manifest(manifest_path)
    require_private_root(cli.private_root)
    verify_git_checkout(cli.comparison_checkout)
    prelock = cli.workspace_root / "prelock"
    manifest_id = manifest_identity(manifest_path, cli)
    snapshot = read_canonical_model(prelock / "normalized-program.json", NormalizedProgramSnapshot)
    snapshot_identity = read_identity(prelock / "normalized-program.json.identity")
    if (
        identity_for_bytes(
            canonical_model_bytes(snapshot),
            artifact_type=snapshot_identity.artifact_type,
            version=snapshot_identity.version,
        )
        != snapshot_identity
    ):
        fail_prelock("normalized program identity mismatch")
    receipt = read_canonical_model(prelock / "validation-receipt.json", NormalizationReceipt)
    receipt_identity = read_identity(prelock / "validation-receipt.json.identity")
    if (
        receipt.comparison_manifest_identity != manifest_id
        or receipt.normalized_program_identity != snapshot_identity
        or identity_for_bytes(
            canonical_model_bytes(receipt),
            artifact_type=receipt_identity.artifact_type,
            version=receipt_identity.version,
        )
        != receipt_identity
    ):
        fail_prelock("validation receipt identity mismatch")
    source_manifest = reverify_profile_snapshot(cli.profiles_source, prelock / "profile-source")
    if source_manifest_identity(source_manifest) != receipt.profiles_source_manifest_sha256:
        fail_prelock("profile source manifest identity mismatch")
    for lane in cli.lanes.values():
        authenticate_lane(lane)
    return cli, snapshot, receipt, receipt_identity, source_manifest


def reverify_frozen_policy(
    manifest_path: Path,
) -> tuple[
    LockedComparisonCliManifestV1,
    NormalizedProgramSnapshot,
    NormalizationReceipt,
    ArtifactIdentity,
    ProfileSourceManifest,
    FrozenCascadeEnvelopeV1,
    ArtifactIdentity,
]:
    """Reconstruct the validation binding for the exact frozen empty policy."""

    cli, snapshot, receipt, receipt_identity, source_manifest = reverify_prelock(manifest_path)
    policy_root = cli.workspace_root / "prelock" / "policy"
    policy = read_canonical_model(policy_root / "cascade-policy.json", EmptyCascadePolicy)
    policy_record_identity = read_identity(policy_root / "cascade-policy.json.identity")
    if (
        identity_for_bytes(
            canonical_model_bytes(policy),
            artifact_type=policy_record_identity.artifact_type,
            version=policy_record_identity.version,
        )
        != policy_record_identity
    ):
        fail_prelock("cascade policy identity mismatch")
    envelope = read_canonical_model(
        policy_root / "cascade-envelope.json",
        FrozenCascadeEnvelopeV1,
    )
    envelope_identity = read_identity(policy_root / "cascade-envelope.json.identity")
    if (
        identity_for_bytes(
            canonical_model_bytes(envelope),
            artifact_type=envelope_identity.artifact_type,
            version=envelope_identity.version,
        )
        != envelope_identity
        or envelope.comparison_manifest_identity != receipt.comparison_manifest_identity
        or envelope.validation_receipt_identity != receipt_identity
        or envelope.comparison_commit_sha != receipt.comparison_commit_sha
        or envelope.profiles_source_manifest_sha256 != receipt.profiles_source_manifest_sha256
        or envelope.locked_row_ids_identity != cli.locked_row_ids.identity
        or envelope.dispositions != receipt.dispositions
        or envelope.validation_prediction_identities != receipt.validation_prediction_identities
        or envelope.policy != policy
        or envelope.test_accessed is not False
    ):
        fail_prelock("cascade policy identity mismatch")
    return (
        cli,
        snapshot,
        receipt,
        receipt_identity,
        source_manifest,
        envelope,
        envelope_identity,
    )


__all__ = ["reverify_frozen_policy", "reverify_prelock"]
