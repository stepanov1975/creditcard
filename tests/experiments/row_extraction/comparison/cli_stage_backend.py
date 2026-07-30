from __future__ import annotations

from typing import cast

from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.comparison.cli_execution import (
    MeasuredLockedRun,
    PreparedPage,
    assert_preparation_repeat,
)
from experiments.row_extraction.comparison.cli_locked import LockedInputs
from experiments.row_extraction.comparison.cli_schedule import LockedRunPaths
from experiments.row_extraction.comparison.cli_state import canonical_model_bytes
from experiments.row_extraction.comparison.handoff_contracts import ValidatedHandoffs
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.runner import PreparationMeasurements
from tests.experiments.row_extraction.comparison.test_compare import (
    _measurement,
    _write_page_evidence,
    _write_preparation_measurements,
    _write_resource_inventory,
)

from .cli_stage_case import SyntheticCase, _locked_prediction


class SyntheticBackend:
    def __init__(
        self,
        case: SyntheticCase,
        locked: LockedInputs,
        handoffs: ValidatedHandoffs,
    ) -> None:
        self._case = case
        self._locked = locked
        self._handoffs = handoffs
        self.run_count = 0
        self.preparation_count = 0

    def prepare(self, locked_paths: LockedRunPaths) -> PreparedPage:
        assert locked_paths.preparation_cache is not None
        assert locked_paths.page_evidence is not None
        assert locked_paths.preparation_measurements is not None
        assert locked_paths.preparation_resource_inventory is not None
        locked_paths.preparation_cache.mkdir()
        binding = self._handoffs.arm_bindings[locked_paths.experiment_id]
        evidence_identity = _write_page_evidence(
            locked_paths.page_evidence,
            locked_paths.experiment_id,
            binding,
            page_keys=tuple((row.document_id, row.page_number) for row in self._case.rows),
        )
        inventory_identity = _write_resource_inventory(
            locked_paths.preparation_resource_inventory,
            cache_files=(locked_paths.page_evidence,),
        )
        measurements = PreparationMeasurements(
            experiment_id=locked_paths.experiment_id,
            config_id=binding.config_id,
            row_sequence_identity=self._locked.row_sequence_identity,
            row_count=len(self._case.rows),
            split=DatasetSplit.TEST,
            cache_policy="new-empty-v1",
            resource_basis="end-to-end-method",
            preparation_ns=30,
            peak_rss_bytes=1_024,
            subprocess_count=1,
            worker_count=1,
            runtime_identity=binding.runtime_identity,
            arm_manifest_identity=evidence_identity,
            resource_inventory_path=locked_paths.preparation_resource_inventory,
            resource_inventory_identity=inventory_identity,
        )
        _write_preparation_measurements(locked_paths.preparation_measurements, measurements)
        self.preparation_count += 1
        return PreparedPage(locked_paths.page_evidence, evidence_identity, measurements)

    def run(
        self,
        locked_paths: LockedRunPaths,
        preparation: PreparedPage | None,
    ) -> MeasuredLockedRun:
        binding = self._handoffs.arm_bindings[locked_paths.experiment_id]
        locked_paths.run_cache.mkdir()
        predictions = tuple(
            _locked_prediction(row, locked_paths.experiment_id, binding.config_id)
            for row in self._case.rows
        )
        prediction_identity = write_jsonl(locked_paths.predictions, predictions)
        inventory_identity = _write_resource_inventory(
            locked_paths.resource_inventory,
            cache_files=(() if preparation is None else (preparation.evidence_path,)),
        )
        measurements = _measurement(
            locked_paths.experiment_id,
            self._locked.row_sequence_identity,
            prediction_identity,
            binding,
            inventory_identity,
            split=DatasetSplit.TEST,
            arm_manifest_identity=(
                prediction_identity
                if locked_paths.experiment_id == "accepted-baseline"
                else (
                    preparation.evidence_identity
                    if preparation is not None
                    else cast(ArtifactIdentity, binding.arm_manifest)
                )
            ),
        )
        locked_paths.measurements.write_bytes(canonical_model_bytes(measurements))
        self.run_count += 1
        return MeasuredLockedRun(
            experiment_id=locked_paths.experiment_id,
            config_id=binding.config_id,
            paths=locked_paths,
            predictions_identity=prediction_identity,
            measurements=measurements,
            preparation=preparation,
        )

    def assert_page_evidence(self, first: PreparedPage, second: PreparedPage) -> None:
        assert_preparation_repeat(first, second)

    def assert_predictions(self, first: MeasuredLockedRun, second: MeasuredLockedRun) -> None:
        assert first.predictions_identity == second.predictions_identity
        assert first.paths.predictions.read_bytes() == second.paths.predictions.read_bytes()
