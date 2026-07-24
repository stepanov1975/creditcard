"""Local Tesseract OCR with deterministic rendering and content-addressed caching."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import threading
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import cast

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.

from ccparser._traced_subprocess import run_traced_subprocess
from ccparser.evidence.currency import CURRENCY_OCR_SYMBOLS
from ccparser.evidence.models import Word
from ccparser.geometry import BBox, Point, intersection_over_smaller

OCR_LANGUAGES = "heb+eng"
OCR_PREPROCESSING_VERSION = "raw-pixmap-v1"
OCR_PIPELINE_VERSION = "tesseract-tsv-fused-structured-numeric-v4"
OCR_RECOGNITION_CACHE_VERSION = "tesseract-tsv-fused-numeric-v2"
OCR_NUMERIC_RECOGNITION_CACHE_VERSION = "tesseract-whitelisted-numeric-v1"
OCR_CURRENCY_RECOGNITION_CACHE_VERSION = "tesseract-isolated-currency-v1"
TESSERACT_VERSION_TIMEOUT_SECONDS = 10.0
TESSERACT_RECOGNITION_TIMEOUT_SECONDS = 120.0


class OcrError(RuntimeError):
    """A typed failure from local OCR version detection or recognition."""


@dataclass(frozen=True, slots=True)
class TesseractExecutionRuntime:
    """Descriptor-backed Tesseract executable, data root, and child context."""

    executable_path: str
    tessdata_directory: str
    pass_fds: tuple[int, ...]
    environment: tuple[tuple[str, str], ...]
    command_prefix: tuple[str, ...] = ()
    allowed_file_descriptors: tuple[int, ...] = ()
    staging_validator: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def child_environment(self) -> dict[str, str]:
        """Return a fresh environment mapping for one subprocess invocation."""

        return dict(self.environment)

    def run(
        self,
        command: tuple[str, ...],
        *,
        input_bytes: bytes | None,
        timeout: float,
        stderr_to_stdout: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        """Execute one OCR command with the bound native mapping policy."""

        if self.staging_validator is not None:
            self.staging_validator()
        try:
            completed = run_traced_subprocess(
                command,
                cwd=Path.cwd(),
                environment=self.child_environment(),
                inherited_file_descriptors=self.pass_fds,
                allowed_file_descriptors=self.allowed_file_descriptors,
                timeout=timeout,
                input_bytes=input_bytes,
                stderr_to_stdout=stderr_to_stdout,
            )
        finally:
            if self.staging_validator is not None:
                self.staging_validator()
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                command,
                completed.stdout,
                completed.stderr,
            )
        return completed


_ACTIVE_TESSERACT_RUNTIME: TesseractExecutionRuntime | None = None
_TESSERACT_RUNTIME_LOCK = threading.Lock()


@contextmanager
def bind_tesseract_runtime(runtime: TesseractExecutionRuntime) -> Iterator[None]:
    """Activate one immutable gate runtime across OCR worker threads."""

    global _ACTIVE_TESSERACT_RUNTIME
    with _TESSERACT_RUNTIME_LOCK:
        if _ACTIVE_TESSERACT_RUNTIME is not None:
            raise RuntimeError("Tesseract runtime is already bound")
        _ACTIVE_TESSERACT_RUNTIME = runtime
    try:
        yield
    finally:
        with _TESSERACT_RUNTIME_LOCK:
            if _ACTIVE_TESSERACT_RUNTIME is not runtime:
                raise RuntimeError("Tesseract runtime binding changed")
            _ACTIVE_TESSERACT_RUNTIME = None


def _bound_tesseract_invocation(
    command: tuple[str, ...],
    *,
    include_tessdata: bool,
) -> tuple[tuple[str, ...], TesseractExecutionRuntime | None]:
    runtime = _ACTIVE_TESSERACT_RUNTIME
    if runtime is None:
        return command, None
    if not command or command[0] != "tesseract":
        raise OcrError("Tesseract command is incompatible with the bound runtime")
    arguments = command[1:]
    if include_tessdata:
        if not arguments:
            raise OcrError("Tesseract command is incomplete")
        arguments = (
            *arguments[:-1],
            "--tessdata-dir",
            runtime.tessdata_directory,
            arguments[-1],
        )
    prefix = runtime.command_prefix or (runtime.executable_path,)
    return (*prefix, *arguments), runtime


def _launch_tesseract(
    command: tuple[str, ...],
    *,
    include_tessdata: bool,
    input_bytes: bytes | None,
    timeout: float,
    stderr_to_stdout: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Launch Tesseract through the active descriptor-capability route."""

    execution_command, runtime = _bound_tesseract_invocation(
        command,
        include_tessdata=include_tessdata,
    )
    if runtime is not None and runtime.allowed_file_descriptors:
        return runtime.run(
            execution_command,
            input_bytes=input_bytes,
            timeout=timeout,
            stderr_to_stdout=stderr_to_stdout,
        )
    if stderr_to_stdout:
        if runtime is None:
            return subprocess.run(
                execution_command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        return subprocess.run(
            execution_command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=runtime.child_environment(),
            pass_fds=runtime.pass_fds,
            timeout=timeout,
        )
    if runtime is None:
        return subprocess.run(
            execution_command,
            input=input_bytes,
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    return subprocess.run(
        execution_command,
        input=input_bytes,
        check=True,
        capture_output=True,
        env=runtime.child_environment(),
        pass_fds=runtime.pass_fds,
        timeout=timeout,
    )


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


def supplemental_tesseract_command() -> tuple[str, ...]:
    """Return the fixed English pass used only to repair truncated numeric OCR."""

    return (
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


def numeric_tesseract_command() -> tuple[str, ...]:
    """Return the fixed whitelisted pass used to corroborate damaged numeric OCR."""

    return (
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


def currency_tesseract_command() -> tuple[str, ...]:
    """Return the isolated English pass for a suspected currency symbol glyph."""

    return (
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


_NUMERIC_TOKEN_PATTERN = re.compile(r"^[+-]?(?:\d{1,3}(?:[,.]\d{3})+|\d+)(?:[,.]\d{1,2})?$")
_DATE_TOKEN_PATTERN = re.compile(
    r"^(?P<first>\d{1,4})(?P<separator>[./-])(?P<second>\d{1,2})"
    r"(?P=separator)(?P<third>\d{1,4})$"
)


def _numeric_digit_count(text: str) -> int:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFC", text).strip()
        if unicodedata.category(char) != "Cf"
    )
    if _NUMERIC_TOKEN_PATTERN.fullmatch(normalized) is not None:
        return sum(char.isdigit() for char in normalized)
    match = _DATE_TOKEN_PATTERN.fullmatch(normalized)
    if match is None:
        return 0
    first, second, third = (match.group(name) for name in ("first", "second", "third"))
    if len(first) == 4 and len(third) <= 2:
        year, month, day = int(first), int(second), int(third)
    elif len(first) <= 2 and len(third) in {2, 4}:
        day, month = int(first), int(second)
        year = int(third) if len(third) == 4 else 2000 + int(third)
    else:
        return 0
    try:
        date(year, month, day)
    except ValueError:
        return 0
    return sum(char.isdigit() for char in normalized)


def _minimal_letter_numeric_repair(primary: str, candidate: str) -> bool:
    primary_normalized = "".join(
        char
        for char in unicodedata.normalize("NFC", primary).strip()
        if unicodedata.category(char) != "Cf"
    )
    candidate_normalized = "".join(
        char
        for char in unicodedata.normalize("NFC", candidate).strip()
        if unicodedata.category(char) != "Cf"
    )
    if (
        len(primary_normalized) != len(candidate_normalized)
        or sum(char.isdigit() for char in primary_normalized) < 2
        or _NUMERIC_TOKEN_PATTERN.fullmatch(candidate_normalized) is None
    ):
        return False
    differences = tuple(
        (primary_char, candidate_char)
        for primary_char, candidate_char in zip(
            primary_normalized,
            candidate_normalized,
            strict=True,
        )
        if primary_char != candidate_char
    )
    return len(differences) == 1 and differences[0][0].isalpha() and differences[0][1].isdigit()


def fuse_ocr_words(
    primary: tuple[Word, ...],
    supplemental: tuple[Word, ...],
    numeric_supplemental: tuple[Word, ...] = (),
) -> tuple[Word, ...]:
    """Replace only overlapping truncated numeric tokens with stronger OCR evidence."""

    numeric_supplements = tuple(
        word
        for word in (*supplemental, *numeric_supplemental)
        if _numeric_digit_count(word.text) >= 2
    )
    fused: list[Word] = []
    for word in primary:
        primary_digits = _numeric_digit_count(word.text)
        candidates = tuple(
            candidate
            for candidate in numeric_supplements
            if intersection_over_smaller(word.bbox, candidate.bbox) >= 0.7
            and (
                (primary_digits and _numeric_digit_count(candidate.text) > primary_digits)
                or _minimal_letter_numeric_repair(word.text, candidate.text)
            )
        )
        fused.append(
            max(
                candidates,
                key=lambda candidate: (
                    _numeric_digit_count(candidate.text),
                    candidate.confidence,
                    candidate.text,
                ),
            )
            if candidates
            else word
        )
    return tuple(fused)


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

    def __init__(self, cache_dir: str | Path, dpi: int = 300) -> None:
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        self.cache_dir = Path(cache_dir)
        self.dpi = dpi
        self._command = tesseract_command()
        self._supplemental_command = supplemental_tesseract_command()
        self._numeric_command = numeric_tesseract_command()
        self._currency_command = currency_tesseract_command()
        self._version: str | None = None

    def _tesseract_version(self) -> str:
        if self._version is None:
            try:
                completed = _launch_tesseract(
                    (self._command[0], "--version"),
                    include_tessdata=False,
                    input_bytes=None,
                    timeout=TESSERACT_VERSION_TIMEOUT_SECONDS,
                    stderr_to_stdout=True,
                )
            except (
                subprocess.TimeoutExpired,
                subprocess.CalledProcessError,
                OSError,
                RuntimeError,
            ) as error:
                raise OcrError("Tesseract version detection failed") from error
            first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()
            self._version = first_line[0].strip() if first_line else "unknown"
        return self._version

    def cache_key(self, source_sha256: str, page_index: int, clip: BBox | None = None) -> str:
        """Hash every input that can change the rendered OCR result."""

        payload = {
            "clip": list(clip) if clip is not None else None,
            "command": list(self._command),
            "dpi": self.dpi,
            "languages": OCR_LANGUAGES,
            "page_index": page_index,
            "pipeline_version": OCR_RECOGNITION_CACHE_VERSION,
            "preprocessing_version": OCR_PREPROCESSING_VERSION,
            "source_sha256": source_sha256,
            "supplemental_command": list(self._supplemental_command),
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

    def _numeric_cache_key(self, recognition_key: str) -> str:
        payload = {
            "command": list(self._numeric_command),
            "recognition_cache_version": OCR_NUMERIC_RECOGNITION_CACHE_VERSION,
            "recognition_key": recognition_key,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(serialized).hexdigest()

    def _currency_cache_key(self, recognition_key: str) -> str:
        payload = {
            "command": list(self._currency_command),
            "recognition_cache_version": OCR_CURRENCY_RECOGNITION_CACHE_VERSION,
            "recognition_key": recognition_key,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(serialized).hexdigest()

    def _recognize(self, image: bytes, command: tuple[str, ...]) -> bytes:
        try:
            completed = _launch_tesseract(
                command,
                include_tessdata=True,
                input_bytes=image,
                timeout=TESSERACT_RECOGNITION_TIMEOUT_SECONDS,
                stderr_to_stdout=False,
            )
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            OSError,
            RuntimeError,
        ) as error:
            raise OcrError("Tesseract recognition failed") from error
        return completed.stdout

    def _cached_recognition(
        self,
        cache_path: Path,
        image: bytes,
        command: tuple[str, ...],
    ) -> bytes:
        if cache_path.is_file():
            return cache_path.read_bytes()
        tsv = self._recognize(image, command)
        self._write_cache(cache_path, tsv)
        return tsv

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

        if hashlib.sha256(pdf_bytes).hexdigest() != source_sha256:
            raise ValueError("source SHA-256 does not match PDF bytes")
        image, origin = self._render(pdf_bytes, page_index, clip)
        key = self.cache_key(source_sha256, page_index, clip)
        primary_tsv = self._cached_recognition(
            self.cache_dir / f"{key}.primary.tsv",
            image,
            self._command,
        )
        supplemental_tsv = self._cached_recognition(
            self.cache_dir / f"{key}.supplemental.tsv",
            image,
            self._supplemental_command,
        )
        numeric_key = self._numeric_cache_key(key)
        numeric_tsv = self._cached_recognition(
            self.cache_dir / f"{numeric_key}.numeric.tsv",
            image,
            self._numeric_command,
        )
        return fuse_ocr_words(
            parse_tesseract_tsv(primary_tsv, dpi=self.dpi, origin=origin),
            parse_tesseract_tsv(supplemental_tsv, dpi=self.dpi, origin=origin),
            parse_tesseract_tsv(numeric_tsv, dpi=self.dpi, origin=origin),
        )

    def extract_currency_symbol(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox,
    ) -> Word | None:
        """OCR one geometry-proven custom glyph without forcing a symbol whitelist."""

        if hashlib.sha256(pdf_bytes).hexdigest() != source_sha256:
            raise ValueError("source SHA-256 does not match PDF bytes")
        image, origin = self._render(pdf_bytes, page_index, clip)
        recognition_key = self.cache_key(source_sha256, page_index, clip)
        currency_key = self._currency_cache_key(recognition_key)
        tsv = self._cached_recognition(
            self.cache_dir / f"{currency_key}.currency.tsv",
            image,
            self._currency_command,
        )
        candidates: list[Word] = []
        for word in parse_tesseract_tsv(tsv, dpi=self.dpi, origin=origin):
            symbols = tuple(char for char in word.text if char in CURRENCY_OCR_SYMBOLS)
            residual = tuple(
                char
                for char in word.text
                if not char.isspace()
                and char not in CURRENCY_OCR_SYMBOLS
                and unicodedata.category(char)[0] not in {"M", "P"}
            )
            if len(symbols) == 1 and not residual:
                candidates.append(word.model_copy(update={"text": symbols[0]}))
        distinct_symbols = {word.text for word in candidates}
        if len(distinct_symbols) != 1:
            return None
        return max(candidates, key=lambda word: (word.confidence, word.bbox))
