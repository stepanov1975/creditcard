"""Privacy-safe corpus projections and isolated regression-gate execution."""

from __future__ import annotations

import _imp
import fcntl
import json
import locale
import os
import platform
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from importlib import metadata
from importlib.machinery import (
    EXTENSION_SUFFIXES,
    BuiltinImporter,
    ExtensionFileLoader,
    FrozenImporter,
    SourceFileLoader,
    SourcelessFileLoader,
)
from importlib.util import cache_from_source
from pathlib import Path, PurePosixPath
from types import (
    BuiltinFunctionType,
    ClassMethodDescriptorType,
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MemberDescriptorType,
    MethodDescriptorType,
    ModuleType,
    WrapperDescriptorType,
)
from typing import Annotated, Literal, Protocol, Self, runtime_checkable

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser._traced_subprocess import run_traced_subprocess
from ccparser.corpus_spool import StatementSpool
from ccparser.evidence.ocr import (
    OCR_CURRENCY_RECOGNITION_CACHE_VERSION,
    OCR_NUMERIC_RECOGNITION_CACHE_VERSION,
    OCR_PIPELINE_VERSION,
    OCR_PREPROCESSING_VERSION,
    OCR_RECOGNITION_CACHE_VERSION,
    TESSERACT_RECOGNITION_TIMEOUT_SECONDS,
    TESSERACT_VERSION_TIMEOUT_SECONDS,
    TesseractExecutionRuntime,
    bind_tesseract_runtime,
    currency_tesseract_command,
    numeric_tesseract_command,
    supplemental_tesseract_command,
    tesseract_command,
)
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
)
from ccparser.output import (
    _canonical_json_value_bytes,
    canonical_json_bytes,
    transactions_csv_bytes,
    write_canonical_batch_json_stream,
    write_streaming_batch_outputs,
    write_transactions_csv_stream,
)
from ccparser.parser import (
    BatchDisposition,
    StatementParser,
    convert_directory_statements,
    summarize_batch_statuses,
)
from ccparser.paths import DirectoryRootPolicy, iter_regular_pdf_files, paths_overlap

type Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
type PresentFieldPath = Literal[
    "category",
    "conversion_date",
    "description",
    "foreign_exchange.exchange_rate",
    "foreign_exchange.fee_discount",
    "foreign_exchange.fee_percentage",
    "foreign_exchange.gross_fee",
    "foreign_exchange.net_fee",
    "installment_current",
    "installment_total",
    "original_amount",
    "original_currency",
    "posting_date",
    "transaction_date",
]

type _GroupProjection = tuple[str, str, str, tuple[str, ...]]
type _GroupStructure = tuple[tuple[_GroupProjection, ...], ...]
type _TransactionIdentity = tuple[str, tuple[str, ...]]
type _TransactionIdentities = tuple[tuple[_TransactionIdentity, ...], ...]
type _FieldPresence = tuple[tuple[tuple[PresentFieldPath, ...], ...], ...]
type _EvidenceReferenceProjection = tuple[int, tuple[float, float, float, float], str]
type _EvidenceSiteProjection = tuple[str, tuple[_EvidenceReferenceProjection, ...]]
type _EvidenceProvenance = tuple[tuple[tuple[_EvidenceSiteProjection, ...], ...], ...]
type _AmbiguityProjection = tuple[tuple[tuple[str, ...], ...], ...]
type StatementResultFactory = Callable[[], Iterator[StatementResult]]


class CorpusGateMode(StrEnum):
    """Supported corpus gate lifecycle modes."""

    VERIFY = "verify"
    RECORD = "record"


class CorpusGateReason(StrEnum):
    """Closed, policy-ordered vocabulary for corpus gate failures."""

    INVALID_CONFIGURATION = "invalid_configuration"
    PATH_OUTSIDE_REPOSITORY = "path_outside_repository"
    UNSAFE_PATH_TOPOLOGY = "unsafe_path_topology"
    PRIVATE_PATH_NOT_IGNORED = "private_path_not_ignored"
    CORPUS_SYMLINK = "corpus_symlink"
    RUN_PATH_NOT_EMPTY = "run_path_not_empty"
    DIRTY_REPOSITORY = "dirty_repository"
    REPOSITORY_CHANGED = "repository_changed"
    TOOLCHAIN_UNAVAILABLE = "toolchain_unavailable"
    TOOLCHAIN_CHANGED = "toolchain_changed"
    INVENTORY_INVALID = "inventory_invalid"
    BASELINE_MISSING = "baseline_missing"
    BASELINE_INVALID = "baseline_invalid"
    PARSER_RUNTIME_FAILED = "parser_runtime_failed"
    MEMBERSHIP_DRIFT = "membership_drift"
    RETAINED_NOT_RECONCILED = "retained_not_reconciled"
    QUARANTINE_MISCLASSIFIED = "quarantine_misclassified"
    COUNTS_DRIFT = "counts_drift"
    JSON_DRIFT = "json_drift"
    CSV_DRIFT = "csv_drift"
    STATUS_DRIFT = "status_drift"
    GROUP_STRUCTURE_DRIFT = "group_structure_drift"
    TRANSACTION_STRUCTURE_DRIFT = "transaction_structure_drift"
    FIELD_PRESENCE_DRIFT = "field_presence_drift"
    EVIDENCE_PROVENANCE_DRIFT = "evidence_provenance_drift"
    AMBIGUITY_DRIFT = "ambiguity_drift"
    RUNTIME_CONTEXT_DRIFT = "runtime_context_drift"
    RUNTIME_REGRESSION = "runtime_regression"

    @property
    def exit_code(self) -> Literal[1, 2]:
        """Map input/runtime failures to 1 and acceptance failures to 2."""

        if self in _INPUT_OR_RUNTIME_FAILURE_REASONS:
            return 1
        return 2


_INPUT_OR_RUNTIME_FAILURE_REASONS = frozenset(
    tuple(CorpusGateReason)[: tuple(CorpusGateReason).index(CorpusGateReason.MEMBERSHIP_DRIFT)]
)


class CorpusGateError(RuntimeError):
    """Base class for gate failures containing only closed reason codes."""

    def __init__(self, reasons: tuple[CorpusGateReason, ...]) -> None:
        if not reasons:
            raise ValueError("at least one corpus gate reason is required")
        self.reasons = tuple(reason for reason in CorpusGateReason if reason in set(reasons))
        super().__init__(",".join(reason.value for reason in self.reasons))


class CorpusGateInputError(CorpusGateError):
    """The gate configuration or local repository state is unsafe."""


class CorpusGateRuntimeError(CorpusGateError):
    """A local parser or toolchain operation failed safely."""


class CorpusGateAcceptanceError(CorpusGateError):
    """A completed corpus run did not satisfy the acceptance policy."""


