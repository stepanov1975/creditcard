# Grounded Merchant Atom Tagger Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether a small locally trained atom-role model can provide a useful, fully source-grounded first guess for merchant text and description details on current evidence, while remaining reusable for later row-OCR evidence variants.

**Architecture:** Freeze immutable financial/date/category atoms first, then label only residual row-bundle atoms as merchant, location, reference, transaction marker, auxiliary, layout noise, or outside. Compare the current WIP description claims with a deterministic rule baseline and a dependency-free averaged structured perceptron. Model output is a review-only atom-label map; a deterministic ledger renderer converts selected merchant atoms into the shared `MerchantPrediction` solely for exact evaluation. No model generates or normalizes text.

**Tech Stack:** Python 3.13 standard library (`dataclasses`, `enum`, `fractions.Fraction`, canonical `json`), existing evidence ledger/layout types, shared row-recovery contracts, Pydantic v2, pytest, Ruff, and mypy. No PyTorch, scikit-learn, network model, pretrained tokenizer, root dependency, or `pyproject.toml` change.

## Global Constraints

- Execute only in `.worktrees/exp-merchant-tagger` on branch `codex/exp-merchant-tagger`, created from the exact frozen foundation SHA.
- Exclusive tracked ownership is `src/ccparser/experiments/row_recovery/merchant/` and `tests/experiments/row_recovery/merchant/`. Do not edit shared foundation or production files.
- Set `CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments`. Read only physically split development/validation manifests, prepared cases, annotations, and approved OCR variants; never open test manifests, their underlying source files, prepared test cases, or test labels. Store annotations, detailed predictions, feature vocabularies, trained weights, calibration output, and case-level metrics below that shared ignored root, never in a worktree-local artifact tree. Never stage or publish them.
- Every annotation and prediction is scoped by `case_id + evidence_fingerprint`. Current evidence uses `PreparedRowCase.case_fingerprint`; a later OCR variant uses its own fingerprint and requires new reviewed labels for supervised evaluation.
- Predictions contain labels and source atom IDs, never model-generated text. The only text-valued shared prediction is rendered deterministically from the selected source atoms after inference.
- Every lane proposal is shadow/review-only. The lane has no parser, normalizer, reconciliation, status, public JSON/CSV, or automatic acceptance path.
- Freeze immutable owners before residual labeling: transaction/posting/conversion date, billed/original value, exchange rate/fees, installment, and category. Never allow the model to relabel those atoms.
- Do not freeze current description, location, processor-reference, marker, ancillary, or layout-noise claims; those are the roles the experiment is meant to test.
- Features may use local residual source characters and geometry, but no feature may use source/case IDs, paths, hashes, issuer names, transaction values, dates, gold labels, baseline semantic labels, or a merchant dictionary. A trusted projection may use immutable semantic claims only to replace every immutable atom with the same generic `IMMUTABLE` sentinel before feature extraction; owner identity is not exposed. Learned character weights remain private because they may encode corpus text.
- Pre-register two feature sets: `shape-v1` excludes literal character n-grams; `local-char-v1` adds local NFC character n-grams. Compare them on development/validation to quantify memorization-sensitive lift. Prefer `shape-v1` when exact performance is tied.
- Sort training examples by a canonical SHA-256 of feature vectors plus gold label sequence—not case/source identity—use a fixed label order and epoch count, never shuffle, use exact rational averaging, and resolve every score tie deterministically to `OUTSIDE`/abstention. Every residual atom that determines the merchant boundary must have strictly positive exact max-margin before any configurable threshold is considered; the configured margin applies to the minimum across the complete ordered residual label map.
- Train for the pre-registered 12 epochs on development only. Choose only the feature schema and one margin from the pre-registered validation grid; validation may not choose an epoch or change splits. Lane workers do not load sealed test labels.
- Evaluate whole-case exact atom maps and exact merchant atom/string recovery. Atom accuracy and macro-F1 are diagnostic and must not hide boundary errors or `OUTSIDE` dominance.
- Stop on any unknown/missing/duplicate atom, fingerprint drift, split leak, immutable-atom relabel, ungrounded output, private-data leak, nondeterministic model/prediction bytes, or wrong control change.
- `AnnotationState.INHERENTLY_AMBIGUOUS` is evaluation metadata only. It is never copied into `ResidualMerchantCase`, features, a labeler, proposal auditing, or inference-time abstention logic.
- Load the pinned shared `SourceRecord` records and report only the shared closed `EvaluationSlice` aggregates. Source/layout/temporal family identifiers may enforce grouped splits and support private diagnosis, but may never appear in public output.
- Before each commit run the complete repository Ruff format/check, mypy, and pytest gates through `/root/creditcard/.venv/bin/...`.

## Private Annotation Layout

```text
artifacts/row-experiments/merchant/
├── annotations/
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
├── approvals/
│   ├── training-manifest.json
│   └── <binding-id>.json
├── models/
│   └── <model-id>.json
└── runs/
    └── <run-id>/
```

The model file is private even when features are generic. Record its full SHA-256, training inventory SHA-256, feature schema, code revision, epoch count, and label order in the private run manifest. Never commit learned weights or corpus-derived feature vocabulary.

## Lane Contracts

Create in `src/ccparser/experiments/row_recovery/merchant/contracts.py`:

