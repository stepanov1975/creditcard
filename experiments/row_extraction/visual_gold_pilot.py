"""Deterministic selection and sanitized artifacts for the visual-gold pilot."""

from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.contracts import (
    BBox,
    DatasetSplit,
    EvidenceAtom,
    FrozenRow,
    GoldRow,
    RowType,
    _FrozenModel,
)
from experiments.row_extraction.crops import (
    CropRecord,
    PageContextRecord,
    render_page_context,
    render_reference_crop,
)

PILOT_SELECTOR_VERSION = "visual-gold-v2-pilot-v1"
_EXPECTED_POPULATION_SIZE = 2_503
_DOCUMENT_ROW_CAP = 2
_WORKTREE = Path(__file__).resolve().parents[2]


class PilotSelectionError(ValueError):
    """The frozen training population cannot satisfy the locked pilot design."""


class VisualReviewPacket(_FrozenModel):
    """Sanitized source evidence for one blind visual review."""

    document_id: str
    row_id: str
    page_number: int
    row_bbox: BBox
    previous_row_id: str | None
    next_row_id: str | None
    column_boundaries: tuple[BBox, ...]
    atoms: tuple[EvidenceAtom, ...]
    crop_relative_path: str
    crop_sha256: str
    page_context_relative_path: str
    page_context_sha256: str


class VisualReviewDecision(_FrozenModel):
    """One blind label plus whether the reviewer needed page context."""

    label: GoldRow
    page_context_used: bool


def build_review_packet(
    row: FrozenRow,
    crop: CropRecord,
    context: PageContextRecord,
) -> VisualReviewPacket:
    """Remove hidden selection data from matching rendered row evidence."""

    identity = (row.document_id, row.row_id)
    if (
        (crop.document_id, crop.row_id) != identity
        or crop.row_bbox != row.bbox
        or (context.document_id, context.row_id) != identity
        or context.page_number != row.page_number
        or context.row_bbox != row.bbox
    ):
        raise ValueError("review artifacts do not match fixed row")
    return VisualReviewPacket(
        document_id=row.document_id,
        row_id=row.row_id,
        page_number=row.page_number,
        row_bbox=row.bbox,
        previous_row_id=row.previous_row_id,
        next_row_id=row.next_row_id,
        column_boundaries=tuple(band.bbox for band in row.column_bands),
        atoms=row.atoms,
        crop_relative_path=f"crops/{crop.relative_path}",
        crop_sha256=crop.sha256,
        page_context_relative_path=f"page-contexts/{context.relative_path}",
        page_context_sha256=context.sha256,
    )


def _stable_key(row: FrozenRow) -> tuple[bytes, str, str]:
    content = f"{PILOT_SELECTOR_VERSION}\0{row.document_id}\0{row.row_id}".encode()
    return hashlib.sha256(content).digest(), row.document_id, row.row_id


def _source_class(row: FrozenRow) -> str:
    if any(atom.source == "ocr" for atom in row.atoms):
        return "ocr"
    return "digital"


def _validated_population(rows: Sequence[FrozenRow]) -> tuple[FrozenRow, ...]:
    if len(rows) != _EXPECTED_POPULATION_SIZE:
        raise PilotSelectionError("pilot population count mismatch")

    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.split is not DatasetSplit.TRAIN:
            raise PilotSelectionError("pilot population contains nontraining rows")
        identity = (row.document_id, row.row_id)
        if identity in seen:
            raise PilotSelectionError("pilot population contains duplicate row identity")
        seen.add(identity)
        if not row.atoms or any(atom.source not in {"digital", "ocr"} for atom in row.atoms):
            raise PilotSelectionError("pilot population contains invalid row atoms")

    return tuple(sorted(rows, key=_stable_key))


def _select_stage(
    ordered: tuple[FrozenRow, ...],
    required: int,
    eligible: Callable[[FrozenRow], bool],
    selected: list[FrozenRow],
    selected_identities: set[tuple[str, str]],
    document_counts: Counter[str],
) -> None:
    added = 0
    for row in ordered:
        identity = (row.document_id, row.row_id)
        if (
            identity in selected_identities
            or document_counts[row.document_id] >= _DOCUMENT_ROW_CAP
            or not eligible(row)
        ):
            continue
        selected.append(row)
        selected_identities.add(identity)
        document_counts[row.document_id] += 1
        added += 1
        if added == required:
            return
    raise PilotSelectionError("pilot stage quota unsatisfied")


def _is_digital(row: FrozenRow) -> bool:
    return _source_class(row) == "digital"


def _is_ocr_primary(row: FrozenRow) -> bool:
    return row.baseline_type is RowType.PRIMARY_TRANSACTION and _source_class(row) == "ocr"


