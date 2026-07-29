"""Single typed catalog for the fixed comparison result set."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, cast

from experiments.row_extraction.annotations import (
    _PRIMARY_REQUIRED_ROLES as PRIMARY_REQUIRED_FIELD_ROLES,
)

type BaselineId = Literal[
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
]
type LaneId = Literal["row-ocr", "row-profiles", "row-text", "row-vision"]
type ResultId = BaselineId | LaneId
type ResultKind = Literal["baseline", "lane"]
type ManifestPolicy = Literal[
    "fixed",
    "locked-materialized-input",
    "locked-page-preparation",
]


class StopReason(StrEnum):
    """Closed validation-stop reason for each experiment lane."""

    OCR_STAGE_VALIDATION_FAILED = "ocr_stage_validation_failed"
    NO_PROFILE_CANDIDATE_MET_VALIDATION_GATE = "no_profile_candidate_met_validation_gate"
    NO_TEXT_CANDIDATE_MET_VALIDATION_GATE = "no_text_candidate_met_validation_gate"
    NO_PIXEL_GAIN = "no_pixel_gain"


@dataclass(frozen=True)
class ResultDefinition:
    """One ordered comparison member and its predeclared lane stop reason."""

    result_id: ResultId
    kind: ResultKind
    manifest_policy: ManifestPolicy = "fixed"
    stop_reason: StopReason | None = None


RESULT_CATALOG = (
    ResultDefinition("accepted-baseline", "baseline", "locked-materialized-input"),
    ResultDefinition(
        "conditional-page-ocr",
        "baseline",
        "locked-page-preparation",
    ),
    ResultDefinition(
        "forced-page-ocr",
        "baseline",
        "locked-page-preparation",
    ),
    ResultDefinition("row-ocr", "lane", "fixed", StopReason.OCR_STAGE_VALIDATION_FAILED),
    ResultDefinition(
        "row-profiles",
        "lane",
        "fixed",
        StopReason.NO_PROFILE_CANDIDATE_MET_VALIDATION_GATE,
    ),
    ResultDefinition(
        "row-text",
        "lane",
        "fixed",
        StopReason.NO_TEXT_CANDIDATE_MET_VALIDATION_GATE,
    ),
    ResultDefinition("row-vision", "lane", "fixed", StopReason.NO_PIXEL_GAIN),
)

RESULT_IDS = cast(tuple[ResultId, ...], tuple(item.result_id for item in RESULT_CATALOG))
BASELINE_IDS = cast(
    tuple[BaselineId, ...],
    tuple(item.result_id for item in RESULT_CATALOG if item.kind == "baseline"),
)
LANE_IDS = cast(
    tuple[LaneId, ...],
    tuple(item.result_id for item in RESULT_CATALOG if item.kind == "lane"),
)
BASELINE_ID_SET = frozenset(BASELINE_IDS)
LANE_ID_SET = frozenset(LANE_IDS)
STOP_REASON_BY_LANE = MappingProxyType(
    {
        item.result_id: item.stop_reason
        for item in RESULT_CATALOG
        if item.kind == "lane" and item.stop_reason is not None
    }
)
MANIFEST_POLICY_BY_RESULT = MappingProxyType(
    {item.result_id: item.manifest_policy for item in RESULT_CATALOG}
)

__all__ = [
    "BASELINE_IDS",
    "BASELINE_ID_SET",
    "LANE_IDS",
    "LANE_ID_SET",
    "MANIFEST_POLICY_BY_RESULT",
    "PRIMARY_REQUIRED_FIELD_ROLES",
    "RESULT_CATALOG",
    "RESULT_IDS",
    "STOP_REASON_BY_LANE",
    "BaselineId",
    "LaneId",
    "ManifestPolicy",
    "ResultDefinition",
    "ResultId",
    "StopReason",
]
