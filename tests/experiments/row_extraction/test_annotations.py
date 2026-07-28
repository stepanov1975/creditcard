from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from ccparser.models import TransactionKind
from experiments.row_extraction.annotations import (
    AnnotationError,
    AnnotationSummary,
    validate_annotations,
)
from experiments.row_extraction.contracts import (
    EvidenceAtom,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    OcrReference,
    RowType,
)
from tests.experiments.row_extraction.factories import frozen_row

_DOCUMENT_ID = "a" * 64
_SECOND_DOCUMENT_ID = "b" * 64


def _atom(
    atom_id: str,
    text: str,
    x0: float,
    x1: float,
) -> EvidenceAtom:
    return EvidenceAtom(
        atom_id=atom_id,
        text=text,
        bbox=(x0, 10.0, x1, 20.0),
        source="digital",
        confidence=1.0,
        column_index=None,
    )


def _primary_row(
    *,
    document_id: str = _DOCUMENT_ID,
    row_id: str = "row-primary",
    baseline_type: RowType = RowType.PRIMARY_TRANSACTION,
    previous_row_id: str | None = None,
    next_row_id: str | None = None,
) -> FrozenRow:
    atoms = (
        _atom("transaction-date", "2026-04-03", 5.0, 20.0),
        _atom("posting-date", "2026-04-04", 21.0, 36.0),
        _atom("conversion-date", "2026-04-05", 37.0, 52.0),
        _atom("description", "SYNTHETIC BOOKSHOP", 53.0, 90.0),
        _atom("billing-currency", "USD", 91.0, 99.0),
        _atom("billed-amount", "12.34", 100.0, 115.0),
        _atom("original-currency", "EUR", 116.0, 124.0),
        _atom("original-amount", "10.20", 125.0, 140.0),
        _atom("installment", "2/6", 141.0, 150.0),
        _atom("fx-rate", "1.2098", 151.0, 165.0),
        _atom("ancillary", "SYNTHETIC NOTE", 166.0, 195.0),
    )
    row = frozen_row(
        document_id=document_id,
        row_id=row_id,
        bbox=(0.0, 0.0, 200.0, 30.0),
        baseline_type=baseline_type,
        atoms=atoms,
    )
    return row.model_copy(
        update={
            "previous_row_id": previous_row_id,
            "next_row_id": next_row_id,
        }
    )


def _field(
    role: FieldRole,
    canonical_value: str,
    atom_ids: tuple[str, ...],
    *,
    source_region: tuple[float, float, float, float] | None = None,
) -> GoldField:
    return GoldField(
        role=role,
        canonical_value=canonical_value,
        atom_ids=atom_ids,
        source_region=source_region,
    )


def _required_primary_fields() -> tuple[GoldField, ...]:
    return (
        _field(FieldRole.BILLED_AMOUNT, "12.34", ("billed-amount",)),
        _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",)),
        _field(
            FieldRole.KIND,
            TransactionKind.CHARGE.value,
            ("billed-amount",),
        ),
    )


def _primary_gold(
    *,
    document_id: str = _DOCUMENT_ID,
    row_id: str = "row-primary",
    fields: tuple[GoldField, ...] | None = None,
    row_type: RowType = RowType.PRIMARY_TRANSACTION,
    ambiguous: bool = False,
) -> GoldRow:
    return GoldRow(
        document_id=document_id,
        row_id=row_id,
        row_type=row_type,
        fields=_required_primary_fields() if fields is None else fields,
        ambiguous=ambiguous,
    )


def _error_text(
    rows: tuple[FrozenRow, ...],
    labels: tuple[GoldRow, ...],
    references: tuple[OcrReference, ...] = (),
) -> str:
    with pytest.raises(AnnotationError) as captured:
        validate_annotations(rows, labels, references)
    return str(captured.value)


