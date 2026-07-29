from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from experiments.row_extraction import foundation_admin
from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.contracts import ArtifactIdentity
from experiments.row_extraction.foundation_admin import app
from experiments.row_extraction.grouping import (
    PageSkeleton,
    RegionSkeleton,
    ReviewedGrouping,
    ReviewedPartition,
    ReviewerAttestation,
    candidate_relations,
    grouping_review_digest,
    structure_profile,
)
from tests.experiments.row_extraction.test_runtime import _toolchain

runner = CliRunner()


def _page(index: int) -> PageSkeleton:
    return PageSkeleton(
        page_number=1,
        size_points=(300 + index * 20, 792),
        requires_ocr=False,
        image_area_bucket=0,
        image_boxes=(),
        vector_rule_boxes=(),
        regions=(
            RegionSkeleton(
                bbox=(2, 12, 62, 58),
                header=(2, 12, 62, 18),
                column_edges=(2, 13, 49, 62),
                row_bands=((20, 24),),
            ),
        ),
    )


def _write_model(path: Path, model: object) -> None:
    payload = model.model_dump(mode="json")  # type: ignore[union-attr]
    path.write_text(
        json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )


def _freeze_fixture(
    private: Path,
    *,
    combined: bool = False,
) -> tuple[list[str], tuple[Path, ...]]:
    profiles = tuple(
        structure_profile(document_id=f"{index:064x}", pages=(_page(index),))
        for index in range(1, 11)
    )
    proposals = candidate_relations(profiles)
    profile_path = private / "profiles.jsonl"
    proposal_path = private / "proposals.jsonl"
    profile_identity = write_jsonl(profile_path, profiles)
    proposal_identity = write_jsonl(proposal_path, proposals)
    partitions = (
        (ReviewedPartition.from_documents(tuple(item.document_id for item in profiles)),)
        if combined
        else tuple(ReviewedPartition.from_documents((item.document_id,)) for item in profiles)
    )
    digest = grouping_review_digest(
        profile_identity,
        proposal_identity,
        partitions,
        partitions,
    )
    reviewed = ReviewedGrouping(
        version="reviewed-row-grouping-v1",
        profile_identity=profile_identity,
        proposal_identity=proposal_identity,
        duplicate_partitions=partitions,
        layout_partitions=partitions,
        reviewer_attestations=(
            ReviewerAttestation(reviewer_id="1" * 64, reviewed_sha256=digest),
            ReviewerAttestation(reviewer_id="2" * 64, reviewed_sha256=digest),
        ),
    )
    reviewed_path = private / "reviewed.json"
    _write_model(reviewed_path, reviewed)
    outputs = tuple(
        private / name
        for name in (
            "groups.jsonl",
            "groups.identity.json",
            "split.json",
            "split.identity.json",
        )
    )
    arguments = [
        "freeze-groups",
        "--private-root",
        str(private),
        "--profiles",
        str(profile_path),
        "--proposals",
        str(proposal_path),
        "--reviewed-grouping",
        str(reviewed_path),
        "--seed",
        "row-extraction-v1",
        "--groups-output",
        str(outputs[0]),
        "--groups-identity-output",
        str(outputs[1]),
        "--split-output",
        str(outputs[2]),
        "--split-identity-output",
        str(outputs[3]),
    ]
    return arguments, outputs


def test_admin_cli_has_only_foundation_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "profile-groups",
        "freeze-groups",
        "prepare-runtime",
        "verify-runtime",
        "prepare-report-context",
    ):
        assert command in result.stdout
    for experiment_command in ("prepare-page-evidence", "run-baseline", "score"):
        assert experiment_command not in result.stdout


