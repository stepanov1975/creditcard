from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from ccparser.evidence.models import Glyph, ImageEvidence, Word
from ccparser.evidence.pdf import _extract_text_blocks, assess_extraction_quality, extract_pdf


def _save_digital_pdf(path: Path) -> None:
    document = fitz.open()
    document.set_metadata({"title": "Synthetic evidence"})
    page = document.new_page(width=240, height=320)
    page.insert_text((24, 48), "Readable digital statement line", fontsize=11)
    page.draw_line((20, 80), (220, 80), width=0.75)
    document.save(path)
    document.close()


def _save_image_only_pdf(path: Path) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
    pixmap.clear_with(255)
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.insert_image((10, 10, 190, 190), stream=pixmap.tobytes("png"))
    document.save(path)
    document.close()


def _save_rotated_pdf(path: Path) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    pixmap.clear_with(255)
    document = fitz.open()
    page = document.new_page(width=120, height=200)
    page.insert_text((20, 40), "Rotate", fontsize=11)
    page.draw_line((10, 60), (100, 60), width=0.5)
    page.insert_image((10, 100, 50, 140), stream=pixmap.tobytes("png"))
    page.set_rotation(90)
    document.save(path)
    document.close()


def test_extract_pdf_returns_stable_positioned_digital_evidence(tmp_path: Path) -> None:
    path = tmp_path / "digital.pdf"
    _save_digital_pdf(path)

    first = extract_pdf(path)
    second = extract_pdf(path)

    assert first == second
    assert first.source_sha256 == second.source_sha256
    assert len(first.source_sha256) == 64
    assert dict(first.metadata)["title"] == "Synthetic evidence"
    assert len(first.pages) == 1
    page = first.pages[0]
    assert page.page_number == 1
    assert page.width == 240.0
    assert page.height == 320.0
    assert "".join(glyph.char for glyph in page.glyphs) == "Readable digital statement line"
    assert all(glyph.source == "digital" for glyph in page.glyphs)
    assert all(0 <= value <= 320 for glyph in page.glyphs for value in glyph.bbox)
    assert [word.text for word in page.words] == [
        "Readable",
        "digital",
        "statement",
        "line",
    ]
    assert page.vector_rules
    assert page.vector_rules[0].bbox == (20.0, 80.0, 220.0, 80.0)
    assert page.vector_rules[0].width == 0.75
    assert page.quality.requires_ocr is False


def test_extract_pdf_transforms_all_evidence_to_rotated_display_coordinates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rotated.pdf"
    _save_rotated_pdf(path)

    evidence = extract_pdf(path)

    page = evidence.pages[0]
    assert (page.width, page.height) == (200.0, 120.0)
    assert page.glyphs[0].origin == (160.0, 20.0)
    assert page.words[0].bbox == pytest.approx((156.711, 20.0, 171.825, 52.406))
    assert page.vector_rules[0].bbox == (140.0, 10.0, 140.0, 100.0)
    assert page.images[0].bbox == (60.0, 10.0, 100.0, 50.0)
    for bbox in (
        *(glyph.bbox for glyph in page.glyphs),
        *(word.bbox for word in page.words),
        *(rule.bbox for rule in page.vector_rules),
        *(image.bbox for image in page.images),
    ):
        assert 0 <= bbox[0] <= bbox[2] <= page.width
        assert 0 <= bbox[1] <= bbox[3] <= page.height


