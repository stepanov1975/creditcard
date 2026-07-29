"""Identity-bound execution and resource measurement for frozen row arms."""

from __future__ import annotations

import hashlib
import math
import os
import resource
import stat
import subprocess
import tempfile
import warnings
from collections.abc import Iterable
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    ExperimentArm,
    FrozenRow,
    RowPrediction,
    _FrozenModel,
)

_RESOURCE_INVENTORY_VERSION: Literal["row-resource-inventory-v1"] = "row-resource-inventory-v1"
_ROW_SEQUENCE_VERSION: Literal["canonical-jsonl-v1"] = "canonical-jsonl-v1"
_MEASUREMENT_PROTOCOL: Literal["row-resource-measurement-v1"] = "row-resource-measurement-v1"

type ResourceCategory = Literal["model", "dependency", "cache"]
type ResourceBasis = Literal["end-to-end-method", "materialized-adapter"]


class RunContractError(ValueError):
    """A measured run cannot satisfy the frozen execution contract."""


class InventoryRoots(_FrozenModel):
    version: Literal["row-resource-roots-v1"]
    category: Literal["model", "dependency"]
    roots: tuple[Path, ...]


class ResourceInventoryEntry(_FrozenModel):
    category: ResourceCategory
    resolved_path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    device: int = Field(ge=0)
    inode: int = Field(gt=0)


class ResourceInventory(_FrozenModel):
    version: Literal["row-resource-inventory-v1"]
    entries: tuple[ResourceInventoryEntry, ...]


