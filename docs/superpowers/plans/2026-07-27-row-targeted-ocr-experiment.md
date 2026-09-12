# Row-Targeted OCR Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether OCR on tightly bounded transaction-row images creates more exact, source-grounded merchant evidence than the existing digital/page OCR evidence, and whether a conservative consensus selector can recover failures without changing correct rows.

**Architecture:** Read the frozen `PreparedRowCase` records and original private PDF bytes, derive deterministic row and description-band clips, and run a development-only Tesseract configuration sweep. Each OCR result becomes a separate `RowEvidenceVariant`: immutable baseline non-description atoms plus candidate-local OCR atoms projected into the unique existing description scope. The baseline case is never mutated. Existing description proof runs in shadow mode on each variant, and a selector proposes only uniquely supported cross-configuration consensus; otherwise it abstains.

**Tech Stack:** Python 3.13, PyMuPDF, the repository's traced Tesseract execution and TSV parser, shared row-recovery contracts, SHA-256 caches, pytest, Ruff, and mypy.

## Global Constraints

- Execute this plan only in `.worktrees/exp-row-ocr` on branch `codex/exp-row-ocr`, created from the exact frozen foundation SHA.
- Exclusive tracked ownership is `src/ccparser/experiments/row_recovery/ocr/` and `tests/experiments/row_recovery/ocr/`. Do not edit shared foundation files or production parser/OCR/layout modules.
- Set `CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments`. Read only the physically split development/validation source/case/label manifests, prepared cases, and atom gold below its `dataset/`, `prepared/`, and `atom-gold/` children; never open test manifests, their underlying source files, prepared test cases, or test labels. Runner code writes only to `runs/<run-id>/ocr/`, `cache/ocr/`, and new create-without-overwrite bindings under `ocr/approvals/`, while authorized human review may write independently pinned variant partitions only to `atom-gold/variants/row_ocr/<run-id>/`. Do not create a worktree-local artifact root.
- Development chooses the matrix and thresholds; validation evaluates the frozen choice; the primary agent alone runs sealed test later.
- Preserve the baseline as a separate evidence variant. Do not copy baseline description atoms into OCR variants, merge OCR words into `PageEvidence`, append them to the prepared baseline ledger, or overwrite digital evidence.
- Each OCR variant may reuse baseline non-description atoms and claims only to keep financial/date evidence immutable. All description-scope atoms in that variant come from exactly one OCR configuration.
- Require one unique existing `ColumnRole.DESCRIPTION` scope. If it is absent or ambiguous, emit an OCR-lane abstention; do not expand into amount/date columns.
- Run full-row OCR to give Tesseract context, but retain only words whose centers project into the description scope. A description-band crop is the narrower comparison arm.
- Never accept an OCR candidate because it resembles a merchant dictionary entry. Text must be copied from OCR atoms, and exact boxes/configuration/evidence fingerprints must accompany it.
- `missing_description_cell`, `missing_description_evidence`, `ambiguous_description_detail`, `ambiguous_description_continuation`, and `ambiguous_mixed_description_direction` are generic trigger evidence, not merchant/layout-specific exceptions.
- Forced control sweeps are evaluation-only. A baseline-complete row that does not meet the frozen trigger must always abstain in simulated recovery mode even if an OCR variant differs.
- Exact merchant string and source grounding are primary for every OCR variant. Exact atom set is co-primary only for variants with an independently reviewed `MerchantAtomGold`; report other variants as atom-exact-not-evaluated. OCR character error rate, recognized-gold oracle coverage, runtime, and cache rate are diagnostic.
- Before each commit run all four repository verification commands from the worktree using `/root/creditcard/.venv/bin/...`.

## Experiment Matrix

The development oracle sweep evaluates these fixed factors:

| Factor | Values |
|---|---|
| Crop | `full_row`, `description_band` |
| Vertical boundary | neighbor midpoint with `0.00` or `0.25 × median segment height` inward-safe padding |
| DPI | `300`, `450` |
| Page segmentation | Tesseract PSM `6`, `7` |
| Language | `heb+eng`, `eng` for every development case |

Clip padding is clamped to the page and may never cross the midpoint to an adjacent non-bundle row. The full matrix is development-only. Freeze at most four Pareto configurations for validation, minimizing exact error first, then runtime. Do not tune a configuration on a document, merchant, issuer, or filename.

## Lane Interfaces

Create these OCR-local contracts in `src/ccparser/experiments/row_recovery/ocr/contracts.py`:

