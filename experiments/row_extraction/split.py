from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from experiments.row_extraction.contracts import DatasetSplit, FrozenRow, _FrozenModel

_SPLIT_VERSION: Literal["row-extraction-split-v1"] = "row-extraction-split-v1"
_RATIO_DENOMINATOR = 5
_SPLIT_TARGETS = (
    (DatasetSplit.TRAIN, 3),
    (DatasetSplit.VALIDATION, 1),
    (DatasetSplit.TEST, 1),
)


class SplitError(ValueError):
    """Raised when a split or fold violates the frozen grouping contract."""


def _require_nonempty(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


class DocumentGroup(_FrozenModel):
    document_ids: frozenset[str] = Field(min_length=1)
    duplicate_group: str = Field(min_length=1)
    layout_group: str = Field(min_length=1)
    stratum: str = Field(min_length=1)

    @field_validator("document_ids")
    @classmethod
    def nonempty_document_ids(cls, values: frozenset[str]) -> frozenset[str]:
        if any(not value.strip() for value in values):
            raise ValueError("document ID must not be empty")
        return values

    @field_validator("duplicate_group", "layout_group", "stratum")
    @classmethod
    def nonempty_group_metadata(cls, value: str, info: ValidationInfo) -> str:
        return _require_nonempty(value, info.field_name or "group metadata")


class DocumentMembership(_FrozenModel):
    document_id: str = Field(min_length=1)
    split: DatasetSplit
    atomic_unit: str = Field(min_length=1)
    stratum: str = Field(min_length=1)

    @field_validator("document_id", "atomic_unit", "stratum")
    @classmethod
    def nonempty_membership_metadata(cls, value: str, info: ValidationInfo) -> str:
        return _require_nonempty(value, info.field_name or "membership metadata")


class SplitManifest(_FrozenModel):
    seed: str = Field(min_length=1)
    version: Literal["row-extraction-split-v1"]
    memberships: tuple[DocumentMembership, ...] = Field(min_length=1)

    @field_validator("seed")
    @classmethod
    def nonempty_manifest_metadata(cls, value: str, info: ValidationInfo) -> str:
        return _require_nonempty(value, info.field_name or "manifest metadata")

    @model_validator(mode="after")
    def consistent_membership(self) -> Self:
        document_ids: set[str] = set()
        unit_splits: dict[str, DatasetSplit] = {}
        for membership in self.memberships:
            if membership.document_id in document_ids:
                raise ValueError("document membership must be unique")
            document_ids.add(membership.document_id)
            existing_split = unit_splits.setdefault(
                membership.atomic_unit,
                membership.split,
            )
            if existing_split is not membership.split:
                raise ValueError("atomic unit cannot span splits")
        return self

    def split_for(self, document_id: str) -> DatasetSplit:
        return self._membership_for(document_id).split

    def atomic_unit_for(self, document_id: str) -> str:
        return self._membership_for(document_id).atomic_unit

    def stratum_for(self, document_id: str) -> str:
        return self._membership_for(document_id).stratum

    def _membership_for(self, document_id: str) -> DocumentMembership:
        for membership in self.memberships:
            if membership.document_id == document_id:
                return membership
        raise SplitError("unknown document ID")


class Fold(_FrozenModel):
    index: int = Field(ge=0)
    train_document_ids: frozenset[str] = Field(min_length=1)
    validation_document_ids: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def disjoint_membership(self) -> Self:
        if not self.train_document_ids.isdisjoint(self.validation_document_ids):
            raise ValueError("fold document sets must be disjoint")
        return self


@dataclass(frozen=True)
class _AtomicUnit:
    unit_id: str
    document_ids: tuple[str, ...]
    stratum_counts: tuple[tuple[str, int], ...]


class _DisjointSet:
    def __init__(self, values: Sequence[str]) -> None:
        self._parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self._parent[value]
        while parent != self._parent[parent]:
            parent = self._parent[parent]
        root = parent
        current = value
        while current != root:
            parent = self._parent[current]
            self._parent[current] = root
            current = parent
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root


def _connected_units(groups: Sequence[DocumentGroup]) -> tuple[_AtomicUnit, ...]:
    document_metadata: dict[str, tuple[str, str, str]] = {}
    for group in groups:
        metadata = (group.duplicate_group, group.layout_group, group.stratum)
        for document_id in group.document_ids:
            previous = document_metadata.setdefault(document_id, metadata)
            if previous != metadata:
                raise SplitError("conflicting document metadata")

    disjoint_set = _DisjointSet(tuple(sorted(document_metadata)))
    duplicate_representatives: dict[str, str] = {}
    layout_representatives: dict[str, str] = {}
    for group in groups:
        documents = tuple(sorted(group.document_ids))
        representative = documents[0]
        for document_id in documents[1:]:
            disjoint_set.union(representative, document_id)
        duplicate = duplicate_representatives.setdefault(
            group.duplicate_group,
            representative,
        )
        disjoint_set.union(representative, duplicate)
        layout = layout_representatives.setdefault(group.layout_group, representative)
        disjoint_set.union(representative, layout)

    component_documents: dict[str, list[str]] = {}
    for document_id in sorted(document_metadata):
        root = disjoint_set.find(document_id)
        component_documents.setdefault(root, []).append(document_id)

    component_duplicates: dict[str, set[str]] = {root: set() for root in component_documents}
    component_layouts: dict[str, set[str]] = {root: set() for root in component_documents}
    for group in groups:
        root = disjoint_set.find(min(group.document_ids))
        component_duplicates[root].add(group.duplicate_group)
        component_layouts[root].add(group.layout_group)

    units: list[_AtomicUnit] = []
    for root, component_document_ids in component_documents.items():
        stratum_counts = Counter(document_metadata[value][2] for value in component_document_ids)
        canonical = json.dumps(
            {
                "documents": [
                    [document_id, document_metadata[document_id][2]]
                    for document_id in component_document_ids
                ],
                "duplicate_groups": sorted(component_duplicates[root]),
                "layout_groups": sorted(component_layouts[root]),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        units.append(
            _AtomicUnit(
                unit_id=hashlib.sha256(canonical).hexdigest(),
                document_ids=tuple(component_document_ids),
                stratum_counts=tuple(sorted(stratum_counts.items())),
            )
        )
    return tuple(units)


def _seeded_order_key(seed: str, unit_id: str, purpose: str) -> tuple[str, str]:
    payload = f"{purpose}\0{seed}\0{unit_id}".encode()
    return hashlib.sha256(payload).hexdigest(), unit_id


def _assignment_deviation(
    candidate: DatasetSplit,
    unit: _AtomicUnit,
    assigned_totals: dict[DatasetSplit, int],
    assigned_strata: dict[str, dict[DatasetSplit, int]],
    total_documents: int,
    stratum_totals: dict[str, int],
) -> int:
    unit_strata = dict(unit.stratum_counts)
    deviation = 0
    for split, numerator in _SPLIT_TARGETS:
        count = assigned_totals[split]
        if split is candidate:
            count += len(unit.document_ids)
        deviation += abs(_RATIO_DENOMINATOR * count - numerator * total_documents)
        for stratum, stratum_total in stratum_totals.items():
            stratum_count = assigned_strata[stratum][split]
            if split is candidate:
                stratum_count += unit_strata.get(stratum, 0)
            deviation += abs(_RATIO_DENOMINATOR * stratum_count - numerator * stratum_total)
    return deviation


def assign_splits(
    groups: Sequence[DocumentGroup],
    seed: str,
) -> SplitManifest:
    if not groups:
        raise SplitError("at least one document group is required")
    if not seed.strip():
        raise SplitError("split seed must not be empty")
    units = tuple(
        sorted(
            _connected_units(groups),
            key=lambda unit: _seeded_order_key(seed, unit.unit_id, "split"),
        )
    )
    stratum_totals = Counter(
        stratum for unit in units for stratum, count in unit.stratum_counts for _ in range(count)
    )
    assigned_totals = {split: 0 for split, _ in _SPLIT_TARGETS}
    assigned_strata = {
        stratum: {split: 0 for split, _ in _SPLIT_TARGETS} for stratum in stratum_totals
    }
    unit_splits: dict[str, DatasetSplit] = {}
    total_documents = sum(len(unit.document_ids) for unit in units)

    for unit in units:
        split = min(
            (value for value, _ in _SPLIT_TARGETS),
            key=lambda value: (
                _assignment_deviation(
                    value,
                    unit,
                    assigned_totals,
                    assigned_strata,
                    total_documents,
                    dict(stratum_totals),
                ),
                tuple(value for value, _ in _SPLIT_TARGETS).index(value),
            ),
        )
        unit_splits[unit.unit_id] = split
        assigned_totals[split] += len(unit.document_ids)
        for stratum, count in unit.stratum_counts:
            assigned_strata[stratum][split] += count

    stratum_by_document = {
        document_id: stratum
        for group in groups
        for document_id in group.document_ids
        for stratum in (group.stratum,)
    }
    memberships = tuple(
        DocumentMembership(
            document_id=document_id,
            split=unit_splits[unit.unit_id],
            atomic_unit=unit.unit_id,
            stratum=stratum_by_document[document_id],
        )
        for unit in sorted(units, key=lambda value: value.unit_id)
        for document_id in unit.document_ids
    )
    return SplitManifest(
        seed=seed,
        version=_SPLIT_VERSION,
        memberships=memberships,
    )


def _membership_index(
    manifest: SplitManifest,
) -> tuple[dict[str, DocumentMembership], dict[str, frozenset[str]]]:
    memberships: dict[str, DocumentMembership] = {}
    unit_documents: dict[str, set[str]] = {}
    unit_splits: dict[str, DatasetSplit] = {}
    for membership in manifest.memberships:
        if membership.document_id in memberships:
            raise SplitError("manifest document membership is duplicated")
        memberships[membership.document_id] = membership
        unit_documents.setdefault(membership.atomic_unit, set()).add(membership.document_id)
        previous_split = unit_splits.setdefault(
            membership.atomic_unit,
            membership.split,
        )
        if previous_split is not membership.split:
            raise SplitError("manifest atomic unit spans splits")
    return memberships, {
        unit: frozenset(document_ids) for unit, document_ids in unit_documents.items()
    }


def validate_split(rows: Sequence[FrozenRow], manifest: SplitManifest) -> None:
    memberships, _ = _membership_index(manifest)
    row_identities: set[tuple[str, str]] = set()
    row_documents: set[str] = set()
    for row in rows:
        identity = (row.document_id, row.row_id)
        if identity in row_identities:
            raise SplitError("row identity must be unique")
        row_identities.add(identity)
        membership = memberships.get(row.document_id)
        if membership is None:
            raise SplitError("row document is absent from manifest")
        if row.split is not membership.split:
            raise SplitError("row split differs from manifest")
        row_documents.add(row.document_id)
    if row_documents != set(memberships):
        raise SplitError("manifest document has no row")


def grouped_folds(
    rows: Sequence[FrozenRow],
    manifest: SplitManifest,
    fold_count: int,
) -> tuple[Fold, ...]:
    if not rows:
        raise SplitError("at least one training row is required")
    if fold_count < 2:
        raise SplitError("fold_count must be at least two")
    memberships, manifest_units = _membership_index(manifest)
    row_ids: set[str] = set()
    selected_documents: set[str] = set()
    selected_units: set[str] = set()
    for row in rows:
        if row.row_id in row_ids:
            raise SplitError("fold row ID must be unique")
        row_ids.add(row.row_id)
        membership = memberships.get(row.document_id)
        if membership is None:
            raise SplitError("fold row document is absent from manifest")
        if (
            row.split is not DatasetSplit.TRAIN
            or membership.split is not DatasetSplit.TRAIN
            or row.split is not membership.split
        ):
            raise SplitError("fold rows must be training membership")
        selected_documents.add(row.document_id)
        selected_units.add(membership.atomic_unit)

    for unit_id in selected_units:
        if not manifest_units[unit_id] <= selected_documents:
            raise SplitError("atomic unit is only partially represented")
    if len(selected_units) < fold_count:
        raise SplitError("fewer atomic units than folds")

    ordered_units = sorted(
        selected_units,
        key=lambda unit_id: _seeded_order_key(manifest.seed, unit_id, "fold"),
    )
    validation_units: list[list[str]] = [[] for _ in range(fold_count)]
    validation_document_counts = [0] * fold_count
    validation_strata: list[Counter[str]] = [Counter() for _ in range(fold_count)]
    for unit_id in ordered_units:
        unit_documents = manifest_units[unit_id]
        unit_strata = Counter(memberships[document_id].stratum for document_id in unit_documents)
        fold_index = min(
            range(fold_count),
            key=lambda index: (
                validation_document_counts[index],
                sum(
                    validation_strata[index][stratum] * count
                    for stratum, count in unit_strata.items()
                ),
                index,
            ),
        )
        validation_units[fold_index].append(unit_id)
        validation_document_counts[fold_index] += len(unit_documents)
        validation_strata[fold_index].update(unit_strata)

    all_documents = frozenset(selected_documents)
    return tuple(
        Fold(
            index=index,
            train_document_ids=all_documents - validation_documents,
            validation_document_ids=validation_documents,
        )
        for index, unit_ids in enumerate(validation_units)
        for validation_documents in (
            frozenset(
                document_id for unit_id in unit_ids for document_id in manifest_units[unit_id]
            ),
        )
    )
