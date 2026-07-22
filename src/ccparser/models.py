"""Immutable public domain models for statement parsing."""

from __future__ import annotations

import unicodedata
from datetime import date
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic.functional_validators import AfterValidator

from ccparser.date_tokens import (
    MAX_CONTEXT_YEAR,
    MIN_CONTEXT_YEAR,
    SuffixYearMappingValidationError,
    SuffixYearMappingViolation,
    validate_suffix_year_mapping,
)
from ccparser.decimal_math import exact_difference, finite_decimal, plain_decimal_string
from ccparser.paths import safe_relative_posix_path


def _finite_coordinate(value: float) -> float:
    if not isfinite(value):
        raise ValueError("coordinates must be finite")
    return value


type FiniteDecimal = Annotated[Decimal, AfterValidator(finite_decimal)]
type FiniteCoordinate = Annotated[float, AfterValidator(_finite_coordinate)]
type FiniteBBox = tuple[FiniteCoordinate, FiniteCoordinate, FiniteCoordinate, FiniteCoordinate]
type FinitePoint = tuple[FiniteCoordinate, FiniteCoordinate]


class TransactionKind(StrEnum):
    """The direction of a billed transaction."""

    CHARGE = "charge"
    CREDIT = "credit"


class TransactionCategory(StrEnum):
    """Issuer-neutral semantic category without changing amount direction."""

    UNKNOWN = "unknown"
    PURCHASE = "purchase"
    REFUND = "refund"
    FEE = "fee"
    INTEREST = "interest"
    ADJUSTMENT = "adjustment"
    INSTALLMENT = "installment"


class Status(StrEnum):
    """Public processing status shared by statement and batch results."""

    RECONCILED = "reconciled"
    UNRECONCILED = "unreconciled"
    UNSUPPORTED = "unsupported"
    NOT_STATEMENT = "not_statement"


class EvidenceReference(BaseModel):
    """Source text and geometry supporting an extracted value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int
    bbox: FiniteBBox
    raw_text: str


class ExtractedDecimal(BaseModel):
    """One finite decimal value with the exact evidence that proves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: FiniteDecimal
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)

    @field_serializer("value")
    def serialize_value(self, value: Decimal) -> str:
        return plain_decimal_string(value)


class ExtractedMoney(BaseModel):
    """One printed or exactly derived monetary value with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: FiniteDecimal
    currency: str
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    derivation: Literal["printed", "gross_fee_minus_discount"] = "printed"

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return plain_decimal_string(value)


class ForeignExchangeDetails(BaseModel):
    """Structured rate and fee details for a foreign-currency transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_rate: ExtractedDecimal | None = None
    fee_percentage: ExtractedDecimal | None = None
    gross_fee: ExtractedMoney | None = None
    fee_discount: ExtractedMoney | None = None
    net_fee: ExtractedMoney | None = None

    @model_validator(mode="after")
    def validate_details(self) -> Self:
        if all(
            value is None
            for value in (
                self.exchange_rate,
                self.fee_percentage,
                self.gross_fee,
                self.fee_discount,
                self.net_fee,
            )
        ):
            raise ValueError("at least one FX value is required")
        if self.exchange_rate is not None and self.exchange_rate.value <= 0:
            raise ValueError("exchange rate must be positive")
        if self.fee_percentage is not None and self.fee_percentage.value < 0:
            raise ValueError("fee percentage cannot be negative")
        if self.gross_fee is not None and self.gross_fee.derivation != "printed":
            raise ValueError("gross fee must be printed")
        if self.fee_discount is not None and self.fee_discount.derivation != "printed":
            raise ValueError("fee discount must be printed")
        if self.net_fee is not None and self.net_fee.derivation == "gross_fee_minus_discount":
            if self.gross_fee is None or self.fee_discount is None:
                raise ValueError("derived net fee requires gross fee and discount")
            if (
                len(
                    {
                        self.gross_fee.currency,
                        self.fee_discount.currency,
                        self.net_fee.currency,
                    }
                )
                != 1
            ):
                raise ValueError("derived fee currencies must match")
            expected = exact_difference(self.gross_fee.amount, self.fee_discount.amount)
            expected_evidence = tuple(
                dict.fromkeys((*self.gross_fee.evidence, *self.fee_discount.evidence))
            )
            if (
                expected < 0
                or self.net_fee.amount != expected
                or self.net_fee.evidence != expected_evidence
            ):
                raise ValueError("net fee must equal exact gross fee minus discount")
        return self