```python
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from ccparser.evidence.models import BBox, Word
from ccparser.experiments.row_recovery.contracts import (
    CandidateSupportLineage,
    ExperimentReasonCode,
    FrozenExperimentModel,
    GroundedCandidateBatch,
    MerchantPrediction,
    PreparedRowCase,
    ProducerIdentity,
    RowEvidenceVariant,
    SplitRunInputBinding,
)
from ccparser.layout.models import TableRegion


class CropKind(StrEnum):
    FULL_ROW = "full_row"
    DESCRIPTION_BAND = "description_band"


class PaddingKind(StrEnum):
    MIDPOINT = "midpoint"
    PADDED_MIDPOINT = "padded_midpoint"


class PageSegmentationMode(IntEnum):
    BLOCK = 6
    SINGLE_LINE = 7


class OcrReasonCode(StrEnum):
    INVALID_ROW_CLIP = "invalid_row_clip"
    MISSING_DESCRIPTION_SCOPE = "missing_description_scope"
    AMBIGUOUS_DESCRIPTION_SCOPE = "ambiguous_description_scope"
    OCR_FAILURE = "ocr_failure"
    OCR_ATOM_LIMIT_EXCEEDED = "ocr_atom_limit_exceeded"
    MISSING_DESCRIPTION_OCR = "missing_description_ocr"
    AMBIGUOUS_DIRECTION = "ambiguous_direction"
    COMPETING_CANDIDATES = "competing_candidates"


class OcrToolchainFingerprint(FrozenExperimentModel):
    tesseract_version: str
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    traineddata_sha256: tuple[tuple[str, str], ...]
    bound_runtime_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing_revision: str = Field(pattern=r"^[0-9a-f]{40}$")


class RowOcrConfig(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    crop_kind: CropKind
    padding_kind: PaddingKind
    dpi: Literal[300, 450]
    psm: PageSegmentationMode
    languages: Literal["heb+eng", "eng"]


class OcrConfigBinding(FrozenExperimentModel):
    config: RowOcrConfig
    identity: ProducerIdentity


class RowCrop(FrozenExperimentModel):
    segment_ordinal: int = Field(ge=0)
    page_index: int = Field(ge=0)
    bbox: BBox
    description_scope: BBox
    config: RowOcrConfig
    base_case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    crop_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class OcrVariantRecord(FrozenExperimentModel):
    config: RowOcrConfig
    evidence_variant: RowEvidenceVariant


```

The package exports:

```python
def crop_for_segment(
    case: PreparedRowCase,
    segment_ordinal: int,
    config: RowOcrConfig,
    page_bbox: BBox,
) -> RowCrop | None: ...


class RowOcrRecognizer(Protocol):
    def recognize(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        crop: RowCrop,
    ) -> tuple[Word, ...]: ...


class SegmentOcrResult(FrozenExperimentModel):
    crop: RowCrop
    words: tuple[Word, ...]


def build_ocr_variant(
    case: PreparedRowCase,
    results: tuple[SegmentOcrResult, ...],
    identity: ProducerIdentity,
) -> OcrVariantRecord: ...


def select_ocr_prediction(
    case: PreparedRowCase,
    variants: tuple[RowEvidenceVariant, ...],
    batches: tuple[GroundedCandidateBatch, ...],
    selector_identity: ProducerIdentity,
) -> MerchantPrediction: ...


def to_grounded_ocr_batches(
    case: PreparedRowCase,
    records: tuple[OcrVariantRecord, ...],
    candidate_identity: ProducerIdentity,
) -> tuple[GroundedCandidateBatch, ...]: ...


def to_experiment_reason(reason: OcrReasonCode) -> ExperimentReasonCode: ...
```

---

### Task 1: Define the fixed OCR configuration matrix and crop geometry

**Files:**
- Create: `src/ccparser/experiments/row_recovery/ocr/__init__.py`
- Create: `src/ccparser/experiments/row_recovery/ocr/contracts.py`
- Create: `src/ccparser/experiments/row_recovery/ocr/geometry.py`
- Create: `tests/experiments/row_recovery/ocr/test_geometry.py`

- [ ] **Step 1: Write geometry tests with synthetic rows**

Cover one anchor, anchor plus continuations, preceding/following rows, first/last page rows, cross-page continuations with distinct region schemas, full-row versus description-band x bounds, both padding policies, page clamping, adjacent-row midpoint exclusion, exact configuration enumeration, stable crop fingerprints, no description column, and multiple description columns.

Include the invariant:

```python
assert crop.bbox[1] >= previous_midpoint
assert crop.bbox[3] <= following_midpoint
assert crop.description_scope == unique_description_column.bbox
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_geometry.py
```

Expected: collection/import failure because the OCR package does not exist.

- [ ] **Step 3: Implement deterministic geometry**

