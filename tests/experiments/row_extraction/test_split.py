from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from experiments.row_extraction.contracts import DatasetSplit, FrozenRow
from experiments.row_extraction.split import (
    DocumentGroup,
    DocumentMembership,
    Fold,
    SplitError,
    SplitManifest,
    assign_splits,
    grouped_folds,
    validate_split,
)
from tests.experiments.row_extraction.factories import frozen_row


def _document(index: int) -> str:
    return f"{index:064x}"


def _group(
    index: int,
    *,
    documents: frozenset[str] | None = None,
    duplicate_group: str | None = None,
    layout_group: str | None = None,
    stratum: str = "stratum-a",
) -> DocumentGroup:
    return DocumentGroup(
        document_ids=documents or frozenset({_document(index)}),
        duplicate_group=duplicate_group or f"duplicate-{index}",
        layout_group=layout_group or f"layout-{index}",
        stratum=stratum,
    )


def _membership(
    index: int,
    *,
    split: DatasetSplit = DatasetSplit.TRAIN,
    atomic_unit: str | None = None,
    stratum: str = "stratum-a",
) -> DocumentMembership:
    return DocumentMembership(
        document_id=_document(index),
        split=split,
        atomic_unit=atomic_unit or f"unit-{index}",
        stratum=stratum,
    )


def _manifest(*memberships: DocumentMembership) -> SplitManifest:
    return SplitManifest(
        seed="synthetic-seed",
        version="row-extraction-split-v1",
        memberships=memberships,
    )


def _forged_manifest(
    *memberships: DocumentMembership,
    seed: str = "synthetic-seed",
    version: str = "row-extraction-split-v1",
) -> SplitManifest:
    return SplitManifest.model_construct(
        seed=seed,
        version=version,
        memberships=memberships,
    )


@pytest.mark.parametrize(
    ("overrides", "match"),
    (
        ({"document_ids": frozenset()}, "document_ids"),
        ({"document_ids": frozenset({""})}, "document ID"),
        ({"duplicate_group": ""}, "duplicate_group"),
        ({"layout_group": ""}, "layout_group"),
        ({"stratum": ""}, "stratum"),
    ),
)
def test_document_group_rejects_empty_identity_metadata(
    overrides: dict[str, object],
    match: str,
) -> None:
    values: dict[str, object] = {
        "document_ids": frozenset({_document(1)}),
        "duplicate_group": "duplicate-1",
        "layout_group": "layout-1",
        "stratum": "stratum-a",
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=match):
        DocumentGroup.model_validate(values)


def test_assign_splits_rejects_conflicting_duplicate_document_metadata() -> None:
    document_id = _document(1)
    groups = (
        _group(1, documents=frozenset({document_id})),
        _group(
            2,
            documents=frozenset({document_id}),
            duplicate_group="conflicting-duplicate",
        ),
    )

    with pytest.raises(SplitError, match="conflicting document metadata"):
        assign_splits(groups, seed="synthetic-seed")


def test_assign_splits_rejects_empty_groups_and_seed() -> None:
    with pytest.raises(SplitError, match="at least one document group is required"):
        assign_splits((), seed="synthetic-seed")

    with pytest.raises(SplitError, match="split seed must not be empty"):
        assign_splits((_group(1),), seed="")


def test_assign_splits_builds_transitive_duplicate_and_layout_components() -> None:
    groups = (
        _group(
            1,
            documents=frozenset({_document(1), _document(2)}),
            duplicate_group="duplicate-a",
            layout_group="layout-a",
        ),
        _group(
            3,
            duplicate_group="duplicate-b",
            layout_group="layout-a",
            stratum="stratum-b",
        ),
        _group(
            4,
            duplicate_group="duplicate-b",
            layout_group="layout-c",
            stratum="stratum-b",
        ),
    )

    manifest = assign_splits(groups, seed="synthetic-seed")
    document_ids = frozenset(_document(index) for index in range(1, 5))

    assert len({manifest.split_for(value) for value in document_ids}) == 1
    assert len({manifest.atomic_unit_for(value) for value in document_ids}) == 1
    assert manifest.stratum_for(_document(1)) == "stratum-a"
    assert manifest.stratum_for(_document(4)) == "stratum-b"


