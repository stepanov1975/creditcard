from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.comparison import cli as comparison_cli
from experiments.row_extraction.comparison import cli_manifest_author
from experiments.row_extraction.comparison.cli_adapters import (
    AuthenticatedLaneEvidence,
    OcrRawHandoff,
    ProfileConfigRecord,
    ProfileMeasurementPair,
    ProfileRawHandoff,
    RawHandoffError,
    RawProvenanceBinding,
    TextFileDigest,
    TextRawHandoff,
    VisionRawHandoff,
    authenticate_lane,
    authenticate_measurement_provenance,
    authenticate_provenance,
    profile_config_identity,
)
from experiments.row_extraction.comparison.cli_cascade import derive_empty_cascade
from experiments.row_extraction.comparison.cli_execution import (
    LockedExecutionError,
    PreparedPage,
    assert_preparation_repeat,
)
from experiments.row_extraction.comparison.cli_locked import start_and_read_locked_inputs
from experiments.row_extraction.comparison.cli_manifest import (
    BASELINE_INPUT_IDS,
    LANE_INPUT_IDS,
    BaselineCliInput,
    DeferredLockedInputs,
    GitCheckoutPin,
    LaneCliInput,
    LockedComparisonCliManifestV1,
    PinnedArtifact,
    ProfileSourcePin,
    read_cli_manifest,
)
from experiments.row_extraction.comparison.cli_manifest_author import (
    LockedIdentitySidecarsV1,
    ManifestAuthoringError,
    author_cli_manifest,
)
from experiments.row_extraction.comparison.cli_schedule import (
    LockedRunPaths,
    execute_locked_schedule,
)
from experiments.row_extraction.comparison.cli_state import (
    ControllerStateError,
    canonical_model_bytes,
    create_stage,
    verify_git_checkout,
)
from experiments.row_extraction.comparison.profile_source import (
    ProfileSourceError,
    reverify_profile_snapshot,
    snapshot_profile_source,
)
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    Decision,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from tests.experiments.row_extraction.test_report import _metric_report, _run

runner = CliRunner()


def _identity(token: str, *, artifact_type: str = "jsonl") -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=token * 64,
        version="canonical-jsonl-v1",
        byte_size=1,
    )


def _standard_runtime_identity(token: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="row-runtime-manifest",
        sha256=token * 64,
        version="row-runtime-manifest-v1",
        byte_size=1,
    )


def _vision_runtime_identity(token: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="runtime-lock",
        sha256=token * 64,
        version="row-vision-runtime-v1",
        byte_size=1,
    )


def _artifact(root: Path, name: str, token: str) -> PinnedArtifact:
    return PinnedArtifact(path=root / name, identity=_identity(token))


def _write_pinned_model(
    path: Path,
    model: BaseModel,
    *,
    artifact_type: str,
    version: str,
) -> PinnedArtifact:
    value = model.model_dump(mode="json")
    payload = _canonical_json_value_content(value) + b"\n"
    path.write_bytes(payload)
    return PinnedArtifact(
        path=path,
        identity=ArtifactIdentity(
            artifact_type=artifact_type,
            sha256=hashlib.sha256(payload).hexdigest(),
            version=version,
            byte_size=len(payload),
        ),
    )


def _manifest(root: Path) -> LockedComparisonCliManifestV1:
    checkout = GitCheckoutPin(root=root / "comparison", commit_sha="a" * 40)
    common = {
        "foundation_sha": "b" * 40,
        "bundle_identity": _identity("1", artifact_type="bundle"),
        "split_identity": _identity("2", artifact_type="row-split-manifest"),
        "label_identity": _identity("3", artifact_type="labels"),
        "runtime_identity": _standard_runtime_identity("4"),
        "model_inventory": _artifact(root, "model.json", "5"),
        "dependency_inventory": _artifact(root, "dependencies.json", "6"),
        "validation_predictions": _artifact(root, "predictions.jsonl", "7"),
        "validation_metrics": _artifact(root, "metrics.json", "8"),
        "validation_measurements": (_artifact(root, "measurements.json", "9"),),
        "validation_error_summary": _artifact(root, "errors.json", "a"),
        "arm_manifest": _artifact(root, "arm.json", "b"),
    }
    baselines = {
        experiment_id: BaselineCliInput(
            experiment_id=experiment_id,
            loader_kind=experiment_id,
            config_id=f"{experiment_id}-config",
            validation_replay_cache_root=root / "workspace" / "prelock" / "replay" / experiment_id,
            **common,
        )
        for experiment_id in BASELINE_INPUT_IDS
    }
    lanes = {
        experiment_id: LaneCliInput(
            experiment_id=experiment_id,
            schema_kind={
                "row-ocr": "ocr_stop_v2",
                "row-profiles": "profiles_v2",
                "row-text": "text_stop_v2",
                "row-vision": "vision_stop_v2",
            }[experiment_id],
            raw_handoff=_artifact(root, f"{experiment_id}-handoff.json", "c"),
            artifacts={
                **common,
                "runtime_identity": (
                    _vision_runtime_identity("4")
                    if experiment_id == "row-vision"
                    else common["runtime_identity"]
                ),
                "arm_manifest": (
                    common["arm_manifest"] if experiment_id == "row-profiles" else None
                ),
                "validation_measurements": (
                    () if experiment_id == "row-profiles" else common["validation_measurements"]
                ),
                "validation_measurement_envelope": (
                    _artifact(root, "profile-measurement-pair.json", "0")
                    if experiment_id == "row-profiles"
                    else None
                ),
            },
            validation_replay_cache_root=(
                root / "workspace" / "prelock" / "replay" / experiment_id
                if experiment_id == "row-profiles"
                else None
            ),
        )
        for experiment_id in LANE_INPUT_IDS
    }
    return LockedComparisonCliManifestV1(
        version="row-extraction-locked-comparison-cli-v1",
        private_root=root,
        workspace_root=root / "workspace",
        comparison_checkout=checkout,
        foundation_sha="b" * 40,
        expected_bundle_identity=_identity("1", artifact_type="bundle"),
        expected_split_identity=_identity("2", artifact_type="row-split-manifest"),
        expected_label_identity=_identity("3", artifact_type="labels"),
        foundation_bundle=PinnedArtifact(
            path=root / "foundation-bundle.json",
            identity=_identity("1", artifact_type="bundle"),
        ),
        split_manifest=PinnedArtifact(
            path=root / "split-manifest.json",
            identity=_identity("2", artifact_type="row-split-manifest"),
        ),
        validation_rows=_artifact(root, "validation-rows.jsonl", "d"),
        validation_gold=PinnedArtifact(
            path=root / "validation-gold.jsonl",
            identity=_identity("3", artifact_type="labels"),
        ),
        locked_row_ids=_artifact(root, "locked-row-ids.jsonl", "f"),
        locked_inputs=DeferredLockedInputs(
            rows=_artifact(root, "locked-rows.jsonl", "1"),
            gold=_artifact(root, "locked-gold.jsonl", "2"),
            accepted_predictions=_artifact(root, "locked-accepted.jsonl", "3"),
            accepted_predictions_identity_file=_artifact(
                root, "locked-accepted.identity.json", "4"
            ),
        ),
        baselines=baselines,
        lanes=lanes,
        profiles_source=ProfileSourcePin(
            checkout=GitCheckoutPin(root=root / "profiles", commit_sha="c" * 40),
            package_tree_sha="d" * 40,
        ),
    )


