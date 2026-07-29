# Lightweight Row-Text Field Model Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether a small local discriminative model over the fixed positioned evidence atoms improves exact evidence-span, exact transaction-row, and merchant accuracy over experiment 2 while remaining evidence-grounded, selectively calibrated, deterministic, and small.

**Architecture:** Experiment 3 is an isolated, read-only consumer of the frozen shared foundation. A stable hashed linear classifier predicts the closed `RowType`; a deterministic-feature linear-chain CRF predicts BIO field roles over the row's existing evidence atoms; an evidence decoder emits only `FieldProposal` atom IDs; and a sigmoid meta-calibrator estimates the probability that the complete emitted row is exact. `DatasetSplit.TRAIN` grouped out-of-fold predictions fit calibration, `DatasetSplit.VALIDATION` selects one predeclared arm and abstention threshold, and experiment 3 stops at a frozen validation/configuration handoff. Only the central comparison/cascade plan may later open `DatasetSplit.TEST` for the single locked run.

**Tech Stack:** Python 3.13, NumPy 2.5.1, scikit-learn 1.9.0, python-crfsuite 0.9.12, the frozen `experiments.row_extraction` foundation contracts/runner/metrics/codecs, pytest, Ruff, and mypy.

## Global Constraints

- Work only on branch `codex/row-extraction-text`, created from the reviewed foundation commit whose ancestor is accepted SHA `dee4b071ad65231da13825f2f7c74a488ca96c7c`.
- Treat `docs/research/2026-07-28-row-text-models-calibration.md` as the model/calibration rationale: hashed compact row classification first, direct python-crfsuite for linear-chain tagging, complete-row rather than token-confidence calibration, document-grouped uncertainty, and risk/coverage-driven abstention.
- Production `src/` and all shared files under `experiments/row_extraction/` outside `arms/text/` are read-only. Shared tests are read-only. A missing or insufficient shared contract is a stop condition and must be proposed upstream; never patch it in this lane.
- Before Task 1, require the foundation to make `experiments.row_extraction.arms` and `tests.experiments.row_extraction.arms` importable, either with committed parent `__init__.py` files or an explicitly tested namespace-package decision. The text lane must not create those shared parent files.
- Lane-owned code is limited to `experiments/row_extraction/arms/text/`; lane-owned tests are limited to `tests/experiments/row_extraction/arms/text/`. This plan itself is the only file created while planning.
- Fixed inputs are the charter, accepted SHA, and frozen row, partition, grouping, annotation, evidence, renderer, metric, and common prediction contracts from the shared foundation. The lane may not detect, split, merge, reorder, crop, OCR, or otherwise redefine rows or evidence atoms.
- The only learned models are a hashed linear row classifier and a linear-chain sequence tagger. Do not add a transformer, embedding service, language model, generator, document-specific branch, filename/path/hash/date/amount/total feature, merchant identity, template identity, or free-form predicted value.
- All financial parsing and comparison remain in the shared deterministic renderer/metrics and use `Decimal`. Model scores and geometry may use floating point; model code never performs financial arithmetic.
- Private documents, tokens, labels, group membership, predictions, traces, reports, caches, model/calibrator artifacts, artifact hashes, dependency inventories, and locked configuration values stay below ignored lane-private paths supplied on the command line. No private value or derived financial datum enters Git, test output, commit text, or a tracked fixture.
- The shared contract is consumed exactly as follows:

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
      FeatureSchema,
      FeatureVector,
      FrozenRow,
      GoldField,
      GoldRow,
      LaneDisposition,
      RowPrediction,
      RowType,
  )
  from experiments.row_extraction.codecs import read_jsonl, write_jsonl
  from experiments.row_extraction.metrics import MetricReport, score_predictions
  from experiments.row_extraction.runner import ResourceSpec, RunMeasurements, run_arm
  ```

  `ExperimentArm` has read-only `experiment_id: str`, `config_id: str`, and `predict(row: FrozenRow) -> RowPrediction`. `FieldProposal` contains a `FieldRole`, nonempty exact `atom_ids`, optional source region, optional continuation `owner_row_id`, and a raw score. `RowPrediction` contains experiment/config/document/row IDs, predicted type, the complete fixed evidence-atom ledger, proposals, exact-row confidence, decision, and stable reasons. `run_arm(rows, factory, sink, resource_spec) -> RunMeasurements` and `score_predictions(rows, gold, predictions) -> MetricReport` remain the only canonical execution and scoring paths. The row stream is mandatory ownership context and is not an additional feature source. Shared `write_jsonl(path: Path, records: Iterable[BaseModel]) -> ArtifactIdentity` and `read_jsonl(path: Path, model: type[T]) -> Iterator[T]` stream records; this lane must not load the private corpus into an additional all-document model.
- `MetricReport` is consumed without flattening, including `log_loss`, `area_under_risk_coverage`, and `coverage_at_risk`; merchant is exactly `fields[FieldRole.DESCRIPTION]` and billed amount is `fields[FieldRole.BILLED_AMOUNT]`. The frozen handoff writes canonical model/dependency inventories; each fresh measured invocation builds a matching static `ResourceSpec` and `TextExperimentArmFactory`, and the shared runner measures and publishes that same execution. `RunMeasurements` is consumed without duplication, including `preparation_ns`, `total_ns`, `end_to_end_ns`, `cold_start_ns`, `throughput_rows_per_second`, `dependency_bytes`, `worker_count`, `measurement_protocol`, and its canonical prediction SHA-256. The only lane-local resource addition is `dependency_count`; shared fields may not be renamed, copied into parallel fields, recomputed under different definitions, or filled with unavailable-as-zero placeholders.
- The exact frozen records are those in `docs/superpowers/plans/2026-07-28-row-extraction-shared-foundation.md`: `BBox` is `tuple[float, float, float, float]`; `EvidenceAtom` exposes `atom_id/text/bbox/source/confidence/column_index`; `FrozenRow` exposes `document_id/row_id/split/source_pdf/page_number/bbox/baseline_type/column_bands/atoms/previous_row_id/next_row_id/gap_before/gap_after/render_version`; `GoldField` exposes `role/canonical_value/atom_ids/source_region`; and the remaining constructors match Task 1's exact field-set tests. Any mismatch stops the lane before implementation; reconcile it on the foundation branch and regenerate this plan rather than adding reflection or compatibility branches.
- `FrozenRow.source_pdf`, `document_id`, `row_id`, `split`, `page_number`, `baseline_type`, `previous_row_id`, `next_row_id`, and `render_version` are forbidden feature inputs. The source and IDs are identity/coordination metadata; `baseline_type` is an accepted-anchor observation, not gold. Tests must prove changing any of them leaves features byte-identical. Adjacency IDs may be copied only into `FieldProposal.owner_row_id` after a model has predicted `RowType.CONTINUATION`; they never enter a model score and are used by shared metrics only to verify ownership correctness.
- The shared `grouped_folds(rows: Sequence[FrozenRow], manifest: SplitManifest, fold_count: int) -> tuple[Fold, ...]` is the only training fold constructor. Its `Fold.train_document_ids` and `Fold.validation_document_ids` preserve the duplicate/layout atomic units frozen by the shared manifest. This lane consumes that read-only manifest and does not create or accept a second lane-local `group_id`.
- Private `DatasetSplit.TEST` observations and labels are not lane inputs. Synthetic `DatasetSplit.TEST` records may appear only in focused fail-closed unit tests proving the guard; they contain no private contents and are never scored.
- Shared `FeatureSchema(version: str, names: tuple[str, ...])` and `FeatureVector(schema_version: str, row_id: str, values: tuple[float, ...])` remain unchanged. They describe fixed row-level vectors and are not stretched into a ragged atom-sequence contract. Experiment 3's lane-local `AtomFeatureTensor` has the exact order/mask/dtype schema in Task 2 and is not a cross-lane import; experiment 4 owns its equivalent frozen nonvisual adapter and may not import this lane.
- Each task starts by restating the scope block, follows RED/GREEN TDD, runs the focused test first, then runs the tracked repository gates before its commit. Use `/root/creditcard/.venv/bin/` from the repository virtual environment in the isolated worktree. Do not execute any private-data command until its task's synthetic tests pass, extraction-relevant tests are green, and the full-suite result matches the accepted inherited baseline described next.
- At this planning baseline, `/root/creditcard/.venv/bin/pytest -q` has exactly five inherited out-of-scope sandbox/controller failures. Every task still runs the extraction-relevant suite and requires it green, then runs the complete suite and requires the same five failures with no new, changed, or missing failure. Record that inherited result; do not investigate it in this lane and do not claim the complete pytest command exited 0. If the upstream baseline becomes green, require it to remain green.
- Fixture names used in the RED snippets are concrete local pytest fixtures defined in the same test module, not deferred corpus fixtures. They must be built only from shared `frozen_row()`/`gold_row()`, Pydantic `model_copy`, `tmp_path`, and public synthetic literals. `synthetic_development_rows` covers every `RowType` across at least five distinct `DatasetSplit.TRAIN` document IDs; `synthetic_split_manifest` assigns exactly those document IDs to training while preserving at least one multi-document atomic family; `synthetic_test_rows` is the same shape with `DatasetSplit.TEST`; `synthetic_frozen_row` has at least two uniquely identified atoms; `legal_tag_sequence` has one legal description span; trained artifacts are created under `tmp_path`; `candidate_validations`/`candidate_selection` instantiate Task 9's exact dataclasses with `Decimal` aggregates; `canonical_jsonl_sink_factory` returns the shared temporary-file `PredictionSink`; and `verified_text_handoff`/`validation_readiness` contain only train/validation synthetic identities. No fixture opens a source path, carries a real value, or depends on execution order.
- Stop immediately if implementation would require a production `src/` change, shared-contract mutation, row/split/label mutation, document-specific feature, free-form value, transformer/generative model, cloud call, or fifth experiment.

---

### Task 1: Establish the Lane Boundary and Locked Configuration Types

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/__init__.py, experiments/row_extraction/arms/text/config.py, experiments/row_extraction/arms/text/requirements-text.txt, tests/experiments/row_extraction/arms/text/test_config.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/__init__.py`
- Create: `experiments/row_extraction/arms/text/config.py`
- Create: `experiments/row_extraction/arms/text/requirements-text.txt`
- Test: `tests/experiments/row_extraction/arms/text/test_config.py`

**Interfaces:**

- Consumes: all frozen shared imports listed under Global Constraints.
- Produces: `TextFeatureConfig`, `LinearRowConfig`, `CrfTaggerConfig`, `CalibrationConfig`, `CandidateConfig`, `LockedTextConfig`, `candidate_configs() -> tuple[CandidateConfig, ...]`, and `canonical_config_bytes(config: LockedTextConfig) -> bytes`.
- The hashed linear classifier is the row-type control inside both learned candidates. The two predeclared complete extraction candidates are `text-shape-v1` and `text-shape-geometry-v1`; both add the same CRF span tagger. Experiment 2 is the fixed no-learning control and is scored separately, never reimplemented or imported from its lane.

