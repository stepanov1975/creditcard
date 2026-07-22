from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import TypeAdapter, ValidationError

from ccparser.corpus_gate import (
    CommitSha,
    CorpusBaseline,
    CorpusCounts,
    CorpusGateMode,
    CorpusGateReason,
    CorpusMembership,
    CorpusMembershipInventory,
    CorpusPairManifest,
    Digest,
    FieldCount,
    RunManifest,
    ToolchainFingerprint,
    compare_independent_runs,
    compare_with_baseline,
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


def _membership(*, count: int = 1, digest: str = "a" * 64) -> CorpusMembership:
    return CorpusMembership(
        document_count=count,
        source_multiset_digest=digest,
    )


def _run_manifest(
    *,
    elapsed: str = "1",
    counts: CorpusCounts | None = None,
    digest: str = "a" * 64,
) -> RunManifest:
    return RunManifest(
        elapsed_seconds=Decimal(elapsed),
        counts=counts or _counts(),
        json_digest=digest,
        csv_digest=digest,
        ordered_status_digest=digest,
        group_structure_digest=digest,
        transaction_identity_digest=digest,
        field_presence_digest=digest,
        evidence_provenance_digest=digest,
        ambiguity_digest=digest,
    )


def _toolchain(digest_prefix: str = "a") -> ToolchainFingerprint:
    return ToolchainFingerprint(
        python_version="3.13.5",
        package_version="0.1.0",
        pymupdf_version="1.26.3",
        tesseract_version="5.3.4",
        ocr_pipeline_version="1",
        ocr_cache_versions=("layout-v1", "text-v1"),
        command_digest="c" * 64,
        digest=digest_prefix * 64,
    )


def _pair(
    *,
    membership: CorpusMembership | None = None,
    first_elapsed: str = "1",
    second_elapsed: str | None = None,
    manifest: RunManifest | None = None,
) -> CorpusPairManifest:
    first = manifest or _run_manifest(elapsed=first_elapsed)
    second = manifest or _run_manifest(elapsed=second_elapsed or first_elapsed)
    return CorpusPairManifest(
        membership=membership or _membership(),
        first=first,
        second=second,
        worst_elapsed_seconds=max(first.elapsed_seconds, second.elapsed_seconds),
    )


def _baseline(
    *,
    elapsed: str = "10",
    second_elapsed: str | None = None,
    jobs: int = 4,
    toolchain: str = "a",
    tolerance: str = "0.2",
    retained_membership: CorpusMembership | None = None,
    quarantine_membership: CorpusMembership | None = None,
) -> CorpusBaseline:
    return CorpusBaseline(
        version=1,
        commit_sha="d" * 40,
        jobs=jobs,
        runtime_tolerance_ratio=Decimal(tolerance),
        toolchain=_toolchain(toolchain),
        retained=_pair(
            membership=retained_membership,
            first_elapsed=elapsed,
            second_elapsed=second_elapsed,
        ),
        quarantine=_pair(membership=quarantine_membership),
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
        FieldCount.model_validate({"path": "arbitrary.private.path", "count": 1})
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


def test_gate_reason_vocabulary_and_exit_mapping_are_closed_and_ordered() -> None:
    expected = (
        ("invalid_configuration", 1),
        ("path_outside_repository", 1),
        ("unsafe_path_topology", 1),
        ("private_path_not_ignored", 1),
        ("corpus_symlink", 1),
        ("run_path_not_empty", 1),
        ("dirty_repository", 1),
        ("repository_changed", 1),
        ("toolchain_unavailable", 1),
        ("toolchain_changed", 1),
        ("inventory_invalid", 1),
        ("baseline_missing", 1),
        ("baseline_invalid", 1),
        ("parser_runtime_failed", 1),
        ("membership_drift", 2),
        ("retained_not_reconciled", 2),
        ("quarantine_misclassified", 2),
        ("counts_drift", 2),
        ("json_drift", 2),
        ("csv_drift", 2),
        ("status_drift", 2),
        ("group_structure_drift", 2),
        ("transaction_structure_drift", 2),
        ("field_presence_drift", 2),
        ("evidence_provenance_drift", 2),
        ("ambiguity_drift", 2),
        ("runtime_regression", 2),
    )

    assert tuple((reason.value, reason.exit_code) for reason in CorpusGateReason) == expected
    assert tuple(mode.value for mode in CorpusGateMode) == ("verify", "record")


@pytest.mark.parametrize("field", ("command_digest", "digest"))
def test_toolchain_fingerprint_rejects_malformed_digests(field: str) -> None:
    values = _toolchain().model_dump()
    values[field] = "invalid"

    with pytest.raises(ValidationError):
        ToolchainFingerprint.model_validate(values)


def test_toolchain_fingerprint_requires_sorted_cache_versions() -> None:
    values = _toolchain().model_dump()
    values["ocr_cache_versions"] = ("text-v1", "layout-v1")

    with pytest.raises(ValidationError, match="sorted"):
        ToolchainFingerprint.model_validate(values)


def test_comparison_models_reject_invalid_versions_and_numeric_bounds() -> None:
    baseline_values = _baseline().model_dump()

    with pytest.raises(ValidationError):
        CorpusBaseline.model_validate({**baseline_values, "version": 2})
    with pytest.raises(ValidationError):
        CorpusBaseline.model_validate(
            {**baseline_values, "runtime_tolerance_ratio": Decimal("-0.01")}
        )
    with pytest.raises(ValidationError):
        CorpusBaseline.model_validate({**baseline_values, "jobs": 0})

    pair_values = _pair().model_dump()
    with pytest.raises(ValidationError):
        CorpusPairManifest.model_validate(
            {**pair_values, "worst_elapsed_seconds": Decimal("-0.01")}
        )


def test_pair_manifest_requires_the_actual_worst_run_time() -> None:
    first = _run_manifest(elapsed="2")
    second = _run_manifest(elapsed="3")

    with pytest.raises(ValidationError, match="maximum"):
        CorpusPairManifest(
            membership=_membership(),
            first=first,
            second=second,
            worst_elapsed_seconds=Decimal("2"),
        )


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("json_digest", CorpusGateReason.JSON_DRIFT),
        ("csv_digest", CorpusGateReason.CSV_DRIFT),
        ("ordered_status_digest", CorpusGateReason.STATUS_DRIFT),
        ("group_structure_digest", CorpusGateReason.GROUP_STRUCTURE_DRIFT),
        (
            "transaction_identity_digest",
            CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT,
        ),
        ("field_presence_digest", CorpusGateReason.FIELD_PRESENCE_DRIFT),
        (
            "evidence_provenance_digest",
            CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT,
        ),
        ("ambiguity_digest", CorpusGateReason.AMBIGUITY_DRIFT),
    ),
)
def test_independent_run_digest_difference_has_exact_reason(
    field: str, reason: CorpusGateReason
) -> None:
    first = _run_manifest()
    second = first.model_copy(update={field: "f" * 64})

    assert compare_independent_runs(first, second) == (reason,)


