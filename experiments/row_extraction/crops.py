"""Deterministic reference crops for the frozen row-image comparison."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.

from experiments.row_extraction.contracts import BBox, FrozenRow, _FrozenModel

_REFERENCE_DPI = 300
_POINTS_PER_INCH = 72


class CropRenderError(ValueError):
    """A fixed row cannot be rendered without changing its source geometry."""


class CropRecord(_FrozenModel):
    """Private index entry for one exact frozen-row reference image."""

    document_id: str
    row_id: str
    row_bbox: BBox
    relative_path: str
    sha256: str
    width: int
    height: int


def _relative_crop_path(row: FrozenRow) -> Path:
    return Path(row.document_id[:2]) / row.document_id / f"{row.row_id}.ppm"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
        temporary_path.replace(path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def render_reference_crop(row: FrozenRow, private_root: Path) -> CropRecord:
    """Render one unpadded, 300-DPI RGB PPM from the exact fixed bbox."""

    try:
        with fitz.open(row.source_pdf) as document:
            if row.page_number > document.page_count:
                raise CropRenderError("fixed row page is absent from source PDF")
            page = document[row.page_number - 1]
            clip = fitz.Rect(row.bbox)
            if clip.is_empty or clip.is_infinite or not page.rect.contains(clip):
                raise CropRenderError("fixed row bbox is outside source page")
            scale = _REFERENCE_DPI / _POINTS_PER_INCH
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB,
                alpha=False,
                clip=clip,
            )
            content = pixmap.tobytes("ppm")
            width = pixmap.width
            height = pixmap.height
    except CropRenderError:
        raise
    except Exception:
        raise CropRenderError("fixed row crop rendering failed") from None

    relative_path = _relative_crop_path(row)
    _atomic_write(private_root / relative_path, content)
    return CropRecord(
        document_id=row.document_id,
        row_id=row.row_id,
        row_bbox=row.bbox,
        relative_path=relative_path.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        width=width,
        height=height,
    )


__all__ = ["CropRecord", "CropRenderError", "render_reference_crop"]
