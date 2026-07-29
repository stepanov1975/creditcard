from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

type BBox = tuple[float, float, float, float]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class LaneDisposition(StrEnum):
    FROZEN_ELIGIBLE = "frozen_eligible"
    VALIDATION_STOPPED = "validation_stopped"


class RowType(StrEnum):
    PRIMARY_TRANSACTION = "primary_transaction"
    CONTINUATION = "continuation"
    STRUCTURAL = "structural"
    AMBIGUOUS = "ambiguous"


class FieldRole(StrEnum):
    TRANSACTION_DATE = "transaction_date"
    POSTING_DATE = "posting_date"
    CONVERSION_DATE = "conversion_date"
    DESCRIPTION = "description"
    BILLED_AMOUNT = "billed_amount"
    BILLING_CURRENCY = "billing_currency"
    ORIGINAL_AMOUNT = "original_amount"
    ORIGINAL_CURRENCY = "original_currency"
    KIND = "kind"
    INSTALLMENT = "installment"
    FX_RATE = "fx_rate"
    ANCILLARY = "ancillary"


PRIMARY_REQUIRED_FIELD_ROLES = frozenset(
    {FieldRole.BILLED_AMOUNT, FieldRole.BILLING_CURRENCY, FieldRole.KIND}
)


class Decision(StrEnum):
    ACCEPT = "accept"
    ABSTAIN = "abstain"
    REJECT = "reject"
    IGNORE = "ignore"


class EvidenceAtom(_FrozenModel):
    atom_id: str = Field(min_length=1)
    text: str
    bbox: BBox
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0.0, le=1.0)
    column_index: int | None = Field(default=None, ge=0)


class ColumnBand(_FrozenModel):
    index: int = Field(ge=0)
    role: FieldRole | None = None
    bbox: BBox


class FrozenRow(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    split: DatasetSplit
    source_pdf: Path
    page_number: int = Field(gt=0)
    bbox: BBox
    baseline_type: RowType
    column_bands: tuple[ColumnBand, ...]
    atoms: tuple[EvidenceAtom, ...]
    render_version: str = Field(min_length=1)
    previous_row_id: str | None = None
    next_row_id: str | None = None
    gap_before: float | None = Field(default=None, ge=0.0)
    gap_after: float | None = Field(default=None, ge=0.0)


class GoldField(_FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    role: FieldRole
    canonical_value: str
    atom_ids: tuple[str, ...] = ()
    source_region: BBox | None = None

    @model_validator(mode="after")
    def has_evidence_support(self) -> GoldField:
        if not self.atom_ids and self.source_region is None:
            raise ValueError("gold field requires atom IDs or source region")
        return self


class GoldRow(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    row_type: RowType
    fields: tuple[GoldField, ...]
    ambiguous: bool = False


class OcrReference(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    role: FieldRole
    verbatim_text: str = Field(min_length=1)
    source_region: BBox


class FieldProposal(_FrozenModel):
    role: FieldRole
    atom_ids: tuple[str, ...] = Field(min_length=1)
    source_region: BBox | None = None
    owner_row_id: str | None = None
    raw_score: float = Field(ge=0.0, le=1.0)


class RowPrediction(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    predicted_type: RowType
    evidence_atoms: tuple[EvidenceAtom, ...]
    proposals: tuple[FieldProposal, ...]
    exact_row_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: Decision
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def unique_evidence_ids(self) -> RowPrediction:
        ids = tuple(atom.atom_id for atom in self.evidence_atoms)
        if len(ids) != len(set(ids)):
            raise ValueError("prediction evidence atom IDs must be unique")
        return self

    @model_validator(mode="after")
    def proposals_reference_evidence(self) -> RowPrediction:
        evidence_ids = {atom.atom_id for atom in self.evidence_atoms}
        if any(
            atom_id not in evidence_ids
            for proposal in self.proposals
            for atom_id in proposal.atom_ids
        ):
            raise ValueError("proposal atom IDs must reference prediction evidence")
        return self


class ArtifactIdentity(_FrozenModel):
    artifact_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = Field(min_length=1)
    byte_size: int = Field(ge=0)


class FeatureSchema(_FrozenModel):
    version: str = Field(min_length=1)
    names: tuple[str, ...]


class FeatureVector(_FrozenModel):
    schema_version: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    values: tuple[float, ...]


class ExperimentArm(Protocol):
    @property
    def experiment_id(self) -> str: ...

    @property
    def config_id(self) -> str: ...

    def predict(self, row: FrozenRow) -> RowPrediction: ...