def test_canonical_manifest_round_trips_without_opening_artifacts(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_bytes(manifest.canonical_bytes())

    assert read_cli_manifest(path) == manifest


def test_manifest_rejects_extra_fields_and_relative_paths(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        LockedComparisonCliManifestV1.model_validate(payload)


@pytest.mark.parametrize("escaped_role", ("workspace", "input"))
def test_manifest_rejects_descendant_symlink_escape(
    tmp_path: Path,
    escaped_role: str,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (private / "escape").symlink_to(outside, target_is_directory=True)
    manifest = _manifest(private)
    payload = manifest.model_dump(mode="python")
    if escaped_role == "workspace":
        workspace = private / "escape" / "workspace"
        payload["workspace_root"] = workspace
        for key in payload["baselines"]:
            payload["baselines"][key]["validation_replay_cache_root"] = (
                workspace / "prelock" / "replay" / key
            )
        payload["lanes"]["row-profiles"]["validation_replay_cache_root"] = (
            workspace / "prelock" / "replay" / "row-profiles"
        )
    else:
        payload["validation_rows"]["path"] = private / "escape" / "validation-rows.jsonl"

    with pytest.raises(ValidationError, match=r"symlink|private root"):
        LockedComparisonCliManifestV1.model_validate(payload)

    payload = manifest.model_dump(mode="json")
    payload["workspace_root"] = "relative/workspace"
    with pytest.raises(ValidationError, match="absolute"):
        LockedComparisonCliManifestV1.model_validate(payload)


def test_manifest_rejects_closed_key_drift_and_path_overlap(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = manifest.model_dump(mode="python")
    del payload["lanes"]["row-vision"]
    with pytest.raises(ValidationError, match="lane key set"):
        LockedComparisonCliManifestV1.model_validate(payload)


@pytest.mark.parametrize(
    "deferred_field",
    (
        "rows",
        "gold",
        "accepted_predictions",
        "accepted_predictions_identity_file",
        "optional_ocr_references",
    ),
)
def test_manifest_rejects_exact_prelock_deferred_alias_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deferred_field: str,
) -> None:
    manifest = _manifest(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["locked_inputs"][deferred_field] = manifest.validation_rows.model_dump(mode="json")
    path = tmp_path / "aliased-manifest.json"
    path.write_bytes(_canonical_json_value_content(payload) + b"\n")
    reads: list[Path] = []
    original = Path.read_bytes

    def guarded_read(value: Path) -> bytes:
        reads.append(value)
        if value == manifest.validation_rows.path:
            raise AssertionError("aliased deferred input was opened")
        return original(value)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    with pytest.raises(ValueError, match="invalid comparison manifest"):
        read_cli_manifest(path)

    assert reads == [path]
    assert not manifest.workspace_root.exists()

    payload = manifest.model_dump(mode="python")
    payload["locked_inputs"]["gold"]["path"] = payload["locked_inputs"]["rows"]["path"]
    with pytest.raises(ValidationError, match="overlap"):
        LockedComparisonCliManifestV1.model_validate(payload)


def test_manifest_file_must_be_canonical_json(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2))

    with pytest.raises(ValueError, match="canonical"):
        read_cli_manifest(path)


def test_manifest_author_uses_only_predeclared_locked_identity_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    locked = manifest.locked_inputs
    accepted_sidecar = _write_pinned_model(
        locked.accepted_predictions_identity_file.path,
        locked.accepted_predictions.identity,
        artifact_type="row-prediction-identity-record",
        version="row-prediction-identity-v1",
    )
    manifest = manifest.model_copy(
        update={
            "locked_inputs": locked.model_copy(
                update={"accepted_predictions_identity_file": accepted_sidecar}
            )
        }
    )
    row_sidecar = tmp_path / "locked-rows.identity.json"
    gold_sidecar = tmp_path / "locked-gold.identity.json"
    row_sidecar.write_bytes(
        _canonical_json_value_content(locked.rows.identity.model_dump(mode="json")) + b"\n"
    )
    gold_sidecar.write_bytes(
        _canonical_json_value_content(locked.gold.identity.model_dump(mode="json")) + b"\n"
    )
    sidecars = LockedIdentitySidecarsV1(
        version="row-comparison-locked-identity-sidecars-v1",
        rows=row_sidecar,
        gold=gold_sidecar,
        accepted_predictions=accepted_sidecar.path,
    )
    for path, identity in (
        (sidecars.rows, manifest.locked_inputs.rows.identity),
        (sidecars.gold, manifest.locked_inputs.gold.identity),
        (sidecars.accepted_predictions, manifest.locked_inputs.accepted_predictions.identity),
    ):
        path.write_bytes(canonical_model_bytes(identity))
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2))
    sidecars_path = tmp_path / "locked-sidecars.json"
    sidecars_path.write_bytes(
        _canonical_json_value_content(sidecars.model_dump(mode="json")) + b"\n"
    )
    output = tmp_path / "comparison-manifest.json"
    forbidden = {
        locked.rows.path,
        locked.gold.path,
        locked.accepted_predictions.path,
    }
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        if path in forbidden:
            raise AssertionError("deferred locked content was read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    authored = author_cli_manifest(descriptor, sidecars_path, output)

    assert authored == manifest
    assert output.read_bytes() == manifest.canonical_bytes()


def test_manifest_author_preserves_process_interrupts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(_descriptor: Path, _sidecars: Path, _output: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_manifest_author, "author_cli_manifest", interrupt)

    with pytest.raises(KeyboardInterrupt):
        cli_manifest_author.author_command(
            tmp_path / "descriptor.json",
            tmp_path / "sidecars.json",
            tmp_path / "manifest.json",
        )


def test_manifest_author_rejects_outside_paths_before_sidecar_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = _manifest(private)
    descriptor = private / "descriptor.json"
    descriptor.write_bytes(manifest.canonical_bytes())
    sidecars = LockedIdentitySidecarsV1(
        version="row-comparison-locked-identity-sidecars-v1",
        rows=outside / "rows.identity.json",
        gold=outside / "gold.identity.json",
        accepted_predictions=outside / "accepted.identity.json",
    )
    sidecars_path = private / "sidecars.json"
    sidecars_path.write_bytes(canonical_model_bytes(sidecars))
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        if path.is_relative_to(outside):
            raise AssertionError("outside sidecar was opened")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    with pytest.raises(ManifestAuthoringError):
        author_cli_manifest(descriptor, sidecars_path, outside / "manifest.json")


def _git_checkout(root: Path) -> GitCheckoutPin:
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(
        ("git", "config", "user.email", "synthetic@example.invalid"),
        cwd=root,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "Synthetic Test"), cwd=root, check=True)
    (root / "tracked.txt").write_text("synthetic\n")
    subprocess.run(("git", "add", "tracked.txt"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "synthetic"), cwd=root, check=True)
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return GitCheckoutPin(root=root, commit_sha=commit)


def test_checkout_gate_requires_exact_clean_commit(tmp_path: Path) -> None:
    pin = _git_checkout(tmp_path / "checkout")
    verify_git_checkout(pin)

    (pin.root / "tracked.txt").write_text("dirty\n")
    with pytest.raises(ControllerStateError, match="checkout is dirty"):
        verify_git_checkout(pin)


def test_exclusive_stage_refuses_existing_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stage = create_stage(workspace, "locked")
    assert stage == workspace / "locked"

    with pytest.raises(ControllerStateError, match="stage already exists"):
        create_stage(workspace, "locked")


def _profile_checkout(root: Path) -> tuple[ProfileSourcePin, Path]:
    _git_checkout(root)
    package = root / "experiments" / "row_extraction" / "arms" / "profiles"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 'synthetic'\n")
    (package / "arm.py").write_text("ARM = 'synthetic'\n")
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "add profile package"), cwd=root, check=True)
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        (
            "git",
            "rev-parse",
            f"{commit}:experiments/row_extraction/arms/profiles",
        ),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (
        ProfileSourcePin(
            checkout=GitCheckoutPin(root=root, commit_sha=commit),
            package_tree_sha=tree,
        ),
        package,
    )


