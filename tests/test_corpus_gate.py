from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import TypeAdapter, ValidationError

from ccparser.corpus_gate import (
    CommitSha,
    CorpusCounts,
    CorpusMembershipInventory,
    Digest,
    FieldCount,
    RunManifest,
    digest_membership,
    project_run,
)
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    ExtractedDecimal,
    ExtractedMoney,
    ForeignExchangeDetails,
    ReconciliationGroup,
    RowNormalizationSummary,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
    TransactionKind,
)
from ccparser.output import canonical_json_bytes, transactions_csv_bytes


def _evidence(raw_text: str, *, page_number: int = 1, y: float = 10.0) -> EvidenceReference:
    return EvidenceReference(
        page_number=page_number,
        bbox=(10.0, y, 80.0, y + 5.0),
        raw_text=raw_text,
    )


def _transaction(
    *,
    with_fx: bool = False,
    ambiguities: tuple[str, ...] = (),
    transaction_id: str = "private-transaction-id",
) -> Transaction:
    transaction_evidence = _evidence("private transaction evidence")
    foreign_exchange: ForeignExchangeDetails | None = None
    if with_fx:
        rate_evidence = _evidence("private exchange-rate evidence", y=20.0)
        fee_evidence = _evidence("private fee evidence", y=30.0)
        discount_evidence = _evidence("private discount evidence", y=40.0)
        foreign_exchange = ForeignExchangeDetails(
            exchange_rate=ExtractedDecimal(
                value=Decimal("3.5"),
                evidence=(rate_evidence,),
            ),
            fee_percentage=ExtractedDecimal(
                value=Decimal("2.5"),
                evidence=(fee_evidence,),
            ),
            gross_fee=ExtractedMoney(
                amount=Decimal("4.00"),
                currency="ILS",
                evidence=(fee_evidence,),
            ),
            fee_discount=ExtractedMoney(
                amount=Decimal("1.00"),
                currency="ILS",
                evidence=(discount_evidence,),
            ),
            net_fee=ExtractedMoney(
                amount=Decimal("3.00"),
                currency="ILS",
                evidence=(fee_evidence, discount_evidence),
            ),
        )
    return Transaction(
        transaction_id=transaction_id,
        kind=TransactionKind.CHARGE,
        billed_amount=Decimal("123.45"),
        billing_currency="ILS",
        reconciliation_group_ids=("private-group-id",),
        ambiguities=ambiguities,
        transaction_date=date(2026, 7, 21),
        description="Private Merchant",
        category=TransactionCategory.PURCHASE,
        original_amount=Decimal("35.27"),
        original_currency="USD",
        foreign_exchange=foreign_exchange,
        evidence=(transaction_evidence,),
    )


def _batch(*, transaction: Transaction | None = None) -> BatchResult:
    chosen_transaction = transaction or _transaction()
    group = ReconciliationGroup(
        group_id="private-group-id",
        currency="ILS",
        printed_total=Decimal("123.45"),
        calculated_total=Decimal("123.45"),
        difference=Decimal("0"),
        transaction_ids=(chosen_transaction.transaction_id,),
        status=Status.RECONCILED,
    )
    row_result = RowNormalizationSummary(
        page_number=1,
        bbox=(1.0, 2.0, 3.0, 4.0),
        raw_text="private normalization row",
        evidence=(),
        transaction=chosen_transaction,
        confidence=1.0,
    )
    statement = StatementResult(
        status=Status.RECONCILED,
        transactions=(chosen_transaction,),
        groups=(group,),
        source_name="private/statement.pdf",
        source_sha256="a" * 64,
        statement_id="private-statement-id",
        row_results=(row_result,),
    )
    return BatchResult(status=Status.RECONCILED, statements=(statement,))


def _counts(*, present_fields: tuple[FieldCount, ...] = ()) -> CorpusCounts:
    return CorpusCounts(
        documents=0,
        reconciled=0,
        unreconciled=0,
        unsupported=0,
        not_statement=0,
        groups=0,
        row_results=0,
        transactions=0,
        ambiguous_transactions=0,
        ambiguity_occurrences=0,
        evidence_references=0,
        present_fields=present_fields,
    )


