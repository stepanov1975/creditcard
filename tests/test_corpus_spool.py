from __future__ import annotations

import os
import stat
import traceback
from contextlib import suppress
from pathlib import Path

import pytest

import ccparser.corpus_spool as corpus_spool_module
from ccparser.corpus_spool import StatementSpool, StatementSpoolError
from ccparser.models import StatementResult, Status
from ccparser.output import canonical_json_bytes


class _InjectedInterruption(KeyboardInterrupt):
    pass


def _statement(source_name: str) -> StatementResult:
    return StatementResult(
        status=Status.RECONCILED,
        transactions=(),
        groups=(),
        source_name=source_name,
        source_sha256="a" * 64,
        statement_id="a" * 64,
    )


def test_spool_round_trips_out_of_order_records_in_ordinal_order(tmp_path: Path) -> None:
    first = _statement("nested/a.pdf")
    second = _statement("z.pdf")
    with StatementSpool.create(tmp_path) as spool:
        spool.append(1, second)
        spool.append(0, first)
        spool.seal(2)

        assert tuple(spool.iter_statements()) == (first, second)
        names = tuple(sorted(path.name for path in spool.path.iterdir()))
        assert names == ("00000000.json", "00000001.json")
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in spool.path.iterdir())

    assert not spool.path.exists()


def test_spool_enforces_private_modes_under_restrictive_umask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_open = os.open

    def permission_aware_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if isinstance(path, str) and path.startswith(".statement-spool-") and not flags & os.O_PATH:
            directory_stat = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
            if not directory_stat.st_mode & stat.S_IXUSR:
                raise PermissionError("owner cannot open mode-zero directory")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    previous_umask = os.umask(0o777)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(corpus_spool_module.os, "open", permission_aware_open)
            with StatementSpool.create(tmp_path) as spool:
                spool.append(0, _statement("source.pdf"))
                spool.seal(1)

                assert stat.S_IMODE(spool.path.stat().st_mode) == 0o700
                assert stat.S_IMODE(next(spool.path.iterdir()).stat().st_mode) == 0o400
    finally:
        os.umask(previous_umask)


def test_spool_rejects_duplicate_ordinals(tmp_path: Path) -> None:
    with StatementSpool.create(tmp_path) as spool:
        spool.append(0, _statement("first.pdf"))

        with pytest.raises(StatementSpoolError, match=r"^statement spool operation failed$"):
            spool.append(0, _statement("second.pdf"))


def test_spool_rejects_missing_ordinal_range_without_sealing(tmp_path: Path) -> None:
    with StatementSpool.create(tmp_path) as spool:
        spool.append(1, _statement("second.pdf"))

        with pytest.raises(StatementSpoolError, match=r"^statement spool operation failed$"):
            spool.seal(2)

        spool.append(0, _statement("first.pdf"))
        spool.seal(2)
        assert len(tuple(spool.iter_statements())) == 2


def test_spool_rejects_append_after_seal(tmp_path: Path) -> None:
    with StatementSpool.create(tmp_path) as spool:
        spool.seal(0)

        with pytest.raises(StatementSpoolError, match=r"^statement spool operation failed$"):
            spool.append(0, _statement("private.pdf"))


def test_spool_rejects_read_before_seal(tmp_path: Path) -> None:
    with StatementSpool.create(tmp_path) as spool:
        spool.append(0, _statement("private.pdf"))

        with pytest.raises(StatementSpoolError, match=r"^statement spool operation failed$"):
            tuple(spool.iter_statements())


def test_spool_close_is_idempotent(tmp_path: Path) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private.pdf"))
    spool.close()

    spool.close()

    assert not spool.path.exists()