def test_profile_snapshot_copies_exact_pinned_regular_tree(tmp_path: Path) -> None:
    pin, _package = _profile_checkout(tmp_path / "checkout")
    destination = tmp_path / "snapshot"

    snapshot = snapshot_profile_source(pin, destination)

    assert tuple(value.relative_path for value in snapshot.files) == (
        "__init__.py",
        "arm.py",
    )
    assert reverify_profile_snapshot(pin, destination) == snapshot


def test_profile_snapshot_rejects_dirty_or_unexpected_source(tmp_path: Path) -> None:
    pin, package = _profile_checkout(tmp_path / "checkout")
    (package / "unexpected.py").write_text("UNTRACKED = True\n")

    with pytest.raises(ProfileSourceError, match="source checkout is invalid"):
        snapshot_profile_source(pin, tmp_path / "snapshot")


def _profile_provenance(
    lane: LaneCliInput,
    config: ProfileConfigRecord,
) -> RawProvenanceBinding:
    artifacts = lane.artifacts
    assert artifacts.arm_manifest is not None
    return RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha=artifacts.foundation_sha,
        bundle_identity=artifacts.bundle_identity,
        split_identity=artifacts.split_identity,
        label_identity=artifacts.label_identity,
        config_id=f"row-profiles-v1:{config.version}",
        config_identity=profile_config_identity(config),
        runtime_identity=artifacts.runtime_identity,
        arm_manifest_identity=artifacts.arm_manifest.identity,
        model_inventory_identity=artifacts.model_inventory.identity,
        dependency_inventory_identity=artifacts.dependency_inventory.identity,
        resource_inventory_identities=(
            _identity("0", artifact_type="resource-inventory"),
            _identity("0", artifact_type="resource-inventory"),
        ),
        row_sequence_identity=_identity("d", artifact_type="frozen-row-sequence"),
    )


