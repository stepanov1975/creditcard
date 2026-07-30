"""Contracts and canonical artifact I/O for the pre-lock state machine."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Never

from pydantic import Field, ValidationError, model_validator

from experiments.row_extraction.contracts import ArtifactIdentity, LaneDisposition, _FrozenModel

from .cli_manifest import LockedComparisonCliManifestV1
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    stable_regular_bytes,
    write_identified_model,
)

_MANIFEST_TYPE = "row-comparison-cli-manifest"
_MANIFEST_VERSION = "row-extraction-locked-comparison-cli-v1"


class PrelockError(ValueError):
    """A pre-lock stage cannot advance without changing frozen evidence."""


def fail_prelock(message: str) -> Never:
    raise PrelockError(message)


class EmptyCascadePolicy(_FrozenModel):
    version: Literal["row-cascade-policy-v1"]
    rules: tuple[()] = ()


class FrozenCascadeEnvelopeV1(_FrozenModel):
    version: Literal["row-comparison-frozen-cascade-envelope-v1"]
    comparison_manifest_identity: ArtifactIdentity
    validation_receipt_identity: ArtifactIdentity
    comparison_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    profiles_source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locked_row_ids_identity: ArtifactIdentity
    baseline_id: Literal["accepted-baseline"]
    dispositions: dict[str, LaneDisposition]
    validation_prediction_identities: dict[str, ArtifactIdentity]
    eligible_candidate_ids: tuple[Literal["row-profiles"], ...]
    excluded_control_ids: tuple[Literal["conditional-page-ocr"], Literal["forced-page-ocr"]]
    exclusion_reason_codes: tuple[str, ...]
    candidate_policy_count: Literal[0]
    policy: EmptyCascadePolicy
    test_accessed: Literal[False]

    @model_validator(mode="after")
    def closed_empty_policy(self) -> FrozenCascadeEnvelopeV1:
        if (
            self.eligible_candidate_ids != ("row-profiles",)
            or self.excluded_control_ids != ("conditional-page-ocr", "forced-page-ocr")
            or self.policy.rules
        ):
            raise ValueError("frozen cascade envelope is not the closed empty policy")
        return self


def manifest_identity(
    path: Path,
    manifest: LockedComparisonCliManifestV1,
) -> ArtifactIdentity:
    payload = manifest.canonical_bytes()
    try:
        if stable_regular_bytes(path, "comparison manifest identity mismatch") != payload:
            fail_prelock("comparison manifest identity mismatch")
    except OSError:
        fail_prelock("comparison manifest identity mismatch")
    return identity_for_bytes(
        payload,
        artifact_type=_MANIFEST_TYPE,
        version=_MANIFEST_VERSION,
    )


def read_canonical_model[Model: _FrozenModel](path: Path, model: type[Model]) -> Model:
    try:
        payload = stable_regular_bytes(path, "pre-lock artifact is invalid")
        value = model.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        fail_prelock("pre-lock artifact is invalid")
    if payload != canonical_model_bytes(value):
        fail_prelock("pre-lock artifact is invalid")
    return value


def read_identity(path: Path) -> ArtifactIdentity:
    return read_canonical_model(path, ArtifactIdentity)


__all__ = [
    "EmptyCascadePolicy",
    "FrozenCascadeEnvelopeV1",
    "PrelockError",
    "fail_prelock",
    "manifest_identity",
    "read_canonical_model",
    "read_identity",
    "write_identified_model",
]
