from decimal import Decimal, localcontext

import pytest


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
