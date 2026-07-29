from __future__ import annotations

import hashlib
import json
import resource
import warnings
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest

import experiments.row_extraction.runner as runner_module
from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    Decision,
    ExperimentArm,
    FieldProposal,
    FieldRole,
    FrozenRow,
    RowPrediction,
)
from experiments.row_extraction.runner import (
    InventoryRoots,
    JsonlPredictionSink,
    PreparationMeasurements,
    ResourceInventory,
    ResourceInventoryEntry,
    ResourceSpec,
    RunContractError,
    RunMeasurements,
    build_resource_inventory,
    run_arm,
)
from tests.experiments.row_extraction.factories import frozen_row


def _artifact(
    label: str,
    *,
    artifact_type: str = "synthetic",
    version: str = "synthetic-v1",
) -> ArtifactIdentity:
    payload = label.encode("utf-8")
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        version=version,
        byte_size=len(payload),
    )


def _row_sequence_identity(rows: tuple[FrozenRow, ...]) -> ArtifactIdentity:
    payload = b"".join(_canonical_record_bytes(row) for row in rows)
    return ArtifactIdentity(
        artifact_type="frozen-row-sequence",
        sha256=hashlib.sha256(payload).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(payload),
    )


def _inventory_bytes(inventory: ResourceInventory) -> bytes:
    return _canonical_json_value_content(inventory.model_dump(mode="json")) + b"\n"


def _write_inventory(path: Path, inventory: ResourceInventory) -> ArtifactIdentity:
    payload = _inventory_bytes(inventory)
    path.write_bytes(payload)
    return ArtifactIdentity(
        artifact_type="resource-inventory",
        sha256=hashlib.sha256(payload).hexdigest(),
        version="row-resource-inventory-v1",
        byte_size=len(payload),
    )


def _prediction(
    row: FrozenRow,
    *,
    experiment_id: str = "synthetic-arm",
    config_id: str = "synthetic-config",
) -> RowPrediction:
    return RowPrediction(
        experiment_id=experiment_id,
        config_id=config_id,
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=row.baseline_type,
        evidence_atoms=row.atoms,
        proposals=(),
        decision=Decision.ABSTAIN,
        reasons=("synthetic_no_fields",),
    )


class _Arm:
    def __init__(
        self,
        factory: _Factory,
        predict: Callable[[FrozenRow], RowPrediction],
    ) -> None:
        self._factory = factory
        self._predict = predict

    @property
    def experiment_id(self) -> str:
        return self._factory.experiment_id

    @property
    def config_id(self) -> str:
        return self._factory.config_id

    def predict(self, row: FrozenRow) -> RowPrediction:
        self._factory.prediction_calls += 1
        if self._factory.launch_per_prediction:
            self._factory.launches += 1
        return self._predict(row)


class _Factory:
    def __init__(
        self,
        rows: tuple[FrozenRow, ...],
        *,
        runtime_identity: ArtifactIdentity,
        arm_manifest_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
        predict: Callable[[FrozenRow], RowPrediction] = _prediction,
        resource_basis: Literal["end-to-end-method", "materialized-adapter"] = (
            "end-to-end-method"
        ),
        launch_on_build: bool = False,
        launch_per_prediction: bool = False,
        cache_payload: bytes | None = None,
        experiment_id: str = "synthetic-arm",
    ) -> None:
        self.experiment_id = experiment_id
        self.config_id = "synthetic-config"
        self.row_sequence_identity = _row_sequence_identity(rows)
        self.expected_row_count = len(rows)
        self.split = rows[0].split
        self.arm_manifest_identity = arm_manifest_identity
        self.runtime_identity = runtime_identity
        self.model_inventory_identity = model_inventory_identity
        self.dependency_inventory_identity = dependency_inventory_identity
        self.cache_root = cache_root
        self.resource_basis = resource_basis
        self.worker_count: Literal[1] = 1
        self.launches = 0
        self.build_calls = 0
        self.prediction_calls = 0
        self.launch_on_build = launch_on_build
        self.launch_per_prediction = launch_per_prediction
        self.cache_payload = cache_payload
        self._predict = predict

    @property
    def subprocess_count(self) -> int:
        return self.launches

    def build(self) -> ExperimentArm:
        self.build_calls += 1
        if self.launch_on_build:
            self.launches += 1
        if self.cache_payload is not None:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            (self.cache_root / "derived.cache").write_bytes(self.cache_payload)
        return _Arm(self, self._predict)


@dataclass(frozen=True)
class _RunSetup:
    private_root: Path
    rows: tuple[FrozenRow, ...]
    spec: ResourceSpec
    factory: _Factory
    sink: JsonlPredictionSink
    dependency_file: Path


