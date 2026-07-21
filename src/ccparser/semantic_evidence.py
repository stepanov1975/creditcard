"""Deterministic ownership accounting for transaction-row evidence."""

from __future__ import annotations

import re
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
    EXCHANGE_RATE = "exchange_rate"
    FX_FEE_PERCENTAGE = "fx_fee_percentage"
    GROSS_FX_FEE = "gross_fx_fee"
    FX_FEE_DISCOUNT = "fx_fee_discount"
    NET_FX_FEE = "net_fx_fee"
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
class EvidenceCluster:
    """A same-line evidence span separated from its neighbors by a material gap."""

    bbox: BBox
    atom_ids: frozenset[int]
    text: str


@dataclass(frozen=True, slots=True)
class FragmentedDateCandidate:
    """A date-shaped token reconstructed from contiguous positioned glyphs."""

    text: str
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class PositionedDecimalCandidate:
    """A decimal reconstructed from one contiguous positioned numeric run."""

    text: str
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class DescriptionExtraction:
    """A reconstructed merchant description and the evidence dispositions it created."""

    value: str | None
    claims: tuple[EvidenceClaim, ...]
    diagnostics: tuple[str, ...]


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


def _character_signature(text: str) -> tuple[str, ...]:
    return tuple(sorted(char for char in _normalized(text) if not char.isspace()))


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
        standalone_boundary = previous.text in {
            "-",
            "\N{EN DASH}",
            "\N{EM DASH}",
            "(",
            ")",
        } or word.text in {
            "-",
            "\N{EN DASH}",
            "\N{EM DASH}",
            "(",
            ")",
        }
        if shared_line and gap <= join_threshold and not standalone_boundary:
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
                elif cell.words and _character_signature(cell.text) == _character_signature(
                    "".join(word.text for word in cell.words)
                ):
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

    def atoms_in_bbox(self, atom_ids: Iterable[int], bbox: BBox) -> frozenset[int]:
        """Return selected atom IDs whose positioned centers fall inside a box."""

        selected = frozenset(atom_ids)
        return frozenset(
            atom.atom_id
            for atom in self.atoms
            if atom.atom_id in selected and _inside_bbox(atom.bbox, bbox)
        )

    def clusters_for_cell(self, cell: Cell) -> tuple[EvidenceCluster, ...]:
        """Split one cell into same-line spans using only positioned evidence gaps."""

        cell_atom_ids = self.atoms_for_cell(cell)
        if not cell_atom_ids:
            return ()
        ordered_words = tuple(
            sorted(cell.words, key=lambda word: (_center_y(word.bbox), word.bbox[0], word.bbox[2]))
        )
        if not ordered_words:
            bbox = _union_bbox(
                tuple(atom.bbox for atom in self.atoms if atom.atom_id in cell_atom_ids)
            )
            return (
                EvidenceCluster(
                    bbox=bbox,
                    atom_ids=cell_atom_ids,
                    text=self.render(cell_atom_ids),
                ),
            )
        word_groups: list[list[Word]] = [[ordered_words[0]]]
        for previous, word in pairwise(ordered_words):
            height = min(_height(previous.bbox), _height(word.bbox))
            shared_line = abs(_center_y(previous.bbox) - _center_y(word.bbox)) <= height * 0.5
            gap = word.bbox[0] - previous.bbox[2]
            if shared_line and gap <= height * 0.6:
                word_groups[-1].append(word)
            else:
                word_groups.append([word])
        clusters: list[EvidenceCluster] = []
        claimed_ids: set[int] = set()
        for group in word_groups:
            bbox = _union_bbox(tuple(word.bbox for word in group))
            ids = self.atoms_in_bbox(cell_atom_ids, bbox)
            if not ids:
                continue
            claimed_ids.update(ids)
            clusters.append(EvidenceCluster(bbox=bbox, atom_ids=ids, text=self.render(ids)))
        remaining_ids = cell_atom_ids - claimed_ids
        if remaining_ids:
            bbox = _union_bbox(
                tuple(atom.bbox for atom in self.atoms if atom.atom_id in remaining_ids)
            )
            clusters.append(
                EvidenceCluster(
                    bbox=bbox,
                    atom_ids=remaining_ids,
                    text=self.render(remaining_ids),
                )
            )
        return tuple(sorted(clusters, key=lambda cluster: (cluster.bbox[1], cluster.bbox[0])))

    def fragmented_date_candidates(self, cell: Cell) -> tuple[FragmentedDateCandidate, ...]:
        """Recover date-shaped tokens from physical glyph order, not logical cell text."""

        cell_atom_ids = self.atoms_for_cell(cell)
        atom_id_by_glyph_key = {
            _glyph_key(atom.page_number, atom.glyph): atom.atom_id
            for atom in self.atoms
            if atom.atom_id in cell_atom_ids and atom.glyph is not None
        }
        positioned = tuple(
            (glyph, atom_id_by_glyph_key.get(_glyph_key(cell.page_number, glyph)))
            for glyph in cell.glyphs
        )
        if not positioned:
            return ()

        lines: list[list[tuple[Glyph, int | None]]] = []
        for item in sorted(positioned, key=lambda value: _center_y(value[0].bbox)):
            glyph = item[0]
            matching_line = next(
                (
                    candidate
                    for candidate in lines
                    if abs(_center_y(candidate[0][0].bbox) - _center_y(glyph.bbox))
                    <= min(_height(candidate[0][0].bbox), _height(glyph.bbox)) * 0.5
                ),
                None,
            )
            if matching_line is None:
                lines.append([item])
            else:
                matching_line.append(item)
        ordered_lines = tuple(
            tuple(
                sorted(
                    line,
                    key=lambda item: (item[0].bbox[0], item[0].bbox[2]),
                )
            )
            for line in sorted(lines, key=lambda line: _center_y(line[0][0].bbox))
        )
        date_pattern = re.compile(
            r"(?<!\d)\d{1,4}(?P<separator>[./-])\d{1,2}"
            r"(?P=separator)\d{1,4}(?!\d)"
        )
        candidates: list[FragmentedDateCandidate] = []
        segment: list[tuple[Glyph, int]] = []

        def flush() -> None:
            if not segment:
                return
            text = "".join(glyph.char for glyph, _ in segment)
            for match in date_pattern.finditer(text):
                matched = segment[match.start() : match.end()]
                candidates.append(
                    FragmentedDateCandidate(
                        text=match.group(0),
                        atom_ids=frozenset(atom_id for _, atom_id in matched),
                    )
                )
            segment.clear()

        for ordered_line in ordered_lines:
            previous: Glyph | None = None
            for glyph, atom_id in ordered_line:
                gap = 0.0 if previous is None else glyph.bbox[0] - previous.bbox[2]
                contiguous = (
                    previous is None
                    or gap <= min(_height(previous.bbox), _height(glyph.bbox)) * 0.6
                )
                if (
                    atom_id is None
                    or glyph.char.isspace()
                    or (not glyph.char.isdigit() and glyph.char not in "./-")
                    or not contiguous
                ):
                    flush()
                if atom_id is not None and (glyph.char.isdigit() or glyph.char in "./-"):
                    segment.append((glyph, atom_id))
                previous = glyph
            flush()

        unique = {(candidate.text, candidate.atom_ids): candidate for candidate in candidates}
        return tuple(unique.values())

    def positioned_decimal_candidates(
        self,
        atom_ids: Iterable[int],
        *,
        max_fraction_digits: int = 6,
    ) -> tuple[PositionedDecimalCandidate, ...]:
        """Recover decimals from bounded, contiguous, physically positioned glyphs."""

        if max_fraction_digits < 1:
            raise ValueError("maximum fraction digits must be positive")
        selected_ids = frozenset(atom_ids)
        selected = tuple(
            atom for atom in self.atoms if atom.atom_id in selected_ids and atom.glyph is not None
        )
        if not selected:
            return ()

        lines: list[list[EvidenceAtom]] = []
        for atom in sorted(
            selected,
            key=lambda item: (item.page_number, _center_y(item.bbox), item.bbox[0]),
        ):
            matching_line = next(
                (
                    line
                    for line in lines
                    if line[0].page_number == atom.page_number
                    and abs(_center_y(line[0].bbox) - _center_y(atom.bbox))
                    <= min(_height(line[0].bbox), _height(atom.bbox)) * 0.5
                ),
                None,
            )
            if matching_line is None:
                lines.append([atom])
            else:
                matching_line.append(atom)

        pattern = re.compile(rf"\d+[.,]\d{{1,{max_fraction_digits}}}")
        candidates: list[PositionedDecimalCandidate] = []

        def flush(segment: list[EvidenceAtom]) -> None:
            if not segment:
                return
            start = 0
            end = len(segment)
            while start < end and segment[start].text in ".,":
                start += 1
            while end > start and segment[end - 1].text in ".,":
                end -= 1
            matched_atoms = segment[start:end]
            text = "".join(atom.text for atom in matched_atoms)
            if pattern.fullmatch(text) is not None:
                candidates.append(
                    PositionedDecimalCandidate(
                        text=text,
                        atom_ids=frozenset(atom.atom_id for atom in matched_atoms),
                    )
                )
            segment.clear()

        for line in sorted(lines, key=lambda item: (item[0].page_number, _center_y(item[0].bbox))):
            segment: list[EvidenceAtom] = []

            previous: EvidenceAtom | None = None
            for atom in sorted(line, key=lambda item: (item.bbox[0], item.bbox[2])):
                gap = 0.0 if previous is None else atom.bbox[0] - previous.bbox[2]
                contiguous = (
                    previous is None or gap <= min(_height(previous.bbox), _height(atom.bbox)) * 0.6
                )
                if not contiguous:
                    flush(segment)
                if atom.text.isdigit() or atom.text in ".,":
                    segment.append(atom)
                else:
                    flush(segment)
                previous = atom
            flush(segment)

        unique: list[PositionedDecimalCandidate] = []
        seen: set[tuple[str, frozenset[int]]] = set()
        for candidate in candidates:
            key = (candidate.text, candidate.atom_ids)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return tuple(unique)

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
    "DescriptionExtraction",
    "EvidenceAtom",
    "EvidenceAtomKind",
    "EvidenceClaim",
    "EvidenceCluster",
    "EvidenceLedger",
    "FragmentedDateCandidate",
    "PositionedDecimalCandidate",
    "SemanticOwner",
]
