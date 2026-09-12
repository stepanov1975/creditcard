# Deterministic Row Profile Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether a deterministic, multi-label description-shape profile can expose the right generic extraction strategies for each row bundle and improve exact merchant recovery without a brittle flat row classifier or hard routing.

**Architecture:** Convert each frozen current-evidence case into scale-normalized, evidence-backed profile signals. Carry the existing structural axes through unchanged, run every applicable deterministic merchant-span strategy, rank strategies from the profile, and propose only when the grounded candidates have one uniquely supported result. The profiler describes extraction geometry and evidence shape; it does not predict `RowTag`, `ContinuationKind`, `FieldDisposition`, or `TransactionCategory`.

**Tech Stack:** Python 3.13, existing layout/ledger/description-proof primitives, shared row-recovery contracts, Pydantic v2, deterministic tuple scoring, canonical JSON Lines, pytest, Ruff, and mypy. No new dependency or learned parameter is introduced.

## Global Constraints

- Execute only in `.worktrees/exp-row-profiler` on branch `codex/exp-row-profiler`, created from the frozen foundation SHA.
- Exclusive tracked ownership is `src/ccparser/experiments/row_recovery/profiles/` and `tests/experiments/row_recovery/profiles/`. Do not edit foundation or production files.
- Set `CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments`. Read only the physically split development/validation source/case/label manifests, prepared inputs, and atom gold below that shared root; never open test manifests, their underlying source files, prepared test cases, or test labels. Write only to `runs/<run-id>/profiles/` and new create-without-overwrite bindings under `profiles/approvals/`, and never create a worktree-local artifact root.
- Treat each `ObservedSegmentAxes` record as immutable observed input. Preserve every segment's `row_tags` and `continuation_kinds` independently, and preserve the group-level baseline `field_disposition` and `transaction_category` independently.
- Do not create a flat `RowType`, predict one existing axis from another, or route a row to exactly one extractor. Profiles are multi-label evidence; strategies are ranked but all applicable strategies run.
- Profile features may use relative geometry, atom kind/source/confidence, Unicode script/direction/category, cell/line/segment membership, column role, and existing semantic claims. They may not use source/case IDs, paths, hashes, dates, amounts, exact merchant tokens, merchant dictionaries, issuer names, or corpus-specific constants.
- Every signal and strategy result must name its supporting atom IDs or geometry reason code. An unsupported boolean or unexplained score is invalid.
- A strategy may select/reorder source atoms only through the existing ledger renderer. It may not generate, correct, canonicalize, transliterate, or spell-check merchant text.
- Existing current description proof is the baseline strategy and remains available. The profiler may not propose a replacement when current proof is semantically complete and has no frozen recovery-trigger diagnostic; baseline exactness is used only by the evaluator, never by the selector.
- Primary metrics are exact merchant string, exact atom set where reviewed, recovered failures, wrong proposals, and wrong control changes. Candidate recall at ranks 1/3/5 and candidate burden are diagnostic; no signal-label F1 is claimed because the program does not create independent gold signal labels.
- Any wrong control change, financial/status mutation, ungrounded atom, nondeterminism, or split leak stops the lane.
- Before each commit run the repository's full Ruff format/check, mypy, and pytest gates through `/root/creditcard/.venv/bin/...`.

## Lane Interfaces

Create in `src/ccparser/experiments/row_recovery/profiles/contracts.py`:

