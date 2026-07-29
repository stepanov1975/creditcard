from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from decimal import Decimal

import pytest

from experiments.row_extraction.contracts import (
    Decision,
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    GoldField,
    GoldRow,
    OcrReference,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.metrics import (
    DESCRIPTION_NORMALIZATION_VERSION,
    ScoringInputError,
    character_error_rate,
    risk_coverage,
    score_predictions,
    word_error_rate,
)

_DOCUMENT_ID = "0" * 64


def _gold_row(
    *,
    row_id: str,
    row_type: RowType = RowType.CONTINUATION,
    fields: tuple[GoldField, ...] = (),
) -> GoldRow:
    return GoldRow(
        document_id=_DOCUMENT_ID,
        row_id=row_id,
        row_type=row_type,
        fields=fields,
    )


def _description_field(value: str = "SYNTHETIC MERCHANT") -> GoldField:
    return GoldField(
        role=FieldRole.DESCRIPTION,
        canonical_value=value,
        atom_ids=("description",),
    )


def _gold_field(role: FieldRole, value: str) -> GoldField:
    return GoldField(
        role=role,
        canonical_value=value,
        atom_ids=("field",),
    )


def _prediction(
    *,
    row_id: str,
    predicted_type: RowType = RowType.CONTINUATION,
    decision: Decision = Decision.ACCEPT,
    description: str | None = None,
    confidence: float | None = 0.9,
) -> RowPrediction:
    atoms: tuple[EvidenceAtom, ...] = ()
    proposals: tuple[FieldProposal, ...] = ()
    if description is not None:
        atoms = (
            EvidenceAtom(
                atom_id="description",
                text=description,
                bbox=(0.0, 0.0, 10.0, 10.0),
                source="digital",
                confidence=1.0,
                column_index=0,
            ),
        )
        proposals = (
            FieldProposal(
                role=FieldRole.DESCRIPTION,
                atom_ids=("description",),
                raw_score=1.0,
            ),
        )
    return RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=_DOCUMENT_ID,
        row_id=row_id,
        predicted_type=predicted_type,
        evidence_atoms=atoms,
        proposals=proposals,
        exact_row_confidence=confidence,
        decision=decision,
        reasons=() if decision is Decision.ACCEPT else ("synthetic_abstention",),
    )


def test_score_predictions_counts_a_complete_accepted_row_as_exact() -> None:
    report = score_predictions(
        gold=(
            _gold_row(
                row_id="row-1",
                fields=(_description_field(),),
            ),
        ),
        predictions=(_prediction(row_id="row-1", description="SYNTHETIC MERCHANT"),),
    )

    assert report.row_count == 1
    assert report.exact_rows == 1
    assert report.exact_row_rate == Decimal("1")
    assert report.fields[FieldRole.DESCRIPTION].exact_matches == 1


def test_score_predictions_separates_omission_from_hallucination() -> None:
    report = score_predictions(
        gold=(
            _gold_row(row_id="row-1", fields=(_description_field(),)),
            _gold_row(row_id="row-2", row_type=RowType.STRUCTURAL),
        ),
        predictions=(
            _prediction(row_id="row-1", decision=Decision.ABSTAIN),
            _prediction(
                row_id="row-2",
                predicted_type=RowType.STRUCTURAL,
                description="SYNTHETIC EXTRA",
            ),
        ),
    )

    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.omissions == 1
    assert merchant.hallucinations == 1


def test_risk_coverage_counts_wrong_accepted_rows() -> None:
    points = risk_coverage(
        outcomes=((0.9, True), (0.8, False), (0.2, True)),
    )

    assert points[1].coverage == Decimal("0.6666666666666666666666666667")
    assert points[1].selective_risk == Decimal("0.5")


def test_wrong_accepted_value_is_hallucinated_not_omitted() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(_prediction(row_id="row-1", description="SYNTHETIC WRONG"),),
    )

    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.exact_matches == 0
    assert merchant.omissions == 0
    assert merchant.hallucinations == 1
    assert report.exact_rows == 0