def _setup(
    tmp_path: Path,
    *,
    rows: tuple[FrozenRow, ...] | None = None,
    predict: Callable[[FrozenRow], RowPrediction] = _prediction,
    resource_basis: Literal["end-to-end-method", "materialized-adapter"] = ("end-to-end-method"),
    launch_on_build: bool = False,
    launch_per_prediction: bool = False,
    cache_payload: bytes | None = None,
    experiment_id: str = "synthetic-arm",
) -> _RunSetup:
    selected_rows = rows if rows is not None else (frozen_row(),)
    selected_predict = (
        (lambda row: _prediction(row, experiment_id=experiment_id))
        if predict is _prediction
        else predict
    )
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir(parents=True)
    dependency_file = private_root / "runtime.bin"
    dependency_file.write_bytes(b"runtime-dependency")
    model_inventory = build_resource_inventory(
        InventoryRoots(version="row-resource-roots-v1", category="model", roots=())
    )
    dependency_inventory = build_resource_inventory(
        InventoryRoots(
            version="row-resource-roots-v1",
            category="dependency",
            roots=(dependency_file,),
        )
    )
    model_path = private_root / "models.json"
    dependency_path = private_root / "dependencies.json"
    model_identity = _write_inventory(model_path, model_inventory)
    dependency_identity = _write_inventory(dependency_path, dependency_inventory)
    runtime_identity = _artifact("runtime")
    arm_manifest_identity = _artifact("arm")
    cache_root = private_root / "run-cache"
    factory = _Factory(
        selected_rows,
        runtime_identity=runtime_identity,
        arm_manifest_identity=arm_manifest_identity,
        model_inventory_identity=model_identity,
        dependency_inventory_identity=dependency_identity,
        cache_root=cache_root,
        predict=selected_predict,
        resource_basis=resource_basis,
        launch_on_build=launch_on_build,
        launch_per_prediction=launch_per_prediction,
        cache_payload=cache_payload,
        experiment_id=experiment_id,
    )
    spec = ResourceSpec(
        experiment_id=factory.experiment_id,
        config_id=factory.config_id,
        row_sequence_identity=_row_sequence_identity(selected_rows),
        expected_row_count=len(selected_rows),
        split=selected_rows[0].split,
        cache_policy="new-empty-v1",
        resource_basis=resource_basis,
        worker_count=1,
        runtime_identity=runtime_identity,
        arm_manifest_identity=arm_manifest_identity,
        private_root=private_root,
        model_inventory_path=model_path,
        model_inventory_identity=model_identity,
        dependency_inventory_path=dependency_path,
        dependency_inventory_identity=dependency_identity,
        cache_root=cache_root,
        resource_inventory_output=private_root / "combined-resources.json",
    )
    return _RunSetup(
        private_root=private_root,
        rows=selected_rows,
        spec=spec,
        factory=factory,
        sink=JsonlPredictionSink(private_root / "predictions.jsonl"),
        dependency_file=dependency_file,
    )


def test_inventory_builds_canonical_sorted_regular_file_entries(tmp_path: Path) -> None:
    root = (tmp_path / "assets").resolve()
    root.mkdir()
    second = root / "z.bin"
    first = root / "a.bin"
    second.write_bytes(b"second")
    first.write_bytes(b"first")

    inventory = build_resource_inventory(
        InventoryRoots(
            version="row-resource-roots-v1",
            category="dependency",
            roots=(root,),
        )
    )

    assert tuple(entry.resolved_path for entry in inventory.entries) == (first, second)
    assert tuple(entry.category for entry in inventory.entries) == (
        "dependency",
        "dependency",
    )
    assert inventory.entries[0].sha256 == hashlib.sha256(b"first").hexdigest()
    assert inventory.entries[0].byte_size == 5


def test_inventory_allows_only_an_explicit_empty_model_inventory() -> None:
    empty_model = build_resource_inventory(
        InventoryRoots(version="row-resource-roots-v1", category="model", roots=())
    )
    assert empty_model.entries == ()

    with pytest.raises(RunContractError, match="dependency inventory cannot be empty"):
        build_resource_inventory(
            InventoryRoots(version="row-resource-roots-v1", category="dependency", roots=())
        )


def test_inventory_rejects_relative_symlink_and_overlapping_roots(tmp_path: Path) -> None:
    root = (tmp_path / "assets").resolve()
    root.mkdir()
    asset = root / "asset.bin"
    asset.write_bytes(b"asset")
    link = root / "link.bin"
    link.symlink_to(asset)

    with pytest.raises(RunContractError, match="absolute"):
        build_resource_inventory(
            InventoryRoots(
                version="row-resource-roots-v1",
                category="model",
                roots=(Path("relative.bin"),),
            )
        )
    with pytest.raises(RunContractError, match="symlink"):
        build_resource_inventory(
            InventoryRoots(
                version="row-resource-roots-v1",
                category="model",
                roots=(root,),
            )
        )
    link.unlink()
    with pytest.raises(RunContractError, match="overlap"):
        build_resource_inventory(
            InventoryRoots(
                version="row-resource-roots-v1",
                category="model",
                roots=(root, asset),
            )
        )


def test_jsonl_sink_is_one_shot_and_abort_removes_staging(tmp_path: Path) -> None:
    target = tmp_path / "predictions.jsonl"
    sink = JsonlPredictionSink(target)
    prediction = _prediction(frozen_row())

    staged = sink.stage((prediction,))
    staging = target.with_name(f".{target.name}.staging")
    assert staged.sha256 == hashlib.sha256(staging.read_bytes()).hexdigest()
    assert not target.exists()
    with pytest.raises(RunContractError, match="one-shot"):
        sink.stage((prediction,))
    sink.abort()
    assert not target.exists()
    assert not target.with_name(f".{target.name}.staging").exists()
    with pytest.raises(RunContractError, match="one-shot"):
        sink.commit()