def test_independent_run_count_difference_has_exact_reason() -> None:
    first = _run_manifest()
    changed_counts = first.counts.model_copy(update={"transactions": 1})
    second = first.model_copy(update={"counts": changed_counts})

    assert compare_independent_runs(first, second) == (CorpusGateReason.COUNTS_DRIFT,)


def test_independent_run_reasons_follow_policy_order() -> None:
    first = _run_manifest()
    second = first.model_copy(
        update={
            "ambiguity_digest": "f" * 64,
            "ordered_status_digest": "f" * 64,
            "json_digest": "f" * 64,
            "counts": first.counts.model_copy(update={"documents": 1}),
        }
    )

    assert compare_independent_runs(first, second) == (
        CorpusGateReason.COUNTS_DRIFT,
        CorpusGateReason.JSON_DRIFT,
        CorpusGateReason.STATUS_DRIFT,
        CorpusGateReason.AMBIGUITY_DRIFT,
    )


@pytest.mark.parametrize("pair_name", ("retained", "quarantine"))
def test_baseline_comparison_rejects_membership_change(pair_name: str) -> None:
    baseline = _baseline()
    candidate_pair = getattr(baseline, pair_name).model_copy(
        update={"membership": _membership(count=2, digest="b" * 64)}
    )
    candidate = baseline.model_copy(update={pair_name: candidate_pair})

    assert compare_with_baseline(baseline, candidate) == (CorpusGateReason.MEMBERSHIP_DRIFT,)


