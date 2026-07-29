# Row Extraction Shared Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frozen, private, document-disjoint data and evaluation foundation consumed unchanged by all four row-extraction experiments.

**Architecture:** A top-level experiment package streams immutable Pydantic records through canonical JSONL codecs. It prepares fixed rows from the accepted parser without changing row detection, validates reviewed gold labels and grouped splits, runs evidence-grounded experiment arms, and emits privacy-safe aggregate metrics. Production `src/` remains read-only.

**Tech Stack:** Python 3.13, Pydantic 2, PyMuPDF, Typer, `Decimal`, Tesseract through the accepted provider, pytest, Ruff, and mypy.

## Global Constraints

- Before every task, answer: “Does this directly measure or improve transaction-row recognition or field extraction?” and name the program component, metric, fixed inputs, allowed files, and stop condition.
- The program has exactly four experiments: per-row OCR, deterministic row types, a lightweight text model, and a lightweight image or image-plus-text model.
- Baselines and the final cascade are comparison infrastructure, not experiments.
- Row identities, row bounding boxes, row count, document partitions, and reviewed labels are immutable inputs to experiment lanes.
- Production `src/` behavior remains unchanged throughout this plan.
- No document-, issuer-, template-, merchant-, filename-, path-, hash-, amount-, date-, total-, or corpus-specific predictive feature or extraction branch is allowed.
- Every financial number is parsed and compared with `Decimal`, never binary floating point.
- Learned or OCR arms return typed proposals backed by exact evidence atoms; they do not return authoritative free-form values.
- Reconciliation may reject a candidate but may not select or repair candidates.
- Private documents, source paths, crops, labels, outputs, caches, model artifacts, and derived values stay in ignored local paths and never enter tests, commits, or public logs.
- Use Python 3.13 and `/root/creditcard/.venv`; keep all functions fully typed and deterministic.
- Follow red-green-refactor TDD for each deterministic behavior.
- A shared-contract change after experiment worktrees branch requires the lanes to stop and return to the foundation branch.
- Do not investigate or modify C5a0-P, C5aA, C5a0-R, trusted-worker/controller architecture, attestations, cryptography, ptrace/seccomp machinery, private-gate redesign, release bundles, or toolchain authority.

Before every commit in this plan, run this exact gate in addition to the task's focused RED/GREEN commands:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/mypy experiments/row_extraction
/root/creditcard/.venv/bin/pytest -q
/root/creditcard/.venv/bin/pytest -q --ignore=tests/test_corpus_gate.py
```

Ruff, both mypy runs, and the extraction-relevant pytest run must pass. The full suite must
either pass after an upstream fix or reproduce exactly the established five inherited
out-of-scope sandbox/controller failures. Any new or changed failure stops the task.

---

## File Structure

- `experiments/__init__.py`: marks tracked experiment code as a package without changing production installation.
- `experiments/row_extraction/__init__.py`: exports the stable foundation surface.
- `experiments/row_extraction/contracts.py`: immutable shared enums, records, protocol, and feature-vector contracts.
- `experiments/row_extraction/codecs.py`: bounded-memory canonical JSONL readers and writers.
- `experiments/row_extraction/evidence.py`: proposal-ledger validation and exact evidence rendering.
- `experiments/row_extraction/bundle.py`: accepted-anchor fixed-row preparation.
- `experiments/row_extraction/crops.py`: deterministic unpadded fixed-row reference crops and private crop index.
- `experiments/row_extraction/annotations.py`: private gold-label validation.
- `experiments/row_extraction/split.py`: deterministic grouped train/validation/test assignment and grouped folds.
- `experiments/row_extraction/metrics.py`: exact, normalized, OCR, omission, hallucination, calibration, and selective metrics.
- `experiments/row_extraction/runner.py`: streaming arm execution, timing, canonical prediction output, and repeat checks.
- `experiments/row_extraction/baselines.py`: accepted-anchor prediction adapter.
- `experiments/row_extraction/report.py`: privacy-safe aggregate report projection.
- `experiments/row_extraction/cli.py`: private-path preparation, validation, baseline, and scoring commands.
- `experiments/row_extraction/grouping.py`: content-neutral structure profiles, review
  candidates, reviewed partitions, and leakage-safe split freezing.
- `experiments/row_extraction/runtime.py`: canonical runtime manifests and report-context
  derivation through the existing toolchain-inspector seam.
- `experiments/row_extraction/foundation_admin.py`: separate privacy-safe administration for
  grouping and runtime artifacts; it does not add an experiment or a command to `cli.py`.
- `experiments/row_extraction/arms/__init__.py`: stable parent package for the four isolated experiment lanes.
- `docs/experiments/row-extraction-annotation-handbook.md`: tracked annotation semantics with synthetic examples only.
- `docs/experiments/row-extraction-foundation-runbook.md`: exact private commands and freeze gates without private values.
- `tests/experiments/row_extraction/factories.py`: shared synthetic contract factories.
- `tests/experiments/row_extraction/`: focused foundation tests mirroring the modules above.
- `tests/experiments/row_extraction/arms/__init__.py`: stable parent test package for lane tests.

### Task 1: Define the immutable shared contracts

```text
Scope answer: YES
Program component: shared foundation
Measured effect: all four experiments can exchange evidence-grounded predictions without changing row identities or inventing values
Fixed inputs: charter enums, fixed-row semantics, evidence-only proposal rule
Allowed files: experiments package contracts, canonical test package initializers, and synthetic contract tests
Stop condition: stop if a contract needs production models to change or permits an authoritative generated value
```

**Files:**
- Create: `experiments/__init__.py`
- Create: `experiments/row_extraction/__init__.py`
- Create: `experiments/row_extraction/contracts.py`
- Create: `experiments/row_extraction/arms/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/experiments/__init__.py`
- Create: `tests/experiments/row_extraction/__init__.py`
- Create: `tests/experiments/row_extraction/factories.py`
- Create: `tests/experiments/row_extraction/arms/__init__.py`
- Test: `tests/experiments/row_extraction/test_contracts.py`

**Interfaces:**
- Consumes: Pydantic `BaseModel`, `Field`, and Python `Protocol`, `StrEnum`, `Literal`.
- Produces: `BBox`, `DatasetSplit`, `LaneDisposition`, `RowType`, `FieldRole`, `Decision`, `EvidenceAtom`, `ColumnBand`, `FrozenRow`, `GoldField`, `GoldRow`, `OcrReference`, `FieldProposal`, `RowPrediction`, `ArtifactIdentity`, `FeatureSchema`, `FeatureVector`, and `ExperimentArm`.
- Invariant: every `FieldProposal.atom_ids` entry must resolve to an `EvidenceAtom` in the enclosing `RowPrediction.evidence_atoms`; model construction rejects unsupported references.

- [ ] **Step 1: Write failing contract tests**

```python
# tests/experiments/row_extraction/test_contracts.py
import pytest
from pydantic import ValidationError

from experiments.row_extraction.contracts import (
    Decision,
    FieldProposal,
    FieldRole,
    LaneDisposition,
    RowPrediction,
    RowType,
)
from tests.experiments.row_extraction.factories import frozen_row


def test_field_proposal_requires_evidence_atoms() -> None:
    with pytest.raises(ValidationError):
        FieldProposal(role=FieldRole.DESCRIPTION, atom_ids=(), raw_score=0.8)


def test_lane_disposition_vocabulary_is_closed() -> None:
    assert tuple(LaneDisposition) == (
        LaneDisposition.FROZEN_ELIGIBLE,
        LaneDisposition.VALIDATION_STOPPED,
    )


def test_prediction_rejects_duplicate_evidence_atom_ids() -> None:
    row = frozen_row()
    with pytest.raises(ValidationError, match="evidence atom IDs must be unique"):
        RowPrediction(
            experiment_id="control",
            config_id="v1",
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=RowType.PRIMARY_TRANSACTION,
            evidence_atoms=(row.atoms[0], row.atoms[0]),
            proposals=(),
            exact_row_confidence=None,
            decision=Decision.ABSTAIN,
            reasons=("synthetic_duplicate",),
        )


def test_prediction_rejects_proposal_atom_ids_absent_from_evidence() -> None:
    row = frozen_row()
    with pytest.raises(
        ValidationError,
        match="proposal atom IDs must reference prediction evidence",
    ):
        RowPrediction(
            experiment_id="control",
            config_id="v1",
            document_id=row.document_id,
            row_id=row.row_id,
            predicted_type=RowType.PRIMARY_TRANSACTION,
            evidence_atoms=row.atoms,
            proposals=(
                FieldProposal(
                    role=FieldRole.DESCRIPTION,
                    atom_ids=("unsupported-atom",),
                    raw_score=0.8,
                ),
            ),
            exact_row_confidence=None,
            decision=Decision.ABSTAIN,
            reasons=("synthetic_unsupported_proposal",),
        )
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_contracts.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'experiments'`.

- [ ] **Step 3: Implement the closed shared record vocabulary**

```python
# experiments/row_extraction/contracts.py
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

