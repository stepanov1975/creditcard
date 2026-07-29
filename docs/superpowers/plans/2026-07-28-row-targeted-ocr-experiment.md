# Per-Row Targeted OCR Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build experiment 1 as an isolated, deterministic per-row Tesseract OCR lane that measures exact merchant and transaction-field accuracy, OCR CER/WER, omissions, hallucinations, ownership errors, latency, RSS, and repeatability while row identities and bounds remain fixed.

**Architecture:** Implement a read-only `ExperimentArm` under `experiments.row_extraction/arms/ocr/` that renders only shared-foundation fixed rows, performs a predeclared sequential Tesseract sweep, maps positioned tokens back to page coordinates, and emits evidence-backed `RowPrediction` records through shared codecs. Keep selection, validation freeze, deterministic replay, and the privacy-safe checkpoint in lane-owned modules; use the shared runner and metric implementation unchanged, store every corpus-derived artifact in an ignored lane root, and never call production row detection.

**Tech Stack:** Python 3.13, repository `.venv`, PyMuPDF, local Tesseract 5 TSV output with pinned `heb` and `eng` traineddata, shared Pydantic contracts in `experiments.row_extraction`, `Decimal`-safe shared validation/metrics, pytest, Ruff, and mypy.

## Global Constraints

- Scope answer: YES.
- Program component: experiment 1.
- Measured effect: complete-row exact match, merchant exact/normalized accuracy, per-field exact accuracy, OCR CER/WER, omission rate, hallucination rate, unsupported-evidence and ownership-collision rate, abstention behavior, p50/p95 latency, throughput, subprocess count, peak RSS, cache bytes, and byte-identical canonical prediction repeatability.
- Fixed inputs: accepted comparison anchor `dee4b071ad65231da13825f2f7c74a488ca96c7c`; reviewed `FrozenRow` identities, bboxes, continuation context, and source render version; immutable document-disjoint split; reviewed labels; accepted column bands for recognition-only comparisons; accepted and forced whole-page baseline predictions; shared contracts, codecs, runner, metrics, renderer/validator semantics, and worker count from the frozen foundation commit.
- Allowed tracked files: `experiments/row_extraction/arms/ocr/**` and `tests/experiments/row_extraction/arms/ocr/**` only. Shared `experiments/row_extraction` modules and all production `src/**` files are read-only.
- Allowed private files: `/root/creditcard/artifacts/row-extraction/experiment-1-ocr/**` only. Shared private inputs under `/root/creditcard/artifacts/row-extraction/shared/**` are read-only.
- Stop condition: stop and return a foundation proposal if the lane requires row addition/removal/splitting/merging/movement, a shared-contract mutation, a document/issuer/template/merchant/filename/path/hash/date/amount/total-specific predictive rule, neural OCR, production `src/**` changes, cloud processing, or any private artifact outside the declared roots.
- Start implementation only after the shared foundation is reviewed and committed, then create isolated branch `codex/row-extraction-ocr` from the exact SHA recorded in `/root/creditcard/artifacts/row-extraction/shared/foundation-identity.json` using `superpowers:using-git-worktrees`.
- Use a sequential sweep, never a Cartesian search: crop contract, language order, DPI, Tesseract thresholding, fixed-field crops/fixed-row cell reconstruction, then traineddata. Carry one validation-approved incumbent between stages.
- Train/development selects one challenger per stage; validation compares only that challenger with the prior incumbent. This lane never opens `DatasetSplit.TEST`; only the central comparison plan may run the frozen arm on it.
- `ExperimentArm.predict()` may consume `FrozenRow.source_pdf` only to locate its private source artifact. It may not use the document ID, source path, filename, hash, page ordinal, continuation IDs/gaps, or configuration-specific artifact location as a predictive feature.
- `FieldProposal` contains only a role, nonempty exact evidence atom IDs, optional source region, raw score, and optional fixed owner row ID. Recognized strings live in `RowPrediction.evidence_atoms`, never as authoritative values in proposals. Shared deterministic field rendering and typed validation remain authoritative.
- Use `Decimal` only through shared financial parsers and metrics; do not introduce binary floating-point financial arithmetic.
- Keep raw PDFs, crops, TSV, candidate atoms, predictions, gold, baseline outputs, caches, runtime measurements, metric reports, artifact hashes, and freeze/handoff manifests ignored and private. Commands must print only aggregate counts/status and never source names, merchant text, dates, amounts, totals, row IDs, or private hashes.
- Tesseract commands are argument tuples executed without a shell. Pin executable version, Leptonica version, language order, PSM, threshold settings, traineddata SHA-256 values, DPI, raster padding, source-render identity, worker count, and cache schema in every configuration identity.
- Synthetic tracked tests may use invented Latin/Hebrew words and invented nonfinancial digits. They must not copy private document content or derived values.
- Before every task commit run `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy src`, `.venv/bin/mypy experiments/row_extraction/arms/ocr`, and `.venv/bin/pytest -q`.
- The established full-suite baseline has exactly five inherited out-of-scope sandbox/controller failures. Every task still runs the full suite, requires the failure set to remain identical, then runs `.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py` and requires it to pass. Any new or changed failure stops the lane; no task claims the inherited failures are green.
- Experiment results are not parser integration and not corpus acceptance. Do not modify normal parsing, emit a production recommendation, run the private production corpus gate, or claim all-document success.

---

## Shared Foundation Interfaces to Reconcile Before Task 1

The foundation is read-only to this lane. The plan consumes these exact exports supplied by the foundation owner:

```python
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    ColumnBand,
    DatasetSplit,
    Decision,
    EvidenceAtom,
    ExperimentArm,
    FieldProposal,
    FieldRole,
    FrozenRow,
    GoldField,
    GoldRow,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from experiments.row_extraction.metrics import MetricReport, score_predictions
from experiments.row_extraction.runner import (
    MeasuredArmFactory,
    PredictionSink,
    ResourceSpec,
    RunMeasurements,
    run_arm,
)
```

Required signatures are:

```python
class ExperimentArm(Protocol):
    @property
    def experiment_id(self) -> str: ...

    @property
    def config_id(self) -> str: ...

    def predict(self, row: FrozenRow) -> RowPrediction: ...


def run_arm(
    rows: Iterable[FrozenRow],
    factory: MeasuredArmFactory,
    sink: PredictionSink,
    resource_spec: ResourceSpec,
) -> RunMeasurements: ...


def score_predictions(
    rows: Sequence[FrozenRow],
    gold: Sequence[GoldRow],
    predictions: Sequence[RowPrediction],
) -> MetricReport: ...
```

The lane also expects the frozen foundation models/codecs to expose the following concrete read-only fields and streaming operations. Reconcile names once in Task 1; if semantics differ, stop for a foundation change rather than add an adapter that weakens the contract:

- `BBox` is `(x0: float, y0: float, x1: float, y1: float)` in page display points.
- `FrozenRow` is `FrozenRow(document_id: str, row_id: str, split: DatasetSplit, source_pdf: Path, page_number: int, bbox: BBox, baseline_type: RowType, column_bands: tuple[ColumnBand, ...], atoms: tuple[EvidenceAtom, ...], render_version: str, previous_row_id: str | None = None, next_row_id: str | None = None, gap_before: float | None = None, gap_after: float | None = None)`. `baseline_type` is accepted-anchor structural context, not gold; experiment 1 copies it to its output but never uses it as an OCR feature.
- `ColumnBand` is `ColumnBand(index: int, role: FieldRole | None, bbox: BBox)` in the same coordinate system.
- `EvidenceAtom` is `EvidenceAtom(atom_id: str, text: str, bbox: BBox, source: Literal["digital", "ocr"], confidence: float, column_index: int | None = None)`.
- `FieldProposal` is `FieldProposal(role: FieldRole, atom_ids: tuple[str, ...], source_region: BBox | None = None, owner_row_id: str | None = None, raw_score: float)` and requires nonempty `atom_ids`.
- `RowPrediction` is `RowPrediction(experiment_id: str, config_id: str, document_id: str, row_id: str, predicted_type: RowType, evidence_atoms: tuple[EvidenceAtom, ...], proposals: tuple[FieldProposal, ...], exact_row_confidence: float | None, decision: Decision, reasons: tuple[str, ...])`. Its evidence ledger is complete support for all proposal IDs; the shared validator rejects missing or duplicate IDs.
- `Decision` provides `ACCEPT`, `ABSTAIN`, `REJECT`, and `IGNORE`; `DatasetSplit` provides `TRAIN`, `VALIDATION`, and `TEST`; `LaneDisposition` provides `FROZEN_ELIGIBLE` and `VALIDATION_STOPPED`.
- `ArtifactIdentity` is `ArtifactIdentity(artifact_type: str, sha256: str, version: str, byte_size: int)` and has canonical JSON serialization.
- `MetricReport` exposes `row_count`, `exact_rows`, `exact_row_rate`, `row_type_correct`, `row_type_accuracy`, `row_type_macro_f1`, `row_types`, `row_type_confusion`, `fields: Mapping[FieldRole, FieldMetric]`, `accepted_rows`, `abstained_rows`, `rejected_rows`, `ignored_rows`, `unsupported_evidence`, `ownership_collisions`, `ocr_cer`, `ocr_wer`, `calibration_bins`, `brier_score`, `log_loss`, `expected_calibration_error`, `risk_coverage`, `area_under_risk_coverage`, and `coverage_at_risk`. `FieldMetric` exposes `role`, `eligible_rows`, `exact_matches`, `normalized_matches`, `omissions`, `hallucinations`, `exact_rate`, `normalized_rate`, `omission_rate`, and `hallucination_rate`. `sweep.py` creates the static identity-bound `ResourceSpec`; the shared runner measures the same execution whose predictions it publishes. `RunMeasurements` exposes `experiment_id`, `config_id`, `row_sequence_identity`, `split`, `cache_policy`, `resource_basis`, `arm_manifest_identity`, `row_count`, `total_ns`, `p50_ns`, `p95_ns`, `preparation_ns`, `end_to_end_ns`, `cold_start_ns`, `throughput_rows_per_second`, `peak_rss_bytes`, `model_bytes`, `dependency_bytes`, `cache_bytes`, `subprocess_count`, `worker_count`, `measurement_protocol`, `runtime_identity`, `model_inventory_identity`, `dependency_inventory_identity`, `resource_inventory_identity`, and `predictions_sha256`.
- `experiments.row_extraction.codecs` provides `write_jsonl(path: Path, records: Iterable[BaseModel]) -> ArtifactIdentity` and `read_jsonl(path: Path, model: type[T]) -> Iterator[T]`; the shared runner provides `JsonlPredictionSink`. `score_predictions(rows, gold, predictions)` resolves every proposal through the complete `RowPrediction.evidence_atoms` ledger and uses the rows only for frozen ownership/region validation, so no OCR text sidecar or mutable registry is allowed.
- Shared synthetic constructors are `tests.experiments.row_extraction.factories.frozen_row()` and `tests.experiments.row_extraction.factories.gold_row()`.