```python
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from ccparser.experiments.row_recovery.contracts import (
    CandidateSupportLineage,
    ExperimentReasonCode,
    FrozenExperimentModel,
    GroundedCandidateBatch,
    MerchantPrediction,
    ObservedSegmentAxes,
    PreparedRowCase,
    ProducerIdentity,
    RowEvidenceVariant,
    SplitRunInputBinding,
)
from ccparser.models import TransactionCategory
from ccparser.layout.models import TableRegion
from ccparser.normalization_fields import FieldDisposition


class ProfileSignalKind(StrEnum):
    SINGLE_DESCRIPTION_SCOPE = "single_description_scope"
    MULTIPLE_DESCRIPTION_CLUSTERS = "multiple_description_clusters"
    MULTI_SEGMENT = "multi_segment"
    MULTI_LINE = "multi_line"
    MIXED_STRONG_DIRECTION = "mixed_strong_direction"
    TYPED_DETAIL_CLAIMS = "typed_detail_claims"
    UNCLAIMED_ALPHABETIC_RESIDUAL = "unclaimed_alphabetic_residual"
    REPEATED_SECONDARY_BAND = "repeated_secondary_band"
    OCR_DESCRIPTION_SOURCE = "ocr_description_source"
    LOW_CONFIDENCE_DESCRIPTION = "low_confidence_description"


class ExtractionStrategyKind(StrEnum):
    CURRENT_DESCRIPTION_PROOF = "current_description_proof"
    PRIMARY_CLUSTER = "primary_cluster"
    CLAIM_COMPLEMENT = "claim_complement"
    LINEWISE_PRIMARY = "linewise_primary"
    REPEATED_BAND_EXCLUSION = "repeated_band_exclusion"


class ProfileReasonCode(StrEnum):
    MISSING_DESCRIPTION_SCOPE = "missing_description_scope"
    AMBIGUOUS_DESCRIPTION_SCOPE = "ambiguous_description_scope"
    COMPETING_CLUSTERS = "competing_clusters"
    UNCLAIMED_RESIDUAL = "unclaimed_residual"
    AMBIGUOUS_DIRECTION = "ambiguous_direction"
    INSUFFICIENT_PROOF = "insufficient_proof"
    COMPETING_CANDIDATES = "competing_candidates"


class GeometrySupport(FrozenExperimentModel):
    segment_ordinal: int = Field(ge=0)
    region_ordinal: int = Field(ge=0)
    relative_bbox_basis_points: tuple[int, int, int, int]


class ProfileSignal(FrozenExperimentModel):
    kind: ProfileSignalKind
    atom_ids: frozenset[int] = frozenset()
    segment_ordinals: frozenset[int] = frozenset()
    geometry_support: tuple[GeometrySupport, ...] = ()
    reason_codes: tuple[ProfileReasonCode, ...] = ()


class RowExtractionProfile(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_axes: tuple[ObservedSegmentAxes, ...]
    field_disposition: FieldDisposition
    transaction_category: TransactionCategory | None
    signals: tuple[ProfileSignal, ...]
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class StrategyCandidate(FrozenExperimentModel):
    case_id: str
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy: ExtractionStrategyKind
    applicable: bool
    merchant_text: str | None
    merchant_atom_ids: frozenset[int]
    proof_key: tuple[int, int, int, int, int, int]
    reason_codes: tuple[ProfileReasonCode, ...]
    candidate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
```

The package exports:

```python
def profile_evidence(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None = None,
) -> RowExtractionProfile: ...


def profile_group_regions(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None = None,
) -> tuple[TableRegion, ...]: ...


def run_strategies(
    case: PreparedRowCase,
    profile: RowExtractionProfile,
    evidence: RowEvidenceVariant | None = None,
) -> tuple[StrategyCandidate, ...]: ...


def to_profile_candidate_batch(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None,
    candidates: tuple[StrategyCandidate, ...],
    candidate_identity: ProducerIdentity,
) -> GroundedCandidateBatch: ...


def select_profile_prediction(
    case: PreparedRowCase,
    evidence_variants: tuple[RowEvidenceVariant, ...],
    batches: tuple[GroundedCandidateBatch, ...],
    minimum_proof_key: tuple[int, int, int, int, int, int],
    selector_identity: ProducerIdentity,
) -> MerchantPrediction: ...


def to_experiment_reason(reason: ProfileReasonCode) -> ExperimentReasonCode: ...
```

`None` evidence means the frozen current-evidence atoms and `case_fingerprint`. The same batch adapter accepts an OCR variant later in the bake-off without changing profile semantics. Evaluate two closed invocation contexts: `CURRENT` is an empty `evidence_variants` tuple plus exactly one current-evidence batch; `OCR_VARIANT` is the final policy's complete ordered 1–4 variant tuple plus a batch tuple containing the current-evidence batch first and exactly one fingerprint-matched batch per variant. Thus `OCR_VARIANT` means current evidence augmented by OCR alternatives, not OCR replacing native evidence. It is legal for only `OCR_VARIANT` to have candidate/selector headroom: its mandatory current batch is internal to that augmented context and does not imply that `CURRENT` is independently admitted as a bake-off context. The batch projection converts every applicable `StrategyCandidate` into a shared grounded envelope plus typed `ProfileSelectionProof(strategy, proof_key)`. It derives `CandidateSupportLineage.EXISTING_DESCRIPTION_PROOF` for `CURRENT_DESCRIPTION_PROOF` and `PROFILE_GEOMETRY` for every other profile strategy; callers cannot override this mapping. The selector validates this mapping, consumes only the explicit case/variants and canonical reloaded batches, and emits at most one prediction per case per invocation context—never one metric observation per OCR variant and never live profiler state. It abstains on unresolved cross-variant merchant disagreement. Equal text may survive only when every contributing variant is independently grounded; the chosen evidence-specific envelope is the uniquely strongest proof, or current-before-frozen-OCR order only after proof and rendered text are equal. Atom exactness remains scoped to that chosen evidence fingerprint.

