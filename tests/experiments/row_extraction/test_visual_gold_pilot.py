from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import fitz
import pytest
from pydantic import ValidationError

import experiments.row_extraction.visual_gold_pilot as pilot
from experiments.row_extraction.codecs import read_jsonl
from experiments.row_extraction.contracts import (
    ColumnBand,
    DatasetSplit,
    EvidenceAtom,
    FieldRole,
    FrozenRow,
    GoldRow,
    RowType,
)
from experiments.row_extraction.crops import CropRecord, PageContextRecord
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row

_EXPECTED_POPULATION_SIZE = 2_503
_SECRET_TEXT = "SECRET_ROW_TEXT"
_SECRET_FILENAME = "SECRET_FILENAME.pdf"
_SECRET_CANONICAL_VALUE = "SECRET_CANONICAL_VALUE"


def _atoms(
    row_index: int,
    count: int,
    *,
    source: Literal["digital", "ocr"] = "digital",
    mixed_source: bool = False,
) -> tuple[EvidenceAtom, ...]:
    result = []
    for atom_index in range(count):
        atom_source: Literal["digital", "ocr"] = "ocr" if source == "ocr" else "digital"
        if mixed_source and atom_index == 0:
            atom_source = "digital"
        result.append(
            evidence_atom(
                atom_id=f"atom-{row_index}-{atom_index}",
                text=f"{_SECRET_TEXT}-{row_index}-{atom_index}",
                source=atom_source,
            )
        )
    return tuple(result)


def _synthetic_row(
    row_index: int,
    row_type: RowType,
    atom_count: int,
    *,
    source: Literal["digital", "ocr"] = "digital",
    mixed_source: bool = False,
    document_index: int | None = None,
) -> FrozenRow:
    document_number = row_index if document_index is None else document_index
    return frozen_row(
        document_id=f"{document_number:064x}",
        row_id=f"synthetic-row-{row_index:04d}",
        source_pdf=Path("private") / _SECRET_FILENAME,
        baseline_type=row_type,
        atoms=_atoms(
            row_index,
            atom_count,
            source=source,
            mixed_source=mixed_source,
        ),
    )


def _feasible_population(*, mixed_ocr_row: bool = False) -> tuple[FrozenRow, ...]:
    rows: list[FrozenRow] = [
        _synthetic_row(0, RowType.STRUCTURAL, 4),
        _synthetic_row(1, RowType.AMBIGUOUS, 10),
    ]
    rows.extend(
        _synthetic_row(
            index,
            RowType.PRIMARY_TRANSACTION,
            2 if mixed_ocr_row and index == 2 else 10,
            source="ocr",
            mixed_source=mixed_ocr_row and index == 2,
        )
        for index in range(2, 12)
    )
    rows.extend(_synthetic_row(index, RowType.CONTINUATION, 1) for index in range(12, 27))
    rows.extend(_synthetic_row(index, RowType.CONTINUATION, 4) for index in range(27, 37))
    rows.extend(_synthetic_row(index, RowType.PRIMARY_TRANSACTION, 4) for index in range(37, 51))
    rows.extend(_synthetic_row(index, RowType.CONTINUATION, 10) for index in range(51, 74))
    rows.extend(
        _synthetic_row(index, RowType.PRIMARY_TRANSACTION, 10)
        for index in range(74, _EXPECTED_POPULATION_SIZE)
    )
    assert len(rows) == _EXPECTED_POPULATION_SIZE
    return tuple(rows)


def _assert_error_is_sanitized(error: BaseException) -> None:
    message = str(error)
    assert _SECRET_TEXT not in message
    assert _SECRET_FILENAME not in message
    assert _SECRET_CANONICAL_VALUE not in message


