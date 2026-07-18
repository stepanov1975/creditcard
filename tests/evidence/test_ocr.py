from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from typing import Any

import fitz
import pytest

import ccparser.evidence.ocr as ocr_module
from ccparser.evidence.ocr import (
    OCR_LANGUAGES,
    OCR_PREPROCESSING_VERSION,
    TesseractOcr,
    parse_tesseract_tsv,
    tesseract_command,
)
from ccparser.evidence.pdf import extract_pdf


def _save_blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page(width=144, height=216)
    document.save(path)
    document.close()


def _save_rotated_partial_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=120, height=200)
    page.insert_text((20, 40), "Rotate", fontsize=11)
    page.set_rotation(90)
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


def test_ocr_exposes_a_typed_runtime_error() -> None:
    error_type = getattr(ocr_module, "OcrError", object)

    assert issubclass(error_type, RuntimeError)


def test_ocr_uses_named_version_and_recognition_timeouts() -> None:
    assert getattr(ocr_module, "TESSERACT_VERSION_TIMEOUT_SECONDS", None) == 10.0
    assert getattr(ocr_module, "TESSERACT_RECOGNITION_TIMEOUT_SECONDS", None) == 120.0


def test_ocr_exposes_command_configuration_and_pipeline_version() -> None:
    constructor = inspect.signature(TesseractOcr)

    assert "command" in constructor.parameters
    assert getattr(ocr_module, "OCR_PIPELINE_VERSION", None) == "tesseract-tsv-v1"