Use each segment's recorded region to find its unique neighboring rows. Compute segment-local midpoint bounds; on adjacent same-page description continuations, the shared boundary remains the row midpoint rather than creating an overlapping crop. `PADDED_MIDPOINT` may expand by `0.25 × median bundle-segment height` only inside neighbor midpoint bounds; it may not consume adjacent-row space. Intersect x bounds with that page and region. Return `None` for missing/ambiguous description scope.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/ocr tests/experiments/row_recovery/ocr
git commit -m "test: define row OCR crop matrix"
```

### Task 2: Add a deterministic PSM-aware row recognizer and cache

**Files:**
- Create: `src/ccparser/experiments/row_recovery/ocr/recognizer.py`
- Create: `tests/experiments/row_recovery/ocr/test_recognizer.py`

**Interfaces:**

```python
class TesseractRowRecognizer:
    def __init__(
        self,
        cache_dir: Path,
        toolchain: OcrToolchainFingerprint,
    ) -> None: ...

    def cache_key(
        self,
        source_sha256: str,
        crop: RowCrop,
        toolchain: OcrToolchainFingerprint,
    ) -> str: ...

    def recognize(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        crop: RowCrop,
    ) -> tuple[Word, ...]: ...
```

- [ ] **Step 1: Write recognizer tests around a fake launcher**

Cover SHA mismatch, exact non-shell command arguments for PSM/language, DPI/origin coordinate mapping, TSV parsing, NFC text, confidence bounds, clip-aware cache keys, distinct keys for every matrix factor and Tesseract version, atomic cache writes, cache hits without relaunch, malformed TSV, and typed OCR failure. Assert neither stdout nor error messages contain source path/text. Exhaustively map every `OcrReasonCode` to exactly one shared `ExperimentReasonCode` and prove shared predictions never contain a lane-local reason.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_recognizer.py
```

Expected: import failure because `recognizer.py` does not exist.

- [ ] **Step 3: Implement by reusing existing safe OCR primitives**

Reuse the existing traced Tesseract launcher, bound runtime policy, PyMuPDF rendering semantics, and `parse_tesseract_tsv()` from `ccparser.evidence.ocr`. The experiment wrapper may depend on those pinned private helpers but must not modify them. Its command is exactly:

```python
(
    "tesseract", "stdin", "stdout", "-l", config.languages,
    "--oem", "1", "--psm", str(int(config.psm)), "tsv",
)
```

Hash source digest, base-case/crop fingerprints, page, crop coordinates, DPI, PSM, languages, experiment/preprocessing revisions, complete command, Tesseract version, executable SHA-256, traineddata SHA-256 values, and bound-runtime identity. Map returned boxes to display coordinates using the actual pixmap origin.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/ocr/recognizer.py tests/experiments/row_recovery/ocr/test_recognizer.py
git commit -m "feat: recognize bounded row OCR variants"
```

### Task 3: Build isolated OCR evidence variants

**Files:**
- Create: `src/ccparser/experiments/row_recovery/ocr/variants.py`
- Create: `tests/experiments/row_recovery/ocr/test_variants.py`

- [ ] **Step 1: Write source-isolation and projection tests**

Cover center-inside description projection, boundary ambiguity rejection, full-row financial words discarded, per-segment and cross-page OCR word ordering, candidate-local atom IDs, immutable reuse of baseline non-description claims, exclusion of baseline description atoms, exact base-case/protected-outcome echoing, typed config provenance, rejection when segment results mix configs or the canonical config fingerprint disagrees with `ProducerIdentity.configuration_fingerprint`, per-segment region/direction mapping, lossless shadow-row serialization, stable evidence fingerprint, stale-case rejection, empty OCR result, duplicate/overlapping OCR words, a maximum of 64 retained description atoms per segment, and proof that the input `PreparedRowCase` bytes/fingerprint do not change.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_variants.py
```

Expected: import failure because `variants.py` does not exist.

- [ ] **Step 3: Implement candidate-local shadow rows**

