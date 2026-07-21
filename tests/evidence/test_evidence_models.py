from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from ccparser.evidence.models import (
    DocumentEvidence,
    ExtractionQuality,
    Glyph,
    ImageEvidence,
    PageEvidence,
    VectorRule,
    Word,
)
from ccparser.geometry import BBox, Point

type EvidenceBBoxFactory = Callable[[BBox], object]


def _glyph(bbox: BBox, *, origin: Point = (10.0, 19.0)) -> Glyph:
    return Glyph(
        char="A",
        bbox=bbox,
        origin=origin,
        font="SyntheticSans",
        size=10.0,
        source="digital",
        confidence=1.0,
    )


def _word(bbox: BBox) -> Word:
    return Word(
        text="Alpha",
        bbox=bbox,
        source="digital",
        confidence=1.0,
    )


def _vector_rule(bbox: BBox) -> VectorRule:
    return VectorRule(bbox=bbox, width=1.0)


def _image_evidence(bbox: BBox) -> ImageEvidence:
    return ImageEvidence(bbox=bbox, width=100, height=50)


_BBOX_FACTORIES: tuple[EvidenceBBoxFactory, ...] = (
    _glyph,
    _word,
    _vector_rule,
    _image_evidence,
)

_INVALID_BBOXES: tuple[tuple[str, BBox], ...] = (
    ("nan", (math.nan, 0.0, 10.0, 10.0)),
    ("positive-infinity", (0.0, 0.0, math.inf, 10.0)),
    ("negative-infinity", (-math.inf, 0.0, 10.0, 10.0)),
    ("inverted-x", (10.0, 0.0, 9.0, 10.0)),
    ("inverted-y", (0.0, 10.0, 10.0, 9.0)),
)

_VALID_BBOXES: tuple[tuple[str, BBox], ...] = (
    ("ordered", (0.0, 0.0, 10.0, 10.0)),
    ("zero-area", (5.0, 5.0, 5.0, 5.0)),
    ("outside-page", (-0.25, -0.5, 100.25, 200.5)),
)


def test_evidence_models_are_immutable() -> None:
    quality = ExtractionQuality(
        character_count=1,
        usable_character_count=1,
        word_count=1,
        replacement_character_ratio=0.0,
        control_character_ratio=0.0,
        image_area_ratio=0.0,
        requires_ocr=False,
    )
    page = PageEvidence(
        page_number=1,
        width=200.0,
        height=300.0,
        glyphs=(
            Glyph(
                char="A",
                bbox=(10.0, 20.0, 17.0, 30.0),
                origin=(10.0, 29.0),
                font="SyntheticSans",
                size=10.0,
                source="digital",
                confidence=1.0,
            ),
        ),
        words=(
            Word(
                text="Alpha",
                bbox=(10.0, 20.0, 40.0, 30.0),
                source="digital",
                confidence=1.0,
            ),
        ),
        quality=quality,
    )
    evidence = DocumentEvidence(
        source_sha256="a" * 64,
        pages=(page,),
        metadata=(("title", "Synthetic document"),),
    )

    with pytest.raises(ValidationError):
        evidence.pages = ()
    with pytest.raises(ValidationError):
        evidence.pages[0].words = ()


@pytest.mark.parametrize("factory", _BBOX_FACTORIES, ids=lambda value: value.__name__)
@pytest.mark.parametrize("_name,bbox", _INVALID_BBOXES, ids=[name for name, _ in _INVALID_BBOXES])
def test_evidence_bbox_models_reject_impossible_geometry(
    factory: EvidenceBBoxFactory,
    _name: str,
    bbox: BBox,
) -> None:
    with pytest.raises(ValidationError):
        factory(bbox)


@pytest.mark.parametrize("factory", _BBOX_FACTORIES, ids=lambda value: value.__name__)
@pytest.mark.parametrize("_name,bbox", _VALID_BBOXES, ids=[name for name, _ in _VALID_BBOXES])
def test_evidence_bbox_models_accept_ordered_finite_geometry(
    factory: EvidenceBBoxFactory,
    _name: str,
    bbox: BBox,
) -> None:
    factory(bbox)


@pytest.mark.parametrize(
    "origin",
    (
        (math.nan, 0.0),
        (math.inf, 0.0),
        (-math.inf, 0.0),
        (0.0, math.nan),
        (0.0, math.inf),
        (0.0, -math.inf),
    ),
)
def test_glyph_rejects_nonfinite_origin(origin: Point) -> None:
    with pytest.raises(ValidationError):
        _glyph((0.0, 0.0, 10.0, 10.0), origin=origin)


def test_glyph_accepts_finite_origin_outside_page_bounds() -> None:
    glyph = Glyph(
        char="A",
        bbox=(-0.25, -0.5, 10.0, 10.0),
        origin=(-0.5, 10.25),
        font="SyntheticSans",
        size=10.0,
        source="digital",
        confidence=1.0,
    )

    assert glyph.origin == (-0.5, 10.25)