---

### Task 1: Define evidence-backed multi-label profiles

**Files:**
- Create: `src/ccparser/experiments/row_recovery/profiles/__init__.py`
- Create: `src/ccparser/experiments/row_recovery/profiles/contracts.py`
- Create: `tests/experiments/row_recovery/profiles/test_contracts.py`

- [ ] **Step 1: Write profile contract tests**

Cover closed signal/strategy/reason vocabularies, an exhaustive `ProfileReasonCode` to shared `ExperimentReasonCode` mapping, immutable/extra-forbid models, stable signal ordering, structured geometry support for support-free signals, duplicate signal rejection, base-case/evidence/protected-fingerprint scoping, an exact six-component proof key with the first five components limited to `0/1` and nonnegative agreement count, candidate fingerprinting, exact carrying of observed axes/outcome fields, and canonical serialization. Shared predictions must never contain a lane-local reason.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_contracts.py
```

Expected: collection/import failure because the profile package does not exist.

- [ ] **Step 3: Implement minimum typed contracts**

Use a fixed enum order only for deterministic serialization/sorting. Validators must reject merchant text without atoms, atoms without text, any candidate atom outside the referenced evidence fingerprint, or mismatched protected outcomes. Never append the strategy enum to `proof_key`; semantic uniqueness compares proof only. For descending proof order, stable output sorting uses `tuple(-component for component in proof_key) + (strategy.value, candidate_fingerprint)` separately.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/profiles tests/experiments/row_recovery/profiles
git commit -m "test: define deterministic row profiles"
```

### Task 2: Extract scale-normalized profile signals without leakage

**Files:**
- Create: `src/ccparser/experiments/row_recovery/profiles/features.py`
- Create: `src/ccparser/experiments/row_recovery/profiles/evidence.py`
- Create: `src/ccparser/experiments/row_recovery/profiles/profiler.py`
- Create: `tests/experiments/row_recovery/profiles/test_profiler.py`

**Interfaces:**

```python
class AtomShape(FrozenExperimentModel):
    atom_id: int
    relative_x0: int
    relative_y0: int
    relative_x1: int
    relative_y1: int
    script_mask: int
    unicode_category_mask: int
    strong_direction_mask: int
    confidence_bucket: int
    segment_ordinal: int
    column_indices: tuple[int, ...]
    is_preclaimed: bool


def atom_shapes(
    case: PreparedRowCase,
    evidence: RowEvidenceVariant | None = None,
) -> tuple[AtomShape, ...]: ...
```

Coordinates are integer basis points relative to each atom's owning row and recorded region, so cross-page segments never share an artificial union box; confidence uses fixed buckets. No floating comparison or raw token value enters a rank key.

- [ ] **Step 1: Write invariance and leakage tests**

Cover uniform scale/translation invariance, atom-order determinism, Hebrew/Latin/mixed direction masks, confidence bucket boundaries, current versus OCR source signal, exact atom-to-segment/region/page mapping, existing claim support, multiple clusters/lines, and byte-for-byte preservation of `segment_axes`, `field_disposition`, `transaction_category`, and protected-outcome fingerprint. For an OCR variant, prove `profile_group_regions()` replaces every participating baseline row exactly once with its corresponding shadow row across same- and cross-page regions, rejects missing/ambiguous/cardinality-mismatched substitution, changes current-proof/repeated-band results when shadow text or geometry changes, and leaves baseline regions byte-identical. Add a source-code AST test rejecting access to `source_id`, `case_id`, `source_relative_path`, `source_sha256`, `merchant_text`, or `TransactionCategory` in feature extraction.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_profiler.py
```

Expected: import failure because feature extraction/profiling does not exist.

- [ ] **Step 3: Implement the minimum profiler**

Reuse ledger cluster/line rendering and existing semantic claims. Each signal is independently derived and may coexist with any other. Sort signals by enum value and structured support. For current evidence, copy the exact typed axes, group regions, and baseline outcome fields from the prepared case. For an OCR variant, `profile_group_regions()` creates immutable candidate-local region copies by uniquely substituting the recorded shadow rows; all group/neighbor-dependent proof must consume those copies, never baseline row text/geometry. Preserve the reviewed row-tag and continuation-kind sets while taking only the variant's explicitly recorded segment-region mapping, base direction, and direction-evidence atom IDs; validate equal cardinality and bind the result to the variant fingerprint. Never infer one structural axis from another, fingerprint in place of typed fields, or reinterpret the baseline outcome.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/profiles/evidence.py src/ccparser/experiments/row_recovery/profiles/features.py src/ccparser/experiments/row_recovery/profiles/profiler.py tests/experiments/row_recovery/profiles/test_profiler.py
git commit -m "feat: profile row extraction evidence"
```