def test_profile_raw_handoff_authenticates_exact_frozen_references(tmp_path: Path) -> None:
    lane = _manifest(tmp_path).lanes["row-profiles"]
    artifacts = lane.artifacts
    assert artifacts.validation_measurement_envelope is not None
    assert artifacts.arm_manifest is not None
    config = ProfileConfigRecord(version="default", max_continuation_gap="0.75")
    measurement = _run(
        experiment_id="row-profiles",
        config_id="row-profiles-v1:default",
        runtime_identity=artifacts.runtime_identity,
        arm_manifest_identity=artifacts.arm_manifest.identity,
        model_inventory_identity=artifacts.model_inventory.identity,
        dependency_inventory_identity=artifacts.dependency_inventory.identity,
    )
    pair = _write_pinned_model(
        tmp_path / "profile-measurements.json",
        ProfileMeasurementPair(
            version="profile-measurement-pair-v1",
            config="default",
            runs=(measurement, measurement),
            test_accessed=False,
        ),
        artifact_type="run-measurement-pair",
        version="profile-measurement-pair-v1",
    )
    lane = lane.model_copy(
        update={"artifacts": artifacts.model_copy(update={"validation_measurement_envelope": pair})}
    )
    artifacts = lane.artifacts
    provenance = _profile_provenance(lane, config).model_copy(
        update={
            "resource_inventory_identities": (
                measurement.resource_inventory_identity,
                measurement.resource_inventory_identity,
            ),
            "row_sequence_identity": measurement.row_sequence_identity,
        }
    )
    raw = ProfileRawHandoff(
        schema_version="row-profiles-handoff-v2",
        provenance=provenance,
        disposition=LaneDisposition.FROZEN_ELIGIBLE,
        config=config,
        stop_reason=None,
        validation_predictions=artifacts.validation_predictions.identity,
        validation_metrics=artifacts.validation_metrics.identity,
        validation_measurements=artifacts.validation_measurement_envelope.identity,
        determinism=_identity("1", artifact_type="determinism"),
        error_summary=artifacts.validation_error_summary.identity,
        frozen_arm_manifest=artifacts.arm_manifest.identity,
        model_inventory=artifacts.model_inventory.identity,
        dependency_inventory=artifacts.dependency_inventory.identity,
        test_accessed=False,
    )
    raw_pin = _write_pinned_model(
        tmp_path / "row-profiles-handoff.json",
        raw,
        artifact_type="profile-handoff",
        version="profile-v1",
    )
    input_value = lane.model_copy(update={"raw_handoff": raw_pin})

    authenticated = authenticate_lane(input_value)

    assert authenticated.config_id == "row-profiles-v1:default"
    assert authenticated.disposition is LaneDisposition.FROZEN_ELIGIBLE
    assert authenticated.source_generation_replayed is True


@pytest.mark.parametrize(
    "missing_field",
    (
        "foundation_sha",
        "bundle_identity",
        "split_identity",
        "label_identity",
        "config_id",
        "config_identity",
        "runtime_identity",
        "arm_manifest_identity",
        "model_inventory_identity",
        "dependency_inventory_identity",
        "resource_inventory_identities",
        "row_sequence_identity",
    ),
)
def test_raw_provenance_binding_requires_every_authenticated_fact(
    missing_field: str,
) -> None:
    payload = {
        "version": "row-lane-provenance-v1",
        "foundation_sha": "f" * 40,
        "bundle_identity": _identity("1", artifact_type="bundle"),
        "split_identity": _identity("2", artifact_type="split"),
        "label_identity": _identity("3", artifact_type="labels"),
        "config_id": "row-profiles-v1:default",
        "config_identity": _identity("4", artifact_type="config"),
        "runtime_identity": _identity("5", artifact_type="runtime"),
        "arm_manifest_identity": _identity("6", artifact_type="arm-manifest"),
        "model_inventory_identity": _identity("7", artifact_type="model-inventory"),
        "dependency_inventory_identity": _identity("8", artifact_type="dependency-inventory"),
        "resource_inventory_identities": (_identity("9", artifact_type="resource-inventory"),),
        "row_sequence_identity": _identity("a", artifact_type="frozen-row-sequence"),
    }
    del payload[missing_field]

    with pytest.raises(ValidationError):
        RawProvenanceBinding.model_validate(payload)


@pytest.mark.parametrize(
    "label_identity",
    (
        ArtifactIdentity(
            artifact_type="gold-labels",
            sha256="3" * 64,
            version="canonical-jsonl-v1",
            byte_size=1,
        ),
        ArtifactIdentity(
            artifact_type="labels",
            sha256="3" * 64,
            version="legacy-labels-v1",
            byte_size=1,
        ),
    ),
)
def test_raw_provenance_rejects_noncanonical_label_contract(
    label_identity: ArtifactIdentity,
) -> None:
    measurement = _run(
        experiment_id="row-text",
        config_id="row-text:synthetic",
        runtime_identity=_standard_runtime_identity("5"),
    )

    with pytest.raises(ValidationError, match="canonical label identity"):
        RawProvenanceBinding(
            version="row-lane-provenance-v1",
            foundation_sha="f" * 40,
            bundle_identity=_identity("1", artifact_type="bundle"),
            split_identity=_identity("2", artifact_type="split"),
            label_identity=label_identity,
            config_id=measurement.config_id,
            config_identity=_identity("4", artifact_type="config"),
            runtime_identity=measurement.runtime_identity,
            arm_manifest_identity=measurement.arm_manifest_identity,
            model_inventory_identity=measurement.model_inventory_identity,
            dependency_inventory_identity=measurement.dependency_inventory_identity,
            resource_inventory_identities=(measurement.resource_inventory_identity,),
            row_sequence_identity=measurement.row_sequence_identity,
        )


def test_authenticated_lane_evidence_exposes_only_raw_bound_provenance() -> None:
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="f" * 40,
        bundle_identity=_identity("1", artifact_type="bundle"),
        split_identity=_identity("2", artifact_type="split"),
        label_identity=_identity("3", artifact_type="labels"),
        config_id="row-profiles-v1:default",
        config_identity=_identity("4", artifact_type="config"),
        runtime_identity=_identity("5", artifact_type="runtime"),
        arm_manifest_identity=_identity("6", artifact_type="arm-manifest"),
        model_inventory_identity=_identity("7", artifact_type="model-inventory"),
        dependency_inventory_identity=_identity("8", artifact_type="dependency-inventory"),
        resource_inventory_identities=(_identity("9", artifact_type="resource-inventory"),),
        row_sequence_identity=_identity("a", artifact_type="frozen-row-sequence"),
    )
    evidence = AuthenticatedLaneEvidence(
        experiment_id="row-profiles",
        disposition=LaneDisposition.FROZEN_ELIGIBLE,
        stop_reason=None,
        provenance=provenance,
        raw_handoff_identity=_identity("b", artifact_type="raw-handoff"),
        source_commit_sha="c" * 40,
        source_generation_replayed=True,
        provenance_limitation=None,
    )

    assert evidence.config_id == provenance.config_id
    assert evidence.runtime_identity == provenance.runtime_identity