def test_valid_annotation_summary_is_immutable_and_contains_only_coverage_counts() -> None:
    row = _primary_row()
    fields = (
        _field(FieldRole.TRANSACTION_DATE, "2026-04-03", ("transaction-date",)),
        _field(FieldRole.POSTING_DATE, "2026-04-04", ("posting-date",)),
        _field(FieldRole.CONVERSION_DATE, "2026-04-05", ("conversion-date",)),
        _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
        *_required_primary_fields(),
        _field(FieldRole.ORIGINAL_AMOUNT, "10.2", ("original-amount",)),
        _field(FieldRole.ORIGINAL_CURRENCY, "EUR", ("original-currency",)),
        _field(FieldRole.INSTALLMENT, "2/6", ("installment",)),
        _field(FieldRole.FX_RATE, "1.2098", ("fx-rate",)),
        _field(FieldRole.ANCILLARY, "SYNTHETIC NOTE", ("ancillary",)),
    )
    label = _primary_gold(fields=fields)
    reference = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="SYNTHETIC BOOKSHOP",
        source_region=(53.0, 10.0, 90.0, 20.0),
    )

    summary = validate_annotations((row,), (label,), (reference,))

    assert summary == AnnotationSummary(
        row_count=1,
        label_count=1,
        field_count=12,
        primary_row_count=1,
        continuation_row_count=0,
        structural_row_count=0,
        ambiguous_row_count=0,
        ocr_reference_count=1,
        ocr_referenced_row_count=1,
        ocr_referenced_field_count=1,
    )
    serialized = summary.model_dump_json()
    assert row.row_id not in serialized
    assert row.document_id not in serialized
    assert "SYNTHETIC" not in serialized
    assert "12.34" not in serialized
    with pytest.raises(ValidationError, match="Instance is frozen"):
        summary.row_count = 2


def test_annotation_rejects_unknown_atom() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("unknown",)),
        )
    )

    error = _error_text((row,), (label,))

    assert "gold atom is not present in frozen row" in error
    assert row.document_id in error
    assert row.row_id in error
    assert "SYNTHETIC BOOKSHOP" not in error


def test_ambiguous_gold_cannot_contain_unique_fields() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(_field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),),
        row_type=RowType.AMBIGUOUS,
        ambiguous=True,
    )

    assert "ambiguous row cannot assert unique fields" in _error_text((row,), (label,))


def test_every_frozen_row_requires_exactly_one_label() -> None:
    first = _primary_row(row_id="row-first")
    second = _primary_row(row_id="row-second")

    error = _error_text((first, second), (_primary_gold(row_id=first.row_id),))

    assert "frozen row is missing a gold label" in error
    assert second.row_id in error
    assert "12.34" not in error


def test_unknown_label_identity_is_rejected_without_field_values() -> None:
    row = _primary_row()
    label = _primary_gold(document_id=_SECOND_DOCUMENT_ID, row_id="unknown-row")

    error = _error_text((row,), (label,))

    assert "gold label has no frozen row" in error
    assert _SECOND_DOCUMENT_ID in error
    assert "unknown-row" in error
    assert "12.34" not in error


def test_invalid_frozen_row_bbox_is_rejected() -> None:
    row = _primary_row().model_copy(update={"bbox": (0.0, 0.0, 0.0, 30.0)})

    assert "frozen row bbox is invalid" in _error_text((row,), (_primary_gold(),))


def test_duplicate_frozen_atom_ids_are_rejected() -> None:
    row = _primary_row()
    row = row.model_copy(update={"atoms": (row.atoms[0], row.atoms[0])})

    assert "frozen row atom IDs must be unique" in _error_text(
        (row,),
        (_primary_gold(),),
    )


@pytest.mark.parametrize(
    ("rows", "labels", "message"),
    (
        (
            (_primary_row(), _primary_row()),
            (_primary_gold(),),
            "duplicate frozen row identity",
        ),
        (
            (_primary_row(),),
            (_primary_gold(), _primary_gold()),
            "duplicate gold label identity",
        ),
    ),
)
def test_duplicate_row_or_label_identity_is_rejected(
    rows: tuple[FrozenRow, ...],
    labels: tuple[GoldRow, ...],
    message: str,
) -> None:
    assert message in _error_text(rows, labels)