def _is_digital_type_with_atom_range(
    row: FrozenRow,
    row_type: RowType,
    minimum_atoms: int,
    maximum_atoms: int | None,
) -> bool:
    atom_count = len(row.atoms)
    return (
        row.baseline_type is row_type
        and _is_digital(row)
        and atom_count >= minimum_atoms
        and (maximum_atoms is None or atom_count <= maximum_atoms)
    )


def _require_final_invariants(selected: list[FrozenRow]) -> None:
    type_counts = Counter(row.baseline_type for row in selected)
    source_counts = Counter(_source_class(row) for row in selected)
    small_atoms = sum(1 <= len(row.atoms) <= 3 for row in selected)
    medium_atoms = sum(4 <= len(row.atoms) <= 9 for row in selected)
    document_counts = Counter(row.document_id for row in selected)
    if (
        len(selected) != 100
        or type_counts
        != {
            RowType.PRIMARY_TRANSACTION: 50,
            RowType.CONTINUATION: 48,
            RowType.STRUCTURAL: 1,
            RowType.AMBIGUOUS: 1,
        }
        or source_counts != {"ocr": 10, "digital": 90}
        or small_atoms < 15
        or medium_atoms < 25
        or max(document_counts.values(), default=0) > _DOCUMENT_ROW_CAP
    ):
        raise PilotSelectionError("selected pilot invariants unsatisfied")


def select_visual_gold_pilot(
    rows: Sequence[FrozenRow],
) -> tuple[FrozenRow, ...]:
    """Select the locked, stratified 100-row training pilot."""

    ordered = _validated_population(rows)
    selected: list[FrozenRow] = []
    selected_identities: set[tuple[str, str]] = set()
    document_counts: Counter[str] = Counter()

    stages: tuple[tuple[int, Callable[[FrozenRow], bool]], ...] = (
        (
            1,
            lambda row: row.baseline_type is RowType.STRUCTURAL and _is_digital(row),
        ),
        (
            1,
            lambda row: row.baseline_type is RowType.AMBIGUOUS and _is_digital(row),
        ),
        (10, _is_ocr_primary),
        (
            15,
            lambda row: _is_digital_type_with_atom_range(row, RowType.CONTINUATION, 1, 3),
        ),
        (
            10,
            lambda row: _is_digital_type_with_atom_range(row, RowType.CONTINUATION, 4, 9),
        ),
        (
            14,
            lambda row: _is_digital_type_with_atom_range(row, RowType.PRIMARY_TRANSACTION, 4, 9),
        ),
        (
            23,
            lambda row: _is_digital_type_with_atom_range(row, RowType.CONTINUATION, 10, None),
        ),
        (
            26,
            lambda row: _is_digital_type_with_atom_range(
                row, RowType.PRIMARY_TRANSACTION, 10, None
            ),
        ),
    )
    for required, eligible in stages:
        _select_stage(
            ordered,
            required,
            eligible,
            selected,
            selected_identities,
            document_counts,
        )

    _require_final_invariants(selected)
    return tuple(sorted(selected, key=_stable_key))


def _require_empty_private_pilot_root(private_root: Path) -> Path:
    if (
        not private_root.is_absolute()
        or private_root.name != "pilot-v1"
        or private_root.is_symlink()
    ):
        raise ValueError("pilot output root is invalid")
    resolved = private_root.resolve(strict=False)
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError("pilot output root must be new or empty")
    if resolved.is_relative_to(_WORKTREE):
        try:
            completed = subprocess.run(
                ("git", "check-ignore", "--quiet", str(resolved)),
                cwd=_WORKTREE,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise ValueError("pilot output privacy could not be verified") from None
        if completed.returncode != 0:
            raise ValueError("pilot output root is not ignored")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def materialize_visual_gold_pilot(
    rows: Sequence[FrozenRow],
    private_root: Path,
) -> tuple[VisualReviewPacket, ...]:
    """Render and atomically record the locked private pilot evidence."""

    pilot_root = _require_empty_private_pilot_root(private_root)
    selected = select_visual_gold_pilot(rows)
    packets: list[VisualReviewPacket] = []
    for row in selected:
        crop = render_reference_crop(row, pilot_root / "crops")
        context = render_page_context(row, pilot_root / "page-contexts")
        packets.append(build_review_packet(row, crop, context))
    result = tuple(packets)
    write_jsonl(pilot_root / "packets.jsonl", result)
    return result


__all__ = [
    "PILOT_SELECTOR_VERSION",
    "PilotSelectionError",
    "VisualReviewDecision",
    "VisualReviewPacket",
    "build_review_packet",
    "materialize_visual_gold_pilot",
    "select_visual_gold_pilot",
]
