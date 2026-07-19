from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

import ccparser
import ccparser.cli as cli_module
from ccparser.audit import AuditAction, AuditDecision, AuditReport
from ccparser.cli import app
from ccparser.discovery import DocumentClassification
from ccparser.evidence import DocumentEvidence
from ccparser.models import (
    BatchResult,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
    TransactionKind,
)
from ccparser.parser import ParserInputError

runner = CliRunner()


def _statement(status: Status, source: str = "synthetic.pdf") -> StatementResult:
    transaction = Transaction(
        transaction_id="transaction-0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("10.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        description="private merchant description",
    )
    group = ReconciliationGroup(
        group_id="group-0001",
        currency="ILS",
        printed_total=Decimal("10.00"),
        calculated_total=Decimal("10.00"),
        difference=Decimal("0.00"),
        transaction_ids=(transaction.transaction_id,),
        status=status,
        diagnostics=("private diagnostic must not print",),
    )
    return StatementResult(
        status=status,
        transactions=(transaction,),
        groups=(group,),
        diagnostics=("private diagnostic must not print",),
        source_name=source,
        source_sha256="c" * 64,
        statement_id="c" * 64,
    )


@pytest.mark.parametrize(
    ("strict", "expected_exit"),
    ((False, 0), (True, 2)),
)
def test_parse_cli_writes_single_file_results_and_uses_exact_validation_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    expected_exit: int,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic")
    output_dir = tmp_path / ("strict-output" if strict else "ordinary-output")
    cache_dir = tmp_path / "cache"
    captured: dict[str, object] = {}

    def fake_parse(
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        captured.update(path=Path(path), strict=strict, cache_dir=Path(cache_dir or ""))
        return _statement(Status.UNRECONCILED)

    monkeypatch.setattr(cli_module, "parse_statement", fake_parse)
    arguments = [
        "parse",
        str(source),
        "--output-dir",
        str(output_dir),
        "--cache-dir",
        str(cache_dir),
    ]
    if strict:
        arguments.append("--strict")

    result = runner.invoke(app, arguments)

    assert result.exit_code == expected_exit
    assert captured == {"path": source, "strict": strict, "cache_dir": cache_dir}
    assert (output_dir / "results.json").is_file()
    assert (output_dir / "transactions.csv").is_file()
    assert "synthetic.pdf unreconciled" in result.output
    assert "private merchant" not in result.output
    assert "private diagnostic" not in result.output
    assert str(tmp_path) not in result.output


def test_parse_cli_directory_wires_jobs_cache_and_prints_relative_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    captured: dict[str, object] = {}
    batch = BatchResult(
        status=Status.RECONCILED,
        statements=(_statement(Status.RECONCILED, "nested/statement.pdf"),),
    )

    def fake_directory(
        path: str | Path,
        output_dir: str | Path,
        strict: bool = False,
        jobs: int | None = None,
        *,
        cache_dir: str | Path | None = None,
    ) -> BatchResult:
        captured.update(
            path=Path(path),
            output_dir=Path(output_dir),
            strict=strict,
            jobs=jobs,
            cache_dir=Path(cache_dir or ""),
        )
        return batch

    monkeypatch.setattr(cli_module, "parse_directory", fake_directory)

    result = runner.invoke(
        app,
        [
            "parse",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--jobs",
            "3",
            "--cache-dir",
            str(cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "path": input_dir,
        "output_dir": output_dir,
        "strict": False,
        "jobs": 3,
        "cache_dir": cache_dir,
    }
    assert "nested/statement.pdf reconciled" in result.output
    assert str(tmp_path) not in result.output


def test_parse_cli_runtime_input_error_is_exit_one_and_redacts_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "secret-name.pdf"
    source.write_bytes(b"synthetic")

    def fail(*args: object, **kwargs: object) -> StatementResult:
        del args, kwargs
        raise ParserInputError("private runtime detail")

    monkeypatch.setattr(cli_module, "parse_statement", fail)

    result = runner.invoke(
        app,
        ["parse", str(source), "--output-dir", str(tmp_path / "output")],
    )

    assert result.exit_code == 1
    assert "input_or_runtime_error" in result.output
    assert "private runtime detail" not in result.output
    assert "secret-name" not in result.output
    assert str(tmp_path) not in result.output


def test_audit_cli_injects_local_ocr_and_preserves_apply_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    cache_dir = tmp_path / "cache"
    provider = object()
    captured: dict[str, object] = {}
    evidence = DocumentEvidence(source_sha256="d" * 64, pages=())

    monkeypatch.setattr(cli_module, "TesseractOcr", lambda path: provider)

    def fake_extract(path: str | Path, ocr_provider: object | None = None) -> DocumentEvidence:
        captured.update(extract_path=Path(path), provider=ocr_provider)
        return evidence

    def fake_audit(
        input_path: str | Path,
        quarantine_path: str | Path,
        apply: bool = False,
        *,
        extractor: object,
    ) -> AuditReport:
        captured.update(
            input_path=Path(input_path),
            quarantine_path=Path(quarantine_path),
            apply=apply,
        )
        assert callable(extractor)
        extractor(input_dir / "synthetic.pdf")
        return AuditReport(
            decisions=(
                AuditDecision(
                    original_relative_path="nested/form.pdf",
                    quarantine_relative_path="nested/form.pdf",
                    sha256="d" * 64,
                    classification=DocumentClassification.NOT_STATEMENT,
                    confidence=0.95,
                    action=AuditAction.QUARANTINE,
                    reason_codes=("positive_non_statement_form_evidence",),
                ),
            ),
            applied=apply,
            moved_count=1 if apply else 0,
        )

    monkeypatch.setattr(cli_module, "extract_pdf", fake_extract)
    monkeypatch.setattr(cli_module, "audit_directory", fake_audit)

    result = runner.invoke(
        app,
        [
            "audit",
            str(input_dir),
            "--quarantine-dir",
            str(quarantine_dir),
            "--apply",
            "--cache-dir",
            str(cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "input_path": input_dir,
        "quarantine_path": quarantine_dir,
        "apply": True,
        "extract_path": input_dir / "synthetic.pdf",
        "provider": provider,
    }
    assert "nested/form.pdf quarantine" in result.output
    assert "d" * 64 not in result.output
    assert str(tmp_path) not in result.output


def test_public_exports_runtime_dependency_and_console_entrypoint() -> None:
    configuration = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert ccparser.parse_statement is not None
    assert ccparser.parse_directory is not None
    assert ccparser.audit_directory is not None
    assert any(
        requirement.startswith("typer") for requirement in configuration["project"]["dependencies"]
    )
    assert configuration["project"]["scripts"]["ccparse"] == "ccparser.cli:app"


def test_cli_sanitizes_control_characters_in_relative_source_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    batch = BatchResult(
        status=Status.RECONCILED,
        statements=(_statement(Status.RECONCILED, "nested/\nstatus-injection.pdf"),),
    )
    monkeypatch.setattr(cli_module, "parse_directory", lambda *args, **kwargs: batch)

    result = runner.invoke(
        app,
        ["parse", str(input_dir), "--output-dir", str(tmp_path / "output")],
    )

    assert result.exit_code == 0
    assert "nested/?status-injection.pdf reconciled" in result.output
    assert "\nstatus-injection.pdf" not in result.output


@pytest.mark.parametrize("jobs", ("0", "1.5", "workers"))
def test_parse_cli_maps_malformed_or_non_positive_jobs_to_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    jobs: str,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic")
    called = False

    def fake_parse(*args: object, **kwargs: object) -> StatementResult:
        nonlocal called
        del args, kwargs
        called = True
        return _statement(Status.RECONCILED)

    monkeypatch.setattr(cli_module, "parse_statement", fake_parse)

    result = runner.invoke(
        app,
        [
            "parse",
            str(source),
            "--output-dir",
            str(tmp_path / "output"),
            "--jobs",
            jobs,
        ],
    )

    assert result.exit_code == 1
    assert "input_or_runtime_error" in result.output
    assert called is False


def test_single_file_cli_publishes_with_one_pair_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"synthetic")
    output_dir = tmp_path / "output"
    published: list[tuple[Path, BatchResult]] = []
    monkeypatch.setattr(
        cli_module, "parse_statement", lambda *args, **kwargs: _statement(Status.RECONCILED)
    )
    monkeypatch.setattr(
        cli_module,
        "write_batch_outputs",
        lambda path, batch: published.append((Path(path), batch)),
    )

    result = runner.invoke(
        app,
        ["parse", str(source), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert len(published) == 1
    assert published[0][0] == output_dir
    assert published[0][1].status is Status.RECONCILED
