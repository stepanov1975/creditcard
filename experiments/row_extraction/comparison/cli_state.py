"""Fail-closed filesystem, Git, and canonical-artifact controller primitives."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Never, Protocol

from pydantic import BaseModel, ValidationError

from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.contracts import ArtifactIdentity

_WORKTREE = Path(__file__).resolve().parents[3]


class ControllerStateError(ValueError):
    """The controller cannot advance without weakening exactly-once state."""


class PinnedArtifactLike(Protocol):
    """Structural input required by an identity-bound file read."""

    path: Path
    identity: ArtifactIdentity


class GitCheckoutPinLike(Protocol):
    """Structural input required by Git checkout verification."""

    root: Path
    commit_sha: str


def _fail(message: str) -> Never:
    raise ControllerStateError(message)


def canonical_model_bytes(model: BaseModel) -> bytes:
    """Return the repository canonical one-record JSON representation."""

    return _canonical_json_value_content(model.model_dump(mode="json")) + b"\n"


def identity_for_bytes(
    payload: bytes,
    *,
    artifact_type: str,
    version: str,
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        version=version,
        byte_size=len(payload),
    )


def _regular_file(path: Path, message: str) -> os.stat_result:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError:
        _fail(message)
    if path.is_symlink() or not stat.S_ISREG(value.st_mode):
        _fail(message)
    return value


def stable_regular_bytes(path: Path, message: str) -> bytes:
    """Read a non-symlink regular file whose identity stays stable during the read."""

    before = _regular_file(path, message)
    try:
        payload = path.read_bytes()
    except OSError:
        _fail(message)
    after = _regular_file(path, message)
    before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_key != after_key:
        _fail(message)
    return payload


def verified_bytes(artifact: PinnedArtifactLike, message: str) -> bytes:
    """Read one pinned regular file once and require stable exact bytes."""

    payload = stable_regular_bytes(artifact.path, message)
    actual = identity_for_bytes(
        payload,
        artifact_type=artifact.identity.artifact_type,
        version=artifact.identity.version,
    )
    if actual != artifact.identity:
        _fail(message)
    return payload


def read_pinned_model[Model: BaseModel](
    artifact: PinnedArtifactLike,
    model: type[Model],
    message: str,
) -> Model:
    payload = verified_bytes(artifact, message)
    try:
        value = model.model_validate_json(payload)
    except (ValidationError, ValueError):
        _fail(message)
    if payload != canonical_model_bytes(value):
        _fail(message)
    return value


def write_bytes_exclusive(path: Path, payload: bytes) -> None:
    """Publish bytes once without an overwrite or symlink-following window."""

    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            output.write(payload)
    except FileExistsError:
        _fail("output already exists")
    except OSError:
        _fail("output publication failed")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_model_exclusive(path: Path, model: BaseModel) -> ArtifactIdentity:
    payload = canonical_model_bytes(model)
    write_bytes_exclusive(path, payload)
    return identity_for_bytes(
        payload,
        artifact_type="row-comparison-controller-json",
        version="row-comparison-controller-v1",
    )


def write_identified_model(
    path: Path,
    model: BaseModel,
    *,
    artifact_type: str,
    version: str,
) -> ArtifactIdentity:
    """Publish one canonical model and its canonical identity sidecar exactly once."""

    payload = canonical_model_bytes(model)
    write_bytes_exclusive(path, payload)
    identity = identity_for_bytes(
        payload,
        artifact_type=artifact_type,
        version=version,
    )
    write_bytes_exclusive(
        path.with_suffix(f"{path.suffix}.identity"),
        canonical_model_bytes(identity),
    )
    return identity


def create_stage(workspace: Path, name: str) -> Path:
    """Create one irreversible stage directory beneath an existing workspace."""

    if not name or "/" in name or name in {".", ".."}:
        _fail("invalid stage name")
    stage = workspace / name
    try:
        stage.mkdir(mode=0o700)
    except FileExistsError:
        _fail("stage already exists")
    except OSError:
        _fail("stage creation failed")
    return stage


def verify_git_checkout(pin: GitCheckoutPinLike) -> None:
    """Require an exact commit and a completely clean worktree."""

    try:
        root_stat = pin.root.stat(follow_symlinks=False)
        if pin.root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
            _fail("checkout is unavailable")
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=pin.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ("git", "status", "--porcelain=v1", "--untracked-files=all"),
            cwd=pin.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except ControllerStateError:
        raise
    except (OSError, subprocess.SubprocessError):
        _fail("checkout verification failed")
    if head != pin.commit_sha:
        _fail("checkout commit mismatch")
    if status:
        _fail("checkout is dirty")


def verify_git_tree(pin: GitCheckoutPinLike, relative: Path, expected_sha: str) -> None:
    """Require one package directory to be the exact pinned Git tree object."""

    if relative.is_absolute() or ".." in relative.parts:
        _fail("package tree path is invalid")
    verify_git_checkout(pin)
    try:
        actual = subprocess.run(
            ("git", "rev-parse", f"{pin.commit_sha}:{relative.as_posix()}"),
            cwd=pin.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        _fail("package tree verification failed")
    if actual != expected_sha:
        _fail("package tree identity mismatch")


def require_private_root(path: Path) -> None:
    """Require an existing ignored or external non-symlink private directory."""

    try:
        value = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISDIR(value.st_mode):
            _fail("private root is invalid")
        resolved = path.resolve(strict=True)
    except ControllerStateError:
        raise
    except OSError:
        _fail("private root is invalid")
    if not resolved.is_relative_to(_WORKTREE):
        return
    try:
        result = subprocess.run(
            ("git", "check-ignore", "--quiet", os.fspath(resolved)),
            cwd=_WORKTREE,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        _fail("private root verification failed")
    if result.returncode != 0:
        _fail("private root is not ignored")


__all__ = [
    "ControllerStateError",
    "canonical_model_bytes",
    "create_stage",
    "identity_for_bytes",
    "read_pinned_model",
    "require_private_root",
    "stable_regular_bytes",
    "verified_bytes",
    "verify_git_checkout",
    "verify_git_tree",
    "write_bytes_exclusive",
    "write_identified_model",
    "write_model_exclusive",
]
