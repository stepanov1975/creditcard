from pathlib import Path
from typing import Literal

from experiments.row_extraction.contracts import (
    BBox,
    DatasetSplit,
    EvidenceAtom,
    FrozenRow,
    RowType,
)


def evidence_atom(
    *,
    atom_id: str = "atom-1",
    text: str = "SYNTHETIC MERCHANT",
    bbox: BBox = (10.0, 20.0, 110.0, 30.0),
    source: Literal["digital", "ocr"] = "digital",
    confidence: float = 1.0,
    column_index: int | None = 0,
) -> EvidenceAtom:
    return EvidenceAtom(
        atom_id=atom_id,
        text=text,
        bbox=bbox,
        source=source,
        confidence=confidence,
        column_index=column_index,
    )


def frozen_row(
    *,
    document_id: str = "0" * 64,
    row_id: str = "row-1",
    split: DatasetSplit = DatasetSplit.TRAIN,
    source_pdf: Path = Path("private/source.pdf"),
    page_number: int = 1,
    bbox: BBox = (0.0, 10.0, 200.0, 40.0),
    baseline_type: RowType = RowType.PRIMARY_TRANSACTION,
    atoms: tuple[EvidenceAtom, ...] | None = None,
) -> FrozenRow:
    return FrozenRow(
        document_id=document_id,
        row_id=row_id,
        split=split,
        source_pdf=source_pdf,
        page_number=page_number,
        bbox=bbox,
        baseline_type=baseline_type,
        column_bands=(),
        atoms=atoms if atoms is not None else (evidence_atom(),),
        render_version="synthetic-v1",
    )