Project retained OCR words into shadow cells in each segment's existing description column and preserve segment/region ordinals. Require every segment result to carry the same typed `RowOcrConfig`; retain it in `OcrVariantRecord` and require the variant configuration fingerprint to be the canonical hash of that config plus the bound toolchain/preprocessing identity. Rebuild only the shadow description rows/ledger and serialize those rows in the variant. Carry baseline non-description atoms/claims as immutable context; allocate OCR atom IDs deterministically after them in segment and ledger-render order. Derive and record per-segment base direction plus supporting OCR atom IDs; ambiguous direction remains `None`. Bind the variant fingerprint to the base case, protected outcome, producer revision, configuration, segment mapping, shadow rows, atoms, and scoped claims. Reject a segment exceeding 64 retained description atoms. Never write to the baseline case, regions, rows, evidence, or claims.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/ocr/variants.py tests/experiments/row_recovery/ocr/test_variants.py
git commit -m "feat: isolate OCR row evidence variants"
```

### Task 4: Run existing description proof in shadow mode and select consensus

**Files:**
- Create: `src/ccparser/experiments/row_recovery/ocr/extraction.py`
- Create: `src/ccparser/experiments/row_recovery/ocr/selection.py`
- Create: `tests/experiments/row_recovery/ocr/test_extraction.py`
- Create: `tests/experiments/row_recovery/ocr/test_selection.py`

**Interfaces:**

```python
class OcrDescriptionCandidate(FrozenExperimentModel):
    config: RowOcrConfig
    evidence_variant: RowEvidenceVariant
    merchant_text: str | None
    merchant_atom_ids: frozenset[int]
    description_complete: bool
    reason_codes: tuple[OcrReasonCode, ...]


def extract_ocr_description(
    case: PreparedRowCase,
    record: OcrVariantRecord,
) -> OcrDescriptionCandidate: ...


def variant_group_regions(
    case: PreparedRowCase,
    variant: RowEvidenceVariant,
) -> tuple[TableRegion, ...]: ...


def should_attempt_row_ocr(case: PreparedRowCase) -> bool: ...
```

- [ ] **Step 1: Write shadow extraction tests**

Use synthetic prepared cases and variants to prove current description proof receives the losslessly reconstructed shadow rows, retained year context, exact excluded atom IDs, and group-scoped `DescriptionEvidenceContext` rebuilt from group-region copies in which each participating baseline row is replaced by its exact shadow row. Cover repeated-band proof that changes when candidate-local text/geometry changes, unique participating-row substitution across same-page and cross-page regions, and byte-identical baseline group regions after extraction. Financial/date claims remain unchanged; merchant evidence points only to OCR atoms; only the anchor plus explicitly reviewed `ContinuationKind.DESCRIPTION` segments can contribute merchant atoms; other detail segments remain available for exclusion/ownership proof; ambiguity causes description-incomplete/abstain; and neither parser status nor baseline result is constructed or mutated.

- [ ] **Step 2: Write trigger and consensus tests**

Cover every closed recovery trigger, a baseline description-complete control, two typed configuration-diverse results agreeing exactly, one safe configuration retained for downstream evidence only, opaque-fingerprint differences without crop/PSM diversity, equal-support disagreement, same text with different punctuation/order, identical configuration duplicates, and control forced-audit behavior. Project raw results into exactly one round-trippable `GroundedCandidateBatch` per evidence fingerprint/config record; every batch uses the aggregate candidate identity while its `OcrSelectionProof` retains exact crop/PSM/configuration fingerprint and validates against one auxiliary config binding. Every OCR envelope derives `CandidateSupportLineage.EXISTING_DESCRIPTION_PROOF` because it runs the existing description extractor on alternate recognition evidence; reject any caller-supplied different lineage. The selector consumes the explicit tuple of variants plus matching batches. Treat cross-configuration agreement as correlated stability evidence, never independent corroboration. A standalone proposal requires matching output across at least two typed configs differing in crop or PSM; one safe config remains usable by downstream consumers but has no standalone selector. Repeated cache copies or opaque fingerprint differences do not add support. Abstain on every equal-proof conflicting string. A lexicographic evidence-fingerprint tie-break is permitted only after merchant text and selected atom rendering are semantically identical.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_extraction.py tests/experiments/row_recovery/ocr/test_selection.py
```

Expected: import failure because extraction and selection do not exist.

- [ ] **Step 4: Implement minimal shadow extraction and fail-closed selection**

Build `variant_group_regions()` by locating each participating baseline row exactly once in its recorded `case.regions`/`case.group_regions` region and replacing it with the corresponding losslessly serialized `variant.shadow_rows` row in an immutable region copy; reject missing or ambiguous substitution. Rebuild `DescriptionEvidenceContext` from those candidate-local group-region copies, then invoke the existing `extract_description()` contract against the shadow rows/ledger with `case.year_context` and `case.description_excluded_atom_ids`. `description_complete` means nonempty description value/evidence with no closed ambiguous/missing description condition; it is not full transaction semantic completeness. Emit every complete source-grounded result into the raw batch before selection. A selector proposal additionally requires configuration-diverse stability, no competing merchant string with equal proof support, an unambiguous recorded base direction, and the frozen trigger. Otherwise retain the detailed local reason only in private proof/candidate artifacts and return a shared abstention after the exhaustive `to_experiment_reason()` mapping.

