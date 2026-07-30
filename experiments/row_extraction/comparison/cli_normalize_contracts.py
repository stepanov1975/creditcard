"""Serializable contracts for independently normalized handoff evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never

from pydantic import Field

from experiments.row_extraction.contracts import ArtifactIdentity, LaneDisposition, _FrozenModel

from .cli_manifest import PinnedArtifact
from .handoff_contracts import ComparisonManifest
from .profile_loader import ProfileLaneAdapter


class NormalizationError(ValueError):
    """Pre-lock inputs cannot prove the closed comparison binding."""


def fail_normalization(message: str) -> Never:
    raise NormalizationError(message)


class NormalizedArmSnapshot(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    runtime_identity: ArtifactIdentity
    model_inventory: PinnedArtifact
    dependency_inventory: PinnedArtifact
    arm_manifest: PinnedArtifact | None
    validation_predictions: PinnedArtifact
    validation_metrics: PinnedArtifact
    validation_measurements: tuple[PinnedArtifact, ...]
    validation_error_summary: PinnedArtifact
    disposition: LaneDisposition | None
    stop_reason: str | None
    validation_replay_cache_root: Path | None


class NormalizedProgramSnapshot(_FrozenModel):
    version: Literal["row-comparison-normalized-program-v1"]
    foundation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    bundle_identity: ArtifactIdentity
    split_identity: ArtifactIdentity
    label_identity: ArtifactIdentity
    validation_rows: PinnedArtifact
    locked_row_ids: PinnedArtifact
    arms: tuple[NormalizedArmSnapshot, ...]


class NormalizationReceipt(_FrozenModel):
    version: Literal["row-comparison-normalization-receipt-v1"]
    comparison_manifest_identity: ArtifactIdentity
    comparison_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    profiles_source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_program_identity: ArtifactIdentity
    independently_recomputed_foundation_binding: Literal[True]
    stopped_source_generation_provenance: Literal["unreplayable_authenticated_outputs"]
    raw_handoff_identities: dict[str, ArtifactIdentity]
    source_commit_pins: dict[str, str | None]
    runtime_identities: dict[str, ArtifactIdentity]
    dispositions: dict[str, LaneDisposition]
    validation_prediction_identities: dict[str, ArtifactIdentity]
    provenance_limitations: dict[str, str]
    test_accessed: Literal[False]


@dataclass(frozen=True)
class NormalizedProgram:
    manifest: ComparisonManifest
    profile_adapter: ProfileLaneAdapter
    snapshot: NormalizedProgramSnapshot
    receipt: NormalizationReceipt


__all__ = [
    "NormalizationError",
    "NormalizationReceipt",
    "NormalizedArmSnapshot",
    "NormalizedProgram",
    "NormalizedProgramSnapshot",
    "fail_normalization",
]
