from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

import experiments.row_extraction.merchant_context as merchant_context
from experiments.row_extraction.contracts import DatasetSplit, FrozenRow
from experiments.row_extraction.merchant_context import (
    AssertionDisposition,
    MerchantAssertion,
    MerchantContextError,
    MerchantErrorCategory,
    MerchantReference,
    MerchantReferenceSummary,
    ReferenceDisposition,
    canonical_merchant_text,
    validate_merchant_reference,
)
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row


def test_canonical_merchant_text_changes_only_nfc_and_layout_whitespace() -> None:
    assert canonical_merchant_text("  Cafe\u0301\n  Store  ") == "Café Store"
    assert canonical_merchant_text("A-B, Ltd.") == "A-B, Ltd."


def test_transaction_reference_requires_one_owner_and_source_support() -> None:
    reference = MerchantReference(
        document_id="a" * 64,
        anchor_row_id="continuation",
        disposition=ReferenceDisposition.TRANSACTION,
        owner_row_id="primary",
        owned_row_ids=("primary", "continuation"),
        merchant_text="SYNTHETIC MERCHANT",
        atom_ids=("merchant-1",),
        source_regions=(),
        ambiguity_category=None,
    )
    assert reference.owner_row_id == "primary"

    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {
                **reference.model_dump(),
                "owner_row_id": None,
                "atom_ids": (),
                "source_regions": (),
            }
        )


def test_transaction_reference_rejects_duplicate_or_unowned_support_ids() -> None:
    payload = {
        "document_id": "a" * 64,
        "anchor_row_id": "continuation",
        "disposition": ReferenceDisposition.TRANSACTION,
        "owner_row_id": "primary",
        "owned_row_ids": ("primary", "continuation"),
        "merchant_text": "SYNTHETIC MERCHANT",
        "atom_ids": ("merchant-1",),
        "source_regions": (),
        "ambiguity_category": None,
    }

    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {**payload, "owned_row_ids": ("continuation", "continuation")}
        )
    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "atom_ids": ("merchant-1", "merchant-1")})


def test_nontransaction_and_ambiguous_references_cannot_carry_merchant_values() -> None:
    with pytest.raises(ValidationError):
        MerchantReference(
            document_id="a" * 64,
            anchor_row_id="row",
            disposition=ReferenceDisposition.NONTRANSACTION,
            owner_row_id=None,
            owned_row_ids=(),
            merchant_text="SECRET MERCHANT",
            atom_ids=(),
            source_regions=(),
            ambiguity_category=None,
        )

    with pytest.raises(ValidationError):
        MerchantReference(
            document_id="a" * 64,
            anchor_row_id="row",
            disposition=ReferenceDisposition.AMBIGUOUS,
            owner_row_id=None,
            owned_row_ids=(),
            merchant_text=None,
            atom_ids=(),
            source_regions=(),
            ambiguity_category=None,
        )


def test_reference_rejects_noncanonical_or_empty_merchant_text() -> None:
    payload = {
        "document_id": "a" * 64,
        "anchor_row_id": "row",
        "disposition": ReferenceDisposition.TRANSACTION,
        "owner_row_id": "row",
        "owned_row_ids": ("row",),
        "atom_ids": ("merchant-1",),
        "source_regions": (),
        "ambiguity_category": None,
    }

    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "merchant_text": "  MERCHANT  "})
    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "merchant_text": " \n "})


def test_assertion_contract_has_only_merchant_nontransaction_or_abstain() -> None:
    assertion = MerchantAssertion(
        context_id="b" * 64,
        document_id="a" * 64,
        anchor_row_id="row",
        disposition=AssertionDisposition.ABSTAIN,
        owner_row_id=None,
        merchant_text=None,
        atom_ids=(),
        source_regions=(),
    )
    assert assertion.model_dump(mode="json")["disposition"] == "abstain"
    with pytest.raises(ValidationError):
        MerchantAssertion.model_validate({**assertion.model_dump(), "prediction": "SECRET"})

    with pytest.raises(ValidationError):
        MerchantAssertion.model_validate(
            {
                **assertion.model_dump(),
                "disposition": AssertionDisposition.MERCHANT,
                "merchant_text": "SYNTHETIC MERCHANT",
                "atom_ids": ("merchant-1",),
            }
        )