## File Structure

- `experiments/row_extraction/arms/ocr/__init__.py`: narrow public lane exports.
- `experiments/row_extraction/arms/ocr/config.py`: immutable OCR configuration, sequential stage values, command construction, and content identity.
- `experiments/row_extraction/arms/ocr/crop.py`: fixed-bbox PDF rendering, deterministic white raster padding, and pixel/page coordinate transforms.
- `experiments/row_extraction/arms/ocr/tesseract.py`: local subprocess execution, TSV parsing, conservative three-pass fusion, content-addressed cache, and stable OCR evidence atoms.
- `experiments/row_extraction/arms/ocr/assignment.py`: fixed-column ownership and fixed-row-only cell reconstruction; never row clustering.
- `experiments/row_extraction/arms/ocr/arm.py`: `ExperimentArm` implementation that composes source lookup, rendering, OCR, assignment, the complete prediction evidence ledger, and abstention.
- `experiments/row_extraction/arms/ocr/selection.py`: deterministic admissibility and sequential winner selection from shared metric/resource reports.
- `experiments/row_extraction/arms/ocr/sweep.py`: exact stage matrix and development-to-validation orchestration.
- `experiments/row_extraction/arms/ocr/freeze.py`: exclusive validation-freeze manifest and frozen-config verification.
- `experiments/row_extraction/arms/ocr/checkpoint.py`: canonical handoff and the charter's eight-section privacy-safe checkpoint.
- `experiments/row_extraction/arms/ocr/cli.py` and `__main__.py`: private lane commands with locked-split guards and aggregate-only stdout.
- `tests/experiments/row_extraction/arms/ocr/`: one focused test module per lane responsibility plus a synthetic end-to-end test.

### Task 1: Lock shared-contract compatibility and OCR configuration identity

```text
Scope answer: YES
Program component: experiment 1
Measured effect: configuration isolation and deterministic experiment identity for all OCR accuracy/resource measurements
Fixed inputs: accepted SHA, shared contract signatures, fixed rows/splits/labels/columns, predeclared ablation values
Allowed files: experiments/row_extraction/arms/ocr/__init__.py, experiments/row_extraction/arms/ocr/config.py, tests/experiments/row_extraction/arms/ocr/test_config.py
Stop condition: stop if shared contracts cannot represent lane-created evidence, fixed rows, predictions, or artifact identities without mutation
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/__init__.py`
- Create: `experiments/row_extraction/arms/ocr/config.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_config.py`

**Interfaces:**
- Consumes: the shared exports and field semantics listed in “Shared Foundation Interfaces”; `ArtifactIdentity` remains read-only metadata.
- Produces: `Thresholding`, `CropMode`, `AssignmentMode`, `OcrConfig`, `build_tesseract_commands(config, tessdata_dir) -> tuple[tuple[str, ...], ...]`, and stable `OcrConfig.config_id`.
- Preserves: no filenames, paths, document IDs, row IDs, page numbers, merchants, dates, amounts, or private values enter `OcrConfig` or command-selection logic.

- [ ] **Step 1: Write the failing contract/configuration tests**

Create `tests/experiments/row_extraction/arms/ocr/test_config.py` with:

```python
from experiments.row_extraction.arms.ocr.config import (
    AssignmentMode,
    CropMode,
    OcrConfig,
    Thresholding,
    build_tesseract_commands,
)
from experiments.row_extraction.contracts import ExperimentArm, FieldProposal, RowPrediction
from tests.experiments.row_extraction.factories import frozen_row


def test_shared_contracts_needed_by_ocr_lane_are_importable() -> None:
    assert ExperimentArm is not None
    assert "atom_ids" in FieldProposal.model_fields
    assert "source_region" in FieldProposal.model_fields
    assert "owner_row_id" in FieldProposal.model_fields
    assert "evidence_atoms" in RowPrediction.model_fields
    assert "proposals" in RowPrediction.model_fields
    row = frozen_row()
    assert row.previous_row_id is None
    assert row.next_row_id is None
    assert row.gap_before is None
    assert row.gap_after is None


def test_ocr_config_identity_covers_every_recognition_input() -> None:
    base = OcrConfig(
        dpi=300,
        padding_px=5,
        row_psm=7,
        field_psm=7,
        languages="heb+eng",
        thresholding=Thresholding.INTERNAL_OTSU,
        crop_mode=CropMode.WHOLE_ROW,
        assignment_mode=AssignmentMode.FIXED_COLUMNS,
        traineddata_sha256=(("eng", "1" * 64), ("heb", "2" * 64)),
        cache_schema="row-ocr-v1",
    )

    assert base.config_id == base.config_id
    assert base.config_id != base.with_updates(padding_px=10).config_id
    assert base.config_id != base.with_updates(languages="eng+heb").config_id
    assert base.config_id != base.with_updates(thresholding=Thresholding.SAUVOLA).config_id


def test_commands_are_local_argument_tuples_and_keep_numeric_pass_english() -> None:
    config = OcrConfig.baseline((('eng', '1' * 64), ('heb', '2' * 64)))

    assert build_tesseract_commands(config, "/private/tessdata") == (
        (
            "tesseract", "stdin", "stdout", "--tessdata-dir", "/private/tessdata",
            "-l", "heb+eng", "--oem", "1", "--psm", "6", "tsv",
        ),
        (
            "tesseract", "stdin", "stdout", "--tessdata-dir", "/private/tessdata",
            "-l", "eng", "--oem", "1", "--psm", "6", "tsv",
        ),
        (
            "tesseract", "stdin", "stdout", "--tessdata-dir", "/private/tessdata",
            "-l", "eng", "--oem", "1", "--psm", "6", "-c",
            "tessedit_char_whitelist=0123456789.,/-+()", "tsv",
        ),
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_config.py
```

Expected: FAIL during collection because `experiments.row_extraction.arms.ocr.config` does not exist. If the shared-contract assertion fails after the module exists, stop and return the exact missing foundation field; do not change shared code in this lane.

- [ ] **Step 3: Implement immutable configuration and exact command construction**

Create `experiments/row_extraction/arms/ocr/config.py` with these public types and validations:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum


class Thresholding(StrEnum):
    INTERNAL_OTSU = "internal-otsu"
    ADAPTIVE_OTSU = "adaptive-otsu"
    SAUVOLA = "sauvola"


class CropMode(StrEnum):
    WHOLE_ROW = "whole-row"
    FIXED_FIELDS = "fixed-fields"


class AssignmentMode(StrEnum):
    FIXED_COLUMNS = "fixed-columns"
    FIXED_ROW_CELLS = "fixed-row-cells"


@dataclass(frozen=True, slots=True)
class OcrConfig:
    dpi: int
    padding_px: int
    row_psm: int
    field_psm: int
    languages: str
    thresholding: Thresholding
    crop_mode: CropMode
    assignment_mode: AssignmentMode
    traineddata_sha256: tuple[tuple[str, str], ...]
    cache_schema: str

    def __post_init__(self) -> None:
        if self.dpi not in {300, 400, 450}:
            raise ValueError("dpi must be one of 300, 400, or 450")
        if self.padding_px not in {0, 5, 10}:
            raise ValueError("padding_px must be one of 0, 5, or 10")
        if self.row_psm not in {6, 7, 13} or self.field_psm not in {7, 13}:
            raise ValueError("unsupported Tesseract page-segmentation mode")
        if self.languages not in {"heb+eng", "eng+heb"}:
            raise ValueError("languages must contain the pinned Hebrew and English packs")
        if tuple(name for name, _ in self.traineddata_sha256) != ("eng", "heb"):
            raise ValueError("traineddata identities must be sorted as eng then heb")
        if any(len(digest) != 64 for _, digest in self.traineddata_sha256):
            raise ValueError("traineddata SHA-256 values must contain 64 hex characters")

    @classmethod
    def baseline(cls, traineddata: tuple[tuple[str, str], ...]) -> OcrConfig:
        return cls(
            dpi=300,
            padding_px=0,
            row_psm=6,
            field_psm=7,
            languages="heb+eng",
            thresholding=Thresholding.INTERNAL_OTSU,
            crop_mode=CropMode.WHOLE_ROW,
            assignment_mode=AssignmentMode.FIXED_COLUMNS,
            traineddata_sha256=traineddata,
            cache_schema="row-ocr-v1",
        )

    def with_updates(self, **changes: object) -> OcrConfig:
        return replace(self, **changes)

    @property
    def config_id(self) -> str:
        payload = asdict(self)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"ocr-{hashlib.sha256(encoded).hexdigest()}"


