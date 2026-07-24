"""Crash-safe publication of a rendered JSON/CSV output pair."""

from __future__ import annotations

import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

type BinaryRenderer = Callable[[BinaryIO], None]


@dataclass(slots=True)
class _ArtifactPublication:
    destination: Path
    renderer: BinaryRenderer
    stage: Path | None = None
    previous_metadata: os.stat_result | None = None
    backup: Path | None = None
    replacement_attempted: bool = False


@dataclass(slots=True)
class _PairPublication:
    artifacts: tuple[_ArtifactPublication, ...]
    committed: bool = False


def write_bytes_atomic(path: str | Path, content: bytes) -> None:
    """Atomically replace one destination with rendered bytes."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _owned_paths(publication: _PairPublication) -> Iterator[Path | None]:
    yield from (artifact.stage for artifact in publication.artifacts)
    yield from (artifact.backup for artifact in publication.artifacts)


def _render_output_stage(directory: Path, artifact: _ArtifactPublication) -> None:
    primary_error: BaseException | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=directory,
            prefix=f".{artifact.destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            artifact.stage = Path(stream.name)
            try:
                os.fchmod(stream.fileno(), 0o600)
                artifact.renderer(cast(BinaryIO, stream))
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException as error:
                primary_error = error
                raise
    except BaseException:
        if primary_error is not None:
            raise primary_error from None
        raise
    if artifact.stage is None:
        raise RuntimeError("output stage was not created")


def _classify_output_destination(path: Path) -> os.stat_result | None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"output destination must be a regular file: {path.name}")
    return metadata


def _hard_link_backup(
    artifact: _ArtifactPublication,
    metadata: os.stat_result,
) -> None:
    path = artifact.destination
    for _ in range(100):
        backup_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.backup")
        try:
            os.link(path, backup_path, follow_symlinks=False)
        except FileExistsError:
            continue
        artifact.backup = backup_path
        backup_metadata = backup_path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(backup_metadata.st_mode)
            or backup_metadata.st_dev != metadata.st_dev
            or backup_metadata.st_ino != metadata.st_ino
        ):
            raise OSError(f"output destination changed during publication: {path.name}")
        return
    raise FileExistsError(f"unable to reserve output backup: {path.name}")


def _fsync_directory(directory: Path) -> None:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(directory, directory_flags)
    try:
        os.fsync(directory_descriptor)
    except BaseException:
        with suppress(BaseException):
            os.close(directory_descriptor)
        raise
    os.close(directory_descriptor)


def _fsync_directory_at_commit(
    directory: Path,
    publication: _PairPublication,
) -> None:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(directory, directory_flags)
    try:
        os.fsync(directory_descriptor)
    except BaseException:
        with suppress(BaseException):
            os.close(directory_descriptor)
        raise
    publication.committed = True
    os.close(directory_descriptor)


def _restore_published_output(artifact: _ArtifactPublication) -> None:
    if not artifact.replacement_attempted:
        return
    if artifact.previous_metadata is not None:
        if artifact.backup is None:
            raise RuntimeError("missing output backup during rollback")
        os.replace(artifact.backup, artifact.destination)
    else:
        artifact.destination.unlink(missing_ok=True)


def _rollback_output_pair(
    directory: Path,
    publication: _PairPublication,
) -> BaseException | None:
    first_error: BaseException | None = None
    for artifact in publication.artifacts:
        try:
            _restore_published_output(artifact)
        except BaseException as error:
            if first_error is None:
                first_error = error
    try:
        _fsync_directory(directory)
    except BaseException as error:
        if first_error is None:
            first_error = error
    return first_error


def _cleanup_output_paths(paths: Iterable[Path | None]) -> BaseException | None:
    first_error: BaseException | None = None
    retry_paths: list[Path] = []
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except BaseException as error:
            retry_paths.append(path)
            if first_error is None:
                first_error = error
    for path in retry_paths:
        with suppress(BaseException):
            path.unlink(missing_ok=True)
    return first_error


def _record_directory_fsync_error(
    directory: Path,
    first_error: BaseException | None,
) -> BaseException | None:
    try:
        _fsync_directory(directory)
    except BaseException as error:
        if first_error is None:
            return error
    return first_error


def write_output_pair_atomic(
    output_dir: str | Path,
    *,
    render_json: BinaryRenderer,
    render_csv: BinaryRenderer,
) -> None:
    """Publish a rendered JSON/CSV pair with handled-error rollback."""

    directory = Path(output_dir)
    directory_created = False
    try:
        directory.mkdir(parents=True)
        directory_created = True
    except FileExistsError:
        if not directory.is_dir():
            raise

    publication = _PairPublication(
        artifacts=(
            _ArtifactPublication(directory / "results.json", render_json),
            _ArtifactPublication(directory / "transactions.csv", render_csv),
        )
    )

    try:
        for artifact in publication.artifacts:
            _render_output_stage(directory, artifact)

        for artifact in publication.artifacts:
            artifact.previous_metadata = _classify_output_destination(artifact.destination)
        for artifact in publication.artifacts:
            if artifact.previous_metadata is not None:
                _hard_link_backup(artifact, artifact.previous_metadata)

        _fsync_directory(directory)
        for artifact in publication.artifacts:
            artifact.replacement_attempted = True
            os.replace(cast(Path, artifact.stage), artifact.destination)
        _fsync_directory_at_commit(directory, publication)
    except BaseException:
        if publication.committed:
            cleanup_error = _cleanup_output_paths(_owned_paths(publication))
            _record_directory_fsync_error(directory, cleanup_error)
            raise
        if any(artifact.replacement_attempted for artifact in publication.artifacts):
            _rollback_output_pair(directory, publication)
        cleanup_error = _cleanup_output_paths(_owned_paths(publication))
        _record_directory_fsync_error(directory, cleanup_error)
        if directory_created:
            with suppress(BaseException):
                directory.rmdir()
        raise

    cleanup_error = _cleanup_output_paths(_owned_paths(publication))
    cleanup_error = _record_directory_fsync_error(directory, cleanup_error)
    if cleanup_error is not None:
        raise cleanup_error


__all__ = ["BinaryRenderer", "write_bytes_atomic", "write_output_pair_atomic"]
