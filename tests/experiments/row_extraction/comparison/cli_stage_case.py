from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel

from experiments.row_extraction.baselines import page_arm_config_id
from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.comparison.cli_adapters import (
    OcrRawHandoff,
    ProfileConfigRecord,
    ProfileMeasurementPair,
    ProfileRawHandoff,
    RawProvenanceBinding,
    TextFileDigest,
    TextRawHandoff,
    VisionRawHandoff,
    profile_config_identity,
)
from experiments.row_extraction.comparison.cli_manifest import (
    BASELINE_INPUT_IDS,
    LANE_INPUT_IDS,
    BaselineCliInput,
    DeferredLockedInputs,
    HandoffArtifacts,
    LaneCliInput,
    LockedComparisonCliManifestV1,
    PinnedArtifact,
)
from experiments.row_extraction.comparison.cli_normalize_contracts import (
    NormalizationReceipt,
    NormalizedArmSnapshot,
    NormalizedProgram,
    NormalizedProgramSnapshot,
)
from experiments.row_extraction.comparison.cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
)
from experiments.row_extraction.comparison.handoff_contracts import (
    ArtifactFile,
    BaselineHandoff,
    ComparisonManifest,
    FrozenArmFactoryLoader,
    FrozenArmInput,
    LaneHandoff,
)
from experiments.row_extraction.comparison.profile_loader import ProfileLaneAdapter
from experiments.row_extraction.comparison.result_catalog import BaselineId
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    Decision,
    FieldProposal,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import (
    MeasuredArmFactory,
    ResourceSpec,
    RunMeasurements,
)
from experiments.row_extraction.split import DocumentMembership, SplitManifest
from tests.experiments.row_extraction.comparison.test_handoffs import (
    _manifest as source_handoff_manifest,
)
from tests.experiments.row_extraction.comparison.test_handoffs import _metric
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row

from .test_cli import _git_checkout, _identity, _profile_checkout, _write_pinned_model


def _pin(value: ArtifactFile) -> PinnedArtifact:
    return PinnedArtifact(path=value.path, identity=value.identity)


def _model_artifact(
    path: Path,
    value: BaseModel,
    *,
    artifact_type: str,
    version: str,
) -> ArtifactFile:
    payload = canonical_model_bytes(value)
    path.write_bytes(payload)
    return ArtifactFile(
        path=path,
        identity=identity_for_bytes(payload, artifact_type=artifact_type, version=version),
    )


class _Predictor(Protocol):
    def predict(self, row: FrozenRow) -> RowPrediction: ...


class _ArmOverride:
    def __init__(self, source: _Predictor, *, config_id: str, no_confidence: bool) -> None:
        self._source = source
        self._config_id = config_id
        self._no_confidence = no_confidence

    def predict(self, row: FrozenRow) -> RowPrediction:
        prediction = self._source.predict(row)
        return prediction.model_copy(
            update={
                "config_id": self._config_id,
                "exact_row_confidence": None
                if self._no_confidence
                else prediction.exact_row_confidence,
            }
        )


class _FactoryOverride:
    def __init__(self, source: MeasuredArmFactory, *, config_id: str, no_confidence: bool) -> None:
        self._source = source
        self._config_id = config_id
        self._no_confidence = no_confidence

    def __getattr__(self, name: str) -> object:
        return getattr(self._source, name)

    @property
    def config_id(self) -> str:
        return self._config_id

    def build(self) -> _ArmOverride:
        return _ArmOverride(
            self._source.build(),
            config_id=self._config_id,
            no_confidence=self._no_confidence,
        )