def test_jsonl_sink_commits_exact_staged_bytes_and_refuses_existing_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "predictions.jsonl"
    sink = JsonlPredictionSink(target)
    staged = sink.stage((_prediction(frozen_row()),))
    committed = sink.commit()
    assert committed == staged
    assert hashlib.sha256(target.read_bytes()).hexdigest() == staged.sha256
    sink.abort()
    assert not target.exists()
    with pytest.raises(RunContractError, match="one-shot"):
        sink.abort()

    target.write_bytes(b"existing")
    with pytest.raises(RunContractError, match="already exists"):
        JsonlPredictionSink(target)


def test_jsonl_sink_abort_never_deletes_a_target_it_did_not_create(tmp_path: Path) -> None:
    target = tmp_path / "predictions.jsonl"
    sink = JsonlPredictionSink(target)
    target.write_bytes(b"foreign")

    sink.abort()

    assert target.read_bytes() == b"foreign"


def test_jsonl_sink_abort_preserves_a_replacement_after_commit(tmp_path: Path) -> None:
    target = tmp_path / "predictions.jsonl"
    sink = JsonlPredictionSink(target)
    sink.stage((_prediction(frozen_row()),))
    sink.commit()
    target.unlink()
    target.write_bytes(b"foreign-replacement")

    sink.abort()

    assert target.read_bytes() == b"foreign-replacement"


class _MismatchingCommitSink(JsonlPredictionSink):
    def commit(self) -> ArtifactIdentity:
        identity = super().commit()
        return identity.model_copy(update={"sha256": "0" * 64})


class _WrongStageIdentitySink(JsonlPredictionSink):
    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity:
        super().stage(predictions)
        return _artifact("wrong-stage")


class _DifferentPredictionSink(JsonlPredictionSink):
    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity:
        records = tuple(predictions)
        changed = records[0].model_copy(update={"reasons": ("different_prediction",)})
        return super().stage((changed, *records[1:]))


class _StreamingSink(JsonlPredictionSink):
    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity:
        assert not isinstance(predictions, (list, tuple))
        return super().stage(predictions)


class _MutatingCommitSink(JsonlPredictionSink):
    def __init__(self, target: Path, mutate: Callable[[], None]) -> None:
        super().__init__(target)
        self._mutate = mutate

    def commit(self) -> ArtifactIdentity:
        identity = super().commit()
        self._mutate()
        return identity


class _SwitchingTargetSink(JsonlPredictionSink):
    def __init__(self, target: Path, outside_target: Path) -> None:
        super().__init__(target)
        self._reported_target = target
        self._outside_target = outside_target

    @property
    def target(self) -> Path:
        return self._reported_target

    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity:
        identity = super().stage(predictions)
        self._reported_target = self._outside_target
        return identity


class _TargetCallbackSink(JsonlPredictionSink):
    def __init__(self, target: Path, callback: Callable[[], None]) -> None:
        super().__init__(target)
        self._callback = callback

    @property
    def target(self) -> Path:
        self._callback()
        return super().target


