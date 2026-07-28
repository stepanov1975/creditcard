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
    atom_ids: tuple[str, ...] = Field(min_length=1)
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
evidence membership and nonoverlap; `Decimal` parsing for amount roles; existing date and
currency parsers for typed roles; paired original amount/currency; primary-versus-
continuation rules; and explicit ambiguity. The handbook defines these decisions with
synthetic merchant, amount, date, currency, continuation, structural, and ambiguous examples.
It states that accepted output is a proposal, not gold.

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
Fixed inputs: reviewed GoldRow records and self-contained RowPrediction evidence ledgers
Allowed files: metrics module and tests
Stop condition: stop if a metric uses reconciliation as ground truth or silently excludes abstentions/errors
```

**Files:**
- Create: `experiments/row_extraction/metrics.py`
- Test: `tests/experiments/row_extraction/test_metrics.py`

**Interfaces:**
- Consumes: sequences of `GoldRow` and `RowPrediction` joined by document/row IDs, plus optional reviewed `OcrReference` records.
- Produces: immutable `FieldMetric`, `RowTypeMetric`, `ConfusionCell`, `CalibrationBin`, `RiskCoveragePoint`, `RiskTargetCoverage`, `MetricReport`, `score_predictions(gold: Sequence[GoldRow], predictions: Sequence[RowPrediction], ocr_references: Sequence[OcrReference] = ()) -> MetricReport`, `character_error_rate`, and `word_error_rate`.

- [ ] **Step 1: Write failing exactness, omission, hallucination, and risk tests**

```python
def test_score_predictions_separates_omission_from_hallucination() -> None:
    report = score_predictions(
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
    row_count: int = Field(ge=0)
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

Normalize merchant comparison under one versioned NFC/case/space policy while retaining raw
exact match separately. Use edit distance for CER/WER. Count every eligible gold row in
coverage. Treat accepted wrong/extra fields as hallucinations and absent expected fields as
omissions. Build fixed predeclared calibration bins, Brier/log loss, and risk-coverage points
from exact-row outcomes. Reject duplicate/missing prediction IDs instead of dropping them.
Compute CER/WER only against supplied verbatim `OcrReference` records; report `None` when none
are eligible, never against accepted OCR or canonicalized date/amount values.

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
Measured effect: identical execution, timing, evidence validation, deterministic output, and aggregate reporting for every arm
Fixed inputs: FrozenRow stream, ExperimentArm protocol, common metrics
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
- Consumes: `Iterable[FrozenRow]`, `ExperimentArm`, `PredictionSink`, gold records, optional reviewed `OcrReference` records, and artifact identities.
- Produces: `RunMeasurements`, `run_arm(rows: Iterable[FrozenRow], arm: ExperimentArm, sink: PredictionSink) -> RunMeasurements`, `AcceptedBaselineArm`, `ConditionalPageOcrArm`, `ForcedPageOcrArm`, `assert_repeated_output(first: Path, second: Path) -> None`, `privacy_safe_report(metrics: MetricReport, run: RunMeasurements) -> dict[str, object]`, and Typer commands `prepare`, `validate`, `run-baseline`, and `score`.

- [ ] **Step 1: Write failing identity, immutability, and privacy tests**

```python
def test_runner_rejects_prediction_for_another_row(tmp_path: Path) -> None:
    sink = JsonlPredictionSink(tmp_path / "predictions.jsonl")
    with pytest.raises(RunContractError, match="prediction identity mismatch"):
        run_arm((frozen_row(),), WrongIdentityArm(), sink)


def test_privacy_safe_report_contains_no_row_or_field_values() -> None:
    report = privacy_safe_report(metric_report(), run_measurements())
    serialized = json.dumps(report, sort_keys=True)
    assert "row_id" not in serialized
    assert "canonical_value" not in serialized
    assert "source_pdf" not in serialized


def test_forced_page_ocr_is_clipped_to_the_fixed_row_and_bands() -> None:
    row = frozen_row()
    prediction = ForcedPageOcrArm(synthetic_forced_page_words()).predict(row)
    assert prediction.experiment_id == "forced-page-ocr"
    assert prediction.row_id == row.row_id
    assert all(row.bbox[0] <= atom.bbox[0] <= atom.bbox[2] <= row.bbox[2] for atom in prediction.evidence_atoms)
```

- [ ] **Step 2: Run runner/report tests to verify RED**

Run: `/root/creditcard/.venv/bin/pytest -q tests/experiments/row_extraction/test_runner.py tests/experiments/row_extraction/test_report.py tests/experiments/row_extraction/test_cli.py`

Expected: collection fails because runner/report/CLI modules do not exist.

- [ ] **Step 3: Implement bounded execution and accepted baseline projection**

Use this exact public resource schema:

```python
class RunMeasurements(_FrozenModel):
    row_count: int = Field(ge=0)
    total_ns: int = Field(ge=0)
    p50_ns: int = Field(ge=0)
    p95_ns: int = Field(ge=0)
    cold_start_ns: int = Field(ge=0)
    throughput_rows_per_second: Decimal
    peak_rss_bytes: int = Field(ge=0)
    model_bytes: int = Field(ge=0)
    dependency_bytes: int = Field(ge=0)
    cache_bytes: int = Field(ge=0)
    subprocess_count: int = Field(ge=0)
    worker_count: int = Field(ge=1)
    predictions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

The runner deep-compares the immutable input before/after prediction, validates identity and
evidence references, measures `perf_counter_ns`, counts calls, streams canonical predictions,
and records process peak RSS without emitting values. `AcceptedBaselineArm` converts the
private accepted-anchor baseline observation into the same evidence-grounded proposal format.
`ConditionalPageOcrArm` deterministically reassigns the accepted page evidence to the frozen
row and column bands. `ForcedPageOcrArm` consumes one private, pinned whole-page Tesseract word
stream, selects words by fixed row/column geometry, and uses the same deterministic field
resolver. Neither page-OCR arm may redetect rows or columns. Their public experiment IDs are
exactly `conditional-page-ocr` and `forced-page-ocr`.
The report includes only aggregate counts, ratios, resource measures, experiment/config IDs,
and public runtime versions.

The CLI requires explicit private bundle/label/output paths, refuses paths tracked by Git,
and never defaults outputs into the source tree. `validate` and `score` accept an optional
explicit `--ocr-references` JSONL path, validate it through `validate_annotations`, and pass
it unchanged to `score_predictions`; when omitted, CER/WER remain `None`.

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
- Create: `docs/experiments/row-extraction-foundation-runbook.md`
- Test: all foundation and repository tests.

**Interfaces:**
- Consumes: `experiments.row_extraction.cli` commands and ignored private directories.
- Produces: exact privacy-safe commands, required artifact categories, freeze checklist, and the committed foundation SHA used by all four experiment worktrees.

- [ ] **Step 1: Write the runbook with exact commands**

Document commands using shell variables whose values point only to ignored local paths:

```bash
PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli prepare \
  --documents "$ROW_EXPERIMENT_DOCUMENTS" \
  --split-manifest "$ROW_EXPERIMENT_PRIVATE/splits.json" \
  --output "$ROW_EXPERIMENT_PRIVATE/rows.jsonl"

PYTHONPATH="$PWD/src:$PWD" /root/creditcard/.venv/bin/python -m \
  experiments.row_extraction.cli validate \
  --rows "$ROW_EXPERIMENT_PRIVATE/rows.jsonl" \
  --labels "$ROW_EXPERIMENT_PRIVATE/gold.jsonl" \
  --ocr-references "$ROW_EXPERIMENT_PRIVATE/ocr-references.jsonl"
```

Require two independent reviewers for the predeclared sample, a clean annotation validation,
one accepted baseline run, byte-identical repeated baseline predictions, and no private path
or value in Git status/diff. If no reviewed verbatim OCR references exist, omit the optional
flag and require the report to show CER/WER as unavailable rather than substituting another
target.

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
Report only privacy-safe aggregate status, runtime/resource measurements, and whether the two
canonical baseline prediction files are byte-identical. Do not claim field accuracy or corpus
acceptance.

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
