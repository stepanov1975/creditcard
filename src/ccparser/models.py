"""Immutable public domain models for statement parsing."""

from __future__ import annotations

import unicodedata
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


def _decimal_string(value: Decimal) -> str:
    """Return a canonical plain-decimal representation for financial output."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        return "0"
    return text


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
    bbox: tuple[float, float, float, float]
    raw_text: str


class Transaction(BaseModel):
    """A transaction contributing to one or more candidate statement groups."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str
    kind: TransactionKind
    billed_amount: Decimal
    billing_currency: str
    reconciliation_group_ids: tuple[str, ...]
    ambiguities: tuple[str, ...] = ()
    transaction_date: date | None = None
    posting_date: date | None = None
    description: str | None = None
    category: TransactionCategory = TransactionCategory.UNKNOWN
    original_amount: Decimal | None = None
    original_currency: str | None = None
    installment_current: int | None = Field(default=None, gt=0)
    installment_total: int | None = Field(default=None, gt=0)
    evidence: tuple[EvidenceReference, ...] = ()

    @field_serializer("billed_amount", "original_amount")
    def serialize_amount(self, value: Decimal | None) -> str | None:
        return _decimal_string(value) if value is not None else None

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
    amount: Decimal
    currency: str
    minor_unit: Decimal = Field(default=Decimal("0.01"), gt=0)

    @field_serializer("amount", "minor_unit")
    def serialize_money(self, value: Decimal) -> str:
        return _decimal_string(value)


class ReconciliationGroup(BaseModel):
    """Exact reconciliation of one printed total and its member transactions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str
    currency: str
    printed_total: Decimal
    calculated_total: Decimal
    difference: Decimal
    transaction_ids: tuple[str, ...]
    status: Status
    diagnostics: tuple[str, ...] = ()

    @field_serializer("printed_total", "calculated_total", "difference")
    def serialize_money(self, value: Decimal) -> str:
        return _decimal_string(value)


class StatementResult(BaseModel):
    """Transactions and reconciliation evidence for one statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    transactions: tuple[Transaction, ...]
    groups: tuple[ReconciliationGroup, ...]
    diagnostics: tuple[str, ...] = ()


class BatchResult(BaseModel):
    """Ordered results and aggregate status for a statement batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    statements: tuple[StatementResult, ...]
    diagnostics: tuple[str, ...] = ()