```python
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ccparser.experiments.row_recovery.contracts import (
    CandidateSupportLineage,
    DatasetSplit,
    ExperimentReasonCode,
    GroundedCandidateBatch,
    ObservedSegmentAxes,
    PreparedAtom,
    PreparedClaim,
    ProducerIdentity,
    SplitRunInputBinding,
)
from ccparser.layout.models import Row, TableRegion
from ccparser.semantic_evidence import SemanticOwner


class MerchantAtomLabel(StrEnum):
    OUTSIDE = "outside"
    MERCHANT = "merchant"
    LOCATION = "location"
    REFERENCE = "reference"
    TRANSACTION_MARKER = "transaction_marker"
    AUXILIARY = "auxiliary"
    LAYOUT_NOISE = "layout_noise"


class AnnotationState(StrEnum):
    ADJUDICATED = "adjudicated"
    INHERENTLY_AMBIGUOUS = "inherently_ambiguous"


class AnnotationReasonCode(StrEnum):
    ADJUDICATION_DISAGREEMENT = "adjudication_disagreement"
    NO_AUTHORITATIVE_PARTITION = "no_authoritative_partition"


class MerchantReasonCode(StrEnum):
    LOW_SEQUENCE_MARGIN = "low_sequence_margin"
    EMPTY_MERCHANT = "empty_merchant"
    DISCONNECTED_MERCHANT = "disconnected_merchant"
    AMBIGUOUS_DIRECTION = "ambiguous_direction"
    CONTROL_DISAGREEMENT = "control_disagreement"
    GROUNDING_FAILED = "grounding_failed"
    IMMUTABLE_ATOM_CONFLICT = "immutable_atom_conflict"
    PRODUCER_IDENTITY_MISMATCH = "producer_identity_mismatch"
    MODEL_IDENTITY_MISMATCH = "model_identity_mismatch"


class ReviewedAtomLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    atom_id: int = Field(ge=0)
    label: MerchantAtomLabel


class MerchantAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    case_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: AnnotationState
    labels: tuple[ReviewedAtomLabel, ...]
    reason_codes: tuple[AnnotationReasonCode, ...] = ()


class AtomPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    atom_id: int = Field(ge=0)
    label: MerchantAtomLabel
    margin_numerator: int
    margin_denominator: int = Field(gt=0)


class MerchantAtomProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    case_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    predictions: tuple[AtomPrediction, ...]
    review_required: Literal[True] = True
    reason_codes: tuple[MerchantReasonCode, ...] = ()


class ResidualMerchantCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    case_id: str
    split: DatasetSplit
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_atoms: tuple[PreparedAtom, ...]
    scoped_claims: tuple[PreparedClaim, ...]
    regions: tuple[TableRegion, ...]
    group_regions: tuple[TableRegion, ...]
    rows: tuple[Row, ...]
    segment_axes: tuple[ObservedSegmentAxes, ...]
    immutable_atom_ids: frozenset[int]
    immutable_owner_by_atom: tuple[tuple[int, SemanticOwner], ...]
    residual_atom_ids: tuple[int, ...]


class LabeledMerchantCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    case: ResidualMerchantCase
    labels: tuple[ReviewedAtomLabel, ...]


class AtomLabeler(Protocol):
    @property
    def identity(self) -> ProducerIdentity: ...

    @property
    def model_fingerprint(self) -> str: ...

    def predict(self, case: ResidualMerchantCase) -> MerchantAtomProposal: ...
```

The proposal schema deliberately has no `text`, `raw_text`, `bbox`, normalized value, generated value, source path, or financial field. `AtomPrediction.margin_*` is the exact max-marginal for that target atom: the score of the globally selected label sequence minus the best globally legal sequence constrained to use any other label at that atom. The denominator is positive, the fraction is reduced, and the numerator is nonnegative; a tie therefore has margin zero. Deterministic controls use the same definition over their explicitly tested integer scoring functions.

## Label Policy

- `MERCHANT`: exact atoms printed as the merchant/payee description.
- `LOCATION`: printed place or branch qualifier that is not part of the exact merchant field.
- `REFERENCE`: processor/reference/order/authorization identifier.
- `TRANSACTION_MARKER`: a printed transaction-type marker separate from the merchant.
- `AUXILIARY`: other meaningful non-merchant description detail.
- `LAYOUT_NOISE`: duplicated/overlaid/stray layout evidence with no semantic field.
- `OUTSIDE`: residual context atom that belongs to none of the above; immutable preclaimed atoms are not prediction targets.

An adjudicated annotation labels every residual atom exactly once. Punctuation supporting a semantic span inherits that span's label. An inherently ambiguous annotation has `labels=()`, at least one closed ambiguity reason, no authoritative training/evaluation partition, and contributes only to the aggregate ambiguous-case count. It cannot change the labeler's observable input or force an inference abstention. Baseline claims may seed a reviewer UI but never become gold without adjudication.

---

### Task 1: Define review-only atom-label contracts and import isolation

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/__init__.py`
- Create: `src/ccparser/experiments/row_recovery/merchant/contracts.py`
- Create: `tests/experiments/row_recovery/merchant/test_contracts.py`
- Create: `tests/experiments/row_recovery/merchant/test_import_isolation.py`

- [ ] **Step 1: Write contract and boundary tests**

Cover frozen/extra-forbid models, closed label order, fingerprint/revision patterns, exact rational margins, `review_required=True`, rejection of text/raw text/bbox/generated fields, complete deterministic prediction ordering, and AST guards proving production modules do not import the experiment and importing `ccparser` does not import the merchant package.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_contracts.py tests/experiments/row_recovery/merchant/test_import_isolation.py
```

Expected: collection/import failure because the merchant package does not exist.

- [ ] **Step 3: Implement minimal contracts and boundary scanner**

Use fixed enum order beginning with `OUTSIDE`. Validators reject duplicate atom IDs, negative or non-reduced margin fractions, nonpositive denominators, and free-form exception details in reason codes. They also require proposal identity to be complete and prediction order to match the residual ledger order.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant tests/experiments/row_recovery/merchant
git commit -m "test: define grounded merchant atom contracts"
```

### Task 2: Project immutable preclaims and validate private annotations

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/projection.py`
- Create: `src/ccparser/experiments/row_recovery/merchant/annotations.py`
- Create: `tests/experiments/row_recovery/merchant/test_projection.py`
- Create: `tests/experiments/row_recovery/merchant/test_annotations.py`

**Interfaces:**

```python
def project_residual_case(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None = None,
) -> ResidualMerchantCase: ...


def merchant_group_regions(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None = None,
) -> tuple[TableRegion, ...]: ...


def load_annotations(
    path: Path,
    cases: Mapping[str, ResidualMerchantCase],
    atom_gold: Mapping[tuple[str, str], MerchantAtomGold],
    *,
    expected_sha256: str,
    expected_split: DatasetSplit,
) -> tuple[MerchantAnnotation, ...]: ...
```

- [ ] **Step 1: Write projection tests**

Cover current and OCR evidence fingerprints, stable ledger order, complete context atoms, participating and group regions, cross-page segment axes, shadow rows, immutable financial/date/FX/installment/category owners, description/detail/noise atoms left residual, unknown/conflicting claim atoms, duplicate atom IDs, no residual atoms, and byte-identical input cases after projection. For OCR evidence, prove `merchant_group_regions()` replaces every participating baseline row exactly once with its corresponding shadow row across same- and cross-page regions, rejects missing/ambiguous/cardinality-mismatched substitution, changes repeated-band/control evidence when shadow text or geometry changes, and leaves baseline regions byte-identical.

- [ ] **Step 2: Write annotation validation tests**

