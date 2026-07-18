"""Deterministic positive-evidence directory audit with rollback-safe quarantine."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ccparser.discovery import (
    DocumentClassification,
    StatementDiscovery,
    discover_statement,
)
from ccparser.evidence import DocumentEvidence, extract_pdf

HIGH_CONFIDENCE_NON_STATEMENT = 0.9
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
_POSITIVE_NON_STATEMENT_REASONS = frozenset({"positive_non_statement_form_evidence"})


class AuditApplyError(RuntimeError):
    """An apply failure after which all moves from this call were rolled back."""


class EvidenceExtractor(Protocol):
    def __call__(self, path: Path) -> DocumentEvidence: ...


class StatementClassifier(Protocol):
    def __call__(self, evidence: DocumentEvidence) -> StatementDiscovery: ...


class _ImmutableAuditModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AuditAction(StrEnum):
    """Filesystem action justified by the classification evidence."""

    KEEP = "keep"
    QUARANTINE = "quarantine"
    REVIEW = "review"


class AuditDecision(_ImmutableAuditModel):
    """One privacy-safe decision containing reason codes rather than raw text."""

    original_relative_path: str
    quarantine_relative_path: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: DocumentClassification
    confidence: float = Field(ge=0, le=1)
    action: AuditAction
    reason_codes: tuple[str, ...]


class AuditReport(_ImmutableAuditModel):
    """Ordered decisions and the number of files moved by this invocation."""

    decisions: tuple[AuditDecision, ...]
    applied: bool
    moved_count: int = Field(ge=0)


class _ManifestEntry(_ImmutableAuditModel):
    original_relative_path: str
    quarantine_relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: DocumentClassification
    confidence: float = Field(ge=0, le=1)
    reason_codes: tuple[str, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validated_relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise AuditApplyError("manifest contains an unsafe relative path")
    return relative


def _safe_join(root: Path, relative_value: str) -> Path:
    relative = _validated_relative_path(relative_value)
    candidate = root.joinpath(*relative.parts)
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    if not _is_relative_to(resolved_candidate, resolved_root):
        raise AuditApplyError("audit destination escapes quarantine directory")
    return candidate


def _iter_pdf_files(input_dir: Path, quarantine_dir: Path) -> tuple[Path, ...]:
    resolved_input = input_dir.resolve(strict=True)
    resolved_quarantine = quarantine_dir.resolve(strict=False)
    files: list[Path] = []
    for root_value, directory_names, file_names in os.walk(resolved_input, followlinks=False):
        root = Path(root_value)
        retained_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory = root / directory_name
            if directory.is_symlink() or directory_name == ".cache":
                continue
            if _is_relative_to(directory.resolve(strict=False), resolved_quarantine):
                continue
            retained_directories.append(directory_name)
        directory_names[:] = retained_directories
        for file_name in sorted(file_names):
            path = root / file_name
            if path.suffix.casefold() != ".pdf" or path.is_symlink() or not path.is_file():
                continue
            if _is_relative_to(path.resolve(strict=False), resolved_quarantine):
                continue
            files.append(path)
    return tuple(sorted(files, key=lambda path: path.relative_to(resolved_input).as_posix()))


def _destination_relative(
    quarantine_dir: Path,
    original_relative_path: str,
    source_sha256: str,
) -> str:
    original = _validated_relative_path(original_relative_path)
    candidate = _safe_join(quarantine_dir, original.as_posix())
    if not candidate.exists() and not candidate.is_symlink():
        return original.as_posix()
    suffix = original.suffix
    stem = original.name[: -len(suffix)] if suffix else original.name
    hash_name = f"{stem}-{source_sha256[:12]}{suffix}"
    collision = original.with_name(hash_name)
    index = 2
    while True:
        collision_path = _safe_join(quarantine_dir, collision.as_posix())
        if not collision_path.exists() and not collision_path.is_symlink():
            return collision.as_posix()
        collision = original.with_name(f"{stem}-{source_sha256[:12]}-{index}{suffix}")
        index += 1


def _decision_for_discovery(
    relative_path: str,
    source_sha256: str,
    discovery: StatementDiscovery,
    quarantine_dir: Path,
) -> AuditDecision:
    reasons = list(discovery.reason_codes)
    if discovery.classification is DocumentClassification.STATEMENT:
        action = AuditAction.KEEP
    elif discovery.classification is DocumentClassification.NOT_STATEMENT:
        has_positive_reason = bool(
            _POSITIVE_NON_STATEMENT_REASONS.intersection(discovery.reason_codes)
        )
        if discovery.confidence < HIGH_CONFIDENCE_NON_STATEMENT:
            reasons.append("non_statement_confidence_below_threshold")
            action = AuditAction.REVIEW
        elif not has_positive_reason:
            reasons.append("non_statement_positive_evidence_missing")
            action = AuditAction.REVIEW
        else:
            action = AuditAction.QUARANTINE
    else:
        action = AuditAction.REVIEW
    quarantine_relative = (
        _destination_relative(quarantine_dir, relative_path, source_sha256)
        if action is AuditAction.QUARANTINE
        else None
    )
    return AuditDecision(
        original_relative_path=relative_path,
        quarantine_relative_path=quarantine_relative,
        sha256=source_sha256,
        classification=discovery.classification,
        confidence=discovery.confidence,
        action=action,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _error_decision(relative_path: str, source_sha256: str, reason: str) -> AuditDecision:
    return AuditDecision(
        original_relative_path=relative_path,
        sha256=source_sha256,
        classification=DocumentClassification.AMBIGUOUS,
        confidence=0.0,
        action=AuditAction.REVIEW,
        reason_codes=(reason,),
    )


def _manifest_entry(decision: AuditDecision) -> _ManifestEntry:
    if decision.quarantine_relative_path is None:
        raise ValueError("quarantine decision requires a destination")
    return _ManifestEntry(
        original_relative_path=decision.original_relative_path,
        quarantine_relative_path=decision.quarantine_relative_path,
        sha256=decision.sha256,
        classification=decision.classification,
        confidence=decision.confidence,
        reason_codes=decision.reason_codes,
    )


def _historical_decision(entry: _ManifestEntry) -> AuditDecision:
    return AuditDecision(
        original_relative_path=entry.original_relative_path,
        quarantine_relative_path=entry.quarantine_relative_path,
        sha256=entry.sha256,
        classification=entry.classification,
        confidence=entry.confidence,
        action=AuditAction.QUARANTINE,
        reason_codes=entry.reason_codes,
    )


def _load_manifest(quarantine_dir: Path) -> tuple[_ManifestEntry, ...]:
    manifest_path = quarantine_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return ()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise AuditApplyError("audit manifest is not a regular file")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != MANIFEST_VERSION:
            raise AuditApplyError("audit manifest version is invalid")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise AuditApplyError("audit manifest entries are invalid")
        entries = tuple(_ManifestEntry.model_validate(entry) for entry in raw_entries)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
        raise AuditApplyError("audit manifest could not be validated") from error
    expected_order = tuple(sorted(entries, key=lambda entry: entry.original_relative_path))
    if entries != expected_order or len({entry.original_relative_path for entry in entries}) != len(
        entries
    ):
        raise AuditApplyError("audit manifest ordering or uniqueness is invalid")
    for entry in entries:
        _validated_relative_path(entry.original_relative_path)
        destination = _safe_join(quarantine_dir, entry.quarantine_relative_path)
        if destination.is_symlink() or not destination.is_file():
            raise AuditApplyError("audit manifest destination is missing")
        if _sha256_file(destination) != entry.sha256:
            raise AuditApplyError("audit manifest destination hash mismatch")
    return entries


def _canonical_manifest(entries: Iterable[_ManifestEntry]) -> bytes:
    ordered = tuple(sorted(entries, key=lambda entry: entry.original_relative_path))
    payload = {
        "entries": [entry.model_dump(mode="json") for entry in ordered],
        "version": MANIFEST_VERSION,
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _write_manifest_atomic(quarantine_dir: Path, entries: Iterable[_ManifestEntry]) -> None:
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = quarantine_dir / MANIFEST_NAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=quarantine_dir,
            prefix=".manifest-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(_canonical_manifest(entries))
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, manifest_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _copy_exclusive(source: Path, destination: Path) -> None:
    with source.open("rb") as source_file, destination.open("xb") as destination_file:
        shutil.copyfileobj(source_file, destination_file)
        destination_file.flush()
        os.fsync(destination_file.fileno())


def _move_file(source: Path, destination: Path) -> None:
    """Move without ever replacing an existing destination."""

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        try:
            _copy_exclusive(source, destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    try:
        source.unlink()
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _rollback_moves(moves: Iterable[tuple[Path, Path]]) -> None:
    failures: list[OSError] = []
    for source, destination in reversed(tuple(moves)):
        try:
            if source.exists() or source.is_symlink():
                raise FileExistsError(source)
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, source)
        except OSError as error:
            failures.append(error)
    if failures:
        raise AuditApplyError("audit apply failed and rollback could not restore every source")


def _apply_quarantine(
    input_dir: Path,
    quarantine_dir: Path,
    decisions: tuple[AuditDecision, ...],
    historical_entries: tuple[_ManifestEntry, ...],
) -> int:
    current_quarantine = tuple(
        decision for decision in decisions if decision.action is AuditAction.QUARANTINE
    )
    if not current_quarantine:
        return 0
    moved: list[tuple[Path, Path]] = []
    new_entries: list[_ManifestEntry] = []
    try:
        for decision in current_quarantine:
            source = _safe_join(input_dir, decision.original_relative_path)
            if source.is_symlink() or not source.is_file():
                raise AuditApplyError("source disappeared before move")
            if _sha256_file(source) != decision.sha256:
                raise AuditApplyError("source changed before move")
            if decision.quarantine_relative_path is None:
                raise AuditApplyError("quarantine destination is missing")
            destination = _safe_join(
                quarantine_dir,
                decision.quarantine_relative_path,
            )
            _move_file(source, destination)
            moved.append((source, destination))
            new_entries.append(_manifest_entry(decision))
        _write_manifest_atomic(quarantine_dir, (*historical_entries, *new_entries))
    except Exception as error:
        try:
            _rollback_moves(moved)
        except AuditApplyError as rollback_error:
            raise rollback_error from error
        raise AuditApplyError(f"audit apply failed: {error}") from error
    return len(moved)


def audit_directory(
    input_dir: str | Path,
    quarantine_dir: str | Path,
    apply: bool = False,
    *,
    extractor: EvidenceExtractor | None = None,
    classifier: StatementClassifier | None = None,
) -> AuditReport:
    """Audit PDFs recursively; optionally apply only positive non-statement moves."""

    input_path = Path(input_dir).resolve(strict=True)
    quarantine_path = Path(quarantine_dir).resolve(strict=False)
    if not input_path.is_dir():
        raise ValueError("input directory must be a directory")
    if _is_relative_to(input_path, quarantine_path):
        raise ValueError("quarantine directory must not contain input")
    extract = extractor or extract_pdf
    classify = classifier or discover_statement
    historical_entries = _load_manifest(quarantine_path)
    historical_paths = {entry.original_relative_path for entry in historical_entries}
    decisions: list[AuditDecision] = []
    for source in _iter_pdf_files(input_path, quarantine_path):
        relative_path = source.relative_to(input_path).as_posix()
        source_sha256 = _sha256_file(source)
        if relative_path in historical_paths:
            raise AuditApplyError("a previously quarantined source path has reappeared")
        try:
            evidence = extract(source)
        except Exception:
            decisions.append(_error_decision(relative_path, source_sha256, "extraction_error"))
            continue
        if evidence.source_sha256 != source_sha256:
            decisions.append(
                _error_decision(
                    relative_path,
                    source_sha256,
                    "extraction_source_hash_mismatch",
                )
            )
            continue
        try:
            discovery = classify(evidence)
        except Exception:
            decisions.append(_error_decision(relative_path, source_sha256, "classification_error"))
            continue
        decisions.append(
            _decision_for_discovery(
                relative_path,
                source_sha256,
                discovery,
                quarantine_path,
            )
        )
    current_decisions = tuple(
        sorted(decisions, key=lambda decision: decision.original_relative_path)
    )
    moved_count = (
        _apply_quarantine(input_path, quarantine_path, current_decisions, historical_entries)
        if apply
        else 0
    )
    combined = tuple(
        sorted(
            (*current_decisions, *(_historical_decision(entry) for entry in historical_entries)),
            key=lambda decision: decision.original_relative_path,
        )
    )
    return AuditReport(decisions=combined, applied=apply, moved_count=moved_count)


__all__ = [
    "AuditAction",
    "AuditApplyError",
    "AuditDecision",
    "AuditReport",
    "audit_directory",
]
