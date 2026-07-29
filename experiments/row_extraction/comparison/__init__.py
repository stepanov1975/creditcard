"""Closed comparison interfaces for the four row-extraction experiments."""

from experiments.row_extraction.comparison.errors import (
    ErrorAssignment,
    ErrorCategory,
    ErrorClassificationError,
    classify_error,
)
from experiments.row_extraction.comparison.handoffs import (
    BASELINE_IDS,
    EXPERIMENT_IDS,
    ArtifactFile,
    BaselineHandoff,
    ComparisonManifest,
    FrozenArmFactoryLoader,
    FrozenArmInput,
    FrozenRunInputs,
    HandoffError,
    LaneHandoff,
    RowIdentity,
    ValidatedHandoffs,
    validate_handoffs,
)
from experiments.row_extraction.comparison.statistics import (
    PairedInterval,
    StatisticsError,
    paired_document_bootstrap,
)

__all__ = [
    "BASELINE_IDS",
    "EXPERIMENT_IDS",
    "ArtifactFile",
    "BaselineHandoff",
    "ComparisonManifest",
    "ErrorAssignment",
    "ErrorCategory",
    "ErrorClassificationError",
    "FrozenArmFactoryLoader",
    "FrozenArmInput",
    "FrozenRunInputs",
    "HandoffError",
    "LaneHandoff",
    "PairedInterval",
    "RowIdentity",
    "StatisticsError",
    "ValidatedHandoffs",
    "classify_error",
    "paired_document_bootstrap",
    "validate_handoffs",
]
