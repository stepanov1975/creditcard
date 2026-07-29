"""Self-authenticating runtime manifests for comparable row experiments."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ccparser.corpus_gate import ToolchainFingerprint, ToolchainInspector
from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel
from experiments.row_extraction.report import ReportContext
from experiments.row_extraction.runner import RunMeasurements

_RUNTIME_VERSION: Literal["row-runtime-manifest-v1"] = "row-runtime-manifest-v1"
_WORKTREE = Path(__file__).resolve().parents[2]
_TOOLCHAIN_PROBE_TIMEOUT_SECONDS = 300.0
_TOOLCHAIN_PROBE_SOURCE = """\
import sys

from ccparser.corpus_gate import LocalToolchainInspector
from ccparser.output import _canonical_json_value_content

inspector = LocalToolchainInspector()
try:
    fingerprint = inspector.fingerprint()
    sys.stdout.buffer.write(
        _canonical_json_value_content(fingerprint.model_dump(mode="json")) + b"\\n"
    )
finally:
    inspector.close()
"""


class RuntimeContractError(ValueError):
    """Runtime evidence does not bind to the measured extraction run."""


class CleanProcessToolchainInspector:
    """Run the production inspector before experiment modules enter the child process."""

    def fingerprint(self) -> ToolchainFingerprint:
        """Return the canonical, typed fingerprint emitted by a clean child process."""

        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(_WORKTREE / "src"), str(_WORKTREE)))
        try:
            completed = subprocess.run(
                (sys.executable, "-c", _TOOLCHAIN_PROBE_SOURCE),
                cwd=_WORKTREE,
                check=False,
                env=environment,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=_TOOLCHAIN_PROBE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("runtime toolchain is unavailable") from None
        if completed.returncode != 0:
            raise RuntimeError("runtime toolchain is unavailable")
        try:
            fingerprint = ToolchainFingerprint.model_validate_json(completed.stdout)
            canonical = _canonical_json_value_content(fingerprint.model_dump(mode="json")) + b"\n"
        except (TypeError, ValidationError, ValueError):
            raise RuntimeError("runtime toolchain is unavailable") from None
        if completed.stdout != canonical:
            raise RuntimeError("runtime toolchain is unavailable")
        return fingerprint

    def close(self) -> None:
        """Close the inspector; each probe already owns and closes its child resources."""


class RowRuntimeManifest(_FrozenModel):
    version: Literal["row-runtime-manifest-v1"]
    toolchain: ToolchainFingerprint
    dependency_inventory_identity: ArtifactIdentity


def _manifest_bytes(manifest: RowRuntimeManifest) -> bytes:
    return _canonical_json_value_content(manifest.model_dump(mode="json")) + b"\n"


def runtime_identity(manifest: RowRuntimeManifest) -> ArtifactIdentity:
    """Identify the exact canonical runtime manifest consumed by all arms."""

    try:
        validated = RowRuntimeManifest.model_validate(manifest.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuntimeContractError("invalid runtime manifest") from None
    content = _manifest_bytes(validated)
    return ArtifactIdentity(
        artifact_type="row-runtime-manifest",
        sha256=hashlib.sha256(content).hexdigest(),
        version=_RUNTIME_VERSION,
        byte_size=len(content),
    )


def _validated_dependency(identity: ArtifactIdentity) -> ArtifactIdentity:
    try:
        validated = ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuntimeContractError("invalid dependency inventory identity") from None
    if (
        validated.artifact_type != "resource-inventory"
        or validated.version != "row-resource-inventory-v1"
    ):
        raise RuntimeContractError("invalid dependency inventory identity")
    return validated


def capture_runtime(
    inspector: ToolchainInspector,
    dependency_inventory_identity: ArtifactIdentity,
) -> tuple[RowRuntimeManifest, ArtifactIdentity]:
    """Capture one complete production toolchain fingerprint through its public seam."""

    dependency = _validated_dependency(dependency_inventory_identity)
    try:
        inspected = inspector.fingerprint()
        toolchain = ToolchainFingerprint.model_validate(inspected.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError, RuntimeError):
        raise RuntimeContractError("runtime toolchain is unavailable") from None
    manifest = RowRuntimeManifest(
        version=_RUNTIME_VERSION,
        toolchain=toolchain,
        dependency_inventory_identity=dependency,
    )
    return manifest, runtime_identity(manifest)


def verify_runtime(
    inspector: ToolchainInspector,
    manifest: RowRuntimeManifest,
    identity: ArtifactIdentity,
    dependency_inventory_identity: ArtifactIdentity,
) -> None:
    """Reinspect and reject any change from the previously captured runtime."""

    try:
        validated_manifest = RowRuntimeManifest.model_validate(manifest.model_dump(mode="python"))
        validated_identity = ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuntimeContractError("invalid runtime verification input") from None
    if runtime_identity(validated_manifest) != validated_identity:
        raise RuntimeContractError("runtime identity mismatch")
    dependency = _validated_dependency(dependency_inventory_identity)
    if dependency != validated_manifest.dependency_inventory_identity:
        raise RuntimeContractError("dependency inventory changed")
    try:
        current = ToolchainFingerprint.model_validate(
            inspector.fingerprint().model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValidationError, ValueError, RuntimeError):
        raise RuntimeContractError("runtime toolchain is unavailable") from None
    if current != validated_manifest.toolchain:
        raise RuntimeContractError("toolchain changed")


def report_context_from_runtime(
    run: RunMeasurements,
    manifest: RowRuntimeManifest,
    identity: ArtifactIdentity,
) -> ReportContext:
    """Derive report metadata instead of accepting user-authored run identifiers."""

    try:
        run = RunMeasurements.model_validate(run.model_dump(mode="python"))
        manifest = RowRuntimeManifest.model_validate(manifest.model_dump(mode="python"))
        identity = ArtifactIdentity.model_validate(identity.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuntimeContractError("invalid report runtime input") from None
    if (
        runtime_identity(manifest) != identity
        or run.runtime_identity != identity
        or run.dependency_inventory_identity != manifest.dependency_inventory_identity
    ):
        raise RuntimeContractError("run runtime binding mismatch")
    toolchain = manifest.toolchain
    versions = tuple(
        sorted(
            (
                *(
                    (f"dependency:{dependency.name}", dependency.version)
                    for dependency in toolchain.dependencies
                ),
                ("ocr-pipeline", toolchain.ocr_pipeline_version),
                ("pymupdf-binding", toolchain.pymupdf_binding_version),
                ("pymupdf-engine", toolchain.pymupdf_engine_version),
                ("tesseract", toolchain.tesseract_version),
            )
        )
    )
    return ReportContext(
        experiment_id=run.experiment_id,
        config_id=run.config_id,
        measurement_protocol=run.measurement_protocol,
        runtime_identity=identity,
        python_version=toolchain.python_version,
        public_runtime_versions=versions,
    )


__all__ = [
    "CleanProcessToolchainInspector",
    "RowRuntimeManifest",
    "RuntimeContractError",
    "capture_runtime",
    "report_context_from_runtime",
    "runtime_identity",
    "verify_runtime",
]
