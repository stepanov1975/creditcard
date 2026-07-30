"""Snapshot and reverify the exact pinned deterministic profile package."""

from __future__ import annotations

import hashlib
import stat
import subprocess
from pathlib import Path
from typing import Literal, Never

from pydantic import Field, ValidationError

from experiments.row_extraction.contracts import _FrozenModel

from .cli_manifest import ProfileSourcePin
from .cli_state import (
    ControllerStateError,
    canonical_model_bytes,
    verify_git_tree,
    write_bytes_exclusive,
)

_PACKAGE_PATH = Path("experiments/row_extraction/arms/profiles")


class ProfileSourceError(ValueError):
    """The pinned profile source cannot be imported without provenance drift."""


def _fail(message: str) -> Never:
    raise ProfileSourceError(message)


class ProfileSourceFile(_FrozenModel):
    relative_path: str = Field(min_length=1)
    git_blob_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)


class ProfileSourceManifest(_FrozenModel):
    version: Literal["row-profile-source-snapshot-v1"]
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    package_tree_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: tuple[ProfileSourceFile, ...] = Field(min_length=1)


def _tracked_entries(pin: ProfileSourcePin) -> tuple[tuple[str, str, str], ...]:
    try:
        verify_git_tree(pin.checkout, _PACKAGE_PATH, pin.package_tree_sha)
    except ControllerStateError:
        _fail("source checkout is invalid")
    try:
        payload = subprocess.run(
            (
                "git",
                "ls-tree",
                "-r",
                "-z",
                pin.checkout.commit_sha,
                "--",
                _PACKAGE_PATH.as_posix(),
            ),
            cwd=pin.checkout.root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        _fail("source checkout is invalid")
    entries: list[tuple[str, str, str]] = []
    try:
        for raw_entry in payload.rstrip(b"\0").split(b"\0"):
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, kind, blob_sha = metadata.decode("ascii").split(" ")
            path = Path(raw_path.decode("utf-8"))
            relative = path.relative_to(_PACKAGE_PATH)
            if (
                mode != "100644"
                or kind != "blob"
                or not relative.parts
                or "__pycache__" in relative.parts
                or relative.suffix == ".pyc"
            ):
                _fail("source checkout is invalid")
            entries.append((relative.as_posix(), blob_sha, path.as_posix()))
    except (UnicodeError, ValueError):
        _fail("source checkout is invalid")
    if not entries or tuple(value[0] for value in entries) != tuple(
        sorted(value[0] for value in entries)
    ):
        _fail("source checkout is invalid")
    return tuple(entries)


def _blob(pin: ProfileSourcePin, blob_sha: str) -> bytes:
    try:
        return subprocess.run(
            ("git", "cat-file", "blob", blob_sha),
            cwd=pin.checkout.root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        _fail("source checkout is invalid")


def _worktree_bytes(pin: ProfileSourcePin, source_path: str, expected: bytes) -> None:
    path = pin.checkout.root / source_path
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            _fail("source checkout is invalid")
        actual = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except ProfileSourceError:
        raise
    except OSError:
        _fail("source checkout is invalid")
    if actual != expected or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        _fail("source checkout is invalid")


def snapshot_profile_source(
    pin: ProfileSourcePin,
    destination: Path,
) -> ProfileSourceManifest:
    """Copy exactly the regular tracked package files to one new source snapshot."""

    entries = _tracked_entries(pin)
    try:
        destination.mkdir(mode=0o700)
        package_root = destination / "profiles"
        package_root.mkdir(mode=0o700)
    except OSError:
        _fail("source snapshot destination is invalid")
    files: list[ProfileSourceFile] = []
    for relative_path, blob_sha, source_path in entries:
        content = _blob(pin, blob_sha)
        _worktree_bytes(pin, source_path, content)
        target = package_root / relative_path
        try:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            _fail("source snapshot publication failed")
        write_bytes_exclusive(target, content)
        files.append(
            ProfileSourceFile(
                relative_path=relative_path,
                git_blob_sha=blob_sha,
                sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
            )
        )
    manifest = ProfileSourceManifest(
        version="row-profile-source-snapshot-v1",
        commit_sha=pin.checkout.commit_sha,
        package_tree_sha=pin.package_tree_sha,
        files=tuple(files),
    )
    write_bytes_exclusive(destination / "source-manifest.json", canonical_model_bytes(manifest))
    return reverify_profile_snapshot(pin, destination)


def reverify_profile_snapshot(
    pin: ProfileSourcePin,
    destination: Path,
) -> ProfileSourceManifest:
    """Recheck Git and every copied byte before loading or locked execution."""

    entries = _tracked_entries(pin)
    manifest_path = destination / "source-manifest.json"
    try:
        payload = manifest_path.read_bytes()
        manifest = ProfileSourceManifest.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        _fail("source snapshot is invalid")
    if (
        payload != canonical_model_bytes(manifest)
        or manifest.commit_sha != pin.checkout.commit_sha
        or manifest.package_tree_sha != pin.package_tree_sha
        or tuple((value.relative_path, value.git_blob_sha) for value in manifest.files)
        != tuple((relative, blob_sha) for relative, blob_sha, _path in entries)
    ):
        _fail("source snapshot is invalid")
    package_root = destination / "profiles"
    try:
        observed = tuple(
            sorted(
                path.relative_to(package_root).as_posix()
                for path in package_root.rglob("*")
                if path.is_file() or path.is_symlink()
            )
        )
    except OSError:
        _fail("source snapshot is invalid")
    if observed != tuple(value.relative_path for value in manifest.files):
        _fail("source snapshot is invalid")
    for value in manifest.files:
        path = package_root / value.relative_path
        try:
            file_stat = path.stat(follow_symlinks=False)
            content = path.read_bytes()
        except OSError:
            _fail("source snapshot is invalid")
        if (
            path.is_symlink()
            or not stat.S_ISREG(file_stat.st_mode)
            or len(content) != value.byte_size
            or hashlib.sha256(content).hexdigest() != value.sha256
        ):
            _fail("source snapshot is invalid")
    return manifest


def source_manifest_identity(manifest: ProfileSourceManifest) -> str:
    """Return the aggregate SHA-256 used by pre-lock and locked receipts."""

    return hashlib.sha256(canonical_model_bytes(manifest)).hexdigest()


__all__ = [
    "ProfileSourceError",
    "ProfileSourceFile",
    "ProfileSourceManifest",
    "reverify_profile_snapshot",
    "snapshot_profile_source",
    "source_manifest_identity",
]