- [ ] **Step 1: Write the failing contract/configuration test.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_config.py
  from experiments.row_extraction.contracts import FieldProposal, FrozenRow, RowPrediction
  from experiments.row_extraction.arms.text.config import (
      LockedTextConfig,
      candidate_configs,
      canonical_config_bytes,
  )


  def test_foundation_accessors_match_the_frozen_plan() -> None:
      assert set(FrozenRow.model_fields) == {
          "document_id", "row_id", "split", "source_pdf", "page_number", "bbox",
          "baseline_type", "column_bands", "atoms", "previous_row_id", "next_row_id",
          "gap_before", "gap_after", "render_version",
      }
      assert set(FieldProposal.model_fields) == {
          "role", "atom_ids", "source_region", "owner_row_id", "raw_score"
      }
      assert set(RowPrediction.model_fields) == {
          "experiment_id", "config_id", "document_id", "row_id", "predicted_type",
          "evidence_atoms", "proposals", "exact_row_confidence", "decision", "reasons"
      }


  def test_candidate_matrix_is_closed_and_geometry_is_the_only_ablation() -> None:
      configs = candidate_configs()
      assert tuple(config.config_id for config in configs) == (
          "text-shape-v1",
          "text-shape-geometry-v1",
      )
      assert configs[0].feature.include_geometry is False
      assert configs[1].feature.include_geometry is True


  def test_locked_config_is_canonical_and_contains_no_artifact_bytes() -> None:
      locked_text_config = LockedTextConfig(
          candidate=candidate_configs()[0],
          exact_row_threshold=0.95,
          accepted_commit="dee4b071ad65231da13825f2f7c74a488ca96c7c",
          foundation_commit="a" * 40,
          split_manifest_sha256="b" * 64,
          label_contract_sha256="c" * 64,
          feature_schema_sha256="d" * 64,
          model_artifact_sha256="e" * 64,
          tagger_artifact_sha256="1" * 64,
          calibrator_artifact_sha256="f" * 64,
          python_version="3.13.5",
          dependency_versions=(
              ("numpy", "2.5.1"),
              ("python-crfsuite", "0.9.12"),
              ("scikit-learn", "1.9.0"),
          ),
          worker_count=1,
      )
      first = canonical_config_bytes(locked_text_config)
      second = canonical_config_bytes(locked_text_config)
      assert first == second
      assert first.endswith(b"\n")
      assert b"pickle" not in first
      assert b"merchant" not in first.lower()
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_config.py`

  Expected: FAIL during collection with `ModuleNotFoundError: No module named 'experiments.row_extraction.arms.text'`.

- [ ] **Step 3: Add exact dependency pins and the minimal immutable configuration implementation.**

  ```text
  # experiments/row_extraction/arms/text/requirements-text.txt
  numpy==2.5.1
  scikit-learn==1.9.0
  python-crfsuite==0.9.12
  ```

  ```python
  # experiments/row_extraction/arms/text/config.py
  from __future__ import annotations

  import json
  from dataclasses import asdict, dataclass


  @dataclass(frozen=True)
  class TextFeatureConfig:
      schema_id: str = "row-text-features-v1"
      hash_algorithm: str = "blake2b-64"
      hash_person: str = "cc-row-text-v1"
      hash_buckets: int = 65_536
      max_active_hashes: int = 64
      char_ngram_min: int = 2
      char_ngram_max: int = 4
      include_geometry: bool = False


  @dataclass(frozen=True)
  class LinearRowConfig:
      loss: str = "log_loss"
      alpha: float = 0.0001
      max_iter: int = 2_000
      tolerance: float = 1e-8
      random_seed: int = 20_260_728
      shuffle: bool = False


  @dataclass(frozen=True)
  class CrfTaggerConfig:
      algorithm: str = "lbfgs"
      c1: float = 0.1
      c2: float = 0.1
      max_iterations: int = 200
      possible_transitions: bool = True


  @dataclass(frozen=True)
  class CalibrationConfig:
      method: str = "sigmoid"
      training_folds: int = 5
      risk_targets: tuple[float, ...] = (0.001, 0.005, 0.01)
      reliability_bins: int = 10
      random_seed: int = 20_260_728


  @dataclass(frozen=True)
  class CandidateConfig:
      experiment_id: str
      config_id: str
      feature: TextFeatureConfig
      row_model: LinearRowConfig
      tagger: CrfTaggerConfig
      calibration: CalibrationConfig


  @dataclass(frozen=True)
  class LockedTextConfig:
      candidate: CandidateConfig
      exact_row_threshold: float
      accepted_commit: str
      foundation_commit: str
      split_manifest_sha256: str
      label_contract_sha256: str
      feature_schema_sha256: str
      model_artifact_sha256: str
      tagger_artifact_sha256: str
      calibrator_artifact_sha256: str
      python_version: str
      dependency_versions: tuple[tuple[str, str], ...]
      worker_count: int


  def candidate_configs() -> tuple[CandidateConfig, ...]:
      def make(config_id: str, geometry: bool) -> CandidateConfig:
          return CandidateConfig(
              experiment_id="row-text",
              config_id=config_id,
              feature=TextFeatureConfig(include_geometry=geometry),
              row_model=LinearRowConfig(),
              tagger=CrfTaggerConfig(),
              calibration=CalibrationConfig(),
          )

      return (
          make("text-shape-v1", False),
          make("text-shape-geometry-v1", True),
      )


  def canonical_config_bytes(config: LockedTextConfig) -> bytes:
      payload = json.dumps(
          asdict(config), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
      )
      return payload.encode("utf-8") + b"\n"
  ```

  Re-export only these immutable configuration names from `__init__.py`. Do not import scikit-learn or CRFsuite at package import time.

- [ ] **Step 4: Install the exact experiment-only dependencies and run a Python 3.13 smoke test.**

  Run:

  ```bash
  /root/creditcard/.venv/bin/python -m pip install --only-binary=:all: \
    --requirement experiments/row_extraction/arms/text/requirements-text.txt
  /root/creditcard/.venv/bin/python -c \
    'import sys; from importlib.metadata import version; import numpy, pycrfsuite, sklearn; assert sys.version_info[:2] == (3, 13); assert version("numpy") == "2.5.1"; assert version("scikit-learn") == "1.9.0"; assert version("python-crfsuite") == "0.9.12"'
  ```

  Expected: install exits 0 using Python 3.13-compatible wheels and the import/version smoke
  test exits 0. These packages remain experiment-environment dependencies only;
  `pyproject.toml` and production dependencies remain unchanged. If a pinned wheel is
  unavailable, stop and return a dependency-contract proposal rather than installing from
  source or changing a pin locally.

- [ ] **Step 5: Run the focused test and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_config.py`

  Expected: PASS.

- [ ] **Step 6: Run lane typing and all tracked verification gates.**

  Run:

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  ```

  Expected: formatting, Ruff, both mypy commands, and the extraction-relevant suite exit 0.
  The complete pytest run has exactly the five inherited sandbox/controller failures and no
  new or changed failure. If the dependency pins cannot install on Python 3.13, stop and
  return a dependency-contract proposal; do not change `pyproject.toml` in this lane.

- [ ] **Step 7: Commit the lane boundary.**

  ```bash
  git add experiments/row_extraction/arms/text/__init__.py experiments/row_extraction/arms/text/config.py experiments/row_extraction/arms/text/requirements-text.txt tests/experiments/row_extraction/arms/text/test_config.py
  git commit -m "experiment: freeze row text candidate matrix"
  ```

---

### Task 2: Build Privacy-Safe, Order-Preserving Atom Features

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/features.py, tests/experiments/row_extraction/arms/text/test_features.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/features.py`
- Test: `tests/experiments/row_extraction/arms/text/test_features.py`

**Interfaces:**

- Consumes: `FrozenRow`, canonical `FrozenRow.atoms` order, tuple `BBox`, and `TextFeatureConfig`.
- Produces: `DENSE_FEATURE_NAMES`, `TextFeatureIdentity`, `AtomFeatureTensor`, `feature_identity(config) -> TextFeatureIdentity`, and `extract_atom_features(row, config) -> AtomFeatureTensor`.
- `AtomFeatureTensor` contains only structural numeric features and stable hash buckets. It never contains raw token text, document/group/split identity, a filename/path/hash, a merchant identity, or an exact digit string.