@pytest.mark.parametrize(
    "mutation",
    ("truncate", "replace", "chmod", "hardlink", "delete", "symlink"),
)
def test_spool_rejects_changed_sealed_records_without_sensitive_details(
    tmp_path: Path,
    mutation: str,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private/source.pdf"))
    spool.seal(1)
    record = next(spool.path.iterdir())
    if mutation == "truncate":
        record.chmod(0o600)
        record.write_bytes(b"private financial content")
    elif mutation == "replace":
        record.unlink()
        record.write_bytes(b"{}")
    elif mutation == "chmod":
        record.chmod(0o600)
    elif mutation == "hardlink":
        os.link(record, spool.path / "extra-link")
    elif mutation == "delete":
        record.unlink()
    else:
        record.unlink()
        record.symlink_to(tmp_path / "outside")

    with pytest.raises(StatementSpoolError) as caught:
        tuple(spool.iter_statements())

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    with suppress(StatementSpoolError):
        spool.close()


@pytest.mark.parametrize("corruption", ("invalid_schema", "malformed_json", "noncanonical"))
def test_spool_rejects_invalid_record_content_without_sensitive_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    statement = _statement("private/source.pdf")
    if corruption == "invalid_schema":
        payload = b'{"confidential":"financial content"}\n'
    elif corruption == "malformed_json":
        payload = b'{"confidential":\n'
    else:
        payload = b" " + canonical_json_bytes(statement)
    spool = StatementSpool.create(tmp_path)

    def injected_payload(_: StatementResult) -> bytes:
        return payload

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module, "canonical_json_bytes", injected_payload)
        spool.append(0, statement)
    spool.seal(1)

    with pytest.raises(StatementSpoolError) as caught:
        tuple(spool.iter_statements())

    formatted = "".join(traceback.format_exception(caught.value))
    assert str(caught.value) == "statement spool operation failed"
    assert "confidential" not in formatted
    assert "private" not in formatted
    spool.close()