def test_gold_field_roles_are_unique() -> None:
    row = _primary_row()
    duplicate = _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",))
    label = _primary_gold(fields=(*_required_primary_fields(), duplicate))

    assert "gold field roles must be unique" in _error_text((row,), (label,))


def test_gold_field_atom_ids_are_unique_within_the_field() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP",
                ("description", "description"),
            ),
        )
    )

    assert "gold field atom IDs must be unique" in _error_text((row,), (label,))


def test_gold_field_atom_ids_must_preserve_frozen_source_order() -> None:
    row = _primary_row()
    atoms = list(row.atoms)
    atoms.insert(4, _atom("description-tail", "EAST", 90.0, 91.0))
    row = row.model_copy(update={"atoms": tuple(atoms)})
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP EAST",
                ("description-tail", "description"),
            ),
        )
    )

    assert "gold field atom IDs must preserve frozen source order" in _error_text(
        (row,),
        (label,),
    )


def test_independent_gold_fields_cannot_share_an_atom() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
            _field(FieldRole.ANCILLARY, "SYNTHETIC NOTE", ("description",)),
        )
    )

    assert "gold atom is owned by multiple fields" in _error_text((row,), (label,))


def test_kind_may_share_only_the_exact_billed_amount_support() -> None:
    row = _primary_row()
    different_support = _primary_gold(
        fields=(
            _field(FieldRole.BILLED_AMOUNT, "12.34", ("billed-amount",)),
            _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",)),
            _field(FieldRole.KIND, "charge", ("original-amount",)),
        )
    )

    assert "kind must use the exact billed amount support" in _error_text(
        (row,),
        (different_support,),
    )
    assert validate_annotations((row,), (_primary_gold(),)).field_count == 3


def test_overlapping_independent_source_regions_are_rejected() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP",
                ("description",),
                source_region=(53.0, 9.0, 170.0, 21.0),
            ),
            _field(
                FieldRole.ANCILLARY,
                "SYNTHETIC NOTE",
                ("ancillary",),
                source_region=(80.0, 9.0, 195.0, 21.0),
            ),
        )
    )

    assert "gold source regions overlap across fields" in _error_text((row,), (label,))


def test_gold_source_region_must_overlap_its_declared_support_atoms() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP",
                ("description",),
                source_region=(5.0, 10.0, 20.0, 20.0),
            ),
        )
    )

    assert "gold source region does not overlap declared atoms" in _error_text(
        (row,),
        (label,),
    )


def test_gold_source_region_must_overlap_every_declared_atom() -> None:
    row = _primary_row()
    atoms = list(row.atoms)
    atoms.insert(4, _atom("description-tail", "EAST", 90.0, 91.0))
    row = row.model_copy(update={"atoms": tuple(atoms)})
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP EAST",
                ("description", "description-tail"),
                source_region=(53.0, 10.0, 89.0, 20.0),
            ),
        )
    )

    assert "gold source region does not overlap declared atoms" in _error_text(
        (row,),
        (label,),
    )


def test_gold_source_region_outside_the_fixed_row_is_rejected() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP",
                ("description",),
                source_region=(53.0, 10.0, 201.0, 20.0),
            ),
        )
    )

    assert "gold source region is outside the exact fixed row" in _error_text(
        (row,),
        (label,),
    )