def test_description_normalization_is_nfc_casefold_and_whitespace_only() -> None:
    report = score_predictions(
        gold=(
            _gold_row(
                row_id="row-1",
                fields=(_description_field("SYNTHÉTIC MERCHANT"),),
            ),
        ),
        predictions=(_prediction(row_id="row-1", description="synthe\u0301tic\tmerchant"),),
    )

    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.exact_matches == 0
    assert merchant.normalized_matches == 1
    assert merchant.hallucinations == 1


def test_description_normalization_policy_has_a_stable_version() -> None:
    assert DESCRIPTION_NORMALIZATION_VERSION == "description-nfc-casefold-whitespace-v1"


def test_invalid_typed_evidence_is_unsupported_and_cannot_match() -> None:
    prediction = _prediction(row_id="row-1", description="ZZZ")
    prediction = prediction.model_copy(
        update={
            "proposals": (
                prediction.proposals[0].model_copy(update={"role": FieldRole.BILLING_CURRENCY}),
            ),
        }
    )
    report = score_predictions(
        gold=(
            _gold_row(
                row_id="row-1",
                fields=(_gold_field(FieldRole.BILLING_CURRENCY, "USD"),),
            ),
        ),
        predictions=(prediction,),
    )

    currency = report.fields[FieldRole.BILLING_CURRENCY]
    assert currency.exact_matches == 0
    assert currency.omissions == 0
    assert currency.hallucinations == 0
    assert report.unsupported_evidence == 1
    assert report.exact_rows == 0


def test_duplicate_role_fails_closed_without_selecting_a_convenient_value() -> None:
    prediction = _prediction(row_id="row-1", description="SYNTHETIC MERCHANT")
    duplicate = prediction.proposals[0].model_copy(
        update={"owner_row_id": "row-1", "raw_score": 0.1}
    )
    prediction = prediction.model_copy(update={"proposals": (*prediction.proposals, duplicate)})
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(prediction,),
    )

    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.exact_matches == 0
    assert merchant.omissions == 0
    assert report.unsupported_evidence == 1
    assert report.ownership_collisions == 0
    assert report.exact_rows == 0


def test_distinct_owners_for_one_role_are_one_ownership_collision() -> None:
    prediction = _prediction(row_id="row-1", description="SYNTHETIC MERCHANT")
    proposals = (
        prediction.proposals[0],
        prediction.proposals[0].model_copy(update={"owner_row_id": "row-owner"}),
    )
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(prediction.model_copy(update={"proposals": proposals}),),
    )

    assert report.unsupported_evidence == 1
    assert report.ownership_collisions == 1
    assert report.exact_rows == 0


@pytest.mark.parametrize("owner", ("", " \t"))
def test_empty_explicit_owner_is_unsupported_and_cannot_be_exact(owner: str) -> None:
    prediction = _prediction(row_id="row-1", description="SYNTHETIC MERCHANT")
    proposal = prediction.proposals[0].model_copy(update={"owner_row_id": owner})

    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(prediction.model_copy(update={"proposals": (proposal,)}),),
    )

    assert report.unsupported_evidence == 1
    assert report.fields[FieldRole.DESCRIPTION].exact_matches == 0
    assert report.exact_rows == 0


@pytest.mark.parametrize("decision", (Decision.ABSTAIN, Decision.REJECT, Decision.IGNORE))
def test_nonaccepted_rows_remain_field_omissions(decision: Decision) -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(_prediction(row_id="row-1", decision=decision),),
    )

    assert report.fields[FieldRole.DESCRIPTION].omissions == 1
    assert report.exact_rows == 0


@pytest.mark.parametrize("case", ("duplicate_gold", "duplicate_prediction", "missing", "extra"))
def test_identity_join_rejects_nonbijective_inputs_without_echoing_values(case: str) -> None:
    label = _gold_row(row_id="PRIVATE-ROW", fields=(_description_field("PRIVATE VALUE"),))
    prediction = _prediction(row_id="PRIVATE-ROW", description="PRIVATE VALUE")
    gold: tuple[GoldRow, ...] = (label,)
    predictions: tuple[RowPrediction, ...] = (prediction,)
    if case == "duplicate_gold":
        gold = (label, label)
    elif case == "duplicate_prediction":
        predictions = (prediction, prediction)
    elif case == "missing":
        predictions = ()
    else:
        gold = ()

    with pytest.raises(ScoringInputError) as caught:
        score_predictions(gold=gold, predictions=predictions)

    message = str(caught.value)
    assert "PRIVATE-ROW" not in message
    assert "PRIVATE VALUE" not in message
    assert _DOCUMENT_ID not in message


