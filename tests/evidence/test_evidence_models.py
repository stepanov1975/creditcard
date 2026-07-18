from __future__ import annotations

import pytest
from pydantic import ValidationError

from ccparser.evidence.models import (
    DocumentEvidence,
    ExtractionQuality,
    Glyph,
    PageEvidence,
    Word,
)


def test_evidence_models_are_immutable() -> None:
    quality = ExtractionQuality(
        character_count=1,
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
