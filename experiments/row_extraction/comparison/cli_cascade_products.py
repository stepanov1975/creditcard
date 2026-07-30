"""Identity-bound reader for the completed derived-cascade stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel

from .cli_cascade import CascadeCompletionReceiptV1, DerivedCascadeEvaluationV1
from .cli_locked_products import read_locked_products
from .cli_locked_records import LockedProducts
from .cli_manifest import PinnedArtifact
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    stable_regular_bytes,
    verified_bytes,
)


class CascadeProductsError(ValueError):
    """The derived cascade stage no longer matches the locked comparison."""


def _fail(message: str) -> Never:
    raise CascadeProductsError(message)


@dataclass(frozen=True)
class CascadeProducts:
    locked: LockedProducts
    evaluation: DerivedCascadeEvaluationV1
    evaluation_identity: ArtifactIdentity
    receipt: CascadeCompletionReceiptV1
    receipt_identity: ArtifactIdentity


def _read[Model: _FrozenModel](path: Path, model: type[Model], message: str) -> Model:
    try:
        payload = stable_regular_bytes(path, message)
        value = model.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        _fail(message)
    if payload != canonical_model_bytes(value):
        _fail(message)
    return value


def _identity(path: Path, message: str) -> ArtifactIdentity:
    return _read(path, ArtifactIdentity, message)


def _matches(value: _FrozenModel, identity: ArtifactIdentity) -> bool:
    return (
        identity_for_bytes(
            canonical_model_bytes(value),
            artifact_type=identity.artifact_type,
            version=identity.version,
        )
        == identity
    )


def read_cascade_products(manifest_path: Path) -> CascadeProducts:
    """Reverify every cascade output and its locked-comparison binding."""

    locked = read_locked_products(manifest_path)
    root = locked.cli.workspace_root / "locked" / "cascade"
    evaluation = _read(
        root / "evaluation.json",
        DerivedCascadeEvaluationV1,
        "derived cascade evaluation is invalid",
    )
    evaluation_identity = _identity(
        root / "evaluation.json.identity",
        "derived cascade evaluation identity is invalid",
    )
    receipt = _read(
        root / "completion-receipt.json",
        CascadeCompletionReceiptV1,
        "cascade completion receipt is invalid",
    )
    receipt_identity = _identity(
        root / "completion-receipt.json.identity",
        "cascade completion identity is invalid",
    )
    if (
        not _matches(evaluation, evaluation_identity)
        or not _matches(receipt, receipt_identity)
        or receipt.locked_completion_identity != locked.receipt_identity
        or receipt.evaluation_identity != evaluation_identity
        or receipt.cascade_policy_identity != locked.receipt.cascade_policy_identity
        or evaluation.cascade_policy_identity != receipt.cascade_policy_identity
        or evaluation.row_sequence_identity != locked.locked_inputs.row_sequence_identity
        or receipt.row_sequence_identity != evaluation.row_sequence_identity
        or evaluation.derived_predictions[0].identity != evaluation.derived_predictions[1].identity
    ):
        _fail("derived cascade completion binding mismatch")
    pins = (
        *evaluation.derived_predictions,
        evaluation.error_assignments,
        PinnedArtifact(path=root / "metrics.json", identity=evaluation.metric_identity),
    )
    for pin in pins:
        verified_bytes(pin, "derived cascade artifact changed")
    return CascadeProducts(
        locked=locked,
        evaluation=evaluation,
        evaluation_identity=evaluation_identity,
        receipt=receipt,
        receipt_identity=receipt_identity,
    )


__all__ = ["CascadeProducts", "CascadeProductsError", "read_cascade_products"]
