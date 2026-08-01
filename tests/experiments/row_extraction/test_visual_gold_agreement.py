from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest
from pydantic import ValidationError

from experiments.row_extraction.annotations import AnnotationError
from experiments.row_extraction.contracts import (
    BBox,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    RowType,
)
from experiments.row_extraction.visual_gold_agreement import (
    AnnotationDefectCategory,
    AnnotationDefectSummary,
    CurrentGoldDefect,
    DisagreementKind,
    VisualAgreementSummary,
    compare_visual_reviews,
    summarize_current_gold_defects,
)
from experiments.row_extraction.visual_gold_pilot import VisualReviewDecision
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row

_SECRET_VALUE = "SECRET CANONICAL VALUE"
_SECRET_TEXT = "SECRET ROW TEXT"


def _row(index: int) -> FrozenRow:
    return frozen_row(
        document_id=f"{index:064x}",
        row_id=f"opaque-row-{index:03d}",
        atoms=(
            evidence_atom(
                atom_id=f"amount-{index}",
                text="12.34",
                bbox=(10.0, 20.0, 30.0, 30.0),
            ),
            evidence_atom(
                atom_id=f"currency-{index}",
                text="USD",
                bbox=(40.0, 20.0, 60.0, 30.0),
            ),
            evidence_atom(
                atom_id=f"description-a-{index}",
                text=_SECRET_TEXT,
                bbox=(70.0, 20.0, 90.0, 30.0),
            ),
            evidence_atom(
                atom_id=f"description-b-{index}",
                text=_SECRET_TEXT,
                bbox=(72.0, 20.0, 92.0, 30.0),
            ),
        ),
    )


def _rows() -> tuple[FrozenRow, ...]:
    return tuple(_row(index) for index in range(100))


def _primary_label(
    row: FrozenRow,
    *,
    billed_amount: str = "12.34",
    description: str | None = None,
    description_atom: str = "a",
    description_region: BBox | None = None,
) -> GoldRow:
    index = int(row.row_id.rsplit("-", maxsplit=1)[1])
    amount_atom = f"amount-{index}"
    fields = [
        GoldField(
            role=FieldRole.BILLED_AMOUNT,
            canonical_value=billed_amount,
            atom_ids=(amount_atom,),
        ),
        GoldField(
            role=FieldRole.BILLING_CURRENCY,
            canonical_value="USD",
            atom_ids=(f"currency-{index}",),
        ),
        GoldField(
            role=FieldRole.KIND,
            canonical_value="charge",
            atom_ids=(amount_atom,),
        ),
    ]
    if description is not None:
        fields.append(
            GoldField(
                role=FieldRole.DESCRIPTION,
                canonical_value=description,
                atom_ids=(f"description-{description_atom}-{index}",),
                source_region=description_region,
            )
        )
    return GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.PRIMARY_TRANSACTION,
        fields=tuple(fields),
    )


def _fieldless_label(row: FrozenRow, row_type: RowType) -> GoldRow:
    return GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=row_type,
        fields=(),
        ambiguous=row_type is RowType.AMBIGUOUS,
    )


def _decisions(labels: Sequence[GoldRow]) -> tuple[VisualReviewDecision, ...]:
    return tuple(VisualReviewDecision(label=label, page_context_used=False) for label in labels)


