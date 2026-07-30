"""Build model targets from validated fixed-row annotations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from experiments.row_extraction.contracts import FieldRole, FrozenRow, GoldRow, RowType


class TargetEncodingError(ValueError):
    """A reviewed annotation cannot be represented by the shared targets."""


class TargetDisposition(StrEnum):
    """How one reviewed field contributes to extraction supervision."""

    SUPERVISED = "supervised"
    DERIVED = "derived"
    MASKED = "masked"


@dataclass(frozen=True)
class EncodedTargets:
    """Row and atom targets shared by evidence-grounded extractors."""

    row_type: RowType
    row_type_eligible: bool
    atom_ids: tuple[str, ...]
    bio_tags: tuple[str, ...]
    atom_loss_mask: tuple[bool, ...]
    field_supervision_eligible: bool
    dispositions: tuple[tuple[FieldRole, TargetDisposition], ...]


def encode_targets(row: FrozenRow, gold: GoldRow) -> EncodedTargets:
    """Encode one validated annotation without learning deterministic fields."""

    if (row.document_id, row.row_id) != (gold.document_id, gold.row_id):
        raise TargetEncodingError("gold row identity differs from frozen row")

    atom_ids = tuple(atom.atom_id for atom in row.atoms)
    positions = {atom_id: index for index, atom_id in enumerate(atom_ids)}
    if len(positions) != len(atom_ids):
        raise TargetEncodingError("frozen evidence atom IDs must be unique")

    tags = ["O"] * len(atom_ids)
    atom_loss_mask = [not gold.ambiguous] * len(atom_ids)
    occupied: set[int] = set()
    dispositions: list[tuple[FieldRole, TargetDisposition]] = []
    for field in gold.fields:
        if field.role is FieldRole.KIND:
            dispositions.append((field.role, TargetDisposition.DERIVED))
            continue
        if not field.atom_ids:
            dispositions.append((field.role, TargetDisposition.MASKED))
            continue
        try:
            indexes = tuple(positions[atom_id] for atom_id in field.atom_ids)
        except KeyError:
            raise TargetEncodingError("gold atom is absent from frozen row") from None
        if indexes != tuple(range(indexes[0], indexes[0] + len(indexes))):
            for index in indexes:
                atom_loss_mask[index] = False
            dispositions.append((field.role, TargetDisposition.MASKED))
            continue
        if occupied.intersection(indexes):
            raise TargetEncodingError("learned fields overlap on frozen atoms")
        occupied.update(indexes)
        for offset, index in enumerate(indexes):
            prefix = "B" if offset == 0 else "I"
            tags[index] = f"{prefix}:{field.role.value}"
        dispositions.append((field.role, TargetDisposition.SUPERVISED))

    return EncodedTargets(
        row_type=gold.row_type,
        row_type_eligible=not gold.ambiguous,
        atom_ids=atom_ids,
        bio_tags=tuple(tags),
        atom_loss_mask=tuple(atom_loss_mask),
        field_supervision_eligible=any(atom_loss_mask),
        dispositions=tuple(sorted(dispositions, key=lambda item: item[0].value)),
    )


__all__ = [
    "EncodedTargets",
    "TargetDisposition",
    "TargetEncodingError",
    "encode_targets",
]
