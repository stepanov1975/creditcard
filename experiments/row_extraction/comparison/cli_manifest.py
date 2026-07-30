"""Closed serializable inputs for the exactly-once comparison controller."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationError, field_validator, model_validator

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel

from .cli_paths import require_private_containment, resolved_overlap
from .cli_state import stable_regular_bytes
from .result_catalog import BASELINE_IDS, LANE_IDS, BaselineId, LaneId

BASELINE_INPUT_IDS = BASELINE_IDS
LANE_INPUT_IDS = LANE_IDS

type LoaderKind = BaselineId
type LaneSchemaKind = Literal[
    "ocr_stop_v2",
    "profiles_v2",
    "text_stop_v2",
    "vision_stop_v2",
]

_SHA40_PATTERN = r"^[0-9a-f]{40}$"
_SCHEMA_BY_LANE: dict[str, str] = {
    "row-ocr": "ocr_stop_v2",
    "row-profiles": "profiles_v2",
    "row-text": "text_stop_v2",
    "row-vision": "vision_stop_v2",
}


def _absolute(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    normalized = Path(os.path.normpath(os.fspath(path)))
    if normalized != path:
        raise ValueError("path must be lexically normalized")
    return path


class PinnedArtifact(_FrozenModel):
    """One deferred or pre-lock file path with a predeclared byte identity."""

    path: Path
    identity: ArtifactIdentity

    _absolute_path = field_validator("path")(_absolute)


class GitCheckoutPin(_FrozenModel):
    """Exact source checkout required by one controller stage."""

    root: Path
    commit_sha: str = Field(pattern=_SHA40_PATTERN)

    _absolute_root = field_validator("root")(_absolute)


class ProfileSourcePin(_FrozenModel):
    """Pinned profile package tree imported only from a validated snapshot."""

    checkout: GitCheckoutPin
    package_tree_sha: str = Field(pattern=_SHA40_PATTERN)


class DeferredLockedInputs(_FrozenModel):
    """Paths that pre-lock stages may parse but must never dereference."""

    rows: PinnedArtifact
    gold: PinnedArtifact
    accepted_predictions: PinnedArtifact
    accepted_predictions_identity_file: PinnedArtifact
    optional_ocr_references: PinnedArtifact | None = None


class HandoffArtifacts(_FrozenModel):
    """Located evidence authenticated by a raw handoff and central replay."""

    foundation_sha: str = Field(pattern=_SHA40_PATTERN)
    bundle_identity: ArtifactIdentity
    split_identity: ArtifactIdentity
    label_identity: ArtifactIdentity
    runtime_identity: ArtifactIdentity
    model_inventory: PinnedArtifact
    dependency_inventory: PinnedArtifact
    validation_predictions: PinnedArtifact
    validation_metrics: PinnedArtifact
    validation_measurements: tuple[PinnedArtifact, ...] = Field(max_length=2)
    validation_measurement_envelope: PinnedArtifact | None = None
    validation_error_summary: PinnedArtifact | None
    arm_manifest: PinnedArtifact | None


class BaselineCliInput(HandoffArtifacts):
    """Closed serializable input for one shared baseline control."""

    experiment_id: BaselineId
    loader_kind: LoaderKind
    config_id: str = Field(min_length=1)
    validation_replay_cache_root: Path

    _absolute_replay_cache = field_validator("validation_replay_cache_root")(_absolute)

    @model_validator(mode="after")
    def kind_matches_identity(self) -> Self:
        if (
            self.loader_kind != self.experiment_id
            or self.arm_manifest is None
            or not self.validation_measurements
            or self.validation_measurement_envelope is not None
        ):
            raise ValueError("baseline loader binding mismatch")
        return self


class LaneCliInput(_FrozenModel):
    """Discriminated raw lane schema plus explicitly located artifacts."""

    experiment_id: LaneId
    schema_kind: LaneSchemaKind
    raw_handoff: PinnedArtifact
    artifacts: HandoffArtifacts
    validation_replay_cache_root: Path | None = None
    source_commit_sha: str | None = Field(default=None, pattern=_SHA40_PATTERN)

    @field_validator("validation_replay_cache_root")
    @classmethod
    def absolute_optional_path(cls, value: Path | None) -> Path | None:
        return None if value is None else _absolute(value)

    @model_validator(mode="after")
    def closed_lane_shape(self) -> Self:
        if self.schema_kind != _SCHEMA_BY_LANE[self.experiment_id]:
            raise ValueError("lane schema kind mismatch")
        eligible = self.experiment_id == "row-profiles"
        if eligible != (self.validation_replay_cache_root is not None):
            raise ValueError("lane replay-cache binding mismatch")
        if eligible != (self.artifacts.arm_manifest is not None):
            raise ValueError("lane frozen-arm binding mismatch")
        if eligible != (self.artifacts.validation_measurement_envelope is not None):
            raise ValueError("lane measurement-envelope binding mismatch")
        if eligible == bool(self.artifacts.validation_measurements):
            raise ValueError("lane measurement-member binding mismatch")
        return self


class LockedComparisonCliManifestV1(_FrozenModel):
    """Canonical controller manifest; locked paths remain opaque until the marker."""

    version: Literal["row-extraction-locked-comparison-cli-v1"]
    private_root: Path
    workspace_root: Path
    comparison_checkout: GitCheckoutPin
    foundation_sha: str = Field(pattern=_SHA40_PATTERN)
    expected_bundle_identity: ArtifactIdentity
    expected_split_identity: ArtifactIdentity
    expected_label_identity: ArtifactIdentity
    foundation_bundle: PinnedArtifact
    split_manifest: PinnedArtifact
    validation_rows: PinnedArtifact
    validation_gold: PinnedArtifact
    validation_ocr_references: PinnedArtifact | None = None
    locked_row_ids: PinnedArtifact
    locked_inputs: DeferredLockedInputs
    baselines: Mapping[str, BaselineCliInput]
    lanes: Mapping[str, LaneCliInput]
    profiles_source: ProfileSourcePin

    _absolute_private_root = field_validator("private_root")(_absolute)
    _absolute_workspace_root = field_validator("workspace_root")(_absolute)

    @model_validator(mode="after")
    def closed_program_and_paths(self) -> Self:
        if set(self.baselines) != set(BASELINE_INPUT_IDS):
            raise ValueError("baseline key set mismatch")
        if set(self.lanes) != set(LANE_INPUT_IDS):
            raise ValueError("lane key set mismatch")
        if any(key != value.experiment_id for key, value in self.baselines.items()):
            raise ValueError("baseline key binding mismatch")
        if any(key != value.experiment_id for key, value in self.lanes.items()):
            raise ValueError("lane key binding mismatch")
        if (
            self.foundation_bundle.identity != self.expected_bundle_identity
            or self.split_manifest.identity != self.expected_split_identity
            or self.validation_gold.identity != self.expected_label_identity
        ):
            raise ValueError("foundation artifact identity mismatch")
        try:
            workspace_root = require_private_containment(
                self.workspace_root,
                self.private_root,
            )
            pinned_paths = {
                value.path: require_private_containment(value.path, self.private_root)
                for value in self._pinned_inputs()
            }
        except ValueError as error:
            raise ValueError(str(error)) from None
        if self.workspace_root == self.private_root:
            raise ValueError("workspace root must be beneath private root")

        pinned = list(self._pinned_inputs())
        if any(
            resolved_overlap(deferred.path, prelock.path)
            for deferred in self._deferred_pins()
            for prelock in self._prelock_pins()
        ):
            raise ValueError("deferred and pre-lock input paths overlap")
        for index, first in enumerate(pinned):
            if pinned_paths[first.path] == workspace_root or pinned_paths[
                first.path
            ].is_relative_to(workspace_root):
                raise ValueError("input and workspace paths overlap")
            for second in pinned[index + 1 :]:
                if resolved_overlap(first.path, second.path) and first != second:
                    raise ValueError("private input paths overlap")

        outputs = tuple(
            value.validation_replay_cache_root for value in self.baselines.values()
        ) + tuple(
            value.validation_replay_cache_root
            for value in self.lanes.values()
            if value.validation_replay_cache_root is not None
        )
        if any(
            require_private_containment(output, self.workspace_root) == workspace_root
            for output in outputs
        ):
            raise ValueError("replay cache escapes workspace")
        if any(
            resolved_overlap(first, second)
            for i, first in enumerate(outputs)
            for second in outputs[i + 1 :]
        ):
            raise ValueError("controller output paths overlap")
        return self

    def _pinned_inputs(self) -> tuple[PinnedArtifact, ...]:
        return (*self._prelock_pins(), *self._deferred_pins())

    def _prelock_pins(self) -> tuple[PinnedArtifact, ...]:
        common = (
            self.foundation_bundle,
            self.split_manifest,
            self.validation_rows,
            self.validation_gold,
            self.locked_row_ids,
        )
        optional = tuple(value for value in (self.validation_ocr_references,) if value is not None)
        baseline = tuple(
            artifact for value in self.baselines.values() for artifact in _handoff_pins(value)
        )
        lanes = tuple(
            artifact
            for value in self.lanes.values()
            for artifact in (value.raw_handoff, *_handoff_pins(value.artifacts))
        )
        return (*common, *optional, *baseline, *lanes)

    def _deferred_pins(self) -> tuple[PinnedArtifact, ...]:
        optional = tuple(
            value for value in (self.locked_inputs.optional_ocr_references,) if value is not None
        )
        return (
            self.locked_inputs.rows,
            self.locked_inputs.gold,
            self.locked_inputs.accepted_predictions,
            self.locked_inputs.accepted_predictions_identity_file,
            *optional,
        )

    def canonical_bytes(self) -> bytes:
        return _canonical_json_value_content(self.model_dump(mode="json")) + b"\n"


def _handoff_pins(value: HandoffArtifacts) -> tuple[PinnedArtifact, ...]:
    optional = tuple(
        artifact
        for artifact in (
            value.validation_error_summary,
            value.arm_manifest,
            value.validation_measurement_envelope,
        )
        if artifact is not None
    )
    return (
        value.model_inventory,
        value.dependency_inventory,
        value.validation_predictions,
        value.validation_metrics,
        *value.validation_measurements,
        *optional,
    )


def read_cli_manifest(path: Path) -> LockedComparisonCliManifestV1:
    """Read one canonical manifest without dereferencing any path it contains."""

    try:
        payload = stable_regular_bytes(path, "invalid comparison manifest")
        manifest = LockedComparisonCliManifestV1.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        raise ValueError("invalid comparison manifest") from None
    if payload != manifest.canonical_bytes():
        raise ValueError("comparison manifest is not canonical")
    return manifest


__all__ = [
    "BASELINE_INPUT_IDS",
    "LANE_INPUT_IDS",
    "BaselineCliInput",
    "DeferredLockedInputs",
    "GitCheckoutPin",
    "HandoffArtifacts",
    "LaneCliInput",
    "LockedComparisonCliManifestV1",
    "PinnedArtifact",
    "ProfileSourcePin",
    "read_cli_manifest",
]
