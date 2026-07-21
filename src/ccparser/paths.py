"""Policy-neutral safe path validation and deterministic PDF traversal."""

from __future__ import annotations

import os
from collections.abc import Callable, Collection, Sequence
from pathlib import Path, PurePosixPath


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
) -> tuple[Path, ...]:
    """Return resolved regular PDFs beneath *root* in relative POSIX order."""

    resolved_root = root.resolve(strict=True)
    resolved_exclusions = tuple(path.resolve(strict=False) for path in excluded_roots)
    if any(is_relative_to(resolved_root, excluded) for excluded in resolved_exclusions):
        return ()
    files: list[Path] = []
    for root_value, directory_names, file_names in os.walk(
        resolved_root,
        followlinks=False,
        onerror=on_error,
    ):
        current_root = Path(root_value)
        retained_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory = current_root / directory_name
            resolved_directory = directory.resolve(strict=False)
            if (
                directory_name in excluded_directory_names
                or directory.is_symlink()
                or any(
                    is_relative_to(resolved_directory, excluded) for excluded in resolved_exclusions
                )
            ):
                continue
            retained_directories.append(directory_name)
        directory_names[:] = retained_directories
        for file_name in sorted(file_names):
            source = current_root / file_name
            if source.suffix.casefold() != ".pdf" or source.is_symlink() or not source.is_file():
                continue
            resolved_source = source.resolve(strict=False)
            if any(is_relative_to(resolved_source, excluded) for excluded in resolved_exclusions):
                continue
            files.append(resolved_source)
    return tuple(sorted(files, key=lambda source: source.relative_to(resolved_root).as_posix()))