- [ ] **Step 5: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/ocr/extraction.py src/ccparser/experiments/row_recovery/ocr/selection.py tests/experiments/row_recovery/ocr/test_extraction.py tests/experiments/row_recovery/ocr/test_selection.py
git commit -m "feat: select grounded row OCR consensus"
```

### Task 5: Add the development sweep, oracle report, and frozen validation runner

**Files:**
- Create: `src/ccparser/experiments/row_recovery/ocr/runner.py`
- Create in the finalization step: `src/ccparser/experiments/row_recovery/ocr/policy.py`
- Create: `src/ccparser/experiments/row_recovery/ocr/__main__.py`
- Create: `tests/experiments/row_recovery/ocr/test_runner.py`

**Interfaces:**

```python
class FrozenOcrPolicy(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    trigger_codes: tuple[RecoveryTriggerCode, ...]
    config_bindings: tuple[OcrConfigBinding, ...] = Field(min_length=1, max_length=4)
    minimum_diverse_support: Literal[2] = 2
    standalone_selector_enabled: bool
    foundation_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_identity: ProducerIdentity
    selector_identity: ProducerIdentity | None = None
    toolchain: OcrToolchainFingerprint


class OcrRunBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs: SplitRunInputBinding


class OcrDevelopmentBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    trigger_codes: tuple[RecoveryTriggerCode, ...]
    config_bindings: tuple[OcrConfigBinding, ...] = Field(min_length=32, max_length=32)
    minimum_diverse_support: Literal[2] = 2
    candidate_identity: ProducerIdentity
    selector_identity: ProducerIdentity
    foundation_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    inputs: SplitRunInputBinding
    toolchain: OcrToolchainFingerprint


def load_ocr_development_binding(
    path: Path,
    *,
    expected_sha256: str,
) -> OcrDevelopmentBinding: ...


def load_ocr_policy(
    path: Path,
    *,
    expected_sha256: str,
) -> FrozenOcrPolicy: ...


def load_ocr_run_binding(
    path: Path,
    *,
    expected_sha256: str,
) -> OcrRunBinding: ...


def run_ocr_experiment(
    dataset: LoadedDataset,
    cases: tuple[PreparedRowCase, ...],
    atom_labels: tuple[MerchantAtomGold, ...],
    trusted_source_root: Path,
    cache_dir: Path,
    output_dir: Path,
    *,
    toolchain: OcrToolchainFingerprint,
    config_bindings: tuple[OcrConfigBinding, ...],
    candidate_identity: ProducerIdentity,
    selector_identity: ProducerIdentity | None,
    policy: FrozenOcrPolicy | None,
    audit_controls: bool,
) -> tuple[OracleStageMetrics, AggregateMetrics]: ...
```

- [ ] **Step 1: Write runner/privacy/determinism tests**

Cover development matrix enumeration, validation requiring an independently pinned frozen policy, shared dataset/prepared/atom-gold loaders, missing or self-derived expected-pin rejection, test split rejection, each source read once and SHA-validated before OCR, explicit trusted source/cache/output roots, controls swept but not proposed without trigger, shared recognition/generation/selection oracle decomposition, exact character-edit counts, reviewed-box IoU diagnostics only for cases/variants with an independently reviewed atom partition, one-to-four configuration freeze, rejection of duplicate configs/identities, distinct config-specific variant identities plus aggregate candidate and optional selector identities, exact proof-to-auxiliary-config validation, canonical identity derivation and stale/dirty-revision rejection, rejection when separately supplied toolchain/config bindings/candidate/selector identities differ from the verified development binding or validation policy, fresh-process batch reload/selection, canonical variant/candidate/prediction output, repeated byte identity, aggregate-only stdout with no private-derived hashes, and failure cleanup. Accept one safe recognition-improving config only as an evidence producer with `standalone_selector_enabled=false` and no selector identity; when the selector is enabled, require at least two configs including a crop- or PSM-diverse pair and a matching selector identity.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_runner.py
```

Expected: import failure because the runner does not exist.

- [ ] **Step 3: Implement the development runner**

The CLI must call shared `load_dataset()`, `load_prepared_cases()`, and `load_atom_gold()` with independently supplied expected pins before invoking the typed runner. Development loads `OcrDevelopmentBinding`; final-policy runs load both `FrozenOcrPolicy` and an independently pinned split-specific `OcrRunBinding`, and no loader may derive an expected pin from the object being checked. The runner receives only the verified toolchain/config/candidate/optional-selector identities plus already loaded inputs and rejects any unequal separately supplied value. Validators require unique configs and identities, exactly the 32-member matrix in the development binding, and one to four final configs. A final policy with `standalone_selector_enabled=true` must contain at least two configs with one pair differing in crop or PSM and a non-`None` selector identity; a one-config policy or any policy without that diverse pair must set the selector flag false and identity `None` while retaining its safe candidate/evidence identities. For every matrix configuration derive its evidence identity from canonical typed config plus complete toolchain/preprocessing schema. Derive the aggregate raw-candidate identity from ordered evidence identities plus extractor/renderer/proof-envelope schema; derive the optional selector identity from candidate identity plus trigger, diversity, consensus, and selector schemas. All producer identities exclude dataset/prepared/gold/run-binding pins and use the exact clean lane HEAD. The CLI checks clean HEAD against the expected revision and rejects mismatches. The run binding separately authenticates split inputs and exact policy digest. Development writes private variants, candidate batches, optional predictions, metrics, timing, toolchain fingerprint, and hashes. Public output contains only aggregate counts and pin/repeat/privacy verification booleans.

Freeze a one-to-four-configuration evidence policy only after candidate-local atom review. Discard any configuration with grounding/invariance/control-artifact failure, then rank by: exact recognition-ceiling recoveries, candidate-generation-ceiling recoveries, standalone exact recoveries, lower runtime, and canonical configuration tuple. Retain the capped union of the recognition and generation Pareto frontiers and let recognition win the final tie so a configuration useful to downstream profile/tagger consumers is not discarded merely because the existing selector cannot use it. Freeze the standalone selector capability separately: enable it only when at least two retained configs include crop/PSM diversity and its zero-wrong-proposal/control and positive-gain gate passes. Otherwise keep one or more safe recognition-improving configs as evidence producers with the selector disabled.

Support these exact commands. All expected pins come from a separately reviewed private approval record; the command must not calculate an expected value from the file it is checking:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development atom-gold SHA-256}"
: "${ROW_OCR_DEVELOPMENT_SWEEP_BINDING_SHA256:?set the independently reviewed development sweep binding SHA-256}"
: "${ROW_OCR_DEVELOPMENT_REVISION:?set the reviewed clean development-runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr develop \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-sweep.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --cache-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/ocr/development-a" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-a/ocr" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-binding-sha256 "$ROW_OCR_DEVELOPMENT_SWEEP_BINDING_SHA256" \
  --expected-producer-revision "$ROW_OCR_DEVELOPMENT_REVISION" \
  --worktree-root . \
  --split development \
  --audit-controls
