from __future__ import annotations

import hashlib
import time
from base64 import b64decode
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.
import pytest

from ccparser.discovery import DocumentClassification, StatementDiscovery
from ccparser.evidence import DocumentEvidence, OcrError
from ccparser.evidence.models import BBox, Word
from ccparser.models import BatchResult, ReconciliationGroup, StatementResult, Status
from ccparser.normalize import StatementNormalization
from ccparser.parser import (
    ParserInputError,
    ParserRuntimeError,
    parse_directory,
    parse_statement,
)


def _evidence(content: bytes) -> DocumentEvidence:
    return DocumentEvidence(source_sha256=hashlib.sha256(content).hexdigest(), pages=())


def _discovery(
    classification: DocumentClassification,
    *,
    reason_codes: tuple[str, ...] = (),
    diagnostics: tuple[str, ...] = (),
) -> StatementDiscovery:
    return StatementDiscovery(
        classification=classification,
        confidence=1.0,
        reason_codes=reason_codes,
        diagnostics=diagnostics,
    )


def _normalizer(
    status: Status,
    *,
    diagnostics: tuple[str, ...] = (),
) -> Callable[[StatementDiscovery], StatementNormalization]:
    def normalize(discovery: StatementDiscovery) -> StatementNormalization:
        groups = (
            (
                ReconciliationGroup(
                    group_id="group-0001",
                    currency="ILS",
                    printed_total=Decimal("0.00"),
                    calculated_total=Decimal("0.00"),
                    difference=Decimal("0.00"),
                    transaction_ids=(),
                    status=Status.RECONCILED,
                ),
            )
            if status is Status.RECONCILED
            else ()
        )
        reconciliation = StatementResult(
            status=status,
            transactions=(),
            groups=groups,
            diagnostics=diagnostics,
        )
        return StatementNormalization(
            discovery=discovery,
            transactions=(),
            printed_totals=(),
            row_results=(),
            reconciliation=reconciliation,
            confidence=1.0,
            diagnostics=diagnostics,
        )

    return normalize


@pytest.mark.parametrize(
    ("classification", "expected"),
    (
        (DocumentClassification.NOT_STATEMENT, Status.NOT_STATEMENT),
        (DocumentClassification.AMBIGUOUS, Status.UNSUPPORTED),
    ),
)
def test_parse_statement_maps_non_statement_and_unknown_layout_without_normalizing(
    tmp_path: Path,
    classification: DocumentClassification,
    expected: Status,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic")
    normalized = False

    def extractor(path: Path, ocr_provider: object) -> DocumentEvidence:
        assert path == source
        assert ocr_provider is not None
        return _evidence(path.read_bytes())

    def normalizer(discovery: StatementDiscovery) -> StatementNormalization:
        nonlocal normalized
        normalized = True
        return _normalizer(Status.RECONCILED)(discovery)

    result = parse_statement(
        source,
        extractor=extractor,
        discoverer=lambda evidence: _discovery(
            classification,
            reason_codes=("classification_reason",),
            diagnostics=("layout_diagnostic",),
        ),
        normalizer=normalizer,
        ocr_provider=object(),
    )

    assert result.status is expected
    assert result.source_name == "synthetic.pdf"
    assert result.source_sha256 == hashlib.sha256(b"synthetic").hexdigest()
    assert result.statement_id == result.source_sha256
    assert result.diagnostics == ("classification_reason", "layout_diagnostic")
    assert normalized is False


@pytest.mark.parametrize("normalized_status", (Status.RECONCILED, Status.UNRECONCILED))
def test_parse_statement_maps_normalized_statement_and_strict_does_not_change_data(
    tmp_path: Path,
    normalized_status: Status,
) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")
    evidence = _evidence(source.read_bytes())
    discovery = _discovery(DocumentClassification.STATEMENT)
    dependencies = {
        "extractor": lambda path, ocr_provider: evidence,
        "discoverer": lambda value: discovery,
        "normalizer": _normalizer(normalized_status),
        "ocr_provider": object(),
    }

    ordinary = parse_statement(source, strict=False, **dependencies)
    strict = parse_statement(source, strict=True, **dependencies)

    assert ordinary == strict
    assert ordinary.status is normalized_status


def test_parse_statement_downgrades_inconsistent_reconciled_result(tmp_path: Path) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")
    discovery = _discovery(DocumentClassification.STATEMENT)

    result = parse_statement(
        source,
        extractor=lambda path, ocr_provider: _evidence(path.read_bytes()),
        discoverer=lambda value: discovery,
        normalizer=_normalizer(Status.RECONCILED, diagnostics=("unresolved_row",)),
        ocr_provider=object(),
    )

    assert result.status is Status.UNRECONCILED
    assert "unresolved_row" in result.diagnostics


@pytest.mark.parametrize("missing_kind", ("missing", "directory"))
def test_parse_statement_rejects_missing_or_non_file_input(
    tmp_path: Path,
    missing_kind: str,
) -> None:
    source = tmp_path / "source"
    if missing_kind == "directory":
        source.mkdir()

    with pytest.raises(ParserInputError, match="input PDF"):
        parse_statement(source)


@pytest.mark.parametrize("error", (OcrError("private detail"), RuntimeError("private detail")))
def test_parse_statement_wraps_ocr_and_processing_failures_without_detail(
    tmp_path: Path,
    error: Exception,
) -> None:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")

    def failing_extractor(path: Path, ocr_provider: object) -> DocumentEvidence:
        del path, ocr_provider
        raise error

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, extractor=failing_extractor, ocr_provider=object())

    assert "private detail" not in str(caught.value)


