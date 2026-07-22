"""Policy-neutral safe path validation and deterministic PDF traversal."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Collection, Sequence
from enum import StrEnum
from pathlib import Path, PurePosixPath


class DirectoryRootPolicy(StrEnum):
    """Control whether a directory root is resolved or retained as a capability."""

    RESOLVE = "resolve"
    TRUSTED_DESCRIPTOR = "trusted_descriptor"


def normalize_directory_root(
    root: str | Path,
    *,
    policy: DirectoryRootPolicy,
    strict: bool,
) -> Path:
    """Normalize a path, preserving only an exact validated process-fd directory."""

    path = Path(root)
    if policy is DirectoryRootPolicy.RESOLVE:
        return path.resolve(strict=strict)
    if policy is not DirectoryRootPolicy.TRUSTED_DESCRIPTOR:
        raise ValueError("unsupported directory-root policy")
    descriptor_name = path.name
    if (
        path.parent != Path("/proc/self/fd")
        or not descriptor_name.isdecimal()
        or str(int(descriptor_name)) != descriptor_name
    ):
        raise ValueError("trusted root must be an exact process-fd path")
    descriptor = int(descriptor_name)
    descriptor_stat = os.fstat(descriptor)
    path_stat = os.stat(path)
    if not stat.S_ISDIR(descriptor_stat.st_mode) or (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ) != (path_stat.st_dev, path_stat.st_ino):
        raise ValueError("trusted root must identify its open directory descriptor")
    return path


def safe_relative_posix_path(value: str) -> PurePosixPath:
    """Return a normalized relative POSIX path without parent traversal."""

    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("value must be a safe relative POSIX path")
    return relative


def is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether *path* is equal to or nested beneath *parent*."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def paths_overlap(left: Path, right: Path) -> bool:
    """Return whether either path is equal to or nested beneath the other."""

    return is_relative_to(left, right) or is_relative_to(right, left)


def iter_regular_pdf_files(
    root: Path,
    *,
    excluded_roots: Sequence[Path] = (),
    excluded_directory_names: Collection[str] = (),
    on_error: Callable[[OSError], None] | None = None,
    root_policy: DirectoryRootPolicy = DirectoryRootPolicy.RESOLVE,
) -> tuple[Path, ...]:
    """Return regular PDFs beneath a normalized root in relative POSIX order."""

    selected_root = normalize_directory_root(root, policy=root_policy, strict=True)
    selected_exclusions = tuple(
        normalize_directory_root(path, policy=root_policy, strict=False) for path in excluded_roots
    )
    if any(is_relative_to(selected_root, excluded) for excluded in selected_exclusions):
        return ()
    files: list[Path] = []
    for root_value, directory_names, file_names in os.walk(
        selected_root,
        followlinks=False,
        onerror=on_error,
    ):
        current_root = Path(root_value)
        retained_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory = current_root / directory_name
            selected_directory = (
                directory.resolve(strict=False)
                if root_policy is DirectoryRootPolicy.RESOLVE
                else directory
            )
            if (
                directory_name in excluded_directory_names
                or directory.is_symlink()
                or any(
                    is_relative_to(selected_directory, excluded) for excluded in selected_exclusions
                )
            ):
                continue
            retained_directories.append(directory_name)
        directory_names[:] = retained_directories
        for file_name in sorted(file_names):
            source = current_root / file_name
            if source.suffix.casefold() != ".pdf" or source.is_symlink() or not source.is_file():
                continue
            selected_source = (
                source.resolve(strict=False)
                if root_policy is DirectoryRootPolicy.RESOLVE
                else source
            )
            if any(is_relative_to(selected_source, excluded) for excluded in selected_exclusions):
                continue
            files.append(selected_source)
    return tuple(sorted(files, key=lambda source: source.relative_to(selected_root).as_posix()))
