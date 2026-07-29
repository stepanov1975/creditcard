import pytest

from experiments.row_extraction.comparison.errors import (
    ErrorCategory,
    classify_error,
)
from experiments.row_extraction.contracts import (
    Decision,
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    GoldField,
    GoldRow,
    RowPrediction,
    RowType,
)

_DOCUMENT_ID = "a" * 64
_ATOM = EvidenceAtom(
    atom_id="description",
    text="SYNTHETIC SHOP",
    bbox=(1.0, 1.0, 10.0, 2.0),
    source="digital",
    confidence=1.0,
    column_index=0,
)


def _gold(
    *fields: GoldField,
    row_type: RowType = RowType.PRIMARY_TRANSACTION,
    ambiguous: bool = False,
) -> GoldRow:
    return GoldRow(
        document_id=_DOCUMENT_ID,
        row_id="row-1",
        row_type=row_type,
        fields=fields,
        ambiguous=ambiguous,
    )


def _prediction(
    *proposals: FieldProposal,
    predicted_type: RowType = RowType.PRIMARY_TRANSACTION,
    decision: Decision = Decision.ACCEPT,
    reasons: tuple[str, ...] = ("synthetic",),
    atoms: tuple[EvidenceAtom, ...] = (_ATOM,),
) -> RowPrediction:
    return RowPrediction(
        experiment_id="synthetic-arm",
        config_id="synthetic-v1",
        document_id=_DOCUMENT_ID,
        row_id="row-1",
        predicted_type=predicted_type,
        evidence_atoms=atoms,
        proposals=proposals,
        exact_row_confidence=0.75,
        decision=decision,
        reasons=reasons,
    )


def _description_proposal() -> FieldProposal:
    return FieldProposal(
        role=FieldRole.DESCRIPTION,
        atom_ids=("description",),
        raw_score=1.0,
    )


def test_extra_accepted_description_is_hallucination() -> None:
    assignment = classify_error(_gold(), _prediction(_description_proposal()))

    assert assignment.primary is ErrorCategory.UNSUPPORTED_FIELD_HALLUCINATION
    assert assignment.secondary == (ErrorCategory.CALIBRATION_FALSE_ACCEPT,)
    assert assignment.reason_codes == (
        "unsupported_description_hallucination",
        "accepted_inexact_row",
    )


def test_annotation_ambiguity_has_priority_and_preserves_correct_abstention() -> None:
    assignment = classify_error(
        _gold(ambiguous=True),
        _prediction(decision=Decision.ABSTAIN),
    )

    assert assignment.primary is ErrorCategory.ANNOTATION_AMBIGUITY
    assert assignment.secondary == (ErrorCategory.CORRECT_ABSTENTION,)
    assert assignment.reason_codes == (
        "annotation_ambiguous",
        "ambiguous_row_abstained",
    )


def test_evidence_contract_failure_precedes_semantic_field_errors() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )
    duplicated = (_description_proposal(), _description_proposal())

    assignment = classify_error(gold, _prediction(*duplicated))

    assert assignment.primary is ErrorCategory.EVIDENCE_CONTRACT
    assert assignment.secondary == (ErrorCategory.CALIBRATION_FALSE_ACCEPT,)
    assert assignment.reason_codes == (
        "nonunique_description_proposal",
        "accepted_inexact_row",
    )


def test_row_type_error_precedes_merchant_error() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="DIFFERENT SHOP",
            atom_ids=("different",),
        )
    )

    assignment = classify_error(
        gold,
        _prediction(
            _description_proposal(),
            predicted_type=RowType.CONTINUATION,
        ),
    )

    assert assignment.primary is ErrorCategory.ROW_TYPE
    assert ErrorCategory.MERCHANT_SPAN in assignment.secondary
    assert assignment.reason_codes[0] == "row_type_mismatch"


def test_closed_taxonomy_maps_predeclared_diagnostic_reasons() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="DIFFERENT SHOP",
            atom_ids=("different",),
        )
    )

    assignment = classify_error(
        gold,
        _prediction(
            _description_proposal(),
            reasons=("ocr_segmentation_error", "column_assignment_drift"),
        ),
    )

    assert assignment.primary is ErrorCategory.OCR_EDIT_OR_SEGMENTATION
    assert assignment.secondary == (
        ErrorCategory.CROP_BOX_OR_COLUMN,
        ErrorCategory.MERCHANT_SPAN,
        ErrorCategory.CALIBRATION_FALSE_ACCEPT,
    )
    assert assignment.reason_codes == (
        "ocr_edit_or_segmentation",
        "crop_box_or_column",
        "description_value_mismatch",
        "accepted_inexact_row",
    )


def test_exact_supported_acceptance_has_no_error_assignment() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )

    assignment = classify_error(gold, _prediction(_description_proposal()))

    assert assignment.primary is None
    assert assignment.secondary == ()
    assert assignment.reason_codes == ()


def test_merchant_error_precedes_date_error_independent_of_field_enum_order() -> None:
    date_atom = EvidenceAtom(
        atom_id="date",
        text="02/02/2026",
        bbox=(11.0, 1.0, 20.0, 2.0),
        source="digital",
        confidence=1.0,
        column_index=1,
    )
    gold = _gold(
        GoldField(
            role=FieldRole.TRANSACTION_DATE,
            canonical_value="2026-01-01",
            atom_ids=("gold-date",),
        ),
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="DIFFERENT SHOP",
            atom_ids=("gold-description",),
        ),
    )
    date_proposal = FieldProposal(
        role=FieldRole.TRANSACTION_DATE,
        atom_ids=("date",),
        raw_score=1.0,
    )

    assignment = classify_error(
        gold,
        _prediction(
            _description_proposal(),
            date_proposal,
            atoms=(_ATOM, date_atom),
        ),
    )

    assert assignment.primary is ErrorCategory.MERCHANT_SPAN
    assert assignment.secondary[:1] == (ErrorCategory.DATE,)


