"""Closed adapters for the four heterogeneous raw lane handoff schemas."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Literal, Never, Self

from pydantic import Field, ValidationError, model_validator

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    LaneDisposition,
    _FrozenModel,
)
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import RunMeasurements

from .cli_manifest import LaneCliInput, PinnedArtifact
from .cli_state import (
    ControllerStateError,
    canonical_model_bytes,
    identity_for_bytes,
    read_pinned_model,
    verified_bytes,
)
from .handoff_contracts import runtime_identity_contract


class RawHandoffError(ValueError):
    """A raw lane handoff is not the exact closed schema its adapter expects."""


def _fail(message: str) -> Never:
    raise RawHandoffError(message)


def _require_runtime_contract(
    experiment_id: str,
    runtime_identity: ArtifactIdentity,
) -> None:
    contract = runtime_identity_contract(experiment_id)
    if (
        contract is None
        or runtime_identity.artifact_type != contract.artifact_type
        or runtime_identity.version != contract.version
    ):
        _fail("runtime identity contract mismatch")


class ProfileConfigRecord(_FrozenModel):
    version: Literal["tight", "default", "wide"]
    max_continuation_gap: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def predeclared(self) -> Self:
        expected = {
            "tight": Decimal("0.50"),
            "default": Decimal("0.75"),
            "wide": Decimal("1.00"),
        }
        if expected[self.version] != self.max_continuation_gap:
            raise ValueError("profile configuration is not predeclared")
        return self


def profile_config_identity(config: ProfileConfigRecord) -> ArtifactIdentity:
    """Identify the exact canonical deterministic profile configuration."""

    return identity_for_bytes(
        canonical_model_bytes(config),
        artifact_type="row-profile-config",
        version="row-profiles-config-v1",
    )


class RawProvenanceBinding(_FrozenModel):
    """Facts explicitly asserted by a raw lane handoff and its measurements."""

    version: Literal["row-lane-provenance-v1"]
    foundation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    bundle_identity: ArtifactIdentity
    split_identity: ArtifactIdentity
    label_identity: ArtifactIdentity
    config_id: str = Field(min_length=1)
    config_identity: ArtifactIdentity
    runtime_identity: ArtifactIdentity
    arm_manifest_identity: ArtifactIdentity
    model_inventory_identity: ArtifactIdentity
    dependency_inventory_identity: ArtifactIdentity
    resource_inventory_identities: tuple[ArtifactIdentity, ...] = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity

    @model_validator(mode="after")
    def canonical_label_contract(self) -> Self:
        if (
            self.label_identity.artifact_type != "labels"
            or self.label_identity.version != "canonical-jsonl-v1"
        ):
            raise ValueError("raw provenance requires canonical label identity")
        return self


class AuthenticatedLaneEvidence(_FrozenModel):
    """Schema-specific lane facts whose provenance came only from raw evidence."""

    experiment_id: Literal["row-ocr", "row-profiles", "row-text", "row-vision"]
    disposition: LaneDisposition
    stop_reason: str | None
    provenance: RawProvenanceBinding
    raw_handoff_identity: ArtifactIdentity
    source_commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    source_generation_replayed: bool
    provenance_limitation: Literal["stopped_source_generation_not_replayable"] | None

    @property
    def config_id(self) -> str:
        return self.provenance.config_id

    @property
    def runtime_identity(self) -> ArtifactIdentity:
        return self.provenance.runtime_identity


def authenticate_provenance(
    value: LaneCliInput,
    provenance: RawProvenanceBinding,
    *,
    disposition: LaneDisposition,
    stop_reason: str | None,
    source_commit_sha: str | None,
    source_generation_replayed: bool,
    provenance_limitation: Literal["stopped_source_generation_not_replayable"] | None,
) -> AuthenticatedLaneEvidence:
    """Bind raw-asserted provenance to outer artifact locations without filling facts."""

    artifacts = value.artifacts
    _require_runtime_contract(value.experiment_id, provenance.runtime_identity)
    if (
        provenance.foundation_sha != artifacts.foundation_sha
        or provenance.bundle_identity != artifacts.bundle_identity
        or provenance.split_identity != artifacts.split_identity
        or provenance.label_identity != artifacts.label_identity
        or provenance.runtime_identity != artifacts.runtime_identity
        or provenance.model_inventory_identity != artifacts.model_inventory.identity
        or provenance.dependency_inventory_identity != artifacts.dependency_inventory.identity
    ):
        _fail("raw provenance locator mismatch")
    return AuthenticatedLaneEvidence(
        experiment_id=value.experiment_id,
        disposition=disposition,
        stop_reason=stop_reason,
        provenance=provenance,
        raw_handoff_identity=value.raw_handoff.identity,
        source_commit_sha=source_commit_sha,
        source_generation_replayed=source_generation_replayed,
        provenance_limitation=provenance_limitation,
    )


def authenticate_measurement_provenance(
    provenance: RawProvenanceBinding,
    *,
    experiment_id: Literal["row-ocr", "row-profiles", "row-text", "row-vision"],
    measurements: tuple[RunMeasurements, ...],
) -> None:
    """Require raw provenance to equal every fact in its raw-bound measurements."""

    _require_runtime_contract(experiment_id, provenance.runtime_identity)
    if (
        not measurements
        or provenance.resource_inventory_identities
        != tuple(value.resource_inventory_identity for value in measurements)
        or any(
            value.experiment_id != experiment_id
            or value.config_id != provenance.config_id
            or value.split is not DatasetSplit.VALIDATION
            or value.runtime_identity != provenance.runtime_identity
            or value.arm_manifest_identity != provenance.arm_manifest_identity
            or value.model_inventory_identity != provenance.model_inventory_identity
            or value.dependency_inventory_identity != provenance.dependency_inventory_identity
            or value.row_sequence_identity != provenance.row_sequence_identity
            or value.worker_count != 1
            for value in measurements
        )
    ):
        _fail("measured provenance mismatch")


class ProfileRawHandoff(_FrozenModel):
    schema_version: Literal["row-profiles-handoff-v2"]
    provenance: RawProvenanceBinding
    disposition: LaneDisposition
    config: ProfileConfigRecord | None
    stop_reason: str | None
    validation_predictions: ArtifactIdentity
    validation_metrics: ArtifactIdentity
    validation_measurements: ArtifactIdentity
    determinism: ArtifactIdentity
    error_summary: ArtifactIdentity
    frozen_arm_manifest: ArtifactIdentity | None
    model_inventory: ArtifactIdentity
    dependency_inventory: ArtifactIdentity
    test_accessed: Literal[False]

    @model_validator(mode="after")
    def disposition_and_provenance_are_consistent(self) -> Self:
        eligible = self.disposition is LaneDisposition.FROZEN_ELIGIBLE
        if eligible and (
            self.config is None or self.stop_reason is not None or self.frozen_arm_manifest is None
        ):
            raise ValueError("eligible profile handoff is incomplete")
        if not eligible and (
            self.config is not None
            or self.stop_reason != "no_profile_candidate_met_validation_gate"
            or self.frozen_arm_manifest is not None
        ):
            raise ValueError("stopped profile handoff is inconsistent")
        if self.config is not None and (
            self.provenance.config_id != f"row-profiles-v1:{self.config.version}"
            or self.provenance.config_identity != profile_config_identity(self.config)
        ):
            raise ValueError("profile handoff config provenance mismatch")
        if (
            self.frozen_arm_manifest is not None
            and self.frozen_arm_manifest != self.provenance.arm_manifest_identity
        ):
            raise ValueError("profile handoff arm provenance mismatch")
        if (
            self.model_inventory != self.provenance.model_inventory_identity
            or self.dependency_inventory != self.provenance.dependency_inventory_identity
        ):
            raise ValueError("profile handoff inventory provenance mismatch")
        return self


class ProfileMeasurementPair(_FrozenModel):
    """The exact two raw-bound validation measurements for the selected profile."""

    version: Literal["profile-measurement-pair-v1"]
    config: Literal["tight", "default", "wide"]
    runs: tuple[RunMeasurements, RunMeasurements]
    test_accessed: Literal[False]


class OcrRawHandoff(_FrozenModel):
    schema_version: Literal["row-ocr-handoff-v2"]
    experiment_id: Literal["row-ocr"]
    disposition: LaneDisposition
    stop_reason: str | None
    config_identity: ArtifactIdentity | None
    frozen_arm_manifest: ArtifactIdentity | None
    validation_predictions: ArtifactIdentity
    validation_metric_identity: ArtifactIdentity
    validation_metric_report: MetricReport
    validation_measurement_identity: ArtifactIdentity
    validation_measurements: RunMeasurements
    provenance: RawProvenanceBinding
    error_summary: ArtifactIdentity
    determinism: ArtifactIdentity | None
    accepted_anchor_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    foundation_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    lane_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_identity: ArtifactIdentity
    worker_count: Literal[1]
    locked_test_status: Literal["not_opened"]

    @model_validator(mode="after")
    def provenance_matches_measurement(self) -> Self:
        measurement = self.validation_measurements
        provenance = self.provenance
        authenticate_measurement_provenance(
            provenance,
            experiment_id="row-ocr",
            measurements=(measurement,),
        )
        if (
            self.config_identity is None
            or provenance.foundation_sha != self.foundation_sha
            or provenance.config_identity != self.config_identity
            or provenance.runtime_identity != self.runtime_identity
        ):
            raise ValueError("OCR handoff provenance differs from measured validation evidence")
        return self


class TextFileDigest(_FrozenModel):
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TextRawHandoff(_FrozenModel):
    disposition: LaneDisposition
    files: Mapping[str, TextFileDigest]
    provenance: RawProvenanceBinding
    stop_reason: str | None
    test_accessed: Literal[False]
    version: Literal["row-text-handoff-v2"]


class VisionRawHandoff(_FrozenModel):
    schema_version: Literal["row-vision-handoff-v2"]
    provenance: RawProvenanceBinding
    accepted_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    experiment_id: Literal["row-vision"]
    disposition: LaneDisposition
    stop_reason: Literal["no_pixel_gain"] | None
    pixels_on_config_id: str = Field(min_length=1)
    pixels_off_config_id: str = Field(min_length=1)
    pixels_off_config_identity: ArtifactIdentity
    artifact_identities: tuple[ArtifactIdentity, ...] = Field(min_length=1)
    train_manifest_identity: ArtifactIdentity
    validation_manifest_identity: ArtifactIdentity
    validation_predictions_sha256_first: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_predictions_sha256_second: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_metric_identity: ArtifactIdentity
    validation_metric_report: MetricReport
    validation_measurements: RunMeasurements
    pixel_gate_evidence: ArtifactIdentity
    frozen_arm_manifest: None
    owner_none_means_current: Literal[True]
    test_accessed: Literal[False]

    @model_validator(mode="after")
    def stopped_disposition_and_provenance(self) -> Self:
        if (
            self.disposition is not LaneDisposition.VALIDATION_STOPPED
            or self.stop_reason != "no_pixel_gain"
            or self.frozen_arm_manifest is not None
        ):
            raise ValueError("validation-stopped vision handoff is inconsistent")
        authenticate_measurement_provenance(
            self.provenance,
            experiment_id="row-vision",
            measurements=(self.validation_measurements,),
        )
        if (
            self.accepted_sha == self.provenance.foundation_sha
            or self.pixels_on_config_id != self.provenance.config_id
            or self.pixels_off_config_identity.artifact_type != "row-vision-config"
            or self.pixels_off_config_identity.version != "row-vision-trained-v1"
            or self.pixels_off_config_identity == self.provenance.config_identity
        ):
            raise ValueError("vision handoff provenance mismatch")
        return self


def _read_raw[Model: _FrozenModel](value: LaneCliInput, model: type[Model]) -> Model:
    try:
        payload = verified_bytes(value.raw_handoff, "raw handoff is invalid")
        parsed = model.model_validate_json(payload)
    except (ControllerStateError, ValidationError, ValueError):
        _fail("raw handoff is invalid")
    if payload != canonical_model_bytes(parsed):
        _fail("raw handoff is invalid")
    return parsed


def _profile(value: LaneCliInput) -> AuthenticatedLaneEvidence:
    raw = _read_raw(value, ProfileRawHandoff)
    artifacts = value.artifacts
    if (
        raw.disposition is not LaneDisposition.FROZEN_ELIGIBLE
        or raw.config is None
        or raw.stop_reason is not None
        or raw.frozen_arm_manifest is None
        or artifacts.arm_manifest is None
        or artifacts.validation_measurement_envelope is None
        or artifacts.validation_error_summary is None
        or raw.validation_predictions != artifacts.validation_predictions.identity
        or raw.validation_metrics != artifacts.validation_metrics.identity
        or raw.validation_measurements != artifacts.validation_measurement_envelope.identity
        or raw.error_summary != artifacts.validation_error_summary.identity
        or raw.frozen_arm_manifest != artifacts.arm_manifest.identity
        or raw.model_inventory != artifacts.model_inventory.identity
        or raw.dependency_inventory != artifacts.dependency_inventory.identity
    ):
        _fail("raw handoff identity mismatch")
    pair = read_pinned_model(
        artifacts.validation_measurement_envelope,
        ProfileMeasurementPair,
        "profile measurement pair is invalid",
    )
    if pair.config != raw.config.version:
        _fail("raw handoff identity mismatch")
    authenticate_measurement_provenance(
        raw.provenance,
        experiment_id="row-profiles",
        measurements=pair.runs,
    )
    return authenticate_provenance(
        value,
        raw.provenance,
        disposition=raw.disposition,
        stop_reason=None,
        source_commit_sha=value.source_commit_sha,
        source_generation_replayed=True,
        provenance_limitation=None,
    )


def _ocr(value: LaneCliInput) -> AuthenticatedLaneEvidence:
    raw = _read_raw(value, OcrRawHandoff)
    artifacts = value.artifacts
    measurement = raw.validation_measurements
    members = artifacts.validation_measurements
    if (
        raw.disposition is not LaneDisposition.VALIDATION_STOPPED
        or raw.stop_reason != "ocr_stage_validation_failed"
        or raw.frozen_arm_manifest is not None
        or raw.determinism is not None
        or len(members) != 1
        or artifacts.validation_error_summary is None
        or raw.validation_predictions != artifacts.validation_predictions.identity
        or raw.validation_metric_identity != artifacts.validation_metrics.identity
        or raw.validation_measurement_identity != members[0].identity
        or raw.error_summary != artifacts.validation_error_summary.identity
        or raw.runtime_identity != artifacts.runtime_identity
        or measurement.runtime_identity != artifacts.runtime_identity
        or measurement.model_inventory_identity != artifacts.model_inventory.identity
        or measurement.dependency_inventory_identity != artifacts.dependency_inventory.identity
        or measurement.experiment_id != "row-ocr"
        or measurement.worker_count != 1
    ):
        _fail("raw handoff identity mismatch")
    return authenticate_provenance(
        value,
        raw.provenance,
        disposition=raw.disposition,
        stop_reason=raw.stop_reason,
        source_commit_sha=raw.lane_sha,
        source_generation_replayed=False,
        provenance_limitation="stopped_source_generation_not_replayable",
    )


def _text(value: LaneCliInput) -> AuthenticatedLaneEvidence:
    raw = _read_raw(value, TextRawHandoff)
    artifacts = value.artifacts
    members = artifacts.validation_measurements
    if (
        raw.disposition is not LaneDisposition.VALIDATION_STOPPED
        or raw.stop_reason != "no_text_candidate_met_validation_gate"
        or len(members) != 2
        or artifacts.arm_manifest is not None
    ):
        _fail("raw handoff identity mismatch")
    located: tuple[PinnedArtifact, ...] = (
        artifacts.model_inventory,
        artifacts.dependency_inventory,
        artifacts.validation_predictions,
        artifacts.validation_metrics,
        *members,
    )
    if artifacts.validation_error_summary is not None:
        located = (*located, artifacts.validation_error_summary)
    for artifact in located:
        digest = raw.files.get(artifact.path.name)
        if digest is None or (digest.sha256, digest.byte_size) != (
            artifact.identity.sha256,
            artifact.identity.byte_size,
        ):
            _fail("raw handoff identity mismatch")
    try:
        measurements = tuple(
            RunMeasurements.model_validate_json(verified_bytes(member, "raw handoff is invalid"))
            for member in members
        )
    except (ControllerStateError, ValidationError, ValueError):
        _fail("raw handoff is invalid")
    authenticate_measurement_provenance(
        raw.provenance,
        experiment_id="row-text",
        measurements=measurements,
    )
    return authenticate_provenance(
        value,
        raw.provenance,
        disposition=raw.disposition,
        stop_reason=raw.stop_reason,
        source_commit_sha=value.source_commit_sha,
        source_generation_replayed=False,
        provenance_limitation="stopped_source_generation_not_replayable",
    )


def _vision(value: LaneCliInput) -> AuthenticatedLaneEvidence:
    raw = _read_raw(value, VisionRawHandoff)
    artifacts = value.artifacts
    members = artifacts.validation_measurements
    measurement = raw.validation_measurements
    if (
        raw.disposition is not LaneDisposition.VALIDATION_STOPPED
        or raw.stop_reason != "no_pixel_gain"
        or raw.validation_predictions_sha256_first != raw.validation_predictions_sha256_second
        or raw.validation_predictions_sha256_first
        != artifacts.validation_predictions.identity.sha256
        or raw.validation_metric_identity != artifacts.validation_metrics.identity
        or len(members) != 1
        or measurement.experiment_id != "row-vision"
        or measurement
        != RunMeasurements.model_validate_json(verified_bytes(members[0], "raw handoff is invalid"))
        or measurement.runtime_identity != artifacts.runtime_identity
        or measurement.model_inventory_identity != artifacts.model_inventory.identity
        or measurement.dependency_inventory_identity != artifacts.dependency_inventory.identity
    ):
        _fail("raw handoff identity mismatch")
    return authenticate_provenance(
        value,
        raw.provenance,
        disposition=raw.disposition,
        stop_reason=raw.stop_reason,
        source_commit_sha=value.source_commit_sha,
        source_generation_replayed=False,
        provenance_limitation="stopped_source_generation_not_replayable",
    )


def authenticate_lane(value: LaneCliInput) -> AuthenticatedLaneEvidence:
    """Authenticate one exact raw schema without consulting any locked input."""

    if value.schema_kind == "profiles_v2":
        return _profile(value)
    if value.schema_kind == "ocr_stop_v2":
        return _ocr(value)
    if value.schema_kind == "text_stop_v2":
        return _text(value)
    if value.schema_kind == "vision_stop_v2":
        return _vision(value)
    _fail("raw handoff is invalid")


__all__ = [
    "AuthenticatedLaneEvidence",
    "OcrRawHandoff",
    "ProfileConfigRecord",
    "ProfileMeasurementPair",
    "ProfileRawHandoff",
    "RawHandoffError",
    "RawProvenanceBinding",
    "TextRawHandoff",
    "VisionRawHandoff",
    "authenticate_lane",
    "authenticate_measurement_provenance",
    "authenticate_provenance",
    "profile_config_identity",
]
