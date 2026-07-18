from decimal import Decimal

import pytest
from pydantic import ValidationError


def test_transaction_enforces_charge_and_credit_sign_conventions() -> None:
    try:
        from ccparser.models import Transaction, TransactionKind
    except ImportError as exc:
        pytest.fail(f"transaction models are not implemented: {exc}")

    charge = Transaction(
        transaction_id="charge-1",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("12.34"),
        billing_currency="ILS",
        reconciliation_group_ids=("card-1",),
    )
    credit = Transaction(
        transaction_id="credit-1",
        kind=TransactionKind.CREDIT,
        billed_amount=Decimal("-2.34"),
        billing_currency="ILS",
        reconciliation_group_ids=("card-1",),
    )

    assert charge.billed_amount == Decimal("12.34")
    assert credit.billed_amount == Decimal("-2.34")
    with pytest.raises(ValueError, match="charge amount must be positive"):
        Transaction(
            transaction_id="charge-wrong-sign",
            kind=TransactionKind.CHARGE,
            billed_amount=Decimal("-1.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("card-1",),
        )
    with pytest.raises(ValueError, match="credit amount must be negative"):
        Transaction(
            transaction_id="credit-wrong-sign",
            kind=TransactionKind.CREDIT,
            billed_amount=Decimal("1.00"),
            billing_currency="ILS",
            reconciliation_group_ids=("card-1",),
        )


def test_evidence_reference_is_immutable_and_retains_raw_text() -> None:
    try:
        from ccparser.models import EvidenceReference
    except ImportError as exc:
        pytest.fail(f"evidence model is not implemented: {exc}")

    evidence = EvidenceReference(
        page_number=2,
        bbox=(10.0, 20.0, 30.0, 40.0),
        raw_text="  שלום  ",
    )

    assert evidence.raw_text == "  שלום  "
    with pytest.raises(ValidationError, match="frozen"):
        evidence.raw_text = "changed"


def test_monetary_serialization_is_canonical_and_stable() -> None:
    from ccparser.models import PrintedTotal, Transaction, TransactionKind
    from ccparser.reconcile import reconcile

    result = reconcile(
        (
            Transaction(
                transaction_id="scientific-input",
                kind=TransactionKind.CHARGE,
                billed_amount=Decimal("1E+2"),
                billing_currency="ILS",
                reconciliation_group_ids=("card-1",),
            ),
        ),
        (
            PrintedTotal(
                group_id="card-1",
                amount=Decimal("100.00"),
                currency="ILS",
            ),
        ),
    )

    payload = result.model_dump(mode="json")

    assert payload["transactions"][0]["billed_amount"] == "100"
    assert payload["groups"][0]["printed_total"] == "100"
    assert payload["groups"][0]["calculated_total"] == "100"
    assert payload["groups"][0]["difference"] == "0"
    assert result.model_dump_json() == result.model_dump_json()


def test_batch_result_is_immutable_and_uses_public_statuses() -> None:
    try:
        from ccparser.models import BatchResult, StatementResult, Status
    except ImportError as exc:
        pytest.fail(f"batch result model is not implemented: {exc}")

    statement = StatementResult(
        status=Status.UNSUPPORTED,
        transactions=(),
        groups=(),
        diagnostics=("unknown layout",),
    )
    batch = BatchResult(status=Status.UNSUPPORTED, statements=(statement,))

    assert batch.statements == (statement,)
    with pytest.raises(ValidationError, match="frozen"):
        batch.status = Status.RECONCILED