Cover exact residual partition, missing/duplicate/unknown/immutable atom labels, fingerprint drift, wrong independent file pin, wrong split, duplicate case annotations, adjudicated versus inherently ambiguous shape, label order, NFC punctuation policy, missing/extra shared atom gold, and proof that baseline claims cannot fill missing human labels. Require adjudicated cases to have a complete partition whose `MERCHANT` IDs exactly equal the independently pinned shared `MerchantAtomGold` for the same case/evidence fingerprint, and render those IDs through the shared ledger renderer to exact NFC equality with that split's independently loaded `MerchantTextGold`. Reject an annotation if either cross-check fails. Inherently ambiguous cases have no labels plus at least one closed reason and no supervised merchant partition.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_projection.py tests/experiments/row_recovery/merchant/test_annotations.py
```

Expected: import failure because projection/annotation modules do not exist.

- [ ] **Step 4: Implement projection and fail-closed loading**

Load the frozen prepared cases first with the shared `load_prepared_cases()` contract, then project them and create annotations against those exact candidate-local atom IDs. Define one closed immutable-owner set using `SemanticOwner`. For a `RowEvidenceVariant`, use its atoms, claims, shadow rows, segment-region mapping, and base directions; rebuild immutable candidate-local group-region copies through `merchant_group_regions()` and never retain baseline row text/geometry in a group-dependent feature/control. Preserve only the prepared protected fingerprint. Sort residual atoms in existing ledger render order, not naive left-to-right order. Do not silently map labels across an evidence fingerprint change.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant/projection.py src/ccparser/experiments/row_recovery/merchant/annotations.py tests/experiments/row_recovery/merchant/test_projection.py tests/experiments/row_recovery/merchant/test_annotations.py
git commit -m "feat: prepare reviewed merchant residual atoms"
```

### Task 3: Record deterministic control labelers

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/control.py`
- Create: `tests/experiments/row_recovery/merchant/test_control.py`

**Interfaces:**

```python
class ExistingClaimsLabeler:
    @property
    def identity(self) -> ProducerIdentity: ...

    @property
    def model_fingerprint(self) -> str: ...

    def predict(self, case: ResidualMerchantCase) -> MerchantAtomProposal: ...


class ShapeRuleLabeler:
    @property
    def identity(self) -> ProducerIdentity: ...

    @property
    def model_fingerprint(self) -> str: ...

    def predict(self, case: ResidualMerchantCase) -> MerchantAtomProposal: ...
```

- [ ] **Step 1: Write existing-claim mapping tests**

Map `DESCRIPTION→MERCHANT`, `LOCATION→LOCATION`, `PROCESSOR_REFERENCE→REFERENCE`, `TRANSACTION_MARKER→TRANSACTION_MARKER`, `ANCILLARY→AUXILIARY`, and `LAYOUT_NOISE→LAYOUT_NOISE`. Everything else residual is `OUTSIDE`. Cover claim conflicts, description-extraction versus broader semantic-completeness scope, and complete atom coverage.

- [ ] **Step 2: Write generic shape-rule tests**

Use only description-column containment, primary cluster/line position, typed marker/reference shapes, relative geometry, Unicode categories, and existing repeated-band proof. Cover Hebrew/Latin/mixed, continuation, reference/location/detail, competing cluster, and abstaining low-evidence cases. No exact merchant token appears in rules.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_control.py
```

Expected: import failure because `control.py` does not exist.

- [ ] **Step 4: Implement both complete review-only controls**

Both labelers emit one label for every residual atom and exact rational max-margins under their closed integer scoring rules. Their `ProducerIdentity` and control-configuration fingerprint are constructor inputs and are echoed exactly; the control's canonical rule-table fingerprint is its `model_fingerprint`. Conflicts or weak shape evidence use zero margin plus a closed review reason; they never omit an atom or emit text.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant/control.py tests/experiments/row_recovery/merchant/test_control.py
git commit -m "feat: record merchant atom control proposals"
```

### Task 4: Extract deterministic leakage-audited features

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/features.py`
- Create: `tests/experiments/row_recovery/merchant/test_features.py`

**Interfaces:**

```python
class FeatureSchema(StrEnum):
    SHAPE_V1 = "merchant-atom-shape-v1"
    LOCAL_CHAR_V1 = "merchant-atom-local-char-v1"


@dataclass(frozen=True, slots=True)
class AtomFeatureVector:
    values: tuple[tuple[str, int], ...]


class FeatureSafeAtom(FrozenExperimentModel):
    atom_id: int
    feature_text: str
    kind: EvidenceAtomKind
    source: Literal["digital", "ocr", "cell_text"]
    confidence_bucket: int
    bbox: BBox
    segment_ordinal: int
    cell_indices: tuple[int, ...]
    column_indices: tuple[int, ...]
    is_prediction_target: bool


class MerchantFeatureCase(FrozenExperimentModel):
    atoms: tuple[FeatureSafeAtom, ...]
    residual_atom_ids: tuple[int, ...]
    row_bboxes: tuple[BBox, ...]
    region_bboxes: tuple[BBox, ...]
    segment_axes: tuple[ObservedSegmentAxes, ...]


def project_feature_case(case: ResidualMerchantCase) -> MerchantFeatureCase: ...


def sequence_features(
    case: MerchantFeatureCase,
    schema: FeatureSchema,
) -> tuple[AtomFeatureVector, ...]: ...
```

Common features include Unicode category/bidi/script/digit/currency/percent/case/length shapes, atom kind/source/confidence decile, row/column normalized geometry buckets, x/y gaps, line change, column index, segment position, and sequence edges. `project_feature_case()` copies only primitive geometry and observed axes, removes rows/regions/scoped claims/owner mappings, and replaces every immutable atom's text with the same generic `IMMUTABLE` sentinel. Thus its literal date, amount, currency, category, and semantic owner are unavailable to feature code. `LOCAL_CHAR_V1` additionally includes NFC character unigrams/bigrams/trigrams for the residual target and immediate residual neighbors, or the generic sentinel when an immediate ledger neighbor is immutable. It never uses Python `hash()`; feature strings are canonical and model artifacts stay private.

- [ ] **Step 1: Write exact feature snapshots**

Cover Hebrew, Latin, mixed, numeric, punctuation/marker, digital/OCR source, confidence buckets, scale/translation invariance, generic immutable context, complete removal of scoped claims/owner labels/raw rows/raw regions, and sequence boundaries.

- [ ] **Step 2: Write leakage/ablation guards**

Changing source/case IDs, gold annotations, any mutable claim owner (`DESCRIPTION`, `LOCATION`, `PROCESSOR_REFERENCE`, `TRANSACTION_MARKER`, `ANCILLARY`, or `LAYOUT_NOISE`), any immutable owner label, category, date, amount, currency, or any immutable atom's literal text must not change features when the immutable/residual partition is unchanged. Add an AST/data-model guard proving feature code cannot access `ResidualMerchantCase.scoped_claims`, `immutable_owner_by_atom`, raw `rows`, or raw `regions`. `SHAPE_V1` must contain no literal source character; `LOCAL_CHAR_V1` may contain only residual target/immediate-residual-neighbor characters and the generic `IMMUTABLE` sentinel. Repeated extraction must be byte-identical.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_features.py
```

Expected: import failure because `features.py` does not exist.

- [ ] **Step 4: Implement both pre-registered schemas**

Use integer geometry basis points and fixed confidence buckets. Keep feature names/version frozen; changing feature semantics requires a new schema value and invalidates old model hashes.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant/features.py tests/experiments/row_recovery/merchant/test_features.py
git commit -m "feat: extract merchant atom model features"
```