```

Use the same pre-existing external pins and new empty `development-b` cache/run paths for the repeat. This phase executes only `develop`, which accepts only `development`; the final-policy validation command and its not-yet-created pins appear in Step 6. No subcommand accepts `test`.

- [ ] **Step 4: Verify and commit the generic runner before private execution**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/ocr tests/experiments/row_recovery/ocr
git commit -m "test: freeze row OCR experiment runner"
git status --short
```

Expected: all gates pass and the worktree is clean. Record the exact code revision in the ignored development binding. A code/configuration edit invalidates the corresponding variants and predictions.

- [ ] **Step 5: Run development twice and review variant atom partitions**

From that exact clean revision, construct the typed 32-config development binding without reading development labels, independently review and pin it, and set the development-specific command variables above. Use two new run directories and empty OCR caches. Require identical canonical variants and predictions. After variants are frozen, independently review and pin candidate-local `MerchantAtomGold` for every proposed or potentially recoverable evidence fingerprint; do not map current-evidence atom IDs onto OCR atoms. Re-run the shared oracle with those partitions using the exact commands below. Stop the OCR component only if recognition does not improve over current evidence or a hard artifact gate fails. If recognition improves but current description proof cannot generate/select it, retain the evidence-producer capability, disable the failing standalone-selector capability, and test the frozen variants with profile/tagger consumers in the bake-off.

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_OCR_DEVELOPMENT_VARIANTS_SHA256:?set the independently reviewed development variants SHA-256}"
: "${ROW_OCR_DEVELOPMENT_PREDICTIONS_SHA256:?set the independently reviewed development predictions SHA-256}"
: "${ROW_OCR_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed development variant atom-gold SHA-256}"
: "${ROW_OCR_DEVELOPMENT_SWEEP_BINDING_SHA256:?set the independently reviewed development sweep binding SHA-256}"
: "${ROW_OCR_DEVELOPMENT_REVISION:?set the reviewed clean development-runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_OCR_ORACLE_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr oracle \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/development-sweep/development.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-a/ocr/variants.jsonl" \
    --predictions "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-a/ocr/predictions.jsonl" \
    --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-sweep.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-oracle-$ROW_OCR_ORACLE_REPEAT/ocr" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_DEVELOPMENT_VARIANTS_SHA256" \
    --expected-predictions-sha256 "$ROW_OCR_DEVELOPMENT_PREDICTIONS_SHA256" \
    --expected-binding-sha256 "$ROW_OCR_DEVELOPMENT_SWEEP_BINDING_SHA256" \
    --expected-producer-revision "$ROW_OCR_DEVELOPMENT_REVISION" \
    --worktree-root . \
    --split development