- [ ] **Step 1: Write failing tests for atom order, masks, geometry ablation, stable hashing, and privacy.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_features.py
  import numpy as np

  from experiments.row_extraction.arms.text.config import TextFeatureConfig
  from experiments.row_extraction.arms.text.features import (
      DENSE_FEATURE_NAMES,
      extract_atom_features,
      feature_identity,
  )
  from tests.experiments.row_extraction.factories import frozen_row


  def test_tensor_preserves_frozen_atom_order_and_exact_shapes() -> None:
      row = frozen_row()
      tensor = extract_atom_features(row, TextFeatureConfig())
      count = len(row.atoms)
      assert tensor.atom_ids == tuple(atom.atom_id for atom in row.atoms)
      np.testing.assert_array_equal(tensor.order, np.arange(count, dtype=np.int32))
      assert tensor.dense.shape == (count, len(DENSE_FEATURE_NAMES))
      assert tensor.dense_mask.shape == tensor.dense.shape
      assert tensor.hashed_indices.shape == (count, 64)
      assert tensor.hashed_values.shape == tensor.hashed_indices.shape
      assert tensor.hashed_mask.shape == tensor.hashed_indices.shape
      assert tensor.order.dtype == np.int32
      assert tensor.dense.dtype == np.float32
      assert tensor.dense_mask.dtype == np.bool_


  def test_text_control_masks_every_geometry_dimension() -> None:
      row = frozen_row()
      text = extract_atom_features(row, TextFeatureConfig(include_geometry=False))
      geometry = extract_atom_features(row, TextFeatureConfig(include_geometry=True))
      geometry_columns = [DENSE_FEATURE_NAMES.index(name) for name in (
          "relative_x0", "relative_y0", "relative_x1", "relative_y1", "relative_width",
          "relative_height", "column_index_normalized", "column_role_present",
          "gap_before_rows", "gap_after_rows",
      )]
      assert not text.dense_mask[:, geometry_columns].any()
      assert np.all(text.dense[:, geometry_columns] == 0.0)
      assert geometry.dense_mask[:, geometry_columns].all()


  def test_feature_identity_and_hashes_are_repeatable_without_raw_text() -> None:
      row = frozen_row()
      config = TextFeatureConfig(include_geometry=True)
      first = extract_atom_features(row, config)
      second = extract_atom_features(row, config)
      np.testing.assert_array_equal(first.hashed_indices, second.hashed_indices)
      np.testing.assert_array_equal(first.hashed_values, second.hashed_values)
      assert feature_identity(config) == feature_identity(config)
      serialized = first.canonical_bytes()
      for atom in row.atoms:
          assert atom.text.encode("utf-8") not in serialized


  def test_identity_and_baseline_metadata_are_never_features() -> None:
      row = frozen_row()
      changed = row.model_copy(update={
          "document_id": "f" * 64,
          "row_id": "different-row",
          "split": next(value for value in type(row.split) if value != row.split),
          "source_pdf": row.source_pdf.with_name("different.pdf"),
          "page_number": row.page_number + 10,
          "baseline_type": next(value for value in type(row.baseline_type) if value != row.baseline_type),
          "previous_row_id": "different-previous",
          "next_row_id": "different-next",
          "render_version": "different-render-version",
      })
      assert extract_atom_features(row, TextFeatureConfig()).canonical_bytes() == (
          extract_atom_features(changed, TextFeatureConfig()).canonical_bytes()
      )
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_features.py`

  Expected: FAIL during collection because `features.py` does not exist.

- [ ] **Step 3: Implement the exact typed tensor and stable feature identity.**

  ```python
  # experiments/row_extraction/arms/text/features.py
  from __future__ import annotations

  import hashlib
  import json
  import math
  import unicodedata
  from dataclasses import dataclass

  import numpy as np
  from numpy.typing import NDArray

  from experiments.row_extraction.contracts import FrozenRow

  from .config import TextFeatureConfig

  DENSE_FEATURE_NAMES = (
      "relative_x0", "relative_y0", "relative_x1", "relative_y1", "relative_width",
      "relative_height", "column_index_normalized", "column_role_present",
      "gap_before_rows", "gap_after_rows", "ocr_confidence", "log_token_length",
      "digit_fraction", "letter_fraction", "punctuation_fraction", "rtl_fraction",
  )
  _GEOMETRY_COUNT = 10


  @dataclass(frozen=True)
  class TextFeatureIdentity:
      schema_id: str
      schema_sha256: str
      dense_feature_names: tuple[str, ...]
      hash_algorithm: str
      hash_person: str
      hash_buckets: int
      max_active_hashes: int
      include_geometry: bool


  @dataclass(frozen=True)
  class AtomFeatureTensor:
      identity: TextFeatureIdentity
      atom_ids: tuple[str, ...]
      order: NDArray[np.int32]
      dense: NDArray[np.float32]
      dense_mask: NDArray[np.bool_]
      hashed_indices: NDArray[np.int32]
      hashed_values: NDArray[np.float32]
      hashed_mask: NDArray[np.bool_]

      def canonical_bytes(self) -> bytes:
          header = json.dumps(
              {
                  "atom_count": len(self.atom_ids),
                  "identity": self.identity.schema_sha256,
                  "shapes": [self.dense.shape, self.hashed_indices.shape],
              },
              sort_keys=True,
              separators=(",", ":"),
          ).encode("ascii")
          return b"\n".join((
              header,
              self.order.astype("<i4", copy=False).tobytes(),
              self.dense.astype("<f4", copy=False).tobytes(),
              self.dense_mask.tobytes(),
              self.hashed_indices.astype("<i4", copy=False).tobytes(),
              self.hashed_values.astype("<f4", copy=False).tobytes(),
              self.hashed_mask.tobytes(),
          ))


  def feature_identity(config: TextFeatureConfig) -> TextFeatureIdentity:
      payload = {
          "dense_feature_names": DENSE_FEATURE_NAMES,
          "hash_algorithm": config.hash_algorithm,
          "hash_buckets": config.hash_buckets,
          "hash_person": config.hash_person,
          "include_geometry": config.include_geometry,
          "max_active_hashes": config.max_active_hashes,
          "schema_id": config.schema_id,
      }
      encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
      return TextFeatureIdentity(
          schema_id=config.schema_id,
          schema_sha256=hashlib.sha256(encoded).hexdigest(),
          dense_feature_names=DENSE_FEATURE_NAMES,
          hash_algorithm=config.hash_algorithm,
          hash_person=config.hash_person,
          hash_buckets=config.hash_buckets,
          max_active_hashes=config.max_active_hashes,
          include_geometry=config.include_geometry,
      )
  ```

  Complete `extract_atom_features` with these fixed rules:

  1. Preserve `atoms` order exactly; duplicate atom IDs are a `ValueError`.
  2. Normalize each character to a privacy-safe stream: digits become `0`; whitespace becomes one space; letters are casefolded; punctuation remains only as its Unicode category. Emit Unicode script/category/shape transitions and proper substrings of length 2 through 4, never an entire token. No exact numeric string or complete token is a feature.
  3. Hash `feature_name=value` with `hashlib.blake2b(digest_size=8, person=b"cc-row-text-v1")`; the lower 63 bits modulo `65_536` select the bucket and the high bit selects `+1/-1`. Sum collisions, sort by bucket, retain the first 64 nonzero buckets, and pad with index/value zero plus mask false.
  4. Unpack `row.bbox`, `atom.bbox`, and `ColumnBand.bbox` as `(x0, y0, x1, y1)` tuples. Normalize atom coordinates by the fixed row bbox, column index by `max(1, len(row.column_bands) - 1)`, and optional before/after gaps by row height. `column_role_present` is only the boolean that the atom's fixed band has a role; the role value itself is not copied as a lexical target. When geometry is disabled, write zeros and false masks in exactly the first ten dense columns. Atom confidence is always present under the shared contract. Missing optional gaps are zero with false masks; all nongeometry columns are present.
  5. Mark every NumPy array read-only before returning. Validate finite values and exact dtypes/shapes. Raise a stable `ValueError` rather than repair malformed foundation data.

  The complete extraction loop must use only local scalars and fixed-size per-row arrays; it must not cache raw token text or document data.
  It must destructure only `row.bbox` and iterate `row.atoms`; a guard test monkeypatches every
  forbidden metadata field listed in Global Constraints and requires identical feature bytes.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_features.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/features.py tests/experiments/row_extraction/arms/text/test_features.py
  git commit -m "experiment: add stable row atom features"
  ```

---

### Task 3: Encode Frozen Gold as Legal BIO Sequences

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/labels.py, experiments/row_extraction/arms/text/training_data.py, tests/experiments/row_extraction/arms/text/test_labels.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/labels.py`
- Create: `experiments/row_extraction/arms/text/training_data.py`
- Test: `tests/experiments/row_extraction/arms/text/test_labels.py`

**Interfaces:**

- Consumes: `FrozenRow`, `GoldRow`, `GoldField`, `FieldRole`, `RowType`, `DatasetSplit`.
- Produces: `LabeledRow`, `BioSpan`, `gold_bio_tags(example) -> tuple[str, ...]`, `validate_bio(tags) -> tuple[BioSpan, ...]`, `exact_evidence_event(gold, prediction) -> bool`, and `complete_exact_row_event(gold, prediction) -> bool`.
- `LabeledRow(row, gold)` pairs immutable foundation records. Split membership comes only from `row.split`; grouped fold membership comes only from shared `Fold` document-ID sets. Feature functions accept `FrozenRow`, never `LabeledRow`.

- [ ] **Step 1: Write failing tests for exact ownership, sequence legality, and exact-row labels.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_labels.py
  import pytest

  from experiments.row_extraction.arms.text.labels import validate_bio
  from experiments.row_extraction.arms.text.training_data import LabeledRow, gold_bio_tags
  from tests.experiments.row_extraction.factories import frozen_row, gold_row


  def test_gold_spans_become_bio_in_canonical_atom_order() -> None:
      row = frozen_row()
      gold = gold_row(atom_ids=(row.atoms[0].atom_id,))
      tags = gold_bio_tags(LabeledRow(row=row, gold=gold))
      assert len(tags) == len(row.atoms)
      spans = validate_bio(tags)
      assert len(spans) == 1
      assert spans[0].role == gold.fields[0].role
      assert (spans[0].start, spans[0].stop) == (0, 1)


  @pytest.mark.parametrize(
      "tags",
      [
          ("I:description",),
          ("B:date", "I:description"),
          ("B:description", "B:description"),
          ("B:not-a-field-role",),
      ],
  )
  def test_illegal_bio_never_gets_repaired(tags: tuple[str, ...]) -> None:
      with pytest.raises(ValueError, match="illegal_bio"):
          validate_bio(tags)


  def test_overlapping_gold_stops_training() -> None:
      row = frozen_row()
      base = gold_row(atom_ids=(row.atoms[0].atom_id,))
      overlapping = base.model_copy(update={"fields": (base.fields[0], base.fields[0])})
      with pytest.raises(ValueError, match="gold_evidence_ownership"):
          gold_bio_tags(LabeledRow(row=row, gold=overlapping))


  def test_canonical_values_are_targets_for_shared_scoring_not_model_features() -> None:
      row = frozen_row()
      gold = gold_row(atom_ids=(row.atoms[0].atom_id,))
      changed_field = gold.fields[0].model_copy(update={"canonical_value": "different-private-value"})
      changed_gold = gold.model_copy(update={"fields": (changed_field,)})
      assert gold_bio_tags(LabeledRow(row=row, gold=gold)) == gold_bio_tags(
          LabeledRow(row=row, gold=changed_gold)
      )
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_labels.py`

  Expected: FAIL during collection because `labels.py` and `training_data.py` do not exist.

- [ ] **Step 3: Implement the closed BIO codec without creating a second field vocabulary.**

  ```python
  # experiments/row_extraction/arms/text/labels.py
  from __future__ import annotations

  from dataclasses import dataclass

  from experiments.row_extraction.contracts import FieldRole


  @dataclass(frozen=True)
  class BioSpan:
      role: FieldRole
      start: int
      stop: int


  def begin(role: FieldRole) -> str:
      return f"B:{role.value}"


  def inside(role: FieldRole) -> str:
      return f"I:{role.value}"


  def _parse(tag: str) -> tuple[str, FieldRole | None]:
      if tag == "O":
          return "O", None
      prefix, separator, value = tag.partition(":")
      if separator != ":" or prefix not in {"B", "I"}:
          raise ValueError("illegal_bio: malformed tag")
      try:
          return prefix, FieldRole(value)
      except ValueError as error:
          raise ValueError("illegal_bio: unknown field role") from error


  def validate_bio(tags: tuple[str, ...]) -> tuple[BioSpan, ...]:
      spans: list[BioSpan] = []
      active_role: FieldRole | None = None
      active_start = 0
      for index, tag in enumerate((*tags, "O")):
          prefix, role = _parse(tag)
          if prefix == "I" and role != active_role:
              raise ValueError("illegal_bio: inside tag has no matching begin")
          if prefix == "B" and active_role == role:
              raise ValueError("illegal_bio: adjacent same-role spans are ambiguous")
          if active_role is not None and (prefix != "I" or role != active_role):
              spans.append(BioSpan(active_role, active_start, index))
              active_role = None
          if prefix == "B":
              if role is None:
                  raise ValueError("illegal_bio: begin tag lacks role")
              active_role = role
              active_start = index
      return tuple(spans)
  ```

  In `training_data.py`, define:

  ```python
  @dataclass(frozen=True)
  class LabeledRow:
      row: FrozenRow
      gold: GoldRow
  ```

  `gold_bio_tags` must verify matching document/row IDs, unique row atom IDs, every gold atom present exactly once, each field's atoms contiguous and canonically ordered, no atom owned by two fields, and no empty gold field. It fills `O`, then `B:<FieldRole.value>` and `I:<FieldRole.value>`, and round-trips through `validate_bio`. `exact_evidence_event` returns true only for an accepted prediction whose predicted `RowType`, proposal role/atom tuples, and complete proposal set exactly match gold; duplicate roles/ownership, source regions, nonfinite scores, ambiguous gold, or abstention are false. `complete_exact_row_event` is the calibrator target and delegates value rendering/normalization to the shared metric path exactly:

  ```python
  def complete_exact_row_event(
      row: FrozenRow,
      gold: GoldRow,
      prediction: RowPrediction,
  ) -> bool:
      report = score_predictions((row,), (gold,), (prediction,))
      if report.row_count != 1:
          raise ValueError("exact_row_target_contract")
      return report.exact_rows == 1
  ```

  The lane never parses or compares a financial value itself.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_labels.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/labels.py experiments/row_extraction/arms/text/training_data.py tests/experiments/row_extraction/arms/text/test_labels.py
  git commit -m "experiment: encode row gold as legal evidence tags"
  ```

---

### Task 4: Train and Serialize the Hashed Linear Row-Type Control

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/linear.py, tests/experiments/row_extraction/arms/text/test_linear.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/linear.py`
- Test: `tests/experiments/row_extraction/arms/text/test_linear.py`

**Interfaces:**

- Consumes: `AtomFeatureTensor`, `LinearRowConfig`, the closed `RowType`, and development `LabeledRow` records.
- Produces: `RowTypeScores`, `LinearRowArtifact`, `train_linear_row_model(examples, feature_config, model_config) -> LinearRowArtifact`, `LinearRowArtifact.score(row) -> RowTypeScores`, and deterministic directory serialization.

