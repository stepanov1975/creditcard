"""Resolve field proposals exclusively from their prediction evidence ledger."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Never

from ccparser.decimal_math import finite_decimal, plain_decimal_string
from ccparser.models import TransactionKind
from ccparser.money import canonical_currency, currencies_in_text, parse_amount
from ccparser.normalization_dates import _parse_date
from ccparser.normalization_fields import _parse_installment
from ccparser.text_tokens import normalize_text
from experiments.row_extraction.contracts import (
    EvidenceAtom,
    FieldProposal,
    FieldRole,
    RowPrediction,
    _FrozenModel,
)


class EvidenceContractError(ValueError):
    """A proposal cannot be resolved exactly from its declared evidence."""


class ResolvedField(_FrozenModel):
    """One canonical field value with its exact supporting atom IDs."""

    role: FieldRole
    canonical_value: str
    atom_ids: tuple[str, ...]


def prediction_ledger(prediction: RowPrediction) -> dict[str, EvidenceAtom]:
    """Return the self-contained atom ledger carried by one prediction."""

    return {atom.atom_id: atom for atom in prediction.evidence_atoms}


def render_proposal(prediction: RowPrediction, proposal: FieldProposal) -> str:
    """Render only the proposal's declared atoms, preserving their declared order."""

    ledger = prediction_ledger(prediction)
    try:
        atoms = tuple(ledger[atom_id] for atom_id in proposal.atom_ids)
    except KeyError as error:
        raise EvidenceContractError("missing evidence atom") from error
    if len(atoms) != len(set(proposal.atom_ids)):
        raise EvidenceContractError("duplicate proposal evidence atom")
    return " ".join(atom.text for atom in atoms)


def _invalid_value() -> Never:
    raise EvidenceContractError("invalid or nonunique proposal value")


def _currency_value(rendered: str) -> str:
    currency = canonical_currency(rendered)
    if currency is None:
        _invalid_value()
    return currency


def _currency_hint(
    prediction: RowPrediction,
    currency_role: FieldRole,
    owner_row_id: str,
) -> str:
    proposals = tuple(
        proposal
        for proposal in prediction.proposals
        if proposal.role is currency_role
        and (proposal.owner_row_id or prediction.row_id) == owner_row_id
    )
    if len(proposals) != 1:
        _invalid_value()
    return _currency_value(render_proposal(prediction, proposals[0]))


def _amount_value(
    prediction: RowPrediction,
    proposal: FieldProposal,
    rendered: str,
    currency_role: FieldRole,
) -> Decimal:
    currency_hint = None
    if not currencies_in_text(rendered):
        currency_hint = _currency_hint(
            prediction,
            currency_role,
            proposal.owner_row_id or prediction.row_id,
        )
    parsed = parse_amount(rendered, currency_hint=currency_hint)
    if parsed.diagnostics or parsed.amount is None:
        _invalid_value()
    return parsed.amount


def _date_value(rendered: str) -> str:
    parsed, diagnostic = _parse_date(rendered, None)
    if parsed is None or diagnostic is not None:
        _invalid_value()
    return parsed.isoformat()


def _decimal_value(rendered: str) -> Decimal:
    try:
        return finite_decimal(Decimal(normalize_text(rendered)))
    except (InvalidOperation, ValueError):
        _invalid_value()


def _kind_amount(
    prediction: RowPrediction,
    proposal: FieldProposal,
    rendered: str,
) -> Decimal:
    try:
        return _decimal_value(rendered)
    except EvidenceContractError:
        return _amount_value(prediction, proposal, rendered, FieldRole.BILLING_CURRENCY)


def _canonical_value(
    prediction: RowPrediction,
    proposal: FieldProposal,
    rendered: str,
) -> str:
    role = proposal.role
    if role in {FieldRole.DESCRIPTION, FieldRole.ANCILLARY}:
        value = normalize_text(rendered)
        if not value:
            _invalid_value()
        return value
    if role in {
        FieldRole.TRANSACTION_DATE,
        FieldRole.POSTING_DATE,
        FieldRole.CONVERSION_DATE,
    }:
        return _date_value(rendered)
    if role in {FieldRole.BILLING_CURRENCY, FieldRole.ORIGINAL_CURRENCY}:
        return _currency_value(rendered)
    if role is FieldRole.INSTALLMENT:
        installment = _parse_installment(rendered)
        if installment is None:
            _invalid_value()
        current, total = installment
        return f"{current}/{total}"
    if role is FieldRole.BILLED_AMOUNT:
        return plain_decimal_string(
            _amount_value(prediction, proposal, rendered, FieldRole.BILLING_CURRENCY)
        )
    if role is FieldRole.ORIGINAL_AMOUNT:
        return plain_decimal_string(
            _amount_value(prediction, proposal, rendered, FieldRole.ORIGINAL_CURRENCY)
        )
    if role is FieldRole.KIND:
        amount = _kind_amount(prediction, proposal, rendered)
        if amount == 0:
            _invalid_value()
        return TransactionKind.CREDIT.value if amount < 0 else TransactionKind.CHARGE.value
    if role is FieldRole.FX_RATE:
        return plain_decimal_string(_decimal_value(rendered))
    _invalid_value()


def resolve_proposal(
    prediction: RowPrediction,
    proposal: FieldProposal,
) -> ResolvedField:
    """Resolve a proposal without consulting or repairing evidence outside its ledger."""

    rendered = render_proposal(prediction, proposal)
    return ResolvedField(
        role=proposal.role,
        canonical_value=_canonical_value(prediction, proposal, rendered),
        atom_ids=proposal.atom_ids,
    )
