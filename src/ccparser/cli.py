"""Privacy-safe Typer commands for local statement parsing and audit."""

from __future__ import annotations

import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
from typer._click.core import Context as ClickContext
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from ccparser.audit import AuditReport, audit_directory
from ccparser.corpus_gate import (
    CorpusGateAcceptanceError,
    CorpusGateAttestation,
    CorpusGateConfig,
    CorpusGateInputError,
    CorpusGateMode,
    CorpusGateReason,
    CorpusGateRuntimeError,
    run_corpus_gate,
)
from ccparser.evidence import TesseractOcr, extract_pdf
from ccparser.models import BatchResult, StatementResult, Status
from ccparser.output import write_batch_outputs
from ccparser.parser import (
    ParserInputError,
    default_cache_directory,
    parse_directory,
    parse_statement,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _safe_console_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return "".join(character if character.isprintable() else "?" for character in normalized)


def _batch_for_statement(statement: StatementResult) -> BatchResult:
    diagnostics = (
        ("documents_not_reconciled:1",) if statement.status is not Status.RECONCILED else ()
    )
    return BatchResult(
        status=statement.status,
        statements=(statement,),
        diagnostics=diagnostics,
    )


def _write_single_output(output_dir: Path, batch: BatchResult) -> None:
    write_batch_outputs(output_dir, batch)


def _validated_jobs(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        jobs = int(value)
    except ValueError:
        raise ParserInputError("jobs must be a positive integer") from None
    if jobs <= 0:
        raise ParserInputError("jobs must be a positive integer")
    return jobs


def _invalid_gate_configuration() -> CorpusGateInputError:
    return CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))


def _required_gate_value(value: str | None) -> str:
    if value is None or not value:
        raise _invalid_gate_configuration()
    return value


def _validated_gate_mode(value: str | None) -> CorpusGateMode:
    try:
        return CorpusGateMode(_required_gate_value(value))
    except ValueError:
        raise _invalid_gate_configuration() from None


def _validated_gate_jobs(value: str | None) -> int:
    try:
        jobs = int(_required_gate_value(value))
    except ValueError:
        raise _invalid_gate_configuration() from None
    if jobs <= 0:
        raise _invalid_gate_configuration()
    return jobs


def _validated_lowercase_hex(value: str | None, *, length: int) -> str:
    candidate = _required_gate_value(value)
    if len(candidate) != length or any(
        character not in "0123456789abcdef" for character in candidate
    ):
        raise _invalid_gate_configuration()
    return candidate


def _validated_runtime_tolerance(
    value: str | None,
    mode: CorpusGateMode,
) -> Decimal | None:
    if mode is CorpusGateMode.VERIFY:
        if value is not None:
            raise _invalid_gate_configuration()
        return None
    if value is None or not value:
        raise _invalid_gate_configuration()
    try:
        tolerance = Decimal(value)
    except (InvalidOperation, ValueError):
        raise _invalid_gate_configuration() from None
    if not tolerance.is_finite() or tolerance < 0:
        raise _invalid_gate_configuration()
    return tolerance


def _validated_baseline_sha256(
    value: str | None,
    mode: CorpusGateMode,
) -> str | None:
    if mode is CorpusGateMode.RECORD:
        if value is not None:
            raise _invalid_gate_configuration()
        return None
    return _validated_lowercase_hex(value, length=64)


def _gate_reason_values(reasons: tuple[CorpusGateReason, ...]) -> str:
    return ",".join(reason.value for reason in reasons)


def _print_gate_failure(
    status: str,
    reasons: tuple[CorpusGateReason, ...],
) -> None:
    typer.echo(f"status={status} reason_codes={_gate_reason_values(reasons)}", err=True)


def _print_gate_attestation(attestation: CorpusGateAttestation) -> None:
    typer.echo(
        " ".join(
            (
                "status=passed",
                f"mode={attestation.mode.value}",
                f"retained={attestation.retained_counts.documents}",
                f"reconciled={attestation.retained_counts.reconciled}",
                f"quarantined={attestation.quarantine_counts.documents}",
                f"elapsed_seconds={attestation.elapsed_seconds}",
                f"performance_checked={str(attestation.performance_checked).lower()}",
            )
        )
    )


class _CorpusGateCommand(TyperCommand):
    """Map this command's parser-level contract failures to the gate's safe exit."""

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except UsageError:
            _print_gate_failure("error", (CorpusGateReason.INVALID_CONFIGURATION,))
            raise typer.Exit(1) from None


def _print_batch(batch: BatchResult, fallback_name: str) -> None:
    counts = Counter(statement.status.value for statement in batch.statements)
    typer.echo(
        " ".join(
            (
                f"status={batch.status.value}",
                f"documents={len(batch.statements)}",
                f"reconciled={counts[Status.RECONCILED.value]}",
                f"unreconciled={counts[Status.UNRECONCILED.value]}",
                f"unsupported={counts[Status.UNSUPPORTED.value]}",
                f"not_statement={counts[Status.NOT_STATEMENT.value]}",
            )
        )
    )
    for index, statement in enumerate(batch.statements, start=1):
        source = statement.source_name or (fallback_name if len(batch.statements) == 1 else "")
        if not source:
            source = f"document-{index:04d}"
        typer.echo(f"{_safe_console_name(source)} {statement.status.value}")