def test_freeze_groups_writes_private_canonical_outputs_without_values(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 0
    assert result.stdout == "status=ok command=freeze-groups\n"
    assert all(path.is_file() for path in outputs)


def _dependency_identity(private: Path) -> Path:
    dependency = private / "dependency.identity.json"
    _write_model(
        dependency,
        ArtifactIdentity(
            artifact_type="resource-inventory",
            sha256="a" * 64,
            version="row-resource-inventory-v1",
            byte_size=1,
        ),
    )
    return dependency


def _prepare_runtime_arguments(
    private: Path,
    dependency: Path,
    output: Path,
    identity_output: Path,
) -> list[str]:
    return [
        "prepare-runtime",
        "--private-root",
        str(private),
        "--dependency-inventory-identity",
        str(dependency),
        "--output",
        str(output),
        "--identity-output",
        str(identity_output),
    ]


def test_freeze_groups_stops_when_reviewed_components_cannot_fill_splits(
    tmp_path: Path,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private, combined=True)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert result.stderr == "status=error command=freeze-groups\n"
    assert not any(path.exists() for path in outputs)


def test_freeze_groups_rolls_back_owned_outputs_and_preserves_foreign_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private)
    real_link = foundation_admin.os.link
    calls = 0

    def fail_third_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            Path(destination).write_bytes(b"foreign")
            raise FileExistsError
        real_link(source, destination)

    monkeypatch.setattr(foundation_admin.os, "link", fail_third_link)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert not outputs[0].exists()
    assert not outputs[1].exists()
    assert outputs[2].read_bytes() == b"foreign"
    assert not outputs[3].exists()


def test_freeze_groups_rejects_in_place_staging_mutation_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private)
    real_link = foundation_admin.os.link
    calls = 0

    def mutate_then_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(source).write_bytes(b"mutated-staging")
        real_link(source, destination)

    monkeypatch.setattr(foundation_admin.os, "link", mutate_then_link)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert not any(path.exists() for path in outputs)


