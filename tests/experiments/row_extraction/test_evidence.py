from __future__ import annotations

from collections.abc import Sequence

import pytest

from experiments.row_extraction.contracts import (
    Decision,
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.evidence import (
    EvidenceContractError,
    ResolvedField,
    prediction_ledger,
    render_proposal,
    resolve_proposal,
)
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row


def accepted_prediction(
    *,
    role: FieldRole = FieldRole.DESCRIPTION,
    texts: Sequence[str] = ("SYNTHETIC",),
    atom_ids: tuple[str, ...] | None = None,
) -> RowPrediction:
    row = frozen_row()
    atoms = tuple(
        evidence_atom(atom_id=f"atom-{index}", text=text)
        for index, text in enumerate(texts, start=1)
    )
    proposal_atom_ids = atom_ids or tuple(atom.atom_id for atom in atoms)
    proposal = FieldProposal(
        role=role,
        atom_ids=proposal_atom_ids,
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(proposal,),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )
    return prediction


def test_prediction_ledger_contains_only_self_contained_prediction_atoms() -> None:
    prediction = accepted_prediction(texts=("first", "second"))

    ledger = prediction_ledger(prediction)

    assert ledger == {
        "atom-1": prediction.evidence_atoms[0],
        "atom-2": prediction.evidence_atoms[1],
    }


def test_render_proposal_uses_exact_declared_atom_order() -> None:
    prediction = accepted_prediction(texts=("first", "second"), atom_ids=("atom-2", "atom-1"))

    assert render_proposal(prediction, prediction.proposals[0]) == "second first"


def test_render_proposal_rejects_missing_atom() -> None:
    row = frozen_row()
    atom = evidence_atom(atom_id="present", text="supported")
    proposal = FieldProposal(
        role=FieldRole.DESCRIPTION,
        atom_ids=("missing",),
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=(atom,),
        proposals=(),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    ).model_copy(update={"proposals": (proposal,)})

    with pytest.raises(EvidenceContractError, match="missing evidence atom"):
        render_proposal(prediction, prediction.proposals[0])


def test_render_proposal_rejects_duplicate_atom_reference() -> None:
    prediction = accepted_prediction(atom_ids=("atom-1", "atom-1"))

    with pytest.raises(EvidenceContractError, match="duplicate proposal evidence atom"):
        render_proposal(prediction, prediction.proposals[0])


@pytest.mark.parametrize(
    ("role", "source", "expected"),
    (
        (FieldRole.TRANSACTION_DATE, "03/02/2026", "2026-02-03"),
        (FieldRole.POSTING_DATE, "2026-02-04", "2026-02-04"),
        (FieldRole.CONVERSION_DATE, "05.02.2026", "2026-02-05"),
        (FieldRole.BILLING_CURRENCY, "$", "USD"),
        (FieldRole.ORIGINAL_CURRENCY, "eur", "EUR"),
        (FieldRole.BILLED_AMOUNT, "USD 0012.30", "12.3"),
        (FieldRole.ORIGINAL_AMOUNT, "EUR -2.50", "-2.5"),
        (FieldRole.FX_RATE, "3.5000", "3.5"),
        (FieldRole.INSTALLMENT, "2 / 6", "2/6"),
        (FieldRole.DESCRIPTION, "SYNTHETIC MERCHANT", "SYNTHETIC MERCHANT"),
        (FieldRole.ANCILLARY, "synthetic note", "synthetic note"),
    ),
)
def test_resolve_proposal_uses_role_typed_canonicalization(
    role: FieldRole,
    source: str,
    expected: str,
) -> None:
    prediction = accepted_prediction(role=role, texts=(source,))
    proposal = prediction.proposals[0]

    assert resolve_proposal(prediction, proposal) == ResolvedField(
        role=role,
        canonical_value=expected,
        atom_ids=proposal.atom_ids,
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    (("USD 12.34", "charge"), ("EUR -2.50", "credit")),
)
def test_kind_is_derived_only_from_supported_billed_amount_sign(
    source: str,
    expected: str,
) -> None:
    prediction = accepted_prediction(role=FieldRole.KIND, texts=(source,))

    assert resolve_proposal(prediction, prediction.proposals[0]).canonical_value == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    (("12.34", "charge"), ("-12.34", "credit")),
)
def test_kind_accepts_bare_supported_amount_sign(source: str, expected: str) -> None:
    prediction = accepted_prediction(role=FieldRole.KIND, texts=(source,))

    assert resolve_proposal(prediction, prediction.proposals[0]).canonical_value == expected


