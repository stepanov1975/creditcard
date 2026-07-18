"""Immutable public domain models for statement parsing."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


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

    @field_serializer("billed_amount")
    def serialize_billed_amount(self, value: Decimal) -> str:
        return _decimal_string(value)

    @model_validator(mode="after")
    def validate_amount_sign(self) -> Self:
        if self.kind is TransactionKind.CHARGE and self.billed_amount <= 0:
            raise ValueError("charge amount must be positive")
        if self.kind is TransactionKind.CREDIT and self.billed_amount >= 0:
            raise ValueError("credit amount must be negative")
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