def test_freeze_groups_rejects_mutation_before_first_staging_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private)
    real_snapshot = foundation_admin._file_snapshot
    calls = 0

    def mutate_before_snapshot(path: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            path.write_bytes(b"mutated-before-first-snapshot")
        return real_snapshot(path)

    monkeypatch.setattr(foundation_admin, "_file_snapshot", mutate_before_snapshot)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert not any(path.exists() for path in outputs)


def test_freeze_groups_rolls_back_when_link_creates_target_then_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    arguments, outputs = _freeze_fixture(private)
    real_link = foundation_admin.os.link
    calls = 0

    def link_then_raise(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        real_link(source, destination)
        if calls == 1:
            raise OSError

    monkeypatch.setattr(foundation_admin.os, "link", link_then_raise)

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert not any(path.exists() for path in outputs)


def test_profile_groups_publishes_geometry_atlas_and_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    documents = (tmp_path / "documents").resolve()
    documents.mkdir()
    (documents / "private-name.pdf").write_bytes(b"synthetic")
    profiles = tuple(
        structure_profile(document_id=f"{index:064x}", pages=(_page(index),))
        for index in range(1, 4)
    )
    monkeypatch.setattr(
        foundation_admin,
        "profile_documents",
        lambda _sources, _cache: profiles,
    )
    outputs = tuple(
        private / name
        for name in (
            "profiles.jsonl",
            "profiles.identity.json",
            "proposals.jsonl",
            "proposals.identity.json",
            "atlas.svg",
            "atlas.identity.json",
        )
    )

    result = runner.invoke(
        app,
        [
            "profile-groups",
            "--private-root",
            str(private),
            "--documents",
            str(documents),
            "--cache-dir",
            str(private / "cache"),
            "--profiles-output",
            str(outputs[0]),
            "--profiles-identity-output",
            str(outputs[1]),
            "--proposals-output",
            str(outputs[2]),
            "--proposals-identity-output",
            str(outputs[3]),
            "--atlas-output",
            str(outputs[4]),
            "--atlas-identity-output",
            str(outputs[5]),
        ],
    )

    assert result.exit_code == 0
    assert all(path.is_file() for path in outputs)
    assert outputs[4].read_bytes().startswith(b"<svg")
    assert b"private-name" not in outputs[4].read_bytes()


def test_profile_groups_publication_failure_rolls_back_owned_cache_and_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    documents = (tmp_path / "documents").resolve()
    documents.mkdir()
    (documents / "source.pdf").write_bytes(b"synthetic")
    profile = structure_profile(document_id="1" * 64, pages=(_page(1),))
    monkeypatch.setattr(
        foundation_admin,
        "profile_documents",
        lambda _sources, cache: ((cache / "owned.cache").write_bytes(b"cache") and profile,),
    )
    real_link = foundation_admin.os.link
    calls = 0

    def fail_second_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError
        real_link(source, destination)

    monkeypatch.setattr(foundation_admin.os, "link", fail_second_link)
    outputs = tuple(private / f"output-{index}" for index in range(6))

    result = runner.invoke(
        app,
        [
            "profile-groups",
            "--private-root",
            str(private),
            "--documents",
            str(documents),
            "--cache-dir",
            str(private / "cache"),
            "--profiles-output",
            str(outputs[0]),
            "--profiles-identity-output",
            str(outputs[1]),
            "--proposals-output",
            str(outputs[2]),
            "--proposals-identity-output",
            str(outputs[3]),
            "--atlas-output",
            str(outputs[4]),
            "--atlas-identity-output",
            str(outputs[5]),
        ],
    )

    assert result.exit_code == 1
    assert not (private / "cache").exists()
    assert not any(path.exists() for path in outputs)


def test_profile_groups_preserves_replaced_foreign_cache_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    documents = (tmp_path / "documents").resolve()
    documents.mkdir()
    (documents / "source.pdf").write_bytes(b"synthetic")
    cache = private / "cache"

    def replace_cache(_sources: object, cache_path: Path) -> object:
        cache_path.rmdir()
        cache_path.mkdir()
        (cache_path / "foreign").write_bytes(b"foreign")
        raise RuntimeError

    monkeypatch.setattr(foundation_admin, "profile_documents", replace_cache)
    outputs = tuple(private / f"output-{index}" for index in range(6))

    result = runner.invoke(
        app,
        [
            "profile-groups",
            "--private-root",
            str(private),
            "--documents",
            str(documents),
            "--cache-dir",
            str(cache),
            "--profiles-output",
            str(outputs[0]),
            "--profiles-identity-output",
            str(outputs[1]),
            "--proposals-output",
            str(outputs[2]),
            "--proposals-identity-output",
            str(outputs[3]),
            "--atlas-output",
            str(outputs[4]),
            "--atlas-identity-output",
            str(outputs[5]),
        ],
    )

    assert result.exit_code == 1
    assert (cache / "foreign").read_bytes() == b"foreign"
    assert not any(path.exists() for path in outputs)


def test_prepare_runtime_publication_failure_rolls_back_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    dependency = _dependency_identity(private)

    class Inspector:
        def fingerprint(self) -> object:
            return _toolchain()

        def close(self) -> None:
            return None

    monkeypatch.setattr(foundation_admin, "LocalToolchainInspector", Inspector)
    real_link = foundation_admin.os.link
    calls = 0

    def fail_second_link(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError
        real_link(source, destination)

    monkeypatch.setattr(foundation_admin.os, "link", fail_second_link)
    output = private / "runtime.json"
    identity_output = private / "runtime.identity.json"

    result = runner.invoke(
        app,
        _prepare_runtime_arguments(private, dependency, output, identity_output),
    )

    assert result.exit_code == 1
    assert not output.exists()
    assert not identity_output.exists()


def test_admin_cli_rejects_relative_output_independently(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    dependency = _dependency_identity(private)

    result = runner.invoke(
        app,
        _prepare_runtime_arguments(
            private,
            dependency,
            Path("relative.json"),
            private / "identity.json",
        ),
    )

    assert result.exit_code == 1
    assert result.stderr == "status=error command=prepare-runtime\n"


def test_admin_cli_rejects_existing_output_independently(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    dependency = _dependency_identity(private)
    output = private / "runtime.json"
    output.write_text("occupied", encoding="utf-8")

    result = runner.invoke(
        app,
        _prepare_runtime_arguments(
            private,
            dependency,
            output,
            private / "identity.json",
        ),
    )

    assert result.exit_code == 1
    assert result.stderr == "status=error command=prepare-runtime\n"


def test_admin_cli_rejects_symlink_input_independently(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    dependency = _dependency_identity(private)
    link = private / "dependency-link.json"
    link.symlink_to(dependency)

    result = runner.invoke(
        app,
        _prepare_runtime_arguments(
            private,
            link,
            private / "runtime.json",
            private / "identity.json",
        ),
    )

    assert result.exit_code == 1
    assert result.stderr == "status=error command=prepare-runtime\n"
    assert str(private) not in result.stderr


def test_admin_cli_rejects_symlink_output_independently(tmp_path: Path) -> None:
    private = (tmp_path / "private").resolve()
    private.mkdir()
    dependency = _dependency_identity(private)
    target = private / "target.json"
    target.write_bytes(b"foreign")
    output = private / "runtime-link.json"
    output.symlink_to(target)

    result = runner.invoke(
        app,
        _prepare_runtime_arguments(
            private,
            dependency,
            output,
            private / "identity.json",
        ),
    )

    assert result.exit_code == 1
    assert target.read_bytes() == b"foreign"
    assert result.stderr == "status=error command=prepare-runtime\n"
