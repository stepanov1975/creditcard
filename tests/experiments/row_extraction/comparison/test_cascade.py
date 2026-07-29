from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path

import pytest

from experiments.row_extraction.comparison.cascade import (
    CascadeCandidates,
    CascadePolicy,
    CascadePolicyError,
    CascadeRule,
    CascadeValidation,
    CascadeValidationRow,
    apply_cascade,
    select_cascade_policy,
)
from experiments.row_extraction.contracts import (
    DatasetSplit,
    Decision,
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)


def _accepted_prediction(
    *,
    experiment_id: str = "accepted-baseline",
    atom_text: str = "SYNTHETIC SHOP",
    confidence: float | None = 1.0,
    decision: Decision = Decision.ACCEPT,
) -> RowPrediction:
    description = EvidenceAtom(
        atom_id="description-1",
        text=atom_text,
        bbox=(10.0, 10.0, 80.0, 20.0),
        source="digital",
        confidence=1.0,
        column_index=1,
    )
    billed = EvidenceAtom(
        atom_id="billed-1",
        text="-12.34",
        bbox=(110.0, 10.0, 145.0, 20.0),
        source="digital",
        confidence=1.0,
        column_index=2,
    )
    currency = EvidenceAtom(
        atom_id="currency-1",
        text="USD",
        bbox=(150.0, 10.0, 180.0, 20.0),
        source="digital",
        confidence=1.0,
        column_index=3,
    )
    return RowPrediction(
        experiment_id=experiment_id,
        config_id="synthetic-v1",
        document_id="0" * 64,
        row_id="row-1",
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=(description, billed, currency),
        proposals=(
            FieldProposal(
                role=FieldRole.DESCRIPTION,
                atom_ids=(description.atom_id,),
                raw_score=1.0,
            ),
            FieldProposal(
                role=FieldRole.BILLED_AMOUNT,
                atom_ids=(billed.atom_id,),
                raw_score=1.0,
            ),
            FieldProposal(
                role=FieldRole.BILLING_CURRENCY,
                atom_ids=(currency.atom_id,),
                raw_score=1.0,
            ),
            FieldProposal(
                role=FieldRole.KIND,
                atom_ids=(billed.atom_id,),
                raw_score=1.0,
            ),
        ),
        exact_row_confidence=confidence,
        decision=decision,
        reasons=(),
    )


def _fixed_row(prediction: RowPrediction) -> FrozenRow:
    return FrozenRow(
        document_id=prediction.document_id,
        row_id=prediction.row_id,
        split=DatasetSplit.VALIDATION,
        source_pdf=Path("private/synthetic.pdf"),
        page_number=1,
        bbox=(0.0, 0.0, 200.0, 40.0),
        baseline_type=RowType.PRIMARY_TRANSACTION,
        column_bands=(),
        atoms=prediction.evidence_atoms,
        render_version="synthetic-v1",
    )


def _cascade_candidates(
    *,
    baseline: RowPrediction,
    candidates: Mapping[str, RowPrediction],
    dispositions: Mapping[str, LaneDisposition],
    reconciliation: Callable[[RowPrediction], object] | None = None,
) -> CascadeCandidates:
    kwargs: dict[str, object] = {}
    if reconciliation is not None:
        kwargs["reconciliation"] = reconciliation
    return CascadeCandidates(
        row=_fixed_row(baseline),
        baseline=baseline,
        candidates=candidates,
        dispositions=dispositions,
        **kwargs,
    )


def test_empty_cascade_preserves_grounded_accepted_baseline() -> None:
    baseline = _accepted_prediction()

    result = apply_cascade(
        CascadePolicy(version="cascade-v1", rules=()),
        _cascade_candidates(baseline=baseline, candidates={}, dispositions={}),
    )

    assert result == baseline
    assert result.experiment_id == "accepted-baseline"
    assert result.exact_row_confidence == Decimal("1")


