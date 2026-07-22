from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import ccparser.corpus_gate as corpus_gate_module
from ccparser.corpus_gate import (
    CommitSha,
    CompletedCorpusRun,
    CorpusBaseline,
    CorpusCounts,
    CorpusGateAcceptanceError,
    CorpusGateAttestation,
    CorpusGateConfig,
    CorpusGateDependencies,
    CorpusGateInputError,
    CorpusGateMode,
    CorpusGateReason,
    CorpusGateRuntimeError,
    CorpusMembership,
    CorpusMembershipInventory,
    CorpusPairManifest,
    Digest,
    FieldCount,
    GitRepositoryInspector,
    LocalCorpusRunner,
    LocalToolchainInspector,
    RepositoryState,
    RunManifest,
    ToolchainFingerprint,
    compare_independent_runs,
    compare_with_baseline,
    digest_membership,
    project_run,
    run_corpus_gate,
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
from ccparser.output import (
    canonical_json_bytes,
    transactions_csv_bytes,
    write_batch_outputs,
)


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


def _status_batch(status: Status) -> BatchResult:
    return BatchResult(
        status=status,
        statements=(StatementResult(status=status, transactions=(), groups=()),),
    )


def _write_synthetic_pdf(directory: Path, name: str, content: bytes) -> CorpusMembership:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(content)
    return digest_membership((sha256(content).hexdigest(),))


def _write_inventory(
    path: Path,
    *,
    retained: CorpusMembership,
    quarantine: CorpusMembership,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inventory = CorpusMembershipInventory(
        version=1,
        retained=retained,
        quarantine=quarantine,
    )
    path.write_text(inventory.model_dump_json(), encoding="utf-8")


@dataclass
class _FakeRepository:
    root: Path
    states: list[RepositoryState] = field(default_factory=list)
    ignored: bool = True
    ignored_results: dict[Path, bool] = field(default_factory=dict)
    ignored_paths: list[Path] = field(default_factory=list)

    def state(self) -> RepositoryState:
        if self.states:
            return self.states.pop(0)
        return RepositoryState(root=self.root, commit_sha="d" * 40, clean=True)

    def is_ignored(self, path: Path) -> bool:
        self.ignored_paths.append(path)
        return self.ignored_results.get(path, self.ignored)


@dataclass
class _FakeToolchain:
    fingerprints: list[ToolchainFingerprint] = field(default_factory=list)

    def fingerprint(self) -> ToolchainFingerprint:
        if self.fingerprints:
            return self.fingerprints.pop(0)
        return _toolchain()


@dataclass
class _RecordingRunner:
    memberships: dict[Path, CorpusMembership]
    retained_status: Status = Status.RECONCILED
    quarantine_status: Status = Status.NOT_STATEMENT
    on_call: Callable[[int, Path], None] | None = None
    elapsed_values: list[Decimal] = field(default_factory=list)
    membership_pairs: dict[int, tuple[CorpusMembership, CorpusMembership]] = field(
        default_factory=dict
    )
    manifest_updates: dict[int, dict[str, object]] = field(default_factory=dict)
    batch_overrides: dict[int, BatchResult] = field(default_factory=dict)
    input_dirs: list[Path] = field(default_factory=list)
    output_dirs: list[Path] = field(default_factory=list)
    cache_dirs: list[Path] = field(default_factory=list)
    strict_values: list[bool] = field(default_factory=list)
    jobs_values: list[int] = field(default_factory=list)
    cache_was_empty: list[bool] = field(default_factory=list)
    output_was_empty: list[bool] = field(default_factory=list)

    def __call__(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        cache_dir: Path,
        strict: bool,
        jobs: int,
    ) -> CompletedCorpusRun:
        call_index = len(self.input_dirs)
        self.input_dirs.append(input_dir)
        self.output_dirs.append(output_dir)
        self.cache_dirs.append(cache_dir)
        self.strict_values.append(strict)
        self.jobs_values.append(jobs)
        self.output_was_empty.append(output_dir.is_dir() and not any(output_dir.iterdir()))
        self.cache_was_empty.append(cache_dir.is_dir() and not any(cache_dir.iterdir()))
        if self.on_call is not None:
            self.on_call(call_index, input_dir)
        membership = self.memberships[input_dir]
        membership_before, membership_after = self.membership_pairs.get(
            call_index,
            (membership, membership),
        )
        status = self.retained_status if strict else self.quarantine_status
        batch = self.batch_overrides.get(call_index, _status_batch(status))
        elapsed = (
            self.elapsed_values[call_index]
            if call_index < len(self.elapsed_values)
            else Decimal(call_index + 1)
        )
        manifest = project_run(batch, elapsed_seconds=elapsed).model_copy(
            update=self.manifest_updates.get(call_index, {}),
        )
        return CompletedCorpusRun(
            batch=batch,
            manifest=manifest,
            membership_before=membership_before,
            membership_after=membership_after,
        )


def _gate_fixture(
    tmp_path: Path,
    *,
    retained_status: Status = Status.RECONCILED,
    quarantine_status: Status = Status.NOT_STATEMENT,
    runtime_tolerance_ratio: Decimal | None = Decimal("0.2"),
) -> tuple[CorpusGateConfig, CorpusGateDependencies, _RecordingRunner]:
    retained_dir = tmp_path / "retained"
    quarantine_dir = tmp_path / "quarantine"
    retained_membership = _write_synthetic_pdf(retained_dir, "retained.pdf", b"retained")
    quarantine_membership = _write_synthetic_pdf(quarantine_dir, "quarantine.pdf", b"quarantine")
    inventory_path = tmp_path / "private" / "membership.json"
    _write_inventory(
        inventory_path,
        retained=retained_membership,
        quarantine=quarantine_membership,
    )
    config = CorpusGateConfig(
        retained_dir=retained_dir,
        quarantine_dir=quarantine_dir,
        membership_inventory_path=inventory_path,
        baseline_path=tmp_path / "private" / "baseline.json",
        work_dir=tmp_path / "private" / "run",
        jobs=4,
        runtime_tolerance_ratio=runtime_tolerance_ratio,
    )
    runner = _RecordingRunner(
        memberships={
            retained_dir.resolve(): retained_membership,
            quarantine_dir.resolve(): quarantine_membership,
        },
        retained_status=retained_status,
        quarantine_status=quarantine_status,
    )
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(),
    )
    return config, dependencies, runner


def test_orchestration_models_are_strict_frozen_and_validate_numeric_bounds(
    tmp_path: Path,
) -> None:
    config = CorpusGateConfig(
        retained_dir=tmp_path / "retained",
        quarantine_dir=tmp_path / "quarantine",
        membership_inventory_path=tmp_path / "membership.json",
        baseline_path=tmp_path / "baseline.json",
        work_dir=tmp_path / "work",
        jobs=4,
        runtime_tolerance_ratio=Decimal("0.2"),
    )

    with pytest.raises(ValidationError, match="frozen"):
        config.jobs = 2
    with pytest.raises(ValidationError):
        CorpusGateConfig.model_validate({**config.model_dump(), "jobs": 0})
    with pytest.raises(ValidationError):
        CorpusGateConfig.model_validate(
            {**config.model_dump(), "runtime_tolerance_ratio": Decimal("-0.01")}
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CorpusGateConfig.model_validate({**config.model_dump(), "private": "value"})


def test_record_runs_four_isolated_pairs_and_writes_baseline_last(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    inventory_content = config.membership_inventory_path.read_bytes()

    attestation = run_corpus_gate(
        config,
        CorpusGateMode.RECORD,
        dependencies=dependencies,
    )

    assert isinstance(attestation, CorpusGateAttestation)
    assert attestation.passed is True
    assert attestation.mode is CorpusGateMode.RECORD
    assert attestation.commit_abbreviation == "d" * 12
    assert attestation.toolchain_abbreviation == "a" * 12
    assert attestation.retained_counts.reconciled == 1
    assert attestation.quarantine_counts.not_statement == 1
    assert attestation.elapsed_seconds == Decimal("10")
    assert attestation.performance_checked is False
    assert attestation.reason_codes == ()
    assert runner.strict_values == [True, True, False, False]
    assert runner.jobs_values == [4, 4, 4, 4]
    assert len(set((*runner.output_dirs, *runner.cache_dirs))) == 8
    assert all(runner.output_was_empty)
    assert all(runner.cache_was_empty)
    baseline = CorpusBaseline.model_validate_json(config.baseline_path.read_bytes())
    assert baseline.commit_sha == "d" * 40
    assert baseline.runtime_tolerance_ratio == Decimal("0.2")
    assert config.membership_inventory_path.read_bytes() == inventory_content


def test_record_failure_never_replaces_baseline(tmp_path: Path) -> None:
    config, dependencies, _runner = _gate_fixture(
        tmp_path,
        retained_status=Status.UNRECONCILED,
    )
    config.baseline_path.write_bytes(b"accepted")

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(
            config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.RETAINED_NOT_RECONCILED,)
    assert str(caught.value) == CorpusGateReason.RETAINED_NOT_RECONCILED.value
    assert config.baseline_path.read_bytes() == b"accepted"


@pytest.mark.parametrize(
    "error_type",
    (CorpusGateInputError, CorpusGateRuntimeError, CorpusGateAcceptanceError),
)
def test_typed_gate_errors_render_only_closed_reasons(
    error_type: type[CorpusGateInputError | CorpusGateRuntimeError | CorpusGateAcceptanceError],
) -> None:
    error = error_type((CorpusGateReason.INVALID_CONFIGURATION,))

    assert error.reasons == (CorpusGateReason.INVALID_CONFIGURATION,)
    assert str(error) == CorpusGateReason.INVALID_CONFIGURATION.value


@pytest.mark.parametrize("payload", (None, b"not-json", b'{"version":2}'))
def test_record_requires_valid_approved_membership_inventory(
    tmp_path: Path,
    payload: bytes | None,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    if payload is None:
        config.membership_inventory_path.unlink()
    else:
        config.membership_inventory_path.write_bytes(payload)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.INVENTORY_INVALID,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize("corpus_name", ("retained", "quarantine"))
@pytest.mark.parametrize("dimension", ("document_count", "source_multiset_digest"))
def test_record_rejects_each_approved_membership_dimension_change(
    tmp_path: Path,
    corpus_name: str,
    dimension: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    inventory = CorpusMembershipInventory.model_validate_json(
        config.membership_inventory_path.read_bytes()
    )
    approved = getattr(inventory, corpus_name)
    changed_value: int | str = (
        approved.document_count + 1 if dimension == "document_count" else "f" * 64
    )
    changed = approved.model_copy(update={dimension: changed_value})
    _write_inventory(
        config.membership_inventory_path,
        retained=changed if corpus_name == "retained" else inventory.retained,
        quarantine=changed if corpus_name == "quarantine" else inventory.quarantine,
    )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.MEMBERSHIP_DRIFT,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize(
    ("payload", "reason"),
    (
        (None, CorpusGateReason.BASELINE_MISSING),
        (b"not-json", CorpusGateReason.BASELINE_INVALID),
        (b'{"version":2}', CorpusGateReason.BASELINE_INVALID),
    ),
)
def test_verify_rejects_missing_corrupt_and_unknown_baselines(
    tmp_path: Path,
    payload: bytes | None,
    reason: CorpusGateReason,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path, runtime_tolerance_ratio=None)
    if payload is not None:
        config.baseline_path.write_bytes(payload)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (reason,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_verify_validates_independent_inventory_before_loading_baseline(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path, runtime_tolerance_ratio=None)
    config.membership_inventory_path.unlink()

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.INVENTORY_INVALID,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_verify_uses_accepted_tolerance_and_never_rewrites_baseline(tmp_path: Path) -> None:
    record_config, record_dependencies, record_runner = _gate_fixture(
        tmp_path,
        runtime_tolerance_ratio=Decimal("0.5"),
    )
    run_corpus_gate(
        record_config,
        CorpusGateMode.RECORD,
        dependencies=record_dependencies,
    )
    accepted_content = record_config.baseline_path.read_bytes()
    verify_runner = _RecordingRunner(
        memberships=record_runner.memberships,
        elapsed_values=[Decimal("3"), Decimal("3"), Decimal("3"), Decimal("4")],
    )
    verify_dependencies = CorpusGateDependencies(
        runner=verify_runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(),
    )
    verify_config = record_config.model_copy(
        update={
            "work_dir": tmp_path / "private" / "verify-run",
            "runtime_tolerance_ratio": None,
        }
    )

    attestation = run_corpus_gate(
        verify_config,
        CorpusGateMode.VERIFY,
        dependencies=verify_dependencies,
    )

    assert attestation.performance_checked is True
    assert verify_config.baseline_path.read_bytes() == accepted_content


@pytest.mark.parametrize(
    ("mode", "tolerance"),
    (
        (CorpusGateMode.RECORD, None),
        (CorpusGateMode.VERIFY, Decimal("0.2")),
    ),
)
def test_mode_specific_runtime_tolerance_contract_is_enforced_before_mutation(
    tmp_path: Path,
    mode: CorpusGateMode,
    tolerance: Decimal | None,
) -> None:
    config, dependencies, runner = _gate_fixture(
        tmp_path,
        runtime_tolerance_ratio=tolerance,
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, mode, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.INVALID_CONFIGURATION,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_dirty_repository_is_rejected_before_toolchain_or_filesystem_mutation(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=_FakeRepository(
            tmp_path,
            states=[RepositoryState(root=tmp_path, commit_sha="d" * 40, clean=False)],
        ),
        toolchain=_FakeToolchain(),
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.DIRTY_REPOSITORY,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize(
    "field_name",
    (
        "membership_inventory_path",
        "baseline_path",
        "work_dir",
    ),
)
def test_each_private_destination_must_be_git_ignored(
    tmp_path: Path,
    field_name: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    path = getattr(config, field_name).resolve(strict=False)
    repository = _FakeRepository(tmp_path, ignored_results={path: False})
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=repository,
        toolchain=_FakeToolchain(),
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.PRIVATE_PATH_NOT_IGNORED,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize(
    "field_name",
    (
        "retained_dir",
        "quarantine_dir",
        "membership_inventory_path",
        "baseline_path",
        "work_dir",
    ),
)
def test_every_configured_path_must_resolve_beneath_project_root(
    tmp_path: Path,
    field_name: str,
) -> None:
    project_root = tmp_path / "project"
    config, dependencies, runner = _gate_fixture(project_root)
    outside = tmp_path / "outside"
    replacement = outside / field_name
    if field_name in {"retained_dir", "quarantine_dir"}:
        replacement.mkdir(parents=True)
    changed_config = config.model_copy(update={field_name: replacement})

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(
            changed_config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.PATH_OUTSIDE_REPOSITORY,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize(
    ("left_field", "right_field"),
    (
        ("retained_dir", "quarantine_dir"),
        ("retained_dir", "membership_inventory_path"),
        ("retained_dir", "baseline_path"),
        ("retained_dir", "work_dir"),
        ("quarantine_dir", "membership_inventory_path"),
        ("quarantine_dir", "baseline_path"),
        ("quarantine_dir", "work_dir"),
        ("membership_inventory_path", "baseline_path"),
        ("membership_inventory_path", "work_dir"),
        ("baseline_path", "work_dir"),
    ),
)
def test_every_configured_path_pair_must_not_overlap(
    tmp_path: Path,
    left_field: str,
    right_field: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    changed_config = config.model_copy(
        update={right_field: getattr(config, left_field)},
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(
            changed_config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []


@pytest.mark.parametrize("entry_kind", ("file", "directory"))
def test_corpus_symlink_files_and_directories_are_rejected(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    target = tmp_path / f"target-{entry_kind}"
    link = config.retained_dir / f"linked-{entry_kind}.pdf"
    if entry_kind == "file":
        target.write_bytes(b"linked")
        link.symlink_to(target)
    else:
        target.mkdir()
        link.symlink_to(target, target_is_directory=True)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.CORPUS_SYMLINK,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_symlinked_destination_ancestor_is_rejected_before_directory_creation(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    real_destination = tmp_path / "real-destination"
    real_destination.mkdir()
    linked_destination = tmp_path / "linked-destination"
    linked_destination.symlink_to(real_destination, target_is_directory=True)
    changed_config = config.model_copy(update={"work_dir": linked_destination / "run"})

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(
            changed_config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []
    assert not (real_destination / "run").exists()


def test_existing_work_directory_must_be_empty(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.work_dir.mkdir()
    (config.work_dir / "stale").write_bytes(b"stale")

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.RUN_PATH_NOT_EMPTY,)
    assert runner.input_dirs == []


def test_existing_empty_work_directory_is_allowed(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.work_dir.mkdir()

    run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert len(runner.input_dirs) == 4


@pytest.mark.parametrize("unsafe_kind", ("outside", "duplicate", "input_overlap"))
def test_derived_output_and_cache_paths_are_validated_before_work_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    safe_pairs = list(corpus_gate_module._run_paths(config.work_dir.resolve(strict=False)))
    if unsafe_kind == "outside":
        safe_pairs[0] = (tmp_path.parent / "outside-output", safe_pairs[0][1])
    elif unsafe_kind == "duplicate":
        safe_pairs[0] = (safe_pairs[0][0], safe_pairs[0][0])
    else:
        safe_pairs[0] = (config.retained_dir / "nested-output", safe_pairs[0][1])
    monkeypatch.setattr(corpus_gate_module, "_run_paths", lambda _work_dir: tuple(safe_pairs))

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    expected_reason = (
        CorpusGateReason.PATH_OUTSIDE_REPOSITORY
        if unsafe_kind == "outside"
        else CorpusGateReason.UNSAFE_PATH_TOPOLOGY
    )
    assert caught.value.reasons == (expected_reason,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_dotdot_normalization_cannot_hide_symlinked_destination_ancestor(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    unused = tmp_path / "unused"
    unused.mkdir()
    real_destination = tmp_path / "real-destination"
    real_destination.mkdir()
    linked_destination = tmp_path / "linked-destination"
    linked_destination.symlink_to(real_destination, target_is_directory=True)
    disguised_work = unused / ".." / linked_destination.name / "run"
    changed_config = config.model_copy(update={"work_dir": disguised_work})

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(
            changed_config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []
    assert not (real_destination / "run").exists()


def test_existing_baseline_directory_is_rejected_before_runs(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.baseline_path.mkdir()

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.INVALID_CONFIGURATION,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


@pytest.mark.parametrize("call_index", range(4))
@pytest.mark.parametrize("snapshot_name", ("before", "after"))
def test_every_run_membership_snapshot_is_checked(
    tmp_path: Path,
    call_index: int,
    snapshot_name: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    input_dir = config.retained_dir.resolve() if call_index < 2 else config.quarantine_dir.resolve()
    approved = runner.memberships[input_dir]
    changed = approved.model_copy(update={"source_multiset_digest": "f" * 64})
    runner.membership_pairs[call_index] = (
        (changed, approved) if snapshot_name == "before" else (approved, changed)
    )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.MEMBERSHIP_DRIFT,)
    assert len(runner.input_dirs) == 4
    assert not config.baseline_path.exists()


@pytest.mark.parametrize("call_index", range(4))
def test_source_mutation_during_any_run_is_rejected_by_final_snapshot(
    tmp_path: Path,
    call_index: int,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)

    def mutate_source(index: int, input_dir: Path) -> None:
        if index == call_index:
            next(input_dir.glob("*.pdf")).write_bytes(b"mutated")

    runner.on_call = mutate_source

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.MEMBERSHIP_DRIFT,)
    assert len(runner.input_dirs) == 4
    assert not config.baseline_path.exists()


def test_symlink_introduced_during_a_run_is_not_skipped_by_membership_snapshot(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    target = tmp_path / "late-target.pdf"
    target.write_bytes(b"late target")

    def add_symlink(index: int, input_dir: Path) -> None:
        if index == 0:
            (input_dir / "late-link.pdf").symlink_to(target)

    runner.on_call = add_symlink

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.CORPUS_SYMLINK,)
    assert not config.baseline_path.exists()


@pytest.mark.parametrize("corpus_name", ("retained", "quarantine"))
def test_each_run_must_process_the_approved_document_count(
    tmp_path: Path,
    corpus_name: str,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    call_indexes = (0, 1) if corpus_name == "retained" else (2, 3)
    status = Status.RECONCILED if corpus_name == "retained" else Status.NOT_STATEMENT
    empty_batch = BatchResult(status=status, statements=())
    for call_index in call_indexes:
        runner.batch_overrides[call_index] = empty_batch

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.COUNTS_DRIFT,)
    assert not config.baseline_path.exists()


@pytest.mark.parametrize(
    ("retained_status", "quarantine_status", "reason"),
    (
        (
            Status.UNRECONCILED,
            Status.NOT_STATEMENT,
            CorpusGateReason.RETAINED_NOT_RECONCILED,
        ),
        (
            Status.RECONCILED,
            Status.UNSUPPORTED,
            CorpusGateReason.QUARANTINE_MISCLASSIFIED,
        ),
    ),
)
def test_completed_runs_enforce_corpus_status_policy(
    tmp_path: Path,
    retained_status: Status,
    quarantine_status: Status,
    reason: CorpusGateReason,
) -> None:
    config, dependencies, runner = _gate_fixture(
        tmp_path,
        retained_status=retained_status,
        quarantine_status=quarantine_status,
    )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (reason,)
    assert len(runner.input_dirs) == 4
    assert not config.baseline_path.exists()


def test_independent_output_mismatch_rejects_record_without_replacing_baseline(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.baseline_path.write_bytes(b"accepted")
    runner.manifest_updates[1] = {"json_digest": "f" * 64}

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.JSON_DRIFT,)
    assert config.baseline_path.read_bytes() == b"accepted"


def test_verify_compares_both_candidate_runs_with_accepted_baseline(tmp_path: Path) -> None:
    record_config, record_dependencies, record_runner = _gate_fixture(tmp_path)
    run_corpus_gate(
        record_config,
        CorpusGateMode.RECORD,
        dependencies=record_dependencies,
    )
    accepted_content = record_config.baseline_path.read_bytes()
    verify_runner = _RecordingRunner(
        memberships=record_runner.memberships,
        manifest_updates={
            0: {"json_digest": "f" * 64},
            1: {"json_digest": "f" * 64},
        },
    )
    verify_config = record_config.model_copy(
        update={
            "work_dir": tmp_path / "private" / "verify-run",
            "runtime_tolerance_ratio": None,
        }
    )
    verify_dependencies = CorpusGateDependencies(
        runner=verify_runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(),
    )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(
            verify_config,
            CorpusGateMode.VERIFY,
            dependencies=verify_dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.JSON_DRIFT,)
    assert verify_config.baseline_path.read_bytes() == accepted_content


@pytest.mark.parametrize("mismatch", ("toolchain", "jobs"))
def test_baseline_runtime_is_not_compared_across_runtime_contexts(
    tmp_path: Path,
    mismatch: str,
) -> None:
    record_config, record_dependencies, record_runner = _gate_fixture(tmp_path)
    run_corpus_gate(
        record_config,
        CorpusGateMode.RECORD,
        dependencies=record_dependencies,
    )
    verify_runner = _RecordingRunner(
        memberships=record_runner.memberships,
        elapsed_values=[Decimal("100")] * 4,
    )
    verify_config = record_config.model_copy(
        update={
            "work_dir": tmp_path / "private" / "verify-run",
            "runtime_tolerance_ratio": None,
            "jobs": 2 if mismatch == "jobs" else record_config.jobs,
        }
    )
    fingerprint = _toolchain("b") if mismatch == "toolchain" else _toolchain()
    verify_dependencies = CorpusGateDependencies(
        runner=verify_runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(fingerprints=[fingerprint, fingerprint]),
    )

    attestation = run_corpus_gate(
        verify_config,
        CorpusGateMode.VERIFY,
        dependencies=verify_dependencies,
    )

    assert attestation.performance_checked is False


@pytest.mark.parametrize("final_change", ("dirty", "commit", "root"))
def test_repository_change_after_runs_rejects_before_baseline_write(
    tmp_path: Path,
    final_change: str,
) -> None:
    config, _dependencies, runner = _gate_fixture(tmp_path)
    initial = RepositoryState(root=tmp_path, commit_sha="d" * 40, clean=True)
    changed_root = tmp_path / "changed-root"
    changed_root.mkdir()
    final = RepositoryState(
        root=changed_root if final_change == "root" else tmp_path,
        commit_sha="e" * 40 if final_change == "commit" else "d" * 40,
        clean=final_change != "dirty",
    )
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=_FakeRepository(tmp_path, states=[initial, final]),
        toolchain=_FakeToolchain(),
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.REPOSITORY_CHANGED,)
    assert len(runner.input_dirs) == 4
    assert not config.baseline_path.exists()


def test_toolchain_change_after_runs_rejects_before_baseline_write(tmp_path: Path) -> None:
    config, _dependencies, runner = _gate_fixture(tmp_path)
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(fingerprints=[_toolchain("a"), _toolchain("b")]),
    )

    with pytest.raises(CorpusGateRuntimeError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.TOOLCHAIN_CHANGED,)
    assert len(runner.input_dirs) == 4
    assert not config.baseline_path.exists()


def test_unavailable_toolchain_is_privacy_safe_and_precedes_filesystem_mutation(
    tmp_path: Path,
) -> None:
    config, _dependencies, runner = _gate_fixture(tmp_path)

    class UnavailableToolchain:
        def fingerprint(self) -> ToolchainFingerprint:
            raise RuntimeError("private.pdf merchant 123.45")

    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=_FakeRepository(tmp_path),
        toolchain=UnavailableToolchain(),
    )

    with pytest.raises(CorpusGateRuntimeError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.TOOLCHAIN_UNAVAILABLE,)
    assert str(caught.value) == CorpusGateReason.TOOLCHAIN_UNAVAILABLE.value
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_parser_failure_is_privacy_safe_and_preserves_existing_baseline(tmp_path: Path) -> None:
    config, _dependencies, _runner = _gate_fixture(tmp_path)
    config.baseline_path.write_bytes(b"accepted")

    class FailingRunner:
        def __call__(
            self,
            *,
            input_dir: Path,
            output_dir: Path,
            cache_dir: Path,
            strict: bool,
            jobs: int,
        ) -> CompletedCorpusRun:
            del input_dir, output_dir, cache_dir, strict, jobs
            raise RuntimeError("private.pdf merchant 123.45")

    dependencies_repository = _FakeRepository(tmp_path)
    dependencies = CorpusGateDependencies(
        runner=FailingRunner(),
        repository=dependencies_repository,
        toolchain=_FakeToolchain(),
    )

    with pytest.raises(CorpusGateRuntimeError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert str(caught.value) == CorpusGateReason.PARSER_RUNTIME_FAILED.value
    assert config.baseline_path.read_bytes() == b"accepted"


def test_successful_record_writes_baseline_only_after_final_attestations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _dependencies, runner = _gate_fixture(tmp_path)
    events: list[str] = []
    runner.on_call = lambda _index, _input_dir: events.append("run")
    repository = _FakeRepository(tmp_path)
    toolchain = _FakeToolchain()

    class EventRepository:
        def state(self) -> RepositoryState:
            events.append("repository")
            return repository.state()

        def is_ignored(self, path: Path) -> bool:
            return repository.is_ignored(path)

    class EventToolchain:
        def fingerprint(self) -> ToolchainFingerprint:
            events.append("toolchain")
            return toolchain.fingerprint()

    original_write = corpus_gate_module.write_json_atomic

    def recording_write(path: str | Path, result: CorpusBaseline) -> None:
        events.append("write")
        original_write(path, result)

    monkeypatch.setattr(corpus_gate_module, "write_json_atomic", recording_write)
    dependencies = CorpusGateDependencies(
        runner=runner,
        repository=EventRepository(),
        toolchain=EventToolchain(),
    )

    run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert events == [
        "repository",
        "toolchain",
        "run",
        "run",
        "run",
        "run",
        "repository",
        "toolchain",
        "write",
    ]


def test_local_runner_uses_adjacent_membership_snapshots_and_emitted_outputs(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    input_dir.mkdir()
    output_dir.mkdir()
    cache_dir.mkdir()
    source = input_dir / "statement.pdf"
    source.write_bytes(b"before")
    expected_before = digest_membership((sha256(b"before").hexdigest(),))
    expected_after = digest_membership((sha256(b"after").hexdigest(),))
    batch = _status_batch(Status.RECONCILED)
    calls: list[tuple[Path, Path, bool, int | None, Path]] = []

    def fake_parser(
        path: str | Path,
        selected_output_dir: str | Path,
        strict: bool = False,
        jobs: int | None = None,
        *,
        cache_dir: str | Path | None = None,
    ) -> BatchResult:
        assert cache_dir is not None
        calls.append(
            (
                Path(path),
                Path(selected_output_dir),
                strict,
                jobs,
                Path(cache_dir),
            )
        )
        source.write_bytes(b"after")
        write_batch_outputs(selected_output_dir, batch)
        return batch

    clock_values = iter((1_000_000_000, 2_250_000_000))
    runner = LocalCorpusRunner(parser=fake_parser, monotonic_ns=lambda: next(clock_values))

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=4,
    )

    assert calls == [(input_dir, output_dir, True, 4, cache_dir)]
    assert completed.batch == batch
    assert completed.membership_before == expected_before
    assert completed.membership_after == expected_after
    assert completed.manifest.elapsed_seconds == Decimal("1.25")
    assert (
        completed.manifest.json_digest
        == sha256((output_dir / "results.json").read_bytes()).hexdigest()
    )
    assert (
        completed.manifest.csv_digest
        == sha256((output_dir / "transactions.csv").read_bytes()).hexdigest()
    )


def test_git_repository_inspector_uses_common_parent_and_active_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    common_dir = project_root / ".git"
    active_worktree = project_root / ".worktrees" / "active"
    common_dir.mkdir(parents=True)
    active_worktree.mkdir(parents=True)
    commands: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
        capture_output: bool = False,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, capture_output, timeout
        commands.append((command, cwd))
        arguments = command[1:]
        if arguments == ("rev-parse", "--path-format=absolute", "--git-common-dir"):
            output = f"{common_dir}\n".encode()
            return subprocess.CompletedProcess(command, 0, output, b"")
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(command, 0, b"d" * 40 + b"\n", b"")
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if arguments[:2] == ("check-ignore", "--quiet"):
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError("unexpected Git command")

    monkeypatch.setattr(corpus_gate_module.subprocess, "run", fake_run)
    inspector = GitRepositoryInspector(cwd=active_worktree)

    state = inspector.state()
    ignored = inspector.is_ignored(project_root / "private" / "baseline.json")

    assert state == RepositoryState(root=project_root, commit_sha="d" * 40, clean=True)
    assert ignored is True
    state_commands = commands[:3]
    ignore_commands = commands[3:]
    assert all(cwd == active_worktree for _command, cwd in state_commands)
    assert ignore_commands == [
        (
            (
                "git",
                "check-ignore",
                "--quiet",
                "--",
                str(project_root / "private" / "baseline.json"),
            ),
            project_root,
        )
    ]


def test_local_toolchain_fingerprint_hashes_versions_caches_and_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(corpus_gate_module.platform, "python_version", lambda: "3.13.5")
    monkeypatch.setattr(corpus_gate_module.metadata, "version", lambda _package: "0.1.0")
    monkeypatch.setattr(corpus_gate_module.fitz, "VersionBind", "1.28.0")

    def fake_run(
        command: tuple[str, ...],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, timeout
        assert command == ("tesseract", "--version")
        return subprocess.CompletedProcess(command, 0, b"tesseract 5.7.1\nbuild details\n", b"")

    monkeypatch.setattr(corpus_gate_module.subprocess, "run", fake_run)
    inspector = LocalToolchainInspector()

    first = inspector.fingerprint()
    monkeypatch.setattr(
        corpus_gate_module,
        "tesseract_command",
        lambda: ("tesseract", "stdin", "stdout", "--changed"),
    )
    changed = inspector.fingerprint()

    assert first.python_version == "3.13.5"
    assert first.package_version == "0.1.0"
    assert first.pymupdf_version == "1.28.0"
    assert first.tesseract_version == "tesseract 5.7.1"
    assert first.ocr_pipeline_version == corpus_gate_module.OCR_PIPELINE_VERSION
    assert first.ocr_cache_versions == tuple(sorted(first.ocr_cache_versions))
    assert first.command_digest != changed.command_digest
    assert first.digest != changed.digest


def test_default_dependencies_bind_real_adapters_without_executing_them() -> None:
    dependencies = corpus_gate_module._default_dependencies()

    assert isinstance(dependencies.runner, LocalCorpusRunner)
    assert isinstance(dependencies.repository, GitRepositoryInspector)
    assert isinstance(dependencies.toolchain, LocalToolchainInspector)


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