class _RecordingOcr:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[int] = []
        self.error = error

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]:
        del pdf_bytes, source_sha256, clip
        self.calls.append(page_index)
        if self.error is not None:
            raise self.error
        return ()


def _write_digital_pdf(path: Path) -> None:
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.insert_text((10, 50), "Synthetic digital statement text")
        document.save(path)


def _write_image_pdf(path: Path) -> None:
    one_pixel_png = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    with fitz.open() as document:
        page = document.new_page(width=100, height=100)
        page.insert_image(page.rect, stream=one_pixel_png)
        document.save(path)


def test_parse_statement_real_digital_pdf_does_not_invoke_ocr(tmp_path: Path) -> None:
    source = tmp_path / "digital.pdf"
    _write_digital_pdf(source)
    provider = _RecordingOcr()

    result = parse_statement(
        source,
        ocr_provider=provider,
        discoverer=lambda evidence: _discovery(DocumentClassification.AMBIGUOUS),
    )

    assert result.status is Status.UNSUPPORTED
    assert provider.calls == []


def test_parse_statement_real_image_only_pdf_invokes_local_ocr(tmp_path: Path) -> None:
    source = tmp_path / "image.pdf"
    _write_image_pdf(source)
    provider = _RecordingOcr()

    result = parse_statement(
        source,
        ocr_provider=provider,
        discoverer=lambda evidence: _discovery(DocumentClassification.AMBIGUOUS),
    )

    assert result.status is Status.UNSUPPORTED
    assert provider.calls == [0]


def test_parse_statement_image_ocr_dependency_failure_is_typed(tmp_path: Path) -> None:
    source = tmp_path / "image.pdf"
    _write_image_pdf(source)
    provider = _RecordingOcr(OcrError("private OCR executable detail"))

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, ocr_provider=provider)

    assert "private OCR executable detail" not in str(caught.value)


def test_parse_statement_corrupt_pdf_failure_is_typed_and_redacted(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.pdf"
    source.write_bytes(b"private corrupt PDF detail")

    with pytest.raises(ParserRuntimeError) as caught:
        parse_statement(source, ocr_provider=_RecordingOcr())

    assert "private corrupt PDF detail" not in str(caught.value)


def _directory_parser(calls: list[str]) -> Callable[..., StatementResult]:
    def parse(
        path: Path, strict: bool = False, *, cache_dir: str | Path | None = None
    ) -> StatementResult:
        del strict, cache_dir
        calls.append(path.name)
        if path.name.startswith("slow"):
            time.sleep(0.02)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        return StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name=path.name,
            source_sha256=digest,
            statement_id=digest,
        )

    return parse