### Task 5: Implement an exact deterministic averaged structured perceptron

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/perceptron.py`
- Create: `tests/experiments/row_recovery/merchant/test_perceptron.py`

**Interfaces:**

```python
class RationalWeight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature: str
    label: MerchantAtomLabel
    numerator: int
    denominator: int = Field(gt=0)


class TransitionWeight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    previous_label: MerchantAtomLabel
    label: MerchantAtomLabel
    numerator: int
    denominator: int = Field(gt=0)


class PerceptronModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    feature_schema: FeatureSchema
    labels: tuple[MerchantAtomLabel, ...]
    emission_weights: tuple[RationalWeight, ...]
    transition_weights: tuple[TransitionWeight, ...]
    epochs: Literal[12] = 12
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    training_manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def train_perceptron(
    examples: Sequence[LabeledMerchantCase],
    *,
    feature_schema: FeatureSchema,
    producer_revision: str,
    expected_training_manifest_fingerprint: str,
    epochs: Literal[12] = 12,
) -> PerceptronModel: ...


def dump_model(model: PerceptronModel, path: Path) -> str: ...


def load_model(
    path: Path,
    *,
    expected_sha256: str,
    expected_training_manifest_fingerprint: str,
    expected_producer_revision: str,
) -> PerceptronModel: ...
```

- [ ] **Step 1: Write synthetic learning and Viterbi tests**

Prove the model learns merchant/reference boundaries, uses transitions to distinguish equal local features, emits every residual atom once, fixes label/tie order, and routes zero-score ties to `OUTSIDE`. For every atom, compare its reported max-marginal with exhaustive enumeration on small sequences: selected global sequence score minus the best global sequence constrained to any alternate label at that atom.

- [ ] **Step 2: Write exact determinism/model IO tests**

Three trainings over differently ordered input containers and arbitrary case-ID renamings must produce identical canonical bytes, private SHA, and feature-equivalent predictions. Save/load preserves exact `Fraction` scores and exact per-atom max-marginals. Reject wrong model hash/schema/label order/training fingerprint/producer revision, overwrite attempts, nonreduced weights, and any non-standard ML import.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_perceptron.py
```

Expected: import failure because `perceptron.py` does not exist.

- [ ] **Step 4: Implement sorted training, rational averaging, and Viterbi**

Canonicalize each training example from its feature vectors and gold label sequence, hash those bytes, and sort by that digest; case/source IDs never enter ordering or features. Identical digests must represent identical training content, so multiplicity is deterministic and tie order has no semantic effect. Use fixed label order and lexicographic feature order and train exactly 12 epochs; do not emit/evaluate intermediate checkpoints. Serialize compact sorted UTF-8 JSON with trailing newline and atomic create-without-overwrite publication. A model-backed `AtomLabeler` receives an externally pinned raw-candidate `ProducerIdentity`; its configuration fingerprint commits to the exact model-file fingerprint, feature schema, fixed epoch count, label order, and proposal/renderer revisions, but deliberately excludes the training-manifest fingerprint, every evaluation input pin, selected margin, and selector audit policy. The authenticated model/policy provenance retains and verifies the development training-manifest fingerprint separately. The selector identity adds threshold/audit values so byte-identical raw proposals remain one producer across margin arms.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant/perceptron.py tests/experiments/row_recovery/merchant/test_perceptron.py
git commit -m "feat: train deterministic merchant atom perceptron"
```

### Task 6: Audit proposals and render grounded shared predictions

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/review.py`
- Create: `tests/experiments/row_recovery/merchant/test_review.py`

**Interfaces:**

```python
class ProposalAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    grounded: bool
    immutable_preserved: bool
    merchant_atom_ids: frozenset[int]
    minimum_margin_numerator: int
    minimum_margin_denominator: int = Field(gt=0)
    reason_codes: tuple[MerchantReasonCode, ...]


def audit_proposal(
    case: ResidualMerchantCase,
    proposal: MerchantAtomProposal,
    *,
    labeler: AtomLabeler,
    expected_candidate_identity: ProducerIdentity,
    expected_model_fingerprint: str,
) -> ProposalAudit: ...


def to_grounded_candidate_batch(
    prepared_case: PreparedRowCase,
    evidence: RowEvidenceVariant | None,
    proposal: MerchantAtomProposal,
    audit: ProposalAudit,
    expected_candidate_identity: ProducerIdentity,
) -> GroundedCandidateBatch: ...


def select_merchant_prediction(
    prepared_case: PreparedRowCase,
    evidence_variants: tuple[RowEvidenceVariant, ...],
    batches: tuple[GroundedCandidateBatch, ...],
    *,
    control_labelers: tuple[AtomLabeler, AtomLabeler],
    expected_candidate_identity: ProducerIdentity,
    selector_identity: ProducerIdentity,
    minimum_margin: Fraction,
) -> MerchantPrediction: ...


def to_experiment_reason(reason: MerchantReasonCode) -> ExperimentReasonCode: ...
```

- [ ] **Step 1: Write grounding/audit tests**

Cover missing/duplicate/unknown/immutable IDs, candidate/configuration/model identity mismatch between the expected binding, labeler, and proposal, invalid or incorrectly computed max-marginals, nondeterministic re-scoring, wrong/missing/duplicate control labelers, empty/multiple disconnected merchant spans, ambiguous observable base direction, `OUTSIDE` tie, control disagreement, and an exhaustive `MerchantReasonCode` to shared `ExperimentReasonCode` mapping. Add a global-sequence tie where deterministic Viterbi selects a stable sequence but one `OUTSIDE` residual atom has zero max-margin to an alternate merchant boundary; require candidate abstention even when configured selector margin is zero. The raw audit calls the verified labeler again and requires its full canonical proposal—including every residual atom's exact structured max-marginal—to equal the supplied proposal. Grounding/fingerprint/immutable/span/direction failures or any residual margin `<= 0` prevent a raw candidate. `to_grounded_candidate_batch()` serializes the exact complete ordered `(atom_id, label, margin numerator, denominator)` map and proposal fingerprint in `MerchantSelectionProof` and derives `CandidateSupportLineage.MERCHANT_ATOM_TAGGER`; reject any different caller-supplied lineage. Round-trip all batches through canonical bytes and select in a fresh object/process using only case, the complete explicit variant tuple, matching batches, verified controls, selector identity, and threshold; reject altered/missing proof entries, missing/duplicate/extra/reordered-policy variants or batches, or producer-call state. Evaluate two closed invocation contexts. `CURRENT` supplies no variants and exactly one current-evidence batch. `OCR_VARIANT` supplies the final policy's complete ordered 1–4 variant tuple and a batch tuple containing the current-evidence batch first plus exactly one fingerprint-matched batch per variant; it is current evidence augmented by OCR alternatives, not OCR replacing native evidence. Apply the configured threshold to the minimum across each complete residual map, emit at most one prediction/metric observation per case per invocation context, and never count individual OCR variants as separate cases. Abstain on unresolved cross-variant merchant disagreement. Equal text may survive only when every candidate is independently grounded; choose the uniquely greatest minimum margin, or current-before-frozen-OCR policy order only after margin and rendered text are equal. Annotation state is not an input and is forbidden from affecting either result. Control disagreement is retained as a review reason but does not suppress the shadow proposal, because measuring correct disagreements is the experiment's purpose.

