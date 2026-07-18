"""Immutable coordinate models for raw document evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type BBox = tuple[float, float, float, float]
type Point = tuple[float, float]
type EvidenceSource = Literal["digital", "ocr"]


class _ImmutableEvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Glyph(_ImmutableEvidenceModel):
    """A positioned character read directly from the PDF text layer."""

    char: str = Field(min_length=1)
    bbox: BBox
    origin: Point
    font: str
    size: float = Field(ge=0)
    source: EvidenceSource
    confidence: float = Field(ge=0, le=1)


class Word(_ImmutableEvidenceModel):
    """A positioned digital or OCR word."""

    text: str = Field(min_length=1)
    bbox: BBox
    source: EvidenceSource
    confidence: float = Field(ge=0, le=1)


class VectorRule(_ImmutableEvidenceModel):
    """The bounding box and stroke width of a PDF vector path."""

    bbox: BBox
    width: float = Field(ge=0)


class ImageEvidence(_ImmutableEvidenceModel):
    """The page-space bounds and intrinsic pixel dimensions of an image."""

    bbox: BBox
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ExtractionQuality(_ImmutableEvidenceModel):
    """Measured digital-text quality and issuer-neutral OCR decision."""

    character_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    replacement_character_ratio: float = Field(ge=0, le=1)
    control_character_ratio: float = Field(ge=0, le=1)
    image_area_ratio: float = Field(ge=0, le=1)
    requires_ocr: bool
    reasons: tuple[str, ...] = ()


class PageEvidence(_ImmutableEvidenceModel):
    """All raw evidence retained for one one-based PDF page."""

    page_number: int = Field(gt=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    glyphs: tuple[Glyph, ...] = ()
    words: tuple[Word, ...] = ()
    vector_rules: tuple[VectorRule, ...] = ()
    images: tuple[ImageEvidence, ...] = ()
    quality: ExtractionQuality


class DocumentEvidence(_ImmutableEvidenceModel):
    """Deterministically ordered positioned evidence for a source document."""

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[PageEvidence, ...]
    metadata: tuple[tuple[str, str], ...] = ()
