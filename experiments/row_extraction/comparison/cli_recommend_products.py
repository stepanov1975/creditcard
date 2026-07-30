"""Identity-bound reader for the completed recommendation stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel

from .cli_cascade_products import CascadeProducts, read_cascade_products
from .cli_recommend import RecommendationCompletionReceiptV1, RecommendationEnvelopeV1
from .cli_state import canonical_model_bytes, identity_for_bytes, stable_regular_bytes


class RecommendationProductsError(ValueError):
    """The recommendation no longer matches its completed evidence chain."""


def _fail(message: str) -> Never:
    raise RecommendationProductsError(message)


@dataclass(frozen=True)
class RecommendationProducts:
    cascade: CascadeProducts
    recommendation: RecommendationEnvelopeV1
    recommendation_identity: ArtifactIdentity
    receipt: RecommendationCompletionReceiptV1
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


def read_recommendation_products(manifest_path: Path) -> RecommendationProducts:
    """Reverify the final recommendation and every upstream completion binding."""

    cascade = read_cascade_products(manifest_path)
    root = cascade.locked.cli.workspace_root / "locked" / "recommendation"
    recommendation = _read(
        root / "recommendation.json",
        RecommendationEnvelopeV1,
        "recommendation artifact is invalid",
    )
    recommendation_identity = _identity(
        root / "recommendation.json.identity",
        "recommendation identity is invalid",
    )
    receipt = _read(
        root / "completion-receipt.json",
        RecommendationCompletionReceiptV1,
        "recommendation completion receipt is invalid",
    )
    receipt_identity = _identity(
        root / "completion-receipt.json.identity",
        "recommendation completion identity is invalid",
    )
    decision = recommendation.recommendation
    if (
        not _matches(recommendation, recommendation_identity)
        or not _matches(receipt, receipt_identity)
        or receipt.cascade_completion_identity != cascade.receipt_identity
        or receipt.comparison_identity != cascade.locked.report_identity
        or receipt.recommendation_identity != recommendation_identity
        or receipt.kind != decision.kind
        or receipt.selected_ids != decision.selected_ids
        or receipt.reason_codes != decision.reasons
        or receipt.candidate_ids != recommendation.candidate_ids
    ):
        _fail("recommendation completion binding mismatch")
    return RecommendationProducts(
        cascade=cascade,
        recommendation=recommendation,
        recommendation_identity=recommendation_identity,
        receipt=receipt,
        receipt_identity=receipt_identity,
    )


__all__ = [
    "RecommendationProducts",
    "RecommendationProductsError",
    "read_recommendation_products",
]