def test_project_run_tracks_structure_presence_evidence_and_ambiguity() -> None:
    batch = _batch(transaction=_transaction(with_fx=True, ambiguities=("candidate",)))

    manifest = project_run(batch, elapsed_seconds=Decimal("1.25"))

    assert manifest.elapsed_seconds == Decimal("1.25")
    assert manifest.counts.documents == 1
    assert manifest.counts.reconciled == 1
    assert manifest.counts.groups == 1
    assert manifest.counts.row_results == 1
    assert manifest.counts.transactions == 1
    assert manifest.counts.ambiguous_transactions == 1
    assert manifest.counts.ambiguity_occurrences == 1
    assert manifest.counts.evidence_references == 7
    assert FieldCount(path="foreign_exchange.exchange_rate", count=1) in (
        manifest.counts.present_fields
    )
    assert manifest.evidence_provenance_digest
    assert manifest.ambiguity_digest


def test_project_run_counts_each_document_status() -> None:
    statements = tuple(
        StatementResult(status=status, transactions=(), groups=())
        for status in (
            Status.RECONCILED,
            Status.UNRECONCILED,
            Status.UNSUPPORTED,
            Status.NOT_STATEMENT,
        )
    )

    manifest = project_run(
        BatchResult(status=Status.UNRECONCILED, statements=statements),
        elapsed_seconds=Decimal("0"),
    )

    assert manifest.counts.documents == 4
    assert manifest.counts.reconciled == 1
    assert manifest.counts.unreconciled == 1
    assert manifest.counts.unsupported == 1
    assert manifest.counts.not_statement == 1


def test_project_run_hashes_the_exact_canonical_outputs() -> None:
    batch = _batch()

    manifest = project_run(batch, elapsed_seconds=Decimal("0.5"))

    assert manifest.json_digest == sha256(canonical_json_bytes(batch)).hexdigest()
    assert manifest.csv_digest == sha256(transactions_csv_bytes(batch)).hexdigest()


def test_each_structural_projection_affects_its_corresponding_digest() -> None:
    batch = _batch()
    statement = batch.statements[0]
    transaction = statement.transactions[0]
    group = statement.groups[0]
    base = project_run(batch, elapsed_seconds=Decimal("1"))

    status_batch = batch.model_copy(
        update={
            "statements": (statement.model_copy(update={"status": Status.UNRECONCILED}),),
        }
    )
    group_batch = batch.model_copy(
        update={
            "statements": (
                statement.model_copy(
                    update={
                        "groups": (
                            group.model_copy(
                                update={"transaction_ids": (*group.transaction_ids, "another")}
                            ),
                        )
                    }
                ),
            )
        }
    )
    identity_batch = batch.model_copy(
        update={
            "statements": (
                statement.model_copy(
                    update={
                        "transactions": (
                            transaction.model_copy(update={"transaction_id": "another"}),
                        )
                    }
                ),
            )
        }
    )
    presence_batch = batch.model_copy(
        update={
            "statements": (
                statement.model_copy(
                    update={
                        "transactions": (
                            transaction.model_copy(update={"posting_date": date(2026, 7, 22)}),
                        )
                    }
                ),
            )
        }
    )
    changed_evidence = transaction.evidence[0].model_copy(update={"bbox": (11.0, 12.0, 13.0, 14.0)})
    evidence_batch = batch.model_copy(
        update={
            "statements": (
                statement.model_copy(
                    update={
                        "transactions": (
                            transaction.model_copy(update={"evidence": (changed_evidence,)}),
                        )
                    }
                ),
            )
        }
    )
    ambiguity_batch = batch.model_copy(
        update={
            "statements": (
                statement.model_copy(
                    update={
                        "transactions": (
                            transaction.model_copy(update={"ambiguities": ("candidate",)}),
                        )
                    }
                ),
            )
        }
    )

    assert (
        project_run(status_batch, elapsed_seconds=Decimal("1")).ordered_status_digest
        != base.ordered_status_digest
    )
    assert (
        project_run(group_batch, elapsed_seconds=Decimal("1")).group_structure_digest
        != base.group_structure_digest
    )
    assert (
        project_run(identity_batch, elapsed_seconds=Decimal("1")).transaction_identity_digest
        != base.transaction_identity_digest
    )
    assert (
        project_run(presence_batch, elapsed_seconds=Decimal("1")).field_presence_digest
        != base.field_presence_digest
    )
    assert (
        project_run(evidence_batch, elapsed_seconds=Decimal("1")).evidence_provenance_digest
        != base.evidence_provenance_digest
    )
    assert (
        project_run(ambiguity_batch, elapsed_seconds=Decimal("1")).ambiguity_digest
        != base.ambiguity_digest
    )


