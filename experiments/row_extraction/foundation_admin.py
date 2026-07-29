"""Separate privacy-safe administration for the frozen experiment foundation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import BaseModel, ValidationError

from ccparser.corpus_gate import LocalToolchainInspector
from ccparser.output import _canonical_json_value_content
from ccparser.paths import iter_regular_pdf_files
from experiments.row_extraction.codecs import _canonical_record_bytes, read_jsonl
from experiments.row_extraction.contracts import ArtifactIdentity
from experiments.row_extraction.grouping import (
    CandidateRelation,
    DocumentStructureProfile,
    ReviewedGrouping,
    candidate_relations,
    freeze_grouping,
    profile_atlas,
    profile_documents,
)
from experiments.row_extraction.runner import RunMeasurements
from experiments.row_extraction.runtime import (
    RowRuntimeManifest,
    capture_runtime,
    report_context_from_runtime,
    runtime_identity,
)
from experiments.row_extraction.runtime import (
    verify_runtime as verify_runtime_binding,
)

_WORKTREE = Path(__file__).resolve().parents[2]

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Profile, review, freeze, and bind the private row-experiment foundation.",
)


class FoundationAdminError(ValueError):
    """A foundation administration command cannot safely complete."""


def _abort(command: str) -> Never:
    typer.echo(f"status=error command={command}", err=True)
    raise typer.Exit(code=1) from None


def _run_safely(command: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        _abort(command)


def _is_ignored_or_external(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(_WORKTREE):
        return True
    completed = subprocess.run(
        ("git", "check-ignore", "--quiet", str(resolved)),
        cwd=_WORKTREE,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _private_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise FoundationAdminError("invalid private root")
    resolved = path.resolve(strict=True)
    if not _is_ignored_or_external(resolved):
        raise FoundationAdminError("private root is not ignored")
    return resolved


def _beneath(path: Path, root: Path) -> Path:
    if not path.is_absolute():
        raise FoundationAdminError("private path must be absolute")
    resolved = path.resolve(strict=False)
    if resolved == root or not resolved.is_relative_to(root):
        raise FoundationAdminError("private path escapes root")
    return resolved


def _input_file(path: Path, root: Path) -> Path:
    resolved = _beneath(path, root)
    if path.is_symlink() or not resolved.is_file():
        raise FoundationAdminError("private input is invalid")
    return resolved.resolve(strict=True)


def _input_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise FoundationAdminError("private input directory is invalid")
    resolved = path.resolve(strict=True)
    if not _is_ignored_or_external(resolved):
        raise FoundationAdminError("private input directory is not ignored")
    return resolved


def _new_file(path: Path, root: Path) -> Path:
    resolved = _beneath(path, root)
    if resolved.exists() or not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise FoundationAdminError("output file must be new")
    return resolved


def _new_directory(path: Path, root: Path) -> Path:
    resolved = _beneath(path, root)
    if resolved.exists() or not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise FoundationAdminError("output directory must be new")
    return resolved


def _canonical_model_bytes(model: BaseModel) -> bytes:
    return _canonical_json_value_content(model.model_dump(mode="json")) + b"\n"


@dataclass(frozen=True, slots=True)
class _InodeIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    identity: _InodeIdentity
    mode: int
    byte_size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _ContentIdentity:
    byte_size: int
    sha256: str


def _inode_identity(path: Path) -> _InodeIdentity:
    value = path.stat(follow_symlinks=False)
    return _InodeIdentity(value.st_dev, value.st_ino)


def _file_snapshot(path: Path) -> _FileSnapshot:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise FoundationAdminError("artifact is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    before_stability = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_stability = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_stability != after_stability:
        raise FoundationAdminError("artifact changed during verification")
    return _FileSnapshot(
        identity=_InodeIdentity(after.st_dev, after.st_ino),
        mode=after.st_mode,
        byte_size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def _unlink_owned(path: Path, identity: _InodeIdentity) -> None:
    try:
        current = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError:
        return
    if (
        not stat.S_ISREG(current.st_mode)
        or _InodeIdentity(current.st_dev, current.st_ino) != identity
    ):
        return
    try:
        path.unlink()
    except OSError:
        return


def _publish_batch(artifacts: Sequence[tuple[Path, bytes]]) -> None:
    """Publish all new files or roll back only links owned by this call."""

    if not artifacts:
        raise FoundationAdminError("publication batch is empty")
    prepared = tuple(
        (
            path,
            content,
            _ContentIdentity(
                byte_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            ),
        )
        for path, content in artifacts
    )
    destinations = tuple(path for path, _content, _identity in prepared)
    _require_distinct(destinations)
    staged: list[tuple[Path, _FileSnapshot, Path]] = []
    owned_staging: list[tuple[Path, _InodeIdentity]] = []
    try:
        for destination, content, content_identity in prepared:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                staging = Path(output.name)
                owned_staging.append((staging, _inode_identity(staging)))
                output.write(content)
            snapshot = _file_snapshot(staging)
            if (
                snapshot.byte_size != content_identity.byte_size
                or snapshot.sha256 != content_identity.sha256
            ):
                raise FoundationAdminError("staged artifact content changed")
            staged.append((staging, snapshot, destination))
        for staging, expected, destination in staged:
            if _file_snapshot(staging) != expected:
                raise FoundationAdminError("staged artifact changed")
            os.link(staging, destination)
            if _file_snapshot(staging) != expected or _file_snapshot(destination) != expected:
                raise FoundationAdminError("published artifact identity changed")
        if any(
            _file_snapshot(staging) != expected or _file_snapshot(destination) != expected
            for staging, expected, destination in staged
        ):
            raise FoundationAdminError("published artifact identity changed")
    except BaseException:
        for _staging, expected, destination in reversed(staged):
            _unlink_owned(destination, expected.identity)
        raise FoundationAdminError("artifact batch publication failed") from None
    finally:
        for staging, identity in owned_staging:
            _unlink_owned(staging, identity)


def _create_owned_directory(path: Path) -> _InodeIdentity:
    try:
        path.mkdir()
        value = path.stat(follow_symlinks=False)
    except OSError:
        raise FoundationAdminError("private directory cannot be created") from None
    if not stat.S_ISDIR(value.st_mode):
        raise FoundationAdminError("private directory ownership changed")
    return _InodeIdentity(value.st_dev, value.st_ino)


def _remove_owned_directory(path: Path, identity: _InodeIdentity) -> None:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError:
        return
    if (
        not stat.S_ISDIR(value.st_mode)
        or path.is_symlink()
        or _InodeIdentity(value.st_dev, value.st_ino) != identity
    ):
        return
    try:
        shutil.rmtree(path)
    except OSError:
        return


def _read_model[Model: BaseModel](path: Path, model: type[Model]) -> Model:
    try:
        payload = path.read_bytes()
        value = model.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        raise FoundationAdminError("private model is invalid") from None
    if payload != _canonical_model_bytes(value):
        raise FoundationAdminError("private model is not canonical")
    return value


def _stream_identity(path: Path) -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            byte_size += len(block)
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=digest.hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=byte_size,
    )


def _records_bytes(records: Iterable[BaseModel]) -> bytes:
    return b"".join(_canonical_record_bytes(record) for record in records)


def _jsonl_identity(content: bytes) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=hashlib.sha256(content).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(content),
    )


def _read_jsonl_exact[Model: BaseModel](
    path: Path,
    model: type[Model],
    *,
    allow_empty: bool = False,
) -> tuple[Model, ...]:
    try:
        values = tuple(read_jsonl(path, model))
        expected = b"".join(_canonical_record_bytes(value) for value in values)
        actual = path.read_bytes()
    except (OSError, ValidationError, ValueError):
        raise FoundationAdminError("private record stream is invalid") from None
    if (not values and not allow_empty) or expected != actual:
        raise FoundationAdminError("private record stream is not canonical")
    return values


def _model_identity(model: BaseModel, *, artifact_type: str, version: str) -> ArtifactIdentity:
    content = _canonical_model_bytes(model)
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=hashlib.sha256(content).hexdigest(),
        version=version,
        byte_size=len(content),
    )


def _require_distinct(paths: Iterable[Path]) -> None:
    values = tuple(paths)
    if len(values) != len(set(values)):
        raise FoundationAdminError("private paths must be distinct")


def _profile_groups(
    *,
    private_root: Path,
    documents: Path,
    cache_dir: Path,
    profiles_output: Path,
    profiles_identity_output: Path,
    proposals_output: Path,
    proposals_identity_output: Path,
    atlas_output: Path,
    atlas_identity_output: Path,
) -> None:
    root = _private_root(private_root)
    document_root = _input_directory(documents)
    cache = _new_directory(cache_dir, root)
    outputs = tuple(
        _new_file(value, root)
        for value in (
            profiles_output,
            profiles_identity_output,
            proposals_output,
            proposals_identity_output,
            atlas_output,
            atlas_identity_output,
        )
    )
    _require_distinct((cache, *outputs))
    if any(value.is_relative_to(cache) for value in outputs):
        raise FoundationAdminError("profile output overlaps cache")
    sources = iter_regular_pdf_files(document_root)
    cache_identity = _create_owned_directory(cache)
    try:
        profiles = profile_documents(sources, cache)
        proposals = candidate_relations(profiles)
        profile_content = _records_bytes(profiles)
        proposal_content = _records_bytes(proposals)
        atlas_content, atlas_identity = profile_atlas(profiles)
        profile_identity = _jsonl_identity(profile_content)
        proposal_identity = _jsonl_identity(proposal_content)
        _publish_batch(
            (
                (outputs[0], profile_content),
                (outputs[1], _canonical_model_bytes(profile_identity)),
                (outputs[2], proposal_content),
                (outputs[3], _canonical_model_bytes(proposal_identity)),
                (outputs[4], atlas_content),
                (outputs[5], _canonical_model_bytes(atlas_identity)),
            )
        )
    except BaseException:
        _remove_owned_directory(cache, cache_identity)
        raise
    typer.echo("status=ok command=profile-groups")


@app.command("profile-groups")
def profile_groups_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    documents: Annotated[Path, typer.Option("--documents")],
    cache_dir: Annotated[Path, typer.Option("--cache-dir")],
    profiles_output: Annotated[Path, typer.Option("--profiles-output")],
    profiles_identity_output: Annotated[Path, typer.Option("--profiles-identity-output")],
    proposals_output: Annotated[Path, typer.Option("--proposals-output")],
    proposals_identity_output: Annotated[Path, typer.Option("--proposals-identity-output")],
    atlas_output: Annotated[Path, typer.Option("--atlas-output")],
    atlas_identity_output: Annotated[Path, typer.Option("--atlas-identity-output")],
) -> None:
    """Create content-neutral profiles and exact-match review proposals."""

    _run_safely(
        "profile-groups",
        lambda: _profile_groups(
            private_root=private_root,
            documents=documents,
            cache_dir=cache_dir,
            profiles_output=profiles_output,
            profiles_identity_output=profiles_identity_output,
            proposals_output=proposals_output,
            proposals_identity_output=proposals_identity_output,
            atlas_output=atlas_output,
            atlas_identity_output=atlas_identity_output,
        ),
    )


def _freeze_groups(
    *,
    private_root: Path,
    profiles: Path,
    proposals: Path,
    reviewed_grouping: Path,
    seed: str,
    groups_output: Path,
    groups_identity_output: Path,
    split_output: Path,
    split_identity_output: Path,
) -> None:
    root = _private_root(private_root)
    profile_path = _input_file(profiles, root)
    proposal_path = _input_file(proposals, root)
    reviewed_path = _input_file(reviewed_grouping, root)
    outputs = tuple(
        _new_file(value, root)
        for value in (
            groups_output,
            groups_identity_output,
            split_output,
            split_identity_output,
        )
    )
    _require_distinct((profile_path, proposal_path, reviewed_path, *outputs))
    profile_records = _read_jsonl_exact(profile_path, DocumentStructureProfile)
    proposal_records = _read_jsonl_exact(
        proposal_path,
        CandidateRelation,
        allow_empty=True,
    )
    reviewed = _read_model(reviewed_path, ReviewedGrouping)
    groups, manifest = freeze_grouping(
        profile_records,
        proposal_records,
        reviewed,
        profile_identity=_stream_identity(profile_path),
        proposal_identity=_stream_identity(proposal_path),
        seed=seed,
    )
    groups_content = _records_bytes(groups)
    groups_identity = _jsonl_identity(groups_content)
    split_identity = _model_identity(
        manifest,
        artifact_type="row-split-manifest",
        version="row-extraction-split-v1",
    )
    _publish_batch(
        (
            (outputs[0], groups_content),
            (outputs[1], _canonical_model_bytes(groups_identity)),
            (outputs[2], _canonical_model_bytes(manifest)),
            (outputs[3], _canonical_model_bytes(split_identity)),
        )
    )
    typer.echo("status=ok command=freeze-groups")


@app.command("freeze-groups")
def freeze_groups_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    profiles: Annotated[Path, typer.Option("--profiles")],
    proposals: Annotated[Path, typer.Option("--proposals")],
    reviewed_grouping: Annotated[Path, typer.Option("--reviewed-grouping")],
    seed: Annotated[str, typer.Option("--seed")],
    groups_output: Annotated[Path, typer.Option("--groups-output")],
    groups_identity_output: Annotated[Path, typer.Option("--groups-identity-output")],
    split_output: Annotated[Path, typer.Option("--split-output")],
    split_identity_output: Annotated[Path, typer.Option("--split-identity-output")],
) -> None:
    """Freeze two-review partitions and deterministically assign document splits."""

    _run_safely(
        "freeze-groups",
        lambda: _freeze_groups(
            private_root=private_root,
            profiles=profiles,
            proposals=proposals,
            reviewed_grouping=reviewed_grouping,
            seed=seed,
            groups_output=groups_output,
            groups_identity_output=groups_identity_output,
            split_output=split_output,
            split_identity_output=split_identity_output,
        ),
    )


def _prepare_runtime(
    *,
    private_root: Path,
    dependency_inventory_identity: Path,
    output: Path,
    identity_output: Path,
) -> None:
    root = _private_root(private_root)
    dependency_path = _input_file(dependency_inventory_identity, root)
    runtime_output = _new_file(output, root)
    identity_path = _new_file(identity_output, root)
    _require_distinct((dependency_path, runtime_output, identity_path))
    dependency = _read_model(dependency_path, ArtifactIdentity)
    inspector = LocalToolchainInspector()
    try:
        manifest, identity = capture_runtime(inspector, dependency)
    finally:
        inspector.close()
    _publish_batch(
        (
            (runtime_output, _canonical_model_bytes(manifest)),
            (identity_path, _canonical_model_bytes(identity)),
        )
    )
    typer.echo("status=ok command=prepare-runtime")


@app.command("prepare-runtime")
def prepare_runtime_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    dependency_inventory_identity: Annotated[Path, typer.Option("--dependency-inventory-identity")],
    output: Annotated[Path, typer.Option("--output")],
    identity_output: Annotated[Path, typer.Option("--identity-output")],
) -> None:
    """Capture the complete parser/OCR runtime through ToolchainInspector."""

    _run_safely(
        "prepare-runtime",
        lambda: _prepare_runtime(
            private_root=private_root,
            dependency_inventory_identity=dependency_inventory_identity,
            output=output,
            identity_output=identity_output,
        ),
    )


def _verify_runtime(
    *,
    private_root: Path,
    manifest: Path,
    identity: Path,
    dependency_inventory_identity: Path,
) -> None:
    root = _private_root(private_root)
    manifest_record = _read_model(_input_file(manifest, root), RowRuntimeManifest)
    identity_record = _read_model(_input_file(identity, root), ArtifactIdentity)
    dependency_record = _read_model(
        _input_file(dependency_inventory_identity, root), ArtifactIdentity
    )
    inspector = LocalToolchainInspector()
    try:
        verify_runtime_binding(
            inspector,
            manifest_record,
            identity_record,
            dependency_record,
        )
    finally:
        inspector.close()
    typer.echo("status=ok command=verify-runtime")


@app.command("verify-runtime")
def verify_runtime_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    manifest: Annotated[Path, typer.Option("--manifest")],
    identity: Annotated[Path, typer.Option("--identity")],
    dependency_inventory_identity: Annotated[Path, typer.Option("--dependency-inventory-identity")],
) -> None:
    """Fail if the complete runtime differs from its captured manifest."""

    _run_safely(
        "verify-runtime",
        lambda: _verify_runtime(
            private_root=private_root,
            manifest=manifest,
            identity=identity,
            dependency_inventory_identity=dependency_inventory_identity,
        ),
    )


def _prepare_report_context(
    *,
    private_root: Path,
    run: Path,
    runtime_manifest: Path,
    runtime_identity_path: Path,
    output: Path,
) -> None:
    root = _private_root(private_root)
    run_record = _read_model(_input_file(run, root), RunMeasurements)
    manifest_record = _read_model(_input_file(runtime_manifest, root), RowRuntimeManifest)
    identity_record = _read_model(_input_file(runtime_identity_path, root), ArtifactIdentity)
    output_path = _new_file(output, root)
    if runtime_identity(manifest_record) != identity_record:
        raise FoundationAdminError("runtime manifest identity mismatch")
    context = report_context_from_runtime(run_record, manifest_record, identity_record)
    _publish_batch(((output_path, _canonical_model_bytes(context)),))
    typer.echo("status=ok command=prepare-report-context")


@app.command("prepare-report-context")
def prepare_report_context_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    run: Annotated[Path, typer.Option("--run")],
    runtime_manifest: Annotated[Path, typer.Option("--runtime-manifest")],
    runtime_identity_path: Annotated[Path, typer.Option("--runtime-identity")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Derive a report context from a measured run and its bound runtime."""

    _run_safely(
        "prepare-report-context",
        lambda: _prepare_report_context(
            private_root=private_root,
            run=run,
            runtime_manifest=runtime_manifest,
            runtime_identity_path=runtime_identity_path,
            output=output,
        ),
    )


if __name__ == "__main__":
    app()


__all__ = ["FoundationAdminError", "app"]
