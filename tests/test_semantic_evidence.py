from __future__ import annotations

from ccparser.evidence import Glyph, Word
from ccparser.layout import Cell, Row
from ccparser.semantic_evidence import EvidenceClaim, EvidenceLedger, SemanticOwner


def _glyph(char: str, x0: float, y: float = 20.0) -> Glyph:
    return Glyph(
        char=char,
        bbox=(x0, y, x0 + 0.8, y + 10.0),
        origin=(x0, y + 9.0),
        font="Synthetic",
        size=10.0,
        source="digital",
        confidence=1.0,
    )


def _word(text: str, x0: float, x1: float, y: float = 20.0) -> Word:
    return Word(
        text=text,
        bbox=(x0, y, x1, y + 10.0),
        source="digital",
        confidence=1.0,
    )


def _cell(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    glyphs: tuple[Glyph, ...] = (),
    words: tuple[Word, ...] = (),
) -> Cell:
    return Cell(
        page_number=1,
        bbox=bbox,
        text=text,
        glyphs=glyphs,
        words=words,
        confidence=1.0,
    )


def _row(*cells: Cell) -> Row:
    return Row(
        page_number=1,
        bbox=(
            min(cell.bbox[0] for cell in cells),
            min(cell.bbox[1] for cell in cells),
            max(cell.bbox[2] for cell in cells),
            max(cell.bbox[3] for cell in cells),
        ),
        cells=cells,
        confidence=1.0,
    )


def test_ledger_deduplicates_overlapping_source_glyphs() -> None:
    glyphs = (_glyph("A", 10.0), _glyph("B", 11.0))
    first = _cell("AB", (10.0, 20.0, 20.0, 30.0), glyphs=glyphs)
    duplicate = _cell("AB", (10.0, 20.0, 20.0, 30.0), glyphs=glyphs)

    ledger = EvidenceLedger.from_rows((_row(first, duplicate),))

    assert tuple(atom.text for atom in ledger.atoms) == ("A", "B")
    assert ledger.atoms_for_cell(first) == ledger.atoms_for_cell(duplicate)


def test_ledger_uses_words_then_cell_text_as_evidence_fallbacks() -> None:
    word_cell = _cell(
        "First Merchant",
        (10.0, 20.0, 80.0, 30.0),
        words=(_word("First", 10.0, 30.0), _word("Merchant", 35.0, 70.0)),
    )
    text_cell = _cell("Fallback", (90.0, 20.0, 130.0, 30.0))

    ledger = EvidenceLedger.from_rows((_row(word_cell, text_cell),))

    assert tuple(atom.text for atom in ledger.atoms) == ("First", "Merchant", "Fallback")
    assert ledger.render(ledger.atoms_for_cell(word_cell)) == "First Merchant"
    assert ledger.render(ledger.atoms_for_cell(text_cell)) == "Fallback"


def test_claim_validation_reports_conflicts_and_meaningful_unclaimed_atoms() -> None:
    merchant = _cell("Merchant", (10.0, 20.0, 60.0, 30.0))
    punctuation = _cell(".", (70.0, 20.0, 72.0, 30.0))
    ledger = EvidenceLedger.from_rows((_row(merchant, punctuation),))
    merchant_ids = ledger.atoms_for_cell(merchant)

    unclaimed = ledger.validate_claims(())
    conflicting = ledger.validate_claims(
        (
            EvidenceClaim(SemanticOwner.DESCRIPTION, merchant_ids),
            EvidenceClaim(SemanticOwner.CATEGORY, merchant_ids),
        )
    )

    assert unclaimed.unclaimed_atom_ids == merchant_ids
    assert unclaimed.diagnostics == ()
    assert conflicting.diagnostics == ("conflicting_semantic_evidence_claim",)


