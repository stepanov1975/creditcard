"""Canonical artifact and resource-inventory validation for comparison handoffs."""

from __future__ import annotations

import hashlib
import stat
from typing import Literal

from pydantic import BaseModel, ValidationError

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import ArtifactIdentity
from experiments.row_extraction.runner import (
    ResourceInventory,
    ResourceInventoryEntry,
)

from .handoff_contracts import ArtifactFile, HandoffBinding, HandoffError

_JSONL_TYPE = "jsonl"
_JSONL_VERSION = "canonical-jsonl-v1"
_INVENTORY_TYPE = "resource-inventory"
_INVENTORY_VERSION = "row-resource-inventory-v1"


def validate_identity(
    value: object,
    label: str,
    *,
    artifact_type: str | None = None,
    version: str | None = None,
) -> ArtifactIdentity:
    """Revalidate one runtime value and any contract-defined type/version."""

    try:
        if not isinstance(value, ArtifactIdentity):
            raise TypeError
        identity = ArtifactIdentity.model_validate(value.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise HandoffError(f"invalid {label} identity") from None
    if artifact_type is not None and identity.artifact_type != artifact_type:
        raise HandoffError(f"invalid {label} identity")
    if version is not None and identity.version != version:
        raise HandoffError(f"invalid {label} identity")
    return identity


def validate_artifact_file(
    value: object,
    label: str,
    *,
    artifact_type: str | None = None,
    version: str | None = None,
) -> ArtifactFile:
    if not isinstance(value, ArtifactFile):
        raise HandoffError(f"invalid {label} artifact")
    validate_identity(
        value.identity,
        label,
        artifact_type=artifact_type,
        version=version,
    )
    return value


def file_content(
    artifact: ArtifactFile,
    label: str,
    *,
    artifact_type: str | None = None,
    version: str | None = None,
) -> bytes:
    artifact = validate_artifact_file(
        artifact,
        label,
        artifact_type=artifact_type,
        version=version,
    )
    expected = artifact.identity
    try:
        before = artifact.path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or artifact.path.is_symlink():
            raise OSError
        digest = hashlib.sha256()
        content = bytearray()
        with artifact.path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                content.extend(block)
        after = artifact.path.stat(follow_symlinks=False)
    except OSError:
        raise HandoffError(f"invalid {label} artifact") from None
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if not stable or expected.byte_size != len(content) or expected.sha256 != digest.hexdigest():
        raise HandoffError(f"invalid {label} artifact")
    return bytes(content)


def read_model[Model: BaseModel](
    artifact: ArtifactFile,
    model: type[Model],
    label: str,
) -> Model:
    content = file_content(artifact, label)
    try:
        value = model.model_validate_json(content)
        canonical = _canonical_json_value_content(value.model_dump(mode="json")) + b"\n"
    except (TypeError, ValidationError, ValueError):
        raise HandoffError(f"invalid {label} artifact") from None
    if content != canonical:
        raise HandoffError(f"invalid {label} artifact")
    return value


def read_jsonl[Model: BaseModel](
    artifact: ArtifactFile,
    model: type[Model],
    label: str,
) -> tuple[Model, ...]:
    content = file_content(
        artifact,
        label,
        artifact_type=_JSONL_TYPE,
        version=_JSONL_VERSION,
    )
    try:
        values = tuple(model.model_validate_json(line) for line in content.splitlines())
        canonical = b"".join(_canonical_record_bytes(value) for value in values)
    except (TypeError, ValidationError, ValueError):
        raise HandoffError(f"invalid {label} artifact") from None
    if content != canonical:
        raise HandoffError(f"invalid {label} artifact")
    return values


def _verify_resource_entry(entry: ResourceInventoryEntry, label: str) -> None:
    try:
        before = entry.resolved_path.stat(follow_symlinks=False)
        if entry.resolved_path.is_symlink() or not stat.S_ISREG(before.st_mode):
            raise OSError
        digest = hashlib.sha256()
        byte_size = 0
        with entry.resolved_path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                byte_size += len(block)
        after = entry.resolved_path.stat(follow_symlinks=False)
    except OSError:
        raise HandoffError(f"invalid {label} inventory") from None
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or entry.device != after.st_dev
        or entry.inode != after.st_ino
        or entry.byte_size != byte_size
        or entry.sha256 != digest.hexdigest()
    ):
        raise HandoffError(f"invalid {label} inventory")


def _read_inventory(
    artifact: ArtifactFile,
    category: Literal["model", "dependency"],
) -> ResourceInventory:
    content = file_content(
        artifact,
        category,
        artifact_type=_INVENTORY_TYPE,
        version=_INVENTORY_VERSION,
    )
    try:
        inventory = ResourceInventory.model_validate_json(content)
    except (TypeError, ValidationError, ValueError):
        raise HandoffError(f"invalid {category} inventory") from None
    canonical = _canonical_json_value_content(inventory.model_dump(mode="json")) + b"\n"
    expected_entries = tuple(
        sorted(
            inventory.entries,
            key=lambda entry: (
                entry.category,
                str(entry.resolved_path),
                entry.sha256,
            ),
        )
    )
    if (
        content != canonical
        or inventory.entries != expected_entries
        or any(entry.category != category for entry in inventory.entries)
        or (category == "dependency" and not inventory.entries)
    ):
        raise HandoffError(f"invalid {category} inventory")
    for entry in inventory.entries:
        _verify_resource_entry(entry, category)
    return inventory


def validate_inventories(handoff: HandoffBinding) -> None:
    model_file = validate_artifact_file(
        handoff.model_inventory,
        "model inventory",
        artifact_type=_INVENTORY_TYPE,
        version=_INVENTORY_VERSION,
    )
    dependency_file = validate_artifact_file(
        handoff.dependency_inventory,
        "dependency inventory",
        artifact_type=_INVENTORY_TYPE,
        version=_INVENTORY_VERSION,
    )
    if model_file.path == dependency_file.path or model_file.identity == dependency_file.identity:
        raise HandoffError("model and dependency inventories overlap")
    model = _read_inventory(model_file, "model")
    dependency = _read_inventory(dependency_file, "dependency")
    model_paths = {entry.resolved_path for entry in model.entries}
    dependency_paths = {entry.resolved_path for entry in dependency.entries}
    model_inodes = {(entry.device, entry.inode) for entry in model.entries}
    dependency_inodes = {(entry.device, entry.inode) for entry in dependency.entries}
    if not model_paths.isdisjoint(dependency_paths) or not model_inodes.isdisjoint(
        dependency_inodes
    ):
        raise HandoffError("model and dependency inventories overlap")


__all__ = [
    "file_content",
    "read_jsonl",
    "read_model",
    "validate_artifact_file",
    "validate_identity",
    "validate_inventories",
]
