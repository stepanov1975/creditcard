"""Exclusive locked-input boundary for the central comparison controller."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never

from pydantic import BaseModel, ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    GoldRow,
    OcrReference,
    RowPrediction,
    _FrozenModel,
)
from experiments.row_extraction.split import SplitManifest

from .cli_manifest import LockedComparisonCliManifestV1, PinnedArtifact
from .cli_state import (
    canonical_model_bytes,
    create_stage,
    identity_for_bytes,
    read_pinned_model,
    verified_bytes,
    write_bytes_exclusive,
)
from .handoff_contracts import RowIdentity


class LockedAccessError(ValueError):
    """Deferred inputs cannot satisfy the one-way locked access contract."""


def _fail(message: str) -> Never:
    raise LockedAccessError(message)


class LockedStartReceiptV1(_FrozenModel):
    version: Literal["row-comparison-locked-start-v1"]
    comparison_manifest_identity: ArtifactIdentity
    validation_receipt_identity: ArtifactIdentity
    policy_identity: ArtifactIdentity
    locked_row_ids_identity: ArtifactIdentity
    test_access_started: Literal[True]


@dataclass(frozen=True)
class LockedInputs:
    rows: tuple[FrozenRow, ...]
    gold: tuple[GoldRow, ...]
    accepted_predictions: tuple[RowPrediction, ...]
    ocr_references: tuple[OcrReference, ...]
    row_sequence_identity: ArtifactIdentity


def _read_jsonl[Model: BaseModel](
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
                _fail(message)
            records.append(value)
    except (ValidationError, ValueError):
        _fail(message)
    if not records:
        _fail(message)
    return tuple(records)


def _row_key(
    value: FrozenRow | GoldRow | OcrReference | RowPrediction | RowIdentity,
) -> tuple[str, str]:
    return value.document_id, value.row_id


def _start_locked_stage(
    cli: LockedComparisonCliManifestV1,
    *,
    comparison_manifest_identity: ArtifactIdentity,
    validation_receipt_identity: ArtifactIdentity,
    policy_identity: ArtifactIdentity,
) -> Path:
    locked_root = create_stage(cli.workspace_root, "locked")
    receipt = LockedStartReceiptV1(
        version="row-comparison-locked-start-v1",
        comparison_manifest_identity=comparison_manifest_identity,
        validation_receipt_identity=validation_receipt_identity,
        policy_identity=policy_identity,
        locked_row_ids_identity=cli.locked_row_ids.identity,
        test_access_started=True,
    )
    write_bytes_exclusive(locked_root / "start-receipt.json", canonical_model_bytes(receipt))
    return locked_root


def read_locked_inputs_after_start(cli: LockedComparisonCliManifestV1) -> LockedInputs:
    """Authenticate deferred inputs only after the irreversible locked marker exists."""

    if not (cli.workspace_root / "locked" / "start-receipt.json").is_file():
        _fail("locked access marker is missing")
    rows = _read_jsonl(cli.locked_inputs.rows, FrozenRow, "locked rows are invalid")
    gold = _read_jsonl(cli.locked_inputs.gold, GoldRow, "locked gold is invalid")
    accepted = _read_jsonl(
        cli.locked_inputs.accepted_predictions,
        RowPrediction,
        "accepted locked predictions are invalid",
    )
    accepted_identity = read_pinned_model(
        cli.locked_inputs.accepted_predictions_identity_file,
        ArtifactIdentity,
        "accepted locked prediction identity is invalid",
    )
    locked_ids = _read_jsonl(cli.locked_row_ids, RowIdentity, "locked row IDs are invalid")
    validation_rows = _read_jsonl(
        cli.validation_rows,
        FrozenRow,
        "validation rows changed before locked access",
    )
    split_manifest = read_pinned_model(
        cli.split_manifest,
        SplitManifest,
        "split manifest changed before locked access",
    )
    references = (
        ()
        if cli.locked_inputs.optional_ocr_references is None
        else _read_jsonl(
            cli.locked_inputs.optional_ocr_references,
            OcrReference,
            "locked OCR references are invalid",
        )
    )
    row_keys = tuple(_row_key(value) for value in rows)
    gold_keys = tuple(_row_key(value) for value in gold)
    prediction_keys = tuple(_row_key(value) for value in accepted)
    id_keys = tuple(_row_key(value) for value in locked_ids)
    baseline = cli.baselines["accepted-baseline"]
    try:
        test_membership = all(
            split_manifest.split_for(value.document_id) is DatasetSplit.TEST for value in rows
        )
    except ValueError:
        _fail("locked split membership mismatch")
    if (
        any(value.split is not DatasetSplit.TEST for value in rows)
        or not test_membership
        or not {value.document_id for value in validation_rows}.isdisjoint(
            value.document_id for value in rows
        )
        or not row_keys
        or len(row_keys) != len(set(row_keys))
        or id_keys != row_keys
        or len(gold_keys) != len(set(gold_keys))
        or set(gold_keys) != set(row_keys)
        or prediction_keys != row_keys
        or any(
            value.experiment_id != "accepted-baseline" or value.config_id != baseline.config_id
            for value in accepted
        )
        or accepted_identity != cli.locked_inputs.accepted_predictions.identity
        or any(_row_key(value) not in set(row_keys) for value in references)
    ):
        _fail("locked input binding mismatch")
    payload = b"".join(_canonical_record_bytes(value) for value in rows)
    return LockedInputs(
        rows=rows,
        gold=gold,
        accepted_predictions=accepted,
        ocr_references=references,
        row_sequence_identity=identity_for_bytes(
            payload,
            artifact_type="frozen-row-sequence",
            version="canonical-jsonl-v1",
        ),
    )


def start_and_read_locked_inputs(
    cli: LockedComparisonCliManifestV1,
    *,
    comparison_manifest_identity: ArtifactIdentity,
    validation_receipt_identity: ArtifactIdentity,
    policy_identity: ArtifactIdentity,
) -> tuple[Path, LockedInputs]:
    """Irreversibly mark locked access, then authenticate all deferred inputs."""

    locked_root = _start_locked_stage(
        cli,
        comparison_manifest_identity=comparison_manifest_identity,
        validation_receipt_identity=validation_receipt_identity,
        policy_identity=policy_identity,
    )
    return locked_root, read_locked_inputs_after_start(cli)


__all__ = [
    "LockedAccessError",
    "LockedInputs",
    "LockedStartReceiptV1",
    "read_locked_inputs_after_start",
    "start_and_read_locked_inputs",
]