- [ ] **Step 2: Write exact renderer tests**

Cover Hebrew/Latin/mixed ordering, punctuation, continuation segments, OCR candidate-local atoms, exact evidence boxes, no normalization beyond existing NFC ledger rendering, shared fingerprint validation, and proof that model code never supplies text.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_review.py
```

Expected: import failure because `review.py` does not exist.

- [ ] **Step 4: Implement fail-closed auditing and deterministic rendering**

All proposals remain review-only even above margin. `to_grounded_candidate_batch()` projects only a strictly-positive-margin, source-grounded raw proposal and echoes the candidate identity; it never applies the selected threshold. `select_merchant_prediction()` validates the complete reloaded typed batch/proof set, makes one case-level decision across the supplied evidence context, may emit `PROPOSE` for experiment scoring, but has no production acceptance meaning and uses a distinct selector identity that binds candidate identity, selected margin, control/audit policy, cross-variant arbitration schema, and renderer revision. Map lane audit failures to the shared closed `ExperimentReasonCode` values; never pass free-form lane details into shared artifacts. Disagreement records contain only scoped atom IDs/labels in private artifacts.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/merchant/review.py tests/experiments/row_recovery/merchant/test_review.py
git commit -m "feat: audit grounded merchant atom proposals"
```

### Task 7: Add paired evaluation, private runner, and CLI

**Files:**
- Create: `src/ccparser/experiments/row_recovery/merchant/evaluation.py`
- Create: `src/ccparser/experiments/row_recovery/merchant/runner.py`
- Create in the finalization step: `src/ccparser/experiments/row_recovery/merchant/policy.py`
- Create: `src/ccparser/experiments/row_recovery/merchant/__main__.py`
- Create: `tests/experiments/row_recovery/merchant/test_evaluation.py`
- Create: `tests/experiments/row_recovery/merchant/test_runner.py`

**Interfaces:**

```python
class TrainingEvidenceContext(StrEnum):
    CURRENT_ONLY = "current_only"
    CURRENT_AND_OCR = "current_and_ocr"


class FrozenMerchantPolicy(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    feature_schema: FeatureSchema
    training_context: TrainingEvidenceContext
    epochs: Literal[12] = 12
    standalone_selector_enabled: bool
    minimum_margin_numerator: int | None = None
    minimum_margin_denominator: int | None = Field(default=None, gt=0)
    model_relative_path: PurePosixPath
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_identity: ProducerIdentity
    selector_identity: ProducerIdentity | None = None


class MerchantRunBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: SplitRunInputBinding
    current_annotations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_annotations_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


def load_merchant_policy(
    path: Path,
    *,
    private_root: Path,
    expected_sha256: str,
) -> FrozenMerchantPolicy: ...


def load_merchant_run_binding(
    path: Path,
    *,
    expected_sha256: str,
) -> MerchantRunBinding: ...
```

The policy is split-neutral. Its model path is safe, normalized, relative to the explicit private root, traversal/symlink-escape resistant, and authenticated by its independent model pin. Candidate identity binds model/features/epochs/labels/proposal/renderer/training schema but excludes margin and every dataset/prepared/gold/annotation/run pin. When `standalone_selector_enabled=true`, both exact margin fields and `selector_identity` are mandatory and the identity adds the chosen margin and control/audit policy. When false, all three are `None`; a candidate-only policy cannot smuggle in a margin or selector identity. A split-specific run binding authenticates evaluation inputs separately.

**Required metrics:**

- exact whole-case atom-label-map match on adjudicated cases, with inherently ambiguous cases reported as a separate count and excluded from supervised denominators;
- exact merchant atom set and rendered string through the shared evaluator;
- exact merchant/detail boundary map;
- atom precision/recall/F1 by label and non-`OUTSIDE` macro-F1 as diagnostics only;
- proposal/review/abstention counts by pre-registered margin;
- paired recovered failures and wrong control changes versus existing claims and shape-rule controls;
- recognition, candidate-generation, and candidate-selection ceilings through the shared oracle evaluator;
- grounding/immutable/schema/privacy/determinism violations;
- only the shared closed `EvaluationSlice` aggregates, joined from pinned `SourceRecord` inputs; and
- runtime/peak-memory aggregates.

- [ ] **Step 1: Write metric and split tests**

Cover exact denominators, `OUTSIDE` dominance, exact boundaries, inherently ambiguous annotations excluded from supervised denominators without changing inference, source/layout/temporal-family split rejection, development-only training, validation-only schema/margin selection, fixed 12-epoch enforcement, test-label rejection, missing shared slice reporting, oracle count conservation, and count-only zero denominators.

- [ ] **Step 2: Write runner/privacy tests**

Cover independent inventory/split-prepared/current-and-variant-annotation/training-manifest/model/policy/run-binding/interaction-approval pins, safe explicit OCR final-policy/run-binding/variant references, exact split-neutral candidate and optional selector identities, complete serialized candidate-batch proofs, ignored nonexisting output/model paths, no overwrite, model trained only from development (current-only or pre-registered current+OCR context), both feature schemas, fixed 12 epochs and margin grid, canonical repeated model/batch/prediction bytes, fresh-process selection without producer state, aggregate-only stdout/stderr with private sentinels and no private-derived hashes, and cleanup on failure. Prove the CLI never derives an expected model, policy, run-binding, or interaction-approval pin from the candidate file it is about to trust and never accepts a test split. Distinguish fixed training provenance from evaluation inputs: changing a development training manifest requires a newly verified model/policy provenance, but candidate identity changes only through the resulting model bytes/configuration; changing development/validation/test run-input pins never changes it. Cover the candidate-only policy invariant: selector flag false, no margin, no selector identity, raw batches still serialized, and case-level selector result always abstains. Evaluate `CURRENT` and augmented `OCR_VARIANT` as separate invocation contexts: the first gets one current batch and no variants; the second gets the current batch first plus the complete final-policy variant tuple and exactly one fingerprint-matched batch per variant in one selector call. Count each case exactly once in each available context, never once per OCR variant, and fail closed on a missing/reordered current batch or cross-variant disagreement. Cover the explicit OCR-unavailable mode: it accepts only the 12 current-only arms and rejects every OCR option, context, or fabricated placeholder.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_evaluation.py tests/experiments/row_recovery/merchant/test_runner.py
```

Expected: import failure because evaluation/runner modules do not exist.

- [ ] **Step 4: Implement fail-closed train/evaluate commands**

Support these exact local command shapes. The operator supplies pins from a separately reviewed private approval record; each command fails before reading private data when a pin is missing. The runner never computes its own expected pin from a candidate artifact:

```bash
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development atom-gold SHA-256}"
: "${ROW_DEVELOPMENT_ANNOTATIONS_SHA256:?set the independently reviewed development-annotation SHA-256}"
: "${ROW_TRAINING_MANIFEST_SHA256:?set the independently reviewed training-manifest SHA-256}"
: "${ROW_LANE_REVISION:?set the reviewed clean 40-character lane revision}"
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant validate-annotations \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/development.jsonl" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-annotations-sha256 "$ROW_DEVELOPMENT_ANNOTATIONS_SHA256" \
  --worktree-root . \
  --split development

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant train-classical \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/development.jsonl" \
  --training-manifest "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/training-manifest.json" \
  --model-out "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/models/perceptron-shape-v1.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --feature-schema merchant-atom-shape-v1 \
  --epochs 12 \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-annotations-sha256 "$ROW_DEVELOPMENT_ANNOTATIONS_SHA256" \
  --expected-training-manifest-sha256 "$ROW_TRAINING_MANIFEST_SHA256" \
  --expected-producer-revision "$ROW_LANE_REVISION" \
  --worktree-root .

