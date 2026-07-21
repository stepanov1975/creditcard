from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

import ccparser.paths as paths_module
from ccparser.paths import (
    is_relative_to,
    iter_regular_pdf_files,
    paths_overlap,
    safe_relative_posix_path,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("statement.pdf", PurePosixPath("statement.pdf")),
        ("nested/statement.pdf", PurePosixPath("nested/statement.pdf")),
        ("nested/./statement.pdf", PurePosixPath("nested/statement.pdf")),
        (r"..\statement.pdf", PurePosixPath(r"..\statement.pdf")),
        (r"\statement.pdf", PurePosixPath(r"\statement.pdf")),
    ),
)
def test_safe_relative_posix_path_normalizes_posix_parts_and_preserves_backslashes(
    value: str,
    expected: PurePosixPath,
) -> None:
    assert safe_relative_posix_path(value) == expected


@pytest.mark.parametrize(
    "value",
    ("", ".", "/", "/statement.pdf", "..", "../statement.pdf", "nested/../statement.pdf"),
)
def test_safe_relative_posix_path_rejects_empty_absolute_and_traversal_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="safe relative POSIX path"):
        safe_relative_posix_path(value)


def test_containment_and_overlap_distinguish_nested_and_sibling_paths(tmp_path: Path) -> None:
    parent = tmp_path / "statements"
    nested = parent / "nested" / "statement.pdf"
    sibling = tmp_path / "statements-copy" / "statement.pdf"

    assert is_relative_to(parent, parent)
    assert is_relative_to(nested, parent)
    assert not is_relative_to(sibling, parent)
    assert paths_overlap(parent, nested)
    assert paths_overlap(nested, parent)
    assert not paths_overlap(parent, sibling)


def test_iter_regular_pdf_files_is_policy_neutral_resolved_and_deterministic(
    tmp_path: Path,
) -> None:
    root = tmp_path / "input"
    for relative in (
        ".cache/cached.pdf",
        "z.pdf",
        "a.PDF",
        "generated/output.PdF",
        "nested/b.pdf",
        "notes.txt",
    ):
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(relative.encode())
    (root / "directory.pdf").mkdir()
    outside_file = tmp_path / "outside.pdf"
    outside_file.write_bytes(b"outside")
    (root / "linked.pdf").symlink_to(outside_file)
    outside_directory = tmp_path / "outside-directory"
    outside_directory.mkdir()
    (outside_directory / "linked-child.pdf").write_bytes(b"outside child")
    (root / "linked-directory").symlink_to(outside_directory, target_is_directory=True)

    files = iter_regular_pdf_files(root / ".." / "input")

    assert files == tuple(
        (root / relative).resolve()
        for relative in (
            ".cache/cached.pdf",
            "a.PDF",
            "generated/output.PdF",
            "nested/b.pdf",
            "z.pdf",
        )
    )


def test_iter_regular_pdf_files_prunes_only_caller_exclusions(tmp_path: Path) -> None:
    root = tmp_path / "input"
    for relative in (
        ".cache/ignored.pdf",
        "generated/ignored.pdf",
        "nested/.cache/ignored.pdf",
        "nested/kept.pdf",
        "kept.pdf",
    ):
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(relative.encode())

    files = iter_regular_pdf_files(
        root,
        excluded_roots=(root / "generated" / ".." / "generated",),
        excluded_directory_names={".cache"},
    )

    assert files == ((root / "kept.pdf").resolve(), (root / "nested/kept.pdf").resolve())


@pytest.mark.parametrize("exclusion_kind", ("equal", "ancestor"))
def test_iter_regular_pdf_files_does_not_walk_an_excluded_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exclusion_kind: str,
) -> None:
    root = tmp_path / "input"
    root.mkdir()
    excluded_root = root if exclusion_kind == "equal" else tmp_path
    walk_calls = 0

    def recording_walk(*args: object, **kwargs: object) -> tuple[object, ...]:
        nonlocal walk_calls
        del args, kwargs
        walk_calls += 1
        return ()

    monkeypatch.setattr(paths_module.os, "walk", recording_walk)

    assert iter_regular_pdf_files(root, excluded_roots=(excluded_root,)) == ()
    assert walk_calls == 0


def test_iter_regular_pdf_files_passes_walk_errors_to_callback_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "input"
    root.mkdir()
    error = PermissionError("private unreadable directory detail")
    received: list[OSError] = []

    def record_error(received_error: OSError) -> None:
        received.append(received_error)

    def failing_walk(
        top: Path,
        *,
        followlinks: bool,
        onerror: Callable[[OSError], None] | None,
    ) -> tuple[object, ...]:
        assert top == root.resolve()
        assert followlinks is False
        assert onerror is record_error
        onerror(error)
        return ()

    monkeypatch.setattr(paths_module.os, "walk", failing_walk)

    assert iter_regular_pdf_files(root, on_error=record_error) == ()
    assert received == [error]
    assert received[0] is error
