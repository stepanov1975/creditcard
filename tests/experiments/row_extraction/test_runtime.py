from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from ccparser import corpus_gate as corpus_gate_module
from ccparser.corpus_gate import (
    RuntimeArtifactIdentity,
    RuntimeDependency,
    ToolchainAsset,
    ToolchainFingerprint,
)
from experiments.row_extraction import runtime as runtime_module
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.report import ReportContext
from experiments.row_extraction.runner import RunMeasurements
from experiments.row_extraction.runtime import (
    RowRuntimeManifest,
    RuntimeContractError,
    capture_runtime,
    report_context_from_runtime,
    runtime_identity,
    verify_runtime,
)


def _identity(value: str, *, artifact_type: str = "resource-inventory") -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=value * 64,
        version="row-resource-inventory-v1",
        byte_size=1,
    )


def _toolchain(*, environment: str = "a") -> ToolchainFingerprint:
    dependencies = tuple(
        RuntimeDependency(
            name=name,
            version="1.0",
            file_count=1,
            size_bytes=1,
            content_digest="f" * 64,
        )
        for name in corpus_gate_module._RUNTIME_DEPENDENCY_NAMES
    )
    assets = tuple(
        ToolchainAsset(role=role, size_bytes=1, sha256="d" * 64)
        for role in corpus_gate_module._TOOLCHAIN_ASSET_ROLES
    )
    artifact = RuntimeArtifactIdentity(file_count=1, size_bytes=1, digest="6" * 64)
    payload: dict[str, object] = {
        "version": 6,
        "python_version": "3.13.5",
        "python_implementation": "CPython",
        "python_runtime_digest": "a" * 64,
        "standard_library": artifact.model_dump(mode="json"),
        "runtime_environment_digest": environment * 64,
        "dependencies": tuple(item.model_dump(mode="json") for item in dependencies),
        "git_executable": ToolchainAsset(
            role="git-executable", size_bytes=1, sha256="e" * 64
        ).model_dump(mode="json"),
        "git_native_closure": artifact.model_dump(mode="json"),
        "native_runtime": artifact.model_dump(mode="json"),
        "pymupdf_binding_version": "1.28.0",
        "pymupdf_engine_version": "1.29.0",
        "tesseract_version": "5.3.4",
        "tesseract_version_output_digest": "b" * 64,
        "tesseract_assets": tuple(item.model_dump(mode="json") for item in assets),
        "tesseract_native_closure": artifact.model_dump(mode="json"),
        "ocr_pipeline_version": "ocr-v1",
        "ocr_cache_versions": ("layout-v1", "text-v1"),
        "command_digest": "c" * 64,
    }
    return ToolchainFingerprint.model_validate(
        {**payload, "digest": corpus_gate_module._toolchain_payload_digest(payload)}
    )


class _Inspector:
    def __init__(self, fingerprint: ToolchainFingerprint) -> None:
        self.value = fingerprint
        self.calls = 0

    def fingerprint(self) -> ToolchainFingerprint:
        self.calls += 1
        return self.value


def _canonical_toolchain_output(toolchain: ToolchainFingerprint) -> bytes:
    return corpus_gate_module._canonical_json_value_bytes(toolchain.model_dump(mode="json"))


