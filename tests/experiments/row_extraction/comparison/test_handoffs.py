from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import BaseModel

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.codecs import read_jsonl, write_jsonl
from experiments.row_extraction.comparison.errors import (
    ErrorCategory,
    ErrorCategoryCount,
    ValidationErrorSummary,
)
from experiments.row_extraction.comparison.handoffs import (
    ArtifactFile,
    BaselineHandoff,
    ComparisonManifest,
    FrozenArmInput,
    HandoffError,
    LaneHandoff,
    RowIdentity,
    validate_handoffs,
)
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
from experiments.row_extraction.metrics import MetricReport, score_predictions
from experiments.row_extraction.runner import (
    MeasuredArmFactory,
    ResourceInventory,
    ResourceInventoryEntry,
    RunMeasurements,
)
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row

_BASELINE_IDS = (
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
)
_LANE_IDS = ("row-ocr", "row-profiles", "row-text", "row-vision")
_FOUNDATION_SHA = "1" * 40


class _SyntheticArm:
    def __init__(self, experiment_id: str, config_id: str) -> None:
        self._experiment_id = experiment_id
        self._config_id = config_id

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    @property
    def config_id(self) -> str:
        return self._config_id

    def predict(self, row: FrozenRow) -> RowPrediction:
        return _prediction(row, self._experiment_id, self._config_id)


class _SyntheticFactory:
    def __init__(
        self,
        rows: tuple[FrozenRow, ...],
        row_sequence_identity: ArtifactIdentity,
        *,
        experiment_id: str,
        config_id: str,
        runtime_identity: ArtifactIdentity,
        arm_manifest_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> None:
        self._rows = rows
        self._row_sequence_identity = row_sequence_identity
        self._experiment_id = experiment_id
        self._config_id = config_id
        self._runtime_identity = runtime_identity
        self._arm_manifest_identity = arm_manifest_identity
        self._model_inventory_identity = model_inventory_identity
        self._dependency_inventory_identity = dependency_inventory_identity
        self._cache_root = cache_root

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    @property
    def config_id(self) -> str:
        return self._config_id

    @property
    def row_sequence_identity(self) -> ArtifactIdentity:
        return self._row_sequence_identity

    @property
    def expected_row_count(self) -> int:
        return len(self._rows)

    @property
    def split(self) -> DatasetSplit:
        return DatasetSplit.VALIDATION

    @property
    def arm_manifest_identity(self) -> ArtifactIdentity:
        return self._arm_manifest_identity

    @property
    def runtime_identity(self) -> ArtifactIdentity:
        return self._runtime_identity

    @property
    def model_inventory_identity(self) -> ArtifactIdentity:
        return self._model_inventory_identity

    @property
    def dependency_inventory_identity(self) -> ArtifactIdentity:
        return self._dependency_inventory_identity

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    @property
    def resource_basis(
        self,
    ) -> Literal["end-to-end-method", "materialized-adapter"]:
        if self._experiment_id == "accepted-baseline":
            return "materialized-adapter"
        return "end-to-end-method"

    @property
    def worker_count(self) -> Literal[1]:
        return 1

    @property
    def subprocess_count(self) -> int:
        return 0

    def build(self) -> _SyntheticArm:
        return _SyntheticArm(self._experiment_id, self._config_id)


def _prediction(row: FrozenRow, experiment_id: str, config_id: str) -> RowPrediction:
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
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=("synthetic",),
    )


def _identity(path: Path, artifact_type: str, version: str) -> ArtifactIdentity:
    content = path.read_bytes()
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=hashlib.sha256(content).hexdigest(),
        version=version,
        byte_size=len(content),
    )


def _write_model(
    path: Path,
    value: object,
    artifact_type: str,
    version: str = "synthetic-v1",
) -> ArtifactFile:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_bytes(_canonical_json_value_content(payload) + b"\n")
    return ArtifactFile(
        path=path,
        identity=_identity(path, artifact_type, version),
    )