done
```

Both oracle output directories must be new and their complete canonical bytes must match.

- [ ] **Step 6: Freeze policy, commit, then rerun its exact configs on development and validation**

Add focused tests first that `ocr/policy.py` exposes exactly the selected 1–4 pre-registered configurations, conditional diversity requirement, triggers, and selector constant, and that `FrozenOcrPolicy` plus each split-specific `OcrRunBinding` must match them. Run the focused test and observe RED because `ocr/policy.py` does not exist. Then write only that chosen non-sensitive matrix and selector constants; do not precompute a producer identity or private policy binding yet. Do not commit metrics, toolchain hashes, or corpus values. Run focused GREEN and all tracked gates, commit the generic policy, and require the worktree to be clean. Only then derive config-specific evidence, aggregate raw-candidate, and optional selector identities from that exact new HEAD and construct one split-neutral `FrozenOcrPolicy` containing algorithm/toolchain identity only. Independently review/pin that single policy, then construct and independently pin separate development and validation `OcrRunBinding` objects for their input pins. Run the same policy twice on both splits with empty caches. The selected-policy development variants are new evidence fingerprints; never reuse or remap sweep atom gold.

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/ocr/test_runner.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/ocr tests/experiments/row_recovery/ocr
git commit -m "test: freeze row OCR experiment policy"
git status --short
```

Run the final policy on development with this exact command shape, then use the Step 3 validation command for validation. In both cases use `-a` and `-b` new directories:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed development run-binding SHA-256}"
: "${ROW_OCR_FINAL_POLICY_REVISION:?set the reviewed clean final-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_OCR_POLICY_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr policy-run \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --cache-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/ocr/development-policy-$ROW_OCR_POLICY_REPEAT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-$ROW_OCR_POLICY_REPEAT/ocr" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_OCR_FINAL_POLICY_REVISION" \
    --worktree-root . \
    --split development \
    --audit-controls
done
```

Require the two final-policy development runs to be byte-identical. The private policy approval also binds each retained config to its exact selected development-sweep config record and artifact pin. Compare a canonical semantic projection of each final-policy development result with that selected sweep arm: exclude only expected code revision, producer/configuration/evidence/candidate/batch/prediction fingerprints, policy/run-binding digests, and run/cache paths; require identical typed crop/PSM/DPI/language/padding, recognized words and confidence buckets, normalized geometry, shadow rows/atoms/claims, protected outcomes, rendered candidate text and source geometry, reason dispositions, and per-config oracle/aggregate counts. A mismatch is reproduction drift and hard-stops before validation; it cannot be explained away by A/B determinism.

Only after that parity check passes and the validation run binding exists, run validation with its phase-local preflights:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation atom-gold SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed validation run-binding SHA-256}"
: "${ROW_OCR_FINAL_POLICY_REVISION:?set the reviewed clean final-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_OCR_POLICY_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr validate \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/validation-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --cache-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/ocr/validation-policy-$ROW_OCR_POLICY_REPEAT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-$ROW_OCR_POLICY_REPEAT/ocr" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_OCR_VALIDATION_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_OCR_FINAL_POLICY_REVISION" \
    --worktree-root . \
    --split validation \
    --audit-controls
done
```

`policy-run` accepts only `development`; `validate` accepts only `validation`; neither accepts test. Require byte-identical final-policy validation pairs before review.

- [ ] **Step 7: Review final-policy development/validation partitions and freeze both oracles**

Without changing policy or code, independently review and pin new candidate-local atom partitions for every final-policy development and validation variant that proposed or could render the exact text. Re-run `evaluate_oracle_stages()` separately against each split's frozen variants/predictions; require exact pins for both files, policy, and new variant atom gold. These post-policy reviews may classify failure stage and determine capability contexts, but may not change configurations, thresholds, or selection. Repeat each oracle projection and require identical private bytes and aggregate stage counts. Only these final-policy development artifacts—not the 32-config sweep—enter profile/merchant interaction approvals.

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation current atom-gold SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256:?set the independently reviewed final-policy development variants SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_PREDICTIONS_SHA256:?set the independently reviewed final-policy development predictions SHA-256}"
: "${ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy development variant atom-gold SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256:?set the independently reviewed final-policy validation variants SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_PREDICTIONS_SHA256:?set the independently reviewed final-policy validation predictions SHA-256}"
: "${ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256:?set the independently reviewed final-policy validation variant atom-gold SHA-256}"
: "${ROW_OCR_FINAL_POLICY_SHA256:?set the independently reviewed final OCR policy SHA-256}"
: "${ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256:?set the independently reviewed development run-binding SHA-256}"
: "${ROW_OCR_VALIDATION_RUN_BINDING_SHA256:?set the independently reviewed validation run-binding SHA-256}"
: "${ROW_OCR_FINAL_POLICY_REVISION:?set the reviewed clean frozen-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

