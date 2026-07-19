from __future__ import annotations

import pytest

from ccparser.discovery import DateTokenStyle, DocumentClassification, discover_statement
from ccparser.evidence import DocumentEvidence, ExtractionQuality, Glyph, PageEvidence, Word
from ccparser.models import Status
from ccparser.normalize import normalize_statement


def _word(
    text: str,
    x0: float,
    x1: float,
    y: float,
    *,
    page: int = 1,
    height: float = 10.0,
) -> Word:
    del page
    return Word(
        text=text,
        bbox=(x0, y, x1, y + height),
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


def _ltr_glyphs(
    text: str,
    left: float,
    y: float,
    *,
    height: float,
) -> tuple[Glyph, ...]:
    glyphs: list[Glyph] = []
    cursor = left
    for char in text:
        glyphs.append(
            Glyph(
                char=char,
                bbox=(cursor, y, cursor + 0.2, y + height),
                origin=(cursor, y + height * 0.9),
                font="Synthetic",
                size=height,
                source="digital",
                confidence=1.0,
            )
        )
        cursor += 0.25
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


def test_discover_statement_infers_currency_only_from_proven_billed_amount_band() -> None:
    page = _page(
        1,
        (
            _word("Date", 0.0, 25.0, 20.0),
            _word("Description", 42.0, 72.0, 20.0),
            _word("Amount USD", 88.0, 115.0, 20.0),
            _word("Billed amount", 132.0, 158.0, 20.0),
            _word("01/02/2026", 0.0, 25.0, 40.0),
            _word("Market", 42.0, 72.0, 40.0),
            _word("₪10.00", 132.0, 158.0, 40.0),
            _word("02/02/2026", 0.0, 25.0, 60.0),
            _word("Cafe", 42.0, 72.0, 60.0),
            _word("₪20.00", 132.0, 158.0, 60.0),
            _word("Total", 42.0, 72.0, 80.0),
            _word("30.00", 132.0, 158.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.groups[0].printed_total.currency == "ILS"
    assert "unknown_total_currency" not in result.diagnostics


def test_ambiguous_total_eligible_for_claimed_table_blocks_reconciliation() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 45.0, 80.0, 80.0),
            _word("30.00", 100.0, 125.0, 80.0),
            _word("31.00", 130.0, 155.0, 80.0),
            _word("Total amount", 45.0, 95.0, 100.0),
            _word("30.00", 100.0, 125.0, 100.0),
            _word("31.00", 130.0, 155.0, 100.0),
            _word("Total", 50.0, 95.0, 120.0),
            _word("₪30.00", 118.0, 155.0, 120.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.groups[0].table_regions == result.table_regions
    assert "ambiguous_total_value" in result.diagnostics
    assert len(result.rejected_total_candidates) == 2
    assert all(
        candidate.diagnostics == ("ambiguous_total_value",)
        for candidate in result.rejected_total_candidates
    )
    assert result.rejected_total_candidates[0].evidence[0].raw_text == "Total"
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_ambiguous_total_after_claimed_section_remains_reconciliation_fatal() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("Total", 45.0, 80.0, 100.0),
            _word("30.00", 100.0, 125.0, 100.0),
            _word("31.00", 130.0, 155.0, 100.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("ambiguous_total_value",)
    assert len(result.rejected_total_candidates) == 1
    assert result.rejected_total_candidates[0].diagnostics == ("ambiguous_total_value",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_lossless_tiny_duplicate_of_valid_total_is_excluded_as_overlay_artifact() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 30.0, 65.0, 80.0),
            _word("03/02/2026", 70.0, 105.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("₪30.00", 30.0, 65.0, 92.0, height=0.8),
            _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
            _word("Total", 118.0, 155.0, 92.0, height=0.8),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.rejected_total_candidates == ()
    assert result.diagnostics == ()
    assert normalize_statement(result).reconciliation.status is Status.RECONCILED


def test_tiny_total_with_one_different_word_remains_fatal() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 30.0, 65.0, 80.0),
            _word("03/02/2026", 70.0, 105.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("₪31.00", 30.0, 65.0, 92.0, height=0.8),
            _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
            _word("Total", 118.0, 155.0, 92.0, height=0.8),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_raw_identical_overlay_with_conflicting_amount_glyphs_remains_fatal() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("Total", 30.0, 65.0, 80.0),
        _word("03/02/2026", 70.0, 105.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
        _word("₪30.00", 30.0, 65.0, 92.0, height=0.8),
        _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
        _word("Total", 118.0, 155.0, 92.0, height=0.8),
    )
    candidate_glyphs = _ltr_glyphs("$31.00", 31.0, 92.0, height=0.8)

    result = discover_statement(_document(_page(1, words, candidate_glyphs)))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_raw_identical_overlay_with_swapped_glyph_word_associations_remains_fatal() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("Total", 20.0, 55.0, 80.0),
        _word("03/02/2026", 70.0, 105.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
        _word("₪30.00", 20.0, 55.0, 92.0, height=0.8),
        _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
        _word("Total", 118.0, 155.0, 92.0, height=0.8),
    )
    glyphs = (
        *_ltr_glyphs("Total", 21.0, 80.0, height=0.8),
        *_ltr_glyphs("03/02/2026", 71.0, 80.0, height=0.8),
        *_ltr_glyphs("₪30.00", 119.0, 80.0, height=0.8),
        *_ltr_glyphs("03/02/2026", 21.0, 92.0, height=0.8),
        *_ltr_glyphs("₪30.00", 71.0, 92.0, height=0.8),
        *_ltr_glyphs("Total", 119.0, 92.0, height=0.8),
    )

    result = discover_statement(_document(_page(1, words, glyphs)))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_raw_identical_overlay_with_same_baseline_outside_word_glyph_remains_fatal() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("Total", 30.0, 65.0, 80.0),
        _word("03/02/2026", 70.0, 105.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
        _word("₪30.00", 30.0, 65.0, 92.0, height=0.8),
        _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
        _word("Total", 118.0, 155.0, 92.0, height=0.8),
    )
    outside_word_union = _ltr_glyphs("$", 156.0, 92.0, height=0.8)

    result = discover_statement(_document(_page(1, words, outside_word_union)))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_raw_identical_overlay_with_orphan_glyph_provenance_remains_fatal() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("Total", 30.0, 65.0, 80.0),
        _word("03/02/2026", 70.0, 105.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
        _word("₪30.00", 30.0, 65.0, 92.0, height=0.8),
        _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
        _word("Total", 118.0, 155.0, 92.0, height=0.8),
    )
    orphan = _ltr_glyphs("9", 67.0, 92.0, height=0.8)

    result = discover_statement(_document(_page(1, words, orphan)))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_overlay_ignores_only_normalization_empty_orphan_spacing_glyphs() -> None:
    words = (
        *_table(20.0, "₪", "10.00", "20.00"),
        _word("Total", 30.0, 65.0, 80.0),
        _word("03/02/2026", 70.0, 105.0, 80.0),
        _word("₪30.00", 118.0, 155.0, 80.0),
        _word("₪30.00", 30.0, 65.0, 92.0, height=0.8),
        _word("03/02/2026", 70.0, 105.0, 92.0, height=0.8),
        _word("Total", 118.0, 155.0, 92.0, height=0.8),
    )
    spacing_glyphs = (
        *_ltr_glyphs("  ", 67.0, 80.0, height=0.8),
        *_ltr_glyphs(" ", 67.0, 92.0, height=0.8),
    )

    result = discover_statement(_document(_page(1, words, spacing_glyphs)))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.rejected_total_candidates == ()
    assert result.diagnostics == ()
    assert normalize_statement(result).reconciliation.status is Status.RECONCILED


@pytest.mark.parametrize(
    ("candidate_amount", "candidate_y"),
    (
        ("$30.00", 92.0),
        ("₪03.00", 92.0),
        ("₪30.00", 140.0),
    ),
)
def test_tiny_total_overlay_without_exact_bounded_word_proof_remains_fatal(
    candidate_amount: str,
    candidate_y: float,
) -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 30.0, 65.0, 80.0),
            _word("03/02/2026", 70.0, 105.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word(candidate_amount, 30.0, 65.0, candidate_y, height=0.8),
            _word("03/02/2026", 70.0, 105.0, candidate_y, height=0.8),
            _word("Total", 118.0, 155.0, candidate_y, height=0.8),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.diagnostics == ("total_without_table",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_total_in_explicitly_points_denominated_ledger_is_not_a_monetary_candidate() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("Activity", 50.0, 95.0, 120.0),
            _word("Rewards points", 118.0, 155.0, 120.0),
            _word("Earned", 50.0, 95.0, 140.0),
            _word("1,000", 118.0, 155.0, 140.0),
            _word("Total", 50.0, 95.0, 160.0),
            _word("1,000", 118.0, 155.0, 160.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert result.rejected_total_candidates == ()
    assert result.diagnostics == ()
    assert normalize_statement(result).reconciliation.status is Status.RECONCILED


def test_points_marker_outside_bounded_section_does_not_exempt_later_ambiguous_total() -> None:
    page = _page(
        1,
        (
            _word("Rewards points", 118.0, 155.0, 10.0),
            _word("Earned", 50.0, 95.0, 25.0),
            _word("1,000", 118.0, 155.0, 25.0),
            *_table(40.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 100.0),
            _word("₪30.00", 118.0, 155.0, 100.0),
            _word("Total", 50.0, 95.0, 130.0),
            _word("30.00", 102.0, 125.0, 130.0),
            _word("31.00", 130.0, 155.0, 130.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert len(result.rejected_total_candidates) == 1
    assert "ambiguous_total_value" in result.diagnostics
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_points_ledger_does_not_exempt_total_after_intervening_financial_table() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("Activity", 50.0, 95.0, 110.0),
            _word("Rewards points", 85.0, 155.0, 110.0),
            _word("Earned", 50.0, 95.0, 125.0),
            _word("1,000", 118.0, 155.0, 125.0),
            *_table(145.0, "₪", "5.00", "7.00"),
            _word("Total", 45.0, 80.0, 205.0),
            _word("1,200", 90.0, 115.0, 205.0),
            _word("1,300", 125.0, 155.0, 205.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.table_regions) == 2
    assert len(result.rejected_total_candidates) == 1
    assert "ambiguous_total_value" in result.diagnostics
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_unclaimed_detected_table_region_is_always_reconciliation_fatal() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            *_table(120.0, "₪", "5.00", "7.00"),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert len(result.table_regions) == 2
    assert result.diagnostics == ("unclaimed_table_region",)
    assert normalize_statement(result).reconciliation.status is Status.UNRECONCILED


def test_rejected_total_marker_remains_fatal_when_a_table_is_unclaimed() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            *_table(120.0, "₪", "5.00", "7.00"),
            _word("Total", 45.0, 80.0, 180.0),
            _word("12.00", 100.0, 125.0, 180.0),
            _word("13.00", 130.0, 155.0, 180.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert len(result.table_regions) == 2
    assert "ambiguous_total_value" in result.diagnostics
    assert len(result.rejected_total_candidates) == 1


def test_second_valid_total_candidate_still_blocks_a_fully_claimed_table() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
            _word("Total", 50.0, 95.0, 100.0),
            _word("₪30.00", 118.0, 155.0, 100.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert "total_without_table" in result.diagnostics
    assert result.rejected_total_candidates == ()


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


def test_discover_statement_retains_unique_full_date_year_with_exact_provenance() -> None:
    page = _page(
        1,
        (
            _word("Cycle 03/02/26", 100.0, 155.0, 5.0),
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2026
    assert result.date_year_context.style is DateTokenStyle.DAY_FIRST_SLASH
    assert tuple(item.raw_text for item in result.date_year_context.evidence) == (
        "01/02/2026",
        "02/02/2026",
    )


def test_discover_statement_does_not_choose_a_year_when_full_dates_disagree() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[6] = _word("02/02/2025", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Cycle 03/02/26", 100.0, 155.0, 5.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is None


def test_discover_statement_ignores_implausible_year_in_date_shaped_identifier() -> None:
    page = _page(
        1,
        (
            _word("Reference 1234-01-02", 0.0, 45.0, 5.0),
            _word("Cycle 03/02/26", 100.0, 155.0, 5.0),
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2026


def test_discover_statement_requires_a_matching_short_date_style_for_year_context() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is None


def test_discover_statement_preserves_year_first_dash_context_for_matching_style() -> None:
    page = _page(
        1,
        (
            _word("Period 2026-02-01", 0.0, 45.0, 5.0),
            _word("Cycle 26-02-03", 100.0, 155.0, 5.0),
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2026
    assert result.date_year_context.style is DateTokenStyle.YEAR_FIRST_DASH


def test_discover_statement_matches_stable_table_suffix_to_one_full_year_anchor() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/26", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/26", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Prior terms 01/01/2025", 0.0, 70.0, 2.0),
            _word("Cycle closes 03/02/2026", 80.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2026
    assert result.date_year_context.style is DateTokenStyle.DAY_FIRST_SLASH
    assert tuple(item.raw_text for item in result.date_year_context.evidence) == (
        "Cycle closes 03/02/2026",
    )


def test_discover_statement_infers_missing_suffix_year_from_unique_adjacent_bracket() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/25", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Prior 03/02/2024", 0.0, 70.0, 2.0),
            _word("Next 03/02/2026", 80.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2025
    assert result.date_year_context.style is DateTokenStyle.DAY_FIRST_SLASH
    assert result.date_year_context.year_by_suffix == ((25, 2025),)
    assert tuple(item.raw_text for item in result.date_year_context.evidence) == (
        "Prior 03/02/2024",
        "Next 03/02/2026",
    )


def test_discover_statement_rejects_adjacent_brackets_in_two_centuries() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/25", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Archive start 03/02/1924", 0.0, 70.0, 2.0),
            _word("Archive end 03/02/1926", 80.0, 155.0, 2.0),
            _word("Prior 03/02/2024", 0.0, 70.0, 12.0),
            _word("Next 03/02/2026", 80.0, 155.0, 12.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    assert discover_statement(_document(page)).date_year_context is None


@pytest.mark.parametrize(
    ("direct_anchor", "prior_anchor", "next_anchor"),
    (
        ("Direct 03/02/1925", "Prior 03/02/2024", "Next 03/02/2026"),
        ("Direct 03/02/2025", "Prior 03/02/1924", "Next 03/02/1926"),
    ),
)
def test_discover_statement_rejects_direct_suffix_anchor_conflicting_with_other_century_bracket(
    direct_anchor: str,
    prior_anchor: str,
    next_anchor: str,
) -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/25", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word(direct_anchor, 0.0, 45.0, 2.0),
            _word(prior_anchor, 55.0, 100.0, 2.0),
            _word(next_anchor, 110.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    assert discover_statement(_document(page)).date_year_context is None


def test_discover_statement_preserves_direct_and_bracket_evidence_for_same_year() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/25", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Direct 03/02/2025", 0.0, 45.0, 2.0),
            _word("Prior 03/02/2024", 55.0, 100.0, 2.0),
            _word("Next 03/02/2026", 110.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year == 2025
    assert result.date_year_context.year_by_suffix == ((25, 2025),)
    assert tuple(item.raw_text for item in result.date_year_context.evidence) == (
        "Direct 03/02/2025",
        "Prior 03/02/2024",
        "Next 03/02/2026",
    )


@pytest.mark.parametrize(
    "anchor",
    (
        "Only prior 03/02/2024",
        "Remote 03/02/2022",
    ),
)
def test_discover_statement_rejects_one_sided_or_remote_year_anchor(anchor: str) -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/25", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word(anchor, 0.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    assert discover_statement(_document(page)).date_year_context is None


def test_discover_statement_rejects_multiple_full_years_matching_table_suffix() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/26", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/26", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Archive 03/02/1926", 0.0, 70.0, 2.0),
            _word("Cycle 03/02/2026", 80.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is None


def test_discover_statement_preserves_bijective_table_suffix_year_mapping() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/26", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Prior 03/02/2025", 0.0, 70.0, 2.0),
            _word("Cycle 03/02/2026", 80.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is not None
    assert result.date_year_context.year is None
    assert result.date_year_context.style is DateTokenStyle.DAY_FIRST_SLASH
    assert result.date_year_context.year_by_suffix == ((25, 2025), (26, 2026))
    assert tuple(item.raw_text for item in result.date_year_context.evidence) == (
        "Prior 03/02/2025",
        "Cycle 03/02/2026",
    )


def test_discover_statement_rejects_incomplete_table_suffix_year_mapping() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/26", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/25", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Cycle 03/02/2026", 80.0, 155.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is None


def test_discover_statement_rejects_table_suffix_without_matching_full_year() -> None:
    words = list(_table(20.0, "₪", "10.00", "20.00"))
    words[3] = _word("01/02/26", 0.0, 28.0, 40.0)
    words[6] = _word("02/02/26", 0.0, 28.0, 60.0)
    page = _page(
        1,
        (
            _word("Prior terms 03/02/2025", 0.0, 70.0, 2.0),
            *words,
            _word("Total", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.date_year_context is None


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


def test_discover_statement_recognizes_compact_hebrew_total_label_prefix() -> None:
    page = _page(
        1,
        (
            *_table(20.0, "₪", "10.00", "20.00"),
            _word("סה״כלתאריך", 50.0, 95.0, 80.0),
            _word("₪30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1


def test_discover_statement_infers_numeric_total_currency_from_billed_amount_header() -> None:
    page = _page(
        1,
        (
            _word("Date", 0.0, 28.0, 20.0),
            _word("Description", 50.0, 95.0, 20.0),
            _word("Billed amount (ILS)", 110.0, 155.0, 20.0),
            _word("01/02/2026", 0.0, 28.0, 40.0),
            _word("Market", 50.0, 95.0, 40.0),
            _word("10.00", 118.0, 155.0, 40.0),
            _word("02/02/2026", 0.0, 28.0, 60.0),
            _word("Cafe", 50.0, 95.0, 60.0),
            _word("20.00", 118.0, 155.0, 60.0),
            _word("Total", 50.0, 95.0, 80.0),
            _word("30.00", 118.0, 155.0, 80.0),
        ),
    )

    result = discover_statement(_document(page))

    assert result.classification is DocumentClassification.STATEMENT
    assert result.groups[0].printed_total.currency == "ILS"
    assert result.groups[0].printed_total.amount_text == "30.00"


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
    first_page = _page(1, _table(190.0, "₪", "10.00", "20.00"))
    second_page = _page(
        2,
        (
            *_table(10.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 70.0),
            _word("₪42.00", 118.0, 155.0, 70.0),
        ),
    )

    result = discover_statement(_document(first_page, second_page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert tuple(region.page_number for region in result.groups[0].table_regions) == (1, 2)


def test_consecutive_page_continuation_accepts_semantic_header_wording_variants() -> None:
    first_page = _page(
        1,
        (
            _word("Transaction date", 0.0, 28.0, 190.0),
            _word("Merchant", 50.0, 95.0, 190.0),
            _word("Billed amount", 118.0, 155.0, 190.0),
            *_table(190.0, "₪", "10.00", "20.00")[3:],
        ),
    )
    second_page = _page(
        2,
        (
            *_table(10.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 70.0),
            _word("₪42.00", 118.0, 155.0, 70.0),
        ),
    )

    result = discover_statement(_document(first_page, second_page))

    assert result.classification is DocumentClassification.STATEMENT
    assert len(result.groups) == 1
    assert tuple(region.page_number for region in result.groups[0].table_regions) == (1, 2)


def test_consecutive_tables_with_two_later_totals_do_not_collapse_into_chain() -> None:
    first_page = _page(1, _table(190.0, "₪", "10.00", "20.00"))
    second_page = _page(
        2,
        (
            *_table(10.0, "₪", "5.00", "7.00"),
            _word("Total", 50.0, 95.0, 70.0),
            _word("₪30.00", 118.0, 155.0, 70.0),
            _word("Total", 50.0, 95.0, 90.0),
            _word("₪12.00", 118.0, 155.0, 90.0),
        ),
    )

    result = discover_statement(_document(first_page, second_page))

    assert result.classification is DocumentClassification.AMBIGUOUS
    assert result.groups == ()
    assert "ambiguous_group_region_association" in result.diagnostics