- [ ] **Step 1: Write failing separability, repeatability, and private-artifact tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_linear.py
  import hashlib

  from experiments.row_extraction.arms.text.linear import train_linear_row_model


  def test_linear_control_learns_synthetic_row_shapes(synthetic_development_rows) -> None:
      artifact = train_linear_row_model.from_defaults(synthetic_development_rows)
      for example in synthetic_development_rows:
          scores = artifact.score(example.row)
          assert scores.predicted_type == example.gold.row_type
          assert tuple(row_type for row_type, _ in scores.scores) == artifact.row_types


  def test_training_and_serialization_are_byte_deterministic(
      synthetic_development_rows, tmp_path
  ) -> None:
      first = train_linear_row_model.from_defaults(synthetic_development_rows)
      second = train_linear_row_model.from_defaults(synthetic_development_rows)
      first_path = tmp_path / "first"
      second_path = tmp_path / "second"
      first.write(first_path)
      second.write(second_path)
      first_bytes = b"".join(path.read_bytes() for path in sorted(first_path.iterdir()))
      second_bytes = b"".join(path.read_bytes() for path in sorted(second_path.iterdir()))
      assert hashlib.sha256(first_bytes).digest() == hashlib.sha256(second_bytes).digest()
      for example in synthetic_development_rows:
          for atom in example.row.atoms:
              assert atom.text.encode("utf-8") not in first_bytes
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_linear.py`

  Expected: FAIL during collection because `linear.py` does not exist.

- [ ] **Step 3: Implement deterministic multinomial fitting and a non-pickle artifact.**

  ```python
  # experiments/row_extraction/arms/text/linear.py
  from __future__ import annotations

  from dataclasses import dataclass
  from pathlib import Path

  import numpy as np
  from numpy.typing import NDArray
  from scipy.sparse import csr_matrix
  from sklearn.linear_model import SGDClassifier
  from threadpoolctl import threadpool_limits

  from experiments.row_extraction.contracts import FrozenRow, RowType

  from .config import LinearRowConfig, TextFeatureConfig
  from .features import extract_atom_features
  from .training_data import LabeledRow


  @dataclass(frozen=True)
  class RowTypeScores:
      predicted_type: RowType
      scores: tuple[tuple[RowType, float], ...]
      top_probability: float
      margin: float
      normalized_entropy: float


  @dataclass(frozen=True)
  class LinearRowArtifact:
      feature_config: TextFeatureConfig
      row_types: tuple[RowType, ...]
      weights: NDArray[np.float64]
      intercept: NDArray[np.float64]

      def score(self, row: FrozenRow) -> RowTypeScores:
          vector = _row_csr(row, self.feature_config)
          logits = np.asarray(vector @ self.weights.T).reshape(-1) + self.intercept
          logits -= logits.max()
          probabilities = np.exp(logits) / np.exp(logits).sum()
          order = np.argsort(-probabilities, kind="stable")
          top = int(order[0])
          runner_up = int(order[1]) if len(order) > 1 else top
          entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-15))))
          denominator = np.log(len(self.row_types)) if len(self.row_types) > 1 else 1.0
          return RowTypeScores(
              predicted_type=self.row_types[top],
              scores=tuple(zip(self.row_types, probabilities.tolist(), strict=True)),
              top_probability=float(probabilities[top]),
              margin=float(probabilities[top] - probabilities[runner_up]),
              normalized_entropy=entropy / denominator,
          )
  ```

  `_row_csr` sums signed atom hash buckets and fixed dense summary columns into one `float64` CSR row. It never includes atom/document IDs. `train_linear_row_model` rejects rows outside `DatasetSplit.TRAIN` and duplicate identities, then sorts training records by `(sha256(AtomFeatureTensor.canonical_bytes()), RowType.value)` so SGD order is deterministic without letting document/row identity affect fitting. It uses:

  ```python
  def _fit_estimator(
      matrix: csr_matrix,
      labels: NDArray[np.str_],
      config: LinearRowConfig,
  ) -> SGDClassifier:
      estimator = SGDClassifier(
          loss=config.loss,
          penalty="l2",
          alpha=config.alpha,
          max_iter=config.max_iter,
          tol=config.tolerance,
          shuffle=config.shuffle,
          random_state=config.random_seed,
          average=False,
          class_weight=None,
      )
      with threadpool_limits(limits=1):
          estimator.fit(matrix, labels)
      return estimator
  ```

  Assert that training contains every frozen `RowType`, then fit exactly once inside the
  one-thread context shown above. Export only sorted row-type values, canonical feature/config
  JSON, little-endian `weights.f64le`, and `intercept.f64le`. Use explicit shapes in metadata,
  `os.replace` from a file in the same private output directory, and SHA-256 every exact byte.
  Do not use pickle, joblib, a learned vocabulary, or a filename as an identity input. Loader
  code validates lengths, digests, labels, schema identity, and finite arrays before enabling
  prediction.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_linear.py`

  Expected: PASS, including identical bytes across repeated fits.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/linear.py tests/experiments/row_extraction/arms/text/test_linear.py
  git commit -m "experiment: add hashed linear row control"
  ```

---

### Task 5: Train the Linear-Chain Evidence-Atom Tagger

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/tagger.py, tests/experiments/row_extraction/arms/text/test_tagger.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/tagger.py`
- Test: `tests/experiments/row_extraction/arms/text/test_tagger.py`

**Interfaces:**

- Consumes: `AtomFeatureTensor`, legal gold BIO tags, `CrfTaggerConfig`, and development rows.
- Produces: `TagSequence`, `CrfArtifact`, `train_crf(examples, feature_config, config, output_path) -> CrfArtifact`, and `CrfArtifact.tag(row) -> TagSequence`.
- `TagSequence` contains tags and per-atom predicted-tag marginals in canonical atom order. It contains no rendered text or typed/free-form value.

- [ ] **Step 1: Write failing sequence, evidence-order, and artifact-privacy tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_tagger.py
  import pytest

  from experiments.row_extraction.arms.text.labels import validate_bio
  from experiments.row_extraction.arms.text.tagger import train_crf


  def test_crf_returns_one_legal_tag_and_marginal_per_atom(
      synthetic_development_rows, tmp_path
  ) -> None:
      artifact = train_crf.from_defaults(
          synthetic_development_rows, tmp_path / "tagger.crfsuite"
      )
      result = artifact.tag(synthetic_development_rows[0].row)
      assert result.atom_ids == tuple(
          atom.atom_id for atom in synthetic_development_rows[0].row.atoms
      )
      assert len(result.tags) == len(result.atom_ids)
      assert len(result.marginals) == len(result.atom_ids)
      validate_bio(result.tags)
      assert all(0.0 <= score <= 1.0 for score in result.marginals)


  def test_crf_artifact_has_no_literal_private_tokens(
      synthetic_development_rows, tmp_path
  ) -> None:
      path = tmp_path / "tagger.crfsuite"
      train_crf.from_defaults(synthetic_development_rows, path)
      payload = path.read_bytes()
      for example in synthetic_development_rows:
          for atom in example.row.atoms:
              assert atom.text.encode("utf-8") not in payload


  def test_illegal_model_sequence_abstains_instead_of_repairing(
      monkeypatch, trained_crf, synthetic_frozen_row
  ) -> None:
      monkeypatch.setattr(
          type(trained_crf),
          "_raw_tags",
          lambda self, row: ("I:description",) * len(row.atoms),
      )
      with pytest.raises(ValueError, match="illegal_bio"):
          trained_crf.tag(synthetic_frozen_row)
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_tagger.py`

  Expected: FAIL during collection because `tagger.py` does not exist.

- [ ] **Step 3: Implement the deterministic CRFsuite adapter.**

  ```python
  # experiments/row_extraction/arms/text/tagger.py
  from __future__ import annotations

  import hashlib
  from dataclasses import dataclass
  from pathlib import Path

  import pycrfsuite

  from experiments.row_extraction.contracts import FrozenRow

  from .config import CrfTaggerConfig, TextFeatureConfig
  from .features import AtomFeatureTensor, extract_atom_features
  from .labels import validate_bio


  @dataclass(frozen=True)
  class TagSequence:
      atom_ids: tuple[str, ...]
      tags: tuple[str, ...]
      marginals: tuple[float, ...]
      model_sha256: str


  def _crf_features(tensor: AtomFeatureTensor) -> list[dict[str, float]]:
      sequence: list[dict[str, float]] = []
      for atom_index in range(len(tensor.atom_ids)):
          features: dict[str, float] = {"bias": 1.0}
          for column, name in enumerate(tensor.identity.dense_feature_names):
              if bool(tensor.dense_mask[atom_index, column]):
                  features[f"d:{name}"] = float(tensor.dense[atom_index, column])
          for position in range(tensor.hashed_indices.shape[1]):
              if bool(tensor.hashed_mask[atom_index, position]):
                  bucket = int(tensor.hashed_indices[atom_index, position])
                  features[f"h:{bucket:05d}"] = float(tensor.hashed_values[atom_index, position])
          sequence.append(dict(sorted(features.items())))
      return sequence
  ```

  Training requirements:

  - Reject duplicate/non-training records, then sort by `(sha256(AtomFeatureTensor.canonical_bytes()), tuple(gold_bio_tags(example)))`; document/row identity must not affect CRF append order.
  - Append `_crf_features(tensor)` and `gold_bio_tags(example)` in that order.
  - Call `trainer.select(config.algorithm)` and set exactly `c1`, `c2`, `max_iterations`, `feature.possible_transitions`, and `feature.minfreq=0.0`; do not enable random restarts or multiple workers.
  - Write to an explicit lane-private path, close the trainer, SHA-256 the file, load it into a fresh `pycrfsuite.Tagger`, and verify every label is `O` or a valid shared `FieldRole` BIO label.
  - At prediction, compute the feature sequence, obtain the best tag sequence, call `validate_bio` without repair, and query `tagger.marginal(tag, position)` for each chosen tag. Reject nonfinite/out-of-range marginals or atom-count mismatch.
  - Train twice in a synthetic test and require identical tag sequences, marginals, and artifact SHA-256. If CRFsuite's pinned build cannot produce byte-identical artifacts in the pinned runtime, stop and report that determinism failure; do not weaken the test.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_tagger.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/tagger.py tests/experiments/row_extraction/arms/text/test_tagger.py
  git commit -m "experiment: add evidence atom sequence tagger"
  ```

---

### Task 6: Decode Only Exact, Renderable Evidence Spans

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/evidence.py, tests/experiments/row_extraction/arms/text/test_evidence.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/evidence.py`
- Test: `tests/experiments/row_extraction/arms/text/test_evidence.py`

**Interfaces:**

- Consumes: `FrozenRow`, `TagSequence`, `validate_bio`, `FieldProposal`, and shared `render_proposal(prediction, proposal) -> str`.
- Produces: `DecodedEvidence`, `decode_evidence(row, sequence) -> DecodedEvidence`, and `validate_proposals(row, proposals) -> tuple[FieldProposal, ...]`.
- `DecodedEvidence` contains proposals, legality, minimum/mean span confidence, and stable reason codes. It contains no rendered or generated value.

- [ ] **Step 1: Write failing evidence-identity and fail-closed tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_evidence.py
  from dataclasses import replace

  import pytest

  from experiments.row_extraction.arms.text.evidence import decode_evidence
  from experiments.row_extraction.contracts import Decision, RowPrediction, RowType
  from experiments.row_extraction.evidence import render_proposal


  def test_bio_span_becomes_one_exact_atom_proposal(synthetic_frozen_row, legal_tag_sequence) -> None:
      decoded = decode_evidence(synthetic_frozen_row, legal_tag_sequence)
      atom_ids = tuple(atom.atom_id for atom in synthetic_frozen_row.atoms)
      assert decoded.legal is True
      assert tuple(proposal.atom_ids for proposal in decoded.proposals) == (
          tuple(atom_ids[span.start:span.stop] for span in decoded.spans)
      )
      assert all(proposal.source_region is None for proposal in decoded.proposals)
      assert all(0.0 <= proposal.raw_score <= 1.0 for proposal in decoded.proposals)

      prediction = RowPrediction(
          experiment_id="row-text",
          config_id="synthetic",
          document_id=synthetic_frozen_row.document_id,
          row_id=synthetic_frozen_row.row_id,
          predicted_type=RowType.PRIMARY_TRANSACTION,
          evidence_atoms=synthetic_frozen_row.atoms,
          proposals=decoded.proposals,
          exact_row_confidence=1.0,
          decision=Decision.ACCEPT,
          reasons=(),
      )
      assert tuple(render_proposal(prediction, proposal) for proposal in decoded.proposals) == (
          tuple(
              " ".join(synthetic_frozen_row.atoms[index].text for index in range(span.start, span.stop))
              for span in decoded.spans
          )
      )


  @pytest.mark.parametrize("mutation", ["unknown_atom", "duplicate_atom", "reordered_atom"])
  def test_nonexact_evidence_abstains_without_best_effort(
      synthetic_frozen_row, legal_tag_sequence, mutation
  ) -> None:
      atom_ids = legal_tag_sequence.atom_ids
      assert len(atom_ids) >= 2
      mutated_ids = {
          "unknown_atom": ("missing", *atom_ids[1:]),
          "duplicate_atom": (atom_ids[0], atom_ids[0], *atom_ids[2:]),
          "reordered_atom": (atom_ids[1], atom_ids[0], *atom_ids[2:]),
      }[mutation]
      broken = replace(legal_tag_sequence, atom_ids=mutated_ids)
      with pytest.raises(ValueError, match="evidence_atom_identity_mismatch"):
          decode_evidence(synthetic_frozen_row, broken)
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_evidence.py`

  Expected: FAIL during collection because `evidence.py` does not exist.