def test_comparison_uses_exact_semantic_and_separate_support_rules() -> None:
    rows = _rows()
    labels_a = [_primary_label(row) for row in rows]
    labels_b = [_primary_label(row) for row in rows]
    labels_b[0] = _primary_label(rows[0], billed_amount="11")
    labels_b[1] = _primary_label(rows[1], description="Merchant")
    labels_a[2] = _primary_label(rows[2], description="Merchant")
    labels_b[2] = _primary_label(rows[2], description="Merchant", description_atom="b")
    labels_a[3] = _primary_label(
        rows[3],
        description="Merchant",
        description_region=(70.0, 20.0, 90.0, 30.0),
    )
    labels_b[3] = _primary_label(
        rows[3],
        description="Merchant",
        description_region=(70.0, 20.0, 91.0, 30.0),
    )
    labels_b[4] = _fieldless_label(rows[4], RowType.AMBIGUOUS)

    summary, disagreements = compare_visual_reviews(
        rows,
        tuple(reversed(rows)),
        tuple(reversed(_decisions(labels_a))),
        _decisions(labels_b),
    )

    assert summary == VisualAgreementSummary(
        row_count=100,
        row_type_matches=99,
        row_type_agreement=Decimal("0.99"),
        eligible_field_slots=303,
        exact_field_matches=298,
        field_exact_agreement=Decimal(298) / Decimal(303),
        joint_field_slots=299,
        atom_support_matches=298,
        atom_support_agreement=Decimal(298) / Decimal(299),
        source_region_matches=298,
        source_region_agreement=Decimal(298) / Decimal(299),
        valid=True,
        row_type_gate_passed=True,
        field_exact_gate_passed=True,
        pilot_passed=True,
    )
    assert tuple((item.row_id, item.kinds) for item in disagreements) == (
        ("opaque-row-000", (DisagreementKind.CANONICAL_VALUE,)),
        ("opaque-row-001", (DisagreementKind.FIELD_PRESENCE,)),
        ("opaque-row-002", (DisagreementKind.ATOM_SUPPORT,)),
        ("opaque-row-003", (DisagreementKind.SOURCE_REGION,)),
        (
            "opaque-row-004",
            (
                DisagreementKind.ROW_TYPE,
                DisagreementKind.AMBIGUITY,
                DisagreementKind.FIELD_PRESENCE,
            ),
        ),
    )
    assert tuple(item.document_id for item in disagreements) == tuple(
        f"{index:064x}" for index in range(5)
    )


def test_comparison_summary_is_immutable_and_contains_only_aggregate_data() -> None:
    rows = _rows()
    labels = tuple(_primary_label(row) for row in rows)

    summary, disagreements = compare_visual_reviews(
        rows,
        rows,
        _decisions(labels),
        _decisions(labels),
    )

    assert disagreements == ()
    assert set(summary.model_dump()) == {
        "row_count",
        "row_type_matches",
        "row_type_agreement",
        "eligible_field_slots",
        "exact_field_matches",
        "field_exact_agreement",
        "joint_field_slots",
        "atom_support_matches",
        "atom_support_agreement",
        "source_region_matches",
        "source_region_agreement",
        "valid",
        "row_type_gate_passed",
        "field_exact_gate_passed",
        "pilot_passed",
    }
    serialized = summary.model_dump_json()
    for private_value in (
        rows[0].document_id,
        rows[0].row_id,
        FieldRole.BILLED_AMOUNT.value,
        "12.34",
        rows[0].atoms[0].atom_id,
        str(rows[0].bbox),
        str(rows[0].source_pdf),
        _SECRET_TEXT,
        _SECRET_VALUE,
    ):
        assert private_value not in serialized
    with pytest.raises(ValidationError, match="frozen"):
        summary.valid = False


@pytest.mark.parametrize(
    ("row_mismatches", "expected_rate", "expected_gate"),
    (
        (5, Decimal("0.95"), True),
        (6, Decimal("0.94"), False),
    ),
)
def test_row_type_gate_is_inclusive(
    row_mismatches: int,
    expected_rate: Decimal,
    expected_gate: bool,
) -> None:
    rows = _rows()
    labels_a = tuple(_fieldless_label(row, RowType.STRUCTURAL) for row in rows)
    labels_b = tuple(
        _fieldless_label(
            row,
            RowType.AMBIGUOUS if index < row_mismatches else RowType.STRUCTURAL,
        )
        for index, row in enumerate(rows)
    )

    summary, _ = compare_visual_reviews(
        rows,
        rows,
        _decisions(labels_a),
        _decisions(labels_b),
    )

    assert summary.row_type_agreement == expected_rate
    assert summary.row_type_gate_passed is expected_gate
    assert summary.field_exact_agreement == Decimal(1)
    assert summary.field_exact_gate_passed is True
    assert summary.pilot_passed is expected_gate


