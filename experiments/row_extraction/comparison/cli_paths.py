"""Resolved path-boundary checks for private controller inputs and outputs."""

from __future__ import annotations

import stat
from pathlib import Path


class PrivatePathError(ValueError):
    """A path escapes its declared private boundary or traverses a symlink."""


def resolve_without_symlink_ancestors(path: Path) -> Path:
    """Resolve the existing prefix while rejecting every symlinked component."""

    if not path.is_absolute():
        raise PrivatePathError("private path must be absolute")
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        candidate = current / part
        try:
            metadata = candidate.stat(follow_symlinks=False)
        except FileNotFoundError:
            try:
                resolved_parent = current.resolve(strict=True)
            except OSError:
                raise PrivatePathError("private path ancestor is invalid") from None
            return resolved_parent.joinpath(*parts[index:])
        except OSError:
            raise PrivatePathError("private path ancestor is invalid") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise PrivatePathError("private path ancestor is a symlink")
        current = candidate
    try:
        return current.resolve(strict=True)
    except OSError:
        raise PrivatePathError("private path is invalid") from None


def require_private_containment(path: Path, private_root: Path) -> Path:
    """Return a resolved candidate only when it remains beneath the private root."""

    resolved_root = resolve_without_symlink_ancestors(private_root)
    resolved = resolve_without_symlink_ancestors(path)
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise PrivatePathError("path escapes private root")
    return resolved


def resolved_overlap(first: Path, second: Path) -> bool:
    """Compare two paths after resolving their non-symlink ancestor chains."""

    first_resolved = resolve_without_symlink_ancestors(first)
    second_resolved = resolve_without_symlink_ancestors(second)
    return (
        first_resolved == second_resolved
        or first_resolved.is_relative_to(second_resolved)
        or second_resolved.is_relative_to(first_resolved)
    )


__all__ = [
    "PrivatePathError",
    "require_private_containment",
    "resolve_without_symlink_ancestors",
    "resolved_overlap",
]
