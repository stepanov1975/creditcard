"""Privacy-safe corpus projections and isolated regression-gate execution."""

from __future__ import annotations

import fcntl
import json
import math
import os
import platform
import secrets
import stat
import subprocess
import time
import unicodedata
from collections import Counter
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser.evidence.ocr import (
    OCR_CURRENCY_RECOGNITION_CACHE_VERSION,
    OCR_NUMERIC_RECOGNITION_CACHE_VERSION,
    OCR_PIPELINE_VERSION,
    OCR_PREPROCESSING_VERSION,
    OCR_RECOGNITION_CACHE_VERSION,
    TESSERACT_VERSION_TIMEOUT_SECONDS,
    currency_tesseract_command,
    numeric_tesseract_command,
    supplemental_tesseract_command,
    tesseract_command,
)
from ccparser.models import (
    BatchResult,
    EvidenceReference,
    Status,
    Transaction,
    TransactionCategory,
)
from ccparser.output import canonical_json_bytes, transactions_csv_bytes
from ccparser.parser import parse_directory
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

type _CanonicalJson = (
    str | int | float | bool | None | list[_CanonicalJson] | dict[str, _CanonicalJson]
)
type _GroupProjection = tuple[str, str, str, tuple[str, ...]]
type _GroupStructure = tuple[tuple[_GroupProjection, ...], ...]
type _TransactionIdentity = tuple[str, tuple[str, ...]]
type _TransactionIdentities = tuple[tuple[_TransactionIdentity, ...], ...]
type _FieldPresence = tuple[tuple[tuple[PresentFieldPath, ...], ...], ...]
type _EvidenceReferenceProjection = tuple[int, tuple[float, float, float, float], str]
type _EvidenceSiteProjection = tuple[str, tuple[_EvidenceReferenceProjection, ...]]
type _EvidenceProvenance = tuple[tuple[tuple[_EvidenceSiteProjection, ...], ...], ...]
type _AmbiguityProjection = tuple[tuple[tuple[str, ...], ...], ...]


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

    retained_dir: Path
    quarantine_dir: Path
    membership_inventory_path: Path
    baseline_path: Path
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

    batch: BatchResult
    manifest: RunManifest
    membership_before: CorpusMembership
    membership_after: CorpusMembership


class ToolchainFingerprint(_GateModel):
    """Version and command fingerprint for a corpus run environment."""

    python_version: str
    package_version: str
    pymupdf_version: str
    tesseract_version: str
    ocr_pipeline_version: str
    ocr_cache_versions: tuple[str, ...]
    command_digest: Digest
    digest: Digest

    @model_validator(mode="after")
    def validate_ocr_cache_versions(self) -> Self:
        if self.ocr_cache_versions != tuple(sorted(self.ocr_cache_versions)):
            raise ValueError("OCR cache versions must be sorted")
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


class _DirectoryParser(Protocol):
    def __call__(
        self,
        path: str | Path,
        output_dir: str | Path,
        strict: bool = False,
        jobs: int | None = None,
        *,
        cache_dir: str | Path | None = None,
        directory_root_policy: DirectoryRootPolicy = DirectoryRootPolicy.RESOLVE,
    ) -> BatchResult:
        raise NotImplementedError


class _NanosecondClock(Protocol):
    def __call__(self) -> int:
        raise NotImplementedError


