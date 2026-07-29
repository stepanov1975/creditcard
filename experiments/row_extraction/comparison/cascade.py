"""Validation-frozen, evidence-grounded row prediction cascade."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from ccparser.money import currencies_in_text
from experiments.row_extraction.contracts import (
    PRIMARY_REQUIRED_FIELD_ROLES,
    DatasetSplit,
    Decision,
    FieldProposal,
    FieldRole,
    FrozenRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.evidence import (
    EvidenceContractError,
    render_proposal,
    resolve_proposal,
)

_SHARED_SUPPORT_ROLES = frozenset({FieldRole.BILLED_AMOUNT, FieldRole.KIND})


class CascadePolicyError(ValueError):
    """The cascade policy violates a frozen safety invariant."""


type ReconciliationAdapter = Callable[[RowPrediction], object]


def _accept_reconciliation(_: RowPrediction) -> object:
    return Decision.ACCEPT


@dataclass(frozen=True)
class CascadeRule:
    """One confidence-gated frozen arm and its independent agreement arms."""

    arm_id: str
    minimum_confidence: Decimal
    requires_agreement: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.arm_id:
            raise CascadePolicyError("cascade arm identity is required")
        if (
            not self.minimum_confidence.is_finite()
            or self.minimum_confidence < 0
            or self.minimum_confidence > 1
        ):
            raise CascadePolicyError("confidence threshold must be finite and within [0, 1]")
        if len(self.requires_agreement) != len(set(self.requires_agreement)):
            raise CascadePolicyError("agreement arm identities must be unique")
        if self.arm_id in self.requires_agreement or any(
            not arm_id for arm_id in self.requires_agreement
        ):
            raise CascadePolicyError("agreement arms must be nonempty and independent")


@dataclass(frozen=True)
class CascadePolicy:
    """A validation-selected rule sequence."""

    version: str
    rules: tuple[CascadeRule, ...]

    def __post_init__(self) -> None:
        if not self.version:
            raise CascadePolicyError("cascade policy version is required")
        arm_ids = tuple(rule.arm_id for rule in self.rules)
        if len(arm_ids) != len(set(arm_ids)):
            raise CascadePolicyError("cascade rule arm identities must be unique")


@dataclass(frozen=True)
class CascadeCandidates:
    """Row-aligned predictions and frozen lane dispositions for one cascade decision."""

    row: FrozenRow
    baseline: RowPrediction
    candidates: Mapping[str, RowPrediction]
    dispositions: Mapping[str, LaneDisposition]
    reconciliation: ReconciliationAdapter = _accept_reconciliation

    def __post_init__(self) -> None:
        frozen_candidates = MappingProxyType(dict(self.candidates))
        frozen_dispositions = MappingProxyType(dict(self.dispositions))
        object.__setattr__(self, "candidates", frozen_candidates)
        object.__setattr__(self, "dispositions", frozen_dispositions)
        if (self.row.document_id, self.row.row_id) != (
            self.baseline.document_id,
            self.baseline.row_id,
        ):
            raise CascadePolicyError("cascade frozen-row identity mismatch")


@dataclass(frozen=True)
class CascadeValidationRow:
    """One validation row with reviewed outcomes but no locked-test values."""

    candidates: CascadeCandidates
    exact_outcomes: Mapping[str, bool]
    accepted_row_error_arms: frozenset[str]
    required_field_error_arms: frozenset[str]
    omission_counts: Mapping[str, int]
    latency_ns: Mapping[str, int]

    def __post_init__(self) -> None:
        exact_outcomes = MappingProxyType(dict(self.exact_outcomes))
        omission_counts = MappingProxyType(dict(self.omission_counts))
        latency_ns = MappingProxyType(dict(self.latency_ns))
        if "accepted-baseline" not in exact_outcomes:
            raise CascadePolicyError("validation row lacks baseline exactness state")
        if any(value < 0 for value in (*omission_counts.values(), *latency_ns.values())):
            raise CascadePolicyError("validation costs must be nonnegative")
        object.__setattr__(self, "exact_outcomes", exact_outcomes)
        object.__setattr__(self, "omission_counts", omission_counts)
        object.__setattr__(self, "latency_ns", latency_ns)


@dataclass(frozen=True)
class CascadeValidation:
    """Closed validation-only candidate policy search space."""

    version: str
    rows: tuple[CascadeValidationRow, ...]
    candidate_policies: tuple[CascadePolicy, ...]
    deterministic_arms: Mapping[str, bool]
    maximum_accepted_row_errors: int
    maximum_required_field_errors: int

    def __post_init__(self) -> None:
        if not self.version:
            raise CascadePolicyError("cascade validation version is required")
        if self.maximum_accepted_row_errors < 0 or self.maximum_required_field_errors < 0:
            raise CascadePolicyError("validation error bounds must be nonnegative")
        object.__setattr__(
            self,
            "deterministic_arms",
            MappingProxyType(dict(self.deterministic_arms)),
        )


def _is_grounded(prediction: RowPrediction) -> bool:
    claims: set[tuple[str, object]] = set()
    try:
        for proposal in prediction.proposals:
            owner = proposal.owner_row_id or prediction.row_id
            claim = (owner, proposal.role)
            if claim in claims:
                return False
            claims.add(claim)
            resolve_proposal(prediction, proposal)
    except EvidenceContractError:
        return False
    return True


def _ordered_bbox(bbox: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bbox
    return all(math.isfinite(value) for value in bbox) and x0 < x1 and y0 < y1


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
) -> bool:
    return (
        _ordered_bbox(outer)
        and _ordered_bbox(inner)
        and outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _overlaps(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


def _proposal_owner(row: FrozenRow, prediction: RowPrediction) -> str | None:
    if prediction.predicted_type is RowType.CONTINUATION:
        return row.previous_row_id
    if prediction.predicted_type is RowType.PRIMARY_TRANSACTION:
        return row.row_id
    return None


def _support_boxes(
    prediction: RowPrediction,
    proposal: FieldProposal,
) -> tuple[tuple[float, float, float, float], ...]:
    ledger = {atom.atom_id: atom for atom in prediction.evidence_atoms}
    atom_boxes = tuple(ledger[atom_id].bbox for atom_id in proposal.atom_ids)
    if proposal.source_region is None:
        return atom_boxes
    return (*atom_boxes, proposal.source_region)


def _is_deterministically_valid(row: FrozenRow, prediction: RowPrediction) -> bool:
    if (row.document_id, row.row_id) != (prediction.document_id, prediction.row_id):
        return False
    if not _ordered_bbox(row.bbox) or any(
        not _contains(row.bbox, atom.bbox) for atom in prediction.evidence_atoms
    ):
        return False

    roles = {proposal.role for proposal in prediction.proposals}
    expected_owner = _proposal_owner(row, prediction)
    if prediction.predicted_type is RowType.PRIMARY_TRANSACTION:
        if not roles >= PRIMARY_REQUIRED_FIELD_ROLES:
            return False
    elif prediction.predicted_type is RowType.CONTINUATION:
        if expected_owner is None or not expected_owner.strip() or not prediction.proposals:
            return False
    elif prediction.proposals:
        return False

    atom_order = {atom.atom_id: index for index, atom in enumerate(prediction.evidence_atoms)}
    supports: list[tuple[FieldRole, tuple[float, float, float, float]]] = []
    by_role: dict[FieldRole, FieldProposal] = {}
    for proposal in prediction.proposals:
        if proposal.owner_row_id is not None and not proposal.owner_row_id.strip():
            return False
        owner = proposal.owner_row_id or prediction.row_id
        if expected_owner is None or owner != expected_owner:
            return False
        positions = tuple(atom_order[atom_id] for atom_id in proposal.atom_ids)
        if positions != tuple(sorted(positions)):
            return False
        if proposal.source_region is not None and (
            not _contains(row.bbox, proposal.source_region)
            or not all(
                _overlaps(proposal.source_region, bbox)
                for bbox in _support_boxes(prediction, proposal)[:-1]
            )
        ):
            return False
        boxes = _support_boxes(prediction, proposal)
        if any(
            _overlaps(previous_box, box) and {previous_role, proposal.role} != _SHARED_SUPPORT_ROLES
            for previous_role, previous_box in supports
            for box in boxes
        ):
            return False
        supports.extend((proposal.role, box) for box in boxes)
        by_role[proposal.role] = proposal

    billed = by_role.get(FieldRole.BILLED_AMOUNT)
    kind = by_role.get(FieldRole.KIND)
    if kind is not None and (
        billed is None
        or kind.atom_ids != billed.atom_ids
        or kind.source_region != billed.source_region
    ):
        return False
    billing_currency = by_role.get(FieldRole.BILLING_CURRENCY)
    if billed is not None and billing_currency is not None:
        explicit = currencies_in_text(render_proposal(prediction, billed))
        resolved_currency = resolve_proposal(prediction, billing_currency).canonical_value
        if explicit and explicit != (resolved_currency,):
            return False
    has_original_amount = FieldRole.ORIGINAL_AMOUNT in by_role
    has_original_currency = FieldRole.ORIGINAL_CURRENCY in by_role
    if has_original_amount != has_original_currency:
        return False
    if has_original_amount:
        original_amount = by_role[FieldRole.ORIGINAL_AMOUNT]
        original_currency = by_role[FieldRole.ORIGINAL_CURRENCY]
        explicit = currencies_in_text(render_proposal(prediction, original_amount))
        resolved_currency = resolve_proposal(prediction, original_currency).canonical_value
        if explicit and explicit != (resolved_currency,):
            return False
    return True


def _resolved_signature(prediction: RowPrediction) -> tuple[object, ...]:
    fields = tuple(
        sorted(
            (
                (proposal.owner_row_id or prediction.row_id),
                proposal.role.value,
                resolve_proposal(prediction, proposal).canonical_value,
            )
            for proposal in prediction.proposals
        )
    )
    return prediction.predicted_type, fields


def _abstain_like(prediction: RowPrediction, reason: str) -> RowPrediction:
    return RowPrediction(
        experiment_id="row-cascade",
        config_id="cascade-v1",
        document_id=prediction.document_id,
        row_id=prediction.row_id,
        predicted_type=prediction.predicted_type,
        evidence_atoms=(),
        proposals=(),
        exact_row_confidence=None,
        decision=Decision.ABSTAIN,
        reasons=(reason,),
    )


def _reconcile(
    selected: RowPrediction,
    reconciliation: ReconciliationAdapter,
) -> RowPrediction:
    disposition = reconciliation(selected)
    if disposition is Decision.ACCEPT:
        return selected
    if disposition is Decision.REJECT:
        return RowPrediction(
            experiment_id=selected.experiment_id,
            config_id=selected.config_id,
            document_id=selected.document_id,
            row_id=selected.row_id,
            predicted_type=selected.predicted_type,
            evidence_atoms=selected.evidence_atoms,
            proposals=selected.proposals,
            exact_row_confidence=selected.exact_row_confidence,
            decision=Decision.REJECT,
            reasons=(*selected.reasons, "cascade_reconciliation_rejected"),
        )
    raise CascadePolicyError("reconciliation is rejection-only")


def apply_cascade(
    policy: CascadePolicy,
    candidates: CascadeCandidates,
) -> RowPrediction:
    """Apply one frozen policy without consulting labels or mutable extraction state."""

    referenced_arms = {
        arm_id for rule in policy.rules for arm_id in (rule.arm_id, *rule.requires_agreement)
    }
    for arm_id in referenced_arms:
        disposition = candidates.dispositions.get(arm_id)
        if disposition is LaneDisposition.VALIDATION_STOPPED:
            raise CascadePolicyError("validation-stopped lane cannot enter cascade")
        if disposition is not LaneDisposition.FROZEN_ELIGIBLE:
            raise CascadePolicyError("cascade arm lacks a frozen-eligible disposition")

    baseline = candidates.baseline
    if baseline.experiment_id == "accepted-baseline" and baseline.decision is Decision.ACCEPT:
        if not _is_grounded(baseline):
            return _abstain_like(baseline, "cascade_evidence_contract_failed")
        if not _is_deterministically_valid(candidates.row, baseline):
            return _abstain_like(baseline, "cascade_deterministic_validation_failed")
        return _reconcile(baseline, candidates.reconciliation)

    abstention_reason = "cascade_no_supported_candidate"
    for rule in policy.rules:
        candidate = candidates.candidates.get(rule.arm_id)
        if candidate is None:
            raise CascadePolicyError("frozen cascade candidate is missing")
        if candidate.experiment_id != rule.arm_id:
            raise CascadePolicyError("cascade candidate arm identity mismatch")
        if (candidate.document_id, candidate.row_id) != (
            baseline.document_id,
            baseline.row_id,
        ):
            raise CascadePolicyError("cascade candidate row identity mismatch")
        if candidate.decision is not Decision.ACCEPT:
            continue
        if candidate.exact_row_confidence is None:
            return _abstain_like(baseline, "cascade_uncalibrated_candidate")
        if Decimal(str(candidate.exact_row_confidence)) < rule.minimum_confidence:
            abstention_reason = "cascade_below_confidence_threshold"
            continue
        if not _is_grounded(candidate):
            return _abstain_like(baseline, "cascade_evidence_contract_failed")
        if not _is_deterministically_valid(candidates.row, candidate):
            return _abstain_like(baseline, "cascade_deterministic_validation_failed")
        candidate_signature = _resolved_signature(candidate)
        agreement_failed = False
        for agreement_arm_id in rule.requires_agreement:
            agreement = candidates.candidates.get(agreement_arm_id)
            if agreement is None:
                raise CascadePolicyError("frozen cascade agreement candidate is missing")
            if agreement.experiment_id != agreement_arm_id or (
                agreement.document_id,
                agreement.row_id,
            ) != (baseline.document_id, baseline.row_id):
                raise CascadePolicyError("cascade agreement candidate identity mismatch")
            if (
                agreement.decision is not Decision.ACCEPT
                or not _is_grounded(agreement)
                or not _is_deterministically_valid(candidates.row, agreement)
                or _resolved_signature(agreement) != candidate_signature
            ):
                agreement_failed = True
                break
        if agreement_failed:
            return _abstain_like(baseline, "cascade_required_agreement_failed")
        return _reconcile(candidate, candidates.reconciliation)
    return _abstain_like(baseline, abstention_reason)


def _policy_identity(policy: CascadePolicy) -> tuple[object, ...]:
    return tuple(
        (rule.arm_id, str(rule.minimum_confidence), rule.requires_agreement)
        for rule in policy.rules
    )


def _selected_arm(prediction: RowPrediction) -> str | None:
    if prediction.decision is not Decision.ACCEPT:
        return None
    return prediction.experiment_id


def select_cascade_policy(validation: CascadeValidation) -> CascadePolicy:
    """Choose among predeclared policies using validation outcomes only."""

    if any(row.candidates.row.split is not DatasetSplit.VALIDATION for row in validation.rows):
        raise CascadePolicyError("cascade policy selection requires validation split rows")
    empty_policy = CascadePolicy(version=validation.version, rules=())
    policies_by_identity = {
        _policy_identity(policy): policy
        for policy in (empty_policy, *validation.candidate_policies)
    }
    ranked: list[tuple[tuple[object, ...], CascadePolicy]] = []
    for policy_identity, policy in policies_by_identity.items():
        if policy.version != validation.version:
            raise CascadePolicyError("candidate policy version mismatch")
        referenced_arms = {
            arm_id for rule in policy.rules for arm_id in (rule.arm_id, *rule.requires_agreement)
        }
        if any(validation.deterministic_arms.get(arm_id) is not True for arm_id in referenced_arms):
            continue

        incremental_exact = 0
        accepted_row_errors = 0
        required_field_errors = 0
        omissions = 0
        latency_ns = 0
        for row in validation.rows:
            selected = apply_cascade(policy, row.candidates)
            arm_id = _selected_arm(selected)
            if arm_id is None:
                continue
            if arm_id not in row.exact_outcomes:
                raise CascadePolicyError("validation row lacks selected-arm outcome")
            baseline_exact = row.exact_outcomes["accepted-baseline"]
            if arm_id != "accepted-baseline" and row.exact_outcomes[arm_id] and not baseline_exact:
                incremental_exact += 1
            if arm_id in row.accepted_row_error_arms:
                accepted_row_errors += 1
            if arm_id in row.required_field_error_arms:
                required_field_errors += 1
            omissions += row.omission_counts.get(arm_id, 0)
            latency_ns += row.latency_ns.get(arm_id, 0)

        if (
            accepted_row_errors > validation.maximum_accepted_row_errors
            or required_field_errors > validation.maximum_required_field_errors
        ):
            continue
        rank = (
            -incremental_exact,
            accepted_row_errors,
            required_field_errors,
            omissions,
            latency_ns,
            len(policy.rules),
            policy_identity,
        )
        ranked.append((rank, policy))

    if not ranked:
        return empty_policy
    return min(ranked, key=lambda item: item[0])[1]


__all__ = [
    "CascadeCandidates",
    "CascadePolicy",
    "CascadePolicyError",
    "CascadeRule",
    "CascadeValidation",
    "CascadeValidationRow",
    "ReconciliationAdapter",
    "apply_cascade",
    "select_cascade_policy",
]