for ROW_OCR_ORACLE_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr oracle \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/development-policy/development.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-a/ocr/variants.jsonl" \
    --predictions "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-a/ocr/predictions.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/development-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-policy-oracle-$ROW_OCR_ORACLE_REPEAT/ocr" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_VARIANTS_SHA256" \
    --expected-predictions-sha256 "$ROW_OCR_FINAL_DEVELOPMENT_PREDICTIONS_SHA256" \
    --expected-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_OCR_DEVELOPMENT_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_OCR_FINAL_POLICY_REVISION" \
    --worktree-root . \
    --split development
done

for ROW_OCR_ORACLE_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.ocr oracle \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --variant-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/variants/row_ocr/validation-policy/validation.jsonl" \
    --variants "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-a/ocr/variants.jsonl" \
    --predictions "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-a/ocr/predictions.jsonl" \
    --policy "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/final-policy.json" \
    --run-binding "$CCPARSER_ROW_EXPERIMENT_ROOT/ocr/approvals/validation-run.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-policy-oracle-$ROW_OCR_ORACLE_REPEAT/ocr" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-variant-atom-gold-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANT_ATOM_GOLD_SHA256" \
    --expected-variants-sha256 "$ROW_OCR_FINAL_VALIDATION_VARIANTS_SHA256" \
    --expected-predictions-sha256 "$ROW_OCR_FINAL_VALIDATION_PREDICTIONS_SHA256" \
    --expected-policy-sha256 "$ROW_OCR_FINAL_POLICY_SHA256" \
    --expected-run-binding-sha256 "$ROW_OCR_VALIDATION_RUN_BINDING_SHA256" \
    --expected-producer-revision "$ROW_OCR_FINAL_POLICY_REVISION" \
    --worktree-root . \
    --split validation
done
```

All four oracle directories must be new. Require byte-identical canonical bytes within each split; the input pins remain identical across that split's repeats.

- [ ] **Step 8: Return an explicit lane verdict**

Report evidence-producer, raw-candidate-producer, and standalone-selector capabilities independently with their validated contexts. Return execution status `stop` only for a grounding/invariant/split/privacy/determinism failure or no validation recognition gain. With safe positive recognition gain, return `include_in_bakeoff` for `evidence_producer` even when existing description extraction cannot generate a merchant candidate. Enable `candidate_producer` only when the canonical raw OCR batches are grounded/deterministic and have positive validation candidate-generation headroom; keep it enabled even if selection fails. Enable `standalone_selector` only when candidate production is enabled, exact selected recovery is positive, wrong selected proposals/control changes are zero, and the retained configs meet the conditional diversity gate. If validation disables a development-declared selector, leave the frozen policy unchanged but hand off its declared identity only for verification; the enabled lane-binding identity and selector contexts are empty, and the bake-off must not construct it. The public lane verdict remains `continue_experiment` until support minima and the factorial interaction bake-off pass. Do not read sealed test inputs or claim corpus acceptance.

## Handoff Artifacts

The lane hands the primary agent:

- clean branch SHA;
- foundation code SHA;
- `dataset_pin_verified=true` and `prepared_pin_verified=true`;
- `private_binding_pin_verified=true` for the final OCR policy;
- `model_pin_required=false` and `model_pin_verified=false`;
- `repeated_outputs_identical=true` and `privacy_check_passed=true`;
- aggregate candidate identity, optional policy-declared selector identity, optional validation-enabled selector identity, and every config-specific auxiliary evidence-identity verification boolean, without printing their private fingerprints;
- aggregate recognition-oracle and merchant metrics;
- runtime aggregate;
- execution status `stop` or `include_in_bakeoff`, explicit `evidence_producer`/`candidate_producer`/`standalone_selector` capability booleans with their actually validated `OCR_VARIANT` contexts, plus public verdict `stop` or `continue_experiment`; and
- no private hashes, paths, text, values, per-case diagnostics, or source identifiers in the message.
