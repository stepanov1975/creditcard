# Row-Vision Field Model Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether pixels from frozen transaction rows improve exact, evidence-grounded merchant and field-span recognition over the same nonvisual features, without changing row detection or authoring free-form values.

**Architecture:** Experiment 4 consumes foundation-owned `FrozenRow`, gold, split, feature, runner, metric, and JSONL contracts at the accepted SHA. A deterministic renderer produces fixed atom crops; a MobileNetV3-small encoder contributes a fixed-width visual vector to the same grounded BIO/row-type head used by a pixels-zeroed ablation. Both arms train, calibrate, and freeze independently, but use identical rows, labels, atom ordering, nonvisual features, head shape, training schedule, and evaluation procedures.

**Tech Stack:** Python 3.13; foundation `experiments.row_extraction` contracts; PyTorch 2.13.0; torchvision 0.28.0; NumPy 2.5.1; Pillow 12.3.0; safetensors 0.8.0; pytest, Ruff, and mypy; CPU-only deterministic inference.

## Global Constraints

- Before every task, answer: `Does this directly measure or improve transaction-row recognition or field extraction?` The task-specific scope block below is the required answer.
- Comparison anchor: exact source tree `dee4b071ad65231da13825f2f7c74a488ca96c7c`.
- Row identities, row bounding boxes, row count, document-disjoint split membership, gold labels, atom identities/order, column bands, shared feature schema, common prediction contract, common metrics, and common runner are read-only fixed inputs.
- All observations from one document, near-duplicate revision group, and layout-family group remain in one partition; the target partition ratio is 60% development/train, 20% calibration/validation, and 20% locked test.
- The model may predict only the closed `RowType` vocabulary and BIO roles over exact existing evidence atoms. It may not generate merchant strings, transaction JSON, dates, currencies, amounts, signs, installment values, or any other authoritative value.
- `FieldProposal` contains only a role, exact atom IDs and/or a source region, a raw score, and an optional fixed owner-row ID. Existing shared validators remain responsible for parsing and accepting exact evidence.
- Filenames, paths, hashes, document ordinals, merchant identities, exact dates, exact amounts, totals, template identities, and `FrozenRow.baseline_type` are forbidden predictive features. Paths and hashes may be used only for private storage integrity and artifact identity.
- Use `Decimal` for every financial number. Image tensors, feature values, logits, probabilities, latency, and statistical metrics may use floating point because they are not financial arithmetic.
- Private documents, crops, labels, split manifests, predictions, caches, checkpoints, calibrators, reports, artifact hashes, and derived values remain under ignored `artifacts/row-extraction/vision/`; tracked tests use only synthetic non-sensitive fixtures.
- Production `src/` is read-only. Shared foundation modules and experiment-3 lane modules are read-only. A shared-contract mismatch stops this lane and returns a proposal to the foundation branch.
- The only learned model is a compact MobileNetV3-small-class encoder with `weights=None` plus a small grounded head. LiLT, LayoutLM, Florence, Donut, TrOCR, VLMs, transformers, OCR-free generators, and other heavyweight challengers are forbidden by this plan.
- Neural dependencies live only in `.cache/row-vision-venv` and the lane-owned requirements files. Do not add them to normal project runtime dependencies.
- Development data trains models; calibration data selects calibrators, thresholds, and the pixel stop gate. This lane never receives locked-test data; only central comparison may load a ready frozen handoff on that split.
- Pixel-on must beat both the same-head pixels-zeroed ablation and the frozen best nonvisual control on calibration document-held-out selective risk. Otherwise record `STOP_NO_PIXEL_GAIN`, preserve validation evidence privately, and hand off the terminal stop without locked access.
- Every task follows RED/GREEN TDD, runs its focused tests, runs the experiment-lane type/tests, and runs all repository-required verification before committing.
- After every full `.venv/bin/pytest -q` run, execute `.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py` and require it to pass. The full suite must either pass after an upstream fix or reproduce exactly the five established inherited sandbox/controller failures; any new, removed, or changed failure stops the task.
- Before Task 1, read and verify `docs/superpowers/plans/2026-07-28-row-extraction-shared-foundation.md`; record the reviewed foundation commit in the private handoff. Do not begin against provisional shared types.

## Shared Interface Assumptions and Stop Gate

The foundation branch owns these imports and signatures; this plan does not create or alter
them:

```python
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
from experiments.row_extraction.contracts import FeatureSchema, FeatureVector
from experiments.row_extraction.metrics import MetricReport, score_predictions
from experiments.row_extraction.runner import ResourceSpec, RunMeasurements, run_arm
```

`ExperimentArm` has read-only `experiment_id: str`, `config_id: str`, and
`predict(row: FrozenRow) -> RowPrediction`. `resources.py` creates one static identity-bound
`ResourceSpec` per fresh run; `runner.run_arm(rows, factory, sink, resource_spec) ->
RunMeasurements` measures and publishes the same execution; `metrics.score_predictions(rows,
gold, predictions) -> MetricReport`; shared JSONL codecs stream records.

The lane additionally assumes these immutable field shapes, which Task 1 must verify before
any environment setup or code continues:

```python
# BBox is tuple[float, float, float, float] in (x0, y0, x1, y1) document points.
# EvidenceAtom: atom_id, text, bbox, source ("digital" or "ocr"), confidence,
#               column_index (int or None).
# ColumnBand: index, role (FieldRole or None), bbox.
# FrozenRow: document_id, row_id, split, source_pdf, page_number, bbox,
#            baseline_type, column_bands, atoms, render_version,
#            previous_row_id=None, next_row_id=None, gap_before=None,
#            gap_after=None. atoms are in canonical order. baseline_type is
#            forbidden to feature/model code.
# GoldField: role, canonical_value, atom_ids, source_region. canonical_value is
#            evaluation-only and never a model input or generated output.
# GoldRow: document_id, row_id, row_type, fields, ambiguous.
# FeatureSchema: version, names. Experiment 4 defines one equivalent nonvisual schema.
# FeatureVector: schema_version, row_id, values. Experiment 4 derives it from FrozenRow.
# ArtifactIdentity: artifact_type, sha256, version, byte_size.
# DatasetSplit values are "train", "validation", and "test".
# RowType values are "primary_transaction", "continuation", "structural",
# and "ambiguous". Decision values are "accept", "abstain", "reject", and
# "ignore".
# FieldProposal additionally has owner_row_id=None.
# RowPrediction constructor fields are experiment_id, config_id, document_id,
# row_id, predicted_type, evidence_atoms, proposals, exact_row_confidence,
# decision, reasons.
```

If the reviewed foundation uses different names while preserving semantics, stop and
reconcile this plan with the foundation owner before implementation. Do not add aliases or
parallel shared contracts in the vision lane.

## Planned File Map

- `experiments/row_extraction/arms/vision/__init__.py`: public lane exports only.
- `experiments/row_extraction/arms/vision/requirements.in`: exact direct experiment-only dependencies.
- `experiments/row_extraction/arms/vision/requirements.lock`: hash-locked transitive environment generated with pip-tools 7.6.0.
- `experiments/row_extraction/arms/vision/contracts.py`: foundation compatibility checks and lane protocols.
- `experiments/row_extraction/arms/vision/config.py`: immutable render/model/train/calibration/freeze configuration and canonical IDs.
- `experiments/row_extraction/arms/vision/render.py`: private crop index, integrity checking, deterministic row/atom tensor rendering.
- `experiments/row_extraction/arms/vision/features.py`: foundation row-feature validation, lane-local atom geometry/source/Unicode-shape features, and deterministic tensor batching.
- `experiments/row_extraction/arms/vision/labels.py`: stable row/BIO vocabulary and gold-to-mask encoding.
- `experiments/row_extraction/arms/vision/model.py`: compact MobileNetV3-small encoder and shared grounded head with pixels-on/off switch.
- `experiments/row_extraction/arms/vision/grounding.py`: constrained BIO decoding into exact `FieldProposal` atom spans.
- `experiments/row_extraction/arms/vision/artifacts.py`: safetensors/config identity, atomic private writes, and locked artifact loading.
- `experiments/row_extraction/arms/vision/train.py`: deterministic paired training and private development artifacts.
- `experiments/row_extraction/arms/vision/calibration.py`: exact-row isotonic calibration, threshold selection, and pixel stop gate.
- `experiments/row_extraction/arms/vision/arm.py`: `ExperimentArm` implementation returning common `RowPrediction` objects.
- `experiments/row_extraction/arms/vision/resources.py`: latency, RSS, model/dependency/cache bytes, and repeatability measurements.
- `experiments/row_extraction/arms/vision/cli.py`: split-safe lane workflow and validation-handoff commands.
- `tests/experiments/row_extraction/arms/vision/`: synthetic focused tests mirroring the modules above.

No task creates or modifies files outside those lane paths. The ignored private tree is:

```text
artifacts/row-extraction/vision/
├── crop-index.jsonl
├── crops/
├── development/{pixels-on,pixels-off}/
├── calibration/{pixels-on,pixels-off}/
├── frozen/{pixels-on,pixels-off}/
├── predictions/{train,validation}/
├── measurements/
└── validation-handoff.json
```

---

### Task 1: Lock the Experiment-Only Runtime and Foundation Boundary

```text
Scope answer: YES
Program component: experiment 4
Measured effect: dependency/model bytes and the invariant that experiment 4 consumes frozen rows, atoms, labels, and nonvisual features without a parallel contract
Fixed inputs: accepted SHA and foundation import/signature list above
Allowed files: experiments/row_extraction/arms/vision/{__init__.py,requirements.in,requirements.lock,contracts.py,config.py}; tests/experiments/row_extraction/arms/vision/test_contracts.py
Stop condition: stop on any missing/mismatched shared import, field, dtype, atom order, Python 3.13 wheel, or accepted SHA; do not patch shared modules
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/__init__.py`
- Create: `experiments/row_extraction/arms/vision/requirements.in`
- Create: `experiments/row_extraction/arms/vision/requirements.lock`
- Create: `experiments/row_extraction/arms/vision/contracts.py`
- Create: `experiments/row_extraction/arms/vision/config.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_contracts.py`

**Interfaces:**
- Consumes: the exact shared imports/signatures and field assumptions in the global stop gate.
- Produces: `VISION_EXPERIMENT_ID: str`, `VisionFeatureProvider`, `assert_foundation_contract(row: FrozenRow, schema: FeatureSchema, vector: FeatureVector) -> None`, `RenderConfig`, `ModelConfig`, `TrainConfig`, `CalibrationConfig`, and `VisionRunConfig`.

- [ ] **Step 1: Write the failing foundation-contract tests**

```python
import pytest

from experiments.row_extraction.arms.vision.contracts import assert_foundation_contract
from experiments.row_extraction.contracts import FeatureSchema, FeatureVector
from tests.experiments.row_extraction.factories import frozen_row


def test_foundation_contract_rejects_wrong_row_id() -> None:
    row = frozen_row()
    schema = FeatureSchema(version="row-features-v1", names=("source_ocr_ratio",))
    vector = FeatureVector(schema_version=schema.version, row_id="other-row", values=(0.5,))
    with pytest.raises(ValueError, match="feature row differs from frozen row"):
        assert_foundation_contract(row, schema, vector)


def test_foundation_contract_rejects_nonfinite_or_wrong_width() -> None:
    row = frozen_row()
    schema = FeatureSchema(version="row-features-v1", names=("a", "b"))
    short = FeatureVector(schema_version=schema.version, row_id=row.row_id, values=(0.5,))
    with pytest.raises(ValueError, match="feature width differs from frozen schema"):
        assert_foundation_contract(row, schema, short)
    nonfinite = short.model_copy(update={"values": (0.5, float("nan"))})
    with pytest.raises(ValueError, match="feature values must be finite"):
        assert_foundation_contract(row, schema, nonfinite)


def test_foundation_contract_rejects_accepted_baseline_feature() -> None:
    row = frozen_row()
    schema = FeatureSchema(version="bad-v1", names=("baseline_type",))
    vector = FeatureVector(schema_version=schema.version, row_id=row.row_id, values=(1.0,))
    with pytest.raises(ValueError, match="forbidden predictive feature"):
        assert_foundation_contract(row, schema, vector)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_contracts.py
```

Expected: FAIL during collection with
`ModuleNotFoundError: experiments.row_extraction.arms.vision.contracts`.
If it instead fails because the foundation imports or assumed fields do not exist, invoke
the stop condition and return the mismatch; do not continue to GREEN.

- [ ] **Step 3: Add exact direct dependencies and generate the hash lock**

Write `requirements.in` exactly as:

```text
numpy==2.5.1
pillow==12.3.0
safetensors==0.8.0
torch==2.13.0
torchvision==0.28.0
```

Then run:

```bash
git merge-base --is-ancestor dee4b071ad65231da13825f2f7c74a488ca96c7c HEAD
git diff --quiet dee4b071ad65231da13825f2f7c74a488ca96c7c -- src
.venv/bin/python -m venv .cache/row-vision-venv
.cache/row-vision-venv/bin/python -m pip install pip-tools==7.6.0
.cache/row-vision-venv/bin/pip-compile --generate-hashes --resolver=backtracking \
  --output-file experiments/row_extraction/arms/vision/requirements.lock \
  experiments/row_extraction/arms/vision/requirements.in
.cache/row-vision-venv/bin/python -m pip install --require-hashes \
  -r experiments/row_extraction/arms/vision/requirements.lock
.cache/row-vision-venv/bin/python -m pip install -e '.[dev]'
```

Expected: Python 3.13-compatible CPU wheels install and `pip check` below returns success.
If sandboxed network access fails, request approval for the same package commands and rerun;
do not substitute versions. If the resolver selects a CUDA-only build or no Python 3.13
wheel, stop.

- [ ] **Step 4: Implement immutable configuration and contract validation**

```python
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Protocol

from experiments.row_extraction.contracts import FrozenRow
from experiments.row_extraction.contracts import FeatureSchema, FeatureVector

VISION_EXPERIMENT_ID = "row-vision"


class VisionFeatureProvider(Protocol):
    @property
    def schema(self) -> FeatureSchema: ...

    def vectorize(self, row: FrozenRow) -> FeatureVector: ...


def assert_foundation_contract(
    row: FrozenRow, schema: FeatureSchema, vector: FeatureVector
) -> None:
    forbidden = {
        "baseline_type", "document_id", "source_pdf", "page_number", "row_id",
        "filename", "path", "hash", "merchant", "exact_date", "exact_amount",
        "total", "template_id",
    }
    if forbidden.intersection(schema.names):
        raise ValueError("forbidden predictive feature in frozen schema")
    if vector.schema_version != schema.version:
        raise ValueError("feature vector schema differs from frozen schema")
    if vector.row_id != row.row_id:
        raise ValueError("feature row differs from frozen row")
    if len(vector.values) != len(schema.names):
        raise ValueError("feature width differs from frozen schema")
    if not all(math.isfinite(value) for value in vector.values):
        raise ValueError("feature values must be finite")


def feature_schema_sha256(schema: FeatureSchema) -> str:
    payload = {"names": list(schema.names), "version": schema.version}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
```

Define configs as frozen dataclasses with no environment-derived defaults:

```python
@dataclass(frozen=True)
class RenderConfig:
    version: str = "row-atom-render-v1"
    row_width: int = 512
    row_height: int = 64
    atom_width: int = 128
    atom_height: int = 32
    atom_padding_points: str = "1.50"
    background: int = 255
    interpolation: str = "bilinear"


@dataclass(frozen=True)
class ModelConfig:
    visual_width: int = 64
    row_feature_width: int = 64
    atom_feature_width: int = 32
    hidden_width: int = 96
    dropout: float = 0.0
    pretrained_weights: None = None


@dataclass(frozen=True)
class TrainConfig:
    seed: int = 1729
    epochs: int = 40
    batch_rows: int = 8
    learning_rate: float = 0.0003
    weight_decay: float = 0.0001
    row_loss_weight: float = 1.0
    atom_loss_weight: float = 1.0
    cpu_threads: int = 1


@dataclass(frozen=True)
class CalibrationConfig:
    target_row_risk: float = 0.01
    bootstrap_seed: int = 2718
    bootstrap_replicates: int = 2000


@dataclass(frozen=True)
class VisionRunConfig:
    experiment_id: str
    development_tier: str
    pixels_enabled: bool
    feature_schema_version: str
    feature_schema_sha256: str
    render: RenderConfig
    model: ModelConfig
    train: TrainConfig
    calibration: CalibrationConfig

    @property
    def config_id(self) -> str:
        return canonical_config_sha256(self)
```

Canonicalize config with sorted-key, compact UTF-8 JSON and derive `config_id` from SHA-256.
Reject non-`None` `pretrained_weights` and any experiment ID other than `row-vision`.

- [ ] **Step 5: Run GREEN and environment checks**

Run:

```bash
.cache/row-vision-venv/bin/python -m pip check
.cache/row-vision-venv/bin/python -c 'import torch, torchvision; from torchvision.models import mobilenet_v3_small; assert torch.__version__.startswith("2.13.0"); assert torchvision.__version__.startswith("0.28.0"); mobilenet_v3_small(weights=None).eval()'
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_contracts.py
```

