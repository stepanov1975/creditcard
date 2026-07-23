"""Deterministic ownership accounting for transaction-row evidence."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from ccparser.date_tokens import has_date_token_boundaries
from ccparser.evidence.models import BBox, Glyph, Word
from ccparser.geometry import (
    bbox_center_y as _center_y,
)
from ccparser.geometry import (
    bbox_height as _height,
)
from ccparser.geometry import (
    center_inside as _inside_bbox,
)
from ccparser.geometry import (
    union_bbox as _union_bbox,
)
from ccparser.layout.models import Cell, Row
from ccparser.layout.text import logical_text_for_evidence
from ccparser.money import canonical_currency
from ccparser.text_tokens import normalize_text


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
    """A date-shaped token reconstructed from positioned source evidence."""

    text: str
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class PositionedNumberCandidate:
    """A number reconstructed from one positioned numeric source run."""

    text: str
    atom_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class PositionedDecimalCandidate(PositionedNumberCandidate):
    """A decimal reconstructed from one positioned numeric source run."""


@dataclass(frozen=True, slots=True)
class PositionedWholeNumberCandidate(PositionedNumberCandidate):
    """A whole number reconstructed from one positioned numeric source run."""


@dataclass(frozen=True, slots=True)
class PositionedPercentageCandidate:
    """A positioned number bound to explicit percentage-marker evidence."""

    number: PositionedNumberCandidate
    marker_atom_ids: frozenset[int]
    marker_count: int

    @property
    def text(self) -> str:
        """Return the marker-free numeric text."""

        return self.number.text

    @property
    def numeric_atom_ids(self) -> frozenset[int]:
        """Return atoms supporting the numeric value."""

        return self.number.atom_ids

    @property
    def semantic_atom_ids(self) -> frozenset[int]:
        """Return every atom supporting the percentage semantic value."""

        return self.numeric_atom_ids | self.marker_atom_ids


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
    return normalize_text(text)


def _has_unique_ordered_word_subset(text: str, words: Sequence[Word]) -> bool:
    logical = _normalized(text)
    if not logical or not words:
        return False
    ordered = tuple(
        sorted(
            words,
            key=lambda word: (_center_y(word.bbox), word.bbox[0], word.bbox[2], word.text),
        )
    )
    matches = 0
    for start in range(len(ordered)):
        for end in range(start + 1, len(ordered) + 1):
            if _normalized(" ".join(word.text for word in ordered[start:end])) == logical:
                matches += 1
                if matches > 1:
                    return False
    return matches == 1


_DECIMAL_WORD_WRAPPERS = frozenset("+-()[]{}%\N{MINUS SIGN}\N{EN DASH}\N{EM DASH}")
_DECIMAL_GLYPH_WRAPPERS = _DECIMAL_WORD_WRAPPERS | frozenset(".,;:=\N{EN DASH}\N{EM DASH}")
_DECIMAL_GLYPH_HARD_BOUNDARIES = frozenset(".,;:=")
_DATE_WORD_WRAPPERS = frozenset("()[]{}")


def _wrapped_word_decimal(
    text: str,
    pattern: re.Pattern[str],
) -> str | None:
    """Return one decimal only when the rest of a WORD is a semantic wrapper."""

    matches = tuple(pattern.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    numeric_start = match.start()
    while numeric_start > 0 and (
        text[numeric_start - 1].isdigit() or text[numeric_start - 1] in ".,"
    ):
        numeric_start -= 1
    numeric_end = match.end()
    while numeric_end < len(text) and (text[numeric_end].isdigit() or text[numeric_end] in ".,"):
        numeric_end += 1
    numeric_remainder = text[numeric_start : match.start()] + text[match.end() : numeric_end]
    if any(char.isdigit() for char in numeric_remainder):
        return None
    prefix = text[: match.start()]
    suffix = text[match.end() :]
    prefix_boundaries = tuple(
        index for index, char in enumerate(prefix) if char in _DECIMAL_GLYPH_HARD_BOUNDARIES
    )
    if prefix_boundaries:
        prefix = prefix[max(prefix_boundaries) + 1 :]
    suffix_boundaries = tuple(
        index for index, char in enumerate(suffix) if char in _DECIMAL_GLYPH_HARD_BOUNDARIES
    )
    if suffix_boundaries:
        suffix = suffix[: min(suffix_boundaries)]
    for boundary in (prefix, suffix):
        semantic_text = "".join(
            char
            for char in boundary
            if not char.isspace()
            and char not in _DECIMAL_WORD_WRAPPERS
            and unicodedata.category(char) != "Sc"
        )
        if semantic_text and canonical_currency(semantic_text) is None:
            return None
    return match.group(0)


def _wrapped_word_date(text: str, pattern: re.Pattern[str]) -> str | None:
    matches = tuple(pattern.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    numeric_start = match.start()
    while numeric_start > 0 and (
        text[numeric_start - 1].isdigit() or text[numeric_start - 1] in "./-"
    ):
        numeric_start -= 1
    numeric_end = match.end()
    while numeric_end < len(text) and (text[numeric_end].isdigit() or text[numeric_end] in "./-"):
        numeric_end += 1
    numeric_remainder = text[numeric_start : match.start()] + text[match.end() : numeric_end]
    if any(char.isdigit() for char in numeric_remainder):
        return None
    prefix = text[: match.start()]
    suffix = text[match.end() :]
    prefix_boundaries = tuple(
        index for index, char in enumerate(prefix) if char in _DECIMAL_GLYPH_HARD_BOUNDARIES
    )
    if prefix_boundaries:
        prefix = prefix[max(prefix_boundaries) + 1 :]
    suffix_boundaries = tuple(
        index for index, char in enumerate(suffix) if char in _DECIMAL_GLYPH_HARD_BOUNDARIES
    )
    if suffix_boundaries:
        suffix = suffix[: min(suffix_boundaries)]
    if any(
        char not in _DATE_WORD_WRAPPERS and not char.isspace()
        for boundary in (prefix, suffix)
        for char in boundary
    ):
        return None
    return match.group(0)


def _touching_word_boundary_text(
    candidate: EvidenceAtom,
    word_atoms: Sequence[EvidenceAtom],
    *,
    before: bool,
    logical_texts: Sequence[str],
) -> str:
    candidate_center_x = (candidate.bbox[0] + candidate.bbox[2]) / 2
    nearby = tuple(
        atom
        for atom in word_atoms
        if atom.atom_id != candidate.atom_id
        and atom.page_number == candidate.page_number
        and abs(_center_y(atom.bbox) - _center_y(candidate.bbox))
        <= min(_height(atom.bbox), _height(candidate.bbox)) * 0.5
        and (
            (atom.bbox[0] + atom.bbox[2]) / 2 < candidate_center_x
            if before
            else (atom.bbox[0] + atom.bbox[2]) / 2 > candidate_center_x
        )
    )
    ordered = sorted(
        nearby,
        key=lambda atom: atom.bbox[2] if before else atom.bbox[0],
        reverse=before,
    )
    edge = candidate.bbox[0] if before else candidate.bbox[2]
    attached_text = candidate.text
    run: list[EvidenceAtom] = []
    for atom in ordered:
        gap = edge - atom.bbox[2] if before else atom.bbox[0] - edge
        if gap > min(_height(atom.bbox), _height(candidate.bbox)) * 0.05:
            break
        combined_text = f"{atom.text}{attached_text}" if before else f"{attached_text}{atom.text}"
        if not any(combined_text in logical_text for logical_text in logical_texts):
            break
        run.append(atom)
        attached_text = combined_text
        edge = atom.bbox[0] if before else atom.bbox[2]
    if before:
        run.reverse()
    return "".join(atom.text for atom in run)


def _word_date_has_boundaries(
    candidate: EvidenceAtom,
    word_atoms: Sequence[EvidenceAtom],
    pattern: re.Pattern[str],
    date_text: str,
    logical_texts: Sequence[str],
) -> bool:
    combined = "".join(
        (
            _touching_word_boundary_text(
                candidate,
                word_atoms,
                before=True,
                logical_texts=logical_texts,
            ),
            candidate.text,
            _touching_word_boundary_text(
                candidate,
                word_atoms,
                before=False,
                logical_texts=logical_texts,
            ),
        )
    )
    return _wrapped_word_date(combined, pattern) == date_text


def _word_decimal_has_boundaries(
    candidate: EvidenceAtom,
    word_atoms: Sequence[EvidenceAtom],
    pattern: re.Pattern[str],
    decimal_text: str,
    logical_texts: Sequence[str],
) -> bool:
    combined = "".join(
        (
            _touching_word_boundary_text(
                candidate,
                word_atoms,
                before=True,
                logical_texts=logical_texts,
            ),
            candidate.text,
            _touching_word_boundary_text(
                candidate,
                word_atoms,
                before=False,
                logical_texts=logical_texts,
            ),
        )
    )
    return _wrapped_word_decimal(combined, pattern) == decimal_text


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
                elif cell.words and (
                    _character_signature(cell.text)
                    == _character_signature("".join(word.text for word in cell.words))
                    or _has_unique_ordered_word_subset(cell.text, cell.words)
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
        """Recover date-shaped tokens from positioned glyph or word evidence."""

        cell_atom_ids = self.atoms_for_cell(cell)
        date_pattern = re.compile(
            r"(?<!\d)\d{1,4}(?P<separator>[./-])\d{1,2}"
            r"(?P=separator)\d{1,4}(?!\d)"
        )
        atom_id_by_glyph_key = {
            _glyph_key(atom.page_number, atom.glyph): atom.atom_id
            for atom in self.atoms
            if atom.atom_id in cell_atom_ids and atom.glyph is not None
        }
        positioned = tuple(
            (glyph, atom_id_by_glyph_key.get(_glyph_key(cell.page_number, glyph)))
            for glyph in cell.glyphs
        )
        if not atom_id_by_glyph_key:
            word_atoms = tuple(
                atom
                for atom in self.atoms
                if atom.atom_id in cell_atom_ids and atom.word is not None
            )
            word_candidates = tuple(
                FragmentedDateCandidate(
                    text=date_text,
                    atom_ids=frozenset((atom.atom_id,)),
                )
                for atom in word_atoms
                if (date_text := _wrapped_word_date(atom.text, date_pattern)) is not None
                if _word_date_has_boundaries(
                    atom,
                    word_atoms,
                    date_pattern,
                    date_text,
                    (cell.text,),
                )
            )
            return tuple(
                {
                    (candidate.text, candidate.atom_ids): candidate for candidate in word_candidates
                }.values()
            )

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
        candidates: list[FragmentedDateCandidate] = []
        segment: list[tuple[Glyph, int]] = []

        def has_physical_token_boundaries(candidate: FragmentedDateCandidate) -> bool:
            candidate_atoms = tuple(self.atoms[atom_id] for atom_id in candidate.atom_ids)
            candidate_bbox = _union_bbox(tuple(atom.bbox for atom in candidate_atoms))
            candidate_glyph_keys = {
                _glyph_key(atom.page_number, atom.glyph)
                for atom in candidate_atoms
                if atom.glyph is not None
            }
            same_line = tuple(
                glyph
                for glyph in cell.glyphs
                if _glyph_key(cell.page_number, glyph) not in candidate_glyph_keys
                and abs(_center_y(glyph.bbox) - _center_y(candidate_bbox))
                <= min(_height(glyph.bbox), _height(candidate_bbox)) * 0.5
            )
            candidate_center_x = (candidate_bbox[0] + candidate_bbox[2]) / 2
            left = max(
                (
                    glyph
                    for glyph in same_line
                    if (glyph.bbox[0] + glyph.bbox[2]) / 2 < candidate_center_x
                ),
                key=lambda glyph: (glyph.bbox[0] + glyph.bbox[2]) / 2,
                default=None,
            )
            right = min(
                (
                    glyph
                    for glyph in same_line
                    if (glyph.bbox[0] + glyph.bbox[2]) / 2 > candidate_center_x
                ),
                key=lambda glyph: (glyph.bbox[0] + glyph.bbox[2]) / 2,
                default=None,
            )
            invalid_boundaries = tuple(
                glyph
                for glyph in (left, right)
                if glyph is not None
                and glyph.char.isalnum()
                and max(
                    candidate_bbox[0] - glyph.bbox[2],
                    glyph.bbox[0] - candidate_bbox[2],
                    0.0,
                )
                <= min(_height(glyph.bbox), _height(candidate_bbox)) * 0.6
            )
            if not invalid_boundaries:
                return True
            physical_text = "".join(glyph.char for glyph in cell.glyphs)
            is_reordered_hebrew_source = (
                candidate.text not in cell.text
                and _character_signature(cell.text) == _character_signature(physical_text)
                and all("\u0590" <= glyph.char <= "\u05ff" for glyph in invalid_boundaries)
            )
            return is_reordered_hebrew_source

        def flush() -> None:
            if not segment:
                return
            text = "".join(glyph.char for glyph, _ in segment)
            for match in date_pattern.finditer(text):
                if not has_date_token_boundaries(text, match.start(), match.end()):
                    continue
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

        unique = {
            (candidate.text, candidate.atom_ids): candidate
            for candidate in candidates
            if has_physical_token_boundaries(candidate)
        }
        return tuple(unique.values())

    def fragmented_date_atom_ids(self, atom_ids: Iterable[int]) -> frozenset[int]:
        """Return selected atom IDs participating in complete positioned date tokens."""

        selected_ids = frozenset(atom_ids)
        return frozenset(
            atom_id
            for cell, membership in self._cell_memberships
            if membership & selected_ids
            for candidate in self.fragmented_date_candidates(cell)
            if candidate.atom_ids <= selected_ids
            for atom_id in candidate.atom_ids
        )

    def positioned_decimal_candidates(
        self,
        atom_ids: Iterable[int],
        *,
        max_fraction_digits: int = 6,
    ) -> tuple[PositionedDecimalCandidate, ...]:
        """Recover bounded, physically positioned decimal glyph or word evidence."""

        if max_fraction_digits < 1:
            raise ValueError("maximum fraction digits must be positive")
        candidates = self._positioned_number_candidates(
            atom_ids,
            pattern=re.compile(rf"\d+[.,]\d{{1,{max_fraction_digits}}}"),
        )
        return tuple(
            PositionedDecimalCandidate(candidate.text, candidate.atom_ids)
            for candidate in candidates
        )

    def positioned_whole_number_candidates(
        self,
        atom_ids: Iterable[int],
    ) -> tuple[PositionedWholeNumberCandidate, ...]:
        """Recover bounded, physically positioned whole-number evidence."""

        candidates = self._positioned_number_candidates(
            atom_ids,
            pattern=re.compile(r"\d+"),
        )
        return tuple(
            PositionedWholeNumberCandidate(candidate.text, candidate.atom_ids)
            for candidate in candidates
        )

    def _positioned_number_candidates(
        self,
        atom_ids: Iterable[int],
        *,
        pattern: re.Pattern[str],
    ) -> tuple[PositionedNumberCandidate, ...]:
        """Recover numbers through the shared positioned-evidence engine."""

        selected_ids = frozenset(atom_ids)
        word_atoms = tuple(
            atom for atom in self.atoms if atom.atom_id in selected_ids and atom.word is not None
        )
        logical_texts_by_word_atom = {
            atom.atom_id: tuple(
                cell.text
                for cell, membership in self._cell_memberships
                if atom.atom_id in membership
            )
            for atom in word_atoms
        }
        candidates = [
            PositionedNumberCandidate(
                text=decimal_text,
                atom_ids=frozenset((atom.atom_id,)),
            )
            for atom in word_atoms
            if (decimal_text := _wrapped_word_decimal(atom.text, pattern)) is not None
            if _word_decimal_has_boundaries(
                atom,
                word_atoms,
                pattern,
                decimal_text,
                logical_texts_by_word_atom[atom.atom_id],
            )
        ]
        selected = tuple(
            atom for atom in self.atoms if atom.atom_id in selected_ids and atom.glyph is not None
        )
        whitespace_glyphs = tuple(
            (cell.page_number, glyph)
            for cell, membership in self._cell_memberships
            if membership & selected_ids
            for glyph in cell.glyphs
            if glyph.char.isspace()
        )

        def has_whitespace_between(
            *,
            page_number: int,
            y_center: float,
            height: float,
            left_edge: float,
            right_edge: float,
        ) -> bool:
            return any(
                whitespace_page == page_number
                and abs(_center_y(glyph.bbox) - y_center) <= min(_height(glyph.bbox), height) * 0.5
                and left_edge <= (glyph.bbox[0] + glyph.bbox[2]) / 2 <= right_edge
                for whitespace_page, glyph in whitespace_glyphs
            )

        def adjacent_boundary_text(
            candidate_atoms: tuple[EvidenceAtom, ...],
            *,
            before: bool,
        ) -> str:
            candidate_bbox = _union_bbox(tuple(atom.bbox for atom in candidate_atoms))
            page_number = candidate_atoms[0].page_number
            y_center = _center_y(candidate_bbox)
            height = _height(candidate_bbox)
            candidate_center_x = (candidate_bbox[0] + candidate_bbox[2]) / 2
            nearby = tuple(
                atom
                for atom in selected
                if atom.atom_id not in {item.atom_id for item in candidate_atoms}
                and atom.page_number == page_number
                and abs(_center_y(atom.bbox) - y_center) <= min(_height(atom.bbox), height) * 0.5
                and (
                    (atom.bbox[0] + atom.bbox[2]) / 2 < candidate_center_x
                    if before
                    else (atom.bbox[0] + atom.bbox[2]) / 2 > candidate_center_x
                )
            )
            ordered = sorted(
                nearby,
                key=lambda atom: atom.bbox[2] if before else atom.bbox[0],
                reverse=before,
            )
            edge = candidate_bbox[0] if before else candidate_bbox[2]
            run: list[EvidenceAtom] = []
            for atom in ordered:
                gap = edge - atom.bbox[2] if before else atom.bbox[0] - edge
                left_edge = atom.bbox[2] if before else edge
                right_edge = edge if before else atom.bbox[0]
                if gap > min(_height(atom.bbox), height) * 0.4 or has_whitespace_between(
                    page_number=page_number,
                    y_center=y_center,
                    height=height,
                    left_edge=left_edge,
                    right_edge=right_edge,
                ):
                    break
                run.append(atom)
                edge = atom.bbox[0] if before else atom.bbox[2]
                if atom.text in _DECIMAL_GLYPH_HARD_BOUNDARIES:
                    break
            if before:
                run.reverse()
            return "".join(atom.text for atom in run)

        def has_valid_glyph_boundaries(candidate_atoms: tuple[EvidenceAtom, ...]) -> bool:
            for boundary in (
                adjacent_boundary_text(candidate_atoms, before=True),
                adjacent_boundary_text(candidate_atoms, before=False),
            ):
                semantic_text = "".join(
                    char
                    for char in boundary
                    if char not in _DECIMAL_GLYPH_WRAPPERS and unicodedata.category(char) != "Sc"
                )
                if semantic_text and canonical_currency(semantic_text) is None:
                    return False
            return True

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
                    PositionedNumberCandidate(
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
                whitespace_between = previous is not None and any(
                    page_number == atom.page_number
                    and abs(_center_y(glyph.bbox) - _center_y(atom.bbox))
                    <= min(_height(glyph.bbox), _height(atom.bbox)) * 0.5
                    and previous.bbox[2] <= (glyph.bbox[0] + glyph.bbox[2]) / 2 <= atom.bbox[0]
                    for page_number, glyph in whitespace_glyphs
                )
                contiguous = previous is None or (
                    not whitespace_between
                    and gap <= min(_height(previous.bbox), _height(atom.bbox)) * 0.6
                )
                if not contiguous:
                    flush(segment)
                if atom.text.isdigit() or atom.text in ".,":
                    segment.append(atom)
                else:
                    flush(segment)
                previous = atom
            flush(segment)

        glyph_candidates = tuple(
            candidate
            for candidate in candidates
            if all(self.atoms[atom_id].glyph is not None for atom_id in candidate.atom_ids)
        )
        word_candidates = tuple(
            candidate
            for candidate in candidates
            if all(self.atoms[atom_id].word is not None for atom_id in candidate.atom_ids)
        )
        unique: list[PositionedNumberCandidate] = []
        seen: set[tuple[str, frozenset[int]]] = set()
        for candidate in candidates:
            candidate_atoms = tuple(self.atoms[atom_id] for atom_id in candidate.atom_ids)
            if candidate_atoms and all(atom.word is not None for atom in candidate_atoms):
                word_bbox = _union_bbox(tuple(atom.bbox for atom in candidate_atoms))
                integer_part = re.split(r"[.,]", candidate.text, maxsplit=1)[0]
                has_grouping_prefix = len(integer_part) == 3 and any(
                    atom.atom_id in selected_ids
                    and atom.word is not None
                    and atom.text.isdigit()
                    and atom.page_number == candidate_atoms[0].page_number
                    and abs(_center_y(atom.bbox) - _center_y(word_bbox))
                    <= min(_height(atom.bbox), _height(word_bbox)) * 0.5
                    and 0
                    <= word_bbox[0] - atom.bbox[2]
                    <= min(_height(atom.bbox), _height(word_bbox)) * 0.6
                    and not any(
                        other.atom_id in selected_ids
                        and other.atom_id != atom.atom_id
                        and other.atom_id not in candidate.atom_ids
                        and other.page_number == atom.page_number
                        and atom.bbox[2] < (other.bbox[0] + other.bbox[2]) / 2 < word_bbox[0]
                        for other in self.atoms
                    )
                    for atom in self.atoms
                )
                if has_grouping_prefix:
                    continue
                if any(
                    glyph_candidate.text == candidate.text
                    and all(
                        self.atoms[atom_id].page_number == candidate_atoms[0].page_number
                        for atom_id in glyph_candidate.atom_ids
                    )
                    and all(
                        _inside_bbox(self.atoms[atom_id].bbox, word_bbox)
                        for atom_id in glyph_candidate.atom_ids
                    )
                    for glyph_candidate in glyph_candidates
                ):
                    continue
            elif candidate_atoms and all(atom.glyph is not None for atom in candidate_atoms):
                if not has_valid_glyph_boundaries(candidate_atoms):
                    continue
                glyph_page = candidate_atoms[0].page_number
                glyph_bbox = _union_bbox(tuple(atom.bbox for atom in candidate_atoms))
                integer_part = re.split(r"[.,]", candidate.text, maxsplit=1)[0]
                has_grouping_prefix = len(integer_part) == 3 and any(
                    atom.atom_id in selected_ids
                    and atom.atom_id not in candidate.atom_ids
                    and atom.glyph is not None
                    and atom.text.isdigit()
                    and atom.page_number == glyph_page
                    and abs(_center_y(atom.bbox) - _center_y(glyph_bbox))
                    <= min(_height(atom.bbox), _height(glyph_bbox)) * 0.5
                    and 0
                    <= glyph_bbox[0] - atom.bbox[2]
                    <= min(_height(atom.bbox), _height(glyph_bbox)) * 0.6
                    and any(
                        page_number == glyph_page
                        and abs(_center_y(glyph.bbox) - _center_y(glyph_bbox))
                        <= min(_height(glyph.bbox), _height(glyph_bbox)) * 0.5
                        and atom.bbox[2] <= (glyph.bbox[0] + glyph.bbox[2]) / 2 <= glyph_bbox[0]
                        for page_number, glyph in whitespace_glyphs
                    )
                    and not any(
                        other.atom_id in selected_ids
                        and other.atom_id != atom.atom_id
                        and other.atom_id not in candidate.atom_ids
                        and other.page_number == glyph_page
                        and atom.bbox[2] < (other.bbox[0] + other.bbox[2]) / 2 < glyph_bbox[0]
                        for other in self.atoms
                    )
                    for atom in selected
                )
                if has_grouping_prefix:
                    continue
                equivalent_word_ids = frozenset(
                    atom_id
                    for word_candidate in word_candidates
                    if word_candidate.text == candidate.text
                    if (
                        word_atoms := tuple(
                            self.atoms[atom_id] for atom_id in word_candidate.atom_ids
                        )
                    )
                    if all(atom.page_number == glyph_page for atom in word_atoms)
                    if all(
                        _inside_bbox(
                            glyph_atom.bbox,
                            _union_bbox(tuple(atom.bbox for atom in word_atoms)),
                        )
                        for glyph_atom in candidate_atoms
                    )
                    for atom_id in word_candidate.atom_ids
                )
                if equivalent_word_ids:
                    candidate = PositionedNumberCandidate(
                        text=candidate.text,
                        atom_ids=candidate.atom_ids | equivalent_word_ids,
                    )
            key = (candidate.text, candidate.atom_ids)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return tuple(unique)

    def positioned_percentage_candidates(
        self,
        atom_ids: Iterable[int],
        *,
        max_fraction_digits: int = 6,
    ) -> tuple[PositionedPercentageCandidate, ...]:
        """Bind positioned decimal or whole-number evidence to percent markers."""

        selected_ids = frozenset(atom_ids)
        number_candidates: tuple[PositionedNumberCandidate, ...] = (
            *self.positioned_decimal_candidates(
                selected_ids,
                max_fraction_digits=max_fraction_digits,
            ),
            *self.positioned_whole_number_candidates(selected_ids),
        )
        explicit_marker_atoms = tuple(
            atom for atom in self.atoms if atom.atom_id in selected_ids and atom.text == "%"
        )

        def is_immediate_marker_neighbor(
            candidate: PositionedNumberCandidate,
            marker_atom: EvidenceAtom,
        ) -> bool:
            candidate_atoms = tuple(self.atoms[atom_id] for atom_id in candidate.atom_ids)
            candidate_bbox = _union_bbox(tuple(atom.bbox for atom in candidate_atoms))
            if (
                candidate_atoms[0].page_number != marker_atom.page_number
                or abs(_center_y(candidate_bbox) - _center_y(marker_atom.bbox))
                > min(_height(candidate_bbox), _height(marker_atom.bbox)) * 0.5
            ):
                return False
            if candidate_bbox[2] <= marker_atom.bbox[0]:
                left_edge = candidate_bbox[2]
                right_edge = marker_atom.bbox[0]
            elif marker_atom.bbox[2] <= candidate_bbox[0]:
                left_edge = marker_atom.bbox[2]
                right_edge = candidate_bbox[0]
            else:
                left_edge = right_edge = candidate_bbox[0]
            intervening_atoms = tuple(
                atom
                for atom in self.atoms
                if atom.atom_id not in candidate.atom_ids
                and atom.atom_id != marker_atom.atom_id
                and atom.atom_id in selected_ids
                and atom.page_number == marker_atom.page_number
                and abs(_center_y(atom.bbox) - _center_y(marker_atom.bbox))
                <= min(_height(atom.bbox), _height(marker_atom.bbox)) * 0.5
                and left_edge < (atom.bbox[0] + atom.bbox[2]) / 2 < right_edge
            )
            if any(atom.text != "%" for atom in intervening_atoms):
                return False
            marker_chain = tuple(
                sorted(
                    (
                        candidate_bbox,
                        marker_atom.bbox,
                        *(atom.bbox for atom in intervening_atoms),
                    ),
                    key=lambda bbox: (bbox[0] + bbox[2]) / 2,
                )
            )
            return all(
                right[0] - left[2] <= min(_height(left), _height(right)) * 0.6
                for left, right in pairwise(marker_chain)
            )

        def opposite_backing(left: EvidenceAtom, right: EvidenceAtom) -> bool:
            return (left.word is not None and right.glyph is not None) or (
                left.glyph is not None and right.word is not None
            )

        def represents_same_marker(left: EvidenceAtom, right: EvidenceAtom) -> bool:
            if left.page_number != right.page_number or not opposite_backing(left, right):
                return False
            left_center = (
                (left.bbox[0] + left.bbox[2]) / 2,
                (left.bbox[1] + left.bbox[3]) / 2,
            )
            right_center = (
                (right.bbox[0] + right.bbox[2]) / 2,
                (right.bbox[1] + right.bbox[3]) / 2,
            )
            return (
                left.bbox[0] <= right_center[0] <= left.bbox[2]
                and left.bbox[1] <= right_center[1] <= left.bbox[3]
            ) or (
                right.bbox[0] <= left_center[0] <= right.bbox[2]
                and right.bbox[1] <= left_center[1] <= right.bbox[3]
            )

        bound: list[PositionedPercentageCandidate] = []
        for number in number_candidates:
            embedded_atoms = tuple(
                self.atoms[atom_id]
                for atom_id in number.atom_ids
                if "%" in self.atoms[atom_id].text
            )
            neighboring_atoms = tuple(
                marker_atom
                for marker_atom in explicit_marker_atoms
                if is_immediate_marker_neighbor(number, marker_atom)
            )
            marker_slots: list[tuple[EvidenceAtom, set[int]]] = [
                (atom, {atom.atom_id})
                for atom in embedded_atoms
                for _ in range(atom.text.count("%"))
            ]
            for neighbor in neighboring_atoms:
                equivalent_slot = next(
                    (
                        slot
                        for slot in marker_slots
                        if neighbor.atom_id not in slot[1]
                        and represents_same_marker(slot[0], neighbor)
                    ),
                    None,
                )
                if equivalent_slot is None:
                    marker_slots.append((neighbor, {neighbor.atom_id}))
                else:
                    equivalent_slot[1].add(neighbor.atom_id)
            if marker_slots:
                bound.append(
                    PositionedPercentageCandidate(
                        number=number,
                        marker_atom_ids=frozenset(
                            atom_id
                            for _, slot_atom_ids in marker_slots
                            for atom_id in slot_atom_ids
                        ),
                        marker_count=len(marker_slots),
                    )
                )
        return tuple(bound)

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
    "PositionedNumberCandidate",
    "PositionedPercentageCandidate",
    "PositionedWholeNumberCandidate",
    "SemanticOwner",
]