@pytest.mark.parametrize(
    "source",
    ("1E3", "1_2", "NaN", "Infinity", "1 2", "0", "-0"),
)
def test_kind_rejects_unsupported_nonfinite_or_zero_lexeme(source: str) -> None:
    prediction = accepted_prediction(role=FieldRole.KIND, texts=(source,))

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, prediction.proposals[0])


@pytest.mark.parametrize(
    ("role", "source"),
    (
        (FieldRole.TRANSACTION_DATE, "03/02/26"),
        (FieldRole.BILLING_CURRENCY, "synthetic currency"),
        (FieldRole.BILLED_AMOUNT, "USD 1 2"),
        (FieldRole.BILLED_AMOUNT, "USD NaN"),
        (FieldRole.INSTALLMENT, "6/2"),
        (FieldRole.KIND, "USD 0.00"),
    ),
)
def test_resolve_proposal_rejects_invalid_or_nonunique_typed_value(
    role: FieldRole,
    source: str,
) -> None:
    prediction = accepted_prediction(role=role, texts=(source,))

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, prediction.proposals[0])


@pytest.mark.parametrize(
    ("amount_role", "currency_role", "currency_text", "expected"),
    (
        (FieldRole.BILLED_AMOUNT, FieldRole.BILLING_CURRENCY, "USD", "12.34"),
        (FieldRole.ORIGINAL_AMOUNT, FieldRole.ORIGINAL_CURRENCY, "EUR", "12.34"),
    ),
)
def test_amount_uses_exactly_one_same_family_currency_proposal_as_hint(
    amount_role: FieldRole,
    currency_role: FieldRole,
    currency_text: str,
    expected: str,
) -> None:
    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text="12.34"),
        evidence_atom(atom_id="currency", text=currency_text),
    )
    amount = FieldProposal(role=amount_role, atom_ids=("amount",), raw_score=1.0)
    currency = FieldProposal(role=currency_role, atom_ids=("currency",), raw_score=1.0)
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, currency),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    assert resolve_proposal(prediction, amount).canonical_value == expected


def test_amount_rejects_zero_or_multiple_same_family_currency_hints() -> None:
    without_hint = accepted_prediction(role=FieldRole.BILLED_AMOUNT, texts=("12.34",))
    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(without_hint, without_hint.proposals[0])

    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text="12.34"),
        evidence_atom(atom_id="currency-1", text="USD"),
        evidence_atom(atom_id="currency-2", text="$"),
    )
    amount = FieldProposal(
        role=FieldRole.BILLED_AMOUNT,
        atom_ids=("amount",),
        raw_score=1.0,
    )
    currencies = tuple(
        FieldProposal(
            role=FieldRole.BILLING_CURRENCY,
            atom_ids=(atom_id,),
            raw_score=1.0,
        )
        for atom_id in ("currency-1", "currency-2")
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, *currencies),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, amount)


@pytest.mark.parametrize(
    ("role", "source", "expected"),
    (
        (FieldRole.BILLED_AMOUNT, "12.34", "12.34"),
        (FieldRole.KIND, "12,34", "charge"),
    ),
)
def test_other_owner_currency_does_not_conflict_with_field_resolution(
    role: FieldRole,
    source: str,
    expected: str,
) -> None:
    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text=source),
        evidence_atom(atom_id="same-owner-currency", text="USD"),
        evidence_atom(atom_id="other-owner-currency", text="EUR"),
    )
    amount = FieldProposal(
        role=role,
        atom_ids=("amount",),
        owner_row_id="owner-a",
        raw_score=1.0,
    )
    currencies = (
        FieldProposal(
            role=FieldRole.BILLING_CURRENCY,
            atom_ids=("same-owner-currency",),
            owner_row_id="owner-a",
            raw_score=1.0,
        ),
        FieldProposal(
            role=FieldRole.BILLING_CURRENCY,
            atom_ids=("other-owner-currency",),
            owner_row_id="owner-b",
            raw_score=1.0,
        ),
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, *currencies),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    assert resolve_proposal(prediction, amount).canonical_value == expected


