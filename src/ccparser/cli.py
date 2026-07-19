"""Privacy-safe Typer commands for local statement parsing and audit."""

from __future__ import annotations

import unicodedata
from collections import Counter
from functools import partial
from pathlib import Path
from typing import Annotated

import typer

from ccparser.audit import AuditReport, audit_directory
from ccparser.evidence import TesseractOcr, extract_pdf
from ccparser.models import BatchResult, StatementResult, Status
from ccparser.output import write_csv_atomic, write_json_atomic
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
    write_json_atomic(output_dir / "results.json", batch)
    write_csv_atomic(output_dir / "transactions.csv", batch)


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
    jobs: Annotated[int | None, typer.Option("--jobs", metavar="N")] = None,
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir", metavar="DIR")] = None,
) -> None:
    """Parse one PDF or a directory and write canonical JSON and CSV."""

    try:
        if jobs is not None and jobs <= 0:
            raise ParserInputError("jobs must be a positive integer")
        if input_path.is_dir():
            batch = parse_directory(
                input_path,
                output_dir,
                strict,
                jobs,
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
