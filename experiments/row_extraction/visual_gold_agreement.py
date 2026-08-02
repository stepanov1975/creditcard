"""Privacy-safe agreement measurements for the blind visual-gold pilot."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from experiments.row_extraction.annotations import validate_annotation_subset
from experiments.row_extraction.contracts import (
    DatasetSplit,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    _FrozenModel,
)
from experiments.row_extraction.visual_gold_pilot import VisualReviewDecision

type _RowIdentity = tuple[str, str]

_ROW_TYPE_GATE = Decimal("0.95")
_FIELD_EXACT_GATE = Decimal("0.90")
_PILOT_ROW_COUNT = 100
_RATE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class DisagreementKind(StrEnum):
    """Private categories identifying how two visual reviews differ."""

    ROW_TYPE = "row_type"
    AMBIGUITY = "ambiguity"
    FIELD_PRESENCE = "field_presence"
    CANONICAL_VALUE = "canonical_value"
    ATOM_SUPPORT = "atom_support"
    SOURCE_REGION = "source_region"


class VisualReviewDisagreement(_FrozenModel):
    """Opaque row identity and categories for private adjudication."""

    document_id: str
    row_id: str
    kinds: tuple[DisagreementKind, ...]


class VisualAgreementSummary(_FrozenModel):
    """Aggregate-only agreement metrics safe for public reporting."""

    row_count: int
    row_type_matches: int
    row_type_agreement: Decimal
    eligible_field_slots: int
    exact_field_matches: int
    field_exact_agreement: Decimal
    joint_field_slots: int
    atom_support_matches: int
    atom_support_agreement: Decimal
    source_region_matches: int
    source_region_agreement: Decimal
    valid: bool
    row_type_gate_passed: bool
    field_exact_gate_passed: bool
    pilot_passed: bool


class AnnotationDefectCategory(StrEnum):
    """Predeclared categories for visually confirmed current-gold defects."""

    ROW_TYPE = "row_type"
    FIELD_PRESENCE = "field_presence"
    RTL_MIXED_ORDER = "rtl_mixed_order"
    SEGMENTATION = "segmentation"
    CANONICAL_VALUE_OTHER = "canonical_value_other"
    EVIDENCE_SUPPORT = "evidence_support"


class CurrentGoldDefect(_FrozenModel):
    """Private classification of one current/candidate gold difference."""

    document_id: str
    row_id: str
    categories: tuple[AnnotationDefectCategory, ...]


class AnnotationDefectSummary(_FrozenModel):
    """Aggregate-only current-gold defect counts safe for public reporting."""

    compared_rows: int
    differing_rows: int
    row_type_defects: int
    field_presence_defects: int
    rtl_mixed_order_defects: int
    segmentation_defects: int
    canonical_value_other_defects: int
    evidence_support_defects: int


def _identity(row: FrozenRow | GoldRow) -> _RowIdentity:
    return row.document_id, row.row_id


def _field_map(label: GoldRow) -> dict[FieldRole, GoldField]:
    return {field.role: field for field in label.fields}


def _ratio(matches: int, slots: int) -> Decimal:
    if not slots:
        return Decimal(1)
    with localcontext(_RATE_CONTEXT):
        return Decimal(matches) / Decimal(slots)


def _gate_passed(matches: int, slots: int, threshold: Decimal) -> bool:
    threshold_numerator, threshold_denominator = threshold.as_integer_ratio()
    return slots > 0 and matches * threshold_denominator >= slots * threshold_numerator


def compare_visual_reviews(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    reviewer_a: Sequence[VisualReviewDecision],
    reviewer_b: Sequence[VisualReviewDecision],
) -> tuple[VisualAgreementSummary, tuple[VisualReviewDisagreement, ...]]:
    """Compare two complete, validated blind reviews of the fixed pilot rows."""

    if len(selected_rows) != _PILOT_ROW_COUNT:
        raise ValueError("visual-gold pilot requires exactly 100 selected rows")
    if any(row.split is not DatasetSplit.TRAIN for row in selected_rows):
        raise ValueError("visual-gold pilot requires training rows")

    labels_a = tuple(decision.label for decision in reviewer_a)
    labels_b = tuple(decision.label for decision in reviewer_b)
    validate_annotation_subset(population, selected_rows, labels_a)
    validate_annotation_subset(population, selected_rows, labels_b)

    by_identity_a = {_identity(label): label for label in labels_a}
    by_identity_b = {_identity(label): label for label in labels_b}

    row_type_matches = 0
    eligible_field_slots = 0
    exact_field_matches = 0
    joint_field_slots = 0
    atom_support_matches = 0
    source_region_matches = 0
    disagreements: list[VisualReviewDisagreement] = []

    for identity in sorted(_identity(row) for row in selected_rows):
        label_a = by_identity_a[identity]
        label_b = by_identity_b[identity]
        kinds: list[DisagreementKind] = []

        if label_a.row_type == label_b.row_type:
            row_type_matches += 1
        else:
            kinds.append(DisagreementKind.ROW_TYPE)
        if label_a.ambiguous != label_b.ambiguous:
            kinds.append(DisagreementKind.AMBIGUITY)

        fields_a = _field_map(label_a)
        fields_b = _field_map(label_b)
        roles_a = set(fields_a)
        roles_b = set(fields_b)
        if roles_a != roles_b:
            kinds.append(DisagreementKind.FIELD_PRESENCE)

        canonical_values_match = True
        atom_support_matches_for_row = True
        source_regions_match_for_row = True
        for role in sorted(roles_a | roles_b, key=lambda item: item.value):
            eligible_field_slots += 1
            field_a = fields_a.get(role)
            field_b = fields_b.get(role)
            if field_a is None or field_b is None:
                continue

            joint_field_slots += 1
            if field_a.canonical_value == field_b.canonical_value:
                exact_field_matches += 1
            else:
                canonical_values_match = False
            if field_a.atom_ids == field_b.atom_ids:
                atom_support_matches += 1
            else:
                atom_support_matches_for_row = False
            if field_a.source_region == field_b.source_region:
                source_region_matches += 1
            else:
                source_regions_match_for_row = False

        if not canonical_values_match:
            kinds.append(DisagreementKind.CANONICAL_VALUE)
        if not atom_support_matches_for_row:
            kinds.append(DisagreementKind.ATOM_SUPPORT)
        if not source_regions_match_for_row:
            kinds.append(DisagreementKind.SOURCE_REGION)
        if kinds:
            disagreements.append(
                VisualReviewDisagreement(
                    document_id=identity[0],
                    row_id=identity[1],
                    kinds=tuple(kinds),
                )
            )

    row_count = len(selected_rows)
    row_type_agreement = _ratio(row_type_matches, row_count)
    field_exact_agreement = _ratio(exact_field_matches, eligible_field_slots)
    atom_support_agreement = _ratio(atom_support_matches, joint_field_slots)
    source_region_agreement = _ratio(source_region_matches, joint_field_slots)
    row_type_gate_passed = _gate_passed(row_type_matches, row_count, _ROW_TYPE_GATE)
    field_exact_gate_passed = _gate_passed(
        exact_field_matches,
        eligible_field_slots,
        _FIELD_EXACT_GATE,
    )
    valid = True
    summary = VisualAgreementSummary(
        row_count=row_count,
        row_type_matches=row_type_matches,
        row_type_agreement=row_type_agreement,
        eligible_field_slots=eligible_field_slots,
        exact_field_matches=exact_field_matches,
        field_exact_agreement=field_exact_agreement,
        joint_field_slots=joint_field_slots,
        atom_support_matches=atom_support_matches,
        atom_support_agreement=atom_support_agreement,
        source_region_matches=source_region_matches,
        source_region_agreement=source_region_agreement,
        valid=valid,
        row_type_gate_passed=row_type_gate_passed,
        field_exact_gate_passed=field_exact_gate_passed,
        pilot_passed=valid and row_type_gate_passed and field_exact_gate_passed,
    )
    return summary, tuple(disagreements)


def _gold_difference(
    current: GoldRow,
    candidate: GoldRow,
) -> tuple[bool, bool, bool, bool]:
    current_fields = _field_map(current)
    candidate_fields = _field_map(candidate)
    current_roles = set(current_fields)
    candidate_roles = set(candidate_fields)
    joint_roles = current_roles & candidate_roles
    canonical_value_differs = any(
        current_fields[role].canonical_value != candidate_fields[role].canonical_value
        for role in joint_roles
    )
    evidence_support_differs = any(
        (
            current_fields[role].atom_ids,
            current_fields[role].source_region,
        )
        != (
            candidate_fields[role].atom_ids,
            candidate_fields[role].source_region,
        )
        for role in joint_roles
    )
    return (
        current.row_type != candidate.row_type,
        current_roles != candidate_roles,
        canonical_value_differs,
        evidence_support_differs,
    )


def summarize_current_gold_defects(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    current_gold: Sequence[GoldRow],
    candidate_gold: Sequence[GoldRow],
    classifications: Sequence[CurrentGoldDefect],
) -> AnnotationDefectSummary:
    """Validate and aggregate private classifications of current-gold defects."""

    if len(selected_rows) != _PILOT_ROW_COUNT:
        raise ValueError("visual-gold pilot requires exactly 100 selected rows")
    if any(row.split is not DatasetSplit.TRAIN for row in selected_rows):
        raise ValueError("visual-gold pilot requires training rows")

    validate_annotation_subset(population, selected_rows, current_gold)
    validate_annotation_subset(population, selected_rows, candidate_gold)
    selected_identities = {_identity(row) for row in selected_rows}
    current_by_identity = {_identity(label): label for label in current_gold}
    candidate_by_identity = {_identity(label): label for label in candidate_gold}
    differences = {
        identity: _gold_difference(
            current_by_identity[identity],
            candidate_by_identity[identity],
        )
        for identity in selected_identities
    }
    differing_identities = {identity for identity, flags in differences.items() if any(flags)}

    classifications_by_identity: dict[_RowIdentity, CurrentGoldDefect] = {}
    for classification in classifications:
        identity = (classification.document_id, classification.row_id)
        if identity in classifications_by_identity:
            raise ValueError("duplicate defect classification identity")
        if identity not in selected_identities:
            raise ValueError("defect classification is outside selected rows")
        if identity not in differing_identities:
            raise ValueError("defect classification provided for equal row")
        if not classification.categories:
            raise ValueError("differing row requires at least one defect category")
        if len(classification.categories) != len(set(classification.categories)):
            raise ValueError("duplicate defect category")
        classifications_by_identity[identity] = classification

    if set(classifications_by_identity) != differing_identities:
        raise ValueError("classifications must exactly cover differing rows")

    deterministic_categories = frozenset(
        {
            AnnotationDefectCategory.ROW_TYPE,
            AnnotationDefectCategory.FIELD_PRESENCE,
            AnnotationDefectCategory.EVIDENCE_SUPPORT,
        }
    )
    canonical_categories = frozenset(
        {
            AnnotationDefectCategory.RTL_MIXED_ORDER,
            AnnotationDefectCategory.SEGMENTATION,
            AnnotationDefectCategory.CANONICAL_VALUE_OTHER,
        }
    )
    for identity, classification in classifications_by_identity.items():
        row_type_differs, field_presence_differs, canonical_differs, evidence_differs = differences[
            identity
        ]
        expected_deterministic = {
            category
            for differs, category in (
                (row_type_differs, AnnotationDefectCategory.ROW_TYPE),
                (field_presence_differs, AnnotationDefectCategory.FIELD_PRESENCE),
                (evidence_differs, AnnotationDefectCategory.EVIDENCE_SUPPORT),
            )
            if differs
        }
        actual_categories = set(classification.categories)
        if actual_categories & deterministic_categories != expected_deterministic:
            raise ValueError("classification has inconsistent deterministic defect categories")
        canonical_count = len(actual_categories & canonical_categories)
        if canonical_differs and not canonical_count:
            raise ValueError("canonical difference requires at least one canonical defect category")
        if not canonical_differs and canonical_count:
            raise ValueError("canonical defect category requires a canonical difference")

    category_counts = {
        category: sum(
            category in classification.categories
            for classification in classifications_by_identity.values()
        )
        for category in AnnotationDefectCategory
    }
    return AnnotationDefectSummary(
        compared_rows=len(selected_rows),
        differing_rows=len(differing_identities),
        row_type_defects=category_counts[AnnotationDefectCategory.ROW_TYPE],
        field_presence_defects=category_counts[AnnotationDefectCategory.FIELD_PRESENCE],
        rtl_mixed_order_defects=category_counts[AnnotationDefectCategory.RTL_MIXED_ORDER],
        segmentation_defects=category_counts[AnnotationDefectCategory.SEGMENTATION],
        canonical_value_other_defects=category_counts[
            AnnotationDefectCategory.CANONICAL_VALUE_OTHER
        ],
        evidence_support_defects=category_counts[AnnotationDefectCategory.EVIDENCE_SUPPORT],
    )


__all__ = [
    "AnnotationDefectCategory",
    "AnnotationDefectSummary",
    "CurrentGoldDefect",
    "DisagreementKind",
    "VisualAgreementSummary",
    "VisualReviewDisagreement",
    "compare_visual_reviews",
    "summarize_current_gold_defects",
]