def test_empty_cascade_abstains_when_accepted_baseline_is_not_grounded() -> None:
    result = apply_cascade(
        CascadePolicy(version="cascade-v1", rules=()),
        _cascade_candidates(
            baseline=_accepted_prediction(atom_text=""),
            candidates={},
            dispositions={},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_evidence_contract_failed",)


def test_validation_stopped_lane_cannot_enter_policy_execution() -> None:
    candidate = _accepted_prediction(experiment_id="row-ocr", confidence=0.99)
    inputs = _cascade_candidates(
        baseline=_accepted_prediction(
            confidence=None,
            decision=Decision.ABSTAIN,
        ),
        candidates={"row-ocr": candidate},
        dispositions={"row-ocr": LaneDisposition.VALIDATION_STOPPED},
    )
    policy = CascadePolicy(
        version="cascade-v1",
        rules=(CascadeRule("row-ocr", Decimal("0.95")),),
    )

    with pytest.raises(CascadePolicyError, match="validation-stopped"):
        apply_cascade(policy, inputs)


def test_deterministic_candidate_without_confidence_cannot_override() -> None:
    candidate = _accepted_prediction(
        experiment_id="row-profiles",
        confidence=None,
    )

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-profiles", Decimal("0")),),
        ),
        _cascade_candidates(
            baseline=_accepted_prediction(
                confidence=None,
                decision=Decision.ABSTAIN,
            ),
            candidates={"row-profiles": candidate},
            dispositions={"row-profiles": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_uncalibrated_candidate",)


def test_reconciliation_cannot_replace_selected_candidate() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)

    def rank_candidate(_: RowPrediction) -> object:
        return _accepted_prediction(experiment_id="row-vision", confidence=0.99)

    inputs = _cascade_candidates(
        baseline=_accepted_prediction(
            confidence=None,
            decision=Decision.ABSTAIN,
        ),
        candidates={"row-text": candidate},
        dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        reconciliation=rank_candidate,
    )

    with pytest.raises(CascadePolicyError, match="reconciliation is rejection-only"):
        apply_cascade(
            CascadePolicy(
                version="cascade-v1",
                rules=(CascadeRule("row-text", Decimal("0.95")),),
            ),
            inputs,
        )


def test_reconciliation_can_only_reject_selected_candidate_unchanged() -> None:
    baseline = _accepted_prediction()

    result = apply_cascade(
        CascadePolicy(version="cascade-v1", rules=()),
        _cascade_candidates(
            baseline=baseline,
            candidates={},
            dispositions={},
            reconciliation=lambda _: Decision.REJECT,
        ),
    )

    assert result.experiment_id == baseline.experiment_id
    assert result.proposals == baseline.proposals
    assert result.decision is Decision.REJECT
    assert result.reasons == ("cascade_reconciliation_rejected",)


def test_calibrated_grounded_candidate_can_fill_unresolved_baseline() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=_accepted_prediction(
                confidence=None,
                decision=Decision.ABSTAIN,
            ),
            candidates={"row-text": candidate},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result == candidate


def test_required_agreement_must_match_exact_grounded_fields() -> None:
    learned = _accepted_prediction(experiment_id="row-text", confidence=0.99)
    disagreeing = _accepted_prediction(
        experiment_id="row-profiles",
        atom_text="DIFFERENT SYNTHETIC SHOP",
        confidence=None,
    )

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(
                CascadeRule(
                    "row-text",
                    Decimal("0.95"),
                    requires_agreement=("row-profiles",),
                ),
            ),
        ),
        _cascade_candidates(
            baseline=_accepted_prediction(
                confidence=None,
                decision=Decision.ABSTAIN,
            ),
            candidates={"row-text": learned, "row-profiles": disagreeing},
            dispositions={
                "row-text": LaneDisposition.FROZEN_ELIGIBLE,
                "row-profiles": LaneDisposition.FROZEN_ELIGIBLE,
            },
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_required_agreement_failed",)


def test_evidence_contract_failure_abstains_without_trying_later_rule() -> None:
    invalid = _accepted_prediction(
        experiment_id="row-text",
        atom_text="",
        confidence=0.99,
    )
    later = _accepted_prediction(experiment_id="row-vision", confidence=0.99)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(
                CascadeRule("row-text", Decimal("0.95")),
                CascadeRule("row-vision", Decimal("0.95")),
            ),
        ),
        _cascade_candidates(
            baseline=_accepted_prediction(
                confidence=None,
                decision=Decision.ABSTAIN,
            ),
            candidates={"row-text": invalid, "row-vision": later},
            dispositions={
                "row-text": LaneDisposition.FROZEN_ELIGIBLE,
                "row-vision": LaneDisposition.FROZEN_ELIGIBLE,
            },
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_evidence_contract_failed",)


def test_incomplete_primary_candidate_fails_deterministic_field_validation() -> None:
    incomplete = _accepted_prediction(
        experiment_id="row-text",
        confidence=0.99,
    )
    incomplete = incomplete.model_copy(update={"proposals": incomplete.proposals[:1]})
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=baseline,
            candidates={"row-text": incomplete},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_deterministic_validation_failed",)


def test_wrong_owner_candidate_fails_deterministic_field_validation() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)
    wrong_owner = candidate.proposals[0].model_copy(update={"owner_row_id": "row-other"})
    candidate = candidate.model_copy(update={"proposals": (wrong_owner, *candidate.proposals[1:])})
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=baseline,
            candidates={"row-text": candidate},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_deterministic_validation_failed",)


def test_blank_owner_candidate_fails_deterministic_field_validation() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)
    blank_owner = candidate.proposals[0].model_copy(update={"owner_row_id": ""})
    candidate = candidate.model_copy(update={"proposals": (blank_owner, *candidate.proposals[1:])})
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=baseline,
            candidates={"row-text": candidate},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_deterministic_validation_failed",)


def test_nonoverlapping_source_region_fails_deterministic_field_validation() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)
    unsupported = candidate.proposals[0].model_copy(
        update={"source_region": (90.0, 25.0, 100.0, 35.0)}
    )
    candidate = candidate.model_copy(update={"proposals": (unsupported, *candidate.proposals[1:])})
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=baseline,
            candidates={"row-text": candidate},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_deterministic_validation_failed",)


