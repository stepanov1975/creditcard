from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

import experiments.row_extraction.crops as crops
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


def test_page_context_renders_exact_source_page_as_150_dpi_rgb_ppm(
    tmp_path: Path,
) -> None:
    source = _synthetic_pdf(tmp_path / "sensitive-source-name.pdf")
    row = frozen_row(
        document_id="d" * 64,
        row_id="opaque-row-7",
        source_pdf=source,
        bbox=(10.25, 20.5, 82.25, 44.5),
    )

    record = crops.render_page_context(row, tmp_path / "page-contexts")
    context_path = tmp_path / "page-contexts" / record.relative_path
    content = context_path.read_bytes()
    header = f"P6\n{record.width} {record.height}\n255\n".encode()

    assert record.document_id == row.document_id
    assert record.row_id == row.row_id
    assert record.page_number == 1
    assert record.row_bbox == (10.25, 20.5, 82.25, 44.5)
    assert record.relative_path == f"dd/{row.document_id}/{row.row_id}.context.ppm"
    assert (record.width, record.height) == (417, 209)
    assert content.startswith(header)
    assert len(content) == len(header) + (417 * 209 * 3)
    assert record.sha256 == hashlib.sha256(content).hexdigest()


def test_page_context_is_byte_deterministic(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(
        document_id="e" * 64,
        row_id="opaque-row-8",
        source_pdf=source,
        bbox=(0.0, 0.0, 72.0, 24.0),
    )
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first = crops.render_page_context(row, first_root)
    second = crops.render_page_context(row, second_root)

    assert first == second
    assert (first_root / first.relative_path).read_bytes() == (
        second_root / second.relative_path
    ).read_bytes()


def test_page_context_does_not_replace_reference_crop_in_same_root(
    tmp_path: Path,
) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(
        document_id="f" * 64,
        row_id="opaque-row-9",
        source_pdf=source,
        bbox=(0.0, 0.0, 72.0, 24.0),
    )
    artifact_root = tmp_path / "artifacts"

    crop = render_reference_crop(row, artifact_root)
    crop_path = artifact_root / crop.relative_path
    original_crop_bytes = crop_path.read_bytes()
    context = crops.render_page_context(row, artifact_root)
    context_path = artifact_root / context.relative_path

    assert crop.relative_path != context.relative_path
    assert crop_path.read_bytes() == original_crop_bytes
    assert context_path.read_bytes() != original_crop_bytes
    assert (crop.width, crop.height) == (300, 100)
    assert (context.width, context.height) == (417, 209)


def test_page_context_rejects_absent_source_page(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(source_pdf=source, page_number=2)

    with pytest.raises(crops.CropRenderError, match="page is absent"):
        crops.render_page_context(row, tmp_path / "page-contexts")


def test_page_context_rejects_invalid_row_bbox(tmp_path: Path) -> None:
    source = _synthetic_pdf(tmp_path / "synthetic.pdf")
    row = frozen_row(source_pdf=source, bbox=(-1.0, 0.0, 72.0, 24.0))

    with pytest.raises(crops.CropRenderError, match="bbox is outside source page"):
        crops.render_page_context(row, tmp_path / "page-contexts")


def test_page_context_normalizes_source_render_failure(tmp_path: Path) -> None:
    source = tmp_path / "unreadable.pdf"
    source.write_bytes(b"not a PDF")
    row = frozen_row(source_pdf=source)

    with pytest.raises(crops.CropRenderError, match="page context rendering failed"):
        crops.render_page_context(row, tmp_path / "page-contexts")
