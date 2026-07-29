"""Closed, value-free error taxonomy for frozen row predictions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ValidationError

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


class ErrorClassificationError(ValueError):
    """Gold and prediction records cannot be compared without exposing values."""


_DATE_ROLES = {
    FieldRole.TRANSACTION_DATE,
    FieldRole.POSTING_DATE,
    FieldRole.CONVERSION_DATE,
}
_FINANCIAL_ROLES = {
    FieldRole.BILLED_AMOUNT,
    FieldRole.BILLING_CURRENCY,
    FieldRole.ORIGINAL_AMOUNT,
    FieldRole.ORIGINAL_CURRENCY,
    FieldRole.KIND,
}
_OPTIONAL_ROLES = {
    FieldRole.INSTALLMENT,
    FieldRole.FX_RATE,
    FieldRole.ANCILLARY,
}
_SEMANTIC_ROLE_PRIORITY = (
    FieldRole.DESCRIPTION,
    FieldRole.TRANSACTION_DATE,
    FieldRole.POSTING_DATE,
    FieldRole.CONVERSION_DATE,
    FieldRole.BILLED_AMOUNT,
    FieldRole.BILLING_CURRENCY,
    FieldRole.ORIGINAL_AMOUNT,
    FieldRole.ORIGINAL_CURRENCY,
    FieldRole.KIND,
    FieldRole.INSTALLMENT,
    FieldRole.FX_RATE,
    FieldRole.ANCILLARY,
)
_DIAGNOSTIC_RULES: tuple[tuple[tuple[str, ...], ErrorCategory, str], ...] = (
    (
        ("ocr_substitution", "ocr_insertion", "ocr_deletion", "ocr_segmentation"),
        ErrorCategory.OCR_EDIT_OR_SEGMENTATION,
        "ocr_edit_or_segmentation",
    ),
    (
        (
            "crop_truncation",
            "neighboring_row",
            "mixed_direction",
            "unicode_order",
            "word_box",
            "column_assignment",
        ),
        ErrorCategory.CROP_BOX_OR_COLUMN,
        "crop_box_or_column",
    ),
    (
        ("continuation_ownership", "owner_collision", "wrong_owner"),
        ErrorCategory.CONTINUATION_OWNERSHIP,
        "continuation_ownership",
    ),
)


def _role_category(role: FieldRole) -> ErrorCategory:
    if role is FieldRole.DESCRIPTION:
        return ErrorCategory.MERCHANT_SPAN
    if role in _DATE_ROLES:
        return ErrorCategory.DATE
    if role in _FINANCIAL_ROLES:
        return ErrorCategory.AMOUNT_SIGN_KIND_CURRENCY
    if role in _OPTIONAL_ROLES:
        return ErrorCategory.OPTIONAL_FIELD
    return ErrorCategory.OPTIONAL_FIELD


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

    ambiguous_abstention = gold.ambiguous and prediction.decision is not Decision.ACCEPT
    if gold.ambiguous:
        add(ErrorCategory.ANNOTATION_AMBIGUITY, "annotation_ambiguous")

    grouped = _proposals_by_role(prediction)
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

    for fragments, category, reason_code in _DIAGNOSTIC_RULES:
        if any(fragment in reason for reason in prediction.reasons for fragment in fragments):
            add(category, reason_code)
    if wrong_owner:
        add(ErrorCategory.CONTINUATION_OWNERSHIP, "continuation_ownership")

    expected = {field.role: field for field in gold.fields}
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
        category = _role_category(role)
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
        prediction.decision is Decision.ACCEPT
        and not gold.ambiguous
        and not assignments
        and set(grouped) == set(expected)
        and set(resolved) == set(expected)
    )
    if exact_acceptance:
        return ErrorAssignment(primary=None, secondary=(), reason_codes=())
    if prediction.decision is Decision.ACCEPT:
        add(ErrorCategory.CALIBRATION_FALSE_ACCEPT, "accepted_inexact_row")
    elif ambiguous_abstention:
        add(ErrorCategory.CORRECT_ABSTENTION, "ambiguous_row_abstained")
    elif not assignments:
        add(ErrorCategory.CORRECT_ABSTENTION, "prediction_abstained")

    return ErrorAssignment(
        primary=assignments[0][0] if assignments else None,
        secondary=tuple(category for category, _ in assignments[1:]),
        reason_codes=tuple(reason for _, reason in assignments),
    )


__all__ = [
    "ErrorAssignment",
    "ErrorCategory",
    "ErrorClassificationError",
    "classify_error",
]
