"""Independent pre-lock normalization into the closed comparison core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FrozenRow,
    GoldRow,
    LaneDisposition,
    OcrReference,
)

from .cli_adapters import authenticate_lane
from .cli_baseline_loader import baseline_factory_loader
from .cli_manifest import (
    BASELINE_INPUT_IDS,
    LANE_INPUT_IDS,
    HandoffArtifacts,
    LockedComparisonCliManifestV1,
)
from .cli_normalize_contracts import (
    NormalizationError,
    NormalizationReceipt,
    NormalizedArmSnapshot,
    NormalizedProgram,
    NormalizedProgramSnapshot,
    fail_normalization,
)
from .cli_normalize_evidence import (
    cli_row_identity,
    core_artifact,
    materialize_profile_measurements,
    normalize_evidence,
    read_normalized_jsonl,
)
from .cli_state import ControllerStateError, canonical_model_bytes, identity_for_bytes
from .handoff_contracts import (
    ArtifactFile,
    BaselineHandoff,
    ComparisonManifest,
    FrozenArmFactoryLoader,
    FrozenArmInput,
    LaneHandoff,
)
from .profile_loader import ProfileLaneAdapter


@dataclass(frozen=True)
class _NormalizedArm:
    metrics: ArtifactFile
    measurements: tuple[ArtifactFile, ...]
    errors: ArtifactFile
    frozen_arm: FrozenArmInput | None
    snapshot: NormalizedArmSnapshot


def normalize_program(
    cli: LockedComparisonCliManifestV1,
    prelock_root: Path,
    *,
    profile_adapter: ProfileLaneAdapter,
    manifest_identity: ArtifactIdentity,
    comparison_commit_sha: str,
    profiles_source_manifest_sha256: str,
) -> NormalizedProgram:
    """Authenticate and independently replay all validation evidence exactly once."""

    try:
        rows = read_normalized_jsonl(
            cli.validation_rows,
            FrozenRow,
            "validation rows are invalid",
        )
        gold = read_normalized_jsonl(
            cli.validation_gold,
            GoldRow,
            "validation gold is invalid",
        )
        references = (
            ()
            if cli.validation_ocr_references is None
            else read_normalized_jsonl(
                cli.validation_ocr_references,
                OcrReference,
                "validation OCR references are invalid",
            )
        )
        from .cli_normalize_evidence import validate_foundation

        validate_foundation(cli, rows, gold)
    except (ControllerStateError, ValidationError, ValueError):
        fail_normalization("foundation validation binding mismatch")

    authentications = {
        experiment_id: authenticate_lane(cli.lanes[experiment_id])
        for experiment_id in LANE_INPUT_IDS
    }
    validation_row_identity = cli_row_identity(rows)
    if any(
        (
            authentication.provenance.foundation_sha,
            authentication.provenance.bundle_identity,
            authentication.provenance.split_identity,
            authentication.provenance.label_identity,
            authentication.provenance.row_sequence_identity,
        )
        != (
            cli.foundation_sha,
            cli.expected_bundle_identity,
            cli.expected_split_identity,
            cli.expected_label_identity,
            validation_row_identity,
        )
        for authentication in authentications.values()
    ):
        fail_normalization("authenticated lane foundation binding mismatch")
    if (
        authentications["row-profiles"].config_id != profile_adapter.config_id
        or sum(
            value.disposition is LaneDisposition.FROZEN_ELIGIBLE
            for value in authentications.values()
        )
        != 1
    ):
        fail_normalization("lane disposition set is invalid")

    normalized_root = prelock_root / "normalized"
    try:
        normalized_root.mkdir(mode=0o700)
    except OSError:
        fail_normalization("normalization output is not new")
    baselines: dict[str, BaselineHandoff] = {}
    lanes: dict[str, LaneHandoff] = {}
    snapshots: list[NormalizedArmSnapshot] = []

    def normalize_one(
        experiment_id: str,
        config_id: str,
        artifacts: HandoffArtifacts,
        replay_cache: Path | None,
        disposition: LaneDisposition | None,
        stop_reason: str | None,
        loader: FrozenArmFactoryLoader | None,
    ) -> _NormalizedArm:
        arm_root = normalized_root / experiment_id
        try:
            arm_root.mkdir(mode=0o700)
        except OSError:
            fail_normalization("normalization output is not new")
        profile_members = (
            materialize_profile_measurements(artifacts, arm_root, config_id)
            if experiment_id == "row-profiles"
            else None
        )
        metrics, measurements, errors = normalize_evidence(
            experiment_id,
            config_id,
            artifacts,
            rows=rows,
            gold=gold,
            ocr_references=references,
            output_root=arm_root,
            profile_measurements=profile_members,
        )
        if any(
            value != expected
            for value, expected in (
                (artifacts.foundation_sha, cli.foundation_sha),
                (artifacts.bundle_identity, cli.expected_bundle_identity),
                (artifacts.split_identity, cli.expected_split_identity),
                (artifacts.label_identity, cli.expected_label_identity),
            )
        ):
            fail_normalization("handoff foundation binding mismatch")
        snapshot = NormalizedArmSnapshot(
            experiment_id=experiment_id,
            config_id=config_id,
            runtime_identity=artifacts.runtime_identity,
            model_inventory=artifacts.model_inventory,
            dependency_inventory=artifacts.dependency_inventory,
            arm_manifest=artifacts.arm_manifest,
            validation_predictions=artifacts.validation_predictions,
            validation_metrics=metrics,
            validation_measurements=measurements,
            validation_error_summary=errors,
            disposition=disposition,
            stop_reason=stop_reason,
            validation_replay_cache_root=replay_cache,
        )
        frozen_arm = None
        if loader is not None and artifacts.arm_manifest is not None and replay_cache is not None:
            frozen_arm = FrozenArmInput(
                arm_manifest=core_artifact(artifacts.arm_manifest),
                factory_loader=loader,
                validation_replay_cache_root=replay_cache,
            )
        return _NormalizedArm(
            metrics=core_artifact(metrics),
            measurements=tuple(core_artifact(value) for value in measurements),
            errors=core_artifact(errors),
            frozen_arm=frozen_arm,
            snapshot=snapshot,
        )

    for experiment_id in BASELINE_INPUT_IDS:
        baseline_value = cli.baselines[experiment_id]
        normalized = normalize_one(
            experiment_id,
            baseline_value.config_id,
            baseline_value,
            baseline_value.validation_replay_cache_root,
            None,
            None,
            baseline_factory_loader(baseline_value),
        )
        if normalized.frozen_arm is None:
            fail_normalization("baseline frozen arm is missing")
        baselines[experiment_id] = BaselineHandoff(
            experiment_id=experiment_id,
            config_id=baseline_value.config_id,
            foundation_sha=cli.foundation_sha,
            bundle_identity=cli.expected_bundle_identity,
            split_identity=cli.expected_split_identity,
            label_identity=cli.expected_label_identity,
            runtime_identity=baseline_value.runtime_identity,
            model_inventory=core_artifact(baseline_value.model_inventory),
            dependency_inventory=core_artifact(baseline_value.dependency_inventory),
            validation_predictions=core_artifact(baseline_value.validation_predictions),
            validation_metrics=normalized.metrics,
            validation_measurements=normalized.measurements,
            validation_error_summary=normalized.errors,
            frozen_arm=normalized.frozen_arm,
        )
        snapshots.append(normalized.snapshot)
    for lane_id in LANE_INPUT_IDS:
        lane_value = cli.lanes[lane_id]
        authentication = authentications[lane_id]
        provenance = authentication.provenance
        loader = profile_adapter.factory_loader if lane_id == "row-profiles" else None
        normalized = normalize_one(
            lane_id,
            authentication.config_id,
            lane_value.artifacts,
            lane_value.validation_replay_cache_root,
            authentication.disposition,
            authentication.stop_reason,
            loader,
        )
        lanes[lane_id] = LaneHandoff(
            experiment_id=lane_id,
            config_id=authentication.config_id,
            foundation_sha=provenance.foundation_sha,
            bundle_identity=provenance.bundle_identity,
            split_identity=provenance.split_identity,
            label_identity=provenance.label_identity,
            runtime_identity=provenance.runtime_identity,
            model_inventory=core_artifact(lane_value.artifacts.model_inventory),
            dependency_inventory=core_artifact(lane_value.artifacts.dependency_inventory),
            validation_predictions=core_artifact(lane_value.artifacts.validation_predictions),
            validation_metrics=normalized.metrics,
            validation_measurements=normalized.measurements,
            validation_error_summary=normalized.errors,
            disposition=authentication.disposition,
            stop_reason=authentication.stop_reason,
            frozen_arm=normalized.frozen_arm,
        )
        snapshots.append(normalized.snapshot)

    core_manifest = ComparisonManifest(
        foundation_sha=cli.foundation_sha,
        bundle_identity=cli.expected_bundle_identity,
        split_identity=cli.expected_split_identity,
        label_identity=cli.expected_label_identity,
        runtime_identity=cli.baselines["accepted-baseline"].runtime_identity,
        validation_rows=core_artifact(cli.validation_rows),
        locked_row_ids=core_artifact(cli.locked_row_ids),
        baselines=baselines,
        lanes=lanes,
    )
    program_snapshot = NormalizedProgramSnapshot(
        version="row-comparison-normalized-program-v1",
        foundation_sha=cli.foundation_sha,
        bundle_identity=cli.expected_bundle_identity,
        split_identity=cli.expected_split_identity,
        label_identity=cli.expected_label_identity,
        validation_rows=cli.validation_rows,
        locked_row_ids=cli.locked_row_ids,
        arms=tuple(snapshots),
    )
    snapshot_identity = identity_for_bytes(
        canonical_model_bytes(program_snapshot),
        artifact_type="row-comparison-normalized-program",
        version="row-comparison-normalized-program-v1",
    )
    receipt = NormalizationReceipt(
        version="row-comparison-normalization-receipt-v1",
        comparison_manifest_identity=manifest_identity,
        comparison_commit_sha=comparison_commit_sha,
        profiles_source_manifest_sha256=profiles_source_manifest_sha256,
        normalized_program_identity=snapshot_identity,
        independently_recomputed_foundation_binding=True,
        stopped_source_generation_provenance="unreplayable_authenticated_outputs",
        raw_handoff_identities={
            key: value.raw_handoff.identity for key, value in cli.lanes.items()
        },
        source_commit_pins={key: value.source_commit_sha for key, value in authentications.items()},
        runtime_identities={
            key: arm_snapshot.runtime_identity
            for key, arm_snapshot in zip(
                (*BASELINE_INPUT_IDS, *LANE_INPUT_IDS), snapshots, strict=True
            )
        },
        dispositions={key: value.disposition for key, value in authentications.items()},
        validation_prediction_identities={
            arm_snapshot.experiment_id: arm_snapshot.validation_predictions.identity
            for arm_snapshot in snapshots
        },
        provenance_limitations={
            key: cast(str, value.provenance_limitation)
            for key, value in authentications.items()
            if value.provenance_limitation is not None
        },
        test_accessed=False,
    )
    return NormalizedProgram(
        manifest=core_manifest,
        profile_adapter=profile_adapter,
        snapshot=program_snapshot,
        receipt=receipt,
    )


__all__ = [
    "NormalizationError",
    "NormalizationReceipt",
    "NormalizedArmSnapshot",
    "NormalizedProgram",
    "NormalizedProgramSnapshot",
    "baseline_factory_loader",
    "cli_row_identity",
    "normalize_program",
]
