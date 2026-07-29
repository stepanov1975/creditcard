"""Identity-bound artifact I/O for locked comparison inputs."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.baselines import PageEvidenceRecord, page_arm_config_id
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import ArtifactIdentity
from experiments.row_extraction.runner import ResourceInventory

from .locked_contracts import ComparisonError, fail

_JSONL_VERSION = "canonical-jsonl-v1"
_RESOURCE_INVENTORY_VERSION = "row-resource-inventory-v1"


@dataclass(frozen=True)
class VerifiedRegularFile:
    """Resolved regular-file identity captured while its bytes were verified."""

    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class _VerifiedBytes:
    file: VerifiedRegularFile
    payload: bytes


def _validated_identity(
    identity: ArtifactIdentity,
    *,
    artifact_type: str,
    version: str,
    message: str,
) -> ArtifactIdentity:
    try:
        validated = ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        fail(message)
    if validated.artifact_type != artifact_type or validated.version != version:
        fail(message)
    return validated


def _stable_regular_bytes(path: Path, *, message: str) -> _VerifiedBytes:
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            fail(message)
        payload = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except ComparisonError:
        raise
    except OSError:
        fail(message)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if not stable:
        fail(message)
    return _VerifiedBytes(
        file=VerifiedRegularFile(path.resolve(strict=True), before.st_dev, before.st_ino),
        payload=payload,
    )


def read_verified_model[Model: BaseModel](
    path: Path,
    identity: ArtifactIdentity,
    model: type[Model],
    *,
    artifact_type: str,
    version: str,
    message: str,
) -> tuple[Model, VerifiedRegularFile]:
    """Read one canonical JSON model through its declared byte identity."""

    expected = _validated_identity(
        identity,
        artifact_type=artifact_type,
        version=version,
        message=message,
    )
    verified = _stable_regular_bytes(path, message=message)
    try:
        value = model.model_validate_json(verified.payload)
    except (TypeError, ValidationError, ValueError):
        fail(message)
    canonical = _canonical_json_value_content(value.model_dump(mode="json")) + b"\n"
    if (
        verified.payload != canonical
        or len(verified.payload) != expected.byte_size
        or hashlib.sha256(verified.payload).hexdigest() != expected.sha256
    ):
        fail(message)
    return value, verified.file


def read_verified_jsonl[Record: BaseModel](
    path: Path,
    identity: ArtifactIdentity,
    model: type[Record],
    *,
    artifact_type: str,
    message: str,
) -> tuple[Record, ...]:
    expected = _validated_identity(
        identity,
        artifact_type=artifact_type,
        version=_JSONL_VERSION,
        message=message,
    )
    digest = hashlib.sha256()
    byte_size = 0
    records: list[Record] = []
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            fail(message)
        with path.open("rb") as source:
            for line in source:
                digest.update(line)
                byte_size += len(line)
                record = model.model_validate_json(line)
                if line != _canonical_record_bytes(record):
                    fail(message)
                records.append(record)
        after = path.stat(follow_symlinks=False)
    except ComparisonError:
        raise
    except (OSError, TypeError, ValidationError, ValueError):
        fail(message)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if not stable or byte_size != expected.byte_size or digest.hexdigest() != expected.sha256:
        fail(message)
    return tuple(records)


def verify_resource_inventory(path: Path, identity: ArtifactIdentity) -> ResourceInventory:
    """Require a canonical regular inventory file with the measured byte identity."""

    inventory, _file = read_verified_model(
        path,
        identity,
        ResourceInventory,
        artifact_type="resource-inventory",
        version=_RESOURCE_INVENTORY_VERSION,
        message="resource inventory identity mismatch",
    )
    return inventory


def verified_resource_inventory(
    path: Path,
    identity: ArtifactIdentity,
) -> tuple[ResourceInventory, VerifiedRegularFile]:
    """Return a verified inventory and the regular output identity carrying it."""

    return read_verified_model(
        path,
        identity,
        ResourceInventory,
        artifact_type="resource-inventory",
        version=_RESOURCE_INVENTORY_VERSION,
        message="resource inventory identity mismatch",
    )


def verify_cache_inventory_root(inventory: ResourceInventory, root: Path) -> None:
    """Require every declared preparation-cache entry beneath one verified root."""

    cache_entries = tuple(entry for entry in inventory.entries if entry.category == "cache")
    if not cache_entries:
        fail("preparation cache provenance mismatch")
    for entry in cache_entries:
        verified = _stable_regular_bytes(
            entry.resolved_path,
            message="preparation cache provenance mismatch",
        )
        if (
            not verified.file.path.is_relative_to(root)
            or verified.file.device != entry.device
            or verified.file.inode != entry.inode
            or len(verified.payload) != entry.byte_size
            or hashlib.sha256(verified.payload).hexdigest() != entry.sha256
        ):
            fail("preparation cache provenance mismatch")


def verify_prepared_arm_manifest(
    path: Path,
    identity: ArtifactIdentity,
    inventory: ResourceInventory,
    *,
    experiment_id: str,
    config_id: str,
    runtime_identity: ArtifactIdentity,
    expected_page_keys: frozenset[tuple[str, int]],
) -> VerifiedRegularFile:
    """Bind canonical prepared page evidence to one measured cache inventory."""

    matches = tuple(
        entry
        for entry in inventory.entries
        if entry.category == "cache"
        and entry.sha256 == identity.sha256
        and entry.byte_size == identity.byte_size
    )
    if len(matches) != 1:
        fail("prepared arm manifest inventory mismatch")
    entry = matches[0]
    try:
        metadata = entry.resolved_path.stat(follow_symlinks=False)
    except OSError:
        fail("prepared arm manifest inventory mismatch")
    if (
        entry.resolved_path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_dev != entry.device
        or metadata.st_ino != entry.inode
    ):
        fail("prepared arm manifest inventory mismatch")
    try:
        declared_path = path.resolve(strict=True)
    except OSError:
        fail("prepared arm manifest inventory mismatch")
    if declared_path != entry.resolved_path.resolve(strict=True):
        fail("prepared arm manifest inventory mismatch")
    records = read_verified_jsonl(
        entry.resolved_path,
        identity,
        PageEvidenceRecord,
        artifact_type="jsonl",
        message="prepared arm manifest identity mismatch",
    )
    if not records or any(
        record.mode != experiment_id
        or page_arm_config_id(record.config_id) != config_id
        or record.runtime_identity != runtime_identity
        for record in records
    ):
        fail("prepared arm manifest binding mismatch")
    page_keys = tuple((record.document_id, record.page_number) for record in records)
    if len(page_keys) != len(set(page_keys)) or frozenset(page_keys) != expected_page_keys:
        fail("prepared arm manifest page membership mismatch")
    return VerifiedRegularFile(declared_path, metadata.st_dev, metadata.st_ino)


def verify_cache_root(path: Path) -> Path:
    """Resolve one non-symlink directory used by exactly one measured run."""

    try:
        metadata = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            fail("invalid locked cache root")
        return path.resolve(strict=True)
    except ComparisonError:
        raise
    except OSError:
        fail("invalid locked cache root")


__all__ = [
    "VerifiedRegularFile",
    "read_verified_jsonl",
    "read_verified_model",
    "verified_resource_inventory",
    "verify_cache_inventory_root",
    "verify_cache_root",
    "verify_prepared_arm_manifest",
    "verify_resource_inventory",
]