def test_input_order_does_not_change_canonical_report_serialization() -> None:
    gold = (
        _gold_row(row_id="row-1", fields=(_description_field(),)),
        _gold_row(row_id="row-2", row_type=RowType.STRUCTURAL),
    )
    predictions = (
        _prediction(row_id="row-1", description="SYNTHETIC MERCHANT"),
        _prediction(row_id="row-2", predicted_type=RowType.STRUCTURAL),
    )

    first = score_predictions(gold=gold, predictions=predictions)
    second = score_predictions(
        gold=tuple(reversed(gold)),
        predictions=tuple(reversed(predictions)),
    )

    assert first.model_dump_json() == second.model_dump_json()


def test_calibration_uses_ten_fixed_bins_with_internal_edges_in_the_upper_bin() -> None:
    gold = (
        _gold_row(row_id="row-0", fields=(_description_field(),)),
        _gold_row(row_id="row-edge", fields=(_description_field(),)),
        _gold_row(row_id="row-1", fields=(_description_field(),)),
    )
    predictions = (
        _prediction(
            row_id="row-0",
            description="SYNTHETIC MERCHANT",
            confidence=0.0,
        ),
        _prediction(row_id="row-edge", description="SYNTHETIC WRONG", confidence=0.1),
        _prediction(
            row_id="row-1",
            description="SYNTHETIC MERCHANT",
            confidence=1.0,
        ),
    )

    report = score_predictions(gold=gold, predictions=predictions)

    assert len(report.calibration_bins) == 10
    assert report.calibration_bins[0].count == 1
    assert report.calibration_bins[1].count == 1
    assert report.calibration_bins[9].count == 1
    assert report.calibration_bins[1].lower == Decimal("0.1")
    assert report.calibration_bins[1].upper == Decimal("0.2")
    assert sum(bin_.count for bin_ in report.calibration_bins) == 3
    assert report.brier_score == Decimal("0.3366666666666666666666666667")
    assert report.log_loss is not None and report.log_loss.is_finite()


def test_missing_confidence_keeps_the_row_but_has_no_calibration_or_risk_point() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(
            _prediction(
                row_id="row-1",
                description="SYNTHETIC MERCHANT",
                confidence=None,
            ),
        ),
    )

    assert report.row_count == 1
    assert report.exact_rows == 1
    assert all(bin_.count == 0 for bin_ in report.calibration_bins)
    assert report.brier_score is None
    assert report.log_loss is None
    assert report.expected_calibration_error is None
    assert report.risk_coverage == ()
    assert report.area_under_risk_coverage is None
    assert all(point.coverage == 0 for point in report.coverage_at_risk)


def test_risk_coverage_groups_equal_confidence_without_partial_tie_selection() -> None:
    outcomes = ((Decimal("0.9"), True), (Decimal("0.9"), False), (Decimal("0.8"), True))

    points = risk_coverage(outcomes)
    reversed_points = risk_coverage(tuple(reversed(outcomes)))

    assert points == reversed_points
    assert len(points) == 2
    assert points[0].threshold == Decimal("0.9")
    assert points[0].accepted_rows == 2
    assert points[0].coverage == Decimal("0.6666666666666666666666666667")
    assert points[0].selective_risk == Decimal("0.5")


