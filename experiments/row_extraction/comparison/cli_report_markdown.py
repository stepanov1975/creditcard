"""Private Markdown rendering for the complete aggregate comparison report."""

from __future__ import annotations

from .cli_report_projection import TableRow, display_value, project_comparison_report
from .reporting import ComparisonReport


def _table(
    lines: list[str],
    heading: str,
    headers: tuple[str, ...],
    rows: tuple[TableRow, ...],
) -> None:
    lines.extend(
        (
            f"## {heading}",
            "",
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
        )
    )
    lines.extend("| " + " | ".join(display_value(cell) for cell in row) + " |" for row in rows)
    lines.append("")


def render_comparison_markdown(report: ComparisonReport) -> bytes:
    """Render every tracked aggregate table without content or artifact identifiers."""

    projected = project_comparison_report(report)
    lines = [
        "# Locked row-extraction comparison",
        "",
        "This ignored private report contains aggregate experiment evidence only.",
        "",
    ]
    tables = (
        (
            "Exact rows and merchant extraction",
            (
                "result",
                "basis",
                "rows",
                "exact",
                "exact rate",
                "merchant eligible",
                "merchant exact",
                "merchant exact rate",
                "merchant normalized",
                "merchant normalized rate",
            ),
            projected.exact_rows,
        ),
        (
            "Typed fields, omissions, and hallucinations",
            (
                "result",
                "basis",
                "field",
                "eligible",
                "exact",
                "exact rate",
                "normalized",
                "normalized rate",
                "omissions",
                "omission rate",
                "hallucinations",
                "hallucination rate",
            ),
            projected.field_rows,
        ),
        (
            "Decisions and evidence limitations",
            (
                "result",
                "basis",
                "accepted",
                "abstained",
                "rejected",
                "ignored",
                "unsupported evidence",
                "ownership collisions",
            ),
            projected.decision_rows,
        ),
        ("OCR error", ("result", "basis", "CER", "WER", "limitation"), projected.ocr_rows),
        (
            "Calibration and abstention",
            (
                "result",
                "basis",
                "Brier",
                "log loss",
                "ECE",
                "risk-coverage area",
                "coverage",
                "selective risk",
            ),
            projected.calibration_rows,
        ),
        (
            "Calibration bins",
            (
                "result",
                "basis",
                "lower",
                "upper",
                "count",
                "mean confidence",
                "accuracy",
            ),
            projected.bin_rows,
        ),
        (
            "Risk coverage",
            ("result", "basis", "threshold", "coverage", "selective risk", "accepted"),
            projected.risk_rows,
        ),
        (
            "Coverage at predeclared risk",
            ("result", "basis", "target risk", "coverage"),
            projected.target_rows,
        ),
        (
            "Row types",
            ("result", "basis", "row type", "precision", "recall", "F1", "support"),
            projected.row_type_rows,
        ),
        (
            "Row-type confusion",
            ("result", "basis", "gold type", "predicted type", "count"),
            projected.confusion_rows,
        ),
        (
            "Closed error taxonomy",
            ("result", "basis", "category", "primary", "secondary"),
            projected.error_rows,
        ),
        (
            "Paired document-level effects",
            ("result", "control", "metric", "effect", "low", "high", "samples", "basis"),
            projected.interval_rows,
        ),
        (
            "Resources",
            (
                "result",
                "basis",
                "preparation ns",
                "fixed-row ns",
                "end-to-end ns",
                "cold-start ns",
                "p50 ns",
                "p95 ns",
                "rows/s",
                "peak RSS bytes",
            ),
            projected.resource_rows,
        ),
        (
            "Resource footprints",
            (
                "result",
                "basis",
                "model bytes",
                "dependency bytes",
                "cache bytes",
                "subprocesses",
                "workers",
                "protocol",
            ),
            projected.footprint_rows,
        ),
        (
            "Determinism",
            ("result", "deterministic", "locked", "repeat measurement present"),
            projected.determinism_rows,
        ),
        (
            "Pareto report",
            (
                "result",
                "basis",
                "deterministic",
                "resource basis",
                "exact",
                "merchant exact",
                "wrong required fields",
                "hallucinations",
                "coverage",
                "selective risk",
                "end-to-end ns",
                "peak RSS",
                "model bytes",
                "Pareto member",
            ),
            projected.pareto_rows,
        ),
    )
    for heading, headers, table_rows in tables:
        _table(lines, heading, headers, table_rows)
    lines.extend(
        (
            "## Limitations and decision linkage",
            "",
            f"- locked-test results: {', '.join(report.locked_experiment_ids)}",
            f"- validation-stopped results: {', '.join(report.validation_stopped_ids)}",
            "- stopped lanes were never opened on locked rows and cannot be production winners.",
            "- accepted-baseline resources are materialized-adapter measurements, "
            "not extraction cost or Pareto claims.",
            "- unavailable OCR evidence is explicit and is never represented as zero.",
            "- intervals resample documents and do not establish corpus-wide acceptance.",
            "- resource comparisons require one worker, new empty caches, common phase "
            "definitions, and verified runtime/resource bindings.",
            "- deterministic results require byte-identical canonical repeats from "
            "distinct cache and output locations.",
            "- the derived empty cascade has no incremental candidate rule and is "
            "excluded from Pareto and recommendation candidates.",
            "- only row-profiles is forwarded to the separate recommendation gate.",
            "- this comparison does not authorize production integration or "
            "private-corpus acceptance.",
            "",
        )
    )
    return "\n".join(lines).encode()


__all__ = ["render_comparison_markdown"]
