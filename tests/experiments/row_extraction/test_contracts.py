import pytest
from pydantic import ValidationError

from experiments.row_extraction.contracts import (
    Decision,
    FieldProposal,
    FieldRole,
    GoldField,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from tests.experiments.row_extraction.factories import frozen_row


def test_field_proposal_requires_evidence_atoms() -> None:
    with pytest.raises(ValidationError):
        FieldProposal(role=FieldRole.DESCRIPTION, atom_ids=(), raw_score=0.8)


def test_gold_field_requires_atom_ids_or_source_region() -> None:
    with pytest.raises(
        ValidationError,
        match="gold field requires atom IDs or source region",
    ) as captured:
        GoldField(
            role=FieldRole.DESCRIPTION,
            canonical_value="SECRET",
            atom_ids=(),
        )
    assert "SECRET" not in str(captured.value)


def test_lane_disposition_vocabulary_is_closed() -> None:
    assert tuple(LaneDisposition) == (
        LaneDisposition.FROZEN_ELIGIBLE,
        LaneDisposition.VALIDATION_STOPPED,
    )


def test_prediction_rejects_duplicate_evidence_atom_ids() -> None:
    row = frozen_row()
    with pytest.raises(ValidationError, match="evidence atom IDs must be unique"):
        RowPrediction(
            experiment_id="control",
            config_id="v1",
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=RowType.PRIMARY_TRANSACTION,
            evidence_atoms=(row.atoms[0], row.atoms[0]),
            proposals=(),
            exact_row_confidence=None,
            decision=Decision.ABSTAIN,
            reasons=("synthetic_duplicate",),
        )


def test_prediction_rejects_proposal_atom_ids_absent_from_evidence() -> None:
    row = frozen_row()
    with pytest.raises(
        ValidationError,
        match="proposal atom IDs must reference prediction evidence",
    ):
        RowPrediction(
            experiment_id="control",
            config_id="v1",
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=RowType.PRIMARY_TRANSACTION,
            evidence_atoms=row.atoms,
            proposals=(
                FieldProposal(
                    role=FieldRole.DESCRIPTION,
                    atom_ids=("unsupported-atom",),
                    raw_score=0.8,
                ),
            ),
            exact_row_confidence=None,
            decision=Decision.ABSTAIN,
            reasons=("synthetic_unsupported_proposal",),
        )