def _adapt_handoff(
    root: Path,
    value: BaselineHandoff | LaneHandoff,
    rows: tuple[FrozenRow, ...],
    *,
    config_id: str,
    no_confidence: bool,
) -> BaselineHandoff | LaneHandoff:
    predictions = tuple(
        RowPrediction.model_validate_json(line).model_copy(
            update={
                "config_id": config_id,
                "exact_row_confidence": None if no_confidence else 1.0,
            }
        )
        for line in value.validation_predictions.path.read_bytes().splitlines()
    )
    predictions_path = root / f"{value.experiment_id}-adapted-validation.jsonl"
    prediction_identity = write_jsonl(predictions_path, predictions)
    prediction_file = ArtifactFile(predictions_path, prediction_identity)
    metrics = _model_artifact(
        root / f"{value.experiment_id}-adapted-metrics.json",
        _metric(rows, predictions),
        artifact_type="row-comparison-validation-metrics",
        version="row-comparison-validation-metrics-v1",
    )
    old_measurement = RunMeasurements.model_validate_json(
        value.validation_measurements[0].path.read_bytes()
    )
    measurement = _model_artifact(
        root / f"{value.experiment_id}-adapted-measurement.json",
        old_measurement.model_copy(
            update={"config_id": config_id, "predictions_sha256": prediction_identity.sha256}
        ),
        artifact_type="row-comparison-validation-measurements",
        version="row-comparison-validation-measurements-v1",
    )
    frozen = value.frozen_arm
    assert frozen is not None
    original_loader = frozen.factory_loader

    def load(
        loaded_rows: tuple[FrozenRow, ...],
        row_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory:
        source = original_loader(loaded_rows, row_identity, cache_root)
        return cast(
            MeasuredArmFactory,
            _FactoryOverride(source, config_id=config_id, no_confidence=no_confidence),
        )

    return replace(
        value,
        config_id=config_id,
        validation_predictions=prediction_file,
        validation_metrics=metrics,
        validation_measurements=(measurement,),
        frozen_arm=replace(frozen, factory_loader=cast(FrozenArmFactoryLoader, load)),
    )


def _normalized_manifest(
    root: Path,
    *,
    locked_split: DatasetSplit,
) -> ComparisonManifest:
    root.mkdir()
    source = source_handoff_manifest(
        root,
        stopped=frozenset({"row-ocr", "row-text", "row-vision"}),
    )
    rows = tuple(
        FrozenRow.model_validate_json(line)
        for line in source.validation_rows.path.read_bytes().splitlines()
    )
    baselines = dict(source.baselines)
    for experiment_id in ("conditional-page-ocr", "forced-page-ocr"):
        adapted = _adapt_handoff(
            root,
            baselines[experiment_id],
            rows,
            config_id=page_arm_config_id(f"synthetic-{experiment_id}-provider-v1"),
            no_confidence=False,
        )
        assert isinstance(adapted, BaselineHandoff)
        baselines[experiment_id] = adapted
    lanes = dict(source.lanes)
    adapted_profile = _adapt_handoff(
        root,
        lanes["row-profiles"],
        rows,
        config_id="row-profiles-v1:default",
        no_confidence=True,
    )
    assert isinstance(adapted_profile, LaneHandoff)
    lanes["row-profiles"] = adapted_profile
    split = _model_artifact(
        root / "synthetic-split-manifest.json",
        SplitManifest(
            seed="synthetic",
            version="row-extraction-split-v1",
            memberships=tuple(
                DocumentMembership(
                    document_id=document_id,
                    split=split_value,
                    atomic_unit=atomic_unit,
                    stratum="synthetic",
                )
                for document_id, split_value, atomic_unit in (
                    ("a" * 64, DatasetSplit.VALIDATION, "validation-a"),
                    ("b" * 64, DatasetSplit.VALIDATION, "validation-b"),
                    ("c" * 64, locked_split, "locked-c"),
                    ("d" * 64, locked_split, "locked-d"),
                )
            ),
        ),
        artifact_type="row-split-manifest",
        version="row-extraction-split-v1",
    )
    baselines = {
        key: replace(value, split_identity=split.identity) for key, value in baselines.items()
    }
    lanes = {key: replace(value, split_identity=split.identity) for key, value in lanes.items()}
    return replace(
        source,
        split_identity=split.identity,
        baselines=baselines,
        lanes=lanes,
    )


def _artifacts(value: BaselineHandoff | LaneHandoff) -> HandoffArtifacts:
    return HandoffArtifacts(
        foundation_sha=value.foundation_sha,
        bundle_identity=value.bundle_identity,
        split_identity=value.split_identity,
        label_identity=value.label_identity,
        runtime_identity=value.runtime_identity,
        model_inventory=_pin(value.model_inventory),
        dependency_inventory=_pin(value.dependency_inventory),
        validation_predictions=_pin(value.validation_predictions),
        validation_metrics=_pin(value.validation_metrics),
        validation_measurements=tuple(_pin(item) for item in value.validation_measurements),
        validation_error_summary=(
            None if value.validation_error_summary is None else _pin(value.validation_error_summary)
        ),
        arm_manifest=(None if value.frozen_arm is None else _pin(value.frozen_arm.arm_manifest)),
    )


def _read_metric(value: BaselineHandoff | LaneHandoff) -> MetricReport:
    return MetricReport.model_validate_json(value.validation_metrics.path.read_bytes())


def _read_measurement(value: BaselineHandoff | LaneHandoff) -> RunMeasurements:
    return RunMeasurements.model_validate_json(value.validation_measurements[0].path.read_bytes())


def _raw_lane_inputs(
    root: Path,
    core: ComparisonManifest,
) -> dict[str, LaneCliInput]:
    inputs: dict[str, LaneCliInput] = {}
    profile = core.lanes["row-profiles"]
    profile_artifacts = _artifacts(profile).model_copy(update={"validation_measurements": ()})
    profile_measurement = _read_measurement(profile)
    profile_config = ProfileConfigRecord(
        version="default",
        max_continuation_gap=Decimal("0.75"),
    )
    envelope = _write_pinned_model(
        root / "row-profiles-measurement-envelope.json",
        ProfileMeasurementPair(
            version="profile-measurement-pair-v1",
            config="default",
            test_accessed=False,
            runs=(profile_measurement, profile_measurement),
        ),
        artifact_type="run-measurement-pair",
        version="profile-measurement-pair-v1",
    )
    profile_artifacts = profile_artifacts.model_copy(
        update={"validation_measurement_envelope": envelope}
    )
    raw_profile = _write_pinned_model(
        root / "row-profiles-handoff.json",
        ProfileRawHandoff(
            schema_version="row-profiles-handoff-v2",
            provenance=RawProvenanceBinding(
                version="row-lane-provenance-v1",
                foundation_sha=core.foundation_sha,
                bundle_identity=core.bundle_identity,
                split_identity=core.split_identity,
                label_identity=core.label_identity,
                config_id=profile.config_id,
                config_identity=profile_config_identity(profile_config),
                runtime_identity=profile_measurement.runtime_identity,
                arm_manifest_identity=profile_measurement.arm_manifest_identity,
                model_inventory_identity=profile_measurement.model_inventory_identity,
                dependency_inventory_identity=(profile_measurement.dependency_inventory_identity),
                resource_inventory_identities=(
                    profile_measurement.resource_inventory_identity,
                    profile_measurement.resource_inventory_identity,
                ),
                row_sequence_identity=profile_measurement.row_sequence_identity,
            ),
            disposition=LaneDisposition.FROZEN_ELIGIBLE,
            config=profile_config,
            stop_reason=None,
            validation_predictions=profile.validation_predictions.identity,
            validation_metrics=profile.validation_metrics.identity,
            validation_measurements=envelope.identity,
            determinism=_identity("e", artifact_type="determinism"),
            error_summary=cast(ArtifactFile, profile.validation_error_summary).identity,
            frozen_arm_manifest=cast(FrozenArmInput, profile.frozen_arm).arm_manifest.identity,
            model_inventory=profile.model_inventory.identity,
            dependency_inventory=profile.dependency_inventory.identity,
            test_accessed=False,
        ),
        artifact_type="profile-handoff",
        version="profile-v1",
    )
    inputs["row-profiles"] = LaneCliInput(
        experiment_id="row-profiles",
        schema_kind="profiles_v2",
        raw_handoff=raw_profile,
        artifacts=profile_artifacts,
        validation_replay_cache_root=root / "workspace" / "prelock" / "replay" / "row-profiles",
    )

    ocr = core.lanes["row-ocr"]
    ocr_artifacts = _artifacts(ocr)
    ocr_measurement = _read_measurement(ocr)
    ocr_config_identity = _identity("0", artifact_type="row-ocr-config")
    raw_ocr = _write_pinned_model(
        root / "row-ocr-handoff.json",
        OcrRawHandoff(
            schema_version="row-ocr-handoff-v2",
            experiment_id="row-ocr",
            disposition=LaneDisposition.VALIDATION_STOPPED,
            stop_reason="ocr_stage_validation_failed",
            config_identity=ocr_config_identity,
            frozen_arm_manifest=None,
            validation_predictions=ocr.validation_predictions.identity,
            validation_metric_identity=ocr.validation_metrics.identity,
            validation_metric_report=_read_metric(ocr),
            validation_measurement_identity=ocr.validation_measurements[0].identity,
            validation_measurements=ocr_measurement,
            provenance=RawProvenanceBinding(
                version="row-lane-provenance-v1",
                foundation_sha=core.foundation_sha,
                bundle_identity=core.bundle_identity,
                split_identity=core.split_identity,
                label_identity=core.label_identity,
                config_id=ocr_measurement.config_id,
                config_identity=ocr_config_identity,
                runtime_identity=ocr_measurement.runtime_identity,
                arm_manifest_identity=ocr_measurement.arm_manifest_identity,
                model_inventory_identity=ocr_measurement.model_inventory_identity,
                dependency_inventory_identity=(ocr_measurement.dependency_inventory_identity),
                resource_inventory_identities=(ocr_measurement.resource_inventory_identity,),
                row_sequence_identity=ocr_measurement.row_sequence_identity,
            ),
            error_summary=cast(ArtifactFile, ocr.validation_error_summary).identity,
            determinism=None,
            accepted_anchor_sha="a" * 40,
            foundation_sha=core.foundation_sha,
            lane_sha="b" * 40,
            runtime_identity=ocr.runtime_identity,
            worker_count=1,
            locked_test_status="not_opened",
        ),
        artifact_type="ocr-handoff",
        version="ocr-v1",
    )
    inputs["row-ocr"] = LaneCliInput(
        experiment_id="row-ocr",
        schema_kind="ocr_stop_v2",
        raw_handoff=raw_ocr,
        artifacts=ocr_artifacts,
    )

    text = core.lanes["row-text"]
    text_artifacts = _artifacts(text)
    text_measurement = _read_measurement(text)
    duplicate = _write_pinned_model(
        root / "row-text-repeat-measurement.json",
        text_measurement,
        artifact_type="row-comparison-validation-measurements",
        version="row-comparison-validation-measurements-v1",
    )
    text_artifacts = text_artifacts.model_copy(
        update={"validation_measurements": (*text_artifacts.validation_measurements, duplicate)}
    )
    located = (
        text_artifacts.model_inventory,
        text_artifacts.dependency_inventory,
        text_artifacts.validation_predictions,
        text_artifacts.validation_metrics,
        *text_artifacts.validation_measurements,
        cast(PinnedArtifact, text_artifacts.validation_error_summary),
    )
    raw_text = _write_pinned_model(
        root / "row-text-handoff.json",
        TextRawHandoff(
            disposition=LaneDisposition.VALIDATION_STOPPED,
            files={
                item.path.name: TextFileDigest(
                    byte_size=item.identity.byte_size,
                    sha256=item.identity.sha256,
                )
                for item in located
            },
            provenance=RawProvenanceBinding(
                version="row-lane-provenance-v1",
                foundation_sha=core.foundation_sha,
                bundle_identity=core.bundle_identity,
                split_identity=core.split_identity,
                label_identity=core.label_identity,
                config_id=text_measurement.config_id,
                config_identity=_identity("0", artifact_type="row-text-config"),
                runtime_identity=text_measurement.runtime_identity,
                arm_manifest_identity=text_measurement.arm_manifest_identity,
                model_inventory_identity=text_measurement.model_inventory_identity,
                dependency_inventory_identity=(text_measurement.dependency_inventory_identity),
                resource_inventory_identities=(
                    text_measurement.resource_inventory_identity,
                    text_measurement.resource_inventory_identity,
                ),
                row_sequence_identity=text_measurement.row_sequence_identity,
            ),
            stop_reason="no_text_candidate_met_validation_gate",
            test_accessed=False,
            version="row-text-handoff-v2",
        ),
        artifact_type="text-handoff",
        version="text-v1",
    )
    inputs["row-text"] = LaneCliInput(
        experiment_id="row-text",
        schema_kind="text_stop_v2",
        raw_handoff=raw_text,
        artifacts=text_artifacts,
        source_commit_sha="c" * 40,
    )

    vision = core.lanes["row-vision"]
    vision_artifacts = _artifacts(vision)
    vision_measurement = _read_measurement(vision)
    raw_vision = _write_pinned_model(
        root / "row-vision-handoff.json",
        VisionRawHandoff(
            schema_version="row-vision-handoff-v2",
            provenance=RawProvenanceBinding(
                version="row-lane-provenance-v1",
                foundation_sha=core.foundation_sha,
                bundle_identity=core.bundle_identity,
                split_identity=core.split_identity,
                label_identity=core.label_identity,
                config_id=vision_measurement.config_id,
                config_identity=_identity("0", artifact_type="row-vision-config"),
                runtime_identity=vision_measurement.runtime_identity,
                arm_manifest_identity=vision_measurement.arm_manifest_identity,
                model_inventory_identity=vision_measurement.model_inventory_identity,
                dependency_inventory_identity=(vision_measurement.dependency_inventory_identity),
                resource_inventory_identities=(vision_measurement.resource_inventory_identity,),
                row_sequence_identity=vision_measurement.row_sequence_identity,
            ),
            accepted_sha="a" * 40,
            experiment_id="row-vision",
            disposition=LaneDisposition.VALIDATION_STOPPED,
            stop_reason="no_pixel_gain",
            pixels_on_config_id=vision_measurement.config_id,
            pixels_off_config_id="pixels-off",
            pixels_off_config_identity=ArtifactIdentity(
                artifact_type="row-vision-config",
                sha256="1" * 64,
                version="row-vision-trained-v1",
                byte_size=1,
            ),
            artifact_identities=(vision.validation_predictions.identity,),
            train_manifest_identity=_identity("1", artifact_type="train-manifest"),
            validation_manifest_identity=_identity("2", artifact_type="validation-manifest"),
            validation_predictions_sha256_first=vision.validation_predictions.identity.sha256,
            validation_predictions_sha256_second=vision.validation_predictions.identity.sha256,
            validation_metric_identity=vision.validation_metrics.identity,
            validation_metric_report=_read_metric(vision),
            validation_measurements=vision_measurement,
            pixel_gate_evidence=_identity("3", artifact_type="pixel-gate"),
            frozen_arm_manifest=None,
            owner_none_means_current=True,
            test_accessed=False,
        ),
        artifact_type="vision-handoff",
        version="vision-v1",
    )
    inputs["row-vision"] = LaneCliInput(
        experiment_id="row-vision",
        schema_kind="vision_stop_v2",
        raw_handoff=raw_vision,
        artifacts=vision_artifacts,
        source_commit_sha="d" * 40,
    )
    return inputs


def _jsonl_pin(path: Path, values: Iterable[BaseModel]) -> PinnedArtifact:
    identity = write_jsonl(path, values)
    return PinnedArtifact(path=path, identity=identity)


def _locked_prediction(row: FrozenRow, experiment_id: str, config_id: str) -> RowPrediction:
    return RowPrediction(
        experiment_id=experiment_id,
        config_id=config_id,
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=row.atoms,
        proposals=(
            FieldProposal(
                role=FieldRole.DESCRIPTION,
                atom_ids=(row.atoms[0].atom_id,),
                raw_score=1.0,
            ),
        ),
        exact_row_confidence=None if experiment_id == "row-profiles" else 1.0,
        decision=Decision.ACCEPT,
        reasons=("synthetic",),
    )


def _placeholder(path: Path, identity: ArtifactIdentity) -> PinnedArtifact:
    path.write_bytes(b"synthetic-placeholder\n")
    return PinnedArtifact(path=path, identity=identity)


def _snapshot_arm(value: BaselineHandoff | LaneHandoff) -> NormalizedArmSnapshot:
    return NormalizedArmSnapshot(
        experiment_id=value.experiment_id,
        config_id=value.config_id,
        runtime_identity=value.runtime_identity,
        model_inventory=_pin(value.model_inventory),
        dependency_inventory=_pin(value.dependency_inventory),
        arm_manifest=(None if value.frozen_arm is None else _pin(value.frozen_arm.arm_manifest)),
        validation_predictions=_pin(value.validation_predictions),
        validation_metrics=_pin(value.validation_metrics),
        validation_measurements=tuple(_pin(item) for item in value.validation_measurements),
        validation_error_summary=_pin(cast(ArtifactFile, value.validation_error_summary)),
        disposition=(value.disposition if isinstance(value, LaneHandoff) else None),
        stop_reason=(value.stop_reason if isinstance(value, LaneHandoff) else None),
        validation_replay_cache_root=(
            None if value.frozen_arm is None else value.frozen_arm.validation_replay_cache_root
        ),
    )


class SyntheticCase:
    def __init__(
        self,
        root: Path,
        *,
        locked_split: DatasetSplit = DatasetSplit.TEST,
    ) -> None:
        self.root = root
        self.private_root = root / "private"
        self.private_root.mkdir()
        self.core = _normalized_manifest(
            self.private_root / "inputs",
            locked_split=locked_split,
        )
        checkout = _git_checkout(self.private_root / "comparison-checkout")
        profiles_source, _package = _profile_checkout(self.private_root / "profiles-checkout")
        self.rows = (
            frozen_row(
                document_id="c" * 64,
                row_id="locked-a",
                split=DatasetSplit.TEST,
                atoms=(evidence_atom(atom_id="locked-atom-a", text="SYNTHETIC LOCKED A"),),
            ),
            frozen_row(
                document_id="d" * 64,
                row_id="locked-b",
                split=DatasetSplit.TEST,
                atoms=(evidence_atom(atom_id="locked-atom-b", text="SYNTHETIC LOCKED B"),),
            ),
        )
        self.gold = tuple(
            GoldRow(
                document_id=row.document_id,
                row_id=row.row_id,
                row_type=RowType.PRIMARY_TRANSACTION,
                fields=(
                    GoldField(
                        role=FieldRole.DESCRIPTION,
                        canonical_value=row.atoms[0].text,
                        atom_ids=(row.atoms[0].atom_id,),
                    ),
                ),
            )
            for row in self.rows
        )
        accepted_config = self.core.baselines["accepted-baseline"].config_id
        accepted = tuple(
            _locked_prediction(row, "accepted-baseline", accepted_config) for row in self.rows
        )
        rows_pin = _jsonl_pin(self.private_root / "locked-rows.jsonl", self.rows)
        gold_pin = _jsonl_pin(self.private_root / "locked-gold.jsonl", self.gold)
        accepted_pin = _jsonl_pin(self.private_root / "locked-accepted-predictions.jsonl", accepted)
        accepted_identity_pin = _write_pinned_model(
            self.private_root / "locked-accepted-predictions.identity.json",
            accepted_pin.identity,
            artifact_type="row-prediction-identity-record",
            version="row-prediction-identity-v1",
        )
        lanes = _raw_lane_inputs(self.private_root, self.core)
        baselines = {
            experiment_id: BaselineCliInput(
                experiment_id=cast(BaselineId, experiment_id),
                loader_kind=cast(BaselineId, experiment_id),
                config_id=value.config_id,
                validation_replay_cache_root=(
                    self.private_root / "workspace" / "prelock" / "replay" / experiment_id
                ),
                **_artifacts(value).model_dump(mode="python"),
            )
            for experiment_id, value in self.core.baselines.items()
        }
        validation_gold = _placeholder(
            self.private_root / "validation-gold.jsonl", self.core.label_identity
        )
        self.manifest = LockedComparisonCliManifestV1(
            version="row-extraction-locked-comparison-cli-v1",
            private_root=self.private_root,
            workspace_root=self.private_root / "workspace",
            comparison_checkout=checkout,
            foundation_sha=self.core.foundation_sha,
            expected_bundle_identity=self.core.bundle_identity,
            expected_split_identity=self.core.split_identity,
            expected_label_identity=self.core.label_identity,
            foundation_bundle=_placeholder(
                self.private_root / "foundation-bundle.json", self.core.bundle_identity
            ),
            split_manifest=PinnedArtifact(
                path=self.private_root / "inputs" / "synthetic-split-manifest.json",
                identity=self.core.split_identity,
            ),
            validation_rows=_pin(self.core.validation_rows),
            validation_gold=validation_gold,
            locked_row_ids=_pin(self.core.locked_row_ids),
            locked_inputs=DeferredLockedInputs(
                rows=rows_pin,
                gold=gold_pin,
                accepted_predictions=accepted_pin,
                accepted_predictions_identity_file=accepted_identity_pin,
            ),
            baselines=baselines,
            lanes=lanes,
            profiles_source=profiles_source,
        )
        self.manifest_path = self.private_root / "comparison-manifest.json"
        self.manifest_path.write_bytes(self.manifest.canonical_bytes())
        profile = self.core.lanes["row-profiles"]
        assert profile.frozen_arm is not None

        def forbidden_builder(*_args: object, **_kwargs: object) -> ResourceSpec:
            raise AssertionError("fake backend owns locked execution")

        self.profile_adapter = ProfileLaneAdapter(
            factory_loader=profile.frozen_arm.factory_loader,
            build_resource_spec=forbidden_builder,
            config_id=profile.config_id,
        )

    def profile_loader(self, *_args: object, **_kwargs: object) -> ProfileLaneAdapter:
        return self.profile_adapter

    def normalizer(
        self,
        cli: LockedComparisonCliManifestV1,
        _prelock_root: Path,
        *,
        profile_adapter: ProfileLaneAdapter,
        manifest_identity: ArtifactIdentity,
        comparison_commit_sha: str,
        profiles_source_manifest_sha256: str,
    ) -> NormalizedProgram:
        assert profile_adapter is self.profile_adapter
        arms = tuple(
            _snapshot_arm(
                self.core.baselines[experiment_id]
                if experiment_id in self.core.baselines
                else self.core.lanes[experiment_id]
            )
            for experiment_id in (*BASELINE_INPUT_IDS, *LANE_INPUT_IDS)
        )
        snapshot = NormalizedProgramSnapshot(
            version="row-comparison-normalized-program-v1",
            foundation_sha=self.core.foundation_sha,
            bundle_identity=self.core.bundle_identity,
            split_identity=self.core.split_identity,
            label_identity=self.core.label_identity,
            validation_rows=_pin(self.core.validation_rows),
            locked_row_ids=_pin(self.core.locked_row_ids),
            arms=arms,
        )
        snapshot_identity = identity_for_bytes(
            canonical_model_bytes(snapshot),
            artifact_type="row-comparison-normalized-program",
            version="row-comparison-normalized-program-v1",
        )
        dispositions: dict[str, LaneDisposition] = {
            experiment_id: self.core.lanes[experiment_id].disposition
            for experiment_id in LANE_INPUT_IDS
        }
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
            source_commit_pins={key: value.source_commit_sha for key, value in cli.lanes.items()},
            runtime_identities={value.experiment_id: value.runtime_identity for value in arms},
            dispositions=dispositions,
            validation_prediction_identities={
                value.experiment_id: value.validation_predictions.identity for value in arms
            },
            provenance_limitations={
                experiment_id: "stopped_source_generation_not_replayable"
                for experiment_id, disposition in dispositions.items()
                if disposition is LaneDisposition.VALIDATION_STOPPED
            },
            test_accessed=False,
        )
        return NormalizedProgram(
            manifest=self.core,
            profile_adapter=self.profile_adapter,
            snapshot=snapshot,
            receipt=receipt,
        )