Expected: all commands exit 0 and the focused tests pass.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision tests/experiments/row_extraction/arms/vision/test_contracts.py
git commit -m "experiment: lock row vision runtime and contracts"
```

Expected: the mandatory verification policy in Global Constraints is satisfied; the commit
contains no `src/` or private artifact.

### Task 2: Render Frozen Row and Atom Crops Deterministically

```text
Scope answer: YES
Program component: experiment 4
Measured effect: pixel input repeatability and crop truncation/neighbor-contamination errors for fixed evidence atoms
Fixed inputs: FrozenRow bbox and canonical evidence atom IDs/bboxes; foundation-generated private row crop and its digest
Allowed files: experiments/row_extraction/arms/vision/render.py; tests/experiments/row_extraction/arms/vision/test_render.py
Stop condition: stop if rendering requires a new row box, a page/row detector, production PDF changes, or a crop whose document/row/bbox/digest does not match the frozen record
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/render.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_render.py`

**Interfaces:**
- Consumes: `FrozenRow`, `BBox`, `RenderConfig`, and private foundation row-crop bytes indexed by opaque document/row IDs.
- Produces: `PrivateCropStore.load(row: FrozenRow) -> PIL.Image.Image`, `RenderedAtoms`, and `render_atoms(row: FrozenRow, image: Image.Image, config: RenderConfig) -> RenderedAtoms`; consumes the foundation-owned `CropRecord` rather than defining another crop-index schema.

Import `CropRecord` from `experiments.row_extraction.crops`; a missing shared crop record is a
foundation stop condition, not permission to add a lane-local schema.

- [ ] **Step 1: Write RED tests for integrity, coordinates, and repeated bytes**

```python
from hashlib import sha256

import torch

from experiments.row_extraction.arms.vision.render import render_atoms


def test_render_atoms_preserves_canonical_order_and_is_byte_identical(
    synthetic_row, synthetic_row_image, render_config
) -> None:
    first = render_atoms(synthetic_row, synthetic_row_image, render_config)
    second = render_atoms(synthetic_row, synthetic_row_image, render_config)
    assert first.atom_ids == tuple(atom.atom_id for atom in synthetic_row.atoms)
    assert first.row_image.shape == (3, 64, 512)
    assert first.atom_images.shape == (len(first.atom_ids), 3, 32, 128)
    assert torch.equal(first.row_image, second.row_image)
    assert torch.equal(first.atom_images, second.atom_images)
    assert sha256(first.atom_images.numpy().tobytes()).digest() == sha256(
        second.atom_images.numpy().tobytes()
    ).digest()


def test_render_atoms_clamps_padding_to_frozen_row(
    synthetic_edge_atom_row, synthetic_row_image, render_config
) -> None:
    rendered = render_atoms(synthetic_edge_atom_row, synthetic_row_image, render_config)
    assert rendered.source_pixel_boxes[0][0] == 0
    assert rendered.source_pixel_boxes[0][1] == 0
```

Add a store test whose index digest is deliberately wrong and assert
`ValueError("private row crop digest mismatch")` before image decoding.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_render.py
```

Expected: FAIL during collection with
`ModuleNotFoundError: experiments.row_extraction.arms.vision.render`.

- [ ] **Step 3: Implement the private crop store and deterministic renderer**

```python
@dataclass(frozen=True)
class RenderedAtoms:
    atom_ids: tuple[str, ...]
    row_image: torch.Tensor
    atom_images: torch.Tensor
    source_pixel_boxes: tuple[tuple[int, int, int, int], ...]


def _point_box_to_pixels(atom: BBox, row: BBox, width: int, height: int) -> tuple[int, int, int, int]:
    if not (row[0] <= atom[0] <= atom[2] <= row[2] and row[1] <= atom[1] <= atom[3] <= row[3]):
        raise ValueError("evidence atom leaves frozen row bbox")
    sx = Decimal(width) / Decimal(str(row[2] - row[0]))
    sy = Decimal(height) / Decimal(str(row[3] - row[1]))
    x0 = int(((Decimal(str(atom[0] - row[0]))) * sx).to_integral_value(rounding=ROUND_FLOOR))
    y0 = int(((Decimal(str(atom[1] - row[1]))) * sy).to_integral_value(rounding=ROUND_FLOOR))
    x1 = int(((Decimal(str(atom[2] - row[0]))) * sx).to_integral_value(rounding=ROUND_CEILING))
    y1 = int(((Decimal(str(atom[3] - row[1]))) * sy).to_integral_value(rounding=ROUND_CEILING))
    return max(0, x0), max(0, y0), min(width, x1), min(height, y1)
```

`PrivateCropStore` must load `crop-index.jsonl` as a key-to-record index without exposing
paths to model features, resolve paths strictly below its configured private root, validate
document ID, row ID, exact bbox, byte SHA-256, decoded dimensions, grayscale/RGB conversion,
and reject symlinks or traversal. `render_atoms` must:

1. validate the image is the frozen row crop;
2. convert to RGB;
3. resize the whole row to 512 x 64 with Pillow bilinear interpolation;
4. map each atom bbox with floor-left/top and ceil-right/bottom;
5. expand by exactly 1.50 document points, clamped to the row;
6. fill degenerate/empty crops with the configured white background and record a stable
   `degenerate_atom_crop` condition for later abstention;
7. resize every atom crop to 128 x 32 bilinearly; and
8. return contiguous `torch.float32` CHW tensors normalized to `[0, 1]` in canonical atom
   order.

No random crop, flip, color jitter, antialias setting, or training-only rendering branch is
allowed.

- [ ] **Step 4: Run GREEN and a repeated synthetic hash check**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_render.py
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_render.py
```

Expected: PASS twice with identical expected tensor hashes.

- [ ] **Step 5: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/render.py tests/experiments/row_extraction/arms/vision/test_render.py
git commit -m "experiment: render fixed row atom crops"
```

Expected: the mandatory verification policy is satisfied; no crop, digest, or private path is staged.

### Task 3: Build Comparable Nonvisual Tensors and Grounded Gold Labels

```text
Scope answer: YES
Program component: experiment 4
Measured effect: exact atom-span/row-type supervision and the invariant that pixels-on/off receive identical frozen row features and deterministic atom geometry/source/Unicode-shape features
Fixed inputs: foundation FeatureSchema/FeatureVector contracts, FrozenRow.atoms canonical order, GoldRow/GoldField atom labels, closed shared RowType/FieldRole values
Allowed files: experiments/row_extraction/arms/vision/{features.py,labels.py}; tests/experiments/row_extraction/arms/vision/{test_features.py,test_labels.py}
Stop condition: stop if feature extraction would import mutable experiment-3 lane code, if labels require free-form field values, or if ambiguous gold must be coerced
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/features.py`
- Create: `experiments/row_extraction/arms/vision/labels.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_features.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_labels.py`

**Interfaces:**
- Consumes: `FeatureSchema`, `FeatureVector`, `FrozenRow`, `GoldRow`, `FieldRole`, `RowType`, and `RenderedAtoms`.
- Produces: `NONVISUAL_FEATURE_NAMES`, `nonvisual_schema() -> FeatureSchema`, `build_nonvisual_vector(row: FrozenRow) -> FeatureVector`, `FrozenFeatureStore` implementing `VisionFeatureProvider`, `ATOM_FEATURE_NAMES`, `AtomFeatureTensor`, `LabelVocabulary`, `GoldTargets`, `build_atom_features(...) -> AtomFeatureTensor`, and `encode_gold(row: FrozenRow, gold: GoldRow, vocabulary: LabelVocabulary) -> GoldTargets`.

- [ ] **Step 1: Write RED tests for masked features and exact gold atom support**

```python
import torch

from experiments.row_extraction.arms.vision.features import (
    build_atom_features,
    build_nonvisual_vector,
)
from experiments.row_extraction.arms.vision.labels import LabelVocabulary, encode_gold


def test_pixel_ablation_changes_only_pixel_mask(
    synthetic_row, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms
) -> None:
    on = build_atom_features(
        synthetic_row, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms, True
    )
    off = build_atom_features(
        synthetic_row, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms, False
    )
    assert torch.equal(on.row_values, off.row_values)
    assert torch.equal(on.atom_values, off.atom_values)
    assert torch.equal(on.atom_images, off.atom_images)
    assert on.pixels_enabled is True
    assert off.pixels_enabled is False


def test_ambiguous_gold_row_is_fully_masked(synthetic_row, ambiguous_gold) -> None:
    targets = encode_gold(synthetic_row, ambiguous_gold, LabelVocabulary.from_shared_enums())
    assert targets.row_loss_mask.item() is False
    assert targets.atom_loss_mask.tolist() == [False] * len(synthetic_row.atoms)


def test_accepted_baseline_type_cannot_change_features(
    synthetic_row, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms
) -> None:
    changed = synthetic_row.model_copy(update={"baseline_type": RowType.AMBIGUOUS})
    assert build_nonvisual_vector(changed) == build_nonvisual_vector(synthetic_row)
    original = build_atom_features(
        synthetic_row, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms, True
    )
    changed_features = build_atom_features(
        changed, synthetic_feature_schema, synthetic_feature_vector, rendered_atoms, True
    )
    assert torch.equal(original.row_values, changed_features.row_values)
    assert torch.equal(original.atom_values, changed_features.atom_values)
```