: "${ROW_VALIDATION_ANNOTATIONS_SHA256:?set the independently reviewed validation-annotation SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation atom-gold SHA-256}"
: "${ROW_APPROVED_MODEL_SHA256:?set the independently reviewed candidate-model SHA-256}"
: "${ROW_APPROVED_POLICY_SHA256:?set the independently reviewed candidate-policy SHA-256}"
: "${ROW_APPROVED_RUN_BINDING_SHA256:?set the independently reviewed validation run-binding SHA-256}"
PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant evaluate \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
  --annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/validation.jsonl" \
  --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/candidates/shape-current-margin-1.json" \
  --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/validation-current-run.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --expected-model-sha256 "$ROW_APPROVED_MODEL_SHA256" \
  --expected-policy-sha256 "$ROW_APPROVED_POLICY_SHA256" \
  --expected-run-binding-sha256 "$ROW_APPROVED_RUN_BINDING_SHA256" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/runs/validation-shape-v1" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
  --expected-annotations-sha256 "$ROW_VALIDATION_ANNOTATIONS_SHA256" \
  --expected-training-manifest-sha256 "$ROW_TRAINING_MANIFEST_SHA256" \
  --expected-producer-revision "$ROW_LANE_REVISION" \
  --worktree-root . \
  --split validation
```

The exact CLI options are typed paths plus independent SHA pins; do not accept free-form Python/model/plugin entry points. `--dataset-root` plus `--split` resolves the exact `MerchantTextGold` file and verifies its digest through the independently pinned inventory; `--atom-gold` has its own independent pin. The private run binding contains the model fingerprint, feature schema, epoch count `12`, optional selector margin, both deterministic-control identities/fingerprints, label order, renderer revision, training-manifest fingerprint as separately authenticated provenance, and resulting candidate/optional-selector identities. The training-manifest fingerprint is not an input to either `ProducerIdentity`. The independently approved full-file binding pin is required at evaluation.

- [ ] **Step 5: Verify and commit the runner before touching private training data**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/merchant tests/experiments/row_recovery/merchant
git commit -m "test: freeze merchant atom experiment runner"
git status --short
```

Expected: all gates pass and the lane worktree is clean. Record that exact 40-character code revision inside the ignored approval workflow before training. Any later code/configuration edit invalidates every model and binding and restarts this task.

- [ ] **Step 6: Train current-only candidates, then the pre-registered OCR-augmented candidates**

First train `shape-v1` and `local-char-v1` three times from current development evidence using the exact `train-classical` shape above (change only the pre-registered feature schema and new output path). Require byte-identical model bytes per schema; a separate reviewer records candidate pins.

Then branch on the reviewed OCR lane status. If OCR reports `stop`, finish this step after the two repeated current-only models, record `ocr_context_available=false`, and never create/read an OCR annotation, interaction approval, augmented manifest, or `current_and_ocr` model. If OCR reports `include_in_bakeoff`, wait until its final-policy development variants and atom partitions freeze; authorized reviewers create a complete independently pinned merchant-role annotation file for those exact evidence fingerprints. Never translate current/sweep labels. The primary agent publishes the pinned development interaction approval, then train the pre-registered `current_and_ocr` arm three times for each feature schema:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed current development atom-gold SHA-256}"
: "${ROW_DEVELOPMENT_ANNOTATIONS_SHA256:?set the independently reviewed current development annotations SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256:?set the independently reviewed final-policy OCR development variants SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy OCR development variant atom-gold SHA-256}"
: "${ROW_OCR_DEVELOPMENT_VARIANT_ANNOTATIONS_SHA256:?set the independently reviewed OCR development annotations SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed OCR development run-binding SHA-256}"
: "${ROW_DEVELOPMENT_INTERACTION_APPROVAL_SHA256:?set the independently reviewed development interaction approval SHA-256}"
: "${ROW_AUGMENTED_TRAINING_MANIFEST_SHA256:?set the independently reviewed augmented training-manifest SHA-256}"
: "${ROW_LANE_REVISION:?set the reviewed clean merchant runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_MERCHANT_TRAIN_REPEAT in a b c; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant train-interaction \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --current-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/development.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-a/ocr/variants.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/development-policy/development.jsonl" \
    --variant-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/row_ocr/development-policy/development.jsonl" \
    --ocr-policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --ocr-run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-run.json" \
    --interaction-approval "$CCPARSER_ROW_EXPERIMENT_ROOT/interactions/approvals/development.json" \
    --training-manifest "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/training-current-and-ocr.json" \
    --model-out "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/models/candidates/shape-current-and-ocr-$ROW_MERCHANT_TRAIN_REPEAT.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --feature-schema merchant-atom-shape-v1 \
    --epochs 12 \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-current-annotations-sha256 "$ROW_DEVELOPMENT_ANNOTATIONS_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variant-annotations-sha256 "$ROW_OCR_DEVELOPMENT_VARIANT_ANNOTATIONS_SHA256" \
    --expected-ocr-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-ocr-run-binding-sha256 "$ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256" \
    --expected-interaction-approval-sha256 "$ROW_DEVELOPMENT_INTERACTION_APPROVAL_SHA256" \
    --expected-training-manifest-sha256 "$ROW_AUGMENTED_TRAINING_MANIFEST_SHA256" \
    --expected-producer-revision "$ROW_LANE_REVISION" \
    --worktree-root . \
    --split development