@pytest.mark.parametrize("pair_name", ("retained", "quarantine"))
@pytest.mark.parametrize("run_name", ("first", "second"))
@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("counts", CorpusGateReason.COUNTS_DRIFT),
        ("json_digest", CorpusGateReason.JSON_DRIFT),
        ("csv_digest", CorpusGateReason.CSV_DRIFT),
        ("ordered_status_digest", CorpusGateReason.STATUS_DRIFT),
        ("group_structure_digest", CorpusGateReason.GROUP_STRUCTURE_DRIFT),
        (
            "transaction_identity_digest",
            CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT,
        ),
        ("field_presence_digest", CorpusGateReason.FIELD_PRESENCE_DRIFT),
        (
            "evidence_provenance_digest",
            CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT,
        ),
        ("ambiguity_digest", CorpusGateReason.AMBIGUITY_DRIFT),
    ),
)
def test_baseline_comparison_checks_every_run_dimension(
    pair_name: str,
    run_name: str,
    field: str,
    reason: CorpusGateReason,
) -> None:
    baseline = _baseline()
    candidate_pair = getattr(baseline, pair_name)
    candidate_run = getattr(candidate_pair, run_name)
    changed_value: object = "f" * 64
    if field == "counts":
        changed_value = candidate_run.counts.model_copy(update={"transactions": 1})
    changed_run = candidate_run.model_copy(update={field: changed_value})
    changed_pair = candidate_pair.model_copy(update={run_name: changed_run})
    candidate = baseline.model_copy(update={pair_name: changed_pair})

    assert compare_with_baseline(baseline, candidate) == (reason,)


def test_baseline_comparison_ignores_toolchain_digest_change() -> None:
    baseline = _baseline()
    candidate = baseline.model_copy(update={"toolchain": _toolchain("b")})

    assert compare_with_baseline(baseline, candidate) == ()


def test_runtime_is_enforced_only_for_matching_toolchain_and_jobs() -> None:
    baseline = _baseline(elapsed="10", second_elapsed="9", jobs=4, toolchain="a")
    slower = _baseline(elapsed="11", second_elapsed="13", jobs=4, toolchain="a")

    assert compare_with_baseline(baseline, slower) == (CorpusGateReason.RUNTIME_REGRESSION,)
    assert (
        compare_with_baseline(
            baseline,
            slower.model_copy(update={"toolchain": _toolchain("b")}),
        )
        == ()
    )
    assert (
        compare_with_baseline(
            baseline,
            slower.model_copy(update={"jobs": 2}),
        )
        == ()
    )


def test_runtime_uses_strict_threshold_and_baseline_recorded_tolerance() -> None:
    baseline = _baseline(elapsed="10", tolerance="0.5")
    at_threshold = _baseline(elapsed="15", tolerance="0")

    assert compare_with_baseline(baseline, at_threshold) == ()
    assert compare_with_baseline(
        baseline,
        at_threshold.model_copy(
            update={
                "retained": _pair(first_elapsed="15.01"),
                "runtime_tolerance_ratio": Decimal("100"),
            }
        ),
    ) == (CorpusGateReason.RUNTIME_REGRESSION,)


def test_baseline_comparison_ignores_commit_and_non_digest_toolchain_metadata() -> None:
    baseline = _baseline()
    same_fingerprint = baseline.toolchain.model_copy(update={"package_version": "future-version"})
    candidate = baseline.model_copy(
        update={
            "commit_sha": "e" * 40,
            "toolchain": same_fingerprint,
        }
    )

    assert compare_with_baseline(baseline, candidate) == ()


def test_baseline_reasons_are_deduplicated_in_declaration_order() -> None:
    baseline = _baseline(elapsed="10", tolerance="0")
    changed_counts = _counts().model_copy(update={"documents": 1})
    changed_manifest = _run_manifest(
        elapsed="11",
        counts=changed_counts,
        digest="f" * 64,
    )
    changed_pair = _pair(
        membership=_membership(count=2, digest="b" * 64),
        manifest=changed_manifest,
    )
    candidate = baseline.model_copy(
        update={
            "retained": changed_pair,
            "quarantine": changed_pair,
        }
    )

    assert compare_with_baseline(baseline, candidate) == (
        CorpusGateReason.MEMBERSHIP_DRIFT,
        CorpusGateReason.COUNTS_DRIFT,
        CorpusGateReason.JSON_DRIFT,
        CorpusGateReason.CSV_DRIFT,
        CorpusGateReason.STATUS_DRIFT,
        CorpusGateReason.GROUP_STRUCTURE_DRIFT,
        CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT,
        CorpusGateReason.FIELD_PRESENCE_DRIFT,
        CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT,
        CorpusGateReason.AMBIGUITY_DRIFT,
        CorpusGateReason.RUNTIME_REGRESSION,
    )