def test_assign_splits_hits_ratio_and_stratum_targets_when_units_allow_it() -> None:
    groups = tuple(
        group
        for index in range(1, 6)
        for group in (
            _group(
                index,
                layout_group=f"cross-stratum-family-{index}",
                stratum="stratum-a",
            ),
            _group(
                index + 5,
                layout_group=f"cross-stratum-family-{index}",
                stratum="stratum-b",
            ),
        )
    )

    manifest = assign_splits(groups, seed="synthetic-seed")
    total_counts = Counter(item.split for item in manifest.memberships)
    stratum_counts = {
        stratum: Counter(item.split for item in manifest.memberships if item.stratum == stratum)
        for stratum in ("stratum-a", "stratum-b")
    }

    assert total_counts == {
        DatasetSplit.TRAIN: 6,
        DatasetSplit.VALIDATION: 2,
        DatasetSplit.TEST: 2,
    }
    assert stratum_counts == {
        "stratum-a": {
            DatasetSplit.TRAIN: 3,
            DatasetSplit.VALIDATION: 1,
            DatasetSplit.TEST: 1,
        },
        "stratum-b": {
            DatasetSplit.TRAIN: 3,
            DatasetSplit.VALIDATION: 1,
            DatasetSplit.TEST: 1,
        },
    }


def test_assign_splits_is_canonical_repeatable_and_seeded() -> None:
    groups = tuple(_group(index) for index in range(1, 11))

    first = assign_splits(groups, seed="seed-one")
    repeated = assign_splits(tuple(reversed(groups)), seed="seed-one")
    alternate = assign_splits(groups, seed="seed-two")

    assert first == repeated
    assert {item.document_id: item.split for item in first.memberships} != {
        item.document_id: item.split for item in alternate.memberships
    }


def test_split_manifest_rejects_duplicate_document_membership() -> None:
    with pytest.raises(ValidationError, match="document membership must be unique"):
        _manifest(_membership(1), _membership(1, atomic_unit="another-unit"))


@pytest.mark.parametrize(
    "overrides",
    (
        {"seed": ""},
        {"version": ""},
        {"memberships": ()},
    ),
)
def test_split_manifest_rejects_empty_frozen_metadata(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "seed": "synthetic-seed",
        "version": "row-extraction-split-v1",
        "memberships": (_membership(1),),
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        SplitManifest.model_validate(values)


def test_split_manifest_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError, match="row-extraction-split-v1"):
        SplitManifest.model_validate(
            {
                "seed": "synthetic-seed",
                "version": "row-extraction-split-v2",
                "memberships": (_membership(1),),
            }
        )


def test_split_manifest_rejects_atomic_unit_leakage() -> None:
    with pytest.raises(ValidationError, match="atomic unit cannot span splits"):
        _manifest(
            _membership(1, atomic_unit="shared-unit"),
            _membership(
                2,
                split=DatasetSplit.VALIDATION,
                atomic_unit="shared-unit",
            ),
        )


def test_split_manifest_freezes_seed_version_unit_and_stratum() -> None:
    manifest = _manifest(_membership(1, atomic_unit="shared-unit"))

    assert manifest.seed == "synthetic-seed"
    assert manifest.version == "row-extraction-split-v1"
    assert manifest.split_for(_document(1)) is DatasetSplit.TRAIN
    assert manifest.atomic_unit_for(_document(1)) == "shared-unit"
    assert manifest.stratum_for(_document(1)) == "stratum-a"
    with pytest.raises(ValidationError, match="frozen"):
        manifest.__setattr__("seed", "changed")


def test_split_for_rejects_unknown_document_without_echoing_identity() -> None:
    manifest = _manifest(_membership(1))

    with pytest.raises(SplitError, match=r"^unknown document ID$"):
        manifest.split_for(_document(2))


def test_validate_split_accepts_complete_consistent_rows() -> None:
    manifest = _manifest(
        _membership(1, atomic_unit="shared-unit"),
        _membership(2, atomic_unit="shared-unit"),
        _membership(3, split=DatasetSplit.VALIDATION),
    )
    rows = (
        frozen_row(document_id=_document(1), row_id="row-1"),
        frozen_row(document_id=_document(2), row_id="row-2"),
        frozen_row(
            document_id=_document(3),
            row_id="row-3",
            split=DatasetSplit.VALIDATION,
        ),
    )

    validate_split(rows, manifest)


def test_validate_split_rejects_unknown_and_missing_manifest_documents() -> None:
    manifest = _manifest(_membership(1), _membership(2))

    with pytest.raises(SplitError, match="row document is absent from manifest"):
        validate_split(
            (
                frozen_row(document_id=_document(1), row_id="row-1"),
                frozen_row(document_id=_document(3), row_id="row-3"),
            ),
            manifest,
        )

    with pytest.raises(SplitError, match="manifest document has no row"):
        validate_split(
            (frozen_row(document_id=_document(1), row_id="row-1"),),
            manifest,
        )