def test_report_risk_curve_uses_only_accepted_candidates_but_all_rows_in_coverage() -> None:
    report = score_predictions(
        gold=(
            _gold_row(row_id="row-1", fields=(_description_field(),)),
            _gold_row(row_id="row-2", fields=(_description_field(),)),
        ),
        predictions=(
            _prediction(
                row_id="row-1",
                description="SYNTHETIC MERCHANT",
                confidence=0.9,
            ),
            _prediction(row_id="row-2", decision=Decision.ABSTAIN, confidence=0.8),
        ),
    )

    assert sum(bin_.count for bin_ in report.calibration_bins) == 2
    assert len(report.risk_coverage) == 1
    assert report.risk_coverage[0].coverage == Decimal("0.5")
    assert report.risk_coverage[0].selective_risk == Decimal("0")


def test_report_aurc_and_predeclared_risk_targets_use_group_complete_points() -> None:
    gold = tuple(
        _gold_row(row_id=f"row-{index}", fields=(_description_field(),)) for index in range(3)
    )
    predictions = (
        _prediction(row_id="row-0", description="SYNTHETIC MERCHANT", confidence=0.9),
        _prediction(row_id="row-1", description="SYNTHETIC WRONG", confidence=0.8),
        _prediction(row_id="row-2", description="SYNTHETIC MERCHANT", confidence=0.2),
    )

    report = score_predictions(gold=gold, predictions=predictions)

    assert report.area_under_risk_coverage == Decimal("0.2777777777777777777777777778")
    assert tuple(point.target_risk for point in report.coverage_at_risk) == (
        Decimal("0.001"),
        Decimal("0.005"),
        Decimal("0.01"),
    )
    assert all(
        point.coverage == Decimal("0.3333333333333333333333333333")
        for point in report.coverage_at_risk
    )


@pytest.mark.parametrize(
    "outcomes",
    (
        ((float("nan"), True),),
        ((float("inf"), True),),
        ((-0.01, True),),
        ((1.01, False),),
    ),
)
def test_risk_coverage_rejects_nonfinite_or_out_of_range_confidence(
    outcomes: tuple[tuple[float, bool], ...],
) -> None:
    with pytest.raises(ScoringInputError, match="invalid confidence input"):
        risk_coverage(outcomes)


@pytest.mark.parametrize(
    ("reference", "hypothesis", "expected"),
    (
        ("abc", "axc", Decimal("0.3333333333333333333333333333")),
        ("abc", "abxc", Decimal("0.3333333333333333333333333333")),
        ("abc", "ac", Decimal("0.3333333333333333333333333333")),
        ("", "", Decimal("0")),
        ("", "abc", Decimal("3")),
        ("é", "e\u0301", Decimal("2")),
    ),
)
def test_character_error_rate_uses_literal_unicode_code_points_and_explicit_empty_denominator(
    reference: str,
    hypothesis: str,
    expected: Decimal,
) -> None:
    assert character_error_rate(reference, hypothesis) == expected


@pytest.mark.parametrize(
    ("reference", "hypothesis", "expected"),
    (
        ("alpha beta", "alpha gamma", Decimal("0.5")),
        ("alpha beta", "alpha new beta", Decimal("0.5")),
        ("alpha beta", "alpha", Decimal("0.5")),
        ("", "", Decimal("0")),
        ("", "one two", Decimal("2")),
        (
            "\N{GREEK SMALL LETTER ALPHA}\u2003\N{GREEK SMALL LETTER BETA}",
            "\N{GREEK SMALL LETTER ALPHA} \N{GREEK SMALL LETTER BETA}",
            Decimal("0"),
        ),
    ),
)
def test_word_error_rate_uses_unicode_whitespace_tokens_and_explicit_empty_denominator(
    reference: str,
    hypothesis: str,
    expected: Decimal,
) -> None:
    assert word_error_rate(reference, hypothesis) == expected


def _ocr_reference(
    *,
    row_id: str = "row-1",
    role: FieldRole = FieldRole.DESCRIPTION,
    text: str = "SYNTHETIC MERCHANT",
    source_region: tuple[float, float, float, float] = (0.0, 0.0, 10.0, 10.0),
) -> OcrReference:
    return OcrReference(
        document_id=_DOCUMENT_ID,
        row_id=row_id,
        role=role,
        verbatim_text=text,
        source_region=source_region,
    )