- [ ] **Step 3: Implement exact evidence decoding.**

  ```python
  # experiments/row_extraction/arms/text/evidence.py
  from __future__ import annotations

  import math
  from dataclasses import dataclass

  from experiments.row_extraction.contracts import FieldProposal, FrozenRow

  from .labels import BioSpan, validate_bio
  from .tagger import TagSequence


  @dataclass(frozen=True)
  class DecodedEvidence:
      proposals: tuple[FieldProposal, ...]
      spans: tuple[BioSpan, ...]
      legal: bool
      minimum_span_confidence: float
      mean_span_confidence: float
      reasons: tuple[str, ...]


  def decode_evidence(row: FrozenRow, sequence: TagSequence) -> DecodedEvidence:
      expected_ids = tuple(atom.atom_id for atom in row.atoms)
      if sequence.atom_ids != expected_ids or len(set(expected_ids)) != len(expected_ids):
          raise ValueError("evidence_atom_identity_mismatch")
      if len(sequence.tags) != len(expected_ids) or len(sequence.marginals) != len(expected_ids):
          raise ValueError("evidence_sequence_length_mismatch")
      spans = validate_bio(sequence.tags)
      proposals: list[FieldProposal] = []
      span_scores: list[float] = []
      for span in spans:
          atom_ids = expected_ids[span.start:span.stop]
          marginals = sequence.marginals[span.start:span.stop]
          score = min(marginals)
          if not atom_ids or not math.isfinite(score) or not 0.0 <= score <= 1.0:
              raise ValueError("evidence_span_score_invalid")
          proposals.append(FieldProposal(
              role=span.role,
              atom_ids=atom_ids,
              source_region=None,
              owner_row_id=None,
              raw_score=score,
          ))
          span_scores.append(score)
      validate_proposals(row, tuple(proposals))
      minimum = min(span_scores, default=0.0)
      mean = sum(span_scores) / len(span_scores) if span_scores else 0.0
      return DecodedEvidence(tuple(proposals), spans, True, minimum, mean, ())
  ```

  `validate_proposals` must require: exact membership in one fixed row; canonical atom order; contiguous atoms per proposal; no atom owned by two proposals; no duplicate singleton role; no empty proposal; no source region for this text experiment; finite score in `[0, 1]`; and stable proposal ordering by first atom position. After row type is known, a separate `assign_owner(row, predicted_type, proposal)` preserves `owner_row_id=None` for primary/current-row ownership and sets `row.previous_row_id` only for a continuation; missing previous ownership is a stable abstention. Neither adjacency ID enters a feature or score. The validator returns the input tuple unchanged or raises one exact stable reason from `evidence_atom_identity_mismatch`, `evidence_sequence_length_mismatch`, `evidence_span_score_invalid`, `evidence_proposal_overlap`, `evidence_proposal_role_duplicate`, or `evidence_proposal_order_invalid`. It never joins token strings, parses a value, guesses missing evidence, expands a boundary, or chooses a reconciliation-friendly alternative. The shared `render_proposal` and metrics derive text and typed values from the exact prediction ledger.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_evidence.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/evidence.py tests/experiments/row_extraction/arms/text/test_evidence.py
  git commit -m "experiment: decode only exact evidence spans"
  ```

---

### Task 7: Fit Grouped Out-of-Fold Exact-Row Calibration

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/calibration.py, tests/experiments/row_extraction/arms/text/test_calibration.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/calibration.py`
- Test: `tests/experiments/row_extraction/arms/text/test_calibration.py`

**Interfaces:**

- Consumes: training-only `LabeledRow`, the read-only shared `SplitManifest`, raw row/type/span signals, shared-metric `complete_exact_row_event`, shared `Fold`, shared `grouped_folds`, and `CalibrationConfig`.
- Produces: `ExactRowScoreVector`, `OofPrediction`, `SigmoidCalibrator`, `validate_oof_rows(examples) -> None`, `fold_index_for_document(folds, document_id) -> int`, `fit_oof_calibrator(...) -> SigmoidCalibrator`, and canonical non-pickle calibrator serialization. Risk/coverage is always consumed from shared `MetricReport.risk_coverage`.
- The calibrated event is complete accepted-row exactness: exact row type and exact complete evidence proposal set. The locked test never contributes a label, feature, fold, threshold, or calibrator parameter.

- [ ] **Step 1: Write failing leakage and exact-row calibration tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_calibration.py
  import numpy as np
  import pytest

  from experiments.row_extraction.contracts import DatasetSplit, LaneDisposition
  from experiments.row_extraction.split import SplitManifest, grouped_folds
  from experiments.row_extraction.arms.text.calibration import (
      ExactRowScoreVector,
      fold_index_for_document,
      validate_oof_rows,
  )


  def test_grouped_folds_never_split_a_document_family(
      synthetic_development_rows,
      synthetic_split_manifest: SplitManifest,
  ) -> None:
      rows = tuple(example.row for example in synthetic_development_rows)
      folds = grouped_folds(rows, synthetic_split_manifest, fold_count=3)
      assert all(fold.train_document_ids.isdisjoint(fold.validation_document_ids) for fold in folds)
      assert all(
          fold_index_for_document(folds, example.row.document_id) >= 0
          and example.row.split is DatasetSplit.TRAIN
          for example in synthetic_development_rows
      )


  def test_test_rows_are_rejected_before_oof_fitting(synthetic_test_rows) -> None:
      with pytest.raises(ValueError, match="training_only"):
          validate_oof_rows(synthetic_test_rows)


  def test_score_vector_is_fixed_finite_and_identity_free() -> None:
      vector = ExactRowScoreVector(0.9, 0.4, 0.2, 0.8, 0.85, 1.0, 1.0, 2.0)
      array = vector.as_array()
      assert array.shape == (1, 8)
      assert array.dtype == np.float64
      assert np.isfinite(array).all()

  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_calibration.py`

  Expected: FAIL during collection because `calibration.py` does not exist.

- [ ] **Step 3: Implement fixed score vectors and grouped OOF fitting.**

  ```python
  # experiments/row_extraction/arms/text/calibration.py
  from __future__ import annotations

  from dataclasses import dataclass

  import numpy as np
  from numpy.typing import NDArray
  from sklearn.linear_model import LogisticRegression
  from threadpoolctl import threadpool_limits


  @dataclass(frozen=True)
  class ExactRowScoreVector:
      row_type_probability: float
      row_type_margin: float
      row_type_entropy: float
      minimum_span_marginal: float
      mean_span_marginal: float
      sequence_legal: float
      evidence_valid: float
      proposal_count: float

      def as_array(self) -> NDArray[np.float64]:
          result = np.asarray((
              self.row_type_probability,
              self.row_type_margin,
              self.row_type_entropy,
              self.minimum_span_marginal,
              self.mean_span_marginal,
              self.sequence_legal,
              self.evidence_valid,
              self.proposal_count,
          ), dtype=np.float64).reshape(1, 8)
          if not np.isfinite(result).all():
              raise ValueError("calibration_score_nonfinite")
          return result


  @dataclass(frozen=True)
  class OofPrediction:
      document_id: str
      row_id: str
      fold: int
      score: ExactRowScoreVector
      exact: bool


  @dataclass(frozen=True)
  class SigmoidCalibrator:
      coefficients: NDArray[np.float64]
      intercept: float

      def predict(self, score: ExactRowScoreVector) -> float:
          logit = float((score.as_array() @ self.coefficients.reshape(8, 1))[0, 0]) + self.intercept
          if logit >= 0.0:
              return 1.0 / (1.0 + np.exp(-logit))
          exponential = np.exp(logit)
          return float(exponential / (1.0 + exponential))
  ```

  The lane must call shared `grouped_folds` and then validate its result as follows:

  1. reject empty data, duplicate row IDs, any split other than `DatasetSplit.TRAIN` with stable reason `training_only`, fewer document groups than folds, duplicate validation membership, or any train/validation overlap;
  2. require every training document to appear in exactly one validation fold and never recompute, shuffle, or repair shared fold membership;
  3. verify every fold has at least one positive and one negative exact-row target before fitting; and
  4. never expose document IDs or fold membership to feature/model/calibrator inputs or tracked reports.

  `fit_oof_calibrator` retrains the entire candidate model once per fold on other training groups, predicts only the held-out groups, and creates each binary target with `complete_exact_row_event`. It sorts the fit matrix by `(ExactRowScoreVector.as_array().tobytes(), exact)` so identity does not influence solver order; document/row IDs remain only in the private OOF audit stream. It then fits exactly:

  Each held-out raw prediction uses the ordinary predicted type and exact proposals, sets
  `exact_row_confidence=None`, and uses `Decision.ACCEPT` only when every pre-calibration
  evidence/type/ownership gate passes. Model uncertainty is `Decision.ABSTAIN`; a failed
  deterministic evidence/type/ownership gate is `Decision.REJECT`; both carry no proposals.
  This provisional decision exists only to let the unchanged shared singleton scorer define
  the binary target. It is never written as a canonical evaluated prediction or treated as a
  calibrated acceptance.

  ```python
  def _fit_sigmoid(
      matrix: NDArray[np.float64],
      targets: NDArray[np.int8],
  ) -> LogisticRegression:
      estimator = LogisticRegression(
          penalty="l2",
          C=1.0,
          solver="lbfgs",
          max_iter=2_000,
          tol=1e-10,
          random_state=20_260_728,
      )
      with threadpool_limits(limits=1):
          estimator.fit(matrix, targets)
      return estimator
  ```

  Export only little-endian coefficients/intercept and canonical schema metadata. A calibrator is invalid if its feature-schema, label-contract, candidate-config, OOF-fold-manifest, model artifact, or runtime identity differs. Threshold selection and AURC are computed later from unchanged shared `MetricReport.risk_coverage` on `DatasetSplit.VALIDATION`; this module must not implement a second selective-metric definition.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_calibration.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/calibration.py tests/experiments/row_extraction/arms/text/test_calibration.py
  git commit -m "experiment: calibrate exact rows from grouped oof scores"
  ```

---

