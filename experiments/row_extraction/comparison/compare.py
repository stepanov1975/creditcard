"""Closed aggregate comparison for the four row-extraction lanes and controls."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from experiments.row_extraction.contracts import LaneDisposition, _FrozenModel

_RESULT_IDS = (
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
    "row-ocr",
    "row-profiles",
    "row-text",
    "row-vision",
)
_BASELINE_IDS = frozenset(_RESULT_IDS[:3])
_METRIC_FAMILIES = (
    "row_exact",
    "merchant",
    "typed_fields",
    "omission_hallucination",
    "ocr_error",
    "calibration_abstention",
    "resources_determinism",
    "row_type_errors",
)


class ResultBasis(StrEnum):
    """Whether a result is a locked measurement or a preserved validation stop."""

    LOCKED_TEST = "locked_test"
    VALIDATION_STOP = "validation_stop"


class ExperimentResult(_FrozenModel):
    """Privacy-safe aggregate projection of one baseline or experiment outcome."""

    experiment_id: str = Field(min_length=1)
    result_basis: ResultBasis
    disposition: LaneDisposition | None
    stop_reason: str | None
    row_count: int = Field(gt=0)
    exact_rows: int = Field(ge=0)
    merchant_exact_rows: int = Field(ge=0)
    omissions: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    p95_ns: int | None = Field(default=None, gt=0)
    peak_rss_bytes: int | None = Field(default=None, gt=0)
    model_bytes: int | None = Field(default=None, ge=0)
    dependency_bytes: int | None = Field(default=None, gt=0)
    deterministic: bool
    resource_basis: Literal["end-to-end-method", "materialized-adapter"] | None

    @model_validator(mode="after")
    def coherent_basis(self) -> Self:
        stopped = self.disposition is LaneDisposition.VALIDATION_STOPPED
        resources = (
            self.p95_ns,
            self.peak_rss_bytes,
            self.model_bytes,
            self.dependency_bytes,
            self.resource_basis,
        )
        if stopped and (
            self.result_basis is not ResultBasis.VALIDATION_STOP
            or not self.stop_reason
            or any(value is not None for value in resources)
        ):
            raise ValueError("stopped result must remain validation-only")
        if not stopped and self.result_basis is ResultBasis.VALIDATION_STOP:
            raise ValueError("validation-stop result requires stopped disposition")
        if self.result_basis is ResultBasis.LOCKED_TEST and any(
            value is None for value in resources
        ):
            raise ValueError("locked result requires complete resource aggregates")
        if self.disposition is LaneDisposition.FROZEN_ELIGIBLE and self.stop_reason is not None:
            raise ValueError("eligible result cannot carry a stop reason")
        if self.exact_rows > self.row_count or self.accepted_rows > self.row_count:
            raise ValueError("result counts exceed row count")
        return self


class ComparisonReport(_FrozenModel):
    """Complete, ordered result set without a hidden weighted score."""

    experiment_ids: tuple[str, ...]
    required_metric_families: tuple[str, ...]
    locked_experiment_ids: tuple[str, ...]
    validation_stopped_ids: tuple[str, ...]
    resource_pareto_ids: tuple[str, ...]
    results: tuple[ExperimentResult, ...]


def _dominates(first: ExperimentResult, second: ExperimentResult) -> bool:
    first_axes = (
        first.exact_rows,
        first.merchant_exact_rows,
        -first.omissions,
        -first.hallucinations,
        -(first.p95_ns or 0),
        -(first.peak_rss_bytes or 0),
        -(first.model_bytes or 0),
    )
    second_axes = (
        second.exact_rows,
        second.merchant_exact_rows,
        -second.omissions,
        -second.hallucinations,
        -(second.p95_ns or 0),
        -(second.peak_rss_bytes or 0),
        -(second.model_bytes or 0),
    )
    return all(left >= right for left, right in zip(first_axes, second_axes, strict=True)) and any(
        left > right for left, right in zip(first_axes, second_axes, strict=True)
    )


def build_comparison(results: tuple[ExperimentResult, ...]) -> ComparisonReport:
    """Validate completeness and expose locked, stopped, and Pareto membership."""

    by_id = {result.experiment_id: result for result in results}
    if len(results) != len(_RESULT_IDS) or set(by_id) != set(_RESULT_IDS):
        raise ValueError("comparison requires exactly seven result IDs")
    ordered = tuple(by_id[experiment_id] for experiment_id in _RESULT_IDS)
    for result in ordered:
        if result.experiment_id in _BASELINE_IDS:
            if result.disposition is not None or result.result_basis is not ResultBasis.LOCKED_TEST:
                raise ValueError("baseline must be a locked control result")
        elif result.disposition is None:
            raise ValueError("experiment result requires a lane disposition")
    locked = tuple(
        result.experiment_id for result in ordered if result.result_basis is ResultBasis.LOCKED_TEST
    )
    stopped = tuple(
        result.experiment_id
        for result in ordered
        if result.result_basis is ResultBasis.VALIDATION_STOP
    )
    resource_candidates = tuple(
        result
        for result in ordered
        if result.result_basis is ResultBasis.LOCKED_TEST
        and result.resource_basis == "end-to-end-method"
        and result.deterministic
    )
    pareto = tuple(
        candidate.experiment_id
        for candidate in resource_candidates
        if not any(
            other.experiment_id != candidate.experiment_id and _dominates(other, candidate)
            for other in resource_candidates
        )
    )
    return ComparisonReport(
        experiment_ids=_RESULT_IDS,
        required_metric_families=_METRIC_FAMILIES,
        locked_experiment_ids=locked,
        validation_stopped_ids=stopped,
        resource_pareto_ids=pareto,
        results=ordered,
    )


__all__ = [
    "ComparisonReport",
    "ExperimentResult",
    "ResultBasis",
    "build_comparison",
]
