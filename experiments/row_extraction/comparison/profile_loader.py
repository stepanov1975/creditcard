"""Load the frozen profile factory only from its verified private source snapshot."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol, cast

from pydantic import BaseModel

from experiments.row_extraction.contracts import ArtifactIdentity, FrozenRow
from experiments.row_extraction.runner import MeasuredArmFactory, ResourceSpec

from .cli_manifest import HandoffArtifacts, PinnedArtifact, ProfileSourcePin
from .cli_state import canonical_model_bytes, verified_bytes
from .handoff_contracts import FrozenArmFactoryLoader
from .profile_source import reverify_profile_snapshot


class ProfileSpecBuilder(Protocol):
    """Build the exact resource specification required by a profile factory."""

    def __call__(
        self,
        factory: MeasuredArmFactory,
        *,
        private_root: Path,
        model_inventory_path: Path,
        dependency_inventory_path: Path,
        resource_inventory_output: Path,
    ) -> ResourceSpec: ...


class ProfileFactoryType(Protocol):
    """Construct one fresh measured profile arm from the frozen inputs."""

    def __call__(
        self,
        rows: tuple[FrozenRow, ...],
        config: BaseModel,
        arm_manifest_identity: ArtifactIdentity,
        *,
        row_sequence_identity: ArtifactIdentity,
        runtime_identity: ArtifactIdentity,
        model_inventory_identity: ArtifactIdentity,
        dependency_inventory_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory: ...


class ProfileLoaderError(ValueError):
    """The validated profile snapshot cannot provide the hard-coded factory API."""


def _fail(message: str) -> Never:
    raise ProfileLoaderError(message)


@dataclass(frozen=True)
class ProfileLaneAdapter:
    factory_loader: FrozenArmFactoryLoader
    build_resource_spec: ProfileSpecBuilder
    config_id: str


class ProfileLaneLoader(Protocol):
    """Load the hard-coded profile interface from an authenticated source snapshot."""

    def __call__(
        self,
        source: ProfileSourcePin,
        snapshot_root: Path,
        raw_handoff: PinnedArtifact,
        artifacts: HandoffArtifacts,
    ) -> ProfileLaneAdapter: ...


def _load_symbols(
    snapshot_root: Path,
) -> tuple[type[BaseModel], ProfileFactoryType, ProfileSpecBuilder]:
    prefix = "experiments.row_extraction.arms.profiles"
    if any(name == prefix or name.startswith(f"{prefix}.") for name in sys.modules):
        _fail("profile module was already loaded")
    package_root = snapshot_root / "profiles"
    try:
        from experiments.row_extraction import arms

        search_path = arms.__path__
        source_parent = str(snapshot_root)
        search_path.insert(0, source_parent)
        original_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            freeze = importlib.import_module(f"{prefix}.freeze")
            resources = importlib.import_module(f"{prefix}.resources")
        finally:
            sys.dont_write_bytecode = original_bytecode
            if search_path and search_path[0] == source_parent:
                search_path.pop(0)
    except ProfileLoaderError:
        raise
    except BaseException:
        _fail("profile snapshot import failed")
    loaded = tuple(
        module
        for name, module in sys.modules.items()
        if name == prefix or name.startswith(f"{prefix}.")
    )
    try:
        if not loaded or any(
            not Path(cast(str, module.__file__)).resolve(strict=True).is_relative_to(package_root)
            for module in loaded
        ):
            _fail("profile snapshot import location mismatch")
        handoff_model = cast(type[BaseModel], freeze.FrozenProfileHandoff)
        factory_type = cast(ProfileFactoryType, resources.DeterministicProfileArmFactory)
        builder = cast(ProfileSpecBuilder, resources.build_profile_resource_spec)
    except (AttributeError, OSError, TypeError):
        _fail("profile snapshot interface mismatch")
    return handoff_model, factory_type, builder


def load_profile_lane(
    source: ProfileSourcePin,
    snapshot_root: Path,
    raw_handoff: PinnedArtifact,
    artifacts: HandoffArtifacts,
) -> ProfileLaneAdapter:
    """Build the exact cache-bound loader from one reverified source snapshot."""

    reverify_profile_snapshot(source, snapshot_root)
    handoff_model, factory_type, builder = _load_symbols(snapshot_root)
    raw_payload = verified_bytes(raw_handoff, "profile handoff is invalid")
    try:
        handoff = handoff_model.model_validate_json(raw_payload)
    except (TypeError, ValueError):
        _fail("profile handoff is invalid")
    if raw_payload != canonical_model_bytes(handoff):
        _fail("profile handoff is invalid")
    config = getattr(handoff, "config", None)
    arm_manifest = artifacts.arm_manifest
    if config is None or arm_manifest is None:
        _fail("profile handoff is not frozen eligible")
    config_id = f"row-profiles-v1:{config.version}"

    def load(
        rows: tuple[FrozenRow, ...],
        row_sequence_identity: ArtifactIdentity,
        cache_root: Path,
    ) -> MeasuredArmFactory:
        try:
            value = factory_type(
                rows,
                config,
                arm_manifest.identity,
                row_sequence_identity=row_sequence_identity,
                runtime_identity=artifacts.runtime_identity,
                model_inventory_identity=artifacts.model_inventory.identity,
                dependency_inventory_identity=artifacts.dependency_inventory.identity,
                cache_root=cache_root,
            )
        except BaseException:
            _fail("profile factory construction failed")
        return value

    return ProfileLaneAdapter(
        factory_loader=load,
        build_resource_spec=builder,
        config_id=config_id,
    )


__all__ = [
    "ProfileLaneAdapter",
    "ProfileLaneLoader",
    "ProfileLoaderError",
    "ProfileSpecBuilder",
    "load_profile_lane",
]