def test_currency_hint_rejects_absent_same_owner_proposal() -> None:
    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text="12.34"),
        evidence_atom(atom_id="other-owner-currency", text="USD"),
    )
    amount = FieldProposal(
        role=FieldRole.BILLED_AMOUNT,
        atom_ids=("amount",),
        owner_row_id="owner-a",
        raw_score=1.0,
    )
    currency = FieldProposal(
        role=FieldRole.BILLING_CURRENCY,
        atom_ids=("other-owner-currency",),
        owner_row_id="owner-b",
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, currency),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, amount)


@pytest.mark.parametrize(
    ("amount_owner", "currency_owner"),
    ((None, "row-1"), ("row-1", None)),
)
def test_current_row_and_implicit_owner_are_equivalent_for_currency_hints(
    amount_owner: str | None,
    currency_owner: str | None,
) -> None:
    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text="12,34"),
        evidence_atom(atom_id="currency", text="USD"),
    )
    amount = FieldProposal(
        role=FieldRole.BILLED_AMOUNT,
        atom_ids=("amount",),
        owner_row_id=amount_owner,
        raw_score=1.0,
    )
    currency = FieldProposal(
        role=FieldRole.BILLING_CURRENCY,
        atom_ids=("currency",),
        owner_row_id=currency_owner,
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, currency),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    assert resolve_proposal(prediction, amount).canonical_value == "12.34"


@pytest.mark.parametrize(
    ("amount_owner", "currency_owner"),
    ((None, ""), ("", None), ("row-1", ""), ("", "row-1")),
)
def test_empty_owner_is_not_equivalent_to_current_row_for_currency_hints(
    amount_owner: str | None,
    currency_owner: str | None,
) -> None:
    row = frozen_row()
    atoms = (
        evidence_atom(atom_id="amount", text="12,34"),
        evidence_atom(atom_id="currency", text="USD"),
    )
    amount = FieldProposal(
        role=FieldRole.BILLED_AMOUNT,
        atom_ids=("amount",),
        owner_row_id=amount_owner,
        raw_score=1.0,
    )
    currency = FieldProposal(
        role=FieldRole.BILLING_CURRENCY,
        atom_ids=("currency",),
        owner_row_id=currency_owner,
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(amount, currency),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, amount)


def test_text_resolution_normalizes_nfc_controls_and_spacing() -> None:
    prediction = accepted_prediction(
        role=FieldRole.DESCRIPTION,
        texts=("  Cafe\u0301\u200e   MERCHANT  ",),
    )

    assert (
        resolve_proposal(prediction, prediction.proposals[0]).canonical_value
        == "Caf\u00e9 MERCHANT"
    )


def test_text_resolution_rejects_empty_normalized_value() -> None:
    prediction = accepted_prediction(role=FieldRole.ANCILLARY, texts=(" \u200e ",))

    with pytest.raises(EvidenceContractError, match="invalid or nonunique proposal value"):
        resolve_proposal(prediction, prediction.proposals[0])


def test_resolve_proposal_preserves_declared_evidence_ids() -> None:
    atoms: tuple[EvidenceAtom, ...] = (
        evidence_atom(atom_id="left", text="SYNTHETIC"),
        evidence_atom(atom_id="right", text="MERCHANT"),
    )
    row = frozen_row()
    proposal = FieldProposal(
        role=FieldRole.DESCRIPTION,
        atom_ids=("right", "left"),
        raw_score=1.0,
    )
    prediction = RowPrediction(
        experiment_id="synthetic",
        config_id="v1",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.PRIMARY_TRANSACTION,
        evidence_atoms=atoms,
        proposals=(proposal,),
        exact_row_confidence=1.0,
        decision=Decision.ACCEPT,
        reasons=(),
    )

    assert resolve_proposal(prediction, proposal).atom_ids == ("right", "left")
