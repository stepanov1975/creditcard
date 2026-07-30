"""Pre-lock validation and empty-cascade freeze stages."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    LaneDisposition,
    RowPrediction,
)

from .cascade import CascadePolicy, CascadeValidation, select_cascade_policy
from .cli_manifest import LockedComparisonCliManifestV1, PinnedArtifact, read_cli_manifest
from .cli_normalize import normalize_program
from .cli_normalize_contracts import NormalizedProgram
from .cli_prelock_contracts import (
    EmptyCascadePolicy,
    FrozenCascadeEnvelopeV1,
    PrelockError,
    manifest_identity,
    write_identified_model,
)
from .cli_prelock_contracts import (
    fail_prelock as _fail,
)
from .cli_prelock_verify import reverify_frozen_policy, reverify_prelock
from .cli_state import (
    create_stage,
    require_private_root,
    verified_bytes,
    verify_git_checkout,
)
from .handoffs import validate_handoffs
from .profile_loader import ProfileLaneAdapter, ProfileLaneLoader, load_profile_lane
from .profile_source import (
    reverify_profile_snapshot,
    snapshot_profile_source,
    source_manifest_identity,
)

_POLICY_VERSION: Literal["row-cascade-policy-v1"] = "row-cascade-policy-v1"


class ProgramNormalizer(Protocol):
    """Normalize the reviewed controller program without opening locked inputs."""

    def __call__(
        self,
        cli: LockedComparisonCliManifestV1,
        prelock_root: Path,
        *,
        profile_adapter: ProfileLaneAdapter,
        manifest_identity: ArtifactIdentity,
        comparison_commit_sha: str,
        profiles_source_manifest_sha256: str,
    ) -> NormalizedProgram: ...


def validate_handoffs_stage(
    manifest_path: Path,
    *,
    normalizer: ProgramNormalizer = normalize_program,
    profile_loader: ProfileLaneLoader = load_profile_lane,
) -> dict[str, object]:
    """Normalize and validate all seven arms without dereferencing locked inputs."""

    cli = read_cli_manifest(manifest_path)
    require_private_root(cli.private_root)
    verify_git_checkout(cli.comparison_checkout)
    if cli.workspace_root.exists():
        _fail("comparison workspace already exists")
    try:
        cli.workspace_root.mkdir(mode=0o700)
    except OSError:
        _fail("comparison workspace creation failed")
    prelock = create_stage(cli.workspace_root, "prelock")
    source_root = prelock / "profile-source"
    source_manifest = snapshot_profile_source(cli.profiles_source, source_root)
    profile_adapter = profile_loader(
        cli.profiles_source,
        source_root,
        cli.lanes["row-profiles"].raw_handoff,
        cli.lanes["row-profiles"].artifacts,
    )
    manifest_id = manifest_identity(manifest_path, cli)
    program = normalizer(
        cli,
        prelock,
        profile_adapter=profile_adapter,
        manifest_identity=manifest_id,
        comparison_commit_sha=cli.comparison_checkout.commit_sha,
        profiles_source_manifest_sha256=source_manifest_identity(source_manifest),
    )
    validated = validate_handoffs(program.manifest)
    expected_dispositions = {
        "row-ocr": LaneDisposition.VALIDATION_STOPPED,
        "row-profiles": LaneDisposition.FROZEN_ELIGIBLE,
        "row-text": LaneDisposition.VALIDATION_STOPPED,
        "row-vision": LaneDisposition.VALIDATION_STOPPED,
    }
    if (
        dict(validated.dispositions) != expected_dispositions
        or set(validated.run_inputs)
        != {
            "accepted-baseline",
            "conditional-page-ocr",
            "forced-page-ocr",
            "row-profiles",
        }
        or len(validated.validation_evidence) != 7
    ):
        _fail("validated handoff set is incomplete")
    snapshot_identity = write_identified_model(
        prelock / "normalized-program.json",
        program.snapshot,
        artifact_type="row-comparison-normalized-program",
        version="row-comparison-normalized-program-v1",
    )
    if snapshot_identity != program.receipt.normalized_program_identity:
        _fail("normalized program identity mismatch")
    write_identified_model(
        prelock / "validation-receipt.json",
        program.receipt,
        artifact_type="row-comparison-validation-receipt",
        version="row-comparison-validation-receipt-v1",
    )
    verify_git_checkout(cli.comparison_checkout)
    reverify_profile_snapshot(cli.profiles_source, source_root)
    return {
        "command": "validate-handoffs",
        "complete": True,
        "eligible_lane_count": 1,
        "stopped_lane_count": 3,
    }


def _predictions_have_no_confidence(artifact: PinnedArtifact) -> bool:
    payload = verified_bytes(artifact, "profile validation predictions are invalid")
    try:
        predictions = tuple(
            RowPrediction.model_validate_json(line) for line in payload.splitlines()
        )
    except (ValidationError, ValueError):
        _fail("profile validation predictions are invalid")
    return bool(predictions) and all(value.exact_row_confidence is None for value in predictions)


def select_cascade_validation_stage(manifest_path: Path) -> dict[str, object]:
    """Freeze the reviewed empty cascade from validation evidence only."""

    cli, snapshot, receipt, receipt_identity, _source_manifest = reverify_prelock(manifest_path)
    policy_root = create_stage(cli.workspace_root / "prelock", "policy")
    profile = next(value for value in snapshot.arms if value.experiment_id == "row-profiles")
    if receipt.dispositions != {
        "row-ocr": LaneDisposition.VALIDATION_STOPPED,
        "row-profiles": LaneDisposition.FROZEN_ELIGIBLE,
        "row-text": LaneDisposition.VALIDATION_STOPPED,
        "row-vision": LaneDisposition.VALIDATION_STOPPED,
    } or not _predictions_have_no_confidence(profile.validation_predictions):
        _fail("cascade validation evidence is not the frozen empty-policy case")
    selected = select_cascade_policy(
        CascadeValidation(
            version=_POLICY_VERSION,
            rows=(),
            candidate_policies=(),
            deterministic_arms={"row-profiles": True},
            maximum_accepted_row_errors=0,
            maximum_required_field_errors=0,
        )
    )
    if selected != CascadePolicy(version=_POLICY_VERSION, rules=()):
        _fail("cascade policy is not empty")
    policy = EmptyCascadePolicy(version=_POLICY_VERSION, rules=())
    write_identified_model(
        policy_root / "cascade-policy.json",
        policy,
        artifact_type="row-extraction-cascade-policy-record",
        version=_POLICY_VERSION,
    )
    envelope = FrozenCascadeEnvelopeV1(
        version="row-comparison-frozen-cascade-envelope-v1",
        comparison_manifest_identity=receipt.comparison_manifest_identity,
        validation_receipt_identity=receipt_identity,
        comparison_commit_sha=receipt.comparison_commit_sha,
        profiles_source_manifest_sha256=receipt.profiles_source_manifest_sha256,
        locked_row_ids_identity=cli.locked_row_ids.identity,
        baseline_id="accepted-baseline",
        dispositions=receipt.dispositions,
        validation_prediction_identities=receipt.validation_prediction_identities,
        eligible_candidate_ids=("row-profiles",),
        excluded_control_ids=("conditional-page-ocr", "forced-page-ocr"),
        exclusion_reason_codes=(
            "validation_stopped",
            "page_controls_are_not_candidates",
            "candidate_confidence_uncalibrated",
        ),
        candidate_policy_count=0,
        policy=policy,
        test_accessed=False,
    )
    write_identified_model(
        policy_root / "cascade-envelope.json",
        envelope,
        artifact_type="row-extraction-cascade-policy",
        version="row-comparison-frozen-cascade-envelope-v1",
    )
    return {
        "candidate_policy_count": 0,
        "command": "select-cascade-validation",
        "complete": True,
        "rule_count": 0,
    }


__all__ = [
    "EmptyCascadePolicy",
    "FrozenCascadeEnvelopeV1",
    "PrelockError",
    "reverify_frozen_policy",
    "reverify_prelock",
    "select_cascade_validation_stage",
    "validate_handoffs_stage",
]