@pytest.mark.parametrize(
    "mismatched_field",
    (
        "foundation_sha",
        "bundle_identity",
        "split_identity",
        "label_identity",
        "runtime_identity",
        "model_inventory_identity",
        "dependency_inventory_identity",
    ),
)
def test_raw_provenance_must_match_located_handoff_artifacts(
    tmp_path: Path,
    mismatched_field: str,
) -> None:
    lane = _manifest(tmp_path).lanes["row-profiles"]
    artifacts = lane.artifacts
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha=artifacts.foundation_sha,
        bundle_identity=artifacts.bundle_identity,
        split_identity=artifacts.split_identity,
        label_identity=artifacts.label_identity,
        config_id="row-profiles-v1:default",
        config_identity=_identity("4", artifact_type="config"),
        runtime_identity=artifacts.runtime_identity,
        arm_manifest_identity=_identity("6", artifact_type="arm-manifest"),
        model_inventory_identity=artifacts.model_inventory.identity,
        dependency_inventory_identity=artifacts.dependency_inventory.identity,
        resource_inventory_identities=(_identity("9", artifact_type="resource-inventory"),),
        row_sequence_identity=_identity("a", artifact_type="frozen-row-sequence"),
    )
    wrong: object
    if mismatched_field == "foundation_sha":
        wrong = "0" * 40
    elif mismatched_field == "runtime_identity":
        wrong = _standard_runtime_identity("0")
    else:
        wrong = _identity("0", artifact_type="wrong")

    with pytest.raises(RawHandoffError, match="raw provenance locator mismatch"):
        authenticate_provenance(
            lane,
            provenance.model_copy(update={mismatched_field: wrong}),
            disposition=LaneDisposition.FROZEN_ELIGIBLE,
            stop_reason=None,
            source_commit_sha=None,
            source_generation_replayed=True,
            provenance_limitation=None,
        )


def test_ocr_v1_handoff_without_raw_provenance_is_rejected() -> None:
    config_identity = _identity("1", artifact_type="row-ocr-config")
    runtime_identity = _standard_runtime_identity("2")
    measurement = _run(
        experiment_id="row-ocr",
        config_id="row-ocr:synthetic",
        runtime_identity=runtime_identity,
    )
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="b" * 40,
        bundle_identity=_identity("7", artifact_type="bundle"),
        split_identity=_identity("8", artifact_type="split"),
        label_identity=_identity("9", artifact_type="labels"),
        config_id=measurement.config_id,
        config_identity=config_identity,
        runtime_identity=runtime_identity,
        arm_manifest_identity=measurement.arm_manifest_identity,
        model_inventory_identity=measurement.model_inventory_identity,
        dependency_inventory_identity=measurement.dependency_inventory_identity,
        resource_inventory_identities=(measurement.resource_inventory_identity,),
        row_sequence_identity=measurement.row_sequence_identity,
    )
    payload = {
        "schema_version": "row-ocr-handoff-v2",
        "experiment_id": "row-ocr",
        "disposition": "validation_stopped",
        "stop_reason": "ocr_stage_validation_failed",
        "config_identity": config_identity,
        "frozen_arm_manifest": None,
        "validation_predictions": _identity("3"),
        "validation_metric_identity": _identity("4", artifact_type="metrics"),
        "validation_metric_report": _metric_report(),
        "validation_measurement_identity": _identity("5", artifact_type="measurement"),
        "validation_measurements": measurement,
        "provenance": provenance,
        "error_summary": _identity("6", artifact_type="error-summary"),
        "determinism": None,
        "accepted_anchor_sha": "a" * 40,
        "foundation_sha": "b" * 40,
        "lane_sha": "c" * 40,
        "runtime_identity": runtime_identity,
        "worker_count": 1,
        "locked_test_status": "not_opened",
    }
    assert OcrRawHandoff.model_validate(payload).provenance == provenance
    legacy = dict(payload)
    legacy["schema_version"] = "row-ocr-handoff-v1"
    del legacy["provenance"]

    with pytest.raises(ValidationError):
        OcrRawHandoff.model_validate(legacy)

    mismatched = dict(payload)
    mismatched["provenance"] = provenance.model_copy(
        update={"runtime_identity": _standard_runtime_identity("0")}
    )
    with pytest.raises(ValidationError, match="provenance"):
        OcrRawHandoff.model_validate(mismatched)


@pytest.mark.parametrize(
    "mismatched_field",
    (
        "experiment_id",
        "config_id",
        "runtime_identity",
        "arm_manifest_identity",
        "model_inventory_identity",
        "dependency_inventory_identity",
        "resource_inventory_identity",
        "row_sequence_identity",
    ),
)
def test_measurements_cannot_supply_or_override_raw_provenance(
    mismatched_field: str,
) -> None:
    measurement = _run(
        experiment_id="row-text",
        config_id="row-text:synthetic",
        runtime_identity=_standard_runtime_identity("3"),
    )
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="b" * 40,
        bundle_identity=_identity("7", artifact_type="bundle"),
        split_identity=_identity("8", artifact_type="split"),
        label_identity=_identity("9", artifact_type="labels"),
        config_id=measurement.config_id,
        config_identity=_identity("0", artifact_type="config"),
        runtime_identity=measurement.runtime_identity,
        arm_manifest_identity=measurement.arm_manifest_identity,
        model_inventory_identity=measurement.model_inventory_identity,
        dependency_inventory_identity=measurement.dependency_inventory_identity,
        resource_inventory_identities=(measurement.resource_inventory_identity,),
        row_sequence_identity=measurement.row_sequence_identity,
    )
    wrong: object = (
        "wrong"
        if mismatched_field in {"experiment_id", "config_id"}
        else _identity("f", artifact_type="wrong")
    )

    with pytest.raises(RawHandoffError, match="measured provenance mismatch"):
        authenticate_measurement_provenance(
            provenance,
            experiment_id="row-text",
            measurements=(measurement.model_copy(update={mismatched_field: wrong}),),
        )


