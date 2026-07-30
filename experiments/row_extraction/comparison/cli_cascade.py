"""Derived locked evaluation for the validation-frozen empty cascade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Never

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
    _FrozenModel,
)
from experiments.row_extraction.metrics import MetricReport, score_predictions

from .cascade import CascadeCandidates, CascadePolicy, apply_cascade
from .cli_locked_products import read_locked_products
from .cli_locked_records import LockedProducts
from .cli_manifest import PinnedArtifact, read_cli_manifest
from .cli_prelock import reverify_frozen_policy
from .cli_state import (
    create_stage,
    identity_for_bytes,
    write_bytes_exclusive,
    write_identified_model,
)
from .errors import classify_error
from .locked_artifacts import read_verified_jsonl


class CascadeLockedStageError(ValueError):
    """The frozen cascade cannot be derived from completed locked outputs."""


def _fail(message: str) -> Never:
    raise CascadeLockedStageError(message)


class DerivedCascadeEvaluationV1(_FrozenModel):
    version: Literal["row-comparison-derived-cascade-v1"]
    cascade_policy_identity: ArtifactIdentity
    row_sequence_identity: ArtifactIdentity
    baseline_predictions: tuple[ArtifactIdentity, ArtifactIdentity]
    profile_predictions: tuple[ArtifactIdentity, ArtifactIdentity]
    derived_predictions: tuple[PinnedArtifact, PinnedArtifact]
    metric_report: MetricReport
    metric_identity: ArtifactIdentity
    error_assignments: PinnedArtifact
    resource_basis: Literal["derived-policy-application-unmeasured"]
    candidate_policy_count: Literal[0]
    extraction_run_count: Literal[0]


class CascadeCompletionReceiptV1(_FrozenModel):
    version: Literal["row-comparison-cascade-completion-v1"]
    locked_completion_identity: ArtifactIdentity
    evaluation_identity: ArtifactIdentity
    cascade_policy_identity: ArtifactIdentity
    row_sequence_identity: ArtifactIdentity
    derived_repeat_identical: Literal[True]
    extraction_run_count: Literal[0]
    recommendation_candidate_count: Literal[0]


def derive_empty_cascade(
    rows: Sequence[FrozenRow],
    baseline: Sequence[RowPrediction],
    profiles: Sequence[RowPrediction],
    dispositions: Mapping[str, LaneDisposition],
) -> tuple[RowPrediction, ...]:
    """Apply the empty policy to existing predictions without invoking extraction."""

    if (
        not rows
        or len(rows) != len(baseline)
        or len(rows) != len(profiles)
        or dispositions.get("row-profiles") is not LaneDisposition.FROZEN_ELIGIBLE
    ):
        _fail("cascade input membership mismatch")
    policy = CascadePolicy(version="row-cascade-policy-v1", rules=())
    outputs: list[RowPrediction] = []
    for row, accepted, profile in zip(rows, baseline, profiles, strict=True):
        key = row.document_id, row.row_id
        if (
            (accepted.document_id, accepted.row_id) != key
            or (profile.document_id, profile.row_id) != key
            or accepted.experiment_id != "accepted-baseline"
            or profile.experiment_id != "row-profiles"
        ):
            _fail("cascade input row binding mismatch")
        outputs.append(
            apply_cascade(
                policy,
                CascadeCandidates(
                    row=row,
                    baseline=accepted,
                    candidates={"row-profiles": profile},
                    dispositions=dispositions,
                ),
            )
        )
    return tuple(outputs)


def _write_jsonl(path: Path, values: Sequence[_FrozenModel]) -> PinnedArtifact:
    payload = b"".join(_canonical_record_bytes(value) for value in values)
    write_bytes_exclusive(path, payload)
    return PinnedArtifact(
        path=path,
        identity=identity_for_bytes(payload, artifact_type="jsonl", version="canonical-jsonl-v1"),
    )


def _arm_predictions(
    products: LockedProducts,
    experiment_id: Literal["accepted-baseline", "row-profiles"],
) -> tuple[
    tuple[RowPrediction, ...], tuple[RowPrediction, ...], tuple[PinnedArtifact, PinnedArtifact]
]:
    arm = next(value for value in products.artifacts.arms if value.experiment_id == experiment_id)
    first = read_verified_jsonl(
        arm.first.predictions.path,
        arm.first.predictions.identity,
        RowPrediction,
        artifact_type="jsonl",
        message="cascade source prediction changed",
    )
    repeat = read_verified_jsonl(
        arm.repeat.predictions.path,
        arm.repeat.predictions.identity,
        RowPrediction,
        artifact_type="jsonl",
        message="cascade source prediction changed",
    )
    return first, repeat, (arm.first.predictions, arm.repeat.predictions)


def _private_markdown(evaluation: DerivedCascadeEvaluationV1) -> bytes:
    metrics = evaluation.metric_report
    return (
        "# Derived empty-cascade evaluation\n\n"
        "The cascade used no candidate rules and performed no extraction runs.\n\n"
        f"- rows: {metrics.row_count}\n"
        f"- exact rows: {metrics.exact_rows}\n"
        f"- accepted rows: {metrics.accepted_rows}\n"
        f"- abstained rows: {metrics.abstained_rows}\n"
    ).encode()


def evaluate_cascade_locked_stage(manifest_path: Path) -> dict[str, object]:
    """Derive the frozen empty cascade twice from existing locked prediction streams."""

    cli = read_cli_manifest(manifest_path)
    if (cli.workspace_root / "locked" / "cascade").exists():
        _fail("cascade stage already exists")
    products = read_locked_products(manifest_path)
    _cli, _snapshot, receipt, _receipt_id, _source, envelope, policy_identity = (
        reverify_frozen_policy(manifest_path)
    )
    if envelope.policy.rules or envelope.candidate_policy_count != 0:
        _fail("locked cascade policy is not empty")
    root = create_stage(products.cli.workspace_root / "locked", "cascade")
    baseline_first, baseline_repeat, baseline_pins = _arm_predictions(products, "accepted-baseline")
    profile_first, profile_repeat, profile_pins = _arm_predictions(products, "row-profiles")
    first = derive_empty_cascade(
        products.locked_inputs.rows,
        baseline_first,
        profile_first,
        receipt.dispositions,
    )
    repeat = derive_empty_cascade(
        products.locked_inputs.rows,
        baseline_repeat,
        profile_repeat,
        receipt.dispositions,
    )
    first_pin = _write_jsonl(root / "predictions.jsonl", first)
    repeat_pin = _write_jsonl(root / "repeat-predictions.jsonl", repeat)
    if first_pin.identity != repeat_pin.identity or first != repeat:
        _fail("derived cascade repeat mismatch")
    metrics = score_predictions(
        products.locked_inputs.rows,
        products.locked_inputs.gold,
        first,
        products.locked_inputs.ocr_references,
    )
    metric_identity = write_identified_model(
        root / "metrics.json",
        metrics,
        artifact_type="row-extraction-cascade-metric",
        version="row-extraction-cascade-metric-v1",
    )
    gold = {(value.document_id, value.row_id): value for value in products.locked_inputs.gold}
    assignments = tuple(
        classify_error(gold[(value.document_id, value.row_id)], value) for value in first
    )
    error_pin = _write_jsonl(root / "error-assignments.jsonl", assignments)
    evaluation = DerivedCascadeEvaluationV1(
        version="row-comparison-derived-cascade-v1",
        cascade_policy_identity=policy_identity,
        row_sequence_identity=products.locked_inputs.row_sequence_identity,
        baseline_predictions=(baseline_pins[0].identity, baseline_pins[1].identity),
        profile_predictions=(profile_pins[0].identity, profile_pins[1].identity),
        derived_predictions=(first_pin, repeat_pin),
        metric_report=metrics,
        metric_identity=metric_identity,
        error_assignments=error_pin,
        resource_basis="derived-policy-application-unmeasured",
        candidate_policy_count=0,
        extraction_run_count=0,
    )
    evaluation_identity = write_identified_model(
        root / "evaluation.json",
        evaluation,
        artifact_type="row-extraction-derived-cascade-evaluation",
        version="row-comparison-derived-cascade-v1",
    )
    write_bytes_exclusive(root / "evaluation.md", _private_markdown(evaluation))
    completion = CascadeCompletionReceiptV1(
        version="row-comparison-cascade-completion-v1",
        locked_completion_identity=products.receipt_identity,
        evaluation_identity=evaluation_identity,
        cascade_policy_identity=policy_identity,
        row_sequence_identity=products.locked_inputs.row_sequence_identity,
        derived_repeat_identical=True,
        extraction_run_count=0,
        recommendation_candidate_count=0,
    )
    write_identified_model(
        root / "completion-receipt.json",
        completion,
        artifact_type="row-comparison-cascade-completion",
        version="row-comparison-cascade-completion-v1",
    )
    return {
        "candidate_policy_count": 0,
        "command": "evaluate-cascade-locked",
        "complete": True,
        "extraction_run_count": 0,
    }


__all__ = [
    "CascadeCompletionReceiptV1",
    "CascadeLockedStageError",
    "DerivedCascadeEvaluationV1",
    "derive_empty_cascade",
    "evaluate_cascade_locked_stage",
]