def reference_fixture() -> tuple[
    tuple[FrozenRow, ...],
    tuple[FrozenRow, ...],
    tuple[MerchantReference, ...],
]:
    rows = tuple(
        frozen_row(
            document_id=f"{index:064x}",
            row_id=f"row-{index:03d}",
            atoms=(
                evidence_atom(
                    atom_id=f"merchant-{index:03d}",
                    text="SECRET MERCHANT",
                    bbox=(20.0, 20.0, 80.0, 30.0),
                ),
                evidence_atom(
                    atom_id=f"ancillary-{index:03d}",
                    text="ANCILLARY",
                    bbox=(90.0, 20.0, 130.0, 30.0),
                ),
            ),
        )
        for index in range(100)
    )
    references: list[MerchantReference] = []
    for index, row in enumerate(rows):
        if index == 98:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.AMBIGUOUS,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=MerchantErrorCategory.REFERENCE_AMBIGUITY_OR_DEFECT,
                )
            )
        elif index == 99:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.NONTRANSACTION,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
        else:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.TRANSACTION,
                    owner_row_id=row.row_id,
                    owned_row_ids=(row.row_id,),
                    merchant_text="SECRET MERCHANT",
                    atom_ids=(f"merchant-{index:03d}",),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
    return rows, rows, tuple(references)


def test_reference_validation_is_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    population, selected, references = reference_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    summary = validate_merchant_reference(population, selected, references)

    assert summary == MerchantReferenceSummary(
        anchor_count=100,
        eligible_transaction_count=98,
        ambiguous_anchor_count=1,
        nontransaction_anchor_count=1,
    )
    serialized = summary.model_dump_json()
    assert "SECRET MERCHANT" not in serialized
    assert selected[0].document_id not in serialized
    assert selected[0].row_id not in serialized


def _shared_transaction_fixture() -> tuple[
    tuple[FrozenRow, ...],
    tuple[FrozenRow, ...],
    tuple[MerchantReference, ...],
]:
    population, selected, references = reference_fixture()
    shared_document = selected[0].document_id
    selected = (
        selected[0],
        selected[1].model_copy(update={"document_id": shared_document}),
        *selected[2:],
    )
    population = selected
    shared_payload = {
        "document_id": shared_document,
        "owner_row_id": selected[0].row_id,
        "owned_row_ids": (selected[0].row_id, selected[1].row_id),
        "merchant_text": "SECRET MERCHANT",
        "atom_ids": ("merchant-000",),
        "source_regions": (),
    }
    references = (
        references[0].model_copy(update=shared_payload),
        references[1].model_copy(update=shared_payload),
        *references[2:],
    )
    return population, selected, references


def test_reference_validation_counts_unique_transaction_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    summary = validate_merchant_reference(population, selected, references)

    assert summary.eligible_transaction_count == 97


@pytest.mark.parametrize(
    "break_references",
    (
        lambda references: (*references[:-1], references[0]),
        lambda references: references[:-1],
        lambda references: (
            *references[:-1],
            references[-1].model_copy(update={"document_id": "f" * 64, "anchor_row_id": "unknown"}),
        ),
    ),
)
def test_reference_validation_rejects_duplicate_missing_or_unknown_anchors(
    monkeypatch: pytest.MonkeyPatch,
    break_references: Callable[[tuple[MerchantReference, ...]], tuple[MerchantReference, ...]],
) -> None:
    population, selected, references = reference_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference coverage mismatch$"):
        validate_merchant_reference(population, selected, break_references(references))


def test_reference_validation_rejects_nontraining_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = reference_fixture()
    selected = (
        selected[0].model_copy(update={"split": DatasetSplit.VALIDATION}),
        *selected[1:],
    )
    population = selected
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(
        MerchantContextError, match=r"^merchant reference requires training anchors$"
    ):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_selector_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = reference_fixture()
    different = (
        *selected[:-1],
        selected[-1].model_copy(update={"row_id": "different-row"}),
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: different)

    with pytest.raises(
        MerchantContextError, match=r"^merchant reference pilot membership mismatch$"
    ):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_inconsistent_repeated_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    references = (
        references[0],
        references[1].model_copy(
            update={"merchant_text": "OTHER MERCHANT", "atom_ids": ("merchant-001",)}
        ),
        *references[2:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference transaction mismatch$"):
        validate_merchant_reference(population, selected, references)


@pytest.mark.parametrize(
    "reference_update",
    (
        {"owned_row_ids": ("row-000", "unknown-row")},
        {"atom_ids": ("unknown-atom",)},
        {"atom_ids": (), "source_regions": ((0.0, 0.0, 10.0, 5.0),)},
    ),
)
def test_reference_validation_rejects_unknown_or_outside_source_support(
    monkeypatch: pytest.MonkeyPatch,
    reference_update: dict[str, object],
) -> None:
    population, selected, references = reference_fixture()
    references = (
        references[0].model_copy(update=reference_update),
        *references[1:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference evidence mismatch$"):
        validate_merchant_reference(population, selected, references)
