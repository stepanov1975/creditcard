from __future__ import annotations

import re
from dataclasses import FrozenInstanceError, fields

import pytest

import ccparser.semantic_evidence as semantic_evidence
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


def test_word_date_policy_delegates_numeric_run_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int]] = []

    def reject_numeric_run(text: str, start: int, end: int) -> bool:
        calls.append((text, start, end))
        return False

    monkeypatch.setattr(
        semantic_evidence,
        "has_date_numeric_run_boundaries",
        reject_numeric_run,
    )
    pattern = re.compile(r"\d{2}/\d{2}/\d{2}")

    assert semantic_evidence._wrapped_word_date("(25/06/26)", pattern) is None
    assert calls == [("(25/06/26)", 1, 9)]


def test_word_match_span_owns_cardinality_and_hard_boundary_clipping() -> None:
    pattern = re.compile(r"\d{2}/\d{2}/\d{2}")

    isolated = semantic_evidence._word_match_span(
        "label:(25/06/26),tail",
        pattern,
    )

    assert isolated is not None
    match, prefix, suffix = isolated
    assert (match.group(0), match.span(), prefix, suffix) == (
        "25/06/26",
        (7, 15),
        "(",
        ")",
    )
    assert semantic_evidence._word_match_span("25/06/26 26/06/26", pattern) is None


