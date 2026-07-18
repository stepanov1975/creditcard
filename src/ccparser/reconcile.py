"""Exact statement-total reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from ccparser.models import (
    PrintedTotal,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
)


def _integer_coefficient(value: Decimal) -> tuple[int, int]:
    """Return an exact signed coefficient and base-10 exponent."""

    if not value.is_finite():
        raise ValueError("financial values must be finite")
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise ValueError("financial values must have a finite exponent")
    coefficient = 0
    for digit in parts.digits:
        coefficient = coefficient * 10 + digit
    if parts.sign:
        coefficient = -coefficient
    return coefficient, parts.exponent


def _decimal_from_coefficient(coefficient: int, exponent: int) -> Decimal:
    """Construct a Decimal exactly without consulting the active context."""

    digits = tuple(int(character) for character in str(abs(coefficient)))
    return Decimal((int(coefficient < 0), digits, exponent))


def _exact_sum(values: Iterable[Decimal]) -> Decimal:
    """Sum finite Decimals exactly, independent of context precision."""

    parts = tuple(_integer_coefficient(value) for value in values)
    if not parts:
        return Decimal("0")
    common_exponent = min(exponent for _, exponent in parts)
    coefficient = sum(value * 10 ** (exponent - common_exponent) for value, exponent in parts)
    return _decimal_from_coefficient(coefficient, common_exponent)


def _is_exact_multiple(value: Decimal, unit: Decimal) -> bool:
    """Return whether value is an exact multiple of unit without Decimal division."""

    value_coefficient, value_exponent = _integer_coefficient(value)
    unit_coefficient, unit_exponent = _integer_coefficient(unit)
    common_exponent = min(value_exponent, unit_exponent)
    scaled_value = value_coefficient * 10 ** (value_exponent - common_exponent)
    scaled_unit = unit_coefficient * 10 ** (unit_exponent - common_exponent)
    remainder: int = scaled_value % scaled_unit
    return remainder == 0


def reconcile(
    transactions: Iterable[Transaction],
    printed_totals: Iterable[PrintedTotal],
) -> StatementResult:
    """Reconcile transaction groups against their corresponding printed totals."""

    transaction_tuple = tuple(transactions)
    printed_total_tuple = tuple(printed_totals)
    members: dict[str, list[Transaction]] = defaultdict(list)
    group_diagnostics: dict[str, list[str]] = defaultdict(list)
    emitted_transactions: list[Transaction] = []
    statement_diagnostics = []
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
    for transaction in transaction_tuple:
        if transaction.transaction_id in seen_transaction_ids:
            statement_diagnostics.append(f"duplicate transaction id {transaction.transaction_id!r}")
            continue
        seen_transaction_ids.add(transaction.transaction_id)
        for ambiguity in transaction.ambiguities:
            statement_diagnostics.append(
                f"transaction {transaction.transaction_id!r} has unresolved ambiguity: {ambiguity}"
            )
        membership_count = len(transaction.reconciliation_group_ids)
        if membership_count != 1:
            statement_diagnostics.append(
                f"transaction {transaction.transaction_id!r} must belong to exactly "
                f"one reconciliation group; found {membership_count}"
            )
            continue
        group_id = transaction.reconciliation_group_ids[0]
        matched_total = total_by_group.get(group_id)
        if matched_total is None:
            statement_diagnostics.append(
                f"transaction {transaction.transaction_id!r} references unknown "
                f"reconciliation group {group_id!r}"
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
        emitted_transactions.append(transaction)

    groups = []
    for printed_total in sorted(printed_total_tuple, key=lambda total: total.group_id):
        group_transactions = members[printed_total.group_id]
        calculated_total = _exact_sum(
            transaction.billed_amount for transaction in group_transactions
        )
        diagnostics = list(group_diagnostics[printed_total.group_id])
        if not _is_exact_multiple(printed_total.amount, printed_total.minor_unit):
            diagnostics.append(
                f"printed total is not representable at currency minor unit "
                f"{printed_total.minor_unit}"
            )
        for transaction in group_transactions:
            if not _is_exact_multiple(transaction.billed_amount, printed_total.minor_unit):
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
                difference=_exact_sum((calculated_total, printed_total.amount.copy_negate())),
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
    return StatementResult(
        status=statement_status,
        transactions=tuple(emitted_transactions),
        groups=tuple(groups),
        diagnostics=tuple(statement_diagnostics),
    )