### Task 8: Assemble the Fail-Closed `ExperimentArm`

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/arm.py, tests/experiments/row_extraction/arms/text/test_arm.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/arm.py`
- Test: `tests/experiments/row_extraction/arms/text/test_arm.py`

**Interfaces:**

- Consumes: `LockedTextConfig`, exact shared `ArtifactIdentity` records for the row model/tagger/calibrator, linear row artifact, CRF artifact, exact evidence decoder, sigmoid calibrator, `Decision`, and common contracts.
- Produces: `TextPredictionTrace`, `TextExperimentArm`, `TextExperimentArmFactory`,
  `TextExperimentArm.predict_trace(row) -> TextPredictionTrace`, exact
  `ExperimentArm.predict(row) -> RowPrediction` behavior, and a factory with the frozen-handoff
  manifest identity and exact zero subprocess count.
- The common prediction contains no values. Private trace contains only scores, legality, stable reasons, and artifact/config identities; it contains no raw text or rendered financial data.

- [ ] **Step 1: Write failing accepted/abstained/common-runner tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_arm.py
  from dataclasses import replace

  import numpy as np

  from experiments.row_extraction.arms.text.calibration import SigmoidCalibrator
  from experiments.row_extraction.contracts import Decision, ExperimentArm
  from experiments.row_extraction.runner import run_arm


  def test_arm_satisfies_the_frozen_protocol(trained_text_arm) -> None:
      arm: ExperimentArm = trained_text_arm
      assert arm.experiment_id == "row-text"
      assert arm.config_id == trained_text_arm.locked.candidate.config_id


  def test_prediction_contains_only_exact_proposals(trained_text_arm, synthetic_frozen_row) -> None:
      prediction = trained_text_arm.predict(synthetic_frozen_row)
      row_atom_ids = {atom.atom_id for atom in synthetic_frozen_row.atoms}
      assert prediction.document_id == synthetic_frozen_row.document_id
      assert prediction.row_id == synthetic_frozen_row.row_id
      assert prediction.evidence_atoms == synthetic_frozen_row.atoms
      assert all(set(proposal.atom_ids) <= row_atom_ids for proposal in prediction.proposals)
      assert all(proposal.source_region is None for proposal in prediction.proposals)
      assert 0.0 <= prediction.exact_row_confidence <= 1.0


  def test_low_confidence_abstains_with_no_proposals(
      trained_text_arm, synthetic_frozen_row
  ) -> None:
      low_confidence_arm = replace(
          trained_text_arm,
          calibrator=SigmoidCalibrator(coefficients=np.zeros(8, dtype=np.float64), intercept=-100.0),
      )
      prediction = low_confidence_arm.predict(synthetic_frozen_row)
      assert prediction.decision is Decision.ABSTAIN
      assert prediction.proposals == ()
      assert prediction.reasons == ("text_exact_row_below_threshold",)


  def test_shared_runner_gets_byte_identical_predictions(
      trained_text_arm_factory, synthetic_rows, canonical_jsonl_sink_factory,
      synthetic_resource_spec_factory,
  ) -> None:
      first_sink = canonical_jsonl_sink_factory()
      second_sink = canonical_jsonl_sink_factory()
      first = run_arm(
          synthetic_rows,
          trained_text_arm_factory(),
          first_sink,
          synthetic_resource_spec_factory("run-1"),
      )
      second = run_arm(
          synthetic_rows,
          trained_text_arm_factory(),
          second_sink,
          synthetic_resource_spec_factory("run-2"),
      )
      assert first.predictions_sha256 == second.predictions_sha256
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_arm.py`

  Expected: FAIL during collection because `arm.py` does not exist.

- [ ] **Step 3: Implement prediction tracing and strict abstention.**

  ```python
  # experiments/row_extraction/arms/text/arm.py
  from __future__ import annotations

  from dataclasses import dataclass

  from experiments.row_extraction.contracts import (
      ArtifactIdentity,
      Decision,
      FrozenRow,
      RowPrediction,
  )

  from .calibration import ExactRowScoreVector, SigmoidCalibrator
  from .config import LockedTextConfig
  from .evidence import DecodedEvidence, decode_evidence
  from .linear import LinearRowArtifact, RowTypeScores
  from .tagger import CrfArtifact, TagSequence


  @dataclass(frozen=True)
  class TextPredictionTrace:
      prediction: RowPrediction
      row_type_scores: RowTypeScores
      tag_sequence: TagSequence | None
      decoded: DecodedEvidence | None
      calibration_score: ExactRowScoreVector
      sequence_legal: bool
      artifact_identities: tuple[ArtifactIdentity, ...]


  @dataclass(frozen=True)
  class TextExperimentArm:
      locked: LockedTextConfig
      artifact_identities: tuple[ArtifactIdentity, ...]
      row_model: LinearRowArtifact
      tagger: CrfArtifact
      calibrator: SigmoidCalibrator

      @property
      def experiment_id(self) -> str:
          return self.locked.candidate.experiment_id

      @property
      def config_id(self) -> str:
          return self.locked.candidate.config_id

      def predict(self, row: FrozenRow) -> RowPrediction:
          return self.predict_trace(row).prediction
  ```

  `predict_trace` follows this exact fail-closed order:

  1. Verify the loaded model, tagger, calibrator, feature schema, labels, runtime, config ID, and their SHA-256 values against `LockedTextConfig` and the three exact shared `ArtifactIdentity` records. Mismatch raises `ValueError("text_artifact_identity_mismatch")` before scoring.
  2. Score `RowType` with the hashed linear control, tag the fixed evidence atoms with the CRF, call `decode_evidence`, then assign owners from the predicted row type without using adjacency IDs as features. Experiment 2 predictions are scored separately through common metrics; they never enter this arm.
  3. Model uncertainty, `RowType.AMBIGUOUS`, a model-only `RowType.STRUCTURAL` result, or low calibrated confidence yields `Decision.ABSTAIN`; the learned arm never claims `Decision.IGNORE`. An illegal sequence, unknown atom, overlap, empty required proposal set, or failed deterministic evidence/type/ownership validation yields `Decision.REJECT`. Both outcomes carry no proposals, confidence `0.0`, and exactly one stable reason. Artifact/config/nonfinite failures raise before a prediction is enabled. Do not emit partial fields after a row-level failure.
  4. Build `ExactRowScoreVector` from row probability, margin, normalized entropy, min/mean span marginal (both `1.0` for the frozen deterministic field control), legality, evidence validity, and proposal count. These eight meanings are immutable across both candidates.
  5. Calibrate once. Accept only if confidence is at least the frozen threshold and all evidence/type/ownership validators passed. The accepted prediction contains the unchanged exact proposals. Reconciliation is not inspected and cannot select or repair a proposal.
  6. Construct `RowPrediction` with `evidence_atoms=row.atoms` in exact frozen order, the exact common fields, and canonical reason ordering. Even abstentions carry the complete fixed atom ledger and no proposals. The output is a pure function of the row and locked artifacts; no mutable `last_trace`, cache, clock, environment lookup, or random call is permitted.

  If the shared `Decision` vocabulary does not contain `ABSTAIN`, stop and reconcile the exact shared abstention member on the foundation branch. Do not translate it through a local compatibility alias.

- [ ] **Step 4: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_arm.py`

  Expected: PASS.

- [ ] **Step 5: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/arm.py tests/experiments/row_extraction/arms/text/test_arm.py
  git commit -m "experiment: assemble fail closed row text arm"
  ```

---

### Task 9: Select on Calibration and Freeze the Configuration Handoff

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/train.py, experiments/row_extraction/arms/text/freeze.py, tests/experiments/row_extraction/arms/text/test_freeze.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/train.py`
- Create: `experiments/row_extraction/arms/text/freeze.py`
- Test: `tests/experiments/row_extraction/arms/text/test_freeze.py`

**Interfaces:**

- Consumes: separately materialized foundation `DatasetSplit.TRAIN` and `DatasetSplit.VALIDATION` row/gold streams, the independently supplied split-manifest SHA-256 (not the manifest contents), fixed candidate matrix, experiment-2 validation predictions, common metrics, grouped OOF calibration, and lane-private output paths.
- Produces: `CandidateValidation`, `HandoffVerification`, `FrozenHandoff`, `train_candidates(...) -> tuple[CandidateValidation, ...]`, `select_candidate(validations: Sequence[CandidateValidation], risk_target: Decimal) -> CandidateValidation | None`, `freeze_handoff(selection: CandidateValidation | None, validations: Sequence[CandidateValidation], output_dir: Path) -> FrozenHandoff`, `verify_handoff(handoff: FrozenHandoff) -> HandoffVerification`, and `build_text_resource_spec(rows_identity, row_count, split, handoff, runtime_identity, private_root, model_inventory, dependency_inventory, cache_root, inventory_output) -> ResourceSpec`.
- An eligible private `FrozenHandoff` directory contains canonical `locked-config.json`, a frozen-arm manifest, model/tagger/calibrator bytes, `artifact-identity.json`, dependency/runtime identity, validation predictions/metrics, and SHA-256 inventory. A validation-stopped directory omits `locked-config.json` and the frozen-arm manifest but retains the complete validation evidence, stable stop reason, artifact inventory, and checkpoint. Tracked code contains no realized private hash or metric.
- `freeze_handoff` writes disjoint private model and dependency `ResourceInventory` files. The
  resource-spec builder validates their identities, exact frozen-arm identity, one split-filtered
  row-sequence identity/count, `worker_count=1`, and distinct nonexistent cache/inventory paths.
  It fixes `resource_basis="end-to-end-method"`.
  Text inference has no external subprocess and no separate preparation phase; the factory
  count and shared measured `preparation_ns` are exactly zero.

- [ ] **Step 1: Write failing tests for partition isolation, deterministic selection, and a complete handoff.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_freeze.py
  from dataclasses import replace
  from decimal import Decimal

  import pytest

  from experiments.row_extraction.contracts import DatasetSplit
  from experiments.row_extraction.arms.text.freeze import freeze_handoff, select_candidate


  def test_selection_rejects_any_test_observation(candidate_validations) -> None:
      invalid = (
          replace(
              candidate_validations[0],
              observed_splits=(DatasetSplit.TRAIN, DatasetSplit.VALIDATION, DatasetSplit.TEST),
          ),
          *candidate_validations[1:],
      )
      with pytest.raises(ValueError, match="text_lane_test_split_forbidden"):
          select_candidate(invalid, risk_target=Decimal("0.005"))


  def test_selection_is_predeclared_and_stably_tie_broken(candidate_validations) -> None:
      selected = select_candidate(candidate_validations, risk_target=Decimal("0.005"))
      assert selected.config.config_id == "text-shape-geometry-v1"
      assert selected.threshold_was_selected_on is DatasetSplit.VALIDATION


  def test_frozen_handoff_is_complete_and_self_verifying(
      candidate_selection, candidate_validations, tmp_path
  ) -> None:
      handoff = freeze_handoff(candidate_selection, candidate_validations, tmp_path / "handoff")
      assert handoff.verify_all_sha256()
      assert handoff.disposition is LaneDisposition.FROZEN_ELIGIBLE
      assert handoff.locked_config is not None
      assert handoff.locked_config.worker_count == 1
      assert handoff.files == (
          "artifact-identity.json", "calibrator.f64le", "calibrator.json",
          "dependency-identity.json", "experiment-2-validation-metrics.json",
          "frozen-arm-manifest.json", "intercept.f64le", "locked-config.json",
          "model.json", "tagger.crfsuite",
          "validation-metrics.json", "validation-predictions-repeat.jsonl",
          "validation-predictions.jsonl", "validation-run-repeat.json",
          "validation-run.json", "weights.f64le",
      )
      assert handoff.locked_config.candidate.config_id == candidate_selection.config.config_id


  def test_ineligible_candidates_still_emit_terminal_handoff(
      ineligible_candidate_validations, tmp_path
  ) -> None:
      handoff = freeze_handoff(None, ineligible_candidate_validations, tmp_path / "stopped")
      assert handoff.disposition is LaneDisposition.VALIDATION_STOPPED
      assert handoff.stop_reason == "no_text_candidate_met_validation_gate"
      assert handoff.locked_config is None
      assert handoff.frozen_arm_manifest is None
      assert handoff.validation_metric_report.row_count > 0
      assert handoff.validation_run.row_count > 0
  ```