def test_selector_returns_exact_stable_stratified_membership() -> None:
    population = _feasible_population()

    selected = pilot.select_visual_gold_pilot(population)
    selected_after_permutation = pilot.select_visual_gold_pilot(tuple(reversed(population)))

    identities = tuple((row.document_id, row.row_id) for row in selected)
    type_counts = Counter(row.baseline_type for row in selected)
    source_counts = Counter(
        "ocr" if any(atom.source == "ocr" for atom in row.atoms) else "digital" for row in selected
    )
    atom_counts = Counter(
        "1-3" if len(row.atoms) <= 3 else "4-9" if len(row.atoms) <= 9 else "10+"
        for row in selected
    )
    document_counts = Counter(row.document_id for row in selected)

    assert pilot.PILOT_SELECTOR_VERSION == "visual-gold-v2-pilot-v1"
    assert len(selected) == 100
    assert len(set(identities)) == 100
    assert type_counts == {
        RowType.PRIMARY_TRANSACTION: 50,
        RowType.CONTINUATION: 48,
        RowType.STRUCTURAL: 1,
        RowType.AMBIGUOUS: 1,
    }
    assert source_counts == {"digital": 90, "ocr": 10}
    assert atom_counts["1-3"] >= 15
    assert atom_counts["4-9"] >= 25
    assert atom_counts["10+"] == 100 - atom_counts["1-3"] - atom_counts["4-9"]
    assert max(document_counts.values()) <= 2
    assert tuple(row.model_dump_json() for row in selected_after_permutation) == tuple(
        row.model_dump_json() for row in selected
    )


def test_selector_classifies_mixed_digital_and_ocr_atoms_as_ocr_source() -> None:
    selected = pilot.select_visual_gold_pilot(_feasible_population(mixed_ocr_row=True))

    selected_mixed_row = next(row for row in selected if row.row_id == "synthetic-row-0002")
    assert {atom.source for atom in selected_mixed_row.atoms} == {"digital", "ocr"}
    assert sum(any(atom.source == "ocr" for atom in row.atoms) for row in selected) == 10