class ResourceSpec(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    expected_row_count: int = Field(gt=0)
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: ResourceBasis
    worker_count: Literal[1]
    runtime_identity: ArtifactIdentity
    arm_manifest_identity: ArtifactIdentity
    private_root: Path
    model_inventory_path: Path
    model_inventory_identity: ArtifactIdentity
    dependency_inventory_path: Path
    dependency_inventory_identity: ArtifactIdentity
    cache_root: Path
    resource_inventory_output: Path


class PreparationMeasurements(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    row_count: int = Field(gt=0)
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: Literal["end-to-end-method"]
    preparation_ns: int = Field(gt=0)
    peak_rss_bytes: int = Field(gt=0)
    subprocess_count: int = Field(ge=0)
    worker_count: Literal[1]
    runtime_identity: ArtifactIdentity
    arm_manifest_identity: ArtifactIdentity
    resource_inventory_path: Path
    resource_inventory_identity: ArtifactIdentity


class RunMeasurements(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: ResourceBasis
    arm_manifest_identity: ArtifactIdentity
    row_count: int = Field(gt=0)
    total_ns: int = Field(gt=0)
    p50_ns: int = Field(gt=0)
    p95_ns: int = Field(gt=0)
    preparation_ns: int = Field(ge=0)
    end_to_end_ns: int = Field(gt=0)
    cold_start_ns: int = Field(gt=0)
    throughput_rows_per_second: Decimal = Field(gt=0)
    peak_rss_bytes: int = Field(gt=0)
    model_bytes: int = Field(ge=0)
    dependency_bytes: int = Field(gt=0)
    cache_bytes: int = Field(ge=0)
    subprocess_count: int = Field(ge=0)
    worker_count: Literal[1]
    measurement_protocol: Literal["row-resource-measurement-v1"]
    runtime_identity: ArtifactIdentity
    model_inventory_identity: ArtifactIdentity
    dependency_inventory_identity: ArtifactIdentity
    resource_inventory_identity: ArtifactIdentity
    predictions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MeasuredArmFactory(Protocol):
    @property
    def experiment_id(self) -> str: ...

    @property
    def config_id(self) -> str: ...

    @property
    def row_sequence_identity(self) -> ArtifactIdentity: ...

    @property
    def expected_row_count(self) -> int: ...

    @property
    def split(self) -> DatasetSplit: ...

    @property
    def arm_manifest_identity(self) -> ArtifactIdentity: ...

    @property
    def runtime_identity(self) -> ArtifactIdentity: ...

    @property
    def model_inventory_identity(self) -> ArtifactIdentity: ...

    @property
    def dependency_inventory_identity(self) -> ArtifactIdentity: ...

    @property
    def cache_root(self) -> Path: ...

    @property
    def resource_basis(self) -> ResourceBasis: ...

    @property
    def worker_count(self) -> Literal[1]: ...

    @property
    def subprocess_count(self) -> int: ...

    def build(self) -> ExperimentArm: ...


class PredictionSink(Protocol):
    @property
    def target(self) -> Path: ...

    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity: ...

    def commit(self) -> ArtifactIdentity: ...

    def abort(self) -> None: ...


class JsonlPredictionSink:
    """Publish canonical prediction JSONL only after a successful measured run."""

    def __init__(self, target: Path) -> None:
        if target.exists():
            raise RunContractError("prediction target already exists")
        self._target = target
        self._staging = target.with_name(f".{target.name}.staging")
        if self._staging.exists():
            raise RunContractError("prediction staging target already exists")
        self._state: Literal["new", "staged", "committed", "aborted"] = "new"
        self._identity: ArtifactIdentity | None = None
        self._owned_staging_identity: tuple[int, int] | None = None
        self._owned_target_identity: tuple[int, int] | None = None

    @property
    def target(self) -> Path:
        return self._target

    def stage(self, predictions: Iterable[RowPrediction]) -> ArtifactIdentity:
        if self._state != "new":
            raise RunContractError("prediction sink is one-shot")
        if self._target.exists() or self._staging.exists():
            raise RunContractError("prediction target already exists")
        digest = hashlib.sha256()
        byte_size = 0
        descriptor: int | None = None
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self._staging, flags, 0o600)
            descriptor_stat = os.fstat(descriptor)
            if not stat.S_ISREG(descriptor_stat.st_mode):
                raise RunContractError("prediction staging target is not a regular file")
            self._owned_staging_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                for prediction in predictions:
                    payload = _canonical_record_bytes(prediction)
                    output.write(payload)
                    digest.update(payload)
                    byte_size += len(payload)
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            if self._owned_staging_identity is not None:
                _unlink_owned(self._staging, self._owned_staging_identity)
                self._owned_staging_identity = None
            self._state = "aborted"
            raise
        identity = ArtifactIdentity(
            artifact_type="jsonl",
            sha256=digest.hexdigest(),
            version=_ROW_SEQUENCE_VERSION,
            byte_size=byte_size,
        )
        self._identity = identity
        self._state = "staged"
        return identity

    def commit(self) -> ArtifactIdentity:
        if (
            self._state != "staged"
            or self._identity is None
            or self._owned_staging_identity is None
        ):
            raise RunContractError("prediction sink is one-shot")
        if self._target.exists():
            raise RunContractError("prediction target already exists")
        try:
            staging_stat = self._staging.stat(follow_symlinks=False)
            staging_identity = (staging_stat.st_dev, staging_stat.st_ino)
            if (
                not stat.S_ISREG(staging_stat.st_mode)
                or staging_identity != self._owned_staging_identity
            ):
                raise RunContractError("prediction staging identity changed")
            if _prediction_file_identity(self._staging) != self._identity:
                raise RunContractError("prediction staging identity changed")
            os.link(self._staging, self._target, follow_symlinks=False)
            self._owned_target_identity = self._owned_staging_identity
            target_stat = self._target.stat(follow_symlinks=False)
            target_identity = (target_stat.st_dev, target_stat.st_ino)
            if target_identity != self._owned_target_identity:
                raise RunContractError("prediction target identity changed")
            if _prediction_file_identity(self._target) != self._identity:
                raise RunContractError("prediction target identity changed")
            _unlink_owned(self._staging, self._owned_staging_identity)
            self._owned_staging_identity = None
        except FileExistsError:
            self.abort()
            raise RunContractError("prediction target already exists") from None
        except BaseException:
            self.abort()
            raise
        self._state = "committed"
        return self._identity

    def abort(self) -> None:
        if self._state == "aborted":
            raise RunContractError("prediction sink is one-shot")
        if self._owned_staging_identity is not None:
            _unlink_owned(self._staging, self._owned_staging_identity)
            self._owned_staging_identity = None
        if self._owned_target_identity is not None:
            _unlink_owned(self._target, self._owned_target_identity)
            self._owned_target_identity = None
        self._state = "aborted"


def _hash_file(path: Path) -> tuple[str, int, os.stat_result]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            byte_size += len(block)
    after = path.stat(follow_symlinks=False)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or byte_size != after.st_size:
        raise RunContractError("resource inventory entry changed during hashing")
    return digest.hexdigest(), byte_size, after


def _resolved_regular_files(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved_roots: list[Path] = []
    for root in roots:
        if not root.is_absolute():
            raise RunContractError("resource inventory root must be absolute")
        if root.is_symlink():
            raise RunContractError("resource inventory cannot contain a symlink")
        try:
            resolved = root.resolve(strict=True)
        except OSError:
            raise RunContractError("resource inventory root is unavailable") from None
        for previous in resolved_roots:
            if (
                resolved == previous
                or resolved.is_relative_to(previous)
                or previous.is_relative_to(resolved)
            ):
                raise RunContractError("resource inventory roots overlap")
        resolved_roots.append(resolved)

    files: list[Path] = []
    for root in resolved_roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.is_dir():
            raise RunContractError("resource inventory root is not a regular file or directory")
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink():
                raise RunContractError("resource inventory cannot contain a symlink")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise RunContractError("resource inventory contains a non-regular file")
            files.append(candidate.resolve(strict=True))
    return tuple(files)


def _inventory_for_files(
    category: ResourceCategory,
    files: tuple[Path, ...],
    *,
    allow_empty: bool,
) -> ResourceInventory:
    if not files and not allow_empty:
        raise RunContractError(f"{category} inventory cannot be empty")
    seen_inodes: set[tuple[int, int]] = set()
    entries: list[ResourceInventoryEntry] = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise RunContractError("resource inventory contains a non-regular file")
        sha256, byte_size, stat = _hash_file(path)
        inode = (stat.st_dev, stat.st_ino)
        if inode in seen_inodes:
            raise RunContractError("resource inventory contains a duplicate inode")
        seen_inodes.add(inode)
        entries.append(
            ResourceInventoryEntry(
                category=category,
                resolved_path=path.resolve(strict=True),
                sha256=sha256,
                byte_size=byte_size,
                device=stat.st_dev,
                inode=stat.st_ino,
            )
        )
    return ResourceInventory(
        version=_RESOURCE_INVENTORY_VERSION,
        entries=tuple(
            sorted(
                entries,
                key=lambda entry: (entry.category, str(entry.resolved_path), entry.sha256),
            )
        ),
    )


def build_resource_inventory(roots: InventoryRoots) -> ResourceInventory:
    """Build one deterministic model or dependency inventory from explicit roots."""

    try:
        validated = InventoryRoots.model_validate(_model_dump_safely(roots))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RunContractError("invalid resource inventory roots") from None
    return _inventory_for_files(
        validated.category,
        _resolved_regular_files(validated.roots),
        allow_empty=validated.category == "model" and not validated.roots,
    )


def _inventory_payload(inventory: ResourceInventory) -> bytes:
    return _canonical_json_value_content(inventory.model_dump(mode="json")) + b"\n"


def _inventory_identity(payload: bytes) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="resource-inventory",
        sha256=hashlib.sha256(payload).hexdigest(),
        version=_RESOURCE_INVENTORY_VERSION,
        byte_size=len(payload),
    )


def _model_dump_safely(value: _FrozenModel) -> dict[str, object]:
    """Dump an untrusted model without allowing value-bearing serializer warnings."""

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return value.model_dump(mode="python")


def _validated_resource_spec(resource_spec: ResourceSpec) -> ResourceSpec:
    try:
        return ResourceSpec.model_validate(_model_dump_safely(resource_spec))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RunContractError("invalid resource specification") from None


def _validated_preparation_measurements(
    preparation: PreparationMeasurements,
) -> PreparationMeasurements:
    try:
        return PreparationMeasurements.model_validate(_model_dump_safely(preparation))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RunContractError("invalid preparation measurements") from None


def _validated_prediction_identity(identity: ArtifactIdentity) -> ArtifactIdentity:
    try:
        validated = ArtifactIdentity.model_validate(_model_dump_safely(identity))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RunContractError("staged prediction identity is invalid") from None
    if validated.artifact_type != "jsonl" or validated.version != _ROW_SEQUENCE_VERSION:
        raise RunContractError("staged prediction identity has wrong type or version")
    return validated


def _prediction_file_identity(path: Path) -> ArtifactIdentity:
    """Independently validate and identify a canonical prediction stream."""

    try:
        path_stat = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
            raise RunContractError("prediction output is not a regular file")
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as source:
            for line in source:
                try:
                    prediction = RowPrediction.model_validate_json(line)
                except (ValidationError, ValueError):
                    raise RunContractError("prediction output is not canonical") from None
                if line != _canonical_record_bytes(prediction):
                    raise RunContractError("prediction output is not canonical")
                digest.update(line)
                byte_size += len(line)
        after = path.stat(follow_symlinks=False)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            path_stat.st_dev,
            path_stat.st_ino,
            path_stat.st_size,
            path_stat.st_mtime_ns,
        ) or byte_size != after.st_size:
            raise RunContractError("prediction output identity changed")
    except RunContractError:
        raise
    except OSError:
        raise RunContractError("prediction output is unavailable") from None
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=digest.hexdigest(),
        version=_ROW_SEQUENCE_VERSION,
        byte_size=byte_size,
    )