@pytest.mark.parametrize(
    ("role", "invalid", "atom_id"),
    (
        (FieldRole.BILLED_AMOUNT, "NaN", "billed-amount"),
        (FieldRole.ORIGINAL_AMOUNT, "10.20", "original-amount"),
        (FieldRole.FX_RATE, "Infinity", "fx-rate"),
        (FieldRole.TRANSACTION_DATE, "03/04", "transaction-date"),
        (FieldRole.POSTING_DATE, "2026-02-30", "posting-date"),
        (FieldRole.CONVERSION_DATE, "April 3", "conversion-date"),
        (FieldRole.BILLING_CURRENCY, "$", "billing-currency"),
        (FieldRole.ORIGINAL_CURRENCY, "US D", "original-currency"),
        (FieldRole.KIND, "refund", "billed-amount"),
        (FieldRole.INSTALLMENT, "6/2", "installment"),
        (FieldRole.DESCRIPTION, "  SYNTHETIC   BOOKSHOP  ", "description"),
        (FieldRole.ANCILLARY, "", "ancillary"),
    ),
)
def test_canonical_field_values_must_be_typed_and_normalized(
    role: FieldRole,
    invalid: str,
    atom_id: str,
) -> None:
    row = _primary_row()
    fields_by_role = {field.role: field for field in _required_primary_fields()}
    fields_by_role[role] = _field(role, invalid, (atom_id,))
    if role is FieldRole.ORIGINAL_AMOUNT:
        fields_by_role[FieldRole.ORIGINAL_CURRENCY] = _field(
            FieldRole.ORIGINAL_CURRENCY,
            "EUR",
            ("original-currency",),
        )
    if role is FieldRole.ORIGINAL_CURRENCY:
        fields_by_role[FieldRole.ORIGINAL_AMOUNT] = _field(
            FieldRole.ORIGINAL_AMOUNT,
            "10.2",
            ("original-amount",),
        )

    error = _error_text((row,), (_primary_gold(fields=tuple(fields_by_role.values())),))

    assert "invalid canonical field value" in error
    if invalid:
        assert invalid not in error


@pytest.mark.parametrize(
    "unpaired_role",
    (FieldRole.ORIGINAL_AMOUNT, FieldRole.ORIGINAL_CURRENCY),
)
def test_original_amount_and_currency_must_be_paired(unpaired_role: FieldRole) -> None:
    row = _primary_row()
    extra = (
        _field(FieldRole.ORIGINAL_AMOUNT, "10.2", ("original-amount",))
        if unpaired_role is FieldRole.ORIGINAL_AMOUNT
        else _field(FieldRole.ORIGINAL_CURRENCY, "EUR", ("original-currency",))
    )

    assert "original amount and currency must be paired" in _error_text(
        (row,),
        (_primary_gold(fields=(*_required_primary_fields(), extra)),),
    )


def test_kind_must_agree_with_the_nonzero_billed_amount_sign() -> None:
    row = _primary_row()
    fields = (
        _field(FieldRole.BILLED_AMOUNT, "-12.34", ("billed-amount",)),
        _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",)),
        _field(FieldRole.KIND, "charge", ("billed-amount",)),
    )

    assert "kind does not match billed amount sign" in _error_text(
        (row,),
        (_primary_gold(fields=fields),),
    )


def test_zero_billed_amount_cannot_have_a_transaction_kind() -> None:
    row = _primary_row()
    fields = (
        _field(FieldRole.BILLED_AMOUNT, "0", ("billed-amount",)),
        _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",)),
        _field(FieldRole.KIND, "charge", ("billed-amount",)),
    )

    assert "kind does not match billed amount sign" in _error_text(
        (row,),
        (_primary_gold(fields=fields),),
    )


def test_primary_rules_do_not_consult_accepted_baseline_type() -> None:
    row = _primary_row(baseline_type=RowType.STRUCTURAL)

    summary = validate_annotations((row,), (_primary_gold(),))

    assert summary.primary_row_count == 1


def test_primary_requires_billed_amount_currency_and_kind() -> None:
    row = _primary_row()
    label = _primary_gold(fields=(_field(FieldRole.BILLED_AMOUNT, "12.34", ("billed-amount",)),))

    assert "primary row is missing required transaction fields" in _error_text((row,), (label,))