def _error_summary(row_count: int) -> ValidationErrorSummary:
    empty = tuple(ErrorCategoryCount(category=category, count=0) for category in ErrorCategory)
    return ValidationErrorSummary(
        version="row-comparison-error-summary-v1",
        row_count=row_count,
        primary_counts=empty,
        secondary_counts=empty,
    )


def _inventory(
    tmp_path: Path,
    name: str,
    category: Literal["model", "dependency"],
) -> ArtifactFile:
    resource = tmp_path / f"{name}.bin"
    resource.write_bytes(name.encode("ascii"))
    stat = resource.stat()
    inventory = ResourceInventory(
        version="row-resource-inventory-v1",
        entries=(
            ResourceInventoryEntry(
                category=category,
                resolved_path=resource.resolve(),
                sha256=hashlib.sha256(resource.read_bytes()).hexdigest(),
                byte_size=stat.st_size,
                device=stat.st_dev,
                inode=stat.st_ino,
            ),
        ),
    )
    path = tmp_path / f"{name}.inventory.json"
    path.write_bytes(_canonical_json_value_content(inventory.model_dump(mode="json")) + b"\n")
    return ArtifactFile(
        path=path,
        identity=_identity(
            path,
            "resource-inventory",
            "row-resource-inventory-v1",
        ),
    )


def _metric(rows: Sequence[FrozenRow], predictions: Sequence[RowPrediction]) -> MetricReport:
    gold = tuple(
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
        for row in rows
    )
    return score_predictions(tuple(rows), gold, tuple(predictions))


def _measurement(
    experiment_id: str,
    config_id: str,
    rows_identity: ArtifactIdentity,
    prediction_identity: ArtifactIdentity,
    runtime: ArtifactIdentity,
    arm_manifest: ArtifactIdentity,
    model_inventory: ArtifactIdentity,
    dependency_inventory: ArtifactIdentity,
) -> RunMeasurements:
    return RunMeasurements(
        experiment_id=experiment_id,
        config_id=config_id,
        row_sequence_identity=rows_identity,
        split=DatasetSplit.VALIDATION,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        arm_manifest_identity=arm_manifest,
        row_count=2,
        total_ns=2,
        p50_ns=1,
        p95_ns=1,
        preparation_ns=0,
        end_to_end_ns=2,
        cold_start_ns=1,
        throughput_rows_per_second=Decimal("1"),
        peak_rss_bytes=1,
        model_bytes=1,
        dependency_bytes=1,
        cache_bytes=0,
        subprocess_count=0,
        worker_count=1,
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=runtime,
        model_inventory_identity=model_inventory,
        dependency_inventory_identity=dependency_inventory,
        resource_inventory_identity=ArtifactIdentity(
            artifact_type="resource-inventory",
            sha256="e" * 64,
            version="row-resource-inventory-v1",
            byte_size=1,
        ),
        predictions_sha256=prediction_identity.sha256,
    )