def _read_inventory(path: Path, identity: ArtifactIdentity) -> ResourceInventory:
    if (
        identity.artifact_type != "resource-inventory"
        or identity.version != _RESOURCE_INVENTORY_VERSION
    ):
        raise RunContractError("resource inventory identity has wrong type or version")
    try:
        payload = path.read_bytes()
        inventory = ResourceInventory.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        raise RunContractError("resource inventory is invalid") from None
    if (
        len(payload) != identity.byte_size
        or hashlib.sha256(payload).hexdigest() != identity.sha256
        or payload != _inventory_payload(inventory)
    ):
        raise RunContractError("resource inventory identity mismatch")
    _verify_inventory_entries(inventory)
    return inventory


def _unlink_owned(path: Path, identity: tuple[int, int]) -> None:
    with suppress(FileNotFoundError):
        stat = path.stat(follow_symlinks=False)
        if (stat.st_dev, stat.st_ino) == identity:
            path.unlink()


def _write_inventory(
    path: Path,
    inventory: ResourceInventory,
) -> tuple[ArtifactIdentity, tuple[int, int]]:
    if path.exists():
        raise RunContractError("resource inventory output already exists")
    payload = _inventory_payload(inventory)
    temporary: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    owned_target_identity: tuple[int, int] | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
        temporary_stat = temporary.stat(follow_symlinks=False)
        temporary_identity = (temporary_stat.st_dev, temporary_stat.st_ino)
        os.link(temporary, path, follow_symlinks=False)
        owned_target_identity = temporary_identity
        target_stat = path.stat(follow_symlinks=False)
        if (target_stat.st_dev, target_stat.st_ino) != owned_target_identity:
            raise RunContractError("resource inventory output identity changed")
        _unlink_owned(temporary, temporary_identity)
        temporary = None
        published = True
    except FileExistsError:
        raise RunContractError("resource inventory output already exists") from None
    except BaseException:
        raise
    finally:
        if temporary is not None and temporary_identity is not None:
            _unlink_owned(temporary, temporary_identity)
        if not published and owned_target_identity is not None:
            _unlink_owned(path, owned_target_identity)
    assert owned_target_identity is not None
    return _inventory_identity(payload), owned_target_identity


