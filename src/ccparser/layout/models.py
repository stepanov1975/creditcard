"""Immutable models for inferred page layout and table structure."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ccparser.evidence.models import BBox, Glyph, Word


class _ImmutableLayoutModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ColumnRole(StrEnum):
    """Issuer-neutral semantic role inferred for a statement column."""

    UNKNOWN = "unknown"
    DATE = "date"
    DESCRIPTION = "description"
    AMOUNT = "amount"
    ORIGINAL_AMOUNT = "original_amount"
    CURRENCY = "currency"
    BILLING_CURRENCY = "billing_currency"
    ORIGINAL_CURRENCY = "original_currency"
    INSTALLMENT = "installment"


class Cell(_ImmutableLayoutModel):
    """Logical cell text with its exact positioned source evidence."""

    page_number: int = Field(gt=0)
    bbox: BBox
    text: str = Field(min_length=1)
    glyphs: tuple[Glyph, ...] = ()
    words: tuple[Word, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class Row(_ImmutableLayoutModel):
    """A vertically clustered row of logical cells."""

    page_number: int = Field(gt=0)
    bbox: BBox
    cells: tuple[Cell, ...]
    words: tuple[Word, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class ColumnSpec(_ImmutableLayoutModel):
    """A scale-independent inferred x band and optional semantic role."""

    index: int = Field(ge=0)
    page_number: int = Field(gt=0)
    bbox: BBox
    relative_x0: float = Field(ge=0, le=1)
    relative_x1: float = Field(ge=0, le=1)
    role: ColumnRole = ColumnRole.UNKNOWN
    source_cells: tuple[Cell, ...] = ()
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class TableSchema(_ImmutableLayoutModel):
    """Semantic interpretation of inferred columns with ambiguity diagnostics."""

    page_number: int = Field(gt=0)
    bbox: BBox
    columns: tuple[ColumnSpec, ...]
    header_cells: tuple[Cell, ...]
    sample_cells: tuple[Cell, ...]
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()


class TableRegion(_ImmutableLayoutModel):
    """A detected transaction-like table region and its provenance."""

    page_number: int = Field(gt=0)
    bbox: BBox
    header: Row
    rows: tuple[Row, ...]
    table_schema: TableSchema
    confidence: float = Field(ge=0, le=1)
    diagnostics: tuple[str, ...] = ()