def _manifest(
    tmp_path: Path,
    *,
    lane_ids: tuple[str, ...] = _LANE_IDS,
    prediction_mutator: Callable[[str, list[RowPrediction]], None] | None = None,
    stopped: frozenset[str] = frozenset(),
    runtime_overrides: Mapping[str, ArtifactIdentity] | None = None,
) -> ComparisonManifest:
    rows = (
        frozen_row(
            document_id="a" * 64,
            row_id="row-a",
            split=DatasetSplit.VALIDATION,
            atoms=(evidence_atom(atom_id="atom-a", text="SYNTHETIC A"),),
        ),
        frozen_row(
            document_id="b" * 64,
            row_id="row-b",
            split=DatasetSplit.VALIDATION,
            atoms=(evidence_atom(atom_id="atom-b", text="SYNTHETIC B"),),
        ),
    )
    validation_rows_path = tmp_path / "validation-rows.jsonl"
    validation_rows_identity = write_jsonl(validation_rows_path, rows)
    validation_rows = ArtifactFile(validation_rows_path, validation_rows_identity)
    locked_ids_path = tmp_path / "locked-row-ids.jsonl"
    locked_ids_identity = write_jsonl(
        locked_ids_path,
        (
            RowIdentity(document_id="c" * 64, row_id="locked-a"),
            RowIdentity(document_id="d" * 64, row_id="locked-b"),
        ),
    )
    runtime = ArtifactIdentity(
        artifact_type="row-runtime-manifest",
        sha256="9" * 64,
        version="row-runtime-manifest-v1",
        byte_size=1,
    )
    vision_runtime = ArtifactIdentity(
        artifact_type="runtime-lock",
        sha256="4" * 64,
        version="row-vision-runtime-v1",
        byte_size=1,
    )
    bundle = ArtifactIdentity(
        artifact_type="bundle",
        sha256="6" * 64,
        version="synthetic-v1",
        byte_size=1,
    )
    split = ArtifactIdentity(
        artifact_type="row-split-manifest",
        sha256="7" * 64,
        version="row-extraction-split-v1",
        byte_size=1,
    )
    labels = ArtifactIdentity(
        artifact_type="labels",
        sha256="8" * 64,
        version="canonical-jsonl-v1",
        byte_size=1,
    )

    def handoff(arm_id: str, is_lane: bool) -> BaselineHandoff | LaneHandoff:
        config_id = f"{arm_id}-config"
        default_runtime = vision_runtime if arm_id == "row-vision" else runtime
        arm_runtime = (runtime_overrides or {}).get(arm_id, default_runtime)
        model = _inventory(tmp_path, f"{arm_id}-model", "model")
        dependency = _inventory(tmp_path, f"{arm_id}-dependency", "dependency")
        arm_manifest = _write_model(
            tmp_path / f"{arm_id}-arm.json",
            {"experiment_id": arm_id, "config_id": config_id},
            "frozen-arm-manifest",
        )
        predictions = [_prediction(row, arm_id, config_id) for row in rows]
        metric_report = _metric(rows, predictions)
        if prediction_mutator is not None:
            prediction_mutator(arm_id, predictions)
        predictions_path = tmp_path / f"{arm_id}-validation.jsonl"
        prediction_identity = write_jsonl(predictions_path, predictions)
        prediction_file = ArtifactFile(predictions_path, prediction_identity)
        metric = _write_model(
            tmp_path / f"{arm_id}-metrics.json",
            metric_report,
            "row-comparison-validation-metrics",
            "row-comparison-validation-metrics-v1",
        )
        measurement_value = _measurement(
            arm_id,
            config_id,
            validation_rows_identity,
            prediction_identity,
            arm_runtime,
            arm_manifest.identity,
            model.identity,
            dependency.identity,
        )
        measurement = _write_model(
            tmp_path / f"{arm_id}-run.json",
            measurement_value,
            "row-comparison-validation-measurements",
            "row-comparison-validation-measurements-v1",
        )
        error_summary = _write_model(
            tmp_path / f"{arm_id}-errors.json",
            _error_summary(len(rows)),
            "row-comparison-error-summary",
            "row-comparison-error-summary-v1",
        )

        def load(
            loaded_rows: tuple[FrozenRow, ...],
            row_identity: ArtifactIdentity,
            cache_root: Path,
        ) -> MeasuredArmFactory:
            return _SyntheticFactory(
                loaded_rows,
                row_identity,
                experiment_id=arm_id,
                config_id=config_id,
                runtime_identity=arm_runtime,
                arm_manifest_identity=arm_manifest.identity,
                model_inventory_identity=model.identity,
                dependency_inventory_identity=dependency.identity,
                cache_root=cache_root,
            )

        frozen_arm = FrozenArmInput(
            arm_manifest=arm_manifest,
            factory_loader=load,
            validation_replay_cache_root=tmp_path / f"{arm_id}-replay-cache",
        )
        common = {
            "experiment_id": arm_id,
            "config_id": config_id,
            "foundation_sha": _FOUNDATION_SHA,
            "bundle_identity": bundle,
            "split_identity": split,
            "label_identity": labels,
            "runtime_identity": arm_runtime,
            "model_inventory": model,
            "dependency_inventory": dependency,
            "validation_predictions": prediction_file,
            "validation_metrics": metric,
            "validation_measurements": (measurement,),
            "validation_error_summary": error_summary,
        }
        if not is_lane:
            return BaselineHandoff(**common, frozen_arm=frozen_arm)
        disposition = (
            LaneDisposition.VALIDATION_STOPPED
            if arm_id in stopped
            else LaneDisposition.FROZEN_ELIGIBLE
        )
        return LaneHandoff(
            **common,
            disposition=disposition,
            stop_reason=(
                {
                    "row-ocr": "ocr_stage_validation_failed",
                    "row-profiles": "no_profile_candidate_met_validation_gate",
                    "row-text": "no_text_candidate_met_validation_gate",
                    "row-vision": "no_pixel_gain",
                }[arm_id]
                if disposition is LaneDisposition.VALIDATION_STOPPED
                else None
            ),
            frozen_arm=(None if disposition is LaneDisposition.VALIDATION_STOPPED else frozen_arm),
        )

    baselines: dict[str, BaselineHandoff] = {}
    for arm_id in _BASELINE_IDS:
        value = handoff(arm_id, False)
        assert isinstance(value, BaselineHandoff)
        baselines[arm_id] = value
    lanes: dict[str, LaneHandoff] = {}
    for arm_id in lane_ids:
        value = handoff(arm_id, True)
        assert isinstance(value, LaneHandoff)
        lanes[arm_id] = value
    return ComparisonManifest(
        foundation_sha=_FOUNDATION_SHA,
        bundle_identity=bundle,
        split_identity=split,
        label_identity=labels,
        runtime_identity=runtime,
        validation_rows=validation_rows,
        locked_row_ids=ArtifactFile(locked_ids_path, locked_ids_identity),
        baselines=baselines,
        lanes=lanes,
    )


