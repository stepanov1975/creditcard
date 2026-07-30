"""Shared-runner backend for the fixed central locked execution schedule."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from experiments.row_extraction.cli import (
    _prepare_page_evidence,
    _prepare_run_spec,
    _run_baseline,
)
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.runner import (
    JsonlPredictionSink,
    PreparationMeasurements,
    ResourceSpec,
    RunMeasurements,
    assert_repeated_output,
    run_arm,
)

from .cli_execution_support import (
    LockedExecutionError,
    MeasuredLockedRun,
    PreparedPage,
    assert_preparation_repeat,
    assert_static_spec,
    prediction_identity,
    read_output_model,
    runtime_path,
    write_runtime,
)
from .cli_execution_support import (
    fail_execution as _fail,
)
from .cli_locked import LockedInputs
from .cli_manifest import LockedComparisonCliManifestV1
from .cli_schedule import LockedRunPaths
from .cli_state import canonical_model_bytes, write_bytes_exclusive
from .handoff_contracts import ValidatedHandoffs
from .profile_loader import ProfileLaneAdapter

type BaselineMode = Literal[
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
]
type PageMode = Literal["conditional-page-ocr", "forced-page-ocr"]


class SharedLockedBackend:
    """Perform only the four predeclared arms using the repository shared runner."""

    def __init__(
        self,
        cli: LockedComparisonCliManifestV1,
        locked: LockedInputs,
        handoffs: ValidatedHandoffs,
        profile_adapter: ProfileLaneAdapter,
    ) -> None:
        self._cli = cli
        self._locked = locked
        self._handoffs = handoffs
        self._profile_adapter = profile_adapter
        self._factories: list[object] = []

    def prepare(self, paths: LockedRunPaths) -> PreparedPage:
        if paths.experiment_id not in {"conditional-page-ocr", "forced-page-ocr"}:
            _fail("unexpected page preparation")
        if any(
            value is None
            for value in (
                paths.preparation_cache,
                paths.page_evidence,
                paths.page_evidence_identity,
                paths.preparation_measurements,
                paths.preparation_resource_inventory,
            )
        ):
            _fail("page preparation paths are incomplete")
        preparation_cache = cast(Path, paths.preparation_cache)
        evidence = cast(Path, paths.page_evidence)
        evidence_identity_path = cast(Path, paths.page_evidence_identity)
        measurement_path = cast(Path, paths.preparation_measurements)
        inventory_path = cast(Path, paths.preparation_resource_inventory)
        run_input = self._handoffs.run_inputs[paths.experiment_id]
        runtime_path = write_runtime(paths, run_input)
        baseline = self._cli.baselines[cast(BaselineMode, paths.experiment_id)]
        _prepare_page_evidence(
            private_root=self._cli.private_root,
            rows_path=self._cli.locked_inputs.rows.path,
            split=DatasetSplit.TEST,
            mode=cast(PageMode, paths.experiment_id),
            runtime_path=runtime_path,
            cache_dir=preparation_cache,
            output=evidence,
            identity_output=evidence_identity_path,
            model_inventory_path=baseline.model_inventory.path,
            dependency_inventory_path=baseline.dependency_inventory.path,
            inventory_output=inventory_path,
            preparation_output=measurement_path,
        )
        identity = read_output_model(
            evidence_identity_path,
            ArtifactIdentity,
            "page evidence identity is invalid",
        )
        measurements = read_output_model(
            measurement_path,
            PreparationMeasurements,
            "page preparation measurement is invalid",
        )
        if (
            measurements.experiment_id != paths.experiment_id
            or measurements.config_id != run_input.config_id
            or measurements.row_sequence_identity != self._locked.row_sequence_identity
            or measurements.split is not DatasetSplit.TEST
            or measurements.runtime_identity != run_input.runtime_identity
            or measurements.arm_manifest_identity != identity
            or measurements.worker_count != 1
            or measurements.resource_inventory_path != inventory_path
        ):
            _fail("page preparation binding mismatch")
        return PreparedPage(evidence, identity, measurements)

    def _run_baseline(
        self,
        paths: LockedRunPaths,
        preparation: PreparedPage | None,
    ) -> MeasuredLockedRun:
        mode = cast(BaselineMode, paths.experiment_id)
        run_input = self._handoffs.run_inputs[paths.experiment_id]
        baseline = self._cli.baselines[mode]
        runtime = runtime_path(paths)
        if mode == "accepted-baseline":
            runtime = write_runtime(paths, run_input)
            arm_input = self._cli.locked_inputs.accepted_predictions.path
            arm_identity_path = self._cli.locked_inputs.accepted_predictions_identity_file.path
            preparation_path = None
        else:
            if preparation is None or preparation.measurements is None:
                _fail("page baseline lacks its own preparation")
            arm_input = preparation.evidence_path
            arm_identity_path = cast(Path, paths.page_evidence_identity)
            preparation_path = cast(Path, paths.preparation_measurements)
        _prepare_run_spec(
            private_root=self._cli.private_root,
            rows=self._cli.locked_inputs.rows.path,
            split=DatasetSplit.TEST,
            mode=mode,
            arm_manifest_identity=arm_identity_path,
            runtime_identity=runtime,
            model_inventory=baseline.model_inventory.path,
            dependency_inventory=baseline.dependency_inventory.path,
            cache_root=paths.run_cache,
            inventory_output=paths.resource_inventory,
            output=paths.run_spec,
        )
        spec = read_output_model(
            paths.run_spec, ResourceSpec, "locked run specification is invalid"
        )
        assert_static_spec(spec, run_input, paths)
        if mode == "accepted-baseline":
            if spec.arm_manifest_identity != self._cli.locked_inputs.accepted_predictions.identity:
                _fail("accepted locked manifest binding mismatch")
        elif preparation is None or spec.arm_manifest_identity != preparation.evidence_identity:
            _fail("page locked manifest binding mismatch")
        _run_baseline(
            private_root=self._cli.private_root,
            mode=mode,
            rows=self._cli.locked_inputs.rows.path,
            split=DatasetSplit.TEST,
            baseline_input=arm_input,
            baseline_identity=arm_identity_path,
            resource_spec=paths.run_spec,
            preparation=preparation_path,
            predictions_output=paths.predictions,
            run_output=paths.measurements,
        )
        measurements = read_output_model(
            paths.measurements,
            RunMeasurements,
            "locked run measurement is invalid",
        )
        prediction = prediction_identity(paths.predictions)
        if measurements.predictions_sha256 != prediction.sha256:
            _fail("locked prediction measurement binding mismatch")
        return MeasuredLockedRun(
            experiment_id=paths.experiment_id,
            config_id=run_input.config_id,
            paths=paths,
            predictions_identity=prediction,
            measurements=measurements,
            preparation=preparation,
        )

    def _run_profile(self, paths: LockedRunPaths) -> MeasuredLockedRun:
        run_input = self._handoffs.run_inputs["row-profiles"]
        factory = run_input.factory_loader(
            self._locked.rows,
            self._locked.row_sequence_identity,
            paths.run_cache,
        )
        if any(factory is prior for prior in self._factories):
            _fail("locked profile factory was reused")
        self._factories.append(factory)
        spec = self._profile_adapter.build_resource_spec(
            factory,
            private_root=self._cli.private_root,
            model_inventory_path=run_input.model_inventory_path,
            dependency_inventory_path=run_input.dependency_inventory_path,
            resource_inventory_output=paths.resource_inventory,
        )
        assert_static_spec(spec, run_input, paths)
        if spec.arm_manifest_identity != run_input.arm_manifest:
            _fail("profile locked manifest binding mismatch")
        write_bytes_exclusive(paths.run_spec, canonical_model_bytes(spec))
        measurements = run_arm(
            self._locked.rows,
            factory,
            JsonlPredictionSink(paths.predictions),
            spec,
        )
        write_bytes_exclusive(paths.measurements, canonical_model_bytes(measurements))
        prediction = prediction_identity(paths.predictions)
        if measurements.predictions_sha256 != prediction.sha256:
            _fail("locked prediction measurement binding mismatch")
        return MeasuredLockedRun(
            experiment_id="row-profiles",
            config_id=run_input.config_id,
            paths=paths,
            predictions_identity=prediction,
            measurements=measurements,
            preparation=None,
        )

    def run(
        self,
        paths: LockedRunPaths,
        preparation: PreparedPage | None,
    ) -> MeasuredLockedRun:
        if paths.experiment_id == "row-profiles":
            if preparation is not None:
                _fail("profile arm forbids preparation")
            return self._run_profile(paths)
        return self._run_baseline(paths, preparation)

    def assert_page_evidence(self, first: PreparedPage, second: PreparedPage) -> None:
        assert_preparation_repeat(first, second)

    def assert_predictions(self, first: MeasuredLockedRun, second: MeasuredLockedRun) -> None:
        assert_repeated_output(first.paths.predictions, second.paths.predictions)
        if (
            first.experiment_id != second.experiment_id
            or first.config_id != second.config_id
            or first.predictions_identity != second.predictions_identity
        ):
            _fail("locked prediction repeat mismatch")


__all__ = [
    "LockedExecutionError",
    "MeasuredLockedRun",
    "PreparedPage",
    "SharedLockedBackend",
    "assert_preparation_repeat",
]