@pytest.mark.parametrize(
    "failure",
    (
        subprocess.TimeoutExpired(("tesseract", "--version"), timeout=10.0),
        subprocess.CalledProcessError(2, ("tesseract", "--version")),
    ),
)
def test_version_detection_wraps_subprocess_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: subprocess.SubprocessError,
) -> None:
    observed_timeouts: list[float | None] = []

    def fake_run(command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed_timeouts.append(kwargs.get("timeout"))
        raise failure

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = TesseractOcr(tmp_path / "cache")

    with pytest.raises(ocr_module.OcrError, match="version detection failed") as caught:
        provider.cache_key("e" * 64, page_index=0)

    assert caught.value.__cause__ is failure
    assert observed_timeouts == [10.0]


@pytest.mark.parametrize(
    "failure",
    (
        subprocess.TimeoutExpired(tesseract_command(), timeout=120.0),
        subprocess.CalledProcessError(2, tesseract_command()),
    ),
)
def test_recognition_wraps_subprocess_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: subprocess.SubprocessError,
) -> None:
    path = tmp_path / "recognition.pdf"
    _save_blank_pdf(path)
    observed_timeouts: list[float | None] = []

    def fake_run(command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed_timeouts.append(kwargs.get("timeout"))
        if command == ("tesseract", "--version"):
            return subprocess.CompletedProcess(command, 0, b"tesseract 5.7.1\n", b"")
        raise failure

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = TesseractOcr(tmp_path / "cache")

    with pytest.raises(ocr_module.OcrError, match="recognition failed") as caught:
        provider.extract_words(path.read_bytes(), "f" * 64, page_index=0)

    assert caught.value.__cause__ is failure
    assert observed_timeouts == [10.0, 120.0]


def test_parse_tsv_maps_pixels_to_clipped_pdf_points() -> None:
    tsv = "\n".join(
        (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t30\t60\t90\t30\t87.5\tCafe\u0301",
            "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t-1\tIgnored",
        )
    )

    words = parse_tesseract_tsv(tsv, dpi=300, origin=(12.0, 24.0))

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
        "command": list(tesseract_command()),
        "dpi": 300,
        "languages": OCR_LANGUAGES,
        "page_index": 3,
        "pipeline_version": "tesseract-tsv-v1",
        "preprocessing_version": OCR_PREPROCESSING_VERSION,
        "source_sha256": "b" * 64,
        "tesseract_version": "tesseract 5.7.1",
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert key == hashlib.sha256(serialized).hexdigest()


def test_cache_key_changes_with_configured_ocr_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b"tesseract 5.7.1\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    default = TesseractOcr(tmp_path / "default")
    alternate_command = (*tesseract_command()[:-2], "11", "tsv")
    alternate = TesseractOcr(tmp_path / "alternate", command=alternate_command)

    default_key = default.cache_key("1" * 64, page_index=0)
    alternate_key = alternate.cache_key("1" * 64, page_index=0)

    assert default_key != alternate_key


def test_configured_ocr_command_is_used_for_recognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "configured.pdf"
    _save_blank_pdf(path)
    alternate_command = (*tesseract_command()[:-2], "11", "tsv")
    commands: list[tuple[str, ...]] = []
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t0\t0\t25\t25\t90\tConfigured\n"
    )

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        output = b"tesseract 5.7.1\n" if command == ("tesseract", "--version") else tsv
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = TesseractOcr(tmp_path / "cache", command=alternate_command)

    words = provider.extract_words(path.read_bytes(), "2" * 64, page_index=0)

    assert words[0].text == "Configured"
    assert commands == [("tesseract", "--version"), alternate_command]


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

    first = first_provider.extract_words(path.read_bytes(), source_sha256, page_index=0, clip=clip)
    second_provider = TesseractOcr(tmp_path / "cache")
    second = second_provider.extract_words(
        path.read_bytes(), source_sha256, page_index=0, clip=clip
    )

    assert first == second
    assert first[0].bbox == pytest.approx((18.0, 36.0, 36.0, 42.0))
    assert commands.count(tesseract_command()) == 1
    assert commands.count(("tesseract", "--version")) == 2
    assert len(image_inputs) == 1
    assert image_inputs[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert len(tuple((tmp_path / "cache").glob("*.tsv"))) == 1


@pytest.mark.parametrize(
    ("clip", "expected_origin"),
    (
        ((12.13, 24.13, 132.13, 192.13), (12.0, 24.0)),
        ((-12.13, -24.13, 60.13, 72.13), (0.0, 0.0)),
    ),
)
def test_ocr_maps_words_from_actual_rendered_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clip: tuple[float, float, float, float],
    expected_origin: tuple[float, float],
) -> None:
    path = tmp_path / "clipped.pdf"
    _save_blank_pdf(path)
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t0\t0\t25\t25\t90\tOrigin\n"
    )

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        output = b"tesseract 5.7.1\n" if command == ("tesseract", "--version") else tsv
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = TesseractOcr(tmp_path / "cache")

    words = provider.extract_words(path.read_bytes(), "d" * 64, page_index=0, clip=clip)

    assert words[0].bbox == pytest.approx(
        (*expected_origin, expected_origin[0] + 6.0, expected_origin[1] + 6.0)
    )


def test_rotated_partial_page_preserves_digital_and_ocr_words_in_display_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rotated-partial.pdf"
    _save_rotated_partial_pdf(path)
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t25\t50\t75\t25\t91\tRecovered\n"
    )

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        output = b"tesseract 5.7.1\n" if command == ("tesseract", "--version") else tsv
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    evidence = extract_pdf(path, TesseractOcr(tmp_path / "cache"))

    page = evidence.pages[0]
    assert (page.width, page.height) == (200.0, 120.0)
    assert [(word.text, word.source) for word in page.words] == [
        ("Rotate", "digital"),
        ("Recovered", "ocr"),
    ]
    assert page.words[0].bbox == pytest.approx((156.711, 20.0, 171.825, 52.406))
    assert page.words[1].bbox == pytest.approx((6.0, 12.0, 24.0, 18.0))
    for word in page.words:
        assert 0 <= word.bbox[0] <= word.bbox[2] <= page.width
        assert 0 <= word.bbox[1] <= word.bbox[3] <= page.height