def test_run_arm_rolls_back_a_sink_owned_target_after_commit_identity_drift(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "mismatched.jsonl"
    sink = _MismatchingCommitSink(target)

    with pytest.raises(RunContractError, match="prediction sink identity changed"):
        run_arm(setup.rows, setup.factory, sink, setup.spec)

    assert not target.exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_rejects_wrong_staged_artifact_type_before_commit(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "wrong-stage.jsonl"
    sink = _WrongStageIdentitySink(target)

    with pytest.raises(RunContractError, match="staged prediction identity"):
        run_arm(setup.rows, setup.factory, sink, setup.spec)

    assert not target.exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_independently_binds_staged_bytes_to_same_run_predictions(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "different-predictions.jsonl"

    with pytest.raises(RunContractError, match="staged prediction identity mismatch"):
        run_arm(setup.rows, setup.factory, _DifferentPredictionSink(target), setup.spec)

    assert not target.exists()


def test_run_arm_streams_predictions_into_the_two_phase_sink(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    sink = _StreamingSink(setup.private_root / "streamed.jsonl")

    run_arm(setup.rows, setup.factory, sink, setup.spec)

    assert sink.target.is_file()


def test_run_arm_binds_the_validated_prediction_target_path(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    inside = setup.private_root / "inside.jsonl"
    outside = (tmp_path / "outside.jsonl").resolve()

    with pytest.raises(RunContractError, match="prediction sink target changed"):
        run_arm(
            setup.rows,
            setup.factory,
            _SwitchingTargetSink(inside, outside),
            setup.spec,
        )

    assert not inside.exists()
    assert not outside.exists()


def test_run_arm_revalidates_factory_and_resources_after_publication(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "mutating-commit.jsonl"

    def mutate() -> None:
        setup.factory.config_id = "changed-after-commit"
        setup.dependency_file.write_bytes(b"changed-after-commit")

    with pytest.raises(RunContractError, match="factory binding changed"):
        run_arm(
            setup.rows,
            setup.factory,
            _MutatingCommitSink(target, mutate),
            setup.spec,
        )

    assert not target.exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_revalidates_inventory_bytes_after_publication(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "mutating-resource-commit.jsonl"

    with pytest.raises(RunContractError, match="resource inventory entry changed"):
        run_arm(
            setup.rows,
            setup.factory,
            _MutatingCommitSink(
                target,
                lambda: setup.dependency_file.write_bytes(b"changed-after-commit"),
            ),
            setup.spec,
        )

    assert not target.exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_revalidates_input_inventory_manifests_after_publication(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path)
    target = setup.private_root / "mutating-inventory-manifest-commit.jsonl"

    with pytest.raises(RunContractError, match="resource inventory is invalid"):
        run_arm(
            setup.rows,
            setup.factory,
            _MutatingCommitSink(
                target,
                lambda: setup.spec.dependency_inventory_path.write_bytes(b"not-json"),
            ),
            setup.spec,
        )

    assert not target.exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_jsonl_sink_preserves_a_foreign_staging_replacement(tmp_path: Path) -> None:
    target = tmp_path / "predictions.jsonl"
    staging = target.with_name(f".{target.name}.staging")
    sink = JsonlPredictionSink(target)
    sink.stage((_prediction(frozen_row()),))
    staging.unlink()
    staging.write_bytes(b"foreign-staging-replacement")

    with pytest.raises(RunContractError, match="prediction staging identity changed"):
        sink.commit()

    assert staging.read_bytes() == b"foreign-staging-replacement"
    assert not target.exists()


def test_run_arm_publishes_the_same_single_execution_it_measures(tmp_path: Path) -> None:
    setup = _setup(
        tmp_path,
        launch_on_build=True,
        launch_per_prediction=True,
        cache_payload=b"same-run-cache",
    )

    measurements = run_arm(setup.rows, setup.factory, setup.sink, setup.spec)

    assert setup.factory.build_calls == 1
    assert setup.factory.prediction_calls == len(setup.rows)
    assert measurements.row_count == len(setup.rows)
    assert measurements.subprocess_count == 2
    assert measurements.preparation_ns == 0
    assert measurements.end_to_end_ns == measurements.total_ns
    assert measurements.resource_basis == "end-to-end-method"
    assert measurements.model_bytes == 0
    assert measurements.dependency_bytes == len(b"runtime-dependency")
    assert measurements.cache_bytes == len(b"same-run-cache")
    assert (
        measurements.predictions_sha256
        == hashlib.sha256((setup.private_root / "predictions.jsonl").read_bytes()).hexdigest()
    )
    assert setup.spec.resource_inventory_output.is_file()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((), "empty run"),
        ((frozen_row(), frozen_row()), "duplicate input row identity"),
        (
            (
                frozen_row(row_id="row-1", split=DatasetSplit.TRAIN),
                frozen_row(row_id="row-2", split=DatasetSplit.VALIDATION),
            ),
            "row split mismatch",
        ),
    ],
)
def test_run_arm_rejects_invalid_row_universes(
    tmp_path: Path,
    rows: tuple[FrozenRow, ...],
    message: str,
) -> None:
    setup_rows = rows or (frozen_row(),)
    setup = _setup(tmp_path, rows=setup_rows)
    with pytest.raises(RunContractError, match=message):
        run_arm(rows, setup.factory, setup.sink, setup.spec)
    assert not (setup.private_root / "predictions.jsonl").exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_rejects_wrong_row_sequence_identity(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    wrong_spec = setup.spec.model_copy(
        update={"row_sequence_identity": _artifact("wrong-row-sequence")}
    )
    with pytest.raises(RunContractError, match="row sequence identity mismatch"):
        run_arm(setup.rows, setup.factory, setup.sink, wrong_spec)


def test_run_arm_rejects_prediction_for_another_row_and_rolls_back(tmp_path: Path) -> None:
    def wrong_identity(row: FrozenRow) -> RowPrediction:
        return _prediction(row).model_copy(update={"row_id": "another-row"})

    setup = _setup(tmp_path, predict=wrong_identity)
    with pytest.raises(RunContractError, match="prediction identity mismatch"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)
    assert not (setup.private_root / "predictions.jsonl").exists()
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_rejects_unvalidated_proposal_evidence(tmp_path: Path) -> None:
    def unsupported(row: FrozenRow) -> RowPrediction:
        proposal = FieldProposal(
            role=FieldRole.DESCRIPTION,
            atom_ids=("missing",),
            raw_score=1.0,
        )
        return cast(
            RowPrediction,
            RowPrediction.model_construct(
                experiment_id="synthetic-arm",
                config_id="synthetic-config",
                document_id=row.document_id,
                row_id=row.row_id,
                predicted_type=row.baseline_type,
                evidence_atoms=(),
                proposals=(proposal,),
                exact_row_confidence=None,
                decision=Decision.ACCEPT,
                reasons=(),
            ),
        )

    setup = _setup(tmp_path, predict=unsupported)
    with pytest.raises(RunContractError, match="prediction evidence is invalid"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)


def test_run_arm_rejects_input_mutation(tmp_path: Path) -> None:
    def mutate(row: FrozenRow) -> RowPrediction:
        original_id = row.row_id
        object.__setattr__(row, "row_id", "mutated-row")
        return _prediction(row).model_copy(update={"row_id": original_id})

    setup = _setup(tmp_path, predict=mutate)
    with pytest.raises(RunContractError, match="input row mutation"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)
    assert setup.rows[0].row_id == "row-1"


def test_run_arm_passes_a_revalidated_clone_without_mutating_the_caller(tmp_path: Path) -> None:
    valid = frozen_row()
    forged = cast(
        FrozenRow,
        FrozenRow.model_construct(**(valid.model_dump(mode="python") | {"page_number": "1"})),
    )
    observed: list[type[object]] = []

    def inspect(row: FrozenRow) -> RowPrediction:
        observed.append(type(row.page_number))
        return _prediction(row)

    setup = _setup(tmp_path, rows=(valid,), predict=inspect)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_arm((forged,), setup.factory, setup.sink, setup.spec)

    assert observed == [int]
    assert forged.page_number == "1"
    assert caught == []


def test_run_arm_rechecks_every_row_after_the_complete_execution(tmp_path: Path) -> None:
    rows = (frozen_row(row_id="row-1"), frozen_row(row_id="row-2"))
    passed_rows: list[FrozenRow] = []

    def mutate_prior(row: FrozenRow) -> RowPrediction:
        passed_rows.append(row)
        if row.row_id == "row-2":
            object.__setattr__(passed_rows[0], "row_id", "mutated-after-first-prediction")
        return _prediction(row)

    setup = _setup(tmp_path, rows=rows, predict=mutate_prior)
    with pytest.raises(RunContractError, match="input row mutation"):
        run_arm(rows, setup.factory, setup.sink, setup.spec)


def test_run_arm_rejects_factory_identity_drift(tmp_path: Path) -> None:
    setup = _setup(tmp_path)

    original_build = setup.factory.build

    def drifting_build() -> ExperimentArm:
        arm = original_build()
        setup.factory.config_id = "changed-config"
        return arm

    setup.factory.build = drifting_build  # type: ignore[method-assign]
    with pytest.raises(RunContractError, match="factory binding changed"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)


def test_run_arm_rejects_changed_inventory_content(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    setup.dependency_file.write_bytes(b"changed-after-inventory")

    with pytest.raises(RunContractError, match="resource inventory entry changed"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)
    assert not setup.spec.resource_inventory_output.exists()


def test_run_arm_rejects_cache_and_inventory_path_escape_or_reuse(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    escaped = setup.spec.model_copy(update={"cache_root": (tmp_path / "outside").resolve()})
    with pytest.raises(RunContractError, match="private root"):
        run_arm(setup.rows, setup.factory, setup.sink, escaped)

    setup = _setup(tmp_path / "second")
    setup.spec.cache_root.mkdir()
    (setup.spec.cache_root / "old.cache").write_bytes(b"old")
    with pytest.raises(RunContractError, match="new empty cache"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)


def test_run_arm_rejects_output_paths_inside_the_measured_cache(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    sink = JsonlPredictionSink(setup.spec.cache_root / "predictions.jsonl")
    with pytest.raises(RunContractError, match="cache and output paths overlap"):
        run_arm(setup.rows, setup.factory, sink, setup.spec)

    setup = _setup(tmp_path / "inventory")
    overlapping_spec = setup.spec.model_copy(
        update={
            "resource_inventory_output": setup.spec.cache_root / "resources.json",
        }
    )
    with pytest.raises(RunContractError, match="cache and output paths overlap"):
        run_arm(setup.rows, setup.factory, setup.sink, overlapping_spec)


def test_run_arm_never_removes_a_resource_output_it_did_not_create(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    setup.spec.resource_inventory_output.write_bytes(b"foreign-resource-output")

    with pytest.raises(RunContractError, match="resource inventory output already exists"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)

    assert setup.spec.resource_inventory_output.read_bytes() == b"foreign-resource-output"


def test_resource_inventory_rollback_preserves_a_foreign_link_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = _setup(tmp_path)
    original_link = runner_module.os.link

    def replace_after_link(
        source: Path,
        destination: Path,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        original_link(source, destination, follow_symlinks=follow_symlinks)
        if Path(destination) == setup.spec.resource_inventory_output:
            Path(destination).unlink()
            Path(destination).write_bytes(b"foreign-resource-replacement")

    monkeypatch.setattr(runner_module.os, "link", replace_after_link)

    with pytest.raises(RunContractError, match="resource inventory output identity changed"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)

    assert setup.spec.resource_inventory_output.read_bytes() == b"foreign-resource-replacement"


def test_run_arm_uses_nearest_rank_quantiles_and_exact_clock_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = tuple(frozen_row(row_id=f"row-{index}") for index in range(1, 4))
    setup = _setup(tmp_path, rows=rows)
    ticks = iter((0, 10, 20, 30, 50, 60, 90, 100))
    monkeypatch.setattr(
        "experiments.row_extraction.runner.perf_counter_ns",
        lambda: next(ticks),
    )

    measurements = run_arm(rows, setup.factory, setup.sink, setup.spec)

    assert measurements.total_ns == 100
    assert measurements.cold_start_ns == 20
    assert measurements.p50_ns == 20
    assert measurements.p95_ns == 30
    assert measurements.throughput_rows_per_second == Decimal("30000000")


def test_run_arm_rejects_a_nonadvancing_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = _setup(tmp_path)
    monkeypatch.setattr("experiments.row_extraction.runner.perf_counter_ns", lambda: 1)
    with pytest.raises(RunContractError, match="measurement clock did not advance"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)
    assert not (setup.private_root / "predictions.jsonl").exists()


def test_run_arm_uses_self_plus_waited_children_rss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = _setup(tmp_path)

    def usage(who: int) -> SimpleNamespace:
        return SimpleNamespace(ru_maxrss=3 if who == resource.RUSAGE_SELF else 5)

    monkeypatch.setattr("experiments.row_extraction.runner.resource.getrusage", usage)
    measurements = run_arm(setup.rows, setup.factory, setup.sink, setup.spec)
    assert measurements.peak_rss_bytes == 8 * 1024


def test_run_arm_samples_rss_before_resource_inventory_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = _setup(tmp_path)
    events: list[str] = []
    original_cache_inventory = runner_module._cache_inventory

    def rss() -> int:
        events.append("rss")
        return 1024

    def cache_inventory(path: Path) -> ResourceInventory:
        events.append("inventory")
        return original_cache_inventory(path)

    monkeypatch.setattr(runner_module, "_rss_high_water_bytes", rss)
    monkeypatch.setattr(runner_module, "_cache_inventory", cache_inventory)

    run_arm(setup.rows, setup.factory, setup.sink, setup.spec)

    assert events == ["rss", "inventory", "inventory"]


def _page_preparation(
    setup: _RunSetup,
    *,
    cache_payload: bytes = b"prepared",
    manifest_payload: bytes | None = None,
) -> tuple[ResourceSpec, PreparationMeasurements]:
    preparation_cache = setup.private_root / "preparation-cache"
    preparation_cache.mkdir()
    prepared_evidence = preparation_cache / "page-evidence.jsonl"
    prepared_evidence.write_bytes(cache_payload)
    selected_manifest_payload = cache_payload if manifest_payload is None else manifest_payload
    manifest_identity = ArtifactIdentity(
        artifact_type="jsonl",
        sha256=hashlib.sha256(selected_manifest_payload).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(selected_manifest_payload),
    )
    spec = setup.spec.model_copy(update={"arm_manifest_identity": manifest_identity})
    setup.factory.arm_manifest_identity = manifest_identity
    model_inventory = ResourceInventory.model_validate_json(spec.model_inventory_path.read_bytes())
    dependency_inventory = ResourceInventory.model_validate_json(
        spec.dependency_inventory_path.read_bytes()
    )
    cache_entry = ResourceInventoryEntry(
        category="cache",
        resolved_path=prepared_evidence,
        sha256=hashlib.sha256(cache_payload).hexdigest(),
        byte_size=len(cache_payload),
        device=prepared_evidence.stat().st_dev,
        inode=prepared_evidence.stat().st_ino,
    )
    preparation_inventory = ResourceInventory(
        version="row-resource-inventory-v1",
        entries=tuple(
            sorted(
                (*model_inventory.entries, *dependency_inventory.entries, cache_entry),
                key=lambda entry: (
                    entry.category,
                    str(entry.resolved_path),
                    entry.sha256,
                ),
            )
        ),
    )
    preparation_path = setup.private_root / "preparation-resources.json"
    preparation_identity = _write_inventory(preparation_path, preparation_inventory)
    preparation = PreparationMeasurements(
        experiment_id=spec.experiment_id,
        config_id=spec.config_id,
        row_sequence_identity=spec.row_sequence_identity,
        row_count=spec.expected_row_count,
        split=spec.split,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        preparation_ns=7,
        peak_rss_bytes=4096,
        subprocess_count=4,
        worker_count=1,
        runtime_identity=spec.runtime_identity,
        arm_manifest_identity=spec.arm_manifest_identity,
        resource_inventory_path=preparation_path,
        resource_inventory_identity=preparation_identity,
    )
    return spec, preparation


def test_run_arm_unions_matching_preparation_resources_once(tmp_path: Path) -> None:
    setup = _setup(
        tmp_path,
        cache_payload=b"run-cache",
        experiment_id="conditional-page-ocr",
    )
    spec, preparation = _page_preparation(setup)

    measurements = run_arm(
        setup.rows,
        setup.factory,
        setup.sink,
        spec,
        preparation,
    )

    assert measurements.preparation_ns == 7
    assert measurements.end_to_end_ns == measurements.total_ns + 7
    assert measurements.subprocess_count == 4
    assert measurements.cache_bytes == len(b"prepared") + len(b"run-cache")
    assert measurements.dependency_bytes == len(b"runtime-dependency")
    combined = ResourceInventory.model_validate_json(spec.resource_inventory_output.read_bytes())
    assert len([entry for entry in combined.entries if entry.category == "dependency"]) == 1


def test_page_preparation_inventory_must_contain_the_named_evidence_artifact(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    spec, preparation = _page_preparation(
        setup,
        cache_payload=b"unrelated-cache",
        manifest_payload=b"named-page-evidence",
    )

    with pytest.raises(RunContractError, match="preparation evidence artifact is absent"):
        run_arm(setup.rows, setup.factory, setup.sink, spec, preparation)


def test_page_preparation_record_is_consumed_by_only_one_successful_run(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    spec, preparation = _page_preparation(setup)
    run_arm(setup.rows, setup.factory, setup.sink, spec, preparation)

    second_cache = setup.private_root / "second-run-cache"
    second_spec = spec.model_copy(
        update={
            "cache_root": second_cache,
            "resource_inventory_output": setup.private_root / "second-resources.json",
        }
    )
    second_factory = _Factory(
        setup.rows,
        runtime_identity=spec.runtime_identity,
        arm_manifest_identity=spec.arm_manifest_identity,
        model_inventory_identity=spec.model_inventory_identity,
        dependency_inventory_identity=spec.dependency_inventory_identity,
        cache_root=second_cache,
        experiment_id="conditional-page-ocr",
    )

    with pytest.raises(RunContractError, match="preparation is already consumed"):
        run_arm(
            setup.rows,
            second_factory,
            JsonlPredictionSink(setup.private_root / "second-predictions.jsonl"),
            second_spec,
            preparation,
        )


def test_copying_preparation_inventory_cannot_bypass_single_consumption(
    tmp_path: Path,
) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    spec, preparation = _page_preparation(setup)
    run_arm(setup.rows, setup.factory, setup.sink, spec, preparation)

    copied_path = setup.private_root / "copied-preparation-resources.json"
    copied_path.write_bytes(preparation.resource_inventory_path.read_bytes())
    copied_preparation = preparation.model_copy(update={"resource_inventory_path": copied_path})
    second_cache = setup.private_root / "copy-run-cache"
    second_spec = spec.model_copy(
        update={
            "cache_root": second_cache,
            "resource_inventory_output": setup.private_root / "copy-resources.json",
        }
    )
    second_factory = _Factory(
        setup.rows,
        runtime_identity=spec.runtime_identity,
        arm_manifest_identity=spec.arm_manifest_identity,
        model_inventory_identity=spec.model_inventory_identity,
        dependency_inventory_identity=spec.dependency_inventory_identity,
        cache_root=second_cache,
        predict=lambda row: _prediction(row, experiment_id="conditional-page-ocr"),
        experiment_id="conditional-page-ocr",
    )

    with pytest.raises(RunContractError, match="preparation is already consumed"):
        run_arm(
            setup.rows,
            second_factory,
            JsonlPredictionSink(setup.private_root / "copy-predictions.jsonl"),
            second_spec,
            copied_preparation,
        )


def test_failed_page_run_releases_its_preparation_reservation(tmp_path: Path) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    spec, preparation = _page_preparation(setup)

    def fail_prediction(_row: FrozenRow) -> RowPrediction:
        raise RuntimeError("synthetic prediction failure")

    setup.factory._predict = fail_prediction
    with pytest.raises(RunContractError, match="measured arm execution failed"):
        run_arm(setup.rows, setup.factory, setup.sink, spec, preparation)

    retry_cache = setup.private_root / "retry-run-cache"
    retry_spec = spec.model_copy(
        update={
            "cache_root": retry_cache,
            "resource_inventory_output": setup.private_root / "retry-resources.json",
        }
    )
    retry_factory = _Factory(
        setup.rows,
        runtime_identity=spec.runtime_identity,
        arm_manifest_identity=spec.arm_manifest_identity,
        model_inventory_identity=spec.model_inventory_identity,
        dependency_inventory_identity=spec.dependency_inventory_identity,
        cache_root=retry_cache,
        predict=lambda row: _prediction(row, experiment_id="conditional-page-ocr"),
        experiment_id="conditional-page-ocr",
    )

    measurements = run_arm(
        setup.rows,
        retry_factory,
        JsonlPredictionSink(setup.private_root / "retry-predictions.jsonl"),
        retry_spec,
        preparation,
    )

    assert measurements.experiment_id == "conditional-page-ocr"


def test_preparation_marker_is_the_final_external_state_check(tmp_path: Path) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    spec, preparation = _page_preparation(setup)
    prediction_target = setup.private_root / "callback-predictions.jsonl"

    def remove_published_marker() -> None:
        markers = tuple(setup.private_root.glob(".row-preparation-*.consumed"))
        if prediction_target.exists() and spec.resource_inventory_output.exists() and markers:
            markers[0].unlink()

    with pytest.raises(RunContractError, match="preparation consumption marker changed"):
        run_arm(
            setup.rows,
            setup.factory,
            _TargetCallbackSink(prediction_target, remove_published_marker),
            spec,
            preparation,
        )

    assert not prediction_target.exists()
    assert not spec.resource_inventory_output.exists()


def test_run_arm_rejects_mismatching_or_materialized_preparation(tmp_path: Path) -> None:
    setup = _setup(
        tmp_path,
        resource_basis="materialized-adapter",
        experiment_id="accepted-baseline",
    )
    fake_path = setup.private_root / "preparation.json"
    fake_inventory = ResourceInventory(version="row-resource-inventory-v1", entries=())
    fake_identity = _write_inventory(fake_path, fake_inventory)
    preparation = PreparationMeasurements(
        experiment_id=setup.spec.experiment_id,
        config_id=setup.spec.config_id,
        row_sequence_identity=setup.spec.row_sequence_identity,
        row_count=setup.spec.expected_row_count,
        split=setup.spec.split,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        preparation_ns=1,
        peak_rss_bytes=1,
        subprocess_count=0,
        worker_count=1,
        runtime_identity=setup.spec.runtime_identity,
        arm_manifest_identity=setup.spec.arm_manifest_identity,
        resource_inventory_path=fake_path,
        resource_inventory_identity=fake_identity,
    )
    with pytest.raises(RunContractError, match="materialized adapter forbids preparation"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec, preparation)


def test_run_arm_reserves_preparation_for_page_baselines(tmp_path: Path) -> None:
    setup = _setup(tmp_path, experiment_id="conditional-page-ocr")
    with pytest.raises(RunContractError, match="page baseline requires preparation"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)

    setup = _setup(
        tmp_path / "accepted",
        experiment_id="accepted-baseline",
        resource_basis="end-to-end-method",
    )
    with pytest.raises(RunContractError, match="accepted baseline resource basis"):
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec)


def test_accepted_materialized_adapter_requires_an_empty_model_inventory(
    tmp_path: Path,
) -> None:
    setup = _setup(
        tmp_path,
        experiment_id="accepted-baseline",
        resource_basis="materialized-adapter",
    )
    model_file = setup.private_root / "unexpected-model.bin"
    model_file.write_bytes(b"model")
    inventory = build_resource_inventory(
        InventoryRoots(
            version="row-resource-roots-v1",
            category="model",
            roots=(model_file,),
        )
    )
    model_path = setup.private_root / "nonempty-models.json"
    model_identity = _write_inventory(model_path, inventory)
    setup.factory.model_inventory_identity = model_identity
    spec = setup.spec.model_copy(
        update={
            "model_inventory_path": model_path,
            "model_inventory_identity": model_identity,
        }
    )

    with pytest.raises(RunContractError, match="accepted baseline model inventory must be empty"):
        run_arm(setup.rows, setup.factory, setup.sink, spec)


def test_resource_models_reject_zero_or_unknown_measurements() -> None:
    valid = dict(
        experiment_id="arm",
        config_id="config",
        row_sequence_identity=_artifact("rows"),
        split=DatasetSplit.TRAIN,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        arm_manifest_identity=_artifact("arm"),
        row_count=1,
        total_ns=1,
        p50_ns=1,
        p95_ns=1,
        preparation_ns=0,
        end_to_end_ns=1,
        cold_start_ns=1,
        throughput_rows_per_second=Decimal(1),
        peak_rss_bytes=1,
        model_bytes=0,
        dependency_bytes=1,
        cache_bytes=0,
        subprocess_count=0,
        worker_count=1,
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=_artifact("runtime"),
        model_inventory_identity=_artifact("models"),
        dependency_inventory_identity=_artifact("dependencies"),
        resource_inventory_identity=_artifact("resources"),
        predictions_sha256="0" * 64,
    )
    assert RunMeasurements(**valid).row_count == 1
    with pytest.raises(ValueError):
        RunMeasurements(**(valid | {"row_count": 0}))
    with pytest.raises(ValueError):
        RunMeasurements(**(valid | {"total_ns": 0}))


def test_run_arm_revalidates_forged_resource_spec_and_preparation(tmp_path: Path) -> None:
    setup = _setup(tmp_path)
    forged_spec = setup.spec.model_copy(update={"expected_row_count": 0})
    with pytest.raises(RunContractError, match="invalid resource specification") as error:
        run_arm(setup.rows, setup.factory, setup.sink, forged_spec)
    assert error.value.__cause__ is None

    setup = _setup(tmp_path / "preparation")
    forged_preparation = PreparationMeasurements.model_construct(
        experiment_id=setup.spec.experiment_id,
        config_id=setup.spec.config_id,
        row_sequence_identity=setup.spec.row_sequence_identity,
        row_count=setup.spec.expected_row_count,
        split=setup.spec.split,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        preparation_ns=0,
        peak_rss_bytes=0,
        subprocess_count=0,
        worker_count=1,
        runtime_identity=setup.spec.runtime_identity,
        arm_manifest_identity=setup.spec.arm_manifest_identity,
        resource_inventory_path=setup.private_root / "missing.json",
        resource_inventory_identity=_artifact("missing"),
    )
    with pytest.raises(RunContractError, match="invalid preparation measurements") as error:
        run_arm(setup.rows, setup.factory, setup.sink, setup.spec, forged_preparation)
    assert error.value.__cause__ is None


def test_assert_repeated_output_requires_distinct_canonical_equal_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    payload = _canonical_record_bytes(_prediction(frozen_row()))
    first.write_bytes(payload)
    second.write_bytes(payload)

    runner_module.assert_repeated_output(first, second)

    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("variant", ["same", "different", "missing", "directory", "symlink"])
def test_assert_repeated_output_fails_closed_without_values(
    tmp_path: Path,
    variant: str,
) -> None:
    first = tmp_path / "private-first.jsonl"
    second = tmp_path / "private-second.jsonl"
    first.write_bytes(_canonical_record_bytes(_prediction(frozen_row())))
    if variant == "same":
        second = first
    elif variant == "different":
        second.write_bytes(_canonical_record_bytes(_prediction(frozen_row(row_id="row-2"))))
    elif variant == "missing":
        pass
    elif variant == "directory":
        second.mkdir()
    else:
        second.symlink_to(first)

    with pytest.raises(RunContractError, match="repeated prediction output") as error:
        runner_module.assert_repeated_output(first, second)

    rendered = str(error.value)
    assert "private-first" not in rendered
    assert "private-second" not in rendered
    assert error.value.__cause__ is None


def test_assert_repeated_output_rejects_equal_noncanonical_jsonl(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    payload = json.dumps(
        _prediction(frozen_row()).model_dump(mode="json"),
        indent=2,
    ).encode("utf-8")
    first.write_bytes(payload)
    second.write_bytes(payload)

    with pytest.raises(RunContractError, match="repeated prediction output"):
        runner_module.assert_repeated_output(first, second)