class LocalCorpusRunner:
    """Filesystem adapter for one timed parser run with adjacent membership checks."""

    def __init__(
        self,
        *,
        parser: _DirectoryParser | None = None,
        monotonic_ns: _NanosecondClock | None = None,
    ) -> None:
        self._parser = parser or parse_directory
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
        batch = self._parser(
            input_dir,
            output_dir,
            strict,
            jobs,
            cache_dir=cache_dir,
            directory_root_policy=directory_root_policy,
        )
        end_nanoseconds = self._monotonic_ns()
        membership_after = _snapshot_membership(input_dir, allow_descriptor_root=True)
        elapsed_nanoseconds = end_nanoseconds - start_nanoseconds
        if elapsed_nanoseconds < 0:
            raise RuntimeError("monotonic clock moved backwards")
        elapsed_seconds = Decimal(elapsed_nanoseconds) / Decimal(1_000_000_000)
        manifest = project_run(batch, elapsed_seconds=elapsed_seconds)
        try:
            json_content = (output_dir / "results.json").read_bytes()
            csv_content = (output_dir / "transactions.csv").read_bytes()
            if json_content != canonical_json_bytes(batch) or csv_content != transactions_csv_bytes(
                batch
            ):
                raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,))
        except CorpusGateError:
            raise
        except Exception:
            raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,)) from None
        manifest = manifest.model_copy(
            update={
                "json_digest": _digest_bytes(json_content),
                "csv_digest": _digest_bytes(csv_content),
            }
        )
        return CompletedCorpusRun(
            batch=batch,
            manifest=manifest,
            membership_before=membership_before,
            membership_after=membership_after,
        )


