"""Exact statement-total reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from ccparser.decimal_math import exact_difference, exact_sum, is_exact_multiple
from ccparser.models import (
    PrintedTotal,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
)


class RejectedTransaction(BaseModel):
    """One input transaction occurrence skipped by reconciliation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str
    input_index: int = Field(ge=0)
    diagnostic: str


class ReconciliationOutcome(BaseModel):
    """Internal exact reconciliation state without a partial public result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Status
    accepted_transaction_ids: tuple[str, ...]
    accepted_transaction_indices: tuple[int, ...]
    rejected_transactions: tuple[RejectedTransaction, ...]
    groups: tuple[ReconciliationGroup, ...]
    diagnostics: tuple[str, ...]


def _reconciliation_outcome(
    transaction_tuple: tuple[Transaction, ...],
    printed_total_tuple: tuple[PrintedTotal, ...],
) -> ReconciliationOutcome:
    """Reconcile already-materialized inputs while retaining occurrence membership."""

    members: dict[str, list[Transaction]] = defaultdict(list)
    group_diagnostics: dict[str, list[str]] = defaultdict(list)
    accepted_transaction_ids: list[str] = []
    accepted_transaction_indices: list[int] = []
    rejected_transactions: list[RejectedTransaction] = []
    statement_diagnostics: list[str] = []
    if not printed_total_tuple:
        statement_diagnostics.append("no printed reconciliation totals found")

    total_by_group: dict[str, PrintedTotal] = {}
    for printed_total in printed_total_tuple:
        if printed_total.group_id in total_by_group:
            statement_diagnostics.append(
                f"duplicate printed total group id {printed_total.group_id!r}"
            )
        else:
            total_by_group[printed_total.group_id] = printed_total

    seen_transaction_ids: set[str] = set()
    for input_index, transaction in enumerate(transaction_tuple):
        if transaction.transaction_id in seen_transaction_ids:
            diagnostic = f"duplicate transaction id {transaction.transaction_id!r}"
            statement_diagnostics.append(diagnostic)
            rejected_transactions.append(
                RejectedTransaction(
                    transaction_id=transaction.transaction_id,
                    input_index=input_index,
                    diagnostic=diagnostic,
                )
            )
            continue
        seen_transaction_ids.add(transaction.transaction_id)
        for ambiguity in transaction.ambiguities:
            statement_diagnostics.append(
                f"transaction {transaction.transaction_id!r} has unresolved ambiguity: {ambiguity}"
            )
        membership_count = len(transaction.reconciliation_group_ids)
        if membership_count != 1:
            diagnostic = (
                f"transaction {transaction.transaction_id!r} must belong to exactly "
                f"one reconciliation group; found {membership_count}"
            )
            statement_diagnostics.append(diagnostic)
            rejected_transactions.append(
                RejectedTransaction(
                    transaction_id=transaction.transaction_id,
                    input_index=input_index,
                    diagnostic=diagnostic,
                )
            )
            continue
        group_id = transaction.reconciliation_group_ids[0]
        matched_total = total_by_group.get(group_id)
        if matched_total is None:
            diagnostic = (
                f"transaction {transaction.transaction_id!r} references unknown "
                f"reconciliation group {group_id!r}"
            )
            statement_diagnostics.append(diagnostic)
            rejected_transactions.append(
                RejectedTransaction(
                    transaction_id=transaction.transaction_id,
                    input_index=input_index,
                    diagnostic=diagnostic,
                )
            )
            continue
        if transaction.billing_currency != matched_total.currency:
            diagnostic = (
                f"transaction {transaction.transaction_id!r} currency "
                f"{transaction.billing_currency} does not match group currency "
                f"{matched_total.currency}"
            )
            statement_diagnostics.append(diagnostic)
            group_diagnostics[group_id].append(diagnostic)
        members[group_id].append(transaction)
        accepted_transaction_ids.append(transaction.transaction_id)
        accepted_transaction_indices.append(input_index)

    groups: list[ReconciliationGroup] = []
    for printed_total in sorted(printed_total_tuple, key=lambda total: total.group_id):
        group_transactions = members[printed_total.group_id]
        calculated_total = exact_sum(
            transaction.billed_amount for transaction in group_transactions
        )
        diagnostics = list(group_diagnostics[printed_total.group_id])
        if not is_exact_multiple(printed_total.amount, printed_total.minor_unit):
            diagnostics.append(
                f"printed total is not representable at currency minor unit "
                f"{printed_total.minor_unit}"
            )
        for transaction in group_transactions:
            if not is_exact_multiple(transaction.billed_amount, printed_total.minor_unit):
                diagnostics.append(
                    f"transaction {transaction.transaction_id!r} amount is not "
                    f"representable at currency minor unit {printed_total.minor_unit}"
                )
            for ambiguity in transaction.ambiguities:
                diagnostics.append(
                    f"transaction {transaction.transaction_id!r} has unresolved "
                    f"ambiguity: {ambiguity}"
                )
        status = (
            Status.RECONCILED
            if calculated_total == printed_total.amount and not diagnostics
            else Status.UNRECONCILED
        )
        groups.append(
            ReconciliationGroup(
                group_id=printed_total.group_id,
                currency=printed_total.currency,
                printed_total=printed_total.amount,
                calculated_total=calculated_total,
                difference=exact_difference(calculated_total, printed_total.amount),
                transaction_ids=tuple(
                    sorted(transaction.transaction_id for transaction in group_transactions)
                ),
                status=status,
                diagnostics=tuple(diagnostics),
            )
        )

    statement_status = (
        Status.RECONCILED
        if all(group.status is Status.RECONCILED for group in groups) and not statement_diagnostics
        else Status.UNRECONCILED
    )
    return ReconciliationOutcome(
        status=statement_status,
        accepted_transaction_ids=tuple(accepted_transaction_ids),
        accepted_transaction_indices=tuple(accepted_transaction_indices),
        rejected_transactions=tuple(rejected_transactions),
        groups=tuple(groups),
        diagnostics=tuple(statement_diagnostics),
    )


def reconciliation_outcome(
    transactions: Iterable[Transaction],
    printed_totals: Iterable[PrintedTotal],
) -> ReconciliationOutcome:
    """Return exact internal reconciliation state for materialized input occurrences."""

    return _reconciliation_outcome(tuple(transactions), tuple(printed_totals))


def reconcile(
    transactions: Iterable[Transaction],
    printed_totals: Iterable[PrintedTotal],
) -> StatementResult:
    """Reconcile transaction groups against their corresponding printed totals."""

    transaction_tuple = tuple(transactions)
    outcome = _reconciliation_outcome(transaction_tuple, tuple(printed_totals))
    return StatementResult(
        status=outcome.status,
        transactions=tuple(
            transaction_tuple[index] for index in outcome.accepted_transaction_indices
        ),
        groups=outcome.groups,
        diagnostics=outcome.diagnostics,
    )
