from __future__ import annotations

import pytest

from ccparser.discovery import DocumentClassification, discover_statement
from ccparser.evidence import DocumentEvidence, ExtractionQuality, Glyph, PageEvidence, Word


def _word(text: str, x0: float, x1: float, y: float, *, page: int = 1) -> Word:
    del page
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="digital",
        confidence=1.0,
    )


def _page(
    page_number: int,
    words: tuple[Word, ...],
    glyphs: tuple[Glyph, ...] = (),
) -> PageEvidence:
    return PageEvidence(
        page_number=page_number,
        width=160.0,
        height=260.0,
        glyphs=glyphs,
        words=words,
        quality=ExtractionQuality(
            character_count=len(glyphs),
            usable_character_count=len(glyphs),
            word_count=len(words),
            replacement_character_ratio=0.0,
            control_character_ratio=0.0,
            image_area_ratio=0.0,
            requires_ocr=False,
        ),
    )


def _document(*pages: PageEvidence) -> DocumentEvidence:
    return DocumentEvidence(source_sha256="a" * 64, pages=tuple(pages))


def _table(y: float, currency: str, first: str, second: str) -> tuple[Word, ...]:
    return (
        _word("Date", 0.0, 28.0, y),
        _word("Description", 50.0, 95.0, y),
        _word("Amount", 118.0, 155.0, y),
        _word("01/02/2026", 0.0, 28.0, y + 20.0),
        _word("Market", 50.0, 95.0, y + 20.0),
        _word(f"{currency}{first}", 118.0, 155.0, y + 20.0),
        _word("02/02/2026", 0.0, 28.0, y + 40.0),
        _word("Cafe", 50.0, 95.0, y + 40.0),
        _word(f"{currency}{second}", 118.0, 155.0, y + 40.0),
    )


def _rtl_glyphs(text: str, right: float, y: float) -> tuple[Glyph, ...]:
    glyphs: list[Glyph] = []
    cursor = right
    for token in text.split():
        for char in token:
            glyphs.append(
                Glyph(
                    char=char,
                    bbox=(cursor - 2.0, y, cursor, y + 10.0),
                    origin=(cursor, y + 9.0),
                    font="SyntheticHebrew",
                    size=10.0,
                    source="digital",
                    confidence=1.0,
                )
            )
            cursor -= 3.0
        cursor -= 6.0
    return tuple(glyphs)


def test_discover_statement_builds_deterministic_separate_currency_groups() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            *_table(120.0, "$", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 180.0),
            _word("$12.00", 118.0, 155.0, 180.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert result.reason_codes == ("transaction_table_with_compatible_total",)
    assert tuple(group.group_id for group in result.groups) == ("group-0001", "group-0002")
    assert tuple(group.printed_total.currency for group in result.groups) == ("ILS", "USD")
    assert tuple(group.printed_total.amount_text for group in result.groups) == (
        "₪30.00",
        "$12.00",
    )
    assert all(len(group.table_regions) == 1 for group in result.groups)
    assert result.confidence >= 0.8


def test_discover_statement_keeps_unknown_or_multiple_total_values_ambiguous() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("30.00", 102.0, 125.0, 80.0),
            _word("31.00", 130.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.AMBIGUOUS
    assert result.groups == ()
    assert "ambiguous_total_value" in result.diagnostics
    assert "unknown_total_currency" in result.diagnostics
    assert "statement_evidence_incomplete" in result.reason_codes


def test_discover_statement_uses_positive_form_evidence_and_not_absence() -> None:
    form = _page(
        1,
        (
            _word("Card cancellation form", 10.0, 145.0, 20.0),
            _word("Signature", 10.0, 65.0, 60.0),
            _word("Applicant name", 80.0, 145.0, 60.0),
        ),
    )
    prose = _page(1, (_word("Hello", 10.0, 45.0, 20.0),))

    form_result = discover_statement(_document(form))
    prose_result = discover_statement(_document(prose))

    assert form_result.classification is DocumentClassification.NOT_STATEMENT
    assert form_result.confidence >= 0.9
    assert form_result.reason_codes == ("positive_non_statement_form_evidence",)
    assert prose_result.classification is DocumentClassification.AMBIGUOUS
    assert prose_result.reason_codes == ("insufficient_positive_evidence",)


def test_discover_statement_retains_labeled_metadata_without_leaking_it_to_diagnostics() -> None:
    page = _page(
        1,
        (
            _word("Card number", 10.0, 70.0, 5.0),
            _word("1234-5678-9012-3456", 80.0, 155.0, 5.0),
            *_table(30.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 90.0),
            _word("₪30.00", 118.0, 155.0, 90.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.card_number is not None
    assert result.card_number.value == "1234-5678-9012-3456"
    assert result.card_number.evidence.raw_text == "1234-5678-9012-3456"
    public_diagnostics = " ".join((*result.diagnostics, *result.reason_codes))
    assert "1234" not in public_diagnostics
    assert "3456" not in public_diagnostics


def test_discover_statement_reconstructs_backwards_hebrew_total_from_glyphs() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("לכה ךס", 50.0, 95.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
    )
    glyphs = _rtl_glyphs("סך הכל", 93.0, 80.0)

    result = discover_statement(_document(_page(1, words, glyphs)))

    assert result.classification is DocumentClassification.STATEMENT
    assert result.groups[0].printed_total.label_evidence.raw_text == "סך הכל"


def test_discover_statement_preserves_negative_trailing_sign_total() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00-", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert result.groups[0].printed_total.amount_text == "₪30.00-"


@pytest.mark.parametrize("malformed", ("₪30.00--", "₪-+30.00", "₪30.00- text"))
def test_discover_statement_rejects_malformed_or_residual_total_text(malformed: str) -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word(malformed, 110.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.AMBIGUOUS
    assert result.groups == ()
    assert "ambiguous_total_value" in result.diagnostics


def test_same_currency_multi_card_tables_each_pair_with_their_adjacent_total() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            *_table(110.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 170.0),
            _word("₪12.00", 118.0, 155.0, 170.0),
        ),
    )

    result = discover_statement(_document(page))

    assert tuple(group.group_id for group in result.groups) == ("group-0001", "group-0002")
    assert all(len(group.table_regions) == 1 for group in result.groups)


def test_totals_after_multiple_same_currency_tables_remain_unassigned() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            *_table(90.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 150.0),
            _word("₪30.00", 118.0, 155.0, 150.0),
            _word("Total", 50.0, 95.0, 170.0),
            _word("₪12.00", 118.0, 155.0, 170.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.AMBIGUOUS
    assert result.groups == ()
    assert "ambiguous_group_region_association" in result.diagnostics


def test_mixed_currency_table_is_not_compatible_with_billing_total() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "", "$10.00", "₪20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.AMBIGUOUS
    assert result.groups == ()
    assert "ambiguous_table_currency" in result.diagnostics


def test_consecutive_pages_with_compatible_schema_form_proven_continuation_chain() -> None:
    first_page = _page(1, _table(20.0, "₪", "10.00", "20.00"))
    second_page = _page(
        2,
        (
            *_table(20.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪42.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(first_page, second_page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert tuple(region.page_number for region in result.groups[0].table_regions) == (1, 2)