@pytest.mark.parametrize(
    ("experiment_id", "runtime_identity"),
    (
        (
            "row-vision",
            ArtifactIdentity(
                artifact_type="row-runtime-manifest",
                sha256="3" * 64,
                version="row-runtime-manifest-v1",
                byte_size=1,
            ),
        ),
        (
            "row-text",
            ArtifactIdentity(
                artifact_type="runtime-lock",
                sha256="3" * 64,
                version="row-vision-runtime-v1",
                byte_size=1,
            ),
        ),
    ),
)
def test_raw_measurements_reject_cross_lane_runtime_contracts(
    experiment_id: str,
    runtime_identity: ArtifactIdentity,
) -> None:
    measurement = _run(
        experiment_id=experiment_id,
        config_id=f"{experiment_id}:synthetic",
        runtime_identity=runtime_identity,
    )
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="b" * 40,
        bundle_identity=_identity("7", artifact_type="bundle"),
        split_identity=_identity("8", artifact_type="split"),
        label_identity=_identity("9", artifact_type="labels"),
        config_id=measurement.config_id,
        config_identity=_identity("0", artifact_type="config"),
        runtime_identity=runtime_identity,
        arm_manifest_identity=measurement.arm_manifest_identity,
        model_inventory_identity=measurement.model_inventory_identity,
        dependency_inventory_identity=measurement.dependency_inventory_identity,
        resource_inventory_identities=(measurement.resource_inventory_identity,),
        row_sequence_identity=measurement.row_sequence_identity,
    )

    with pytest.raises(RawHandoffError, match="runtime identity contract mismatch"):
        authenticate_measurement_provenance(
            provenance,
            experiment_id=experiment_id,
            measurements=(measurement,),
        )


def test_raw_vision_provenance_rejects_generic_outer_runtime_locator(tmp_path: Path) -> None:
    truthful_lane = _manifest(tmp_path).lanes["row-vision"]
    lane = truthful_lane.model_copy(
        update={
            "artifacts": truthful_lane.artifacts.model_copy(
                update={"runtime_identity": _standard_runtime_identity("4")}
            )
        }
    )
    artifacts = lane.artifacts
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha=artifacts.foundation_sha,
        bundle_identity=artifacts.bundle_identity,
        split_identity=artifacts.split_identity,
        label_identity=artifacts.label_identity,
        config_id="row-vision:synthetic",
        config_identity=_identity("0", artifact_type="row-vision-config"),
        runtime_identity=artifacts.runtime_identity,
        arm_manifest_identity=_identity("1", artifact_type="arm-manifest"),
        model_inventory_identity=artifacts.model_inventory.identity,
        dependency_inventory_identity=artifacts.dependency_inventory.identity,
        resource_inventory_identities=(_identity("2", artifact_type="resource-inventory"),),
        row_sequence_identity=_identity("3", artifact_type="frozen-row-sequence"),
    )

    with pytest.raises(RawHandoffError, match="runtime identity contract mismatch"):
        authenticate_provenance(
            lane,
            provenance,
            disposition=LaneDisposition.VALIDATION_STOPPED,
            stop_reason="no_pixel_gain",
            source_commit_sha=None,
            source_generation_replayed=False,
            provenance_limitation="stopped_source_generation_not_replayable",
        )


def test_text_v1_handoff_without_raw_provenance_is_rejected() -> None:
    measurement = _run(
        experiment_id="row-text",
        config_id="row-text:synthetic",
        runtime_identity=_standard_runtime_identity("3"),
    )
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="b" * 40,
        bundle_identity=_identity("7", artifact_type="bundle"),
        split_identity=_identity("8", artifact_type="split"),
        label_identity=_identity("9", artifact_type="labels"),
        config_id=measurement.config_id,
        config_identity=_identity("0", artifact_type="row-text-config"),
        runtime_identity=measurement.runtime_identity,
        arm_manifest_identity=measurement.arm_manifest_identity,
        model_inventory_identity=measurement.model_inventory_identity,
        dependency_inventory_identity=measurement.dependency_inventory_identity,
        resource_inventory_identities=(measurement.resource_inventory_identity,),
        row_sequence_identity=measurement.row_sequence_identity,
    )
    current = TextRawHandoff(
        disposition=LaneDisposition.VALIDATION_STOPPED,
        files={"synthetic.json": TextFileDigest(byte_size=1, sha256="1" * 64)},
        provenance=provenance,
        stop_reason="no_text_candidate_met_validation_gate",
        test_accessed=False,
        version="row-text-handoff-v2",
    ).model_dump(mode="python")
    legacy = dict(current)
    legacy["version"] = "row-text-handoff-v1"
    del legacy["provenance"]
    del legacy["test_accessed"]

    with pytest.raises(ValidationError):
        TextRawHandoff.model_validate(legacy)


def test_vision_v1_handoff_without_raw_provenance_is_rejected() -> None:
    measurement = _run(
        experiment_id="row-vision",
        config_id="a" * 64,
        runtime_identity=_vision_runtime_identity("3"),
    )
    provenance = RawProvenanceBinding(
        version="row-lane-provenance-v1",
        foundation_sha="b" * 40,
        bundle_identity=_identity("7", artifact_type="bundle"),
        split_identity=_identity("8", artifact_type="split"),
        label_identity=_identity("9", artifact_type="labels"),
        config_id=measurement.config_id,
        config_identity=ArtifactIdentity(
            artifact_type="row-vision-config",
            sha256="0" * 64,
            version="row-vision-trained-v1",
            byte_size=1,
        ),
        runtime_identity=measurement.runtime_identity,
        arm_manifest_identity=measurement.arm_manifest_identity,
        model_inventory_identity=measurement.model_inventory_identity,
        dependency_inventory_identity=measurement.dependency_inventory_identity,
        resource_inventory_identities=(measurement.resource_inventory_identity,),
        row_sequence_identity=measurement.row_sequence_identity,
    )
    current = VisionRawHandoff(
        schema_version="row-vision-handoff-v2",
        provenance=provenance,
        accepted_sha="a" * 40,
        experiment_id="row-vision",
        disposition=LaneDisposition.VALIDATION_STOPPED,
        stop_reason="no_pixel_gain",
        pixels_on_config_id=measurement.config_id,
        pixels_off_config_id="b" * 64,
        pixels_off_config_identity=ArtifactIdentity(
            artifact_type="row-vision-config",
            sha256="f" * 64,
            version="row-vision-trained-v1",
            byte_size=1,
        ),
        artifact_identities=(_identity("1", artifact_type="vision-artifact"),),
        train_manifest_identity=_identity("2", artifact_type="train-manifest"),
        validation_manifest_identity=_identity("3", artifact_type="validation-manifest"),
        validation_predictions_sha256_first="4" * 64,
        validation_predictions_sha256_second="4" * 64,
        validation_metric_identity=_identity("5", artifact_type="metric"),
        validation_metric_report=_metric_report(),
        validation_measurements=measurement,
        pixel_gate_evidence=_identity("6", artifact_type="pixel-gate"),
        frozen_arm_manifest=None,
        owner_none_means_current=True,
        test_accessed=False,
    ).model_dump(mode="python")
    assert current["accepted_sha"] != provenance.foundation_sha
    same_foundation = dict(current)
    same_foundation["accepted_sha"] = provenance.foundation_sha

    with pytest.raises(ValidationError, match="vision handoff provenance mismatch"):
        VisionRawHandoff.model_validate(same_foundation)

    legacy = dict(current)
    del legacy["schema_version"]
    del legacy["provenance"]
    del legacy["pixels_off_config_identity"]

    with pytest.raises(ValidationError):
        VisionRawHandoff.model_validate(legacy)