### Task 3: Implement independent grounded extraction strategies

**Files:**
- Create: `src/ccparser/experiments/row_recovery/profiles/strategies.py`
- Create: `tests/experiments/row_recovery/profiles/test_strategies.py`

**Strategy contracts:**

- `CURRENT_DESCRIPTION_PROOF`: reproduce the pinned existing description result and its atoms.
- `PRIMARY_CLUSTER`: select one unique alphabetic primary cluster inside the description scope after existing non-description claims.
- `CLAIM_COMPLEMENT`: render the exact residual description-scope atom complement only when it is one connected logical span.
- `LINEWISE_PRIMARY`: select one unique primary cluster per logical line/segment and render in existing base direction.
- `REPEATED_BAND_EXCLUSION`: remove a secondary description band only when equivalent geometry occurs in at least two other rows in that segment's recorded region and is already supported as typed non-merchant detail.

- [ ] **Step 1: Write one focused synthetic test group per strategy**

For each strategy cover applicable exact result, inapplicable shape, competing candidates, mixed direction, punctuation, continuation ordering, claimed date/amount/reference/location exclusion, unknown residual, and exact atom grounding. Add adversarial tests proving numeric/financial atoms and atoms outside the description scope cannot enter a candidate.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_strategies.py
```

Expected: import failure because `strategies.py` does not exist.

- [ ] **Step 3: Implement all strategies as independent pure functions**

Each function returns applicable/inapplicable plus atoms and closed reason codes. It may consume profile signals but may not inspect labels. Return all results in fixed enum order; do not short-circuit after the first candidate.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/profiles/strategies.py tests/experiments/row_recovery/profiles/test_strategies.py
git commit -m "feat: generate grounded profile candidates"
```

### Task 4: Rank all applicable strategies and abstain on disagreement

**Files:**
- Create: `src/ccparser/experiments/row_recovery/profiles/ranking.py`
- Create: `tests/experiments/row_recovery/profiles/test_ranking.py`

**Proof policy:** Compute a tuple of generic proof strength, never a fitted scalar:

```text
description-proof completeness
exact source evidence present
no unclaimed alphabetic residual
no competing cluster
typed-detail proof retained
cross-strategy text agreement count
```

`proof_key` contains only those semantic proof components. Stable descending output sorting uses `tuple(-component for component in proof_key) + (strategy.value, candidate_fingerprint)` after proof is computed; Python tuples cannot be negated. Candidate uniqueness and disagreement compare `proof_key` without the sort tie-break.

Pre-register exactly four component-wise minimum proof candidates for development: `(1,1,0,0,0,1)`, `(1,1,1,0,0,1)`, `(1,1,1,1,0,1)`, and `(1,1,1,1,1,1)`. A candidate clears a threshold only when every component is greater than or equal to the matching component; never use Python tuple lexicographic comparison for threshold eligibility. The agreement component may exceed one.

- [ ] **Step 1: Write ranking/selection tests**

Cover ranking independent of input order, exact descending component-wise proof sorting with the explicit negated-component key, all strategies always executed and retained, mandatory current-proof baseline, baseline-complete preservation, two strategies agreeing, a higher-proof unique result, equal-proof disagreement that remains an abstention regardless of enum order, lower-proof conflicting strings that still block unique support, competing atom sets rendering the same text, inapplicable strategies, and deterministic abstention reason order. Cover the closed proof-to-support-lineage mapping and reject a forged lineage. Cover `CURRENT` selection as one current batch with no variants and augmented `OCR_VARIANT` selection as the complete 1–4 variant tuple with the current batch first plus one fingerprint-matched batch per variant; reject missing current, duplicate, extra, reordered-policy, or cross-case batches. Score exactly once per case per invocation context, abstain on cross-variant text disagreement, and allow the fixed current-before-OCR policy-order tie-break only after proof and rendered text are equal and every candidate is independently grounded. Round-trip all shared candidate batches through canonical bytes and select in a fresh object/process with only case, explicit variants, batches, and selector identity; reject altered strategy/proof/candidate identities or any attempt to consult producer-call state. A non-baseline proposal must be uniquely supported and must not leave meaningful unclaimed description atoms.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_ranking.py
```

Expected: import failure because `ranking.py` does not exist.

- [ ] **Step 3: Implement tuple ranking and fail-closed selection**

Never use a gold label or exact token in ranking. Run and persist every strategy, with `CURRENT_DESCRIPTION_PROOF` mandatory, then project all applicable source-grounded results to one immutable `GroundedCandidateBatch` per evidence fingerprint. Any applicable grounded strategy producing a distinct merchant string blocks a unique-support proposal; score may order review but may not hide disagreement. If two distinct strings share maximal proof within a fingerprint, or surviving fingerprints disagree on text, abstain before applying the deterministic sort key. If current proof is semantically complete and has no frozen recovery trigger, return an abstention rather than a redundant proposal. The pure selector validates and consumes only serialized typed proofs and emits one case-level result across the whole supplied context. Retain additional profile-local detail only in private artifacts and use the exhaustive `to_experiment_reason()` mapping for shared predictions. Strategy-set ablations are diagnostic reports only and never feed selection.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/profiles/ranking.py tests/experiments/row_recovery/profiles/test_ranking.py
git commit -m "feat: rank row extraction strategies"
```