def _verify_inventory_entries(inventory: ResourceInventory) -> None:
    seen_inodes: set[tuple[int, int]] = set()
    seen_paths: set[Path] = set()
    expected_order = tuple(
        sorted(
            inventory.entries,
            key=lambda entry: (entry.category, str(entry.resolved_path), entry.sha256),
        )
    )
    if inventory.entries != expected_order:
        raise RunContractError("resource inventory is not canonically ordered")
    for entry in inventory.entries:
        path = entry.resolved_path
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RunContractError("resource inventory entry changed")
        sha256, byte_size, stat = _hash_file(path)
        current = (stat.st_dev, stat.st_ino)
        if (
            sha256 != entry.sha256
            or byte_size != entry.byte_size
            or current != (entry.device, entry.inode)
        ):
            raise RunContractError("resource inventory entry changed")
        if current in seen_inodes or path in seen_paths:
            raise RunContractError("resource inventory contains a duplicate entry")
        seen_inodes.add(current)
        seen_paths.add(path)


def _row_sequence_identity(rows: tuple[FrozenRow, ...]) -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    for row in rows:
        payload = _canonical_record_bytes(row)
        digest.update(payload)
        byte_size += len(payload)
    return ArtifactIdentity(
        artifact_type="frozen-row-sequence",
        sha256=digest.hexdigest(),
        version=_ROW_SEQUENCE_VERSION,
        byte_size=byte_size,
    )


def _require_beneath(path: Path, private_root: Path) -> Path:
    if not path.is_absolute() or not private_root.is_absolute():
        raise RunContractError("private root paths must be absolute")
    resolved_root = private_root.resolve(strict=True)
    resolved = path.resolve(strict=False)
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise RunContractError("path escapes private root")
    return resolved


def _require_ignored_or_external(private_root: Path) -> None:
    worktree = Path(__file__).resolve().parents[2]
    resolved = private_root.resolve(strict=True)
    if not resolved.is_relative_to(worktree):
        return
    completed = subprocess.run(
        ("git", "check-ignore", "--quiet", str(resolved)),
        cwd=worktree,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RunContractError("private root is not ignored")


def _validated_rows(rows: Iterable[FrozenRow], spec: ResourceSpec) -> tuple[FrozenRow, ...]:
    collected: list[FrozenRow] = []
    seen_identities: set[tuple[str, str]] = set()
    for row in rows:
        try:
            validated = FrozenRow.model_validate(_model_dump_safely(row))
        except (AttributeError, TypeError, ValidationError, ValueError):
            raise RunContractError("invalid input row") from None
        identity = (validated.document_id, validated.row_id)
        if identity in seen_identities:
            raise RunContractError("duplicate input row identity")
        seen_identities.add(identity)
        if validated.split is not spec.split:
            raise RunContractError("row split mismatch")
        collected.append(validated)
    result = tuple(collected)
    if not result:
        raise RunContractError("empty run")
    if len(result) != spec.expected_row_count:
        raise RunContractError("row count mismatch")
    sequence_identity = _row_sequence_identity(result)
    if (
        spec.row_sequence_identity.artifact_type != "frozen-row-sequence"
        or spec.row_sequence_identity.version != _ROW_SEQUENCE_VERSION
        or sequence_identity != spec.row_sequence_identity
    ):
        raise RunContractError("row sequence identity mismatch")
    return result


def _factory_binding(factory: MeasuredArmFactory) -> tuple[object, ...]:
    try:
        subprocess_count = factory.subprocess_count
        if (
            not isinstance(subprocess_count, int)
            or isinstance(subprocess_count, bool)
            or subprocess_count < 0
        ):
            raise RunContractError("factory subprocess count is invalid")
        return (
            factory.experiment_id,
            factory.config_id,
            factory.row_sequence_identity,
            factory.expected_row_count,
            factory.split,
            factory.arm_manifest_identity,
            factory.runtime_identity,
            factory.model_inventory_identity,
            factory.dependency_inventory_identity,
            factory.cache_root,
            factory.resource_basis,
            factory.worker_count,
        )
    except RunContractError:
        raise
    except BaseException:
        raise RunContractError("factory binding is unavailable") from None


def _expected_binding(spec: ResourceSpec) -> tuple[object, ...]:
    return (
        spec.experiment_id,
        spec.config_id,
        spec.row_sequence_identity,
        spec.expected_row_count,
        spec.split,
        spec.arm_manifest_identity,
        spec.runtime_identity,
        spec.model_inventory_identity,
        spec.dependency_inventory_identity,
        spec.cache_root,
        spec.resource_basis,
        spec.worker_count,
    )


def _validate_factory(
    factory: MeasuredArmFactory,
    spec: ResourceSpec,
    *,
    changed: bool,
) -> None:
    if _factory_binding(factory) != _expected_binding(spec):
        message = "factory binding changed" if changed else "factory binding mismatch"
        raise RunContractError(message)


def _validated_prediction(
    prediction: RowPrediction,
    row: FrozenRow,
    arm: ExperimentArm,
    spec: ResourceSpec,
) -> RowPrediction:
    try:
        validated = RowPrediction.model_validate(_model_dump_safely(prediction))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RunContractError("prediction evidence is invalid") from None
    if validated.document_id != row.document_id or validated.row_id != row.row_id:
        raise RunContractError("prediction identity mismatch")
    if (
        validated.experiment_id != spec.experiment_id
        or validated.config_id != spec.config_id
        or arm.experiment_id != spec.experiment_id
        or arm.config_id != spec.config_id
    ):
        raise RunContractError("prediction arm identity mismatch")
    return validated


def _nearest_rank(values: tuple[int, ...], percentile: int) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered) / 100))
    return ordered[rank - 1]


