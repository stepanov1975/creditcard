"""Descriptor-bound temporary storage for ordered statement results."""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ccparser import _corpus_spool_fs as spool_fs
from ccparser.models import StatementResult
from ccparser.output import canonical_json_bytes

_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_DIRECTORY_CAPABILITY_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_RECORD_NAME_WIDTH = 8
_MAX_ORDINAL = 10**_RECORD_NAME_WIDTH - 1
_READ_CHUNK_SIZE = 1024 * 1024


class StatementSpoolError(RuntimeError):
    """Privacy-safe statement spool failure."""


@dataclass(frozen=True, slots=True)
class SealedStatementRecord:
    ordinal: int
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    digest: str


def _spool_error() -> StatementSpoolError:
    return StatementSpoolError("statement spool operation failed")


def _record_name(ordinal: int) -> str:
    if type(ordinal) is not int or not 0 <= ordinal <= _MAX_ORDINAL:
        raise _spool_error()
    return f"{ordinal:0{_RECORD_NAME_WIDTH}d}.json"


class StatementSpool:
    """Store canonical statements in a private ordinal-only temporary directory."""

    def __init__(
        self,
        *,
        path: Path,
        name: str,
        parent_fd: int,
        directory_fd: int,
        directory_identity: tuple[int, int],
    ) -> None:
        self._path = path
        self._name = name
        self._parent_fd: int | None = parent_fd
        self._directory_fd: int | None = directory_fd
        self._directory_identity = spool_fs.FileIdentity(*directory_identity)
        self._records: dict[int, SealedStatementRecord] = {}
        self._owned_files: dict[str, spool_fs.FileIdentity] = {}
        self._expected_count: int | None = None
        self._closed = False

    @classmethod
    def create(cls, parent: Path) -> StatementSpool:
        """Create a private hidden spool beneath a trusted run output directory."""

        parent_fd: int | None = None
        capability_fd: int | None = None
        directory_fd: int | None = None
        name: str | None = None
        directory_identity: spool_fs.FileIdentity | None = None
        try:
            parent_fd = spool_fs.open_parent_directory(parent)
            parent_stat = os.fstat(parent_fd)
            if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.geteuid():
                raise _spool_error()
            for _ in range(16):
                candidate = f".statement-spool-{secrets.token_hex(16)}"
                name = candidate
                try:
                    os.mkdir(candidate, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    name = None
                    continue
                break
            if name is None:
                raise _spool_error()
            created_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            directory_identity = spool_fs.FileIdentity.from_stat(created_stat)
            if not stat.S_ISDIR(created_stat.st_mode) or created_stat.st_uid != os.geteuid():
                raise _spool_error()
            capability_fd = os.open(name, _DIRECTORY_CAPABILITY_FLAGS, dir_fd=parent_fd)
            capability_stat = os.fstat(capability_fd)
            if (
                not stat.S_ISDIR(capability_stat.st_mode)
                or capability_stat.st_uid != os.geteuid()
                or spool_fs.FileIdentity.from_stat(capability_stat) != directory_identity
            ):
                raise _spool_error()
            os.chmod(f"/proc/self/fd/{capability_fd}", 0o700)
            capability_stat = os.fstat(capability_fd)
            if (
                stat.S_IMODE(capability_stat.st_mode) != 0o700
                or spool_fs.FileIdentity.from_stat(capability_stat) != directory_identity
            ):
                raise _spool_error()
            directory_fd = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
            os.fchmod(directory_fd, 0o700)
            directory_stat = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(directory_stat.st_mode)
                or directory_stat.st_uid != os.geteuid()
                or stat.S_IMODE(directory_stat.st_mode) != 0o700
                or spool_fs.FileIdentity.from_stat(directory_stat) != directory_identity
            ):
                raise _spool_error()
            named_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(named_stat.st_mode)
                or spool_fs.FileIdentity.from_stat(named_stat) != directory_identity
            ):
                raise _spool_error()
            owned_capability_fd = capability_fd
            capability_fd = None
            os.close(owned_capability_fd)
            return cls(
                path=parent / name,
                name=name,
                parent_fd=parent_fd,
                directory_fd=directory_fd,
                directory_identity=(
                    directory_identity.device,
                    directory_identity.inode,
                ),
            )
        except BaseException as error:
            if directory_fd is not None:
                owned_directory_fd = directory_fd
                directory_fd = None
                spool_fs.close_no_throw(owned_directory_fd)
            if capability_fd is not None:
                owned_capability_fd = capability_fd
                capability_fd = None
                spool_fs.close_no_throw(owned_capability_fd)
            if parent_fd is not None and name is not None and directory_identity is None:
                directory_identity = spool_fs.owned_directory_identity_at_no_throw(
                    parent_fd,
                    name,
                )
            if parent_fd is not None and name is not None and directory_identity is not None:
                spool_fs.rmdir_if_owned_no_throw(parent_fd, name, directory_identity)
            if parent_fd is not None:
                owned_parent_fd = parent_fd
                parent_fd = None
                spool_fs.close_no_throw(owned_parent_fd)
            if isinstance(error, Exception):
                raise _spool_error() from None
            raise

    @property
    def path(self) -> Path:
        return self._path

    def append(self, ordinal: int, result: StatementResult, /) -> None:
        """Append one canonical statement under its unique ordinal."""

        file_descriptor: int | None = None
        directory_fd: int | None = None
        created_identity: spool_fs.FileIdentity | None = None
        name: str | None = None
        content: bytes | None = None
        try:
            directory_fd = self._active_directory_fd()
            if self._expected_count is not None or ordinal in self._records:
                raise _spool_error()
            name = _record_name(ordinal)
            self._validate_directory()
            content = canonical_json_bytes(result)
            file_descriptor = os.open(
                name,
                _FILE_WRITE_FLAGS,
                mode=0o600,
                dir_fd=directory_fd,
            )
            opened_stat = os.fstat(file_descriptor)
            created_identity = spool_fs.FileIdentity.from_stat(opened_stat)
            self._owned_files[name] = created_identity
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_uid != os.geteuid()
                or opened_stat.st_nlink != 1
                or opened_stat.st_size != 0
            ):
                raise _spool_error()
            os.fchmod(file_descriptor, 0o600)
            writable_stat = os.fstat(file_descriptor)
            if (
                not spool_fs.valid_record_stat(writable_stat, mode=0o600)
                or spool_fs.FileIdentity.from_stat(writable_stat) != created_identity
                or writable_stat.st_size != 0
            ):
                raise _spool_error()
            spool_fs.write_all(file_descriptor, content)
            os.fsync(file_descriptor)
            written_stat = os.fstat(file_descriptor)
            if (
                not spool_fs.valid_record_stat(written_stat, mode=0o600)
                or spool_fs.FileIdentity.from_stat(written_stat) != created_identity
                or written_stat.st_size != len(content)
            ):
                raise _spool_error()
            record = SealedStatementRecord(
                ordinal=ordinal,
                device=written_stat.st_dev,
                inode=written_stat.st_ino,
                size_bytes=written_stat.st_size,
                modified_ns=written_stat.st_mtime_ns,
                digest=sha256(content).hexdigest(),
            )
            os.fchmod(file_descriptor, 0o400)
            final_stat = os.fstat(file_descriptor)
            if not _stat_matches_record(final_stat, record):
                raise _spool_error()
            owned_file_descriptor = file_descriptor
            file_descriptor = None
            os.close(owned_file_descriptor)
            named_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not _stat_matches_record(named_stat, record):
                raise _spool_error()
            self._validate_directory()
            self._records[ordinal] = record
        except BaseException as error:
            if file_descriptor is not None:
                if created_identity is None:
                    created_identity = spool_fs.owned_regular_identity_no_throw(file_descriptor)
                    if created_identity is None and name is not None and directory_fd is not None:
                        created_identity = spool_fs.owned_exclusive_record_identity_at_no_throw(
                            file_descriptor,
                            directory_fd,
                            name,
                        )
                    if name is not None and created_identity is not None:
                        self._owned_files[name] = created_identity
                owned_file_descriptor = file_descriptor
                file_descriptor = None
                spool_fs.close_no_throw(owned_file_descriptor)
            if (
                name is not None
                and created_identity is not None
                and spool_fs.unlink_if_owned(self._directory_fd, name, created_identity)
            ):
                self._owned_files.pop(name, None)
            if isinstance(error, Exception):
                raise _spool_error() from None
            raise
        finally:
            del content

    def seal(self, expected_count: int, /) -> None:
        """Seal a complete zero-based ordinal range against later appends."""

        try:
            self._active_directory_fd()
            if self._expected_count is not None:
                raise _spool_error()
            if type(expected_count) is not int or not 0 <= expected_count <= _MAX_ORDINAL + 1:
                raise _spool_error()
            if len(self._records) != expected_count or any(
                ordinal not in self._records for ordinal in range(expected_count)
            ):
                raise _spool_error()
            self._validate_directory()
            self._expected_count = expected_count
        except Exception:
            raise _spool_error() from None

    def iter_statements(self) -> Iterator[StatementResult]:
        """Yield sealed statements in ordinal order after validating each record."""

        try:
            self._active_directory_fd()
            expected_count = self._expected_count
            if expected_count is None:
                raise _spool_error()
            self._validate_directory()
        except Exception:
            raise _spool_error() from None

        for ordinal in range(expected_count):
            content: bytes | None = None
            result: StatementResult | None = None
            try:
                record = self._records[ordinal]
                content = self._read_stable_record(record)
                result = StatementResult.model_validate_json(content)
                if canonical_json_bytes(result) != content:
                    raise _spool_error()
                yield result
            except Exception:
                raise _spool_error() from None
            finally:
                del result, content

    def close(self) -> None:
        """Best-effort remove owned records and release the spool descriptors."""

        if self._closed:
            return
        self._closed = True
        failed = False
        interruption: BaseException | None = None
        directory_fd = self._directory_fd
        parent_fd = self._parent_fd
        self._directory_fd = None
        self._parent_fd = None
        if directory_fd is not None:
            for name, identity in sorted(self._owned_files.items()):
                try:
                    named_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except BaseException as error:
                    if isinstance(error, Exception):
                        failed = True
                    elif interruption is None:
                        interruption = error
                    continue
                if (
                    not stat.S_ISREG(named_stat.st_mode)
                    or spool_fs.FileIdentity.from_stat(named_stat) != identity
                ):
                    failed = True
                    continue
                try:
                    os.unlink(name, dir_fd=directory_fd)
                except BaseException as error:
                    if isinstance(error, Exception):
                        failed = True
                    elif interruption is None:
                        interruption = error
        if parent_fd is not None:
            try:
                directory_matches = spool_fs.named_directory_matches(
                    parent_fd,
                    self._name,
                    self._directory_identity,
                )
            except BaseException as error:
                directory_matches = False
                if isinstance(error, Exception):
                    failed = True
                elif interruption is None:
                    interruption = error
            if directory_matches:
                try:
                    os.rmdir(self._name, dir_fd=parent_fd)
                except BaseException as error:
                    if isinstance(error, Exception):
                        failed = True
                    elif interruption is None:
                        interruption = error
            else:
                failed = True
        for file_descriptor in (directory_fd, parent_fd):
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except BaseException as error:
                    if isinstance(error, Exception):
                        failed = True
                    elif interruption is None:
                        interruption = error
        if interruption is not None:
            raise interruption
        if failed:
            raise _spool_error() from None

    def __enter__(self) -> StatementSpool:
        try:
            self._active_directory_fd()
        except Exception:
            raise _spool_error() from None
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _active_directory_fd(self) -> int:
        if self._closed or self._directory_fd is None:
            raise _spool_error()
        return self._directory_fd

    def _validate_directory(self) -> None:
        directory_fd = self._active_directory_fd()
        parent_fd = self._parent_fd
        if parent_fd is None:
            raise _spool_error()
        descriptor_stat = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or descriptor_stat.st_uid != os.geteuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != 0o700
            or spool_fs.FileIdentity.from_stat(descriptor_stat) != self._directory_identity
        ):
            raise _spool_error()
        if not spool_fs.named_directory_matches(
            parent_fd,
            self._name,
            self._directory_identity,
        ):
            raise _spool_error()

    def _read_stable_record(self, record: SealedStatementRecord) -> bytes:
        directory_fd = self._active_directory_fd()
        name = _record_name(record.ordinal)
        self._validate_directory()
        file_descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
        try:
            before = os.fstat(file_descriptor)
            if not _stat_matches_record(before, record):
                raise _spool_error()
            content = bytearray()
            digest = sha256()
            while chunk := os.read(file_descriptor, _READ_CHUNK_SIZE):
                content.extend(chunk)
                digest.update(chunk)
                if len(content) > record.size_bytes:
                    raise _spool_error()
            after = os.fstat(file_descriptor)
            named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            self._validate_directory()
            if (
                not _stat_matches_record(after, record)
                or not _stat_matches_record(named_after, record)
                or len(content) != record.size_bytes
                or digest.hexdigest() != record.digest
            ):
                raise _spool_error()
            result = bytes(content)
        except BaseException:
            spool_fs.close_no_throw(file_descriptor)
            raise
        os.close(file_descriptor)
        return result


def _stat_matches_record(file_stat: os.stat_result, record: SealedStatementRecord) -> bool:
    return spool_fs.valid_record_stat(file_stat, mode=0o400) and (
        spool_fs.FileIdentity.from_stat(file_stat)
        == spool_fs.FileIdentity(device=record.device, inode=record.inode)
        and file_stat.st_size == record.size_bytes
        and file_stat.st_mtime_ns == record.modified_ns
    )


__all__ = ["SealedStatementRecord", "StatementSpool", "StatementSpoolError"]