### Task 5: Add oracle, runner, and frozen profile policy

**Files:**
- Create: `src/ccparser/experiments/row_recovery/profiles/runner.py`
- Create in the finalization step: `src/ccparser/experiments/row_recovery/profiles/policy.py`
- Create: `src/ccparser/experiments/row_recovery/profiles/__main__.py`
- Create: `tests/experiments/row_recovery/profiles/test_runner.py`

**Interfaces:**

```python
class ProfileRankingDiagnostics(FrozenExperimentModel):
    eligible_cases: int
    gold_generated_by_any_strategy: int
    gold_ranked_first: int
    gold_recalled_at_three: int
    gold_recalled_at_five: int
    generation_misses: int
    ranking_misses: int
    total_applicable_candidates: int
    maximum_candidates_per_case: int


class FrozenProfilePolicy(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    strategy_schema: Literal["all-grounded-strategies-v1"]
    standalone_selector_enabled: bool
    minimum_proof_key: tuple[int, int, int, int, int, int] | None = None
    foundation_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_identity: ProducerIdentity
    selector_identity: ProducerIdentity | None = None


class ProfileRunBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    policy_or_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: SplitRunInputBinding


class ProfilePolicyManifest(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    policies: tuple[
        FrozenProfilePolicy,
        FrozenProfilePolicy,
        FrozenProfilePolicy,
        FrozenProfilePolicy,
    ]


def load_profile_policy_manifest(
    path: Path,
    *,
    expected_sha256: str,
) -> ProfilePolicyManifest: ...


def load_profile_policy(
    path: Path,
    *,
    expected_sha256: str,
) -> FrozenProfilePolicy: ...


def load_profile_run_binding(
    path: Path,
    *,
    expected_sha256: str,
) -> ProfileRunBinding: ...


def run_profile_experiment(
    dataset: LoadedDataset,
    cases: tuple[PreparedRowCase, ...],
    atom_labels: tuple[MerchantAtomGold, ...],
    output_dir: Path,
    *,
    policy: FrozenProfilePolicy,
) -> tuple[OracleStageMetrics, ProfileRankingDiagnostics, AggregateMetrics]: ...
```

Every development-manifest member has `standalone_selector_enabled=true`, one of the four pre-registered thresholds, and its matching selector identity. A final candidate-only policy has the flag false and both threshold and selector identity `None`; its raw candidate identity/bytes remain unchanged, and case-level selection always abstains. Validators reject every other combination.

- [ ] **Step 1: Write runner and privacy tests**