class Transaction(BaseModel):
    """A transaction contributing to one or more candidate statement groups."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str
    kind: TransactionKind
    billed_amount: FiniteDecimal
    billing_currency: str
    reconciliation_group_ids: tuple[str, ...]
    ambiguities: tuple[str, ...] = ()
    transaction_date: date | None = None
    posting_date: date | None = None
    conversion_date: date | None = None
    description: str | None = None
    category: TransactionCategory = TransactionCategory.UNKNOWN
    original_amount: FiniteDecimal | None = None
    original_currency: str | None = None
    installment_current: int | None = Field(default=None, gt=0)
    installment_total: int | None = Field(default=None, gt=0)
    foreign_exchange: ForeignExchangeDetails | None = None
    evidence: tuple[EvidenceReference, ...] = ()

    @field_serializer("billed_amount", "original_amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return plain_decimal_string(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return unicodedata.normalize("NFC", value) if value is not None else None

    @model_validator(mode="after")
    def validate_amount_sign(self) -> Self:
        if self.kind is TransactionKind.CHARGE and self.billed_amount <= 0:
            raise ValueError("charge amount must be positive")
        if self.kind is TransactionKind.CREDIT and self.billed_amount >= 0:
            raise ValueError("credit amount must be negative")
        installment_values = (self.installment_current, self.installment_total)
        if (installment_values[0] is None) != (installment_values[1] is None):
            raise ValueError("installment current and total must be provided together")
        if (
            self.installment_current is not None
            and self.installment_total is not None
            and self.installment_current > self.installment_total
        ):
            raise ValueError("installment current cannot exceed installment total")
        if (self.original_amount is None) != (self.original_currency is None):
            raise ValueError("original amount and currency must be provided together")
        return self


class PrintedTotal(BaseModel):
    """A total printed for a structurally identified statement group."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str
    amount: FiniteDecimal
    currency: str
    minor_unit: Annotated[FiniteDecimal, Field(gt=0)] = Decimal("0.01")

    @field_serializer("amount", "minor_unit")
    def serialize_money(self, value: Decimal) -> str:
        return plain_decimal_string(value)


class ReconciliationGroup(BaseModel):
    """Exact reconciliation of one printed total and its member transactions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str
    currency: str
    printed_total: FiniteDecimal
    calculated_total: FiniteDecimal
    difference: FiniteDecimal
    transaction_ids: tuple[str, ...]
    status: Status
    diagnostics: tuple[str, ...] = ()

    @field_serializer("printed_total", "calculated_total", "difference")
    def serialize_money(self, value: Decimal) -> str:
        return plain_decimal_string(value)


class DiscoveryMetadataSummary(BaseModel):
    """A discovered metadata value and the exact evidence supporting it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    value: str
    evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


_SUMMARY_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY = (
    SuffixYearMappingViolation.EMPTY,
    SuffixYearMappingViolation.UNSORTED,
    SuffixYearMappingViolation.DUPLICATE_SUFFIX,
    SuffixYearMappingViolation.INVALID_SUFFIX,
    SuffixYearMappingViolation.INVALID_YEAR,
    SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH,
    SuffixYearMappingViolation.SINGLE_YEAR_DISAGREEMENT,
)
_SUMMARY_GENERIC_SUFFIX_YEAR_MAPPING_VIOLATIONS = frozenset(
    {
        SuffixYearMappingViolation.INVALID_SUFFIX,
        SuffixYearMappingViolation.INVALID_YEAR,
        SuffixYearMappingViolation.SUFFIX_YEAR_MISMATCH,
    }
)


class DiscoveryDateYearContextSummary(BaseModel):
    """Proven short-date suffix mappings and every supporting evidence cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int | None = Field(default=None, ge=MIN_CONTEXT_YEAR, le=MAX_CONTEXT_YEAR)
    year_by_suffix: tuple[tuple[int, int], ...] = ()
    style: str
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    metadata_evidence: tuple[tuple[str, str], ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_year_mapping(self) -> Self:
        try:
            validate_suffix_year_mapping(self.year, self.year_by_suffix)
        except SuffixYearMappingValidationError as error:
            violation, message = error.resolve(_SUMMARY_SUFFIX_YEAR_MAPPING_VIOLATION_PRIORITY)
            if violation in _SUMMARY_GENERIC_SUFFIX_YEAR_MAPPING_VIOLATIONS:
                message = "invalid date suffix-year mapping"
            raise ValueError(message) from error
        return self


class RejectedTotalCandidateSummary(BaseModel):
    """A rejected total-like row retained as a nonfatal discovery advisory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = Field(min_length=1)