def test_validate_split_rejects_row_split_mismatch() -> None:
    manifest = _manifest(_membership(1, split=DatasetSplit.VALIDATION))

    with pytest.raises(SplitError, match="row split differs from manifest"):
        validate_split(
            (frozen_row(document_id=_document(1), row_id="row-1"),),
            manifest,
        )


def test_validate_split_rejects_duplicate_row_identity() -> None:
    manifest = _manifest(_membership(1))
    row = frozen_row(document_id=_document(1), row_id="row-1")

    with pytest.raises(SplitError, match="row identity must be unique"):
        validate_split((row, row), manifest)


def test_validate_split_rejects_manifest_atomic_unit_leakage() -> None:
    memberships = (
        _membership(1, atomic_unit="shared-unit"),
        _membership(
            2,
            split=DatasetSplit.VALIDATION,
            atomic_unit="shared-unit",
        ),
    )
    invalid = SplitManifest.model_construct(
        seed="synthetic-seed",
        version="row-extraction-split-v1",
        memberships=memberships,
    )

    with pytest.raises(SplitError, match="manifest atomic unit spans splits"):
        validate_split(
            (
                frozen_row(document_id=_document(1), row_id="row-1"),
                frozen_row(
                    document_id=_document(2),
                    row_id="row-2",
                    split=DatasetSplit.VALIDATION,
                ),
            ),
            invalid,
        )


def test_public_consumers_reject_forged_empty_manifest_before_rows() -> None:
    invalid = _forged_manifest()

    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        validate_split((), invalid)
    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        grouped_folds((), invalid, fold_count=2)


@pytest.mark.parametrize(
    ("seed", "version"),
    (
        ("", "row-extraction-split-v1"),
        ("synthetic-seed", "row-extraction-split-v2"),
    ),
)
def test_public_consumers_reject_forged_manifest_identity_metadata(
    seed: str,
    version: str,
) -> None:
    memberships = (_membership(1), _membership(2))
    invalid = _forged_manifest(*memberships, seed=seed, version=version)
    rows = (
        frozen_row(document_id=_document(1), row_id="row-1"),
        frozen_row(document_id=_document(2), row_id="row-2"),
    )

    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        validate_split(rows, invalid)
    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        grouped_folds(rows, invalid, fold_count=2)


@pytest.mark.parametrize(
    "overrides",
    (
        {"document_id": ""},
        {"document_id": " "},
        {"atomic_unit": ""},
        {"atomic_unit": " "},
        {"stratum": ""},
        {"stratum": " "},
        {"split": "not-a-split"},
    ),
)
def test_public_consumers_revalidate_forged_membership_contracts(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "document_id": _document(1),
        "split": DatasetSplit.TRAIN,
        "atomic_unit": "unit-1",
        "stratum": "stratum-a",
    }
    values.update(overrides)
    membership = DocumentMembership.model_construct(
        document_id=cast(str, values["document_id"]),
        split=cast(DatasetSplit, values["split"]),
        atomic_unit=cast(str, values["atomic_unit"]),
        stratum=cast(str, values["stratum"]),
    )
    invalid = _forged_manifest(membership)

    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        validate_split((), invalid)
    with pytest.raises(SplitError, match=r"^invalid split manifest$"):
        grouped_folds((), invalid, fold_count=2)


def _training_manifest() -> SplitManifest:
    return _manifest(
        _membership(1, atomic_unit="family-a", stratum="stratum-a"),
        _membership(2, atomic_unit="family-a", stratum="stratum-b"),
        _membership(3, atomic_unit="family-b"),
        _membership(4, atomic_unit="family-c"),
        _membership(5, atomic_unit="family-d"),
    )


def _training_rows() -> tuple[FrozenRow, ...]:
    return tuple(
        frozen_row(document_id=_document(index), row_id=f"row-{index}") for index in range(1, 6)
    )


def test_grouped_folds_use_manifest_units_exactly_once() -> None:
    manifest = _training_manifest()
    rows = _training_rows()

    folds = grouped_folds(rows, manifest, fold_count=3)
    validation_counts = Counter(
        document_id for fold in folds for document_id in fold.validation_document_ids
    )

    assert len(folds) == 3
    assert validation_counts == Counter(row.document_id for row in rows)
    assert all(fold.train_document_ids.isdisjoint(fold.validation_document_ids) for fold in folds)
    assert all(
        {_document(1), _document(2)} <= fold.validation_document_ids
        or {_document(1), _document(2)} <= fold.train_document_ids
        for fold in folds
    )