class GitRepositoryInspector:
    """Inspect the active worktree while deriving containment from Git common state."""

    _TIMEOUT_SECONDS = 10.0

    def __init__(self, *, cwd: Path | None = None) -> None:
        self._cwd = (cwd or Path.cwd()).resolve(strict=True)

    def _git_output(self, *arguments: str) -> bytes:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=self._cwd,
            check=True,
            capture_output=True,
            timeout=self._TIMEOUT_SECONDS,
        )
        return completed.stdout

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

    def state(self) -> RepositoryState:
        project_root = self._read_project_root()
        commit_output = self._git_output("rev-parse", "--verify", "HEAD")
        status_output = self._git_output(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        commit_sha = commit_output.decode("ascii").strip()
        if not commit_sha:
            raise RuntimeError("Git metadata unavailable")
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
        completed = subprocess.run(
            ("git", "check-ignore", "--quiet", "--", str(resolved_path)),
            cwd=worktree_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=self._TIMEOUT_SECONDS,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError("Git ignore policy unavailable")
        return completed.returncode == 0


class LocalToolchainInspector:
    """Fingerprint every local version and OCR command affecting parser output."""

    def fingerprint(self) -> ToolchainFingerprint:
        commands = (
            tesseract_command(),
            supplemental_tesseract_command(),
            numeric_tesseract_command(),
            currency_tesseract_command(),
        )
        completed = subprocess.run(
            (commands[0][0], "--version"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=TESSERACT_VERSION_TIMEOUT_SECONDS,
        )
        version_lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        if not version_lines or not version_lines[0].strip():
            raise RuntimeError("Tesseract version unavailable")
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
        command_digest = _digest_json(commands)
        python_version = platform.python_version()
        package_version = metadata.version("ccparser")
        pymupdf_version = str(fitz.VersionBind)
        tesseract_version = version_lines[0].strip()
        fingerprint_payload: dict[str, object] = {
            "python_version": python_version,
            "package_version": package_version,
            "pymupdf_version": pymupdf_version,
            "tesseract_version": tesseract_version,
            "ocr_pipeline_version": OCR_PIPELINE_VERSION,
            "ocr_cache_versions": cache_versions,
            "command_digest": command_digest,
        }
        return ToolchainFingerprint(
            python_version=python_version,
            package_version=package_version,
            pymupdf_version=pymupdf_version,
            tesseract_version=tesseract_version,
            ocr_pipeline_version=OCR_PIPELINE_VERSION,
            ocr_cache_versions=cache_versions,
            command_digest=command_digest,
            digest=_digest_json(fingerprint_payload),
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


def _normalized_json(value: object) -> _CanonicalJson:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numeric values must be finite")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list | tuple):
        return [_normalized_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, _CanonicalJson] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[unicodedata.normalize("NFC", key)] = _normalized_json(item)
        return normalized
    raise TypeError("unsupported canonical JSON value")


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _digest_json(value: object) -> str:
    normalized = _normalized_json(value)
    content = (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    return _digest_bytes(content)


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


def _project_structural_dimensions(batch: BatchResult) -> _StructuralProjections:
    statuses = Counter(statement.status for statement in batch.statements)
    present_field_counts: Counter[PresentFieldPath] = Counter()
    field_presence: list[tuple[tuple[PresentFieldPath, ...], ...]] = []
    evidence_provenance: list[tuple[tuple[_EvidenceSiteProjection, ...], ...]] = []
    evidence_reference_count = 0

    for statement in batch.statements:
        statement_fields: list[tuple[PresentFieldPath, ...]] = []
        statement_evidence: list[tuple[_EvidenceSiteProjection, ...]] = []
        for transaction in statement.transactions:
            transaction_fields = _transaction_present_fields(transaction)
            present_field_counts.update(transaction_fields)
            statement_fields.append(transaction_fields)

            transaction_evidence = _transaction_evidence_provenance(transaction)
            statement_evidence.append(transaction_evidence)
            evidence_reference_count += sum(
                len(references) for _, references in transaction_evidence
            )
        field_presence.append(tuple(statement_fields))
        evidence_provenance.append(tuple(statement_evidence))

    counts = CorpusCounts(
        documents=len(batch.statements),
        reconciled=statuses[Status.RECONCILED],
        unreconciled=statuses[Status.UNRECONCILED],
        unsupported=statuses[Status.UNSUPPORTED],
        not_statement=statuses[Status.NOT_STATEMENT],
        groups=sum(len(statement.groups) for statement in batch.statements),
        row_results=sum(len(statement.row_results) for statement in batch.statements),
        transactions=sum(len(statement.transactions) for statement in batch.statements),
        ambiguous_transactions=sum(
            bool(transaction.ambiguities)
            for statement in batch.statements
            for transaction in statement.transactions
        ),
        ambiguity_occurrences=sum(
            len(transaction.ambiguities)
            for statement in batch.statements
            for transaction in statement.transactions
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
            tuple(statement.status.value for statement in batch.statements),
        ),
        group_structure=tuple(
            tuple(
                (group.group_id, group.currency, group.status.value, group.transaction_ids)
                for group in statement.groups
            )
            for statement in batch.statements
        ),
        transaction_identities=tuple(
            tuple(
                (transaction.transaction_id, transaction.reconciliation_group_ids)
                for transaction in statement.transactions
            )
            for statement in batch.statements
        ),
        field_presence=tuple(field_presence),
        evidence_provenance=tuple(evidence_provenance),
        ambiguities=tuple(
            tuple(transaction.ambiguities for transaction in statement.transactions)
            for statement in batch.statements
        ),
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
        baseline.toolchain.digest == candidate.toolchain.digest and baseline.jobs == candidate.jobs
    )
    runtime_limit = baseline.retained.worst_elapsed_seconds * (
        Decimal(1) + baseline.runtime_tolerance_ratio
    )
    if matching_runtime_context and candidate.retained.worst_elapsed_seconds > runtime_limit:
        failed.add(CorpusGateReason.RUNTIME_REGRESSION)

    return tuple(reason for reason in CorpusGateReason if reason in failed)


@dataclass(frozen=True, slots=True)
class _ResolvedGateConfig:
    retained_dir: Path
    quarantine_dir: Path
    membership_inventory_path: Path
    baseline_path: Path
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
) -> CorpusMembershipInventory:
    try:
        content = _read_stable_regular_file(repository_fd, repository_root, path)
        return CorpusMembershipInventory.model_validate_json(content)
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.INVENTORY_INVALID,)) from None


def _load_baseline(
    repository_fd: int,
    repository_root: Path,
    path: Path,
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
        return CorpusBaseline.model_validate_json(content)
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None


def _resolve_config(config: CorpusGateConfig) -> _ResolvedGateConfig:
    try:
        return _ResolvedGateConfig(
            retained_dir=config.retained_dir.resolve(strict=True),
            quarantine_dir=config.quarantine_dir.resolve(strict=True),
            membership_inventory_path=config.membership_inventory_path.resolve(strict=False),
            baseline_path=config.baseline_path.resolve(strict=False),
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
        if resolved.runtime_tolerance_ratio is None:
            raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
        if resolved.baseline_path.exists() and not resolved.baseline_path.is_file():
            raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
    else:
        if resolved.runtime_tolerance_ratio is not None:
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
        )
        if mode is CorpusGateMode.RECORD:
            runtime_tolerance_ratio = resolved.runtime_tolerance_ratio
            if runtime_tolerance_ratio is None:
                raise CorpusGateInputError((CorpusGateReason.INVALID_CONFIGURATION,))
            accepted_baseline = None
        else:
            accepted_baseline = _load_baseline(
                repository_fd,
                repository_root,
                resolved.baseline_path,
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


def _load_locked_baseline(parent_fd: int, name: str) -> CorpusBaseline:
    try:
        content = _read_stable_regular_file_at(parent_fd, name)
    except FileNotFoundError:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
    except CorpusGateError:
        raise
    except Exception:
        raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,)) from None
    try:
        return CorpusBaseline.model_validate_json(content)
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
            locked_baseline = _load_locked_baseline(
                baseline_parent_fd,
                prepared.config.baseline_path.name,
            )
            if locked_baseline != prepared.accepted_baseline:
                raise CorpusGateInputError((CorpusGateReason.BASELINE_INVALID,))
        _validate_baseline_destination(
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
        run.completed.batch.status is not Status.RECONCILED
        or any(
            statement.status is not Status.RECONCILED
            for statement in run.completed.batch.statements
        )
        for run in retained_runs
    ):
        reasons.append(CorpusGateReason.RETAINED_NOT_RECONCILED)
    if any(
        run.completed.batch.status is not Status.NOT_STATEMENT
        or any(
            statement.status is not Status.NOT_STATEMENT
            for statement in run.completed.batch.statements
        )
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
        if (
            run.completed.manifest.counts.documents != expected.document_count
            or len(run.completed.batch.statements) != expected.document_count
        ):
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
    return CorpusGateDependencies(
        runner=LocalCorpusRunner(),
        repository=GitRepositoryInspector(),
        toolchain=LocalToolchainInspector(),
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
        _validate_baseline_destination(parent_fd, name)
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
        _validate_baseline_destination(parent_fd, name)
        os.fsync(parent_fd)
        if not _name_matches_inode(parent_fd, temporary_name, temporary_identity):
            raise CorpusGateInputError((CorpusGateReason.UNSAFE_PATH_TOPOLOGY,))
        try:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        except BaseException:
            if _name_matches_inode(parent_fd, name, temporary_identity):
                committed = True
                return
            raise
        committed = True
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


def run_corpus_gate(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
    *,
    dependencies: CorpusGateDependencies | None = None,
) -> CorpusGateAttestation:
    """Run four isolated corpus parses and accept or reject them atomically."""

    active_dependencies = dependencies or _default_dependencies()
    prepared = _prepare_gate(config, mode, active_dependencies)
    bound_paths = _bind_execution_paths(prepared)
    try:
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
            (run.completed.manifest.elapsed_seconds for run in (*retained_runs, *quarantine_runs)),
            Decimal(0),
        )
        performance_checked = (
            prepared.accepted_baseline is not None
            and prepared.accepted_baseline.toolchain.digest == candidate.toolchain.digest
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
                raise CorpusGateRuntimeError((CorpusGateReason.PARSER_RUNTIME_FAILED,)) from None
        return attestation
    finally:
        bound_paths.close()