class _GateModel(BaseModel):
    """Strict immutable base for persisted gate data."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldCount(_GateModel):
    """Aggregate presence count for one closed transaction field path."""

    path: PresentFieldPath
    count: int = Field(ge=0)


class CorpusCounts(_GateModel):
    """Non-sensitive aggregate counts for one parsed corpus."""

    documents: int = Field(ge=0)
    reconciled: int = Field(ge=0)
    unreconciled: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    not_statement: int = Field(ge=0)
    groups: int = Field(ge=0)
    row_results: int = Field(ge=0)
    transactions: int = Field(ge=0)
    ambiguous_transactions: int = Field(ge=0)
    ambiguity_occurrences: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    present_fields: tuple[FieldCount, ...]

    @model_validator(mode="after")
    def validate_present_fields(self) -> Self:
        paths = tuple(field.path for field in self.present_fields)
        if paths != tuple(sorted(paths)):
            raise ValueError("present fields must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("present field paths must be unique")
        return self


class RepositoryState(_GateModel):
    """Privacy-safe Git state used to bind one gate execution."""

    root: Path
    commit_sha: CommitSha
    clean: bool


class CorpusGateConfig(_GateModel):
    """Filesystem and runtime configuration for one corpus gate execution."""

    expected_commit_sha: CommitSha
    retained_dir: Path
    quarantine_dir: Path
    membership_inventory_path: Path
    membership_inventory_sha256: Digest
    baseline_path: Path
    baseline_sha256: Digest | None = None
    work_dir: Path
    jobs: int = Field(gt=0)
    runtime_tolerance_ratio: Decimal | None = Field(default=None, ge=0)


class CorpusGateAttestation(_GateModel):
    """Aggregate privacy-safe result returned only by an accepted execution."""

    passed: bool
    mode: CorpusGateMode
    commit_abbreviation: str
    toolchain_abbreviation: str
    retained_counts: CorpusCounts
    quarantine_counts: CorpusCounts
    elapsed_seconds: Decimal = Field(ge=0)
    performance_checked: bool
    reason_codes: tuple[CorpusGateReason, ...]


class CorpusMembership(_GateModel):
    """Count and order-independent multiset digest for corpus inputs."""

    document_count: int = Field(ge=0)
    source_multiset_digest: Digest


class CorpusMembershipInventory(_GateModel):
    """Approved retained and quarantine corpus membership."""

    version: Literal[1]
    retained: CorpusMembership
    quarantine: CorpusMembership


class RunManifest(_GateModel):
    """Aggregate and digest-only snapshot of one parser run."""

    elapsed_seconds: Decimal = Field(ge=0)
    counts: CorpusCounts
    json_digest: Digest
    csv_digest: Digest
    ordered_status_digest: Digest
    group_structure_digest: Digest
    transaction_identity_digest: Digest
    field_presence_digest: Digest
    evidence_provenance_digest: Digest
    ambiguity_digest: Digest


@dataclass(frozen=True, slots=True)
class CompletedCorpusRun:
    """One parser result with immediately adjacent corpus snapshots."""

    batch_status: Status
    manifest: RunManifest
    membership_before: CorpusMembership
    membership_after: CorpusMembership


type RuntimeDependencyName = Literal[
    "annotated-doc",
    "annotated-types",
    "ccparser",
    "pydantic",
    "pydantic-core",
    "pymupdf",
    "shellingham",
    "typer",
    "typing-extensions",
    "typing-inspection",
]
type ToolchainAssetRole = Literal[
    "config:tsv",
    "git-executable",
    "tesseract-executable",
    "traineddata:eng",
    "traineddata:heb",
]

_RUNTIME_DEPENDENCY_NAMES: tuple[RuntimeDependencyName, ...] = (
    "annotated-doc",
    "annotated-types",
    "ccparser",
    "pydantic",
    "pydantic-core",
    "pymupdf",
    "shellingham",
    "typer",
    "typing-extensions",
    "typing-inspection",
)
_TOOLCHAIN_ASSET_ROLES: tuple[ToolchainAssetRole, ...] = (
    "config:tsv",
    "tesseract-executable",
    "traineddata:eng",
    "traineddata:heb",
)


class RuntimeDependency(_GateModel):
    """Version and aggregate byte identity of one installed distribution."""

    name: RuntimeDependencyName
    version: str = Field(min_length=1)
    file_count: int = Field(gt=0)
    size_bytes: int = Field(ge=0)
    content_digest: Digest


class RuntimeArtifactIdentity(_GateModel):
    """Aggregate content identity for a closed runtime artifact set."""

    file_count: int = Field(gt=0)
    size_bytes: int = Field(ge=0)
    digest: Digest


class ToolchainAsset(_GateModel):
    """Content identity of one executable or OCR data asset."""

    role: ToolchainAssetRole
    size_bytes: int = Field(ge=0)
    sha256: Digest


def _toolchain_payload_digest(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


class ToolchainFingerprint(_GateModel):
    """Self-authenticating runtime, dependency, executable, and OCR identity."""

    version: Literal[6]
    python_version: str
    python_implementation: str
    python_runtime_digest: Digest
    standard_library: RuntimeArtifactIdentity
    runtime_environment_digest: Digest
    dependencies: tuple[RuntimeDependency, ...]
    git_executable: ToolchainAsset
    git_native_closure: RuntimeArtifactIdentity
    native_runtime: RuntimeArtifactIdentity
    pymupdf_binding_version: str
    pymupdf_engine_version: str
    tesseract_version: str
    tesseract_version_output_digest: Digest
    tesseract_assets: tuple[ToolchainAsset, ...]
    tesseract_native_closure: RuntimeArtifactIdentity
    ocr_pipeline_version: str
    ocr_cache_versions: tuple[str, ...]
    command_digest: Digest
    digest: Digest

    @model_validator(mode="after")
    def validate_complete_fingerprint(self) -> Self:
        dependency_names = tuple(dependency.name for dependency in self.dependencies)
        if dependency_names != _RUNTIME_DEPENDENCY_NAMES:
            raise ValueError("runtime dependencies must be complete, sorted, and unique")
        if self.git_executable.role != "git-executable":
            raise ValueError("Git executable identity is invalid")
        asset_roles = tuple(asset.role for asset in self.tesseract_assets)
        if asset_roles != _TOOLCHAIN_ASSET_ROLES:
            raise ValueError("toolchain assets must be complete, sorted, and unique")
        if self.ocr_cache_versions != tuple(sorted(self.ocr_cache_versions)) or len(
            self.ocr_cache_versions
        ) != len(set(self.ocr_cache_versions)):
            raise ValueError("OCR cache versions must be sorted and unique")
        payload = self.model_dump(mode="json", exclude={"digest"})
        if self.digest != _toolchain_payload_digest(payload):
            raise ValueError("toolchain digest does not match fingerprint fields")
        return self


class CorpusPairManifest(_GateModel):
    """Membership and projections from two independent corpus runs."""

    membership: CorpusMembership
    first: RunManifest
    second: RunManifest
    worst_elapsed_seconds: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_worst_elapsed_seconds(self) -> Self:
        expected = max(self.first.elapsed_seconds, self.second.elapsed_seconds)
        if self.worst_elapsed_seconds != expected:
            raise ValueError("worst elapsed seconds must equal the maximum run time")
        return self


class CorpusBaseline(_GateModel):
    """Versioned private baseline for retained and quarantine corpora."""

    version: Literal[1]
    commit_sha: CommitSha
    jobs: int = Field(gt=0)
    runtime_tolerance_ratio: Decimal = Field(ge=0)
    toolchain: ToolchainFingerprint
    retained: CorpusPairManifest
    quarantine: CorpusPairManifest


class CorpusRunner(Protocol):
    """Execute one isolated parser run."""

    def __call__(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        cache_dir: Path,
        strict: bool,
        jobs: int,
    ) -> CompletedCorpusRun:
        raise NotImplementedError


class RepositoryInspector(Protocol):
    """Read active-worktree state and Git ignore policy."""

    def state(self) -> RepositoryState:
        raise NotImplementedError

    def is_ignored(self, path: Path) -> bool:
        raise NotImplementedError


@runtime_checkable
class _SourceCodeLoader(Protocol):
    def get_code(self, fullname: str) -> CodeType | None:
        raise NotImplementedError


class ToolchainInspector(Protocol):
    """Produce the complete parser toolchain fingerprint."""

    def fingerprint(self) -> ToolchainFingerprint:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CorpusGateDependencies:
    """Injectable filesystem-bound adapters for tracked synthetic tests."""

    runner: CorpusRunner
    repository: RepositoryInspector
    toolchain: ToolchainInspector
    runtime_capabilities: _GateRuntimeCapabilities | None = None


class _NanosecondClock(Protocol):
    def __call__(self) -> int:
        raise NotImplementedError


class LocalCorpusRunner:
    """Filesystem adapter for one timed parser run with adjacent membership checks."""

    def __init__(
        self,
        *,
        statement_parser: StatementParser | None = None,
        monotonic_ns: _NanosecondClock | None = None,
    ) -> None:
        self._statement_parser = statement_parser
        self._monotonic_ns = monotonic_ns or time.monotonic_ns

    def __call__(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        cache_dir: Path,
        strict: bool,
        jobs: int,
    ) -> CompletedCorpusRun:
        membership_before = _snapshot_membership(input_dir, allow_descriptor_root=True)
        start_nanoseconds = self._monotonic_ns()
        directory_root_policy = (
            DirectoryRootPolicy.TRUSTED_DESCRIPTOR
            if all(_is_process_fd_path(path) for path in (input_dir, output_dir, cache_dir))
            else DirectoryRootPolicy.RESOLVE
        )
        try:
            with StatementSpool.create(output_dir) as spool:
                status_counts: Counter[Status] = Counter()

                def consume(ordinal: int, result: StatementResult, /) -> None:
                    spool.append(ordinal, result)
                    status_counts[result.status] += 1

                conversion = convert_directory_statements(
                    input_dir,
                    output_dir,
                    strict,
                    jobs,
                    cache_dir=cache_dir,
                    statement_parser=self._statement_parser,
                    result_sink=consume,
                    directory_root_policy=directory_root_policy,
                )
                spool.seal(conversion.source_count)
                disposition = summarize_batch_statuses(status_counts)
                if disposition.document_count != conversion.source_count:
                    raise RuntimeError("statement sink count mismatch")
                write_streaming_batch_outputs(
                    conversion.resolved_output_dir,
                    status=disposition.status,
                    diagnostics=disposition.diagnostics,
                    statements=spool.iter_statements,
                )
                end_nanoseconds = self._monotonic_ns()
                membership_after = _snapshot_membership(
                    input_dir,
                    allow_descriptor_root=True,
                )
                elapsed_nanoseconds = end_nanoseconds - start_nanoseconds
                if elapsed_nanoseconds < 0:
                    raise RuntimeError("monotonic clock moved backwards")
                elapsed_seconds = Decimal(elapsed_nanoseconds) / Decimal(1_000_000_000)
                expected_json_digest, expected_csv_digest = _canonical_stream_digests(
                    disposition,
                    spool.iter_statements,
                )
                _require_file_digest(
                    conversion.resolved_output_dir / "results.json",
                    expected_json_digest,
                )
                _require_file_digest(
                    conversion.resolved_output_dir / "transactions.csv",
                    expected_csv_digest,
                )
                manifest = project_streamed_run(
                    batch_status=disposition.status,
                    elapsed_seconds=elapsed_seconds,
                    json_digest=expected_json_digest,
                    csv_digest=expected_csv_digest,
                    statements=spool.iter_statements,
                )
        except CorpusGateError:
            raise
        except Exception:
            raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,)) from None
        return CompletedCorpusRun(
            batch_status=disposition.status,
            manifest=manifest,
            membership_before=membership_before,
            membership_after=membership_after,
        )


class _Sha256Writer:
    """Binary writer that retains only an incremental SHA-256 state."""

    def __init__(self) -> None:
        self._digest = sha256()

    def write(self, content: bytes, /) -> int:
        self._digest.update(content)
        return len(content)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _canonical_stream_digests(
    disposition: BatchDisposition,
    statements: StatementResultFactory,
) -> tuple[str, str]:
    json_writer = _Sha256Writer()
    write_canonical_batch_json_stream(
        json_writer,
        status=disposition.status,
        diagnostics=disposition.diagnostics,
        statements=statements(),
    )
    csv_writer = _Sha256Writer()
    write_transactions_csv_stream(
        csv_writer,
        status=disposition.status,
        diagnostics=disposition.diagnostics,
        statements=statements(),
    )
    return json_writer.hexdigest(), csv_writer.hexdigest()


_EMITTED_OUTPUT_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_EMITTED_OUTPUT_READ_SIZE = 1024 * 1024


def _require_file_digest(path: Path, expected_digest: str) -> None:
    file_descriptor = os.open(path, _EMITTED_OUTPUT_READ_FLAGS)
    try:
        before = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
        ):
            raise RuntimeError("emitted output is unsafe")
        digest = sha256()
        while chunk := os.read(file_descriptor, _EMITTED_OUTPUT_READ_SIZE):
            digest.update(chunk)
        after = os.fstat(file_descriptor)
        named_after = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != os.geteuid()
            or after.st_nlink != 1
            or _stable_file_identity(after) != _stable_file_identity(before)
            or _stable_file_identity(named_after) != _stable_file_identity(before)
            or digest.hexdigest() != expected_digest
        ):
            raise RuntimeError("emitted output digest mismatch")
    finally:
        os.close(file_descriptor)


_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "MALLOC_ARENA_MAX",
        "OPENBLAS_NUM_THREADS",
    }
)
_CHILD_ENVIRONMENT_PREFIXES = ("GOMP_", "KMP_", "OMP_")


def _sanitized_child_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _CHILD_ENVIRONMENT_KEYS
        or any(key.startswith(prefix) for prefix in _CHILD_ENVIRONMENT_PREFIXES)
    }
    environment["LANG"] = "C.UTF-8"
    environment["LANGUAGE"] = "C"
    environment["LC_ALL"] = "C.UTF-8"
    environment["PATH"] = "/nonexistent"
    environment["SASL_PATH"] = "/nonexistent"
    environment["TZ"] = "UTC"
    return environment


def _git_child_environment() -> dict[str, str]:
    environment = _sanitized_child_environment()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "PAGER": "cat",
        }
    )
    return environment


@dataclass(frozen=True, slots=True)
class _SealedCapability:
    """Immutable descriptor-backed bytes used for one gate capability."""

    file_descriptor: int
    size_bytes: int
    sha256: str
    executable: bool

    @classmethod
    def bind_path(cls, path: Path, *, executable: bool) -> _SealedCapability:
        resolved = path.resolve(strict=True)
        source_fd = os.open(
            resolved,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        capability_fd: int | None = None
        try:
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode) or (executable and before.st_mode & 0o111 == 0):
                raise RuntimeError("toolchain capability unavailable")
            capability_fd = os.memfd_create(
                "ccparser-capability",
                flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
            )
            digest = sha256()
            size = 0
            while content := os.read(source_fd, 1024 * 1024):
                digest.update(content)
                size += len(content)
                offset = 0
                while offset < len(content):
                    offset += os.write(capability_fd, content[offset:])
            after = os.fstat(source_fd)
            if (
                _stable_file_identity(before) != _stable_file_identity(after)
                or size != before.st_size
            ):
                raise RuntimeError("toolchain capability changed")
            os.fchmod(capability_fd, 0o500 if executable else 0o400)
            os.lseek(capability_fd, 0, os.SEEK_SET)
            seals = fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SEAL
            fcntl.fcntl(capability_fd, fcntl.F_ADD_SEALS, seals)
            capability = cls(
                file_descriptor=capability_fd,
                size_bytes=size,
                sha256=digest.hexdigest(),
                executable=executable,
            )
            capability_fd = None
            return capability
        finally:
            with suppress(OSError):
                os.close(source_fd)
            if capability_fd is not None:
                with suppress(OSError):
                    os.close(capability_fd)

    @classmethod
    def bind_command(cls, command: str) -> _SealedCapability:
        executable = shutil.which(command)
        if executable is None:
            raise RuntimeError("toolchain executable unavailable")
        return cls.bind_path(Path(executable), executable=True)

    @property
    def descriptor_path(self) -> str:
        return f"/proc/self/fd/{self.file_descriptor}"

    def asset(self, role: ToolchainAssetRole) -> ToolchainAsset:
        return ToolchainAsset(
            role=role,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
        )

    def close(self) -> None:
        with suppress(OSError):
            os.close(self.file_descriptor)


def _elf_interpreter(capability: _SealedCapability) -> Path:
    header = os.pread(capability.file_descriptor, 64, 0)
    if len(header) < 52 or header[:4] != b"\x7fELF":
        raise RuntimeError("external runtime unavailable")
    elf_class = header[4]
    byte_order = {1: "<", 2: ">"}.get(header[5])
    if byte_order is None:
        raise RuntimeError("external runtime unavailable")
    try:
        if elf_class == 2:
            values = struct.unpack(f"{byte_order}16sHHIQQQIHHHHHH", header[:64])
            program_offset = values[5]
            program_entry_size = values[9]
            program_count = values[10]
            program_format = f"{byte_order}IIQQQQQQ"
            offset_index = 2
            size_index = 5
        elif elf_class == 1:
            values = struct.unpack(f"{byte_order}16sHHIIIIIHHHHHH", header[:52])
            program_offset = values[5]
            program_entry_size = values[9]
            program_count = values[10]
            program_format = f"{byte_order}IIIIIIII"
            offset_index = 1
            size_index = 4
        else:
            raise RuntimeError("external runtime unavailable")
    except struct.error:
        raise RuntimeError("external runtime unavailable") from None
    expected_machine = {"aarch64": 183, "x86_64": 62}.get(platform.machine().lower())
    if expected_machine is None or values[2] != expected_machine:
        raise RuntimeError("external runtime unavailable")
    expected_entry_size = struct.calcsize(program_format)
    if program_entry_size != expected_entry_size or program_count <= 0 or program_count > 1024:
        raise RuntimeError("external runtime unavailable")
    interpreter: Path | None = None
    for index in range(program_count):
        raw_entry = os.pread(
            capability.file_descriptor,
            program_entry_size,
            program_offset + index * program_entry_size,
        )
        if len(raw_entry) != program_entry_size:
            raise RuntimeError("external runtime unavailable")
        entry = struct.unpack(program_format, raw_entry)
        if entry[0] != 3:  # PT_INTERP
            continue
        raw_interpreter = os.pread(
            capability.file_descriptor,
            entry[size_index],
            entry[offset_index],
        )
        if (
            not raw_interpreter.endswith(b"\0")
            or b"\0" in raw_interpreter[:-1]
            or interpreter is not None
        ):
            raise RuntimeError("external runtime unavailable")
        try:
            decoded = os.fsdecode(raw_interpreter[:-1])
        except UnicodeError:
            raise RuntimeError("external runtime unavailable") from None
        candidate = Path(decoded)
        if not candidate.is_absolute():
            raise RuntimeError("external runtime unavailable")
        interpreter = candidate.resolve(strict=True)
    if interpreter is None:
        raise RuntimeError("external runtime unavailable")
    return interpreter


def _script_interpreter(
    capability: _SealedCapability,
) -> tuple[Path, tuple[str, ...]] | None:
    first_line = os.pread(capability.file_descriptor, 4096, 0).partition(b"\n")[0]
    if not first_line.startswith(b"#!"):
        return None
    try:
        specification = os.fsdecode(first_line[2:]).strip()
    except UnicodeError:
        raise RuntimeError("external runtime unavailable") from None
    fields = specification.split(maxsplit=1)
    if not fields or not Path(fields[0]).is_absolute():
        raise RuntimeError("external runtime unavailable")
    if Path(fields[0]).name == "env":
        raise RuntimeError("external runtime unavailable")
    arguments = () if len(fields) == 1 else (fields[1],)
    return Path(fields[0]).resolve(strict=True), arguments


@dataclass(frozen=True, slots=True)
class _BoundDynamicLibrary:
    alias: str
    capability: _SealedCapability


@dataclass(slots=True)
class _BoundDynamicExecutable:
    """Executable plus a sealed ELF interpreter and shared-library closure."""

    executable: _SealedCapability
    program: _SealedCapability
    interpreter: _SealedCapability
    libraries: tuple[_BoundDynamicLibrary, ...]
    staging_path: Path
    staging_file_descriptor: int
    script_arguments: tuple[str, ...]
    _closed: bool = False

    @classmethod
    def bind_command(
        cls,
        command: str,
        *,
        staging_parent: Path,
    ) -> _BoundDynamicExecutable:
        executable = shutil.which(command)
        if executable is None:
            raise RuntimeError("external runtime unavailable")
        return cls.bind_path(Path(executable), staging_parent=staging_parent)

    @classmethod
    def bind_path(
        cls,
        path: Path,
        *,
        staging_parent: Path,
    ) -> _BoundDynamicExecutable:
        capabilities: list[_SealedCapability] = []
        directory_fd: int | None = None
        staging_path: Path | None = None
        created_aliases: list[str] = []
        try:
            executable = _SealedCapability.bind_path(path, executable=True)
            capabilities.append(executable)
            script = _script_interpreter(executable)
            if script is None:
                program = executable
                script_arguments: tuple[str, ...] = ()
            else:
                program = _SealedCapability.bind_path(script[0], executable=True)
                capabilities.append(program)
                script_arguments = (*script[1], executable.descriptor_path)
            interpreter_path = _elf_interpreter(program)
            interpreter = _SealedCapability.bind_path(interpreter_path, executable=True)
            capabilities.append(interpreter)
            discovery = subprocess.run(
                (interpreter.descriptor_path, "--list", program.descriptor_path),
                check=True,
                capture_output=True,
                env=_sanitized_child_environment(),
                pass_fds=(interpreter.file_descriptor, program.file_descriptor),
                timeout=10.0,
            ).stdout.decode("utf-8", errors="strict")
            library_sources: dict[Path, _SealedCapability] = {}
            libraries: list[_BoundDynamicLibrary] = []
            aliases: set[str] = set()
            for line in discovery.splitlines():
                match = _DYNAMIC_LIBRARY_LIST_LINE.fullmatch(line)
                if match is None:
                    continue
                alias = match.group("alias")
                if "/" in alias:
                    continue
                if alias in aliases or alias in {"", ".", ".."}:
                    raise RuntimeError("external runtime unavailable")
                source = Path(match.group("path")).resolve(strict=True)
                capability = library_sources.get(source)
                if capability is None:
                    capability = _SealedCapability.bind_path(source, executable=False)
                    capabilities.append(capability)
                    library_sources[source] = capability
                aliases.add(alias)
                libraries.append(_BoundDynamicLibrary(alias, capability))
            if not libraries:
                raise RuntimeError("external runtime unavailable")
            staging_parent = staging_parent.resolve(strict=True)
            if not staging_parent.is_dir():
                raise RuntimeError("external runtime unavailable")
            staging_path = Path(
                tempfile.mkdtemp(prefix="ccparser-runtime-", dir=staging_parent)
            ).resolve(strict=True)
            directory_fd = os.open(staging_path, _DIRECTORY_OPEN_FLAGS)
            for library in libraries:
                os.symlink(
                    library.capability.descriptor_path,
                    library.alias,
                    dir_fd=directory_fd,
                )
                created_aliases.append(library.alias)
            os.fchmod(directory_fd, 0o500)
            result = cls(
                executable=executable,
                program=program,
                interpreter=interpreter,
                libraries=tuple(libraries),
                staging_path=staging_path,
                staging_file_descriptor=directory_fd,
                script_arguments=script_arguments,
            )
            capabilities.clear()
            directory_fd = None
            staging_path = None
            return result
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("external runtime unavailable") from None
        finally:
            if directory_fd is not None:
                with suppress(OSError):
                    os.fchmod(directory_fd, 0o700)
                for alias in reversed(created_aliases):
                    with suppress(OSError):
                        os.unlink(alias, dir_fd=directory_fd)
                with suppress(OSError):
                    os.close(directory_fd)
            if staging_path is not None:
                with suppress(OSError):
                    os.rmdir(staging_path)
            for capability in reversed(capabilities):
                capability.close()

    @property
    def executable_file_descriptors(self) -> tuple[int, ...]:
        unique = {
            capability.file_descriptor: capability
            for capability in (
                self.program,
                self.interpreter,
                *(library.capability for library in self.libraries),
            )
        }
        return tuple(unique)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.executable.file_descriptor,
                    *self.executable_file_descriptors,
                    self.staging_file_descriptor,
                )
            )
        )

    @property
    def native_closure(self) -> RuntimeArtifactIdentity:
        unique = {
            capability.file_descriptor: capability
            for capability in (
                self.program,
                self.interpreter,
                *(library.capability for library in self.libraries),
            )
        }
        records = tuple(
            sorted((capability.size_bytes, capability.sha256) for capability in unique.values())
        )
        bindings = (
            ("program", self.program.sha256),
            ("interpreter", self.interpreter.sha256),
            *(sorted((library.alias, library.capability.sha256) for library in self.libraries)),
        )
        return RuntimeArtifactIdentity(
            file_count=len(records),
            size_bytes=sum(size for size, _digest in records),
            digest=_toolchain_payload_digest({"bindings": bindings, "files": records}),
        )

    def _validate_staging(self) -> None:
        directory = os.fstat(self.staging_file_descriptor)
        named_directory = os.stat(self.staging_path, follow_symlinks=False)
        expected_names = tuple(sorted(library.alias for library in self.libraries))
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.geteuid()
            or stat.S_IMODE(directory.st_mode) != 0o500
            or _stable_file_identity(directory) != _stable_file_identity(named_directory)
            or tuple(sorted(os.listdir(self.staging_file_descriptor))) != expected_names
        ):
            raise RuntimeError("external runtime unavailable")
        for library in self.libraries:
            capability = os.fstat(library.capability.file_descriptor)
            link = os.stat(
                library.alias,
                dir_fd=self.staging_file_descriptor,
                follow_symlinks=False,
            )
            target = os.stat(
                library.alias,
                dir_fd=self.staging_file_descriptor,
                follow_symlinks=True,
            )
            if (
                not stat.S_ISLNK(link.st_mode)
                or os.readlink(library.alias, dir_fd=self.staging_file_descriptor)
                != library.capability.descriptor_path
                or _stable_file_identity(target) != _stable_file_identity(capability)
            ):
                raise RuntimeError("external runtime unavailable")

    def command(self, arguments: tuple[str, ...], *, argv0: str) -> tuple[str, ...]:
        return (
            self.interpreter.descriptor_path,
            "--inhibit-cache",
            "--library-path",
            f"/proc/self/fd/{self.staging_file_descriptor}",
            "--glibc-hwcaps-mask",
            "",
            "--argv0",
            argv0,
            self.program.descriptor_path,
            *self.script_arguments,
            *arguments,
        )

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
        if self._closed:
            raise RuntimeError("external runtime unavailable")
        self._validate_staging()
        try:
            return run_traced_subprocess(
                self.command(arguments, argv0="external-tool"),
                cwd=cwd,
                environment=dict(environment),
                inherited_file_descriptors=self.pass_fds,
                allowed_file_descriptors=(
                    self.executable_file_descriptors
                    if allowed_file_descriptors is None
                    else allowed_file_descriptors
                ),
                timeout=timeout,
                input_bytes=input_bytes,
                stderr_to_stdout=stderr_to_stdout,
            )
        finally:
            self._validate_staging()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(OSError):
            os.fchmod(self.staging_file_descriptor, 0o700)
        for library in self.libraries:
            with suppress(OSError):
                os.unlink(library.alias, dir_fd=self.staging_file_descriptor)
        with suppress(OSError):
            os.close(self.staging_file_descriptor)
        with suppress(OSError):
            os.rmdir(self.staging_path)
        unique = {
            capability.file_descriptor: capability
            for capability in (
                self.executable,
                self.program,
                self.interpreter,
                *(library.capability for library in self.libraries),
            )
        }
        for capability in reversed(tuple(unique.values())):
            capability.close()


_DYNAMIC_LIBRARY_LIST_LINE = re.compile(r"\s*(?P<alias>\S+) => (?P<path>/\S+) \(0x[0-9a-fA-F]+\)")


def _active_git_directory(cwd: Path) -> Path:
    resolved = cwd.resolve(strict=True)
    for candidate_root in (resolved, *resolved.parents):
        marker = candidate_root / ".git"
        if marker.is_dir():
            return marker.resolve(strict=True)
        if not marker.is_file() or marker.is_symlink():
            continue
        content = marker.read_text(encoding="utf-8").strip()
        prefix = "gitdir: "
        if not content.startswith(prefix) or "\n" in content:
            raise RuntimeError("external runtime unavailable")
        git_directory = Path(content.removeprefix(prefix))
        if not git_directory.is_absolute():
            git_directory = marker.parent / git_directory
        return git_directory.resolve(strict=True)
    raise RuntimeError("external runtime unavailable")


@dataclass(slots=True)
class _GateRuntimeCapabilities:
    """Exact external capabilities shared by every adapter in one gate."""

    git: _SealedCapability
    git_runtime: _BoundDynamicExecutable
    staging_parent: Path
    git_environment: tuple[tuple[str, str], ...]
    tesseract_environment: tuple[tuple[str, str], ...]
    tesseract: _BoundTesseract | None = None

    @classmethod
    def bind(cls) -> _GateRuntimeCapabilities:
        staging_parent = _active_git_directory(Path.cwd())
        git_runtime = _BoundDynamicExecutable.bind_command(
            "git",
            staging_parent=staging_parent,
        )
        return cls(
            git=git_runtime.executable,
            git_runtime=git_runtime,
            staging_parent=staging_parent,
            git_environment=tuple(sorted(_git_child_environment().items())),
            tesseract_environment=tuple(sorted(_sanitized_child_environment().items())),
        )

    def tesseract_metadata(
        self,
        commands: tuple[tuple[str, ...], ...],
    ) -> tuple[str, str, tuple[ToolchainAsset, ...]]:
        if self.tesseract is None:
            self.tesseract = _BoundTesseract.bind(
                commands,
                environment=self.tesseract_environment,
                staging_parent=self.staging_parent,
            )
        return self.tesseract.metadata()

    def stage_tesseract(self, work_fd: int) -> _StagedTesseractRuntime:
        if self.tesseract is None:
            raise RuntimeError("Tesseract capability is not fingerprinted")
        return self.tesseract.stage(work_fd)

    @property
    def tesseract_native_closure(self) -> RuntimeArtifactIdentity:
        if self.tesseract is None:
            raise RuntimeError("Tesseract capability is not fingerprinted")
        return self.tesseract.execution_runtime.native_closure

    def close(self) -> None:
        if self.tesseract is not None:
            self.tesseract.close()
        self.git_runtime.close()


class GitRepositoryInspector:
    """Inspect the active worktree while deriving containment from Git common state."""

    _TIMEOUT_SECONDS = 10.0
    _PACKAGE_ERROR = "active worktree package unavailable"
    _PACKAGE_PREFIX = ("src", "ccparser")
    _PACKAGE_PATHSPEC = ":(top,literal)src/ccparser"

    def __init__(
        self,
        *,
        cwd: Path | None = None,
        executable: _SealedCapability | None = None,
        execution_runtime: _BoundDynamicExecutable | None = None,
        environment: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        self._cwd = (cwd or Path.cwd()).resolve(strict=True)
        self._execution_runtime = execution_runtime
        self._executable = executable or (
            execution_runtime.executable
            if execution_runtime is not None
            else _SealedCapability.bind_command("git")
        )
        self._owns_executable = executable is None
        self._environment = environment or tuple(sorted(_git_child_environment().items()))

    @property
    def executable_asset(self) -> ToolchainAsset:
        return self._executable.asset("git-executable")

    def _command(self, *arguments: str) -> tuple[str, ...]:
        return (self._executable.descriptor_path, "--no-replace-objects", *arguments)

    def _git_output(self, *arguments: str) -> bytes:
        if self._execution_runtime is not None:
            completed = self._execution_runtime.run(
                ("--no-replace-objects", *arguments),
                cwd=self._cwd,
                environment=self._environment,
                timeout=self._TIMEOUT_SECONDS,
            )
            if completed.returncode != 0:
                raise subprocess.CalledProcessError(
                    completed.returncode,
                    completed.args,
                    completed.stdout,
                    completed.stderr,
                )
            return completed.stdout
        completed = subprocess.run(
            self._command(*arguments),
            cwd=self._cwd,
            check=True,
            capture_output=True,
            env=dict(self._environment),
            pass_fds=(self._executable.file_descriptor,),
            timeout=self._TIMEOUT_SECONDS,
        )
        return completed.stdout

    def close(self) -> None:
        if self._owns_executable:
            if self._execution_runtime is not None:
                self._execution_runtime.close()
            else:
                self._executable.close()

    def _read_project_root(self) -> Path:
        common_output = self._git_output(
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
        common_value = common_output.decode("utf-8").strip()
        if not common_value:
            raise RuntimeError("Git metadata unavailable")
        return Path(common_value).resolve(strict=True).parent

    def _validate_active_worktree_package(self) -> Path:
        try:
            active_output = self._git_output("rev-parse", "--show-toplevel")
            active_value = active_output.decode("utf-8").strip()
            if not active_value:
                raise ValueError
            active_root = Path(active_value).resolve(strict=True)
            expected_module = (active_root / "src" / "ccparser" / "corpus_gate.py").resolve(
                strict=True
            )
            imported_module = Path(__file__).resolve(strict=True)
            if (
                not expected_module.is_relative_to(active_root)
                or expected_module != imported_module
            ):
                raise ValueError
        except Exception:
            raise RuntimeError(self._PACKAGE_ERROR) from None
        return active_root

    @classmethod
    def _runtime_path(cls, raw_path: bytes) -> PurePosixPath:
        decoded_path = os.fsdecode(raw_path)
        path = PurePosixPath(decoded_path)
        if (
            path.is_absolute()
            or path.as_posix() != decoded_path
            or len(path.parts) <= len(cls._PACKAGE_PREFIX)
            or path.parts[: len(cls._PACKAGE_PREFIX)] != cls._PACKAGE_PREFIX
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError
        return path

    def _indexed_runtime_paths(self) -> frozenset[PurePosixPath]:
        output = self._git_output(
            "ls-files",
            "-v",
            "-z",
            "--full-name",
            "--",
            self._PACKAGE_PATHSPEC,
        )
        paths: set[PurePosixPath] = set()
        for record in output.split(b"\0"):
            if not record:
                continue
            if len(record) < 3 or record[1:2] != b" " or record[:1] != b"H":
                raise ValueError
            path = self._runtime_path(record[2:])
            if path in paths:
                raise ValueError
            paths.add(path)
        if not paths:
            raise ValueError
        return frozenset(paths)

    def _head_runtime_sources(
        self,
        active_root: Path,
        commit_sha: str,
    ) -> Mapping[Path, bytes]:
        output = self._git_output(
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit_sha,
            "--",
            self._PACKAGE_PATHSPEC,
        )
        indexed_paths = self._indexed_runtime_paths()
        tree_paths: set[PurePosixPath] = set()
        sources: dict[Path, bytes] = {}
        active_root_fd = os.open(active_root, _DIRECTORY_OPEN_FLAGS)
        try:
            for record in output.split(b"\0"):
                if not record:
                    continue
                metadata_bytes, separator, raw_path = record.partition(b"\t")
                metadata = metadata_bytes.split(b" ")
                if separator != b"\t" or len(metadata) != 3:
                    raise ValueError
                mode, object_type, raw_object_id = metadata
                if mode not in {b"100644", b"100755"} or object_type != b"blob":
                    raise ValueError
                object_id = raw_object_id.decode("ascii")
                if len(object_id) != 40 or any(
                    character not in "0123456789abcdef" for character in object_id
                ):
                    raise ValueError
                path = self._runtime_path(raw_path)
                if path in tree_paths:
                    raise ValueError
                tree_paths.add(path)
                active_path = active_root.joinpath(*path.parts)
                if active_path.resolve(strict=True) != active_path:
                    raise ValueError
                active_source = _read_stable_regular_file(
                    active_root_fd,
                    active_root,
                    active_path,
                )
                if active_source != self._git_output("cat-file", "blob", object_id):
                    raise ValueError
                sources[active_path] = active_source
        finally:
            os.close(active_root_fd)
        if frozenset(tree_paths) != indexed_paths:
            raise ValueError
        expected_gate = active_root.joinpath(*self._PACKAGE_PREFIX, "corpus_gate.py")
        if expected_gate not in sources:
            raise ValueError
        return sources

    @staticmethod
    def _nested_code_objects(code: CodeType) -> frozenset[CodeType]:
        nested = {code}
        for constant in code.co_consts:
            if isinstance(constant, CodeType):
                nested.update(GitRepositoryInspector._nested_code_objects(constant))
        return frozenset(nested)

    @staticmethod
    def _runtime_functions(module: ModuleType) -> tuple[FunctionType, ...]:
        functions: set[FunctionType] = set()
        seen_classes: set[type[object]] = set()

        def collect(value: object) -> None:
            if isinstance(value, FunctionType):
                if value.__module__ == "ccparser" or value.__module__.startswith("ccparser."):
                    functions.add(value)
                return
            if isinstance(value, staticmethod | classmethod):
                collect(value.__func__)
                return
            if isinstance(value, property):
                for accessor in (value.fget, value.fset, value.fdel):
                    if accessor is not None:
                        collect(accessor)
                return
            if (
                isinstance(value, type)
                and value not in seen_classes
                and (value.__module__ == "ccparser" or value.__module__.startswith("ccparser."))
            ):
                seen_classes.add(value)
                for member in vars(value).values():
                    collect(member)

        for attribute in vars(module).values():
            collect(attribute)
        return tuple(
            sorted(
                functions,
                key=lambda function: (
                    function.__module__,
                    function.__qualname__,
                    function.__code__.co_filename,
                    function.__code__.co_firstlineno,
                ),
            )
        )

    @classmethod
    def _validate_live_runtime_code(
        cls,
        loaded_modules: tuple[tuple[str, ModuleType], ...],
        sources: Mapping[Path, bytes],
    ) -> None:
        compiled_by_origin: dict[tuple[Path, str], frozenset[CodeType]] = {}
        for _module_name, module in loaded_modules:
            for function in cls._runtime_functions(module):
                code = function.__code__
                if code.co_filename.startswith("<"):
                    continue
                try:
                    source_path = Path(code.co_filename).resolve(strict=True)
                except OSError:
                    raise ValueError from None
                source = sources.get(source_path)
                if source is None:
                    if "ccparser" in source_path.parts:
                        raise ValueError
                    continue
                cache_key = (source_path, code.co_filename)
                allowed_codes = compiled_by_origin.get(cache_key)
                if allowed_codes is None:
                    allowed_codes = cls._nested_code_objects(
                        compile(
                            source,
                            code.co_filename,
                            "exec",
                            dont_inherit=True,
                            optimize=sys.flags.optimize,
                        )
                    )
                    compiled_by_origin[cache_key] = allowed_codes
                if code not in allowed_codes:
                    raise ValueError

    @staticmethod
    def _executed_package_top_levels(
        package: ModuleType,
        sources: Mapping[Path, bytes],
    ) -> Mapping[Path, frozenset[CodeType]]:
        raw_registry = vars(package).get("_EXECUTED_PACKAGE_CODES")
        if not isinstance(raw_registry, dict):
            raise ValueError
        registry: dict[Path, frozenset[CodeType]] = {}
        for raw_path, raw_codes in raw_registry.items():
            if not isinstance(raw_path, str) or not isinstance(raw_codes, set) or not raw_codes:
                raise ValueError
            source_path = Path(raw_path).resolve(strict=True)
            if (
                str(source_path) != raw_path
                or source_path not in sources
                or source_path in registry
            ):
                raise ValueError
            codes: set[CodeType] = set()
            for code in raw_codes:
                if (
                    not isinstance(code, CodeType)
                    or code.co_name != "<module>"
                    or Path(code.co_filename).resolve(strict=True) != source_path
                ):
                    raise ValueError
                codes.add(code)
            approved_code = compile(
                sources[source_path],
                raw_path,
                "exec",
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
            if codes != {approved_code}:
                raise ValueError
            registry[source_path] = frozenset(codes)
        return registry

    @classmethod
    def _validate_loaded_runtime(cls, sources: Mapping[Path, bytes]) -> None:
        gate_loaded = False
        raw_loaded_modules = tuple(
            sorted(
                (
                    (name, module)
                    for name, module in sys.modules.items()
                    if name == "ccparser" or name.startswith("ccparser.")
                ),
                key=lambda item: item[0],
            )
        )
        package = dict(raw_loaded_modules).get("ccparser")
        if not isinstance(package, ModuleType):
            raise ValueError
        executed_top_levels = cls._executed_package_top_levels(package, sources)
        loaded_modules: list[tuple[str, ModuleType]] = []
        for module_name, module in raw_loaded_modules:
            if not isinstance(module, ModuleType):
                raise ValueError
            loaded_modules.append((module_name, module))
            module_file = getattr(module, "__file__", None)
            specification = module.__spec__
            if (
                not isinstance(module_file, str)
                or specification is None
                or specification.name != module_name
                or not isinstance(specification.origin, str)
                or not isinstance(specification.loader, _SourceCodeLoader)
            ):
                raise ValueError
            module_path = Path(module_file).resolve(strict=True)
            if Path(specification.origin).resolve(strict=True) != module_path:
                raise ValueError
            source = sources.get(module_path)
            if source is None:
                raise ValueError
            loaded_code = specification.loader.get_code(module_name)
            if not isinstance(loaded_code, CodeType):
                raise ValueError
            compiled_code = compile(
                source,
                specification.origin,
                "exec",
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
            if loaded_code != compiled_code:
                raise ValueError
            if compiled_code not in executed_top_levels.get(module_path, frozenset()):
                raise ValueError
            gate_loaded = gate_loaded or module_name == "ccparser.corpus_gate"
        if not gate_loaded:
            raise ValueError
        cls._validate_live_runtime_code(tuple(loaded_modules), sources)

    def _validate_runtime_attribution(self, active_root: Path, commit_sha: str) -> None:
        try:
            sources = self._head_runtime_sources(active_root, commit_sha)
            self._validate_loaded_runtime(sources)
        except Exception:
            raise RuntimeError(self._PACKAGE_ERROR) from None

    def _repository_observation(self) -> tuple[str, bytes]:
        commit_output = self._git_output("rev-parse", "--verify", "HEAD")
        status_output = self._git_output(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        commit_sha = commit_output.decode("ascii").strip()
        if len(commit_sha) != 40 or any(
            character not in "0123456789abcdef" for character in commit_sha
        ):
            raise RuntimeError("Git metadata unavailable")
        return commit_sha, status_output

    def state(self) -> RepositoryState:
        active_root = self._validate_active_worktree_package()
        project_root = self._read_project_root()
        commit_sha, status_output = self._repository_observation()
        self._validate_runtime_attribution(active_root, commit_sha)
        if self._repository_observation() != (commit_sha, status_output):
            raise RuntimeError(self._PACKAGE_ERROR)
        return RepositoryState(
            root=project_root,
            commit_sha=commit_sha,
            clean=not bool(status_output.strip()),
        )

    def _worktree_for_path(self, path: Path) -> Path:
        worktree_output = self._git_output("worktree", "list", "--porcelain", "-z")
        roots = tuple(
            Path(os.fsdecode(entry.removeprefix(b"worktree "))).resolve(strict=False)
            for entry in worktree_output.split(b"\0")
            if entry.startswith(b"worktree ")
        )
        candidates = tuple(root for root in roots if path.is_relative_to(root))
        if not candidates:
            raise RuntimeError("Git worktree unavailable for path")
        return max(candidates, key=lambda root: len(root.parts))

    def is_ignored(self, path: Path) -> bool:
        resolved_path = path.resolve(strict=False)
        worktree_root = self._worktree_for_path(resolved_path)
        if self._execution_runtime is None:
            completed = subprocess.run(
                self._command("check-ignore", "--quiet", "--", str(resolved_path)),
                cwd=worktree_root,
                check=False,
                env=dict(self._environment),
                pass_fds=(self._executable.file_descriptor,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self._TIMEOUT_SECONDS,
            )
        else:
            completed = self._execution_runtime.run(
                (
                    "--no-replace-objects",
                    "check-ignore",
                    "--quiet",
                    "--",
                    str(resolved_path),
                ),
                cwd=worktree_root,
                environment=self._environment,
                timeout=self._TIMEOUT_SECONDS,
            )
        if completed.returncode not in {0, 1}:
            raise RuntimeError("Git ignore policy unavailable")
        return completed.returncode == 0


_RUNTIME_ENVIRONMENT_KEYS = frozenset(
    {
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "MALLOC_ARENA_MAX",
        "OPENBLAS_NUM_THREADS",
        "PATH",
        "PYTHONHASHSEED",
        "PYTHONMALLOC",
        "PYTHONUTF8",
        "TESSDATA_PREFIX",
        "TZ",
    }
)
_RUNTIME_ENVIRONMENT_PREFIXES = ("GOMP_", "KMP_", "LC_", "OMP_")
_TESSDATA_HEADER = re.compile(r'^List of available languages in "(?P<directory>.+)" \(\d+\):$')


def _stable_content_identity(path: Path, *, require_executable: bool = False) -> tuple[int, str]:
    resolved = path.resolve(strict=True)
    file_descriptor = os.open(
        resolved,
        os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or (require_executable and before.st_mode & 0o111 == 0):
            raise RuntimeError("toolchain asset unavailable")
        digest = sha256()
        size = 0
        while content := os.read(file_descriptor, 1024 * 1024):
            digest.update(content)
            size += len(content)
        after = os.fstat(file_descriptor)
        if _stable_file_identity(before) != _stable_file_identity(after) or size != before.st_size:
            raise RuntimeError("toolchain asset changed")
        return size, digest.hexdigest()
    finally:
        os.close(file_descriptor)


@dataclass(frozen=True, slots=True)
class _RuntimeDistributionInventory:
    distribution: metadata.Distribution
    files: tuple[metadata.PackagePath, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeDistributionSnapshot:
    dependency: RuntimeDependency
    installation_root: Path
    artifact_paths: frozenset[Path]
    source_origins: frozenset[tuple[str, Path]]
    bytecode_origins: frozenset[tuple[str, Path]]
    native_origins: frozenset[tuple[str, Path]]


@dataclass(frozen=True, slots=True)
class _StandardLibrarySnapshot:
    identity: RuntimeArtifactIdentity
    artifact_paths: frozenset[Path]
    source_origins: frozenset[Path]
    bytecode_origins: frozenset[Path]
    native_origins: frozenset[Path]


type _StandardLibraryCandidate = tuple[str, Path, str | None]
type _LoadedModuleKind = Literal["source", "bytecode", "native"]

_STANDARD_LIBRARY_EXCLUDED_DIRECTORIES = frozenset({"dist-packages", "site-packages"})


def _module_artifact_kind(filename: str) -> _LoadedModuleKind | None:
    if filename.endswith(".py"):
        return "source"
    if filename.endswith((".pyc", ".pyo")):
        return "bytecode"
    if any(filename.endswith(suffix) for suffix in EXTENSION_SUFFIXES):
        return "native"
    return None


def _standard_library_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for scheme_name in ("stdlib", "platstdlib"):
        raw_root = sysconfig.get_path(scheme_name)
        if not isinstance(raw_root, str) or not raw_root:
            raise RuntimeError("standard-library inventory unavailable")
        root = Path(raw_root).resolve(strict=True)
        if not root.is_dir():
            raise RuntimeError("standard-library inventory unavailable")
        if root not in roots:
            roots.append(root)
    if not roots:
        raise RuntimeError("standard-library inventory unavailable")
    return tuple(roots)


def _standard_library_candidates(
    roots: tuple[Path, ...],
) -> tuple[_StandardLibraryCandidate, ...]:
    candidates: list[_StandardLibraryCandidate] = []

    def fail_walk(error: OSError) -> None:
        raise RuntimeError("standard-library inventory unavailable") from error

    for root_index, root in enumerate(roots):
        for raw_directory, raw_directories, raw_filenames in os.walk(
            root,
            topdown=True,
            onerror=fail_walk,
            followlinks=False,
        ):
            directory = Path(raw_directory)
            directories: list[str] = []
            for name in sorted(raw_directories):
                child = directory / name
                if name in _STANDARD_LIBRARY_EXCLUDED_DIRECTORIES:
                    continue
                if child.is_symlink():
                    raise RuntimeError("standard-library inventory unavailable")
                directories.append(name)
            raw_directories[:] = directories
            for filename in sorted(raw_filenames):
                path = directory / filename
                relative_path = path.relative_to(root)
                if path.is_symlink():
                    try:
                        link_target: str | None = os.readlink(path)
                    except OSError:
                        raise RuntimeError("standard-library inventory unavailable") from None
                else:
                    link_target = None
                candidates.append(
                    (
                        f"{root_index}:{relative_path.as_posix()}",
                        path,
                        link_target,
                    )
                )
    return tuple(candidates)


def _snapshot_standard_library(
    roots: tuple[Path, ...] | None = None,
) -> _StandardLibrarySnapshot:
    raw_roots = _standard_library_roots() if roots is None else roots
    normalized_roots: list[Path] = []
    for raw_root in raw_roots:
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise RuntimeError("standard-library inventory unavailable")
        if root not in normalized_roots:
            normalized_roots.append(root)
    if not normalized_roots:
        raise RuntimeError("standard-library inventory unavailable")
    active_roots = tuple(normalized_roots)
    candidates = _standard_library_candidates(active_roots)
    records: list[tuple[str, str | None, int, str]] = []
    artifact_paths: set[Path] = set()
    source_origins: set[Path] = set()
    bytecode_origins: set[Path] = set()
    native_origins: set[Path] = set()
    for label, path, link_target in candidates:
        resolved_path = path.resolve(strict=True)
        size_bytes, content_digest = _stable_content_identity(resolved_path)
        artifact_paths.add(resolved_path)
        lexical_kind = _module_artifact_kind(path.name)
        resolved_kind = _module_artifact_kind(resolved_path.name)
        artifact_kind = lexical_kind if lexical_kind == resolved_kind else None
        if artifact_kind == "source":
            source_origins.add(resolved_path)
        elif artifact_kind == "bytecode":
            bytecode_origins.add(resolved_path)
        elif artifact_kind == "native":
            native_origins.add(resolved_path)
        records.append((label, link_target, size_bytes, content_digest))
    if not records or _standard_library_candidates(active_roots) != candidates:
        raise RuntimeError("standard-library inventory unavailable")
    identity = RuntimeArtifactIdentity(
        file_count=len(records),
        size_bytes=sum(record[2] for record in records),
        digest=_toolchain_payload_digest({"files": tuple(records)}),
    )
    return _StandardLibrarySnapshot(
        identity=identity,
        artifact_paths=frozenset(artifact_paths),
        source_origins=frozenset(source_origins),
        bytecode_origins=frozenset(bytecode_origins),
        native_origins=frozenset(native_origins),
    )


def _is_runtime_distribution_file(relative_path: PurePosixPath) -> bool:
    return bool(relative_path.parts)


def _module_top_level(relative_path: PurePosixPath) -> str | None:
    if (
        not relative_path.parts
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
        or relative_path.parts[0].endswith((".data", ".dist-info"))
    ):
        return None
    filename = relative_path.name
    is_python = filename.endswith(".py")
    is_bytecode = filename.endswith((".pyc", ".pyo"))
    is_extension = any(filename.endswith(suffix) for suffix in EXTENSION_SUFFIXES)
    if not (is_python or is_bytecode or is_extension):
        return None
    if is_bytecode and relative_path.parts[0] == "__pycache__":
        return filename.partition(".")[0]
    if len(relative_path.parts) > 1:
        return relative_path.parts[0]
    if is_python:
        return filename.removesuffix(".py")
    if is_bytecode:
        return filename.partition(".")[0]
    for suffix in EXTENSION_SUFFIXES:
        if filename.endswith(suffix):
            return filename.removesuffix(suffix)
    raise AssertionError("unreachable extension suffix")


def _inventoried_runtime_distribution(
    name: RuntimeDependencyName,
) -> _RuntimeDistributionInventory:
    try:
        inventoried: list[_RuntimeDistributionInventory] = []
        for distribution in metadata.distributions(name=name):
            raw_files = distribution.files
            if raw_files:
                inventoried.append(
                    _RuntimeDistributionInventory(
                        distribution=distribution,
                        files=tuple(raw_files),
                    )
                )
    except Exception:
        raise RuntimeError("runtime distribution inventory unavailable") from None
    if len(inventoried) != 1:
        raise RuntimeError("runtime distribution inventory unavailable")
    return inventoried[0]


def _snapshot_runtime_distribution(
    name: RuntimeDependencyName,
    *,
    distribution: metadata.Distribution | None = None,
) -> _RuntimeDistributionSnapshot:
    if distribution is None:
        inventory = _inventoried_runtime_distribution(name)
    else:
        discovered_files = distribution.files
        if discovered_files is None:
            raise RuntimeError("runtime distribution inventory unavailable")
        inventory = _RuntimeDistributionInventory(
            distribution=distribution,
            files=tuple(discovered_files),
        )
    installed = inventory.distribution
    raw_files = inventory.files
    records: list[tuple[str, int, str]] = []
    artifact_paths: set[Path] = set()
    source_origins: set[tuple[str, Path]] = set()
    bytecode_origins: set[tuple[str, Path]] = set()
    native_origins: set[tuple[str, Path]] = set()
    seen_labels: set[str] = set()
    seen_paths: set[Path] = set()
    for raw_file in sorted(raw_files, key=str):
        relative_path = PurePosixPath(str(raw_file))
        label = relative_path.as_posix()
        if not label or relative_path.is_absolute() or label in seen_labels:
            raise RuntimeError("runtime distribution inventory unavailable")
        seen_labels.add(label)
        if not _is_runtime_distribution_file(relative_path):
            continue
        actual_path = Path(str(installed.locate_file(raw_file))).resolve(strict=True)
        if actual_path in seen_paths:
            raise RuntimeError("runtime distribution inventory unavailable")
        seen_paths.add(actual_path)
        artifact_paths.add(actual_path)
        size_bytes, content_digest = _stable_content_identity(actual_path)
        records.append((label, size_bytes, content_digest))
        top_level = _module_top_level(relative_path)
        lexical_kind = _module_artifact_kind(relative_path.name)
        resolved_kind = _module_artifact_kind(actual_path.name)
        artifact_kind = lexical_kind if lexical_kind == resolved_kind else None
        if top_level is not None and artifact_kind is not None:
            origin = (top_level, actual_path)
            if artifact_kind == "source":
                source_origins.add(origin)
            elif artifact_kind == "bytecode":
                bytecode_origins.add(origin)
            else:
                native_origins.add(origin)
    if not records:
        raise RuntimeError("runtime distribution inventory unavailable")
    version = str(installed.version)
    dependency = RuntimeDependency(
        name=name,
        version=version,
        file_count=len(records),
        size_bytes=sum(record[1] for record in records),
        content_digest=_toolchain_payload_digest({"files": tuple(records)}),
    )
    return _RuntimeDistributionSnapshot(
        dependency=dependency,
        installation_root=Path(str(installed.locate_file(""))).resolve(strict=True),
        artifact_paths=frozenset(artifact_paths),
        source_origins=frozenset(source_origins),
        bytecode_origins=frozenset(bytecode_origins),
        native_origins=frozenset(native_origins),
    )


@dataclass(frozen=True, slots=True)
class _LoadedModuleBinding:
    kind: _LoadedModuleKind
    origin: Path
    cached_origin: Path | None


def _canonical_file_module_binding(
    module_name: str,
    module: ModuleType,
) -> _LoadedModuleBinding:
    module_file = getattr(module, "__file__", None)
    specification = module.__spec__
    if (
        not isinstance(module_file, str)
        or specification is None
        or specification.name != module_name
        or module.__name__ != module_name
        or not isinstance(specification.origin, str)
        or module_file != specification.origin
        or module.__loader__ is not specification.loader
    ):
        raise RuntimeError("loaded runtime origin unavailable")
    loader: object = specification.loader
    if not isinstance(
        loader,
        SourceFileLoader | SourcelessFileLoader | ExtensionFileLoader,
    ):
        raise RuntimeError("loaded runtime origin unavailable")
    if type(loader) not in (
        SourceFileLoader,
        SourcelessFileLoader,
        ExtensionFileLoader,
    ):
        raise RuntimeError("loaded runtime origin unavailable")
    if loader.name != module_name or loader.path != module_file:
        raise RuntimeError("loaded runtime origin unavailable")
    origin = Path(module_file).resolve(strict=True)
    cached_path: Path | None = None
    raw_cached = getattr(module, "__cached__", None)
    if raw_cached != specification.cached:
        raise RuntimeError("loaded runtime origin unavailable")
    if type(loader) is SourceFileLoader:
        if not Path(module_file).name.endswith(".py"):
            raise RuntimeError("loaded runtime origin unavailable")
        if raw_cached is not None:
            if not isinstance(raw_cached, str) or raw_cached != cache_from_source(module_file):
                raise RuntimeError("loaded runtime origin unavailable")
            cached_candidate = Path(raw_cached)
            if cached_candidate.exists():
                cached_path = cached_candidate.resolve(strict=True)
        loaded_code = loader.get_code(module_name)
        if not isinstance(loaded_code, CodeType):
            raise RuntimeError("loaded runtime origin unavailable")
        return _LoadedModuleBinding(
            kind="source",
            origin=origin,
            cached_origin=cached_path,
        )
    if type(loader) is SourcelessFileLoader:
        if not Path(module_file).name.endswith((".pyc", ".pyo")):
            raise RuntimeError("loaded runtime origin unavailable")
        if raw_cached not in {None, module_file}:
            raise RuntimeError("loaded runtime origin unavailable")
        loaded_code = loader.get_code(module_name)
        if not isinstance(loaded_code, CodeType):
            raise RuntimeError("loaded runtime origin unavailable")
        return _LoadedModuleBinding(
            kind="bytecode",
            origin=origin,
            cached_origin=origin,
        )
    if (
        not any(Path(module_file).name.endswith(suffix) for suffix in EXTENSION_SUFFIXES)
        or raw_cached is not None
        or loader.get_code(module_name) is not None
    ):
        raise RuntimeError("loaded runtime origin unavailable")
    return _LoadedModuleBinding(
        kind="native",
        origin=origin,
        cached_origin=None,
    )


_NATIVE_TYPE_MEMBER_TYPES = (
    BuiltinFunctionType,
    ClassMethodDescriptorType,
    GetSetDescriptorType,
    MemberDescriptorType,
    MethodDescriptorType,
    WrapperDescriptorType,
)


def _is_native_type_metadata(value: object) -> bool:
    if value is None or isinstance(value, bool | bytes | int | str):
        return True
    return isinstance(value, tuple) and all(_is_native_type_metadata(item) for item in value)


def _is_native_extension_type(value: object, *, module_name: str) -> bool:
    if not isinstance(value, type) or value.__module__ != module_name:
        return False
    has_native_member = False
    for member in vars(value).values():
        if isinstance(member, _NATIVE_TYPE_MEMBER_TYPES):
            has_native_member = True
        elif not _is_native_type_metadata(member):
            return False
    return has_native_member


def _is_python_capsule(value: object) -> bool:
    value_type = type(value)
    return (
        value_type.__module__ == "builtins"
        and value_type.__name__ == "PyCapsule"
        and value_type.__flags__ & (1 << 9) == 0  # Py_TPFLAGS_HEAPTYPE
    )


def _is_originless_native_data_module(module_name: str, module: ModuleType) -> bool:
    if (
        module.__name__ != module_name
        or module.__spec__ is not None
        or getattr(module, "__file__", None) is not None
        or getattr(module, "__cached__", None) is not None
        or module.__loader__ is not None
    ):
        return False
    has_native_value = False
    for name, value in vars(module).items():
        if name in {"__name__", "__doc__", "__package__", "__loader__", "__spec__"}:
            continue
        if _is_native_extension_type(value, module_name=module_name) or _is_python_capsule(value):
            has_native_value = True
            continue
        return False
    return has_native_value


def _is_canonical_intrinsic_module(
    mapping_name: str,
    module_name: str,
    module: ModuleType,
) -> bool:
    specification = module.__spec__
    if (
        specification is None
        or specification.name not in {mapping_name, module_name}
        or module.__loader__ is not specification.loader
    ):
        return False
    loader: object = specification.loader
    if specification.origin == "built-in":
        return loader is BuiltinImporter and _imp.is_builtin(specification.name) != 0
    if specification.origin == "frozen":
        return loader is FrozenImporter and _imp.is_frozen(specification.name)
    return False


def _validate_loaded_distribution_origins(
    snapshots: tuple[_RuntimeDistributionSnapshot, ...],
    *,
    standard_library: _StandardLibrarySnapshot | None = None,
    loaded_modules: Mapping[str, object] | None = None,
) -> None:
    approved_sources_by_top_level: dict[str, set[Path]] = {}
    approved_bytecode_by_top_level: dict[str, set[Path]] = {}
    approved_native_by_top_level: dict[str, set[Path]] = {}
    for snapshot in snapshots:
        for top_level, origin in snapshot.source_origins:
            approved_sources_by_top_level.setdefault(top_level, set()).add(origin)
        for top_level, origin in snapshot.bytecode_origins:
            approved_bytecode_by_top_level.setdefault(top_level, set()).add(origin)
        for top_level, origin in snapshot.native_origins:
            approved_native_by_top_level.setdefault(top_level, set()).add(origin)
    standard_library_source_paths = (
        frozenset() if standard_library is None else standard_library.source_origins
    )
    standard_library_bytecode_paths = (
        frozenset() if standard_library is None else standard_library.bytecode_origins
    )
    standard_library_native_paths = (
        frozenset() if standard_library is None else standard_library.native_origins
    )
    observed_modules = sys.modules if loaded_modules is None else loaded_modules
    seen_modules: set[int] = set()
    for mapping_name, raw_module in tuple(observed_modules.items()):
        if not isinstance(mapping_name, str):
            raise RuntimeError("loaded runtime origin unavailable")
        if raw_module is None:
            continue
        if not isinstance(raw_module, ModuleType):
            raise RuntimeError("loaded runtime origin unavailable")
        module_identity = id(raw_module)
        if module_identity in seen_modules:
            continue
        seen_modules.add(module_identity)
        module_name = raw_module.__name__
        top_level = module_name.partition(".")[0]
        if top_level == "ccparser":
            continue
        specification = raw_module.__spec__
        if module_name == "__main__" and specification is None:
            continue
        if specification is None and _is_originless_native_data_module(module_name, raw_module):
            continue
        if _is_canonical_intrinsic_module(mapping_name, module_name, raw_module):
            continue
        dependency_owned = any(
            top_level in approved
            for approved in (
                approved_sources_by_top_level,
                approved_bytecode_by_top_level,
                approved_native_by_top_level,
            )
        )
        try:
            binding = _canonical_file_module_binding(module_name, raw_module)
        except Exception:
            if dependency_owned:
                raise RuntimeError("loaded dependency origin unavailable") from None
            raise RuntimeError("loaded runtime origin unavailable") from None
        if binding.kind == "source":
            standard_library_owned = binding.origin in standard_library_source_paths
            approved_dependency_origins = approved_sources_by_top_level.get(top_level, set())
        elif binding.kind == "bytecode":
            standard_library_owned = binding.origin in standard_library_bytecode_paths
            approved_dependency_origins = approved_bytecode_by_top_level.get(top_level, set())
        else:
            standard_library_owned = binding.origin in standard_library_native_paths
            approved_dependency_origins = approved_native_by_top_level.get(top_level, set())
        if standard_library_owned:
            if (
                binding.cached_origin is not None
                and binding.cached_origin not in standard_library_bytecode_paths
            ):
                raise RuntimeError("loaded runtime origin unavailable")
        elif binding.origin not in approved_dependency_origins:
            if not dependency_owned:
                raise RuntimeError("loaded runtime origin unavailable")
            raise RuntimeError("loaded dependency origin unavailable")
        elif binding.cached_origin is not None and binding.cached_origin not in (
            approved_bytecode_by_top_level.get(top_level, set())
        ):
            raise RuntimeError("loaded dependency origin unavailable")


def _runtime_dependency_snapshots() -> tuple[_RuntimeDistributionSnapshot, ...]:
    return tuple(_snapshot_runtime_distribution(name) for name in _RUNTIME_DEPENDENCY_NAMES)


def _python_runtime_digest() -> str:
    executable_size, executable_digest = _stable_content_identity(
        Path(sys.executable),
        require_executable=True,
    )
    flags = {
        name: value
        for name in dir(sys.flags)
        if not name.startswith("_")
        and isinstance((value := getattr(sys.flags, name)), bool | int | str | type(None))
    }
    implementation_version = sys.implementation.version
    affinity = tuple(sorted(os.sched_getaffinity(0))) if hasattr(os, "sched_getaffinity") else ()
    payload: dict[str, object] = {
        "affinity": affinity,
        "byteorder": sys.byteorder,
        "cpu_count": os.cpu_count(),
        "default_encoding": sys.getdefaultencoding(),
        "executable_digest": executable_digest,
        "executable_size": executable_size,
        "filesystem_encoding": sys.getfilesystemencoding(),
        "flags": flags,
        "implementation_cache_tag": sys.implementation.cache_tag,
        "implementation_version": tuple(implementation_version),
        "libc": platform.libc_ver(),
        "machine": platform.machine(),
        "multiarch": sysconfig.get_config_var("MULTIARCH"),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "python_build": platform.python_build(),
        "python_compiler": platform.python_compiler(),
        "soabi": sysconfig.get_config_var("SOABI"),
        "switch_interval": str(sys.getswitchinterval()),
        "version": sys.version,
    }
    return _toolchain_payload_digest(payload)


def _runtime_environment_digest() -> str:
    selected = {
        key: value
        for key, value in os.environ.items()
        if key in _RUNTIME_ENVIRONMENT_KEYS
        or any(key.startswith(prefix) for prefix in _RUNTIME_ENVIRONMENT_PREFIXES)
    }
    payload: dict[str, object] = {
        "environment": selected,
        "loader_files": _loader_file_identities(),
        "locale": locale.setlocale(locale.LC_ALL, None),
    }
    return _toolchain_payload_digest(payload)


def _loader_file_identities() -> tuple[tuple[int, str], ...]:
    identities: list[tuple[int, str]] = []
    for key in ("LD_AUDIT", "LD_PRELOAD"):
        raw_value = os.environ.get(key, "")
        for token in re.split(r"[\s:]+", raw_value):
            if not token:
                continue
            path = Path(token)
            if path.is_absolute():
                identities.append(_stable_content_identity(path))
    return tuple(sorted(identities))


@dataclass(frozen=True, slots=True)
class _MappedNativeFile:
    path: Path
    device_major: int
    device_minor: int
    inode: int

    @classmethod
    def from_path(cls, path: Path) -> _MappedNativeFile:
        resolved = path.resolve(strict=True)
        file_stat = resolved.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError("native runtime unavailable")
        return cls(
            path=resolved,
            device_major=os.major(file_stat.st_dev),
            device_minor=os.minor(file_stat.st_dev),
            inode=file_stat.st_ino,
        )


_PROC_MAP_PATH_ESCAPE = re.compile(r"\\(?P<value>[0-7]{3})")
_ALLOWED_SPECIAL_EXECUTABLE_MAPPINGS = frozenset({"[vdso]", "[vsyscall]"})


def _decode_proc_map_path(raw_path: str) -> str:
    if "\\012" in raw_path:
        raise RuntimeError("native runtime unavailable")
    return _PROC_MAP_PATH_ESCAPE.sub(
        lambda match: chr(int(match.group("value"), 8)),
        raw_path,
    )


def _mapped_native_files() -> tuple[_MappedNativeFile, ...]:
    mappings: dict[tuple[int, int, int], _MappedNativeFile] = {}
    try:
        maps_content = Path("/proc/self/maps").read_text(encoding="utf-8")
        for line in maps_content.splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) < 5:
                raise RuntimeError("native runtime unavailable")
            _address_range, permissions, _offset, raw_device, raw_inode = fields[:5]
            if "x" not in permissions:
                continue
            if len(fields) != 6:
                raise RuntimeError("native runtime unavailable")
            raw_path = fields[5]
            if raw_path in _ALLOWED_SPECIAL_EXECUTABLE_MAPPINGS:
                continue
            if raw_path.startswith("[") or raw_path.endswith(" (deleted)"):
                raise RuntimeError("native runtime unavailable")
            decoded_path = _decode_proc_map_path(raw_path)
            path = Path(decoded_path)
            if not path.is_absolute():
                raise RuntimeError("native runtime unavailable")
            device_parts = raw_device.split(":")
            if len(device_parts) != 2:
                raise RuntimeError("native runtime unavailable")
            device_major, device_minor = (int(part, 16) for part in device_parts)
            inode = int(raw_inode)
            if inode <= 0:
                raise RuntimeError("native runtime unavailable")
            identity = (device_major, device_minor, inode)
            mapping = _MappedNativeFile(
                path=path,
                device_major=device_major,
                device_minor=device_minor,
                inode=inode,
            )
            existing = mappings.get(identity)
            if existing is not None and existing.path != mapping.path:
                raise RuntimeError("native runtime unavailable")
            mappings[identity] = mapping
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("native runtime unavailable") from None
    if not mappings:
        raise RuntimeError("native runtime unavailable")
    return tuple(
        sorted(
            mappings.values(),
            key=lambda mapping: (
                mapping.device_major,
                mapping.device_minor,
                mapping.inode,
                str(mapping.path),
            ),
        )
    )


def _mapped_native_content_identity(mapping: _MappedNativeFile) -> tuple[int, str]:
    resolved = mapping.path.resolve(strict=True)
    file_descriptor = os.open(
        resolved,
        os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        before = os.fstat(file_descriptor)
        observed_identity = (
            os.major(before.st_dev),
            os.minor(before.st_dev),
            before.st_ino,
        )
        expected_identity = (
            mapping.device_major,
            mapping.device_minor,
            mapping.inode,
        )
        if not stat.S_ISREG(before.st_mode) or observed_identity != expected_identity:
            raise RuntimeError("native runtime changed")
        digest = sha256()
        size = 0
        while content := os.read(file_descriptor, 1024 * 1024):
            digest.update(content)
            size += len(content)
        after = os.fstat(file_descriptor)
        if _stable_file_identity(before) != _stable_file_identity(after) or size != before.st_size:
            raise RuntimeError("native runtime changed")
        return size, digest.hexdigest()
    finally:
        os.close(file_descriptor)


def _validate_native_distribution_origins(
    mappings: tuple[_MappedNativeFile, ...],
    snapshots: tuple[_RuntimeDistributionSnapshot, ...],
) -> None:
    approved_artifacts = frozenset(
        path for snapshot in snapshots for path in snapshot.artifact_paths
    )
    installation_roots = tuple(snapshot.installation_root for snapshot in snapshots)
    for mapping in mappings:
        if any(mapping.path.is_relative_to(root) for root in installation_roots) and (
            mapping.path not in approved_artifacts
        ):
            raise RuntimeError("native dependency origin unavailable")


def _native_runtime_identity(
    mappings: tuple[_MappedNativeFile, ...] | None = None,
    *,
    distributions: tuple[_RuntimeDistributionSnapshot, ...] = (),
) -> RuntimeArtifactIdentity:
    if mappings is None:
        try:
            system_preload = Path("/etc/ld.so.preload")
            if system_preload.exists() and system_preload.read_bytes().strip():
                raise RuntimeError("native runtime unavailable")
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("native runtime unavailable") from None
    observed_mappings = _mapped_native_files() if mappings is None else mappings
    _validate_native_distribution_origins(observed_mappings, distributions)
    records = tuple(
        sorted(_mapped_native_content_identity(mapping) for mapping in observed_mappings)
    )
    if not records:
        raise RuntimeError("native runtime unavailable")
    if mappings is None and _mapped_native_files() != observed_mappings:
        raise RuntimeError("native runtime changed")
    return RuntimeArtifactIdentity(
        file_count=len(records),
        size_bytes=sum(size for size, _digest in records),
        digest=_toolchain_payload_digest({"files": records}),
    )


def _resolved_executable(commands: tuple[tuple[str, ...], ...]) -> Path:
    resolved: set[Path] = set()
    for command in commands:
        if not command:
            raise RuntimeError("Tesseract command unavailable")
        executable = shutil.which(command[0])
        if executable is None:
            raise RuntimeError("Tesseract command unavailable")
        resolved.add(Path(executable).resolve(strict=True))
    if len(resolved) != 1:
        raise RuntimeError("Tesseract commands use different executables")
    return next(iter(resolved))


def _required_ocr_languages(commands: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    languages: set[str] = set()
    for command in commands:
        for index, argument in enumerate(command[:-1]):
            if argument == "-l":
                languages.update(command[index + 1].split("+"))
    result = tuple(sorted(language for language in languages if language))
    if result != ("eng", "heb"):
        raise RuntimeError("OCR language policy unavailable")
    return result


def _validate_tesseract_staging(
    tessdata_fd: int,
    configs_fd: int,
    *,
    tsv_config: _SealedCapability,
    eng_traineddata: _SealedCapability,
    heb_traineddata: _SealedCapability,
) -> None:
    tessdata = os.fstat(tessdata_fd)
    configs = os.fstat(configs_fd)
    named_configs = os.stat("configs", dir_fd=tessdata_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(tessdata.st_mode)
        or not stat.S_ISDIR(configs.st_mode)
        or tessdata.st_uid != os.geteuid()
        or configs.st_uid != os.geteuid()
        or stat.S_IMODE(tessdata.st_mode) != 0o500
        or stat.S_IMODE(configs.st_mode) != 0o500
        or _stable_file_identity(named_configs) != _stable_file_identity(configs)
        or tuple(sorted(os.listdir(tessdata_fd)))
        != ("configs", "eng.traineddata", "heb.traineddata")
        or tuple(os.listdir(configs_fd)) != ("tsv",)
    ):
        raise RuntimeError("external runtime unavailable")
    for directory_fd, name, capability in (
        (configs_fd, "tsv", tsv_config),
        (tessdata_fd, "eng.traineddata", eng_traineddata),
        (tessdata_fd, "heb.traineddata", heb_traineddata),
    ):
        link = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        target = os.stat(name, dir_fd=directory_fd, follow_symlinks=True)
        expected = os.fstat(capability.file_descriptor)
        if (
            not stat.S_ISLNK(link.st_mode)
            or link.st_uid != os.geteuid()
            or os.readlink(name, dir_fd=directory_fd) != capability.descriptor_path
            or _stable_file_identity(target) != _stable_file_identity(expected)
        ):
            raise RuntimeError("external runtime unavailable")


@dataclass(frozen=True, slots=True)
class _StagedTesseractRuntime:
    runtime: TesseractExecutionRuntime
    _directory_fds: tuple[int, ...]

    def close(self) -> None:
        _close_descriptors_no_throw(reversed(self._directory_fds))


@dataclass(frozen=True, slots=True)
class _BoundTesseract:
    execution_runtime: _BoundDynamicExecutable
    executable: _SealedCapability
    tsv_config: _SealedCapability
    eng_traineddata: _SealedCapability
    heb_traineddata: _SealedCapability
    version: str
    version_output_digest: str
    environment: tuple[tuple[str, str], ...]

    @classmethod
    def bind(
        cls,
        commands: tuple[tuple[str, ...], ...],
        *,
        environment: tuple[tuple[str, str], ...],
        staging_parent: Path,
    ) -> _BoundTesseract:
        executable_path = _resolved_executable(commands)
        capabilities: list[_SealedCapability] = []
        execution_runtime: _BoundDynamicExecutable | None = None
        try:
            execution_runtime = _BoundDynamicExecutable.bind_path(
                executable_path,
                staging_parent=staging_parent,
            )
            executable = execution_runtime.executable
            version_completed = execution_runtime.run(
                ("--version",),
                cwd=Path.cwd(),
                environment=environment,
                timeout=TESSERACT_VERSION_TIMEOUT_SECONDS,
                stderr_to_stdout=True,
            )
            if version_completed.returncode != 0:
                raise RuntimeError("Tesseract version unavailable")
            version_output = version_completed.stdout
            version_lines = version_output.decode(
                "utf-8",
                errors="replace",
            ).splitlines()
            if not version_lines or not version_lines[0].strip():
                raise RuntimeError("Tesseract version unavailable")
            language_completed = execution_runtime.run(
                ("--list-langs",),
                cwd=Path.cwd(),
                environment=environment,
                timeout=TESSERACT_VERSION_TIMEOUT_SECONDS,
                stderr_to_stdout=True,
            )
            if language_completed.returncode != 0:
                raise RuntimeError("Tesseract language data unavailable")
            language_output = language_completed.stdout.decode("utf-8", errors="strict")
            language_lines = language_output.splitlines()
            if not language_lines:
                raise RuntimeError("Tesseract language data unavailable")
            header = _TESSDATA_HEADER.fullmatch(language_lines[0])
            if header is None:
                raise RuntimeError("Tesseract language data unavailable")
            tessdata_directory = Path(header.group("directory")).resolve(strict=True)
            available_languages = frozenset(
                line.strip() for line in language_lines[1:] if line.strip()
            )
            required_languages = _required_ocr_languages(commands)
            if not set(required_languages).issubset(available_languages):
                raise RuntimeError("Tesseract language data unavailable")
            tsv_config = _SealedCapability.bind_path(
                tessdata_directory / "configs" / "tsv",
                executable=False,
            )
            capabilities.append(tsv_config)
            eng_traineddata = _SealedCapability.bind_path(
                tessdata_directory / "eng.traineddata",
                executable=False,
            )
            capabilities.append(eng_traineddata)
            heb_traineddata = _SealedCapability.bind_path(
                tessdata_directory / "heb.traineddata",
                executable=False,
            )
            capabilities.append(heb_traineddata)
            result = cls(
                execution_runtime=execution_runtime,
                executable=executable,
                tsv_config=tsv_config,
                eng_traineddata=eng_traineddata,
                heb_traineddata=heb_traineddata,
                version=version_lines[0].strip(),
                version_output_digest=sha256(version_output).hexdigest(),
                environment=environment,
            )
            capabilities.clear()
            execution_runtime = None
            return result
        finally:
            for capability in reversed(capabilities):
                capability.close()
            if execution_runtime is not None:
                execution_runtime.close()

    def metadata(self) -> tuple[str, str, tuple[ToolchainAsset, ...]]:
        assets = (
            self.tsv_config.asset("config:tsv"),
            self.executable.asset("tesseract-executable"),
            self.eng_traineddata.asset("traineddata:eng"),
            self.heb_traineddata.asset("traineddata:heb"),
        )
        return self.version, self.version_output_digest, assets

    @staticmethod
    def _symlink_capability(
        parent_fd: int,
        name: str,
        capability: _SealedCapability,
    ) -> None:
        os.symlink(capability.descriptor_path, name, dir_fd=parent_fd)

    def stage(self, work_fd: int) -> _StagedTesseractRuntime:
        directory_fds: list[int] = []
        try:
            tessdata_fd = _create_bound_child_directory(work_fd, "tessdata-runtime")
            directory_fds.append(tessdata_fd)
            configs_fd = _create_bound_child_directory(tessdata_fd, "configs")
            directory_fds.append(configs_fd)
            self._symlink_capability(configs_fd, "tsv", self.tsv_config)
            self._symlink_capability(tessdata_fd, "eng.traineddata", self.eng_traineddata)
            self._symlink_capability(tessdata_fd, "heb.traineddata", self.heb_traineddata)
            os.fchmod(configs_fd, 0o500)
            os.fchmod(tessdata_fd, 0o500)
            descriptor_fds = (
                *self.execution_runtime.pass_fds,
                self.tsv_config.file_descriptor,
                self.eng_traineddata.file_descriptor,
                self.heb_traineddata.file_descriptor,
                tessdata_fd,
            )

            def validate_staging() -> None:
                self.execution_runtime._validate_staging()
                _validate_tesseract_staging(
                    tessdata_fd,
                    configs_fd,
                    tsv_config=self.tsv_config,
                    eng_traineddata=self.eng_traineddata,
                    heb_traineddata=self.heb_traineddata,
                )

            runtime = TesseractExecutionRuntime(
                executable_path=self.executable.descriptor_path,
                tessdata_directory=f"/proc/self/fd/{tessdata_fd}",
                pass_fds=descriptor_fds,
                environment=self.environment,
                command_prefix=self.execution_runtime.command((), argv0="tesseract"),
                allowed_file_descriptors=self.execution_runtime.executable_file_descriptors,
                staging_validator=validate_staging,
            )
            result = _StagedTesseractRuntime(
                runtime=runtime,
                _directory_fds=tuple(directory_fds),
            )
            directory_fds.clear()
            return result
        finally:
            _close_descriptors_no_throw(reversed(directory_fds))

    def close(self) -> None:
        for capability in (
            self.heb_traineddata,
            self.eng_traineddata,
            self.tsv_config,
        ):
            capability.close()
        self.execution_runtime.close()


def _tesseract_metadata(
    commands: tuple[tuple[str, ...], ...],
) -> tuple[str, str, tuple[ToolchainAsset, ...]]:
    bound = _BoundTesseract.bind(
        commands,
        environment=tuple(sorted(_sanitized_child_environment().items())),
        staging_parent=_active_git_directory(Path.cwd()),
    )
    try:
        return bound.metadata()
    finally:
        bound.close()


class LocalToolchainInspector:
    """Fingerprint the complete local parser, interpreter, and OCR environment."""

    def __init__(
        self,
        *,
        runtime_capabilities: _GateRuntimeCapabilities | None = None,
    ) -> None:
        self._runtime_capabilities = runtime_capabilities or _GateRuntimeCapabilities.bind()
        self._owns_runtime_capabilities = runtime_capabilities is None

    def close(self) -> None:
        if self._owns_runtime_capabilities:
            self._runtime_capabilities.close()

    def fingerprint(self) -> ToolchainFingerprint:
        commands = (
            tesseract_command(),
            supplemental_tesseract_command(),
            numeric_tesseract_command(),
            currency_tesseract_command(),
        )
        cache_versions = tuple(
            sorted(
                (
                    OCR_PREPROCESSING_VERSION,
                    OCR_RECOGNITION_CACHE_VERSION,
                    OCR_NUMERIC_RECOGNITION_CACHE_VERSION,
                    OCR_CURRENCY_RECOGNITION_CACHE_VERSION,
                )
            )
        )
        command_digest = _digest_json(
            {
                "git_environment": self._runtime_capabilities.git_environment,
                "commands": commands,
                "recognition_timeout_seconds": TESSERACT_RECOGNITION_TIMEOUT_SECONDS,
                "tesseract_environment": self._runtime_capabilities.tesseract_environment,
                "version_timeout_seconds": TESSERACT_VERSION_TIMEOUT_SECONDS,
            }
        )
        tesseract_version, version_output_digest, tesseract_assets = (
            self._runtime_capabilities.tesseract_metadata(commands)
        )
        standard_library = _snapshot_standard_library()
        distribution_snapshots = _runtime_dependency_snapshots()
        _validate_loaded_distribution_origins(
            distribution_snapshots,
            standard_library=standard_library,
        )
        dependencies = tuple(snapshot.dependency for snapshot in distribution_snapshots)
        native_runtime = _native_runtime_identity(
            distributions=distribution_snapshots,
        )
        fingerprint_payload: dict[str, object] = {
            "version": 6,
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_runtime_digest": _python_runtime_digest(),
            "standard_library": standard_library.identity.model_dump(mode="json"),
            "runtime_environment_digest": _runtime_environment_digest(),
            "dependencies": tuple(
                dependency.model_dump(mode="json") for dependency in dependencies
            ),
            "git_executable": self._runtime_capabilities.git.asset("git-executable").model_dump(
                mode="json"
            ),
            "git_native_closure": self._runtime_capabilities.git_runtime.native_closure.model_dump(
                mode="json"
            ),
            "native_runtime": native_runtime.model_dump(mode="json"),
            "pymupdf_binding_version": str(fitz.VersionBind),
            "pymupdf_engine_version": str(fitz.mupdf_version),
            "tesseract_version": tesseract_version,
            "tesseract_version_output_digest": version_output_digest,
            "tesseract_assets": tuple(asset.model_dump(mode="json") for asset in tesseract_assets),
            "tesseract_native_closure": (
                self._runtime_capabilities.tesseract_native_closure.model_dump(mode="json")
            ),
            "ocr_pipeline_version": OCR_PIPELINE_VERSION,
            "ocr_cache_versions": cache_versions,
            "command_digest": command_digest,
        }
        return ToolchainFingerprint.model_validate(
            {**fingerprint_payload, "digest": _toolchain_payload_digest(fingerprint_payload)}
        )


@dataclass(frozen=True, slots=True)
class _StructuralProjections:
    counts: CorpusCounts
    ordered_statuses: tuple[str, tuple[str, ...]]
    group_structure: _GroupStructure
    transaction_identities: _TransactionIdentities
    field_presence: _FieldPresence
    evidence_provenance: _EvidenceProvenance
    ambiguities: _AmbiguityProjection


@dataclass(frozen=True, slots=True)
class _StatementStructuralProjection:
    status: str
    groups: tuple[_GroupProjection, ...]
    transaction_identities: tuple[_TransactionIdentity, ...]
    field_presence: tuple[tuple[PresentFieldPath, ...], ...]
    evidence_provenance: tuple[tuple[_EvidenceSiteProjection, ...], ...]
    ambiguities: tuple[tuple[str, ...], ...]
    row_results: int
    evidence_references: int


class _CanonicalArrayDigest:
    def __init__(self, prefix: bytes = b"[", suffix: bytes = b"]\n") -> None:
        self._digest = sha256()
        self._digest.update(prefix)
        self._suffix = suffix
        self._has_value = False

    def append(self, value: object) -> None:
        if self._has_value:
            self._digest.update(b",")
        self._digest.update(_canonical_json_value_bytes(value)[:-1])
        self._has_value = True

    def hexdigest(self) -> str:
        completed = self._digest.copy()
        completed.update(self._suffix)
        return completed.hexdigest()


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _digest_json(value: object) -> str:
    return _digest_bytes(_canonical_json_value_bytes(value))


def digest_membership(source_hashes: Iterable[str]) -> CorpusMembership:
    """Digest a source-hash multiset without depending on traversal order."""

    ordered = tuple(sorted(source_hashes))
    return CorpusMembership(
        document_count=len(ordered),
        source_multiset_digest=_digest_json(ordered),
    )


def _transaction_present_fields(transaction: Transaction) -> tuple[PresentFieldPath, ...]:
    present: list[PresentFieldPath] = []
    if transaction.category is not TransactionCategory.UNKNOWN:
        present.append("category")
    if transaction.conversion_date is not None:
        present.append("conversion_date")
    if transaction.description is not None:
        present.append("description")
    if transaction.installment_current is not None:
        present.append("installment_current")
    if transaction.installment_total is not None:
        present.append("installment_total")
    if transaction.original_amount is not None:
        present.append("original_amount")
    if transaction.original_currency is not None:
        present.append("original_currency")
    if transaction.posting_date is not None:
        present.append("posting_date")
    if transaction.transaction_date is not None:
        present.append("transaction_date")

    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            present.append("foreign_exchange.exchange_rate")
        if details.fee_discount is not None:
            present.append("foreign_exchange.fee_discount")
        if details.fee_percentage is not None:
            present.append("foreign_exchange.fee_percentage")
        if details.gross_fee is not None:
            present.append("foreign_exchange.gross_fee")
        if details.net_fee is not None:
            present.append("foreign_exchange.net_fee")
    return tuple(sorted(present))


def _project_evidence_reference(reference: EvidenceReference) -> _EvidenceReferenceProjection:
    raw_text_digest = _digest_bytes(
        unicodedata.normalize("NFC", reference.raw_text).encode("utf-8")
    )
    return reference.page_number, reference.bbox, raw_text_digest


def _project_evidence_site(
    path: str, references: tuple[EvidenceReference, ...]
) -> _EvidenceSiteProjection:
    return path, tuple(_project_evidence_reference(reference) for reference in references)


def _transaction_evidence_provenance(
    transaction: Transaction,
) -> tuple[_EvidenceSiteProjection, ...]:
    sites = [_project_evidence_site("evidence", transaction.evidence)]
    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.exchange_rate", details.exchange_rate.evidence
                )
            )
        if details.fee_discount is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_discount", details.fee_discount.evidence
                )
            )
        if details.fee_percentage is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_percentage", details.fee_percentage.evidence
                )
            )
        if details.gross_fee is not None:
            sites.append(
                _project_evidence_site("foreign_exchange.gross_fee", details.gross_fee.evidence)
            )
        if details.net_fee is not None:
            sites.append(
                _project_evidence_site("foreign_exchange.net_fee", details.net_fee.evidence)
            )
    return tuple(sorted(sites, key=lambda item: item[0]))


def _project_statement_structural_dimensions(
    statement: StatementResult,
) -> _StatementStructuralProjection:
    transaction_identities: list[_TransactionIdentity] = []
    field_presence: list[tuple[PresentFieldPath, ...]] = []
    evidence_provenance: list[tuple[_EvidenceSiteProjection, ...]] = []
    ambiguities: list[tuple[str, ...]] = []
    evidence_reference_count = 0

    for transaction in statement.transactions:
        transaction_identities.append(
            (transaction.transaction_id, transaction.reconciliation_group_ids)
        )
        field_presence.append(_transaction_present_fields(transaction))
        transaction_evidence = _transaction_evidence_provenance(transaction)
        evidence_provenance.append(transaction_evidence)
        evidence_reference_count += sum(len(references) for _, references in transaction_evidence)
        ambiguities.append(transaction.ambiguities)

    return _StatementStructuralProjection(
        status=statement.status.value,
        groups=tuple(
            (group.group_id, group.currency, group.status.value, group.transaction_ids)
            for group in statement.groups
        ),
        transaction_identities=tuple(transaction_identities),
        field_presence=tuple(field_presence),
        evidence_provenance=tuple(evidence_provenance),
        ambiguities=tuple(ambiguities),
        row_results=len(statement.row_results),
        evidence_references=evidence_reference_count,
    )


def _project_structural_dimensions(batch: BatchResult) -> _StructuralProjections:
    statuses: Counter[str] = Counter()
    present_field_counts: Counter[PresentFieldPath] = Counter()
    ordered_statuses: list[str] = []
    group_structure: list[tuple[_GroupProjection, ...]] = []
    transaction_identities: list[tuple[_TransactionIdentity, ...]] = []
    field_presence: list[tuple[tuple[PresentFieldPath, ...], ...]] = []
    evidence_provenance: list[tuple[tuple[_EvidenceSiteProjection, ...], ...]] = []
    ambiguities: list[tuple[tuple[str, ...], ...]] = []
    row_result_count = 0
    evidence_reference_count = 0

    for statement in batch.statements:
        projection = _project_statement_structural_dimensions(statement)
        statuses[projection.status] += 1
        ordered_statuses.append(projection.status)
        group_structure.append(projection.groups)
        transaction_identities.append(projection.transaction_identities)
        field_presence.append(projection.field_presence)
        evidence_provenance.append(projection.evidence_provenance)
        ambiguities.append(projection.ambiguities)
        row_result_count += projection.row_results
        evidence_reference_count += projection.evidence_references
        for transaction_fields in projection.field_presence:
            present_field_counts.update(transaction_fields)

    counts = CorpusCounts(
        documents=len(batch.statements),
        reconciled=statuses[Status.RECONCILED.value],
        unreconciled=statuses[Status.UNRECONCILED.value],
        unsupported=statuses[Status.UNSUPPORTED.value],
        not_statement=statuses[Status.NOT_STATEMENT.value],
        groups=sum(len(groups) for groups in group_structure),
        row_results=row_result_count,
        transactions=sum(len(identities) for identities in transaction_identities),
        ambiguous_transactions=sum(
            bool(transaction_ambiguities)
            for statement_ambiguities in ambiguities
            for transaction_ambiguities in statement_ambiguities
        ),
        ambiguity_occurrences=sum(
            len(transaction_ambiguities)
            for statement_ambiguities in ambiguities
            for transaction_ambiguities in statement_ambiguities
        ),
        evidence_references=evidence_reference_count,
        present_fields=tuple(
            FieldCount(path=path, count=present_field_counts[path])
            for path in sorted(present_field_counts)
        ),
    )
    return _StructuralProjections(
        counts=counts,
        ordered_statuses=(
            batch.status.value,
            tuple(ordered_statuses),
        ),
        group_structure=tuple(group_structure),
        transaction_identities=tuple(transaction_identities),
        field_presence=tuple(field_presence),
        evidence_provenance=tuple(evidence_provenance),
        ambiguities=tuple(ambiguities),
    )


def project_run(batch: BatchResult, *, elapsed_seconds: Decimal) -> RunManifest:
    """Project a parser result into aggregate counts and one-way digests."""

    json_content = canonical_json_bytes(batch)
    csv_content = transactions_csv_bytes(batch)
    projections = _project_structural_dimensions(batch)
    return RunManifest(
        elapsed_seconds=elapsed_seconds,
        counts=projections.counts,
        json_digest=_digest_bytes(json_content),
        csv_digest=_digest_bytes(csv_content),
        ordered_status_digest=_digest_json(projections.ordered_statuses),
        group_structure_digest=_digest_json(projections.group_structure),
        transaction_identity_digest=_digest_json(projections.transaction_identities),
        field_presence_digest=_digest_json(projections.field_presence),
        evidence_provenance_digest=_digest_json(projections.evidence_provenance),
        ambiguity_digest=_digest_json(projections.ambiguities),
    )


def project_streamed_run(
    *,
    batch_status: Status,
    elapsed_seconds: Decimal,
    json_digest: str,
    csv_digest: str,
    statements: StatementResultFactory,
) -> RunManifest:
    """Project a source-ordered statement stream into an unchanged run manifest."""

    ordered_status_digest = _CanonicalArrayDigest(
        prefix=b"[" + _canonical_json_value_bytes(batch_status.value)[:-1] + b",[",
        suffix=b"]]\n",
    )
    group_structure_digest = _CanonicalArrayDigest()
    transaction_identity_digest = _CanonicalArrayDigest()
    field_presence_digest = _CanonicalArrayDigest()
    evidence_provenance_digest = _CanonicalArrayDigest()
    ambiguity_digest = _CanonicalArrayDigest()
    present_field_counts: Counter[PresentFieldPath] = Counter()
    documents = 0
    reconciled = 0
    unreconciled = 0
    unsupported = 0
    not_statement = 0
    groups = 0
    row_results = 0
    transactions = 0
    ambiguous_transactions = 0
    ambiguity_occurrences = 0
    evidence_references = 0

    for statement in statements():
        projection = _project_statement_structural_dimensions(statement)
        del statement
        documents += 1
        if projection.status == Status.RECONCILED.value:
            reconciled += 1
        elif projection.status == Status.UNRECONCILED.value:
            unreconciled += 1
        elif projection.status == Status.UNSUPPORTED.value:
            unsupported += 1
        elif projection.status == Status.NOT_STATEMENT.value:
            not_statement += 1
        groups += len(projection.groups)
        row_results += projection.row_results
        transactions += len(projection.transaction_identities)
        ambiguous_transactions += sum(bool(value) for value in projection.ambiguities)
        ambiguity_occurrences += sum(len(value) for value in projection.ambiguities)
        evidence_references += projection.evidence_references
        present_field_counts.update(
            path for transaction_fields in projection.field_presence for path in transaction_fields
        )

        ordered_status_digest.append(projection.status)
        group_structure_digest.append(projection.groups)
        transaction_identity_digest.append(projection.transaction_identities)
        field_presence_digest.append(projection.field_presence)
        evidence_provenance_digest.append(projection.evidence_provenance)
        ambiguity_digest.append(projection.ambiguities)
        del projection

    counts = CorpusCounts(
        documents=documents,
        reconciled=reconciled,
        unreconciled=unreconciled,
        unsupported=unsupported,
        not_statement=not_statement,
        groups=groups,
        row_results=row_results,
        transactions=transactions,
        ambiguous_transactions=ambiguous_transactions,
        ambiguity_occurrences=ambiguity_occurrences,
        evidence_references=evidence_references,
        present_fields=tuple(
            FieldCount(path=path, count=present_field_counts[path])
            for path in sorted(present_field_counts)
        ),
    )
    return RunManifest(
        elapsed_seconds=elapsed_seconds,
        counts=counts,
        json_digest=json_digest,
        csv_digest=csv_digest,
        ordered_status_digest=ordered_status_digest.hexdigest(),
        group_structure_digest=group_structure_digest.hexdigest(),
        transaction_identity_digest=transaction_identity_digest.hexdigest(),
        field_presence_digest=field_presence_digest.hexdigest(),
        evidence_provenance_digest=evidence_provenance_digest.hexdigest(),
        ambiguity_digest=ambiguity_digest.hexdigest(),
    )


def compare_independent_runs(
    first: RunManifest, second: RunManifest
) -> tuple[CorpusGateReason, ...]:
    """Return every deterministic-output difference in closed policy order."""

    checks = (
        (first.counts != second.counts, CorpusGateReason.COUNTS_DRIFT),
        (first.json_digest != second.json_digest, CorpusGateReason.JSON_DRIFT),
        (first.csv_digest != second.csv_digest, CorpusGateReason.CSV_DRIFT),
        (
            first.ordered_status_digest != second.ordered_status_digest,
            CorpusGateReason.STATUS_DRIFT,
        ),
        (
            first.group_structure_digest != second.group_structure_digest,
            CorpusGateReason.GROUP_STRUCTURE_DRIFT,
        ),
        (
            first.transaction_identity_digest != second.transaction_identity_digest,
            CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT,
        ),
        (
            first.field_presence_digest != second.field_presence_digest,
            CorpusGateReason.FIELD_PRESENCE_DRIFT,
        ),
        (
            first.evidence_provenance_digest != second.evidence_provenance_digest,
            CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT,
        ),
        (
            first.ambiguity_digest != second.ambiguity_digest,
            CorpusGateReason.AMBIGUITY_DRIFT,
        ),
    )
    return tuple(reason for failed, reason in checks if failed)


def compare_with_baseline(
    baseline: CorpusBaseline, candidate: CorpusBaseline
) -> tuple[CorpusGateReason, ...]:
    """Compare a candidate with an accepted baseline using the closed policy."""

    failed: set[CorpusGateReason] = set()
    for accepted_pair, candidate_pair in (
        (baseline.retained, candidate.retained),
        (baseline.quarantine, candidate.quarantine),
    ):
        if accepted_pair.membership != candidate_pair.membership:
            failed.add(CorpusGateReason.MEMBERSHIP_DRIFT)
        for accepted_run, candidate_run in (
            (accepted_pair.first, candidate_pair.first),
            (accepted_pair.second, candidate_pair.second),
        ):
            failed.update(compare_independent_runs(accepted_run, candidate_run))

    matching_runtime_context = (
        baseline.toolchain == candidate.toolchain and baseline.jobs == candidate.jobs
    )
    if not matching_runtime_context:
        failed.add(CorpusGateReason.RUNTIME_CONTEXT_DRIFT)
    else:
        runtime_limit = baseline.retained.worst_elapsed_seconds * (
            Decimal(1) + baseline.runtime_tolerance_ratio
        )
        if candidate.retained.worst_elapsed_seconds > runtime_limit:
            failed.add(CorpusGateReason.RUNTIME_REGRESSION)

    return tuple(reason for reason in CorpusGateReason if reason in failed)


@dataclass(frozen=True, slots=True)
class _ResolvedGateConfig:
    expected_commit_sha: str
    retained_dir: Path
    quarantine_dir: Path
    membership_inventory_path: Path
    membership_inventory_sha256: str
    baseline_path: Path
    baseline_sha256: str | None
    work_dir: Path
    jobs: int
    runtime_tolerance_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class _PreparedGate:
    config: _ResolvedGateConfig
    repository_state: RepositoryState
    toolchain: ToolchainFingerprint
    inventory: CorpusMembershipInventory
    accepted_baseline: CorpusBaseline | None
    runtime_tolerance_ratio: Decimal
    run_paths: tuple[tuple[Path, Path], ...]


@dataclass(frozen=True, slots=True)
class _ObservedCorpusRun:
    completed: CompletedCorpusRun
    original_membership_before: CorpusMembership
    original_membership_after: CorpusMembership


def _close_descriptors(file_descriptors: Iterable[int]) -> None:
    first_failure: BaseException | None = None
    for file_descriptor in file_descriptors:
        try:
            os.close(file_descriptor)
        except BaseException as error:
            if first_failure is None:
                first_failure = error
    if first_failure is not None:
        raise first_failure


def _close_descriptors_no_throw(file_descriptors: Iterable[int]) -> None:
    with suppress(BaseException):
        _close_descriptors(file_descriptors)


@dataclass(frozen=True, slots=True)
class _BoundExecutionPaths:
    repository_fd: int
    work_fd: int
    retained_input_fd: int
    quarantine_input_fd: int
    run_fds: tuple[tuple[int, int], ...]
    baseline_parent_fd: int
    baseline_name: str
    _file_descriptors: tuple[int, ...]

    @staticmethod
    def path_for(file_descriptor: int) -> Path:
        return Path(f"/proc/self/fd/{file_descriptor}")

    def close(self) -> None:
        for file_descriptor in reversed(self._file_descriptors):
            with suppress(OSError):
                os.close(file_descriptor)


def _ordered_reasons(reasons: Iterable[CorpusGateReason]) -> tuple[CorpusGateReason, ...]:
    failed = set(reasons)
    return tuple(reason for reason in CorpusGateReason if reason in failed)


def _snapshot_membership(
    input_dir: Path,
    *,
    allow_descriptor_root: bool = False,
) -> CorpusMembership:
    _reject_corpus_symlinks(input_dir, allow_descriptor_root=allow_descriptor_root)
    try:
        source_hashes = (
            sha256(source.read_bytes()).hexdigest() for source in iter_regular_pdf_files(input_dir)
        )
        return digest_membership(source_hashes)
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None


def _load_inventory(
    repository_fd: int,
    repository_root: Path,
    path: Path,
    expected_sha256: str,
) -> CorpusMembershipInventory:
    try:
        content = _read_stable_regular_file(repository_fd, repository_root, path)
        if sha256(content).hexdigest() != expected_sha256:
            raise CorpusGateInputError((CorpusGateReason.INVENTORY_INVALID,))
        return CorpusMembershipInventory.model_validate_json(content)
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVENTORY_INVALID,)) from None


def _load_baseline(
    repository_fd: int,
    repository_root: Path,
    path: Path,
    expected_sha256: str,
) -> CorpusBaseline:
    try:
        content = _read_stable_regular_file(repository_fd, repository_root, path)
    except FileNotFoundError:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_MISSING,)) from None
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
    try:
        if sha256(content).hexdigest() != expected_sha256:
            raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))
        return CorpusBaseline.model_validate_json(content)
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None


def _resolve_config(config: CorpusGateConfig) -> _ResolvedGateConfig:
    try:
        return _ResolvedGateConfig(
            expected_commit_sha=config.expected_commit_sha,
            retained_dir=config.retained_dir.resolve(strict=True),
            quarantine_dir=config.quarantine_dir.resolve(strict=True),
            membership_inventory_path=config.membership_inventory_path.resolve(strict=False),
            membership_inventory_sha256=config.membership_inventory_sha256,
            baseline_path=config.baseline_path.resolve(strict=False),
            baseline_sha256=config.baseline_sha256,
            work_dir=config.work_dir.resolve(strict=False),
            jobs=config.jobs,
            runtime_tolerance_ratio=config.runtime_tolerance_ratio,
        )
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None


def _lexical_absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _has_symlink_component(path: Path) -> bool:
    current = _lexical_absolute(path)
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _is_process_fd_path(path: Path) -> bool:
    lexical = _lexical_absolute(path)
    return lexical.parent == Path("/proc/self/fd") and lexical.name.isdecimal()


def _reject_corpus_symlinks(
    path: Path,
    *,
    allow_descriptor_root: bool = False,
) -> None:
    try:
        lexical_root = _lexical_absolute(path)
        if lexical_root.is_symlink() and not (
            allow_descriptor_root and _is_process_fd_path(lexical_root)
        ):
            raise CorpusGateInputError((CorpusGateReason.CORPUS_SYMLINK,))

        def raise_walk_error(error: OSError) -> None:
            raise error

        for root_value, directory_names, file_names in os.walk(
            lexical_root,
            followlinks=False,
            onerror=raise_walk_error,
        ):
            root = Path(root_value)
            if any((root / name).is_symlink() for name in (*directory_names, *file_names)):
                raise CorpusGateInputError((CorpusGateReason.CORPUS_SYMLINK,))
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None


def _configured_paths_overlap(config: _ResolvedGateConfig) -> bool:
    paths = (
        config.retained_dir,
        config.quarantine_dir,
        config.membership_inventory_path,
        config.baseline_path,
        config.work_dir,
    )
    return any(
        paths_overlap(left, right)
        for index, left in enumerate(paths)
        for right in paths[index + 1 :]
    )


def _validated_run_paths(
    config: _ResolvedGateConfig,
    repository_root: Path,
) -> tuple[tuple[Path, Path], ...]:
    raw_pairs = _run_paths(config.work_dir)
    if len(raw_pairs) != 4 or any(len(pair) != 2 for pair in raw_pairs):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    try:
        pairs = tuple(
            (output_dir.resolve(strict=False), cache_dir.resolve(strict=False))
            for output_dir, cache_dir in raw_pairs
        )
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
    children = tuple(path for pair in pairs for path in pair)
    if any(not child.is_relative_to(repository_root) for child in children):
        raise CorpusGateInputError((CorpusGateReason.PATH_OUTSIDE_REPOSITORY,))
    if (
        len(set(children)) != len(children)
        or any(child.parent != config.work_dir for child in children)
        or any(child.exists() or child.is_symlink() for child in children)
        or any(_has_symlink_component(child) for child in children)
    ):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    if any(
        paths_overlap(left, right)
        for index, left in enumerate(children)
        for right in children[index + 1 :]
    ):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    protected_paths = (
        config.retained_dir,
        config.quarantine_dir,
        config.membership_inventory_path,
        config.baseline_path,
    )
    if any(paths_overlap(child, protected) for child in children for protected in protected_paths):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    return pairs


def _inspect_initial_state(dependencies: CorpusGateDependencies) -> RepositoryState:
    try:
        state = dependencies.repository.state()
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
    if not state.clean:
        raise CorpusGateInputError((CorpusGateReason.DIRTY_REPOSITORY,))
    return state


def _inspect_initial_toolchain(
    dependencies: CorpusGateDependencies,
) -> ToolchainFingerprint:
    try:
        return dependencies.toolchain.fingerprint()
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateRuntimeError((CorpusGateReason.TOOLCHAIN_UNAVAILABLE,)) from None


def _prepare_gate(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
    dependencies: CorpusGateDependencies,
) -> _PreparedGate:
    repository_state = _inspect_initial_state(dependencies)
    if repository_state.commit_sha != config.expected_commit_sha:
        raise CorpusGateInputError((CorpusGateReason.REPOSITORY_CHANGED,))
    toolchain = _inspect_initial_toolchain(dependencies)
    resolved = _resolve_config(config)
    try:
        repository_root = repository_state.root.resolve(strict=True)
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
    all_paths = (
        resolved.retained_dir,
        resolved.quarantine_dir,
        resolved.membership_inventory_path,
        resolved.baseline_path,
        resolved.work_dir,
    )
    if any(not path.is_relative_to(repository_root) for path in all_paths):
        raise CorpusGateInputError((CorpusGateReason.PATH_OUTSIDE_REPOSITORY,))
    if not resolved.retained_dir.is_dir() or not resolved.quarantine_dir.is_dir():
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
    if _configured_paths_overlap(resolved):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    _reject_corpus_symlinks(config.retained_dir)
    _reject_corpus_symlinks(config.quarantine_dir)
    if any(
        _has_symlink_component(path)
        for path in (
            config.membership_inventory_path,
            config.baseline_path,
            config.work_dir,
        )
    ):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    try:
        if resolved.work_dir.exists() and (
            not resolved.work_dir.is_dir() or any(resolved.work_dir.iterdir())
        ):
            raise CorpusGateInputError((CorpusGateReason.RUN_PATH_NOT_EMPTY,))
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
    for private_path in (
        resolved.membership_inventory_path,
        resolved.baseline_path,
        resolved.work_dir,
    ):
        try:
            ignored = dependencies.repository.is_ignored(private_path)
        except Exception:
            raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
        if not ignored:
            raise CorpusGateInputError((CorpusGateReason.PRIVATE_PATH_NOT_IGNORED,))
    run_paths = _validated_run_paths(resolved, repository_root)

    if mode is CorpusGateMode.RECORD:
        if resolved.runtime_tolerance_ratio is None or resolved.baseline_sha256 is not None:
            raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
        if resolved.baseline_path.exists() or resolved.baseline_path.is_symlink():
            raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))
    else:
        if resolved.runtime_tolerance_ratio is not None or resolved.baseline_sha256 is None:
            raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))

    try:
        repository_fd = os.open(repository_root, _DIRECTORY_OPEN_FLAGS)
    except OSError:
        raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,)) from None
    try:
        inventory = _load_inventory(
            repository_fd,
            repository_root,
            resolved.membership_inventory_path,
            resolved.membership_inventory_sha256,
        )
        if mode is CorpusGateMode.RECORD:
            runtime_tolerance_ratio = resolved.runtime_tolerance_ratio
            if runtime_tolerance_ratio is None:
                raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
            accepted_baseline = None
        else:
            baseline_sha256 = resolved.baseline_sha256
            if baseline_sha256 is None:
                raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
            accepted_baseline = _load_baseline(
                repository_fd,
                repository_root,
                resolved.baseline_path,
                baseline_sha256,
            )
            runtime_tolerance_ratio = accepted_baseline.runtime_tolerance_ratio
    finally:
        with suppress(OSError):
            os.close(repository_fd)

    retained_membership = _snapshot_membership(resolved.retained_dir)
    quarantine_membership = _snapshot_membership(resolved.quarantine_dir)
    if retained_membership != inventory.retained or quarantine_membership != inventory.quarantine:
        raise CorpusGateAcceptanceError((CorpusGateReason.MEMBERSHIP_DRIFT,))
    return _PreparedGate(
        config=resolved,
        repository_state=repository_state,
        toolchain=toolchain,
        inventory=inventory,
        accepted_baseline=accepted_baseline,
        runtime_tolerance_ratio=runtime_tolerance_ratio,
        run_paths=run_paths,
    )


def _run_paths(work_dir: Path) -> tuple[tuple[Path, Path], ...]:
    return tuple(
        (
            work_dir / f"{corpus_name}-{run_number}-output",
            work_dir / f"{corpus_name}-{run_number}-cache",
        )
        for corpus_name in ("retained", "quarantine")
        for run_number in (1, 2)
    )


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _relative_directory_parts(
    repository_root: Path,
    path: Path,
    *,
    allow_root: bool = False,
) -> tuple[str, ...]:
    try:
        relative = path.relative_to(repository_root)
    except ValueError:
        raise CorpusGateInputError((CorpusGateReason.PATH_OUTSIDE_REPOSITORY,)) from None
    if not relative.parts:
        if allow_root:
            return ()
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    if any(part in {".", ".."} for part in relative.parts):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    return relative.parts


def _open_directory_beneath(
    root_fd: int,
    parts: tuple[str, ...],
    *,
    create_missing: bool,
    require_trusted: bool = False,
) -> int:
    current_fd = os.dup(root_fd)
    try:
        if require_trusted:
            _validate_trusted_directory(os.fstat(current_fd))
        for part in parts:
            if create_missing:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
            next_fd = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            try:
                if require_trusted:
                    _validate_trusted_directory(os.fstat(next_fd))
            except BaseException:
                with suppress(OSError):
                    os.close(next_fd)
                raise
            previous_fd = current_fd
            current_fd = next_fd
            os.close(previous_fd)
        return current_fd
    except BaseException:
        with suppress(OSError):
            os.close(current_fd)
        raise


def _validate_trusted_directory(directory_stat: os.stat_result) -> None:
    untrusted_write_bits = stat.S_IWGRP | stat.S_IWOTH
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or directory_stat.st_uid != os.geteuid()
        or directory_stat.st_mode & untrusted_write_bits
    ):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))


def _stable_file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _read_stable_regular_file(
    repository_fd: int,
    repository_root: Path,
    path: Path,
) -> bytes:
    try:
        parent_fd = _open_directory_beneath(
            repository_fd,
            _relative_directory_parts(
                repository_root,
                path.parent,
                allow_root=True,
            ),
            create_missing=False,
            require_trusted=True,
        )
    except CorpusGateError:
        raise
    except OSError:
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)) from None
    try:
        return _read_stable_regular_file_at(parent_fd, path.name)
    finally:
        with suppress(OSError):
            os.close(parent_fd)


def _read_stable_regular_file_at(parent_fd: int, name: str) -> bytes:
    if not name or name in {".", ".."} or "/" in name:
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    file_fd: int | None = None
    try:
        try:
            file_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError:
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)) from None
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        chunks: list[bytes] = []
        while content := os.read(file_fd, 1024 * 1024):
            chunks.append(content)
        result = b"".join(chunks)
        after = os.fstat(file_fd)
        if (
            _stable_file_identity(before) != _stable_file_identity(after)
            or len(result) != before.st_size
        ):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        return result
    finally:
        if file_fd is not None:
            with suppress(OSError):
                os.close(file_fd)


def _load_locked_baseline(parent_fd: int, name: str, expected_sha256: str) -> CorpusBaseline:
    try:
        content = _read_stable_regular_file_at(parent_fd, name)
    except FileNotFoundError:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
    try:
        if sha256(content).hexdigest() != expected_sha256:
            raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))
        return CorpusBaseline.model_validate_json(content)
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None


def _create_bound_child_directory(parent_fd: int, name: str) -> int:
    if not name or name in {".", ".."} or "/" in name:
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    return os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)


def _write_all(file_descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(file_descriptor, remaining)
        if written <= 0:
            raise OSError("short write")
        remaining = remaining[written:]


def _copy_regular_pdf(source_parent_fd: int, destination_parent_fd: int, name: str) -> str:
    source_fd = os.open(name, _FILE_READ_FLAGS, dir_fd=source_parent_fd)
    opened_file_descriptors = [source_fd]
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise CorpusGateInputError((CorpusGateReason.CORPUS_SYMLINK,))
        destination_fd = os.open(
            name,
            _FILE_WRITE_FLAGS,
            mode=0o400,
            dir_fd=destination_parent_fd,
        )
        opened_file_descriptors.append(destination_fd)
        digest = sha256()
        while content := os.read(source_fd, 1024 * 1024):
            digest.update(content)
            _write_all(destination_fd, content)
        os.fchmod(destination_fd, 0o400)
        result = digest.hexdigest()
    except BaseException:
        _close_descriptors_no_throw(reversed(opened_file_descriptors))
        raise
    _close_descriptors(reversed(opened_file_descriptors))
    return result


def _copy_pdf_tree(source_fd: int, destination_fd: int) -> tuple[str, ...]:
    source_hashes: list[str] = []
    with os.scandir(source_fd) as entries:
        ordered_entries = sorted(entries, key=lambda entry: entry.name)
    for entry in ordered_entries:
        if entry.is_symlink():
            raise CorpusGateInputError((CorpusGateReason.CORPUS_SYMLINK,))
        if entry.is_dir(follow_symlinks=False):
            source_child_fd = os.open(
                entry.name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=source_fd,
            )
            opened_child_descriptors = [source_child_fd]
            try:
                destination_child_fd = _create_bound_child_directory(
                    destination_fd,
                    entry.name,
                )
                opened_child_descriptors.append(destination_child_fd)
                source_hashes.extend(_copy_pdf_tree(source_child_fd, destination_child_fd))
                os.fchmod(destination_child_fd, 0o500)
            except BaseException:
                _close_descriptors_no_throw(reversed(opened_child_descriptors))
                raise
            _close_descriptors(reversed(opened_child_descriptors))
            continue
        if entry.name.casefold().endswith(".pdf") and entry.is_file(follow_symlinks=False):
            source_hashes.append(_copy_regular_pdf(source_fd, destination_fd, entry.name))
    return tuple(source_hashes)


def _validate_baseline_destination(parent_fd: int, name: str) -> None:
    if not name or name in {".", ".."} or "/" in name:
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    try:
        destination = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(destination.st_mode):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))


def _validate_baseline_absent(parent_fd: int, name: str) -> None:
    if not name or name in {".", ".."} or "/" in name:
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    try:
        destination = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(destination.st_mode):
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
    raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))


def _bind_execution_paths(prepared: _PreparedGate) -> _BoundExecutionPaths:
    repository_root = prepared.repository_state.root
    file_descriptors: list[int] = []
    try:
        root_fd = os.open(repository_root, _DIRECTORY_OPEN_FLAGS)
        file_descriptors.append(root_fd)
        _validate_trusted_directory(os.fstat(root_fd))
        baseline_parent_fd = _open_directory_beneath(
            root_fd,
            _relative_directory_parts(
                repository_root,
                prepared.config.baseline_path.parent,
                allow_root=True,
            ),
            create_missing=True,
            require_trusted=True,
        )
        file_descriptors.append(baseline_parent_fd)
        try:
            fcntl.flock(baseline_parent_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)) from None
        if prepared.accepted_baseline is not None:
            baseline_sha256 = prepared.config.baseline_sha256
            if baseline_sha256 is None:
                raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
            locked_baseline = _load_locked_baseline(
                baseline_parent_fd,
                prepared.config.baseline_path.name,
                baseline_sha256,
            )
            if locked_baseline != prepared.accepted_baseline:
                raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))
            _validate_baseline_destination(
                baseline_parent_fd,
                prepared.config.baseline_path.name,
            )
        else:
            _validate_baseline_absent(
                baseline_parent_fd,
                prepared.config.baseline_path.name,
            )

        work_fd = _open_directory_beneath(
            root_fd,
            _relative_directory_parts(repository_root, prepared.config.work_dir),
            create_missing=True,
            require_trusted=True,
        )
        file_descriptors.append(work_fd)
        if os.listdir(work_fd):
            raise CorpusGateInputError((CorpusGateReason.RUN_PATH_NOT_EMPTY,))

        retained_input_fd = _create_bound_child_directory(work_fd, "retained-input")
        file_descriptors.append(retained_input_fd)
        quarantine_input_fd = _create_bound_child_directory(work_fd, "quarantine-input")
        file_descriptors.append(quarantine_input_fd)

        for source_path, destination_fd, expected in (
            (
                prepared.config.retained_dir,
                retained_input_fd,
                prepared.inventory.retained,
            ),
            (
                prepared.config.quarantine_dir,
                quarantine_input_fd,
                prepared.inventory.quarantine,
            ),
        ):
            source_fd = _open_directory_beneath(
                root_fd,
                _relative_directory_parts(repository_root, source_path),
                create_missing=False,
            )
            try:
                staged_membership = digest_membership(_copy_pdf_tree(source_fd, destination_fd))
            except BaseException:
                _close_descriptors_no_throw((source_fd,))
                raise
            _close_descriptors((source_fd,))
            if staged_membership != expected:
                raise CorpusGateAcceptanceError((CorpusGateReason.MEMBERSHIP_DRIFT,))
            os.fchmod(destination_fd, 0o500)

        run_fds: list[tuple[int, int]] = []
        for output_path, cache_path in prepared.run_paths:
            output_fd = _create_bound_child_directory(work_fd, output_path.name)
            file_descriptors.append(output_fd)
            cache_fd = _create_bound_child_directory(work_fd, cache_path.name)
            file_descriptors.append(cache_fd)
            run_fds.append((output_fd, cache_fd))
        for file_descriptor in (
            retained_input_fd,
            quarantine_input_fd,
            *(fd for pair in run_fds for fd in pair),
        ):
            descriptor_stat = os.fstat(file_descriptor)
            proc_stat = os.stat(_BoundExecutionPaths.path_for(file_descriptor))
            if (descriptor_stat.st_dev, descriptor_stat.st_ino) != (
                proc_stat.st_dev,
                proc_stat.st_ino,
            ):
                raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        return _BoundExecutionPaths(
            repository_fd=root_fd,
            work_fd=work_fd,
            retained_input_fd=retained_input_fd,
            quarantine_input_fd=quarantine_input_fd,
            run_fds=tuple(run_fds),
            baseline_parent_fd=baseline_parent_fd,
            baseline_name=prepared.config.baseline_path.name,
            _file_descriptors=tuple(file_descriptors),
        )
    except CorpusGateError:
        _close_descriptors_no_throw(reversed(file_descriptors))
        raise
    except Exception:
        _close_descriptors_no_throw(reversed(file_descriptors))
        raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)) from None
    except BaseException:
        _close_descriptors_no_throw(reversed(file_descriptors))
        raise


def _same_inode(left_fd: int, right_fd: int) -> bool:
    left = os.fstat(left_fd)
    right = os.fstat(right_fd)
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _validate_bound_reachability(
    prepared: _PreparedGate,
    bound_paths: _BoundExecutionPaths,
) -> None:
    repository_root = prepared.repository_state.root
    for path, expected_fd, allow_root in (
        (prepared.config.work_dir, bound_paths.work_fd, False),
        (prepared.config.baseline_path.parent, bound_paths.baseline_parent_fd, True),
    ):
        try:
            reopened_fd = _open_directory_beneath(
                bound_paths.repository_fd,
                _relative_directory_parts(
                    repository_root,
                    path,
                    allow_root=allow_root,
                ),
                create_missing=False,
                require_trusted=True,
            )
        except CorpusGateError:
            raise
        except OSError:
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,)) from None
        try:
            if not _same_inode(reopened_fd, expected_fd):
                raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        finally:
            with suppress(OSError):
                os.close(reopened_fd)


def _execute_run(
    dependencies: CorpusGateDependencies,
    *,
    input_dir: Path,
    original_input_dir: Path,
    output_dir: Path,
    cache_dir: Path,
    strict: bool,
    jobs: int,
) -> _ObservedCorpusRun:
    original_membership_before = _snapshot_membership(original_input_dir)
    try:
        completed = dependencies.runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=strict,
            jobs=jobs,
        )
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,)) from None
    original_membership_after = _snapshot_membership(original_input_dir)
    return _ObservedCorpusRun(
        completed=completed,
        original_membership_before=original_membership_before,
        original_membership_after=original_membership_after,
    )


def _execute_bound_run(
    dependencies: CorpusGateDependencies,
    prepared: _PreparedGate,
    bound_paths: _BoundExecutionPaths,
    *,
    input_dir: Path,
    original_input_dir: Path,
    output_dir: Path,
    cache_dir: Path,
    strict: bool,
) -> _ObservedCorpusRun:
    _validate_bound_reachability(prepared, bound_paths)
    observed = _execute_run(
        dependencies,
        input_dir=input_dir,
        original_input_dir=original_input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=strict,
        jobs=prepared.config.jobs,
    )
    _validate_bound_reachability(prepared, bound_paths)
    return observed


def _candidate_baseline(
    prepared: _PreparedGate,
    retained_runs: tuple[_ObservedCorpusRun, _ObservedCorpusRun],
    quarantine_runs: tuple[_ObservedCorpusRun, _ObservedCorpusRun],
) -> CorpusBaseline:
    retained_first, retained_second = (run.completed for run in retained_runs)
    quarantine_first, quarantine_second = (run.completed for run in quarantine_runs)
    return CorpusBaseline(
        version=1,
        commit_sha=prepared.repository_state.commit_sha,
        jobs=prepared.config.jobs,
        runtime_tolerance_ratio=prepared.runtime_tolerance_ratio,
        toolchain=prepared.toolchain,
        retained=CorpusPairManifest(
            membership=prepared.inventory.retained,
            first=retained_first.manifest,
            second=retained_second.manifest,
            worst_elapsed_seconds=max(
                retained_first.manifest.elapsed_seconds,
                retained_second.manifest.elapsed_seconds,
            ),
        ),
        quarantine=CorpusPairManifest(
            membership=prepared.inventory.quarantine,
            first=quarantine_first.manifest,
            second=quarantine_second.manifest,
            worst_elapsed_seconds=max(
                quarantine_first.manifest.elapsed_seconds,
                quarantine_second.manifest.elapsed_seconds,
            ),
        ),
    )


def _validate_completed_execution(
    prepared: _PreparedGate,
    candidate: CorpusBaseline,
    retained_runs: tuple[_ObservedCorpusRun, _ObservedCorpusRun],
    quarantine_runs: tuple[_ObservedCorpusRun, _ObservedCorpusRun],
) -> tuple[CorpusGateReason, ...]:
    reasons: list[CorpusGateReason] = []
    if any(
        run.completed.batch_status is not Status.RECONCILED
        or run.completed.manifest.counts.reconciled != run.completed.manifest.counts.documents
        for run in retained_runs
    ):
        reasons.append(CorpusGateReason.RETAINED_NOT_RECONCILED)
    if any(
        run.completed.batch_status is not Status.NOT_STATEMENT
        or run.completed.manifest.counts.not_statement != run.completed.manifest.counts.documents
        for run in quarantine_runs
    ):
        reasons.append(CorpusGateReason.QUARANTINE_MISCLASSIFIED)
    for run, expected in (
        *((run, prepared.inventory.retained) for run in retained_runs),
        *((run, prepared.inventory.quarantine) for run in quarantine_runs),
    ):
        if (
            run.completed.membership_before != expected
            or run.completed.membership_after != expected
            or run.original_membership_before != expected
            or run.original_membership_after != expected
        ):
            reasons.append(CorpusGateReason.MEMBERSHIP_DRIFT)
        if run.completed.manifest.counts.documents != expected.document_count:
            reasons.append(CorpusGateReason.COUNTS_DRIFT)
    if _snapshot_membership(prepared.config.retained_dir) != prepared.inventory.retained:
        reasons.append(CorpusGateReason.MEMBERSHIP_DRIFT)
    if _snapshot_membership(prepared.config.quarantine_dir) != prepared.inventory.quarantine:
        reasons.append(CorpusGateReason.MEMBERSHIP_DRIFT)
    reasons.extend(compare_independent_runs(candidate.retained.first, candidate.retained.second))
    reasons.extend(
        compare_independent_runs(candidate.quarantine.first, candidate.quarantine.second)
    )
    if prepared.accepted_baseline is not None:
        reasons.extend(compare_with_baseline(prepared.accepted_baseline, candidate))
    return _ordered_reasons(reasons)


def _validate_final_state(
    prepared: _PreparedGate,
    dependencies: CorpusGateDependencies,
) -> None:
    try:
        final_repository_state = dependencies.repository.state()
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.REPOSITORY_CHANGED,)) from None
    if final_repository_state != prepared.repository_state or not final_repository_state.clean:
        raise CorpusGateInputError((CorpusGateReason.REPOSITORY_CHANGED,))
    try:
        final_toolchain = dependencies.toolchain.fingerprint()
    except Exception:
        raise CorpusGateRuntimeError((CorpusGateReason.TOOLCHAIN_CHANGED,)) from None
    if final_toolchain != prepared.toolchain:
        raise CorpusGateRuntimeError((CorpusGateReason.TOOLCHAIN_CHANGED,))


def _default_dependencies() -> CorpusGateDependencies:
    runtime_capabilities = _GateRuntimeCapabilities.bind()
    return CorpusGateDependencies(
        runner=LocalCorpusRunner(),
        repository=GitRepositoryInspector(
            executable=runtime_capabilities.git,
            execution_runtime=runtime_capabilities.git_runtime,
            environment=runtime_capabilities.git_environment,
        ),
        toolchain=LocalToolchainInspector(runtime_capabilities=runtime_capabilities),
        runtime_capabilities=runtime_capabilities,
    )


type _InodeIdentity = tuple[int, int]


def _inode_identity(file_stat: os.stat_result) -> _InodeIdentity:
    return (file_stat.st_dev, file_stat.st_ino)


def _name_matches_inode(parent_fd: int, name: str, identity: _InodeIdentity) -> bool:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(named.st_mode) and _inode_identity(named) == identity


def _publish_json_secure(
    parent_fd: int,
    name: str,
    result: BaseModel,
) -> None:
    content = canonical_json_bytes(result)
    temporary_name = f".{name}.{secrets.token_hex(16)}.tmp"
    temporary_fd: int | None = None
    temporary_identity: _InodeIdentity | None = None
    committed = False
    try:
        _validate_trusted_directory(os.fstat(parent_fd))
        _validate_baseline_absent(parent_fd, name)
        temporary_fd = os.open(
            temporary_name,
            _FILE_WRITE_FLAGS,
            mode=0o600,
            dir_fd=parent_fd,
        )
        temporary_stat = os.fstat(temporary_fd)
        if (
            not stat.S_ISREG(temporary_stat.st_mode)
            or temporary_stat.st_uid != os.geteuid()
            or temporary_stat.st_nlink != 1
        ):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        temporary_identity = _inode_identity(temporary_stat)
        _write_all(temporary_fd, content)
        os.fsync(temporary_fd)
        if not _name_matches_inode(parent_fd, temporary_name, temporary_identity):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        _validate_baseline_absent(parent_fd, name)
        os.fsync(parent_fd)
        if not _name_matches_inode(parent_fd, temporary_name, temporary_identity):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        try:
            os.link(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
        except BaseException:
            if _name_matches_inode(parent_fd, name, temporary_identity):
                committed = True
                with suppress(OSError):
                    os.unlink(temporary_name, dir_fd=parent_fd)
                return
            raise
        committed = True
        with suppress(OSError):
            os.unlink(temporary_name, dir_fd=parent_fd)
    finally:
        if temporary_fd is not None:
            file_descriptor = temporary_fd
            temporary_fd = None
            with suppress(OSError):
                os.close(file_descriptor)
        if (
            not committed
            and temporary_identity is not None
            and _name_matches_inode(
                parent_fd,
                temporary_name,
                temporary_identity,
            )
        ):
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=parent_fd)


_ISOLATED_BOOTSTRAP = (
    "import json,sys;"
    "sys.dont_write_bytecode=True;"
    "paths=json.loads(sys.stdin.readline());"
    "sys.path.extend(paths);"
    "from ccparser.corpus_gate import _isolated_worker_main;"
    "raise SystemExit(_isolated_worker_main())"
)

_LOADER_INJECTION_ENVIRONMENT_PREFIXES = ("DYLD_", "LD_", "PYTHON")
_LOADER_INJECTION_ENVIRONMENT_KEYS = frozenset({"GLIBC_TUNABLES"})


def _isolated_worker_environment() -> dict[str, str]:
    environment = _sanitized_child_environment()
    environment["PATH"] = os.defpath
    return environment


def _loader_injection_environment_present() -> bool:
    return any(
        key in _LOADER_INJECTION_ENVIRONMENT_KEYS
        or any(key.startswith(prefix) for prefix in _LOADER_INJECTION_ENVIRONMENT_PREFIXES)
        for key in os.environ
    )


def _isolated_search_paths() -> tuple[Path, ...]:
    candidate_source = Path(__file__).resolve(strict=True).parents[1]
    roots: list[Path] = []
    try:
        for distribution_name in ("ccparser", "pydantic", "pymupdf", "typer"):
            inventory = _inventoried_runtime_distribution(distribution_name)
            distribution_root = inventory.distribution.locate_file("")
            root = Path(str(distribution_root)).resolve(strict=True)
            if root != candidate_source and root not in roots:
                roots.append(root)
    except Exception:
        raise CorpusGateRuntimeError((CorpusGateReason.TOOLCHAIN_UNAVAILABLE,)) from None
    roots.append(candidate_source)
    return tuple(roots)


def _isolated_request(config: CorpusGateConfig, mode: CorpusGateMode) -> bytes:
    search_paths = json.dumps(
        tuple(str(path) for path in _isolated_search_paths()),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    payload = json.dumps(
        {
            "config": json.loads(config.model_dump_json()),
            "mode": mode.value,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{search_paths}\n{payload}\n".encode()


def _worker_error_response(error: CorpusGateError) -> dict[str, object]:
    if isinstance(error, CorpusGateAcceptanceError):
        category = "acceptance"
    elif isinstance(error, CorpusGateInputError):
        category = "input"
    else:
        category = "runtime"
    return {
        "category": category,
        "kind": "error",
        "reason_codes": tuple(reason.value for reason in error.reasons),
    }


def _isolated_worker_main() -> int:
    try:
        if (
            not (
                sys.flags.dont_write_bytecode
                and sys.flags.ignore_environment
                and sys.flags.isolated
                and sys.flags.no_site
            )
            or _loader_injection_environment_present()
        ):
            raise RuntimeError("isolated interpreter required")
        raw_request = json.loads(sys.stdin.readline())
        if not isinstance(raw_request, dict) or set(raw_request) != {"config", "mode"}:
            raise ValueError
        config = CorpusGateConfig.model_validate(raw_request["config"])
        mode = CorpusGateMode(raw_request["mode"])
        attestation = _run_corpus_gate_in_process(config, mode)
        response: dict[str, object] = {
            "attestation": json.loads(attestation.model_dump_json()),
            "kind": "success",
        }
    except CorpusGateError as error:
        response = _worker_error_response(error)
    except Exception:
        response = _worker_error_response(
            CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,))
        )
    serialized = json.dumps(
        response,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write(f"{serialized}\n")
    sys.stdout.flush()
    return 0


def _raise_worker_error(response: Mapping[str, object]) -> None:
    if set(response) != {"category", "kind", "reason_codes"} or response.get("kind") != "error":
        raise ValueError
    raw_reasons = response["reason_codes"]
    if not isinstance(raw_reasons, list) or not raw_reasons:
        raise ValueError
    reasons = tuple(CorpusGateReason(value) for value in raw_reasons if isinstance(value, str))
    if len(reasons) != len(raw_reasons):
        raise ValueError
    category = response["category"]
    if category == "acceptance":
        raise CorpusGateAcceptanceError(reasons)
    if category == "input":
        raise CorpusGateInputError(reasons)
    if category == "runtime":
        raise CorpusGateRuntimeError(reasons)
    raise ValueError


def _run_corpus_gate_isolated(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
) -> CorpusGateAttestation:
    command = (sys.executable, "-I", "-B", "-S", "-c", _ISOLATED_BOOTSTRAP)
    try:
        completed = subprocess.run(
            command,
            input=_isolated_request(config, mode),
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            env=_isolated_worker_environment(),
            timeout=None,
        )
        if completed.returncode != 0:
            raise ValueError
        response = json.loads(completed.stdout)
        if not isinstance(response, dict):
            raise ValueError
        if response.get("kind") == "error":
            _raise_worker_error(response)
        if set(response) != {"attestation", "kind"} or response.get("kind") != "success":
            raise ValueError
        return CorpusGateAttestation.model_validate(response["attestation"])
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,)) from None


def _run_corpus_gate_in_process(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
    *,
    dependencies: CorpusGateDependencies | None = None,
) -> CorpusGateAttestation:
    """Run four isolated corpus parses and accept or reject them atomically."""

    owns_dependencies = dependencies is None
    active_dependencies = dependencies or _default_dependencies()
    try:
        prepared = _prepare_gate(config, mode, active_dependencies)
        bound_paths = _bind_execution_paths(prepared)
        with ExitStack() as execution_stack:
            execution_stack.callback(bound_paths.close)
            runtime_capabilities = active_dependencies.runtime_capabilities
            if runtime_capabilities is not None:
                staged_runtime = runtime_capabilities.stage_tesseract(bound_paths.work_fd)
                execution_stack.callback(staged_runtime.close)
                execution_stack.enter_context(bind_tesseract_runtime(staged_runtime.runtime))
            paths = tuple(
                tuple(_BoundExecutionPaths.path_for(file_descriptor) for file_descriptor in pair)
                for pair in bound_paths.run_fds
            )
            retained_input = _BoundExecutionPaths.path_for(bound_paths.retained_input_fd)
            quarantine_input = _BoundExecutionPaths.path_for(bound_paths.quarantine_input_fd)
            retained_runs = (
                _execute_bound_run(
                    active_dependencies,
                    prepared,
                    bound_paths,
                    input_dir=retained_input,
                    original_input_dir=prepared.config.retained_dir,
                    output_dir=paths[0][0],
                    cache_dir=paths[0][1],
                    strict=True,
                ),
                _execute_bound_run(
                    active_dependencies,
                    prepared,
                    bound_paths,
                    input_dir=retained_input,
                    original_input_dir=prepared.config.retained_dir,
                    output_dir=paths[1][0],
                    cache_dir=paths[1][1],
                    strict=True,
                ),
            )
            quarantine_runs = (
                _execute_bound_run(
                    active_dependencies,
                    prepared,
                    bound_paths,
                    input_dir=quarantine_input,
                    original_input_dir=prepared.config.quarantine_dir,
                    output_dir=paths[2][0],
                    cache_dir=paths[2][1],
                    strict=False,
                ),
                _execute_bound_run(
                    active_dependencies,
                    prepared,
                    bound_paths,
                    input_dir=quarantine_input,
                    original_input_dir=prepared.config.quarantine_dir,
                    output_dir=paths[3][0],
                    cache_dir=paths[3][1],
                    strict=False,
                ),
            )
            candidate = _candidate_baseline(prepared, retained_runs, quarantine_runs)
            reasons = _validate_completed_execution(
                prepared,
                candidate,
                retained_runs,
                quarantine_runs,
            )
            _validate_final_state(prepared, active_dependencies)
            if reasons:
                raise CorpusGateAcceptanceError(reasons)
            elapsed_seconds = sum(
                (
                    run.completed.manifest.elapsed_seconds
                    for run in (*retained_runs, *quarantine_runs)
                ),
                Decimal(0),
            )
            performance_checked = (
                prepared.accepted_baseline is not None
                and prepared.accepted_baseline.toolchain == candidate.toolchain
                and prepared.accepted_baseline.jobs == candidate.jobs
            )
            attestation = CorpusGateAttestation(
                passed=True,
                mode=mode,
                commit_abbreviation=candidate.commit_sha[:12],
                toolchain_abbreviation=candidate.toolchain.digest[:12],
                retained_counts=candidate.retained.first.counts,
                quarantine_counts=candidate.quarantine.first.counts,
                elapsed_seconds=elapsed_seconds,
                performance_checked=performance_checked,
                reason_codes=(),
            )
            if mode is CorpusGateMode.RECORD:
                _validate_bound_reachability(prepared, bound_paths)
                try:
                    _publish_json_secure(
                        bound_paths.baseline_parent_fd,
                        bound_paths.baseline_name,
                        candidate,
                    )
                except CorpusGateError:
                    raise
                except Exception:
                    raise CorpusGateRuntimeError(
                        (CorpusGateReason.PARSER_RUNTIME_FAILED,)
                    ) from None
            return attestation
    finally:
        if owns_dependencies and active_dependencies.runtime_capabilities is not None:
            active_dependencies.runtime_capabilities.close()


def run_corpus_gate(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
    *,
    dependencies: CorpusGateDependencies | None = None,
) -> CorpusGateAttestation:
    """Run the gate in a fresh isolated interpreter unless adapters are injected."""

    if dependencies is None:
        return _run_corpus_gate_isolated(config, mode)
    return _run_corpus_gate_in_process(config, mode, dependencies=dependencies)
