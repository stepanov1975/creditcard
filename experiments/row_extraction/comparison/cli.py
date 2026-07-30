"""Privacy-safe exactly-once comparison and cascade command boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Never

import typer

from ccparser.output import _canonical_json_value_content

from .cli_cascade import evaluate_cascade_locked_stage
from .cli_compare import compare_locked_stage
from .cli_prelock import select_cascade_validation_stage, validate_handoffs_stage
from .cli_recommend import recommend_stage
from .recommend import RecommendationKind, RecommendationReasonCode
from .result_catalog import LANE_ID_SET

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate, execute, and report the fixed locked row comparison.",
)


def _abort(code: str) -> Never:
    typer.echo(code, err=True)
    raise typer.Exit(code=1) from None


_SUCCESS_CONTRACTS = {
    "ROW_COMPARISON_HANDOFF_ERROR": (
        "validate-handoffs",
        frozenset({"command", "complete", "eligible_lane_count", "stopped_lane_count"}),
    ),
    "ROW_COMPARISON_POLICY_ERROR": (
        "select-cascade-validation",
        frozenset({"candidate_policy_count", "command", "complete", "rule_count"}),
    ),
    "ROW_COMPARISON_LOCKED_ERROR": (
        "compare-locked",
        frozenset(
            {
                "command",
                "complete",
                "deterministic_result_count",
                "locked_result_count",
                "stopped_result_count",
            }
        ),
    ),
    "ROW_COMPARISON_CASCADE_ERROR": (
        "evaluate-cascade-locked",
        frozenset({"candidate_policy_count", "command", "complete", "extraction_run_count"}),
    ),
    "ROW_COMPARISON_RECOMMEND_ERROR": (
        "recommend",
        frozenset(
            {
                "candidate_count",
                "cascade_candidate_count",
                "command",
                "complete",
                "decision",
                "reason_codes",
                "selected_ids",
            }
        ),
    ),
}


def _validated_aggregate(code: str, aggregate: dict[str, object]) -> dict[str, object]:
    expected_command, expected_keys = _SUCCESS_CONTRACTS[code]
    if (
        set(aggregate) != set(expected_keys)
        or aggregate.get("command") != expected_command
        or aggregate.get("complete") is not True
    ):
        raise ValueError("invalid aggregate output")
    count_values = tuple(
        value
        for key, value in aggregate.items()
        if key not in {"command", "complete", "decision", "reason_codes", "selected_ids"}
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in count_values
    ):
        raise ValueError("invalid aggregate output")
    if expected_command != "recommend":
        return aggregate
    decision = aggregate["decision"]
    reasons = aggregate["reason_codes"]
    selected = aggregate["selected_ids"]
    if (
        decision not in {value.value for value in RecommendationKind}
        or not isinstance(reasons, tuple)
        or not reasons
        or any(value not in {code.value for code in RecommendationReasonCode} for value in reasons)
        or not isinstance(selected, tuple)
        or any(value not in LANE_ID_SET for value in selected)
    ):
        raise ValueError("invalid aggregate output")
    return aggregate


def _run_safely(code: str, operation: Callable[[], dict[str, object]]) -> None:
    try:
        aggregate = _validated_aggregate(code, operation())
        typer.echo(_canonical_json_value_content(aggregate).decode("utf-8"))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        _abort(code)


@app.command("validate-handoffs")
def validate_handoffs_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
) -> None:
    """Validate and normalize every frozen handoff before locked access."""

    _run_safely(
        "ROW_COMPARISON_HANDOFF_ERROR",
        lambda: validate_handoffs_stage(manifest),
    )


@app.command("select-cascade-validation")
def select_cascade_validation_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
) -> None:
    """Freeze the reviewed empty cascade using validation evidence only."""

    _run_safely(
        "ROW_COMPARISON_POLICY_ERROR",
        lambda: select_cascade_validation_stage(manifest),
    )


@app.command("compare-locked")
def compare_locked_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
) -> None:
    """Perform the exclusive eight-run locked comparison."""

    _run_safely(
        "ROW_COMPARISON_LOCKED_ERROR",
        lambda: compare_locked_stage(manifest),
    )


@app.command("evaluate-cascade-locked")
def evaluate_cascade_locked_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
) -> None:
    """Derive and score the empty-policy cascade without a ninth extraction run."""

    _run_safely(
        "ROW_COMPARISON_CASCADE_ERROR",
        lambda: evaluate_cascade_locked_stage(manifest),
    )


@app.command("recommend")
def recommend_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
) -> None:
    """Produce the evidence-bound no-change or design-integration decision."""

    _run_safely(
        "ROW_COMPARISON_RECOMMEND_ERROR",
        lambda: recommend_stage(manifest),
    )


if __name__ == "__main__":
    app()