def test_handoff_requires_exactly_four_experiment_ids(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, lane_ids=("row-ocr", "row-text"))

    with pytest.raises(HandoffError, match="missing required experiment handoff"):
        validate_handoffs(manifest)


def test_handoff_rejects_one_extra_or_missing_validation_row(tmp_path: Path) -> None:
    def remove_row(arm_id: str, predictions: list[RowPrediction]) -> None:
        if arm_id == "row-vision":
            predictions.pop()

    manifest = _manifest(tmp_path, prediction_mutator=remove_row)

    with pytest.raises(HandoffError, match="validation prediction row universe mismatch"):
        validate_handoffs(manifest)


def test_handoff_validates_exact_closed_program_and_stopped_lane(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))

    validated = validate_handoffs(manifest)

    assert validated.foundation_sha == _FOUNDATION_SHA
    assert validated.dispositions == {
        "row-ocr": LaneDisposition.VALIDATION_STOPPED,
        "row-profiles": LaneDisposition.FROZEN_ELIGIBLE,
        "row-text": LaneDisposition.FROZEN_ELIGIBLE,
        "row-vision": LaneDisposition.FROZEN_ELIGIBLE,
    }
    assert set(validated.run_inputs) == {
        *_BASELINE_IDS,
        "row-profiles",
        "row-text",
        "row-vision",
    }
    assert "row-ocr" not in validated.run_inputs
    assert set(validated.validation_predictions) == {*_BASELINE_IDS, *_LANE_IDS}
    assert validated.locked_row_ids == {
        ("c" * 64, "locked-a"),
        ("d" * 64, "locked-b"),
    }


def test_handoff_rejects_extra_lane_instead_of_ignoring_it(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    lanes: Mapping[str, LaneHandoff] = {
        **manifest.lanes,
        "row-extra": next(iter(manifest.lanes.values())),
    }
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "lanes": lanes,
        }
    )

    with pytest.raises(HandoffError, match="unknown experiment handoff"):
        validate_handoffs(changed)


def test_handoff_rejects_stopped_lane_with_run_inputs(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    original = manifest.lanes["row-ocr"]
    stopped = LaneHandoff(
        **{
            **original.__dict__,
            "disposition": LaneDisposition.VALIDATION_STOPPED,
            "stop_reason": "ocr_stage_validation_failed",
        }
    )
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "lanes": {**manifest.lanes, "row-ocr": stopped},
        }
    )

    with pytest.raises(HandoffError, match="stopped lane cannot have run inputs"):
        validate_handoffs(changed)