def test_spool_rejects_same_identity_digest_corruption_without_sensitive_details(
    tmp_path: Path,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private/source.pdf"))
    spool.seal(1)
    record = next(spool.path.iterdir())
    sealed_stat = record.stat()
    corrupted = bytearray(record.read_bytes())
    corrupted[-2] ^= 1
    record.chmod(0o600)
    record.write_bytes(corrupted)
    os.utime(
        record,
        ns=(sealed_stat.st_atime_ns, sealed_stat.st_mtime_ns),
        follow_symlinks=False,
    )
    record.chmod(0o400)
    changed_stat = record.stat()
    assert (
        changed_stat.st_dev,
        changed_stat.st_ino,
        changed_stat.st_size,
        changed_stat.st_mtime_ns,
    ) == (
        sealed_stat.st_dev,
        sealed_stat.st_ino,
        sealed_stat.st_size,
        sealed_stat.st_mtime_ns,
    )

    with pytest.raises(StatementSpoolError) as caught:
        tuple(spool.iter_statements())

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    spool.close()


def test_spool_rejects_record_with_changed_owner_without_sensitive_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private/source.pdf"))
    spool.seal(1)
    original_fstat = os.fstat

    def report_changed_owner(file_descriptor: int) -> os.stat_result:
        file_stat = original_fstat(file_descriptor)
        if stat.S_ISREG(file_stat.st_mode) and stat.S_IMODE(file_stat.st_mode) == 0o400:
            values = list(file_stat)
            values[stat.ST_UID] = file_stat.st_uid + 1
            return os.stat_result(values)
        return file_stat

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fstat", report_changed_owner)
        with pytest.raises(StatementSpoolError) as caught:
            tuple(spool.iter_statements())

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    spool.close()


def test_spool_removes_partial_record_after_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    statement = _statement("private/source.pdf")

    def fail_fsync(_: int) -> None:
        raise OSError("private append failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fsync", fail_fsync)
        with pytest.raises(StatementSpoolError) as caught:
            spool.append(0, statement)

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    assert tuple(spool.path.iterdir()) == ()
    spool.close()


def test_spool_removes_created_record_when_initial_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    original_fstat = os.fstat
    failed = False

    def fail_first_record_fstat(file_descriptor: int) -> os.stat_result:
        nonlocal failed
        file_stat = original_fstat(file_descriptor)
        if stat.S_ISREG(file_stat.st_mode) and not failed:
            failed = True
            raise OSError("private initial fstat failure")
        return file_stat

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fstat", fail_first_record_fstat)
        with pytest.raises(StatementSpoolError):
            spool.append(0, _statement("source.pdf"))

    assert tuple(spool.path.iterdir()) == ()
    spool.close()


def test_spool_tracks_exclusive_record_when_all_descriptor_stats_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    record_path = spool.path / "00000000.json"
    original_fstat = os.fstat
    original_stat = os.stat
    original_unlink = os.unlink
    record_stat_calls: list[tuple[int | None, bool]] = []
    unlink_attempts = 0

    def fail_record_fstat(file_descriptor: int) -> os.stat_result:
        file_stat = original_fstat(file_descriptor)
        if stat.S_ISREG(file_stat.st_mode):
            raise OSError("private descriptor stat failure")
        return file_stat

    def record_name_stat(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if path == "00000000.json":
            record_stat_calls.append((dir_fd, follow_symlinks))
        return original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    def fail_first_unlink(name: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_attempts
        unlink_attempts += 1
        if unlink_attempts == 1:
            raise OSError("private transient cleanup failure")
        original_unlink(name, dir_fd=dir_fd)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(corpus_spool_module.os, "fstat", fail_record_fstat)
            scoped.setattr(corpus_spool_module.os, "stat", record_name_stat)
            scoped.setattr(corpus_spool_module.os, "unlink", fail_first_unlink)
            with pytest.raises(StatementSpoolError) as caught:
                spool.append(0, _statement("source.pdf"))

        assert str(caught.value) == "statement spool operation failed"
        assert "private" not in "".join(traceback.format_exception(caught.value))
        assert record_path.exists()
        spool.close()

        assert not spool.path.exists()
        assert record_stat_calls
        assert all(
            directory_fd is not None and not follow_symlinks
            for directory_fd, follow_symlinks in record_stat_calls
        )
        assert unlink_attempts == 1
    finally:
        with suppress(StatementSpoolError):
            spool.close()
        with suppress(FileNotFoundError):
            record_path.unlink()
        with suppress(FileNotFoundError):
            spool.path.rmdir()


def test_spool_retries_owned_partial_cleanup_on_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    statement = _statement("private/source.pdf")
    original_unlink = os.unlink
    unlink_attempts = 0

    def fail_first_unlink(name: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_attempts
        unlink_attempts += 1
        if unlink_attempts == 1:
            raise OSError("private transient cleanup failure")
        original_unlink(name, dir_fd=dir_fd)

    def fail_fsync(_: int) -> None:
        raise OSError("private append failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fsync", fail_fsync)
        scoped.setattr(corpus_spool_module.os, "unlink", fail_first_unlink)
        with pytest.raises(StatementSpoolError):
            spool.append(0, statement)

    assert tuple(path.name for path in spool.path.iterdir()) == ("00000000.json",)
    spool.close()

    assert not spool.path.exists()


def test_spool_cleans_created_directory_when_creation_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = _InjectedInterruption()

    def interrupt_fchmod(_: int, __: int) -> None:
        raise interruption

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fchmod", interrupt_fchmod)
        with pytest.raises(_InjectedInterruption) as caught:
            StatementSpool.create(tmp_path)

    assert caught.value is interruption
    assert tuple(tmp_path.iterdir()) == ()


def test_spool_cleans_created_directory_when_mkdir_reports_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = _InjectedInterruption()
    original_mkdir = os.mkdir

    def mkdir_then_interrupt(
        path: str,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        original_mkdir(path, mode, dir_fd=dir_fd)
        raise interruption

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "mkdir", mkdir_then_interrupt)
        with pytest.raises(_InjectedInterruption) as caught:
            StatementSpool.create(tmp_path)

    assert caught.value is interruption
    assert tuple(tmp_path.iterdir()) == ()


def test_spool_cleans_partial_record_when_append_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    interruption = _InjectedInterruption()

    def interrupt_fsync(_: int) -> None:
        raise interruption

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "fsync", interrupt_fsync)
        with pytest.raises(_InjectedInterruption) as caught:
            spool.append(0, _statement("source.pdf"))

    assert caught.value is interruption
    assert tuple(spool.path.iterdir()) == ()
    spool.close()


def test_spool_does_not_retry_a_descriptor_after_close_releases_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    original_close = os.close
    reused_descriptor: int | None = None

    def close_then_reuse(file_descriptor: int) -> None:
        nonlocal reused_descriptor
        if reused_descriptor is None and stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            original_close(file_descriptor)
            reused_descriptor = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
            if reused_descriptor != file_descriptor:
                raise RuntimeError("descriptor allocator did not reuse the released number")
            raise OSError("private close failure after release")
        original_close(file_descriptor)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(corpus_spool_module.os, "close", close_then_reuse)
            with pytest.raises(StatementSpoolError):
                spool.append(0, _statement("source.pdf"))

        assert reused_descriptor is not None
        os.fstat(reused_descriptor)
    finally:
        if reused_descriptor is not None:
            with suppress(OSError):
                original_close(reused_descriptor)
        spool.close()


def test_spool_closes_record_after_read_failure_without_sensitive_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private/source.pdf"))
    spool.seal(1)
    read_descriptors: list[int] = []
    closed_descriptors: list[int] = []
    original_close = os.close

    def fail_read(file_descriptor: int, _: int) -> bytes:
        read_descriptors.append(file_descriptor)
        raise OSError("private read failure")

    def record_close(file_descriptor: int) -> None:
        closed_descriptors.append(file_descriptor)
        original_close(file_descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "read", fail_read)
        scoped.setattr(corpus_spool_module.os, "close", record_close)
        with pytest.raises(StatementSpoolError) as caught:
            tuple(spool.iter_statements())

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    assert len(read_descriptors) == 1
    assert read_descriptors == closed_descriptors
    with pytest.raises(OSError):
        os.fstat(read_descriptors[0])
    spool.close()
    assert not spool.path.exists()


def test_spool_preserves_read_interruption_when_record_close_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("source.pdf"))
    spool.seal(1)
    interruption = _InjectedInterruption()
    original_close = os.close

    def interrupt_read(_: int, __: int) -> bytes:
        raise interruption

    def close_then_fail(file_descriptor: int) -> None:
        original_close(file_descriptor)
        raise OSError("private close failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "read", interrupt_read)
        scoped.setattr(corpus_spool_module.os, "close", close_then_fail)
        with pytest.raises(_InjectedInterruption) as caught:
            tuple(spool.iter_statements())

    assert caught.value is interruption
    spool.close()


def test_spool_close_continues_cleanup_without_unlinking_unknown_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("first.pdf"))
    spool.append(1, _statement("second.pdf"))
    unknown = spool.path / "unknown-entry"
    unknown.write_bytes(b"unowned")
    original_unlink = os.unlink
    unlink_calls: list[str] = []

    def fail_first_record_unlink(name: str, *, dir_fd: int | None = None) -> None:
        unlink_calls.append(name)
        if name == "00000000.json":
            raise OSError("private close failure")
        original_unlink(name, dir_fd=dir_fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "unlink", fail_first_record_unlink)
        with pytest.raises(StatementSpoolError) as caught:
            spool.close()

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    assert unlink_calls == ["00000000.json", "00000001.json"]
    assert (spool.path / "00000000.json").exists()
    assert not (spool.path / "00000001.json").exists()
    assert unknown.read_bytes() == b"unowned"
    spool.close()

    (spool.path / "00000000.json").unlink()
    unknown.unlink()
    spool.path.rmdir()


def test_spool_close_releases_descriptors_and_continues_after_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("first.pdf"))
    spool.append(1, _statement("second.pdf"))
    original_unlink = os.unlink
    original_close = os.close
    interruption = _InjectedInterruption()
    unlink_calls: list[str] = []
    closed_descriptors: list[int] = []

    def interrupt_first_unlink(name: str, *, dir_fd: int | None = None) -> None:
        unlink_calls.append(name)
        if name == "00000000.json":
            raise interruption
        original_unlink(name, dir_fd=dir_fd)

    def record_close(file_descriptor: int) -> None:
        closed_descriptors.append(file_descriptor)
        original_close(file_descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(corpus_spool_module.os, "unlink", interrupt_first_unlink)
        scoped.setattr(corpus_spool_module.os, "close", record_close)
        with pytest.raises(_InjectedInterruption) as caught:
            spool.close()

    assert caught.value is interruption
    assert unlink_calls == ["00000000.json", "00000001.json"]
    assert (spool.path / "00000000.json").exists()
    assert not (spool.path / "00000001.json").exists()
    assert len(closed_descriptors) == 2
    spool.close()

    (spool.path / "00000000.json").unlink()
    spool.path.rmdir()
