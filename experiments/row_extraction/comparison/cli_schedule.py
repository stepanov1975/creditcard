"""Fixed serial two-run filesystem schedule for the locked comparison."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol

from .result_catalog import BASELINE_IDS, ResultId

_LOCKED_IDS: tuple[ResultId, ...] = (*BASELINE_IDS, "row-profiles")
_PAGE_IDS = frozenset({"conditional-page-ocr", "forced-page-ocr"})


class LockedScheduleError(ValueError):
    """The locked schedule cannot preserve its exact fresh-path contract."""


def _fail(message: str) -> Never:
    raise LockedScheduleError(message)


@dataclass(frozen=True)
class LockedRunPaths:
    experiment_id: ResultId
    run_number: int
    run_root: Path
    run_cache: Path
    run_spec: Path
    predictions: Path
    measurements: Path
    resource_inventory: Path
    preparation_cache: Path | None
    page_evidence: Path | None
    page_evidence_identity: Path | None
    preparation_measurements: Path | None
    preparation_resource_inventory: Path | None


class LockedScheduleBackend[Preparation, Result](Protocol):
    def prepare(self, paths: LockedRunPaths) -> Preparation: ...

    def run(self, paths: LockedRunPaths, preparation: Preparation | None) -> Result: ...

    def assert_page_evidence(self, first: Preparation, second: Preparation) -> None: ...

    def assert_predictions(self, first: Result, second: Result) -> None: ...


def _paths(root: Path, experiment_id: ResultId, run_number: int) -> LockedRunPaths:
    run_root = root / experiment_id / f"run-{run_number}"
    try:
        run_root.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        _fail("locked run directory already exists")
    except OSError:
        _fail("locked run directory creation failed")
    page = experiment_id in _PAGE_IDS
    preparation_cache = run_root / "preparation-cache" if page else None
    return LockedRunPaths(
        experiment_id=experiment_id,
        run_number=run_number,
        run_root=run_root,
        run_cache=run_root / "run-cache",
        run_spec=run_root / "run-spec.json",
        predictions=run_root / "predictions.jsonl",
        measurements=run_root / "measurements.json",
        resource_inventory=run_root / "resource-inventory.json",
        preparation_cache=preparation_cache,
        page_evidence=(
            preparation_cache / "page-evidence.jsonl" if preparation_cache is not None else None
        ),
        page_evidence_identity=(
            preparation_cache / "page-evidence.identity.json"
            if preparation_cache is not None
            else None
        ),
        preparation_measurements=(run_root / "preparation-measurements.json" if page else None),
        preparation_resource_inventory=(
            run_root / "preparation-resource-inventory.json" if page else None
        ),
    )


def _require_unique_paths(values: tuple[LockedRunPaths, ...]) -> None:
    required = tuple(
        path
        for value in values
        for path in (
            value.run_cache,
            value.run_spec,
            value.predictions,
            value.measurements,
            value.resource_inventory,
            value.preparation_cache,
            value.page_evidence,
            value.page_evidence_identity,
            value.preparation_measurements,
            value.preparation_resource_inventory,
        )
        if path is not None
    )
    if len(required) != len(set(required)) or any(path.exists() for path in required):
        _fail("locked schedule paths are not distinct and new")


def execute_locked_schedule[Preparation, Result](
    arms_root: Path,
    backend: LockedScheduleBackend[Preparation, Result],
) -> dict[ResultId, tuple[Result, Result]]:
    """Execute exactly four arms twice, with four independent page preparations."""

    try:
        arms_root.mkdir(mode=0o700)
    except FileExistsError:
        _fail("locked arms stage already exists")
    except OSError:
        _fail("locked arms stage creation failed")
    paths = tuple(
        _paths(arms_root, experiment_id, run_number)
        for experiment_id in _LOCKED_IDS
        for run_number in (1, 2)
    )
    _require_unique_paths(paths)
    by_arm = {
        experiment_id: tuple(value for value in paths if value.experiment_id == experiment_id)
        for experiment_id in _LOCKED_IDS
    }
    pairs: dict[ResultId, tuple[Result, Result]] = {}
    for experiment_id in _LOCKED_IDS:
        first_path, second_path = by_arm[experiment_id]
        first_preparation = backend.prepare(first_path) if experiment_id in _PAGE_IDS else None
        first = backend.run(first_path, first_preparation)
        second_preparation = backend.prepare(second_path) if experiment_id in _PAGE_IDS else None
        second = backend.run(second_path, second_preparation)
        if first_preparation is not None and second_preparation is not None:
            backend.assert_page_evidence(first_preparation, second_preparation)
        backend.assert_predictions(first, second)
        pairs[experiment_id] = (first, second)
    return pairs


__all__ = [
    "LockedRunPaths",
    "LockedScheduleBackend",
    "LockedScheduleError",
    "execute_locked_schedule",
]