def test_profile_raw_handoff_rejects_identity_alias_or_extra_field(tmp_path: Path) -> None:
    lane = _manifest(tmp_path).lanes["row-profiles"]
    artifacts = lane.artifacts
    assert artifacts.validation_measurement_envelope is not None
    assert artifacts.arm_manifest is not None
    payload = {
        "schema_version": "row-profiles-handoff-v2",
        "provenance": _profile_provenance(
            lane,
            ProfileConfigRecord(version="default", max_continuation_gap="0.75"),
        ).model_dump(mode="json"),
        "config": {"max_continuation_gap": "0.75", "version": "default"},
        "dependency_inventory": artifacts.dependency_inventory.identity.model_dump(mode="json"),
        "determinism": _identity("1", artifact_type="determinism").model_dump(mode="json"),
        "disposition": "frozen_eligible",
        "error_summary": artifacts.validation_error_summary.identity.model_dump(mode="json"),
        "frozen_arm_manifest": artifacts.arm_manifest.identity.model_dump(mode="json"),
        "model_inventory": artifacts.model_inventory.identity.model_dump(mode="json"),
        "stop_reason": None,
        "test_accessed": False,
        "unexpected": True,
        "validation_measurements": artifacts.validation_measurement_envelope.identity.model_dump(
            mode="json"
        ),
        "validation_metrics": artifacts.validation_metrics.identity.model_dump(mode="json"),
        "validation_predictions": artifacts.validation_predictions.identity.model_dump(mode="json"),
    }
    raw_path = tmp_path / "invalid-profile-handoff.json"
    raw_path.write_bytes(_canonical_json_value_content(payload) + b"\n")
    raw_pin = PinnedArtifact(
        path=raw_path,
        identity=ArtifactIdentity(
            artifact_type="profile-handoff",
            sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            version="profile-v1",
            byte_size=raw_path.stat().st_size,
        ),
    )

    with pytest.raises(RawHandoffError, match="raw handoff is invalid"):
        authenticate_lane(lane.model_copy(update={"raw_handoff": raw_pin}))


def test_profile_v1_handoff_without_raw_provenance_is_rejected(tmp_path: Path) -> None:
    lane = _manifest(tmp_path).lanes["row-profiles"]
    artifacts = lane.artifacts
    assert artifacts.validation_measurement_envelope is not None
    assert artifacts.arm_manifest is not None
    legacy = {
        "disposition": LaneDisposition.FROZEN_ELIGIBLE,
        "config": ProfileConfigRecord(version="default", max_continuation_gap="0.75"),
        "stop_reason": None,
        "validation_predictions": artifacts.validation_predictions.identity,
        "validation_metrics": artifacts.validation_metrics.identity,
        "validation_measurements": artifacts.validation_measurement_envelope.identity,
        "determinism": _identity("1", artifact_type="determinism"),
        "error_summary": artifacts.validation_error_summary.identity,
        "frozen_arm_manifest": artifacts.arm_manifest.identity,
        "model_inventory": artifacts.model_inventory.identity,
        "dependency_inventory": artifacts.dependency_inventory.identity,
        "test_accessed": False,
    }

    with pytest.raises(ValidationError):
        ProfileRawHandoff.model_validate(legacy)


def test_cli_registers_the_exact_five_controller_commands() -> None:
    result = runner.invoke(comparison_cli.app, ["--help"])

    assert result.exit_code == 0
    assert all(
        command in result.stdout
        for command in (
            "validate-handoffs",
            "select-cascade-validation",
            "compare-locked",
            "evaluate-cascade-locked",
            "recommend",
        )
    )