Also test that overlapping non-ambiguous gold fields, missing atom IDs, reordered feature
records, duplicate/missing row feature vectors, and a gold document/row mismatch raise stable
`ValueError`s.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_features.py \
  tests/experiments/row_extraction/arms/vision/test_labels.py
```

Expected: FAIL during collection because `features` and `labels` do not exist.

- [ ] **Step 3: Implement exact tensor and label contracts**

```python
ATOM_FEATURE_NAMES = (
    "x0_norm", "y0_norm", "x1_norm", "y1_norm", "width_norm", "height_norm",
    "source_confidence", "is_ocr", "has_column", "column_fraction", "length_norm",
    "digit_ratio", "letter_ratio", "punctuation_ratio", "rtl_ratio",
    "currency_symbol_ratio", "looks_date", "looks_money", "mixed_script",
)


@dataclass(frozen=True)
class AtomFeatureTensor:
    atom_ids: tuple[str, ...]
    row_values: torch.Tensor
    atom_values: torch.Tensor
    atom_images: torch.Tensor
    atom_mask: torch.Tensor
    pixels_enabled: bool


@dataclass(frozen=True)
class GoldTargets:
    atom_ids: tuple[str, ...]
    row_type_index: torch.Tensor
    row_loss_mask: torch.Tensor
    bio_indices: torch.Tensor
    atom_loss_mask: torch.Tensor
```

`build_nonvisual_vector` deterministically derives an experiment-4-owned equivalent
nonvisual control from allowed aggregate row geometry, source-confidence, column occupancy,
Unicode/character-shape, and generic date/money-shape signals. Its closed
`NONVISUAL_FEATURE_NAMES` tuple is the `FeatureSchema`; it excludes raw token strings,
accepted `baseline_type`, identifiers, source paths, exact dates, exact amounts, currencies,
and merchant values. Task 3 materializes these vectors from TRAIN and VALIDATION `FrozenRow`
streams through shared codecs before model training; no experiment-3 artifact or code is
imported.

`build_atom_features` first calls `assert_foundation_contract`, converts the flat frozen
`FeatureVector.values` to one `torch.float32` row tensor, and derives the 19 named atom
features in canonical `FrozenRow.atoms` order. Geometry is normalized only against the fixed
row bbox; source is `digital`/`ocr`; column membership comes only from `column_index`; and
text contributes only Unicode/character-shape ratios and generic date/money shape booleans.
No raw atom text, n-gram, merchant, date, or amount value is retained in tensors or tracked
artifacts. Missing column index is represented by `has_column=0` and `column_fraction=0`.
The pixels-off arm retains the identical image tensor and head input dimensions; only the
immutable `pixels_enabled` flag causes the model to replace visual embeddings with exact
zeroes.

`FrozenFeatureStore` reads the lane-generated private `FeatureSchema` record and streams
the lane-generated `FeatureVector` JSONL through the shared codecs into an immutable row-ID index. It rejects
duplicate IDs, missing/extra requested rows, schema-version drift, non-finite values, and
width mismatches. It exposes only `schema` and `vectorize(row)` and never imports
`experiments.row_extraction.arms.text`. The schema/vector artifact identities are frozen in
both arm configs so experiment 4 and its pixels-off ablation consume the same equivalent
nonvisual values.

Create vocabulary without relying on enum declaration order:

```python
@dataclass(frozen=True)
class LabelVocabulary:
    row_types: tuple[RowType, ...]
    bio_labels: tuple[str, ...]

    @classmethod
    def from_shared_enums(cls) -> "LabelVocabulary":
        row_types = tuple(sorted(RowType, key=lambda item: item.value))
        roles = tuple(sorted(FieldRole, key=lambda item: item.value))
        labels = ("O",) + tuple(
            label
            for role in roles
            for label in (f"B:{role.value}", f"I:{role.value}")
        )
        return cls(row_types=row_types, bio_labels=labels)
```

`encode_gold` marks every uniquely supported field with one `B` followed by `I` labels in
canonical atom order. It never reads `GoldField.canonical_value`. A `GoldRow.ambiguous` row
is fully masked from both losses. Unlabeled atoms in a reviewed unambiguous row are `O`.
`GoldField.atom_ids` must be nonempty; an optional `source_region` is validation context only.
Missing, reordered, noncontiguous, multiply resolvable, or overlapping support is a hard
eligibility error rather than a coerced label.

- [ ] **Step 4: Run GREEN**

```bash
.cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_features.py \
  tests/experiments/row_extraction/arms/vision/test_labels.py
```

Expected: PASS with no dtype, order, overlap, or ambiguity failures.

- [ ] **Step 5: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/features.py experiments/row_extraction/arms/vision/labels.py tests/experiments/row_extraction/arms/vision/test_features.py tests/experiments/row_extraction/arms/vision/test_labels.py
git commit -m "experiment: encode grounded vision features and labels"
```

Expected: the mandatory verification policy is satisfied and the commit contains synthetic data only.

### Task 4: Implement the Compact MobileNetV3-Small Model and Matched Ablation

```text
Scope answer: YES
Program component: experiment 4
Measured effect: incremental row-type and exact atom-role signal contributed by pixels over an otherwise identical nonvisual head
Fixed inputs: feature tensors, role vocabulary, architecture widths, weights=None, seed, and pixels-on/off as the only arm difference
Allowed files: experiments/row_extraction/arms/vision/model.py; tests/experiments/row_extraction/arms/vision/test_model.py
Stop condition: stop if implementation requires pretrained weights, a transformer/generator, free-form decoding, more than 3,000,000 parameters, GPU-only operators, or a different head/nonvisual tensor between ablations
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/model.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_model.py`

**Interfaces:**
- Consumes: `AtomFeatureTensor`, `FeatureSchema`, `LabelVocabulary`, and `ModelConfig`.
- Produces: `ModelOutput(row_type_logits: Tensor, bio_logits: Tensor, raw_exact_score: Tensor)` and `RowVisionModel.forward(features: AtomFeatureTensor) -> ModelOutput`.

- [ ] **Step 1: Write RED tests for shape, size, and the matched zero-pixel path**

```python
import torch

from experiments.row_extraction.arms.vision.model import RowVisionModel


def test_model_is_compact_and_outputs_one_label_per_atom(model_inputs, schema, vocabulary) -> None:
    model = RowVisionModel(schema, vocabulary, model_inputs.config)
    output = model(model_inputs.features)
    assert sum(parameter.numel() for parameter in model.parameters()) < 3_000_000
    assert output.row_type_logits.shape == (len(vocabulary.row_types),)
    assert output.bio_logits.shape == (
        len(model_inputs.features.atom_ids), len(vocabulary.bio_labels)
    )
    assert output.raw_exact_score.shape == ()


def test_pixels_off_does_not_call_encoder(model_inputs, schema, vocabulary, monkeypatch) -> None:
    model = RowVisionModel(schema, vocabulary, model_inputs.config)
    monkeypatch.setattr(
        model,
        "encode_pixels",
        lambda images: (_ for _ in ()).throw(AssertionError("encoder called")),
    )
    output = model(model_inputs.features_with_pixels(False))
    assert torch.isfinite(output.bio_logits).all()
```

Add a test that constructs pixels-on and pixels-off models from the same state dict and
asserts identical parameter names, shapes, initial bytes, row/nonvisual inputs, and head
dimensions.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_model.py
```

Expected: FAIL during collection because `model.py` does not exist.

- [ ] **Step 3: Implement the compact encoder and common head**

```python
@dataclass(frozen=True)
class ModelOutput:
    row_type_logits: torch.Tensor
    bio_logits: torch.Tensor
    raw_exact_score: torch.Tensor