def test_parse_directory_recurses_regular_pdfs_skips_trees_and_orders_posix_paths(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = input_dir / "generated"
    cache_dir = input_dir / "cache"
    for relative in ("z.pdf", "a.PDF", "nested/slow-b.pdf", "notes.txt"):
        source = input_dir / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(relative.encode())
    output_dir.mkdir(parents=True)
    (output_dir / "ignored.pdf").write_bytes(b"ignored")
    cache_dir.mkdir()
    (cache_dir / "ignored.pdf").write_bytes(b"ignored")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    (input_dir / "linked.pdf").symlink_to(outside)
    calls: list[str] = []

    result = parse_directory(
        input_dir,
        output_dir,
        jobs=3,
        cache_dir=cache_dir,
        statement_parser=_directory_parser(calls),
    )

    assert isinstance(result, BatchResult)
    assert result.status is Status.RECONCILED
    assert tuple(statement.source_name for statement in result.statements) == (
        "a.PDF",
        "nested/slow-b.pdf",
        "z.pdf",
    )
    assert sorted(calls) == ["a.PDF", "slow-b.pdf", "z.pdf"]
    assert (output_dir / "results.json").is_file()
    assert (output_dir / "transactions.csv").is_file()


def test_parse_directory_jobs_are_bounded_and_byte_identical_to_sequential(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    for name in ("slow-c.pdf", "a.pdf", "b.pdf"):
        input_dir.mkdir(exist_ok=True)
        (input_dir / name).write_bytes(name.encode())
    sequential_output = tmp_path / "sequential"
    concurrent_output = tmp_path / "concurrent"

    sequential = parse_directory(
        input_dir,
        sequential_output,
        jobs=1,
        statement_parser=_directory_parser([]),
    )
    concurrent = parse_directory(
        input_dir,
        concurrent_output,
        jobs=10_000,
        statement_parser=_directory_parser([]),
    )

    assert sequential == concurrent
    assert (sequential_output / "results.json").read_bytes() == (
        concurrent_output / "results.json"
    ).read_bytes()
    assert (sequential_output / "transactions.csv").read_bytes() == (
        concurrent_output / "transactions.csv"
    ).read_bytes()


def test_parse_directory_empty_is_explicit_unsupported_and_serialized(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"

    result = parse_directory(input_dir, output_dir, statement_parser=_directory_parser([]))

    assert result.status is Status.UNSUPPORTED
    assert result.statements == ()
    assert result.diagnostics == ("no_pdf_files",)
    assert b"no_pdf_files" in (output_dir / "results.json").read_bytes()
    assert b"no_pdf_files" in (output_dir / "transactions.csv").read_bytes()


@pytest.mark.parametrize("jobs", (0, -1, 1.5, True))
def test_parse_directory_validates_positive_integer_jobs(tmp_path: Path, jobs: object) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    with pytest.raises(ParserInputError, match="jobs"):
        parse_directory(input_dir, tmp_path / "output", jobs=jobs)  # type: ignore[arg-type]


def test_parse_directory_does_not_write_outputs_when_one_input_fails(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"valid")
    (input_dir / "b.pdf").write_bytes(b"failure")
    output_dir = tmp_path / "output"

    def parser(
        path: Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        if path.name == "b.pdf":
            raise ParserRuntimeError("generic processing failure")
        return StatementResult(status=Status.RECONCILED, transactions=(), groups=())

    with pytest.raises(ParserRuntimeError):
        parse_directory(input_dir, output_dir, jobs=2, statement_parser=parser)

    assert not (output_dir / "results.json").exists()
    assert not (output_dir / "transactions.csv").exists()