def test_private_values_never_enter_aggregate_counts() -> None:
    batch = _batch(transaction=_transaction(with_fx=True, ambiguities=("candidate",)))
    statement = batch.statements[0]
    transaction = statement.transactions[0]
    private_value_change = transaction.model_copy(
        update={
            "billed_amount": Decimal("999.99"),
            "transaction_date": date(2025, 1, 2),
            "description": "Different Private Merchant",
        }
    )
    changed_batch = batch.model_copy(
        update={
            "statements": (statement.model_copy(update={"transactions": (private_value_change,)}),)
        }
    )

    counts = project_run(batch, elapsed_seconds=Decimal("1")).counts

    assert project_run(changed_batch, elapsed_seconds=Decimal("1")).counts == counts
    serialized_counts = counts.model_dump_json()
    for private_value in (
        "private/statement.pdf",
        "private-statement-id",
        "private-transaction-id",
        "private-group-id",
        "Private Merchant",
        "private transaction evidence",
        "123.45",
        "2026-07-21",
    ):
        assert private_value not in serialized_counts


def test_membership_digest_is_order_independent_but_duplicate_sensitive() -> None:
    assert digest_membership(("a", "b")) == digest_membership(("b", "a"))
    assert digest_membership(("a", "a", "b")) != digest_membership(("a", "b"))
    assert digest_membership(("a", "a", "b")).document_count == 3


def test_gate_models_are_frozen_and_forbid_extra_fields() -> None:
    membership = digest_membership(("a",))
    inventory = CorpusMembershipInventory(
        version=1,
        retained=membership,
        quarantine=digest_membership(()),
    )

    with pytest.raises(ValidationError, match="frozen"):
        inventory.version = 1
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FieldCount.model_validate({"path": "description", "count": 1, "private": "value"})


def test_present_field_paths_are_closed_sorted_and_unique() -> None:
    with pytest.raises(ValidationError):
        FieldCount(path="arbitrary.private.path", count=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="sorted"):
        _counts(
            present_fields=(
                FieldCount(path="posting_date", count=1),
                FieldCount(path="description", count=1),
            )
        )
    with pytest.raises(ValidationError, match="unique"):
        _counts(
            present_fields=(
                FieldCount(path="description", count=1),
                FieldCount(path="description", count=2),
            )
        )


@pytest.mark.parametrize(
    ("adapter", "invalid"),
    (
        (TypeAdapter(Digest), "a" * 63),
        (TypeAdapter(Digest), "A" * 64),
        (TypeAdapter(CommitSha), "a" * 39),
        (TypeAdapter(CommitSha), "A" * 40),
    ),
)
def test_digest_and_commit_sha_types_require_exact_lowercase_hex(
    adapter: TypeAdapter[str], invalid: str
) -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python(invalid)


def test_run_manifest_rejects_invalid_digest_and_negative_elapsed_time() -> None:
    manifest = project_run(_batch(), elapsed_seconds=Decimal("1"))

    with pytest.raises(ValidationError):
        RunManifest.model_validate({**manifest.model_dump(), "json_digest": "invalid"})
    with pytest.raises(ValidationError):
        project_run(_batch(), elapsed_seconds=Decimal("-0.01"))