def _threshold_args(value: Thresholding) -> tuple[str, ...]:
    return {
        Thresholding.INTERNAL_OTSU: (),
        Thresholding.ADAPTIVE_OTSU: ("-c", "thresholding_method=1"),
        Thresholding.SAUVOLA: ("-c", "thresholding_method=2"),
    }[value]


def _command(
    *, languages: str, psm: int, tessdata_dir: str, thresholding: Thresholding,
    whitelist: str | None = None,
) -> tuple[str, ...]:
    command = (
        "tesseract", "stdin", "stdout", "--tessdata-dir", tessdata_dir,
        "-l", languages, "--oem", "1", "--psm", str(psm),
        *_threshold_args(thresholding),
    )
    if whitelist is not None:
        command += ("-c", f"tessedit_char_whitelist={whitelist}")
    return (*command, "tsv")


def build_tesseract_commands(
    config: OcrConfig,
    tessdata_dir: str,
) -> tuple[tuple[str, ...], ...]:
    psm = config.field_psm if config.crop_mode is CropMode.FIXED_FIELDS else config.row_psm
    return (
        _command(
            languages=config.languages,
            psm=psm,
            tessdata_dir=tessdata_dir,
            thresholding=config.thresholding,
        ),
        _command(
            languages="eng",
            psm=psm,
            tessdata_dir=tessdata_dir,
            thresholding=config.thresholding,
        ),
        _command(
            languages="eng",
            psm=psm,
            tessdata_dir=tessdata_dir,
            thresholding=config.thresholding,
            whitelist="0123456789.,/-+()",
        ),
    )
```

Export only the lane arm/config types from `__init__.py`; add `OcrExperimentArm` after Task 4 rather than exporting internal helpers.

- [ ] **Step 4: Verify GREEN and type safety**

Run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr tests/experiments/row_extraction/arms/ocr
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_config.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/config.py tests/experiments/row_extraction/arms/ocr/test_config.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/config.py
```

Expected: all commands pass; configuration identities change for every recognition variable and command tuples exactly match the intended local three-pass baseline.

- [ ] **Step 5: Run repository verification and commit Task 1**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/__init__.py experiments/row_extraction/arms/ocr/config.py tests/experiments/row_extraction/arms/ocr/test_config.py
git commit -m "experiment: define deterministic row OCR configurations"
```

Expected: Ruff, mypy, focused, and extraction-relevant tests pass; the full-suite failure set
is either green after an upstream fix or exactly the five inherited controller failures. The
commit contains only Task 1 files.

### Task 2: Render fixed row and fixed-field crops with reversible coordinates

```text
Scope answer: YES
Program component: experiment 1
Measured effect: crop truncation/contamination, OCR CER/WER, field ownership, rendered bytes, cache size, and latency under fixed row bounds
Fixed inputs: FrozenRow row_id/bbox/page_number/render_version, accepted ColumnBand geometry, shared private source bytes, accepted display coordinate system
Allowed files: experiments/row_extraction/arms/ocr/crop.py, tests/experiments/row_extraction/arms/ocr/test_crop.py
Stop condition: stop if correct rendering requires moving/splitting/merging rows, reading an undeclared private root, or changing production PDF/OCR code
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/crop.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_crop.py`

**Interfaces:**
- Consumes: shared `BBox`; PDF bytes selected operationally by opaque document ID; `OcrConfig.dpi` and `padding_px`.
- Produces: `RenderedCrop`, `render_clip(pdf_bytes, page_index, clip, dpi, padding_px) -> RenderedCrop`, and `map_pixel_bbox(crop, pixel_bbox) -> BBox`.
- Preserves: input `clip` as the fixed page-space content box; synthetic border is raster-only and removed before mapping TSV coordinates back to page points.

- [ ] **Step 1: Write failing crop and mapping tests**

Create `tests/experiments/row_extraction/arms/ocr/test_crop.py`:

```python
from __future__ import annotations

import fitz

from experiments.row_extraction.arms.ocr.crop import map_pixel_bbox, render_clip


def _one_page_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_text((30, 60), "Synthetic 123.45", fontsize=10)
    data = document.tobytes()
    document.close()
    return data


def test_render_clip_keeps_fixed_bbox_and_adds_exact_white_border() -> None:
    crop = render_clip(
        _one_page_pdf(),
        page_index=0,
        clip=(20.0, 40.0, 180.0, 70.0),
        dpi=300,
        padding_px=5,
    )

    assert crop.clip == (20.0, 40.0, 180.0, 70.0)
    assert crop.padding_px == 5
    assert crop.image_bytes.startswith(b"P6\n")
    assert crop.width_px == crop.content_width_px + 10
    assert crop.height_px == crop.content_height_px + 10