def test_clean_process_inspector_uses_fixed_shell_free_candidate_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _toolchain()
    invocation: dict[str, object] = {}

    def run_probe(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        invocation["command"] = command
        invocation.update(kwargs)
        return subprocess.CompletedProcess(command, 0, _canonical_toolchain_output(expected), b"")

    monkeypatch.setattr(runtime_module.subprocess, "run", run_probe)

    actual = runtime_module.CleanProcessToolchainInspector().fingerprint()

    worktree = Path(runtime_module.__file__).resolve().parents[2]
    assert actual == expected
    assert invocation["command"] == (
        sys.executable,
        "-c",
        runtime_module._TOOLCHAIN_PROBE_SOURCE,
    )
    assert invocation["cwd"] == worktree
    assert invocation["check"] is False
    assert invocation["stdin"] is subprocess.DEVNULL
    assert invocation["stdout"] is subprocess.PIPE
    assert invocation["stderr"] is subprocess.DEVNULL
    assert invocation["shell"] is False
    environment = invocation["env"]
    assert isinstance(environment, dict)
    assert environment["PYTHONPATH"] == os.pathsep.join((str(worktree / "src"), str(worktree)))


@pytest.mark.parametrize(
    "completed",
    (
        subprocess.CompletedProcess(("probe",), 1, b"", b"private failure"),
        subprocess.CompletedProcess(("probe",), 0, b"not-json\n", b""),
        subprocess.CompletedProcess(
            ("probe",),
            0,
            _canonical_toolchain_output(_toolchain()).removesuffix(b"\n"),
            b"",
        ),
    ),
)
def test_clean_process_inspector_fails_generically_on_failed_or_noncanonical_probe(
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[bytes],
) -> None:
    monkeypatch.setattr(runtime_module.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(RuntimeError) as failure:
        runtime_module.CleanProcessToolchainInspector().fingerprint()

    assert str(failure.value) == "runtime toolchain is unavailable"
    assert "private failure" not in str(failure.value)


@pytest.mark.parametrize(
    "error",
    (
        OSError("private path"),
        subprocess.TimeoutExpired(("probe",), 1),
    ),
)
def test_clean_process_inspector_fails_generically_when_probe_cannot_complete(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise error

    monkeypatch.setattr(runtime_module.subprocess, "run", unavailable)

    with pytest.raises(RuntimeError) as failure:
        runtime_module.CleanProcessToolchainInspector().fingerprint()

    assert str(failure.value) == "runtime toolchain is unavailable"


def _run(runtime: ArtifactIdentity, dependency: ArtifactIdentity) -> RunMeasurements:
    generic = _identity("8", artifact_type="test")
    return RunMeasurements(
        experiment_id="per-row-ocr",
        config_id="config-v1",
        row_sequence_identity=generic,
        split=DatasetSplit.VALIDATION,
        cache_policy="new-empty-v1",
        resource_basis="end-to-end-method",
        arm_manifest_identity=generic,
        row_count=2,
        total_ns=10,
        p50_ns=4,
        p95_ns=6,
        preparation_ns=0,
        end_to_end_ns=10,
        cold_start_ns=4,
        throughput_rows_per_second=Decimal("200000000"),
        peak_rss_bytes=1,
        model_bytes=0,
        dependency_bytes=1,
        cache_bytes=0,
        subprocess_count=0,
        worker_count=1,
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=runtime,
        model_inventory_identity=generic,
        dependency_inventory_identity=dependency,
        resource_inventory_identity=generic,
        predictions_sha256="9" * 64,
    )


def test_capture_runtime_binds_validated_toolchain_and_dependency_inventory() -> None:
    inspector = _Inspector(_toolchain())
    dependency = _identity("1")

    manifest, identity = capture_runtime(inspector, dependency)

    assert manifest == RowRuntimeManifest(
        version="row-runtime-manifest-v1",
        toolchain=inspector.value,
        dependency_inventory_identity=dependency,
    )
    assert identity == runtime_identity(manifest)
    assert identity.artifact_type == "row-runtime-manifest"
    assert identity.version == "row-runtime-manifest-v1"
    assert inspector.calls == 1


def test_verify_runtime_rejects_environment_or_dependency_change() -> None:
    dependency = _identity("1")
    manifest, identity = capture_runtime(_Inspector(_toolchain()), dependency)

    with pytest.raises(RuntimeContractError, match="toolchain changed"):
        verify_runtime(_Inspector(_toolchain(environment="2")), manifest, identity, dependency)

    with pytest.raises(RuntimeContractError, match="dependency inventory changed"):
        verify_runtime(_Inspector(_toolchain()), manifest, identity, _identity("3"))


def test_verify_runtime_rejects_forged_manifest_identity_before_inspection() -> None:
    dependency = _identity("1")
    manifest, identity = capture_runtime(_Inspector(_toolchain()), dependency)
    forged = identity.model_copy(update={"sha256": "f" * 64})
    inspector = _Inspector(_toolchain())

    with pytest.raises(RuntimeContractError, match="runtime identity mismatch"):
        verify_runtime(inspector, manifest, forged, dependency)

    assert inspector.calls == 0


def test_report_context_is_derived_from_bound_run_and_safe_public_versions() -> None:
    dependency = _identity("1")
    manifest, identity = capture_runtime(_Inspector(_toolchain()), dependency)
    run = _run(identity, dependency)

    context = report_context_from_runtime(run, manifest, identity)

    assert context == ReportContext(
        experiment_id="per-row-ocr",
        config_id="config-v1",
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=identity,
        python_version="3.13.5",
        public_runtime_versions=(
            ("dependency:annotated-doc", "1.0"),
            ("dependency:annotated-types", "1.0"),
            ("dependency:ccparser", "1.0"),
            ("dependency:pydantic", "1.0"),
            ("dependency:pydantic-core", "1.0"),
            ("dependency:pymupdf", "1.0"),
            ("dependency:shellingham", "1.0"),
            ("dependency:typer", "1.0"),
            ("dependency:typing-extensions", "1.0"),
            ("dependency:typing-inspection", "1.0"),
            ("ocr-pipeline", "ocr-v1"),
            ("pymupdf-binding", "1.28.0"),
            ("pymupdf-engine", "1.29.0"),
            ("tesseract", "5.3.4"),
        ),
    )
    serialized = context.model_dump_json()
    assert manifest.toolchain.digest not in serialized
    assert dependency.sha256 not in serialized


@pytest.mark.parametrize("mismatch", ("runtime", "dependency"))
def test_report_context_rejects_run_not_bound_to_manifest(mismatch: str) -> None:
    dependency = _identity("1")
    manifest, identity = capture_runtime(_Inspector(_toolchain()), dependency)
    run = _run(identity, dependency)
    if mismatch == "runtime":
        run = run.model_copy(update={"runtime_identity": _identity("4")})
    else:
        run = run.model_copy(update={"dependency_inventory_identity": _identity("5")})

    with pytest.raises(RuntimeContractError, match="run runtime binding mismatch"):
        report_context_from_runtime(run, manifest, identity)
