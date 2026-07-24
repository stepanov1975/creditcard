from __future__ import annotations

import ast
import hashlib
import inspect
from decimal import Decimal

import ccparser.ocr_repair as ocr_repair_module
from ccparser.evidence import DocumentEvidence, ExtractionQuality, PageEvidence, Word
from ccparser.layout import detect_table_regions
from ccparser.ocr_repair import repair_table_numeric_ocr


def test_ocr_schema_preview_calls_row_only_candidate_schema() -> None:
    tree = ast.parse(inspect.getsource(ocr_repair_module._repair_page))
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_candidate_schema"
    )

    assert len(call.args) == 2


def _ocr_word(text: str, x0: float, x1: float, y: float) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="ocr",
        confidence=0.7,
    )


class _ClipOcr:
    def __init__(self) -> None:
        self.clips: list[tuple[float, float, float, float] | None] = []

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: tuple[float, float, float, float] | None = None,
    ) -> tuple[Word, ...]:
        assert hashlib.sha256(pdf_bytes).hexdigest() == source_sha256
        assert page_index == 0
        self.clips.append(clip)
        assert clip is not None
        return (
            _ocr_word("₪", 2.0, 7.0, 30.0),
            _ocr_word("14.90", 9.0, 28.0, 30.0).model_copy(update={"confidence": 0.96}),
        )


def test_geometry_bounded_ocr_repairs_truncated_table_amount() -> None:
    pdf_bytes = b"synthetic image statement"
    damaged = _ocr_word("₪1", 2.0, 28.0, 30.0)
    words = (
        _ocr_word("Billed amount", 0.0, 30.0, 10.0),
        _ocr_word("Description", 60.0, 90.0, 10.0),
        _ocr_word("Date", 105.0, 130.0, 10.0),
        damaged,
        _ocr_word("Market", 60.0, 90.0, 30.0),
        _ocr_word("01/02/2026", 105.0, 130.0, 30.0),
        _ocr_word("20.00", 2.0, 28.0, 50.0),
        _ocr_word("Cafe", 60.0, 90.0, 50.0),
        _ocr_word("02/02/2026", 105.0, 130.0, 50.0),
        _ocr_word("30.00", 2.0, 28.0, 70.0),
        _ocr_word("Hotel", 60.0, 90.0, 70.0),
        _ocr_word("03/02/2026", 105.0, 130.0, 70.0),
        _ocr_word("Total", 60.0, 90.0, 90.0),
        _ocr_word("64.90", 2.0, 28.0, 90.0),
    )
    page = PageEvidence(
        page_number=1,
        width=130.0,
        height=120.0,
        words=words,
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=1.0,
            requires_ocr=True,
            reasons=("image_dominant_without_words",),
        ),
    )
    evidence = DocumentEvidence(
        source_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        pages=(page,),
    )
    provider = _ClipOcr()

    repaired = repair_table_numeric_ocr(
        evidence,
        pdf_bytes,
        provider,
        currency_hints=("ILS",),
    )

    assert 1 <= len(provider.clips) <= 3
    assert damaged not in repaired.pages[0].words
    regions = detect_table_regions(repaired.pages[0])
    assert len(regions) == 1
    assert tuple(row.cells[0].text for row in regions[0].rows) == (
        "₪ 14.90",
        "20.00",
        "30.00",
    )


def test_geometry_bounded_ocr_does_not_run_on_born_digital_page() -> None:
    pdf_bytes = b"synthetic digital statement"
    page = PageEvidence(
        page_number=1,
        width=130.0,
        height=120.0,
        words=(),
        quality=ExtractionQuality(
            character_count=100,
            usable_character_count=100,
            word_count=10,
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )
    evidence = DocumentEvidence(
        source_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        pages=(page,),
    )
    provider = _ClipOcr()

    assert (
        repair_table_numeric_ocr(
            evidence,
            pdf_bytes,
            provider,
            currency_hints=("ILS",),
        )
        == evidence
    )
    assert provider.clips == []


def test_geometry_bounded_ocr_repairs_summary_value_to_proven_group_total() -> None:
    pdf_bytes = b"synthetic damaged summary"
    damaged = _ocr_word("1130.00", 90.0, 125.0, 15.0)
    words = (
        _ocr_word("Total amount", 40.0, 80.0, 0.0),
        damaged,
        _ocr_word("Date", 0.0, 22.0, 30.0),
        _ocr_word("Description", 35.0, 72.0, 30.0),
        _ocr_word("Amount", 92.0, 120.0, 30.0),
        _ocr_word("01/02/2026", 0.0, 22.0, 50.0),
        _ocr_word("Market", 35.0, 72.0, 50.0),
        _ocr_word("30.00", 92.0, 120.0, 50.0),
        _ocr_word("Total", 35.0, 72.0, 70.0),
        _ocr_word("30.00", 92.0, 120.0, 70.0),
    )
    page = PageEvidence(
        page_number=1,
        width=130.0,
        height=100.0,
        words=words,
        quality=ExtractionQuality(
            character_count=0,
            usable_character_count=0,
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=1.0,
            requires_ocr=True,
            reasons=("image_dominant_without_words",),
        ),
    )
    evidence = DocumentEvidence(
        source_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        pages=(page,),
    )

    class SummaryOcr(_ClipOcr):
        def extract_words(
            self,
            pdf_bytes: bytes,
            source_sha256: str,
            page_index: int,
            clip: tuple[float, float, float, float] | None = None,
        ) -> tuple[Word, ...]:
            super().extract_words(pdf_bytes, source_sha256, page_index, clip)
            return (_ocr_word("30.00", 92.0, 120.0, 15.0),)

    repaired = repair_table_numeric_ocr(
        evidence,
        pdf_bytes,
        SummaryOcr(),
        currency_hints=("ILS",),
        expected_totals=(Decimal("30.00"),),
    )

    assert damaged not in repaired.pages[0].words
    assert any(word.text == "30.00" and word.bbox[1] == 15.0 for word in repaired.pages[0].words)