done
```

Repeat that exact loop for `merchant-atom-local-char-v1` with distinct new paths. In the OCR-available branch require byte-identical model bytes within all four schema×training-context arms; in the OCR-unavailable branch require it for the two current-only schema arms. Model files/pins remain private.

- [ ] **Step 7: Pre-register the complete model/context/margin grid before validation**

Before opening any validation annotation, freeze the branch-appropriate complete grid. With OCR available this is 24 bindings: two feature schemas × `{current_only, current_and_ocr}` development-trained models × `{0, 1/4, 1/2, 1, 2, 4}`. With OCR unavailable this is exactly 12 bindings: two current-only models × the same six margins; the manifest schema records `ocr_context_available=false` and rejects every `current_and_ocr` arm. Candidate identity excludes the margin; each selector identity adds it. Independently review/pin every model and binding, or one canonical manifest containing all full bindings and independent file pins. No validation result may create a new arm, epoch, threshold, feature, or training context.

- [ ] **Step 8: Evaluate the untouched grid on current and OCR validation contexts**

If OCR is available, after its validation variants and candidate-local atom gold freeze, authorized reviewers create/pin complete merchant-role annotations for those exact fingerprints. Evaluate the already pinned 24-arm manifest twice; the command trains nothing and permits no configuration override:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed current validation atom-gold SHA-256}"
: "${ROW_VALIDATION_ANNOTATIONS_SHA256:?set the independently reviewed current validation annotations SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256:?set the independently reviewed final-policy OCR validation variants SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy OCR validation variant atom-gold SHA-256}"
: "${ROW_OCR_VALIDATION_VARIANT_ANNOTATIONS_SHA256:?set the independently reviewed OCR validation annotations SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed OCR validation run-binding SHA-256}"
: "${ROW_VALIDATION_INTERACTION_APPROVAL_SHA256:?set the independently reviewed validation interaction approval SHA-256}"
: "${ROW_MERCHANT_CANDIDATE_MANIFEST_SHA256:?set the independently reviewed branch-appropriate candidate manifest SHA-256}"
: "${ROW_LANE_REVISION:?set the reviewed clean merchant runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_MERCHANT_EVALUATION_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant evaluate-grid \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --current-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/validation.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-a/ocr/variants.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/validation-policy/validation.jsonl" \
    --variant-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/row_ocr/validation-policy/validation.jsonl" \
    --ocr-policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --ocr-run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/validation-run.json" \
    --interaction-approval "$CCPARSER_ROW_EXPERIMENT_ROOT/interactions/approvals/validation.json" \
    --candidate-manifest "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/candidate-grid.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/runs/validation-grid-$ROW_MERCHANT_EVALUATION_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-current-annotations-sha256 "$ROW_VALIDATION_ANNOTATIONS_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variant-annotations-sha256 "$ROW_OCR_VALIDATION_VARIANT_ANNOTATIONS_SHA256" \
    --expected-ocr-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-ocr-run-binding-sha256 "$ROW_OCR_VALIDATION_RUN_BINDING_SHA256" \
    --expected-interaction-approval-sha256 "$ROW_VALIDATION_INTERACTION_APPROVAL_SHA256" \
    --expected-candidate-manifest-sha256 "$ROW_MERCHANT_CANDIDATE_MANIFEST_SHA256" \
    --expected-producer-revision "$ROW_LANE_REVISION" \
    --worktree-root . \
    --split validation
done
```

If OCR is unavailable, run the same `evaluate-grid` command twice against the pinned 12-arm manifest using only `--current-atom-gold`, `--current-annotations`, the common dataset/prepared/source inputs, and their independent pins. Omit all `--variants`, `--variant-*`, `--ocr-*`, and `--interaction-approval` options together; the command must reject empty placeholders or an OCR-capable manifest in this mode.

Require identical complete canonical model-reference, batch, prediction, oracle, and metric bytes. Evaluate every eligible policy separately in each available invocation context: `CURRENT` alone, and `OCR_VARIANT` as current evidence augmented by the complete ordered OCR variant set. Produce at most one selector prediction and one metric observation per case per invocation context. Derive `candidate_contexts` independently from safe grounded generation headroom in each context and derive `selector_contexts` independently from positive exact gain, zero wrong selected proposals/controls, and all hard gates in that same context; success in one context never enables the other. `candidate_contexts={OCR_VARIANT}` without `CURRENT` is valid when only augmentation has headroom because the mandatory current batch is an internal member of the augmented context, not admission of the separate current-only arm. Select the final binding from these context-indexed results. If at least one selector/context pair is eligible, maximize exact recovered failures jointly across all available pre-registered eligible contexts, then minimize proposals, prefer `current_only`, prefer `shape-v1`, and prefer the larger margin. A model's margin-independent candidate identity can remain interaction-eligible in only the contexts where its raw batches are safely grounded/deterministic with generation headroom. If no selector is eligible but at least one candidate model/context pair is eligible, freeze a candidate-only model by maximizing exact candidate-generation-oracle recoveries, then exact grounded raw merchant-candidate recall, minimizing raw candidate burden, preferring `current_only`, preferring `shape-v1`, and finally canonical candidate identity. Collapse all six margin bindings of that model to one candidate choice: margin is not consulted or stored, `standalone_selector_enabled=false`, and selector identity is absent. Selection chooses one already pinned selector binding or candidate identity plus its independently eligible context set; it is not retuning. Gold/annotation state never enters `predict()`, raw batch projection, or selector input.

- [ ] **Step 9: Commit the selected algorithm policy test-first and reproduce final artifacts**

