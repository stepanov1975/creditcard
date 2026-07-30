"""Independent validation-evidence replay and canonical normalization."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    GoldRow,
    OcrReference,
    RowPrediction,
)
from experiments.row_extraction.metrics import MetricReport, score_predictions
from experiments.row_extraction.runner import RunMeasurements
from experiments.row_extraction.split import SplitManifest

from .cli_adapters import ProfileMeasurementPair
from .cli_manifest import HandoffArtifacts, LockedComparisonCliManifestV1, PinnedArtifact
from .cli_normalize_contracts import fail_normalization
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    read_pinned_model,
    verified_bytes,
    write_bytes_exclusive,
)
from .errors import ErrorCategory, ErrorCategoryCount, ValidationErrorSummary, classify_error
from .handoff_contracts import (
    VALIDATION_ERROR_TYPE,
    VALIDATION_ERROR_VERSION,
    VALIDATION_MEASUREMENT_TYPE,
    VALIDATION_MEASUREMENT_VERSION,
    VALIDATION_METRIC_TYPE,
    VALIDATION_METRIC_VERSION,
    ArtifactFile,
)


def read_normalized_jsonl[Model: BaseModel](
    artifact: PinnedArtifact,
    model: type[Model],
    message: str,
) -> tuple[Model, ...]:
    payload = verified_bytes(artifact, message)
    records: list[Model] = []
    try:
        for line in payload.splitlines(keepends=True):
            value = model.model_validate_json(line)
            if line != _canonical_record_bytes(value):
                fail_normalization(message)
            records.append(value)
    except (ValidationError, ValueError):
        fail_normalization(message)
    if not records:
        fail_normalization(message)
    return tuple(records)


def write_normalized_model(
    path: Path,
    model: BaseModel,
    *,
    artifact_type: str,
    version: str,
) -> PinnedArtifact:
    payload = canonical_model_bytes(model)
    write_bytes_exclusive(path, payload)
    return PinnedArtifact(
        path=path,
        identity=identity_for_bytes(payload, artifact_type=artifact_type, version=version),
    )


def _error_summary(
    gold: Sequence[GoldRow],
    predictions: Sequence[RowPrediction],
) -> ValidationErrorSummary:
    assignments = tuple(
        classify_error(label, prediction)
        for label, prediction in zip(gold, predictions, strict=True)
    )
    return ValidationErrorSummary(
        version="row-comparison-error-summary-v1",
        row_count=len(assignments),
        primary_counts=tuple(
            ErrorCategoryCount(
                category=category,
                count=sum(value.primary is category for value in assignments),
            )
            for category in ErrorCategory
        ),
        secondary_counts=tuple(
            ErrorCategoryCount(
                category=category,
                count=sum(category in value.secondary for value in assignments),
            )
            for category in ErrorCategory
        ),
    )


def materialize_profile_measurements(
    artifacts: HandoffArtifacts,
    output_root: Path,
    config_id: str,
) -> tuple[PinnedArtifact, PinnedArtifact]:
    envelope_pin = artifacts.validation_measurement_envelope
    if envelope_pin is None:
        fail_normalization("profile measurement envelope is missing")
    envelope = read_pinned_model(
        envelope_pin,
        ProfileMeasurementPair,
        "profile measurement envelope is invalid",
    )
    if f"row-profiles-v1:{envelope.config}" != config_id:
        fail_normalization("profile measurement envelope binding mismatch")
    members = tuple(
        write_normalized_model(
            output_root / f"validation-measurement-{index}.json",
            measurement,
            artifact_type=VALIDATION_MEASUREMENT_TYPE,
            version=VALIDATION_MEASUREMENT_VERSION,
        )
        for index, measurement in enumerate(envelope.runs, start=1)
    )
    if any(value.identity == envelope_pin.identity for value in members):
        fail_normalization("profile measurement identity aliases its envelope")
    return cast(tuple[PinnedArtifact, PinnedArtifact], members)


def validate_foundation(
    cli: LockedComparisonCliManifestV1,
    rows: tuple[FrozenRow, ...],
    gold: tuple[GoldRow, ...],
) -> None:
    verified_bytes(cli.foundation_bundle, "foundation bundle is invalid")
    split = read_pinned_model(cli.split_manifest, SplitManifest, "split manifest is invalid")
    row_keys = tuple((value.document_id, value.row_id) for value in rows)
    gold_keys = tuple((value.document_id, value.row_id) for value in gold)
    if (
        cli.foundation_bundle.identity != cli.expected_bundle_identity
        or cli.split_manifest.identity != cli.expected_split_identity
        or cli.validation_gold.identity != cli.expected_label_identity
        or row_keys != gold_keys
        or len(row_keys) != len(set(row_keys))
        or any(value.split is not DatasetSplit.VALIDATION for value in rows)
        or any(split.split_for(value.document_id) is not DatasetSplit.VALIDATION for value in rows)
    ):
        fail_normalization("foundation validation binding mismatch")


def normalize_evidence(
    experiment_id: str,
    config_id: str,
    artifacts: HandoffArtifacts,
    *,
    rows: tuple[FrozenRow, ...],
    gold: tuple[GoldRow, ...],
    ocr_references: tuple[OcrReference, ...],
    output_root: Path,
    profile_measurements: tuple[PinnedArtifact, ...] | None = None,
) -> tuple[PinnedArtifact, tuple[PinnedArtifact, ...], PinnedArtifact]:
    predictions = read_normalized_jsonl(
        artifacts.validation_predictions,
        RowPrediction,
        "validation prediction is invalid",
    )
    if any(
        value.experiment_id != experiment_id or value.config_id != config_id
        for value in predictions
    ):
        fail_normalization("validation prediction binding mismatch")
    expected_keys = tuple((value.document_id, value.row_id) for value in rows)
    if tuple((value.document_id, value.row_id) for value in predictions) != expected_keys:
        fail_normalization("validation prediction row universe mismatch")
    frozen_metrics = read_pinned_model(
        artifacts.validation_metrics,
        MetricReport,
        "validation metric is invalid",
    )
    recomputed = score_predictions(rows, gold, predictions, ocr_references)
    if recomputed != frozen_metrics:
        fail_normalization("validation metric replay mismatch")
    metric_pin = write_normalized_model(
        output_root / "validation-metrics.json",
        recomputed,
        artifact_type=VALIDATION_METRIC_TYPE,
        version=VALIDATION_METRIC_VERSION,
    )
    measurement_inputs = (
        artifacts.validation_measurements if profile_measurements is None else profile_measurements
    )
    if not measurement_inputs:
        fail_normalization("validation measurements are missing")
    measurement_pins: list[PinnedArtifact] = []
    for index, raw_pin in enumerate(measurement_inputs, start=1):
        measurement = read_pinned_model(
            raw_pin,
            RunMeasurements,
            "validation measurement is invalid",
        )
        if (
            measurement.experiment_id != experiment_id
            or measurement.config_id != config_id
            or measurement.row_sequence_identity != cli_row_identity(rows)
            or measurement.split is not DatasetSplit.VALIDATION
            or measurement.row_count != len(rows)
            or measurement.runtime_identity != artifacts.runtime_identity
            or measurement.model_inventory_identity != artifacts.model_inventory.identity
            or measurement.dependency_inventory_identity != artifacts.dependency_inventory.identity
            or measurement.predictions_sha256 != artifacts.validation_predictions.identity.sha256
            or measurement.worker_count != 1
        ):
            fail_normalization("validation measurement binding mismatch")
        measurement_pins.append(
            write_normalized_model(
                output_root / f"normalized-measurement-{index}.json",
                measurement,
                artifact_type=VALIDATION_MEASUREMENT_TYPE,
                version=VALIDATION_MEASUREMENT_VERSION,
            )
        )
    summary = _error_summary(gold, predictions)
    error_pin = write_normalized_model(
        output_root / "validation-errors.json",
        summary,
        artifact_type=VALIDATION_ERROR_TYPE,
        version=VALIDATION_ERROR_VERSION,
    )
    return metric_pin, tuple(measurement_pins), error_pin


def cli_row_identity(rows: Sequence[FrozenRow]) -> ArtifactIdentity:
    payload = b"".join(_canonical_record_bytes(value) for value in rows)
    return identity_for_bytes(
        payload,
        artifact_type="frozen-row-sequence",
        version="canonical-jsonl-v1",
    )


def core_artifact(value: PinnedArtifact) -> ArtifactFile:
    return ArtifactFile(path=value.path, identity=value.identity)


__all__ = [
    "cli_row_identity",
    "core_artifact",
    "materialize_profile_measurements",
    "normalize_evidence",
    "read_normalized_jsonl",
]