- [ ] **Step 2: Run the focused test and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_freeze.py`

  Expected: FAIL during collection because `train.py` and `freeze.py` do not exist.

- [ ] **Step 3: Implement the development/calibration workflow and deterministic selection rule.**

  `train_candidates` must execute, for each candidate in `candidate_configs()` and no others:

  1. Validate the accepted/foundation SHA, private manifest/label/schema pins, canonical fixed row IDs, and that every supplied row is exactly `DatasetSplit.TRAIN` or `DatasetSplit.VALIDATION` before reading its matching label. Encountering `DatasetSplit.TEST` raises `text_lane_test_split_forbidden`. The central foundation/comparison owns 60/20/20 membership and supplies only the two lane-visible streams.
  2. Stream development rows, train grouped OOF models, fit the exact-row sigmoid only on development OOF predictions, then train one candidate artifact on all development rows. Do not add calibration rows to model or calibrator fitting.
  3. Stream calibration rows through the candidate and the shared `score_predictions`. Keep the experiment-2 control immutable and score it through the same common metric path.
  4. Compute exact evidence-span/entity accuracy, exact transaction-row accuracy, merchant exact and normalized accuracy from `MetricReport.fields[FieldRole.DESCRIPTION]`, billed-amount results from `MetricReport.fields[FieldRole.BILLED_AMOUNT]`, all-field accuracy, omission, hallucination, cross-row/column ownership errors, row-type macro/micro F1, Brier, log loss, 10-bin reliability, risk/coverage/AURC, abstention, p50/p95/cold latency, throughput, peak subprocess RSS, artifact bytes, dependency bytes/count, cache bytes, and repeated canonical-prediction equality. Confidence intervals resample documents, never rows.
  5. Store all row-level outputs privately. Return only aggregate typed values; never print document IDs, source names, atom IDs, text, labels, financial values, or private artifact hashes.

  Use this exact lane-local selection projection; it wraps rather than changes shared reports:

  ```python
  # experiments/row_extraction/arms/text/freeze.py
  from dataclasses import dataclass
  from decimal import Decimal
  from pathlib import Path

  from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit, LaneDisposition
  from experiments.row_extraction.metrics import MetricReport
  from experiments.row_extraction.runner import RunMeasurements

  from .config import CandidateConfig, LockedTextConfig


  @dataclass(frozen=True)
  class CandidateValidation:
      config: CandidateConfig
      observed_splits: tuple[DatasetSplit, ...]
      threshold_was_selected_on: DatasetSplit
      exact_row_threshold: float
      metric_report: MetricReport
      run_measurements: RunMeasurements
      exact_span_f1: Decimal
      predictions_are_byte_identical: bool
      dependency_count: int
      artifact_identities: tuple[ArtifactIdentity, ...]
      artifact_paths: tuple[Path, ...]


  @dataclass(frozen=True)
  class FrozenHandoff:
      root: Path
      disposition: LaneDisposition
      stop_reason: str | None
      locked_config: LockedTextConfig | None
      frozen_arm_manifest: ArtifactIdentity | None
      artifact_identities: tuple[ArtifactIdentity, ...]
      observed_splits: tuple[DatasetSplit, ...]
      validation_prediction: ArtifactIdentity
      validation_repeat_prediction: ArtifactIdentity
      validation_metric_report: MetricReport
      experiment_2_validation_report: MetricReport
      validation_run: RunMeasurements
      validation_repeat_run: RunMeasurements
      dependency_count: int
      files: tuple[str, ...]

      def verify_all_sha256(self) -> bool:
          return verify_handoff(self).valid
  ```

  Select one candidate by this frozen lexicographic rule on calibration only:

  1. eligible candidates have zero hallucinated accepted rows, zero ownership collisions, byte-identical repeated predictions, valid artifact identity, and empirical risk at or below target `0.005`;
  2. maximize exact accepted transaction-row coverage at that risk target;
  3. maximize exact evidence-span F1;
  4. maximize normalized merchant accuracy;
  5. minimize AURC;
  6. minimize p95 warm latency;
  7. minimize total model plus calibrator bytes; and
  8. use the fixed candidate order from Task 1 as the final tie breaker.

  If no candidate is eligible, preserve the highest-ranked attempted candidate only as
  validation evidence, set `disposition=LaneDisposition.VALIDATION_STOPPED` with the stable
  reason `no_text_candidate_met_validation_gate`, omit the frozen-arm manifest, and do not
  open the locked test. An eligible selection sets
  `disposition=LaneDisposition.FROZEN_ELIGIBLE` and `stop_reason=None`. Do not lower the
  safety target, tune through reconciliation, inspect a locked metric, or add a candidate.

- [ ] **Step 4: Implement canonical private handoff writing and loading.**

  `freeze_handoff` writes into a new nonexistent directory under an ignored lane-private root
  and calls `fsync` before atomic rename. For an eligible selection it records the exact
  foundation commit, split/label/schema pins, candidate config, threshold, deterministic
  seeds, resolved Python/platform/package versions, worker count 1,
  model/calibrator/tagger identities, exact training command, and every file size/hash; it
  then reloads the frozen arm and predicts the synthetic contract row. For `selection=None`
  it writes `VALIDATION_STOPPED`, the stable reason, both candidates' complete validation
  `MetricReport`/`RunMeasurements` identities, determinism and error evidence, and no locked
  config or frozen-arm manifest. Existing destinations, mismatches, missing required files,
  unexpected files, symlinks, nonregular files, absolute paths inside JSON, or unpinned
  dependencies fail closed. Both paths continue to Task 10 checkpoint/handoff verification.

  Add a module entry point with this exact private command shape:

  ```bash
  test -n "$ROW_EXPERIMENT_PRIVATE"
  test "${#ROW_TEXT_FOUNDATION_COMMIT}" -eq 40
  test "${#ROW_TEXT_SPLIT_MANIFEST_SHA256}" -eq 64
  PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
    experiments.row_extraction.arms.text.train \
    --train-rows-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/train-rows.jsonl" \
    --train-gold-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/train-gold.jsonl" \
    --validation-rows-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/validation-rows.jsonl" \
    --validation-gold-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/validation-gold.jsonl" \
    --split-manifest-sha256 "$ROW_TEXT_SPLIT_MANIFEST_SHA256" \
    --experiment-2-predictions "$ROW_EXPERIMENT_PRIVATE/experiment-2/validation.jsonl" \
    --foundation-commit "$ROW_TEXT_FOUNDATION_COMMIT" \
    --output-root "$ROW_EXPERIMENT_PRIVATE/experiment-3/candidate-run"
  ```

  The runbook requires `ROW_EXPERIMENT_PRIVATE` to be an ignored local directory and
  `ROW_TEXT_FOUNDATION_COMMIT` to be the full reviewed foundation SHA. The implementation
  rejects an output root tracked by Git and any split manifest containing a test-label read
  request during training/selection.

- [ ] **Step 5: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_freeze.py`

  Expected: PASS.

- [ ] **Step 6: Run tracked gates and commit.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/train.py experiments/row_extraction/arms/text/freeze.py tests/experiments/row_extraction/arms/text/test_freeze.py
  git commit -m "experiment: freeze calibrated row text handoff"
  ```

---

### Task 10: Verify the Validation Handoff and Emit a Privacy-Safe Checkpoint

**Scope block**

```text
Scope answer: YES
Program component: experiment 3
Measured effect: exact evidence-span and transaction-row accuracy, merchant exact/normalized accuracy, calibration/risk-coverage, omission/hallucination, latency/model size/determinism
Fixed inputs: charter, accepted SHA, frozen row/split/label/common contracts defined by the shared foundation plan
Allowed files: only experiments/row_extraction/arms/text/readiness.py, experiments/row_extraction/arms/text/report.py, tests/experiments/row_extraction/arms/text/test_readiness.py, tests/experiments/row_extraction/arms/text/test_report.py
Stop condition: stop if the plan requires transformer/generative models, document-specific features, free-form values, production src changes, or shared-contract mutation
```

**Files:**

- Create: `experiments/row_extraction/arms/text/readiness.py`
- Create: `experiments/row_extraction/arms/text/report.py`
- Test: `tests/experiments/row_extraction/arms/text/test_readiness.py`
- Test: `tests/experiments/row_extraction/arms/text/test_report.py`

**Interfaces:**

- Consumes: verified `FrozenHandoff`, its already-frozen validation predictions/metrics/run measurements, independent experiment-2 validation metrics, exact shared codecs, and privacy-safe report contracts.
- Produces: `ValidationReadiness`, `verify_validation_readiness(handoff: FrozenHandoff) -> ValidationReadiness`, and `checkpoint_markdown(readiness: ValidationReadiness) -> str` with exactly the charter's eight substantive sections.
- `DatasetSplit.TEST` rows, gold, predictions, metrics, receipts, and paths are forbidden inputs to this task and to every experiment-3 command. Only the central comparison/cascade plan may open and score the locked test.

- [ ] **Step 1: Write failing test-inaccessibility, handoff-completeness, determinism, and privacy tests.**

  ```python
  # tests/experiments/row_extraction/arms/text/test_readiness.py
  from dataclasses import replace

  import pytest

  from experiments.row_extraction.contracts import DatasetSplit, FieldRole
  from experiments.row_extraction.arms.text.readiness import verify_validation_readiness


  def test_readiness_rejects_any_test_split_receipt(
      verified_text_handoff,
  ) -> None:
      invalid = replace(
          verified_text_handoff,
          observed_splits=(DatasetSplit.TRAIN, DatasetSplit.VALIDATION, DatasetSplit.TEST),
      )
      with pytest.raises(ValueError, match="text_lane_test_split_forbidden"):
          verify_validation_readiness(invalid)


  def test_validation_readiness_contains_exact_shared_metrics_and_resources(
      verified_text_handoff,
  ) -> None:
      result = verify_validation_readiness(verified_text_handoff)
      assert result.validation_predictions_are_byte_identical
      report = result.validation_metric_report
      merchant = report.fields[FieldRole.DESCRIPTION]
      assert 0 <= report.exact_rows <= report.row_count
      assert merchant.exact_matches <= merchant.eligible_rows
      assert merchant.normalized_matches <= merchant.eligible_rows
      assert merchant.omissions >= 0
      assert merchant.hallucinations >= 0
      assert report.brier_score is not None
      assert report.log_loss is not None
      assert report.area_under_risk_coverage is not None
      assert report.coverage_at_risk
      assert report.calibration_bins
      assert report.risk_coverage
      assert result.validation_run.p95_ns >= result.validation_run.p50_ns
      assert result.validation_run.model_bytes > 0
      assert result.validation_run.predictions_sha256 == result.validation_prediction.sha256
      assert result.validation_run.cold_start_ns > 0
      assert result.validation_run.throughput_rows_per_second > 0
      assert result.dependency_count >= 3
      assert result.validation_run.dependency_bytes > 0
      assert result.validation_run.worker_count == 1
      assert result.observed_splits == (DatasetSplit.TRAIN, DatasetSplit.VALIDATION)
  ```

  ```python
  # tests/experiments/row_extraction/arms/text/test_report.py
  from experiments.row_extraction.arms.text.report import checkpoint_markdown

  EXPECTED_HEADINGS = (
      "Scope answer and program component",
      "Hypothesis tested",
      "Fixed inputs and exact configuration",
      "Files changed",
      "Tests and verification evidence",
      "Measurements without private contents",
      "Error categories and limitations",
      "Next in-scope action or stop decision",
  )


  def test_checkpoint_has_exact_sections_and_no_private_payload(
      validation_readiness,
  ) -> None:
      report = checkpoint_markdown(validation_readiness)
      assert tuple(line[3:] for line in report.splitlines() if line.startswith("## ")) == EXPECTED_HEADINGS
      for forbidden in ("private/source.pdf", "synthetic merchant", "123.45", "row-id"):
          assert forbidden not in report
      assert "test split opened: no" in report.lower()
      assert "central comparison owns the locked run" in report.lower()
  ```

- [ ] **Step 2: Run the focused tests and confirm RED.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_readiness.py tests/experiments/row_extraction/arms/text/test_report.py`

  Expected: FAIL during collection because `readiness.py` and `report.py` do not exist.

