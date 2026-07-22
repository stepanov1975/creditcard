from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, localcontext

import pytest

from ccparser.models import (
    PrintedTotal,
    ReconciliationGroup,
    StatementResult,
    Status,
    Transaction,
    TransactionKind,
)
from ccparser.reconcile import reconcile


@dataclass(frozen=True)
class _ReconciliationOutcomeCase:
    name: str
    transactions: tuple[Transaction, ...]
    printed_totals: tuple[PrintedTotal, ...]
    expected_status: Status
    accepted_indices: tuple[int, ...]
    rejected: tuple[tuple[str, int, str], ...]
    expected_groups: tuple[ReconciliationGroup, ...]
    expected_diagnostics: tuple[str, ...]


def _matrix_transaction(
    transaction_id: str,
    amount: str,
    *,
    group_ids: tuple[str, ...] = ("card-1",),
    currency: str = "ILS",
    ambiguities: tuple[str, ...] = (),
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal(amount),
        billing_currency=currency,
        reconciliation_group_ids=group_ids,
        ambiguities=ambiguities,
    )


def _matrix_total(
    amount: str,
    *,
    group_id: str = "card-1",
    currency: str = "ILS",
) -> PrintedTotal:
    return PrintedTotal(
        group_id=group_id,
        amount=Decimal(amount),
        currency=currency,
    )


def _matrix_group(
    *,
    printed_total: str,
    calculated_total: str,
    difference: str,
    transaction_ids: tuple[str, ...],
    currency: str = "ILS",
    status: Status = Status.RECONCILED,
    diagnostics: tuple[str, ...] = (),
) -> ReconciliationGroup:
    return ReconciliationGroup(
        group_id="card-1",
        currency=currency,
        printed_total=Decimal(printed_total),
        calculated_total=Decimal(calculated_total),
        difference=Decimal(difference),
        transaction_ids=transaction_ids,
        status=status,
        diagnostics=diagnostics,
    )


_ORDERED_ACCEPTED_TRANSACTIONS = (
    _matrix_transaction("order-z", "1.00"),
    _matrix_transaction("order-a", "2.00"),
)
_ORDERED_ACCEPTED_GROUP = _matrix_group(
    printed_total="3.00",
    calculated_total="3.00",
    difference="0.00",
    transaction_ids=("order-a", "order-z"),
)


