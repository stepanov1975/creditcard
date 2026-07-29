"""Identity-bound frozen-arm replay for central handoff validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    FrozenRow,
    RowPrediction,
)

from .artifact_validation import file_content
from .handoff_contracts import (
    BaselineHandoff,
    FrozenRunInputs,
    HandoffError,
    LaneHandoff,
    RowKey,
)

type RunnableHandoff = BaselineHandoff | LaneHandoff


def _factory_property(factory: object, name: str) -> object:
    try:
        return getattr(factory, name)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        raise HandoffError("frozen factory identity mismatch") from None


def validate_factory_replay(
    handoff: RunnableHandoff,
    rows: tuple[FrozenRow, ...],
    rows_identity: ArtifactIdentity,
    prediction_identity: ArtifactIdentity,
) -> FrozenRunInputs:
    """Rebuild one arm and require byte-identical validation predictions."""

    frozen_arm = handoff.frozen_arm
    if frozen_arm is None:
        raise HandoffError("eligible lane requires frozen run inputs")
    replay_cache_root = frozen_arm.validation_replay_cache_root
    if (
        not isinstance(replay_cache_root, Path)
        or not replay_cache_root.is_absolute()
        or replay_cache_root.exists()
        or replay_cache_root.is_symlink()
    ):
        raise HandoffError("validation replay cache must be new")
    file_content(frozen_arm.arm_manifest, "frozen arm manifest")
    try:
        factory = frozen_arm.factory_loader(
            rows,
            rows_identity,
            replay_cache_root,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        raise HandoffError("frozen factory loader failed") from None
    resource_basis = (
        "materialized-adapter"
        if handoff.experiment_id == "accepted-baseline"
        else "end-to-end-method"
    )
    actual = (
        _factory_property(factory, "experiment_id"),
        _factory_property(factory, "config_id"),
        _factory_property(factory, "row_sequence_identity"),
        _factory_property(factory, "expected_row_count"),
        _factory_property(factory, "split"),
        _factory_property(factory, "arm_manifest_identity"),
        _factory_property(factory, "runtime_identity"),
        _factory_property(factory, "model_inventory_identity"),
        _factory_property(factory, "dependency_inventory_identity"),
        _factory_property(factory, "worker_count"),
        _factory_property(factory, "resource_basis"),
        _factory_property(factory, "cache_root"),
    )
    expected = (
        handoff.experiment_id,
        handoff.config_id,
        rows_identity,
        len(rows),
        DatasetSplit.VALIDATION,
        frozen_arm.arm_manifest.identity,
        handoff.runtime_identity,
        handoff.model_inventory.identity,
        handoff.dependency_inventory.identity,
        1,
        resource_basis,
        replay_cache_root,
    )
    if actual != expected:
        raise HandoffError("frozen factory identity mismatch")
    try:
        arm = factory.build()
        digest = hashlib.sha256()
        byte_size = 0
        replay_keys: list[RowKey] = []
        for row in rows:
            prediction = RowPrediction.model_validate(arm.predict(row).model_dump(mode="python"))
            if (
                prediction.experiment_id != handoff.experiment_id
                or prediction.config_id != handoff.config_id
            ):
                raise HandoffError("validation prediction replay mismatch")
            replay_keys.append((prediction.document_id, prediction.row_id))
            content = _canonical_record_bytes(prediction)
            digest.update(content)
            byte_size += len(content)
    except HandoffError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValidationError, ValueError):
        raise HandoffError("validation prediction replay mismatch") from None
    if (
        len(replay_keys) != len(set(replay_keys))
        or digest.hexdigest() != prediction_identity.sha256
        or byte_size != prediction_identity.byte_size
    ):
        raise HandoffError("validation prediction replay mismatch")
    return FrozenRunInputs(
        experiment_id=handoff.experiment_id,
        config_id=handoff.config_id,
        arm_manifest=frozen_arm.arm_manifest.identity,
        runtime_identity=handoff.runtime_identity,
        model_inventory=handoff.model_inventory.identity,
        dependency_inventory=handoff.dependency_inventory.identity,
        worker_count=1,
        factory_loader=frozen_arm.factory_loader,
        arm_manifest_path=frozen_arm.arm_manifest.path,
        model_inventory_path=handoff.model_inventory.path,
        dependency_inventory_path=handoff.dependency_inventory.path,
    )


__all__ = ["validate_factory_replay"]
