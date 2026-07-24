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
from ccparser.evidence import Word
from ccparser.evidence.ocr import (
    OCR_LANGUAGES,
    OCR_PREPROCESSING_VERSION,
    OCR_RECOGNITION_CACHE_VERSION,
    TesseractExecutionRuntime,
    TesseractOcr,
    currency_tesseract_command,
    fuse_ocr_words,
    numeric_tesseract_command,
    parse_tesseract_tsv,
    supplemental_tesseract_command,
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


def _source_sha256(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


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


def test_supplemental_tesseract_command_is_english_numeric_pass() -> None:
    assert supplemental_tesseract_command() == (
        "tesseract",
        "stdin",
        "stdout",
        "-l",
        "eng",
        "--oem",
        "1",
        "--psm",
        "6",
        "tsv",
    )


def test_numeric_tesseract_command_is_deterministic_whitelisted_pass() -> None:
    assert numeric_tesseract_command() == (
        "tesseract",
        "stdin",
        "stdout",
        "-l",
        "eng",
        "--oem",
        "1",
        "--psm",
        "6",
        "-c",
        "tessedit_char_whitelist=0123456789.,/-+()",
        "tsv",
    )


def test_currency_tesseract_command_is_isolated_english_symbol_pass() -> None:
    assert currency_tesseract_command() == (
        "tesseract",
        "stdin",
        "stdout",
        "-l",
        "eng",
        "--oem",
        "1",
        "--psm",
        "10",
        "tsv",
    )


def test_currency_ocr_accepts_one_symbol_with_punctuation_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "blank.pdf"
    _save_blank_pdf(path)
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t0\t0\t25\t25\t24\t_\xe2\x82\xac\n"
    )

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        output = b"tesseract 5.7.1\n" if command == ("tesseract", "--version") else tsv
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf_bytes = path.read_bytes()
    provider = TesseractOcr(tmp_path / "cache")

    word = provider.extract_currency_symbol(
        pdf_bytes,
        _source_sha256(pdf_bytes),
        page_index=0,
        clip=(10.0, 20.0, 30.0, 40.0),
    )

    assert word is not None
    assert word.text == "€"
    assert word.source == "ocr"


def test_fuse_ocr_words_replaces_only_overlapping_truncated_numeric_token() -> None:
    primary = (
        Word(
            text="כותרת",
            bbox=(10.0, 10.0, 40.0, 20.0),
            source="ocr",
            confidence=0.9,
        ),
        Word(
            text="₪",
            bbox=(50.0, 30.0, 55.0, 40.0),
            source="ocr",
            confidence=0.8,
        ),
        Word(
            text="1",
            bbox=(58.0, 30.0, 82.0, 40.0),
            source="ocr",
            confidence=0.95,
        ),
    )
    supplemental = (
        Word(
            text="256.81",
            bbox=(58.0, 30.0, 82.0, 40.0),
            source="ocr",
            confidence=0.9,
        ),
        Word(
            text="2026",
            bbox=(100.0, 70.0, 120.0, 80.0),
            source="ocr",
            confidence=0.9,
        ),
    )

    fused = fuse_ocr_words(primary, supplemental)

    assert tuple(word.text for word in fused) == ("כותרת", "₪", "256.81")


def test_fuse_ocr_words_repairs_truncated_valid_calendar_date() -> None:
    primary = (Word(text="3", bbox=(28.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.96),)
    supplemental = (
        Word(
            text="29/01/23",
            bbox=(10.0, 30.0, 32.0, 40.0),
            source="ocr",
            confidence=0.95,
        ),
    )

    fused = fuse_ocr_words(primary, supplemental)

    assert tuple(word.text for word in fused) == ("29/01/23",)


def test_fuse_ocr_words_rejects_malformed_calendar_date_supplement() -> None:
    primary = (Word(text="3", bbox=(28.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.96),)
    supplemental = (
        Word(
            text="39/19/23",
            bbox=(10.0, 30.0, 32.0, 40.0),
            source="ocr",
            confidence=0.95,
        ),
    )

    fused = fuse_ocr_words(primary, supplemental)

    assert fused == primary


def test_fuse_ocr_words_repairs_one_letter_inside_otherwise_exact_amount() -> None:
    primary = (Word(text="A34.96", bbox=(10.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.3),)
    numeric = (Word(text="134.96", bbox=(10.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.0),)

    fused = fuse_ocr_words(primary, (), numeric)

    assert tuple(word.text for word in fused) == ("134.96",)


def test_fuse_ocr_words_rejects_nonminimal_amount_disagreement() -> None:
    primary = (Word(text="A34.96", bbox=(10.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.3),)
    numeric = (Word(text="734.98", bbox=(10.0, 30.0, 32.0, 40.0), source="ocr", confidence=0.9),)

    fused = fuse_ocr_words(primary, (), numeric)

    assert fused == primary


def test_ocr_exposes_a_typed_runtime_error() -> None:
    error_type = getattr(ocr_module, "OcrError", object)

    assert issubclass(error_type, RuntimeError)


def test_ocr_uses_named_version_and_recognition_timeouts() -> None:
    assert getattr(ocr_module, "TESSERACT_VERSION_TIMEOUT_SECONDS", None) == 10.0
    assert getattr(ocr_module, "TESSERACT_RECOGNITION_TIMEOUT_SECONDS", None) == 120.0


def test_tesseract_launcher_owns_unbound_byte_stdio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def fake_run(
        command: tuple[str, ...],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[bytes]:
        observed.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"version", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    completed = ocr_module._launch_tesseract(
        ("tesseract", "--version"),
        include_tessdata=False,
        input_bytes=None,
        timeout=10.0,
        stderr_to_stdout=True,
    )

    assert completed.stdout == b"version"
    assert observed == [
        (
            ("tesseract", "--version"),
            {
                "check": True,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "timeout": 10.0,
            },
        )
    ]


def test_bound_runtime_validates_staging_before_and_after_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def validate() -> None:
        events.append("validate")

    def fake_run(*_: Any, **__: Any) -> subprocess.CompletedProcess[bytes]:
        events.append("execute")
        return subprocess.CompletedProcess(("bound",), 0, b"recognized", b"")

    monkeypatch.setattr(ocr_module, "run_traced_subprocess", fake_run)
    runtime = TesseractExecutionRuntime(
        executable_path="/proc/self/fd/10",
        tessdata_directory="/proc/self/fd/11",
        pass_fds=(10, 11),
        environment=(),
        command_prefix=("bound",),
        allowed_file_descriptors=(10,),
        staging_validator=validate,
    )

    completed = runtime.run(
        ("bound", "stdin", "stdout"),
        input_bytes=b"image",
        timeout=1.0,
        stderr_to_stdout=False,
    )

    assert completed.stdout == b"recognized"
    assert events == ["validate", "execute", "validate"]


def test_ocr_constructor_has_no_command_override() -> None:
    constructor = inspect.signature(TesseractOcr)

    assert "command" not in constructor.parameters
    assert (
        getattr(ocr_module, "OCR_PIPELINE_VERSION", None)
        == "tesseract-tsv-fused-structured-numeric-v4"
    )


@pytest.mark.parametrize(
    "failure",
    (
        subprocess.TimeoutExpired(("tesseract", "--version"), timeout=10.0),
        subprocess.CalledProcessError(2, ("tesseract", "--version")),
        OSError("synthetic version launch failure"),
        RuntimeError("synthetic bound-runtime violation"),
    ),
)
def test_version_detection_wraps_subprocess_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: subprocess.SubprocessError | OSError | RuntimeError,
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
        OSError("synthetic recognition launch failure"),
        RuntimeError("synthetic bound-runtime violation"),
    ),
)
def test_recognition_wraps_subprocess_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: subprocess.SubprocessError | OSError | RuntimeError,
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
    pdf_bytes = path.read_bytes()

    with pytest.raises(ocr_module.OcrError, match="recognition failed") as caught:
        provider.extract_words(pdf_bytes, _source_sha256(pdf_bytes), page_index=0)

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
        "pipeline_version": OCR_RECOGNITION_CACHE_VERSION,
        "preprocessing_version": OCR_PREPROCESSING_VERSION,
        "source_sha256": "b" * 64,
        "supplemental_command": list(supplemental_tesseract_command()),
        "tesseract_version": "tesseract 5.7.1",
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert key == hashlib.sha256(serialized).hexdigest()


def test_cache_key_changes_when_internal_ocr_command_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b"tesseract 5.7.1\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    default = TesseractOcr(tmp_path / "default")
    alternate_command = (*tesseract_command()[:-2], "11", "tsv")
    monkeypatch.setattr(ocr_module, "tesseract_command", lambda: alternate_command)
    alternate = TesseractOcr(tmp_path / "alternate")

    default_key = default.cache_key("1" * 64, page_index=0)
    alternate_key = alternate.cache_key("1" * 64, page_index=0)

    assert default_key != alternate_key


def test_internal_ocr_command_snapshot_is_used_for_recognition(
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
    monkeypatch.setattr(ocr_module, "tesseract_command", lambda: alternate_command)
    provider = TesseractOcr(tmp_path / "cache")
    pdf_bytes = path.read_bytes()

    words = provider.extract_words(pdf_bytes, _source_sha256(pdf_bytes), page_index=0)

    assert words[0].text == "Configured"
    assert commands == [
        ("tesseract", "--version"),
        alternate_command,
        supplemental_tesseract_command(),
        numeric_tesseract_command(),
    ]


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
    pdf_bytes = path.read_bytes()
    source_sha256 = _source_sha256(pdf_bytes)
    first_provider = TesseractOcr(tmp_path / "cache")

    first = first_provider.extract_words(pdf_bytes, source_sha256, page_index=0, clip=clip)
    second_provider = TesseractOcr(tmp_path / "cache")
    second = second_provider.extract_words(pdf_bytes, source_sha256, page_index=0, clip=clip)

    assert first == second
    assert first[0].bbox == pytest.approx((18.0, 36.0, 36.0, 42.0))
    assert commands.count(tesseract_command()) == 1
    assert commands.count(("tesseract", "--version")) == 2
    assert len(image_inputs) == 3
    assert image_inputs[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert image_inputs[1] == image_inputs[0]
    assert image_inputs[2] == image_inputs[0]
    assert len(tuple((tmp_path / "cache").glob("*.tsv"))) == 3


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
    pdf_bytes = path.read_bytes()

    words = provider.extract_words(
        pdf_bytes,
        _source_sha256(pdf_bytes),
        page_index=0,
        clip=clip,
    )

    assert words[0].bbox == pytest.approx(
        (*expected_origin, expected_origin[0] + 6.0, expected_origin[1] + 6.0)
    )


def test_ocr_rejects_source_hash_mismatch_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mismatch.pdf"
    _save_blank_pdf(path)
    pdf_bytes = path.read_bytes()
    cache_dir = tmp_path / "cache"
    provider = TesseractOcr(cache_dir)
    render_count = 0
    subprocess_commands: list[tuple[str, ...]] = []
    original_render = provider._render

    def recording_render(
        source_bytes: bytes,
        page_index: int,
        clip: tuple[float, float, float, float] | None,
    ) -> tuple[bytes, tuple[float, float]]:
        nonlocal render_count
        render_count += 1
        return original_render(source_bytes, page_index, clip)

    def fake_run(command: tuple[str, ...], **_: Any) -> subprocess.CompletedProcess[bytes]:
        subprocess_commands.append(command)
        output = b"tesseract 5.7.1\n" if command == ("tesseract", "--version") else b""
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(provider, "_render", recording_render)
    monkeypatch.setattr(subprocess, "run", fake_run)
    error_message: str | None = None

    try:
        provider.extract_words(pdf_bytes, "0" * 64, page_index=0)
    except ValueError as error:
        error_message = str(error)

    assert (
        error_message,
        render_count,
        subprocess_commands,
        cache_dir.exists(),
    ) == (
        "source SHA-256 does not match PDF bytes",
        0,
        [],
        False,
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
