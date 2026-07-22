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
from ccparser.corpus_gate import (
    CorpusCounts,
    CorpusGateAcceptanceError,
    CorpusGateAttestation,
    CorpusGateConfig,
    CorpusGateInputError,
    CorpusGateMode,
    CorpusGateReason,
    CorpusGateRuntimeError,
)
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

_PRIVATE_GATE_BAIT = (
    "/private/corpus/secret-name.pdf "
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef "
    "SECRET MERCHANT 2026-07-22 amount=1234.56 total=7890.12"
)


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


def _corpus_counts(*, documents: int, reconciled: int, not_statement: int) -> CorpusCounts:
    return CorpusCounts(
        documents=documents,
        reconciled=reconciled,
        unreconciled=0,
        unsupported=0,
        not_statement=not_statement,
        groups=4,
        row_results=5,
        transactions=6,
        ambiguous_transactions=0,
        ambiguity_occurrences=0,
        evidence_references=7,
        present_fields=(),
    )


def _corpus_attestation(
    *,
    mode: CorpusGateMode = CorpusGateMode.VERIFY,
    performance_checked: bool = True,
) -> CorpusGateAttestation:
    return CorpusGateAttestation(
        passed=True,
        mode=mode,
        commit_abbreviation="a" * 12,
        toolchain_abbreviation="b" * 12,
        retained_counts=_corpus_counts(documents=3, reconciled=3, not_statement=0),
        quarantine_counts=_corpus_counts(documents=2, reconciled=0, not_statement=2),
        elapsed_seconds=Decimal("1.25"),
        performance_checked=performance_checked,
        reason_codes=(),
    )


def _verify_corpus_arguments(
    *,
    mode: str = "verify",
    jobs: str = "4",
    runtime_tolerance: str | None = None,
) -> list[str]:
    arguments = [
        "verify-corpus",
        "retained",
        "--quarantine-dir",
        "quarantine",
        "--membership-inventory",
        "artifacts/membership.json",
        "--baseline",
        "artifacts/baseline.json",
        "--work-dir",
        "artifacts/run",
        "--mode",
        mode,
        "--jobs",
        jobs,
    ]
    if runtime_tolerance is not None:
        arguments.extend(("--runtime-tolerance", runtime_tolerance))
    return arguments


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


def test_verify_corpus_cli_prints_only_exact_aggregate_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_corpus_gate",
        lambda *_args, **_kwargs: _corpus_attestation(),
        raising=False,
    )

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 0
    assert result.output == (
        "status=passed mode=verify retained=3 reconciled=3 "
        "quarantined=2 elapsed_seconds=1.25 performance_checked=true\n"
    )


@pytest.mark.parametrize(
    ("mode", "runtime_tolerance", "expected_tolerance"),
    (
        (CorpusGateMode.VERIFY, None, None),
        (CorpusGateMode.RECORD, "0.1250", Decimal("0.1250")),
    ),
)
def test_verify_corpus_cli_forwards_complete_immutable_configuration(
    monkeypatch: pytest.MonkeyPatch,
    mode: CorpusGateMode,
    runtime_tolerance: str | None,
    expected_tolerance: Decimal | None,
) -> None:
    captured: list[tuple[CorpusGateConfig, CorpusGateMode]] = []

    def fake_gate(config: CorpusGateConfig, actual_mode: CorpusGateMode) -> CorpusGateAttestation:
        captured.append((config, actual_mode))
        return _corpus_attestation(mode=actual_mode)

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(
        app,
        _verify_corpus_arguments(
            mode=mode.value,
            jobs="7",
            runtime_tolerance=runtime_tolerance,
        ),
    )

    assert result.exit_code == 0
    assert len(captured) == 1
    config, actual_mode = captured[0]
    assert actual_mode is mode
    assert config == CorpusGateConfig(
        retained_dir=Path("retained"),
        quarantine_dir=Path("quarantine"),
        membership_inventory_path=Path("artifacts/membership.json"),
        baseline_path=Path("artifacts/baseline.json"),
        work_dir=Path("artifacts/run"),
        jobs=7,
        runtime_tolerance_ratio=expected_tolerance,
    )
    assert config.model_config["frozen"] is True
    if expected_tolerance is not None:
        assert config.runtime_tolerance_ratio is not None
        assert config.runtime_tolerance_ratio.as_tuple() == expected_tolerance.as_tuple()