def test_touching_word_span_text_reconstructs_prefix_candidate_and_suffix_once() -> None:
    cell = _cell(
        "ref25/06/26x",
        (10.0, 20.0, 40.0, 30.0),
        words=(
            _word("ref", 10.0, 13.2),
            _word("25/06/26", 13.0, 30.0),
            _word("x", 29.8, 31.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    word_atoms = tuple(atom for atom in ledger.atoms if atom.word is not None)
    candidate = next(atom for atom in word_atoms if atom.text == "25/06/26")

    assert (
        semantic_evidence._touching_word_span_text(
            candidate,
            word_atoms,
            logical_texts=(cell.text,),
        )
        == cell.text
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


@pytest.mark.parametrize(
    ("logical_text", "residual_words"),
    (("6", ("6",)), ("6 7", ("6", "7"))),
)
def test_ledger_preserves_words_for_unique_ordered_logical_subset(
    logical_text: str,
    residual_words: tuple[str, ...],
) -> None:
    words = (
        _word("25/07/26", 10.0, 30.0),
        *tuple(
            _word(text, 40.0 + index * 10.0, 45.0 + index * 10.0)
            for index, text in enumerate(residual_words)
        ),
    )
    cell = _cell(logical_text, (10.0, 20.0, 80.0, 30.0), words=words)

    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(ledger.atoms[atom_id].text for atom_id in sorted(ledger.atoms_for_cell(cell))) == (
        "25/07/26",
        *residual_words,
    )
    assert all(ledger.atoms[atom_id].word is not None for atom_id in ledger.atoms_for_cell(cell))


@pytest.mark.parametrize(
    ("logical_text", "physical_words"),
    (("6 7", ("25/07/26", "7", "6")), ("6", ("25/07/26", "6", "6"))),
)
def test_ledger_rejects_permuted_or_ambiguous_logical_word_subset(
    logical_text: str,
    physical_words: tuple[str, ...],
) -> None:
    cell = _cell(
        logical_text,
        (10.0, 20.0, 80.0, 30.0),
        words=tuple(
            _word(text, 10.0 + index * 15.0, 20.0 + index * 15.0)
            for index, text in enumerate(physical_words)
        ),
    )

    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(ledger.atoms[atom_id].text for atom_id in ledger.atoms_for_cell(cell)) == (
        logical_text,
    )
    assert all(ledger.atoms[atom_id].word is None for atom_id in ledger.atoms_for_cell(cell))


def test_ledger_preserves_positioned_word_when_logical_text_only_adds_directional_mark() -> None:
    cell = _cell(
        "25/07/26\u200e",
        (10.0, 20.0, 40.0, 30.0),
        words=(_word("25/07/26", 10.0, 40.0),),
    )

    ledger = EvidenceLedger.from_rows((_row(cell),))

    atom_ids = ledger.atoms_for_cell(cell)
    assert tuple(ledger.atoms[atom_id].text for atom_id in atom_ids) == ("25/07/26",)
    assert all(ledger.atoms[atom_id].word is not None for atom_id in atom_ids)


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


def test_hebrew_reorder_exception_requires_hebrew_offending_boundary() -> None:
    cell = _fragmented_date_cell("בא 26/06/25x", "x25/06/26אב")
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


def test_glyph_backed_date_candidates_reject_logical_alphanumeric_embedding() -> None:
    cell = _fragmented_date_cell(
        "Converted on ref25/06/26x",
        "Converted on ref25/06/26x",
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


@pytest.mark.parametrize(
    "numeric_run",
    (
        "1.25/06/26",
        "25/06/26.1",
        "1-25/06/26",
        "25/06/26-1",
        "1..25/06/26",
        "1.-25/06/26",
        "25/06/26..1",
        "25/06/26-.1",
    ),
)
def test_glyph_backed_date_candidates_reject_larger_numeric_runs(
    numeric_run: str,
) -> None:
    cell = _fragmented_date_cell(numeric_run, numeric_run)
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


def test_glyph_date_boundaries_reject_slightly_overlapping_neighbors() -> None:
    date_glyphs = tuple(_glyph(char, 11.0 + index) for index, char in enumerate("25/06/26"))
    prefix = _glyph("x", 10.0).model_copy(update={"bbox": (10.0, 20.0, 11.2, 30.0)})
    suffix = _glyph("x", 19.6).model_copy(update={"bbox": (19.6, 20.0, 20.8, 30.0)})
    prefix_cell = _cell(
        "x25/06/26",
        (10.0, 20.0, 20.0, 30.0),
        glyphs=(prefix, *date_glyphs),
    )
    suffix_cell = _cell(
        "25/06/26x",
        (30.0, 20.0, 40.0, 30.0),
        glyphs=(
            *tuple(_glyph(char, 30.0 + index) for index, char in enumerate("25/06/26")),
            suffix.model_copy(update={"bbox": (37.6, 20.0, 38.8, 30.0)}),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(prefix_cell, suffix_cell),))

    assert ledger.fragmented_date_candidates(prefix_cell) == ()
    assert ledger.fragmented_date_candidates(suffix_cell) == ()


def test_glyph_date_boundaries_are_checked_per_physical_occurrence() -> None:
    cell = _fragmented_date_cell(
        "ref25/06/26x 25/06/26",
        "ref25/06/26x 25/06/26",
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.fragmented_date_candidates(cell)

    assert len(candidates) == 1
    assert candidates[0].text == "25/06/26"


def test_glyph_date_boundaries_do_not_trust_unrelated_logical_text() -> None:
    cell = _fragmented_date_cell("unrelated logical text", "ref25/06/26x")
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


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


def test_positioned_number_orchestrator_preserves_backing_order_and_exact_atom_ids() -> None:
    word_only = _cell(
        "1.10",
        (10.0, 20.0, 25.0, 30.0),
        words=(_word("1.10", 10.0, 25.0),),
    )
    glyph_only = _cell(
        "2.20",
        (40.0, 20.0, 55.0, 30.0),
        glyphs=tuple(_glyph(char, 40.0 + index) for index, char in enumerate("2.20")),
    )
    overlapping_word = _cell(
        "3.30",
        (70.0, 20.0, 85.0, 30.0),
        words=(_word("3.30", 70.0, 85.0),),
    )
    overlapping_glyph = _cell(
        "3.30",
        (70.0, 20.0, 85.0, 30.0),
        glyphs=tuple(_glyph(char, 70.0 + index) for index, char in enumerate("3.30")),
    )
    ledger = EvidenceLedger.from_rows(
        (_row(word_only, glyph_only, overlapping_word, overlapping_glyph),)
    )
    selected_ids = frozenset(atom.atom_id for atom in ledger.atoms)

    candidates = ledger.positioned_decimal_candidates(selected_ids)

    assert tuple((candidate.text, candidate.atom_ids) for candidate in candidates) == (
        ("1.10", ledger.atoms_for_cell(word_only)),
        ("2.20", ledger.atoms_for_cell(glyph_only)),
        (
            "3.30",
            ledger.atoms_for_cell(overlapping_word) | ledger.atoms_for_cell(overlapping_glyph),
        ),
    )


def test_positioned_number_orchestrator_delegates_word_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = _cell(
        "2.9430",
        (10.0, 20.0, 30.0, 30.0),
        words=(_word("2.9430", 10.0, 30.0),),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    selected_ids = ledger.atoms_for_cell(cell)
    calls: list[tuple[frozenset[int], str]] = []

    def collect(
        self: EvidenceLedger,
        atom_ids: frozenset[int],
        *,
        pattern: re.Pattern[str],
    ) -> tuple[semantic_evidence.PositionedNumberCandidate, ...]:
        calls.append((atom_ids, pattern.pattern))
        return ()

    monkeypatch.setattr(
        EvidenceLedger,
        "_collect_validated_word_number_candidates",
        collect,
    )

    assert ledger.positioned_decimal_candidates(selected_ids) == ()
    assert calls == [(selected_ids, r"\d+[.,]\d{1,6}")]


def test_positioned_number_glyph_view_is_immutable_and_preserves_whitespace() -> None:
    text = "1 2.30"
    cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    view = ledger._positioned_number_glyph_view(ledger.atoms_for_cell(cell))

    assert tuple(field.name for field in fields(view)) == (
        "selected_atoms",
        "whitespace_glyphs",
    )
    assert tuple(atom.text for atom in view.selected_atoms) == ("1", "2", ".", "3", "0")
    assert tuple((page, glyph.char) for page, glyph in view.whitespace_glyphs) == ((1, " "),)
    with pytest.raises(FrozenInstanceError):
        view.selected_atoms = ()


def test_positioned_number_orchestrator_delegates_glyph_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "2.9430"
    cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    selected_ids = ledger.atoms_for_cell(cell)
    calls: list[tuple[frozenset[int], str, tuple[int, ...]]] = []

    def collect(
        self: EvidenceLedger,
        atom_ids: frozenset[int],
        *,
        pattern: re.Pattern[str],
        view: semantic_evidence._PositionedNumberGlyphView,
    ) -> tuple[semantic_evidence.PositionedNumberCandidate, ...]:
        calls.append(
            (
                atom_ids,
                pattern.pattern,
                tuple(atom.atom_id for atom in view.selected_atoms),
            )
        )
        return ()

    monkeypatch.setattr(
        EvidenceLedger,
        "_collect_validated_glyph_number_candidates",
        collect,
    )

    assert ledger.positioned_decimal_candidates(selected_ids) == ()
    assert calls == [(selected_ids, r"\d+[.,]\d{1,6}", tuple(sorted(selected_ids)))]


def test_positioned_number_orchestrator_delegates_stable_coalescing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = _cell(
        "2.9430",
        (10.0, 20.0, 30.0, 30.0),
        words=(_word("2.9430", 10.0, 30.0),),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    selected_ids = ledger.atoms_for_cell(cell)
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def coalesce(
        self: EvidenceLedger,
        atom_ids: frozenset[int],
        word_candidates: tuple[semantic_evidence.PositionedNumberCandidate, ...],
        glyph_candidates: tuple[semantic_evidence.PositionedNumberCandidate, ...],
        *,
        glyph_view: semantic_evidence._PositionedNumberGlyphView,
    ) -> tuple[semantic_evidence.PositionedNumberCandidate, ...]:
        assert atom_ids == selected_ids
        assert glyph_view.selected_atoms == ()
        calls.append(
            (
                tuple(candidate.text for candidate in word_candidates),
                tuple(candidate.text for candidate in glyph_candidates),
            )
        )
        return (semantic_evidence.PositionedNumberCandidate("9.99", frozenset()),)

    monkeypatch.setattr(
        EvidenceLedger,
        "_coalesce_positioned_number_candidates",
        coalesce,
    )

    assert tuple(
        candidate.text for candidate in ledger.positioned_decimal_candidates(selected_ids)
    ) == ("9.99",)
    assert calls == [(("2.9430",), ())]


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


@pytest.mark.parametrize("delimiter", (":", ";", ",", "="))
def test_glyph_decimal_hard_delimiter_terminates_adjacent_label(delimiter: str) -> None:
    physical_text = f"rate{delimiter}2.9430"
    cell = _cell(
        physical_text,
        (10.0, 20.0, 40.0, 30.0),
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


def test_positioned_decimal_candidates_preserve_unselected_whitespace_boundaries() -> None:
    physical_text = "32/06/26 2.9660"
    cell = _cell(
        physical_text,
        (10.0, 20.0, 50.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(physical_text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))

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


def test_word_backed_date_and_decimal_candidates_preserve_exact_atom_ownership() -> None:
    date_word = _word("22/06/26", 10.0, 30.0)
    rate_word = _word("2.9660", 35.0, 50.0)
    cell = _cell(
        "22/06/26 2.9660",
        (10.0, 20.0, 50.0, 30.0),
        words=(date_word, rate_word),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    atom_id_by_text = {atom.text: atom.atom_id for atom in ledger.atoms}

    date_candidates = ledger.fragmented_date_candidates(cell)
    assert tuple((candidate.text, candidate.atom_ids) for candidate in date_candidates) == (
        ("22/06/26", frozenset((atom_id_by_text["22/06/26"],))),
    )

    date_atom_ids = date_candidates[0].atom_ids
    decimal_candidates = ledger.positioned_decimal_candidates(
        ledger.atoms_for_cell(cell) - date_atom_ids
    )
    assert tuple((candidate.text, candidate.atom_ids) for candidate in decimal_candidates) == (
        ("2.9660", frozenset((atom_id_by_text["2.9660"],))),
    )


def test_word_backed_candidates_reject_embedded_numeric_substrings() -> None:
    date_cell = _cell(
        "ref22/06/26x",
        (10.0, 20.0, 40.0, 30.0),
        words=(_word("ref22/06/26x", 10.0, 40.0),),
    )
    decimal_cell = _cell(
        "v2.9660x 1'234.56",
        (45.0, 20.0, 95.0, 30.0),
        words=(
            _word("v2.9660x", 45.0, 65.0),
            _word("1'234.56", 70.0, 95.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(date_cell, decimal_cell),))

    assert ledger.fragmented_date_candidates(date_cell) == ()
    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(decimal_cell)) == ()


def test_word_backed_date_rejects_touching_alphanumeric_neighbors() -> None:
    cell = _cell(
        "ref25/06/26x",
        (10.0, 20.0, 40.0, 30.0),
        words=(
            _word("ref", 10.0, 13.2),
            _word("25/06/26", 13.0, 30.0),
            _word("x", 29.8, 31.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


def test_word_backed_date_allows_logically_spaced_touching_neighbor() -> None:
    cell = _cell(
        "on 25/06/26",
        (10.0, 20.0, 40.0, 30.0),
        words=(
            _word("on", 10.0, 13.0),
            _word("25/06/26", 13.0, 30.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(candidate.text for candidate in ledger.fragmented_date_candidates(cell)) == (
        "25/06/26",
    )


@pytest.mark.parametrize(
    "text",
    ("25/06/26,", "(25/06/26)", "date:25/06/26", "25/06/26;"),
)
def test_word_backed_date_accepts_semantic_wrappers_and_hard_boundaries(text: str) -> None:
    cell = _cell(text, (10.0, 20.0, 40.0, 30.0), words=(_word(text, 10.0, 40.0),))
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(candidate.text for candidate in ledger.fragmented_date_candidates(cell)) == (
        "25/06/26",
    )


@pytest.mark.parametrize(
    "text",
    ("1/25/06/26", "25/06/26/1", "1.25/06/26", "25/06/26-1"),
)
def test_word_backed_date_rejects_joined_numeric_runs(text: str) -> None:
    cell = _cell(text, (10.0, 20.0, 40.0, 30.0), words=(_word(text, 10.0, 40.0),))
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.fragmented_date_candidates(cell) == ()


def test_word_backed_decimal_rejects_touching_alphanumeric_neighbors() -> None:
    cell = _cell(
        "v2.9660x",
        (10.0, 20.0, 40.0, 30.0),
        words=(
            _word("v", 10.0, 11.2),
            _word("2.9660", 11.0, 25.0),
            _word("x", 24.8, 26.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()


def test_word_backed_decimal_allows_logically_spaced_touching_neighbor() -> None:
    cell = _cell(
        "rate 2.9660",
        (10.0, 20.0, 40.0, 30.0),
        words=(
            _word("rate", 10.0, 15.0),
            _word("2.9660", 15.0, 30.0),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(
        candidate.text
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))
    ) == ("2.9660",)


def test_word_backed_date_ignores_whitespace_only_glyph_artifacts() -> None:
    date_word = _word("22/06/26", 10.0, 30.0)
    cell = _cell(
        "22/06/26",
        (10.0, 20.0, 30.0, 30.0),
        glyphs=(_glyph(" ", 10.0),),
        words=(date_word,),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    date_atom_id = next(atom.atom_id for atom in ledger.atoms if atom.word is date_word)

    assert tuple(
        (candidate.text, candidate.atom_ids)
        for candidate in ledger.fragmented_date_candidates(cell)
    ) == (("22/06/26", frozenset((date_atom_id,))),)


def test_decimal_candidates_coalesce_overlapping_glyph_and_word_backing() -> None:
    text = "2.9660"
    glyph_cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    word_cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        words=(_word(text, 10.0, 30.0),),
    )
    ledger = EvidenceLedger.from_rows((_row(glyph_cell, word_cell),))

    candidates = ledger.positioned_decimal_candidates(
        ledger.atoms_for_cell(glyph_cell) | ledger.atoms_for_cell(word_cell)
    )

    assert len(candidates) == 1
    assert candidates[0].text == text
    assert candidates[0].atom_ids == (
        ledger.atoms_for_cell(glyph_cell) | ledger.atoms_for_cell(word_cell)
    )


def test_decimal_overlap_precedence_never_crosses_pages() -> None:
    text = "2.9660"
    word_cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        words=(_word(text, 10.0, 30.0),),
    )
    glyph_cell = _cell(
        text,
        (10.0, 20.0, 30.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    ).model_copy(update={"page_number": 2})
    second_row = Row(
        page_number=2,
        bbox=glyph_cell.bbox,
        cells=(glyph_cell,),
        confidence=1.0,
    )
    ledger = EvidenceLedger.from_rows((_row(word_cell), second_row))

    candidates = ledger.positioned_decimal_candidates(
        ledger.atoms_for_cell(word_cell) | ledger.atoms_for_cell(glyph_cell)
    )

    assert len(candidates) == 2
    assert {
        tuple(sorted(ledger.atoms[atom_id].page_number for atom_id in candidate.atom_ids))
        for candidate in candidates
    } == {(1,), (2, 2, 2, 2, 2, 2)}


def test_word_backed_decimal_candidates_preserve_typed_precision_but_reject_spaced_grouping() -> (
    None
):
    grouped_word = _cell(
        "1,234",
        (10.0, 20.0, 30.0, 30.0),
        words=(_word("1,234", 10.0, 30.0),),
    )
    split_group = _cell(
        "1 234,56",
        (35.0, 20.0, 70.0, 30.0),
        words=(_word("1", 35.0, 40.0), _word("234,56", 42.0, 70.0)),
    )
    ledger = EvidenceLedger.from_rows((_row(grouped_word, split_group),))

    assert tuple(
        candidate.text
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(grouped_word))
    ) == ("1,234",)
    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(split_group)) == ()


@pytest.mark.parametrize("text", ["1 234,56", "1 234.56"])
def test_glyph_backed_decimal_candidates_reject_spaced_grouping(text: str) -> None:
    cell = _cell(
        text,
        (10.0, 20.0, 35.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()


@pytest.mark.parametrize("text", ("1'234.56", "v234.56x", "v234.56", "234.56x"))
def test_glyph_backed_decimal_candidates_require_semantic_boundaries(text: str) -> None:
    cell = _cell(
        text,
        (10.0, 20.0, 35.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()


def test_glyph_decimal_boundaries_reject_slightly_overlapping_neighbors() -> None:
    decimal_glyphs = tuple(_glyph(char, 11.0 + index) for index, char in enumerate("2.9660"))
    prefix = _glyph("x", 10.0).model_copy(update={"bbox": (10.0, 20.0, 11.2, 30.0)})
    suffix = _glyph("x", 16.6).model_copy(update={"bbox": (16.6, 20.0, 17.8, 30.0)})
    prefix_cell = _cell(
        "x2.9660",
        (10.0, 20.0, 20.0, 30.0),
        glyphs=(prefix, *decimal_glyphs),
    )
    suffix_cell = _cell(
        "2.9660x",
        (30.0, 20.0, 40.0, 30.0),
        glyphs=(
            *tuple(_glyph(char, 30.0 + index) for index, char in enumerate("2.9660")),
            suffix.model_copy(update={"bbox": (35.6, 20.0, 36.8, 30.0)}),
        ),
    )
    ledger = EvidenceLedger.from_rows((_row(prefix_cell, suffix_cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(prefix_cell)) == ()
    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(suffix_cell)) == ()


@pytest.mark.parametrize("text", ("ILS234.56", "234.56ILS", "₪234.56"))
def test_glyph_backed_decimal_candidates_allow_currency_boundaries(text: str) -> None:
    cell = _cell(
        text,
        (10.0, 20.0, 35.0, 30.0),
        glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate(text)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(
        candidate.text
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))
    ) == ("234.56",)


@pytest.mark.parametrize(
    "text",
    ("rate:2.9660", "2.9660,", "ILS2.9660", "2.9660ILS"),
)
def test_word_backed_decimal_candidates_match_semantic_glyph_boundaries(text: str) -> None:
    word = _word(text, 10.0, 35.0)
    cell = _cell(text, (10.0, 20.0, 35.0, 30.0), words=(word,))
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert tuple(
        candidate.text
        for candidate in ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell))
    ) == ("2.9660",)


@pytest.mark.parametrize(
    "text",
    (
        "2.9660,123",
        "2.9660.123",
        "1.2.9430",
        "1..2.9660",
        "1.,2.9660",
        "2.9660..1",
        "2.9660.,1",
    ),
)
def test_word_backed_decimal_candidates_reject_joined_numeric_runs(text: str) -> None:
    word = _word(text, 10.0, 35.0)
    cell = _cell(text, (10.0, 20.0, 35.0, 30.0), words=(word,))
    ledger = EvidenceLedger.from_rows((_row(cell),))

    assert ledger.positioned_decimal_candidates(ledger.atoms_for_cell(cell)) == ()


def test_whole_number_candidates_are_a_dedicated_positioned_evidence_path() -> None:
    cell = _cell(
        "7%",
        (10.0, 20.0, 20.0, 30.0),
        glyphs=(_glyph("7", 10.0), _glyph("%", 11.0)),
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    atom_ids = ledger.atoms_for_cell(cell)

    assert ledger.positioned_decimal_candidates(atom_ids) == ()
    candidates = ledger.positioned_whole_number_candidates(atom_ids)

    assert tuple(candidate.text for candidate in candidates) == ("7",)
    assert candidates[0].atom_ids == frozenset(
        atom_id for atom_id in atom_ids if ledger.atoms[atom_id].text == "7"
    )


@pytest.mark.parametrize("backing", ("glyph", "word"))
def test_positioned_percentage_candidates_expose_numeric_and_marker_ownership(
    backing: str,
) -> None:
    cell = (
        _cell(
            "7%",
            (10.0, 20.0, 20.0, 30.0),
            glyphs=(_glyph("7", 10.0), _glyph("%", 11.0)),
        )
        if backing == "glyph"
        else _cell(
            "7%",
            (10.0, 20.0, 20.0, 30.0),
            words=(_word("7%", 10.0, 20.0),),
        )
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))
    atom_ids = ledger.atoms_for_cell(cell)

    candidates = ledger.positioned_percentage_candidates(atom_ids)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == "7"
    assert candidate.numeric_atom_ids
    assert candidate.marker_atom_ids
    assert candidate.semantic_atom_ids == (candidate.numeric_atom_ids | candidate.marker_atom_ids)
    assert candidate.semantic_atom_ids == atom_ids


@pytest.mark.parametrize("backing", ("glyph", "word"))
def test_positioned_percentage_candidates_count_adjacent_markers_consistently(
    backing: str,
) -> None:
    cell = (
        _cell(
            "3.00%%",
            (10.0, 20.0, 20.0, 30.0),
            glyphs=tuple(_glyph(char, 10.0 + index) for index, char in enumerate("3.00%%")),
        )
        if backing == "glyph"
        else _cell(
            "3.00%%",
            (10.0, 20.0, 20.0, 30.0),
            words=(_word("3.00%%", 10.0, 20.0),),
        )
    )
    ledger = EvidenceLedger.from_rows((_row(cell),))

    candidates = ledger.positioned_percentage_candidates(ledger.atoms_for_cell(cell))

    assert len(candidates) == 1
    assert candidates[0].text == "3.00"
    assert candidates[0].marker_count == 2
