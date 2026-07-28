from __future__ import annotations

from pathlib import Path

import fitz

from experiments.row_extraction.crops import render_reference_crop
from tests.experiments.row_extraction.factories import frozen_row


def _synthetic_pdf(path: Path) -> Path:
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.draw_rect((0.0, 0.0, 72.0, 24.0), color=(1.0, 0.0, 0.0), fill=(1.0, 0.0, 0.0))
        document.save(path)
    return path


def test_reference_crop_uses_exact_fixed_bbox_and_rgb_ppm(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(
        document_id="b" * 64,
        row_id="c" * 64,
        source_pdf=source,
        bbox=(0.0, 0.0, 72.0, 24.0),
    )

    record = render_reference_crop(row, tmp_path / "private-crops")
    crop_path = tmp_path / "private-crops" / record.relative_path
    first_bytes = crop_path.read_bytes()

    assert record.row_bbox == row.bbox
    assert record.document_id == row.document_id
    assert record.row_id == row.row_id
    assert record.relative_path == f"{row.document_id[:2]}/{row.document_id}/{row.row_id}.ppm"
    assert (record.width, record.height) == (300, 100)
    assert first_bytes.startswith(f"P6\n{record.width} {record.height}\n255\n".encode())
    assert len(first_bytes) == len(f"P6\n{record.width} {record.height}\n255\n".encode()) + (
        record.width * record.height * 3
    )


def test_reference_crop_is_byte_deterministic(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(
        document_id="b" * 64,
        row_id="c" * 64,
        source_pdf=source,
        bbox=(0.0, 0.0, 72.0, 24.0),
    )
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first = render_reference_crop(row, first_root)
    second = render_reference_crop(row, second_root)

    assert first.sha256 == second.sha256
    assert (first_root / first.relative_path).read_bytes() == (
        second_root / second.relative_path
    ).read_bytes()


def test_reference_crop_fractional_origin_has_no_device_envelope_padding(
    tmp_path: Path,
) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(
        document_id="b" * 64,
        row_id="d" * 64,
        source_pdf=source,
        bbox=(10.25, 20.5, 82.25, 44.5),
    )

    record = render_reference_crop(row, tmp_path / "private-crops")
    crop_path = tmp_path / "private-crops" / record.relative_path
    content = crop_path.read_bytes()
    header = f"P6\n{record.width} {record.height}\n255\n".encode()

    assert record.row_bbox == (10.25, 20.5, 82.25, 44.5)
    assert (record.width, record.height) == (300, 100)
    assert len(content) == len(header) + (300 * 100 * 3)