@pytest.mark.parametrize(
    ("field_mismatches", "expected_rate", "expected_gate"),
    (
        (30, Decimal("0.90"), True),
        (31, Decimal(269) / Decimal(300), False),
    ),
)
def test_field_exact_gate_is_inclusive(
    field_mismatches: int,
    expected_rate: Decimal,
    expected_gate: bool,
) -> None:
    rows = _rows()
    labels_a = tuple(_primary_label(row) for row in rows)
    labels_b = tuple(
        _primary_label(
            row,
            billed_amount="11" if index < field_mismatches else "12.34",
        )
        for index, row in enumerate(rows)
    )

    summary, _ = compare_visual_reviews(
        rows,
        rows,
        _decisions(labels_a),
        _decisions(labels_b),
    )

    assert summary.field_exact_agreement == expected_rate
    assert summary.field_exact_gate_passed is expected_gate
    assert summary.row_type_gate_passed is True
    assert summary.pilot_passed is expected_gate


def test_comparison_requires_exactly_100_selected_rows() -> None:
    population = _rows()
    rows = population[:99]
    labels = tuple(_primary_label(row) for row in rows)

    with pytest.raises(ValueError, match="exactly 100"):
        compare_visual_reviews(
            population,
            rows,
            _decisions(labels),
            _decisions(labels),
        )


@pytest.mark.parametrize("reviewer", ("a", "b"))
def test_comparison_requires_complete_unique_reviewer_coverage(reviewer: str) -> None:
    rows = _rows()
    labels = tuple(_primary_label(row) for row in rows)
    decisions_a = _decisions(labels)
    decisions_b = _decisions(labels)
    duplicated = (*decisions_a[:-1], decisions_a[0])
    if reviewer == "a":
        decisions_a = duplicated
    else:
        decisions_b = duplicated

    with pytest.raises(AnnotationError, match="duplicate gold label identity"):
        compare_visual_reviews(rows, rows, decisions_a, decisions_b)


@pytest.mark.parametrize("reviewer", ("a", "b"))
def test_comparison_validates_each_reviewer_label(reviewer: str) -> None:
    rows = _rows()
    labels_a = list(_primary_label(row) for row in rows)
    labels_b = labels_a.copy()
    invalid = GoldRow(
        document_id=rows[0].document_id,
        row_id=rows[0].row_id,
        row_type=RowType.STRUCTURAL,
        fields=(
            GoldField(
                role=FieldRole.DESCRIPTION,
                canonical_value=_SECRET_VALUE,
                atom_ids=(rows[0].atoms[2].atom_id,),
            ),
        ),
    )
    if reviewer == "a":
        labels_a[0] = invalid
    else:
        labels_b[0] = invalid

    with pytest.raises(AnnotationError, match="structural row cannot assert"):
        compare_visual_reviews(
            rows,
            rows,
            _decisions(labels_a),
            _decisions(labels_b),
        )


def test_comparison_uses_population_for_unselected_continuation_predecessor() -> None:
    base_rows = _rows()
    predecessor = _row(100).model_copy(
        update={
            "document_id": base_rows[0].document_id,
            "row_id": "opaque-predecessor",
            "next_row_id": base_rows[0].row_id,
        }
    )
    continuation = base_rows[0].model_copy(update={"previous_row_id": predecessor.row_id})
    selected_rows = (continuation, *base_rows[1:])
    labels = (
        GoldRow(
            document_id=continuation.document_id,
            row_id=continuation.row_id,
            row_type=RowType.CONTINUATION,
            fields=(
                GoldField(
                    role=FieldRole.DESCRIPTION,
                    canonical_value="Merchant",
                    atom_ids=("description-a-0",),
                ),
            ),
        ),
        *(_primary_label(row) for row in base_rows[1:]),
    )

    summary, disagreements = compare_visual_reviews(
        (*selected_rows, predecessor),
        selected_rows,
        _decisions(labels),
        _decisions(labels),
    )

    assert summary.valid is True
    assert disagreements == ()


def _defect(
    row: FrozenRow,
    *categories: AnnotationDefectCategory,
) -> CurrentGoldDefect:
    return CurrentGoldDefect(
        document_id=row.document_id,
        row_id=row.row_id,
        categories=categories,
    )


