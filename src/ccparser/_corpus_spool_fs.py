"""Low-level descriptor and stat helpers for the statement spool."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """Immutable device/inode identity for an owned filesystem entry."""

    device: int
    inode: int

    @classmethod
    def from_stat(cls, file_stat: os.stat_result, /) -> FileIdentity:
        return cls(device=file_stat.st_dev, inode=file_stat.st_ino)


def _process_fd_number(path: Path) -> int | None:
    descriptor_name = path.name
    if (
        path.parent != Path("/proc/self/fd")
        or not descriptor_name.isdecimal()
        or str(int(descriptor_name)) != descriptor_name
    ):
        return None
    return int(descriptor_name)


def close_no_throw(file_descriptor: int, /) -> None:
    with suppress(Exception, KeyboardInterrupt, SystemExit):
        os.close(file_descriptor)


def open_parent_directory(parent: Path, /) -> int:
    """Open a path or validated exact ``/proc/self/fd`` directory reference."""

    descriptor = _process_fd_number(parent)
    if descriptor is None:
        return os.open(parent, _DIRECTORY_OPEN_FLAGS)

    descriptor_stat = os.fstat(descriptor)
    path_stat = os.stat(parent)
    expected_identity = FileIdentity.from_stat(descriptor_stat)
    if (
        not stat.S_ISDIR(descriptor_stat.st_mode)
        or descriptor_stat.st_uid != os.geteuid()
        or not stat.S_ISDIR(path_stat.st_mode)
        or path_stat.st_uid != os.geteuid()
        or FileIdentity.from_stat(path_stat) != expected_identity
    ):
        raise OSError("unsafe parent directory descriptor")

    duplicate = os.dup(descriptor)
    try:
        os.set_inheritable(duplicate, False)
        duplicate_stat = os.fstat(duplicate)
        if (
            not stat.S_ISDIR(duplicate_stat.st_mode)
            or duplicate_stat.st_uid != os.geteuid()
            or FileIdentity.from_stat(duplicate_stat) != expected_identity
            or os.get_inheritable(duplicate)
        ):
            raise OSError("unsafe duplicated parent directory descriptor")
        return duplicate
    except BaseException:
        close_no_throw(duplicate)
        raise


def write_all(file_descriptor: int, content: bytes, /) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(file_descriptor, remaining)
        if written <= 0:
            raise OSError
        remaining = remaining[written:]


def valid_record_stat(file_stat: os.stat_result, *, mode: int) -> bool:
    return (
        stat.S_ISREG(file_stat.st_mode)
        and file_stat.st_uid == os.geteuid()
        and stat.S_IMODE(file_stat.st_mode) == mode
        and file_stat.st_nlink == 1
    )


def named_directory_matches(
    parent_fd: int,
    name: str,
    identity: FileIdentity,
    /,
) -> bool:
    try:
        named_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(named_stat.st_mode) and FileIdentity.from_stat(named_stat) == identity


def owned_regular_identity_no_throw(
    file_descriptor: int,
    /,
) -> FileIdentity | None:
    try:
        file_stat = os.fstat(file_descriptor)
    except (Exception, KeyboardInterrupt, SystemExit):
        return None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.geteuid():
        return None
    return FileIdentity.from_stat(file_stat)


def owned_exclusive_record_identity_at_no_throw(
    file_descriptor: int,
    directory_fd: int,
    name: str,
    /,
) -> FileIdentity | None:
    try:
        descriptor_stat = os.stat(
            f"/proc/self/fd/{file_descriptor}",
            follow_symlinks=True,
        )
        named_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except (Exception, KeyboardInterrupt, SystemExit):
        return None
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or descriptor_stat.st_uid != os.geteuid()
        or descriptor_stat.st_nlink != 1
        or descriptor_stat.st_size != 0
        or stat.S_IMODE(descriptor_stat.st_mode) & ~0o600
        or not stat.S_ISREG(named_stat.st_mode)
        or named_stat.st_uid != os.geteuid()
        or named_stat.st_nlink != 1
        or named_stat.st_size != 0
        or stat.S_IMODE(named_stat.st_mode) & ~0o600
        or FileIdentity.from_stat(named_stat) != FileIdentity.from_stat(descriptor_stat)
    ):
        return None
    return FileIdentity.from_stat(descriptor_stat)


def owned_directory_identity_at_no_throw(
    parent_fd: int,
    name: str,
    /,
) -> FileIdentity | None:
    try:
        directory_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except (Exception, KeyboardInterrupt, SystemExit):
        return None
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.geteuid():
        return None
    return FileIdentity.from_stat(directory_stat)


def unlink_if_owned(
    directory_fd: int | None,
    name: str,
    identity: FileIdentity,
    /,
) -> bool:
    if directory_fd is None:
        return False
    try:
        named_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except (Exception, KeyboardInterrupt, SystemExit):
        return False
    if stat.S_ISREG(named_stat.st_mode) and FileIdentity.from_stat(named_stat) == identity:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except (Exception, KeyboardInterrupt, SystemExit):
            return False
        return True
    return False


def rmdir_if_owned_no_throw(
    parent_fd: int,
    name: str,
    identity: FileIdentity,
    /,
) -> None:
    try:
        if named_directory_matches(parent_fd, name, identity):
            os.rmdir(name, dir_fd=parent_fd)
    except (Exception, KeyboardInterrupt, SystemExit):
        pass


__all__ = [
    "FileIdentity",
    "close_no_throw",
    "named_directory_matches",
    "open_parent_directory",
    "owned_directory_identity_at_no_throw",
    "owned_exclusive_record_identity_at_no_throw",
    "owned_regular_identity_no_throw",
    "rmdir_if_owned_no_throw",
    "unlink_if_owned",
    "valid_record_stat",
    "write_all",
]
