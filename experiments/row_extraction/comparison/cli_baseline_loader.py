"""Closed factory loaders for the three shared baseline controls."""

from __future__ import annotations

from pathlib import Path

from experiments.row_extraction.baselines import (
    AcceptedBaselineArmFactory,
    ConditionalPageOcrArmFactory,
    ForcedPageOcrArmFactory,
    PageEvidenceRecord,
)
from experiments.row_extraction.contracts import ArtifactIdentity, FrozenRow, RowPrediction
from experiments.row_extraction.runner import MeasuredArmFactory

from .cli_manifest import BaselineCliInput
from .cli_normalize_contracts import fail_normalization
from .cli_normalize_evidence import read_normalized_jsonl
from .handoff_contracts import FrozenArmFactoryLoader


def baseline_factory_loader(value: BaselineCliInput) -> FrozenArmFactoryLoader:
    """Build a cache-bound loader for one predeclared shared baseline."""

    arm_manifest = value.arm_manifest
    if arm_manifest is None:
        fail_normalization("baseline arm manifest is missing")

    def load(
        rows: tuple[FrozenRow, ...],
        row_sequence_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory:
        if value.loader_kind == "accepted-baseline":
            predictions = read_normalized_jsonl(
                arm_manifest,
                RowPrediction,
                "baseline arm manifest is invalid",
            )
            return AcceptedBaselineArmFactory(
                rows,
                predictions,
                arm_manifest.identity,
                row_sequence_identity=row_sequence_identity,
                runtime_identity=value.runtime_identity,
                model_inventory_identity=value.model_inventory.identity,
                dependency_inventory_identity=value.dependency_inventory.identity,
                cache_root=cache_root,
            )
        pages = read_normalized_jsonl(
            arm_manifest,
            PageEvidenceRecord,
            "baseline arm manifest is invalid",
        )
        factory = (
            ConditionalPageOcrArmFactory
            if value.loader_kind == "conditional-page-ocr"
            else ForcedPageOcrArmFactory
        )
        return factory(
            rows,
            pages,
            arm_manifest.identity,
            row_sequence_identity=row_sequence_identity,
            runtime_identity=value.runtime_identity,
            model_inventory_identity=value.model_inventory.identity,
            dependency_inventory_identity=value.dependency_inventory.identity,
            cache_root=cache_root,
        )

    return load


__all__ = ["baseline_factory_loader"]