type BBox = tuple[float, float, float, float]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class LaneDisposition(StrEnum):
    FROZEN_ELIGIBLE = "frozen_eligible"
    VALIDATION_STOPPED = "validation_stopped"


class RowType(StrEnum):
    PRIMARY_TRANSACTION = "primary_transaction"
    CONTINUATION = "continuation"
    STRUCTURAL = "structural"
    AMBIGUOUS = "ambiguous"


class FieldRole(StrEnum):
    TRANSACTION_DATE = "transaction_date"
    POSTING_DATE = "posting_date"
    CONVERSION_DATE = "conversion_date"
    DESCRIPTION = "description"
    BILLED_AMOUNT = "billed_amount"
    BILLING_CURRENCY = "billing_currency"
    ORIGINAL_AMOUNT = "original_amount"
    ORIGINAL_CURRENCY = "original_currency"
    KIND = "kind"
    INSTALLMENT = "installment"
    FX_RATE = "fx_rate"
    ANCILLARY = "ancillary"


class Decision(StrEnum):
    ACCEPT = "accept"
    ABSTAIN = "abstain"
    REJECT = "reject"
    IGNORE = "ignore"


class EvidenceAtom(_FrozenModel):
    atom_id: str = Field(min_length=1)
    text: str
    bbox: BBox
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0.0, le=1.0)
    column_index: int | None = Field(default=None, ge=0)


class ColumnBand(_FrozenModel):
    index: int = Field(ge=0)
    role: FieldRole | None = None
    bbox: BBox