def test_render_uses_selected_glyphs_and_word_boxes_to_restore_spaces() -> None:
    first_text = "BACKBLAZE"
    second_text = "INC"
    first_glyphs = tuple(_glyph(char, 10.0 + index) for index, char in enumerate(first_text))
    second_glyphs = tuple(_glyph(char, 22.0 + index) for index, char in enumerate(second_text))
    cell = _cell(
        "BACKBLAZEINC",
        (10.0, 20.0, 30.0, 30.0),
        glyphs=(*first_glyphs, *second_glyphs),
        words=(_word(first_text, 10.0, 19.0), _word(second_text, 22.0, 25.0)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.render(ledger.atoms_for_cell(cell)) == "BACKBLAZE INC"


def test_render_preserves_standalone_hyphen_word_boundaries() -> None:
    text = "HEALTH-INSURANCE"
    cell = _cell(
        "HEALTH - INSURANCE",
        (10.0, 20.0, 50.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
        words=(
            _word("HEALTH", 10.0, 15.8),
            _word("-", 16.0, 16.8),
            _word("INSURANCE", 17.0, 25.8),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.render(ledger.atoms_for_cell(cell)) == "HEALTH - INSURANCE"


def _fragmented_date_cell(logical_text: str, physical_text: str) -> Cell:
    glyphs = tuple(_glyph(char, 10.0 + index) for index, char in enumerate(physical_text))
    return _cell(logical_text, (10.0, 20.0, 70.0, 30.0), glyphs=glyphs)


def test_fragmented_date_candidates_follow_physical_digit_geometry() -> None:
    first = _fragmented_date_cell(". ב 8/0 6/2 6 - לא", "אל8/06/26 -ב .")
    second = _fragmented_date_cell(". ב 2 5/0 6/2 6 - לא", "אל25/06/26 -ב .")
    first_ledger = EvidenceLedger.from_rows((_row(first),))
    second_ledger = EvidenceLedger.from_rows((_row(second),))

    first_candidates = first_ledger.fragmented_date_candidates(first)
    second_candidates = second_ledger.fragmented_date_candidates(second)

    assert tuple(candidate.text for candidate in first_candidates) == ("8/06/26",)
    assert tuple(candidate.text for candidate in second_candidates) == ("25/06/26",)
    assert all(candidate.atom_ids for candidate in (*first_candidates, *second_candidates))


def test_fragmented_date_candidates_reject_inconsistent_separators_and_large_gaps() -> None:
    inconsistent = _fragmented_date_cell("25/06-26", "25/06-26")
    separated_glyphs = (
        *tuple(_glyph(char, 10.0 + index) for index, char in enumerate("25/")),
        *tuple(_glyph(char, 40.0 + index) for index, char in enumerate("06/26")),
    )
    separated = _cell(
        "25/ 06/26",
        (10.0, 20.0, 60.0, 30.0),
        glyphs=separated_glyphs,
    )

    inconsistent_ledger = EvidenceLedger.from_rows((_row(inconsistent),))
    separated_ledger = EvidenceLedger.from_rows((_row(separated),))

    assert inconsistent_ledger.fragmented_date_candidates(inconsistent) == ()
    assert separated_ledger.fragmented_date_candidates(separated) == ()


def test_fragmented_date_candidates_preserve_multiple_candidates_for_validation() -> None:
    cell = _fragmented_date_cell("8/06/26 9/06/26", "8/06/26 9/06/26")
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(candidate.text for candidate in ledger.fragmented_date_candidates(cell)) == (
        "8/06/26",
        "9/06/26",
    )


def test_fragmented_date_candidates_tolerate_same_line_vertical_jitter() -> None:
    glyphs = tuple(
        _glyph(char, 10.0 + index, 20.0 + (0.15 if index % 2 else 0.0))
        for index, char in enumerate("25/06/26")
    )
    cell = _cell("25/06/26", (10.0, 20.0, 30.0, 31.0), glyphs=glyphs)
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(candidate.text for candidate in ledger.fragmented_date_candidates(cell)) == (
        "25/06/26",
    )


def _fragmented_decimal_cell(
    logical_text: str,
    first_fragment: str,
    second_fragment: str,
    *,
    fragment_gap: float,
) -> Cell:
    first_glyphs = tuple(_glyph(char, 10.0 + index) for index, char in enumerate(first_fragment))
    second_x = first_glyphs[-1].bbox[2] + fragment_gap
    second_glyphs = tuple(
        _glyph(char, second_x + index) for index, char in enumerate(second_fragment)
    )
    return _cell(
        logical_text,
        (10.0, 20.0, second_glyphs[-1].bbox[2], 30.0),
        glyphs=(*first_glyphs, *second_glyphs),
    )


def test_positioned_decimal_candidates_join_only_small_numeric_gaps() -> None:
    cell = _fragmented_decimal_cell(
        "rate 2.94 30",
        "2.94",
        "30",
        fragment_gap=0.2,
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

    assert tuple(candidate.text for candidate in candidates) == ("2.9430",)


def test_positioned_decimal_candidates_ignore_adjacent_sentence_punctuation() -> None:
    physical_text = ".2.9430"
    cell = _cell(
        "exchange rate 2.9430",
        (10.0, 20.0, 30.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(physical_text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

    assert tuple(candidate.text for candidate in candidates) == ("2.9430",)


def test_positioned_decimal_candidates_exclude_claimed_date_atoms() -> None:
    physical_text = "22/06/26 2.9660"
    cell = _cell(
        physical_text,
        (10.0, 20.0, 50.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(physical_text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    date_ids = frozenset(
        atom_id
        for candidate in ledger.fragmented_date_candidates(cell)
        for atom_id in candidate.atom_ids
    )

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell) - date_ids)

    assert tuple(candidate.text for candidate in candidates) == ("2.9660",)


def test_positioned_decimal_candidates_do_not_join_material_gaps() -> None:
    cell = _fragmented_decimal_cell(
        "2.94 30",
        "2.94",
        "30",
        fragment_gap=8.0,
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

    assert tuple(candidate.text for candidate in candidates) == ("2.94",)


def test_positioned_decimal_candidates_preserve_distinct_physical_runs() -> None:
    cell = _fragmented_decimal_cell(
        "2.94 3.10",
        "2.94",
        "3.10",
        fragment_gap=8.0,
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

    assert tuple(candidate.text for candidate in candidates) == ("2.94", "3.10")


def test_positioned_decimal_candidates_require_positioned_evidence() -> None:
    cell = _cell("2.9430", (10.0, 20.0, 50.0, 30.0))
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()