def _rss_high_water_bytes() -> int:
    self_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    children_rss = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    value = (self_rss + children_rss) * 1024
    if value <= 0:
        raise RunContractError("RSS measurement is unavailable")
    return value


def _cache_inventory(cache_root: Path) -> ResourceInventory:
    files = _resolved_regular_files((cache_root,))
    return _inventory_for_files("cache", files, allow_empty=True)


def _union_inventories(inventories: tuple[ResourceInventory, ...]) -> ResourceInventory:
    by_inode: dict[tuple[int, int], ResourceInventoryEntry] = {}
    by_path: dict[Path, ResourceInventoryEntry] = {}
    for inventory in inventories:
        _verify_inventory_entries(inventory)
        for entry in inventory.entries:
            inode = (entry.device, entry.inode)
            existing_inode = by_inode.get(inode)
            existing_path = by_path.get(entry.resolved_path)
            for existing in (existing_inode, existing_path):
                if existing is not None and existing != entry:
                    raise RunContractError("resource inventory category or metadata conflict")
            by_inode[inode] = entry
            by_path[entry.resolved_path] = entry
    return ResourceInventory(
        version=_RESOURCE_INVENTORY_VERSION,
        entries=tuple(
            sorted(
                by_inode.values(),
                key=lambda entry: (entry.category, str(entry.resolved_path), entry.sha256),
            )
        ),
    )


def _entries(
    inventory: ResourceInventory,
    category: ResourceCategory,
) -> tuple[ResourceInventoryEntry, ...]:
    return tuple(entry for entry in inventory.entries if entry.category == category)


def _validate_preparation(
    preparation: PreparationMeasurements | None,
    spec: ResourceSpec,
    model_inventory: ResourceInventory,
    dependency_inventory: ResourceInventory,
) -> ResourceInventory | None:
    page_baselines = {"conditional-page-ocr", "forced-page-ocr"}
    if spec.experiment_id == "accepted-baseline" and spec.resource_basis != "materialized-adapter":
        raise RunContractError("accepted baseline resource basis mismatch")
    if spec.experiment_id in page_baselines and spec.resource_basis != "end-to-end-method":
        raise RunContractError("page baseline resource basis mismatch")
    if (
        spec.experiment_id != "accepted-baseline"
        and spec.experiment_id not in page_baselines
        and spec.resource_basis != "end-to-end-method"
    ):
        raise RunContractError("materialized adapter is reserved for accepted baseline")
    if preparation is None:
        if spec.experiment_id in page_baselines:
            raise RunContractError("page baseline requires preparation")
        return None
    if spec.resource_basis == "materialized-adapter":
        raise RunContractError("materialized adapter forbids preparation")
    if spec.experiment_id not in page_baselines:
        raise RunContractError("preparation is reserved for page baselines")
    expected = (
        spec.experiment_id,
        spec.config_id,
        spec.row_sequence_identity,
        spec.expected_row_count,
        spec.split,
        spec.cache_policy,
        spec.resource_basis,
        spec.worker_count,
        spec.runtime_identity,
        spec.arm_manifest_identity,
    )
    actual = (
        preparation.experiment_id,
        preparation.config_id,
        preparation.row_sequence_identity,
        preparation.row_count,
        preparation.split,
        preparation.cache_policy,
        preparation.resource_basis,
        preparation.worker_count,
        preparation.runtime_identity,
        preparation.arm_manifest_identity,
    )
    if actual != expected:
        raise RunContractError("preparation binding mismatch")
    _require_beneath(preparation.resource_inventory_path, spec.private_root)
    inventory = _read_inventory(
        preparation.resource_inventory_path,
        preparation.resource_inventory_identity,
    )
    if _entries(inventory, "model") != model_inventory.entries:
        raise RunContractError("preparation model inventory mismatch")
    if _entries(inventory, "dependency") != dependency_inventory.entries:
        raise RunContractError("preparation dependency inventory mismatch")
    for entry in _entries(inventory, "cache"):
        _require_beneath(entry.resolved_path, spec.private_root)
    if not _entries(inventory, "cache"):
        raise RunContractError("preparation cache inventory cannot be empty")
    if not any(
        entry.sha256 == spec.arm_manifest_identity.sha256
        and entry.byte_size == spec.arm_manifest_identity.byte_size
        for entry in _entries(inventory, "cache")
    ):
        raise RunContractError("preparation evidence artifact is absent")
    return inventory