def test_pixel_mapping_removes_raster_padding_before_point_scaling() -> None:
    crop = render_clip(
        _one_page_pdf(),
        page_index=0,
        clip=(20.0, 40.0, 180.0, 70.0),
        dpi=360,
        padding_px=10,
    )

    assert map_pixel_bbox(crop, (10, 10, 60, 30)) == (
        crop.origin[0],
        crop.origin[1],
        crop.origin[0] + 10.0,
        crop.origin[1] + 4.0,
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_crop.py
```

Expected: FAIL during collection because `crop.py` does not exist.

- [ ] **Step 3: Implement deterministic RGB PPM rendering and coordinate mapping**

Create `experiments/row_extraction/arms/ocr/crop.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import fitz  # type: ignore[import-untyped]

from experiments.row_extraction.contracts import BBox


@dataclass(frozen=True, slots=True)
class RenderedCrop:
    image_bytes: bytes
    clip: BBox
    origin: tuple[float, float]
    dpi: int
    padding_px: int
    width_px: int
    height_px: int
    content_width_px: int
    content_height_px: int


def _ppm(rgb: bytes, width: int, height: int, padding: int) -> tuple[bytes, int, int]:
    padded_width = width + padding * 2
    white_row = b"\xff\xff\xff" * padded_width
    rows = [white_row] * padding
    source_stride = width * 3
    side = b"\xff\xff\xff" * padding
    rows.extend(
        side + rgb[offset : offset + source_stride] + side
        for offset in range(0, len(rgb), source_stride)
    )
    rows.extend([white_row] * padding)
    header = f"P6\n{padded_width} {height + padding * 2}\n255\n".encode("ascii")
    return header + b"".join(rows), padded_width, height + padding * 2


def render_clip(
    pdf_bytes: bytes,
    *,
    page_index: int,
    clip: BBox,
    dpi: int,
    padding_px: int,
) -> RenderedCrop:
    if dpi <= 0 or padding_px < 0:
        raise ValueError("dpi must be positive and padding nonnegative")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(
            dpi=dpi,
            clip=fitz.Rect(clip),
            colorspace=fitz.csRGB,
            alpha=False,
        )
        image, width, height = _ppm(
            cast(bytes, pixmap.samples), pixmap.width, pixmap.height, padding_px
        )
        scale = 72.0 / dpi
        return RenderedCrop(
            image_bytes=image,
            clip=clip,
            origin=(float(pixmap.x) * scale, float(pixmap.y) * scale),
            dpi=dpi,
            padding_px=padding_px,
            width_px=width,
            height_px=height,
            content_width_px=pixmap.width,
            content_height_px=pixmap.height,
        )


def map_pixel_bbox(
    crop: RenderedCrop,
    pixel_bbox: tuple[int, int, int, int],
) -> BBox:
    left, top, right, bottom = pixel_bbox
    scale = 72.0 / crop.dpi
    return (
        crop.origin[0] + (left - crop.padding_px) * scale,
        crop.origin[1] + (top - crop.padding_px) * scale,
        crop.origin[0] + (right - crop.padding_px) * scale,
        crop.origin[1] + (bottom - crop.padding_px) * scale,
    )
```

Do not expand the PDF clip to simulate padding: that would admit neighboring content. The border must be white raster pixels around the exact accepted row/field clip.

- [ ] **Step 4: Verify GREEN at every approved DPI/padding level**

Extend the mapping test with parametrization for `(300, 0)`, `(300, 5)`, `(400, 10)`, and `(450, 5)`, using `pytest.approx` for non-integer point results. Then run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/crop.py tests/experiments/row_extraction/arms/ocr/test_crop.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_crop.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/crop.py tests/experiments/row_extraction/arms/ocr/test_crop.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/crop.py
```

Expected: all commands pass; exact clips remain unchanged and pixel boxes map through the actual PyMuPDF pixmap origin.

- [ ] **Step 5: Run repository verification and commit Task 2**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/crop.py tests/experiments/row_extraction/arms/ocr/test_crop.py
git commit -m "experiment: render reversible fixed row OCR crops"
```

### Task 3: Recognize and cache positioned Tesseract evidence deterministically

```text
Scope answer: YES
Program component: experiment 1
Measured effect: OCR CER/WER, omissions, insertions, latency, subprocess count, cache bytes, and byte-identical repeated TSV under fixed crops
Fixed inputs: RenderedCrop bytes/origin, OcrConfig, pinned Tesseract/Leptonica/traineddata identities, conservative accepted three-pass numeric fusion rule
Allowed files: experiments/row_extraction/arms/ocr/tesseract.py, tests/experiments/row_extraction/arms/ocr/test_tesseract.py
Stop condition: stop if recognition needs neural/cloud OCR, unpinned traineddata, shell execution, document-specific commands, or production OCR mutation
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/tesseract.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_tesseract.py`

**Interfaces:**
- Consumes: `OcrConfig`, `build_tesseract_commands`, `RenderedCrop`, `map_pixel_bbox`, and shared `EvidenceAtom`.
- Produces: `CommandRunner`, `LocalCommandRunner`, `RecognitionResult`, and `TesseractRecognizer.recognize(row_id, render_version, crop, config) -> RecognitionResult`.
- Produces evidence: stable content-addressed atom IDs, normalized logical Unicode text, page-space bboxes, confidence, and three raw TSV artifact identities; no proposal or authoritative field value.

- [ ] **Step 1: Write a failing cache/TSV/evidence test**

Create a fake `CommandRunner` that returns one version string and fixed TSV bytes, then add:

```python
def test_recognizer_caches_raw_tsv_and_emits_stable_page_atoms(tmp_path: Path) -> None:
    runner = FakeRunner(
        version=b"tesseract 5.5.0\n leptonica-1.85.0\n",
        outputs=(
            _tsv("Synthetic", left=5, top=5, width=40, height=10, confidence=91),
            _tsv("Synthetic", left=5, top=5, width=40, height=10, confidence=88),
            _tsv("", left=0, top=0, width=0, height=0, confidence=-1),
        ),
    )
    config = OcrConfig.baseline((("eng", "1" * 64), ("heb", "2" * 64)))
    crop = RenderedCrop(
        image_bytes=b"P6\n1 1\n255\n\xff\xff\xff",
        clip=(10.0, 20.0, 40.0, 30.0),
        origin=(10.0, 20.0),
        dpi=360,
        padding_px=5,
        width_px=1,
        height_px=1,
        content_width_px=1,
        content_height_px=1,
    )
    recognizer = TesseractRecognizer(
        cache_dir=tmp_path / "cache",
        tessdata_dir=tmp_path / "tessdata",
        runner=runner,
    )

    first = recognizer.recognize("row-opaque", "shared-render-v1", crop, config)
    second = recognizer.recognize("row-opaque", "shared-render-v1", crop, config)

    assert first == second
    assert len(first.atoms) == 1
    assert first.atoms[0].text == "Synthetic"
    assert first.atoms[0].bbox == (10.0, 20.0, 18.0, 22.0)
    assert runner.recognition_calls == 3
    assert tuple(path.suffix for path in first.raw_tsv_paths) == (".tsv", ".tsv", ".tsv")
```

The test helper `_tsv()` must emit the real 12-column Tesseract TSV header and one level-5 row; the empty text case emits only the header.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_tesseract.py::test_recognizer_caches_raw_tsv_and_emits_stable_page_atoms
```

Expected: FAIL during collection because `TesseractRecognizer` does not exist.

- [ ] **Step 3: Implement subprocess isolation, canonical cache keys, TSV parsing, and atoms**

Implement these exact public shapes in `tesseract.py`:

```python
class CommandRunner(Protocol):
    def version(self, executable: str) -> bytes: ...

    def run(self, command: tuple[str, ...], image: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    atoms: tuple[EvidenceAtom, ...]
    raw_tsv_paths: tuple[Path, ...]
    subprocess_count: int


class LocalCommandRunner:
    def version(self, executable: str) -> bytes:
        completed = subprocess.run(
            (executable, "--version"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10.0,
        )
        return completed.stdout

    def run(self, command: tuple[str, ...], image: bytes) -> bytes:
        completed = subprocess.run(
            command,
            input=image,
            check=True,
            capture_output=True,
            timeout=120.0,
        )
        return completed.stdout
```

Use canonical compact sorted JSON for a recognition key containing `row_id`, `render_version`, `sha256(crop.image_bytes)`, `crop.clip`, `crop.origin`, DPI, padding, complete `OcrConfig`, complete commands, Tesseract/Leptonica version bytes, traineddata SHA-256 values, and cache schema. Store each pass as `{recognition_key}.primary.tsv`, `{recognition_key}.supplemental.tsv`, and `{recognition_key}.numeric.tsv`; write through `NamedTemporaryFile(dir=cache_dir, delete=False)` followed by `replace()` and cleanup.

Parse only valid level-5 rows with 12 TSV fields, nonnegative confidence, positive width/height, and nonempty NFC text. Map `(left, top, left + width, top + height)` through `map_pixel_bbox()`. Reuse the accepted public `ccparser.evidence.ocr.fuse_ocr_words()` for conservative numeric replacement; convert fused words back to `EvidenceAtom` and assign each atom ID as:

```python
def _atom_id(row_id: str, index: int, text: str, bbox: BBox) -> str:
    encoded = json.dumps(
        {"bbox": bbox, "index": index, "row_id": row_id, "text": text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"ocr:{hashlib.sha256(encoded).hexdigest()}"
```

The cache-hit path must read bytes only and return `subprocess_count=0`; a miss reports three calls. Cache keys may use opaque row IDs for artifact identity but no prediction branch may inspect them.

- [ ] **Step 4: Add negative and determinism coverage**

Add tests that malformed TSV rows are ignored; NFC-equivalent text produces NFC output; changing padding, DPI, language order, thresholding, traineddata hash, Tesseract version, or image bytes changes the cache path; timeout/nonzero exit raises `OcrRecognitionError`; and two independent empty cache roots produce byte-identical TSV and atom JSON. Run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/tesseract.py tests/experiments/row_extraction/arms/ocr/test_tesseract.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_tesseract.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/tesseract.py tests/experiments/row_extraction/arms/ocr/test_tesseract.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/tesseract.py
```

Expected: all commands pass; cache identity covers every declared recognition input and repeated empty-cache outputs match byte-for-byte.

- [ ] **Step 5: Run repository verification and commit Task 3**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/tesseract.py tests/experiments/row_extraction/arms/ocr/test_tesseract.py
git commit -m "experiment: cache positioned row OCR evidence"
```

### Task 4: Assign OCR evidence without changing fixed rows

```text
Scope answer: YES
Program component: experiment 1
Measured effect: exact merchant/field accuracy, cross-column ownership collisions, omissions, unsupported evidence, and abstentions under fixed rows
Fixed inputs: FrozenRow identity/bbox/type, accepted ColumnBand geometry, recognized positioned EvidenceAtom records, shared proposal/prediction contract
Allowed files: experiments/row_extraction/arms/ocr/assignment.py, tests/experiments/row_extraction/arms/ocr/test_assignment.py
Stop condition: stop before invoking row clustering, changing a row bbox/count/membership, inventing field values, or selecting candidates through reconciliation
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/assignment.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_assignment.py`

**Interfaces:**
- Consumes: `EvidenceAtom`, accepted `ColumnBand`, `AssignmentMode`, and shared `FieldProposal`.
- Produces: `AssignmentResult(evidence_atoms, proposals, reasons)`, `assign_fixed_columns(owner_row_id: str | None, atoms, bands)`, and `assign_fixed_row_cells(owner_row_id: str | None, atoms, bands)`.
- Preserves: row identity/bbox and accepted bands; recognition-only and reconstructed-cell results are distinct configuration modes.

- [ ] **Step 1: Write failing ownership/collision tests**

Use the shared synthetic contract constructors and add:

```python
def test_fixed_column_assignment_groups_only_unique_center_members() -> None:
    atoms = (
        atom("a", "Merchant", (45.0, 10.0, 75.0, 20.0), 0.90),
        atom("b", "123.45", (115.0, 10.0, 145.0, 20.0), 0.95),
    )
    bands = (
        band(FieldRole.DESCRIPTION, (20.0, 0.0, 90.0, 30.0)),
        band(FieldRole.BILLED_AMOUNT, (100.0, 0.0, 160.0, 30.0)),
    )

    result = assign_fixed_columns(None, atoms, bands)

    assert tuple(proposal.role for proposal in result.proposals) == (
        FieldRole.DESCRIPTION,
        FieldRole.BILLED_AMOUNT,
    )
    assert result.proposals[0].atom_ids == ("a",)
    assert result.proposals[0].owner_row_id is None
    assert tuple(atom.column_index for atom in result.evidence_atoms) == (0, 1)
    assert result.reasons == ()


def test_overlapping_column_membership_abstains_instead_of_guessing() -> None:
    result = assign_fixed_columns(
        None,
        (atom("a", "Synthetic", (80.0, 10.0, 100.0, 20.0), 0.9),),
        (
            band(FieldRole.DESCRIPTION, (20.0, 0.0, 95.0, 30.0)),
            band(FieldRole.BILLED_AMOUNT, (85.0, 0.0, 160.0, 30.0)),
        ),
    )

    assert result.proposals == ()
    assert result.reasons == ("ownership_collision",)
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_assignment.py
```

Expected: FAIL during collection because `assignment.py` does not exist.

- [ ] **Step 3: Implement unique fixed-band assignment**

Implement `AssignmentResult` and center ownership without text-dependent branches:

```python
@dataclass(frozen=True, slots=True)
class AssignmentResult:
    evidence_atoms: tuple[EvidenceAtom, ...]
    proposals: tuple[FieldProposal, ...]
    reasons: tuple[str, ...]


def _center_x(bbox: BBox) -> float:
    return (bbox[0] + bbox[2]) / 2.0


def assign_fixed_columns(
    owner_row_id: str | None,
    atoms: tuple[EvidenceAtom, ...],
    bands: tuple[ColumnBand, ...],
) -> AssignmentResult:
    grouped: dict[FieldRole, list[EvidenceAtom]] = {}
    assigned_atoms: list[EvidenceAtom] = []
    collision = False
    for atom in atoms:
        owners = tuple(
            band for band in bands if band.bbox[0] <= _center_x(atom.bbox) <= band.bbox[2]
        )
        if len(owners) > 1:
            collision = True
            continue
        if len(owners) == 1:
            owner = owners[0]
            assigned = atom.model_copy(update={"column_index": owner.index})
            assigned_atoms.append(assigned)
            if owner.role is not None:
                grouped.setdefault(owner.role, []).append(assigned)
    if collision:
        return AssignmentResult(tuple(assigned_atoms), (), ("ownership_collision",))
    proposals = tuple(
        FieldProposal(
            role=role,
            atom_ids=tuple(atom.atom_id for atom in sorted(items, key=_logical_atom_key)),
            source_region=_union_bbox(tuple(atom.bbox for atom in items)),
            raw_score=sum(atom.confidence for atom in items) / len(items),
            owner_row_id=owner_row_id,
        )
        for role, items in sorted(grouped.items(), key=lambda item: item[0].value)
    )
    return AssignmentResult(tuple(assigned_atoms), proposals, ())
```

`_logical_atom_key()` must use Unicode bidirectional class plus x geometry, never reverse an entire mixed-script field. For purely RTL letter groups sort descending x; for numeric/LTR groups sort ascending x; preserve stable `(x0, y0, atom_id)` tie-breakers. `_union_bbox()` uses min/max only.

- [ ] **Step 4: Implement and separately test fixed-row cell reconstruction**

`assign_fixed_row_cells(owner_row_id, atoms, bands)` may group tokens within the already-fixed row using the accepted gap rule only: sort by x, calculate median positive token height, join adjacent tokens when `gap <= median_height * 0.6`, assign each resulting cell by its center to exactly one accepted band, set every grouped atom's `column_index` to that band's fixed index, and use the same collision abstention. `owner_row_id=None` means the current `FrozenRow`; only continuation ownership passes a non-`None` previous-row ID. Bands whose `role is None` retain evidence atoms but cannot produce a `FieldProposal`. It must not cluster y lines, produce a row, alter a bbox, infer column bands, or call `ccparser.layout.rows.cluster_rows()`.

Add a test where two close merchant atoms group together, a distant amount remains separate, and the input row bbox supplied to the test is identical before/after. Then run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/assignment.py tests/experiments/row_extraction/arms/ocr/test_assignment.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_assignment.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/assignment.py tests/experiments/row_extraction/arms/ocr/test_assignment.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/assignment.py
```

Expected: all tests pass; overlap becomes an explicit abstention and the reconstructed mode cannot create or move rows.

- [ ] **Step 5: Run repository verification and commit Task 4**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/assignment.py tests/experiments/row_extraction/arms/ocr/test_assignment.py
git commit -m "experiment: assign row OCR to frozen fields"
```

### Task 5: Compose the read-only OCR experiment arm and complete evidence ledger

```text
Scope answer: YES
Program component: experiment 1
Measured effect: common-contract exact field predictions, omissions, hallucinations, unsupported evidence, ownership errors, abstentions, and per-row runtime under fixed rows
Fixed inputs: FrozenRow records, private source path/render version, OcrConfig, accepted baseline type/bbox/columns/continuation context, shared prediction contract
Allowed files: experiments/row_extraction/arms/ocr/arm.py, experiments/row_extraction/arms/ocr/__init__.py, tests/experiments/row_extraction/arms/ocr/test_arm.py
Stop condition: stop if prediction requires gold access, row detection, shared mutation, authoritative value generation, or private output outside the lane root
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/arm.py`
- Modify: `experiments/row_extraction/arms/ocr/__init__.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_arm.py`

**Interfaces:**
- Consumes: `FrozenRow`, `ExperimentArm`, `RowPrediction`, `Decision`, lane renderer/recognizer/assignment, and the row's fixed `source_pdf`, `page_number`, `render_version`, and `baseline_type`.
- Produces: `PdfSource.read(source_pdf: Path) -> bytes` protocol, `PrivatePdfSource`,
  `OcrExperimentArm.predict(row) -> RowPrediction`, and `OcrExperimentArmFactory` with the
  frozen config/artifact-manifest identity, fresh-arm construction, and an exact subprocess
  counter shared with the lane-owned Tesseract launcher.
- Emits: a complete immutable `RowPrediction.evidence_atoms` ledger containing every OCR atom referenced by a proposal; no sidecar registry.

- [ ] **Step 1: Write a failing synthetic arm test**

```python
from tests.experiments.row_extraction.factories import frozen_row


def test_arm_preserves_row_identity_and_carries_every_proposed_atom() -> None:
    synthetic_frozen_row = frozen_row()
    source = FakePdfSource(b"synthetic-pdf")
    recognizer = FakeRecognizer(
        atoms=(atom("ocr:a", "Merchant", (45.0, 10.0, 75.0, 20.0), 0.91),)
    )
    config = OcrConfig.baseline((("eng", "1" * 64), ("heb", "2" * 64)))
    arm = OcrExperimentArm(config, source, recognizer)

    prediction = arm.predict(synthetic_frozen_row)

    assert prediction.experiment_id == "row-ocr"
    assert prediction.config_id == config.config_id
    assert prediction.document_id == synthetic_frozen_row.document_id
    assert prediction.row_id == synthetic_frozen_row.row_id
    assert prediction.predicted_type == synthetic_frozen_row.baseline_type
    assert prediction.decision is Decision.ACCEPT
    assert {atom.atom_id for atom in prediction.evidence_atoms} == {
        atom_id
        for proposal in prediction.proposals
        for atom_id in proposal.atom_ids
    }
    assert synthetic_frozen_row.bbox == synthetic_frozen_row.model_copy().bbox
```

Add tests for recognition failure (`Decision.ABSTAIN`, reason `ocr_failure`), ownership collision (`Decision.ABSTAIN`), and zero recognized atoms (`Decision.ABSTAIN`, reason `no_supported_ocr_evidence`).
Add a continuation test using `synthetic_frozen_row.model_copy(update={"baseline_type": RowType.CONTINUATION, "previous_row_id": "row-primary"})` and assert every proposal has `owner_row_id == "row-primary"`. A continuation with no `previous_row_id` must abstain with `continuation_owner_missing`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_arm.py
```

Expected: FAIL during collection because `OcrExperimentArm` does not exist.

- [ ] **Step 3: Implement the bounded private-source reader**

Use these exact protocols and source layout:

```python
class PdfSource(Protocol):
    def read(self, source_pdf: Path) -> bytes: ...


@dataclass(frozen=True, slots=True)
class PrivatePdfSource:
    root: Path

    def read(self, source_pdf: Path) -> bytes:
        root = self.root.resolve(strict=True)
        candidate = source_pdf.resolve(strict=True)
        candidate.relative_to(root)
        return candidate.read_bytes()
```

The private reader root is `/root/creditcard/artifacts/row-extraction/shared/`; `FrozenRow.source_pdf` is an operational location created by the shared bundle and must resolve beneath it. The path and `render_version` enter render/cache identity but never a proposal, OCR feature, selection key, report, or stdout.

- [ ] **Step 4: Implement `OcrExperimentArm.predict()`**

The arm must:

1. read source bytes through `source.read(row.source_pdf)`;
2. convert the shared 1-based `row.page_number` to PyMuPDF's 0-based index exactly once; for `WHOLE_ROW`, render exactly `row.bbox`; for `FIXED_FIELDS`, render the intersection of `row.bbox` and each accepted typed `ColumnBand.bbox` without changing either input;
3. recognize each crop with `row.render_version` as an explicit cache input and assemble its OCR atoms into one duplicate-free evidence ledger;
4. determine proposal ownership as `row.previous_row_id` only when `row.baseline_type is RowType.CONTINUATION`; otherwise use `None`, which canonically means the current `FrozenRow`; abstain with `continuation_owner_missing` when accepted continuation context lacks a previous row;
5. use `assign_fixed_columns` or `assign_fixed_row_cells` according to configuration, passing that fixed owner; copy `row.baseline_type` to `predicted_type` without using it as a recognition feature; never consume `next_row_id`, `gap_before`, or `gap_after` in OCR or selection;
6. return `Decision.ACCEPT` only when at least one uniquely supported proposal exists; otherwise return `Decision.ABSTAIN` with stable sorted reasons;
7. catch only `OcrRecognitionError`, `FileNotFoundError`, and invalid empty intersections as stable abstentions; do not mask programming/contract errors.

Core return construction:

```python
return RowPrediction(
    experiment_id=self.experiment_id,
    config_id=self.config_id,
    document_id=row.document_id,
    row_id=row.row_id,
    predicted_type=row.baseline_type,
    evidence_atoms=assignment.evidence_atoms,
    proposals=assignment.proposals,
    exact_row_confidence=None,
    decision=Decision.ACCEPT if assignment.proposals else Decision.ABSTAIN,
    reasons=assignment.reasons,
)
```

Expose `OcrExperimentArm.experiment_id` as the constant `row-ocr`; keep every ablation
identity in `config_id`. Export `OcrConfig` and `OcrExperimentArm` from `__init__.py`. Run:

Every Tesseract launch in `tesseract.py` increments the factory-owned counter exactly once
before process creation. Cache hits launch nothing. Construction-time version detection and
all recognition passes use the same counter; a direct uncounted subprocess call is forbidden.

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr tests/experiments/row_extraction/arms/ocr/test_arm.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_arm.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/arm.py tests/experiments/row_extraction/arms/ocr/test_arm.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/arm.py
```

Expected: all tests pass and every proposal atom resolves exactly once in `prediction.evidence_atoms`.

- [ ] **Step 5: Run repository verification and commit Task 5**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/__init__.py experiments/row_extraction/arms/ocr/arm.py tests/experiments/row_extraction/arms/ocr/test_arm.py
git commit -m "experiment: implement fixed-row OCR arm"
```

### Task 6: Encode the sequential ablation matrix and deterministic selection

```text
Scope answer: YES
Program component: experiment 1
Measured effect: exact merchant/field gain versus omission, hallucination, ownership, CER/WER, latency, RSS, and determinism regressions at each predeclared OCR stage
Fixed inputs: development and validation splits, shared metrics, incumbent configuration, accepted/best traineddata identities, no locked-test records
Allowed files: experiments/row_extraction/arms/ocr/selection.py, experiments/row_extraction/arms/ocr/sweep.py, tests/experiments/row_extraction/arms/ocr/test_selection.py, tests/experiments/row_extraction/arms/ocr/test_sweep.py
Stop condition: stop if selection needs locked results, a new ablation family, a Cartesian sweep, document-specific tuning, neural OCR, reconciliation-based choice, or shared metric changes
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/selection.py`
- Create: `experiments/row_extraction/arms/ocr/sweep.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_selection.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_sweep.py`

**Interfaces:**
- Consumes: shared `MetricReport`, `ResourceSpec`, `RunMeasurements`, `DatasetSplit`; lane
  `OcrConfig`; exact split-filtered row-sequence identity/count; frozen-arm/runtime identities;
  pinned traineddata model inventory; dependency inventory; and distinct new private cache and
  resource-inventory paths per run.
- Produces: `Stage`, `SelectionMetrics`, `CandidateResult`,
  `build_ocr_resource_spec(...) -> ResourceSpec`, `project_selection_metrics(report,
  measurements)`, `stage_candidates(stage, incumbent, best_traineddata)`,
  `select_development_challenger()`, and `approve_validation_challenger()`.
- Selection invariant: a challenger must be deterministic, preserve fixed row count/IDs, and not increase omission, hallucination, or ownership-collision counts on the identical evaluation rows. Reconciliation is not a selection feature.

`build_ocr_resource_spec` binds one candidate's config/frozen-arm manifest, the exact ordered
row sequence and split, the runtime, the disjoint traineddata-model/dependency inventories,
`worker_count=1`, and one new-empty cache root. Each candidate and repeat gets a distinct spec;
every OCR spec fixes `resource_basis="end-to-end-method"`;
the runner, not `sweep.py`, observes cold start, process-family RSS, cache bytes, subprocesses,
and prediction latency from the same published execution. Row OCR has no separate preparation
record because crop rendering and recognition occur inside `predict`.

- [ ] **Step 1: Write failing exact-matrix tests**

```python
def test_stage_matrix_is_sequential_and_contains_no_neural_candidate() -> None:
    incumbent = OcrConfig.baseline((("eng", "1" * 64), ("heb", "2" * 64)))

    crop = stage_candidates(Stage.CROP_CONTRACT, incumbent, None)
    assert {(item.row_psm, item.padding_px) for item in crop} == {
        (6, 0), (6, 5), (6, 10),
        (7, 0), (7, 5), (7, 10),
        (13, 0), (13, 5), (13, 10),
    }
    assert {item.languages for item in stage_candidates(Stage.LANGUAGE_ORDER, incumbent, None)} == {
        "heb+eng", "eng+heb"
    }
    assert {item.dpi for item in stage_candidates(Stage.DPI, incumbent, None)} == {300, 400, 450}
    assert {
        item.thresholding
        for item in stage_candidates(Stage.THRESHOLDING, incumbent, None)
    } == {
        Thresholding.INTERNAL_OTSU,
        Thresholding.ADAPTIVE_OTSU,
        Thresholding.SAUVOLA,
    }
    assert {
        (item.crop_mode, item.assignment_mode, item.field_psm)
        for item in stage_candidates(Stage.FIELD_CROPS_AND_CELLS, incumbent, None)
    } == {
        (CropMode.WHOLE_ROW, AssignmentMode.FIXED_COLUMNS, incumbent.field_psm),
        (CropMode.WHOLE_ROW, AssignmentMode.FIXED_ROW_CELLS, incumbent.field_psm),
        (CropMode.FIXED_FIELDS, AssignmentMode.FIXED_COLUMNS, 7),
        (CropMode.FIXED_FIELDS, AssignmentMode.FIXED_COLUMNS, 13),
    }
```

For `Stage.TRAINEDDATA`, pass synthetic best identities and assert exactly the incumbent and one otherwise-identical best-pack candidate are returned. Assert every stage deduplicates by `config_id`.

- [ ] **Step 2: Write failing hard-gate and tie-break tests**

Create synthetic `CandidateResult` values and assert:

```python
def test_validation_rejects_accuracy_gain_with_hallucination_regression() -> None:
    incumbent = candidate(config_id="ocr-a", exact="0.80", description="0.82", hallucinations=1)
    challenger = candidate(config_id="ocr-b", exact="0.85", description="0.90", hallucinations=2)

    assert approve_validation_challenger(incumbent, challenger) == incumbent


def test_admissible_tie_break_is_deterministic_and_resource_aware() -> None:
    slower = candidate(config_id="ocr-z", exact="0.85", description="0.90", p95_ns=40_000_000)
    faster = candidate(config_id="ocr-a", exact="0.85", description="0.90", p95_ns=30_000_000)

    assert select_development_challenger((slower, faster)) == faster
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_selection.py tests/experiments/row_extraction/arms/ocr/test_sweep.py
```

Expected: FAIL during collection because the sweep/selection modules do not exist.

- [ ] **Step 4: Implement stage enumeration and hard-gated ranking**

Use this exact stage order:

```python
class Stage(StrEnum):
    CROP_CONTRACT = "01-crop-contract"
    LANGUAGE_ORDER = "02-language-order"
    DPI = "03-dpi"
    THRESHOLDING = "04-thresholding"
    FIELD_CROPS_AND_CELLS = "05-field-crops-and-cells"
    TRAINEDDATA = "06-traineddata"


STAGE_ORDER = tuple(Stage)
```

Define `SelectionMetrics` as a frozen dataclass with `exact_row_rate: Decimal`, `description_exact_rate: Decimal`, `description_normalized_rate: Decimal`, `omissions: int`, `hallucinations: int`, `ownership_collisions: int`, `ocr_cer: Decimal | None`, `ocr_wer: Decimal | None`, `p95_ns: int`, and `peak_rss_bytes: int`. `project_selection_metrics()` takes exactness from `report.exact_row_rate`, description results from `report.fields[FieldRole.DESCRIPTION]`, sums omission/hallucination counts across `report.fields.values()`, takes ownership collisions and OCR error directly from the shared report, and takes resource values from `RunMeasurements`. It must not recalculate or replace common metric semantics.

```python
def project_selection_metrics(
    report: MetricReport,
    measurements: RunMeasurements,
) -> SelectionMetrics:
    description = report.fields[FieldRole.DESCRIPTION]
    return SelectionMetrics(
        exact_row_rate=report.exact_row_rate,
        description_exact_rate=description.exact_rate,
        description_normalized_rate=description.normalized_rate,
        omissions=sum(field.omissions for field in report.fields.values()),
        hallucinations=sum(field.hallucinations for field in report.fields.values()),
        ownership_collisions=report.ownership_collisions,
        ocr_cer=report.ocr_cer,
        ocr_wer=report.ocr_wer,
        p95_ns=measurements.p95_ns,
        peak_rss_bytes=measurements.peak_rss_bytes,
    )
```

Define `CandidateResult` with `config`, shared `metrics`, shared `measurements`, projected `selection`, `deterministic: bool`, `fixed_row_ids_match: bool`, and private prediction artifact identities. An admissible challenger must satisfy:

```python
def _admissible(incumbent: CandidateResult, challenger: CandidateResult) -> bool:
    return (
        challenger.deterministic
        and challenger.fixed_row_ids_match
        and challenger.selection.omissions <= incumbent.selection.omissions
        and challenger.selection.hallucinations <= incumbent.selection.hallucinations
        and challenger.selection.ownership_collisions
        <= incumbent.selection.ownership_collisions
    )
```

Rank admissible results by `selection.exact_row_rate`, description exact, description normalized,
lower CER, lower WER, lower `p95_ns`, lower peak RSS, then lexicographically smaller
`config_id`. CER/WER availability must match for every candidate on an evaluation set; when
both are `None`, omit that axis, and reject mixed availability as an eligibility mismatch.
Train/development selects one challenger; validation returns it only if it remains admissible
and ranks above the incumbent. Do not read or rank reconciliation outcomes.

- [ ] **Step 5: Verify GREEN and exact candidate cardinality**

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/selection.py experiments/row_extraction/arms/ocr/sweep.py tests/experiments/row_extraction/arms/ocr/test_selection.py tests/experiments/row_extraction/arms/ocr/test_sweep.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_selection.py tests/experiments/row_extraction/arms/ocr/test_sweep.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/selection.py experiments/row_extraction/arms/ocr/sweep.py tests/experiments/row_extraction/arms/ocr/test_selection.py tests/experiments/row_extraction/arms/ocr/test_sweep.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/selection.py experiments/row_extraction/arms/ocr/sweep.py
```

Expected: all commands pass; stages contain `9, 2, 3, 3, 4, 2` candidates before incumbent deduplication and never include neural OCR.

- [ ] **Step 6: Run repository verification and commit Task 6**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/selection.py experiments/row_extraction/arms/ocr/sweep.py tests/experiments/row_extraction/arms/ocr/test_selection.py tests/experiments/row_extraction/arms/ocr/test_sweep.py
git commit -m "experiment: stage row OCR ablations sequentially"
```

### Task 7: Stream private runs and forbid lane-local locked-test access

```text
Scope answer: YES
Program component: experiment 1
Measured effect: reproducible predictions/metrics/resources per stage, invariant row membership, privacy-safe execution, and locked-test isolation
Fixed inputs: shared frozen-row/gold/baseline JSONL, shared runner/metrics/codecs, current stage incumbent, lane artifact root
Allowed files: experiments/row_extraction/arms/ocr/cli.py, experiments/row_extraction/arms/ocr/__main__.py, tests/experiments/row_extraction/arms/ocr/test_cli.py, /root/creditcard/artifacts/row-extraction/experiment-1-ocr/**
Stop condition: stop on any locked-test input, row-ID mismatch, evidence-resolution failure, nonprivate output path, shared input write, or stdout containing row/document/financial content
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/cli.py`
- Create: `experiments/row_extraction/arms/ocr/__main__.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_cli.py`
- Create privately when commands run: `/root/creditcard/artifacts/row-extraction/experiment-1-ocr/**`

**Interfaces:**
- Consumes: shared streaming codecs, `run_arm`, `score_predictions`, lane stages/selection, shared private source/gold/baseline artifacts.
- Produces CLI commands `run-candidate` and `run-stage`; canonical private `predictions.jsonl` (including complete evidence ledgers), `measurements.json`, `metrics.json`, `config.json`, and `run-identity.json` per config/split.
- Stdout: one aggregate line containing stage, split, candidate count, processed row count, success/failure, and no private identity/value.

- [ ] **Step 1: Write failing split/privacy guard tests**

```python
def test_run_stage_rejects_locked_split_before_freeze(tmp_path: Path) -> None:
    result = run_cli(
        "run-stage",
        "--stage", "01-crop-contract",
        "--split", "test",
        "--shared-root", str(tmp_path / "shared"),
        "--lane-root", str(tmp_path / "lane"),
    )

    assert result.exit_code == 2
    assert "locked test belongs to the central comparison stage" in result.stderr


def test_output_root_must_be_lane_private_root(tmp_path: Path) -> None:
    result = run_cli(
        "run-candidate",
        "--split", "train",
        "--output", str(tmp_path / "tracked-output"),
    )

    assert result.exit_code == 2
    assert "output must be under the experiment-1 private root" in result.stderr
```

Add a synthetic successful run test that captures stdout and asserts none of the synthetic document ID, row ID, merchant text, or invented amount appears.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_cli.py
```

Expected: FAIL during collection because `cli.py` does not exist.

- [ ] **Step 3: Implement streamed candidate execution**

`run-candidate` must:

1. resolve paths beneath `/root/creditcard/artifacts/row-extraction/experiment-1-ocr/` and reject escape after `Path.resolve()`;
2. verify the candidate's `ResourceSpec` against the exact requested split-filtered sequence in
   shared `frozen-rows.jsonl`, then open a fresh filtered row iterator for execution;
3. reject `DatasetSplit.TEST` unconditionally; the central comparison package imports the verified frozen arm and owns the only locked run;
4. construct a fresh `OcrExperimentArmFactory` and `JsonlPredictionSink` inside a new,
   nonexistent run directory;
5. call `run_arm(rows, factory, prediction_sink, resource_spec)` exactly once in this fresh
   isolated command process so its returned measurements and prediction digest describe that
   same execution;
6. reopen independent filtered row and gold iterators plus predictions with `read_jsonl`,
   require every proposal ID to resolve exactly once in its prediction's `evidence_atoms`, and
   call `score_predictions(reopened_rows, reopened_gold, predictions)` exactly once; never
   reuse the iterator consumed by `run_arm`;
7. compare emitted row IDs with expected fixed row IDs in streaming sorted order and fail closed on any missing, extra, duplicate, or reordered ID;
8. write canonical compact sorted JSON with mode `0o600`, atomic rename, and no source names/values;
9. print only `f"experiment=1 split={split.value} rows={row_count} status=ok"`.

Use `__main__.py` only as:

```python
from experiments.row_extraction.arms.ocr.cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Implement one-stage development/validation orchestration**

`run-stage` reads the incumbent config from the previous stage's private winner manifest, runs all deduplicated candidates on development, selects one challenger, runs only challenger and incumbent on validation, and writes `stage-decision.json` containing candidate config IDs, shared metric/resource artifact identities, admissibility outcomes, winner config ID, and stable rejection reasons. It must refuse to run stage N unless stage N-1 has a completed decision, except the first stage which starts from `OcrConfig.baseline()`.

Run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/cli.py experiments/row_extraction/arms/ocr/__main__.py tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/cli.py experiments/row_extraction/arms/ocr/__main__.py tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/cli.py
```

Expected: all commands pass; locked access and unsafe output paths fail before reading inputs, and successful stdout is aggregate-only.

- [ ] **Step 5: Run repository verification and commit Task 7**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/cli.py experiments/row_extraction/arms/ocr/__main__.py tests/experiments/row_extraction/arms/ocr/test_cli.py
git commit -m "experiment: stream private row OCR sweeps"
```

### Task 8: Freeze validation selection and emit deterministic handoff artifacts

```text
Scope answer: YES
Program component: experiment 1
Measured effect: configuration-freeze integrity, repeated canonical prediction identity, final validation measurements, and comparison-ready handoff completeness
Fixed inputs: completed six-stage development/validation decisions, exact lane commit, accepted SHA, frozen foundation/runtime/worker identity, untouched locked split
Allowed files: experiments/row_extraction/arms/ocr/freeze.py, experiments/row_extraction/arms/ocr/checkpoint.py, experiments/row_extraction/arms/ocr/cli.py, tests/experiments/row_extraction/arms/ocr/test_freeze.py, tests/experiments/row_extraction/arms/ocr/test_checkpoint.py, tests/experiments/row_extraction/arms/ocr/test_cli.py, /root/creditcard/artifacts/row-extraction/experiment-1-ocr/**
Stop condition: on an in-scope validation failure, stop further OCR/model work but still emit the typed terminal checkpoint/handoff; stop all processing if the worktree is dirty, runtime identity differs, locked results were opened, private content would enter Git/stdout, or a scope-forbidden follow-up is needed
```

**Files:**
- Create: `experiments/row_extraction/arms/ocr/freeze.py`
- Create: `experiments/row_extraction/arms/ocr/checkpoint.py`
- Modify: `experiments/row_extraction/arms/ocr/cli.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_freeze.py`
- Create: `tests/experiments/row_extraction/arms/ocr/test_checkpoint.py`
- Modify: `tests/experiments/row_extraction/arms/ocr/test_cli.py`
- Create privately: `/root/creditcard/artifacts/row-extraction/experiment-1-ocr/freeze/**`

**Interfaces:**
- Consumes: six ordered `stage-decision.json` files, final config, code/foundation/runtime identities, validation prediction/evidence/metric/resource identities.
- Produces: `ValidationFreeze`, `OcrLaneHandoff`, `write_freeze_exclusive()`, `verify_freeze()`, `write_terminal_handoff()`, `write_checkpoint()`, and private canonical `validation-freeze.json` when eligible plus `determinism.json`, `checkpoint.json`, and `handoff.json` for both dispositions.
- Handoff invariant: records exactly one shared `LaneDisposition`. `FROZEN_ELIGIBLE` identifies one frozen experiment-1 arm; `VALIDATION_STOPPED` has no frozen-arm manifest and carries a stable stop reason plus complete validation metric/resource/error evidence. Neither contains locked metrics, source identifiers, field values, or a production recommendation.

- [ ] **Step 1: Write failing freeze immutability/determinism tests**

```python
def test_validation_freeze_is_canonical_exclusive_and_rejects_locked_access(
    tmp_path: Path,
) -> None:
    freeze = synthetic_freeze(locked_test_opened=False)
    path = tmp_path / "validation-freeze.json"

    identity = write_freeze_exclusive(path, freeze)

    assert path.read_bytes() == canonical_freeze_bytes(freeze)
    assert identity.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        write_freeze_exclusive(path, freeze)
    with pytest.raises(ValueError, match="locked test was opened before freeze"):
        write_freeze_exclusive(tmp_path / "bad.json", replace(freeze, locked_test_opened=True))


def test_repeat_report_requires_identical_predictions_and_raw_tsv() -> None:
    with pytest.raises(ValueError, match="prediction bytes differ"):
        build_determinism_report(
            first=repeat_identity(predictions="1" * 64),
            second=repeat_identity(predictions="2" * 64),
        )


def test_failed_stage_still_emits_a_typed_terminal_handoff(tmp_path: Path) -> None:
    handoff = write_terminal_handoff(tmp_path / "handoff.json", synthetic_failed_stage())
    assert handoff.disposition is LaneDisposition.VALIDATION_STOPPED
    assert handoff.stop_reason == "ocr_stage_validation_failed"
    assert handoff.frozen_arm_manifest is None
    assert handoff.locked_test_status == "not_opened"
    assert handoff.validation_metrics is not None
    assert handoff.validation_measurements is not None
```

- [ ] **Step 2: Write the failing exact eight-section checkpoint test**

```python
def test_checkpoint_has_exact_charter_sections_and_no_private_values(tmp_path: Path) -> None:
    checkpoint = build_checkpoint(synthetic_handoff())
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint)

    assert tuple(checkpoint) == (
        "scope",
        "hypothesis",
        "fixed_inputs_and_configuration",
        "files_changed",
        "tests_and_verification",
        "measurements",
        "errors_and_limitations",
        "next_action_or_stop",
    )
    serialized = path.read_text(encoding="utf-8")
    assert "Synthetic Merchant" not in serialized
    assert "123.45" not in serialized
    assert "document-opaque" not in serialized
```

Extend `test_cli.py` with an exact boundary test for each new command: `repeat-validation` rejects a repeat root outside the lane root, `freeze-validation` rejects a preexisting output, and `write-handoff` rejects a missing verified freeze. Assert failure occurs before the fake shared-row reader is called.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_freeze.py tests/experiments/row_extraction/arms/ocr/test_checkpoint.py
```

Expected: FAIL during collection because freeze/checkpoint modules do not exist.

- [ ] **Step 4: Implement the exclusive freeze and repeat verifier**

Define `ValidationFreeze` as a frozen dataclass containing:

```python
@dataclass(frozen=True, slots=True)
class ValidationFreeze:
    schema_version: str
    experiment_id: str
    config: OcrConfig
    accepted_anchor_sha: str
    foundation_sha: str
    lane_sha: str
    runtime_identity: ArtifactIdentity
    worker_count: int
    traineddata: tuple[ArtifactIdentity, ...]
    stage_decisions: tuple[ArtifactIdentity, ...]
    validation_predictions: ArtifactIdentity
    validation_metrics: ArtifactIdentity
    validation_measurements: ArtifactIdentity
    locked_test_opened: bool


@dataclass(frozen=True, slots=True)
class OcrLaneHandoff:
    schema_version: str
    experiment_id: Literal["row-ocr"]
    disposition: LaneDisposition
    stop_reason: str | None
    config_identity: ArtifactIdentity | None
    frozen_arm_manifest: ArtifactIdentity | None
    validation_predictions: ArtifactIdentity
    validation_metric_identity: ArtifactIdentity
    validation_metric_report: MetricReport
    validation_measurement_identity: ArtifactIdentity
    validation_measurements: RunMeasurements
    error_summary: ArtifactIdentity
    determinism: ArtifactIdentity | None
    accepted_anchor_sha: str
    foundation_sha: str
    lane_sha: str
    runtime_identity: ArtifactIdentity
    worker_count: int
    locked_test_status: Literal["not_opened"]
```

`write_freeze_exclusive()` requires exactly six stage identities in `STAGE_ORDER`, the accepted anchor exactly `dee4b071ad65231da13825f2f7c74a488ca96c7c`, nonempty full 40-character foundation/lane SHAs, positive worker count, `locked_test_opened is False`, and a nonexistent output path. Serialize canonical JSON with sorted keys, compact separators, UTF-8, trailing newline, and mode `0o600`; return a shared `ArtifactIdentity`.

`build_determinism_report()` requires equal SHA-256 identities for canonical predictions (including complete evidence ledgers), every raw TSV file in sorted relative-path order, config, row-ID sequence, and runtime/worker identity across two independent empty-cache runs. Latency/RSS measurements are reported as two observations and are not required to be byte-identical.

- [ ] **Step 5: Implement the privacy-safe checkpoint and handoff**

The checkpoint's measurement section contains only aggregate shared metric/resource fields,
paired development/validation deltas versus accepted and forced whole-page baselines, row
counts, and privacy-safe slice names. Minimum reportable sample sizes and all document-macro or
stratified slice enforcement belong to the central comparison package, not the foundation or
this lane. Error sections contain taxonomy counts, not examples. `next_action_or_stop` is
exactly one of `handoff_to_locked_comparison` or `stop_experiment_1` plus stable reasons.

`handoff.json` contains the shared `LaneDisposition`: `FROZEN_ELIGIBLE` when a complete,
deterministic validation freeze exists, otherwise `VALIDATION_STOPPED` with one stable
predeclared stop reason and its validation evidence. It also contains the frozen config
identity, freeze identity, deterministic-repeat identity, validation
prediction/metric/measurement identities, exact lane/foundation/runtime/worker identities,
and `locked_test_status: "not_opened"`. A stopped handoff has no frozen-arm manifest and is
never opened on locked data. The handoff contains no metric-driven production recommendation.
Extend `cli.py` with `repeat-validation`, `freeze-validation`, and `write-handoff`; each
command validates that its output path is under the lane private root before reading inputs
and prints only an aggregate success/failure line.

Define `OcrLaneHandoff` with `disposition`, optional `stop_reason`, optional frozen config/arm
manifest identities, validation prediction/metric/measurement identities, error-taxonomy
counts, deterministic-repeat identity when available, exact lane/foundation/runtime/worker
identities, and `locked_test_status: Literal["not_opened"]`. Eligible and stopped fields are
mutually validated. Both dispositions render the charter's exact eight checkpoint sections.

Run:

```bash
.venv/bin/ruff format experiments/row_extraction/arms/ocr/freeze.py experiments/row_extraction/arms/ocr/checkpoint.py experiments/row_extraction/arms/ocr/cli.py tests/experiments/row_extraction/arms/ocr/test_freeze.py tests/experiments/row_extraction/arms/ocr/test_checkpoint.py tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/pytest -q tests/experiments/row_extraction/arms/ocr/test_freeze.py tests/experiments/row_extraction/arms/ocr/test_checkpoint.py tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/ruff check experiments/row_extraction/arms/ocr/freeze.py experiments/row_extraction/arms/ocr/checkpoint.py experiments/row_extraction/arms/ocr/cli.py tests/experiments/row_extraction/arms/ocr/test_freeze.py tests/experiments/row_extraction/arms/ocr/test_checkpoint.py tests/experiments/row_extraction/arms/ocr/test_cli.py
.venv/bin/mypy experiments/row_extraction/arms/ocr/freeze.py experiments/row_extraction/arms/ocr/checkpoint.py experiments/row_extraction/arms/ocr/cli.py
```

Expected: all commands pass; repeated predictions/evidence/TSV must match byte-for-byte, freeze creation is exclusive, and checkpoint keys match the charter exactly.

- [ ] **Step 6: Run repository verification and commit Task 8**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/mypy experiments/row_extraction/arms/ocr
.venv/bin/pytest -q
git add experiments/row_extraction/arms/ocr/freeze.py experiments/row_extraction/arms/ocr/checkpoint.py experiments/row_extraction/arms/ocr/cli.py tests/experiments/row_extraction/arms/ocr/test_freeze.py tests/experiments/row_extraction/arms/ocr/test_checkpoint.py tests/experiments/row_extraction/arms/ocr/test_cli.py
git commit -m "experiment: freeze and hand off row OCR validation"
```

- [ ] **Step 7: Execute the six validation stages without exposing private output**

From the clean committed experiment branch, run each command in order. The CLI must print one privacy-safe aggregate line per stage:

```bash
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 01-crop-contract --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 02-language-order --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 03-dpi --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 04-thresholding --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 05-field-crops-and-cells --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
.venv/bin/python -m experiments.row_extraction.arms.ocr run-stage --stage 06-traineddata --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr
```

Expected: all six stages complete; each stage has development candidates, exactly one development challenger, validation incumbent/challenger outputs, a decision, and fixed row-ID parity. If any stage fails, retain private diagnostics, emit only a safe failure aggregate, stop later ablations, and proceed directly to Step 8's terminal-handoff path; do not skip the required disposition/checkpoint.

- [ ] **Step 8: Run independent empty-cache repeats, freeze, and create handoff**

For an eligible lane, use CLI subcommands implemented alongside `freeze.py`/`checkpoint.py`:
`repeat-validation` creates two new nonexistent run roots, `freeze-validation` verifies them
and writes the exclusive freeze, and `write-handoff` produces checkpoint/handoff files. For
a stopped stage, skip repeat/freeze commands and invoke `write-terminal-handoff` with the
failed stage evidence; it writes `VALIDATION_STOPPED`, the stable reason, complete available
validation metric/resource/error identities, and the same eight-section checkpoint.

```bash
.venv/bin/python -m experiments.row_extraction.arms.ocr repeat-validation --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr --repeat-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr/repeats
.venv/bin/python -m experiments.row_extraction.arms.ocr freeze-validation --shared-root /root/creditcard/artifacts/row-extraction/shared --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr --output /root/creditcard/artifacts/row-extraction/experiment-1-ocr/freeze/validation-freeze.json
.venv/bin/python -m experiments.row_extraction.arms.ocr write-handoff --lane-root /root/creditcard/artifacts/row-extraction/experiment-1-ocr --output /root/creditcard/artifacts/row-extraction/experiment-1-ocr/freeze/handoff.json
git status --short
```

Expected: repeat predictions (including evidence ledgers), row-ID sequence, and raw TSV hashes match; `locked_test_status` remains `not_opened`; the checkpoint has exactly eight sections; `git status --short` is empty because every generated artifact is ignored. Do not stage or commit anything under `artifacts/`.

## Locked-Comparison Handoff Boundary

Experiment 1 ends after Step 8. The common comparison owner—not this lane—may later consume
the frozen handoff for the charter's one locked measured run plus its sole determinism repeat.
That owner must verify the freeze and exact row/foundation/runtime/worker/arm/inventory
identities, construct two fresh factories and static locked `ResourceSpec` values with distinct
new caches/sinks, invoke `run_arm` once for each, require byte-identical predictions, and score
the first output beside all baselines and other lanes. Any configuration change, rerun for
tuning, added candidate, learned/neural recognizer, production edit, or row/split/label change
invalidates the handoff and requires stopping under the charter.

## Expected Handoff Contents

The private directory `/root/creditcard/artifacts/row-extraction/experiment-1-ocr/freeze/` must contain:

- `validation-freeze.json`: immutable chosen OCR config and full code/foundation/runtime/model/worker identity;
- `determinism.json`: equality evidence for two independent empty-cache validation runs;
- `checkpoint.json`: exactly the eight charter sections with privacy-safe aggregates and limitations;
- `handoff.json`: artifact identities required by the common locked-comparison runner;
- no PDFs, crops, OCR text, merchant strings, dates, amounts, totals, row/document IDs, raw predictions, or raw TSV copied into tracked files or public logs.

The handoff explicitly records these experiment-1 limitations: fixed-row conditional accuracy cannot recover missed rows; physical rows may not equal logical transactions; accepted-row survivorship bias remains; OCR confidence is not calibrated financial correctness; fixed-field crops can conceal cross-column context; higher DPI/padding/threshold/model packs may increase resource cost; and no validation result constitutes production corpus acceptance.