def test_cli_failure_prints_only_stable_aggregate_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "document-secret.jsonl"

    def fail(_manifest: Path) -> dict[str, object]:
        raise RuntimeError(f"sensitive path {secret}")

    monkeypatch.setattr(comparison_cli, "validate_handoffs_stage", fail)
    result = runner.invoke(
        comparison_cli.app,
        ["validate-handoffs", "--manifest", str(tmp_path / "manifest.json")],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "ROW_COMPARISON_HANDOFF_ERROR\n"
    assert str(secret) not in result.output


def test_cli_rejects_private_fields_in_a_success_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "private-source-name.jsonl"

    def unsafe(_manifest: Path) -> dict[str, object]:
        return {
            "command": "validate-handoffs",
            "complete": True,
            "eligible_lane_count": 1,
            "private_path": str(secret),
            "stopped_lane_count": 3,
        }

    monkeypatch.setattr(comparison_cli, "validate_handoffs_stage", unsafe)
    result = runner.invoke(
        comparison_cli.app,
        ["validate-handoffs", "--manifest", str(tmp_path / "manifest.json")],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "ROW_COMPARISON_HANDOFF_ERROR\n"
    assert str(secret) not in result.output


@pytest.mark.parametrize(
    ("command", "stage_name", "aggregate"),
    (
        (
            "validate-handoffs",
            "validate_handoffs_stage",
            {
                "command": "validate-handoffs",
                "complete": True,
                "eligible_lane_count": 1,
                "stopped_lane_count": 3,
            },
        ),
        (
            "select-cascade-validation",
            "select_cascade_validation_stage",
            {
                "candidate_policy_count": 0,
                "command": "select-cascade-validation",
                "complete": True,
                "rule_count": 0,
            },
        ),
        (
            "compare-locked",
            "compare_locked_stage",
            {
                "command": "compare-locked",
                "complete": True,
                "deterministic_result_count": 4,
                "locked_result_count": 4,
                "stopped_result_count": 3,
            },
        ),
        (
            "evaluate-cascade-locked",
            "evaluate_cascade_locked_stage",
            {
                "candidate_policy_count": 0,
                "command": "evaluate-cascade-locked",
                "complete": True,
                "extraction_run_count": 0,
            },
        ),
        (
            "recommend",
            "recommend_stage",
            {
                "candidate_count": 1,
                "cascade_candidate_count": 0,
                "command": "recommend",
                "complete": True,
                "decision": "no_production_change",
                "reason_codes": ("no_eligible_positive_locked_gain",),
                "selected_ids": (),
            },
        ),
    ),
)
def test_all_success_outputs_are_closed_aggregate_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    stage_name: str,
    aggregate: dict[str, object],
) -> None:
    monkeypatch.setattr(comparison_cli, stage_name, lambda _manifest: aggregate)
    result = runner.invoke(
        comparison_cli.app,
        [command, "--manifest", str(tmp_path / "private-manifest.json")],
    )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert not re.search(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b", result.stdout)
    assert "/" not in result.stdout
    assert all(
        token not in result.stdout
        for token in ("document", "row_id", "merchant", "amount", "2026-", "private-manifest")
    )


def test_locked_schedule_is_exactly_eight_runs_and_four_preparations(tmp_path: Path) -> None:
    events: list[tuple[object, ...]] = []

    class Backend:
        def prepare(self, paths: LockedRunPaths) -> str:
            events.append(("prepare", paths.experiment_id, paths.run_number, paths))
            return f"preparation:{paths.experiment_id}:{paths.run_number}"

        def run(self, paths: LockedRunPaths, preparation: str | None) -> str:
            events.append(("run", paths.experiment_id, paths.run_number, preparation, paths))
            return f"run:{paths.experiment_id}:{paths.run_number}"

        def assert_page_evidence(self, first: str, second: str) -> None:
            events.append(("page-repeat", first, second))

        def assert_predictions(self, first: str, second: str) -> None:
            events.append(("prediction-repeat", first, second))

    pairs = execute_locked_schedule(tmp_path / "arms", Backend())

    assert tuple(pairs) == (
        "accepted-baseline",
        "conditional-page-ocr",
        "forced-page-ocr",
        "row-profiles",
    )
    assert [(event[1], event[2]) for event in events if event[0] == "run"] == [
        ("accepted-baseline", 1),
        ("accepted-baseline", 2),
        ("conditional-page-ocr", 1),
        ("conditional-page-ocr", 2),
        ("forced-page-ocr", 1),
        ("forced-page-ocr", 2),
        ("row-profiles", 1),
        ("row-profiles", 2),
    ]
    assert len([event for event in events if event[0] == "prepare"]) == 4
    assert len([event for event in events if event[0] == "page-repeat"]) == 2
    assert len([event for event in events if event[0] == "prediction-repeat"]) == 4
    paths = [event[4] for event in events if event[0] == "run"]
    assert len({path.run_cache for path in paths}) == 8
    assert len({path.resource_inventory for path in paths}) == 8
    assert len({path.predictions for path in paths}) == 8
    assert len({path.measurements for path in paths}) == 8


def test_locked_marker_precedes_every_deferred_input_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    manifest.workspace_root.mkdir()
    reads: list[Path] = []

    def refuse_after_observing_marker(artifact: PinnedArtifact, _message: str) -> bytes:
        assert (manifest.workspace_root / "locked" / "start-receipt.json").is_file()
        reads.append(artifact.path)
        raise RuntimeError("synthetic stop")

    monkeypatch.setattr(
        "experiments.row_extraction.comparison.cli_locked.verified_bytes",
        refuse_after_observing_marker,
    )

    with pytest.raises(RuntimeError, match="synthetic stop"):
        start_and_read_locked_inputs(
            manifest,
            comparison_manifest_identity=_identity("a", artifact_type="comparison-manifest"),
            validation_receipt_identity=_identity("b", artifact_type="validation-receipt"),
            policy_identity=_identity("c", artifact_type="cascade-policy"),
        )

    assert reads == [manifest.locked_inputs.rows.path]


def test_page_preparation_repeat_binds_generated_evidence_bytes(tmp_path: Path) -> None:
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    first_path.write_bytes(b"synthetic-page-evidence\n")
    second_path.write_bytes(first_path.read_bytes())
    identity = ArtifactIdentity(
        artifact_type="jsonl",
        sha256=hashlib.sha256(first_path.read_bytes()).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=first_path.stat().st_size,
    )
    first = PreparedPage(first_path, identity, object())
    second = PreparedPage(second_path, identity, object())

    assert_preparation_repeat(first, second)

    second_path.write_bytes(b"changed-page-evidence\n")
    with pytest.raises(LockedExecutionError, match="page evidence repeat mismatch"):
        assert_preparation_repeat(first, second)


def test_empty_cascade_is_derived_without_an_extraction_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = FrozenRow(
        document_id="0" * 64,
        row_id="row-1",
        split=DatasetSplit.TEST,
        source_pdf=tmp_path / "synthetic.pdf",
        page_number=1,
        bbox=(0.0, 0.0, 10.0, 10.0),
        baseline_type=RowType.PRIMARY_TRANSACTION,
        column_bands=(),
        atoms=(),
        render_version="synthetic-v1",
    )

    def prediction(experiment_id: str) -> RowPrediction:
        return RowPrediction(
            experiment_id=experiment_id,
            config_id=f"{experiment_id}-v1",
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=row.baseline_type,
            evidence_atoms=(),
            proposals=(),
            decision=Decision.ABSTAIN,
            reasons=("synthetic_abstention",),
        )

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("run_arm must not be called")

    monkeypatch.setattr("experiments.row_extraction.runner.run_arm", forbidden)
    derived = derive_empty_cascade(
        (row,),
        (prediction("accepted-baseline"),),
        (prediction("row-profiles"),),
        {"row-profiles": LaneDisposition.FROZEN_ELIGIBLE},
    )

    assert len(derived) == 1
    assert derived[0].experiment_id == "row-cascade"
    assert derived[0].decision is Decision.ABSTAIN
