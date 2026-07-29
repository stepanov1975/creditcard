from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

import experiments.row_extraction.cli as cli_module
from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.annotations import AnnotationSummary
from experiments.row_extraction.baselines import PageEvidenceRecord
from experiments.row_extraction.bundle import PreparedBundle
from experiments.row_extraction.cli import (
    CliContractError,
    _verify_ocr_cache,
    app,
    assert_repeated_output,
)
from experiments.row_extraction.codecs import read_jsonl, write_jsonl
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    DatasetSplit,
    Decision,
    FrozenRow,
    GoldRow,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.crops import CropRecord
from experiments.row_extraction.report import ReportContext
from experiments.row_extraction.runner import (
    InventoryRoots,
    PreparationMeasurements,
    ResourceInventory,
    ResourceSpec,
    RunMeasurements,
    build_resource_inventory,
)
from experiments.row_extraction.split import DocumentMembership, SplitManifest
from tests.experiments.row_extraction.factories import frozen_row

_RUNNER = CliRunner()


def _identity(
    marker: str = "a",
    *,
    artifact_type: str = "synthetic",
    version: str = "synthetic-v1",
    byte_size: int = 1,
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=marker * 64,
        version=version,
        byte_size=byte_size,
    )


def _write_model(path: Path, value: object) -> None:
    path.write_bytes(_canonical_json_value_content(value) + b"\n")


def _write_identity(path: Path, identity: ArtifactIdentity) -> None:
    _write_model(path, identity.model_dump(mode="json"))


def _inventory_identity(path: Path) -> ArtifactIdentity:
    payload = path.read_bytes()
    return ArtifactIdentity(
        artifact_type="resource-inventory",
        sha256=hashlib.sha256(payload).hexdigest(),
        version="row-resource-inventory-v1",
        byte_size=len(payload),
    )


def _structural_row(private_root: Path, *, split: DatasetSplit) -> FrozenRow:
    return frozen_row(
        split=split,
        source_pdf=private_root / "source.pdf",
        baseline_type=RowType.STRUCTURAL,
        atoms=(),
    )


def _structural_prediction(row: FrozenRow) -> RowPrediction:
    return RowPrediction(
        experiment_id="accepted-baseline",
        config_id="accepted-anchor",
        document_id=row.document_id,
        row_id=row.row_id,
        predicted_type=RowType.STRUCTURAL,
        evidence_atoms=(),
        proposals=(),
        decision=Decision.IGNORE,
        reasons=("synthetic_structural",),
    )


def _run_measurements(
    row: FrozenRow,
    predictions_identity: ArtifactIdentity,
) -> RunMeasurements:
    row_identity = write_jsonl(row.source_pdf.parent / "row-sequence.tmp", (row,))
    row_sequence = row_identity.model_copy(update={"artifact_type": "frozen-row-sequence"})
    inventory = _identity(
        "b",
        artifact_type="resource-inventory",
        version="row-resource-inventory-v1",
    )
    return RunMeasurements(
        experiment_id="accepted-baseline",
        config_id="accepted-anchor",
        row_sequence_identity=row_sequence,
        split=row.split,
        cache_policy="new-empty-v1",
        resource_basis="materialized-adapter",
        arm_manifest_identity=predictions_identity,
        row_count=1,
        total_ns=10,
        p50_ns=5,
        p95_ns=5,
        preparation_ns=0,
        end_to_end_ns=10,
        cold_start_ns=5,
        throughput_rows_per_second=Decimal("100000000"),
        peak_rss_bytes=1024,
        model_bytes=0,
        dependency_bytes=1,
        cache_bytes=0,
        subprocess_count=0,
        worker_count=1,
        measurement_protocol="row-resource-measurement-v1",
        runtime_identity=_identity("c"),
        model_inventory_identity=inventory,
        dependency_inventory_identity=inventory.model_copy(update={"sha256": "d" * 64}),
        resource_inventory_identity=inventory.model_copy(update={"sha256": "e" * 64}),
        predictions_sha256=predictions_identity.sha256,
    )


def _inventory_files(private_root: Path, *, with_model: bool = False) -> tuple[Path, Path]:
    dependency = private_root / "runtime.bin"
    dependency.write_bytes(b"runtime")
    model_asset = private_root / "model.bin"
    if with_model:
        model_asset.write_bytes(b"model")
    model = build_resource_inventory(
        InventoryRoots(
            version="row-resource-roots-v1",
            category="model",
            roots=((model_asset,) if with_model else ()),
        )
    )
    dependencies = build_resource_inventory(
        InventoryRoots(
            version="row-resource-roots-v1",
            category="dependency",
            roots=(dependency,),
        )
    )
    model_path = private_root / "models.json"
    dependency_path = private_root / "dependencies.json"
    _write_model(model_path, model.model_dump(mode="json"))
    _write_model(dependency_path, dependencies.model_dump(mode="json"))
    return model_path, dependency_path


def test_cli_exposes_only_the_seven_foundation_commands() -> None:
    result = _RUNNER.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "prepare",
        "prepare-inventory",
        "prepare-page-evidence",
        "prepare-run-spec",
        "validate",
        "run-baseline",
        "score",
    ):
        assert command in result.stdout
    for forbidden in ("runtime-identity", "report-context", "group", "split"):
        assert forbidden not in result.stdout