def test_grouped_folds_are_repeatable_and_canonical() -> None:
    manifest = _training_manifest()
    rows = _training_rows()

    first = grouped_folds(rows, manifest, fold_count=3)
    repeated = grouped_folds(tuple(reversed(rows)), manifest, fold_count=3)

    assert first == repeated
    assert tuple(fold.index for fold in first) == (0, 1, 2)


def test_grouped_folds_reject_unknown_documents() -> None:
    manifest = _training_manifest()

    with pytest.raises(SplitError, match="fold row document is absent from manifest"):
        grouped_folds(
            (frozen_row(document_id=_document(9), row_id="row-9"),),
            manifest,
            fold_count=2,
        )


def test_grouped_folds_reject_empty_rows_and_invalid_fold_count() -> None:
    manifest = _training_manifest()

    with pytest.raises(SplitError, match="at least one training row is required"):
        grouped_folds((), manifest, fold_count=2)

    with pytest.raises(SplitError, match="fold_count must be at least two"):
        grouped_folds(_training_rows(), manifest, fold_count=1)


def test_grouped_folds_reject_nontraining_documents() -> None:
    validation_manifest = _manifest(
        _membership(1, split=DatasetSplit.VALIDATION),
        _membership(2),
    )
    with pytest.raises(SplitError, match="fold rows must be training membership"):
        grouped_folds(
            (
                frozen_row(
                    document_id=_document(1),
                    row_id="row-1",
                    split=DatasetSplit.VALIDATION,
                ),
                frozen_row(document_id=_document(2), row_id="row-2"),
            ),
            validation_manifest,
            fold_count=2,
        )


def test_grouped_folds_reject_duplicate_row_ids() -> None:
    manifest = _training_manifest()

    with pytest.raises(SplitError, match="fold row ID must be unique"):
        grouped_folds(
            (
                frozen_row(document_id=_document(1), row_id="same-row"),
                frozen_row(document_id=_document(2), row_id="same-row"),
                frozen_row(document_id=_document(3), row_id="row-3"),
            ),
            manifest,
            fold_count=2,
        )


def test_grouped_folds_reject_fewer_units_than_folds() -> None:
    manifest = _training_manifest()

    with pytest.raises(SplitError, match="fewer atomic units than folds"):
        grouped_folds(_training_rows(), manifest, fold_count=5)


def test_grouped_folds_reject_partial_atomic_unit_representation() -> None:
    manifest = _training_manifest()
    rows = tuple(row for row in _training_rows() if row.document_id != _document(2))

    with pytest.raises(SplitError, match="atomic unit is only partially represented"):
        grouped_folds(rows, manifest, fold_count=3)


def test_fold_rejects_train_validation_overlap() -> None:
    with pytest.raises(ValidationError, match="fold document sets must be disjoint"):
        Fold(
            index=0,
            train_document_ids=frozenset({_document(1)}),
            validation_document_ids=frozenset({_document(1)}),
        )


@pytest.mark.parametrize(
    ("train", "validation"),
    (
        (frozenset(), frozenset({_document(1)})),
        (frozenset({_document(1)}), frozenset()),
    ),
)
def test_fold_rejects_empty_train_or_validation_membership(
    train: frozenset[str],
    validation: frozenset[str],
) -> None:
    with pytest.raises(ValidationError):
        Fold(
            index=0,
            train_document_ids=train,
            validation_document_ids=validation,
        )


def test_fold_json_is_canonical_across_python_hash_seeds() -> None:
    repository = Path(__file__).parents[3]
    script = """
from experiments.row_extraction.split import Fold

fold = Fold(
    index=2,
    train_document_ids=frozenset({
        "opaque-08", "opaque-02", "opaque-11", "opaque-05",
        "opaque-01", "opaque-09", "opaque-04", "opaque-07",
    }),
    validation_document_ids=frozenset({"opaque-10", "opaque-03", "opaque-06"}),
)
print(fold.model_dump_json())
"""
    outputs = {
        subprocess.run(
            (sys.executable, "-c", script),
            check=True,
            capture_output=True,
            cwd=repository,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(repository)},
            text=True,
        ).stdout.strip()
        for seed in ("1", "2", "17", "101")
    }

    assert outputs == {
        '{"index":2,"train_document_ids":["opaque-01","opaque-02",'
        '"opaque-04","opaque-05","opaque-07","opaque-08","opaque-09",'
        '"opaque-11"],"validation_document_ids":["opaque-03","opaque-06",'
        '"opaque-10"]}'
    }