@pytest.mark.parametrize(
    "arguments",
    (
        _verify_corpus_arguments(mode="record"),
        _verify_corpus_arguments(runtime_tolerance="0.2"),
    ),
    ids=("record-missing-tolerance", "verify-supplied-tolerance"),
)
def test_verify_corpus_cli_rejects_mode_specific_tolerance_contract_before_running(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize(
    "missing_value",
    ("retained", "quarantine", "inventory", "baseline", "work", "mode", "jobs"),
)
def test_verify_corpus_cli_maps_omitted_contract_values_to_exit_one(
    monkeypatch: pytest.MonkeyPatch,
    missing_value: str,
) -> None:
    arguments = _verify_corpus_arguments()
    option_by_value = {
        "quarantine": "--quarantine-dir",
        "inventory": "--membership-inventory",
        "baseline": "--baseline",
        "work": "--work-dir",
        "mode": "--mode",
        "jobs": "--jobs",
    }
    if missing_value == "retained":
        arguments.pop(1)
    else:
        option_index = arguments.index(option_by_value[missing_value])
        del arguments[option_index : option_index + 2]
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize(
    "arguments",
    (
        [*_verify_corpus_arguments(), f"--private-option={_PRIVATE_GATE_BAIT}"],
        [*_verify_corpus_arguments(), _PRIVATE_GATE_BAIT],
        [*_verify_corpus_arguments()[:-1]],
    ),
    ids=("unknown-option", "extra-positional", "option-missing-value"),
)
def test_verify_corpus_cli_maps_usage_failures_to_redacted_exit_one(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize("mode", ("", "VERIFY", "other"))
def test_verify_corpus_cli_maps_invalid_mode_to_exit_one_before_running(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, _verify_corpus_arguments(mode=mode))

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize("jobs", ("0", "-1", "1.5", "workers"))
def test_verify_corpus_cli_maps_invalid_jobs_to_exit_one_before_running(
    monkeypatch: pytest.MonkeyPatch,
    jobs: str,
) -> None:
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, _verify_corpus_arguments(jobs=jobs))

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize(
    "runtime_tolerance",
    ("not-a-decimal", "NaN", "Infinity", "-Infinity", "-0.01"),
)
def test_verify_corpus_cli_rejects_invalid_record_tolerance_without_float_conversion(
    monkeypatch: pytest.MonkeyPatch,
    runtime_tolerance: str,
) -> None:
    called = False

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        nonlocal called
        called = True
        return _corpus_attestation()

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(
        app,
        _verify_corpus_arguments(mode="record", runtime_tolerance=runtime_tolerance),
    )

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=invalid_configuration\n"
    assert called is False


@pytest.mark.parametrize(
    ("error_type", "reason", "expected_output"),
    (
        (
            CorpusGateInputError,
            CorpusGateReason.PATH_OUTSIDE_REPOSITORY,
            "status=error reason_codes=path_outside_repository\n",
        ),
        (
            CorpusGateRuntimeError,
            CorpusGateReason.TOOLCHAIN_UNAVAILABLE,
            "status=error reason_codes=toolchain_unavailable\n",
        ),
    ),
)
def test_verify_corpus_cli_redacts_typed_input_and_runtime_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[CorpusGateInputError | CorpusGateRuntimeError],
    reason: CorpusGateReason,
    expected_output: str,
) -> None:
    error = error_type((reason,))
    error.args = (_PRIVATE_GATE_BAIT,)

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        raise error

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 1
    assert result.output == expected_output
    assert all(fragment not in result.output for fragment in _PRIVATE_GATE_BAIT.split())


def test_verify_corpus_cli_redacts_unexpected_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        raise RuntimeError(_PRIVATE_GATE_BAIT)

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=parser_runtime_failed\n"
    assert all(fragment not in result.output for fragment in _PRIVATE_GATE_BAIT.split())


def test_verify_corpus_cli_prints_only_ordered_closed_acceptance_reason_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = CorpusGateAcceptanceError(
        (
            CorpusGateReason.RUNTIME_REGRESSION,
            CorpusGateReason.JSON_DRIFT,
            CorpusGateReason.MEMBERSHIP_DRIFT,
        )
    )
    error.args = (_PRIVATE_GATE_BAIT,)

    def fake_gate(*_args: object, **_kwargs: object) -> CorpusGateAttestation:
        raise error

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 2
    assert result.output == (
        "status=failed reason_codes=membership_drift,json_drift,runtime_regression\n"
    )
    assert all(fragment not in result.output for fragment in _PRIVATE_GATE_BAIT.split())


def test_verify_corpus_cli_explicitly_reports_unchecked_performance_without_extra_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_corpus_gate",
        lambda *_args, **_kwargs: _corpus_attestation(performance_checked=False),
        raising=False,
    )

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 0
    assert result.output == (
        "status=passed mode=verify retained=3 reconciled=3 "
        "quarantined=2 elapsed_seconds=1.25 performance_checked=false\n"
    )


def test_verify_corpus_cli_never_exits_zero_for_an_unpassed_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unpassed = _corpus_attestation().model_copy(update={"passed": False})
    monkeypatch.setattr(
        cli_module,
        "run_corpus_gate",
        lambda *_args, **_kwargs: unpassed,
        raising=False,
    )

    result = runner.invoke(app, _verify_corpus_arguments())

    assert result.exit_code == 1
    assert result.output == "status=error reason_codes=parser_runtime_failed\n"


@pytest.mark.parametrize(
    ("mode", "runtime_tolerance"),
    (("verify", None), ("record", "0.2")),
)
def test_verify_corpus_cli_never_mutates_approved_membership_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    runtime_tolerance: str | None,
) -> None:
    inventory = tmp_path / "membership.json"
    approved_bytes = b"approved immutable inventory"
    inventory.write_bytes(approved_bytes)
    captured: list[CorpusGateConfig] = []

    def fake_gate(config: CorpusGateConfig, actual_mode: CorpusGateMode) -> CorpusGateAttestation:
        captured.append(config)
        return _corpus_attestation(mode=actual_mode)

    monkeypatch.setattr(cli_module, "run_corpus_gate", fake_gate, raising=False)
    arguments = [
        "verify-corpus",
        str(tmp_path / "retained"),
        "--quarantine-dir",
        str(tmp_path / "quarantine"),
        "--membership-inventory",
        str(inventory),
        "--baseline",
        str(tmp_path / "baseline.json"),
        "--work-dir",
        str(tmp_path / "run"),
        "--mode",
        mode,
        "--jobs",
        "3",
    ]
    if runtime_tolerance is not None:
        arguments.extend(("--runtime-tolerance", runtime_tolerance))

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert len(captured) == 1
    assert captured[0].membership_inventory_path == inventory
    assert captured[0].model_config["frozen"] is True
    assert inventory.read_bytes() == approved_bytes