def test_prepare_writes_all_canonical_identity_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = (tmp_path / "private").resolve()
    documents = (tmp_path / "documents").resolve()
    private_root.mkdir()
    documents.mkdir()
    source = documents / "source.pdf"
    source.write_bytes(b"synthetic")
    source_identity = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = SplitManifest(
        seed="public-seed",
        version="row-extraction-split-v1",
        memberships=(
            DocumentMembership(
                document_id=source_identity,
                split=DatasetSplit.TRAIN,
                atomic_unit="unit",
                stratum="stratum",
            ),
        ),
    )
    manifest_path = private_root / "split.json"
    _write_model(manifest_path, manifest.model_dump(mode="json"))
    prepared: list[PreparedBundle] = []

    def fake_prepare(
        sources: Iterable[Path],
        destination: Path,
        split_by_document: Mapping[str, DatasetSplit],
    ) -> PreparedBundle:
        assert tuple(sources) == (documents / "source.pdf",)
        assert split_by_document == {source_identity: DatasetSplit.TRAIN}
        destination.mkdir()
        row = _structural_row(private_root, split=DatasetSplit.TRAIN).model_copy(
            update={"document_id": source_identity}
        )
        prediction = _structural_prediction(row)
        crop_path = destination / "crops" / "private.ppm"
        crop_path.parent.mkdir()
        crop_path.write_bytes(b"synthetic-crop")
        crop = CropRecord(
            document_id=row.document_id,
            row_id=row.row_id,
            row_bbox=row.bbox,
            relative_path="private.ppm",
            sha256=hashlib.sha256(crop_path.read_bytes()).hexdigest(),
            width=1,
            height=1,
        )
        bundle = PreparedBundle(
            rows=write_jsonl(destination / "rows.jsonl", (row,)),
            accepted_predictions=write_jsonl(
                destination / "accepted_predictions.jsonl", (prediction,)
            ),
            crop_index=write_jsonl(destination / "crop_index.jsonl", (crop,)),
        )
        prepared.append(bundle)
        return bundle

    monkeypatch.setattr("experiments.row_extraction.cli.prepare_bundle", fake_prepare)
    output = private_root / "bundle"
    result = _RUNNER.invoke(
        app,
        [
            "prepare",
            "--private-root",
            str(private_root),
            "--documents",
            str(documents),
            "--split-manifest",
            str(manifest_path),
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    identities = prepared[0]
    for name, identity in (
        ("rows", identities.rows),
        ("accepted_predictions", identities.accepted_predictions),
        ("crop_index", identities.crop_index),
    ):
        assert (
            ArtifactIdentity.model_validate_json((output / f"{name}.identity.json").read_bytes())
            == identity
        )


def test_validate_bundle_allows_frozen_documents_without_detected_rows(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "bundle"
    crop_root = destination / "crops"
    crop_root.mkdir(parents=True)
    row = _structural_row(tmp_path, split=DatasetSplit.TRAIN)
    prediction = _structural_prediction(row)
    crop_path = crop_root / "row.ppm"
    crop_path.write_bytes(b"synthetic-crop")
    crop = CropRecord(
        document_id=row.document_id,
        row_id=row.row_id,
        row_bbox=row.bbox,
        relative_path="row.ppm",
        sha256=hashlib.sha256(crop_path.read_bytes()).hexdigest(),
        width=1,
        height=1,
    )
    for name, records in (
        ("rows", (row,)),
        ("accepted_predictions", (prediction,)),
        ("crop_index", (crop,)),
    ):
        identity = write_jsonl(destination / f"{name}.jsonl", records)
        _write_identity(destination / f"{name}.identity.json", identity)
    manifest = SplitManifest(
        seed="public-seed",
        version="row-extraction-split-v1",
        memberships=(
            DocumentMembership(
                document_id=row.document_id,
                split=DatasetSplit.TRAIN,
                atomic_unit="unit-with-row",
                stratum="stratum",
            ),
            DocumentMembership(
                document_id="e" * 64,
                split=DatasetSplit.VALIDATION,
                atomic_unit="zero-row-unit",
                stratum="stratum",
            ),
        ),
    )

    cli_module._validate_bundle(destination, manifest)


def test_prepare_orders_documents_by_content_identity_not_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = (tmp_path / "private").resolve()
    documents = (tmp_path / "documents").resolve()
    private_root.mkdir()
    documents.mkdir()
    first_by_name = documents / "a.pdf"
    second_by_name = documents / "z.pdf"
    first_by_name.write_bytes(b"z-content")
    second_by_name.write_bytes(b"a-content")
    by_identity = tuple(
        sorted(
            (first_by_name, second_by_name),
            key=lambda path: hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    )
    memberships = tuple(
        DocumentMembership(
            document_id=hashlib.sha256(path.read_bytes()).hexdigest(),
            split=DatasetSplit.TRAIN,
            atomic_unit=f"unit-{index}",
            stratum="stratum",
        )
        for index, path in enumerate(by_identity)
    )
    manifest_path = private_root / "split.json"
    _write_model(
        manifest_path,
        SplitManifest(
            seed="public-seed",
            version="row-extraction-split-v1",
            memberships=memberships,
        ).model_dump(mode="json"),
    )
    observed: list[tuple[Path, ...]] = []

    def fake_prepare(
        sources: Iterable[Path],
        _destination: Path,
        _split_by_document: Mapping[str, DatasetSplit],
    ) -> PreparedBundle:
        observed.append(tuple(sources))
        raise RuntimeError("stop after discovery")

    monkeypatch.setattr("experiments.row_extraction.cli.prepare_bundle", fake_prepare)
    result = _RUNNER.invoke(
        app,
        [
            "prepare",
            "--private-root",
            str(private_root),
            "--documents",
            str(documents),
            "--split-manifest",
            str(manifest_path),
            "--output-dir",
            str(private_root / "bundle"),
        ],
    )

    assert result.exit_code == 1
    assert observed == [by_identity]


def test_prepare_rejects_complete_accepted_prediction_type_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = (tmp_path / "private").resolve()
    documents = (tmp_path / "documents").resolve()
    private_root.mkdir()
    documents.mkdir()
    source = documents / "source.pdf"
    source.write_bytes(b"synthetic")
    source_identity = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = SplitManifest(
        seed="public-seed",
        version="row-extraction-split-v1",
        memberships=(
            DocumentMembership(
                document_id=source_identity,
                split=DatasetSplit.TRAIN,
                atomic_unit="unit",
                stratum="stratum",
            ),
        ),
    )
    manifest_path = private_root / "split.json"
    _write_model(manifest_path, manifest.model_dump(mode="json"))

    def fake_prepare(
        _sources: Iterable[Path],
        destination: Path,
        _split_by_document: Mapping[str, DatasetSplit],
    ) -> PreparedBundle:
        destination.mkdir()
        row = _structural_row(private_root, split=DatasetSplit.TRAIN).model_copy(
            update={"document_id": source_identity}
        )
        prediction = _structural_prediction(row).model_copy(
            update={"predicted_type": RowType.AMBIGUOUS}
        )
        crop_path = destination / "crops" / "private.ppm"
        crop_path.parent.mkdir()
        crop_path.write_bytes(b"synthetic-crop")
        crop = CropRecord(
            document_id=row.document_id,
            row_id=row.row_id,
            row_bbox=row.bbox,
            relative_path="private.ppm",
            sha256=hashlib.sha256(crop_path.read_bytes()).hexdigest(),
            width=1,
            height=1,
        )
        return PreparedBundle(
            rows=write_jsonl(destination / "rows.jsonl", (row,)),
            accepted_predictions=write_jsonl(
                destination / "accepted_predictions.jsonl", (prediction,)
            ),
            crop_index=write_jsonl(destination / "crop_index.jsonl", (crop,)),
        )

    monkeypatch.setattr("experiments.row_extraction.cli.prepare_bundle", fake_prepare)
    output = private_root / "bundle"
    result = _RUNNER.invoke(
        app,
        [
            "prepare",
            "--private-root",
            str(private_root),
            "--documents",
            str(documents),
            "--split-manifest",
            str(manifest_path),
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_PREPARE_ERROR\n"
    assert not output.exists()


def test_prepare_inventory_is_canonical_and_refuses_existing_output(tmp_path: Path) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    asset = private_root / "asset.bin"
    asset.write_bytes(b"dependency")
    roots = private_root / "roots.json"
    _write_model(
        roots,
        InventoryRoots(
            version="row-resource-roots-v1",
            category="dependency",
            roots=(asset,),
        ).model_dump(mode="json"),
    )
    output = private_root / "inventory.json"
    identity_output = private_root / "inventory.identity.json"
    arguments = [
        "prepare-inventory",
        "--private-root",
        str(private_root),
        "--roots",
        str(roots),
        "--output",
        str(output),
        "--identity-output",
        str(identity_output),
    ]

    result = _RUNNER.invoke(app, arguments)

    assert result.exit_code == 0
    assert result.stdout == ""
    inventory = ResourceInventory.model_validate_json(output.read_bytes())
    identity = ArtifactIdentity.model_validate_json(identity_output.read_bytes())
    assert identity.artifact_type == "resource-inventory"
    assert hashlib.sha256(output.read_bytes()).hexdigest() == identity.sha256
    assert inventory.entries[0].resolved_path == asset

    second = _RUNNER.invoke(app, arguments)
    assert second.exit_code == 1
    assert second.stdout == ""
    assert second.stderr == "ROW_CLI_INVENTORY_ERROR\n"
    assert str(asset) not in second.stderr


def test_prepare_inventory_preserves_a_foreign_identity_race_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    asset = private_root / "asset.bin"
    asset.write_bytes(b"dependency")
    roots = private_root / "roots.json"
    _write_model(
        roots,
        InventoryRoots(
            version="row-resource-roots-v1",
            category="dependency",
            roots=(asset,),
        ).model_dump(mode="json"),
    )
    output = private_root / "inventory.json"
    identity_output = private_root / "inventory.identity.json"
    original_link = os.link

    def racing_link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        follow_symlinks: bool = True,
    ) -> None:
        if Path(destination) == identity_output:
            identity_output.write_bytes(b"foreign-identity")
            raise FileExistsError
        original_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "link", racing_link)
    result = _RUNNER.invoke(
        app,
        [
            "prepare-inventory",
            "--private-root",
            str(private_root),
            "--roots",
            str(roots),
            "--output",
            str(output),
            "--identity-output",
            str(identity_output),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_INVENTORY_ERROR\n"
    assert not output.exists()
    assert identity_output.read_bytes() == b"foreign-identity"


def test_validate_accepts_omitted_ocr_references_and_prints_only_counts(tmp_path: Path) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.TRAIN)
    label = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.STRUCTURAL,
        fields=(),
    )
    rows = private_root / "rows.jsonl"
    labels = private_root / "labels.jsonl"
    write_jsonl(rows, (row,))
    write_jsonl(labels, (label,))

    result = _RUNNER.invoke(
        app,
        [
            "validate",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--labels",
            str(labels),
        ],
    )

    assert result.exit_code == 0
    summary = AnnotationSummary.model_validate_json(result.stdout)
    assert summary.row_count == 1
    assert summary.ocr_reference_count == 0
    assert "row-1" not in result.stdout
    assert str(private_root) not in result.stdout


@pytest.mark.parametrize("mode", ("conditional-page-ocr", "forced-page-ocr"))
def test_prepare_page_evidence_uses_exact_fresh_tesseract_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    source = private_root / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    row = frozen_row(
        document_id=source_sha,
        split=DatasetSplit.VALIDATION,
        source_pdf=source,
        bbox=(0.0, 10.0, 200.0, 40.0),
        baseline_type=RowType.STRUCTURAL,
        atoms=(),
    )
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    runtime_path = private_root / "runtime.json"
    _write_identity(runtime_path, _identity("9", artifact_type="runtime"))
    model_inventory, dependency_inventory = _inventory_files(private_root, with_model=True)
    launches: list[tuple[str, ...]] = []

    class _Completed:
        returncode = 0
        stderr = b""

        def __init__(self, stdout: bytes) -> None:
            self.stdout = stdout

    def fake_launch(command: tuple[str, ...], **_kwargs: object) -> _Completed:
        launches.append(command)
        return _Completed(b"tesseract 5.5.0\n" if "--version" in command else b"")

    monkeypatch.setattr("ccparser.evidence.ocr._launch_tesseract", fake_launch)
    events: list[str] = []
    original_input_file = cli_module._input_file
    original_clock = cli_module.perf_counter_ns

    def observed_input_file(path: Path) -> Path:
        resolved = original_input_file(path)
        if path == source:
            events.append("row-source")
        return resolved

    def observed_clock() -> int:
        events.append("clock")
        return original_clock()

    monkeypatch.setattr(cli_module, "_input_file", observed_input_file)
    monkeypatch.setattr(cli_module, "perf_counter_ns", observed_clock)
    cache_dir = private_root / f"{mode}.cache"
    output = cache_dir / "page-evidence.jsonl"
    identity_output = cache_dir / "page-evidence.identity.json"
    inventory_output = private_root / f"{mode}.inventory.json"
    preparation_output = private_root / f"{mode}.preparation.json"
    result = _RUNNER.invoke(
        app,
        [
            "prepare-page-evidence",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            mode,
            "--runtime-identity",
            str(runtime_path),
            "--cache-dir",
            str(cache_dir),
            "--output",
            str(output),
            "--identity-output",
            str(identity_output),
            "--model-inventory",
            str(model_inventory),
            "--dependency-inventory",
            str(dependency_inventory),
            "--inventory-output",
            str(inventory_output),
            "--preparation-output",
            str(preparation_output),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert events.index("row-source") < events.index("clock")
    assert result.stdout == ""
    assert len(launches) == 4
    record = tuple(read_jsonl(output, PageEvidenceRecord))
    assert len(record) == 1
    assert record[0].mode == mode
    preparation = PreparationMeasurements.model_validate_json(preparation_output.read_bytes())
    assert preparation.subprocess_count == 4
    expected_configs = {
        "conditional-page-ocr": (
            "fixed-page-evidence-v1:production-conditional-page-evidence-v1:"
            "unique-intersection-ownership-v1"
        ),
        "forced-page-ocr": (
            "fixed-page-evidence-v1:production-forced-whole-page-tesseract-v1:"
            "unique-intersection-ownership-v1"
        ),
    }
    assert preparation.config_id == expected_configs[mode]
    assert preparation.arm_manifest_identity == ArtifactIdentity.model_validate_json(
        identity_output.read_bytes()
    )
    run_cache = private_root / f"{mode}.run-cache"
    run_inventory = private_root / f"{mode}.run-inventory.json"
    spec_path = private_root / f"{mode}.spec.json"
    prepare_spec = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            mode,
            "--arm-manifest-identity",
            str(identity_output),
            "--runtime-identity",
            str(runtime_path),
            "--model-inventory",
            str(model_inventory),
            "--dependency-inventory",
            str(dependency_inventory),
            "--cache-root",
            str(run_cache),
            "--inventory-output",
            str(run_inventory),
            "--output",
            str(spec_path),
        ],
    )
    assert prepare_spec.exit_code == 0, prepare_spec.stderr
    empty_models = build_resource_inventory(
        InventoryRoots(version="row-resource-roots-v1", category="model", roots=())
    )
    empty_models_path = private_root / f"{mode}.empty-models.json"
    _write_model(empty_models_path, empty_models.model_dump(mode="json"))
    forged_spec = ResourceSpec.model_validate_json(spec_path.read_bytes()).model_copy(
        update={
            "model_inventory_path": empty_models_path,
            "model_inventory_identity": _inventory_identity(empty_models_path),
            "cache_root": private_root / f"{mode}.forged-cache",
            "resource_inventory_output": private_root / f"{mode}.forged-inventory.json",
        }
    )
    forged_spec_path = private_root / f"{mode}.forged-spec.json"
    _write_model(forged_spec_path, forged_spec.model_dump(mode="json"))
    called: list[bool] = []

    def forbidden_run(*_args: object, **_kwargs: object) -> RunMeasurements:
        called.append(True)
        raise AssertionError("execution must not start")

    with monkeypatch.context() as run_patch:
        run_patch.setattr(cli_module, "run_arm", forbidden_run)
        forged_result = _RUNNER.invoke(
            app,
            [
                "run-baseline",
                "--private-root",
                str(private_root),
                "--mode",
                mode,
                "--rows",
                str(rows),
                "--split",
                "validation",
                "--baseline-input",
                str(output),
                "--baseline-identity",
                str(identity_output),
                "--resource-spec",
                str(forged_spec_path),
                "--preparation",
                str(preparation_output),
                "--predictions-output",
                str(private_root / f"{mode}.forged-predictions.jsonl"),
                "--run-output",
                str(private_root / f"{mode}.forged-run.json"),
            ],
        )
    assert forged_result.exit_code == 1
    assert called == []
    predictions_output = private_root / f"{mode}.predictions.jsonl"
    run_output = private_root / f"{mode}.run.json"
    run_result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            mode,
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(output),
            "--baseline-identity",
            str(identity_output),
            "--resource-spec",
            str(spec_path),
            "--preparation",
            str(preparation_output),
            "--predictions-output",
            str(predictions_output),
            "--run-output",
            str(run_output),
        ],
    )
    assert run_result.exit_code == 0, run_result.stderr
    run_measurements = RunMeasurements.model_validate_json(run_output.read_bytes())
    assert run_measurements.config_id == preparation.config_id
    predictions = tuple(read_jsonl(predictions_output, RowPrediction))
    assert {prediction.config_id for prediction in predictions} == {preparation.config_id}


def test_ocr_cache_requires_exact_pass_correspondence_and_counts_all_launches(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    for suffix in ("primary", "supplemental", "numeric", "currency"):
        (cache / f"page-1.{suffix}.tsv").write_bytes(b"")

    first_batch = frozenset(cache.iterdir())
    assert (
        _verify_ocr_cache(
            cache,
            page_count=1,
            forced=True,
            requested_artifacts=first_batch,
            word_request_count=1,
        )
        == 5
    )

    (cache / "page-1.supplemental.tsv").rename(cache / "page-2.supplemental.tsv")
    with pytest.raises(CliContractError, match="OCR cache key binding mismatch"):
        _verify_ocr_cache(
            cache,
            page_count=1,
            forced=True,
            requested_artifacts=first_batch,
            word_request_count=1,
        )


def test_ocr_cache_accounts_for_a_later_page_cache_hit(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    for suffix in ("primary", "supplemental", "numeric"):
        (cache / f"shared-page.{suffix}.tsv").write_bytes(b"")
    first_batch = frozenset(cache.iterdir())

    assert (
        _verify_ocr_cache(
            cache,
            page_count=2,
            forced=True,
            requested_artifacts=first_batch,
            word_request_count=2,
        )
        == 4
    )


@pytest.mark.parametrize("rogue_name", ("unclassified.tsv", "unclassified.bin"))
def test_ocr_cache_refuses_an_unclassified_artifact(tmp_path: Path, rogue_name: str) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    for suffix in ("primary", "supplemental", "numeric"):
        (cache / f"page.{suffix}.tsv").write_bytes(b"")
    batch = frozenset(cache.iterdir())
    (cache / rogue_name).write_bytes(b"")

    with pytest.raises(CliContractError, match="OCR cache pass artifact is invalid"):
        _verify_ocr_cache(
            cache,
            page_count=1,
            forced=True,
            requested_artifacts=batch,
            word_request_count=1,
        )


def test_observed_ocr_binds_currency_artifact_to_the_requested_cache_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    pdf_bytes = source.read_bytes()
    source_sha = hashlib.sha256(pdf_bytes).hexdigest()

    class _Completed:
        returncode = 0
        stderr = b""

        def __init__(self, stdout: bytes) -> None:
            self.stdout = stdout

    def fake_launch(command: tuple[str, ...], **_kwargs: object) -> _Completed:
        return _Completed(b"tesseract 5.5.0\n" if "--version" in command else b"")

    monkeypatch.setattr("ccparser.evidence.ocr._launch_tesseract", fake_launch)
    cache = tmp_path / "cache"
    provider = cli_module._ObservedTesseractOcr(cache)
    clip = (0.0, 0.0, 20.0, 20.0)
    recognition_key = provider.cache_key(source_sha, 0, clip)
    expected = cache / f"{provider._currency_cache_key(recognition_key)}.currency.tsv"

    assert provider.extract_currency_symbol(pdf_bytes, source_sha, 0, clip) is None
    assert provider.currency_request_count == 1
    assert provider.requested_artifacts == frozenset((expected,))
    assert expected.is_file()


def test_ocr_cache_refuses_symlinks_and_unbounded_conditional_pages(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    for stem in ("page-1", "page-2"):
        for suffix in ("primary", "supplemental", "numeric"):
            (cache / f"{stem}.{suffix}.tsv").write_bytes(b"")

    with pytest.raises(CliContractError, match="OCR page cache mismatch"):
        _verify_ocr_cache(
            cache,
            page_count=1,
            forced=False,
            requested_artifacts=frozenset(cache.glob("*.tsv")),
            word_request_count=2,
        )

    for path in cache.iterdir():
        path.unlink()
    target = cache / "outside.tsv"
    target.write_bytes(b"")
    (cache / "page-1.primary.tsv").symlink_to(target)
    (cache / "page-1.supplemental.tsv").write_bytes(b"")
    (cache / "page-1.numeric.tsv").write_bytes(b"")
    with pytest.raises(CliContractError, match="OCR cache contains a symlink"):
        _verify_ocr_cache(
            cache,
            page_count=1,
            forced=True,
            requested_artifacts=frozenset(cache.glob("page-1.*.tsv")),
            word_request_count=1,
        )


@pytest.mark.parametrize("case", ("overlapping-evidence-outputs", "empty-model"))
def test_prepare_page_evidence_rejects_invalid_resources_before_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    source = private_root / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    row = frozen_row(
        document_id=hashlib.sha256(source.read_bytes()).hexdigest(),
        split=DatasetSplit.VALIDATION,
        source_pdf=source,
        bbox=(0.0, 10.0, 200.0, 40.0),
        baseline_type=RowType.STRUCTURAL,
        atoms=(),
    )
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("9", artifact_type="runtime"))
    models, dependencies = _inventory_files(
        private_root,
        with_model=case != "empty-model",
    )
    constructed: list[bool] = []

    def forbidden_provider(_cache: Path) -> None:
        constructed.append(True)
        raise AssertionError("OCR must not start")

    monkeypatch.setattr(
        "experiments.row_extraction.cli._ObservedTesseractOcr",
        forbidden_provider,
    )
    cache = private_root / "cache"
    evidence = cache / "evidence.jsonl"
    identity = evidence if case == "overlapping-evidence-outputs" else cache / "identity.json"
    result = _RUNNER.invoke(
        app,
        [
            "prepare-page-evidence",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "forced-page-ocr",
            "--runtime-identity",
            str(runtime),
            "--cache-dir",
            str(cache),
            "--output",
            str(evidence),
            "--identity-output",
            str(identity),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--inventory-output",
            str(private_root / "inventory.json"),
            "--preparation-output",
            str(private_root / "preparation.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_PAGE_EVIDENCE_ERROR\n"
    assert constructed == []
    assert not cache.exists()


@pytest.mark.parametrize(
    "case",
    ("document-hash-mismatch", "document-two-paths", "inode-two-documents"),
)
def test_prepare_page_evidence_rejects_source_mapping_before_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    first_source = private_root / "first.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(first_source)
    first_sha = hashlib.sha256(first_source.read_bytes()).hexdigest()
    first = frozen_row(
        document_id=first_sha,
        row_id="first-row",
        split=DatasetSplit.VALIDATION,
        source_pdf=first_source,
        bbox=(0.0, 10.0, 200.0, 40.0),
        baseline_type=RowType.STRUCTURAL,
        atoms=(),
    )
    rows_to_write = (first,)
    if case == "document-hash-mismatch":
        rows_to_write = (first.model_copy(update={"document_id": "f" * 64}),)
    else:
        second_source = private_root / "second.pdf"
        if case == "inode-two-documents":
            os.link(first_source, second_source)
            second_document_id = "f" * 64
        else:
            second_source.write_bytes(first_source.read_bytes())
            second_document_id = first_sha
        second = first.model_copy(
            update={
                "document_id": second_document_id,
                "row_id": "second-row",
                "source_pdf": second_source,
            }
        )
        rows_to_write = (first, second)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, rows_to_write)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("9", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root, with_model=True)
    constructed: list[bool] = []

    def forbidden_provider(_cache: Path) -> None:
        constructed.append(True)
        raise AssertionError("OCR must not start")

    monkeypatch.setattr(cli_module, "_ObservedTesseractOcr", forbidden_provider)
    cache = private_root / "cache"
    result = _RUNNER.invoke(
        app,
        [
            "prepare-page-evidence",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "forced-page-ocr",
            "--runtime-identity",
            str(runtime),
            "--cache-dir",
            str(cache),
            "--output",
            str(cache / "evidence.jsonl"),
            "--identity-output",
            str(cache / "identity.json"),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--inventory-output",
            str(private_root / "inventory.json"),
            "--preparation-output",
            str(private_root / "preparation.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_PAGE_EVIDENCE_ERROR\n"
    assert constructed == []
    assert not cache.exists()


@pytest.mark.parametrize("race", ("before-link", "after-link"))
def test_write_model_never_clobbers_or_cleans_a_foreign_race_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    target = tmp_path / "model.json"
    original_link = os.link

    def racing_link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        follow_symlinks: bool = True,
    ) -> None:
        destination_path = Path(destination)
        if race == "before-link":
            destination_path.write_bytes(b"foreign-before-link")
            raise FileExistsError
        original_link(source, destination, follow_symlinks=follow_symlinks)
        destination_path.unlink()
        destination_path.write_bytes(b"foreign-after-link")

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(CliContractError):
        cli_module._write_model(target, _identity("a"))

    assert target.read_bytes() == f"foreign-{race}".encode()
    assert tuple(tmp_path.glob(f".{target.name}.*.tmp")) == ()


def test_prepare_run_spec_refuses_test_without_echoing_private_arguments(tmp_path: Path) -> None:
    private_root = (tmp_path / "PRIVATE-root").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.TEST)
    rows = private_root / "PRIVATE-rows.jsonl"
    write_jsonl(rows, (row,))
    runtime = private_root / "runtime.json"
    manifest = private_root / "manifest.json"
    _write_identity(runtime, _identity("1"))
    _write_identity(manifest, _identity("2", artifact_type="jsonl", version="canonical-jsonl-v1"))
    models, dependencies = _inventory_files(private_root)
    result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "test",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(manifest),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(private_root / "combined.json"),
            "--output",
            str(private_root / "spec.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_SPEC_ERROR\n"
    assert "PRIVATE" not in result.stderr
    assert result.exception is not None
    assert result.exception.__cause__ is None


def test_prepare_run_spec_filters_rows_and_fixes_the_mode_resource_basis(
    tmp_path: Path,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    train = _structural_row(private_root, split=DatasetSplit.TRAIN)
    validation = _structural_row(private_root, split=DatasetSplit.VALIDATION).model_copy(
        update={"row_id": "validation-row"}
    )
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (train, validation))
    manifest = private_root / "manifest.json"
    runtime = private_root / "runtime.json"
    _write_identity(
        manifest,
        _identity("1", artifact_type="jsonl", version="canonical-jsonl-v1"),
    )
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root, with_model=True)
    output = private_root / "spec.json"

    result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "forced-page-ocr",
            "--arm-manifest-identity",
            str(manifest),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(private_root / "combined.json"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    spec = ResourceSpec.model_validate_json(output.read_bytes())
    assert spec.experiment_id == "forced-page-ocr"
    assert spec.config_id == (
        "fixed-page-evidence-v1:production-forced-whole-page-tesseract-v1:"
        "unique-intersection-ownership-v1"
    )
    assert spec.resource_basis == "end-to-end-method"
    assert spec.expected_row_count == 1
    assert spec.split is DatasetSplit.VALIDATION
    assert spec.row_sequence_identity.artifact_type == "frozen-row-sequence"
    assert not spec.cache_root.exists()


@pytest.mark.parametrize(
    ("mode", "with_model"),
    (("accepted-baseline", True), ("conditional-page-ocr", False)),
)
def test_prepare_run_spec_enforces_mode_model_inventory_contract(
    tmp_path: Path,
    mode: str,
    with_model: bool,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    manifest = private_root / "manifest.json"
    runtime = private_root / "runtime.json"
    _write_identity(
        manifest,
        _identity("1", artifact_type="jsonl", version="canonical-jsonl-v1"),
    )
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root, with_model=with_model)

    result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            mode,
            "--arm-manifest-identity",
            str(manifest),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(private_root / "combined.json"),
            "--output",
            str(private_root / "spec.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_SPEC_ERROR\n"


@pytest.mark.parametrize("collision", ("spec", "inventory"))
def test_prepare_run_spec_rejects_cache_output_overlap_before_writing(
    tmp_path: Path,
    collision: str,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    manifest = private_root / "manifest.json"
    runtime = private_root / "runtime.json"
    _write_identity(
        manifest,
        _identity("1", artifact_type="jsonl", version="canonical-jsonl-v1"),
    )
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    cache = private_root / "cache"
    spec_output = cache if collision == "spec" else private_root / "spec.json"
    inventory_output = cache if collision == "inventory" else private_root / "combined.json"

    result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(manifest),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(cache),
            "--inventory-output",
            str(inventory_output),
            "--output",
            str(spec_output),
        ],
    )

    assert result.exit_code == 1
    assert not spec_output.exists()
    assert not inventory_output.exists()


def test_run_accepted_baseline_validates_the_complete_artifact_then_selects_split(
    tmp_path: Path,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    train = _structural_row(private_root, split=DatasetSplit.TRAIN)
    validation = _structural_row(private_root, split=DatasetSplit.VALIDATION).model_copy(
        update={"row_id": "validation-row"}
    )
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (train, validation))
    baseline = private_root / "accepted.jsonl"
    baseline_stream_identity = write_jsonl(
        baseline,
        (_structural_prediction(train), _structural_prediction(validation)),
    )
    baseline_identity = private_root / "accepted.identity.json"
    _write_identity(baseline_identity, baseline_stream_identity)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    spec_path = private_root / "spec.json"
    prepare_result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(baseline_identity),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(private_root / "combined.json"),
            "--output",
            str(spec_path),
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stderr
    predictions_output = private_root / "predictions.jsonl"
    run_output = private_root / "run.json"

    result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            "accepted-baseline",
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(baseline),
            "--baseline-identity",
            str(baseline_identity),
            "--resource-spec",
            str(spec_path),
            "--predictions-output",
            str(predictions_output),
            "--run-output",
            str(run_output),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    published = tuple(read_jsonl(predictions_output, RowPrediction))
    assert tuple(prediction.row_id for prediction in published) == (validation.row_id,)
    measurements = RunMeasurements.model_validate_json(run_output.read_bytes())
    assert measurements.arm_manifest_identity == baseline_stream_identity
    assert measurements.resource_basis == "materialized-adapter"
    assert measurements.row_count == 1


@pytest.mark.parametrize("case", ("nonempty-model", "identity-mismatch"))
def test_run_accepted_baseline_rechecks_model_inventory_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    baseline = private_root / "accepted.jsonl"
    baseline_stream_identity = write_jsonl(baseline, (_structural_prediction(row),))
    baseline_identity = private_root / "accepted.identity.json"
    _write_identity(baseline_identity, baseline_stream_identity)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    valid_spec_path = private_root / "valid-spec.json"
    prepare_result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(baseline_identity),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "valid-cache"),
            "--inventory-output",
            str(private_root / "valid-combined.json"),
            "--output",
            str(valid_spec_path),
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stderr
    spec = ResourceSpec.model_validate_json(valid_spec_path.read_bytes())
    if case == "nonempty-model":
        model_asset = private_root / "forged-model.bin"
        model_asset.write_bytes(b"forged-model")
        forged_models = build_resource_inventory(
            InventoryRoots(
                version="row-resource-roots-v1",
                category="model",
                roots=(model_asset,),
            )
        )
        forged_models_path = private_root / "forged-models.json"
        _write_model(forged_models_path, forged_models.model_dump(mode="json"))
        spec = spec.model_copy(
            update={
                "model_inventory_path": forged_models_path,
                "model_inventory_identity": _inventory_identity(forged_models_path),
            }
        )
    else:
        spec = spec.model_copy(
            update={
                "model_inventory_identity": spec.model_inventory_identity.model_copy(
                    update={"sha256": "f" * 64}
                )
            }
        )
    spec = spec.model_copy(
        update={
            "cache_root": private_root / f"{case}.cache",
            "resource_inventory_output": private_root / f"{case}.combined.json",
        }
    )
    forged_spec_path = private_root / f"{case}.spec.json"
    _write_model(forged_spec_path, spec.model_dump(mode="json"))
    called: list[bool] = []

    def forbidden_run(*_args: object, **_kwargs: object) -> RunMeasurements:
        called.append(True)
        raise AssertionError("execution must not start")

    monkeypatch.setattr(cli_module, "run_arm", forbidden_run)
    result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            "accepted-baseline",
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(baseline),
            "--baseline-identity",
            str(baseline_identity),
            "--resource-spec",
            str(forged_spec_path),
            "--predictions-output",
            str(private_root / f"{case}.predictions.jsonl"),
            "--run-output",
            str(private_root / f"{case}.run.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_BASELINE_ERROR\n"
    assert called == []


def test_run_accepted_baseline_rejects_wrong_type_outside_selected_split(
    tmp_path: Path,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    train = _structural_row(private_root, split=DatasetSplit.TRAIN)
    validation = _structural_row(private_root, split=DatasetSplit.VALIDATION).model_copy(
        update={"row_id": "validation-row"}
    )
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (train, validation))
    baseline = private_root / "accepted.jsonl"
    forged_train = _structural_prediction(train).model_copy(
        update={"predicted_type": RowType.AMBIGUOUS}
    )
    baseline_stream_identity = write_jsonl(
        baseline,
        (forged_train, _structural_prediction(validation)),
    )
    baseline_identity = private_root / "accepted.identity.json"
    _write_identity(baseline_identity, baseline_stream_identity)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    spec_path = private_root / "spec.json"
    prepare_result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(baseline_identity),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(private_root / "combined.json"),
            "--output",
            str(spec_path),
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stderr

    result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            "accepted-baseline",
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(baseline),
            "--baseline-identity",
            str(baseline_identity),
            "--resource-spec",
            str(spec_path),
            "--predictions-output",
            str(private_root / "predictions.jsonl"),
            "--run-output",
            str(private_root / "run.json"),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_BASELINE_ERROR\n"
    assert not (private_root / "predictions.jsonl").exists()
    assert not (private_root / "combined.json").exists()


def test_run_baseline_rejects_measurement_output_overlapping_cache_before_publication(
    tmp_path: Path,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    baseline = private_root / "accepted.jsonl"
    baseline_stream_identity = write_jsonl(baseline, (_structural_prediction(row),))
    baseline_identity = private_root / "accepted.identity.json"
    _write_identity(baseline_identity, baseline_stream_identity)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    spec_path = private_root / "spec.json"
    cache = private_root / "cache"
    inventory_output = private_root / "combined.json"
    prepare_result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(baseline_identity),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(cache),
            "--inventory-output",
            str(inventory_output),
            "--output",
            str(spec_path),
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stderr
    predictions_output = private_root / "predictions.jsonl"

    result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            "accepted-baseline",
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(baseline),
            "--baseline-identity",
            str(baseline_identity),
            "--resource-spec",
            str(spec_path),
            "--predictions-output",
            str(predictions_output),
            "--run-output",
            str(cache),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_BASELINE_ERROR\n"
    assert not cache.exists()
    assert not predictions_output.exists()
    assert not inventory_output.exists()


@pytest.mark.parametrize("foreign_replacement", (False, True))
def test_run_baseline_rolls_back_owned_publications_when_measurement_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foreign_replacement: bool,
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    rows = private_root / "rows.jsonl"
    write_jsonl(rows, (row,))
    baseline = private_root / "accepted.jsonl"
    baseline_stream_identity = write_jsonl(baseline, (_structural_prediction(row),))
    baseline_identity = private_root / "accepted.identity.json"
    _write_identity(baseline_identity, baseline_stream_identity)
    runtime = private_root / "runtime.json"
    _write_identity(runtime, _identity("2", artifact_type="runtime"))
    models, dependencies = _inventory_files(private_root)
    spec_path = private_root / "spec.json"
    inventory_output = private_root / "combined.json"
    prepare_result = _RUNNER.invoke(
        app,
        [
            "prepare-run-spec",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--mode",
            "accepted-baseline",
            "--arm-manifest-identity",
            str(baseline_identity),
            "--runtime-identity",
            str(runtime),
            "--model-inventory",
            str(models),
            "--dependency-inventory",
            str(dependencies),
            "--cache-root",
            str(private_root / "cache"),
            "--inventory-output",
            str(inventory_output),
            "--output",
            str(spec_path),
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stderr
    predictions_output = private_root / "predictions.jsonl"
    run_output = private_root / "run.json"
    original_write_model = cli_module._write_model

    def failed_measurement_write(path: Path, model: BaseModel) -> None:
        if path != run_output:
            original_write_model(path, model)
            return
        if foreign_replacement:
            predictions_output.unlink()
            predictions_output.write_bytes(b"foreign-predictions")
            inventory_output.unlink()
            inventory_output.write_bytes(b"foreign-inventory")
            run_output.write_bytes(b"foreign-measurement")
        raise OSError("PRIVATE write failure")

    monkeypatch.setattr(cli_module, "_write_model", failed_measurement_write)
    result = _RUNNER.invoke(
        app,
        [
            "run-baseline",
            "--private-root",
            str(private_root),
            "--mode",
            "accepted-baseline",
            "--rows",
            str(rows),
            "--split",
            "validation",
            "--baseline-input",
            str(baseline),
            "--baseline-identity",
            str(baseline_identity),
            "--resource-spec",
            str(spec_path),
            "--predictions-output",
            str(predictions_output),
            "--run-output",
            str(run_output),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_RUN_BASELINE_ERROR\n"
    if foreign_replacement:
        assert predictions_output.read_bytes() == b"foreign-predictions"
        assert inventory_output.read_bytes() == b"foreign-inventory"
        assert run_output.read_bytes() == b"foreign-measurement"
    else:
        assert not predictions_output.exists()
        assert not inventory_output.exists()
        assert not run_output.exists()


def test_score_writes_a_report_with_unavailable_ocr_metrics(tmp_path: Path) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    row = _structural_row(private_root, split=DatasetSplit.VALIDATION)
    label = GoldRow(
        document_id=row.document_id,
        row_id=row.row_id,
        row_type=RowType.STRUCTURAL,
        fields=(),
    )
    prediction = _structural_prediction(row)
    rows = private_root / "rows.jsonl"
    labels = private_root / "labels.jsonl"
    predictions = private_root / "predictions.jsonl"
    write_jsonl(rows, (row,))
    write_jsonl(labels, (label,))
    prediction_identity = write_jsonl(predictions, (prediction,))
    run = _run_measurements(row, prediction_identity)
    run_path = private_root / "run.json"
    _write_model(run_path, run.model_dump(mode="json"))
    context = ReportContext(
        experiment_id=run.experiment_id,
        config_id=run.config_id,
        measurement_protocol=run.measurement_protocol,
        runtime_identity=run.runtime_identity,
        python_version="3.13",
        public_runtime_versions=(),
    )
    context_path = private_root / "context.json"
    _write_model(context_path, context.model_dump(mode="json"))
    output = private_root / "report.json"

    result = _RUNNER.invoke(
        app,
        [
            "score",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--labels",
            str(labels),
            "--predictions",
            str(predictions),
            "--context",
            str(context_path),
            "--run",
            str(run_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["metrics"]["ocr_cer"] is None
    assert report["metrics"]["ocr_wer"] is None
    serialized = json.dumps(report, sort_keys=True)
    assert row.row_id not in serialized
    assert str(private_root) not in serialized
    assert prediction_identity.sha256 not in serialized


def test_cli_sanitizes_internal_exceptions_without_chaining(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = (tmp_path / "private").resolve()
    private_root.mkdir()
    rows = private_root / "rows.jsonl"
    labels = private_root / "labels.jsonl"
    rows.write_text("PRIVATE-ROW-VALUE")
    labels.write_text("PRIVATE-LABEL-VALUE")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("PRIVATE-IDENTITY PRIVATE-AMOUNT")

    monkeypatch.setattr("experiments.row_extraction.cli.validate_annotations", fail)
    result = _RUNNER.invoke(
        app,
        [
            "validate",
            "--private-root",
            str(private_root),
            "--rows",
            str(rows),
            "--labels",
            str(labels),
        ],
    )

    assert result.exit_code == 1
    assert result.stderr == "ROW_CLI_VALIDATE_ERROR\n"
    assert "PRIVATE" not in result.stderr
    assert result.exception is not None
    assert result.exception.__cause__ is None


def test_assert_repeated_output_compares_bytes_without_exposing_paths(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    prediction = _structural_prediction(_structural_row(tmp_path, split=DatasetSplit.TRAIN))
    write_jsonl(first, (prediction,))
    write_jsonl(second, (prediction,))
    assert_repeated_output(first, second)

    second.write_bytes(b"different")
    with pytest.raises(ValueError, match="repeated prediction output mismatch") as caught:
        assert_repeated_output(first, second)
    assert str(tmp_path) not in str(caught.value)
    assert caught.value.__cause__ is None


def test_assert_repeated_output_delegates_canonical_distinct_file_contract(
    tmp_path: Path,
) -> None:
    row = _structural_row(tmp_path, split=DatasetSplit.TRAIN)
    prediction = _structural_prediction(row)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    write_jsonl(first, (prediction,))
    write_jsonl(second, (prediction,))
    assert_repeated_output(first, second)

    with pytest.raises(ValueError, match="repeated prediction output is invalid"):
        assert_repeated_output(first, first)

    first.write_bytes(b"not-canonical-jsonl\n")
    second.write_bytes(b"not-canonical-jsonl\n")
    with pytest.raises(ValueError, match="repeated prediction output is not canonical"):
        assert_repeated_output(first, second)