Cover the exact four-selector development manifest, candidate-only final-policy invariant, final-development requiring an independently pinned split-neutral policy plus development run binding, validation requiring the same policy plus validation run binding, shared dataset/prepared/atom-gold loaders, independently pinned interaction approval with safe explicit references, missing or self-derived expected-pin rejection, sealed test rejection, pinned `SourceRecord` joins and closed `EvaluationSlice` output, mandatory execution/retention of every strategy, shared recognition/generation/selection oracle stages, recall at ranks 1/3/5, candidate burden, exact carried axes/outcome preservation, canonical candidate/optional-selector identity derivation and dirty/stale-revision rejection, exact equality between loaded candidate identity and every raw candidate plus any selector identity and emitted predictions, proof that producer identities exclude split-input pins, canonical profile/candidate/prediction artifacts, repeated byte identity, aggregate-only output with no private-derived hashes, and cleanup on error. Prove that changing the minimum proof key cannot suppress a disagreeing candidate and that candidate-only policy still emits the same raw batches plus case-level abstentions. For OCR context, prove the runner feeds the complete final-policy variant set to one selector call per case, preserves one batch per fingerprint, and increments every case-level denominator once rather than once per variant.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_runner.py
```

Expected: import failure because the runner does not exist.

- [ ] **Step 3: Implement development analysis and stop gate**

The CLI calls shared `load_dataset()`, `load_prepared_cases()`, and `load_atom_gold()` with independently supplied expected pins, loads the four-policy manifest for development or `load_profile_policy()` for validation, then independently loads the split-specific `ProfileRunBinding` before invoking the typed runner. It may not compute an expected pin from any candidate artifact. Derive the raw-candidate identity from the strategy, evidence-adapter, renderer, and candidate/proof schemas plus foundation revision; it deliberately excludes `minimum_proof_key` and every dataset/prepared/gold/run pin. Derive the selector identity from that candidate identity plus exact threshold, disagreement policy, and selector schema, again excluding run inputs. The four development policies therefore share one candidate identity/candidate bytes while carrying distinct selector identities. Set `producer_revision` to the exact clean lane HEAD, verify HEAD/cleanliness against the expected revision, and reject any serialized mismatch. The runner writes private profiles and every raw grounded candidate before selection, then uses the shared evaluator/oracle. Zero current-evidence recognition/generation recovery disables only that context in the final lane capability binding; it does not prune the producer before its pre-registered OCR-variant interaction run. Global strategy ablations may be reported privately, but every evaluated selector receives every applicable candidate.

Support these exact commands, with expected pins supplied from a separately reviewed private approval record:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development atom-gold SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_BINDING_SHA256:?set the independently reviewed development manifest SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed development run-binding SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_REVISION:?set the reviewed clean development-runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.profiles develop \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --policy-manifest "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/development.json" \
  --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/development-run.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-a/profiles" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-policy-manifest-sha256 "$ROW_PROFILE_DEVELOPMENT_BINDING_SHA256" \
  --expected-run-binding-sha256 "$ROW_PROFILE_DEVELOPMENT_RUN_BINDING_SHA256" \
  --expected-producer-revision "$ROW_PROFILE_DEVELOPMENT_REVISION" \
  --worktree-root . \
  --split development
```

Use a new empty `development-b` run directory for the repeat. This phase executes only `develop`, which accepts only `development`; the final-policy `final-develop` and validation commands and their not-yet-created pins appear in Step 7. `final-develop` accepts only `development`, `validate` only `validation`, and none accepts `test`.

- [ ] **Step 4: Verify and commit the generic runner before private execution**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/profiles tests/experiments/row_recovery/profiles
git commit -m "test: freeze row profile experiment runner"
git status --short
```

Expected: all gates pass and the worktree is clean. Record the exact code revision in the ignored development binding. Any later code/configuration edit invalidates outputs made by that revision.

- [ ] **Step 5: Run the preliminary current-evidence development analysis**

From the exact clean development-runner revision, construct the four pre-registered candidate bindings without opening development labels, place them in one canonical `ProfilePolicyManifest`, and independently review/pin it. Run the exact development command twice into separate empty ignored directories and require byte-identical profiles, candidates, predictions, and aggregate metrics. Record the current-context result, but do not freeze the final threshold until the pre-registered OCR-variant development context is available. `CURRENT_DESCRIPTION_PROOF` and every other strategy remain enabled regardless of threshold, and every distinct applicable string participates in disagreement.

- [ ] **Step 6: Evaluate frozen OCR development variants twice and choose one policy**

Branch on the OCR lane's reviewed execution status. If OCR reports `include_in_bakeoff`, the primary agent gives this lane only the exact frozen development variants and candidate-local atom gold, and the lane runs all four already registered profile policies over current plus the complete OCR variant set. If OCR reports `stop`, no OCR policy, variant, atom-gold, run-binding, or interaction-approval path is created or passed: choose among the same four policies using the repeated current-development artifacts from Step 5, record `ocr_context_available=false`, and continue to Step 7. In either branch, do not add a threshold or strategy after seeing results.

For the OCR-available branch use:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_BINDING_SHA256:?set the independently reviewed profile development manifest SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed profile development run-binding SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_REVISION:?set the reviewed clean profile runner revision}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256:?set the independently reviewed final-policy OCR development variants SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy OCR development variant atom-gold SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed OCR development run-binding SHA-256}"
: "${ROW_DEVELOPMENT_INTERACTION_APPROVAL_SHA256:?set the independently reviewed development interaction-approval SHA-256}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_PROFILE_INTERACTION_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.profiles interact-develop \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/development-policy/development.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-a/ocr/variants.jsonl" \
    --ocr-policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --ocr-run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-run.json" \
    --interaction-approval "$CCPARSER_ROW_EXPERIMENT_ROOT/interactions/approvals/development.json" \
    --policy-manifest "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/development.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/development-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/profile-interaction-development-$ROW_PROFILE_INTERACTION_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256" \
    --expected-ocr-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-ocr-run-binding-sha256 "$ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256" \
    --expected-interaction-approval-sha256 "$ROW_DEVELOPMENT_INTERACTION_APPROVAL_SHA256" \
    --expected-policy-manifest-sha256 "$ROW_PROFILE_DEVELOPMENT_BINDING_SHA256" \
    --expected-run-binding-sha256 "$ROW_PROFILE_DEVELOPMENT_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_PROFILE_DEVELOPMENT_REVISION" \
    --worktree-root . \
    --split development
done
```