def _continuation_pair() -> tuple[FrozenRow, FrozenRow, GoldRow, GoldRow]:
    previous = _primary_row(row_id="row-previous", next_row_id="row-continuation")
    current = frozen_row(
        document_id=_DOCUMENT_ID,
        row_id="row-continuation",
        bbox=(0.0, 31.0, 200.0, 50.0),
        atoms=(
            EvidenceAtom(
                atom_id="continuation-description",
                text="SYNTHETIC CONTINUATION",
                bbox=(20.0, 35.0, 120.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
            EvidenceAtom(
                atom_id="continuation-conversion-date",
                text="2026-04-05",
                bbox=(121.0, 35.0, 140.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
            EvidenceAtom(
                atom_id="continuation-original-currency",
                text="EUR",
                bbox=(141.0, 35.0, 150.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
            EvidenceAtom(
                atom_id="continuation-original-amount",
                text="10.20",
                bbox=(151.0, 35.0, 165.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
            EvidenceAtom(
                atom_id="continuation-installment",
                text="2/6",
                bbox=(166.0, 35.0, 176.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
            EvidenceAtom(
                atom_id="continuation-fx-rate",
                text="1.2098",
                bbox=(177.0, 35.0, 195.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
        ),
    ).model_copy(update={"previous_row_id": previous.row_id})
    previous_gold = _primary_gold(row_id=previous.row_id)
    current_gold = GoldRow(
        document_id=current.document_id,
        row_id=current.row_id,
        row_type=RowType.CONTINUATION,
        fields=(
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC CONTINUATION",
                ("continuation-description",),
            ),
        ),
    )
    return previous, current, previous_gold, current_gold


def _synthetic_continuation(
    *,
    row_id: str,
    previous_row_id: str,
    next_row_id: str,
    atom_id: str,
) -> tuple[FrozenRow, GoldRow]:
    row = frozen_row(
        document_id=_DOCUMENT_ID,
        row_id=row_id,
        bbox=(0.0, 31.0, 200.0, 50.0),
        atoms=(
            EvidenceAtom(
                atom_id=atom_id,
                text="SYNTHETIC CONTINUATION",
                bbox=(20.0, 35.0, 120.0, 45.0),
                source="digital",
                confidence=1.0,
                column_index=None,
            ),
        ),
    ).model_copy(
        update={
            "previous_row_id": previous_row_id,
            "next_row_id": next_row_id,
        }
    )
    label = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.CONTINUATION,
        fields=(
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC CONTINUATION",
                (atom_id,),
            ),
        ),
    )
    return row, label


def test_continuation_requires_a_valid_fixed_predecessor() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()

    summary = validate_annotations((previous, current), (previous_gold, current_gold))

    assert summary.continuation_row_count == 1


def test_continuation_ownership_rejects_a_self_loop() -> None:
    row, label = _synthetic_continuation(
        row_id="row-self-loop",
        previous_row_id="row-self-loop",
        next_row_id="row-self-loop",
        atom_id="self-loop-description",
    )

    assert "continuation ownership must terminate at a primary row" in _error_text(
        (row,),
        (label,),
    )


def test_continuation_ownership_rejects_an_all_continuation_cycle() -> None:
    first, first_label = _synthetic_continuation(
        row_id="row-cycle-first",
        previous_row_id="row-cycle-second",
        next_row_id="row-cycle-second",
        atom_id="cycle-first-description",
    )
    second, second_label = _synthetic_continuation(
        row_id="row-cycle-second",
        previous_row_id="row-cycle-first",
        next_row_id="row-cycle-first",
        atom_id="cycle-second-description",
    )

    assert "continuation ownership must terminate at a primary row" in _error_text(
        (first, second),
        (first_label, second_label),
    )


def test_continuation_rejects_missing_or_nonreciprocal_predecessor() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()
    missing = current.model_copy(update={"previous_row_id": None})
    nonreciprocal = previous.model_copy(update={"next_row_id": "another-row"})

    assert "continuation row has no fixed predecessor" in _error_text(
        (previous, missing),
        (previous_gold, current_gold),
    )
    assert "continuation predecessor is not reciprocal" in _error_text(
        (nonreciprocal, current),
        (previous_gold, current_gold),
    )


def test_continuation_predecessor_must_have_transaction_ownership() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()
    previous_gold = previous_gold.model_copy(update={"row_type": RowType.STRUCTURAL, "fields": ()})

    assert "continuation predecessor has no transaction ownership" in _error_text(
        (previous, current),
        (previous_gold, current_gold),
    )


def test_continuation_must_have_a_uniquely_supported_field() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()
    current_gold = current_gold.model_copy(update={"fields": ()})

    assert "continuation row has no uniquely supported fields" in _error_text(
        (previous, current),
        (previous_gold, current_gold),
    )


def test_continuation_rejects_unknown_or_cross_document_predecessor() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()
    unknown = current.model_copy(update={"previous_row_id": "unknown-row"})
    other_document = previous.model_copy(update={"document_id": _SECOND_DOCUMENT_ID})
    other_document_gold = previous_gold.model_copy(update={"document_id": _SECOND_DOCUMENT_ID})

    assert "continuation predecessor is not a fixed row" in _error_text(
        (previous, unknown),
        (previous_gold, current_gold),
    )
    assert "continuation predecessor is not a fixed row" in _error_text(
        (other_document, current),
        (other_document_gold, current_gold),
    )


def test_continuation_may_carry_typed_subordinate_financial_fields() -> None:
    previous, current, previous_gold, current_gold = _continuation_pair()
    current_gold = current_gold.model_copy(
        update={
            "fields": (
                _field(
                    FieldRole.CONVERSION_DATE,
                    "2026-04-05",
                    ("continuation-conversion-date",),
                ),
                _field(
                    FieldRole.ORIGINAL_CURRENCY,
                    "EUR",
                    ("continuation-original-currency",),
                ),
                _field(
                    FieldRole.ORIGINAL_AMOUNT,
                    "10.2",
                    ("continuation-original-amount",),
                ),
                _field(
                    FieldRole.INSTALLMENT,
                    "2/6",
                    ("continuation-installment",),
                ),
                _field(
                    FieldRole.FX_RATE,
                    "1.2098",
                    ("continuation-fx-rate",),
                ),
            )
        }
    )

    summary = validate_annotations(
        (previous, current),
        (previous_gold, current_gold),
    )

    assert summary.continuation_row_count == 1
    assert summary.field_count == 8


def test_cited_atom_must_be_inside_the_exact_fixed_row() -> None:
    row = _primary_row()
    atoms = tuple(
        atom.model_copy(update={"bbox": (100.0, 31.0, 115.0, 40.0)})
        if atom.atom_id == "billed-amount"
        else atom
        for atom in row.atoms
    )
    row = row.model_copy(update={"atoms": atoms})

    assert "gold atom is outside the exact fixed row" in _error_text(
        (row,),
        (_primary_gold(),),
    )


def test_structural_row_cannot_assert_transaction_fields() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(_field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),),
        row_type=RowType.STRUCTURAL,
    )

    assert "structural row cannot assert transaction fields" in _error_text((row,), (label,))


@pytest.mark.parametrize(
    ("row_type", "ambiguous"),
    (
        (RowType.AMBIGUOUS, False),
        (RowType.PRIMARY_TRANSACTION, True),
    ),
)
def test_ambiguity_flag_and_row_type_must_agree(row_type: RowType, ambiguous: bool) -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=() if row_type is RowType.AMBIGUOUS else _required_primary_fields(),
        row_type=row_type,
        ambiguous=ambiguous,
    )

    assert "ambiguous flag must match ambiguous row type" in _error_text((row,), (label,))


def test_ocr_reference_identity_must_be_unique_by_row_role_and_region() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
        )
    )
    reference = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="SYNTHETIC BOOKSHOP",
        source_region=(53.0, 10.0, 90.0, 20.0),
    )

    assert "duplicate OCR reference identity" in _error_text(
        (row,),
        (label,),
        (reference, reference),
    )


def test_ocr_reference_requires_an_exact_fixed_row_and_annotated_role() -> None:
    row = _primary_row()
    label = _primary_gold()
    unknown = OcrReference(
        document_id=row.document_id,
        row_id="unknown-row",
        role=FieldRole.DESCRIPTION,
        verbatim_text="SYNTHETIC BOOKSHOP",
        source_region=(53.0, 10.0, 90.0, 20.0),
    )
    unannotated = unknown.model_copy(update={"row_id": row.row_id})

    assert "OCR reference has no frozen row" in _error_text((row,), (label,), (unknown,))
    assert "OCR reference role is not annotated" in _error_text(
        (row,),
        (label,),
        (unannotated,),
    )


@pytest.mark.parametrize(
    "region",
    (
        (-1.0, 10.0, 90.0, 20.0),
        (53.0, 10.0, 201.0, 20.0),
        (53.0, 10.0, 53.0, 20.0),
        (53.0, 10.0, float("inf"), 20.0),
    ),
)
def test_ocr_reference_region_must_be_finite_nonempty_and_inside_exact_row(
    region: tuple[float, float, float, float],
) -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
        )
    )
    reference = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="TRANSCRIPTION INDEPENDENT OF CANONICAL VALUE",
        source_region=region,
    )

    error = _error_text((row,), (label,), (reference,))

    assert "OCR reference region is outside the exact fixed row" in error
    assert reference.verbatim_text not in error