def test_explicit_amount_currency_mismatch_fails_deterministic_validation() -> None:
    candidate = _accepted_prediction(experiment_id="row-text", confidence=0.99)
    mismatched_amount = candidate.evidence_atoms[1].model_copy(update={"text": "EUR -12.34"})
    candidate = candidate.model_copy(
        update={
            "evidence_atoms": (
                candidate.evidence_atoms[0],
                mismatched_amount,
                candidate.evidence_atoms[2],
            )
        }
    )
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)

    result = apply_cascade(
        CascadePolicy(
            version="cascade-v1",
            rules=(CascadeRule("row-text", Decimal("0.95")),),
        ),
        _cascade_candidates(
            baseline=baseline,
            candidates={"row-text": candidate},
            dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
        ),
    )

    assert result.decision is Decision.ABSTAIN
    assert result.reasons == ("cascade_deterministic_validation_failed",)


def test_validation_selection_keeps_empty_policy_when_only_arm_cannot_override() -> None:
    row = CascadeValidationRow(
        candidates=_cascade_candidates(
            baseline=_accepted_prediction(
                confidence=None,
                decision=Decision.ABSTAIN,
            ),
            candidates={
                "row-profiles": _accepted_prediction(
                    experiment_id="row-profiles",
                    confidence=None,
                )
            },
            dispositions={"row-profiles": LaneDisposition.FROZEN_ELIGIBLE},
        ),
        exact_outcomes={"accepted-baseline": False, "row-profiles": True},
        accepted_row_error_arms=frozenset(),
        required_field_error_arms=frozenset(),
        omission_counts={"row-profiles": 0},
        latency_ns={"row-profiles": 100},
    )

    selected = select_cascade_policy(
        CascadeValidation(
            version="cascade-v1",
            rows=(row,),
            candidate_policies=(
                CascadePolicy(
                    version="cascade-v1",
                    rules=(CascadeRule("row-profiles", Decimal("0")),),
                ),
            ),
            deterministic_arms={"row-profiles": True},
            maximum_accepted_row_errors=0,
            maximum_required_field_errors=0,
        )
    )

    assert selected == CascadePolicy(version="cascade-v1", rules=())


@pytest.mark.parametrize("threshold", (Decimal("-0.01"), Decimal("1.01"), Decimal("NaN")))
def test_cascade_rule_rejects_invalid_confidence_threshold(threshold: Decimal) -> None:
    with pytest.raises(CascadePolicyError, match="confidence threshold"):
        CascadeRule("row-text", threshold)


def test_validation_selection_rejects_policy_above_accepted_row_risk_bound() -> None:
    policy = CascadePolicy(
        version="cascade-v1",
        rules=(CascadeRule("row-text", Decimal("0.95")),),
    )

    def validation_row(*, row_id: str, exact: bool) -> CascadeValidationRow:
        baseline = _accepted_prediction(
            confidence=None,
            decision=Decision.ABSTAIN,
        ).model_copy(update={"row_id": row_id})
        candidate = _accepted_prediction(
            experiment_id="row-text",
            confidence=0.99,
        ).model_copy(update={"row_id": row_id})
        return CascadeValidationRow(
            candidates=_cascade_candidates(
                baseline=baseline,
                candidates={"row-text": candidate},
                dispositions={"row-text": LaneDisposition.FROZEN_ELIGIBLE},
            ),
            exact_outcomes={"accepted-baseline": False, "row-text": exact},
            accepted_row_error_arms=frozenset() if exact else frozenset({"row-text"}),
            required_field_error_arms=frozenset(),
            omission_counts={"row-text": 0},
            latency_ns={"row-text": 100},
        )

    selected = select_cascade_policy(
        CascadeValidation(
            version="cascade-v1",
            rows=(
                validation_row(row_id="row-1", exact=True),
                validation_row(row_id="row-2", exact=False),
            ),
            candidate_policies=(policy,),
            deterministic_arms={"row-text": True},
            maximum_accepted_row_errors=0,
            maximum_required_field_errors=0,
        )
    )

    assert selected.rules == ()


def test_validation_selection_rejects_locked_test_row() -> None:
    baseline = _accepted_prediction(confidence=None, decision=Decision.ABSTAIN)
    test_row = _fixed_row(baseline).model_copy(update={"split": DatasetSplit.TEST})
    row = CascadeValidationRow(
        candidates=CascadeCandidates(
            row=test_row,
            baseline=baseline,
            candidates={},
            dispositions={},
        ),
        exact_outcomes={"accepted-baseline": False},
        accepted_row_error_arms=frozenset(),
        required_field_error_arms=frozenset(),
        omission_counts={},
        latency_ns={},
    )

    with pytest.raises(CascadePolicyError, match="validation split"):
        select_cascade_policy(
            CascadeValidation(
                version="cascade-v1",
                rows=(row,),
                candidate_policies=(),
                deterministic_arms={},
                maximum_accepted_row_errors=0,
                maximum_required_field_errors=0,
            )
        )