@pytest.mark.parametrize(
    "case",
    (
        _ReconciliationOutcomeCase(
            name="duplicate_transaction_ids",
            transactions=(
                _matrix_transaction("duplicate", "1.00"),
                _matrix_transaction("duplicate", "9.00"),
                _matrix_transaction("accepted-after", "2.00"),
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0, 2),
            rejected=(("duplicate", 1, "duplicate transaction id 'duplicate'"),),
            expected_groups=(
                _matrix_group(
                    printed_total="3.00",
                    calculated_total="3.00",
                    difference="0.00",
                    transaction_ids=("accepted-after", "duplicate"),
                ),
            ),
            expected_diagnostics=("duplicate transaction id 'duplicate'",),
        ),
        _ReconciliationOutcomeCase(
            name="duplicate_id_after_rejected_occurrence",
            transactions=(
                _matrix_transaction("duplicate", "1.00", group_ids=()),
                _matrix_transaction("duplicate", "9.00"),
                _matrix_transaction("accepted-after", "3.00"),
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(2,),
            rejected=(
                (
                    "duplicate",
                    0,
                    "transaction 'duplicate' must belong to exactly one "
                    "reconciliation group; found 0",
                ),
                ("duplicate", 1, "duplicate transaction id 'duplicate'"),
            ),
            expected_groups=(
                _matrix_group(
                    printed_total="3.00",
                    calculated_total="3.00",
                    difference="0.00",
                    transaction_ids=("accepted-after",),
                ),
            ),
            expected_diagnostics=(
                "transaction 'duplicate' must belong to exactly one reconciliation group; found 0",
                "duplicate transaction id 'duplicate'",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="zero_group_memberships",
            transactions=(
                _ORDERED_ACCEPTED_TRANSACTIONS[0],
                _matrix_transaction("unassigned", "5.00", group_ids=()),
                _ORDERED_ACCEPTED_TRANSACTIONS[1],
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0, 2),
            rejected=(
                (
                    "unassigned",
                    1,
                    "transaction 'unassigned' must belong to exactly one "
                    "reconciliation group; found 0",
                ),
            ),
            expected_groups=(_ORDERED_ACCEPTED_GROUP,),
            expected_diagnostics=(
                "transaction 'unassigned' must belong to exactly one reconciliation group; found 0",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="multiple_group_memberships",
            transactions=(
                _ORDERED_ACCEPTED_TRANSACTIONS[0],
                _matrix_transaction(
                    "multiply-assigned",
                    "5.00",
                    group_ids=("card-1", "card-2"),
                ),
                _ORDERED_ACCEPTED_TRANSACTIONS[1],
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0, 2),
            rejected=(
                (
                    "multiply-assigned",
                    1,
                    "transaction 'multiply-assigned' must belong to exactly one "
                    "reconciliation group; found 2",
                ),
            ),
            expected_groups=(_ORDERED_ACCEPTED_GROUP,),
            expected_diagnostics=(
                "transaction 'multiply-assigned' must belong to exactly one "
                "reconciliation group; found 2",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="unknown_group",
            transactions=(
                _ORDERED_ACCEPTED_TRANSACTIONS[0],
                _matrix_transaction("unknown-group", "5.00", group_ids=("missing",)),
                _ORDERED_ACCEPTED_TRANSACTIONS[1],
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0, 2),
            rejected=(
                (
                    "unknown-group",
                    1,
                    "transaction 'unknown-group' references unknown reconciliation group 'missing'",
                ),
            ),
            expected_groups=(_ORDERED_ACCEPTED_GROUP,),
            expected_diagnostics=(
                "transaction 'unknown-group' references unknown reconciliation group 'missing'",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="currency_mismatch",
            transactions=(_matrix_transaction("wrong-currency", "3.00", currency="USD"),),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0,),
            rejected=(),
            expected_groups=(
                _matrix_group(
                    printed_total="3.00",
                    calculated_total="3.00",
                    difference="0.00",
                    transaction_ids=("wrong-currency",),
                    status=Status.UNRECONCILED,
                    diagnostics=(
                        "transaction 'wrong-currency' currency USD does not match "
                        "group currency ILS",
                    ),
                ),
            ),
            expected_diagnostics=(
                "transaction 'wrong-currency' currency USD does not match group currency ILS",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="transaction_ambiguity",
            transactions=(
                _matrix_transaction(
                    "ambiguous-row",
                    "3.00",
                    ambiguities=("two billing-amount candidates",),
                ),
            ),
            printed_totals=(_matrix_total("3.00"),),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0,),
            rejected=(),
            expected_groups=(
                _matrix_group(
                    printed_total="3.00",
                    calculated_total="3.00",
                    difference="0.00",
                    transaction_ids=("ambiguous-row",),
                    status=Status.UNRECONCILED,
                    diagnostics=(
                        "transaction 'ambiguous-row' has unresolved ambiguity: "
                        "two billing-amount candidates",
                    ),
                ),
            ),
            expected_diagnostics=(
                "transaction 'ambiguous-row' has unresolved ambiguity: "
                "two billing-amount candidates",
            ),
        ),
        _ReconciliationOutcomeCase(
            name="duplicate_totals",
            transactions=(_matrix_transaction("accepted", "3.00"),),
            printed_totals=(_matrix_total("3.00"), _matrix_total("4.00", currency="USD")),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(0,),
            rejected=(),
            expected_groups=(
                _matrix_group(
                    printed_total="3.00",
                    calculated_total="3.00",
                    difference="0.00",
                    transaction_ids=("accepted",),
                ),
                _matrix_group(
                    printed_total="4.00",
                    calculated_total="3.00",
                    difference="-1.00",
                    transaction_ids=("accepted",),
                    currency="USD",
                    status=Status.UNRECONCILED,
                ),
            ),
            expected_diagnostics=("duplicate printed total group id 'card-1'",),
        ),
        _ReconciliationOutcomeCase(
            name="no_totals",
            transactions=(_matrix_transaction("no-total", "3.00"),),
            printed_totals=(),
            expected_status=Status.UNRECONCILED,
            accepted_indices=(),
            rejected=(
                (
                    "no-total",
                    0,
                    "transaction 'no-total' references unknown reconciliation group 'card-1'",
                ),
            ),
            expected_groups=(),
            expected_diagnostics=(
                "no printed reconciliation totals found",
                "transaction 'no-total' references unknown reconciliation group 'card-1'",
            ),
        ),
    ),
    ids=lambda case: case.name,
)
def test_reconciliation_outcome_preserves_rejected_membership_matrix(
    case: _ReconciliationOutcomeCase,
) -> None:
    from ccparser.reconcile import reconciliation_outcome

    expected_transactions = tuple(case.transactions[index] for index in case.accepted_indices)
    expected_public_result = StatementResult(
        status=case.expected_status,
        transactions=expected_transactions,
        groups=case.expected_groups,
        diagnostics=case.expected_diagnostics,
    )

    assert reconcile(case.transactions, case.printed_totals) == expected_public_result

    outcome = reconciliation_outcome(case.transactions, case.printed_totals)

    assert outcome.status is case.expected_status
    assert outcome.accepted_transaction_indices == case.accepted_indices
    assert outcome.accepted_transaction_ids == tuple(
        transaction.transaction_id for transaction in expected_transactions
    )
    assert (
        tuple(
            (rejected.transaction_id, rejected.input_index, rejected.diagnostic)
            for rejected in outcome.rejected_transactions
        )
        == case.rejected
    )
    assert outcome.groups == case.expected_groups
    assert outcome.diagnostics == case.expected_diagnostics


class _SingleUseIterable[T]:
    def __init__(self, values: tuple[T, ...]) -> None:
        self._values = values
        self.iterations = 0

    def __iter__(self) -> Iterator[T]:
        if self.iterations:
            raise AssertionError("input iterable was materialized more than once")
        self.iterations += 1
        yield from self._values


def test_reconciliation_outcome_and_public_wrapper_materialize_inputs_once() -> None:
    from ccparser.reconcile import reconciliation_outcome

    transaction = _matrix_transaction("accepted", "3.00")
    printed_total = _matrix_total("3.00")
    outcome_transactions = _SingleUseIterable((transaction,))
    outcome_totals = _SingleUseIterable((printed_total,))

    outcome = reconciliation_outcome(outcome_transactions, outcome_totals)

    assert outcome.accepted_transaction_indices == (0,)
    assert outcome_transactions.iterations == 1
    assert outcome_totals.iterations == 1

    public_transactions = _SingleUseIterable((transaction,))
    public_totals = _SingleUseIterable((printed_total,))

    result = reconcile(public_transactions, public_totals)

    assert result.transactions == (transaction,)
    assert public_transactions.iterations == 1
    assert public_totals.iterations == 1


def test_reconcile_assigns_transactions_to_multiple_groups() -> None:
    try:
        from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
        from ccparser.reconcile import reconcile
    except ImportError as exc:
        pytest.fail(f"reconciliation is not implemented: {exc}")

    transactions = (
        Transaction(
            transaction_id="card-2-charge",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("7.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("card-2",),
        ),
        Transaction(
            transaction_id="card-1-charge",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("10.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("card-1",),
        ),
    )
    printed_totals = (
        PrintedTotal(group_id="card-2", amount=Decimal("7.00"), currency="ILS"),
        PrintedTotal(group_id="card-1", amount=Decimal("10.00"), currency="ILS"),
    )

    result = reconcile(transactions, printed_totals)

    assert result.status is Status.RECONCILED
    assert tuple(group.group_id for group in result.groups) == ("card-1", "card-2")
    assert result.groups[0].transaction_ids == ("card-1-charge",)
    assert result.groups[1].transaction_ids == ("card-2-charge",)


def test_reconcile_uses_exact_decimal_totals_at_the_currency_minor_unit() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    exact = reconcile(
        (
            Transaction(
                transaction_id="one-tenth",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("0.10"),
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
            ),
            Transaction(
                transaction_id="two-tenths",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("0.20"),
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
            ),
        ),
        (
            PrintedTotal(
                group_id="card-1",
                amount=Decimal("0.30"),
                currency="ILS",
                minor_unit=Decimal("0.01"),
            ),
        ),
    )

    assert exact.status is Status.RECONCILED
    assert exact.groups[0].calculated_total == Decimal("0.30")
    assert exact.groups[0].difference == Decimal("0.00")

    below_minor_unit = reconcile(
        (
            Transaction(
                transaction_id="fractional-agora",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("0.101"),
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
            ),
        ),
        (
            PrintedTotal(
                group_id="card-1",
                amount=Decimal("0.101"),
                currency="ILS",
                minor_unit=Decimal("0.01"),
            ),
        ),
    )

    assert below_minor_unit.status is Status.UNRECONCILED
    assert "currency minor unit" in below_minor_unit.groups[0].diagnostics[0]


def test_reconcile_preserves_transactions_when_cycle_total_disagrees() -> None:
    """A source-level mismatch must stay explicit instead of triggering guesses."""

    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    transactions = (
        Transaction(
            transaction_id="first-charge",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("4.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("cycle",),
        ),
        Transaction(
            transaction_id="second-charge",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("6.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("cycle",),
        ),
    )

    result = reconcile(
        transactions,
        (PrintedTotal(group_id="cycle", amount=Decimal("12.00"), currency="ILS"),),
    )

    assert result.status is Status.UNRECONCILED
    assert result.transactions == transactions
    assert len(result.groups) == 1
    assert result.groups[0].status is Status.UNRECONCILED
    assert result.groups[0].calculated_total == Decimal("10.00")
    assert result.groups[0].printed_total == Decimal("12.00")
    assert result.groups[0].difference == Decimal("-2.00")
    assert result.groups[0].transaction_ids == ("first-charge", "second-charge")


@pytest.mark.parametrize(
    ("group_ids", "membership_count"),
    [
        ((), 0),
        (("card-1", "card-2"), 2),
    ],
)
def test_reconcile_fails_when_membership_is_not_exactly_one_group(
    group_ids: tuple[str, ...], membership_count: int
) -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    result = reconcile(
        (
            Transaction(
                transaction_id="unassigned",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("5.00"),
                billing_currency="ILS",
                reconciliation_group_ids=group_ids,
            ),
        ),
        (
            PrintedTotal(
                group_id="card-1",
                amount=Decimal("0.00"),
                currency="ILS",
            ),
            PrintedTotal(
                group_id="card-2",
                amount=Decimal("0.00"),
                currency="ILS",
            ),
        ),
    )

    assert result.status is Status.UNRECONCILED
    assert result.diagnostics == (
        "transaction 'unassigned' must belong to exactly one reconciliation group; "
        f"found {membership_count}",
    )
    assert result.transactions == ()


def test_reconcile_reports_ambiguity_even_when_amounts_balance() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    result = reconcile(
        (
            Transaction(
                transaction_id="ambiguous-row",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("5.00"),
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
                ambiguities=("two billing-amount candidates",),
            ),
        ),
        (
            PrintedTotal(
                group_id="card-1",
                amount=Decimal("5.00"),
                currency="ILS",
            ),
        ),
    )

    assert result.status is Status.UNRECONCILED
    assert result.groups[0].status is Status.UNRECONCILED
    assert result.diagnostics == (
        "transaction 'ambiguous-row' has unresolved ambiguity: two billing-amount candidates",
    )


def test_reconcile_rejects_unknown_group_and_currency_mismatch() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    result = reconcile(
        (
            Transaction(
                transaction_id="unknown-group",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("5.00"),
                billing_currency="ILS",
                reconciliation_group_ids=("missing",),
            ),
            Transaction(
                transaction_id="wrong-currency",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("7.00"),
                billing_currency="USD",
                reconciliation_group_ids=("card-1",),
            ),
        ),
        (PrintedTotal(group_id="card-1", amount=Decimal("7.00"), currency="ILS"),),
    )

    assert result.status is Status.UNRECONCILED
    assert any("unknown reconciliation group 'missing'" in item for item in result.diagnostics)
    assert any(
        "currency USD does not match group currency ILS" in item for item in result.diagnostics
    )
    assert tuple(item.transaction_id for item in result.transactions) == ("wrong-currency",)
    assert result.groups[0].status is Status.UNRECONCILED
    assert any("currency USD does not match" in item for item in result.groups[0].diagnostics)


def test_reconcile_rejects_duplicate_transaction_and_total_identifiers() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    transaction = Transaction(
        transaction_id="duplicate",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("card-1",),
    )
    result = reconcile(
        (transaction, transaction),
        (
            PrintedTotal(group_id="card-1", amount=Decimal("2.00"), currency="ILS"),
            PrintedTotal(group_id="card-1", amount=Decimal("2.00"), currency="ILS"),
        ),
    )

    assert result.status is Status.UNRECONCILED
    assert "duplicate transaction id 'duplicate'" in result.diagnostics
    assert "duplicate printed total group id 'card-1'" in result.diagnostics
    assert tuple(item.transaction_id for item in result.transactions) == ("duplicate",)


def test_reconcile_requires_at_least_one_printed_total() -> None:
    from ccparser.models import Status
    from ccparser.reconcile import reconcile

    result = reconcile((), ())

    assert result.status is Status.UNRECONCILED
    assert result.diagnostics == ("no printed reconciliation totals found",)


def test_reconcile_arithmetic_is_independent_of_decimal_context() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    with localcontext() as context:
        context.prec = 5
        result = reconcile(
            (
                Transaction(
                    transaction_id="large",
                    kind=TransactionKind.CHARGE,
                    billed_amount=Decimal("1234.56"),
                    billing_currency="ILS",
                    reconciliation_group_ids=("card-1",),
                ),
                Transaction(
                    transaction_id="small",
                    kind=TransactionKind.CHARGE,
                    billed_amount=Decimal("0.01"),
                    billing_currency="ILS",
                    reconciliation_group_ids=("card-1",),
                ),
            ),
            (PrintedTotal(group_id="card-1", amount=Decimal("1234.57"), currency="ILS"),),
        )

    assert result.status is Status.RECONCILED
    assert result.groups[0].calculated_total == Decimal("1234.57")


def test_reconcile_preserves_amounts_larger_than_default_context() -> None:
    from ccparser.models import PrintedTotal, Status, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    amount = Decimal("123456789012345678901234567890.12")
    result = reconcile(
        (
            Transaction(
                transaction_id="very-large",
                kind=TransactionKind.CHARGE,
                billed_amount=amount,
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
            ),
        ),
        (PrintedTotal(group_id="card-1", amount=amount, currency="ILS"),),
    )

    assert result.status is Status.RECONCILED
    assert result.groups[0].calculated_total == amount
