"""Born-digital PDF evidence extraction and quality measurement."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.

from ccparser.evidence.currency import custom_currency_glyph_candidates
from ccparser.evidence.models import (
    BBox,
    DocumentEvidence,
    ExtractionQuality,
    Glyph,
    ImageEvidence,
    PageEvidence,
    Point,
    VectorRule,
    Word,
)
from ccparser.evidence.provider import CurrencySymbolOcrProvider, OcrProvider

NEARLY_EMPTY_USABLE_CHARACTER_COUNT = 8
EXCESSIVE_REPLACEMENT_CHARACTER_RATIO = 0.05
EXCESSIVE_CONTROL_CHARACTER_RATIO = 0.02
IMAGE_DOMINANT_AREA_RATIO = 0.5


def _custom_currency_glyph_clips(
    glyphs: Sequence[Glyph],
    words: Sequence[Word],
) -> tuple[BBox, ...]:
    clips = []
    for glyph in custom_currency_glyph_candidates(glyphs, words):
        padding = max(0.0, glyph.bbox[3] - glyph.bbox[1]) * 0.3
        right_padding = max(0.0, glyph.bbox[3] - glyph.bbox[1]) * 0.24
        clips.append(
            (
                glyph.bbox[0] - padding,
                glyph.bbox[1] - padding,
                glyph.bbox[2] + right_padding,
                glyph.bbox[3] + padding,
            )
        )
    return tuple(clips)


def _number(value: object) -> float:
    if not isinstance(value, int | float):
        raise TypeError("coordinate must be numeric")
    return float(value)


def _bbox(value: object) -> BBox:
    if isinstance(value, fitz.Rect):
        return (float(value.x0), float(value.y0), float(value.x1), float(value.y1))
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) != 4:
        raise TypeError("bounding box must contain four coordinates")
    return (_number(value[0]), _number(value[1]), _number(value[2]), _number(value[3]))


def _point(value: object) -> Point:
    if isinstance(value, fitz.Point):
        return (float(value.x), float(value.y))
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) != 2:
        raise TypeError("point must contain two coordinates")
    return (_number(value[0]), _number(value[1]))


def _transform_point(point: Point, matrix: fitz.Matrix) -> Point:
    transformed = fitz.Point(point) * matrix
    return (float(transformed.x), float(transformed.y))


def _transform_bbox(bbox: BBox, matrix: fitz.Matrix) -> BBox:
    transformed = (
        _transform_point((bbox[0], bbox[1]), matrix),
        _transform_point((bbox[2], bbox[1]), matrix),
        _transform_point((bbox[2], bbox[3]), matrix),
        _transform_point((bbox[0], bbox[3]), matrix),
    )
    x_coordinates = tuple(point[0] for point in transformed)
    y_coordinates = tuple(point[1] for point in transformed)
    return (
        min(x_coordinates),
        min(y_coordinates),
        max(x_coordinates),
        max(y_coordinates),
    )


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return cast(Sequence[object], value)


def _extract_text_blocks(
    raw: Mapping[str, object], rotation_matrix: fitz.Matrix
) -> tuple[tuple[Glyph, ...], tuple[ImageEvidence, ...]]:
    glyphs: list[Glyph] = []
    images: list[ImageEvidence] = []
    for block_value in _sequence(raw.get("blocks")):
        block = _mapping(block_value)
        if block is None:
            continue
        if block.get("type") == 1:
            width = block.get("width")
            height = block.get("height")
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                images.append(
                    ImageEvidence(
                        bbox=_transform_bbox(_bbox(block.get("bbox")), rotation_matrix),
                        width=width,
                        height=height,
                    )
                )
            continue
        if block.get("type") != 0:
            continue
        for line_value in _sequence(block.get("lines")):
            line = _mapping(line_value)
            if line is None:
                continue
            for span_value in _sequence(line.get("spans")):
                span = _mapping(span_value)
                if span is None:
                    continue
                font = span.get("font")
                size = span.get("size")
                if not isinstance(font, str) or not isinstance(size, int | float):
                    continue
                for character_value in _sequence(span.get("chars")):
                    character = _mapping(character_value)
                    if character is None:
                        continue
                    char = character.get("c")
                    if not isinstance(char, str) or not char:
                        continue
                    glyphs.append(
                        Glyph(
                            char=char,
                            bbox=_transform_bbox(_bbox(character.get("bbox")), rotation_matrix),
                            origin=_transform_point(
                                _point(character.get("origin")), rotation_matrix
                            ),
                            font=font,
                            size=float(size),
                            source="digital",
                            confidence=1.0,
                        )
                    )
    return tuple(glyphs), tuple(images)


def _extract_words(page: fitz.Page, rotation_matrix: fitz.Matrix) -> tuple[Word, ...]:
    words: list[Word] = []
    for value in _sequence(page.get_text("words", sort=False)):
        fields = _sequence(value)
        if len(fields) < 5 or not isinstance(fields[4], str) or not fields[4]:
            continue
        words.append(
            Word(
                text=fields[4],
                bbox=_transform_bbox(
                    (
                        _number(fields[0]),
                        _number(fields[1]),
                        _number(fields[2]),
                        _number(fields[3]),
                    ),
                    rotation_matrix,
                ),
                source="digital",
                confidence=1.0,
            )
        )
    return tuple(words)


def _extract_vector_rules(page: fitz.Page, rotation_matrix: fitz.Matrix) -> tuple[VectorRule, ...]:
    rules: list[VectorRule] = []
    for value in page.get_drawings():
        drawing = _mapping(value)
        if drawing is None:
            continue
        width = drawing.get("width")
        if not isinstance(width, int | float):
            continue
        rules.append(
            VectorRule(
                bbox=_transform_bbox(_bbox(drawing.get("rect")), rotation_matrix),
                width=float(width),
            )
        )
    return tuple(rules)


def _rectangle_area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def assess_extraction_quality(
    *,
    glyphs: tuple[Glyph, ...],
    words: tuple[Word, ...],
    images: tuple[ImageEvidence, ...],
    page_bbox: BBox,
) -> ExtractionQuality:
    """Measure digital extraction quality with named, issuer-independent thresholds."""

    character_count = len(glyphs)
    usable_character_count = sum(
        1
        for glyph in glyphs
        for char in glyph.char
        if not char.isspace()
        and char != "\ufffd"
        and not unicodedata.category(char).startswith("C")
    )
    denominator = max(character_count, 1)
    replacement_count = sum(glyph.char.count("\ufffd") for glyph in glyphs)
    control_count = sum(
        1 for glyph in glyphs for char in glyph.char if unicodedata.category(char) in {"Cc", "Cf"}
    )
    replacement_ratio = replacement_count / denominator
    control_ratio = control_count / denominator
    page_area = _rectangle_area(page_bbox)
    image_area = sum(_rectangle_area(image.bbox) for image in images)
    image_ratio = min(image_area / page_area, 1.0) if page_area else 0.0

    reasons: list[str] = []
    if usable_character_count < NEARLY_EMPTY_USABLE_CHARACTER_COUNT:
        reasons.append("nearly_empty_text")
    if replacement_ratio > EXCESSIVE_REPLACEMENT_CHARACTER_RATIO:
        reasons.append("excessive_replacement_characters")
    if control_ratio > EXCESSIVE_CONTROL_CHARACTER_RATIO:
        reasons.append("excessive_control_characters")
    if not words and image_ratio > IMAGE_DOMINANT_AREA_RATIO:
        reasons.append("image_dominant_without_words")

    return ExtractionQuality(
        character_count=character_count,
        usable_character_count=usable_character_count,
        word_count=len(words),
        replacement_character_ratio=replacement_ratio,
        control_character_ratio=control_ratio,
        image_area_ratio=image_ratio,
        requires_ocr=bool(reasons),
        reasons=tuple(reasons),
    )


def _source_sha256(source_bytes: bytes) -> str:
    return hashlib.sha256(source_bytes).hexdigest()


def _metadata(document: fitz.Document) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (key, value)
            for key, value in document.metadata.items()
            if isinstance(key, str) and isinstance(value, str) and value
        )
    )


def extract_pdf(path: str | Path, ocr_provider: OcrProvider | None = None) -> DocumentEvidence:
    """Extract deterministic, rotated top-left display-point evidence in page order."""

    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    source_sha256 = _source_sha256(source_bytes)
    pages: list[PageEvidence] = []
    with fitz.open(stream=source_bytes, filetype="pdf") as document:
        metadata = _metadata(document)
        for page_index, page in enumerate(document):
            rotation_matrix = page.rotation_matrix
            raw = cast(Mapping[str, object], page.get_text("rawdict"))
            glyphs, images = _extract_text_blocks(raw, rotation_matrix)
            digital_words = _extract_words(page, rotation_matrix)
            rules = _extract_vector_rules(page, rotation_matrix)
            page_bbox = _bbox(page.rect)
            quality = assess_extraction_quality(
                glyphs=glyphs,
                words=digital_words,
                images=images,
                page_bbox=page_bbox,
            )
            currency_words: tuple[Word, ...] = ()
            if isinstance(ocr_provider, CurrencySymbolOcrProvider):
                currency_words = tuple(
                    word
                    for clip in _custom_currency_glyph_clips(glyphs, digital_words)
                    if (
                        word := ocr_provider.extract_currency_symbol(
                            source_bytes,
                            source_sha256,
                            page_index,
                            clip,
                        )
                    )
                    is not None
                )
            words = (*digital_words, *currency_words)
            if quality.requires_ocr and ocr_provider is not None:
                words = (
                    *words,
                    *ocr_provider.extract_words(
                        source_bytes,
                        source_sha256,
                        page_index,
                    ),
                )
            pages.append(
                PageEvidence(
                    page_number=page_index + 1,
                    width=page_bbox[2] - page_bbox[0],
                    height=page_bbox[3] - page_bbox[1],
                    glyphs=glyphs,
                    words=words,
                    vector_rules=rules,
                    images=images,
                    quality=quality,
                )
            )
    return DocumentEvidence(source_sha256=source_sha256, pages=tuple(pages), metadata=metadata)