def test_ocr_rates_compare_reviewed_verbatim_text_to_matching_raw_support() -> None:
    prediction = _prediction(row_id="row-1", description="USD 0012.30")
    prediction = prediction.model_copy(
        update={
            "proposals": (
                prediction.proposals[0].model_copy(update={"role": FieldRole.BILLED_AMOUNT}),
            ),
        }
    )
    report = score_predictions(
        gold=(
            _gold_row(
                row_id="row-1",
                fields=(_gold_field(FieldRole.BILLED_AMOUNT, "12.3"),),
            ),
        ),
        predictions=(prediction,),
        ocr_references=(
            _ocr_reference(
                role=FieldRole.BILLED_AMOUNT,
                text="USD 0012.30",
            ),
        ),
    )

    assert report.ocr_cer == Decimal("0")
    assert report.ocr_wer == Decimal("0")


def test_ocr_reference_without_matching_prediction_support_is_ineligible() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(_prediction(row_id="row-1", description="SYNTHETIC MERCHANT"),),
        ocr_references=(_ocr_reference(source_region=(20.0, 20.0, 30.0, 30.0)),),
    )

    assert report.ocr_cer is None
    assert report.ocr_wer is None


@pytest.mark.parametrize("case", ("duplicate", "ambiguous", "unknown_row", "unknown_role"))
def test_ocr_reference_identity_must_be_unique_known_and_unambiguous(case: str) -> None:
    label = _gold_row(row_id="row-1", fields=(_description_field(),))
    prediction = _prediction(row_id="row-1", description="SYNTHETIC MERCHANT")
    reference = _ocr_reference()
    references: tuple[OcrReference, ...] = (reference,)
    if case == "duplicate":
        references = (reference, reference)
    elif case == "ambiguous":
        references = (
            reference,
            _ocr_reference(source_region=(1.0, 1.0, 9.0, 9.0)),
        )
    elif case == "unknown_row":
        references = (_ocr_reference(row_id="PRIVATE-UNKNOWN"),)
    else:
        references = (_ocr_reference(role=FieldRole.ANCILLARY),)

    with pytest.raises(ScoringInputError) as caught:
        score_predictions(
            gold=(label,),
            predictions=(prediction,),
            ocr_references=references,
        )

    assert "PRIVATE-UNKNOWN" not in str(caught.value)
    assert _DOCUMENT_ID not in str(caught.value)


def test_row_type_metrics_include_every_closed_class_and_zero_support_in_macro_f1() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", row_type=RowType.CONTINUATION),),
        predictions=(_prediction(row_id="row-1"),),
    )

    assert tuple(metric.row_type for metric in report.row_types) == tuple(RowType)
    assert tuple(metric.support for metric in report.row_types) == (0, 1, 0, 0)
    assert tuple(metric.f1 for metric in report.row_types) == (
        Decimal("0"),
        Decimal("1"),
        Decimal("0"),
        Decimal("0"),
    )
    assert report.row_type_macro_f1 == Decimal("0.25")
    assert len(report.row_type_confusion) == len(RowType) ** 2
    assert tuple((cell.gold, cell.predicted) for cell in report.row_type_confusion) == tuple(
        (gold_type, predicted_type) for gold_type in RowType for predicted_type in RowType
    )


def test_wrong_row_type_is_not_an_exact_row_even_when_fields_match() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(
            _prediction(
                row_id="row-1",
                predicted_type=RowType.PRIMARY_TRANSACTION,
                description="SYNTHETIC MERCHANT",
            ),
        ),
    )

    assert report.exact_rows == 0
    assert report.row_type_correct == 0
    assert report.row_type_accuracy == Decimal("0")
    assert (
        next(
            cell.count
            for cell in report.row_type_confusion
            if cell.gold is RowType.CONTINUATION and cell.predicted is RowType.PRIMARY_TRANSACTION
        )
        == 1
    )