Add a focused failing test that the tracked merchant policy exposes exactly one pre-registered feature-schema/training-context choice plus either one eligible margin with its standalone selector enabled or the explicit candidate-only state with no margin/selector identity, and that a private policy/run binding must match it. Observe RED, implement the minimum non-sensitive constants in `merchant/policy.py`, run focused GREEN and all tracked gates, then commit. Do not commit the model, pins, metrics, or corpus values:

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/merchant/test_runner.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/merchant/policy.py tests/experiments/row_recovery/merchant/test_runner.py
git commit -m "test: freeze merchant atom experiment policy"
git status --short
```

From that exact clean revision, retrain the chosen development arm three times into new paths. Use `train-classical` for `current_only` or, only when OCR is available, the exact `train-interaction` shape from Step 6 for `current_and_ocr`; the committed policy decides which command is legal and every other arm is rejected. Require identical model bytes, independently pin the common model, then construct/pin one split-neutral `FrozenMerchantPolicy` and separate development/validation `MerchantRunBinding` objects. The policy's model path/pin and candidate identity must match the reproduced model. An enabled selector identity adds only the committed margin/audit policy; a candidate-only policy has no margin or selector identity and `policy-run` emits raw batches plus case-level abstentions.

Before validation, run the final policy on development twice in new directories using the same branch-appropriate input shape and final model/policy identities. Use the development run binding, current development gold/annotations, and—only when available—the unchanged frozen OCR development variants, annotations, atom gold, policy, OCR run binding, and interaction approval. Require byte-identical candidate batches, predictions, oracle metrics, and verification flags. These runs establish development capabilities for the final revision; pre-commit grid artifacts cannot do so.

Then run the final policy on validation twice with new directories and the same frozen inputs used for grid evaluation. The block below is the OCR-available shape:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed current validation atom-gold SHA-256}"
: "${ROW_VALIDATION_ANNOTATIONS_SHA256:?set the independently reviewed current validation annotations SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256:?set the independently reviewed final-policy OCR validation variants SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy OCR validation variant atom-gold SHA-256}"
: "${ROW_OCR_VALIDATION_VARIANT_ANNOTATIONS_SHA256:?set the independently reviewed OCR validation annotations SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed OCR validation run-binding SHA-256}"
: "${ROW_VALIDATION_INTERACTION_APPROVAL_SHA256:?set the independently reviewed validation interaction approval SHA-256}"
: "${ROW_MERCHANT_FINAL_POLICY_SHA256:?set the independently reviewed final merchant policy SHA-256}"
: "${ROW_MERCHANT_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed merchant validation run-binding SHA-256}"
: "${ROW_MERCHANT_FINAL_MODEL_SHA256:?set the independently reviewed final model SHA-256}"
: "${ROW_MERCHANT_FINAL_REVISION:?set the reviewed clean final merchant-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_MERCHANT_FINAL_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.merchant policy-run \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --current-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/validation.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-a/ocr/variants.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/validation-policy/validation.jsonl" \
    --variant-annotations "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/annotations/row_ocr/validation-policy/validation.jsonl" \
    --ocr-policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --ocr-run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/validation-run.json" \
    --interaction-approval "$CCPARSER_ROW_EXPERIMENT_ROOT/interactions/approvals/validation.json" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/approvals/validation-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/merchant/runs/final-validation-$ROW_MERCHANT_FINAL_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-current-annotations-sha256 "$ROW_VALIDATION_ANNOTATIONS_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variant-annotations-sha256 "$ROW_OCR_VALIDATION_VARIANT_ANNOTATIONS_SHA256" \
    --expected-ocr-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-ocr-run-binding-sha256 "$ROW_OCR_VALIDATION_RUN_BINDING_SHA256" \
    --expected-interaction-approval-sha256 "$ROW_VALIDATION_INTERACTION_APPROVAL_SHA256" \
    --expected-policy-sha256 "$ROW_MERCHANT_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_MERCHANT_VALIDATION_RUN_BINDING_SHA256" \
    --expected-model-sha256 "$ROW_MERCHANT_FINAL_MODEL_SHA256" \
    --expected-producer-revision "$ROW_MERCHANT_FINAL_REVISION" \
    --worktree-root . \
    --split validation
done
```

When OCR is unavailable, use the same `policy-run` command twice with current validation gold/annotations, model, merchant policy/run binding, dataset/prepared/source inputs, and their independent pins, while omitting all variant, OCR-policy, OCR-run-binding, and interaction-approval options together. The final policy must be `CURRENT_ONLY`, and the command rejects empty placeholders or any `OCR_VARIANT` capability. Require byte-identical final candidate batches, predictions, oracle metrics, and verification flags. Also compare a canonical semantic projection of the reproduced final run with the exact validation-selected grid arm: after excluding only expected code-revision, producer-identity, model-path, model-digest, binding-digest, and run-directory fields, require identical feature schema/training context/margin, learned label weights, per-case candidate texts and atom sets, selector dispositions, oracle counts, and aggregate metrics. Any other drift is a hard stop; no parameter changes are allowed.

- [ ] **Step 10: Return the lane status without making a production claim**

Return execution status `stop` only on a hard split/privacy/grounding/immutable/schema/identity/model/determinism violation or no candidate-generation headroom across every context that was actually available. Otherwise return `include_in_bakeoff` with `candidate_producer=true`, `model_pin_required=true`, and `model_pin_verified=true` for every validated context. Enable the selector only in contexts with positive exact recovery, zero wrong selected proposals/control changes, and all hard gates; a disabled selector cannot discard the safe raw candidate producer. When OCR stopped, report only `CURRENT` capability and never fabricate an OCR artifact or context. The public lane verdict remains `continue_experiment` until the shared bake-off verifies baseline-correct controls in at least 60 distinct source-family clusters and 60 source documents, cluster-level rule-of-three upper bound `3 / control_cluster_count <= 0.05`, at least five exact recovered failures across at least three independent source/layout families, at least two percentage points safe exact-coverage gain, zero hard violations, and nonredundant factorial contribution. Insufficient support is `continue_experiment`, never promotion eligibility.

## Neural Follow-up Gate

Do not add a neural model to this lane. Write a separate dependency-isolated plan only if all of these are true on development/validation:

- annotations and fingerprints pass with no unresolved data defect;
- the perceptron produces at least five net exact recoveries over the best deterministic control across at least three independent source/layout families, with zero newly wrong controls;
- its fixed 12-epoch result leaves at least five validation selection misses after successful recognition and candidate generation, spanning at least three independent source/layout families;
- blinded private error review assigns at least 60% of those remaining selection misses to the closed category `CHARACTER_GEOMETRY_INTERACTION`, rather than missing OCR evidence, row grouping, label ambiguity, or immutable-preclaim error;
- the shared oracle independently confirms that selection, not recognition or candidate generation, is the limiting stage;
- at least 60 independent source-family control clusters, 60 source documents, three independent layout families, and 200 adjudicated merchant atoms exist for a grouped held-out comparison; and
- the expected incremental value justifies a new isolated environment and artifact distribution design.

Any neural follow-up remains local/offline, labels atoms rather than generating text, keeps weights ignored and hash-pinned, uses the same JSONL input/output contract, and makes no root dependency or production import change.

## Handoff Artifacts

The lane writes foundation/dataset/prepared/annotation/model/binding pins, repeat fingerprints, the selected private configuration, and detailed diagnostics only to a new ignored handoff manifest under the shared experiment root. The primary agent verifies that manifest locally; subagent messages and public documents must not repeat any private-derived hash.

The message handoff contains only the clean final-policy branch SHA, aggregate counts/rates/timings, closed reason codes, `dataset_pin_verified`, split-specific `prepared_pin_verified`, `private_binding_pin_verified`, `model_pin_required=true`, `model_pin_verified=true`, repeat/privacy booleans, explicit candidate/optional-selector capabilities and their actually validated `CURRENT`/`OCR_VARIANT` context sets, execution status `stop`/`include_in_bakeoff`, and public verdict `stop`/`continue_experiment`. It must not include learned weights, feature vocabulary, atom data, text, case/source IDs, private paths or hashes, financial values, family identifiers, or per-case errors.