class FrozenRow(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    split: DatasetSplit
    source_pdf: Path
    page_number: int = Field(gt=0)
    bbox: BBox
    baseline_type: RowType
    column_bands: tuple[ColumnBand, ...]
    atoms: tuple[EvidenceAtom, ...]
    render_version: str = Field(min_length=1)
    previous_row_id: str | None = None
    next_row_id: str | None = None
    gap_before: float | None = Field(default=None, ge=0.0)
    gap_after: float | None = Field(default=None, ge=0.0)


class GoldField(_FrozenModel):
    role: FieldRole
    canonical_value: str
    atom_ids: tuple[str, ...] = ()
    source_region: BBox | None = None


class GoldRow(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    row_type: RowType
    fields: tuple[GoldField, ...]
    ambiguous: bool = False


class OcrReference(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    role: FieldRole
    verbatim_text: str = Field(min_length=1)
    source_region: BBox


class FieldProposal(_FrozenModel):
    role: FieldRole
    atom_ids: tuple[str, ...] = Field(min_length=1)
    source_region: BBox | None = None
    owner_row_id: str | None = None
    raw_score: float = Field(ge=0.0, le=1.0)


class RowPrediction(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_id: str = Field(min_length=1)
    predicted_type: RowType
    evidence_atoms: tuple[EvidenceAtom, ...]
    proposals: tuple[FieldProposal, ...]
    exact_row_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: Decision
    reasons: tuple[str, ...]

    @model_validator(mode="after")
    def unique_evidence_ids(self) -> RowPrediction:
        ids = tuple(atom.atom_id for atom in self.evidence_atoms)
        if len(ids) != len(set(ids)):
            raise ValueError("prediction evidence atom IDs must be unique")
        return self

    @model_validator(mode="after")
    def proposals_reference_evidence(self) -> RowPrediction:
        evidence_ids = {atom.atom_id for atom in self.evidence_atoms}
        if any(
            atom_id not in evidence_ids
            for proposal in self.proposals
            for atom_id in proposal.atom_ids
        ):
            raise ValueError("proposal atom IDs must reference prediction evidence")
        return self


class ArtifactIdentity(_FrozenModel):
    artifact_type: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = Field(min_length=1)
    byte_size: int = Field(ge=0)


class FeatureSchema(_FrozenModel):
    version: str = Field(min_length=1)
    names: tuple[str, ...]


class FeatureVector(_FrozenModel):
    schema_version: str = Field(min_length=1)
    row_id: str = Field(min_length=1)
    values: tuple[float, ...]


class ExperimentArm(Protocol):
    @property
    def experiment_id(self) -> str: ...

    @property
    def config_id(self) -> str: ...

    def predict(self, row: FrozenRow) -> RowPrediction: ...
```

`GoldField` requires at least one exact same-row support form: one or more frozen atom IDs,
or a finite nonempty `source_region` inside the fixed row. Region-only support is required for
legible printing that the accepted digital/OCR atom stream missed; these cases remain in gold
so recovery experiments are measured instead of silently excluded. When both forms are
present, every declared atom overlaps the region. This changes no prediction contract:
`FieldProposal.atom_ids` remains nonempty and every prediction grounds its value in evidence
atoms produced by that measured arm.

`FieldProposal.owner_row_id=None` canonically means the current `FrozenRow.row_id`. A
continuation that proposes evidence for its fixed predecessor must set `owner_row_id` to
`FrozenRow.previous_row_id`; no other cross-row owner is legal. Shared metrics canonicalize
`None` to the current row before ownership comparison.

Create `tests/experiments/row_extraction/factories.py` with constructors using only synthetic values and a `source_pdf=Path("private/source.pdf")` placeholder path that is never opened.

- [ ] **Step 4: Run the contract tests and static checks**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_contracts.py`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction/contracts.py tests/experiments/row_extraction/factories.py`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit the contracts**

```bash
git add experiments/__init__.py experiments/row_extraction/__init__.py \
  experiments/row_extraction/contracts.py experiments/row_extraction/arms/__init__.py \
  tests/__init__.py \
  tests/experiments/__init__.py \
  tests/experiments/row_extraction/__init__.py \
  tests/experiments/row_extraction/arms/__init__.py \
  tests/experiments/row_extraction/factories.py \
  tests/experiments/row_extraction/test_contracts.py
git commit -m "test: define row experiment contracts"
```

### Task 2: Add canonical streaming codecs and evidence validation

```text
Scope answer: YES
Program component: shared foundation
Measured effect: deterministic, bounded-memory experiment interchange and zero unsupported evidence references
Fixed inputs: Task 1 models and evidence-only proposal rule
Allowed files: codecs, evidence validator, and focused tests
Stop condition: stop if scoring requires loading a corpus-sized result or resolving a value outside the prediction ledger
```

**Files:**
- Create: `experiments/row_extraction/codecs.py`
- Create: `experiments/row_extraction/evidence.py`
- Test: `tests/experiments/row_extraction/test_codecs.py`
- Test: `tests/experiments/row_extraction/test_evidence.py`

**Interfaces:**
- Consumes: any `_FrozenModel` subclass and `RowPrediction` from Task 1.
- Produces: `write_jsonl(path: Path, records: Iterable[BaseModel]) -> ArtifactIdentity`, `read_jsonl(path: Path, model: type[T]) -> Iterator[T]`, `prediction_ledger(prediction: RowPrediction) -> Mapping[str, EvidenceAtom]`, `render_proposal(prediction: RowPrediction, proposal: FieldProposal) -> str`, and `resolve_proposal(prediction: RowPrediction, proposal: FieldProposal) -> ResolvedField`.

- [ ] **Step 1: Write failing canonicalization and missing-evidence tests**

```python
def test_jsonl_round_trip_is_byte_deterministic(tmp_path: Path) -> None:
    row = frozen_row()
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    assert write_jsonl(first, (row,)).sha256 == write_jsonl(second, (row,)).sha256
    assert first.read_bytes() == second.read_bytes()


def test_render_proposal_rejects_missing_atom() -> None:
    prediction = accepted_prediction(atom_ids=("missing",))
    with pytest.raises(EvidenceContractError, match="missing evidence atom"):
        render_proposal(prediction, prediction.proposals[0])
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_codecs.py tests/experiments/row_extraction/test_evidence.py`

Expected: collection fails because `codecs.py` and `evidence.py` do not exist.

- [ ] **Step 3: Implement line-at-a-time canonical JSON and exact rendering**

```python
# experiments/row_extraction/evidence.py
class EvidenceContractError(ValueError):
    pass


def prediction_ledger(prediction: RowPrediction) -> dict[str, EvidenceAtom]:
    return {atom.atom_id: atom for atom in prediction.evidence_atoms}


def render_proposal(prediction: RowPrediction, proposal: FieldProposal) -> str:
    ledger = prediction_ledger(prediction)
    try:
        atoms = tuple(ledger[atom_id] for atom_id in proposal.atom_ids)
    except KeyError as error:
        raise EvidenceContractError("missing evidence atom") from error
    if len(atoms) != len(set(proposal.atom_ids)):
        raise EvidenceContractError("duplicate proposal evidence atom")
    return " ".join(atom.text for atom in atoms)
```

Add immutable `ResolvedField(role, canonical_value, atom_ids)`. `resolve_proposal` first
renders the exact supported atoms, then applies the existing typed date, currency,
installment, and `Decimal` parsers for the proposal role. `FieldRole.KIND` is derived only
from the sign of its supported billed-amount evidence. A nonunique or invalid parse raises a
stable evidence-contract error; it never repairs or guesses a value. Metrics compare gold to
these resolved fields rather than comparing raw joined text directly.

In `codecs.py`, serialize each record with `model_dump_json()` after recursively sorting
dictionary keys through the repository's canonical JSON grammar, write exactly one NFC UTF-8
record plus newline, update SHA-256 incrementally, use a temporary sibling followed by
`Path.replace`, and make `read_jsonl` validate one line at a time.

- [ ] **Step 4: Run focused tests and mypy**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_codecs.py tests/experiments/row_extraction/test_evidence.py`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction/codecs.py experiments/row_extraction/evidence.py`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit the interchange boundary**

```bash
git add experiments/row_extraction/codecs.py experiments/row_extraction/evidence.py \
  tests/experiments/row_extraction/test_codecs.py \
  tests/experiments/row_extraction/test_evidence.py
git commit -m "feat: add canonical row experiment interchange"
```

### Task 3: Prepare fixed rows without changing row detection

```text
Scope answer: YES
Program component: shared foundation
Measured effect: every experiment receives the same accepted-anchor row identity, geometry, columns, and atoms
Fixed inputs: accepted comparison anchor and production discovery summaries
Allowed files: bundle preparation and synthetic bundle tests
Stop condition: stop if preparation needs a new row detector, modifies a row box, or copies source data into tracked fixtures
```

**Files:**
- Create: `experiments/row_extraction/bundle.py`
- Create: `experiments/row_extraction/crops.py`
- Test: `tests/experiments/row_extraction/test_bundle.py`
- Test: `tests/experiments/row_extraction/test_crops.py`

**Interfaces:**
- Consumes: `ccparser.models.StatementResult`, private source path, `DatasetSplit`, and exact discovery/row summaries from the accepted parser.
- Produces: `rows_from_statement(source_pdf: Path, result: StatementResult, split: DatasetSplit) -> tuple[FrozenRow, ...]`, `baseline_predictions_from_statement(rows: Sequence[FrozenRow], result: StatementResult) -> tuple[RowPrediction, ...]`, `CropRecord(document_id: str, row_id: str, row_bbox: BBox, relative_path: str, sha256: str, width: int, height: int)`, `render_reference_crop(row: FrozenRow, private_root: Path) -> CropRecord`, `PreparedBundle(rows: ArtifactIdentity, accepted_predictions: ArtifactIdentity, crop_index: ArtifactIdentity)`, and `prepare_bundle(sources: Iterable[Path], destination: Path, split_by_document: Mapping[str, DatasetSplit]) -> PreparedBundle`.

- [ ] **Step 1: Write a failing fixed-identity projection test**

```python
def test_rows_from_statement_preserves_summary_bbox_and_count() -> None:
    statement = synthetic_statement_result()
    rows = rows_from_statement(
        Path("private/source.pdf"),
        statement,
        DatasetSplit.TRAIN,
    )
    source_rows = tuple(
        row
        for region in statement.discovery.table_regions
        for row in region.rows
    )
    assert tuple(row.bbox for row in rows) == tuple(row.bbox for row in source_rows)
    assert len(rows) == len(source_rows)


def test_accepted_baseline_covers_the_same_fixed_row_universe() -> None:
    statement = synthetic_statement_result()
    rows = rows_from_statement(Path("private/source.pdf"), statement, DatasetSplit.TRAIN)
    predictions = baseline_predictions_from_statement(rows, statement)
    assert tuple((item.document_id, item.row_id) for item in predictions) == tuple(
        (item.document_id, item.row_id) for item in rows
    )
    assert all(item.experiment_id == "accepted-baseline" for item in predictions)


def test_reference_crop_uses_the_exact_fixed_bbox(tmp_path: Path) -> None:
    row = frozen_row(source_pdf=synthetic_pdf(tmp_path))
    record = render_reference_crop(row, tmp_path / "private-crops")
    assert record.row_bbox == row.bbox
    assert record.document_id == row.document_id
    assert record.row_id == row.row_id
```

- [ ] **Step 2: Run the bundle test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_bundle.py`

Expected: collection fails because `bundle.py` does not exist.

- [ ] **Step 3: Implement a lossless accepted-summary projection**

Derive `row_id` from document ID, page number, and the canonical fixed bbox; never use it as
a model feature. Project words and glyph-backed text to deterministic atom IDs, preserve
source/confidence/geometry, project the accepted structural row type and schema bands, and
record only adjacent fixed-row IDs and normalized vertical gaps for continuation ownership.
Derive `baseline_type` only from the accepted row result at the same page/bbox:
`PRIMARY_TRANSACTION` when it contains a transaction, `CONTINUATION` for the accepted
`merged_*_continuation` or `unowned_leading_subordinate_detail_continuation` diagnostics,
`STRUCTURAL` only for `printed_total_row`, and `AMBIGUOUS` otherwise.
`baseline_type` is an observation used by OCR/baseline adapters; learned and deterministic
row-type feature extractors must not consume it. Reject duplicate row IDs,
out-of-page boxes, unknown document splits, or any row-count mismatch. Stream completed rows
through `write_jsonl`; do not retain all statements in memory.

Materialize one accepted-baseline `RowPrediction` for every frozen row at the same time.
Map accepted transaction evidence to exact frozen atoms by page/bbox overlap and the shared
typed resolver; use explicit previous-row ownership for merged continuations. If a baseline
field cannot be uniquely grounded, omit it and record a stable abstention/omission reason
instead of copying an authoritative value without support. The accepted output is a proposal,
not gold. Store this prediction stream separately from `FrozenRow` so no learned lane can use
accepted fields as features.

Also render one unpadded 300-DPI RGB PPM reference crop for every exact fixed bbox. Write it
under the ignored destination with a relative opaque-ID path, stream SHA-256 into a canonical
private crop index, and store the crop recipe in `FrozenRow.render_version`. The crop renderer
may convert page points to pixels but may not expand/move a bbox or include neighboring rows.
Experiment 4 consumes this frozen crop index; experiment 1 rerenders from the same source/bbox
because DPI and raster padding are its controlled variables.

```python
def fixed_row_id(document_id: str, page_number: int, bbox: BBox) -> str:
    payload = json.dumps(
        [document_id, page_number, *bbox],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 4: Run the bundle and existing parser-summary tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_bundle.py tests/test_parser.py tests/test_summary.py`

Expected: PASS.

- [ ] **Step 5: Commit fixed-row preparation**

```bash
git add experiments/row_extraction/bundle.py experiments/row_extraction/crops.py \
  tests/experiments/row_extraction/test_bundle.py \
  tests/experiments/row_extraction/test_crops.py
git commit -m "feat: prepare frozen transaction rows"
```

### Task 4: Validate reviewed gold annotations

```text
Scope answer: YES
Program component: shared foundation
Measured effect: exact field and row metrics use reviewed source evidence rather than accepted-anchor output as truth
Fixed inputs: frozen rows and charter annotation semantics
Allowed files: annotation validator, handbook, and synthetic tests
Stop condition: stop if an ambiguous source is coerced into a unique label or private values would enter Git
```

**Files:**
- Create: `experiments/row_extraction/annotations.py`
- Create: `docs/experiments/row-extraction-annotation-handbook.md`
- Test: `tests/experiments/row_extraction/test_annotations.py`

**Interfaces:**
- Consumes: iterables of `FrozenRow`, `GoldRow`, and optional `OcrReference` records.
- Produces: `validate_annotations(rows: Iterable[FrozenRow], labels: Iterable[GoldRow], ocr_references: Iterable[OcrReference] = ()) -> AnnotationSummary` and stable violations with document/row IDs but no field values.

- [ ] **Step 1: Write failing evidence-ownership and ambiguity tests**

```python
def test_annotation_rejects_unknown_atom() -> None:
    row = frozen_row()
    gold = gold_row(atom_ids=("unknown",))
    with pytest.raises(AnnotationError, match="gold atom is not present in frozen row"):
        validate_annotations((row,), (gold,))


def test_ambiguous_gold_cannot_contain_unique_fields() -> None:
    row = frozen_row()
    gold = gold_row(ambiguous=True)
    with pytest.raises(AnnotationError, match="ambiguous row cannot assert unique fields"):
        validate_annotations((row,), (gold,))
```

- [ ] **Step 2: Run the test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_annotations.py`

Expected: collection fails because `annotations.py` does not exist.

- [ ] **Step 3: Implement closed validation and the annotation handbook**

Validate one label per frozen row; exact document/row identity; field-role uniqueness;
atom-or-region support and nonoverlap; `Decimal` parsing for amount roles; existing date and
currency parsers for typed roles; paired original amount/currency; primary-versus-
continuation rules; and explicit ambiguity. The handbook defines these decisions with
synthetic merchant, amount, date, currency, continuation, structural, and ambiguous examples.
It states that accepted output is a proposal, not gold.

An atom-supported field has nonempty, unique, source-ordered frozen atom IDs. A region-supported
field has a finite nonempty image region wholly inside the exact fixed row. At least one form is
mandatory. If both are supplied, every atom overlaps the region. Independent field supports
cannot overlap; billed amount and kind are the sole exception and use exactly the same atom
tuple and region. Region-only support remains valid for a legible field absent from the frozen
atoms, including its optional matching `OcrReference`.

An `OcrReference` is optional and records a human-reviewed verbatim source transcription plus
the exact source region for a field whose printing is legible enough to score recognition.
Validate its row/role/region identity separately from canonical field semantics. Never infer a
reference from accepted OCR text, and never coerce an illegible region into a transcript.

- [ ] **Step 4: Run annotation, money, and date tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_annotations.py tests/test_normalize.py tests/test_normalization_dates.py`

Expected: PASS.

- [ ] **Step 5: Commit annotation semantics**

```bash
git add experiments/row_extraction/annotations.py \
  docs/experiments/row-extraction-annotation-handbook.md \
  tests/experiments/row_extraction/test_annotations.py
git commit -m "feat: validate reviewed row annotations"
```

### Task 5: Freeze grouped document partitions and folds

```text
Scope answer: YES
Program component: shared foundation
Measured effect: prevents row, page, revision, and layout-family leakage across train, validation, and locked test
Fixed inputs: opaque document groups and target 60/20/20 ratios
Allowed files: split module and tests
Stop condition: stop if a split requires filename, merchant, date, amount, or total content
```

**Files:**
- Create: `experiments/row_extraction/split.py`
- Test: `tests/experiments/row_extraction/test_split.py`

**Interfaces:**
- Consumes: `DocumentGroup(document_ids: frozenset[str], duplicate_group: str, layout_group: str, stratum: str)` records and a fixed seed string.
- Produces: `SplitManifest`, `assign_splits(groups: Sequence[DocumentGroup], seed: str) -> SplitManifest`, `validate_split(rows: Sequence[FrozenRow], manifest: SplitManifest) -> None`, `Fold`, and `grouped_folds(rows: Sequence[FrozenRow], manifest: SplitManifest, fold_count: int) -> tuple[Fold, ...]`.

`SplitManifest` freezes both split membership and the connected duplicate/layout atomic unit
for every opaque document ID. The manifest parameter is mandatory for grouped folds: a
`FrozenRow` deliberately contains no duplicate/layout family identifier, so a rows-only fold
API cannot preserve those groups without hidden state or forbidden inference.

- [ ] **Step 1: Write failing group-leakage tests**

```python
def test_assign_splits_keeps_duplicate_and_layout_groups_together() -> None:
    groups = synthetic_document_groups()
    manifest = assign_splits(groups, seed="row-extraction-v1")
    for group in groups:
        assert len({manifest.split_for(value) for value in group.document_ids}) == 1


def test_grouped_folds_never_share_document_ids() -> None:
    folds = grouped_folds(tuple(training_rows()), manifest, fold_count=3)
    assert all(
        fold.train_document_ids.isdisjoint(fold.validation_document_ids)
        for fold in folds
    )
```

- [ ] **Step 2: Run the test to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_split.py`

Expected: collection fails because `split.py` does not exist.

- [ ] **Step 3: Implement deterministic group assignment**

Assign connected duplicate/layout groups as atomic units. Order units by
`sha256(seed + canonical_group_ids)` and greedily minimize absolute stratum and total-ratio
deviation without inspecting field values. Freeze explicit document membership in a private
manifest. `grouped_folds` operates only on training documents and uses the atomic units frozen
in that explicit manifest. It rejects rows absent from the manifest, non-training membership,
and any manifest unit whose documents would be only partially represented.

- [ ] **Step 4: Run split tests twice**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_split.py`

Expected: PASS with identical parameterized assignments on repeated calls.

- [ ] **Step 5: Commit split isolation**

```bash
git add experiments/row_extraction/split.py \
  tests/experiments/row_extraction/test_split.py
git commit -m "feat: freeze grouped row experiment splits"
```

### Task 6: Implement shared exact and selective metrics

```text
Scope answer: YES
Program component: shared foundation
Measured effect: all baselines and experiments are compared with identical exactness, omission, hallucination, OCR, calibration, and abstention definitions
Fixed inputs: frozen rows, reviewed GoldRow records, and self-contained RowPrediction evidence ledgers
Allowed files: metrics module and tests
Stop condition: stop if a metric uses reconciliation as ground truth or silently excludes abstentions/errors
```

**Files:**
- Create: `experiments/row_extraction/metrics.py`
- Test: `tests/experiments/row_extraction/test_metrics.py`

**Interfaces:**
- Consumes: sequences of `FrozenRow`, `GoldRow`, and `RowPrediction` joined by document/row IDs, plus optional reviewed `OcrReference` records. Frozen rows are mandatory ownership and region context, not a feature or alternate truth source.
- Produces: immutable `FieldMetric`, `RowTypeMetric`, `ConfusionCell`, `CalibrationBin`, `RiskCoveragePoint`, `RiskTargetCoverage`, `MetricReport`, `score_predictions(rows: Sequence[FrozenRow], gold: Sequence[GoldRow], predictions: Sequence[RowPrediction], ocr_references: Sequence[OcrReference] = ()) -> MetricReport`, `character_error_rate`, and `word_error_rate`.

- [ ] **Step 1: Write failing exactness, omission, hallucination, and risk tests**

```python
def test_score_predictions_separates_omission_from_hallucination() -> None:
    report = score_predictions(
        rows=(frozen_row(row_id="row-1"), frozen_row(row_id="row-2")),
        gold=(gold_row_with_description(), gold_row_without_description()),
        predictions=(abstained_prediction(), description_prediction_for_second_row()),
    )
    merchant = report.fields[FieldRole.DESCRIPTION]
    assert merchant.omissions == 1
    assert merchant.hallucinations == 1


def test_risk_coverage_counts_wrong_accepted_rows() -> None:
    points = risk_coverage(
        outcomes=((0.9, True), (0.8, False), (0.2, True)),
    )
    assert points[1].coverage == Decimal("0.6666666666666666666666666667")
    assert points[1].selective_risk == Decimal("0.5")
```

- [ ] **Step 2: Run the metric tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_metrics.py`

Expected: collection fails because `metrics.py` does not exist.

- [ ] **Step 3: Implement exact joined scoring with `Decimal` ratios**

Implement these exact public result schemas so every lane and the comparison package consumes
one vocabulary:

```python
class FieldMetric(_FrozenModel):
    role: FieldRole
    eligible_rows: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    normalized_matches: int = Field(ge=0)
    omissions: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    exact_rate: Decimal
    normalized_rate: Decimal
    omission_rate: Decimal
    hallucination_rate: Decimal


class RowTypeMetric(_FrozenModel):
    row_type: RowType
    precision: Decimal
    recall: Decimal
    f1: Decimal
    support: int = Field(ge=0)


class ConfusionCell(_FrozenModel):
    gold: RowType
    predicted: RowType
    count: int = Field(ge=0)


class CalibrationBin(_FrozenModel):
    lower: Decimal
    upper: Decimal
    count: int = Field(ge=0)
    mean_confidence: Decimal | None
    empirical_accuracy: Decimal | None


class RiskCoveragePoint(_FrozenModel):
    threshold: Decimal
    coverage: Decimal
    selective_risk: Decimal
    accepted_rows: int = Field(ge=0)


class RiskTargetCoverage(_FrozenModel):
    target_risk: Decimal
    coverage: Decimal


class MetricReport(_FrozenModel):
    row_count: int = Field(gt=0)
    exact_rows: int = Field(ge=0)
    exact_row_rate: Decimal
    row_type_correct: int = Field(ge=0)
    row_type_accuracy: Decimal
    row_type_macro_f1: Decimal
    row_types: tuple[RowTypeMetric, ...]
    row_type_confusion: tuple[ConfusionCell, ...]
    fields: Mapping[FieldRole, FieldMetric]
    accepted_rows: int = Field(ge=0)
    abstained_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    ignored_rows: int = Field(ge=0)
    unsupported_evidence: int = Field(ge=0)
    ownership_collisions: int = Field(ge=0)
    ocr_cer: Decimal | None
    ocr_wer: Decimal | None
    calibration_bins: tuple[CalibrationBin, ...]
    brier_score: Decimal | None
    log_loss: Decimal | None
    expected_calibration_error: Decimal | None
    risk_coverage: tuple[RiskCoveragePoint, ...]
    area_under_risk_coverage: Decimal | None
    coverage_at_risk: tuple[RiskTargetCoverage, ...]
```

Join the frozen rows bijectively with gold and predictions. Canonicalize proposal owner `None`
to the current row. For a reviewed continuation, the only correct owner is its fixed
`previous_row_id`; for every other reviewed row type, the only correct owner is the current
row. Count a wrong singleton owner or conflicting duplicate owners as one row-level ownership
collision and make the complete-row event false. Never infer adjacency without the frozen row.

Normalize merchant comparison under one versioned NFC/case/space policy while retaining raw
exact match separately. Use edit distance for CER/WER. Count every eligible gold row in
coverage. Treat accepted wrong/extra fields as hallucinations and absent expected fields as
omissions. Build fixed predeclared calibration bins, Brier/log loss, and risk-coverage points
from exact-row outcomes. Reject duplicate/missing prediction IDs instead of dropping them.
Reviewed ambiguous rows remain in row, calibration, and coverage denominators but can never be
a complete exact-row success because they have no unique gold transaction value.
Compute CER/WER only against supplied verbatim `OcrReference` records. Every supplied valid
reviewed region is eligible: derive its hypothesis directly from the prediction evidence atoms
overlapping that exact region in ledger order, and use an empty hypothesis when recognition
produced no regional atoms. Do not condition OCR scoring on a successful or unique field
proposal. Report `None` only when no reviewed references were supplied, never score against
accepted OCR or canonicalized date/amount values.

- [ ] **Step 4: Run focused metrics and Decimal tests**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_metrics.py tests/test_decimal_math.py`

Expected: PASS.

- [ ] **Step 5: Commit common metrics**

```bash
git add experiments/row_extraction/metrics.py \
  tests/experiments/row_extraction/test_metrics.py
git commit -m "feat: score exact row extraction experiments"
```

### Task 7: Add the streaming runner, accepted baseline, and privacy-safe report

```text
Scope answer: YES
Program component: shared foundation and baselines
Measured effect: identical execution, same-run phase-separated resource measurement, evidence validation, deterministic output, and aggregate reporting for every arm
Fixed inputs: FrozenRow stream, measured-arm factory protocol, common metrics, identity-bound resource specification, optional preparation measurements, and typed page-evidence artifacts
Allowed files: runner, baseline adapter, report, CLI, and focused tests
Stop condition: stop if the runner exposes private row contents or lets an arm mutate shared inputs
```

**Files:**
- Create: `experiments/row_extraction/runner.py`
- Create: `experiments/row_extraction/baselines.py`
- Create: `experiments/row_extraction/report.py`
- Create: `experiments/row_extraction/cli.py`
- Test: `tests/experiments/row_extraction/test_runner.py`
- Test: `tests/experiments/row_extraction/test_baselines.py`
- Test: `tests/experiments/row_extraction/test_report.py`
- Test: `tests/experiments/row_extraction/test_cli.py`

**Interfaces:**
- Consumes: a nonempty `Iterable[FrozenRow]`, `MeasuredArmFactory`, one-shot two-phase `PredictionSink`, an identity-bound `ResourceSpec`, optional matching `PreparationMeasurements`, gold records, optional reviewed `OcrReference` records, typed page evidence, and artifact identities.
- Produces: `InventoryRoots`, `ResourceInventoryEntry`, `ResourceInventory`, `build_resource_inventory(...)`, `ResourceSpec`, `PreparationMeasurements`, `RunMeasurements`, `MeasuredArmFactory`, `PredictionSink`, `JsonlPredictionSink`, `run_arm(rows: Iterable[FrozenRow], factory: MeasuredArmFactory, sink: PredictionSink, resource_spec: ResourceSpec, preparation: PreparationMeasurements | None = None) -> RunMeasurements`, `PageWord`, `PageEvidenceRecord`, baseline arm factories, `assert_repeated_output(first: Path, second: Path) -> None`, `ReportContext`, `privacy_safe_report(metrics: MetricReport, run: RunMeasurements, context: ReportContext) -> dict[str, object]`, and Typer commands `prepare`, `prepare-inventory`, `prepare-page-evidence`, `prepare-run-spec`, `validate`, `run-baseline`, and `score`.

The factory and static resource specification are mandatory. `ExperimentArm` exposes only IDs
and `predict`, so an already-constructed arm cannot truthfully yield isolated cold start or
bind its artifacts, rows, cache policy, and footprint inventories. `run_arm` constructs and
executes the arm once inside the measured process, then publishes that same execution's
predictions and measurements together. A formal repeat uses a second fresh process, factory,
cache root, preparation record, and sink. Zero is a real measured value, not a placeholder for
unavailable data.

- [ ] **Step 1: Write failing identity, immutability, and privacy tests**

```python
def test_runner_rejects_prediction_for_another_row(tmp_path: Path) -> None:
    sink = JsonlPredictionSink(tmp_path / "predictions.jsonl")
    with pytest.raises(RunContractError, match="prediction identity mismatch"):
        run_arm((frozen_row(),), WrongIdentityArmFactory(), sink, synthetic_resource_spec())


def test_privacy_safe_report_contains_no_row_or_field_values() -> None:
    report = privacy_safe_report(metric_report(), run_measurements(), report_context())
    serialized = json.dumps(report, sort_keys=True)
    assert "row_id" not in serialized
    assert "canonical_value" not in serialized
    assert "source_pdf" not in serialized


def test_forced_page_ocr_is_clipped_to_the_fixed_row_and_bands() -> None:
    row = frozen_row()
    arm = ForcedPageOcrArm((row,), synthetic_forced_page_evidence(), artifact_identity())
    prediction = arm.predict(row)
    assert prediction.experiment_id == "forced-page-ocr"
    assert prediction.row_id == row.row_id
    assert all(
        row.bbox[0] <= atom.bbox[0] <= atom.bbox[2] <= row.bbox[2]
        and row.bbox[1] <= atom.bbox[1] <= atom.bbox[3] <= row.bbox[3]
        for atom in prediction.evidence_atoms
    )
```

The focused RED suite also covers empty and duplicate rows, unstable arm IDs, mismatched
row/split/arm/runtime/model/dependency/cache identities, reordered predictions, input mutation,
fresh factory construction, exact subprocess counts, one-shot sink publication
and abort cleanup, nearest-rank quantiles, and a nonadvancing clock. Baseline tests cover an
accepted-prediction bijection; missing/duplicate/extra/wrong-mode page records; noncontiguous
word ordinals; wrong page identity; half-open boundary assignment; strict unique overlap
assignment and tied-overlap omission;
both-axis clipping; unique atom ownership; every row-type resolver outcome; and value-free
errors. Report and CLI tests cover every ID mismatch, absence of hashes/paths/values, required
output nonexistence/ignored-root checks, optional OCR references, and traceback-cause
sanitization. Inventory tests cover empty-model roots, forbidden empty dependencies, symlinks,
overlapping roots/inodes/categories, changed stat/hash values, and canonical ordering.

- [ ] **Step 2: Run runner/report tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_runner.py tests/experiments/row_extraction/test_baselines.py tests/experiments/row_extraction/test_report.py tests/experiments/row_extraction/test_cli.py`

Expected: collection fails because runner/report/CLI modules do not exist.

- [ ] **Step 3: Implement bounded execution and accepted baseline projection**

Use these exact public resource schemas:

```python
class InventoryRoots(_FrozenModel):
    version: Literal["row-resource-roots-v1"]
    category: Literal["model", "dependency"]
    roots: tuple[Path, ...]


class ResourceInventoryEntry(_FrozenModel):
    category: Literal["model", "dependency", "cache"]
    resolved_path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    device: int = Field(ge=0)
    inode: int = Field(gt=0)


class ResourceInventory(_FrozenModel):
    version: Literal["row-resource-inventory-v1"]
    entries: tuple[ResourceInventoryEntry, ...]


class ResourceSpec(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    expected_row_count: int = Field(gt=0)
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: Literal["end-to-end-method", "materialized-adapter"]
    worker_count: Literal[1]
    runtime_identity: ArtifactIdentity
    arm_manifest_identity: ArtifactIdentity
    private_root: Path
    model_inventory_path: Path
    model_inventory_identity: ArtifactIdentity
    dependency_inventory_path: Path
    dependency_inventory_identity: ArtifactIdentity
    cache_root: Path
    resource_inventory_output: Path


class PreparationMeasurements(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    row_count: int = Field(gt=0)
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: Literal["end-to-end-method"]
    preparation_ns: int = Field(gt=0)
    peak_rss_bytes: int = Field(gt=0)
    subprocess_count: int = Field(ge=0)
    worker_count: Literal[1]
    runtime_identity: ArtifactIdentity
    arm_manifest_identity: ArtifactIdentity
    resource_inventory_path: Path
    resource_inventory_identity: ArtifactIdentity


class RunMeasurements(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    row_sequence_identity: ArtifactIdentity
    split: DatasetSplit
    cache_policy: Literal["new-empty-v1"]
    resource_basis: Literal["end-to-end-method", "materialized-adapter"]
    arm_manifest_identity: ArtifactIdentity
    row_count: int = Field(gt=0)
    total_ns: int = Field(gt=0)
    p50_ns: int = Field(gt=0)
    p95_ns: int = Field(gt=0)
    preparation_ns: int = Field(ge=0)
    end_to_end_ns: int = Field(gt=0)
    cold_start_ns: int = Field(gt=0)
    throughput_rows_per_second: Decimal = Field(gt=0)
    peak_rss_bytes: int = Field(gt=0)
    model_bytes: int = Field(ge=0)
    dependency_bytes: int = Field(gt=0)
    cache_bytes: int = Field(ge=0)
    subprocess_count: int = Field(ge=0)
    worker_count: Literal[1]
    measurement_protocol: Literal["row-resource-measurement-v1"]
    runtime_identity: ArtifactIdentity
    model_inventory_identity: ArtifactIdentity
    dependency_inventory_identity: ArtifactIdentity
    resource_inventory_identity: ArtifactIdentity
    predictions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportContext(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    measurement_protocol: Literal["row-resource-measurement-v1"]
    runtime_identity: ArtifactIdentity
    python_version: str = Field(min_length=1)
    public_runtime_versions: tuple[tuple[str, str], ...]
```

`ResourceSpec` is static input, never an observation from another run. It pins the exact ordered
row sequence/split, new-empty-cache policy, worker/runtime/arm identities, input model and
dependency inventory identities, private root, new cache root, and new combined-inventory
output. `MeasuredArmFactory` exposes stable `experiment_id`, `config_id`,
`row_sequence_identity`, `expected_row_count`, `split`, `arm_manifest_identity`,
`runtime_identity`, `model_inventory_identity`,
`dependency_inventory_identity`, `cache_root`, `resource_basis`, `worker_count`,
`subprocess_count`, and
`build() -> ExperimentArm`. Every static property must equal `ResourceSpec` before and after
execution. Its subprocess count is zero before build and counts every external process launched
during construction or prediction; the lane must inject the counter at its launcher boundary.

The row-sequence identity has artifact type `frozen-row-sequence`, version
`canonical-jsonl-v1`, and hashes the exact canonical records in run order after split filtering;
its byte size and the spec's positive expected row count are verified while streaming. Every
row must declare the spec's one split.

`PreparationMeasurements` exists only when recognition/evidence is computed before the fixed-
row arm, currently the conditional and forced page baselines. It is produced in a fresh process
with a new empty cache, identifies the exact resulting page-evidence artifact as its arm
manifest, and is consumed by exactly one matching prediction run. The repeat creates a second
preparation record from another empty cache. Other arms pass no preparation record and receive
a measured `preparation_ns == 0`; model training is offline experiment development, not
inference preparation and is never added to end-to-end latency.

Before union, the runner requires the preparation manifest's model and dependency entry sets
to equal the spec-pinned model and dependency manifests exactly; only cache-category entries
may be phase-specific. Preparation experiment/config/row/split/cache/runtime/worker/arm
identities must also equal the spec and factory.

`run_arm` starts cold timing before `factory.build()` and stops it after the first validated
prediction. Fixed-row `total_ns` starts at the same point and covers factory construction, all
prediction/validation, and sink staging, but excludes the independent preparation phase. It sets
`end_to_end_ns = preparation_ns + total_ns`. It verifies every spec/preparation/factory/row
identity before publication and computes all resource observations from this same execution.
Formal comparisons report preparation, fixed-row execution, and end-to-end separately.

Every measurement command runs in a fresh isolated Linux worker. `peak_rss_bytes` has one exact
cross-lane definition: for each phase, sum fresh-worker `RUSAGE_SELF.ru_maxrss` and waited child
`RUSAGE_CHILDREN.ru_maxrss` after conversion from KiB to bytes, then take the maximum across
preparation and fixed-row phases. This is a conservative process-family high-water bound rather
than a claim of simultaneous sampled RSS. `subprocess_count` sums exact injected launcher
counts across the phases. Any launcher that cannot provide an exact count is a stop condition.

The private footprint manifest is canonical, pinned by `resource_inventory_identity`, and
overlap-rejecting. Each entry records one category, resolved local path, SHA-256, byte size,
device, and inode; the manifest and its identity stay ignored and never enter reports. The
entries are sorted by category then resolved path then SHA-256, and recorded totals must be
recomputed from that exact manifest before every run. All spec/inventory/cache/output paths
are absolute, resolve beneath `private_root`, and are ignored by Git; input documents may
instead reside outside the worktree. Symlinks, non-regular files, and changed stat/hash values
fail closed.
Every inventory identity has artifact type `resource-inventory` and version
`row-resource-inventory-v1`; identities of another type/version fail closed.
`model_bytes` sums recognizer or
learned weight/calibrator artifacts required by the locked arm, including configured
Tesseract traineddata; `dependency_bytes` sums locked executable/library/environment artifacts
but excludes model, input, output, and cache entries; and `cache_bytes` sums reusable derived
evidence/cache artifacts created beneath the new run cache root, including the prepared page
evidence for page baselines. Every inventory entry is a resolved regular file with a unique
device/inode identity; duplicates inside one manifest or across categories fail closed. When
the same model/dependency entry appears identically in preparation and run manifests, the
combined union counts it once; any metadata/category disagreement fails closed. An accepted baseline
has measured `model_bytes == 0` because it has no recognizer or learned model, while zero in any
other category is permitted only when the enumerated inventory is genuinely empty.

`build_resource_inventory(roots: InventoryRoots) -> ResourceInventory` accepts only explicit
absolute regular-file or directory roots from an ignored private roots manifest. It recursively
enumerates directory roots without following symlinks, rejects overlapping roots and duplicate
device/inode identities, and emits sorted entries in the one declared category. An empty roots
tuple is the only valid way to declare an empty model inventory. No glob, environment search,
package-manager query, or filename inference may silently expand the footprint.

`PredictionSink` is one-shot and two-phase: `stage(predictions: Iterable[RowPrediction]) ->
ArtifactIdentity` writes only a sink-owned staging artifact, `commit() -> ArtifactIdentity`
atomically publishes it after all measurements validate, and `abort() -> None` removes both
staging and any sink-owned finalized target. `JsonlPredictionSink` requires a nonexistent
target and delegates canonical record bytes to the shared JSONL codec. It cannot be reused
after commit or abort. On any row/arm/sink/resource/clock failure, `run_arm` calls `abort` and
removes its uncommitted combined resource inventory. `predictions_sha256` is exactly the staged
and committed artifact identity.

The runner rejects an empty run, duplicate input row identities, unstable arm IDs, prediction
identity or experiment/config mismatch, missing/extra/reordered predictions, non-self-contained
proposal evidence, and any before/after canonical row snapshot difference. It never deep-
compares the arm because legitimate measurement counters and caches may change. Measure each
row with `perf_counter_ns`; p50/p95 are deterministic nearest-rank quantiles over per-row
prediction-plus-validation time. Throughput divides the nonempty row count by `total_ns` using
`Decimal` and fails if the clock does not advance. Repeats use newly constructed arms,
independent sinks and caches, and identical config/runtime/worker identities.

Use these typed baseline evidence contracts:

```python
class PageWord(_FrozenModel):
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    bbox: BBox
    source: Literal["digital", "ocr"]
    confidence: float = Field(ge=0.0, le=1.0)


class PageEvidenceRecord(_FrozenModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(gt=0)
    page_bbox: BBox
    mode: Literal["conditional-page-ocr", "forced-page-ocr"]
    evidence_version: Literal["fixed-page-evidence-v1"]
    config_id: str = Field(min_length=1)
    runtime_identity: ArtifactIdentity
    words: tuple[PageWord, ...]
```

Ordinals are unique and contiguous in provider order. Page bboxes and words use rotated,
top-left display points. Evidence streams contain exactly one record for every document/page
that owns a frozen row, no extra page, and are pinned by the JSONL `ArtifactIdentity` supplied
to the arm. `prepare-page-evidence` creates conditional records from the ordinary conditional
page evidence provider and forced records by running whole-page Tesseract unconditionally;
both use new empty cache roots for formal preparation measurement. The command writes the
page-evidence JSONL, its matching private `PreparationMeasurements`, and no text to stdout.
The preparation adapter counts one version launch for the first OCR cache-key request, one
launch for every uncached currency-symbol request, and the exact fixed recognition-pass matrix
for every uncached page request; it verifies the corresponding new cache artifacts. Any launch
or cache mismatch fails instead of estimating a count.

All page arms receive the complete frozen-row sequence, the complete typed page stream, and
its expected artifact identity. Candidate rows contain the word center under half-open
right/bottom bounds. Zero candidates are ignored; one is assigned; for multiple candidates,
only a strict unique maximum 2-D word/row intersection is assigned and tied maxima are ignored.
Clip an eligible word bbox to the fixed row, then find candidate column bands by the same
half-open x-center rule. Zero candidates are ignored; one is assigned; for multiple candidates,
only a strict unique maximum horizontal word/band intersection is assigned and tied maxima are
ignored. This local omission policy preserves unique ownership without aborting the complete
control or using row order, identifiers, or extracted values as tie-breakers. Atom IDs hash the
page-evidence
version/config, row ID, word ordinal, text, clipped
bbox, source, and confidence. No word can appear in two predictions. Neither page arm detects,
moves, merges, or splits a row or column.

`AcceptedBaselineArm(rows, accepted_predictions, artifact_identity)` consumes and verifies the
complete already-materialized accepted-prediction stream from `prepare_bundle`. Prediction
identities must be globally unique, and the split-filtered fixed rows must have an exact
bijection with their selected subset; verified predictions for other splits are ignored only
after the complete stream identity is checked. The CLI additionally validates the complete
bundle row/prediction bijection before split selection. The arm returns the selected immutable
projections without consulting gold, while `arm_manifest_identity` remains the identity of the
complete accepted artifact named by Task 8.
`ConditionalPageOcrArm` and `ForcedPageOcrArm` share one deterministic page-word-to-band field
resolver and copy the accepted baseline row type only as fixed baseline context. A structural
row emits `IGNORE` with no proposals; an ambiguous row emits `ABSTAIN` with no proposals. For
a primary or continuation row, collect assigned atoms in canonical word order for every
nonempty fixed band whose role is not `None`, emit at most one proposal per role, and preserve
omissions when a band has no atom. Two nonempty bands claiming the same role, a continuation
without its fixed previous row, or any proposal that fails `resolve_proposal` makes the whole
row `ABSTAIN` with no proposals. Otherwise, a row with at least one valid proposal is `ACCEPT`
and a row with none is `ABSTAIN`; every continuation proposal uses exactly
`FrozenRow.previous_row_id`. Page baselines are uncalibrated, so `exact_row_confidence` is
`None`, and all decisions use only stable value-free reason codes. Their public experiment IDs
are exactly `conditional-page-ocr` and `forced-page-ocr`; config IDs include evidence/config
versions.

`AcceptedBaselineArmFactory`, `ConditionalPageOcrArmFactory`, and
`ForcedPageOcrArmFactory` each expose the exact input artifact as `arm_manifest_identity`,
construct a fresh arm, and report zero fixed-row subprocesses. Page OCR subprocesses belong to
their matching preparation records; counting them again in the geometry/field adapter is
forbidden.

The accepted control is an accuracy anchor over already-materialized production predictions;
its measured run is explicitly `resource_basis="materialized-adapter"`, has no preparation
record, and reports only replay/validation/publication cost. It must never be described as the
accepted production extractor's latency, memory, or footprint and is excluded from resource
Pareto dominance. Conditional/forced page baselines and all four experiment lanes use
`resource_basis="end-to-end-method"` and remain resource-comparable under the declared phase
boundaries.

`privacy_safe_report` validates matching experiment/config/protocol/runtime identities and
requires sorted, unique public runtime-version names. It includes only
aggregate counts, ratios, the split, explicit resource basis, phase-separated resource measures,
experiment/config IDs, and public runtime versions. It never includes artifact hashes, paths,
row/atom IDs, field values,
OCR text, labels, or financial data. Document-macro and stratified slice reporting remain owned
by the central comparison package; no lane may claim the foundation enforced a slice threshold.

The CLI has these exact explicit path shapes:

- `prepare --private-root DIR --documents DIR --split-manifest FILE --output-dir NEW_DIR` creates
  `rows.jsonl`, `accepted_predictions.jsonl`, and `crop_index.jsonl` beneath `NEW_DIR`, plus
  the canonical sidecars `rows.identity.json`, `accepted_predictions.identity.json`, and
  `crop_index.identity.json`.
- `prepare-inventory --private-root DIR --roots FILE --output FILE --identity-output FILE`
  validates `InventoryRoots`, writes its canonical model or dependency inventory and identity,
  and prints no paths or hashes.
- `prepare-page-evidence --private-root DIR --rows FILE --split train|validation
  --mode conditional-page-ocr|forced-page-ocr
  --runtime-identity FILE --cache-dir NEW_DIR --output FILE --identity-output FILE
  --model-inventory FILE --dependency-inventory FILE --inventory-output FILE
  --preparation-output FILE` creates a pinned page stream, its canonical identity sidecar, its
  private canonical resource inventory, and its isolated preparation record. It requires
  `output` and `identity-output` beneath the new `cache-dir`, so prepared evidence is included
  in cache bytes. This foundation command refuses `test`; the central comparison invokes the
  same library operation only after its locked-access gate.
- `prepare-run-spec --private-root DIR --rows FILE --split train|validation
  --mode accepted-baseline|conditional-page-ocr|forced-page-ocr
  --arm-manifest-identity FILE --runtime-identity FILE --model-inventory FILE
  --dependency-inventory FILE --cache-root NEW_DIR --inventory-output FILE --output FILE`
  computes the exact split-filtered row-sequence identity and writes static `ResourceSpec`.
  It fixes accepted mode to `materialized-adapter` and both page modes to
  `end-to-end-method`; callers cannot override the basis.
  This foundation command refuses `test`; the central comparison constructs the same typed
  spec only after its locked-access gate.
- `validate --private-root DIR --rows FILE --labels FILE [--ocr-references FILE]` validates
  annotations.
- `run-baseline --private-root DIR
  --mode accepted-baseline|conditional-page-ocr|forced-page-ocr --rows FILE --split
  train|validation --baseline-input FILE --baseline-identity FILE --resource-spec FILE
  [--preparation FILE] --predictions-output FILE --run-output FILE` runs exactly one measured
  arm. Page modes require their matching `PreparationMeasurements`; accepted mode forbids it.
  Page modes consume `PageEvidenceRecord`, accepted mode consumes `RowPrediction`, and this
  foundation command refuses `test`.
- `score --private-root DIR --rows FILE --labels FILE --predictions FILE
  [--ocr-references FILE]
  --context FILE --run FILE --output FILE` validates annotations, calls the corrected shared
  scorer, and writes the privacy-safe report.

Every output/cache directory must be new and beneath an explicitly configured ignored private
root. Inputs containing document or derived financial data must be ignored or outside the Git
worktree; merely being currently untracked is insufficient. Catch internal annotation/scoring
exceptions before Typer renders them because internal messages can include private IDs. CLI
stdout/stderr contain only stable aggregate codes/counts, never chained exception payloads.
When OCR references are omitted, CER/WER remain `None`.

- [ ] **Step 4: Run all foundation tests and mypy**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction`

Expected: PASS.

Run: `/root/creditcard/.venv/bin/mypy experiments/row_extraction`

Expected: `Success: no issues found`.

- [ ] **Step 5: Commit the common runner**

```bash
git add experiments/row_extraction/runner.py \
  experiments/row_extraction/baselines.py experiments/row_extraction/report.py \
  experiments/row_extraction/cli.py \
  tests/experiments/row_extraction/test_runner.py \
  tests/experiments/row_extraction/test_baselines.py \
  tests/experiments/row_extraction/test_report.py \
  tests/experiments/row_extraction/test_cli.py
git commit -m "feat: run frozen row extraction arms"
```

### Task 8: Freeze and document the foundation handoff

```text
Scope answer: YES
Program component: shared foundation
Measured effect: all four experiment worktrees start from one reviewed contract and reproducible private bundle/split/label baseline
Fixed inputs: completed Tasks 1-7 and authoritative charter
Allowed files: foundation runbook plus verification-only commands
Stop condition: stop if private preparation fails, labels remain unreviewed, split membership changes, or tracked verification regresses
```

**Files:**
- Create: `experiments/row_extraction/grouping.py`
- Create: `experiments/row_extraction/runtime.py`
- Create: `experiments/row_extraction/foundation_admin.py`
- Create: `tests/experiments/row_extraction/test_grouping.py`
- Create: `tests/experiments/row_extraction/test_runtime.py`
- Create: `tests/experiments/row_extraction/test_foundation_admin.py`
- Create: `docs/experiments/row-extraction-foundation-runbook.md`
- Test: all foundation and repository tests.

**Interfaces:**
- Consumes: accepted discovery geometry, the existing `ToolchainInspector`,
  `experiments.row_extraction.cli` commands, and ignored private directories.
- Produces: content-neutral structure profiles, exact-match review candidates, a geometry-only
  SVG atlas, two-review partitions, singleton `DocumentGroup` records, a positive
  train/validation/test `SplitManifest`, a canonical runtime manifest, derived report
  contexts, exact privacy-safe commands, required artifact categories, a freeze checklist,
  and the committed foundation SHA used by all four experiment worktrees.
- Invariant: `experiments.row_extraction.cli` retains exactly its seven shared experiment
  commands. `experiments.row_extraction.foundation_admin` is a separate five-command
  administrative surface: `profile-groups`, `freeze-groups`, `prepare-runtime`,
  `verify-runtime`, and `prepare-report-context`.

The structure profile uses a fixed 64-cell normalized grid and contains no filename, PDF
metadata, glyph or word text, font name, merchant/date/amount/currency/total, parser outcome,
diagnostic, confidence, gold label, or split assignment. Its duplicate fingerprint includes
page topology, image/vector geometry, table/header/column geometry, and row bands. Its layout
fingerprint omits row bands, OCR modality/quality, text density, and semantic column roles.
Exact fingerprints produce review candidates, not mandatory merges. Two independent reviewers
may reject false positives and may conservatively merge visually equivalent or uncertain
non-exact profiles using only the ignored geometry atlas. Their final partitions require two
distinct attestations over one exact decision. Strata are only `digital:single`,
`digital:multi`, `ocr:single`, `ocr:multi`, or `mixed:multi`.

Every source is inode/stat/hash stable before, during, and after profiling. The grouping freeze
emits one singleton `DocumentGroup` per document and refuses a result unless every document is
covered exactly once and train, validation, and locked test each contain at least one document.
Group integrity takes precedence over the target ratio; an empty partition is a stop condition,
not permission to break a reviewed group or tune against labels/results.

All multi-artifact administrative commands stage complete canonical bytes first, publish with
no-clobber inode ownership, and on failure remove only artifacts they still own. The runtime
manifest reuses `ToolchainInspector` and binds the exact dependency-inventory identity. Public
report context is derived from a completed `RunMeasurements` and exposes only Python, fixed
dependency, PyMuPDF binding/engine, Tesseract, and OCR-pipeline versions—never hashes, paths,
environment values, or asset sizes.

- [ ] **Step 1: Write the runbook with exact commands**

Document commands using shell variables whose values point only to ignored local paths:

```bash
PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.foundation_admin profile-groups \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --documents "$ROW_EXPERIMENT_DOCUMENTS" \
  --cache-dir "$ROW_EXPERIMENT_PRIVATE/group-profile-cache" \
  --profiles-output "$ROW_EXPERIMENT_PRIVATE/group-profiles.jsonl" \
  --profiles-identity-output "$ROW_EXPERIMENT_PRIVATE/group-profiles.identity.json" \
  --proposals-output "$ROW_EXPERIMENT_PRIVATE/group-proposals.jsonl" \
  --proposals-identity-output "$ROW_EXPERIMENT_PRIVATE/group-proposals.identity.json" \
  --atlas-output "$ROW_EXPERIMENT_PRIVATE/group-atlas.svg" \
  --atlas-identity-output "$ROW_EXPERIMENT_PRIVATE/group-atlas.identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.foundation_admin freeze-groups \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --profiles "$ROW_EXPERIMENT_PRIVATE/group-profiles.jsonl" \
  --proposals "$ROW_EXPERIMENT_PRIVATE/group-proposals.jsonl" \
  --reviewed-grouping "$ROW_EXPERIMENT_PRIVATE/reviewed-groups.json" \
  --seed "$ROW_EXPERIMENT_SPLIT_SEED" \
  --groups-output "$ROW_EXPERIMENT_PRIVATE/document-groups.jsonl" \
  --groups-identity-output "$ROW_EXPERIMENT_PRIVATE/document-groups.identity.json" \
  --split-output "$ROW_EXPERIMENT_PRIVATE/splits.json" \
  --split-identity-output "$ROW_EXPERIMENT_PRIVATE/splits.identity.json"
```

Before `freeze-groups`, two reviewers independently inspect only the canonical profiles,
exact-match proposals, and geometry-only atlas. Store both ignored draft decisions. They
must agree on the final duplicate/layout partitions, or produce an ignored adjudication; the
final `ReviewedGrouping` has two distinct reviewer attestations over that exact decision.
Reviewers see no filenames, PDF pixels, text, gold, predictions, metrics, or proposed split.
Possible near-duplicates/layout matches are merged when uncertain. The split seed is declared
before labels or results and is never searched to optimize membership or ratios.

```bash
PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --documents "$ROW_EXPERIMENT_DOCUMENTS" \
  --split-manifest "$ROW_EXPERIMENT_PRIVATE/splits.json" \
  --output-dir "$ROW_EXPERIMENT_PRIVATE/bundle"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli validate \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --labels "$ROW_EXPERIMENT_PRIVATE/gold.jsonl" \
  --ocr-references "$ROW_EXPERIMENT_PRIVATE/ocr-references.jsonl"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/empty-model-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/empty-model-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/empty-model-inventory.identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/tesseract-model-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare-inventory \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --roots "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-roots.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.foundation_admin prepare-runtime \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --dependency-inventory-identity \
  "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/runtime-manifest.json" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.foundation_admin verify-runtime \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --manifest "$ROW_EXPERIMENT_PRIVATE/runtime-manifest.json" \
  --identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --dependency-inventory-identity \
  "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.identity.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare-page-evidence \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --split validation \
  --mode conditional-page-ocr \
  --runtime-identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --cache-dir "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1" \
  --output "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1/page-evidence.jsonl" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/conditional-page-cache.run-1/page-evidence.identity.json" \
  --model-inventory "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.json" \
  --dependency-inventory "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.json" \
  --inventory-output "$ROW_EXPERIMENT_PRIVATE/conditional-page-preparation.run-1.inventory.json" \
  --preparation-output "$ROW_EXPERIMENT_PRIVATE/conditional-page-preparation.run-1.json"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare-page-evidence \
  --private-root "$ROW_EXPERIMENT_PRIVATE" \
  --rows "$ROW_EXPERIMENT_PRIVATE/bundle/rows.jsonl" \
  --split validation \
  --mode forced-page-ocr \
  --runtime-identity "$ROW_EXPERIMENT_PRIVATE/runtime-identity.json" \
  --cache-dir "$ROW_EXPERIMENT_PRIVATE/forced-page-cache.run-1" \
  --output "$ROW_EXPERIMENT_PRIVATE/forced-page-cache.run-1/page-evidence.jsonl" \
  --identity-output "$ROW_EXPERIMENT_PRIVATE/forced-page-cache.run-1/page-evidence.identity.json" \
  --model-inventory "$ROW_EXPERIMENT_PRIVATE/tesseract-model-inventory.json" \
  --dependency-inventory "$ROW_EXPERIMENT_PRIVATE/baseline-dependency-inventory.json" \
  --inventory-output "$ROW_EXPERIMENT_PRIVATE/forced-page-preparation.run-1.inventory.json" \
  --preparation-output "$ROW_EXPERIMENT_PRIVATE/forced-page-preparation.run-1.json"
```

Repeat both page-preparation commands with every `run-1` path replaced by a distinct `run-2`
path. The two canonical page-evidence identities must match even though the private cache and
resource-inventory identities may differ.

For each mode in `accepted-baseline`, `conditional-page-ocr`, and `forced-page-ocr`, document
two exact `prepare-run-spec` invocations with identical row/split/runtime/arm/model/dependency
identities but distinct new cache roots, combined-inventory outputs, and spec outputs. Then
document two exact `run-baseline` invocations using those specs, fresh factories, independent
nonexistent prediction/run outputs, and, for page modes, the corresponding run-1/run-2
preparation record; an exact `assert_repeated_output` check; and `score` using a `ReportContext`
with matching IDs. The accepted mode consumes `bundle/accepted_predictions.jsonl` and its
identity sidecar, the empty model inventory, and no preparation record. Page modes consume the corresponding typed
page-evidence JSONL and identity sidecar. Reopen the row and gold streams for every score; never
reuse an exhausted iterator.

Require two independent reviewers for the predeclared sample, clean annotation validation,
truthful phase-separated resources, byte-identical repeated predictions for all three shared
baselines, and no private path or value in Git status/diff. If no reviewed verbatim OCR
references exist, omit the optional flag and require the report to show CER/WER as unavailable
rather than substituting another target.

- [ ] **Step 2: Run the complete tracked verification**

Run:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src experiments/row_extraction
/root/creditcard/.venv/bin/pytest -q
```

Expected: formatting, Ruff, and mypy pass. Extraction-relevant tests pass. If the same five
sandbox-only controller tests fail, record them as inherited and do not investigate them.

- [ ] **Step 3: Run private preparation and baseline validation**

Run the runbook commands from a clean committed candidate. Capture normal output privately.
Report only privacy-safe aggregate status, phase-separated runtime/resource measurements, and
whether each of the three pairs of canonical baseline prediction files is byte-identical. Do
not claim field accuracy or corpus acceptance.

- [ ] **Step 4: Verify the branch is a valid experiment foundation**

Run: `git status --short --branch`

Expected: clean worktree.

Run: `git diff --name-only dee4b071ad65231da13825f2f7c74a488ca96c7c..HEAD -- src`

Expected: no output; production source is unchanged.

- [ ] **Step 5: Commit the runbook and record the foundation SHA privately**

```bash
git add docs/experiments/row-extraction-foundation-runbook.md
git commit -m "docs: freeze row experiment foundation"
```

After this commit, create the four charter-named worktrees from its full SHA. Store the full
SHA in the ignored private experiment manifest and in each lane's execution brief. Do not add
private artifact hashes or membership to Git.
