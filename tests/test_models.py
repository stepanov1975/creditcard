import unicodedata
from datetime import date
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from ccparser.models import EvidenceReference


def _fx_evidence(raw_text: str, y: float) -> EvidenceReference:
    return EvidenceReference(
        page_number=1,
        bbox=(10.0, y, 50.0, y + 10.0),
        raw_text=raw_text,
    )


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


def test_monetary_serialization_never_uses_decimal_context_rounding() -> None:
    from ccparser.models import PrintedTotal

    amount = Decimal("123456789012345678901234567890.1200")
    with localcontext() as context:
        context.prec = 5
        payload = PrintedTotal(
            group_id="large",
            amount=amount,
            currency="ILS",
        ).model_dump(mode="json")

    assert payload["amount"] == "123456789012345678901234567890.12"


def test_extended_transaction_fields_are_optional_immutable_and_nfc() -> None:
    from ccparser.models import (
        EvidenceReference,
        Transaction,
        TransactionCategory,
        TransactionKind,
    )

    decomposed = "Cafe\N{COMBINING ACUTE ACCENT}"
    evidence = EvidenceReference(page_number=1, bbox=(1.0, 2.0, 3.0, 4.0), raw_text=decomposed)
    transaction = Transaction(
        transaction_id="group-0001-p001-r0001",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("12.34"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
        transaction_date=date(2026, 2, 1),
        posting_date=date(2026, 2, 2),
        conversion_date=date(2026, 2, 3),
        description=decomposed,
        category=TransactionCategory.PURCHASE,
        original_amount=Decimal("3.25"),
        original_currency="USD",
        installment_current=2,
        installment_total=6,
        evidence=(evidence,),
    )

    assert transaction.description == unicodedata.normalize("NFC", decomposed)
    assert transaction.category is TransactionCategory.PURCHASE
    assert transaction.conversion_date == date(2026, 2, 3)
    assert transaction.evidence == (evidence,)
    assert transaction.model_dump(mode="json")["original_amount"] == "3.25"
    with pytest.raises(ValidationError, match="frozen"):
        transaction.description = "changed"


def test_existing_transaction_constructor_remains_valid_after_extension() -> None:
    from ccparser.models import Transaction, TransactionCategory, TransactionKind

    transaction = Transaction(
        transaction_id="legacy",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("1.00"),
        billing_currency="ILS",
        reconciliation_group_ids=("group-0001",),
    )

    assert transaction.category is TransactionCategory.UNKNOWN
    assert transaction.description is None
    assert transaction.evidence == ()
    assert transaction.foreign_exchange is None


def test_transaction_preserves_evidence_backed_foreign_exchange_details() -> None:
    from ccparser.models import (
        ExtractedDecimal,
        ExtractedMoney,
        ForeignExchangeDetails,
        Transaction,
        TransactionKind,
    )

    rate_evidence = _fx_evidence("exchange rate 2.9430", 10.0)
    fee_evidence = _fx_evidence("fee ILS 0.88", 20.0)
    discount_evidence = _fx_evidence("discount ILS 0.59", 30.0)
    transaction = Transaction(
        transaction_id="fx-1",
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("29.72"),
        billing_currency="ILS",
        original_amount=Decimal("10.00"),
        original_currency="USD",
        reconciliation_group_ids=("group-1",),
        foreign_exchange=ForeignExchangeDetails(
            exchange_rate=ExtractedDecimal(value=Decimal("2.9430"), evidence=(rate_evidence,)),
            fee_percentage=ExtractedDecimal(value=Decimal("3.00"), evidence=(fee_evidence,)),
            gross_fee=ExtractedMoney(
                amount=Decimal("0.88"), currency="ILS", evidence=(fee_evidence,)
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("0.59"), currency="ILS", evidence=(discount_evidence,)
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("0.29"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
                derivation="gross_fee_minus_discount",
            ),
        ),
    )

    payload = transaction.model_dump(mode="json")["foreign_exchange"]
    assert payload is not None
    assert payload["exchange_rate"]["value"] == "2.943"
    assert payload["fee_percentage"]["value"] == "3"
    assert payload["gross_fee"]["amount"] == "0.88"
    assert payload["net_fee"]["amount"] == "0.29"
    assert payload["net_fee"]["derivation"] == "gross_fee_minus_discount"


def test_foreign_exchange_requires_evidence_and_exact_derivation() -> None:
    from ccparser.models import ExtractedDecimal, ExtractedMoney, ForeignExchangeDetails

    fee_evidence = _fx_evidence("fee ILS 0.88", 20.0)
    discount_evidence = _fx_evidence("discount ILS 0.59", 30.0)
    with pytest.raises(ValidationError, match="at least 1 item"):
        ExtractedDecimal(value=Decimal("2.9430"), evidence=())
    with pytest.raises(ValueError, match="at least one FX value"):
        ForeignExchangeDetails()
    with pytest.raises(ValueError, match="exact gross fee minus discount"):
        ForeignExchangeDetails(
            gross_fee=ExtractedMoney(
                amount=Decimal("0.88"), currency="ILS", evidence=(fee_evidence,)
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("0.59"), currency="ILS", evidence=(discount_evidence,)
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("0.30"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
                derivation="gross_fee_minus_discount",
            ),
        )


@pytest.mark.parametrize("nonfinite", ("NaN", "Infinity", "-Infinity"))
def test_every_financial_model_rejects_nonfinite_decimals(nonfinite: str) -> None:
    from ccparser.models import (
        PrintedTotal,
        ReconciliationGroup,
        Status,
        Transaction,
        TransactionKind,
    )

    value = Decimal(nonfinite)
    transaction_arguments = {
        "transaction_id": "transaction-0001",
        "kind": TransactionKind.CHARGE,
        "billed_amount": Decimal("1.00"),
        "billing_currency": "ILS",
        "reconciliation_group_ids": ("group-0001",),
    }
    group_arguments = {
        "group_id": "group-0001",
        "currency": "ILS",
        "printed_total": Decimal("1.00"),
        "calculated_total": Decimal("1.00"),
        "difference": Decimal("0.00"),
        "transaction_ids": ("transaction-0001",),
        "status": Status.RECONCILED,
    }

    for field_name in ("billed_amount", "original_amount"):
        arguments = dict(transaction_arguments)
        arguments[field_name] = value
        if field_name == "original_amount":
            arguments["original_currency"] = "USD"
        with pytest.raises(ValidationError, match="finite"):
            Transaction(**arguments)
    for field_name in ("amount", "minor_unit"):
        arguments = {
            "group_id": "group-0001",
            "amount": Decimal("1.00"),
            "currency": "ILS",
        }
        arguments[field_name] = value
        with pytest.raises(ValidationError, match="finite"):
            PrintedTotal(**arguments)
    for field_name in ("printed_total", "calculated_total", "difference"):
        arguments = dict(group_arguments)
        arguments[field_name] = value
        with pytest.raises(ValidationError, match="finite"):
            ReconciliationGroup(**arguments)


@pytest.mark.parametrize("nonfinite", ("NaN", "Infinity", "-Infinity"))
def test_foreign_exchange_models_reject_nonfinite_decimals(nonfinite: str) -> None:
    from ccparser.models import ExtractedDecimal, ExtractedMoney

    evidence = _fx_evidence("synthetic FX value", 10.0)
    with pytest.raises(ValidationError, match="finite"):
        ExtractedDecimal(value=Decimal(nonfinite), evidence=(evidence,))
    with pytest.raises(ValidationError, match="finite"):
        ExtractedMoney(
            amount=Decimal(nonfinite),
            currency="ILS",
            evidence=(evidence,),
        )


@pytest.mark.parametrize("coordinate", (float("nan"), float("inf"), float("-inf")))
def test_public_evidence_rejects_nonfinite_coordinates(coordinate: float) -> None:
    from ccparser.models import EvidenceReference

    with pytest.raises(ValidationError, match="finite"):
        EvidenceReference(
            page_number=1,
            bbox=(coordinate, 0.0, 1.0, 1.0),
            raw_text="synthetic",
        )