def test_defect_summary_counts_only_aggregate_classified_differences() -> None:
    rows = _rows()
    current = [_primary_label(row) for row in rows]
    candidate = current.copy()
    candidate[0] = _fieldless_label(rows[0], RowType.AMBIGUOUS)
    candidate[1] = _primary_label(rows[1], description="Merchant")
    candidate[2] = _primary_label(rows[2], billed_amount="11")
    current[3] = _primary_label(rows[3], description="Merchant")
    candidate[3] = _primary_label(rows[3], description="Vendor")
    candidate[4] = _primary_label(rows[4], billed_amount="13")
    current[5] = _primary_label(rows[5], description="Merchant")
    candidate[5] = _primary_label(
        rows[5],
        description="Merchant",
        description_atom="b",
    )
    current[6] = _primary_label(
        rows[6],
        description="Merchant",
        description_region=(70.0, 20.0, 90.0, 30.0),
    )
    candidate[6] = _primary_label(
        rows[6],
        description="Merchant",
        description_region=(70.0, 20.0, 89.0, 30.0),
    )
    classifications = (
        _defect(rows[6], AnnotationDefectCategory.EVIDENCE_SUPPORT),
        _defect(rows[4], AnnotationDefectCategory.CANONICAL_VALUE_OTHER),
        _defect(rows[2], AnnotationDefectCategory.RTL_MIXED_ORDER),
        _defect(
            rows[0], AnnotationDefectCategory.ROW_TYPE, AnnotationDefectCategory.FIELD_PRESENCE
        ),
        _defect(rows[5], AnnotationDefectCategory.EVIDENCE_SUPPORT),
        _defect(rows[3], AnnotationDefectCategory.SEGMENTATION),
        _defect(rows[1], AnnotationDefectCategory.FIELD_PRESENCE),
    )

    summary = summarize_current_gold_defects(
        rows,
        tuple(reversed(rows)),
        tuple(reversed(current)),
        candidate,
        classifications,
    )

    assert summary == AnnotationDefectSummary(
        compared_rows=100,
        differing_rows=7,
        row_type_defects=1,
        field_presence_defects=2,
        rtl_mixed_order_defects=1,
        segmentation_defects=1,
        canonical_value_other_defects=1,
        evidence_support_defects=2,
    )
    serialized = summary.model_dump_json()
    for private_value in (
        rows[0].document_id,
        rows[0].row_id,
        "Merchant",
        "13",
        rows[5].atoms[3].atom_id,
        str(rows[6].bbox),
        str(rows[0].source_pdf),
        _SECRET_TEXT,
    ):
        assert private_value not in serialized
    with pytest.raises(ValidationError, match="frozen"):
        summary.differing_rows = 0


@pytest.mark.parametrize("label_set", ("current", "candidate"))
def test_defect_summary_validates_each_gold_set(label_set: str) -> None:
    rows = _rows()
    labels = tuple(_primary_label(row) for row in rows)
    current = labels
    candidate = labels
    duplicated = (*labels[:-1], labels[0])
    if label_set == "current":
        current = duplicated
    else:
        candidate = duplicated

    with pytest.raises(AnnotationError, match="duplicate gold label identity"):
        summarize_current_gold_defects(rows, rows, current, candidate, ())


def test_defect_summary_requires_exactly_100_selected_rows() -> None:
    population = _rows()
    selected_rows = population[:99]
    labels = tuple(_primary_label(row) for row in selected_rows)

    with pytest.raises(ValueError, match="exactly 100"):
        summarize_current_gold_defects(
            population,
            selected_rows,
            labels,
            labels,
            (),
        )


def test_defect_summary_requires_a_classification_for_every_difference() -> None:
    rows = _rows()
    current = tuple(_primary_label(row) for row in rows)
    candidate = list(current)
    candidate[0] = _primary_label(rows[0], description="Merchant")

    with pytest.raises(ValueError, match="exactly cover differing rows"):
        summarize_current_gold_defects(rows, rows, current, candidate, ())


def test_defect_summary_rejects_a_classification_for_an_equal_row() -> None:
    rows = _rows()
    labels = tuple(_primary_label(row) for row in rows)

    with pytest.raises(ValueError, match="equal row"):
        summarize_current_gold_defects(
            rows,
            rows,
            labels,
            labels,
            (_defect(rows[0], AnnotationDefectCategory.FIELD_PRESENCE),),
        )