def test_empty_complete_input_has_closed_zero_metrics() -> None:
    report = score_predictions(gold=(), predictions=())

    assert report.row_count == 0
    assert report.exact_row_rate == Decimal("0")
    assert report.row_type_accuracy == Decimal("0")
    assert report.row_type_macro_f1 == Decimal("0")
    assert tuple(report.fields) == tuple(FieldRole)
    assert all(field.eligible_rows == 0 for field in report.fields.values())
    assert all(field.exact_rate == 0 for field in report.fields.values())
    assert all(field.hallucination_rate == 0 for field in report.fields.values())
    assert report.brier_score is None
    assert report.risk_coverage == ()


def test_hallucination_rate_uses_all_rows_when_a_role_has_no_eligible_gold() -> None:
    report = score_predictions(
        gold=(
            _gold_row(row_id="row-1", row_type=RowType.STRUCTURAL),
            _gold_row(row_id="row-2", row_type=RowType.STRUCTURAL),
        ),
        predictions=(
            _prediction(
                row_id="row-1",
                predicted_type=RowType.STRUCTURAL,
                description="SYNTHETIC EXTRA",
            ),
            _prediction(row_id="row-2", predicted_type=RowType.STRUCTURAL),
        ),
    )

    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.eligible_rows == 0
    assert merchant.hallucinations == 1
    assert merchant.hallucination_rate == Decimal("0.5")


def test_decision_counts_form_a_complete_partition() -> None:
    gold = tuple(
        _gold_row(row_id=f"row-{index}", row_type=RowType.STRUCTURAL) for index in range(4)
    )
    predictions = tuple(
        _prediction(
            row_id=f"row-{index}",
            predicted_type=RowType.STRUCTURAL,
            decision=decision,
        )
        for index, decision in enumerate(Decision)
    )

    report = score_predictions(gold=gold, predictions=predictions)

    assert (
        report.accepted_rows,
        report.abstained_rows,
        report.rejected_rows,
        report.ignored_rows,
    ) == (1, 1, 1, 1)
    assert (
        sum(
            (
                report.accepted_rows,
                report.abstained_rows,
                report.rejected_rows,
                report.ignored_rows,
            )
        )
        == report.row_count
    )


@pytest.mark.parametrize(
    ("description", "expected_brier", "expected_risk", "expected_coverage"),
    (
        ("SYNTHETIC MERCHANT", Decimal("0.04"), Decimal("0"), Decimal("1")),
        ("SYNTHETIC WRONG", Decimal("0.64"), Decimal("1"), Decimal("0")),
    ),
)
def test_all_correct_and_all_wrong_calibration_remain_explicit(
    description: str,
    expected_brier: Decimal,
    expected_risk: Decimal,
    expected_coverage: Decimal,
) -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(_prediction(row_id="row-1", description=description, confidence=0.8),),
    )

    assert report.brier_score == expected_brier
    assert report.risk_coverage[0].selective_risk == expected_risk
    assert all(point.coverage == expected_coverage for point in report.coverage_at_risk)


@pytest.mark.parametrize(
    ("description", "confidence"),
    (("SYNTHETIC MERCHANT", 1.0), ("SYNTHETIC WRONG", 0.0)),
)
def test_log_loss_is_exactly_zero_at_correct_probability_boundaries(
    description: str,
    confidence: float,
) -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(
            _prediction(
                row_id="row-1",
                description=description,
                confidence=confidence,
            ),
        ),
    )

    assert report.log_loss == Decimal("0")


def test_empty_accepted_set_has_calibration_but_no_selective_curve() -> None:
    report = score_predictions(
        gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
        predictions=(_prediction(row_id="row-1", decision=Decision.ABSTAIN, confidence=0.2),),
    )

    assert report.brier_score == Decimal("0.04")
    assert report.risk_coverage == ()
    assert report.area_under_risk_coverage is None
    assert all(point.coverage == 0 for point in report.coverage_at_risk)


