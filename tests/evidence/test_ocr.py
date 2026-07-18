from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import fitz
import pytest

from ccparser.evidence.ocr import (
    OCR_LANGUAGES,
    OCR_PREPROCESSING_VERSION,
    TesseractOcr,
    parse_tesseract_tsv,
    tesseract_command,
)


def _save_blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page(width=144, height=216)
    document.save(path)
    document.close()


def test_tesseract_command_is_deterministic_and_local() -> None:
    assert tesseract_command() == (
        "tesseract",
        "stdin",
        "stdout",
        "-l",
        "heb+eng",
        "--oem",
        "1",
        "--psm",
        "6",
        "tsv",
    )


def test_parse_tsv_maps_pixels_to_clipped_pdf_points() -> None:
    tsv = "\n".join(
        (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t30\t60\t90\t30\t87.5\tCafe\u0301",
            "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t-1\tIgnored",
        )
    )

    words = parse_tesseract_tsv(tsv, dpi=300, clip=(12.0, 24.0, 120.0, 144.0))

    assert len(words) == 1
    assert words[0].text == "Caf\u00e9"
    assert words[0].bbox == pytest.approx((19.2, 38.4, 40.8, 45.6))
    assert words[0].source == "ocr"
    assert words[0].confidence == 0.875


def test_cache_key_contains_every_extraction_dimension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version_output = b"tesseract 5.7.1\n synthetic build details\n"

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        assert command == ("tesseract", "--version")
        return subprocess.CompletedProcess(command, 0, version_output, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = TesseractOcr(tmp_path / "cache", dpi=300)
    clip = (1.25, 2.5, 101.25, 202.5)

    key = provider.cache_key("b" * 64, page_index=3, clip=clip)

    payload = {
        "clip": list(clip),
        "dpi": 300,
        "languages": OCR_LANGUAGES,
        "page_index": 3,
        "preprocessing_version": OCR_PREPROCESSING_VERSION,
        "source_sha256": "b" * 64,
        "tesseract_version": "tesseract 5.7.1",
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert key == hashlib.sha256(serialized).hexdigest()


def test_ocr_renders_requested_clip_runs_tesseract_and_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "blank.pdf"
    _save_blank_pdf(path)
    commands: list[tuple[str, ...]] = []
    image_inputs: list[bytes] = []
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t25\t50\t75\t25\t94\tRegion\n"
    )

    def fake_run(
        command: tuple[str, ...],
        *,
        input: bytes | None = None,
        **_: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        if command == ("tesseract", "--version"):
            return subprocess.CompletedProcess(command, 0, b"tesseract 5.7.1\n", b"")
        image_inputs.append(input or b"")
        return subprocess.CompletedProcess(command, 0, tsv, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    clip = (12.0, 24.0, 132.0, 192.0)
    source_sha256 = "c" * 64
    first_provider = TesseractOcr(tmp_path / "cache")

    first = first_provider.extract_words(path, source_sha256, page_index=0, clip=clip)
    second_provider = TesseractOcr(tmp_path / "cache")
    second = second_provider.extract_words(path, source_sha256, page_index=0, clip=clip)

    assert first == second
    assert first[0].bbox == pytest.approx((18.0, 36.0, 36.0, 42.0))
    assert commands.count(tesseract_command()) == 1
    assert commands.count(("tesseract", "--version")) == 2
    assert len(image_inputs) == 1
    assert image_inputs[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert len(tuple((tmp_path / "cache").glob("*.tsv"))) == 1
