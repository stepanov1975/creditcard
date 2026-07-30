from __future__ import annotations

from ccparser.models import TransactionKind
from experiments.row_extraction.contracts import (
    FieldRole,
    GoldField,
    GoldRow,
    RowType,
)
from experiments.row_extraction.targets import TargetDisposition, encode_targets
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row


def test_kind_is_derived_without_competing_for_the_billed_amount_atom() -> None:
    row = frozen_row(
        atoms=(
            evidence_atom(atom_id="currency", text="USD", bbox=(10.0, 20.0, 30.0, 30.0)),
            evidence_atom(atom_id="amount", text="12.34", bbox=(40.0, 20.0, 70.0, 30.0)),
        )
    )
    gold = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.PRIMARY_TRANSACTION,
        fields=(
            GoldField(
                role=FieldRole.BILLING_CURRENCY,
                canonical_value="USD",
                atom_ids=("currency",),
            ),
            GoldField(
                role=FieldRole.BILLED_AMOUNT,
                canonical_value="12.34",
                atom_ids=("amount",),
            ),
            GoldField(
                role=FieldRole.KIND,
                canonical_value=TransactionKind.CHARGE.value,
                atom_ids=("amount",),
            ),
        ),
    )

    targets = encode_targets(row, gold)

    assert targets.bio_tags == ("B:billing_currency", "B:billed_amount")
    assert targets.atom_loss_mask == (True, True)
    assert targets.field_supervision_eligible is True
    assert targets.dispositions == (
        (FieldRole.BILLED_AMOUNT, TargetDisposition.SUPERVISED),
        (FieldRole.BILLING_CURRENCY, TargetDisposition.SUPERVISED),
        (FieldRole.KIND, TargetDisposition.DERIVED),
    )


def test_region_only_field_masks_only_that_field() -> None:
    row = frozen_row(
        atoms=(
            evidence_atom(atom_id="currency", text="USD", bbox=(10.0, 20.0, 30.0, 30.0)),
            evidence_atom(atom_id="amount", text="12.34", bbox=(40.0, 20.0, 70.0, 30.0)),
        )
    )
    gold = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.PRIMARY_TRANSACTION,
        fields=(
            GoldField(
                role=FieldRole.DESCRIPTION,
                canonical_value="SYNTHETIC MERCHANT",
                source_region=(80.0, 20.0, 150.0, 30.0),
            ),
            GoldField(
                role=FieldRole.BILLING_CURRENCY,
                canonical_value="USD",
                atom_ids=("currency",),
            ),
            GoldField(
                role=FieldRole.BILLED_AMOUNT,
                canonical_value="12.34",
                atom_ids=("amount",),
            ),
            GoldField(
                role=FieldRole.KIND,
                canonical_value=TransactionKind.CHARGE.value,
                atom_ids=("amount",),
            ),
        ),
    )

    targets = encode_targets(row, gold)

    assert targets.bio_tags == ("B:billing_currency", "B:billed_amount")
    assert targets.atom_loss_mask == (True, True)
    assert targets.field_supervision_eligible is True
    assert targets.dispositions == (
        (FieldRole.BILLED_AMOUNT, TargetDisposition.SUPERVISED),
        (FieldRole.BILLING_CURRENCY, TargetDisposition.SUPERVISED),
        (FieldRole.DESCRIPTION, TargetDisposition.MASKED),
        (FieldRole.KIND, TargetDisposition.DERIVED),
    )


def test_ambiguous_row_masks_row_type_and_atom_supervision() -> None:
    row = frozen_row()
    gold = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.AMBIGUOUS,
        fields=(),
        ambiguous=True,
    )

    targets = encode_targets(row, gold)

    assert targets.row_type_eligible is False
    assert targets.bio_tags == ("O",)
    assert targets.atom_loss_mask == (False,)
    assert targets.field_supervision_eligible is False


def test_noncontiguous_field_masks_only_its_atoms() -> None:
    row = frozen_row(
        atoms=(
            evidence_atom(atom_id="description-head", text="SYNTHETIC"),
            evidence_atom(atom_id="currency", text="USD"),
            evidence_atom(atom_id="description-tail", text="MERCHANT"),
            evidence_atom(atom_id="amount", text="12.34"),
        )
    )
    gold = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.PRIMARY_TRANSACTION,
        fields=(
            GoldField(
                role=FieldRole.DESCRIPTION,
                canonical_value="SYNTHETIC MERCHANT",
                atom_ids=("description-head", "description-tail"),
            ),
            GoldField(
                role=FieldRole.BILLING_CURRENCY,
                canonical_value="USD",
                atom_ids=("currency",),
            ),
            GoldField(
                role=FieldRole.BILLED_AMOUNT,
                canonical_value="12.34",
                atom_ids=("amount",),
            ),
            GoldField(
                role=FieldRole.KIND,
                canonical_value=TransactionKind.CHARGE.value,
                atom_ids=("amount",),
            ),
        ),
    )

    targets = encode_targets(row, gold)

    assert targets.bio_tags == ("O", "B:billing_currency", "O", "B:billed_amount")
    assert targets.atom_loss_mask == (False, True, False, True)
    assert targets.field_supervision_eligible is True
    assert (FieldRole.DESCRIPTION, TargetDisposition.MASKED) in targets.dispositions
