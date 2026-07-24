from __future__ import annotations

import array
import dataclasses
import fcntl
import gc
import inspect
import io
import json
import os
import py_compile
import shutil
import subprocess
import sys
import threading
import traceback
import weakref
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from hashlib import sha256
from importlib.machinery import BuiltinImporter, FrozenImporter, ModuleSpec, SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import CodeType, ModuleType

import pytest
from pydantic import TypeAdapter, ValidationError

import ccparser.corpus_gate as corpus_gate_module
import ccparser.evidence.ocr as ocr_module
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
    RuntimeArtifactIdentity,
    RuntimeDependency,
    ToolchainAsset,
    ToolchainFingerprint,
    compare_independent_runs,
    compare_with_baseline,
    digest_membership,
    project_run,
    project_streamed_run,
    run_corpus_gate,
)
from ccparser.corpus_spool import StatementSpool
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
)
from ccparser.paths import DirectoryRootPolicy


class _SyntheticSourceLoader:
    def __init__(self, path: Path, source: bytes) -> None:
        self._path = path
        self._source = source

    def get_code(self, fullname: str) -> CodeType:
        del fullname
        return compile(
            self._source,
            str(self._path),
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )


def _synthetic_runtime_module(
    path: Path,
    *,
    module_name: str = "ccparser.corpus_gate",
    loaded_source: bytes | None = None,
) -> ModuleType:
    source = path.read_bytes() if loaded_source is None else loaded_source
    loader = _SyntheticSourceLoader(path, source)
    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__spec__ = ModuleSpec(module_name, loader, origin=str(path))
    executed_code = loader.get_code(module_name)
    module.__dict__["_TEST_EXECUTED_TOP_LEVEL_CODE"] = executed_code
    return module


def _install_synthetic_runtime_module(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *additional_modules: ModuleType,
) -> None:
    for module_name in tuple(sys.modules):
        if module_name == "ccparser" or module_name.startswith("ccparser."):
            monkeypatch.delitem(sys.modules, module_name)
    module_file = module.__file__
    assert isinstance(module_file, str)
    package_path = Path(module_file).with_name("__init__.py")
    package = _synthetic_runtime_module(package_path, module_name="ccparser")
    loaded_modules = (package, module, *additional_modules)
    executed_codes: dict[str, set[CodeType]] = {}
    for loaded_module in loaded_modules:
        loaded_file = loaded_module.__file__
        executed_code = vars(loaded_module).get("_TEST_EXECUTED_TOP_LEVEL_CODE")
        assert isinstance(loaded_file, str)
        assert isinstance(executed_code, CodeType)
        executed_codes.setdefault(str(Path(loaded_file).resolve(strict=True)), set()).add(
            executed_code
        )
    package.__dict__["_EXECUTED_PACKAGE_CODES"] = executed_codes
    for loaded_module in loaded_modules:
        monkeypatch.setitem(sys.modules, loaded_module.__name__, loaded_module)


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
    dependencies = tuple(
        RuntimeDependency(
            name=name,
            version="1.0",
            file_count=1,
            size_bytes=1,
            content_digest="f" * 64,
        )
        for name in corpus_gate_module._RUNTIME_DEPENDENCY_NAMES
    )
    assets = tuple(
        ToolchainAsset(role=role, size_bytes=1, sha256="d" * 64)
        for role in corpus_gate_module._TOOLCHAIN_ASSET_ROLES
    )
    git_executable = ToolchainAsset(
        role="git-executable",
        size_bytes=1,
        sha256="e" * 64,
    )
    payload: dict[str, object] = {
        "version": 6,
        "python_version": "3.13.5",
        "python_implementation": "CPython",
        "python_runtime_digest": "a" * 64,
        "standard_library": RuntimeArtifactIdentity(
            file_count=1,
            size_bytes=1,
            digest="6" * 64,
        ).model_dump(mode="json"),
        "runtime_environment_digest": digest_prefix * 64,
        "dependencies": tuple(dependency.model_dump(mode="json") for dependency in dependencies),
        "git_executable": git_executable.model_dump(mode="json"),
        "git_native_closure": RuntimeArtifactIdentity(
            file_count=1,
            size_bytes=1,
            digest="8" * 64,
        ).model_dump(mode="json"),
        "native_runtime": RuntimeArtifactIdentity(
            file_count=1,
            size_bytes=1,
            digest="9" * 64,
        ).model_dump(mode="json"),
        "pymupdf_binding_version": "1.28.0",
        "pymupdf_engine_version": "1.29.0",
        "tesseract_version": "5.3.4",
        "tesseract_version_output_digest": "b" * 64,
        "tesseract_assets": tuple(asset.model_dump(mode="json") for asset in assets),
        "tesseract_native_closure": RuntimeArtifactIdentity(
            file_count=1,
            size_bytes=1,
            digest="7" * 64,
        ).model_dump(mode="json"),
        "ocr_pipeline_version": "1",
        "ocr_cache_versions": ("layout-v1", "text-v1"),
        "command_digest": "c" * 64,
    }
    return ToolchainFingerprint.model_validate(
        {**payload, "digest": corpus_gate_module._toolchain_payload_digest(payload)}
    )