class RowVisionModel(nn.Module):
    def __init__(self, schema: FeatureSchema, vocabulary: LabelVocabulary, config: ModelConfig):
        super().__init__()
        backbone = mobilenet_v3_small(weights=None, dropout=0.0)
        self.visual_features = backbone.features
        self.visual_pool = nn.AdaptiveAvgPool2d(1)
        self.visual_projection = nn.Linear(576, config.visual_width)
        self.row_projection = nn.Linear(len(schema.names), config.row_feature_width)
        self.atom_projection = nn.Linear(len(ATOM_FEATURE_NAMES), config.atom_feature_width)
        joint_width = (
            config.visual_width + config.row_feature_width + config.atom_feature_width
        )
        self.joint = nn.Sequential(nn.Linear(joint_width, config.hidden_width), nn.GELU())
        self.bio_head = nn.Linear(config.hidden_width, len(vocabulary.bio_labels))
        self.row_head = nn.Linear(config.hidden_width, len(vocabulary.row_types))

    def encode_pixels(self, images: torch.Tensor) -> torch.Tensor:
        encoded = self.visual_features(images)
        pooled = self.visual_pool(encoded).flatten(1)
        return self.visual_projection(pooled)

    def forward(self, features: AtomFeatureTensor) -> ModelOutput:
        count = len(features.atom_ids)
        if count == 0:
            raise ValueError("vision model requires at least one fixed evidence atom")
        visual = (
            self.encode_pixels(features.atom_images)
            if features.pixels_enabled
            else features.atom_images.new_zeros((count, self.visual_projection.out_features))
        )
        row = self.row_projection(features.row_values).expand(count, -1)
        atom = self.atom_projection(features.atom_values)
        hidden = self.joint(torch.cat((row, atom, visual), dim=1))
        bio_logits = self.bio_head(hidden)
        row_logits = self.row_head(hidden.mean(dim=0))
        row_probability = row_logits.softmax(dim=0).amax()
        atom_probability = bio_logits.softmax(dim=1).amax(dim=1).values.amin()
        return ModelOutput(row_logits, bio_logits, torch.minimum(row_probability, atom_probability))
```

Use CPU `torch.float32` only. Do not add stochastic augmentation, dropout, batch-normalization
updates during prediction, pretrained downloads, OCR, or image-to-text output.

- [ ] **Step 4: Run GREEN**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_model.py
```

Expected: PASS; model parameter count is below 3,000,000 and pixels-off never calls the
encoder.

- [ ] **Step 5: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/model.py tests/experiments/row_extraction/arms/vision/test_model.py
git commit -m "experiment: add compact grounded row vision model"
```

Expected: the mandatory verification policy is satisfied.

### Task 5: Decode Legal BIO Spans and Implement the Common Experiment Arm

```text
Scope answer: YES
Program component: experiment 4
Measured effect: exact evidence-span precision/recall, unsupported-evidence rate, ownership collision rate, and explicit abstention
Fixed inputs: canonical fixed atoms, closed BIO vocabulary, model logits, common FieldProposal/RowPrediction contracts
Allowed files: experiments/row_extraction/arms/vision/{grounding.py,arm.py}; tests/experiments/row_extraction/arms/vision/{test_grounding.py,test_arm.py}
Stop condition: stop if a proposal cannot resolve to one nonempty contiguous fixed-atom span, if decoding needs generated text, or if existing supported values would be overridden
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/grounding.py`
- Create: `experiments/row_extraction/arms/vision/arm.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_grounding.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_arm.py`

**Interfaces:**
- Consumes: `FrozenRow`, `ModelOutput`, `LabelVocabulary`, `RowVisionModel`, `PrivateCropStore`, `VisionFeatureProvider`, and a `ConfidenceCalibrator`.
- Produces: `GroundedDecode`, `decode_grounded(...) -> GroundedDecode`, `ConfidenceCalibrator.calibrate(raw_score: float) -> float`, `VisionArm` implementing `ExperimentArm`, and `VisionArmFactory` with a frozen-arm manifest identity, fresh model loading, and exact zero subprocess count.

- [ ] **Step 1: Write RED tests for legal decoding and exact support**

```python
from experiments.row_extraction.arms.vision.grounding import decode_grounded


def test_decode_returns_only_exact_nonempty_atom_spans(synthetic_row, vocabulary, logits) -> None:
    decoded = decode_grounded(synthetic_row, vocabulary, logits)
    known = {atom.atom_id for atom in synthetic_row.atoms}
    assert decoded.proposals
    for proposal in decoded.proposals:
        assert proposal.atom_ids
        assert set(proposal.atom_ids) <= known
        assert proposal.source_region is None
        assert proposal.owner_row_id in {None, synthetic_row.previous_row_id}


def test_tied_logits_choose_lowest_legal_label_index(synthetic_row, vocabulary) -> None:
    tied = torch.zeros((len(synthetic_row.atoms), len(vocabulary.bio_labels)))
    first = decode_grounded(synthetic_row, vocabulary, tied)
    second = decode_grounded(synthetic_row, vocabulary, tied)
    assert first == second
```

For `VisionArm`, assert `prediction.evidence_atoms == row.atoms`, every proposal has exact
atom support, `exact_row_confidence` comes only from the calibrator, below-threshold rows use
`Decision.ABSTAIN`, and no prediction field contains `GoldField.canonical_value`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_grounding.py \
  tests/experiments/row_extraction/arms/vision/test_arm.py
```

Expected: FAIL during collection because `grounding.py` and `arm.py` do not exist.

- [ ] **Step 3: Implement constrained Viterbi decoding**

Implement transitions so `I:<role>` can follow only `B:<role>` or `I:<role>`, `B` and `O`
may follow any legal state, and ties choose the lower vocabulary index. Convert each `B/I`
run to one proposal:

```python
@dataclass(frozen=True)
class GroundedDecode:
    predicted_type: RowType
    proposals: tuple[FieldProposal, ...]
    raw_exact_score: float
    reasons: tuple[str, ...]


def _proposal(
    role: FieldRole,
    atoms: tuple[EvidenceAtom, ...],
    score: float,
    owner_row_id: str | None,
) -> FieldProposal:
    atom_ids = tuple(atom.atom_id for atom in atoms)
    if not atom_ids or len(set(atom_ids)) != len(atom_ids):
        raise ValueError("grounded proposal requires unique fixed atoms")
    return FieldProposal(
        role=role,
        atom_ids=atom_ids,
        source_region=None,
        raw_score=score,
        owner_row_id=owner_row_id,
    )
```

Reject duplicate atom IDs in the row, non-finite logits, illegal vocabulary labels, proposal
overlap, or role runs that are noncontiguous in canonical order. Scores are softmax
probabilities over chosen legal labels; they are not financial values. Primary-transaction
proposals use `None`, whose shared meaning is the current frozen row. Continuation proposals use only the fixed
`row.previous_row_id`; if it is absent, the row abstains with
`continuation_owner_unavailable`. Structural/unsupported row types emit no proposals.
`previous_row_id`, `next_row_id`, and gaps may be used for deterministic ownership
validation but never embedded as identity features. `baseline_type` is never read.

- [ ] **Step 4: Implement `VisionArm.predict`**

```python
class ConfidenceCalibrator(Protocol):
    def calibrate(self, raw_score: float) -> float: ...


class VisionArm(ExperimentArm):
    @property
    def experiment_id(self) -> str:
        return self._config.experiment_id

    @property
    def config_id(self) -> str:
        return self._config.config_id

    def predict(self, row: FrozenRow) -> RowPrediction:
        vector = self._features.vectorize(row)
        assert_foundation_contract(row, self._features.schema, vector)
        image = self._crops.load(row)
        rendered = render_atoms(row, image, self._config.render)
        tensors = build_atom_features(
            row, self._features.schema, vector, rendered, self._config.pixels_enabled
        )
        self._model.eval()
        with torch.inference_mode():
            decoded = decode_grounded(row, self._vocabulary, self._model(tensors))
        confidence = self._calibrator.calibrate(decoded.raw_exact_score)
        emit = confidence >= self._threshold and not decoded.reasons
        return RowPrediction(
            experiment_id=self.experiment_id,
            config_id=self.config_id,
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=decoded.predicted_type,
            evidence_atoms=row.atoms,
            proposals=decoded.proposals if emit else (),
            exact_row_confidence=confidence,
            decision=Decision.ACCEPT if emit else Decision.ABSTAIN,
            reasons=decoded.reasons if emit else decoded.reasons + ("below_exact_row_threshold",),
        )
```

An abstention has no proposals. The arm never reads `source_pdf`, filename components, page
number, canonical values, totals, or document identity as features.

- [ ] **Step 5: Run GREEN**

```bash
.cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_grounding.py \
  tests/experiments/row_extraction/arms/vision/test_arm.py
```

Expected: PASS; all emitted proposals are exact atom spans and every unsupported case
abstains.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/grounding.py experiments/row_extraction/arms/vision/arm.py tests/experiments/row_extraction/arms/vision/test_grounding.py tests/experiments/row_extraction/arms/vision/test_arm.py
git commit -m "experiment: ground row vision predictions in evidence"
```

Expected: the mandatory verification policy is satisfied.

### Task 6: Train Matched Pixels-On and Pixels-Off Arms Deterministically

```text
Scope answer: YES
Program component: experiment 4
Measured effect: development exact span, merchant, and complete-row loss for pixels-on versus pixels-off under matched initialization and schedule
Fixed inputs: development partition/tier manifests, gold atom labels, feature schema, render/model/train configs, seed 1729, CPU threads 1
Allowed files: experiments/row_extraction/arms/vision/{artifacts.py,train.py}; tests/experiments/row_extraction/arms/vision/{test_artifacts.py,test_train.py}
Stop condition: stop on locked/calibration rows in training, nondeterministic operators, unequal head initialization/schedule, pretrained downloads, or private artifact writes outside the ignored lane root
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/artifacts.py`
- Create: `experiments/row_extraction/arms/vision/train.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_artifacts.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_train.py`

**Interfaces:**
- Consumes: development `FrozenRow`/`GoldRow` pairs, feature/crop providers, `VisionRunConfig`, `RowVisionModel`, and `GoldTargets`.
- Produces: `TrainedArtifact(identity: ArtifactIdentity, weights_path: Path, config_path: Path)`, `train_arm(...) -> TrainedArtifact`, and `train_matched_pair(...) -> tuple[TrainedArtifact, TrainedArtifact]`.

- [ ] **Step 1: Write RED tests for split refusal, equal starts, and stable artifacts**

```python
def test_training_refuses_non_development_rows(training_case) -> None:
    calibration_row = training_case.row.model_copy(update={"split": DatasetSplit.VALIDATION})
    with pytest.raises(ValueError, match="training accepts development rows only"):
        train_arm((calibration_row,), training_case.gold, training_case.context)


