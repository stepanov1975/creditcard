"""Local Tesseract OCR with deterministic rendering and content-addressed caching."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import cast

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.

from ccparser.evidence.models import BBox, Point, Word

OCR_LANGUAGES = "heb+eng"
OCR_PREPROCESSING_VERSION = "raw-pixmap-v1"
OCR_PIPELINE_VERSION = "tesseract-tsv-v1"
TESSERACT_VERSION_TIMEOUT_SECONDS = 10.0
TESSERACT_RECOGNITION_TIMEOUT_SECONDS = 120.0


class OcrError(RuntimeError):
    """A typed failure from local OCR version detection or recognition."""


def tesseract_command() -> tuple[str, ...]:
    """Return the fixed local OCR command without shell interpretation."""

    return (
        "tesseract",
        "stdin",
        "stdout",
        "-l",
        OCR_LANGUAGES,
        "--oem",
        "1",
        "--psm",
        "6",
        "tsv",
    )


def parse_tesseract_tsv(
    tsv: str | bytes,
    *,
    dpi: int,
    origin: Point,
) -> tuple[Word, ...]:
    """Map Tesseract pixels from the actual render origin into display points."""

    if dpi <= 0:
        raise ValueError("dpi must be positive")
    text = tsv.decode("utf-8", errors="replace") if isinstance(tsv, bytes) else tsv
    point_scale = 72.0 / dpi
    offset_x, offset_y = origin
    words: list[Word] = []
    for row in text.splitlines():
        fields = row.split("\t", 11)
        if len(fields) != 12:
            continue
        try:
            left = int(fields[6])
            top = int(fields[7])
            width = int(fields[8])
            height = int(fields[9])
            confidence = float(fields[10])
        except ValueError:
            continue
        word_text = unicodedata.normalize("NFC", fields[11].strip())
        if confidence < 0 or width <= 0 or height <= 0 or not word_text:
            continue
        words.append(
            Word(
                text=word_text,
                bbox=(
                    offset_x + left * point_scale,
                    offset_y + top * point_scale,
                    offset_x + (left + width) * point_scale,
                    offset_y + (top + height) * point_scale,
                ),
                source="ocr",
                confidence=min(confidence / 100.0, 1.0),
            )
        )
    return tuple(words)


class TesseractOcr:
    """Render PDF pages or clips and cache Tesseract TSV output by all inputs."""

    def __init__(
        self,
        cache_dir: str | Path,
        dpi: int = 300,
        *,
        command: tuple[str, ...] | None = None,
    ) -> None:
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        self.cache_dir = Path(cache_dir)
        self.dpi = dpi
        self.command = command or tesseract_command()
        self._version: str | None = None

    def _tesseract_version(self) -> str:
        if self._version is None:
            try:
                completed = subprocess.run(
                    (self.command[0], "--version"),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=TESSERACT_VERSION_TIMEOUT_SECONDS,
                )
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
                raise OcrError("Tesseract version detection failed") from error
            first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()
            self._version = first_line[0].strip() if first_line else "unknown"
        return self._version

    def cache_key(self, source_sha256: str, page_index: int, clip: BBox | None = None) -> str:
        """Hash every input that can change the rendered OCR result."""

        payload = {
            "clip": list(clip) if clip is not None else None,
            "command": list(self.command),
            "dpi": self.dpi,
            "languages": OCR_LANGUAGES,
            "page_index": page_index,
            "pipeline_version": OCR_PIPELINE_VERSION,
            "preprocessing_version": OCR_PREPROCESSING_VERSION,
            "source_sha256": source_sha256,
            "tesseract_version": self._tesseract_version(),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(serialized).hexdigest()

    def _render(self, pdf_bytes: bytes, page_index: int, clip: BBox | None) -> tuple[bytes, Point]:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(
                dpi=self.dpi,
                clip=fitz.Rect(clip) if clip is not None else None,
                alpha=False,
            )
            point_scale = 72.0 / self.dpi
            origin = (float(pixmap.x) * point_scale, float(pixmap.y) * point_scale)
            return cast(bytes, pixmap.tobytes("png")), origin

    def _recognize(self, image: bytes) -> bytes:
        try:
            completed = subprocess.run(
                self.command,
                input=image,
                check=True,
                capture_output=True,
                timeout=TESSERACT_RECOGNITION_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
            raise OcrError("Tesseract recognition failed") from error
        return completed.stdout

    def _write_cache(self, cache_path: Path, tsv: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.cache_dir,
                prefix=".ocr-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(tsv)
                temporary_path = Path(temporary.name)
            temporary_path.replace(cache_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]:
        """OCR an explicitly requested zero-based page or clip and return word boxes."""

        image, origin = self._render(pdf_bytes, page_index, clip)
        cache_path = self.cache_dir / f"{self.cache_key(source_sha256, page_index, clip)}.tsv"
        if cache_path.is_file():
            tsv = cache_path.read_bytes()
        else:
            tsv = self._recognize(image)
            self._write_cache(cache_path, tsv)
        return parse_tesseract_tsv(tsv, dpi=self.dpi, origin=origin)