def test_handoff_rejects_factory_identity_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    original = manifest.lanes["row-text"]
    assert original.frozen_arm is not None

    def mismatched_loader(
        rows: tuple[FrozenRow, ...],
        row_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory:
        loaded = original.frozen_arm.factory_loader(rows, row_identity, cache_root)
        assert isinstance(loaded, _SyntheticFactory)
        return _SyntheticFactory(
            rows,
            row_identity,
            experiment_id="row-vision",
            config_id=loaded.config_id,
            runtime_identity=loaded.runtime_identity,
            arm_manifest_identity=loaded.arm_manifest_identity,
            model_inventory_identity=loaded.model_inventory_identity,
            dependency_inventory_identity=loaded.dependency_inventory_identity,
            cache_root=cache_root,
        )

    changed_lane = LaneHandoff(
        **{
            **original.__dict__,
            "frozen_arm": FrozenArmInput(
                arm_manifest=original.frozen_arm.arm_manifest,
                factory_loader=mismatched_loader,
                validation_replay_cache_root=(original.frozen_arm.validation_replay_cache_root),
            ),
        }
    )
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "lanes": {**manifest.lanes, "row-text": changed_lane},
        }
    )

    with pytest.raises(HandoffError, match="frozen factory identity mismatch"):
        validate_handoffs(changed)


def test_handoff_replays_frozen_factory_predictions(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    original = manifest.lanes["row-text"]
    assert original.frozen_arm is not None

    class _ChangedFactory(_SyntheticFactory):
        def build(self) -> _SyntheticArm:
            return _SyntheticArm(self.experiment_id, "different-config")

    def changed_loader(
        rows: tuple[FrozenRow, ...],
        row_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory:
        loaded = original.frozen_arm.factory_loader(rows, row_identity, cache_root)
        assert isinstance(loaded, _SyntheticFactory)
        return _ChangedFactory(
            rows,
            row_identity,
            experiment_id=loaded.experiment_id,
            config_id=loaded.config_id,
            runtime_identity=loaded.runtime_identity,
            arm_manifest_identity=loaded.arm_manifest_identity,
            model_inventory_identity=loaded.model_inventory_identity,
            dependency_inventory_identity=loaded.dependency_inventory_identity,
            cache_root=cache_root,
        )

    changed_lane = LaneHandoff(
        **{
            **original.__dict__,
            "frozen_arm": FrozenArmInput(
                arm_manifest=original.frozen_arm.arm_manifest,
                factory_loader=changed_loader,
                validation_replay_cache_root=(original.frozen_arm.validation_replay_cache_root),
            ),
        }
    )
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "lanes": {**manifest.lanes, "row-text": changed_lane},
        }
    )

    with pytest.raises(HandoffError, match="validation prediction replay mismatch"):
        validate_handoffs(changed)


def test_handoff_rejects_overlapping_model_and_dependency_inventory(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    original = manifest.lanes["row-vision"]
    changed_lane = LaneHandoff(
        **{
            **original.__dict__,
            "dependency_inventory": original.model_inventory,
        }
    )
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "lanes": {**manifest.lanes, "row-vision": changed_lane},
        }
    )

    with pytest.raises(HandoffError, match="model and dependency inventories overlap"):
        validate_handoffs(changed)


def test_stopped_handoff_checks_prediction_identity_without_confidence(
    tmp_path: Path,
) -> None:
    def change_identity(arm_id: str, predictions: list[RowPrediction]) -> None:
        if arm_id == "row-vision":
            predictions[0] = predictions[0].model_copy(
                update={
                    "experiment_id": "row-extra",
                    "exact_row_confidence": None,
                }
            )

    manifest = _manifest(
        tmp_path,
        prediction_mutator=change_identity,
        stopped=frozenset({"row-vision"}),
    )

    with pytest.raises(HandoffError, match="validation prediction identity mismatch"):
        validate_handoffs(manifest)


