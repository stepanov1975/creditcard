"""Deterministic ownership accounting for transaction-row evidence."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from ccparser.evidence.models import BBox, Glyph, Word
from ccparser.layout.models import Cell, Row
from ccparser.layout.text import logical_text_for_evidence


class SemanticOwner(StrEnum):
    """A semantic field or ancillary purpose that consumes source evidence."""

    DESCRIPTION = "description"
    TRANSACTION_DATE = "transaction_date"
    POSTING_DATE = "posting_date"
    CONVERSION_DATE = "conversion_date"
    BILLED_VALUE = "billed_value"
    ORIGINAL_VALUE = "original_value"
    INSTALLMENT = "installment"
    CATEGORY = "category"
    LOCATION = "location"
    PROCESSOR_REFERENCE = "processor_reference"
    ANCILLARY = "ancillary"
    LAYOUT_NOISE = "layout_noise"


class EvidenceAtomKind(StrEnum):
    """The source granularity used for one ledger atom."""

    GLYPH = "glyph"
    WORD = "word"
    CELL_TEXT = "cell_text"


@dataclass(frozen=True, slots=True)
class EvidenceAtom:
    """The smallest positioned unit independently assignable to a semantic owner."""

    atom_id: int
    kind: EvidenceAtomKind
    page_number: int
    bbox: BBox
    text: str
    confidence: float
    glyph: Glyph | None = None
    word: Word | None = None


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """Ownership of a set of evidence atoms by one semantic purpose."""

    owner: SemanticOwner
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class ClaimValidation:
    """Conflicts and meaningful evidence left without an owner."""

    unclaimed_atom_ids: frozenset[int]
    diagnostics: tuple[str, ...]


type _AtomKey = tuple[
    EvidenceAtomKind,
    int,
    BBox,
    tuple[float, float] | None,
    str,
    str,
]


@dataclass(frozen=True, slots=True)
class _AtomDraft:
    kind: EvidenceAtomKind
    page_number: int
    bbox: BBox
    text: str
    confidence: float
    glyph: Glyph | None = None
    word: Word | None = None


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _glyph_key(page_number: int, glyph: Glyph) -> _AtomKey:
    return (
        EvidenceAtomKind.GLYPH,
        page_number,
        glyph.bbox,
        glyph.origin,
        glyph.char,
        f"{glyph.font}\0{glyph.source}",
    )


def _word_key(page_number: int, word: Word) -> _AtomKey:
    return (
        EvidenceAtomKind.WORD,
        page_number,
        word.bbox,
        None,
        _normalized(word.text),
        word.source,
    )


def _cell_key(cell: Cell) -> _AtomKey:
    return (
        EvidenceAtomKind.CELL_TEXT,
        cell.page_number,
        cell.bbox,
        None,
        _normalized(cell.text),
        "cell",
    )


def _center_y(bbox: BBox) -> float:
    return (bbox[1] + bbox[3]) / 2


def _inside_bbox(candidate: BBox, container: BBox) -> bool:
    center_x = (candidate[0] + candidate[2]) / 2
    center_y = _center_y(candidate)
    return container[0] <= center_x <= container[2] and container[1] <= center_y <= container[3]


def _height(bbox: BBox) -> float:
    return max(0.0, bbox[3] - bbox[1])


def _union_bbox(boxes: Sequence[BBox]) -> BBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _canonical_words_from_selected_glyphs(
    glyphs: Sequence[Glyph],
    words: Sequence[Word],
) -> tuple[Word, ...]:
    if (
        not glyphs
        or not words
        or any(not any(_inside_bbox(glyph.bbox, word.bbox) for word in words) for glyph in glyphs)
    ):
        return ()
    ordered = tuple(sorted(words, key=lambda word: (_center_y(word.bbox), word.bbox[0])))
    groups: list[list[Word]] = [[ordered[0]]]
    for previous, word in pairwise(ordered):
        shared_line = (
            abs(_center_y(previous.bbox) - _center_y(word.bbox))
            <= min(_height(previous.bbox), _height(word.bbox)) * 0.5
        )
        gap = word.bbox[0] - previous.bbox[2]
        join_threshold = min(_height(previous.bbox), _height(word.bbox)) * 0.1
        if shared_line and gap <= join_threshold:
            groups[-1].append(word)
        else:
            groups.append([word])
    canonical: list[Word] = []
    for group in groups:
        bbox = _union_bbox(tuple(word.bbox for word in group))
        group_glyphs = tuple(glyph for glyph in glyphs if _inside_bbox(glyph.bbox, bbox))
        text = logical_text_for_evidence(group_glyphs, ())
        if not text:
            return ()
        canonical.append(
            Word(
                text=text,
                bbox=bbox,
                source=("digital" if any(word.source == "digital" for word in group) else "ocr"),
                confidence=min(word.confidence for word in group),
            )
        )
    return tuple(canonical)


@dataclass(frozen=True, slots=True)
class EvidenceLedger:
    """Immutable atoms and their source-cell memberships for one transaction row."""

    atoms: tuple[EvidenceAtom, ...]
    _cell_memberships: tuple[tuple[Cell, frozenset[int]], ...]

    @classmethod
    def from_rows(cls, rows: Sequence[Row]) -> EvidenceLedger:
        """Build a deterministic ledger, collapsing duplicated overlapping evidence."""

        drafts: dict[_AtomKey, _AtomDraft] = {}
        keys_by_cell: list[tuple[Cell, tuple[_AtomKey, ...]]] = []
        for row in rows:
            for cell in row.cells:
                visible_glyphs = tuple(glyph for glyph in cell.glyphs if not glyph.char.isspace())
                cell_keys: list[_AtomKey] = []
                if visible_glyphs:
                    for glyph in visible_glyphs:
                        key = _glyph_key(cell.page_number, glyph)
                        draft = _AtomDraft(
                            kind=EvidenceAtomKind.GLYPH,
                            page_number=cell.page_number,
                            bbox=glyph.bbox,
                            text=glyph.char,
                            confidence=glyph.confidence,
                            glyph=glyph,
                        )
                        previous = drafts.get(key)
                        if previous is None or draft.confidence > previous.confidence:
                            drafts[key] = draft
                        cell_keys.append(key)
                elif cell.words:
                    for word in cell.words:
                        text = _normalized(word.text)
                        if not text:
                            continue
                        key = _word_key(cell.page_number, word)
                        draft = _AtomDraft(
                            kind=EvidenceAtomKind.WORD,
                            page_number=cell.page_number,
                            bbox=word.bbox,
                            text=text,
                            confidence=word.confidence,
                            word=word,
                        )
                        previous = drafts.get(key)
                        if previous is None or draft.confidence > previous.confidence:
                            drafts[key] = draft
                        cell_keys.append(key)
                else:
                    text = _normalized(cell.text)
                    if text:
                        key = _cell_key(cell)
                        drafts[key] = _AtomDraft(
                            kind=EvidenceAtomKind.CELL_TEXT,
                            page_number=cell.page_number,
                            bbox=cell.bbox,
                            text=text,
                            confidence=cell.confidence,
                        )
                        cell_keys.append(key)
                keys_by_cell.append((cell, tuple(dict.fromkeys(cell_keys))))

        ordered_keys = tuple(
            sorted(
                drafts,
                key=lambda key: (
                    key[1],
                    _center_y(key[2]),
                    key[2][0],
                    key[2][2],
                    key[0].value,
                    key[4],
                    key[5],
                ),
            )
        )
        atom_id_by_key = {key: atom_id for atom_id, key in enumerate(ordered_keys)}
        atoms = tuple(
            EvidenceAtom(
                atom_id=atom_id,
                kind=drafts[key].kind,
                page_number=drafts[key].page_number,
                bbox=drafts[key].bbox,
                text=drafts[key].text,
                confidence=drafts[key].confidence,
                glyph=drafts[key].glyph,
                word=drafts[key].word,
            )
            for atom_id, key in enumerate(ordered_keys)
        )
        memberships = tuple(
            (cell, frozenset(atom_id_by_key[key] for key in keys)) for cell, keys in keys_by_cell
        )
        return cls(atoms=atoms, _cell_memberships=memberships)

    def atoms_for_cell(self, cell: Cell) -> frozenset[int]:
        """Return the atom IDs backed by one exact source cell."""

        identity_matches = tuple(
            ids for candidate, ids in self._cell_memberships if candidate is cell
        )
        if identity_matches:
            return frozenset().union(*identity_matches)
        equality_matches = tuple(
            ids for candidate, ids in self._cell_memberships if candidate == cell
        )
        return frozenset().union(*equality_matches) if equality_matches else frozenset()

    def render(self, atom_ids: Iterable[int]) -> str:
        """Render selected atoms using exact positioned glyph and word evidence."""

        selected_ids = frozenset(atom_ids)
        selected = tuple(atom for atom in self.atoms if atom.atom_id in selected_ids)
        glyphs = tuple(atom.glyph for atom in selected if atom.glyph is not None)
        if glyphs:
            selected_glyph_ids = {atom.atom_id for atom in selected if atom.glyph is not None}
            source_words = tuple(
                dict.fromkeys(word for cell, _ in self._cell_memberships for word in cell.words)
            )
            covered_words = tuple(
                word
                for word in source_words
                if (
                    word_atom_ids := {
                        atom.atom_id
                        for atom in self.atoms
                        if atom.glyph is not None and _inside_bbox(atom.bbox, word.bbox)
                    }
                )
                and word_atom_ids <= selected_glyph_ids
            )
            canonical_words = _canonical_words_from_selected_glyphs(glyphs, covered_words)
            if canonical_words:
                return _normalized(logical_text_for_evidence((), canonical_words))
            return _normalized(logical_text_for_evidence(glyphs, covered_words))
        words = tuple(atom.word for atom in selected if atom.word is not None)
        if words:
            return _normalized(logical_text_for_evidence((), words))
        return _normalized(" ".join(atom.text for atom in selected))

    def validate_claims(self, claims: Iterable[EvidenceClaim]) -> ClaimValidation:
        """Return conflicting ownership and meaningful atoms without a disposition."""

        known_ids = {atom.atom_id for atom in self.atoms}
        owners_by_atom: dict[int, set[SemanticOwner]] = {}
        diagnostics: list[str] = []
        for claim in claims:
            if not claim.atom_ids <= known_ids:
                diagnostics.append("unknown_semantic_evidence_atom")
            for atom_id in claim.atom_ids & known_ids:
                owners_by_atom.setdefault(atom_id, set()).add(claim.owner)
        if any(len(owners) > 1 for owners in owners_by_atom.values()):
            diagnostics.append("conflicting_semantic_evidence_claim")
        unclaimed = frozenset(
            atom.atom_id
            for atom in self.atoms
            if atom.atom_id not in owners_by_atom and any(char.isalnum() for char in atom.text)
        )
        return ClaimValidation(
            unclaimed_atom_ids=unclaimed,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )


__all__ = [
    "ClaimValidation",
    "EvidenceAtom",
    "EvidenceAtomKind",
    "EvidenceClaim",
    "EvidenceLedger",
    "SemanticOwner",
]