def _with_nontraining_row(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    return (*rows[:-1], rows[-1].model_copy(update={"split": DatasetSplit.VALIDATION}))


def _with_empty_atoms(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    return (*rows[:-1], rows[-1].model_copy(update={"atoms": ()}))


def _with_duplicate_identity(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    duplicate = rows[-1].model_copy(
        update={
            "document_id": rows[-2].document_id,
            "row_id": rows[-2].row_id,
        }
    )
    return (*rows[:-1], duplicate)


def _without_structural_row(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    return (
        rows[0].model_copy(update={"baseline_type": RowType.PRIMARY_TRANSACTION}),
        *rows[1:],
    )


def _without_enough_small_continuations(
    rows: tuple[FrozenRow, ...],
) -> tuple[FrozenRow, ...]:
    replacement = rows[12].model_copy(update={"atoms": _atoms(12, 10)})
    return (*rows[:12], replacement, *rows[13:])


def _with_document_cap_conflict(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    one_document = "f" * 64
    return tuple(row.model_copy(update={"document_id": one_document}) for row in rows)


def _with_unknown_atom_source(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
    unknown_atom = rows[-1].atoms[0].model_copy(update={"source": "scanner"})
    replacement = rows[-1].model_copy(update={"atoms": (unknown_atom,)})
    return (*rows[:-1], replacement)


@pytest.mark.parametrize(
    "break_population",
    (
        _with_nontraining_row,
        _with_empty_atoms,
        _with_duplicate_identity,
        _without_structural_row,
        _without_enough_small_continuations,
        _with_document_cap_conflict,
        _with_unknown_atom_source,
    ),
)
def test_selector_fails_closed_with_sanitized_errors(
    break_population: Callable[[tuple[FrozenRow, ...]], tuple[FrozenRow, ...]],
) -> None:
    population = break_population(_feasible_population())

    with pytest.raises(pilot.PilotSelectionError) as exc_info:
        pilot.select_visual_gold_pilot(population)

    _assert_error_is_sanitized(exc_info.value)


def test_selector_rejects_incorrect_population_count_without_leaking_data() -> None:
    with pytest.raises(pilot.PilotSelectionError) as exc_info:
        pilot.select_visual_gold_pilot(_feasible_population()[:-1])

    _assert_error_is_sanitized(exc_info.value)


def _packet_row() -> FrozenRow:
    return frozen_row(
        document_id="a" * 64,
        row_id="opaque-row",
        source_pdf=Path("private") / _SECRET_FILENAME,
        page_number=3,
        bbox=(1.0, 2.0, 101.0, 22.0),
        baseline_type=RowType.CONTINUATION,
        atoms=(
            evidence_atom(
                atom_id="visible-atom",
                text=_SECRET_TEXT,
                bbox=(2.0, 3.0, 40.0, 10.0),
            ),
        ),
    ).model_copy(
        update={
            "previous_row_id": "previous-row",
            "next_row_id": "next-row",
            "column_bands": (
                ColumnBand(
                    index=0,
                    role=FieldRole.POSTING_DATE,
                    bbox=(0.0, 0.0, 25.0, 50.0),
                ),
            ),
        }
    )


def _crop_record(row: FrozenRow) -> CropRecord:
    return CropRecord(
        document_id=row.document_id,
        row_id=row.row_id,
        row_bbox=row.bbox,
        relative_path=f"aa/{row.document_id}/{row.row_id}.ppm",
        sha256="1" * 64,
        width=100,
        height=20,
    )


def _context_record(row: FrozenRow) -> PageContextRecord:
    return PageContextRecord(
        document_id=row.document_id,
        row_id=row.row_id,
        page_number=row.page_number,
        row_bbox=row.bbox,
        relative_path=f"aa/{row.document_id}/{row.row_id}.context.ppm",
        sha256="2" * 64,
        width=200,
        height=100,
    )


def test_review_packet_is_immutable_sanitized_and_uses_exact_artifact_paths() -> None:
    row = _packet_row()
    crop = _crop_record(row)
    context = _context_record(row)

    packet = pilot.build_review_packet(row, crop, context)
    serialized = packet.model_dump(mode="json")
    serialized_text = json.dumps(serialized, sort_keys=True)

    assert serialized == {
        "document_id": row.document_id,
        "row_id": row.row_id,
        "page_number": 3,
        "row_bbox": [1.0, 2.0, 101.0, 22.0],
        "previous_row_id": "previous-row",
        "next_row_id": "next-row",
        "column_boundaries": [[0.0, 0.0, 25.0, 50.0]],
        "atoms": [row.atoms[0].model_dump(mode="json")],
        "crop_relative_path": f"crops/{crop.relative_path}",
        "crop_sha256": "1" * 64,
        "page_context_relative_path": f"page-contexts/{context.relative_path}",
        "page_context_sha256": "2" * 64,
    }
    for forbidden in (
        "source_pdf",
        "baseline_type",
        "posting_date",
        "current_gold",
        "canonical_value",
        "accepted_value",
        "prediction",
        _SECRET_FILENAME,
    ):
        assert forbidden not in serialized_text
    with pytest.raises(ValidationError, match="frozen"):
        packet.row_id = "changed"


def test_review_decision_is_immutable_and_narrow() -> None:
    label = GoldRow(
        document_id="a" * 64,
        row_id="opaque-row",
        row_type=RowType.AMBIGUOUS,
        fields=(),
        ambiguous=True,
    )

    decision = pilot.VisualReviewDecision(label=label, page_context_used=False)

    assert decision.model_dump(mode="json") == {
        "label": label.model_dump(mode="json"),
        "page_context_used": False,
    }
    with pytest.raises(ValidationError, match="frozen"):
        decision.page_context_used = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        pilot.VisualReviewDecision.model_validate(
            {
                "label": label,
                "page_context_used": False,
                "prediction": _SECRET_CANONICAL_VALUE,
            }
        )


@pytest.mark.parametrize(
    ("changed_crop", "changed_context"),
    (
        ({"document_id": "b" * 64}, {}),
        ({"row_id": "different-row"}, {}),
        ({"row_bbox": (1.0, 2.0, 99.0, 22.0)}, {}),
        ({}, {"document_id": "b" * 64}),
        ({}, {"row_id": "different-row"}),
        ({}, {"page_number": 2}),
        ({}, {"row_bbox": (1.0, 2.0, 99.0, 22.0)}),
    ),
)
def test_review_packet_rejects_artifacts_for_a_different_fixed_row(
    changed_crop: dict[str, object],
    changed_context: dict[str, object],
) -> None:
    row = _packet_row()
    crop = _crop_record(row).model_copy(update=changed_crop)
    context = _context_record(row).model_copy(update=changed_context)

    with pytest.raises(ValueError) as exc_info:
        pilot.build_review_packet(row, crop, context)

    _assert_error_is_sanitized(exc_info.value)


@pytest.fixture(scope="module")
def materializer_population(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[FrozenRow, ...]:
    source = tmp_path_factory.mktemp("visual-gold-source") / "synthetic.pdf"
    with fitz.open() as document:
        document.new_page(width=20, height=20)
        document.save(source)
    return tuple(
        row.model_copy(
            update={
                "source_pdf": source,
                "page_number": 1,
                "bbox": (1.0, 1.0, 5.0, 5.0),
            }
        )
        for row in _feasible_population()
    )


@pytest.mark.parametrize("precreate", (False, True))
def test_materializer_writes_only_exact_evidence_and_canonical_packets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    materializer_population: tuple[FrozenRow, ...],
    precreate: bool,
) -> None:
    pilot_root = (tmp_path / "pilot-v1").resolve()
    if precreate:
        pilot_root.mkdir()
    real_selector = pilot.select_visual_gold_pilot
    selector_calls = 0

    def counting_selector(rows: tuple[FrozenRow, ...]) -> tuple[FrozenRow, ...]:
        nonlocal selector_calls
        selector_calls += 1
        return real_selector(rows)

    monkeypatch.setattr(pilot, "select_visual_gold_pilot", counting_selector)

    packets = pilot.materialize_visual_gold_pilot(materializer_population, pilot_root)

    assert selector_calls == 1
    assert len(packets) == 100
    assert tuple(read_jsonl(pilot_root / "packets.jsonl", pilot.VisualReviewPacket)) == packets
    relative_files = {
        path.relative_to(pilot_root).as_posix() for path in pilot_root.rglob("*") if path.is_file()
    }
    expected_files = {"packets.jsonl"}
    expected_files.update(packet.crop_relative_path for packet in packets)
    expected_files.update(packet.page_context_relative_path for packet in packets)
    assert relative_files == expected_files
    for packet in packets:
        crop_path = pilot_root / packet.crop_relative_path
        context_path = pilot_root / packet.page_context_relative_path
        assert hashlib.sha256(crop_path.read_bytes()).hexdigest() == packet.crop_sha256
        assert hashlib.sha256(context_path.read_bytes()).hexdigest() == packet.page_context_sha256


def test_materializer_interface_cannot_receive_gold_or_predictions() -> None:
    assert tuple(inspect.signature(pilot.materialize_visual_gold_pilot).parameters) == (
        "rows",
        "private_root",
    )


@pytest.mark.parametrize(
    "invalid_root",
    (
        Path("relative") / "pilot-v1",
        Path(__file__).resolve().parents[3] / "pilot-v1",
    ),
)
def test_materializer_rejects_nonprivate_roots_before_selection(
    invalid_root: Path,
    materializer_population: tuple[FrozenRow, ...],
) -> None:
    with pytest.raises(ValueError) as exc_info:
        pilot.materialize_visual_gold_pilot(materializer_population, invalid_root)

    _assert_error_is_sanitized(exc_info.value)
    assert not invalid_root.exists()


def test_materializer_rejects_nonempty_pilot_directory_without_writing_packets(
    tmp_path: Path,
    materializer_population: tuple[FrozenRow, ...],
) -> None:
    pilot_root = (tmp_path / "pilot-v1").resolve()
    pilot_root.mkdir()
    sentinel = pilot_root / _SECRET_FILENAME
    sentinel.write_text(_SECRET_CANONICAL_VALUE)

    with pytest.raises(ValueError) as exc_info:
        pilot.materialize_visual_gold_pilot(materializer_population, pilot_root)

    _assert_error_is_sanitized(exc_info.value)
    assert sentinel.read_text() == _SECRET_CANONICAL_VALUE
    assert tuple(pilot_root.iterdir()) == (sentinel,)