def test_locked_row_identity_stream_rejects_nonopaque_document_id(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    invalid_path = tmp_path / "invalid-locked-row-ids.jsonl"
    invalid_path.write_bytes(
        _canonical_json_value_content({"document_id": "private-name", "row_id": "locked-a"}) + b"\n"
    )
    invalid = ArtifactFile(
        path=invalid_path,
        identity=_identity(invalid_path, "jsonl", "canonical-jsonl-v1"),
    )
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "locked_row_ids": invalid,
        }
    )

    with pytest.raises(HandoffError, match="invalid locked row identity artifact"):
        validate_handoffs(changed)


def test_handoff_rejects_lane_record_in_baseline_mapping(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    lane = manifest.lanes["row-text"]
    changed = ComparisonManifest(
        **{
            **manifest.__dict__,
            "baselines": {
                **manifest.baselines,
                "accepted-baseline": lane,
            },
        }
    )

    with pytest.raises(HandoffError, match="invalid baseline handoff type"):
        validate_handoffs(changed)


def test_handoff_rejects_matching_but_invalid_shared_identity(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    invalid = cast(ArtifactIdentity, None)
    baselines = {
        key: replace(value, bundle_identity=invalid) for key, value in manifest.baselines.items()
    }
    lanes = {key: replace(value, bundle_identity=invalid) for key, value in manifest.lanes.items()}
    changed = replace(
        manifest,
        bundle_identity=invalid,
        baselines=baselines,
        lanes=lanes,
    )

    with pytest.raises(HandoffError, match="invalid bundle identity"):
        validate_handoffs(changed)


def test_handoff_rejects_invalid_runtime_identity_version(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    invalid_runtime = manifest.runtime_identity.model_copy(update={"version": "unknown-runtime-v1"})
    baselines = {
        key: replace(value, runtime_identity=invalid_runtime)
        for key, value in manifest.baselines.items()
    }
    lanes = {
        key: replace(value, runtime_identity=invalid_runtime)
        for key, value in manifest.lanes.items()
    }
    changed = replace(
        manifest,
        runtime_identity=invalid_runtime,
        baselines=baselines,
        lanes=lanes,
    )

    with pytest.raises(HandoffError, match="invalid runtime identity"):
        validate_handoffs(changed)


def test_handoff_rejects_wrong_validation_row_identity_type(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    invalid_rows = replace(
        manifest.validation_rows,
        identity=manifest.validation_rows.identity.model_copy(
            update={"artifact_type": "opaque-binary"}
        ),
    )
    changed = replace(manifest, validation_rows=invalid_rows)

    with pytest.raises(HandoffError, match="invalid validation row identity"):
        validate_handoffs(changed)


@pytest.mark.parametrize("disposition", ["validation_stopped", object()])
def test_handoff_rejects_untyped_or_unknown_disposition(
    tmp_path: Path,
    disposition: object,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    original = manifest.lanes["row-ocr"]
    changed_lane = replace(
        original,
        disposition=cast(LaneDisposition, disposition),
    )
    changed = replace(
        manifest,
        lanes={**manifest.lanes, "row-ocr": changed_lane},
    )

    with pytest.raises(HandoffError, match="invalid lane disposition"):
        validate_handoffs(changed)


def test_stopped_handoff_requires_complete_coherent_validation_metrics(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    original = manifest.lanes["row-ocr"]
    report = MetricReport.model_validate_json(original.validation_metrics.path.read_bytes())
    incomplete = report.model_copy(
        update={
            "exact_rows": 999,
            "row_types": (),
            "row_type_confusion": (),
            "fields": {},
        }
    )
    metric_file = _write_model(
        tmp_path / "row-ocr-invalid-metrics.json",
        incomplete,
        "row-comparison-validation-metrics",
        "row-comparison-validation-metrics-v1",
    )
    changed_lane = replace(original, validation_metrics=metric_file)
    changed = replace(
        manifest,
        lanes={**manifest.lanes, "row-ocr": changed_lane},
    )

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(changed)


def _replace_stopped_metric(
    tmp_path: Path,
    manifest: ComparisonManifest,
    report: MetricReport,
) -> ComparisonManifest:
    original = manifest.lanes["row-ocr"]
    metric_file = _write_model(
        tmp_path / "row-ocr-replacement-metrics.json",
        report,
        "row-comparison-validation-metrics",
        "row-comparison-validation-metrics-v1",
    )
    return replace(
        manifest,
        lanes={**manifest.lanes, "row-ocr": replace(original, validation_metrics=metric_file)},
    )


def test_stopped_handoff_rejects_calibration_mean_outside_bin(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    bins = list(report.calibration_bins)
    bins[-1] = bins[-1].model_copy(update={"mean_confidence": Decimal("0.01")})
    incoherent = report.model_copy(
        update={
            "calibration_bins": tuple(bins),
            "expected_calibration_error": Decimal("0.99"),
        }
    )

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_rejects_nonfinal_calibration_upper_boundary(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    bins = list(report.calibration_bins)
    bins[-2] = bins[-2].model_copy(
        update={
            "count": 2,
            "mean_confidence": Decimal("0.9"),
            "empirical_accuracy": Decimal(1),
        }
    )
    bins[-1] = bins[-1].model_copy(
        update={
            "count": 0,
            "mean_confidence": None,
            "empirical_accuracy": None,
        }
    )
    incoherent = report.model_copy(
        update={
            "calibration_bins": tuple(bins),
            "expected_calibration_error": Decimal("0.1"),
        }
    )

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_rejects_unattainable_calibration_accuracy(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    bins = list(report.calibration_bins)
    bins[-1] = bins[-1].model_copy(update={"empirical_accuracy": Decimal("0.25")})
    incoherent = report.model_copy(
        update={
            "calibration_bins": tuple(bins),
            "expected_calibration_error": Decimal("0.75"),
        }
    )

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_rejects_arbitrary_expected_calibration_error(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    incoherent = report.model_copy(update={"expected_calibration_error": Decimal("0.5")})

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_rejects_arbitrary_area_under_risk_coverage(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    incoherent = report.model_copy(update={"area_under_risk_coverage": Decimal("0.5")})

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_rejects_arbitrary_coverage_at_risk(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))
    report = MetricReport.model_validate_json(
        manifest.lanes["row-ocr"].validation_metrics.path.read_bytes()
    )
    coverage = list(report.coverage_at_risk)
    coverage[0] = coverage[0].model_copy(update={"coverage": Decimal(0)})
    incoherent = report.model_copy(update={"coverage_at_risk": tuple(coverage)})

    with pytest.raises(HandoffError, match="validation metrics are incomplete or incoherent"):
        validate_handoffs(_replace_stopped_metric(tmp_path, manifest, incoherent))


def test_stopped_handoff_preserves_complete_typed_validation_evidence(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-ocr"}))

    validated = validate_handoffs(manifest)
    evidence = validated.validation_evidence["row-ocr"]
    binding = validated.arm_bindings["row-ocr"]

    assert evidence.stop_reason == "ocr_stage_validation_failed"
    assert evidence.metrics.row_count == 2
    assert evidence.measurements[0].row_count == 2
    assert evidence.error_summary is not None
    assert evidence.error_summary.row_count == 2
    assert binding.experiment_id == "row-ocr"
    assert binding.config_id == "row-ocr-config"
    assert binding.arm_manifest is None


def test_frozen_loader_binds_each_explicit_cache_root(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    validated = validate_handoffs(manifest)
    run_inputs = validated.run_inputs["row-text"]
    rows = tuple(read_jsonl(manifest.validation_rows.path, FrozenRow))
    first_cache = tmp_path / "locked-first-cache"
    second_cache = tmp_path / "locked-repeat-cache"

    first = run_inputs.factory_loader(
        rows,
        manifest.validation_rows.identity,
        first_cache,
    )
    second = run_inputs.factory_loader(
        rows,
        manifest.validation_rows.identity,
        second_cache,
    )

    assert first.cache_root == first_cache
    assert second.cache_root == second_cache
    assert first.cache_root != second.cache_root


def test_handoffs_preserve_closed_vision_runtime_identity(
    tmp_path: Path,
) -> None:
    vision_runtime = ArtifactIdentity(
        artifact_type="runtime-lock",
        sha256="4" * 64,
        version="row-vision-runtime-v1",
        byte_size=1,
    )
    manifest = _manifest(
        tmp_path,
        runtime_overrides={"row-vision": vision_runtime},
    )

    validated = validate_handoffs(manifest)

    assert validated.arm_bindings["row-vision"].runtime_identity == vision_runtime
    assert validated.arm_bindings["accepted-baseline"].runtime_identity == manifest.runtime_identity


@pytest.mark.parametrize(
    ("experiment_id", "invalid_runtime"),
    (
        (
            "row-vision",
            ArtifactIdentity(
                artifact_type="row-runtime-manifest",
                sha256="4" * 64,
                version="row-runtime-manifest-v1",
                byte_size=1,
            ),
        ),
        (
            "row-text",
            ArtifactIdentity(
                artifact_type="runtime-lock",
                sha256="4" * 64,
                version="row-vision-runtime-v1",
                byte_size=1,
            ),
        ),
        (
            "row-vision",
            ArtifactIdentity(
                artifact_type="runtime-lock",
                sha256="4" * 64,
                version="row-runtime-manifest-v1",
                byte_size=1,
            ),
        ),
    ),
)
def test_handoffs_reject_cross_lane_or_mixed_runtime_contracts(
    tmp_path: Path,
    experiment_id: str,
    invalid_runtime: ArtifactIdentity,
) -> None:
    manifest = _manifest(
        tmp_path,
        runtime_overrides={experiment_id: invalid_runtime},
    )

    with pytest.raises(HandoffError, match="invalid runtime identity"):
        validate_handoffs(manifest)


def test_handoff_preserves_one_or_two_typed_validation_measurements(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, stopped=frozenset({"row-profiles"}))
    original = manifest.lanes["row-profiles"]
    (first_file,) = original.validation_measurements
    first = RunMeasurements.model_validate_json(first_file.path.read_bytes())
    repeat_file = _write_model(
        tmp_path / "row-profiles-run-repeat.json",
        first,
        "row-comparison-validation-measurements",
        "row-comparison-validation-measurements-v1",
    )
    changed_lane = replace(
        original,
        validation_measurements=(first_file, repeat_file),
    )
    changed = replace(
        manifest,
        lanes={**manifest.lanes, "row-profiles": changed_lane},
    )

    validated = validate_handoffs(changed)
    evidence = validated.validation_evidence["row-profiles"]

    assert len(evidence.measurements) == 2
    assert evidence.measurements[0] == first
    assert evidence.measurements[1] == first
    assert evidence.measurement_paths == (first_file.path, repeat_file.path)
    assert evidence.measurement_identities == (
        first_file.identity,
        repeat_file.identity,
    )


def test_validation_replay_rejects_loader_that_ignores_cache_root(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    original = manifest.lanes["row-text"]
    assert original.frozen_arm is not None

    def ignoring_loader(
        rows: tuple[FrozenRow, ...],
        row_identity: ArtifactIdentity,
        _cache_root: Path,
    ) -> MeasuredArmFactory:
        return original.frozen_arm.factory_loader(
            rows,
            row_identity,
            tmp_path / "ignored-cache-root",
        )

    changed_lane = replace(
        original,
        frozen_arm=FrozenArmInput(
            arm_manifest=original.frozen_arm.arm_manifest,
            factory_loader=ignoring_loader,
            validation_replay_cache_root=(original.frozen_arm.validation_replay_cache_root),
        ),
    )
    changed = replace(
        manifest,
        lanes={**manifest.lanes, "row-text": changed_lane},
    )

    with pytest.raises(HandoffError, match="frozen factory identity mismatch"):
        validate_handoffs(changed)


def test_validation_replay_requires_new_explicit_cache_root(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    lane = manifest.lanes["row-text"]
    assert lane.frozen_arm is not None
    lane.frozen_arm.validation_replay_cache_root.mkdir()

    with pytest.raises(HandoffError, match="validation replay cache must be new"):
        validate_handoffs(manifest)
