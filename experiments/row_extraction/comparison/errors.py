"""Closed, value-free error taxonomy for frozen row predictions."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from experiments.row_extraction.contracts import (
    Decision,
    FieldProposal,
    FieldRole,
    GoldRow,
    RowPrediction,
    RowType,
    _FrozenModel,
)
from experiments.row_extraction.evidence import EvidenceContractError, resolve_proposal


class ErrorCategory(StrEnum):
    ANNOTATION_AMBIGUITY = "annotation_ambiguity"
    EVIDENCE_CONTRACT = "evidence_contract"
    ROW_TYPE = "row_type"
    OCR_EDIT_OR_SEGMENTATION = "ocr_edit_or_segmentation"
    CROP_BOX_OR_COLUMN = "crop_box_or_column"
    CONTINUATION_OWNERSHIP = "continuation_ownership"
    MERCHANT_SPAN = "merchant_span"
    DATE = "date"
    AMOUNT_SIGN_KIND_CURRENCY = "amount_sign_kind_currency"
    OPTIONAL_FIELD = "optional_field"
    UNSUPPORTED_FIELD_HALLUCINATION = "unsupported_field_hallucination"
    CALIBRATION_FALSE_ACCEPT = "calibration_false_accept"
    CORRECT_ABSTENTION = "correct_abstention"


class ErrorAssignment(_FrozenModel):
    primary: ErrorCategory | None
    secondary: tuple[ErrorCategory, ...]
    reason_codes: tuple[str, ...]


class ErrorCategoryCount(_FrozenModel):
    category: ErrorCategory
    count: int = Field(ge=0)


class ValidationErrorSummary(_FrozenModel):
    """Closed aggregate error evidence for one validation prediction stream."""

    version: Literal["row-comparison-error-summary-v1"]
    row_count: int = Field(gt=0)
    primary_counts: tuple[ErrorCategoryCount, ...]
    secondary_counts: tuple[ErrorCategoryCount, ...]

    @model_validator(mode="after")
    def complete_closed_counts(self) -> Self:
        expected = tuple(ErrorCategory)
        if (
            tuple(value.category for value in self.primary_counts) != expected
            or tuple(value.category for value in self.secondary_counts) != expected
            or sum(value.count for value in self.primary_counts) > self.row_count
            or any(value.count > self.row_count for value in self.secondary_counts)
        ):
            raise ValueError("error summary must contain the closed taxonomy")
        return self


class ErrorClassificationError(ValueError):
    """Gold and prediction records cannot be compared without exposing values."""


_ROLE_RULES = {
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
if set(_ROLE_RULES) != set(FieldRole):
    raise RuntimeError("field error taxonomy is incomplete")
_SEMANTIC_ROLE_PRIORITY = tuple(_ROLE_RULES)

_DIAGNOSTIC_CODE_RULES = {
    "ocr_substitution_error": (
        ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
        "ocr_edit_or_segmentation",
    ),
    "ocr_insertion_error": (
        ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
        "ocr_edit_or_segmentation",
    ),
    "ocr_deletion_error": (
        ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
        "ocr_edit_or_segmentation",
    ),
    "ocr_segmentation_error": (
        ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
        "ocr_edit_or_segmentation",
    ),
    "crop_truncation": (ErrorCategory.CROP_BOX_OR_COLUMN, "crop_box_or_column"),
    "neighboring_row_contamination": (
        ErrorCategory.CROP_BOX_OR_COLUMN,
        "crop_box_or_column",
    ),
    "mixed_direction_error": (
        ErrorCategory.CROP_BOX_OR_COLUMN,
        "crop_box_or_column",
    ),
    "unicode_order_error": (
        ErrorCategory.CROP_BOX_OR_COLUMN,
        "crop_box_or_column",
    ),
    "word_box_drift": (ErrorCategory.CROP_BOX_OR_COLUMN, "crop_box_or_column"),
    "column_assignment_drift": (
        ErrorCategory.CROP_BOX_OR_COLUMN,
        "crop_box_or_column",
    ),
    "continuation_ownership_error": (
        ErrorCategory.CONTINUATION_OWNERSHIP,
        "continuation_ownership",
    ),
    "owner_collision": (
        ErrorCategory.CONTINUATION_OWNERSHIP,
        "continuation_ownership",
    ),
    "wrong_owner": (
        ErrorCategory.CONTINUATION_OWNERSHIP,
        "continuation_ownership",
    ),
}
_DIAGNOSTIC_PRIORITY = (
    ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
    ErrorCategory.CROP_BOX_OR_COLUMN,
    ErrorCategory.CONTINUATION_OWNERSHIP,
)


def _role_reason(role: FieldRole, suffix: str) -> str:
    return f"{role.value}_{suffix}"


def _validated(
    gold: GoldRow,
    prediction: RowPrediction,
) -> tuple[GoldRow, RowPrediction]:
    try:
        validated_gold = GoldRow.model_validate(gold.model_dump(mode="python"))
        validated_prediction = RowPrediction.model_validate(prediction.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise ErrorClassificationError("invalid error-classification input") from None
    if (validated_gold.document_id, validated_gold.row_id) != (
        validated_prediction.document_id,
        validated_prediction.row_id,
    ):
        raise ErrorClassificationError("error-classification identity mismatch")
    roles = tuple(field.role for field in validated_gold.fields)
    if len(roles) != len(set(roles)):
        raise ErrorClassificationError("invalid error-classification input")
    return validated_gold, validated_prediction


def _proposals_by_role(
    prediction: RowPrediction,
) -> dict[FieldRole, tuple[FieldProposal, ...]]:
    grouped: dict[FieldRole, list[FieldProposal]] = {}
    for proposal in prediction.proposals:
        grouped.setdefault(proposal.role, []).append(proposal)
    return {role: tuple(proposals) for role, proposals in grouped.items()}


def classify_error(gold: GoldRow, prediction: RowPrediction) -> ErrorAssignment:
    """Assign one primary cause and ordered secondary causes without field values."""

    gold, prediction = _validated(gold, prediction)
    assignments: list[tuple[ErrorCategory, str]] = []

    def add(category: ErrorCategory, reason_code: str) -> None:
        if all(existing != category for existing, _ in assignments):
            assignments.append((category, reason_code))

    accepted = prediction.decision is Decision.ACCEPT
    correct_abstention = gold.ambiguous and prediction.decision is Decision.ABSTAIN
    if gold.ambiguous:
        add(ErrorCategory.ANNOTATION_AMBIGUITY, "annotation_ambiguous")

    grouped = _proposals_by_role(prediction) if accepted else {}
    resolved: dict[FieldRole, tuple[str, tuple[str, ...]]] = {}
    wrong_owner = False
    for role in _SEMANTIC_ROLE_PRIORITY:
        proposals = grouped.get(role, ())
        if len(proposals) > 1:
            add(
                ErrorCategory.EVIDENCE_CONTRACT,
                f"nonunique_{role.value}_proposal",
            )
            continue
        if not proposals:
            continue
        proposal = proposals[0]
        if proposal.owner_row_id is not None and not proposal.owner_row_id.strip():
            add(ErrorCategory.EVIDENCE_CONTRACT, _role_reason(role, "invalid_owner"))
            continue
        wrong_owner = wrong_owner or (
            gold.row_type is not RowType.CONTINUATION
            and proposal.owner_row_id is not None
            and proposal.owner_row_id != prediction.row_id
        )
        try:
            field = resolve_proposal(prediction, proposal)
        except EvidenceContractError:
            add(ErrorCategory.EVIDENCE_CONTRACT, _role_reason(role, "unresolved_evidence"))
            continue
        resolved[role] = field.canonical_value, field.atom_ids

    if prediction.predicted_type is not gold.row_type:
        add(ErrorCategory.ROW_TYPE, "row_type_mismatch")

    diagnostic_categories = {
        value[0]
        for reason in prediction.reasons
        if (value := _DIAGNOSTIC_CODE_RULES.get(reason)) is not None
    }
    for category in _DIAGNOSTIC_PRIORITY:
        if category in diagnostic_categories:
            add(category, category.value)
    if wrong_owner:
        add(ErrorCategory.CONTINUATION_OWNERSHIP, "continuation_ownership")

    expected = {field.role: field for field in gold.fields}
    if not correct_abstention:
        for role in _SEMANTIC_ROLE_PRIORITY:
            gold_field = expected.get(role)
            actual = resolved.get(role)
            if gold_field is None and role in grouped:
                add(
                    ErrorCategory.UNSUPPORTED_FIELD_HALLUCINATION,
                    f"unsupported_{role.value}_hallucination",
                )
                continue
            if gold_field is None:
                continue
            category = _ROLE_RULES[role]
            if role not in grouped:
                add(category, _role_reason(role, "omission"))
                continue
            if actual is None:
                continue
            canonical_value, atom_ids = actual
            if canonical_value != gold_field.canonical_value:
                add(category, _role_reason(role, "value_mismatch"))
            elif gold_field.atom_ids and atom_ids != gold_field.atom_ids:
                add(category, _role_reason(role, "evidence_mismatch"))

    exact_acceptance = (
        accepted
        and not gold.ambiguous
        and not assignments
        and set(grouped) == set(expected)
        and set(resolved) == set(expected)
    )
    if exact_acceptance:
        return ErrorAssignment(primary=None, secondary=(), reason_codes=())
    if accepted:
        add(ErrorCategory.CALIBRATION_FALSE_ACCEPT, "accepted_inexact_row")
    elif correct_abstention:
        add(ErrorCategory.CORRECT_ABSTENTION, "ambiguous_row_abstained")

    return ErrorAssignment(
        primary=assignments[0][0] if assignments else None,
        secondary=tuple(category for category, _ in assignments[1:]),
        reason_codes=tuple(reason for _, reason in assignments),
    )


__all__ = [
    "ErrorAssignment",
    "ErrorCategory",
    "ErrorCategoryCount",
    "ErrorClassificationError",
    "ValidationErrorSummary",
    "classify_error",
]