def test_ocr_reference_transcription_is_not_compared_with_canonical_field_value() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
        )
    )
    reference = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="SYNTHETIC B00KSHOP",
        source_region=(53.0, 10.0, 90.0, 20.0),
    )

    summary = validate_annotations((row,), (label,), (reference,))

    assert summary.ocr_reference_count == 1


def test_ocr_reference_region_must_match_the_annotated_field_support() -> None:
    row = _primary_row()
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(FieldRole.DESCRIPTION, "SYNTHETIC BOOKSHOP", ("description",)),
        )
    )
    disjoint = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="WRONG IN-ROW REGION",
        source_region=(5.0, 10.0, 20.0, 20.0),
    )

    assert "OCR reference region does not match annotated field support" in _error_text(
        (row,),
        (label,),
        (disjoint,),
    )


def test_ocr_reference_region_equals_explicit_gold_field_region() -> None:
    row = _primary_row()
    declared_region = (53.0, 10.0, 90.0, 20.0)
    label = _primary_gold(
        fields=(
            *_required_primary_fields(),
            _field(
                FieldRole.DESCRIPTION,
                "SYNTHETIC BOOKSHOP",
                ("description",),
                source_region=declared_region,
            ),
        )
    )
    narrower = OcrReference(
        document_id=row.document_id,
        row_id=row.row_id,
        role=FieldRole.DESCRIPTION,
        verbatim_text="SYNTHETIC BOOKSHOP",
        source_region=(55.0, 10.0, 88.0, 20.0),
    )
    exact = narrower.model_copy(update={"source_region": declared_region})

    assert "OCR reference region does not match annotated field support" in _error_text(
        (row,),
        (label,),
        (narrower,),
    )
    assert validate_annotations((row,), (label,), (exact,)).ocr_reference_count == 1


def test_validator_never_synthesizes_ocr_references() -> None:
    summary = validate_annotations((_primary_row(),), (_primary_gold(),))

    assert summary.ocr_reference_count == 0
    assert summary.ocr_referenced_row_count == 0
    assert summary.ocr_referenced_field_count == 0


def test_amount_validation_uses_decimal_not_binary_float() -> None:
    row = _primary_row()
    amount = Decimal("0.1") + Decimal("0.2")
    fields = (
        _field(FieldRole.BILLED_AMOUNT, str(amount), ("billed-amount",)),
        _field(FieldRole.BILLING_CURRENCY, "USD", ("billing-currency",)),
        _field(FieldRole.KIND, "charge", ("billed-amount",)),
    )

    assert validate_annotations((row,), (_primary_gold(fields=fields),)).field_count == 3