Require identical complete canonical bytes and one case-level selector result per case across the complete variant tuple. Reject the lane on any hard artifact failure. For each of the four thresholds, derive its selector-eligible context set using the same gate later used by the handoff: positive exact selected gain, zero wrong selected proposals, zero wrong control changes, and all context gates. If at least one threshold has a nonempty eligible set, choose by most total exact recovered failures across only its eligible available contexts, most eligible contexts, fewest proposals there, then the stricter tuple. Freeze that threshold and later enable its selector only in those validation-cleared contexts. If none is eligible but the shared oracle shows safe grounded candidate-generation headroom, freeze an explicit candidate-only policy with no threshold or selector identity; candidate generation/burden then chooses nothing because all four manifests share identical raw candidate bytes. Apply this rule to current+OCR contexts when OCR is available and current only otherwise. Context-specific strategy ablations are diagnostic and cannot change the strategy set.

- [ ] **Step 7: Commit the frozen policy and validate current evidence twice**

First add a focused failing test that `profiles/policy.py` exposes the selected pre-registered strategy schema plus either one eligible proof threshold/selector state or the explicit candidate-only state with no threshold/selector identity, and that a private policy/run binding must match those constants. Run the focused test and observe RED because the module does not exist. Implement only those non-sensitive constants, run focused GREEN and all tracked gates, and commit; do not precompute final identities or private run bindings before that commit. Require a clean worktree, derive the split-neutral final candidate identity and any enabled selector identity from the new exact HEAD and canonical policy content, create one pure final policy plus separate development and validation run bindings with their split-specific pins, and independently review/pin all three. Context enablement is recorded later in the lane verification binding and never changes either producer identity.

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/profiles/test_runner.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/profiles/policy.py tests/experiments/row_recovery/profiles/test_runner.py
git commit -m "test: freeze deterministic row profile policy"
git status --short
```

From that exact final-policy revision, replay development twice into new directories before validation. For the current-only branch use the phase-local command below. When OCR is available, instead replay the exact Step 6 `interact-develop` command with `--policy`/`--expected-policy-sha256` replacing the manifest options, `profiles/approvals/development-final-run.json` plus its independent pin replacing the preliminary run binding, the final-policy revision, and the unchanged pinned OCR policy/run/variant/gold/interaction inputs. When OCR is unavailable, omit every OCR option rather than passing empty placeholders. Require byte-identical final-policy development profiles, batches, predictions, oracle metrics, and verification flags. These replays—not the pre-commit grid outputs—establish the final producer and selector identities used by the handoff.

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development atom-gold SHA-256}"
: "${ROW_PROFILE_FINAL_POLICY_SHA256:?set the independently reviewed final profile policy SHA-256}"
: "${ROW_PROFILE_DEVELOPMENT_FINAL_RUN_BINDING_SHA256:?set the independently reviewed final development run-binding SHA-256}"
: "${ROW_PROFILE_VALIDATION_REVISION:?set the reviewed clean final-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_PROFILE_FINAL_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.profiles final-develop \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/development-final-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/profile-final-current-development-$ROW_PROFILE_FINAL_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-policy-sha256 "$ROW_PROFILE_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_PROFILE_DEVELOPMENT_FINAL_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_PROFILE_VALIDATION_REVISION" \
    --worktree-root . \
    --split development
done
```

Before validation, compare the repeated final-development output with the exact development arm bound by the selection record. Exclude only expected code revision, producer/candidate/batch/prediction/profile fingerprints, policy/run-binding digests, and run paths. Require identical profile signals, strategy applicability/proof keys, candidate texts/atom sets/source boxes, protected outcomes, candidate-generation oracle counts, and aggregate raw-candidate burden. When a selector is enabled, also require identical threshold, case dispositions, selected grounding, selection-oracle counts, and aggregate selected metrics. For a candidate-only final policy, require the raw projection above to match the canonical selected-manifest candidate bytes semantically and require all final selector outputs to abstain; do not compare them with a development selector's proposals. Any other drift hard-stops before validation.