def test_defect_summary_requires_at_least_one_category_per_difference() -> None:
    rows = _rows()
    current = tuple(_primary_label(row) for row in rows)
    candidate = list(current)
    candidate[0] = _primary_label(rows[0], description="Merchant")

    with pytest.raises(ValueError, match="at least one defect category"):
        summarize_current_gold_defects(
            rows,
            rows,
            current,
            candidate,
            (_defect(rows[0]),),
        )


@pytest.mark.parametrize("difference", ("row_type", "field_presence", "evidence"))
def test_defect_summary_requires_exact_deterministic_categories(
    difference: str,
) -> None:
    rows = _rows()
    current = [_primary_label(row) for row in rows]
    candidate = current.copy()
    categories = (AnnotationDefectCategory.FIELD_PRESENCE,)
    if difference == "row_type":
        candidate[0] = _fieldless_label(rows[0], RowType.AMBIGUOUS)
    elif difference == "field_presence":
        candidate[0] = _primary_label(rows[0], description="Merchant")
        categories = (AnnotationDefectCategory.ROW_TYPE,)
    else:
        current[0] = _primary_label(rows[0], description="Merchant")
        candidate[0] = _primary_label(
            rows[0],
            description="Merchant",
            description_atom="b",
        )

    with pytest.raises(ValueError, match="deterministic defect categories"):
        summarize_current_gold_defects(
            rows,
            rows,
            current,
            candidate,
            (_defect(rows[0], *categories),),
        )


def test_defect_summary_requires_exactly_one_visual_canonical_category() -> None:
    rows = _rows()
    current = tuple(_primary_label(row) for row in rows)
    candidate = list(current)
    candidate[0] = _primary_label(rows[0], billed_amount="13")

    with pytest.raises(ValueError, match="exactly one canonical defect category"):
        summarize_current_gold_defects(
            rows,
            rows,
            current,
            candidate,
            (
                _defect(
                    rows[0],
                    AnnotationDefectCategory.RTL_MIXED_ORDER,
                    AnnotationDefectCategory.SEGMENTATION,
                ),
            ),
        )


def test_defect_summary_rejects_visual_category_without_canonical_difference() -> None:
    rows = _rows()
    current = list(_primary_label(row) for row in rows)
    candidate = current.copy()
    current[0] = _primary_label(rows[0], description="Merchant")
    candidate[0] = _primary_label(
        rows[0],
        description="Merchant",
        description_atom="b",
    )

    with pytest.raises(ValueError, match="canonical defect category"):
        summarize_current_gold_defects(
            rows,
            rows,
            current,
            candidate,
            (
                _defect(
                    rows[0],
                    AnnotationDefectCategory.EVIDENCE_SUPPORT,
                    AnnotationDefectCategory.CANONICAL_VALUE_OTHER,
                ),
            ),
        )


def test_defect_summary_rejects_duplicate_classifications() -> None:
    rows = _rows()
    current = tuple(_primary_label(row) for row in rows)
    candidate = list(current)
    candidate[0] = _primary_label(rows[0], description="Merchant")
    classification = _defect(rows[0], AnnotationDefectCategory.FIELD_PRESENCE)

    with pytest.raises(ValueError, match="duplicate defect classification identity"):
        summarize_current_gold_defects(
            rows,
            rows,
            current,
            candidate,
            (classification, classification),
        )


def test_defect_summary_uses_population_for_continuation_predecessor() -> None:
    base_rows = _rows()
    predecessor = _row(100).model_copy(
        update={
            "document_id": base_rows[0].document_id,
            "row_id": "opaque-predecessor",
            "next_row_id": base_rows[0].row_id,
        }
    )
    continuation = base_rows[0].model_copy(update={"previous_row_id": predecessor.row_id})
    selected_rows = (continuation, *base_rows[1:])
    labels = (
        GoldRow(
            document_id=continuation.document_id,
            row_id=continuation.row_id,
            row_type=RowType.CONTINUATION,
            fields=(
                GoldField(
                    role=FieldRole.DESCRIPTION,
                    canonical_value="Merchant",
                    atom_ids=("description-a-0",),
                ),
            ),
        ),
        *(_primary_label(row) for row in base_rows[1:]),
    )

    summary = summarize_current_gold_defects(
        (*selected_rows, predecessor),
        selected_rows,
        labels,
        labels,
        (),
    )

    assert summary.compared_rows == 100
    assert summary.differing_rows == 0