@pytest.mark.parametrize("field", ("confidence", "atom_confidence", "proposal_score"))
def test_scoring_rejects_forged_nonfinite_prediction_values_without_echoing_row_data(
    field: str,
) -> None:
    prediction = _prediction(row_id="PRIVATE-ROW", description="PRIVATE VALUE")
    if field == "confidence":
        prediction = prediction.model_copy(update={"exact_row_confidence": float("nan")})
    elif field == "atom_confidence":
        atom = prediction.evidence_atoms[0].model_copy(update={"confidence": float("inf")})
        prediction = prediction.model_copy(update={"evidence_atoms": (atom,)})
    else:
        proposal = prediction.proposals[0].model_copy(update={"raw_score": float("nan")})
        prediction = prediction.model_copy(update={"proposals": (proposal,)})

    with pytest.raises(ScoringInputError) as caught:
        score_predictions(
            gold=(
                _gold_row(
                    row_id="PRIVATE-ROW",
                    fields=(_description_field("PRIVATE VALUE"),),
                ),
            ),
            predictions=(prediction,),
        )

    assert str(caught.value) == "invalid prediction input"


def test_scoring_rejects_forged_nonfinite_gold_region() -> None:
    field = _description_field().model_copy(
        update={"source_region": (0.0, 0.0, float("nan"), 10.0)}
    )
    label = _gold_row(row_id="row-1", fields=(field,))

    with pytest.raises(ScoringInputError, match=r"^invalid gold input$"):
        score_predictions(
            gold=(label,),
            predictions=(_prediction(row_id="row-1", description="SYNTHETIC MERCHANT"),),
        )


@pytest.mark.parametrize("case", ("prediction", "reference"))
def test_scoring_rejects_empty_or_reversed_source_geometry(case: str) -> None:
    prediction = _prediction(row_id="row-1", description="SYNTHETIC MERCHANT")
    reference = _ocr_reference()
    if case == "prediction":
        atom = prediction.evidence_atoms[0].model_copy(update={"bbox": (10.0, 0.0, 0.0, 10.0)})
        prediction = prediction.model_copy(update={"evidence_atoms": (atom,)})
        expected = "invalid prediction input"
    else:
        reference = reference.model_copy(update={"source_region": (0.0, 0.0, 0.0, 10.0)})
        expected = "invalid OCR reference input"

    with pytest.raises(ScoringInputError, match=f"^{expected}$"):
        score_predictions(
            gold=(_gold_row(row_id="row-1", fields=(_description_field(),)),),
            predictions=(prediction,),
            ocr_references=(reference,),
        )


def test_scoring_rejects_duplicate_gold_roles_at_the_public_boundary() -> None:
    field = _description_field()
    label = _gold_row(row_id="row-1", fields=(field, field))

    with pytest.raises(ScoringInputError, match=r"^invalid gold input$"):
        score_predictions(
            gold=(label,),
            predictions=(_prediction(row_id="row-1", description="SYNTHETIC MERCHANT"),),
        )


def test_canonical_report_json_is_identical_across_python_hash_seeds() -> None:
    script = textwrap.dedent(
        """
        from experiments.row_extraction.contracts import (
            Decision, EvidenceAtom, FieldProposal, FieldRole, GoldField, GoldRow,
            RowPrediction, RowType,
        )
        from experiments.row_extraction.metrics import score_predictions

        document_id = "0" * 64
        atom = EvidenceAtom(
            atom_id="field", text="SYNTHETIC", bbox=(0.0, 0.0, 1.0, 1.0),
            source="digital", confidence=1.0,
        )
        gold = GoldRow(
            document_id=document_id, row_id="row", row_type=RowType.CONTINUATION,
            fields=(GoldField(
                role=FieldRole.DESCRIPTION, canonical_value="SYNTHETIC",
                atom_ids=("field",),
            ),),
        )
        prediction = RowPrediction(
            experiment_id="synthetic", config_id="v1", document_id=document_id,
            row_id="row", predicted_type=RowType.CONTINUATION,
            evidence_atoms=(atom,), proposals=(FieldProposal(
                role=FieldRole.DESCRIPTION, atom_ids=("field",), raw_score=1.0,
            ),), exact_row_confidence=0.9, decision=Decision.ACCEPT, reasons=(),
        )
        print(score_predictions((gold,), (prediction,)).model_dump_json())
        """
    )

    outputs = tuple(
        subprocess.run(
            (sys.executable, "-c", script),
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "8675309")
    )

    assert outputs[0] == outputs[1]