def test_matched_pair_starts_from_identical_state(training_case) -> None:
    result = train_matched_pair(training_case.context)
    assert result.initial_state_sha256_on == result.initial_state_sha256_off
    assert result.schedule_sha256_on == result.schedule_sha256_off


def test_safetensor_bytes_repeat_for_same_state(tmp_path, model) -> None:
    first = save_model_state(model, tmp_path / "first.safetensors")
    second = save_model_state(model, tmp_path / "second.safetensors")
    assert first.sha256 == second.sha256
    assert (tmp_path / "first.safetensors").read_bytes() == (
        tmp_path / "second.safetensors"
    ).read_bytes()
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_artifacts.py \
  tests/experiments/row_extraction/arms/vision/test_train.py
```

Expected: FAIL during collection because `artifacts.py` and `train.py` do not exist.

- [ ] **Step 3: Implement canonical private artifacts**

Save a sorted, contiguous CPU state dict with safetensors and no private metadata embedded:

```python
def save_model_state(model: nn.Module, path: Path, version: str) -> ArtifactIdentity:
    tensors = {
        name: tensor.detach().cpu().contiguous()
        for name, tensor in sorted(model.state_dict().items())
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    save_file(tensors, temporary, metadata={"format": "row-vision-v1", "version": version})
    temporary.replace(path)
    digest = sha256(path.read_bytes()).hexdigest()
    return ArtifactIdentity(
        artifact_type="row-vision-safetensors",
        sha256=digest,
        version=version,
        byte_size=path.stat().st_size,
    )
```

Write config JSON with sorted keys, compact separators, UTF-8, mode `0o600`, and atomic
rename. Load only if artifact type, version, byte count, and SHA-256 match. Private digests
belong in private manifests and `ArtifactIdentity`, not tracked reports or commit messages.

- [ ] **Step 4: Implement deterministic paired training**

Set `PYTHONHASHSEED` in the invoking command, seed Python/NumPy/PyTorch, call
`torch.use_deterministic_algorithms(True)`, set intra/inter-op threads to 1 once at process
start, use CPU float32, and sort input by `(document_id, row_id)`. Create one initial model,
hash its state, clone it into both arms, and use the same epoch permutation generated by a
private `torch.Generator().manual_seed(1729 + epoch)`.

Use AdamW with the frozen learning rate/weight decay. Loss is masked row-type cross entropy
plus masked BIO cross entropy; a batch with no unambiguous target for a loss contributes
zero to that loss. Train exactly 40 epochs with no early stopping or calibration access.
Run predeclared document-grouped development tiers targeting 100, 250, 500, and all eligible
rows without splitting a document; record actual row/document counts privately.

- [ ] **Step 5: Run GREEN and repeat training on the synthetic fixture**

```bash
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_artifacts.py \
  tests/experiments/row_extraction/arms/vision/test_train.py
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_train.py::test_repeated_training_has_identical_artifact
```

Expected: PASS; repeated synthetic training produces byte-identical weights and schedules.
If PyTorch raises for a nondeterministic operator, stop and replace that operator with a
deterministic CPU alternative; do not disable deterministic algorithms.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/artifacts.py experiments/row_extraction/arms/vision/train.py tests/experiments/row_extraction/arms/vision/test_artifacts.py tests/experiments/row_extraction/arms/vision/test_train.py
git commit -m "experiment: train matched deterministic vision arms"
```

Expected: the mandatory verification policy is satisfied; `git status --short` contains no `artifacts/` entry.

### Task 7: Calibrate Exact-Row Confidence, Apply the Pixel Stop Gate, and Freeze

```text
Scope answer: YES
Program component: experiment 4
Measured effect: Brier/log loss, risk-coverage/AURC, coverage at 1% exact-row risk, false accepts, and document-held-out pixel gain versus both nonvisual controls
Fixed inputs: frozen calibration partition, paired arm predictions, common exact atom-span gold, best nonvisual-control predictions, calibration seed 2718
Allowed files: experiments/row_extraction/arms/vision/calibration.py; tests/experiments/row_extraction/arms/vision/test_calibration.py
Stop condition: record STOP_NO_PIXEL_GAIN and stop further model work unless pixels-on has lower calibration document-macro AURC than both controls, no greater false-accept count, and no lower coverage at the 1% risk target; in stopped mode continue only through Task 9 terminal freeze/checkpoint/handoff, and never access locked test
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/calibration.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_calibration.py`

**Interfaces:**
- Consumes: calibration `GoldRow`/`RowPrediction` pairs, frozen nonvisual-control predictions, `CalibrationConfig`, and private trained artifacts.
- Produces: `CalibrationObservation`, `IsotonicCalibrator`, `SelectiveSummary`, `PixelGateDecision`, `fit_isotonic(...)`, `select_threshold(...)`, and `evaluate_pixel_gate(...)`.

- [ ] **Step 1: Write RED tests for exactness, monotonicity, split safety, and the gate**

```python
def test_exactness_compares_row_type_fields_and_owner(row, gold, prediction) -> None:
    assert is_exact_grounded_row(row, gold, prediction)
    extra = prediction.model_copy(
        update={"proposals": prediction.proposals + (prediction.proposals[0],)}
    )
    assert not is_exact_grounded_row(row, gold, extra)


def test_isotonic_calibration_is_monotone() -> None:
    observations = (
        CalibrationObservation("d1", "r1", 0.1, False),
        CalibrationObservation("d2", "r2", 0.4, False),
        CalibrationObservation("d3", "r3", 0.8, True),
        CalibrationObservation("d4", "r4", 0.9, True),
    )
    calibrator = fit_isotonic(observations)
    values = [calibrator.calibrate(score) for score in (0.1, 0.4, 0.8, 0.9)]
    assert values == sorted(values)


def test_pixel_gate_stops_without_selective_risk_gain() -> None:
    tied = SelectiveSummary(document_macro_aurc=0.02, coverage_at_target_risk=0.6, false_accepts=1)
    decision = evaluate_pixel_gate(tied, tied, tied)
    assert decision.status == "STOP_NO_PIXEL_GAIN"
```

Add a test that any non-validation row raises `ValueError("validation split required")`,
and any duplicate/missing document-row outcome raises rather than changing eligibility.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_calibration.py
```

Expected: FAIL during collection because `calibration.py` does not exist.

- [ ] **Step 3: Implement exact grounded-row observations and PAV isotonic calibration**

```python
@dataclass(frozen=True)
class CalibrationObservation:
    document_id: str
    row_id: str
    raw_score: float
    exact: bool


@dataclass(frozen=True)
class SelectiveSummary:
    document_macro_aurc: float
    coverage_at_target_risk: float
    false_accepts: int


def is_exact_grounded_row(row: FrozenRow, gold: GoldRow, prediction: RowPrediction) -> bool:
    if gold.ambiguous or prediction.decision != Decision.ACCEPT:
        return False
    owner = row.previous_row_id if gold.row_type is RowType.CONTINUATION else row.row_id
    if owner is None:
        return False
    expected = sorted((field.role.value, field.atom_ids, owner) for field in gold.fields)
    observed = sorted(
        (
            proposal.role.value,
            proposal.atom_ids,
            proposal.owner_row_id or row.row_id,
        )
        for proposal in prediction.proposals
    )
    return prediction.predicted_type == gold.row_type and observed == expected
```

This function deliberately ignores `GoldField.canonical_value`; common metrics remain the
authority for parsed-value scoring. PAV sorts by `(raw_score, document_id, row_id)`, pools
adjacent decreasing blocks with integer counts, clamps results to `[0, 1]`, and serializes
breakpoints/probabilities as canonical JSON. Threshold selection enumerates unique calibrated
scores from high to low and chooses the lowest threshold whose observed exact-row risk is at
most `0.01`; ties choose higher coverage, then higher threshold.

Generate calibration observations with an identity calibrator and threshold `0.0` so the
unthresholded grounded proposals are available; this provisional arm is validation-only and
cannot be frozen or used on `DatasetSplit.TEST`. Merchant exact match is exactly the common
metric for `FieldRole.DESCRIPTION`; billed-amount accuracy is exactly the common metric for
`FieldRole.BILLED_AMOUNT`.

- [ ] **Step 4: Implement the paired document-level pixel gate and freeze rule**

Use the same eligible calibration row IDs for pixels-on, pixels-off, and the frozen best
nonvisual control. Compute per-document risk-coverage curves and average document AURC.
The gate passes only when:

```python
passed = (
    pixels_on.document_macro_aurc < pixels_off.document_macro_aurc
    and pixels_on.document_macro_aurc < nonvisual.document_macro_aurc
    and pixels_on.coverage_at_target_risk >= pixels_off.coverage_at_target_risk
    and pixels_on.coverage_at_target_risk >= nonvisual.coverage_at_target_risk
    and pixels_on.false_accepts <= pixels_off.false_accepts
    and pixels_on.false_accepts <= nonvisual.false_accepts
)
```

Also compute paired 2,000-replicate document bootstrap intervals for AURC, exact-span F1,
merchant exact match, and complete-row exact match; report them as uncertainty, not as extra
gate tuning. If `passed` is false, write private `STOP_NO_PIXEL_GAIN` evidence, stop model
work, and continue only through Task 9's `VALIDATION_STOPPED` freeze/checkpoint/handoff. If
true, atomically freeze both arm configs, model/calibrator identities, threshold, dependency
identity, render version, feature-schema identity, split-manifest identities, worker count,
and accepted SHA in `artifacts/row-extraction/vision/validation-handoff.json`. The handoff file
contains identities only, never crop paths, text, canonical values, or financial data.

- [ ] **Step 5: Run GREEN**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_calibration.py
```

Expected: PASS; tied/worse pixels stop, genuinely lower synthetic risk passes, and locked
rows cannot enter calibration.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/calibration.py tests/experiments/row_extraction/arms/vision/test_calibration.py
git commit -m "experiment: calibrate and gate row pixel gain"
```

Expected: the mandatory verification policy is satisfied; no private metric values or identities are committed.

### Task 8: Measure Runtime, Memory, Footprint, and Byte Repeatability

```text
Scope answer: YES
Program component: experiment 4
Measured effect: p50/p95 row latency, cold start, throughput, subprocess count, peak RSS, model/dependency/cache bytes, and byte-identical repeated predictions
Fixed inputs: frozen arm/config/runtime, fixed eligible rows, shared runner/codecs, CPU threads/workers=1
Allowed files: experiments/row_extraction/arms/vision/resources.py; tests/experiments/row_extraction/arms/vision/test_resources.py
Stop condition: stop on changed runtime/config/rows between repeats, unbounded logging, private filenames/values in reports, or a non-byte-identical repeated canonical output
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/resources.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_resources.py`

**Interfaces:**
- Consumes: frozen `VisionArmFactory`, exact row-sequence identity/count and split, shared
  `run_arm`, streaming JSONL sink, frozen-arm/runtime identities, canonical model/dependency
  inventories, and distinct lane-private cache/inventory roots.
- Produces: `build_vision_resource_spec(...) -> ResourceSpec`, a privacy-safe lane
  `ResourceReport`, `project_resource_report(run: RunMeasurements) -> ResourceReport`, and
  `assert_repeated_predictions(...) -> tuple[RunMeasurements, RunMeasurements]`.

- [ ] **Step 1: Write RED tests for byte comparison and privacy-safe resource totals**

```python
def test_repeatability_compares_canonical_bytes(tmp_path, deterministic_arm_factory, rows) -> None:
    first, second = assert_repeated_predictions(rows, deterministic_arm_factory, tmp_path)
    assert first.row_count == second.row_count
    assert first.predictions_sha256 == second.predictions_sha256


def test_resource_report_contains_totals_not_paths(resource_report) -> None:
    payload = resource_report.to_json()
    assert "model_bytes" in payload
    assert "dependency_bytes" in payload
    assert "cache_bytes" in payload
    assert "source_pdf" not in payload
    assert "row_id" not in payload
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_resources.py
```

Expected: FAIL during collection because `resources.py` does not exist.

- [ ] **Step 3: Implement isolated measurements**

Build a static `ResourceSpec` that binds the exact row sequence/split, frozen-arm/runtime
identities, disjoint model/dependency inventories, `worker_count=1`, new-empty cache policy,
and distinct new output paths. Vision has no external subprocess and no separate preparation
record; it fixes `resource_basis="end-to-end-method"`, and deterministic tensor rendering and
model inference occur inside the measured arm.

For repeatability, launch two fresh isolated command processes. Each constructs a new
`VisionArmFactory`, sink, cache root, combined-inventory output, and resource spec, then invokes
`run_arm(rows, factory, sink, resource_spec)` once. The shared runner exclusively owns timing,
cold start, process-family RSS, inventory totals, subprocess count, and publication. Read both
prediction files in fixed-size chunks and fail unless bytes and counts match. A mismatch is an
experiment failure; do not normalize or rewrite outputs to make them match. The lane report
projects aggregate shared fields only and keeps preparation, fixed-row execution, and
end-to-end duration separate; it never exposes filenames or private hashes.

- [ ] **Step 4: Run GREEN**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_resources.py
```

Expected: PASS, including a synthetic test that deliberately changes one prediction byte
and receives `RuntimeError("canonical predictions are not byte-identical")`.

- [ ] **Step 5: Run full verification and commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/resources.py tests/experiments/row_extraction/arms/vision/test_resources.py
git commit -m "experiment: measure row vision resource use"
```

Expected: the mandatory verification policy is satisfied.

### Task 9: Add the Split-Safe Lane CLI and Central-Comparison Handoff

```text
Scope answer: YES
Program component: experiment 4
Measured effect: reproducible validation predictions, calibration/pixel-gate evidence, validation resource measurements, and byte-repeatable frozen handoff to central comparison
Fixed inputs: accepted SHA, reviewed train/validation manifests, frozen model/config/calibrator/threshold, shared common contracts/runner/metrics/codecs; DatasetSplit.TEST remains central-only and unopened
Allowed files: experiments/row_extraction/arms/vision/cli.py; tests/experiments/row_extraction/arms/vision/test_cli.py
Stop condition: hard-refuse every DatasetSplit.TEST request before opening its manifest or artifacts; on STOP_NO_PIXEL_GAIN emit the typed terminal freeze/checkpoint/handoff and stop, while missing/mismatched handoff identity, dirty/wrong source revision, or any production/shared file mutation stops all processing
```

**Files:**
- Create: `experiments/row_extraction/arms/vision/cli.py`
- Test: `tests/experiments/row_extraction/arms/vision/test_cli.py`

**Interfaces:**
- Consumes: all lane components, shared streaming codecs, `run_arm`, `score_predictions`, and private ignored roots.
- Produces: commands `preflight`, `train`, `calibrate`, `freeze`, `predict`, `measure`, `checkpoint`, and `handoff`; `VisionHandoff`; `load_handoff(path: Path) -> VisionHandoff`; the immutable private `validation-handoff.json`; repeated validation `RowPrediction` JSONL; and a privacy-safe checkpoint summary for central comparison.

- [ ] **Step 1: Write RED end-to-end tests**

```python
@pytest.mark.parametrize("command", ("train", "calibrate", "predict", "measure"))
def test_lane_refuses_test_before_opening_inputs(cli_runner, tmp_path, command) -> None:
    missing_bundle = tmp_path / "must-not-be-opened.jsonl"
    result = cli_runner(command, "--split", "test", "--bundle", missing_bundle)
    assert result.exit_code == 2
    assert "vision lane cannot access DatasetSplit.TEST" in result.stderr
    assert not missing_bundle.exists()


def test_synthetic_workflow_uses_shared_runner_and_contract(cli_runner, synthetic_bundle) -> None:
    result = cli_runner("checkpoint", synthetic_bundle)
    assert result.exit_code == 0
    assert result.json["experiment_id"] == "row-vision"
    assert set(result.json) == {
        "scope", "hypothesis", "fixed_inputs", "files_changed", "verification",
        "measurements", "errors_and_limitations", "next_action",
    }


def test_handoff_contains_repeated_validation_identity_not_test_output(
    cli_runner, frozen_validation_fixture
) -> None:
    result = cli_runner("handoff", frozen_validation_fixture)
    assert result.exit_code == 0
    assert result.json == {
        "experiment_id": "row-vision",
        "disposition": "frozen_eligible",
        "stop_reason": None,
    }
    handoff = load_handoff(frozen_validation_fixture.handoff_path)
    assert handoff.validation_predictions_sha256_first == (
        handoff.validation_predictions_sha256_second
    )
    assert handoff.validation_metric_identity.artifact_type == "metric-report"
    assert handoff.validation_metric_report.row_count > 0
    assert handoff.pixel_gate_evidence.artifact_type == "pixel-gate"
    assert handoff.test_accessed is False
    assert not hasattr(handoff, "test_predictions_sha256")
```

Also test wrong HEAD, dirty production/shared paths, mismatched render/feature/split/artifact
identity, non-train training, non-validation calibration, a test split hidden behind an
otherwise valid frozen handoff, and changed bytes between repeated validation predictions.
Each must fail closed before reading private row contents.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision/test_cli.py
```

Expected: FAIL during collection because `cli.py` does not exist.

- [ ] **Step 3: Implement fail-closed commands**

Use `argparse`; accept explicit private paths, never glob documents, and never print source
names, row IDs, text, proposals, canonical values, financial values, or artifact hashes.
`preflight` validates that the accepted SHA is an ancestor and `src/` is byte-unchanged from
that anchor, then validates clean shared/production paths, runtime, dependency lock,
foundation contracts, render version, manifest split identities, and ignored artifact root.
Every command accepting `--split` first parses the enum and immediately rejects
`DatasetSplit.TEST` with `vision lane cannot access DatasetSplit.TEST`, before resolving,
opening, statting, or hashing a bundle, gold file, output, or artifact path. `train` then
permits `DatasetSplit.TRAIN` only. `calibrate` permits `DatasetSplit.VALIDATION` only.
`predict` permits train diagnostics or frozen validation only, and `measure` permits frozen
validation only. No lane-local locked-access marker exists because this lane never accesses
the locked split. `freeze` refuses unless Task 7 produced either a passing pixel gate or a
terminal `STOP_NO_PIXEL_GAIN` validation result.

All prediction commands instantiate a fresh `VisionArmFactory`, require a matching static
`ResourceSpec`, call shared `run_arm`, write with shared streaming JSONL codecs, and call shared
`score_predictions`; no lane-local metric replacement is allowed. `checkpoint`
emits exactly the charter's eight sections and privacy-safe
validation aggregates. `handoff` verifies two separately loaded, byte-identical frozen
validation prediction files and then writes the private immutable handoff. It cannot accept,
produce, score, measure, or mention a test prediction artifact.

Use this exact outer handoff model; the identity tuples contain the detailed items enumerated
in the handoff section below:

```python
class VisionHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted_sha: str
    experiment_id: Literal["row-vision"]
    disposition: LaneDisposition
    stop_reason: Literal["no_pixel_gain"] | None
    pixels_on_config_id: str
    pixels_off_config_id: str
    artifact_identities: tuple[ArtifactIdentity, ...]
    train_manifest_identity: ArtifactIdentity
    validation_manifest_identity: ArtifactIdentity
    validation_predictions_sha256_first: str
    validation_predictions_sha256_second: str
    validation_metric_identity: ArtifactIdentity
    validation_metric_report: MetricReport
    validation_measurements: RunMeasurements
    pixel_gate_evidence: ArtifactIdentity
    frozen_arm_manifest: ArtifactIdentity | None
    owner_none_means_current: Literal[True] = True
    test_accessed: Literal[False] = False
```

Validate the pairing: `LaneDisposition.FROZEN_ELIGIBLE` requires `stop_reason=None` and a
frozen-arm manifest; `LaneDisposition.VALIDATION_STOPPED` requires
`stop_reason="no_pixel_gain"` and forbids a frozen-arm manifest. The internal
`STOP_NO_PIXEL_GAIN` gate status is evidence for this shared terminal disposition, not a
third public status vocabulary. Both dispositions require a complete shared validation
`MetricReport`, its canonical artifact identity, validation resources, pixel-gate evidence,
repeat-prediction identity, and the exact eight-section checkpoint.

- [ ] **Step 4: Run GREEN and the synthetic end-to-end workflow**

```bash
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/pytest -q \
  tests/experiments/row_extraction/arms/vision/test_cli.py
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m \
  experiments.row_extraction.arms.vision.cli checkpoint \
  --bundle tests/experiments/row_extraction/fixtures/synthetic-bundle.jsonl \
  --artifact-root artifacts/row-extraction/vision/synthetic
```

Expected: tests pass; the command prints only privacy-safe aggregate keys and exits 0. If
the shared synthetic bundle path differs in the reviewed foundation, stop and reconcile the
single path before implementation rather than creating another bundle format.

- [ ] **Step 5: Run all tracked and lane verification before the final task commit**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py
.cache/row-vision-venv/bin/mypy experiments/row_extraction/arms/vision
.cache/row-vision-venv/bin/pytest -q tests/experiments/row_extraction/arms/vision
git diff --check
git add experiments/row_extraction/arms/vision/cli.py tests/experiments/row_extraction/arms/vision/test_cli.py
git commit -m "experiment: lock row vision evaluation handoff"
```

Expected: Ruff, both mypy runs, the lane suite, and
`.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py` pass. The full
`.venv/bin/pytest -q` run either passes after an upstream fix or reproduces exactly the five
established inherited out-of-scope sandbox/controller failures; any new, removed, or changed
failure stops the task. The commit contains no `src/` changes, and the worktree is clean
except ignored private artifacts.

- [ ] **Step 6: Execute through validation freeze and hand off without opening test**

Run only after the shared foundation and experiment-3 nonvisual control are reviewed and
frozen:

```bash
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli preflight --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli train --split train --tiers 100 250 500 all --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli calibrate --split validation --nonvisual-control artifacts/row-extraction/shared/nonvisual-control.jsonl --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli freeze --artifact-root artifacts/row-extraction/vision
```

`freeze` records the validation gate status. A `STOP_NO_PIXEL_GAIN` freeze is a terminal,
non-test-eligible validation snapshot; a passing freeze is eligible only for handoff to the
central comparison. In both cases, load the frozen validation snapshot independently twice,
compare it without configuration edits, write the checkpoint, and hand off:

```bash
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli predict --split validation --output artifacts/row-extraction/vision/predictions/validation/frozen-first.jsonl --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli predict --split validation --output artifacts/row-extraction/vision/predictions/validation/frozen-second.jsonl --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli measure --split validation --repeat 2 --workers 1 --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli checkpoint --artifact-root artifacts/row-extraction/vision
PYTHONHASHSEED=0 .cache/row-vision-venv/bin/python -m experiments.row_extraction.arms.vision.cli handoff --first-validation artifacts/row-extraction/vision/predictions/validation/frozen-first.jsonl --second-validation artifacts/row-extraction/vision/predictions/validation/frozen-second.jsonl --artifact-root artifacts/row-extraction/vision
```

Expected: validation metrics cover exact row/merchant/fields, omissions, hallucinations,
unsupported/ownership errors, row types, calibration, risk-coverage, abstention, document
bootstrap uncertainty, slices, resources, and byte repeatability. The lane returns the
handoff and stops. Only central comparison/cascade may instantiate this frozen arm on
`DatasetSplit.TEST`, perform the one locked run, score it, or measure its locked performance.
This handoff is not corpus acceptance and not authorization for production integration.

## Central-Comparison Handoff Contents

The final private handoff must lock:

- accepted SHA and clean-source assertion;
- experiment/config IDs for pixels-on and pixels-off;
- `FeatureSchema` version/names canonical SHA-256;
- render config/version and crop-index identity;
- train and validation split-manifest identities, plus an explicit assertion that this lane
  neither opened nor scored `DatasetSplit.TEST`; the central foundation owns the test
  manifest and does not disclose it to this lane;
- model architecture, weights-none declaration, seed, all training hyperparameters, and
  safetensors identities/bytes;
- calibrator breakpoints identity, threshold, 1% risk target, and pixel-gate decision;
- proposal ownership contract version, including `owner_row_id=None` meaning the current row;
- Python, torch, torchvision, NumPy, Pillow, safetensors, platform, CPU, thread, and worker
  identities;
- common runner/metric/codec versions;
- two independently loaded canonical validation prediction identities with byte equality;
- complete shared validation `MetricReport` plus its artifact identity, validation-only
  resource totals, pixel-gate evidence identity, and exact checkpoint sections;
- `test_accessed=false` and no test prediction, score, metric, latency, or resource field; and
- shared terminal disposition `FROZEN_ELIGIBLE` or `VALIDATION_STOPPED`; the latter carries
  the stable reason `no_pixel_gain`.

It must not contain source paths, document/row names, text, atom values, gold canonical
values, financial data, crop bytes, prediction contents, or private hashes in tracked
documentation. Any `DatasetSplit.TEST` artifact in the lane root invalidates the handoff.
Any mismatch or change after freeze invalidates the handoff and requires train/validation
reruns. Central comparison/cascade alone consumes a ready frozen handoff for the single
locked run; it never returns locked rows, predictions, scores, or metrics to this lane for
retuning.
