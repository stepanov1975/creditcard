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