def _install_synthetic_dynamic_runtime(
    monkeypatch: pytest.MonkeyPatch,
    runner: Callable[..., subprocess.CompletedProcess[bytes]],
) -> None:
    class SyntheticDynamicRuntime:
        def __init__(self, path: Path) -> None:
            self.executable = corpus_gate_module._SealedCapability.bind_path(
                path,
                executable=True,
            )

        @property
        def native_closure(self) -> RuntimeArtifactIdentity:
            return RuntimeArtifactIdentity(
                file_count=1,
                size_bytes=self.executable.size_bytes,
                digest=self.executable.sha256,
            )

        @property
        def pass_fds(self) -> tuple[int, ...]:
            return (self.executable.file_descriptor,)

        @property
        def executable_file_descriptors(self) -> tuple[int, ...]:
            return self.pass_fds

        def command(self, arguments: tuple[str, ...], *, argv0: str) -> tuple[str, ...]:
            del argv0
            return (self.executable.descriptor_path, *arguments)

        def run(
            self,
            arguments: tuple[str, ...],
            *,
            cwd: Path,
            environment: tuple[tuple[str, str], ...],
            timeout: float,
            input_bytes: bytes | None = None,
            stderr_to_stdout: bool = False,
            allowed_file_descriptors: tuple[int, ...] | None = None,
        ) -> subprocess.CompletedProcess[bytes]:
            del cwd, input_bytes, allowed_file_descriptors
            return runner(
                (self.executable.descriptor_path, *arguments),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
                env=dict(environment),
                pass_fds=self.pass_fds,
                timeout=timeout,
            )

        def close(self) -> None:
            self.executable.close()

    def bind_path(
        _cls: type[object],
        path: Path,
        *,
        staging_parent: Path,
    ) -> SyntheticDynamicRuntime:
        del staging_parent
        return SyntheticDynamicRuntime(path)

    monkeypatch.setattr(
        corpus_gate_module._BoundDynamicExecutable,
        "bind_path",
        classmethod(bind_path),
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
    batch_status_overrides: dict[int, Status] = field(default_factory=dict)
    manifest_overrides: dict[int, RunManifest] = field(default_factory=dict)
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
        membership = self.memberships.get(input_dir)
        if membership is None:
            membership = corpus_gate_module._snapshot_membership(
                input_dir,
                allow_descriptor_root=True,
            )
        membership_before, membership_after = self.membership_pairs.get(
            call_index,
            (membership, membership),
        )
        status = self.retained_status if strict else self.quarantine_status
        batch_status = self.batch_status_overrides.get(call_index, status)
        elapsed = (
            self.elapsed_values[call_index]
            if call_index < len(self.elapsed_values)
            else Decimal(call_index + 1)
        )
        manifest = self.manifest_overrides.get(
            call_index,
            project_run(_status_batch(status), elapsed_seconds=elapsed),
        )
        return CompletedCorpusRun(
            batch_status=batch_status,
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
        expected_commit_sha="d" * 40,
        retained_dir=retained_dir,
        quarantine_dir=quarantine_dir,
        membership_inventory_path=inventory_path,
        membership_inventory_sha256=sha256(inventory_path.read_bytes()).hexdigest(),
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
        expected_commit_sha="d" * 40,
        retained_dir=tmp_path / "retained",
        quarantine_dir=tmp_path / "quarantine",
        membership_inventory_path=tmp_path / "membership.json",
        membership_inventory_sha256="e" * 64,
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
    for required_field in ("expected_commit_sha", "membership_inventory_sha256"):
        incomplete = config.model_dump()
        incomplete.pop(required_field)
        with pytest.raises(ValidationError, match="Field required"):
            CorpusGateConfig.model_validate(incomplete)
    for field_name, malformed_value in (
        ("expected_commit_sha", "D" * 40),
        ("expected_commit_sha", "d" * 39),
        ("membership_inventory_sha256", "E" * 64),
        ("membership_inventory_sha256", "e" * 63),
    ):
        with pytest.raises(ValidationError, match="String should match pattern"):
            CorpusGateConfig.model_validate({**config.model_dump(), field_name: malformed_value})


def test_completed_corpus_run_cannot_retain_a_batch() -> None:
    fields = {field.name for field in dataclasses.fields(CompletedCorpusRun)}
    assert fields == {
        "batch_status",
        "manifest",
        "membership_before",
        "membership_after",
    }


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
    assert attestation.toolchain_abbreviation == _toolchain().digest[:12]
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


def test_gate_binds_fingerprinted_tesseract_runtime_across_all_parser_runs(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    runtime = ocr_module.TesseractExecutionRuntime(
        executable_path="/proc/self/fd/1000000",
        tessdata_directory="/proc/self/fd/1000001",
        pass_fds=(),
        environment=(("PATH", "/nonexistent"),),
    )

    class StagedRuntime:
        def __init__(self) -> None:
            self.runtime = runtime
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class RuntimeCapabilities:
        def __init__(self) -> None:
            self.work_fds: list[int] = []
            self.staged = StagedRuntime()

        def stage_tesseract(self, work_fd: int) -> StagedRuntime:
            self.work_fds.append(work_fd)
            return self.staged

    runtime_capabilities = RuntimeCapabilities()
    bound_dependencies = CorpusGateDependencies(
        runner=dependencies.runner,
        repository=dependencies.repository,
        toolchain=dependencies.toolchain,
        runtime_capabilities=runtime_capabilities,  # type: ignore[arg-type]
    )

    def assert_bound(_call_index: int, _input_dir: Path) -> None:
        assert ocr_module._ACTIVE_TESSERACT_RUNTIME is runtime

    runner.on_call = assert_bound

    run_corpus_gate(
        config,
        CorpusGateMode.RECORD,
        dependencies=bound_dependencies,
    )

    assert len(runtime_capabilities.work_fds) == 1
    assert runtime_capabilities.staged.closed is True
    assert ocr_module._ACTIVE_TESSERACT_RUNTIME is None


def test_record_failure_never_replaces_baseline(tmp_path: Path) -> None:
    config, dependencies, _runner = _gate_fixture(
        tmp_path,
        retained_status=Status.UNRECONCILED,
    )
    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(
            config,
            CorpusGateMode.RECORD,
            dependencies=dependencies,
        )

    assert caught.value.reasons == (CorpusGateReason.RETAINED_NOT_RECONCILED,)
    assert str(caught.value) == CorpusGateReason.RETAINED_NOT_RECONCILED.value
    assert not config.baseline_path.exists()


def test_record_rejects_an_existing_baseline_before_parser_execution(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.baseline_path.write_bytes(canonical_json_bytes(_baseline()))

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.BASELINE_INVALID,)
    assert runner.input_dirs == []


def test_secure_publication_exposes_only_exclusive_candidate_creation() -> None:
    assert tuple(inspect.signature(corpus_gate_module._publish_json_secure).parameters) == (
        "parent_fd",
        "name",
        "result",
    )


@pytest.mark.parametrize(
    "failure_point",
    (
        "serialization",
        "temporary_open",
        "temporary_write",
        "temporary_fsync",
        "destination_revalidation",
        "parent_fsync",
        "link",
    ),
)
def test_secure_publication_failure_leaves_no_candidate_or_owned_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_open = corpus_gate_module.os.open
    original_fsync = corpus_gate_module.os.fsync
    original_validate = corpus_gate_module._validate_baseline_absent

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected publication failure")

    if failure_point == "serialization":
        monkeypatch.setattr(corpus_gate_module, "canonical_json_bytes", fail)
    elif failure_point == "temporary_open":

        def fail_temporary_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if dir_fd == parent_fd:
                raise OSError("injected publication failure")
            return original_open(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(corpus_gate_module.os, "open", fail_temporary_open)
    elif failure_point == "temporary_write":
        monkeypatch.setattr(corpus_gate_module, "_write_all", fail)
    elif failure_point in {"temporary_fsync", "parent_fsync"}:

        def fail_selected_fsync(file_descriptor: int) -> None:
            if (failure_point == "parent_fsync") == (file_descriptor == parent_fd):
                raise OSError("injected publication failure")
            original_fsync(file_descriptor)

        monkeypatch.setattr(corpus_gate_module.os, "fsync", fail_selected_fsync)
    elif failure_point == "destination_revalidation":
        validation_calls = 0

        def fail_second_validation(parent: int, name: str) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                raise OSError("injected publication failure")
            original_validate(parent, name)

        monkeypatch.setattr(
            corpus_gate_module,
            "_validate_baseline_absent",
            fail_second_validation,
        )
    else:
        monkeypatch.setattr(corpus_gate_module.os, "link", fail)

    try:
        with pytest.raises(OSError, match="injected publication failure"):
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        corpus_gate_module.os.close(parent_fd)

    assert not baseline_path.exists()
    assert tuple(private_dir.iterdir()) == ()


def test_exclusive_candidate_publication_never_overwrites_a_racing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "candidate.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_link = corpus_gate_module.os.link
    racing_content = b"independently promoted baseline"

    def race_before_link(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        baseline_path.write_bytes(racing_content)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(corpus_gate_module.os, "link", race_before_link)
    try:
        with pytest.raises(CorpusGateInputError) as caught:
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        os.close(parent_fd)

    assert caught.value.reasons == (CorpusGateReason.BASELINE_INVALID,)
    assert baseline_path.read_bytes() == racing_content


def test_exclusive_candidate_publication_recognizes_commit_before_link_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "candidate.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_link = corpus_gate_module.os.link

    def commit_then_fail(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        raise OSError("injected post-commit link failure")

    monkeypatch.setattr(corpus_gate_module.os, "link", commit_then_fail)
    try:
        corpus_gate_module._publish_json_secure(
            parent_fd,
            baseline_path.name,
            _baseline(),
        )
    finally:
        os.close(parent_fd)

    assert baseline_path.read_bytes() == canonical_json_bytes(_baseline())
    assert tuple(private_dir.iterdir()) == (baseline_path,)


def test_secure_publication_link_then_cleanup_is_the_final_filesystem_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_fsync = corpus_gate_module.os.fsync
    original_link = corpus_gate_module.os.link
    original_unlink = corpus_gate_module.os.unlink
    events: list[str] = []

    def recording_fsync(file_descriptor: int) -> None:
        events.append("parent_fsync" if file_descriptor == parent_fd else "temporary_fsync")
        original_fsync(file_descriptor)

    def recording_link(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        events.append("link")
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    def recording_unlink(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
    ) -> None:
        events.append("unlink")
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(corpus_gate_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(corpus_gate_module.os, "link", recording_link)
    monkeypatch.setattr(corpus_gate_module.os, "unlink", recording_unlink)
    try:
        corpus_gate_module._publish_json_secure(
            parent_fd,
            baseline_path.name,
            _baseline(),
        )
    finally:
        os.close(parent_fd)

    assert events == ["temporary_fsync", "parent_fsync", "link", "unlink"]
    assert baseline_path.read_bytes() == canonical_json_bytes(_baseline())


def test_secure_publication_suppresses_only_post_commit_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_close = corpus_gate_module.os.close
    failure_injected = False

    def fail_temporary_close(file_descriptor: int) -> None:
        nonlocal failure_injected
        if file_descriptor != parent_fd and not failure_injected:
            failure_injected = True
            original_close(file_descriptor)
            raise OSError("injected close failure")
        original_close(file_descriptor)

    monkeypatch.setattr(corpus_gate_module.os, "close", fail_temporary_close)
    try:
        corpus_gate_module._publish_json_secure(
            parent_fd,
            baseline_path.name,
            _baseline(),
        )
    finally:
        corpus_gate_module.os.close(parent_fd)

    assert failure_injected is True
    assert baseline_path.read_bytes() == canonical_json_bytes(_baseline())


def test_secure_publication_rejects_post_create_name_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    temporary_path = private_dir / ".baseline.json.owned.tmp"
    displaced_temporary = private_dir / "displaced-temporary"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_write = corpus_gate_module._write_all
    monkeypatch.setattr(corpus_gate_module.secrets, "token_hex", lambda _length: "owned")

    def write_then_substitute(file_descriptor: int, content: bytes) -> None:
        original_write(file_descriptor, content)
        temporary_path.rename(displaced_temporary)
        temporary_path.write_bytes(b"substitute")

    monkeypatch.setattr(corpus_gate_module, "_write_all", write_then_substitute)
    try:
        with pytest.raises(CorpusGateInputError) as caught:
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        os.close(parent_fd)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert not baseline_path.exists()
    assert temporary_path.read_bytes() == b"substitute"


def test_secure_publication_cleanup_never_unlinks_a_substituted_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    temporary_path = private_dir / ".baseline.json.owned.tmp"
    displaced_temporary = private_dir / "displaced-temporary"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(corpus_gate_module.secrets, "token_hex", lambda _length: "owned")

    def substitute_then_interrupt(_file_descriptor: int, _content: bytes) -> None:
        temporary_path.rename(displaced_temporary)
        temporary_path.write_bytes(b"substitute")
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_gate_module, "_write_all", substitute_then_interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        os.close(parent_fd)

    assert not baseline_path.exists()
    assert temporary_path.read_bytes() == b"substitute"


def test_secure_publication_treats_commit_then_interrupt_as_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    original_link = corpus_gate_module.os.link

    def commit_then_interrupt(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_gate_module.os, "link", commit_then_interrupt)
    try:
        corpus_gate_module._publish_json_secure(
            parent_fd,
            baseline_path.name,
            _baseline(),
        )
    finally:
        os.close(parent_fd)

    assert baseline_path.read_bytes() == canonical_json_bytes(_baseline())


def test_secure_publication_propagates_interrupt_before_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)

    def interrupt_before_link(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_gate_module.os, "link", interrupt_before_link)
    try:
        with pytest.raises(KeyboardInterrupt):
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        os.close(parent_fd)

    assert not baseline_path.exists()


def test_secure_publication_never_unlinks_an_unowned_temporary_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    baseline_path = private_dir / "baseline.json"
    colliding_temporary_path = private_dir / ".baseline.json.collision.tmp"
    colliding_temporary_path.write_bytes(b"unowned temporary bytes")
    parent_fd = os.open(private_dir, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(corpus_gate_module.secrets, "token_hex", lambda _length: "collision")

    try:
        with pytest.raises(FileExistsError):
            corpus_gate_module._publish_json_secure(
                parent_fd,
                baseline_path.name,
                _baseline(),
            )
    finally:
        os.close(parent_fd)

    assert not baseline_path.exists()
    assert colliding_temporary_path.read_bytes() == b"unowned temporary bytes"


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


def test_record_rejects_semantically_equivalent_inventory_bytes_outside_the_approved_pin(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.membership_inventory_path.write_bytes(
        config.membership_inventory_path.read_bytes() + b"\n"
    )

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
    config = config.model_copy(
        update={
            "membership_inventory_sha256": sha256(
                config.membership_inventory_path.read_bytes()
            ).hexdigest()
        }
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
    config = config.model_copy(
        update={
            "baseline_sha256": (sha256(payload).hexdigest() if payload is not None else "f" * 64)
        }
    )

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (reason,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_verify_validates_independent_inventory_before_loading_baseline(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path, runtime_tolerance_ratio=None)
    config = config.model_copy(update={"baseline_sha256": "f" * 64})
    config.membership_inventory_path.unlink()

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.INVENTORY_INVALID,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_inventory_ancestor_swap_immediately_before_fd_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    private_dir = tmp_path / "private"
    displaced_private = tmp_path / "displaced-private"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "membership.json").write_bytes(b"outside substitute")
    original_read = corpus_gate_module._read_stable_regular_file

    def swap_then_read(repository_fd: int, repository_root: Path, path: Path) -> bytes:
        if path == config.membership_inventory_path.resolve(strict=False):
            private_dir.rename(displaced_private)
            private_dir.symlink_to(outside_dir, target_is_directory=True)
        return original_read(repository_fd, repository_root, path)

    monkeypatch.setattr(corpus_gate_module, "_read_stable_regular_file", swap_then_read)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []


def test_verify_baseline_name_swap_immediately_before_fd_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path, runtime_tolerance_ratio=None)
    retained_membership = runner.memberships[config.retained_dir.resolve()]
    quarantine_membership = runner.memberships[config.quarantine_dir.resolve()]
    baseline_content = canonical_json_bytes(
        _baseline(
            retained_membership=retained_membership,
            quarantine_membership=quarantine_membership,
        )
    )
    config.baseline_path.write_bytes(baseline_content)
    config = config.model_copy(update={"baseline_sha256": sha256(baseline_content).hexdigest()})
    displaced_baseline = config.baseline_path.with_name("displaced-baseline.json")
    outside_baseline = tmp_path / "outside-baseline.json"
    outside_baseline.write_bytes(b"outside substitute")
    original_read = corpus_gate_module._read_stable_regular_file

    def swap_then_read(repository_fd: int, repository_root: Path, path: Path) -> bytes:
        if path == config.baseline_path.resolve(strict=False):
            config.baseline_path.rename(displaced_baseline)
            config.baseline_path.symlink_to(outside_baseline)
        return original_read(repository_fd, repository_root, path)

    monkeypatch.setattr(corpus_gate_module, "_read_stable_regular_file", swap_then_read)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []
    assert outside_baseline.read_bytes() == b"outside substitute"


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
            "baseline_sha256": sha256(accepted_content).hexdigest(),
        }
    )

    attestation = run_corpus_gate(
        verify_config,
        CorpusGateMode.VERIFY,
        dependencies=verify_dependencies,
    )

    assert attestation.performance_checked is True
    assert verify_config.baseline_path.read_bytes() == accepted_content


def test_verify_rejects_a_schema_valid_baseline_that_does_not_match_protected_pin(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(
        tmp_path,
        runtime_tolerance_ratio=None,
    )
    baseline = _baseline(
        retained_membership=runner.memberships[config.retained_dir.resolve()],
        quarantine_membership=runner.memberships[config.quarantine_dir.resolve()],
    )
    config.baseline_path.write_bytes(canonical_json_bytes(baseline))
    config = config.model_copy(update={"baseline_sha256": "f" * 64})

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.BASELINE_INVALID,)
    assert runner.input_dirs == []


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


def test_initial_repository_commit_must_match_the_expected_reviewed_sha(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config = config.model_copy(update={"expected_commit_sha": "e" * 40})

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.REPOSITORY_CHANGED,)
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


@pytest.mark.parametrize("mode", (0o770, 0o707))
def test_destination_ancestry_must_not_be_group_or_other_writable(
    tmp_path: Path,
    mode: int,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    config.baseline_path.parent.chmod(mode)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []


def test_destination_ancestry_must_be_owned_by_effective_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    actual_uid = os.geteuid()
    monkeypatch.setattr(corpus_gate_module.os, "geteuid", lambda: actual_uid + 1)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []


def test_rejected_untrusted_ancestry_does_not_leak_directory_descriptors(
    tmp_path: Path,
) -> None:
    untrusted_dir = tmp_path / "untrusted"
    untrusted_dir.mkdir()
    untrusted_dir.chmod(0o770)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    descriptors_before = set(os.listdir("/proc/self/fd"))
    try:
        for _ in range(10):
            with pytest.raises(CorpusGateInputError):
                corpus_gate_module._open_directory_beneath(
                    root_fd,
                    (untrusted_dir.name,),
                    create_missing=False,
                    require_trusted=True,
                )
        descriptors_after = set(os.listdir("/proc/self/fd"))
    finally:
        os.close(root_fd)

    assert descriptors_after == descriptors_before


def test_interrupted_initial_trust_validation_does_not_leak_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    descriptors_before = set(os.listdir("/proc/self/fd"))
    original_close = os.close
    cleanup_close_injected = False

    def interrupt_validation(_directory_stat: os.stat_result) -> None:
        raise KeyboardInterrupt

    def close_then_fail(file_descriptor: int) -> None:
        nonlocal cleanup_close_injected
        original_close(file_descriptor)
        if file_descriptor != root_fd and not cleanup_close_injected:
            cleanup_close_injected = True
            raise OSError("injected cleanup close failure")

    monkeypatch.setattr(
        corpus_gate_module,
        "_validate_trusted_directory",
        interrupt_validation,
    )
    monkeypatch.setattr(corpus_gate_module.os, "close", close_then_fail)
    try:
        with pytest.raises(KeyboardInterrupt):
            corpus_gate_module._open_directory_beneath(
                root_fd,
                (),
                create_missing=False,
                require_trusted=True,
            )
        descriptors_after = set(os.listdir("/proc/self/fd"))
    finally:
        os.close(root_fd)

    assert cleanup_close_injected
    assert descriptors_after == descriptors_before


def test_staging_interrupt_releases_descriptors_and_baseline_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, _runner = _gate_fixture(tmp_path)
    descriptors_before = set(os.listdir("/proc/self/fd"))

    def interrupt_staging(_source_fd: int, _destination_fd: int) -> tuple[str, ...]:
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus_gate_module, "_copy_pdf_tree", interrupt_staging)

    with pytest.raises(KeyboardInterrupt):
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    descriptors_after = set(os.listdir("/proc/self/fd"))
    lock_probe_fd = os.open(
        config.baseline_path.parent,
        os.O_RDONLY | os.O_DIRECTORY,
    )
    lock_reacquired = False
    try:
        try:
            fcntl.flock(lock_probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            lock_reacquired = True
    finally:
        os.close(lock_probe_fd)
        for leaked_descriptor in descriptors_after - descriptors_before:
            with suppress(OSError):
                os.close(int(leaked_descriptor))

    assert descriptors_after == descriptors_before
    assert lock_reacquired


def test_regular_copy_cleanup_preserves_interrupt_and_attempts_both_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    source_dir.mkdir()
    destination_dir.mkdir()
    (source_dir / "statement.pdf").write_bytes(b"statement")
    source_parent_fd = os.open(source_dir, os.O_RDONLY | os.O_DIRECTORY)
    destination_parent_fd = os.open(destination_dir, os.O_RDONLY | os.O_DIRECTORY)
    descriptors_before = set(os.listdir("/proc/self/fd"))
    original_close = os.close
    close_attempts: list[int] = []

    def interrupt_read(_file_descriptor: int, _size: int) -> bytes:
        raise KeyboardInterrupt

    def close_first_then_fail(file_descriptor: int) -> None:
        close_attempts.append(file_descriptor)
        original_close(file_descriptor)
        if len(close_attempts) == 1:
            raise OSError("injected cleanup close failure")

    monkeypatch.setattr(corpus_gate_module.os, "read", interrupt_read)
    monkeypatch.setattr(corpus_gate_module.os, "close", close_first_then_fail)
    try:
        with pytest.raises(KeyboardInterrupt):
            corpus_gate_module._copy_regular_pdf(
                source_parent_fd,
                destination_parent_fd,
                "statement.pdf",
            )
    finally:
        original_close(source_parent_fd)
        original_close(destination_parent_fd)
        descriptors_after = set(os.listdir("/proc/self/fd"))
        for leaked_descriptor in descriptors_after - descriptors_before:
            with suppress(OSError):
                original_close(int(leaked_descriptor))

    assert len(close_attempts) == 2
    assert len(set(close_attempts)) == 2


def test_recursive_copy_cleanup_preserves_interrupt_and_attempts_both_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    (source_dir / "nested").mkdir(parents=True)
    destination_dir.mkdir()
    source_parent_fd = os.open(source_dir, os.O_RDONLY | os.O_DIRECTORY)
    destination_parent_fd = os.open(destination_dir, os.O_RDONLY | os.O_DIRECTORY)
    descriptors_before = set(os.listdir("/proc/self/fd"))
    original_close = os.close
    original_scandir = os.scandir
    close_attempts: list[int] = []
    scandir_calls = 0

    def interrupt_nested_scan(file_descriptor: int) -> os.ScandirIterator[str]:
        nonlocal scandir_calls
        scandir_calls += 1
        if scandir_calls == 2:
            raise KeyboardInterrupt
        return original_scandir(file_descriptor)

    def close_first_then_fail(file_descriptor: int) -> None:
        close_attempts.append(file_descriptor)
        original_close(file_descriptor)
        if len(close_attempts) == 1:
            raise OSError("injected cleanup close failure")

    monkeypatch.setattr(corpus_gate_module.os, "scandir", interrupt_nested_scan)
    monkeypatch.setattr(corpus_gate_module.os, "close", close_first_then_fail)
    try:
        with pytest.raises(KeyboardInterrupt):
            corpus_gate_module._copy_pdf_tree(
                source_parent_fd,
                destination_parent_fd,
            )
    finally:
        original_close(source_parent_fd)
        original_close(destination_parent_fd)
        descriptors_after = set(os.listdir("/proc/self/fd"))
        for leaked_descriptor in descriptors_after - descriptors_before:
            with suppress(OSError):
                original_close(int(leaked_descriptor))

    assert len(close_attempts) == 2
    assert len(set(close_attempts)) == 2


def test_shared_baseline_parent_lock_excludes_a_concurrent_gate(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    parent_fd = os.open(config.baseline_path.parent, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(parent_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(CorpusGateInputError) as caught:
            run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)
    finally:
        os.close(parent_fd)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []


def test_verify_rejects_baseline_replaced_before_parent_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, runner = _gate_fixture(
        tmp_path,
        runtime_tolerance_ratio=None,
    )
    accepted = _baseline(
        retained_membership=runner.memberships[config.retained_dir.resolve()],
        quarantine_membership=runner.memberships[config.quarantine_dir.resolve()],
    )
    config.baseline_path.write_bytes(canonical_json_bytes(accepted))
    config = config.model_copy(
        update={"baseline_sha256": sha256(config.baseline_path.read_bytes()).hexdigest()}
    )
    replacement = accepted.model_copy(
        update={"runtime_tolerance_ratio": Decimal("0.3")},
    )
    replacement_path = config.baseline_path.with_name("replacement-baseline.json")
    original_flock = fcntl.flock

    def replace_then_lock(file_descriptor: int, operation: int) -> None:
        replacement_path.write_bytes(canonical_json_bytes(replacement))
        os.replace(replacement_path, config.baseline_path)
        original_flock(file_descriptor, operation)

    monkeypatch.setattr(corpus_gate_module.fcntl, "flock", replace_then_lock)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.VERIFY, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.BASELINE_INVALID,)
    assert runner.input_dirs == []
    assert not config.work_dir.exists()


def test_ignored_baseline_may_be_directly_under_repository_root(tmp_path: Path) -> None:
    config, dependencies, _runner = _gate_fixture(tmp_path)
    root_baseline = tmp_path / "baseline.json"
    changed_config = config.model_copy(update={"baseline_path": root_baseline})

    run_corpus_gate(changed_config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert CorpusBaseline.model_validate_json(root_baseline.read_bytes()).version == 1


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

    assert caught.value.reasons == (CorpusGateReason.BASELINE_INVALID,)
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
        runner.manifest_overrides[call_index] = project_run(
            empty_batch,
            elapsed_seconds=Decimal(call_index + 1),
        )

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


def test_retained_batch_status_must_be_reconciled(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    runner.batch_status_overrides[0] = Status.UNRECONCILED
    runner.batch_status_overrides[1] = Status.UNRECONCILED

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.RETAINED_NOT_RECONCILED,)
    assert not config.baseline_path.exists()


def test_quarantine_batch_status_must_be_not_statement(tmp_path: Path) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    runner.batch_status_overrides[2] = Status.UNSUPPORTED
    runner.batch_status_overrides[3] = Status.UNSUPPORTED

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.QUARANTINE_MISCLASSIFIED,)
    assert not config.baseline_path.exists()


@pytest.mark.parametrize(
    ("corpus_name", "manifest_status", "reason"),
    (
        (
            "retained",
            Status.UNRECONCILED,
            CorpusGateReason.RETAINED_NOT_RECONCILED,
        ),
        (
            "quarantine",
            Status.UNSUPPORTED,
            CorpusGateReason.QUARANTINE_MISCLASSIFIED,
        ),
    ),
)
def test_corpus_status_policy_uses_manifest_status_counts(
    tmp_path: Path,
    corpus_name: str,
    manifest_status: Status,
    reason: CorpusGateReason,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    call_indexes = (0, 1) if corpus_name == "retained" else (2, 3)
    for call_index in call_indexes:
        runner.manifest_overrides[call_index] = project_run(
            _status_batch(manifest_status),
            elapsed_seconds=Decimal(call_index + 1),
        )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (reason,)
    assert not config.baseline_path.exists()


def test_independent_output_mismatch_rejects_record_without_replacing_baseline(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    runner.manifest_overrides[1] = project_run(
        _status_batch(Status.RECONCILED),
        elapsed_seconds=Decimal(2),
    ).model_copy(update={"json_digest": "f" * 64})

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.JSON_DRIFT,)
    assert not config.baseline_path.exists()


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
        manifest_overrides={
            call_index: project_run(
                _status_batch(Status.RECONCILED),
                elapsed_seconds=Decimal(call_index + 1),
            ).model_copy(update={"json_digest": "f" * 64})
            for call_index in (0, 1)
        },
    )
    verify_config = record_config.model_copy(
        update={
            "work_dir": tmp_path / "private" / "verify-run",
            "runtime_tolerance_ratio": None,
            "baseline_sha256": sha256(accepted_content).hexdigest(),
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
def test_verify_rejects_runtime_context_drift(
    tmp_path: Path,
    mismatch: str,
) -> None:
    record_config, record_dependencies, record_runner = _gate_fixture(tmp_path)
    run_corpus_gate(
        record_config,
        CorpusGateMode.RECORD,
        dependencies=record_dependencies,
    )
    accepted_content = record_config.baseline_path.read_bytes()
    verify_runner = _RecordingRunner(
        memberships=record_runner.memberships,
        elapsed_values=[Decimal("100")] * 4,
    )
    verify_config = record_config.model_copy(
        update={
            "work_dir": tmp_path / "private" / "verify-run",
            "runtime_tolerance_ratio": None,
            "baseline_sha256": sha256(accepted_content).hexdigest(),
            "jobs": 2 if mismatch == "jobs" else record_config.jobs,
        }
    )
    fingerprint = _toolchain("b") if mismatch == "toolchain" else _toolchain()
    verify_dependencies = CorpusGateDependencies(
        runner=verify_runner,
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(fingerprints=[fingerprint, fingerprint]),
    )

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(
            verify_config,
            CorpusGateMode.VERIFY,
            dependencies=verify_dependencies,
        )

    assert tuple(reason.value for reason in caught.value.reasons) == ("runtime_context_drift",)


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


def test_parser_failure_is_privacy_safe_and_does_not_publish_candidate(tmp_path: Path) -> None:
    config, _dependencies, _runner = _gate_fixture(tmp_path)

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
    assert not config.baseline_path.exists()


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

    original_write = corpus_gate_module._publish_json_secure

    def recording_write(
        parent_fd: int,
        name: str,
        result: CorpusBaseline,
    ) -> None:
        events.append("write")
        original_write(parent_fd, name, result)

    monkeypatch.setattr(corpus_gate_module, "_publish_json_secure", recording_write)
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


def test_swapped_private_ancestor_cannot_redirect_run_or_baseline_writes(
    tmp_path: Path,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    private_dir = tmp_path / "private"
    bound_private_dir = tmp_path / "bound-private"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    def swap_private_ancestor(index: int, _input_dir: Path) -> None:
        if index != 0:
            return
        private_dir.rename(bound_private_dir)
        private_dir.symlink_to(outside_dir, target_is_directory=True)
        (outside_dir / "run").mkdir()

    runner.on_call = swap_private_ancestor

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert len(runner.input_dirs) == 1
    outside_run_entries = tuple((outside_dir / "run").iterdir())
    assert outside_run_entries == ()
    assert not (outside_dir / "baseline.json").exists()
    assert not (bound_private_dir / "baseline.json").exists()
    assert len(tuple((bound_private_dir / "run").iterdir())) == 10


def test_private_parent_swap_immediately_before_publication_uses_bound_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, _runner = _gate_fixture(tmp_path)
    private_dir = tmp_path / "private"
    bound_private_dir = tmp_path / "bound-private"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    original_publish = corpus_gate_module._publish_json_secure

    def swap_then_publish(
        parent_fd: int,
        name: str,
        result: CorpusBaseline,
    ) -> None:
        private_dir.rename(bound_private_dir)
        private_dir.symlink_to(outside_dir, target_is_directory=True)
        original_publish(parent_fd, name, result)

    monkeypatch.setattr(corpus_gate_module, "_publish_json_secure", swap_then_publish)

    run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert not (outside_dir / "baseline.json").exists()
    assert (bound_private_dir / "baseline.json").is_file()


def test_relocation_after_final_attestation_is_rejected_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, _runner = _gate_fixture(tmp_path)
    private_dir = tmp_path / "private"
    displaced_private = tmp_path / "displaced-private"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    original_validate = corpus_gate_module._validate_final_state

    def validate_then_relocate(
        prepared: corpus_gate_module._PreparedGate,
        active_dependencies: CorpusGateDependencies,
    ) -> None:
        original_validate(prepared, active_dependencies)
        private_dir.rename(displaced_private)
        private_dir.symlink_to(outside_dir, target_is_directory=True)

    monkeypatch.setattr(corpus_gate_module, "_validate_final_state", validate_then_relocate)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert not (displaced_private / "baseline.json").exists()
    assert not (outside_dir / "baseline.json").exists()


def test_baseline_name_symlink_swap_immediately_before_publication_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, _runner = _gate_fixture(tmp_path)
    outside_baseline = tmp_path / "outside-baseline.json"
    outside_baseline.write_bytes(b"outside baseline")
    original_publish = corpus_gate_module._publish_json_secure

    def swap_then_publish(
        parent_fd: int,
        name: str,
        result: CorpusBaseline,
    ) -> None:
        (Path(f"/proc/self/fd/{parent_fd}") / name).symlink_to(outside_baseline)
        original_publish(parent_fd, name, result)

    monkeypatch.setattr(corpus_gate_module, "_publish_json_secure", swap_then_publish)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert outside_baseline.read_bytes() == b"outside baseline"
    assert config.baseline_path.is_symlink()


def test_parent_symlink_swap_immediately_before_secure_bind_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, dependencies, runner = _gate_fixture(tmp_path)
    private_dir = tmp_path / "private"
    displaced_private_dir = tmp_path / "displaced-private"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    original_bind = corpus_gate_module._bind_execution_paths

    def swap_then_bind(
        prepared: object,
    ) -> object:
        private_dir.rename(displaced_private_dir)
        private_dir.symlink_to(outside_dir, target_is_directory=True)
        return original_bind(prepared)

    monkeypatch.setattr(corpus_gate_module, "_bind_execution_paths", swap_then_bind)

    with pytest.raises(CorpusGateInputError) as caught:
        run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)
    assert runner.input_dirs == []
    assert tuple(outside_dir.iterdir()) == ()


def test_original_swap_and_restore_cannot_change_staged_parser_bytes(tmp_path: Path) -> None:
    config, _dependencies, base_runner = _gate_fixture(tmp_path)
    retained_source = config.retained_dir / "retained.pdf"
    seen_inputs: list[bytes] = []

    class SwapRestoreRunner:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(
            self,
            *,
            input_dir: Path,
            output_dir: Path,
            cache_dir: Path,
            strict: bool,
            jobs: int,
        ) -> CompletedCorpusRun:
            del output_dir, cache_dir, jobs
            if self.calls == 0:
                retained_source.write_bytes(b"unapproved")
            try:
                source = next(input_dir.resolve(strict=True).rglob("*.pdf"))
                seen_inputs.append(source.read_bytes())
            finally:
                if self.calls == 0:
                    retained_source.write_bytes(b"retained")
            membership = (
                base_runner.memberships[config.retained_dir.resolve()]
                if strict
                else base_runner.memberships[config.quarantine_dir.resolve()]
            )
            status = Status.RECONCILED if strict else Status.NOT_STATEMENT
            batch = _status_batch(status)
            completed = CompletedCorpusRun(
                batch_status=batch.status,
                manifest=project_run(batch, elapsed_seconds=Decimal(1)),
                membership_before=membership,
                membership_after=membership,
            )
            self.calls += 1
            return completed

    dependencies = CorpusGateDependencies(
        runner=SwapRestoreRunner(),
        repository=_FakeRepository(tmp_path),
        toolchain=_FakeToolchain(),
    )

    run_corpus_gate(config, CorpusGateMode.RECORD, dependencies=dependencies)

    assert seen_inputs == [b"retained", b"retained", b"quarantine", b"quarantine"]


def test_local_runner_streams_exact_outputs_without_retaining_batch(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    source_contents = {
        "a.pdf": b"a",
        "b.pdf": b"b",
        "c.pdf": b"c",
    }
    for source_name, content in source_contents.items():
        (input_dir / source_name).write_bytes(content)
    statements = tuple(
        StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name=source_name,
            source_sha256=sha256(content).hexdigest(),
            statement_id=sha256(content).hexdigest(),
        )
        for source_name, content in source_contents.items()
    )
    expected_batch = BatchResult(status=Status.RECONCILED, statements=statements)
    c_completed = threading.Event()
    b_completed = threading.Event()
    completion_order: list[str] = []
    result_references: list[weakref.ReferenceType[StatementResult]] = []

    def parse(
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        source = Path(path)
        content = source.read_bytes()
        result = StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name=source.name,
            source_sha256=sha256(content).hexdigest(),
            statement_id=sha256(content).hexdigest(),
        )
        result_references.append(weakref.ref(result))
        if source.name == "a.pdf":
            assert b_completed.wait(timeout=5)
        elif source.name == "b.pdf":
            assert c_completed.wait(timeout=5)
        completion_order.append(source.name)
        if source.name == "c.pdf":
            c_completed.set()
        elif source.name == "b.pdf":
            b_completed.set()
        return result

    clock_values = iter((1_000_000_000, 2_250_000_000))
    runner = LocalCorpusRunner(
        statement_parser=parse,
        monotonic_ns=lambda: next(clock_values),
    )

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=3,
    )

    expected = project_run(expected_batch, elapsed_seconds=Decimal("1.25"))
    expected_membership = digest_membership(
        sha256(content).hexdigest() for content in source_contents.values()
    )
    assert completion_order == ["c.pdf", "b.pdf", "a.pdf"]
    assert completed.batch_status is expected_batch.status
    assert completed.manifest == expected
    assert completed.membership_before == expected_membership
    assert completed.membership_after == expected_membership
    assert (output_dir / "results.json").read_bytes() == canonical_json_bytes(expected_batch)
    assert (output_dir / "transactions.csv").read_bytes() == transactions_csv_bytes(expected_batch)
    assert not tuple(output_dir.glob(".statement-spool*"))
    gc.collect()
    assert all(reference() is None for reference in result_references)


def test_local_runner_streams_the_exact_empty_batch(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    clock_values = iter((1_000_000_000, 1_500_000_000))
    runner = LocalCorpusRunner(monotonic_ns=lambda: next(clock_values))

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=1,
    )

    expected_batch = BatchResult(
        status=Status.UNSUPPORTED,
        statements=(),
        diagnostics=("no_pdf_files",),
    )
    assert completed.batch_status is Status.UNSUPPORTED
    assert completed.manifest == project_run(
        expected_batch,
        elapsed_seconds=Decimal("0.5"),
    )
    assert completed.membership_before == digest_membership(())
    assert completed.membership_after == digest_membership(())
    assert (output_dir / "results.json").read_bytes() == canonical_json_bytes(expected_batch)
    assert (output_dir / "transactions.csv").read_bytes() == transactions_csv_bytes(expected_batch)
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_snapshots_membership_immediately_around_streaming(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    source = input_dir / "statement.pdf"
    source.write_bytes(b"before")

    def parse_then_mutate(
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        selected = Path(path)
        content = selected.read_bytes()
        digest = sha256(content).hexdigest()
        selected.write_bytes(b"after")
        return StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name=selected.name,
            source_sha256=digest,
            statement_id=digest,
        )

    runner = LocalCorpusRunner(statement_parser=parse_then_mutate)

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=1,
    )

    assert completed.membership_before == digest_membership((sha256(b"before").hexdigest(),))
    assert completed.membership_after == digest_membership((sha256(b"after").hexdigest(),))
    assert not tuple(output_dir.glob(".statement-spool*"))


def _reconciled_statement_parser(
    path: str | Path,
    strict: bool = False,
    *,
    cache_dir: str | Path | None = None,
) -> StatementResult:
    del strict, cache_dir
    source = Path(path)
    digest = sha256(source.read_bytes()).hexdigest()
    return StatementResult(
        status=Status.RECONCILED,
        transactions=(),
        groups=(),
        source_name=source.name,
        source_sha256=digest,
        statement_id=digest,
    )


def test_local_runner_selects_trusted_policy_for_descriptor_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    descriptors = tuple(
        os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        for directory in (input_dir, output_dir, cache_dir)
    )
    proc_paths = tuple(Path(f"/proc/self/fd/{descriptor}") for descriptor in descriptors)
    policies: list[DirectoryRootPolicy] = []
    original_convert = corpus_gate_module.convert_directory_statements

    def record_policy(*args: object, **kwargs: object) -> object:
        policy = kwargs["directory_root_policy"]
        assert isinstance(policy, DirectoryRootPolicy)
        policies.append(policy)
        return original_convert(*args, **kwargs)

    monkeypatch.setattr(
        corpus_gate_module,
        "convert_directory_statements",
        record_policy,
    )

    clock_values = iter((1_000_000_000, 2_000_000_000))
    runner = LocalCorpusRunner(
        statement_parser=_reconciled_statement_parser,
        monotonic_ns=lambda: next(clock_values),
    )
    try:
        runner(
            input_dir=proc_paths[0],
            output_dir=proc_paths[1],
            cache_dir=proc_paths[2],
            strict=True,
            jobs=1,
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)

    assert policies == [DirectoryRootPolicy.TRUSTED_DESCRIPTOR]


@pytest.mark.parametrize("filename", ("results.json", "transactions.csv"))
@pytest.mark.parametrize("failure", ("missing", "mismatch"))
def test_local_runner_rejects_tampered_streamed_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    failure: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    input_dir.mkdir()
    output_dir.mkdir()
    cache_dir.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    original_write = corpus_gate_module.write_streaming_batch_outputs

    def write_then_tamper(
        path: str | Path,
        *,
        status: Status,
        diagnostics: tuple[str, ...],
        statements: Callable[[], Iterator[StatementResult]],
    ) -> None:
        original_write(
            path,
            status=status,
            diagnostics=diagnostics,
            statements=statements,
        )
        emitted_path = Path(path) / filename
        if failure == "missing":
            emitted_path.unlink()
        else:
            emitted_path.write_bytes(b"private tampered output")

    monkeypatch.setattr(
        corpus_gate_module,
        "write_streaming_batch_outputs",
        write_then_tamper,
    )
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private tampered" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_rejects_a_corrupt_spool_record_privately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    original_write = corpus_gate_module.write_streaming_batch_outputs

    def write_then_corrupt(
        path: str | Path,
        *,
        status: Status,
        diagnostics: tuple[str, ...],
        statements: Callable[[], Iterator[StatementResult]],
    ) -> None:
        original_write(
            path,
            status=status,
            diagnostics=diagnostics,
            statements=statements,
        )
        spool_directory = next(Path(path).glob(".statement-spool-*"))
        record = next(spool_directory.iterdir())
        record.chmod(0o600)
        record.write_bytes(b"private corrupt spool record")

    monkeypatch.setattr(
        corpus_gate_module,
        "write_streaming_batch_outputs",
        write_then_corrupt,
    )
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private corrupt" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_cleans_the_spool_after_a_late_parser_failure(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    for source_name in ("a.pdf", "b.pdf", "c.pdf"):
        (input_dir / source_name).write_bytes(source_name.encode())
    parsed = 0

    def fail_second(
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        nonlocal parsed
        parsed += 1
        if parsed == 2:
            raise RuntimeError("private parser failure at document two")
        return _reconciled_statement_parser(path, strict, cache_dir=cache_dir)

    runner = LocalCorpusRunner(statement_parser=fail_second)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert parsed == 2
    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private parser" not in "".join(traceback.format_exception(caught.value))
    assert not (output_dir / "results.json").exists()
    assert not (output_dir / "transactions.csv").exists()
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_cleans_the_spool_after_an_output_writer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")

    def fail_write(
        path: str | Path,
        *,
        status: Status,
        diagnostics: tuple[str, ...],
        statements: Callable[[], Iterator[StatementResult]],
    ) -> None:
        del path, status, diagnostics, statements
        raise RuntimeError("private output writer failure")

    monkeypatch.setattr(
        corpus_gate_module,
        "write_streaming_batch_outputs",
        fail_write,
    )
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private output" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_translates_a_spool_close_failure_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    original_close = StatementSpool.close

    def close_then_fail(spool: StatementSpool) -> None:
        original_close(spool)
        raise RuntimeError("private spool close failure")

    monkeypatch.setattr(StatementSpool, "close", close_then_fail)
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private spool" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_rejects_a_negative_elapsed_clock_privately(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    clock_values = iter((2_000_000_000, 1_000_000_000))
    runner = LocalCorpusRunner(
        statement_parser=_reconciled_statement_parser,
        monotonic_ns=lambda: next(clock_values),
    )

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "clock moved" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))


def test_local_runner_hashes_emitted_outputs_without_path_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    original_read_bytes = Path.read_bytes

    def reject_output_read_bytes(path: Path) -> bytes:
        if path.name in {"results.json", "transactions.csv"}:
            raise AssertionError("emitted outputs must be hashed incrementally")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_output_read_bytes)
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=1,
    )

    assert completed.batch_status is Status.RECONCILED
    assert completed.manifest.counts.documents == 1
    assert not tuple(output_dir.glob(".statement-spool*"))


def _runtime_git_repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository_root = tmp_path / "runtime-repository"
    package_module = repository_root / "src" / "ccparser" / "__init__.py"
    gate_module = repository_root / "src" / "ccparser" / "corpus_gate.py"
    parser_module = repository_root / "src" / "ccparser" / "parser.py"
    gate_module.parent.mkdir(parents=True)
    package_module.write_text("# synthetic package\n", encoding="utf-8")
    gate_module.write_text(
        "def gate_value() -> str:\n    return 'head'\n",
        encoding="utf-8",
    )
    parser_module.write_text(
        "PARSER_VALUE = 'head'\n"
        "def parser_value(value: str = PARSER_VALUE) -> str:\n"
        "    return value\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "init", "-b", "main"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "Corpus Gate Test"),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.email", "corpus-gate@example.invalid"),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "add", "src/ccparser"),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "commit", "-m", "runtime source"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return repository_root, gate_module, parser_module


def test_package_runtime_registry_contains_only_executed_package_top_levels() -> None:
    package = sys.modules["ccparser"]
    package_file = package.__file__
    gate_file = corpus_gate_module.__file__
    assert isinstance(package_file, str)
    assert isinstance(gate_file, str)
    package_dir = Path(package_file).resolve(strict=True).parent
    registry = vars(package).get("_EXECUTED_PACKAGE_CODES")
    assert isinstance(registry, dict)
    gate_path = Path(gate_file).resolve(strict=True)
    gate_codes = registry.get(str(gate_path))
    assert isinstance(gate_codes, set)
    expected_gate_code = compile(
        gate_path.read_bytes(),
        gate_file,
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    assert expected_gate_code in gate_codes
    assert all(
        isinstance(path, str)
        and Path(path).is_relative_to(package_dir)
        and isinstance(codes, set)
        and codes
        and all(isinstance(code, CodeType) and code.co_name == "<module>" for code in codes)
        for path, codes in registry.items()
    )


@pytest.mark.parametrize("mask_flag", ("--assume-unchanged", "--skip-worktree"))
@pytest.mark.parametrize("modify_source", (False, True), ids=("unchanged", "modified"))
def test_git_repository_inspector_rejects_index_masking_of_runtime_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mask_flag: str,
    modify_source: bool,
) -> None:
    repository_root, gate_module, parser_module = _runtime_git_repository(tmp_path)
    subprocess.run(
        ("git", "update-index", mask_flag, "src/ccparser/parser.py"),
        cwd=repository_root,
        check=True,
    )
    if modify_source:
        parser_module.write_text("PARSER_VALUE = 'masked'\n", encoding="utf-8")
    status = subprocess.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    assert status.stdout == b""
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(gate_module),
    )

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(repository_root) not in str(caught.value)


def test_git_repository_inspector_rejects_stale_loaded_bytecode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, _parser_module = _runtime_git_repository(tmp_path)
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(
            gate_module,
            loaded_source=b"GATE_VALUE = 'stale bytecode'\n",
        ),
    )

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(gate_module) not in str(caught.value)


def test_git_repository_inspector_rejects_executed_source_restored_before_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, _parser_module = _runtime_git_repository(tmp_path)
    approved_source = gate_module.read_bytes()
    stale_source = b"def gate_value() -> str:\n    return 'stale'\n"
    gate_module.write_bytes(stale_source)
    module_name = "ccparser.corpus_gate"
    loader = SourceFileLoader(module_name, str(gate_module))
    specification = ModuleSpec(module_name, loader, origin=str(gate_module))
    loaded_module = module_from_spec(specification)
    loaded_module.__file__ = str(gate_module)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    loader.exec_module(loaded_module)
    loaded_module.__dict__["_TEST_EXECUTED_TOP_LEVEL_CODE"] = compile(
        stale_source,
        str(gate_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    gate_value = loaded_module.__dict__["gate_value"]
    assert callable(gate_value)
    assert gate_value() == "stale"
    gate_module.write_bytes(approved_source)
    assert loader.get_code(module_name) == compile(
        approved_source,
        str(gate_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(monkeypatch, loaded_module)

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(gate_module) not in str(caught.value)


def test_git_repository_inspector_rejects_restored_dependency_with_stale_import_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, parser_module = _runtime_git_repository(tmp_path)
    approved_source = parser_module.read_bytes()
    stale_source = approved_source.replace(b"PARSER_VALUE = 'head'", b"PARSER_VALUE = 'stale'")
    parser_module.write_bytes(stale_source)
    module_name = "ccparser.parser"
    loader = SourceFileLoader(module_name, str(parser_module))
    specification = ModuleSpec(module_name, loader, origin=str(parser_module))
    loaded_module = module_from_spec(specification)
    loaded_module.__file__ = str(parser_module)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    loader.exec_module(loaded_module)
    loaded_module.__dict__["_TEST_EXECUTED_TOP_LEVEL_CODE"] = compile(
        stale_source,
        str(parser_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    parser_value = loaded_module.__dict__["parser_value"]
    assert callable(parser_value)
    assert parser_value() == "stale"
    parser_module.write_bytes(approved_source)
    approved_code = compile(
        approved_source,
        str(parser_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    assert loader.get_code(module_name) == approved_code
    approved_namespace: dict[str, object] = {}
    exec(approved_code, approved_namespace)
    approved_parser_value = approved_namespace["parser_value"]
    assert callable(approved_parser_value)
    assert parser_value.__code__ == approved_parser_value.__code__
    assert parser_value.__defaults__ != approved_parser_value.__defaults__
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(gate_module),
        loaded_module,
    )

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(parser_module) not in str(caught.value)


def test_git_repository_inspector_rejects_approved_reload_coexisting_with_stale_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, parser_module = _runtime_git_repository(tmp_path)
    approved_source = parser_module.read_bytes()
    stale_source = approved_source.replace(b"PARSER_VALUE = 'head'", b"PARSER_VALUE = 'stale'")
    parser_module.write_bytes(stale_source)
    module_name = "ccparser.parser"
    loader = SourceFileLoader(module_name, str(parser_module))
    specification = ModuleSpec(module_name, loader, origin=str(parser_module))
    loaded_module = module_from_spec(specification)
    loaded_module.__file__ = str(parser_module)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    loader.exec_module(loaded_module)
    stale_code = compile(
        stale_source,
        str(parser_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    loaded_module.__dict__["_TEST_EXECUTED_TOP_LEVEL_CODE"] = stale_code
    stale_parser_value = loaded_module.__dict__["parser_value"]
    assert callable(stale_parser_value)
    assert stale_parser_value() == "stale"
    parser_module.write_bytes(approved_source)
    approved_code = compile(
        approved_source,
        str(parser_module),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(gate_module),
        loaded_module,
    )
    package = sys.modules["ccparser"]
    registry = vars(package)["_EXECUTED_PACKAGE_CODES"]
    assert isinstance(registry, dict)
    registered = registry[str(parser_module.resolve(strict=True))]
    assert isinstance(registered, set)
    registered.add(approved_code)

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(parser_module) not in str(caught.value)


def test_git_repository_inspector_rejects_replacement_commit_for_pinned_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, parser_module = _runtime_git_repository(tmp_path)
    approved_commit = (
        subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    gate_module.write_text(
        "def gate_value() -> str:\n    return 'replacement'\n",
        encoding="utf-8",
    )
    parser_module.write_text("PARSER_VALUE = 'replacement'\n", encoding="utf-8")
    subprocess.run(("git", "add", "src/ccparser"), cwd=repository_root, check=True)
    subprocess.run(
        ("git", "commit", "-m", "replacement runtime"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    replacement_commit = (
        subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    subprocess.run(
        ("git", "switch", "--detach", approved_commit),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "replace", approved_commit, replacement_commit),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "reset", "--hard", "HEAD"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    status = subprocess.run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    assert status.stdout == b""
    assert (
        subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
        == approved_commit
    )
    assert gate_module.read_text(encoding="utf-8").endswith("return 'replacement'\n")
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(gate_module),
    )

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=repository_root).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert approved_commit not in str(caught.value)
    assert replacement_commit not in str(caught.value)


def test_git_repository_inspector_supports_nested_repository_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root, gate_module, _parser_module = _runtime_git_repository(tmp_path)
    nested_cwd = repository_root / "nested" / "command"
    nested_cwd.mkdir(parents=True)
    monkeypatch.setattr(corpus_gate_module, "__file__", str(gate_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(gate_module),
    )

    state = GitRepositoryInspector(cwd=nested_cwd).state()

    assert state.root == repository_root
    assert state.clean is True


def test_git_repository_inspector_rejects_state_change_during_runtime_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_root = tmp_path / "active"
    project_root = tmp_path / "project"
    active_root.mkdir()
    project_root.mkdir()
    inspector = GitRepositoryInspector(cwd=active_root)
    first_commit = "d" * 40
    second_commit = "e" * 40
    observations = iter(((first_commit, b""), (second_commit, b"")))
    monkeypatch.setattr(
        inspector,
        "_validate_active_worktree_package",
        lambda: active_root,
    )
    monkeypatch.setattr(inspector, "_read_project_root", lambda: project_root)
    monkeypatch.setattr(inspector, "_repository_observation", lambda: next(observations))
    monkeypatch.setattr(
        inspector,
        "_validate_runtime_attribution",
        lambda _active_root, _commit_sha: None,
    )

    with pytest.raises(RuntimeError) as caught:
        inspector.state()

    assert str(caught.value) == "active worktree package unavailable"
    assert first_commit not in str(caught.value)
    assert second_commit not in str(caught.value)


@pytest.mark.parametrize("replacement_kind", ("inode", "content"))
def test_git_repository_inspector_executes_the_bound_executable_after_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    executable = executable_directory / "git"
    poisoned_environment_marker = tmp_path / "poisoned-environment-observed"
    approved_content = (
        "#!/bin/sh\n"
        f"if [ -n \"${{LD_PRELOAD-}}\" ]; then : > '{poisoned_environment_marker}'; fi\n"
        "printf 'approved\\n'\n"
    ).encode()
    executable.write_bytes(approved_content)
    executable.chmod(0o700)
    substitute_marker = tmp_path / "substitute-executed"
    substitute = executable_directory / "substitute"
    substitute.write_text(
        f"#!/bin/sh\nprintf 'substitute\\n'\n: > '{substitute_marker}'\n",
        encoding="utf-8",
    )
    substitute.chmod(0o700)
    monkeypatch.setenv("PATH", str(executable_directory))
    monkeypatch.setenv("LD_PRELOAD", str(tmp_path / "untrusted-library.so"))

    inspector = GitRepositoryInspector(cwd=tmp_path)
    if replacement_kind == "inode":
        os.replace(substitute, executable)
    else:
        executable.write_bytes(substitute.read_bytes())
        executable.chmod(0o700)

    try:
        assert inspector._git_output("--version") == b"approved\n"
        assert inspector.executable_asset.sha256 == sha256(approved_content).hexdigest()
        assert not substitute_marker.exists()
        assert not poisoned_environment_marker.exists()
    finally:
        inspector.close()


def test_git_repository_inspector_uses_common_parent_and_active_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    common_dir = project_root / ".git"
    active_worktree = project_root / ".worktrees" / "active"
    active_module = active_worktree / "src" / "ccparser" / "corpus_gate.py"
    package_module = active_module.with_name("__init__.py")
    common_dir.mkdir(parents=True)
    active_module.parent.mkdir(parents=True)
    package_module.write_text("# synthetic package\n", encoding="utf-8")
    active_module.write_text("# active gate module\n", encoding="utf-8")
    commands: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        stdout: int | None = None,
        stderr: int | None = None,
        capture_output: bool = False,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, capture_output, timeout
        assert env["PATH"] == "/nonexistent"
        assert "LD_PRELOAD" not in env
        assert pass_fds and command[0] == f"/proc/self/fd/{pass_fds[0]}"
        commands.append((command, cwd))
        arguments = command[2:]
        if arguments == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(command, 0, f"{active_worktree}\n".encode(), b"")
        if arguments == ("rev-parse", "--path-format=absolute", "--git-common-dir"):
            output = f"{common_dir}\n".encode()
            return subprocess.CompletedProcess(command, 0, output, b"")
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(command, 0, b"d" * 40 + b"\n", b"")
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if arguments == (
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            "d" * 40,
            "--",
            ":(top,literal)src/ccparser",
        ):
            output = (
                b"100644 blob "
                + b"a" * 40
                + b"\tsrc/ccparser/__init__.py\0"
                + b"100644 blob "
                + b"b" * 40
                + b"\tsrc/ccparser/corpus_gate.py\0"
            )
            return subprocess.CompletedProcess(command, 0, output, b"")
        if arguments == (
            "ls-files",
            "-v",
            "-z",
            "--full-name",
            "--",
            ":(top,literal)src/ccparser",
        ):
            output = b"H src/ccparser/__init__.py\0H src/ccparser/corpus_gate.py\0"
            return subprocess.CompletedProcess(command, 0, output, b"")
        if arguments == ("cat-file", "blob", "a" * 40):
            return subprocess.CompletedProcess(command, 0, package_module.read_bytes(), b"")
        if arguments == ("cat-file", "blob", "b" * 40):
            return subprocess.CompletedProcess(command, 0, active_module.read_bytes(), b"")
        if arguments == ("worktree", "list", "--porcelain", "-z"):
            output = (
                b"worktree "
                + os.fsencode(project_root)
                + b"\0\0worktree "
                + os.fsencode(active_worktree)
                + b"\0\0"
            )
            return subprocess.CompletedProcess(command, 0, output, b"")
        if arguments[:2] == ("check-ignore", "--quiet"):
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError("unexpected Git command")

    monkeypatch.setattr(corpus_gate_module.subprocess, "run", fake_run)
    monkeypatch.setattr(corpus_gate_module, "__file__", str(active_module))
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(active_module),
    )
    inspector = GitRepositoryInspector(cwd=active_worktree)

    state = inspector.state()
    ignored = inspector.is_ignored(project_root / "private" / "baseline.json")

    assert state == RepositoryState(root=project_root, commit_sha="d" * 40, clean=True)
    assert ignored is True
    normalized_commands = [(("git", *command[1:]), cwd) for command, cwd in commands]
    state_commands = normalized_commands[:10]
    ignore_commands = normalized_commands[10:]
    assert all(cwd == active_worktree for _command, cwd in state_commands)
    assert tuple(command[0] for command in state_commands) == (
        ("git", "--no-replace-objects", "rev-parse", "--show-toplevel"),
        (
            "git",
            "--no-replace-objects",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ),
        ("git", "--no-replace-objects", "rev-parse", "--verify", "HEAD"),
        (
            "git",
            "--no-replace-objects",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ),
        (
            "git",
            "--no-replace-objects",
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            "d" * 40,
            "--",
            ":(top,literal)src/ccparser",
        ),
        (
            "git",
            "--no-replace-objects",
            "ls-files",
            "-v",
            "-z",
            "--full-name",
            "--",
            ":(top,literal)src/ccparser",
        ),
        ("git", "--no-replace-objects", "cat-file", "blob", "a" * 40),
        ("git", "--no-replace-objects", "cat-file", "blob", "b" * 40),
        ("git", "--no-replace-objects", "rev-parse", "--verify", "HEAD"),
        (
            "git",
            "--no-replace-objects",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ),
    )
    assert ignore_commands == [
        (
            (
                "git",
                "--no-replace-objects",
                "worktree",
                "list",
                "--porcelain",
                "-z",
            ),
            active_worktree,
        ),
        (
            (
                "git",
                "--no-replace-objects",
                "check-ignore",
                "--quiet",
                "--",
                str(project_root / "private" / "baseline.json"),
            ),
            project_root,
        ),
    ]


def test_git_repository_inspector_rejects_package_from_another_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    common_dir = project_root / ".git"
    active_worktree = project_root / ".worktrees" / "active"
    active_module = active_worktree / "src" / "ccparser" / "corpus_gate.py"
    imported_module = project_root / "src" / "ccparser" / "corpus_gate.py"
    common_dir.mkdir(parents=True)
    active_module.parent.mkdir(parents=True)
    imported_module.parent.mkdir(parents=True)
    active_module.write_text("# active gate module\n", encoding="utf-8")
    imported_module.write_text("# different imported module\n", encoding="utf-8")

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, check, capture_output, timeout
        assert env["PATH"] == "/nonexistent"
        assert pass_fds and command[0] == f"/proc/self/fd/{pass_fds[0]}"
        arguments = command[2:]
        if arguments == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(command, 0, f"{active_worktree}\n".encode(), b"")
        if arguments == ("rev-parse", "--path-format=absolute", "--git-common-dir"):
            return subprocess.CompletedProcess(command, 0, f"{common_dir}\n".encode(), b"")
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(command, 0, b"d" * 40 + b"\n", b"")
        if arguments == ("status", "--porcelain=v1", "--untracked-files=all"):
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError("unexpected Git command")

    monkeypatch.setattr(corpus_gate_module.subprocess, "run", fake_run)
    monkeypatch.setattr(corpus_gate_module, "__file__", str(imported_module))

    with pytest.raises(RuntimeError) as caught:
        GitRepositoryInspector(cwd=active_worktree).state()

    assert str(caught.value) == "active worktree package unavailable"
    assert str(active_worktree) not in str(caught.value)
    assert str(imported_module) not in str(caught.value)


def test_git_ignore_uses_deepest_linked_worktree_for_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repository"
    linked_worktree = repository_root / ".worktrees" / "linked"
    repository_root.mkdir()
    subprocess.run(
        ("git", "init", "-b", "main"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "config", "user.name", "Corpus Gate Test"),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.email", "corpus-gate@example.invalid"),
        cwd=repository_root,
        check=True,
    )
    (repository_root / ".gitignore").write_text(
        ".worktrees/\nartifacts/\n",
        encoding="utf-8",
    )
    (repository_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    module_path = repository_root / "src" / "ccparser" / "corpus_gate.py"
    package_path = module_path.with_name("__init__.py")
    module_path.parent.mkdir(parents=True)
    package_path.write_text("# synthetic package\n", encoding="utf-8")
    module_path.write_text("# synthetic active module\n", encoding="utf-8")
    subprocess.run(
        ("git", "add", ".gitignore", "tracked.txt", "src/ccparser"),
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ("git", "commit", "-m", "initial"),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("git", "worktree", "add", "-b", "linked", str(linked_worktree)),
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        corpus_gate_module,
        "__file__",
        str(linked_worktree / "src" / "ccparser" / "corpus_gate.py"),
    )
    _install_synthetic_runtime_module(
        monkeypatch,
        _synthetic_runtime_module(linked_worktree / "src" / "ccparser" / "corpus_gate.py"),
    )
    inspector = GitRepositoryInspector(cwd=linked_worktree)
    inspector.state()

    assert inspector.is_ignored(linked_worktree / "tracked.txt") is False
    assert inspector.is_ignored(linked_worktree / "artifacts" / "private.json") is True


def test_local_toolchain_fingerprint_hashes_versions_caches_and_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract"
    executable.write_bytes(b"synthetic tesseract executable")
    executable.chmod(0o700)
    tessdata = tmp_path / "tessdata"
    (tessdata / "configs").mkdir(parents=True)
    (tessdata / "configs" / "tsv").write_bytes(b"tsv config")
    (tessdata / "eng.traineddata").write_bytes(b"english data")
    (tessdata / "heb.traineddata").write_bytes(b"hebrew data")
    monkeypatch.setattr(corpus_gate_module.platform, "python_version", lambda: "3.13.5")
    monkeypatch.setattr(
        corpus_gate_module.platform,
        "python_implementation",
        lambda: "CPython",
    )
    versions = {
        name: f"1.0.{index}"
        for index, name in enumerate(corpus_gate_module._RUNTIME_DEPENDENCY_NAMES)
    }
    installed_snapshots = corpus_gate_module._runtime_dependency_snapshots()
    synthetic_snapshots = tuple(
        corpus_gate_module._RuntimeDistributionSnapshot(
            dependency=snapshot.dependency.model_copy(
                update={"version": versions[snapshot.dependency.name]}
            ),
            installation_root=snapshot.installation_root,
            artifact_paths=snapshot.artifact_paths,
            source_origins=snapshot.source_origins,
            bytecode_origins=snapshot.bytecode_origins,
            native_origins=snapshot.native_origins,
        )
        for snapshot in installed_snapshots
    )
    monkeypatch.setattr(
        corpus_gate_module,
        "_runtime_dependency_snapshots",
        lambda: synthetic_snapshots,
    )
    standard_library = corpus_gate_module._StandardLibrarySnapshot(
        identity=RuntimeArtifactIdentity(
            file_count=1,
            size_bytes=1,
            digest="6" * 64,
        ),
        artifact_paths=frozenset(),
        source_origins=frozenset(),
        bytecode_origins=frozenset(),
        native_origins=frozenset(),
    )
    origin_checks: list[tuple[object, object]] = []
    monkeypatch.setattr(corpus_gate_module, "_snapshot_standard_library", lambda: standard_library)

    def validate_origins(
        snapshots: object,
        *,
        standard_library: object,
    ) -> None:
        origin_checks.append((snapshots, standard_library))

    monkeypatch.setattr(
        corpus_gate_module,
        "_validate_loaded_distribution_origins",
        validate_origins,
    )
    monkeypatch.setattr(corpus_gate_module.fitz, "VersionBind", "1.28.0")
    monkeypatch.setattr(corpus_gate_module.fitz, "mupdf_version", "1.29.0")
    monkeypatch.setattr(corpus_gate_module, "_python_runtime_digest", lambda: "e" * 64)
    monkeypatch.setattr(corpus_gate_module, "_runtime_environment_digest", lambda: "f" * 64)
    monkeypatch.setattr(corpus_gate_module.shutil, "which", lambda _command: str(executable))

    def fake_run(
        command: tuple[str, ...],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, timeout
        assert env["PATH"] == "/nonexistent"
        assert pass_fds and command[0] == f"/proc/self/fd/{pass_fds[0]}"
        if command[-1] == "--version":
            output = b"tesseract 5.7.1\nbuild details\n"
        elif command[-1] == "--list-langs":
            output = f'List of available languages in "{tessdata}" (2):\neng\nheb\n'.encode()
        else:
            raise AssertionError("unexpected command")
        return subprocess.CompletedProcess(command, 0, output, b"")

    _install_synthetic_dynamic_runtime(monkeypatch, fake_run)
    inspector = LocalToolchainInspector()

    try:
        first = inspector.fingerprint()
        monkeypatch.setattr(
            corpus_gate_module,
            "tesseract_command",
            lambda: (*ocr_module.tesseract_command(), "--changed"),
        )
        changed = inspector.fingerprint()
    finally:
        inspector.close()

    assert first.version == 6
    assert first.standard_library == standard_library.identity
    assert origin_checks == [
        (synthetic_snapshots, standard_library),
        (synthetic_snapshots, standard_library),
    ]
    assert first.python_version == "3.13.5"
    assert first.python_implementation == "CPython"
    assert tuple(dependency.name for dependency in first.dependencies) == (
        corpus_gate_module._RUNTIME_DEPENDENCY_NAMES
    )
    assert tuple(dependency.version for dependency in first.dependencies) == tuple(
        versions[name] for name in corpus_gate_module._RUNTIME_DEPENDENCY_NAMES
    )
    assert first.pymupdf_binding_version == "1.28.0"
    assert first.pymupdf_engine_version == "1.29.0"
    assert first.tesseract_version == "tesseract 5.7.1"
    assert (
        first.tesseract_version_output_digest
        == sha256(b"tesseract 5.7.1\nbuild details\n").hexdigest()
    )
    assert tuple(asset.role for asset in first.tesseract_assets) == (
        corpus_gate_module._TOOLCHAIN_ASSET_ROLES
    )
    serialized = first.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "english data" not in serialized
    assert first.ocr_pipeline_version == corpus_gate_module.OCR_PIPELINE_VERSION
    assert first.ocr_cache_versions == tuple(sorted(first.ocr_cache_versions))
    assert (
        corpus_gate_module.OCR_CURRENCY_RECOGNITION_CACHE_VERSION
        == ocr_module.OCR_CURRENCY_RECOGNITION_CACHE_VERSION
    )
    assert ocr_module.OCR_CURRENCY_RECOGNITION_CACHE_VERSION in first.ocr_cache_versions
    assert first.command_digest != changed.command_digest
    assert first.digest != changed.digest


def test_standard_library_byte_mutation_changes_aggregate_identity_without_paths(
    tmp_path: Path,
) -> None:
    snapshotter = getattr(corpus_gate_module, "_snapshot_standard_library", None)
    assert callable(snapshotter), "standard-library inventory is missing"
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    source = standard_library / "synthetic_stdlib.py"
    source.write_bytes(b"APPROVED = 1\n")

    before = snapshotter((standard_library,))
    source.write_bytes(b"SUBSTITUTED!\n")
    after = snapshotter((standard_library,))

    assert before.identity != after.identity
    serialized = before.identity.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "APPROVED" not in serialized


def test_standard_library_resource_mutation_changes_aggregate_identity(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    (standard_library / "importable.py").write_bytes(b"VALUE = 1\n")
    resource = standard_library / "resources" / "defaults.json"
    resource.parent.mkdir()
    resource.write_bytes(b'{"mode":"approved"}\n')

    before = corpus_gate_module._snapshot_standard_library((standard_library,))
    resource.write_bytes(b'{"mode":"changed!"}\n')
    after = corpus_gate_module._snapshot_standard_library((standard_library,))

    assert before.identity != after.identity


def test_standard_library_inventory_excludes_distribution_roots(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    (standard_library / "decimal.py").write_bytes(b"APPROVED = 1\n")
    installed = standard_library / "site-packages" / "unapproved_runtime.py"
    installed.parent.mkdir()
    installed.write_bytes(b"VALUE = 1\n")

    before = corpus_gate_module._snapshot_standard_library((standard_library,))
    installed.write_bytes(b"SUBSTITUTE!\n")
    after = corpus_gate_module._snapshot_standard_library((standard_library,))

    assert before.identity == after.identity
    assert installed.resolve() not in before.artifact_paths


def test_standard_library_symlink_retarget_changes_identity(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_bytes(b"SAME = 1\n")
    second.write_bytes(first.read_bytes())
    alias = standard_library / "aliased.py"
    alias.symlink_to(first)

    before = corpus_gate_module._snapshot_standard_library((standard_library,))
    alias.unlink()
    alias.symlink_to(second)
    after = corpus_gate_module._snapshot_standard_library((standard_library,))

    assert before.identity != after.identity


def test_loaded_standard_library_origin_and_cache_must_be_inventoried(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    source = standard_library / "synthetic_stdlib.py"
    source.write_bytes(b"VALUE = 1\n")
    snapshot = corpus_gate_module._snapshot_standard_library((standard_library,))
    specification = spec_from_file_location("synthetic_stdlib", source)
    assert specification is not None
    module = module_from_spec(specification)

    corpus_gate_module._validate_loaded_distribution_origins(
        (),
        standard_library=snapshot,
        loaded_modules={"synthetic_stdlib": module},
    )

    substituted_cache = tmp_path / "synthetic_stdlib.pyc"
    substituted_cache.write_bytes(b"SUBSTITUTE")
    module.__cached__ = str(substituted_cache)
    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            standard_library=snapshot,
            loaded_modules={"synthetic_stdlib": module},
        )


def test_standard_library_resource_cannot_be_used_as_module_source(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    (standard_library / "importable.py").write_bytes(b"VALUE = 1\n")
    resource = standard_library / "defaults.json"
    resource.write_bytes(b"VALUE = 2\n")
    (standard_library / "defaults_alias.py").symlink_to(resource)
    snapshot = corpus_gate_module._snapshot_standard_library((standard_library,))
    loader = SourceFileLoader("defaults", str(resource))
    specification = ModuleSpec("defaults", loader, origin=str(resource))
    module = module_from_spec(specification)
    module.__file__ = str(resource)

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            standard_library=snapshot,
            loaded_modules={"defaults": module},
        )


def test_standard_library_resource_symlink_cannot_become_a_source_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    resource = standard_library / "payload.json"
    resource.write_bytes(b"VALUE = 2\n")
    source_alias = standard_library / "payload_alias.py"
    source_alias.symlink_to(resource)
    snapshot = corpus_gate_module._snapshot_standard_library((standard_library,))
    loader = SourceFileLoader("payload_alias", str(source_alias))
    specification = ModuleSpec("payload_alias", loader, origin=str(source_alias))
    module = module_from_spec(specification)
    module.__file__ = str(source_alias)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            standard_library=snapshot,
            loaded_modules={"payload_alias": module},
        )


def test_loaded_source_module_requires_its_specification_loader(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    source = standard_library / "approved.py"
    source.write_bytes(b"VALUE = 1\n")
    snapshot = corpus_gate_module._snapshot_standard_library((standard_library,))
    specification = spec_from_file_location("approved", source)
    assert specification is not None
    module = module_from_spec(specification)
    module.__loader__ = object()

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            standard_library=snapshot,
            loaded_modules={"approved": module},
        )


def test_loaded_source_module_rejects_noncanonical_missing_cache(tmp_path: Path) -> None:
    standard_library = tmp_path / "stdlib"
    standard_library.mkdir()
    source = standard_library / "approved.py"
    source.write_bytes(b"VALUE = 1\n")
    snapshot = corpus_gate_module._snapshot_standard_library((standard_library,))
    specification = spec_from_file_location("approved", source)
    assert specification is not None
    module = module_from_spec(specification)
    module.__cached__ = str(tmp_path / "not-the-canonical-cache.pyc")

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            standard_library=snapshot,
            loaded_modules={"approved": module},
        )


def test_loaded_origin_without_closed_runtime_owner_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "site-packages" / "unapproved_runtime.py"
    source.parent.mkdir()
    source.write_bytes(b"VALUE = 1\n")
    module = ModuleType("unapproved_runtime")
    module.__file__ = str(source)
    module.__spec__ = ModuleSpec(
        "unapproved_runtime",
        SourceFileLoader("unapproved_runtime", str(source)),
        origin=str(source),
    )

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            loaded_modules={"unapproved_runtime": module},
        )


def test_frozen_standard_library_alias_is_accepted() -> None:
    module = ModuleType("importlib._bootstrap")
    module.__loader__ = FrozenImporter
    module.__spec__ = ModuleSpec(
        "_frozen_importlib",
        loader=FrozenImporter,
        origin="frozen",
    )

    corpus_gate_module._validate_loaded_distribution_origins(
        (),
        loaded_modules={"_frozen_importlib": module},
    )


def test_real_builtin_module_is_accepted() -> None:
    corpus_gate_module._validate_loaded_distribution_origins(
        (),
        loaded_modules={"sys": sys},
    )


@pytest.mark.parametrize(
    ("origin", "loader"),
    (("built-in", BuiltinImporter), ("frozen", FrozenImporter)),
)
def test_fake_builtin_or_frozen_module_is_rejected(origin: str, loader: object) -> None:
    module = ModuleType("unapproved_runtime")
    module.callback = lambda: None
    module.__loader__ = loader
    module.__spec__ = ModuleSpec(
        "unapproved_runtime",
        loader=loader,
        origin=origin,
    )

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            loaded_modules={"unapproved_runtime": module},
        )


def test_originless_native_data_module_is_accepted_but_python_code_is_rejected() -> None:
    native_data = ModuleType("array")
    native_data.NativeType = array.array

    corpus_gate_module._validate_loaded_distribution_origins(
        (),
        loaded_modules={"array": native_data},
    )

    python_code = ModuleType("runtime_data")
    python_code.callback = lambda: None
    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (),
            loaded_modules={"runtime_data": python_code},
        )


def test_toolchain_fingerprint_requires_git_executable_identity() -> None:
    git_field = ToolchainFingerprint.model_fields.get("git_executable")

    assert git_field is not None
    assert git_field.is_required()


def test_toolchain_fingerprint_requires_standard_library_identity() -> None:
    standard_library_field = ToolchainFingerprint.model_fields.get("standard_library")

    assert standard_library_field is not None
    assert standard_library_field.is_required()


def test_toolchain_fingerprint_requires_external_native_closure_identities() -> None:
    git_field = ToolchainFingerprint.model_fields.get("git_native_closure")
    tesseract_field = ToolchainFingerprint.model_fields.get("tesseract_native_closure")

    assert git_field is not None
    assert git_field.is_required()
    assert tesseract_field is not None
    assert tesseract_field.is_required()


def test_bound_dynamic_executable_uses_only_sealed_native_mappings(
    tmp_path: Path,
) -> None:
    executable_path = shutil.which("git")
    if executable_path is None:
        pytest.skip("Git is unavailable")
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        Path(executable_path),
        staging_parent=tmp_path,
    )
    try:
        completed = runtime.run(
            ("--version",),
            cwd=tmp_path,
            environment=tuple(sorted(corpus_gate_module._git_child_environment().items())),
            timeout=10.0,
        )
        required_seals = (
            fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SEAL
        )
        assert all(
            fcntl.fcntl(file_descriptor, fcntl.F_GET_SEALS) == required_seals
            for file_descriptor in runtime.executable_file_descriptors
        )
    finally:
        runtime.close()

    assert completed.returncode == 0
    assert completed.stdout.startswith(b"git version ")
    assert runtime.native_closure.file_count >= 2


def test_script_interpreter_is_part_of_the_native_closure(tmp_path: Path) -> None:
    script = tmp_path / "wrapper"
    script.write_text("#!/bin/sh\nprintf script-interpreter-bound\n", encoding="utf-8")
    script.chmod(0o700)
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        script,
        staging_parent=tmp_path,
    )
    try:
        unique = {
            capability.file_descriptor: capability
            for capability in (
                runtime.program,
                runtime.interpreter,
                *(library.capability for library in runtime.libraries),
            )
        }
        records = tuple(
            sorted((capability.size_bytes, capability.sha256) for capability in unique.values())
        )
        bindings = (
            ("program", runtime.program.sha256),
            ("interpreter", runtime.interpreter.sha256),
            *(sorted((library.alias, library.capability.sha256) for library in runtime.libraries)),
        )
        expected = RuntimeArtifactIdentity(
            file_count=len(records),
            size_bytes=sum(size for size, _digest in records),
            digest=corpus_gate_module._toolchain_payload_digest(
                {"bindings": bindings, "files": records}
            ),
        )

        assert runtime.executable.file_descriptor != runtime.program.file_descriptor
        assert runtime.native_closure == expected
    finally:
        runtime.close()


def test_traced_dynamic_executable_rejects_an_unapproved_native_mapping(
    tmp_path: Path,
) -> None:
    executable_path = shutil.which("git")
    if executable_path is None:
        pytest.skip("Git is unavailable")
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        Path(executable_path),
        staging_parent=tmp_path,
    )
    try:
        with pytest.raises(RuntimeError, match="external runtime unavailable"):
            runtime.run(
                ("--version",),
                cwd=tmp_path,
                environment=tuple(sorted(corpus_gate_module._git_child_environment().items())),
                timeout=10.0,
                allowed_file_descriptors=runtime.executable_file_descriptors[:-1],
            )
    finally:
        runtime.close()


def test_late_tesseract_plugin_mapping_is_rejected_before_execution(
    tmp_path: Path,
) -> None:
    executable_path = shutil.which("tesseract")
    if executable_path is None:
        pytest.skip("Tesseract is unavailable")
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        Path(executable_path),
        staging_parent=tmp_path,
    )
    environment = corpus_gate_module._sanitized_child_environment()
    environment.pop("SASL_PATH")
    try:
        with pytest.raises(RuntimeError, match="external runtime unavailable"):
            runtime.run(
                ("--version",),
                cwd=tmp_path,
                environment=tuple(sorted(environment.items())),
                timeout=10.0,
            )
    finally:
        runtime.close()


def test_traced_runtime_timeout_kills_the_broker_and_tracee(tmp_path: Path) -> None:
    executable_path = shutil.which("sleep")
    if executable_path is None:
        pytest.skip("sleep is unavailable")
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        Path(executable_path),
        staging_parent=tmp_path,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            runtime.run(
                ("10",),
                cwd=tmp_path,
                environment=tuple(
                    sorted(corpus_gate_module._sanitized_child_environment().items())
                ),
                timeout=0.1,
            )
    finally:
        runtime.close()


def test_traced_runtime_rejects_a_second_exec_before_target_code_runs(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "second-exec-returned"
    script = tmp_path / "wrapper"
    script.write_text(
        f"#!/bin/sh\n/bin/true\nprintf returned > '{marker}'\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        script,
        staging_parent=tmp_path,
    )
    try:
        with pytest.raises(RuntimeError, match="external runtime unavailable"):
            runtime.run(
                (),
                cwd=tmp_path,
                environment=tuple(
                    sorted(corpus_gate_module._sanitized_child_environment().items())
                ),
                timeout=10.0,
            )
    finally:
        runtime.close()

    assert not marker.exists()


def test_traced_runtime_supports_multiple_threads_via_legacy_clone_fallback(
    tmp_path: Path,
) -> None:
    runtime = corpus_gate_module._BoundDynamicExecutable.bind_path(
        Path(sys.executable),
        staging_parent=tmp_path,
    )
    program = """
import _thread

remaining = [4]
guard = _thread.allocate_lock()
done = _thread.allocate_lock()
done.acquire()

def finish():
    with guard:
        remaining[0] -= 1
        if remaining[0] == 0:
            done.release()

for _ in range(4):
    _thread.start_new_thread(finish, ())
done.acquire()
print("threads-complete")
"""
    try:
        completed = runtime.run(
            ("-I", "-S", "-c", program),
            cwd=tmp_path,
            environment=tuple(sorted(corpus_gate_module._sanitized_child_environment().items())),
            timeout=10.0,
        )
    finally:
        runtime.close()

    assert completed.returncode == 0
    assert completed.stdout == b"threads-complete\n"


class _SyntheticRuntimeDistribution:
    def __init__(self, root: Path, *, version: str = "9.9.9") -> None:
        self._root = root
        self.version = version
        self.files = tuple(
            path.relative_to(root) for path in sorted(root.rglob("*")) if path.is_file()
        )

    def locate_file(self, path: object) -> Path:
        return self._root / str(path)


class _ChangingRuntimeDistribution:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.version = "9.9.9"
        self._files = tuple(
            path.relative_to(root) for path in sorted(root.rglob("*")) if path.is_file()
        )
        self.inventory_reads = 0

    @property
    def files(self) -> tuple[Path, ...]:
        self.inventory_reads += 1
        if self.inventory_reads == 1:
            return self._files
        return ()

    def locate_file(self, path: object) -> Path:
        return self._root / str(path)


def test_runtime_distribution_ignores_uninventoried_metadata_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shadow = _SyntheticRuntimeDistribution(tmp_path / "shadow")
    installed_root = tmp_path / "site-packages"
    package_file = installed_root / "ccparser" / "__init__.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_bytes(b"APPROVED = 1\n")
    installed = _SyntheticRuntimeDistribution(installed_root)
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distribution",
        lambda _name: shadow,
    )
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: (shadow, installed),
    )

    snapshot = corpus_gate_module._snapshot_runtime_distribution("ccparser")

    assert snapshot.installation_root == installed_root.resolve()
    assert snapshot.artifact_paths == frozenset({package_file.resolve()})


def test_runtime_distribution_snapshots_the_selected_inventory_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_root = tmp_path / "site-packages"
    package_file = installed_root / "ccparser" / "__init__.py"
    package_file.parent.mkdir(parents=True)
    package_file.write_bytes(b"APPROVED = 1\n")
    installed = _ChangingRuntimeDistribution(installed_root)
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: (installed,),
    )

    snapshot = corpus_gate_module._snapshot_runtime_distribution("ccparser")

    assert installed.inventory_reads == 1
    assert snapshot.artifact_paths == frozenset({package_file.resolve()})


def test_runtime_distribution_rejects_multiple_inventoried_installations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installations: list[_SyntheticRuntimeDistribution] = []
    for directory_name in ("first", "second"):
        installation_root = tmp_path / directory_name
        package_file = installation_root / "ccparser" / "__init__.py"
        package_file.parent.mkdir(parents=True)
        package_file.write_bytes(b"APPROVED = 1\n")
        installations.append(_SyntheticRuntimeDistribution(installation_root))
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distribution",
        lambda _name: installations[0],
    )
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: tuple(installations),
    )

    with pytest.raises(RuntimeError, match="runtime distribution inventory unavailable"):
        corpus_gate_module._snapshot_runtime_distribution("ccparser")


def test_runtime_distribution_rejects_missing_inventoried_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: (),
    )

    with pytest.raises(RuntimeError, match="runtime distribution inventory unavailable"):
        corpus_gate_module._snapshot_runtime_distribution("ccparser")


@pytest.mark.parametrize(
    ("dependency_name", "relative_artifact"),
    (
        ("pydantic", "pydantic/__init__.py"),
        (
            "pydantic-core",
            "pydantic_core/_pydantic_core.cpython-313-x86_64-linux-gnu.so",
        ),
    ),
)
def test_same_version_distribution_byte_mutation_changes_dependency_identity(
    tmp_path: Path,
    dependency_name: corpus_gate_module.RuntimeDependencyName,
    relative_artifact: str,
) -> None:
    distribution_root = tmp_path / "site-packages"
    package_file = distribution_root / relative_artifact
    package_file.parent.mkdir(parents=True)
    package_file.write_bytes(b"APPROVED-BYTES")
    metadata_file = distribution_root / f"{dependency_name}-9.9.9.dist-info" / "METADATA"
    metadata_file.parent.mkdir()
    metadata_file.write_text(
        f"Name: {dependency_name}\nVersion: 9.9.9\n",
        encoding="utf-8",
    )
    distribution = _SyntheticRuntimeDistribution(distribution_root)

    before = corpus_gate_module._snapshot_runtime_distribution(
        dependency_name,
        distribution=distribution,
    )
    package_file.write_bytes(b"SUBSTITUTE-DATA")
    after = corpus_gate_module._snapshot_runtime_distribution(
        dependency_name,
        distribution=distribution,
    )

    assert before.dependency.version == after.dependency.version == "9.9.9"
    assert before.dependency.content_digest != after.dependency.content_digest


def test_distribution_resource_symlink_cannot_become_a_source_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution_root = tmp_path / "site-packages"
    resource = distribution_root / "resources" / "payload.json"
    resource.parent.mkdir(parents=True)
    resource.write_bytes(b"VALUE = 2\n")
    source_alias = distribution_root / "pydantic" / "__init__.py"
    source_alias.parent.mkdir()
    source_alias.symlink_to(resource)
    distribution = _SyntheticRuntimeDistribution(distribution_root)
    distribution.files = (source_alias.relative_to(distribution_root),)
    snapshot = corpus_gate_module._snapshot_runtime_distribution(
        "pydantic",
        distribution=distribution,
    )
    specification = spec_from_file_location("pydantic", source_alias)
    assert specification is not None
    module = module_from_spec(specification)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    with pytest.raises(RuntimeError, match="loaded runtime origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (snapshot,),
            loaded_modules={"pydantic": module},
        )


def test_loaded_dependency_origin_must_be_an_inventoried_distribution_file(
    tmp_path: Path,
) -> None:
    distribution_root = tmp_path / "site-packages"
    approved_origin = distribution_root / "pydantic" / "__init__.py"
    approved_origin.parent.mkdir(parents=True)
    approved_origin.write_bytes(b"APPROVED = 1\n")
    distribution = _SyntheticRuntimeDistribution(distribution_root)
    snapshot = corpus_gate_module._snapshot_runtime_distribution(
        "pydantic",
        distribution=distribution,
    )
    substitute_origin = tmp_path / "shadow" / "pydantic" / "__init__.py"
    substitute_origin.parent.mkdir(parents=True)
    substitute_origin.write_bytes(approved_origin.read_bytes())
    substitute = ModuleType("pydantic")
    substitute.__file__ = str(substitute_origin)
    substitute.__spec__ = ModuleSpec("pydantic", loader=None, origin=str(substitute_origin))

    with pytest.raises(RuntimeError, match="dependency origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (snapshot,),
            loaded_modules={"pydantic": substitute},
        )


def test_uninventoried_dependency_bytecode_origin_is_rejected(
    tmp_path: Path,
) -> None:
    distribution_root = tmp_path / "site-packages"
    source = distribution_root / "pydantic" / "__init__.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"APPROVED = 1\n")
    distribution = _SyntheticRuntimeDistribution(distribution_root)
    snapshot = corpus_gate_module._snapshot_runtime_distribution(
        "pydantic",
        distribution=distribution,
    )
    bytecode = source.parent / "__pycache__" / "__init__.cpython-313.pyc"
    bytecode.parent.mkdir()
    py_compile.compile(str(source), cfile=str(bytecode), doraise=True)
    loaded = ModuleType("pydantic")
    loaded.__file__ = str(source)
    loaded.__cached__ = str(bytecode)
    loaded.__spec__ = ModuleSpec(
        "pydantic",
        SourceFileLoader("pydantic", str(source)),
        origin=str(source),
    )

    with pytest.raises(RuntimeError, match="dependency origin unavailable"):
        corpus_gate_module._validate_loaded_distribution_origins(
            (snapshot,),
            loaded_modules={"pydantic": loaded},
        )


def test_same_inode_native_library_byte_mutation_changes_runtime_identity(
    tmp_path: Path,
) -> None:
    library = tmp_path / "libsynthetic.so"
    library.write_bytes(b"approved-native-bytes")
    mapping = corpus_gate_module._MappedNativeFile.from_path(library)
    before_inode = library.stat().st_ino

    before = corpus_gate_module._native_runtime_identity((mapping,))
    library.write_bytes(b"substitute-native-data")
    after = corpus_gate_module._native_runtime_identity((mapping,))

    assert library.stat().st_ino == before_inode
    assert before.digest != after.digest


def test_native_library_path_inode_replacement_fails_closed(tmp_path: Path) -> None:
    library = tmp_path / "libsynthetic.so"
    library.write_bytes(b"approved-native-bytes")
    mapping = corpus_gate_module._MappedNativeFile.from_path(library)
    substitute = tmp_path / "substitute.so"
    substitute.write_bytes(library.read_bytes())
    os.replace(substitute, library)

    with pytest.raises(RuntimeError, match="native runtime changed"):
        corpus_gate_module._native_runtime_identity((mapping,))


def test_fixed_preload_path_byte_mutation_changes_runtime_environment_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preload = tmp_path / "libpreload.so"
    preload.write_bytes(b"approved-preload")
    monkeypatch.setenv("LD_PRELOAD", str(preload))

    before = corpus_gate_module._runtime_environment_digest()
    preload.write_bytes(b"substitute-preload")
    after = corpus_gate_module._runtime_environment_digest()

    assert before != after


def test_external_child_locale_is_fixed_instead_of_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "attacker_LOCALE")
    monkeypatch.setenv("LANGUAGE", "attacker")
    monkeypatch.setenv("LC_ALL", "attacker_LOCALE")
    monkeypatch.setenv("LC_NUMERIC", "attacker_LOCALE")
    monkeypatch.setenv("TZ", "attacker/zone")

    environment = corpus_gate_module._sanitized_child_environment()

    assert environment["LANG"] == "C.UTF-8"
    assert environment["LANGUAGE"] == "C"
    assert environment["LC_ALL"] == "C.UTF-8"
    assert environment["TZ"] == "UTC"
    assert "LC_NUMERIC" not in environment


def test_isolated_worker_environment_never_maps_fixed_path_preload_substitutes(
    tmp_path: Path,
) -> None:
    mapped_libraries = corpus_gate_module._mapped_native_files()
    approved_source = next(
        mapping.path for mapping in mapped_libraries if mapping.path.name.startswith("libuuid.so")
    )
    substitute_source = next(
        mapping.path for mapping in mapped_libraries if mapping.path.name.startswith("liblzma.so")
    )
    fixed_preload = tmp_path / "fixed-preload.so"
    fixed_preload.write_bytes(approved_source.read_bytes())
    probe = (
        "from pathlib import Path;"
        f"print({str(fixed_preload)!r} in Path('/proc/self/maps').read_text())"
    )
    poisoned_environment = dict(os.environ)
    poisoned_environment["LD_PRELOAD"] = str(fixed_preload)

    control = subprocess.run(
        (sys.executable, "-I", "-S", "-c", probe),
        check=True,
        capture_output=True,
        env=poisoned_environment,
        text=True,
    )
    approved = subprocess.run(
        (sys.executable, "-I", "-S", "-c", probe),
        check=True,
        capture_output=True,
        env=corpus_gate_module._isolated_worker_environment(),
        text=True,
    )
    fixed_preload.write_bytes(substitute_source.read_bytes())
    substituted = subprocess.run(
        (sys.executable, "-I", "-S", "-c", probe),
        check=True,
        capture_output=True,
        env=corpus_gate_module._isolated_worker_environment(),
        text=True,
    )

    assert control.stdout == "True\n"
    assert approved.stdout == "False\n"
    assert substituted.stdout == "False\n"


def test_runtime_environment_fingerprint_tracks_relevant_but_not_unrelated_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    monkeypatch.delenv("PRIVATE_UNRELATED_SETTING", raising=False)
    baseline = corpus_gate_module._runtime_environment_digest()

    monkeypatch.setenv("PRIVATE_UNRELATED_SETTING", "private value")
    assert corpus_gate_module._runtime_environment_digest() == baseline

    monkeypatch.setenv("OMP_THREAD_LIMIT", "1")
    assert corpus_gate_module._runtime_environment_digest() != baseline


@pytest.mark.parametrize(
    "relative_asset",
    ("executable", "configs/tsv", "eng.traineddata", "heb.traineddata"),
)
def test_tesseract_fingerprint_tracks_every_executable_and_data_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_asset: str,
) -> None:
    executable = tmp_path / "executable"
    executable.write_bytes(b"executable")
    executable.chmod(0o700)
    tessdata = tmp_path / "tessdata"
    (tessdata / "configs").mkdir(parents=True)
    for relative_path in ("configs/tsv", "eng.traineddata", "heb.traineddata"):
        (tessdata / relative_path).write_bytes(relative_path.encode())
    monkeypatch.setattr(corpus_gate_module.shutil, "which", lambda _command: str(executable))

    def fake_run(
        command: tuple[str, ...],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, timeout
        assert env["PATH"] == "/nonexistent"
        assert pass_fds and command[0] == f"/proc/self/fd/{pass_fds[0]}"
        output = (
            b"tesseract 5.7.1\nlinked libraries\n"
            if command[-1] == "--version"
            else f'List of available languages in "{tessdata}" (2):\neng\nheb\n'.encode()
        )
        return subprocess.CompletedProcess(command, 0, output, b"")

    _install_synthetic_dynamic_runtime(monkeypatch, fake_run)
    commands = (
        ocr_module.tesseract_command(),
        ocr_module.supplemental_tesseract_command(),
        ocr_module.numeric_tesseract_command(),
        ocr_module.currency_tesseract_command(),
    )
    before = corpus_gate_module._tesseract_metadata(commands)
    selected = executable if relative_asset == "executable" else tessdata / relative_asset
    selected.write_bytes(selected.read_bytes() + b" changed")
    if selected == executable:
        selected.chmod(0o700)

    after = corpus_gate_module._tesseract_metadata(commands)

    assert before != after


def test_tesseract_execution_uses_fingerprinted_executable_and_assets_after_swaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git_executable = executable_directory / "git"
    git_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    git_executable.chmod(0o700)
    tessdata = tmp_path / "tessdata"
    (tessdata / "configs").mkdir(parents=True)
    original_assets = {
        "configs/tsv": "approved-config",
        "eng.traineddata": "approved-eng",
        "heb.traineddata": "approved-heb",
    }
    for relative_path, content in original_assets.items():
        (tessdata / relative_path).write_text(f"{content}\n", encoding="utf-8")
    substitute_marker = tmp_path / "substitute-executed"
    poisoned_environment_marker = tmp_path / "poisoned-environment-observed"
    executable = executable_directory / "tesseract"
    executable.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                (
                    f'if [ -n "${{LD_PRELOAD-}}" ] || '
                    f'[ -n "${{TESSDATA_PREFIX-}}" ]; then : > '
                    f"'{poisoned_environment_marker}'; fi"
                ),
                'if [ "${1-}" = "--version" ]; then',
                "  printf 'tesseract approved\\nbuild approved\\n'",
                "  exit 0",
                "fi",
                'if [ "${1-}" = "--list-langs" ]; then',
                f"  printf 'List of available languages in \"{tessdata}\" (2):\\neng\\nheb\\n'",
                "  exit 0",
                "fi",
                "tessdata_directory=",
                'while [ "$#" -gt 0 ]; do',
                '  if [ "$1" = "--tessdata-dir" ]; then',
                "    shift",
                "    tessdata_directory=$1",
                "  fi",
                "  shift",
                "done",
                'IFS= read -r eng < "$tessdata_directory/eng.traineddata"',
                'IFS= read -r heb < "$tessdata_directory/heb.traineddata"',
                'IFS= read -r config < "$tessdata_directory/configs/tsv"',
                'printf \'%s|%s|%s\\n\' "$eng" "$heb" "$config"',
                "",
            )
        ),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    substitute = executable_directory / "substitute"
    substitute.write_text(
        f"#!/bin/sh\n: > '{substitute_marker}'\nprintf 'substitute\\n'\n",
        encoding="utf-8",
    )
    substitute.chmod(0o700)
    monkeypatch.setenv("PATH", str(executable_directory))
    monkeypatch.setenv("LD_PRELOAD", str(tmp_path / "untrusted-library.so"))
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "untrusted-tessdata"))
    commands = (
        ocr_module.tesseract_command(),
        ocr_module.supplemental_tesseract_command(),
        ocr_module.numeric_tesseract_command(),
        ocr_module.currency_tesseract_command(),
    )
    capabilities = corpus_gate_module._GateRuntimeCapabilities.bind()
    work_directory = tmp_path / "work"
    work_directory.mkdir()
    work_fd = os.open(work_directory, os.O_RDONLY | os.O_DIRECTORY)
    staged_runtime = None
    try:
        capabilities.tesseract_metadata(commands)
        os.replace(substitute, executable)
        for relative_path in original_assets:
            (tessdata / relative_path).write_text("substitute-data\n", encoding="utf-8")
        staged_runtime = capabilities.stage_tesseract(work_fd)
        with ocr_module.bind_tesseract_runtime(staged_runtime.runtime):
            provider = ocr_module.TesseractOcr(tmp_path / "cache")
            version = provider._tesseract_version()
            recognized = provider._recognize(
                b"synthetic image",
                ocr_module.tesseract_command(),
            )

        assert version == "tesseract approved"
        assert recognized == b"approved-eng|approved-heb|approved-config\n"
        assert not substitute_marker.exists()
        assert not poisoned_environment_marker.exists()

        assert capabilities.tesseract is not None
        tessdata_fd = staged_runtime._directory_fds[0]
        os.fchmod(tessdata_fd, 0o700)
        os.unlink("eng.traineddata", dir_fd=tessdata_fd)
        os.symlink(
            capabilities.tesseract.heb_traineddata.descriptor_path,
            "eng.traineddata",
            dir_fd=tessdata_fd,
        )
        os.fchmod(tessdata_fd, 0o500)
        with (
            ocr_module.bind_tesseract_runtime(staged_runtime.runtime),
            pytest.raises(ocr_module.OcrError, match="recognition failed"),
        ):
            provider._recognize(
                b"synthetic image",
                ocr_module.tesseract_command(),
            )
    finally:
        if staged_runtime is not None:
            staged_runtime.close()
        os.close(work_fd)
        capabilities.close()


def test_full_tesseract_version_output_changes_fingerprint_even_when_first_line_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tesseract"
    executable.write_bytes(b"executable")
    executable.chmod(0o700)
    tessdata = tmp_path / "tessdata"
    (tessdata / "configs").mkdir(parents=True)
    for relative_path in ("configs/tsv", "eng.traineddata", "heb.traineddata"):
        (tessdata / relative_path).write_bytes(relative_path.encode())
    monkeypatch.setattr(corpus_gate_module.shutil, "which", lambda _command: str(executable))
    build_details = b"build-a"

    def fake_run(
        command: tuple[str, ...],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        del check, stdout, stderr, timeout
        assert env["PATH"] == "/nonexistent"
        assert pass_fds and command[0] == f"/proc/self/fd/{pass_fds[0]}"
        output = (
            b"tesseract 5.7.1\n" + build_details + b"\n"
            if command[-1] == "--version"
            else f'List of available languages in "{tessdata}" (2):\neng\nheb\n'.encode()
        )
        return subprocess.CompletedProcess(command, 0, output, b"")

    _install_synthetic_dynamic_runtime(monkeypatch, fake_run)
    commands = (
        ocr_module.tesseract_command(),
        ocr_module.supplemental_tesseract_command(),
        ocr_module.numeric_tesseract_command(),
        ocr_module.currency_tesseract_command(),
    )
    before = corpus_gate_module._tesseract_metadata(commands)
    build_details = b"build-b"

    after = corpus_gate_module._tesseract_metadata(commands)

    assert before[0] == after[0]
    assert before[1] != after[1]


def test_default_dependencies_bind_real_adapters_without_executing_them() -> None:
    dependencies = corpus_gate_module._default_dependencies()
    try:
        assert isinstance(dependencies.runner, LocalCorpusRunner)
        assert isinstance(dependencies.repository, GitRepositoryInspector)
        assert isinstance(dependencies.toolchain, LocalToolchainInspector)
        assert dependencies.runtime_capabilities is not None
        assert dependencies.repository._executable is dependencies.runtime_capabilities.git
        assert dependencies.toolchain._runtime_capabilities is dependencies.runtime_capabilities
    finally:
        assert dependencies.runtime_capabilities is not None
        dependencies.runtime_capabilities.close()


def test_default_gate_boundary_delegates_to_isolated_worker_despite_live_default_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _dependencies, _runner = _gate_fixture(tmp_path)
    expected = CorpusGateAttestation(
        passed=True,
        mode=CorpusGateMode.RECORD,
        commit_abbreviation="d" * 12,
        toolchain_abbreviation="a" * 12,
        retained_counts=_counts(),
        quarantine_counts=_counts(),
        elapsed_seconds=Decimal("1"),
        performance_checked=False,
        reason_codes=(),
    )

    def untracked_statement_parser(*_args: object, **_kwargs: object) -> StatementResult:
        raise AssertionError("must not be inherited by isolated worker")

    original_defaults = LocalCorpusRunner.__init__.__kwdefaults__
    assert original_defaults is not None
    mutated_defaults = dict(original_defaults)
    mutated_defaults["statement_parser"] = untracked_statement_parser
    monkeypatch.setattr(LocalCorpusRunner.__init__, "__kwdefaults__", mutated_defaults)
    monkeypatch.setattr(
        corpus_gate_module,
        "_run_corpus_gate_in_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default boundary must not execute in parent interpreter")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        corpus_gate_module,
        "_run_corpus_gate_isolated",
        lambda actual_config, actual_mode: expected,
        raising=False,
    )

    assert run_corpus_gate(config, CorpusGateMode.RECORD) == expected


def _isolated_import_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    dependency_root = tmp_path / "approved-dependencies"
    candidate_root = tmp_path / "candidate-src"
    dependency_root.mkdir()
    package_root = candidate_root / "ccparser"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "corpus_gate.py").write_text(
        """def _isolated_worker_main() -> int:
    import decimal
    import fitz
    import pydantic

    if not hasattr(decimal, "Decimal"):
        return 71
    if getattr(pydantic, "APPROVED_ORIGIN", None) != "dependency":
        return 72
    if getattr(fitz, "APPROVED_ORIGIN", None) != "dependency":
        return 73
    return 0
""",
        encoding="utf-8",
    )
    for module_name in ("pydantic", "fitz"):
        (dependency_root / f"{module_name}.py").write_text(
            'APPROVED_ORIGIN = "dependency"\n',
            encoding="utf-8",
        )

    synthetic_distribution = _SyntheticRuntimeDistribution(dependency_root)
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: (synthetic_distribution,),
    )
    monkeypatch.setattr(
        corpus_gate_module,
        "__file__",
        str(package_root / "corpus_gate.py"),
    )
    return dependency_root.resolve(), candidate_root.resolve()