def _preparation_consumption_path(
    preparation: PreparationMeasurements,
    private_root: Path,
) -> Path:
    payload = _canonical_json_value_content(
        {
            "arm_manifest_identity": preparation.arm_manifest_identity.model_dump(mode="json"),
            "config_id": preparation.config_id,
            "experiment_id": preparation.experiment_id,
            "resource_inventory_identity": (
                preparation.resource_inventory_identity.model_dump(mode="json")
            ),
            "row_sequence_identity": preparation.row_sequence_identity.model_dump(mode="json"),
            "runtime_identity": preparation.runtime_identity.model_dump(mode="json"),
            "split": preparation.split.value,
            "version": "row-preparation-consumption-v1",
        }
    )
    key = hashlib.sha256(payload).hexdigest()
    return private_root / f".row-preparation-{key}.consumed"


def _reserve_preparation(
    preparation: PreparationMeasurements,
    private_root: Path,
) -> tuple[Path, tuple[int, int]]:
    marker = _preparation_consumption_path(preparation, private_root)
    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(marker, flags, 0o600)
        marker_stat = os.fstat(descriptor)
        if not stat.S_ISREG(marker_stat.st_mode):
            raise RunContractError("preparation consumption marker is invalid")
        return marker, (marker_stat.st_dev, marker_stat.st_ino)
    except FileExistsError:
        raise RunContractError("preparation is already consumed") from None
    except RunContractError:
        raise
    except OSError:
        raise RunContractError("preparation consumption marker is unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_paths(spec: ResourceSpec, sink: PredictionSink) -> Path:
    try:
        if not spec.private_root.is_dir() or spec.private_root.is_symlink():
            raise RunContractError("private root is invalid")
        _require_ignored_or_external(spec.private_root)
        for path in (
            spec.model_inventory_path,
            spec.dependency_inventory_path,
            spec.cache_root,
            spec.resource_inventory_output,
        ):
            _require_beneath(path, spec.private_root)
        target = sink.target
        if not isinstance(target, Path):
            raise RunContractError("prediction target is invalid")
        validated_target = _require_beneath(target, spec.private_root)
        cache_root = spec.cache_root.resolve(strict=False)
        output_paths = [spec.resource_inventory_output.resolve(strict=False)]
        output_paths.append(validated_target)
        if any(
            output == cache_root or output.is_relative_to(cache_root) for output in output_paths
        ):
            raise RunContractError("cache and output paths overlap")
        if spec.cache_root.exists():
            raise RunContractError("cache root is not a new empty cache")
        if spec.resource_inventory_output.exists():
            raise RunContractError("resource inventory output already exists")
        return validated_target
    except RunContractError:
        raise
    except OSError:
        raise RunContractError("private path validation failed") from None


def _require_sink_target(sink: PredictionSink, expected: Path) -> None:
    try:
        target = sink.target
        if not isinstance(target, Path) or target.resolve(strict=False) != expected:
            raise RunContractError("prediction sink target changed")
    except RunContractError:
        raise
    except OSError:
        raise RunContractError("prediction sink target changed") from None


def _abort_safely(sink: PredictionSink) -> None:
    with suppress(BaseException):
        sink.abort()


def assert_repeated_output(first: Path, second: Path) -> None:
    """Require two distinct canonical prediction streams to be byte-identical."""

    try:
        if first == second or first.is_symlink() or second.is_symlink():
            raise RunContractError("repeated prediction output is invalid")
        first_stat = first.stat(follow_symlinks=False)
        second_stat = second.stat(follow_symlinks=False)
        if (
            not first.is_file()
            or not second.is_file()
            or (first_stat.st_dev, first_stat.st_ino) == (second_stat.st_dev, second_stat.st_ino)
        ):
            raise RunContractError("repeated prediction output is invalid")
        record_count = 0
        with first.open("rb") as first_stream, second.open("rb") as second_stream:
            while True:
                first_line = first_stream.readline()
                second_line = second_stream.readline()
                if not first_line and not second_line:
                    break
                if not first_line or first_line != second_line:
                    raise RunContractError("repeated prediction output mismatch")
                try:
                    prediction = RowPrediction.model_validate_json(first_line)
                except (ValidationError, ValueError):
                    raise RunContractError("repeated prediction output is not canonical") from None
                if first_line != _canonical_record_bytes(prediction):
                    raise RunContractError("repeated prediction output is not canonical")
                record_count += 1
        if record_count == 0:
            raise RunContractError("repeated prediction output is empty")
    except RunContractError:
        raise
    except BaseException:
        raise RunContractError("repeated prediction output read failed") from None


def run_arm(
    rows: Iterable[FrozenRow],
    factory: MeasuredArmFactory,
    sink: PredictionSink,
    resource_spec: ResourceSpec,
    preparation: PreparationMeasurements | None = None,
) -> RunMeasurements:
    """Run, measure, and publish exactly one identity-bound arm execution."""

    inventory_output: Path | None = None
    owned_inventory_identity: tuple[int, int] | None = None
    preparation_marker: Path | None = None
    owned_preparation_marker: tuple[int, int] | None = None
    try:
        spec = _validated_resource_spec(resource_spec)
        inventory_output = spec.resource_inventory_output
        validated_preparation = (
            _validated_preparation_measurements(preparation) if preparation is not None else None
        )
        validated_sink_target = _validate_paths(spec, sink)
        selected_rows = _validated_rows(rows, spec)
        snapshots = tuple(_canonical_record_bytes(row) for row in selected_rows)
        _validate_factory(factory, spec, changed=False)
        if factory.subprocess_count != 0:
            raise RunContractError("factory subprocess count must start at zero")

        model_inventory = _read_inventory(
            spec.model_inventory_path,
            spec.model_inventory_identity,
        )
        dependency_inventory = _read_inventory(
            spec.dependency_inventory_path,
            spec.dependency_inventory_identity,
        )
        if any(entry.category != "model" for entry in model_inventory.entries):
            raise RunContractError("model inventory category mismatch")
        if any(entry.category != "dependency" for entry in dependency_inventory.entries):
            raise RunContractError("dependency inventory category mismatch")
        if not dependency_inventory.entries:
            raise RunContractError("dependency inventory cannot be empty")
        if spec.experiment_id == "accepted-baseline" and model_inventory.entries:
            raise RunContractError("accepted baseline model inventory must be empty")
        preparation_inventory = _validate_preparation(
            validated_preparation,
            spec,
            model_inventory,
            dependency_inventory,
        )
        if validated_preparation is not None:
            preparation_marker, owned_preparation_marker = _reserve_preparation(
                validated_preparation,
                spec.private_root,
            )

        spec.cache_root.mkdir()
        total_start = perf_counter_ns()
        arm = factory.build()
        _validate_factory(factory, spec, changed=True)
        if arm.experiment_id != spec.experiment_id or arm.config_id != spec.config_id:
            raise RunContractError("arm identity mismatch")

        row_durations: list[int] = []
        cold_end: int | None = None
        prediction_digest = hashlib.sha256()
        prediction_byte_size = 0
        prediction_count = 0

        def measured_predictions() -> Iterable[RowPrediction]:
            nonlocal cold_end, prediction_byte_size, prediction_count
            for index, row in enumerate(selected_rows):
                row_start = perf_counter_ns()
                raw_prediction = arm.predict(row)
                if _canonical_record_bytes(row) != snapshots[index]:
                    raise RunContractError("input row mutation")
                prediction = _validated_prediction(
                    raw_prediction,
                    row,
                    arm,
                    spec,
                )
                row_end = perf_counter_ns()
                if row_end <= row_start:
                    raise RunContractError("measurement clock did not advance")
                row_durations.append(row_end - row_start)
                if cold_end is None:
                    cold_end = row_end
                payload = _canonical_record_bytes(prediction)
                prediction_digest.update(payload)
                prediction_byte_size += len(payload)
                prediction_count += 1
                yield prediction

        _require_sink_target(sink, validated_sink_target)
        staged_identity = _validated_prediction_identity(sink.stage(measured_predictions()))
        _require_sink_target(sink, validated_sink_target)
        if prediction_count != len(selected_rows):
            raise RunContractError("prediction sink did not consume the measured stream")
        expected_prediction_identity = ArtifactIdentity(
            artifact_type="jsonl",
            sha256=prediction_digest.hexdigest(),
            version=_ROW_SEQUENCE_VERSION,
            byte_size=prediction_byte_size,
        )
        if staged_identity != expected_prediction_identity:
            raise RunContractError("staged prediction identity mismatch")

        if any(
            _canonical_record_bytes(row) != snapshots[index]
            for index, row in enumerate(selected_rows)
        ):
            raise RunContractError("input row mutation")

        total_end = perf_counter_ns()
        if total_end <= total_start or cold_end is None or cold_end <= total_start:
            raise RunContractError("measurement clock did not advance")
        fixed_rss = _rss_high_water_bytes()
        _validate_factory(factory, spec, changed=True)
        measured_subprocess_count = factory.subprocess_count

        _verify_inventory_entries(model_inventory)
        _verify_inventory_entries(dependency_inventory)
        if preparation_inventory is not None:
            _verify_inventory_entries(preparation_inventory)
        cache_inventory = _cache_inventory(spec.cache_root)
        inventories: tuple[ResourceInventory, ...] = (
            model_inventory,
            dependency_inventory,
            cache_inventory,
        )
        if preparation_inventory is not None:
            inventories = (*inventories, preparation_inventory)
        combined_inventory = _union_inventories(inventories)
        combined_identity, owned_inventory_identity = _write_inventory(
            inventory_output,
            combined_inventory,
        )

        total_ns = total_end - total_start
        preparation_ns = (
            validated_preparation.preparation_ns if validated_preparation is not None else 0
        )
        peak_rss = max(
            fixed_rss,
            validated_preparation.peak_rss_bytes if validated_preparation is not None else 0,
        )
        subprocess_count = measured_subprocess_count + (
            validated_preparation.subprocess_count if validated_preparation is not None else 0
        )
        measurements = RunMeasurements(
            experiment_id=spec.experiment_id,
            config_id=spec.config_id,
            row_sequence_identity=spec.row_sequence_identity,
            split=spec.split,
            cache_policy=spec.cache_policy,
            resource_basis=spec.resource_basis,
            arm_manifest_identity=spec.arm_manifest_identity,
            row_count=len(selected_rows),
            total_ns=total_ns,
            p50_ns=_nearest_rank(tuple(row_durations), 50),
            p95_ns=_nearest_rank(tuple(row_durations), 95),
            preparation_ns=preparation_ns,
            end_to_end_ns=preparation_ns + total_ns,
            cold_start_ns=cold_end - total_start,
            throughput_rows_per_second=(
                Decimal(len(selected_rows)) * Decimal(1_000_000_000) / Decimal(total_ns)
            ),
            peak_rss_bytes=peak_rss,
            model_bytes=sum(entry.byte_size for entry in _entries(combined_inventory, "model")),
            dependency_bytes=sum(
                entry.byte_size for entry in _entries(combined_inventory, "dependency")
            ),
            cache_bytes=sum(entry.byte_size for entry in _entries(combined_inventory, "cache")),
            subprocess_count=subprocess_count,
            worker_count=spec.worker_count,
            measurement_protocol=_MEASUREMENT_PROTOCOL,
            runtime_identity=spec.runtime_identity,
            model_inventory_identity=spec.model_inventory_identity,
            dependency_inventory_identity=spec.dependency_inventory_identity,
            resource_inventory_identity=combined_identity,
            predictions_sha256=staged_identity.sha256,
        )
        _require_sink_target(sink, validated_sink_target)
        committed = _validated_prediction_identity(sink.commit())
        _require_sink_target(sink, validated_sink_target)
        if committed != expected_prediction_identity:
            raise RunContractError("prediction sink identity changed")
        if _prediction_file_identity(validated_sink_target) != expected_prediction_identity:
            raise RunContractError("prediction sink identity changed")
        _validate_factory(factory, spec, changed=True)
        if factory.subprocess_count != measured_subprocess_count:
            raise RunContractError("factory subprocess count changed")
        if any(
            _canonical_record_bytes(row) != snapshots[index]
            for index, row in enumerate(selected_rows)
        ):
            raise RunContractError("input row mutation")
        if (
            _read_inventory(spec.model_inventory_path, spec.model_inventory_identity)
            != model_inventory
            or _read_inventory(
                spec.dependency_inventory_path,
                spec.dependency_inventory_identity,
            )
            != dependency_inventory
        ):
            raise RunContractError("resource inventory identity changed")
        if (
            validated_preparation is not None
            and preparation_inventory is not None
            and _read_inventory(
                validated_preparation.resource_inventory_path,
                validated_preparation.resource_inventory_identity,
            )
            != preparation_inventory
        ):
            raise RunContractError("preparation resource inventory identity changed")
        _verify_inventory_entries(model_inventory)
        _verify_inventory_entries(dependency_inventory)
        if preparation_inventory is not None:
            _verify_inventory_entries(preparation_inventory)
        if _cache_inventory(spec.cache_root) != cache_inventory:
            raise RunContractError("resource inventory entry changed")
        if _read_inventory(inventory_output, combined_identity) != combined_inventory:
            raise RunContractError("resource inventory output identity changed")
        _require_sink_target(sink, validated_sink_target)
        if preparation_marker is not None and owned_preparation_marker is not None:
            try:
                marker_stat = preparation_marker.stat(follow_symlinks=False)
            except OSError:
                raise RunContractError("preparation consumption marker changed") from None
            if (marker_stat.st_dev, marker_stat.st_ino) != owned_preparation_marker:
                raise RunContractError("preparation consumption marker changed")
        return measurements
    except RunContractError:
        _abort_safely(sink)
        if inventory_output is not None and owned_inventory_identity is not None:
            _unlink_owned(inventory_output, owned_inventory_identity)
        if preparation_marker is not None and owned_preparation_marker is not None:
            _unlink_owned(preparation_marker, owned_preparation_marker)
        raise
    except BaseException:
        _abort_safely(sink)
        if inventory_output is not None and owned_inventory_identity is not None:
            _unlink_owned(inventory_output, owned_inventory_identity)
        if preparation_marker is not None and owned_preparation_marker is not None:
            _unlink_owned(preparation_marker, owned_preparation_marker)
        raise RunContractError("measured arm execution failed") from None


__all__ = [
    "InventoryRoots",
    "JsonlPredictionSink",
    "MeasuredArmFactory",
    "PredictionSink",
    "PreparationMeasurements",
    "ResourceInventory",
    "ResourceInventoryEntry",
    "ResourceSpec",
    "RunContractError",
    "RunMeasurements",
    "assert_repeated_output",
    "build_resource_inventory",
    "run_arm",
]