class DiscoveryGlyphSummary(BaseModel):
    """Dependency-neutral positioned glyph provenance for discovered structure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    char: str = Field(min_length=1)
    bbox: FiniteBBox
    origin: FinitePoint
    font: str
    size: Annotated[FiniteCoordinate, Field(ge=0)]
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0, le=1)


class DiscoveryWordSummary(BaseModel):
    """Dependency-neutral positioned word provenance for discovered structure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    bbox: FiniteBBox
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0, le=1)


class DiscoveryCellSummary(BaseModel):
    """A logical discovery cell with its exact text and source provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    text: str = Field(min_length=1)
    glyphs: tuple[DiscoveryGlyphSummary, ...] = ()
    words: tuple[DiscoveryWordSummary, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class DiscoveryRowSummary(BaseModel):
    """A discovered logical row retaining cells, words, and diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    cells: tuple[DiscoveryCellSummary, ...]
    words: tuple[DiscoveryWordSummary, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class DiscoveryColumnSummary(BaseModel):
    """A discovered schema column and the cells supporting its semantic role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0)
    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    relative_x0: Annotated[FiniteCoordinate, Field(ge=0, le=1)]
    relative_x1: Annotated[FiniteCoordinate, Field(ge=0, le=1)]
    role: str
    source_cells: tuple[DiscoveryCellSummary, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class DiscoveryTableSchemaSummary(BaseModel):
    """A complete dependency-neutral snapshot of an inferred table schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    columns: tuple[DiscoveryColumnSummary, ...]
    header_cells: tuple[DiscoveryCellSummary, ...]
    sample_cells: tuple[DiscoveryCellSummary, ...]
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class TableRegionSummary(BaseModel):
    """A public, dependency-neutral summary of one inferred transaction table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    header_evidence: tuple[EvidenceReference, ...]
    column_roles: tuple[str, ...]
    row_count: int = Field(ge=0)
    header: DiscoveryRowSummary
    rows: tuple[DiscoveryRowSummary, ...]
    table_schema: DiscoveryTableSchemaSummary
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class PrintedTotalSummary(BaseModel):
    """A discovered printed total with label and value provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str
    amount_text: str
    currency: str
    label_evidence: EvidenceReference
    value_evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementGroupDiscoverySummary(BaseModel):
    """A discovered statement group with exact table and total association."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str
    table_regions: tuple[TableRegionSummary, ...]
    printed_total: PrintedTotalSummary
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementDiscoverySummary(BaseModel):
    """Structured discovery boundary without importing discovery/layout models."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: str
    metadata: tuple[DiscoveryMetadataSummary, ...] = ()
    date_year_context: DiscoveryDateYearContextSummary | None = None
    rejected_total_candidates: tuple[RejectedTotalCandidateSummary, ...] = ()
    groups: tuple[StatementGroupDiscoverySummary, ...] = ()
    table_regions: tuple[TableRegionSummary, ...] = ()
    printed_totals: tuple[PrintedTotalSummary, ...] = ()
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class RowNormalizationSummary(BaseModel):
    """Every accepted, rejected, or merged normalization row and its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(gt=0)
    bbox: FiniteBBox
    raw_text: str
    evidence: tuple[EvidenceReference, ...]
    transaction: Transaction | None = None
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class StatementResult(BaseModel):
    """Transactions and reconciliation evidence for one statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    transactions: tuple[Transaction, ...]
    groups: tuple[ReconciliationGroup, ...]
    diagnostics: tuple[str, ...] = ()
    source_name: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    statement_id: str | None = None
    discovery: StatementDiscoverySummary | None = None
    row_results: tuple[RowNormalizationSummary, ...] = ()
    normalization_confidence: float | None = Field(default=None, ge=0, le=1)
    normalization_diagnostics: tuple[str, ...] = ()

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            source = safe_relative_posix_path(value)
        except ValueError:
            raise ValueError("source name must be a safe relative POSIX path") from None
        return source.as_posix()


class BatchResult(BaseModel):
    """Ordered results and aggregate status for a statement batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    statements: tuple[StatementResult, ...]
    diagnostics: tuple[str, ...] = ()