def _write_candidate_shadow(
    candidate_root: Path,
    module_name: str,
    artifact_kind: str,
) -> None:
    source = candidate_root / f"{module_name}.py"
    source.write_text('raise RuntimeError("candidate shadow executed")\n', encoding="utf-8")
    if artifact_kind == "bytecode":
        py_compile.compile(
            str(source),
            cfile=str(candidate_root / f"{module_name}.pyc"),
            doraise=True,
        )
        source.unlink()


def test_isolated_search_paths_put_approved_dependencies_before_candidate_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency_root, candidate_root = _isolated_import_roots(tmp_path, monkeypatch)

    assert corpus_gate_module._isolated_search_paths() == (
        dependency_root,
        candidate_root,
    )


def test_isolated_search_paths_ignore_uninventoried_metadata_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency_root, candidate_root = _isolated_import_roots(tmp_path, monkeypatch)
    shadow_root = tmp_path / "metadata-shadow"
    shadow_root.mkdir()
    shadow = _SyntheticRuntimeDistribution(shadow_root)
    installed = _SyntheticRuntimeDistribution(dependency_root)
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distribution",
        lambda _name: shadow,
    )
    monkeypatch.setattr(
        corpus_gate_module.metadata,
        "distributions",
        lambda **_kwargs: (shadow, installed),
    )

    assert corpus_gate_module._isolated_search_paths() == (
        dependency_root,
        candidate_root,
    )