@app.command("parse")
def parse_command(
    input_path: Annotated[Path, typer.Argument(metavar="INPUT")],
    output_dir: Annotated[Path, typer.Option("--output-dir", metavar="DIR")],
    strict: Annotated[bool, typer.Option("--strict")] = False,
    jobs: Annotated[str | None, typer.Option("--jobs", metavar="N")] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir", metavar="DIR")] = None,
) -> None:
    """Parse one PDF or a directory and write canonical JSON and CSV."""

    try:
        validated_jobs = _validated_jobs(jobs)
        if input_path.is_dir():
            batch = parse_directory(
                input_path,
                output_dir,
                strict,
                validated_jobs,
                cache_dir=cache_dir,
            )
        else:
            statement = parse_statement(
                input_path,
                strict,
                cache_dir=cache_dir,
            )
            batch = _batch_for_statement(statement)
            _write_single_output(output_dir, batch)
    except Exception:
        typer.echo("input_or_runtime_error", err=True)
        raise typer.Exit(1) from None

    _print_batch(batch, input_path.name)
    if strict and batch.status is not Status.RECONCILED:
        raise typer.Exit(2)


@app.command("verify-corpus", cls=_CorpusGateCommand)
def verify_corpus_command(
    retained_dir: Annotated[str | None, typer.Argument(metavar="RETAINED")] = None,
    expected_commit_sha: Annotated[
        str | None,
        typer.Option("--expected-commit-sha", metavar="SHA"),
    ] = None,
    quarantine_dir: Annotated[
        str | None,
        typer.Option("--quarantine-dir", metavar="DIR"),
    ] = None,
    membership_inventory: Annotated[
        str | None,
        typer.Option("--membership-inventory", metavar="FILE"),
    ] = None,
    membership_inventory_sha256: Annotated[
        str | None,
        typer.Option("--membership-inventory-sha256", metavar="SHA256"),
    ] = None,
    baseline: Annotated[
        str | None,
        typer.Option("--baseline", metavar="FILE"),
    ] = None,
    baseline_sha256: Annotated[
        str | None,
        typer.Option("--baseline-sha256", metavar="SHA256"),
    ] = None,
    work_dir: Annotated[
        str | None,
        typer.Option("--work-dir", metavar="DIR"),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option("--mode", metavar="MODE"),
    ] = None,
    jobs: Annotated[
        str | None,
        typer.Option("--jobs", metavar="N"),
    ] = None,
    runtime_tolerance: Annotated[
        str | None,
        typer.Option("--runtime-tolerance", metavar="RATIO"),
    ] = None,
) -> None:
    """Run the private corpus acceptance gate and print one aggregate attestation."""

    try:
        validated_mode = _validated_gate_mode(mode)
        config = CorpusGateConfig(
            expected_commit_sha=_validated_lowercase_hex(expected_commit_sha, length=40),
            retained_dir=Path(_required_gate_value(retained_dir)),
            quarantine_dir=Path(_required_gate_value(quarantine_dir)),
            membership_inventory_path=Path(_required_gate_value(membership_inventory)),
            membership_inventory_sha256=_validated_lowercase_hex(
                membership_inventory_sha256,
                length=64,
            ),
            baseline_path=Path(_required_gate_value(baseline)),
            baseline_sha256=_validated_baseline_sha256(
                baseline_sha256,
                validated_mode,
            ),
            work_dir=Path(_required_gate_value(work_dir)),
            jobs=_validated_gate_jobs(jobs),
            runtime_tolerance_ratio=_validated_runtime_tolerance(
                runtime_tolerance,
                validated_mode,
            ),
        )
        attestation = run_corpus_gate(config, validated_mode)
        if not attestation.passed:
            raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,))
        if validated_mode is CorpusGateMode.VERIFY and not attestation.performance_checked:
            raise CorpusGateAcceptanceError((CorpusGateReason.RUNTIME_CONTEXT_DRIFT,))
    except CorpusGateAcceptanceError as error:
        _print_gate_failure("failed", error.reasons)
        raise typer.Exit(2) from None
    except (CorpusGateInputError, CorpusGateRuntimeError) as error:
        _print_gate_failure("error", error.reasons)
        raise typer.Exit(1) from None
    except Exception:
        _print_gate_failure("error", (CorpusGateReason.PARSER_RUNTIME_FAILED,))
        raise typer.Exit(1) from None

    _print_gate_attestation(attestation)


def _print_audit(report: AuditReport) -> None:
    counts = Counter(decision.action.value for decision in report.decisions)
    typer.echo(
        " ".join(
            (
                f"documents={len(report.decisions)}",
                f"keep={counts['keep']}",
                f"review={counts['review']}",
                f"quarantine={counts['quarantine']}",
                f"moved={report.moved_count}",
            )
        )
    )
    for decision in report.decisions:
        typer.echo(f"{_safe_console_name(decision.original_relative_path)} {decision.action.value}")


@app.command("audit")
def audit_command(
    input_path: Annotated[Path, typer.Argument(metavar="INPUT")],
    quarantine_dir: Annotated[Path, typer.Option("--quarantine-dir", metavar="DIR")],
    apply: Annotated[bool, typer.Option("--apply")] = False,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir", metavar="DIR")] = None,
) -> None:
    """Classify PDFs and optionally quarantine only positive non-statements."""

    try:
        ocr_provider = TesseractOcr(cache_dir or default_cache_directory())
        extractor = partial(extract_pdf, ocr_provider=ocr_provider)
        report = audit_directory(
            input_path,
            quarantine_dir,
            apply,
            extractor=extractor,
        )
    except Exception:
        typer.echo("input_or_runtime_error", err=True)
        raise typer.Exit(1) from None
    _print_audit(report)


__all__ = ["app"]