- [ ] **Step 3: Implement validation-only handoff verification.**

  Use this exact lane-local projection; it wraps rather than changes shared contracts:

  ```python
  # experiments/row_extraction/arms/text/readiness.py
  from dataclasses import dataclass
  from decimal import Decimal

  from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit, LaneDisposition
  from experiments.row_extraction.metrics import MetricReport
  from experiments.row_extraction.runner import RunMeasurements

  from .freeze import FrozenHandoff, verify_handoff


  @dataclass(frozen=True)
  class ValidationReadiness:
      experiment_id: str
      config_id: str | None
      disposition: LaneDisposition
      stop_reason: str | None
      observed_splits: tuple[DatasetSplit, ...]
      validation_prediction: ArtifactIdentity
      validation_metric_report: MetricReport
      experiment_2_validation_report: MetricReport
      validation_run: RunMeasurements
      validation_repeat_run: RunMeasurements
      validation_predictions_are_byte_identical: bool
      dependency_count: int


  def verify_validation_readiness(handoff: FrozenHandoff) -> ValidationReadiness:
      verified = verify_handoff(handoff)
      if not verified.valid:
          raise ValueError("text_handoff_identity_mismatch")
      if DatasetSplit.TEST in handoff.observed_splits:
          raise ValueError("text_lane_test_split_forbidden")
      if handoff.observed_splits != (DatasetSplit.TRAIN, DatasetSplit.VALIDATION):
          raise ValueError("text_handoff_split_incomplete")
      if handoff.disposition is LaneDisposition.FROZEN_ELIGIBLE and handoff.stop_reason is not None:
          raise ValueError("eligible_text_handoff_has_stop_reason")
      if handoff.disposition is LaneDisposition.VALIDATION_STOPPED and handoff.stop_reason is None:
          raise ValueError("stopped_text_handoff_missing_reason")
      if handoff.disposition is LaneDisposition.FROZEN_ELIGIBLE and handoff.locked_config is None:
          raise ValueError("eligible_text_handoff_missing_config")
      if handoff.disposition is LaneDisposition.VALIDATION_STOPPED and handoff.locked_config is not None:
          raise ValueError("stopped_text_handoff_has_config")
      if handoff.disposition is LaneDisposition.FROZEN_ELIGIBLE and handoff.frozen_arm_manifest is None:
          raise ValueError("eligible_text_handoff_missing_arm_manifest")
      if handoff.disposition is LaneDisposition.VALIDATION_STOPPED and handoff.frozen_arm_manifest is not None:
          raise ValueError("stopped_text_handoff_has_arm_manifest")
      if handoff.validation_run.predictions_sha256 != handoff.validation_prediction.sha256:
          raise ValueError("text_validation_prediction_identity_mismatch")
      repeated_equal = (
          handoff.validation_run.predictions_sha256
          == handoff.validation_repeat_run.predictions_sha256
      )
      if handoff.disposition is LaneDisposition.FROZEN_ELIGIBLE and not repeated_equal:
          raise ValueError("text_validation_prediction_nondeterministic")
      return ValidationReadiness(
          experiment_id="row-text",
          config_id=(
              handoff.locked_config.candidate.config_id
              if handoff.locked_config is not None
              else None
          ),
          disposition=handoff.disposition,
          stop_reason=handoff.stop_reason,
          observed_splits=handoff.observed_splits,
          validation_prediction=handoff.validation_prediction,
          validation_metric_report=handoff.validation_metric_report,
          experiment_2_validation_report=handoff.experiment_2_validation_report,
          validation_run=handoff.validation_run,
          validation_repeat_run=handoff.validation_repeat_run,
          validation_predictions_are_byte_identical=repeated_equal,
          dependency_count=handoff.dependency_count,
      )
  ```

  `FrozenHandoff` from Task 9 must therefore include `observed_splits`, validation prediction
  and repeat `ArtifactIdentity` records, exact shared validation/experiment-2 reports, exact
  shared run measurements, and the artifact/config inventory. AURC, log loss,
  coverage-at-risk, cold start, throughput, dependency bytes, and worker count are read from
  those shared records rather than duplicated. It must contain no test artifact, test count,
  test hash, test metric, all-lane receipt, or cascade policy. `verify_validation_readiness` reads only
  handoff metadata and streams validation artifacts through shared codecs for digest and schema
  validation; it never receives a foundation row/gold path.

- [ ] **Step 4: Implement the exact eight-section checkpoint renderer.**

  The renderer includes the literal scope answer `YES`, experiment 3, question/hypothesis, accepted/foundation/config identities in privacy-safe form, exact lane file list, tracked test commands and status, aggregate validation measurements/control deltas, frozen error categories/limitations, and either comparison-readiness or a stop decision. It rejects free-form row data and renders only whitelisted aggregate fields. It explicitly states production `src/` was unchanged, `DatasetSplit.TEST` was not opened or scored, central comparison owns the one locked run, and pytest is not corpus or locked-test acceptance.

- [ ] **Step 5: Run focused tests and confirm GREEN.**

  Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/arms/text/test_readiness.py tests/experiments/row_extraction/arms/text/test_report.py`

  Expected: PASS.

- [ ] **Step 6: Run tracked gates and commit readiness code before touching private data.**

  ```bash
  /root/creditcard/.venv/bin/ruff format --check .
  /root/creditcard/.venv/bin/ruff check .
  /root/creditcard/.venv/bin/mypy src
  /root/creditcard/.venv/bin/mypy experiments/row_extraction/arms/text
  /root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction
  /root/creditcard/.venv/bin/pytest -q
  git add experiments/row_extraction/arms/text/readiness.py experiments/row_extraction/arms/text/report.py tests/experiments/row_extraction/arms/text/test_readiness.py tests/experiments/row_extraction/arms/text/test_report.py
  git commit -m "experiment: verify row text comparison handoff"
  ```

- [ ] **Step 7: Verify a clean committed lane, run private selection, and freeze validation artifacts.**

  Run from the committed `codex/row-extraction-text` worktree:

  ```bash
  test -z "$(git status --porcelain)"
  git merge-base --is-ancestor dee4b071ad65231da13825f2f7c74a488ca96c7c HEAD
  test -n "$ROW_EXPERIMENT_PRIVATE"
  test "${#ROW_TEXT_FOUNDATION_COMMIT}" -eq 40
  test "${#ROW_TEXT_SPLIT_MANIFEST_SHA256}" -eq 64
  test -z "$(git diff --name-only "$ROW_TEXT_FOUNDATION_COMMIT"..HEAD -- src pyproject.toml)"
  test -z "$(git diff --name-only "$ROW_TEXT_FOUNDATION_COMMIT"..HEAD -- \
    experiments/row_extraction/contracts.py experiments/row_extraction/codecs.py \
    experiments/row_extraction/evidence.py experiments/row_extraction/metrics.py \
    experiments/row_extraction/runner.py experiments/row_extraction/split.py)"
  PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
    experiments.row_extraction.arms.text.train \
    --train-rows-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/train-rows.jsonl" \
    --train-gold-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/train-gold.jsonl" \
    --validation-rows-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/validation-rows.jsonl" \
    --validation-gold-jsonl "$ROW_EXPERIMENT_PRIVATE/foundation/validation-gold.jsonl" \
    --split-manifest-sha256 "$ROW_TEXT_SPLIT_MANIFEST_SHA256" \
    --experiment-2-predictions "$ROW_EXPERIMENT_PRIVATE/experiment-2/validation.jsonl" \
    --foundation-commit "$ROW_TEXT_FOUNDATION_COMMIT" \
    --output-root "$ROW_EXPERIMENT_PRIVATE/experiment-3/candidate-run"
  ```

  Expected privacy-safe output: one aggregate line containing candidate count, shared lane
  disposition, optional selected config ID, validation-row count, exact accepted-row
  coverage/risk, determinism boolean, resource totals, and `test_split_opened=false`; no
  document/name/text/value/hash output. If no candidate passes, stop model work but continue
  through Step 8 in `VALIDATION_STOPPED` mode so the required evidence/checkpoint/handoff is
  produced.

- [ ] **Step 8: Freeze and verify the comparison handoff without opening the locked test.**

  Run:

  ```bash
  PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
    experiments.row_extraction.arms.text.freeze \
    --candidate-run "$ROW_EXPERIMENT_PRIVATE/experiment-3/candidate-run" \
    --output-dir "$ROW_EXPERIMENT_PRIVATE/experiment-3/frozen-handoff"

  PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
    experiments.row_extraction.arms.text.readiness \
    --handoff "$ROW_EXPERIMENT_PRIVATE/experiment-3/frozen-handoff" \
    --checkpoint "$ROW_EXPERIMENT_PRIVATE/experiment-3/validation-checkpoint.md"
  ```

  Expected privacy-safe output includes `experiment=row-text`, the exact shared disposition,
  `test_split_opened=false`, and `artifacts_verified=true`, plus aggregate validation/resource
  measurements. It reports `comparison_ready=true` only for `FROZEN_ELIGIBLE`; a stopped
  handoff reports `comparison_ready=false` and its stable nonprivate reason. Deliver either
  private handoff and its validation checkpoint location to the central comparison plan
  through the approved local coordination channel, not Git. Stop; do not open a test row,
  test gold record, test prediction, or test metric in this lane.

## Plan Completion Gate

Before implementation begins, the executing worker must confirm every shared accessor and constructor assumption in Task 1 against the committed foundation. Before claiming experiment completion, require:

1. ten focused RED/GREEN task histories and ten focused commits;
2. a clean committed `codex/row-extraction-text` worktree descended from the accepted/foundation SHA;
3. Ruff, mypy, and the extraction-relevant pytest suite green on the final commit, plus the complete pytest suite showing exactly the same five inherited sandbox/controller failures and no new or changed failure;
4. private model/calibrator/config artifacts ignored, hashed, self-verifying, deterministic, and free of literal private tokens;
5. grouped `DatasetSplit.TRAIN` OOF calibration with no group leakage and `DatasetSplit.VALIDATION`-only config/threshold selection;
6. the three required end-to-end controls: experiment 2, text/shape, and text/shape-plus-geometry, plus separately reported hashed-linear row-type diagnostics for both learned feature sets;
7. exact common-runner predictions and common metrics for the measured effects, including calibration/risk-coverage and latency/size/determinism;
8. no `DatasetSplit.TEST` row, label, prediction, metric, receipt, or path opened by experiment 3, with the one locked comparison left exclusively to the central comparison/cascade plan; and
9. an eight-section privacy-safe validation checkpoint that explicitly states production `src/` was unchanged and does not call tracked tests corpus acceptance.

Any failed identity, evidence, split, calibration, privacy, determinism, dependency, or shared-interface gate is a stop decision, not permission to add a special case or broaden model scope.