@pytest.mark.parametrize("module_name", ("decimal", "pydantic", "fitz"))
@pytest.mark.parametrize("artifact_kind", ("source", "bytecode"))
def test_isolated_worker_rejects_candidate_stdlib_and_dependency_shadows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    artifact_kind: str,
) -> None:
    _dependency_root, candidate_root = _isolated_import_roots(tmp_path, monkeypatch)
    _write_candidate_shadow(candidate_root, module_name, artifact_kind)
    search_paths = tuple(str(path) for path in corpus_gate_module._isolated_search_paths())

    completed = subprocess.run(
        (sys.executable, "-I", "-B", "-S", "-c", corpus_gate_module._ISOLATED_BOOTSTRAP),
        input=f"{json.dumps(search_paths)}\n",
        check=False,
        capture_output=True,
        env=corpus_gate_module._isolated_worker_environment(),
        text=True,
    )

    assert completed.returncode == 0, "candidate shadow module executed"


def test_isolated_gate_worker_uses_no_site_isolated_interpreter_and_private_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _dependencies, _runner = _gate_fixture(tmp_path)
    expected = CorpusGateAttestation(
        passed=True,
        mode=CorpusGateMode.RECORD,
        commit_abbreviation="d" * 12,
        toolchain_abbreviation="a" * 12,
        retained_counts=_counts(),
        quarantine_counts=_counts(),
        elapsed_seconds=Decimal("1"),
        performance_checked=False,
        reason_codes=(),
    )
    calls: list[tuple[tuple[str, ...], bytes]] = []

    def fake_run(
        command: tuple[str, ...],
        *,
        input: bytes,
        cwd: Path,
        check: bool,
        capture_output: bool,
        env: dict[str, str],
        timeout: float | None,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, check, capture_output, timeout
        assert env["PATH"] == os.defpath
        assert "LD_PRELOAD" not in env
        assert "LD_LIBRARY_PATH" not in env
        calls.append((command, input))
        response = json.dumps(
            {
                "kind": "success",
                "attestation": json.loads(expected.model_dump_json()),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return subprocess.CompletedProcess(command, 0, response, b"")

    monkeypatch.setattr(corpus_gate_module.subprocess, "run", fake_run)
    monkeypatch.setenv("LD_PRELOAD", "/untrusted/fixed/library.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/untrusted/library/search")
    monkeypatch.setattr(
        corpus_gate_module,
        "_isolated_search_paths",
        lambda: (Path("/approved/candidate/src"), Path("/approved/site-packages")),
        raising=False,
    )

    actual = corpus_gate_module._run_corpus_gate_isolated(config, CorpusGateMode.RECORD)

    assert actual == expected
    assert len(calls) == 1
    command, request = calls[0]
    assert command[:4] == (sys.executable, "-I", "-B", "-S")
    assert command[4] == "-c"
    search_paths, payload = request.splitlines()
    assert json.loads(search_paths) == [
        "/approved/candidate/src",
        "/approved/site-packages",
    ]
    assert json.loads(payload)["mode"] == "record"


def test_isolated_worker_refuses_a_nonisolated_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_input = io.StringIO("not parsed\n")
    worker_output = io.StringIO()
    monkeypatch.setattr(corpus_gate_module.sys, "stdin", worker_input)
    monkeypatch.setattr(corpus_gate_module.sys, "stdout", worker_output)
    monkeypatch.setattr(
        corpus_gate_module,
        "_run_corpus_gate_in_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("nonisolated worker must not run the gate")
        ),
    )

    assert corpus_gate_module._isolated_worker_main() == 0

    assert json.loads(worker_output.getvalue()) == {
        "category": "runtime",
        "kind": "error",
        "reason_codes": [CorpusGateReason.PARSER_RUNTIME_FAILED.value],
    }


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


@pytest.mark.parametrize(
    "batch",
    (
        _batch(),
        BatchResult(status=Status.UNSUPPORTED, statements=(), diagnostics=("no_pdf_files",)),
        BatchResult(
            status=Status.UNRECONCILED,
            statements=(
                _status_batch(Status.RECONCILED).statements[0],
                _status_batch(Status.UNRECONCILED).statements[0],
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
        _batch(transaction=_transaction(with_fx=True, ambiguities=("candidate",))),
    ),
)
def test_project_streamed_run_matches_complete_batch(batch: BatchResult) -> None:
    expected = project_run(batch, elapsed_seconds=Decimal("1.25"))

    actual = project_streamed_run(
        batch_status=batch.status,
        elapsed_seconds=Decimal("1.25"),
        json_digest=expected.json_digest,
        csv_digest=expected.csv_digest,
        statements=lambda: iter(batch.statements),
    )

    assert actual == expected


def test_project_streamed_run_traverses_statements_once() -> None:
    batch = _batch()
    expected = project_run(batch, elapsed_seconds=Decimal("1.25"))
    factory_calls = 0
    yielded_statements = 0

    def statements() -> Iterator[StatementResult]:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls > 1:
            raise AssertionError("statement iterator factory reused")

        def values() -> Iterator[StatementResult]:
            nonlocal yielded_statements
            for statement in batch.statements:
                yielded_statements += 1
                yield statement

        return values()

    actual = project_streamed_run(
        batch_status=batch.status,
        elapsed_seconds=Decimal("1.25"),
        json_digest=expected.json_digest,
        csv_digest=expected.csv_digest,
        statements=statements,
    )

    assert actual == expected
    assert factory_calls == 1
    assert yielded_statements == len(batch.statements)


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
        ("runtime_context_drift", 2),
        ("runtime_regression", 2),
    )

    assert tuple((reason.value, reason.exit_code) for reason in CorpusGateReason) == expected
    assert tuple(mode.value for mode in CorpusGateMode) == ("verify", "record")


@pytest.mark.parametrize(
    "field",
    (
        "python_runtime_digest",
        "runtime_environment_digest",
        "tesseract_version_output_digest",
        "command_digest",
        "digest",
    ),
)
def test_toolchain_fingerprint_rejects_malformed_digests(field: str) -> None:
    values = _toolchain().model_dump()
    values[field] = "invalid"

    with pytest.raises(ValidationError):
        ToolchainFingerprint.model_validate(values)


@pytest.mark.parametrize(
    "field",
    (
        "standard_library",
        "git_native_closure",
        "native_runtime",
        "tesseract_native_closure",
    ),
)
def test_toolchain_fingerprint_rejects_malformed_runtime_artifact_digests(
    field: str,
) -> None:
    values = _toolchain().model_dump()
    values[field]["digest"] = "invalid"

    with pytest.raises(ValidationError):
        ToolchainFingerprint.model_validate(values)


def test_toolchain_fingerprint_requires_sorted_cache_versions() -> None:
    values = _toolchain().model_dump()
    values["ocr_cache_versions"] = ("text-v1", "layout-v1")

    with pytest.raises(ValidationError, match="sorted"):
        ToolchainFingerprint.model_validate(values)


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("python_version", "3.14.0"),
        ("python_implementation", "DifferentPython"),
        ("pymupdf_binding_version", "future-binding"),
        ("pymupdf_engine_version", "future-engine"),
        ("tesseract_version", "future-tesseract"),
    ),
)
def test_toolchain_fingerprint_rejects_fields_inconsistent_with_digest(
    field: str,
    changed: str,
) -> None:
    values = _toolchain().model_dump()
    values[field] = changed

    with pytest.raises(ValidationError, match="does not match"):
        ToolchainFingerprint.model_validate(values)


@pytest.mark.parametrize("collection", ("dependencies", "tesseract_assets"))
def test_toolchain_fingerprint_requires_complete_closed_collections(collection: str) -> None:
    values = _toolchain().model_dump()
    values[collection] = tuple(values[collection][:-1])

    with pytest.raises(ValidationError, match="complete"):
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


def test_baseline_comparison_rejects_toolchain_digest_change() -> None:
    baseline = _baseline()
    candidate = baseline.model_copy(update={"toolchain": _toolchain("b")})

    assert compare_with_baseline(baseline, candidate) == (CorpusGateReason.RUNTIME_CONTEXT_DRIFT,)


def test_runtime_comparison_requires_matching_toolchain_and_jobs() -> None:
    baseline = _baseline(elapsed="10", second_elapsed="9", jobs=4, toolchain="a")
    slower = _baseline(elapsed="11", second_elapsed="13", jobs=4, toolchain="a")

    assert compare_with_baseline(baseline, slower) == (CorpusGateReason.RUNTIME_REGRESSION,)
    assert compare_with_baseline(
        baseline,
        slower.model_copy(update={"toolchain": _toolchain("b")}),
    ) == (CorpusGateReason.RUNTIME_CONTEXT_DRIFT,)
    assert compare_with_baseline(
        baseline,
        slower.model_copy(update={"jobs": 2}),
    ) == (CorpusGateReason.RUNTIME_CONTEXT_DRIFT,)


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


def test_baseline_comparison_ignores_only_the_baseline_source_commit() -> None:
    baseline = _baseline()
    candidate = baseline.model_copy(
        update={
            "commit_sha": "e" * 40,
        }
    )

    assert compare_with_baseline(baseline, candidate) == ()


def test_baseline_comparison_rejects_inconsistent_non_digest_toolchain_metadata() -> None:
    baseline = _baseline()
    inconsistent = baseline.toolchain.model_copy(update={"python_version": "future-version"})
    candidate = baseline.model_copy(update={"toolchain": inconsistent})

    assert compare_with_baseline(baseline, candidate) == (CorpusGateReason.RUNTIME_CONTEXT_DRIFT,)


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