The phase-local current-validation command is:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation atom-gold SHA-256}"
: "${ROW_PROFILE_FINAL_POLICY_SHA256:?set the independently reviewed final profile policy SHA-256}"
: "${ROW_PROFILE_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed validation run-binding SHA-256}"
: "${ROW_PROFILE_VALIDATION_REVISION:?set the reviewed clean final-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_PROFILE_FINAL_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.profiles validate \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/validation-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/profile-final-current-validation-$ROW_PROFILE_FINAL_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-policy-sha256 "$ROW_PROFILE_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_PROFILE_VALIDATION_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_PROFILE_VALIDATION_REVISION" \
    --worktree-root . \
    --split validation
done
```

- [ ] **Step 8: Evaluate frozen OCR validation variants twice**

If OCR was unavailable in Step 6, skip this step, record only `CURRENT` in the candidate/selector context sets, and do not create or reference OCR artifacts. Otherwise, after the OCR lane freezes and independently pins its validation variants and atom gold, evaluate the already committed profile policy without retuning:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation current atom-gold SHA-256}"
: "${ROW_PROFILE_FINAL_POLICY_SHA256:?set the independently reviewed final profile policy SHA-256}"
: "${ROW_PROFILE_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed profile validation run-binding SHA-256}"
: "${ROW_PROFILE_VALIDATION_REVISION:?set the reviewed clean final profile-policy revision}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256:?set the independently reviewed final-policy OCR validation variants SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy OCR validation variant atom-gold SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed OCR validation run-binding SHA-256}"
: "${ROW_VALIDATION_INTERACTION_APPROVAL_SHA256:?set the independently reviewed validation interaction-approval SHA-256}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_PROFILE_INTERACTION_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.profiles interact-validate \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/validation-policy/validation.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-a/ocr/variants.jsonl" \
    --ocr-policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --ocr-run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/validation-run.json" \
    --interaction-approval "$CCPARSER_ROW_EXPERIMENT_ROOT/interactions/approvals/validation.json" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/profiles/approvals/validation-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/profile-interaction-validation-$ROW_PROFILE_INTERACTION_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256" \
    --expected-ocr-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-ocr-run-binding-sha256 "$ROW_OCR_VALIDATION_RUN_BINDING_SHA256" \
    --expected-interaction-approval-sha256 "$ROW_VALIDATION_INTERACTION_APPROVAL_SHA256" \
    --expected-policy-sha256 "$ROW_PROFILE_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_PROFILE_VALIDATION_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_PROFILE_VALIDATION_REVISION" \
    --worktree-root . \
    --split validation
done
```

Require identical complete canonical bytes and reject any OCR/profile identity, evidence fingerprint, split, or policy mismatch. This step may disable a capability/context but may not edit code or policy.

- [ ] **Step 9: Return the lane verdict**

Return execution status `stop` only for a split/privacy/invariant/grounding/determinism failure or no generation headroom across every context that was actually available. Otherwise return `include_in_bakeoff` with `candidate_producer=true` for each validated context. `candidate_contexts={OCR_VARIANT}` without `CURRENT` is valid when only the augmented context has headroom; its serialized augmented batches still include the mandatory current batch. Set `standalone_selector=true` only for a context/policy with positive exact gain and zero wrong selected proposals/control changes; a failing selector is disabled without discarding immutable raw candidates. If validation disables every context for a development-declared selector, keep the frozen policy declaration for audit but hand off no enabled selector identity or context, and require the bake-off never to construct it. When OCR stopped, report only `CURRENT` capabilities and do not manufacture `OCR_VARIANT` evidence. The public lane verdict remains `continue_experiment` until shared support minima and the factorial bake-off pass. Include aggregate counts and pin/repeat/privacy verification booleans only.

## Handoff Artifacts

The lane hands the primary agent its clean branch SHA, foundation code SHA, `dataset_pin_verified=true`, split-specific `prepared_pin_verified=true`, `private_binding_pin_verified=true`, `model_pin_required=false`, `model_pin_verified=false`, `repeated_outputs_identical=true`, `privacy_check_passed=true`, profile oracle counts by current/OCR context, exact shared metrics, runtime aggregate, candidate identity, optional policy-declared selector identity, optional validation-enabled selector identity, `candidate_producer` and optional `standalone_selector` capability flags with validated evidence contexts, execution status `stop`/`include_in_bakeoff`, and public verdict `stop`/`continue_experiment`. It must not include private hashes, row text, atom data, IDs, paths, or per-case diagnostics.
