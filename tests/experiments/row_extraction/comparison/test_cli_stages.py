from pathlib import Path

import pytest

from .cli_stage_fixtures import (
    exercise_locked_split_manifest_rejection,
    exercise_synthetic_controller_progression,
)


def test_synthetic_controller_progresses_once_and_fails_closed_on_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exercise_synthetic_controller_progression(tmp_path, monkeypatch)


def test_locked_rows_require_frozen_test_split_after_marker(tmp_path: Path) -> None:
    exercise_locked_split_manifest_rejection(tmp_path)