def test_quality_requires_ocr_for_excessive_unmapped_glyphs() -> None:
    glyphs = tuple(
        Glyph(
            char="\ufffd" if index < 2 else "A",
            bbox=(float(index), 0.0, float(index + 1), 1.0),
            origin=(float(index), 1.0),
            font="SyntheticCustom",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index in range(20)
    )
    words = (
        Word(
            text="Synthetic",
            bbox=(0.0, 0.0, 10.0, 1.0),
            source="digital",
            confidence=1.0,
        ),
    )

    quality = assess_extraction_quality(
        glyphs=glyphs,
        words=words,
        images=(),
        page_bbox=(0.0, 0.0, 100.0, 100.0),
    )

    assert quality.requires_ocr is True
    assert quality.replacement_character_ratio == 0.1
    assert "excessive_replacement_characters" in quality.reasons


def _positioned_glyphs(text: str) -> tuple[Glyph, ...]:
    return tuple(
        Glyph(
            char=char,
            bbox=(float(index), 0.0, float(index + 1), 1.0),
            origin=(float(index), 1.0),
            font="SyntheticSans",
            size=10.0,
            source="digital",
            confidence=1.0,
        )
        for index, char in enumerate(text)
    )


def _single_digital_word() -> tuple[Word, ...]:
    return (
        Word(
            text="Synthetic",
            bbox=(0.0, 0.0, 10.0, 1.0),
            source="digital",
            confidence=1.0,
        ),
    )


def test_quality_requires_ocr_for_nearly_empty_digital_text() -> None:
    quality = assess_extraction_quality(
        glyphs=_positioned_glyphs("Few"),
        words=_single_digital_word(),
        images=(),
        page_bbox=(0.0, 0.0, 100.0, 100.0),
    )

    assert quality.requires_ocr is True
    assert "nearly_empty_text" in quality.reasons


def test_quality_requires_ocr_for_excessive_control_characters() -> None:
    quality = assess_extraction_quality(
        glyphs=_positioned_glyphs("\u0001\u0002" + "A" * 18),
        words=_single_digital_word(),
        images=(),
        page_bbox=(0.0, 0.0, 100.0, 100.0),
    )

    assert quality.control_character_ratio == 0.1
    assert quality.requires_ocr is True
    assert "excessive_control_characters" in quality.reasons


def test_quality_requires_ocr_when_raw_glyphs_have_no_usable_content() -> None:
    quality = assess_extraction_quality(
        glyphs=_positioned_glyphs(" " * 9),
        words=(),
        images=(),
        page_bbox=(0.0, 0.0, 100.0, 100.0),
    )

    assert quality.character_count == 9
    assert quality.usable_character_count == 0
    assert quality.requires_ocr is True
    assert "nearly_empty_text" in quality.reasons


def test_extract_pdf_marks_image_dominant_page_without_words_for_ocr(tmp_path: Path) -> None:
    path = tmp_path / "image-only.pdf"
    _save_image_only_pdf(path)

    evidence = extract_pdf(path)

    page = evidence.pages[0]
    assert page.glyphs == ()
    assert page.words == ()
    assert page.images == (ImageEvidence(bbox=(10.0, 10.0, 190.0, 190.0), width=64, height=64),)
    assert page.quality.image_area_ratio == 0.81
    assert page.quality.requires_ocr is True
    assert "image_dominant_without_words" in page.quality.reasons


def test_extract_text_blocks_ignores_zero_dimension_image_placeholders() -> None:
    raw = {
        "blocks": [
            {"type": 1, "bbox": (10, 10, 20, 20), "width": 0, "height": 0},
            {"type": 1, "bbox": (30, 30, 50, 50), "width": 12, "height": 8},
        ]
    }

    glyphs, images = _extract_text_blocks(raw, fitz.Matrix(1, 1))

    assert glyphs == ()
    assert images == (ImageEvidence(bbox=(30.0, 30.0, 50.0, 50.0), width=12, height=8),)


class _RecordingOcrProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, int, tuple[float, float, float, float] | None]] = []

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: tuple[float, float, float, float] | None = None,
    ) -> tuple[Word, ...]:
        self.calls.append((pdf_bytes, source_sha256, page_index, clip))
        return (
            Word(
                text="Recognized",
                bbox=(12.0, 18.0, 72.0, 30.0),
                source="ocr",
                confidence=0.92,
            ),
        )


def test_extract_pdf_uses_ocr_only_when_digital_quality_requires_it(tmp_path: Path) -> None:
    digital_path = tmp_path / "digital.pdf"
    image_path = tmp_path / "image.pdf"
    _save_digital_pdf(digital_path)
    _save_image_only_pdf(image_path)
    provider = _RecordingOcrProvider()

    digital = extract_pdf(digital_path, provider)
    image = extract_pdf(image_path, provider)

    assert all(word.source == "digital" for word in digital.pages[0].words)
    assert image.pages[0].words[0].text == "Recognized"
    assert provider.calls == [(image_path.read_bytes(), image.source_sha256, 0, None)]


class _MutatingOcrProvider:
    def __init__(self, source_path: Path, replacement_bytes: bytes) -> None:
        self.source_path = source_path
        self.replacement_bytes = replacement_bytes
        self.received: bytes | object | None = None

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: tuple[float, float, float, float] | None = None,
    ) -> tuple[Word, ...]:
        del source_sha256, page_index, clip
        self.received = pdf_bytes
        self.source_path.write_bytes(self.replacement_bytes)
        title = "Wrong input"
        if isinstance(pdf_bytes, bytes):
            with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                title = document.metadata["title"]
        return (
            Word(
                text=title,
                bbox=(12.0, 18.0, 72.0, 30.0),
                source="ocr",
                confidence=0.92,
            ),
        )


def test_extract_pdf_uses_one_immutable_source_snapshot_for_evidence_and_ocr(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    replacement_path = tmp_path / "replacement.pdf"
    _save_image_only_pdf(source_path)
    with fitz.open(source_path) as source_document:
        source_document.set_metadata({"title": "Original snapshot"})
        source_document.save(source_path.with_suffix(".updated.pdf"))
    source_path.with_suffix(".updated.pdf").replace(source_path)
    _save_digital_pdf(replacement_path)
    original_bytes = source_path.read_bytes()
    provider = _MutatingOcrProvider(source_path, replacement_path.read_bytes())

    evidence = extract_pdf(source_path, provider)

    assert provider.received == original_bytes
    assert evidence.source_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert dict(evidence.metadata)["title"] == "Original snapshot"
    assert evidence.pages[0].words[0].text == "Original snapshot"
    assert source_path.read_bytes() == replacement_path.read_bytes()