def test_blank_proposal_owner_is_an_evidence_contract_error() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )
    proposal = _description_proposal().model_copy(update={"owner_row_id": ""})

    assignment = classify_error(gold, _prediction(proposal))

    assert assignment.primary is ErrorCategory.EVIDENCE_CONTRACT
    assert assignment.reason_codes[0] == "description_invalid_owner"


def test_primary_row_proposal_for_another_owner_is_an_ownership_error() -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )
    proposal = _description_proposal().model_copy(update={"owner_row_id": "row-other"})

    assignment = classify_error(gold, _prediction(proposal))

    assert assignment.primary is ErrorCategory.CONTINUATION_OWNERSHIP
    assert assignment.reason_codes[0] == "continuation_ownership"


def test_correct_abstention_remains_last_in_the_frozen_priority() -> None:
    duplicated = (_description_proposal(), _description_proposal())

    assignment = classify_error(
        _gold(ambiguous=True),
        _prediction(*duplicated, decision=Decision.ABSTAIN),
    )

    assert assignment.primary is ErrorCategory.ANNOTATION_AMBIGUITY
    assert assignment.secondary == (ErrorCategory.CORRECT_ABSTENTION,)


@pytest.mark.parametrize(
    "decision",
    [Decision.ABSTAIN, Decision.REJECT, Decision.IGNORE],
)
def test_nonaccepted_latent_exact_proposal_is_an_accepted_output_omission(
    decision: Decision,
) -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )

    assignment = classify_error(
        gold,
        _prediction(_description_proposal(), decision=decision),
    )

    assert assignment.primary is ErrorCategory.MERCHANT_SPAN
    assert ErrorCategory.UNSUPPORTED_FIELD_HALLUCINATION not in assignment.secondary
    assert ErrorCategory.CORRECT_ABSTENTION not in assignment.secondary
    assert assignment.reason_codes == ("description_omission",)


@pytest.mark.parametrize(
    "decision",
    [Decision.ABSTAIN, Decision.REJECT, Decision.IGNORE],
)
def test_nonaccepted_extra_latent_proposal_is_not_a_hallucination(
    decision: Decision,
) -> None:
    assignment = classify_error(
        _gold(),
        _prediction(_description_proposal(), decision=decision),
    )

    assert assignment.primary is None
    assert ErrorCategory.UNSUPPORTED_FIELD_HALLUCINATION not in assignment.secondary
    assert ErrorCategory.CORRECT_ABSTENTION not in assignment.secondary
    assert assignment.reason_codes == ()


def test_correct_abstention_is_reserved_for_ambiguous_abstain() -> None:
    abstained = classify_error(
        _gold(ambiguous=True),
        _prediction(decision=Decision.ABSTAIN),
    )
    rejected = classify_error(
        _gold(ambiguous=True),
        _prediction(decision=Decision.REJECT),
    )
    ignored = classify_error(
        _gold(ambiguous=True),
        _prediction(decision=Decision.IGNORE),
    )

    assert ErrorCategory.CORRECT_ABSTENTION in abstained.secondary
    assert ErrorCategory.CORRECT_ABSTENTION not in rejected.secondary
    assert ErrorCategory.CORRECT_ABSTENTION not in ignored.secondary


@pytest.mark.parametrize("reason", ["not_ocr_segmentation", "word_boxed"])
def test_diagnostic_reason_near_match_does_not_activate_taxonomy(reason: str) -> None:
    gold = _gold(
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SYNTHETIC SHOP",
            atom_ids=("description",),
        )
    )

    assignment = classify_error(
        gold,
        _prediction(_description_proposal(), reasons=(reason,)),
    )

    assert assignment.primary is None
    assert assignment.secondary == ()
    assert assignment.reason_codes == ()


def test_every_field_role_has_an_explicit_frozen_error_category() -> None:
    expected = {
        FieldRole.DESCRIPTION: ErrorCategory.MERCHANT_SPAN,
        FieldRole.TRANSACTION_DATE: ErrorCategory.DATE,
        FieldRole.POSTING_DATE: ErrorCategory.DATE,
        FieldRole.CONVERSION_DATE: ErrorCategory.DATE,
        FieldRole.BILLED_AMOUNT: ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY,
        FieldRole.BILLING_CURRENCY: ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY,
        FieldRole.ORIGINAL_AMOUNT: ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY,
        FieldRole.ORIGINAL_CURRENCY: ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY,
        FieldRole.KIND: ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY,
        FieldRole.INSTALLMENT: ErrorCategory.OPTIONAL_FIELD,
        FieldRole.FX_RATE: ErrorCategory.OPTIONAL_FIELD,
        FieldRole.ANCILLARY: ErrorCategory.OPTIONAL_FIELD,
    }
    assert set(expected) == set(FieldRole)

    for role, category in expected.items():
        assignment = classify_error(
            _gold(
                GoldField(
                    role=role,
                    canonical_value="SYNTHETIC",
                    atom_ids=("gold",),
                )
            ),
            _prediction(),
        )
        assert assignment.primary is category
