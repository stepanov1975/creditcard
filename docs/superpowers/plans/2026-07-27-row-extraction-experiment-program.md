# Row Extraction Experiment Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether targeted row OCR, deterministic extraction-shape profiling, or a small grounded merchant-atom model can safely recover merchant descriptions that the current semantic pipeline cannot resolve, without changing financial fields, parser status, or production output during experimentation.

**Architecture:** Build one experiment-only, typed benchmark foundation on the clean semantic-contract branch, freeze it at an exact commit, and fork three non-overlapping worktrees from that commit. Every lane consumes the same prepared row bundles and private labels, emits the same grounded-candidate artifact, and is judged by one shared evaluator. A final factorial bake-off composes only successful lane commits in an experiment integration branch; production promotion is a separate later change.

**Tech Stack:** Python 3.13, Pydantic v2 immutable models, PyMuPDF, existing Tesseract integration, `Decimal` for financial values, canonical JSON Lines, SHA-256, pytest, Ruff, and mypy. The merchant lane starts with deterministic rules and a standard-library averaged structured perceptron; no production dependency is added.

## Global Constraints

- Use the repository virtual environment at `/root/creditcard/.venv`; invoke it by absolute path from experiment worktrees.
- Start from the clean semantic-contract snapshot. At plan-writing time it is `dd8d3090659c9bed2a81fd0fb8ad227c2e88d075`; stop and review rather than silently substituting a different commit.
- The semantic-contract snapshot is an experiment foundation, not a corpus-accepted release. Do not describe it or any experiment branch as corpus-verified.
- Keep the experiment package outside the production import graph. No production module, `ccparse` command, parser status, reconciliation rule, JSON schema, or CSV schema may import or invoke `ccparser.experiments`.
- Keep source PDFs, source names, hashes, row text, merchant labels, financial values, detailed predictions, OCR caches, trained weights, and evaluation artifacts under the already ignored absolute root `/root/creditcard/artifacts/row-experiments/`. Every worktree command sets `CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments`; do not create a separate relative `artifacts/` tree inside a lane worktree.
- Public logs may contain only aggregate counts, rates represented by integer numerator/denominator pairs, timings, closed reason codes, and verification booleans. Dataset, prepared-case, label, prediction, model, and private-policy hashes remain inside ignored artifacts and must not appear in public logs, Git, commit messages, decision records, or chat handoffs. Public output must never contain case IDs, source IDs, paths, text, coordinates, diagnostics copied from a document, or financial values.
- Split by complete source/layout/temporal family before annotation or tuning. Never split individual rows from the same family across development, validation, and test, and never allow the same source SHA-256 under different IDs or splits.
- Keep `RowTag`, `ContinuationKind`, `FieldDisposition`, `TransactionCategory`, extraction-shape labels, and merchant-atom labels as separate axes. Do not infer one from another or replace them with one flat row-type enum.
- Capture reviewed `RowTag` and `ContinuationKind` sets plus the baseline `FieldDisposition` while preparing the case. `ContinuationKind`, `FieldDisposition`, and `RowTag.DESCRIPTION_CONTINUATION` cannot be reconstructed losslessly from a serialized `Row` or `RowNormalizationResult`.
- Treat transaction amount, currency, dates, original amount, FX details, installment details, category, row membership, and source evidence as immutable experiment inputs. A lane may propose only a merchant description and its exact source atoms.
- A non-abstaining prediction must be copied from ordered source atoms and carry those atom IDs and evidence boxes. Generated, canonicalized, transliterated, or memorized merchant text is invalid.
- Exact NFC merchant string is primary for every case. Exact merchant atom set is co-primary whenever that evidence fingerprint has a reviewed atom partition; otherwise require complete source grounding and report atom exactness as not evaluated. Character error rate, token F1, label F1, and ranking accuracy are diagnostic metrics only.
- Evaluate known failures and baseline-correct controls together. Any wrong change to a control, grounding violation, financial-field mutation, split leak, or nondeterministic repeated artifact is a hard failure.
- Run an oracle decomposition before optimizing a lane: current-evidence recognition oracle, candidate-generation oracle, and candidate-selection oracle. Stop a lane whose perfect oracle has negligible downstream headroom.
- Except for the independent split curator's one label-free pre-tuning partition attestation, do not open any held-out test input, gold, or annotation namespace until each lane's code/configuration and every private model artifact are frozen. That curator alone may hash/read test structural manifests and source bytes to verify family isolation, emits only a content-free attestation, and may not tune code or disclose diagnostics. Primary/lane agents remain blind to test source/case manifests, underlying source files, prepared cases, text gold, current/variant atom gold, merchant annotations, adjudication records, and derived predictions until the frozen final-test phase. Lane agents use physically split development and validation namespaces only; the primary agent performs the sealed test.
- Before each experiment commit run `/root/creditcard/.venv/bin/ruff format --check .`, `/root/creditcard/.venv/bin/ruff check .`, `/root/creditcard/.venv/bin/mypy src`, and `/root/creditcard/.venv/bin/pytest -q` from that worktree.
- Tracked verification and experiment results are not private corpus acceptance. Any later production change must be committed, clean, independently pinned, and pass the formal private `verify` gate with protected membership, baseline parity, deterministic runs, matching toolchain/workers, and `performance_checked=true`.

## Evidence and Scope

- Research synthesis: `/root/creditcard/docs/research/2026-07-27-document-extraction-literature.md`.
- Row OCR lane: `/root/creditcard/docs/superpowers/plans/2026-07-27-row-targeted-ocr-experiment.md`.
- Profile lane: `/root/creditcard/docs/superpowers/plans/2026-07-27-row-profile-experiment.md`.
- Merchant lane: `/root/creditcard/docs/superpowers/plans/2026-07-27-merchant-atom-tagger-experiment.md`.

This program tests additive recovery after transaction-row separation. It does not revisit page classification, table-region discovery, totals, or reconciliation unless the oracle study shows that row separation is the actual bottleneck.

## Worktree and Artifact Ownership

| Phase | Branch | Worktree | Exclusive tracked paths | Private artifact namespace |
|---|---|---|---|---|
| Foundation | `codex/row-experiment-foundation` | `.worktrees/row-experiment-foundation` | shared files under `src/ccparser/experiments/row_recovery/` except lane subpackages and reserved bake-off files; shared tests except lane subdirectories and reserved `test_bakeoff.py` | `artifacts/row-experiments/dataset/`, `prepared-candidates/`, `prepared/`, `foundation/`, `atom-gold/current/` |
| Row OCR | `codex/exp-row-ocr` | `.worktrees/exp-row-ocr` | `.../row_recovery/ocr/`; `tests/.../ocr/` | `runs/<run-id>/ocr/`, `cache/ocr/`, `ocr/approvals/`, `atom-gold/variants/row_ocr/<run-id>/` |
| Profile | `codex/exp-row-profiler` | `.worktrees/exp-row-profiler` | `.../row_recovery/profiles/`; `tests/.../profiles/` | `runs/<run-id>/profiles/`, `profiles/approvals/` |
| Merchant model | `codex/exp-merchant-tagger` | `.worktrees/exp-merchant-tagger` | `.../row_recovery/merchant/`; `tests/.../merchant/` | `merchant/annotations/`, `merchant/approvals/`, `merchant/models/`, `merchant/runs/<run-id>/` |
| Bake-off | `codex/exp-row-bakeoff` | `.worktrees/exp-row-bakeoff` | `src/ccparser/experiments/row_recovery/bakeoff.py`; `bakeoff_policy.py`; experiment `__main__.py`; `tests/experiments/row_recovery/test_bakeoff.py`; `docs/experiments/row-recovery-decision.md` | `runs/<run-id>/bakeoff/`, `cache/bakeoff/<run-id>/`, `bakeoff/approvals/` |

## Execution Schedule and Concurrency

| Stage | Active workers | Barrier/output |
|---|---|---|
| Foundation | Primary agent | Shared contracts, split-safe preparation/evaluation tooling, frozen clean foundation SHA |
| Independent implementation | Three lane subagents in the OCR/profile/merchant worktrees; primary agent reviews (all four slots) | OCR may finish its sweep; profile/merchant finish code plus current-evidence work |
| Evidence interaction | OCR final-policy artifacts first; then profile and merchant agents run concurrently | If OCR stops, both consumers immediately take their current-only branches; otherwise both consume the same pinned OCR approvals |
| Finalization | Profile and merchant agents commit/replay their selected policies concurrently while primary audits OCR | Clean lane SHAs plus capability/context bindings |
| Factorial bake-off | Primary agent in the bake-off worktree | One pre-registered safe composed policy, final dev/validation replay |
| Sealed test and decision | Primary agent only | One composed held-out verdict; no component-level test attribution |

Never run two writers in one tracked path or private run directory. Parallel workers share the ignored artifact root only through create-without-overwrite, explicitly assigned namespaces and independently pinned handoff records.

The foundation-owned paths are frozen once the three lane branches are created; the explicitly reserved bake-off files do not exist yet and belong only to the later bake-off branch. If a lane discovers a contract defect, pause all lanes, fix it on the foundation branch with tests, then rebase all three branches onto the new exact foundation SHA. Do not let lane agents independently edit shared contracts.

## Shared Data Contract

Create these experiment-only types in `src/ccparser/experiments/row_recovery/contracts.py`:

```python
from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ccparser.evidence.models import BBox
from ccparser.layout.continuations import ContinuationKind
from ccparser.layout.models import Row, TableRegion
from ccparser.layout.row_tags import RowTag
from ccparser.layout.text import BaseDirection
from ccparser.discovery import DiscoveredDateYearContext
from ccparser.models import TransactionCategory
from ccparser.normalization_fields import FieldDisposition
from ccparser.semantic_evidence import EvidenceAtomKind, SemanticOwner


class FrozenExperimentModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    TEST = "test"


class AcquisitionKind(StrEnum):
    DIGITAL = "digital"
    OCR = "ocr"
    MIXED = "mixed"


class ScriptKind(StrEnum):
    HEBREW = "hebrew"
    LATIN = "latin"
    MIXED = "mixed"
    OTHER = "other"


class ExperimentLane(StrEnum):
    BASELINE = "baseline"
    ROW_OCR = "row_ocr"
    ROW_PROFILE = "row_profile"
    MERCHANT_TAGGER = "merchant_tagger"
    COMPOSED = "composed"


class LaneCapability(StrEnum):
    EVIDENCE_PRODUCER = "evidence_producer"
    CANDIDATE_PRODUCER = "candidate_producer"
    STANDALONE_SELECTOR = "standalone_selector"


class EvidenceContextKind(StrEnum):
    CURRENT = "current"
    OCR_VARIANT = "ocr_variant"


class CandidateSupportLineage(StrEnum):
    EXISTING_DESCRIPTION_PROOF = "existing_description_proof"
    PROFILE_GEOMETRY = "profile_geometry"
    MERCHANT_ATOM_TAGGER = "merchant_atom_tagger"


class PredictionDisposition(StrEnum):
    PROPOSE = "propose"
    ABSTAIN = "abstain"


class ClaimScope(StrEnum):
    DESCRIPTION_EXTRACTION = "description_extraction"
    SEMANTIC_COMPLETENESS = "semantic_completeness"


class RecoveryTriggerCode(StrEnum):
    MISSING_DESCRIPTION_CELL = "missing_description_cell"
    MISSING_DESCRIPTION_EVIDENCE = "missing_description_evidence"
    AMBIGUOUS_DESCRIPTION_DETAIL = "ambiguous_description_detail"
    AMBIGUOUS_DESCRIPTION_CONTINUATION = "ambiguous_description_continuation"
    AMBIGUOUS_MIXED_DESCRIPTION_DIRECTION = "ambiguous_mixed_description_direction"


class ExperimentReasonCode(StrEnum):
    NOT_TRIGGERED = "not_triggered"
    MISSING_EVIDENCE = "missing_evidence"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    GROUNDING_FAILED = "grounding_failed"
    PROTECTED_OUTCOME_MISMATCH = "protected_outcome_mismatch"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    COMPETING_CANDIDATES = "competing_candidates"
    PRIVATE_INPUT_INVALID = "private_input_invalid"
    TOOL_FAILURE = "tool_failure"


class EvaluationSlice(StrEnum):
    DIGITAL = "digital"
    OCR = "ocr"
    MIXED_ACQUISITION = "mixed_acquisition"
    HEBREW = "hebrew"
    LATIN = "latin"
    MIXED_SCRIPT = "mixed_script"
    OTHER_SCRIPT = "other_script"
    LAYOUT_HOLDOUT = "layout_holdout"
    NON_LAYOUT_HOLDOUT = "non_layout_holdout"
    TEMPORAL_HOLDOUT = "temporal_holdout"
    NON_TEMPORAL_HOLDOUT = "non_temporal_holdout"


class SourceRecord(FrozenExperimentModel):
    source_id: str = Field(pattern=r"^source-[0-9]{6}$")
    source_relative_path: PurePosixPath
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_family_id: str = Field(min_length=1)
    split: DatasetSplit
    acquisition: AcquisitionKind
    script: ScriptKind
    layout_family_id: str = Field(min_length=1)
    temporal_group_id: str = Field(min_length=1)
    is_layout_holdout: bool
    is_temporal_holdout: bool


class SegmentSpec(FrozenExperimentModel):
    page_index: int = Field(ge=0)
    region_bbox: BBox
    row_bbox: BBox
    reviewed_row_tags: frozenset[RowTag]
    reviewed_continuation_kinds: frozenset[ContinuationKind]


class CaseSpec(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r"^case-[0-9]{6}$")
    source_id: str = Field(pattern=r"^source-[0-9]{6}$")
    segments: tuple[SegmentSpec, ...] = Field(min_length=1)


class MerchantTextGold(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r"^case-[0-9]{6}$")
    merchant_text: str = Field(min_length=1)
    is_control: bool


class MerchantAtomGold(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r"^case-[0-9]{6}$")
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    merchant_atom_ids: frozenset[int]


class PreparedAtom(FrozenExperimentModel):
    atom_id: int = Field(ge=0)
    kind: EvidenceAtomKind
    page_number: int = Field(gt=0)
    bbox: BBox
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    source: Literal["digital", "ocr", "cell_text"]
    segment_ordinal: int = Field(ge=0)
    cell_indices: tuple[int, ...]
    column_indices: tuple[int, ...]


class PreparedClaim(FrozenExperimentModel):
    owner: SemanticOwner
    atom_ids: frozenset[int]
    scope: ClaimScope


class ObservedSegmentAxes(FrozenExperimentModel):
    segment_ordinal: int = Field(ge=0)
    region_ordinal: int = Field(ge=0)
    row_tags: frozenset[RowTag]
    continuation_kinds: frozenset[ContinuationKind]
    base_direction: BaseDirection | None
    direction_evidence_atom_ids: frozenset[int]


class BaselineObservation(FrozenExperimentModel):
    field_disposition: FieldDisposition
    transaction_category: TransactionCategory | None
    merchant_text: str | None
    merchant_atom_ids: frozenset[int]
    semantic_complete: bool
    recovery_triggers: tuple[RecoveryTriggerCode, ...]


class PreparedRowCase(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    source_id: str
    split: DatasetSplit
    regions: tuple[TableRegion, ...] = Field(min_length=1)
    group_regions: tuple[TableRegion, ...] = Field(min_length=1)
    rows: tuple[Row, ...] = Field(min_length=1)
    atoms: tuple[PreparedAtom, ...]
    baseline_claims: tuple[PreparedClaim, ...]
    segment_axes: tuple[ObservedSegmentAxes, ...]
    year_context: DiscoveredDateYearContext | None
    description_excluded_atom_ids: frozenset[int]
    baseline: BaselineObservation
    case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class RowEvidenceVariant(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    lane: ExperimentLane
    variant_id: str = Field(min_length=1)
    base_case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_region_ordinals: tuple[int, ...]
    segment_base_directions: tuple[BaseDirection | None, ...]
    direction_evidence_atom_ids: tuple[frozenset[int], ...]
    shadow_rows: tuple[Row, ...]
    atoms: tuple[PreparedAtom, ...]
    claims: tuple[PreparedClaim, ...]
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[ExperimentReasonCode, ...] = ()


class MerchantPrediction(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    lane: ExperimentLane
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: PredictionDisposition
    evidence_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    merchant_text: str | None = None
    merchant_atom_ids: frozenset[int] = frozenset()
    evidence_bboxes: tuple[BBox, ...] = ()
    reason_codes: tuple[ExperimentReasonCode, ...] = ()
    candidate_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class GroundedMerchantCandidate(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    lane: ExperimentLane
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    merchant_text: str = Field(min_length=1)
    merchant_atom_ids: frozenset[int] = Field(min_length=1)
    evidence_bboxes: tuple[BBox, ...] = Field(min_length=1)
    reason_codes: tuple[ExperimentReasonCode, ...] = ()
    candidate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class OcrSelectionProof(FrozenExperimentModel):
    kind: Literal["ocr"] = "ocr"
    crop_kind: Literal["full_row", "description_band"]
    psm: Literal[6, 7]
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class BaselineSelectionProof(FrozenExperimentModel):
    kind: Literal["baseline"] = "baseline"
    description_proof_complete: bool


class ProfileSelectionProof(FrozenExperimentModel):
    kind: Literal["profile"] = "profile"
    strategy: Literal[
        "current_description_proof",
        "primary_cluster",
        "claim_complement",
        "linewise_primary",
        "repeated_band_exclusion",
    ]
    proof_key: tuple[int, int, int, int, int, int]


class MerchantSelectionProof(FrozenExperimentModel):
    kind: Literal["merchant"] = "merchant"
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    atom_labels_and_margins: tuple[
        tuple[
            int,
            Literal[
                "outside",
                "merchant",
                "location",
                "reference",
                "transaction_marker",
                "auxiliary",
                "layout_noise",
            ],
            int,
            int,
        ],
        ...,
    ]
    proposal_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


SelectionProof = Annotated[
    BaselineSelectionProof
    | OcrSelectionProof
    | ProfileSelectionProof
    | MerchantSelectionProof,
    Field(discriminator="kind"),
]


class GroundedCandidateEnvelope(FrozenExperimentModel):
    candidate: GroundedMerchantCandidate
    support_lineage: CandidateSupportLineage
    selection_proof: SelectionProof


class GroundedCandidateBatch(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    case_id: str
    lane: ExperimentLane
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_identity: ProducerIdentity
    envelopes: tuple[GroundedCandidateEnvelope, ...]
    batch_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProducerIdentity(FrozenExperimentModel):
    lane: ExperimentLane
    producer_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SplitRunInputBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    split: DatasetSplit
    dataset_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_atom_gold_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_atom_gold_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class InteractionApproval(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    split: Literal[DatasetSplit.DEVELOPMENT, DatasetSplit.VALIDATION]
    ocr_policy_relative_path: PurePosixPath
    ocr_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ocr_run_binding_relative_path: PurePosixPath
    ocr_run_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variants_relative_path: PurePosixPath
    variants_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_atom_gold_relative_path: PurePosixPath
    variant_atom_gold_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

For profile and merchant consumers, `OCR_VARIANT` names one augmented invocation context: the current-evidence batch followed by the complete ordered frozen OCR variant set and its fingerprint-matched batches. It never means replacing native evidence, invoking once per OCR variant, or scoring variants as independent cases. A lane may therefore validate `candidate_contexts={OCR_VARIANT}` even when the independent `CURRENT` context has no headroom: the mandatory current batch is an internal input of the augmented context, while the `CURRENT` capability controls admission of that current-only context as a separate bake-off arm. The OCR lane itself still uses the enum to identify OCR-derived evidence and candidate capabilities.

Model validators must enforce that rows, axes, segment-region mappings, directions, and direction-evidence tuples have identical cardinality; ordinals are exactly `0..n-1`; every region ordinal is valid; each prepared atom names a valid segment; and atom `page_number == SegmentSpec.page_index + 1`. Reviewed axis sets must be explicitly present even when empty. The evaluation sampling role (`is_control`) lives only in split-sealed `MerchantTextGold`, never `CaseSpec` or `PreparedRowCase`. Separately, `BaselineObservation.field_disposition == ACCEPT` requires an explicit transaction category (including real `UNKNOWN`), while `REJECT_ROW`/`IGNORE_ROW` require `transaction_category=None`. Every `MerchantAtomGold` set is nonempty and valid only for its exact evidence fingerprint; atom gold is created only after the prepared artifact is frozen and never participates in preparation.

Every `RowEvidenceVariant` must echo the exact base-case and protected-outcome fingerprints, carry a losslessly serializable shadow row per segment, and include producer/configuration fingerprints in `evidence_fingerprint`. An abstention has no merchant text/atoms/boxes and no evidence/candidate fingerprint; a proposal has nonempty text/atoms/boxes, echoes the protected-outcome fingerprint, uses atom IDs from its named evidence fingerprint, and echoes the exact selected candidate fingerprint. Rendering occurs segment by segment with the recorded `BaseDirection`, then in segment order; a selected segment with ambiguous direction forces abstention. The rendered NFC text must equal `merchant_text`. The current-evidence variant uses `PreparedRowCase.case_fingerprint`; row OCR emits separate `RowEvidenceVariant` records. Atom IDs are always scoped by case plus evidence fingerprint. Do not use merchant dictionaries or canonical merchant IDs in this contract.

Every lane projects pre-selection results into immutable `GroundedCandidateBatch` envelopes. Each candidate is nonempty and exactly renderable from its named evidence context; its tagged selection proof contains only the closed facts its pure selector needs after serialization. A batch validator requires one lane/evidence/candidate identity throughout, proof type matching the lane, exact candidate/proof fingerprints, and canonical ordering. `MerchantPrediction` is created only by a separately identified selector that receives the prepared case, explicit matching variants, and serialized batches. Candidate and selector artifacts must never share an identity, disabling a selector cannot suppress or mutate the raw candidate set, and a fresh-process reload must produce the same selection without producer-call state or global lookup.

Algorithm policies and `ProducerIdentity.configuration_fingerprint` are reusable across splits: bind only clean code revision, typed algorithm/configuration, toolchain or exact trained-model bytes, feature/renderer/proof schema, and any upstream producer identities. Never include a training-manifest fingerprint, evaluation dataset, prepared-case, label/gold, run-directory, cache, or private run-binding pin in a producer identity. Learned-model provenance authenticates the fixed development training manifest separately; changing it requires a newly verified model/policy, while identity changes only through resulting model bytes/configuration. Each execution loads an independently pinned `SplitRunInputBinding`; the runner verifies its split-specific inputs before calling a producer. Development, validation, and test therefore use different run-input bindings but the exact same frozen algorithm identity.

## Dataset Protocol

The ignored private dataset has this layout:

```text
artifacts/row-experiments/dataset/
├── sources/
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
├── cases/
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
├── labels/
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
└── inventory.json
```

The three initial label files contain `MerchantTextGold` only; they never name atom IDs. Source and case manifests are also split physically so lane loaders never open test metadata or learn test source paths. Before lanes launch, an authorized curator runs a label-free full-partition validator over all source/case manifests and source digests. `inventory.json` contains schema version, SHA-256 for every JSONL file, the semantic base SHA, manifest-validator revision, and the resulting partition-attestation SHA-256; it contains no document content or test counts/slice/control distribution. Each split loader verifies the pinned inventory and attestation, then opens only the explicitly allowed split. Every test source/case/label file stays sealed from lane workers; only the primary agent runs the final evaluation after lane commits are frozen.

After preparation freezes canonical atom IDs, reviewed atom partitions live separately:

```text
artifacts/row-experiments/atom-gold/
├── current/
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
└── variants/<lane>/<private-run-id>/
```

Every atom-gold file is independently SHA-256 pinned inside an ignored inventory and scoped by `case_id + evidence_fingerprint`. It is evaluation input only, never preparation input.

Prepared cases are split-sealed separately:

```text
artifacts/row-experiments/prepared/
├── development/
│   ├── cases.jsonl
│   └── inventory.json
├── validation/
│   ├── cases.jsonl
│   └── inventory.json
└── test/
    ├── cases.jsonl
    └── inventory.json
```

Each split has its own independently pinned prepared inventory and immutable directory. A loader resolves exactly one explicitly allowed split and never opens a sibling directory. Development and validation are prepared before lane work; the primary/reviewer-only test preparation occurs from the already frozen code only after the final combination is committed.

Selection rules:

1. Include every known merchant-description failure or abstention on the semantic base.
2. Add baseline-correct controls from the same source families and from unaffected source families.
3. Keep all pages and statement periods from one `source_family_id` in one split.
4. Assign development first, validation second, and test last using family groups, not rows. Record the assignment before labels are inspected.
5. Cover digital, OCR, mixed acquisition and Hebrew, Latin, mixed-script slices when present; report absent slices rather than manufacturing examples.
6. Before preparation, annotate exact printed merchant text, row-bundle membership, and independent reviewed row-tag and continuation-kind sets. After preparation, annotate exact current-evidence atom IDs against the pinned case fingerprint. Use a second review for every failure case and every disagreement.
7. Never silently alter a frozen label. Create a new dataset revision, record a reason code, and rerun every lane from the new inventory digest. Evidence-variant atom partitions created after a lane freezes live in that lane's ignored annotation namespace and are pinned independently; they never overwrite current-evidence gold.

## Common Decision Gates

A lane artifact may advance to validation/integration only if:

- every proposal is source-grounded;
- amount/date/currency/original/FX/installment/category fingerprints are byte-identical to baseline;
- repeated runs produce byte-identical prediction JSONL;
- public output passes the privacy test.

Its standalone selector capability advances only if wrong selected proposals and control changes are both zero and exact merchant recovery improves over baseline. Evidence/candidate-producer capabilities may still enter the interaction bake-off with the standalone selector disabled when their artifacts are grounded, immutable, deterministic, and have oracle headroom in at least one pre-registered evidence context. In particular, do not prune profile/merchant consumers solely from the current-evidence oracle, and do not prune OCR evidence solely because the existing description selector cannot consume it. After OCR variants freeze, evaluate profile and merchant generation/selection ceilings in both current-evidence and OCR-evidence contexts. Stop a component only when it has no oracle headroom in every available pre-registered context or violates a hard artifact gate.

A frozen capability is eligible for the sealed test only if the same artifact conditions hold on validation, its exact enabled capability set and configuration revision are committed, and any private model artifact is independently SHA-256 pinned. One exact recovery with zero hard failures is enough to advance a standalone selector from development to validation, but never enough for a production claim. Interaction-only capability sets are chosen on development/validation and frozen before test just like standalone policies.

Pre-register these promotion-evidence minima for the final tested composed policy: baseline-correct held-out controls in at least 60 distinct `source_family_id` clusters and at least 60 source documents; score a cluster as wrong if any control in it changes incorrectly, and require the cluster-level rule-of-three upper bound `3 / control_cluster_count <= 0.05`; at least five exact recovered failures spanning at least three independent source/layout families; at least a two-percentage-point safe exact-coverage gain; zero wrong controls, wrong proposals, grounding violations, protected-outcome mismatches, and repeat mismatches; and nonredundant validation contribution from included capabilities in the factorial bake-off. Row-level `3 / control_row_count` is descriptive only because rows/documents within a family are correlated. If the composed policy clears correctness gates but the available corpus cannot meet these support minima, return `continue_experiment`, not `eligible_for_promotion_plan`. Component lanes receive contribution status only because the sealed test does not contain leave-one-lane-out arms. These are evidence thresholds, not permission to integrate production code.

Report count-valued metrics first:

```text
eligible_cases
baseline_exact
proposal_count
exact_proposals
atom_exact_evaluated
exact_atom_proposals
wrong_proposals
abstentions
recovered_failures
wrong_control_changes
grounding_violations
financial_invariant_violations
```

Rates are derived as numerator/denominator pairs. For zero observed wrong changes, report both descriptive row-level `3 / control_row_count` and the decision-bearing family-cluster bound `3 / control_cluster_count`; do not describe observed zero as proof of zero risk or treat correlated rows as independent.

---

### Task 1: Create and verify the isolated foundation worktree

**Files:**
- Read only: `.gitignore`
- Create later: `.worktrees/row-experiment-foundation/`

- [ ] **Step 1: Verify the base and worktree policy**

Run from `/root/creditcard`:

```bash
git status --short
git rev-parse codex/semantic-contract-fixes
git -C .worktrees/semantic-contract-fixes status --short
git check-ignore -q .worktrees/probe
git check-ignore -q artifacts/row-experiments/probe
test ! -e .worktrees/row-experiment-foundation
test -z "$(git branch --list codex/row-experiment-foundation)"
```

Expected: the semantic worktree is clean, its SHA is exactly `dd8d3090659c9bed2a81fd0fb8ad227c2e88d075`, both private roots are ignored, and the proposed foundation branch/worktree do not already exist. If either exists, stop and review it; never silently reuse, delete, or overwrite it. The main worktree may show the separately authored untracked research/plan documents; do not add them to an experiment commit.

- [ ] **Step 2: Create the foundation branch and run its baseline**

```bash
git worktree add .worktrees/row-experiment-foundation -b codex/row-experiment-foundation dd8d3090659c9bed2a81fd0fb8ad227c2e88d075
git -C .worktrees/row-experiment-foundation status --short
```

From `.worktrees/row-experiment-foundation`, run:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
```

Expected: clean worktree and all tracked gates pass. If the inherited baseline fails, stop and report it before adding experiment code.

### Task 2: Add the experiment-only contracts and import boundary

**Files:**
- Create: `src/ccparser/experiments/__init__.py`
- Create: `src/ccparser/experiments/row_recovery/__init__.py`
- Create: `src/ccparser/experiments/row_recovery/contracts.py`
- Create: `tests/experiments/row_recovery/test_contracts.py`
- Create: `tests/experiments/row_recovery/test_import_boundary.py`

**Interfaces:** Use the types in **Shared Data Contract**. Add `rendered_prediction(case, variants, prediction, *, selected_envelope) -> str | None` as the single validation helper used by all lane artifact readers. `variants` is exactly `tuple[RowEvidenceVariant, ...]`. A `PROPOSE` call requires one explicit `GroundedCandidateEnvelope` and verifies that the prediction exactly echoes its evidence fingerprint, candidate fingerprint, text, atom IDs, boxes, and protected outcome before source rendering. A lane-local prediction must also echo the envelope lane. A `COMPOSED` prediction instead retains its independently identified composed-selector lane/revision/configuration while selecting one non-`COMPOSED` upstream envelope; it must not rewrite the envelope or masquerade as its producer. In every case the prediction's selector identity must differ from the envelope's candidate identity. An `ABSTAIN` call requires `selected_envelope=None`. Never infer or discover an envelope from global state.

- [ ] **Step 1: Write contract and import-boundary tests**

Cover immutable/extra-forbid models, closed enums, proposal/abstention invariants, unknown atom rejection, exact source rendering, NFC behavior, stable sorted serialization of atom IDs, and rejection of an experiment import from any Python file outside `src/ccparser/experiments/`. Merchant-bearing gold, baseline, candidate, and prediction fields must already be NFC; reject rather than silently rewrite non-NFC stored values. A `PROPOSE` prediction requires nonempty text/atoms/boxes, the exact selected envelope's evidence fingerprint, an exact echo of its candidate fingerprint, and no contradictory abstention reason. An `ABSTAIN` requires at least one closed reason, no text/atoms/boxes, `evidence_fingerprint=None`, and `candidate_fingerprint=None`, including empty and multi-variant competing-candidate cases; never choose an arbitrary candidate/fingerprint merely to serialize an abstention. Apply the same grounding rule to composed predictions while preserving their separate `COMPOSED` selector identity and upstream envelope lane. Require a closed, proof-consistent `CandidateSupportLineage` on every envelope: baseline/OCR existing-description proofs and profile `CURRENT_DESCRIPTION_PROOF` map to `EXISTING_DESCRIPTION_PROOF`, other profile strategies map to `PROFILE_GEOMETRY`, and merchant-model proofs map to `MERCHANT_ATOM_TAGGER`; reject caller-selected or mismatched lineage values.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_contracts.py tests/experiments/row_recovery/test_import_boundary.py
```

Expected: collection/import failure because the experiment package and contracts do not exist.

- [ ] **Step 3: Implement the minimum contracts and boundary scanner**

The boundary test must parse imports with `ast`, not substring matching, and permit test modules and the experiment package itself. Export only stable contract types from `row_recovery/__init__.py`.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments tests/experiments/row_recovery
git commit -m "test: define row recovery experiment contracts"
```

### Task 3: Validate private manifests and split isolation

**Files:**
- Create: `src/ccparser/experiments/row_recovery/manifest.py`
- Create: `src/ccparser/experiments/row_recovery/manifest_cli.py`
- Create: `src/ccparser/experiments/row_recovery/interaction.py`
- Create: `tests/experiments/row_recovery/test_manifest.py`
- Create: `tests/experiments/row_recovery/test_interaction.py`
- Create: `docs/experiments/row-recovery-annotation.md`

**Interfaces:**

```python
class DatasetInventory(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    semantic_base_revision: str
    manifest_revision: str
    file_sha256: tuple[tuple[str, str], ...]
    partition_attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PartitionAttestation(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    semantic_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    manifest_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    structural_file_sha256: tuple[tuple[str, str], ...]
    source_content_sha256: tuple[str, ...]
    family_partition_verified: bool


class LoadedCaseManifest(FrozenExperimentModel):
    sources: tuple[SourceRecord, ...]
    cases: tuple[CaseSpec, ...]
    inventory: DatasetInventory


class LoadedDataset(FrozenExperimentModel):
    sources: tuple[SourceRecord, ...]
    cases: tuple[CaseSpec, ...]
    labels: tuple[MerchantTextGold, ...]
    inventory: DatasetInventory


def load_case_manifest(
    root: Path,
    *,
    trusted_source_root: Path,
    allowed_splits: frozenset[DatasetSplit],
    expected_inventory_sha256: str,
) -> LoadedCaseManifest: ...


def validate_partition(
    root: Path,
    *,
    trusted_source_root: Path,
    semantic_base_revision: str,
    manifest_revision: str,
) -> PartitionAttestation: ...


def load_dataset(
    root: Path,
    *,
    trusted_source_root: Path,
    allowed_splits: frozenset[DatasetSplit],
    expected_inventory_sha256: str,
) -> LoadedDataset: ...


def load_atom_gold(
    path: Path,
    *,
    cases: tuple[PreparedRowCase, ...],
    variants: tuple[RowEvidenceVariant, ...],
    allowed_splits: frozenset[DatasetSplit],
    expected_sha256: str,
) -> tuple[MerchantAtomGold, ...]: ...


def require_clean_revision(
    worktree_root: Path,
    *,
    expected_revision: str,
) -> None: ...


def load_interaction_approval(
    path: Path,
    *,
    private_root: Path,
    expected_sha256: str,
    expected_split: DatasetSplit,
) -> InteractionApproval: ...
```

**Closed implementation decisions:**

- The fixed inventory key set is exactly the nine canonical JSONL paths `sources/<split>.jsonl`, `cases/<split>.jsonl`, and `labels/<split>.jsonl` for `development`, `validation`, and `test`, in UTF-8 bytewise path order. `PartitionAttestation.structural_file_sha256` is exactly the six source/case paths; the fixed attestation is `approvals/partition.json` and its digest lives only in `partition_attestation_sha256`.
- Split derives only from the canonical containing file plus each case's referenced `SourceRecord.split`; neither `CaseSpec` nor `MerchantTextGold` gains a caller-controlled split field. Reject noncanonical JSONL record order and noncanonical/duplicate digest tuples instead of silently sorting trusted input.
- An atom-gold partition is keyed semantically by `(case_id, evidence_fingerprint)`. Its split derives from the matched `PreparedRowCase`; filename text never grants TEST authority.
- `require_clean_revision()` additionally runs exact non-shell `git -C <root> rev-parse --show-toplevel` and requires that resolved output equal the resolved supplied root, before the required HEAD/status checks. All failures use typed, content-free module-local errors.
- New manifest/interaction APIs remain module-local in Task 3; do not edit `row_recovery/__init__.py`. Use small typed module-local exception classes with closed messages.
- `InteractionApproval.split` plus the externally pinned approval establishes the Task 3 split assertion; `expected_split=TEST` is always rejected and a path component exactly equal to `test` is rejected as defense in depth. Task 3 verifies the four reference paths, distinct path/inode identities, and exact pins. Later profile/merchant readers must parse the referenced typed OCR policy/run/variant/gold artifacts and independently require their internal split to match; Task 3 must not invent those future schemas or claim content-level split verification.

- [ ] **Step 1: Write fail-closed manifest tests**

Use only synthetic names/text. Cover malformed JSONL, duplicate source/case IDs, the same source SHA-256 under different records or splits, missing source/label, wrong file digest, wrong inventory or partition-attestation pin, attestation/file mismatch, absolute source paths, `..` traversal, symlink escape, path outside the trusted private source root, changed source digest, duplicate source/layout/temporal family across splits, case/label split mismatch, test-label loading without explicit `DatasetSplit.TEST`, and deterministic order. Prove the curator-only validator opens all structural splits and rejects cross-split leakage, while both normal loaders verify its attestation and then open only allowed split-specific source/case files. `load_case_manifest()` neither opens nor returns any text-label file, and `load_dataset()` loads only explicitly allowed label splits. For current and variant atom gold, reject unknown case/fingerprint pairs, duplicate partitions, wrong independent pin, and every test path unless the primary-agent caller explicitly supplies `DatasetSplit.TEST`; lane CLIs must have no test option. Test `load_interaction_approval()` with wrong external root pin/split, absolute/traversing/symlink-escaping references, duplicate/aliased targets, wrong referenced pins, and any test reference; prove profile and merchant callers receive the same canonical typed record. Test `require_clean_revision()` with a fake non-shell process launcher: reject wrong/malformed HEAD, staged/unstaged/untracked files, wrong worktree root, command failure, and any diagnostic that could echo private paths/content.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_manifest.py tests/experiments/row_recovery/test_interaction.py
```

Expected: import failure because `manifest.py` does not exist.

- [ ] **Step 3: Implement strict JSONL loading and the annotation guide**

Resolve `source_relative_path` descriptor-relatively beneath `trusted_source_root`; reject symlinks and require a regular file before hashing. `validate_partition()` is the only API allowed to open all structural splits; it checks source/content uniqueness plus source/layout/temporal hypergraph isolation and emits a canonical content-free attestation. Normal loaders require the attestation named by the independently pinned inventory and never reopen sibling splits. Implement `require_clean_revision()` with exact non-shell `git -C <root> rev-parse HEAD` and `git -C <root> status --porcelain --untracked-files=all` argument vectors; compare only to the externally supplied 40-hex revision and return closed errors without relaying Git output. The guide must define merchant versus location/reference/marker/auxiliary text, mixed-script ordering, punctuation, current-evidence atom selection, row-bundle review, disagreement resolution, control selection, family split assignment, and test-label sealing. Examples must be synthetic and contain no corpus-derived strings or values.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/manifest.py src/ccparser/experiments/row_recovery/manifest_cli.py src/ccparser/experiments/row_recovery/interaction.py tests/experiments/row_recovery/test_manifest.py tests/experiments/row_recovery/test_interaction.py docs/experiments/row-recovery-annotation.md
git commit -m "feat: validate private row experiment manifests"
```

- [ ] **Step 5: Curator validates the complete structural partition**

From the clean committed foundation worktree, an authorized curator runs the label-free validator once over all structural manifests and source bytes. The command writes a new ignored attestation, emits aggregate verification booleans only, and has no label option:

```bash
set -euo pipefail
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_SEMANTIC_BASE_REVISION:?set the reviewed semantic-base revision}"
: "${ROW_MANIFEST_REVISION:?set the reviewed clean manifest-validator revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.manifest_cli validate-partition \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --attestation-out "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset/approvals/partition.json" \
  --semantic-base-revision "$ROW_SEMANTIC_BASE_REVISION" \
  --expected-producer-revision "$ROW_MANIFEST_REVISION" \
  --worktree-root .
```

An independent reviewer pins the attestation, then constructs and pins `inventory.json` so it authenticates that exact attestation and the finalized split files. Any source/case change invalidates both. Lane workers receive the inventory pin but no authority to invoke `validate-partition` or open sibling/test manifests.

### Task 4: Prepare frozen row bundles and baseline observations

**Files:**
- Create: `src/ccparser/experiments/row_recovery/preparation.py`
- Create: `src/ccparser/experiments/row_recovery/preparation_cli.py`
- Create: `tests/experiments/row_recovery/test_preparation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class PreparedDatasetSummary:
    case_count: int
    split: DatasetSplit
    prepared_inventory_sha256: str


def prepare_cases(
    dataset: LoadedCaseManifest,
    output_dir: Path,
    *,
    trusted_source_root: Path,
    ocr_provider_factory: Callable[[Path], OcrProvider],
) -> PreparedDatasetSummary: ...


def load_prepared_cases(
    root: Path,
    *,
    split: DatasetSplit,
    expected_inventory_sha256: str,
) -> tuple[PreparedRowCase, ...]: ...
```

`trusted_source_root` is an explicit preparation-time capability. Keep `LoadedCaseManifest` content-only; never resolve its canonical relative source paths against the ambient working directory, mutate them to absolute paths, or change process cwd. Resolve each source descriptor-relatively below this root and recheck its pinned SHA-256 before extraction.

Preparation must use the pinned semantic base to extract/discover each source without receiving merchant text or atom gold, locate exactly one region and row for every ordered segment by page and geometry, preserve every participating region plus all group regions needed to rebuild `DescriptionEvidenceContext`, and retain `DiscoveredDateYearContext`. Build `EvidenceLedger.from_rows()`, serialize its ordered atoms, capture the exact atom IDs excluded before description extraction, and capture description-extraction claims separately from completed semantic-ownership claims. Invoke the existing row-normalization path to capture the actual `FieldDisposition`. For each segment, record its region ordinal, independently reviewed `RowTag`/`ContinuationKind` sets, and description base direction plus supporting atom IDs; do not derive either structural axis from diagnostics or from the other axis. Keep group-level `FieldDisposition` and `TransactionCategory` in `BaselineObservation`.

Compute `case_fingerprint` over the canonical case input, regions, rows, ordered atoms, scoped claims, axes, year context, exclusions, and base revision. Separately compute `protected_outcome_fingerprint` over row membership, amounts, currencies, transaction/posting/conversion dates, original/FX/installment/category fields, statement status, and reconciliation. No lane may construct a changed protected outcome; variants and predictions only echo this fingerprint.

- [ ] **Step 1: Write synthetic preparation tests**

Cover unique geometry lookup, missing/ambiguous lookup, source digest mismatch, proof that control/failure status is absent from preparation input/output, exact segment order, same-page and cross-page region mapping, group-region/context retention, year context, excluded description atoms, per-segment base direction/provenance, independent preservation of multiple reviewed `RowTag` and `ContinuationKind` values, all three group-level dispositions, unchanged category, baseline description atom capture, protected-outcome fingerprint sensitivity for every protected field, CLI rejection of any label/gold option or more than one split, dirty/stale revision, output overwrite, unequal repeat promotion, wrong candidate pin, sibling-split non-access, and detailed artifacts written only below the supplied private output directory.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_preparation.py
```

Expected: import failure because `preparation.py` does not exist.

- [ ] **Step 3: Implement deterministic preparation**

Use exact source SHA-256 and a bounded geometry tolerance only to account for canonical JSON round-tripping. Require exactly one match; never choose the nearest among multiple candidates. Each invocation accepts exactly one split, canonically sorts by `case_id`, writes `cases.jsonl` plus `inventory.json` into a new split-specific candidate directory, and records the exact hash/count and producer revision. `load_prepared_cases()` resolves `root / split.value`, verifies that split's independently pinned inventory, and never opens any sibling split.

- [ ] **Step 4: Verify and commit code only**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/preparation.py src/ccparser/experiments/row_recovery/preparation_cli.py tests/experiments/row_recovery/test_preparation.py
git commit -m "feat: freeze row experiment inputs"
git status --short
```

Expected: no file below `artifacts/` is staged.

- [ ] **Step 5: Run private preparation from the clean committed revision**

After an authorized reviewer creates the ignored source/case manifest, require the worktree to be clean and prepare development and validation independently with externally reviewed inputs. The CLI loads only `LoadedCaseManifest`; it has no text/atom-gold option, accepts exactly one split, writes new paths without overwrite, and prints aggregate counts/verification booleans only. Do not open or prepare test here.

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_PREPARATION_REVISION:?set the reviewed clean 40-character preparation revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli prepare \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/development-a" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-producer-revision "$ROW_PREPARATION_REVISION" \
  --worktree-root . \
  --split development

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli prepare \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/development-b" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-producer-revision "$ROW_PREPARATION_REVISION" \
  --worktree-root . \
  --split development
```

Repeat the same two commands for `validation-a` and `validation-b` with `--split validation`. Require byte-identical files, inventories, and private summaries within each split. An independent reviewer records each common candidate-inventory pin, then promotes each split without recomputation:

```bash
: "${ROW_DEVELOPMENT_PREPARED_CANDIDATE_SHA256:?set the independently reviewed repeated development candidate SHA-256}"
: "${ROW_VALIDATION_PREPARED_CANDIDATE_SHA256:?set the independently reviewed repeated validation candidate SHA-256}"
PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli promote \
  --candidate-a "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/development-a" \
  --candidate-b "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/development-b" \
  --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared/development" \
  --expected-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_CANDIDATE_SHA256"

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli promote \
  --candidate-a "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/validation-a" \
  --candidate-b "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/validation-b" \
  --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared/validation" \
  --expected-inventory-sha256 "$ROW_VALIDATION_PREPARED_CANDIDATE_SHA256"
```

If development or validation preparation exposes a code defect, return to a new failing synthetic test and commit, then discard and regenerate both splits from the new clean revision. Test preparation later is evaluation-only: a failure there yields no test verdict and cannot justify a code/configuration change.

### Task 5: Review and pin prepared current-evidence atom partitions

**Files:**
- Modify code only if validation is incomplete: `src/ccparser/experiments/row_recovery/manifest.py`
- Modify tests only if validation is incomplete: `tests/experiments/row_recovery/test_manifest.py`
- Write private: `/root/creditcard/artifacts/row-experiments/atom-gold/current/`

- [ ] **Step 1: Load the pinned prepared artifact without text/atom gold**

Use `load_prepared_cases()` with each split's independently reviewed prepared-inventory SHA-256, loading development and validation separately. Confirm aggregate case/split counts and pin verification privately. Do not open `prepared/test/`; it does not exist yet, and the preparation API accepts only `LoadedCaseManifest`, so text and atom gold are absent by construction.

- [ ] **Step 2: Annotate current-evidence atom partitions**

For each adjudicated case, review the exact prepared atoms and create `MerchantAtomGold(case_id=..., evidence_fingerprint=case.case_fingerprint, merchant_atom_ids=...)`. Cases whose current evidence cannot render the printed merchant receive no current-evidence atom partition; that absence is recognition-oracle evidence, not an empty gold set. Keep test partitions sealed.

- [ ] **Step 3: Validate and independently pin each split file**

Use `load_atom_gold()` to reject unknown/missing fingerprints, invalid atoms, duplicates, or split leakage. Run a second review for every failure case and disagreement. Store hashes and review state only under the ignored atom-gold inventory.

- [ ] **Step 4: If validation code is incomplete, change it test-first and commit code only**

First add a focused failing test for the missing validation and run it to observe the expected failure. Implement the minimum generic validation, then run the focused test and all tracked gates. If no validation-code defect exists, make no tracked edit and no commit in this step.

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_manifest.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/manifest.py tests/experiments/row_recovery/test_manifest.py
git commit -m "fix: validate reviewed atom partitions"
git status --short
```

The final status must be clean. Do not commit atom labels, counts, hashes, or example details. Any committed validation change creates a new preparation/annotation code revision; update private approvals that bind that code before continuing.

### Task 6: Add shared exact metrics, invariants, and privacy-safe reporting

**Files:**
- Create: `src/ccparser/experiments/row_recovery/metrics.py`
- Create: `src/ccparser/experiments/row_recovery/reporting.py`
- Create: `tests/experiments/row_recovery/test_metrics.py`
- Create: `tests/experiments/row_recovery/test_reporting.py`

**Interfaces:**

```python
class SliceMetrics(FrozenExperimentModel):
    slice: EvaluationSlice
    eligible_cases: int
    exact_proposals: int
    wrong_proposals: int
    abstentions: int


class AggregateMetrics(FrozenExperimentModel):
    eligible_cases: int
    baseline_exact: int
    proposal_count: int
    exact_proposals: int
    atom_exact_evaluated: int
    exact_atom_proposals: int
    wrong_proposals: int
    abstentions: int
    recovered_failures: int
    wrong_control_changes: int
    grounding_violations: int
    financial_invariant_violations: int
    slices: tuple[SliceMetrics, ...]
    support: SupportMetrics


class SupportMetrics(FrozenExperimentModel):
    final_exact: int
    control_rows: int
    control_documents: int
    control_family_clusters: int
    wrong_control_clusters: int
    recovered_source_families: int
    recovered_layout_families: int


class VerificationFlags(FrozenExperimentModel):
    dataset_pin_verified: bool
    prepared_pin_verified: bool
    private_binding_pin_verified: bool
    model_pin_required: bool
    model_pin_verified: bool
    repeated_outputs_identical: bool
    privacy_check_passed: bool


def evaluate_predictions(
    cases: tuple[PreparedRowCase, ...],
    sources: tuple[SourceRecord, ...],
    labels: tuple[MerchantTextGold, ...],
    atom_labels: tuple[MerchantAtomGold, ...],
    evidence_variants: tuple[RowEvidenceVariant, ...],
    predictions: tuple[MerchantPrediction, ...],
    expected_evidence_producers: tuple[ProducerIdentity, ...],
    expected_producers: tuple[ProducerIdentity, ...],
) -> AggregateMetrics: ...


def write_canonical_predictions(
    path: Path,
    predictions: tuple[MerchantPrediction, ...],
) -> str: ...


def privacy_safe_summary(
    metrics: AggregateMetrics,
    verification: VerificationFlags,
) -> str: ...
```

`evaluate_predictions()` must reject rather than count evidence variants or predictions with duplicate/missing cases, unexpected producer/configuration identity, ungrounded atoms, or a protected-outcome fingerprint mismatch. OCR variant identities and its selector identity are separate expected sets. Use only split-sealed `MerchantTextGold.is_control` when scoring controls and reject a gold record marked as a control unless its frozen baseline merchant text is exactly gold; wrong-control counts therefore cannot be diluted by mislabeled failure cases.

- [ ] **Step 1: Write focused evaluator tests**

Cover baseline-exact controls, recovered failures, wrong proposals, abstentions, exact text with wrong atom set when variant atom gold exists, unreviewed OCR evidence counted as atom-exact-not-evaluated, exact atom set with wrong order/text, unexpected config-specific evidence producer, unexpected selector/prediction producer, financial mutation, duplicate/missing cases, deterministic canonical ordering, byte-identical repeated writes, model-required/model-not-applicable verification semantics, missing private binding verification, and a privacy sentinel that must not occur in `privacy_safe_summary()` or captured stdout/stderr. Also cover distinct control-row/document/family-cluster aggregation, a cluster counted wrong when any member changes, recovered source/layout-family counts, exact baseline/final coverage numerators over one denominator, integer cross-multiplication for the two-percentage-point gain, and the cluster rule-of-three check `3 / control_family_clusters <= 0.05` without floating point.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_metrics.py tests/experiments/row_recovery/test_reporting.py
```

Expected: import failure because the shared evaluator does not exist.

- [ ] **Step 3: Implement exact evaluation and reporting**

Use integer counts as source of truth. Validate `0 <= baseline_exact <= final_exact <= eligible_cases` only when wrong proposals are zero; otherwise still report exact raw counts and fail the safety gate. Compute coverage gain by integer cross-multiplication and the family-cluster rule of three as `3 * 100 <= 5 * control_family_clusters`, never binary float. Determinism is evaluated by comparing complete canonical artifact bytes across independent runs and is represented by `VerificationFlags.repeated_outputs_identical`, not a fabricated count from one prediction set. `VerificationFlags` requires `model_pin_verified=True` when `model_pin_required=True` and requires `model_pin_verified=False` when no model exists; every lane still requires its independently pinned private binding. Emit only counts and the closed acquisition/script/layout-holdout/temporal-holdout slices by joining cases to source records; never emit private family/group IDs. Canonical private JSON must use sorted case order, sorted object keys, UTF-8, NFC text, compact separators, and a trailing newline. Keep detailed per-case dispositions and every private-derived hash in private files only.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/metrics.py src/ccparser/experiments/row_recovery/reporting.py tests/experiments/row_recovery/test_metrics.py tests/experiments/row_recovery/test_reporting.py
git commit -m "feat: score grounded row recovery experiments"
```

### Task 7: Implement and run the shared oracle decomposition

**Files:**
- Create: `src/ccparser/experiments/row_recovery/oracle.py`
- Create: `src/ccparser/experiments/row_recovery/oracle_cli.py`
- Create: `tests/experiments/row_recovery/test_oracle.py`

**Interfaces:**

```python
class OracleStageMetrics(FrozenExperimentModel):
    eligible_cases: int
    baseline_exact: int
    recognition_ceiling_exact: int
    generation_ceiling_exact: int
    selection_exact: int
    recognition_misses: int
    generation_misses: int
    selection_misses: int


def evaluate_oracle_stages(
    cases: tuple[PreparedRowCase, ...],
    text_gold: tuple[MerchantTextGold, ...],
    atom_gold: tuple[MerchantAtomGold, ...],
    evidence_variants: tuple[RowEvidenceVariant, ...],
    expected_evidence_producers: tuple[ProducerIdentity, ...],
    generated_candidates: Mapping[str, tuple[GroundedCandidateBatch, ...]],
    expected_candidate_producers: tuple[ProducerIdentity, ...],
    selected_predictions: tuple[MerchantPrediction, ...],
    expected_selectors: tuple[ProducerIdentity, ...],
) -> OracleStageMetrics: ...
```

For the foundation baseline, `recognition_ceiling_exact` counts cases with a reviewed current-evidence partition that renders the exact text; `generation_ceiling_exact` counts exact candidates produced by current proof; and `selection_exact` is baseline exact. Each lane later supplies its candidate-local evidence variants, atom partitions, and candidates to the same stage contract. Recognition renders atom gold directly from the matching current case or `RowEvidenceVariant`; it does not infer recognition from whether an extractor generated a candidate.

- [ ] **Step 1: Write exact stage-decomposition tests**

Cover recognition miss, OCR variant recognized-but-not-generated, raw candidate generated with its selector disabled, generated-but-not-selected, baseline exact, unreviewed atom set, unknown/duplicate evidence fingerprint, atom gold that names an atom outside its matching case/variant, competing exact candidates, missing/duplicate/unexpected evidence-producer, candidate-producer, or selector identities, protected fingerprint mismatch, and count conservation. Gold may be used only inside this evaluator.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_oracle.py
```

Expected: import failure because `oracle.py` does not exist.

- [ ] **Step 3: Implement integer-only oracle stages and a fail-closed CLI**

The CLI accepts only `development`, loads the split-specific dataset, prepared cases, and current atom gold through independently supplied pins, checks the clean worktree revision, generates the existing current-description-proof candidates deterministically from the prepared cases, and evaluates baseline selection. It writes candidates and detailed stage membership only below a new ignored output directory and never accepts a test path or arbitrary producer entry point. Public output contains counts and verification booleans only. Treat zero current-evidence recognition/generation headroom as a context-specific finding, not a global stop for a consumer that may operate on later OCR evidence. One recoverable case is sufficient to continue a standalone hypothesis, but not sufficient for production promotion.

- [ ] **Step 4: Verify and commit**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add src/ccparser/experiments/row_recovery/oracle.py src/ccparser/experiments/row_recovery/oracle_cli.py tests/experiments/row_recovery/test_oracle.py
git commit -m "feat: decompose row recovery oracle ceilings"
git status --short
```

- [ ] **Step 5: Run the foundation development oracle from the clean revision**

Load only independently pinned development text/atom gold and the pinned prepared cases. Evaluate current-evidence recognition, the existing description-proof candidate generation, and baseline selection twice from the exact clean committed revision:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development atom-gold SHA-256}"
: "${ROW_FOUNDATION_ORACLE_REVISION:?set the reviewed clean 40-character oracle revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.oracle_cli \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/foundation-oracle-a" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-producer-revision "$ROW_FOUNDATION_ORACLE_REVISION" \
  --worktree-root . \
  --split development

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.oracle_cli \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/foundation-oracle-b" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-producer-revision "$ROW_FOUNDATION_ORACLE_REVISION" \
  --worktree-root . \
  --split development
```

Both output directories must be new. Require identical complete canonical output bytes, aggregate counts, and verification flags. Record only aggregate stage counts and verification booleans publicly. A zero current-evidence recognition gain means profile/merchant cannot recover those cases from current evidence alone, but it does not prune their pre-registered role as OCR-evidence consumers. A zero current-proof generation gain with positive recognition headroom motivates alternate profile/model candidate generation and does not authorize test access.

### Task 8: Freeze the foundation and launch three parallel worktrees

**Files:**
- Write private: `artifacts/row-experiments/foundation/foundation.json`
- Create worktrees only after all foundation tests pass

- [ ] **Step 1: Run the full foundation verification**

From `.worktrees/row-experiment-foundation`:

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git rev-parse HEAD
```

Expected: all pass and the worktree is clean. Record the resulting 40-character `FOUNDATION_SHA`, tool versions, dataset inventory digest, and independently pinned development/validation prepared-inventory digests in the ignored foundation record.

- [ ] **Step 2: Create all three lane branches from the exact same SHA**

From `/root/creditcard`, resolve the clean foundation worktree once and require a full SHA:

```bash
ROW_FOUNDATION_SHA="$(git -C .worktrees/row-experiment-foundation rev-parse HEAD)"
test "${#ROW_FOUNDATION_SHA}" -eq 40
test ! -e .worktrees/exp-row-ocr
test ! -e .worktrees/exp-row-profiler
test ! -e .worktrees/exp-merchant-tagger
test -z "$(git branch --list codex/exp-row-ocr)"
test -z "$(git branch --list codex/exp-row-profiler)"
test -z "$(git branch --list codex/exp-merchant-tagger)"
git worktree add .worktrees/exp-row-ocr -b codex/exp-row-ocr "$ROW_FOUNDATION_SHA"
git worktree add .worktrees/exp-row-profiler -b codex/exp-row-profiler "$ROW_FOUNDATION_SHA"
git worktree add .worktrees/exp-merchant-tagger -b codex/exp-merchant-tagger "$ROW_FOUNDATION_SHA"
git worktree list --porcelain
```

Expected: all three worktrees report the same initial HEAD. If any target path or branch already exists, stop and review it; never silently reuse or remove it.

- [ ] **Step 3: Dispatch exactly one lane per subagent**

Give each agent its lane plan, worktree, exclusive tracked paths, exact development/validation dataset and prepared views, and private artifact namespace—not blanket authority over the shared roots. Explicitly prohibit edits to shared foundation files, directory scanning outside those views, and access to every test input or result: `dataset/sources/test.jsonl`, `dataset/cases/test.jsonl`, `dataset/labels/test.jsonl`, source files named by the test manifest, the whole `prepared/test/` directory, `atom-gold/current/test.jsonl`, all `atom-gold/variants/**/test*`, `merchant/annotations/test.jsonl`, adjudication records, or derived test predictions. Keep the primary agent free to review progress and resolve contract questions.

- [ ] **Step 4: Run independent implementation and current-evidence work in parallel**

Execute:

- `/root/creditcard/docs/superpowers/plans/2026-07-27-row-targeted-ocr-experiment.md` in `.worktrees/exp-row-ocr`.
- `/root/creditcard/docs/superpowers/plans/2026-07-27-row-profile-experiment.md` in `.worktrees/exp-row-profiler`.
- `/root/creditcard/docs/superpowers/plans/2026-07-27-merchant-atom-tagger-experiment.md` in `.worktrees/exp-merchant-tagger`.

Use the three subagents concurrently for disjoint code and current-evidence work. The OCR lane may continue through its development sweep; profile and merchant lanes stop at their documented OCR-artifact barriers instead of guessing or scanning for inputs. Private prediction/model/dataset hashes stay in ignored run manifests.

- [ ] **Step 5: Cross the OCR barrier, then evaluate both consumers in parallel**

Branch on the OCR lane's reviewed status rather than assuming it succeeds:

- If OCR returns `include_in_bakeoff`, after its final-policy development variants and reviewed variant atom gold are frozen and independently pinned, write a canonical ignored interaction-approval record at the fixed generic path `artifacts/row-experiments/interactions/approvals/development.json`. An independent reviewer pins it, and the lane launcher injects that expected approval pin plus referenced expected pins through the local private environment—not chat or public logs. Tell the existing profile and merchant agents only that the approval is ready, then run their documented development interaction commands concurrently. Each CLI loads the fixed approval by the externally injected root pin and independently verifies every explicit safe relative reference and artifact pin; it never derives its root of trust from the record or scans. Development freezes one profile policy (selector threshold or candidate-only) and the complete 24-arm merchant model×margin grid. Repeat the same approval flow with `validation.json` after OCR validation variants/reviewed gold freeze, then evaluate the one frozen profile policy and the untouched merchant grid concurrently. Never reopen the four profile development thresholds on validation.
- If OCR returns `stop` because of a hard failure or no safe validation recognition gain, create no development/validation interaction approval and expose no OCR path, pin, placeholder, capability, or context to either consumer. Immediately tell the profile and merchant agents to execute their documented OCR-unavailable branches in parallel. Profile selects from its four current-development policies; merchant pre-registers the exact 12-arm current-only schema×margin grid. Both then replay their committed final policies and validate on current evidence only, and their handoffs may contain only `EvidenceContextKind.CURRENT`.

In either branch, merchant validation may select one already pinned selector binding or candidate identity by its pre-registered ordering; profile validation only enables/disables contexts for its already frozen policy. Validation may not create a new threshold, feature schema, training context, epoch, or model. Commit the chosen non-sensitive policies and reproduce/verify their final development and validation artifacts afterward without retuning. No handoff message contains a private path, hash, identifier, or value.

Only after the applicable branch finishes may each lane return its clean handoff: aggregate validation report, private pin-verification booleans, repeat-equality boolean, execution status `stop` or `include_in_bakeoff`, exact enabled `LaneCapability` and `EvidenceContextKind` sets, and public verdict `stop` or `continue_experiment`. A selector that fails standalone gates is omitted while a safe evidence/candidate producer may remain interaction-only. Stop an entire lane only for a hard artifact failure or no oracle headroom across every context that was actually available. `include_in_bakeoff` is permission to compare experimentally, not a production-eligibility claim.

### Task 9: Run the factorial bake-off without production integration

**Files:**
- Create on bake-off branch: `tests/experiments/row_recovery/test_bakeoff.py`
- Create on bake-off branch: `src/ccparser/experiments/row_recovery/bakeoff.py`
- Create on bake-off branch: `src/ccparser/experiments/row_recovery/bakeoff_policy.py`
- Create on bake-off branch: `src/ccparser/experiments/row_recovery/__main__.py`
- Write private: `artifacts/row-experiments/runs/<run-id>/bakeoff/`

**Interfaces:**

```python
class LaneCombination(FrozenExperimentModel):
    use_row_ocr_evidence: bool
    use_row_ocr_candidates: bool
    use_row_ocr_selector: bool
    use_profile_current_candidates: bool
    use_profile_current_selector: bool
    use_profile_ocr_candidates: bool
    use_profile_ocr_selector: bool
    use_merchant_current_candidates: bool
    use_merchant_current_selector: bool
    use_merchant_ocr_candidates: bool
    use_merchant_ocr_selector: bool


class BoundLaneCombination(FrozenExperimentModel):
    combination: LaneCombination
    composition_selector_identity: ProducerIdentity


class LaneVerificationBinding(FrozenExperimentModel):
    lane: ExperimentLane
    code_attestation: LaneCodeAttestation
    candidate_identity: ProducerIdentity
    declared_selector_identity: ProducerIdentity | None = None
    selector_identity: ProducerIdentity | None = None
    auxiliary_identities: tuple[ProducerIdentity, ...] = ()
    capabilities: frozenset[LaneCapability]
    candidate_contexts: frozenset[EvidenceContextKind]
    selector_contexts: frozenset[EvidenceContextKind]
    dataset_pin_verified: bool
    prepared_pin_verified: bool
    private_binding_pin_verified: bool
    model_pin_required: bool
    model_pin_verified: bool
    repeated_outputs_identical: bool
    privacy_check_passed: bool


class LaneCodeAttestation(FrozenExperimentModel):
    lane: ExperimentLane
    lane_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    owned_paths: tuple[PurePosixPath, ...] = Field(min_length=1)
    owned_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ancestor_verified: Literal[True] = True
    owned_paths_unchanged: Literal[True] = True


class FoundationCodeAttestation(FrozenExperimentModel):
    foundation_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    shared_paths: tuple[PurePosixPath, ...] = Field(min_length=1)
    shared_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_paths_unchanged: Literal[True] = True


class LaneArtifactReference(FrozenExperimentModel):
    lane: ExperimentLane
    private_binding_relative_path: PurePosixPath
    private_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_relative_path: PurePosixPath | None = None
    model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FrozenBakeoffBinding(FrozenExperimentModel):
    schema_version: Literal[1] = 1
    bakeoff_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    combinations: tuple[BoundLaneCombination, ...] = Field(min_length=1)
    foundation_attestation: FoundationCodeAttestation
    lane_bindings: tuple[LaneVerificationBinding, ...]
    lane_artifacts: tuple[LaneArtifactReference, ...]
    run_inputs: tuple[SplitRunInputBinding, ...] = Field(min_length=1)


def load_bakeoff_binding(
    path: Path,
    *,
    expected_sha256: str,
) -> FrozenBakeoffBinding: ...


class OcrVariantProducer(Protocol):
    @property
    def identity(self) -> ProducerIdentity: ...

    def variants_for(self, case: PreparedRowCase) -> tuple[RowEvidenceVariant, ...]: ...

    def candidate_batches_for(
        self,
        case: PreparedRowCase,
        variants: tuple[RowEvidenceVariant, ...],
    ) -> tuple[GroundedCandidateBatch, ...]: ...


class GroundedCandidateProducer(Protocol):
    @property
    def identity(self) -> ProducerIdentity: ...

    def candidate_batch_for(
        self,
        case: PreparedRowCase,
        evidence: RowEvidenceVariant | None,
    ) -> GroundedCandidateBatch: ...


class GroundedSelector(Protocol):
    @property
    def identity(self) -> ProducerIdentity: ...

    def select(
        self,
        case: PreparedRowCase,
        evidence_variants: tuple[RowEvidenceVariant, ...],
        batches: tuple[GroundedCandidateBatch, ...],
    ) -> MerchantPrediction: ...


@dataclass(frozen=True, slots=True)
class LaneProducerSet:
    ocr: OcrVariantProducer | None = None
    ocr_selector: GroundedSelector | None = None
    profile: GroundedCandidateProducer | None = None
    profile_selector: GroundedSelector | None = None
    merchant: GroundedCandidateProducer | None = None
    merchant_selector: GroundedSelector | None = None


def run_bakeoff(
    cases: tuple[PreparedRowCase, ...],
    sources: tuple[SourceRecord, ...],
    text_gold: tuple[MerchantTextGold, ...],
    atom_gold: tuple[MerchantAtomGold, ...],
    combinations: tuple[BoundLaneCombination, ...],
    lane_bindings: tuple[LaneVerificationBinding, ...],
    producers: LaneProducerSet,
    output_dir: Path,
) -> tuple[tuple[BoundLaneCombination, AggregateMetrics], ...]: ...
```

The code-attestation path universes are fixed by code, not supplied by an artifact. OCR is every tracked regular file below `src/ccparser/experiments/row_recovery/ocr/` and `tests/experiments/row_recovery/ocr/`; profile and merchant use their corresponding two fixed roots. The foundation/shared universe is `pyproject.toml` plus every tracked regular file below `src/ccparser/` and `tests/experiments/row_recovery/`, excluding only those six lane roots and the exact reserved bake-off paths `src/ccparser/experiments/row_recovery/bakeoff.py`, `src/ccparser/experiments/row_recovery/bakeoff_policy.py`, `src/ccparser/experiments/row_recovery/__main__.py`, and `tests/experiments/row_recovery/test_bakeoff.py`. Enumerate with Git at the foundation/lane revision and current HEAD, reject symlinks, submodules, non-regular entries, or any missing/extra path, and require each serialized path tuple to equal the complete sorted code-derived tuple. Compute both tree SHA-256 values by concatenating, for each file in UTF-8 bytewise path order, unsigned 64-bit big-endian path length + path bytes + unsigned 64-bit big-endian Git-mode length + ASCII Git mode + unsigned 64-bit big-endian blob length + raw blob bytes. This commits path boundaries, modes, and content without relying on ambiguous separators.

The CLI loads `FrozenBakeoffBinding` by its independent pin, selects exactly one `SplitRunInputBinding` matching the requested split, and rejects every dataset/prepared/current-gold/variant-gold path or pin that differs from it. Before loading private lane artifacts or running a producer, it recomputes the complete foundation attestation against the exact frozen foundation SHA and current HEAD; any shared code/path drift fails comparison, final replay, and test. It then resolves exactly one safe relative `LaneArtifactReference` below the shared private root for each available lane, validates that referenced binding by its independent pin, and constructs producers explicitly before `run_bakeoff()`; it never scans. Both relative paths must be non-absolute, normalized, traversal-free, and resolve beneath the shared private root. The merchant reference must carry both a model path and independent model SHA; non-model lanes must carry neither. The merchant binding, model bytes, model pin, candidate/selector identities, feature schema, and committed policy must agree exactly. For each closed lane-owned path set, recompute the canonical tracked-file SHA-256, require the lane revision to be an ancestor of current HEAD, require `git diff --exit-code <lane revision> HEAD -- <owned paths>`, and match `LaneCodeAttestation`; never trust serialized booleans without rechecking. The function requires exactly one verification binding and artifact reference for every non-`None` producer and none for an absent producer, rejects duplicate lane entries or a combination that enables an absent lane/capability/context, requires every selector flag to imply its matching context-level candidate flag, and enforces the closed dependencies `use_row_ocr_selector => use_row_ocr_candidates => use_row_ocr_evidence`, `use_profile_current_selector => use_profile_current_candidates`, `use_merchant_current_selector => use_merchant_current_candidates`, `use_profile_ocr_selector => use_profile_ocr_candidates => use_row_ocr_evidence`, and `use_merchant_ocr_selector => use_merchant_ocr_candidates => use_row_ocr_evidence`. For profile and merchant, each `*_ocr_candidates` flag admits the complete augmented `OCR_VARIANT` context—its internal current batch followed by its OCR batches—while each `*_current_candidates` flag independently admits the current-only context. An augmented selector does not require that separate current-only flag or capability, but it must validate and consume the mandatory current batch inside its enabled `OCR_VARIANT` context. It rejects a foundation/code-attestation, candidate, selector, proof-envelope, support-lineage, auxiliary, or composition-selector identity mismatch or any false required verification flag, requires `model_pin_verified` when and only when `model_pin_required`, and may not discover policies, models, labels, or predictions through global state. Each lane binding names a mandatory raw-candidate identity, the selector identity declared by its frozen policy (if any), and the identity actually enabled by validation (if any); OCR auxiliary identities name every allowed config-specific evidence producer. A declared identity may remain dormant when validation disables every selector context. In that state the enabled `selector_identity` is `None`, `selector_contexts` is empty, `STANDALONE_SELECTOR` is absent, and `LaneProducerSet` contains no selector even though the policy artifact remains immutable. When enabled, `selector_identity` must equal `declared_selector_identity`, contexts must be nonempty and validation-cleared, and the constructed selector must echo it; a disallowed context is never invoked. Envelope lineage is derived from the closed proof/strategy mapping and revalidated after canonical reload; it is never trusted as a caller-selected independence claim. Each bound combination has one split-neutral `COMPOSED` selector identity derived from only the exact clean bake-off-policy revision, chosen `LaneCombination`, ordered enabled upstream evidence/candidate/selector identities, and versioned support-lineage/equivalence/evidence-priority/guard schemas. Explicitly exclude dormant declared identities, run inputs, dataset/prepared/gold pins, artifact paths or pins, verification flags, run/cache paths, code-attestation digests, and the binding digest. Development, validation, and test at the same final revision therefore share that identity, and every emitted composed prediction must echo it exactly.

`LaneProducerSet` is a non-serializable orchestration dataclass, not a Pydantic artifact model; `bakeoff.py` imports `dataclass` from the standard library. Only the producer identities and verification bindings are serialized.

- [ ] **Step 1: Create the bake-off worktree from the frozen foundation**

```bash
ROW_FOUNDATION_SHA="$(git -C .worktrees/row-experiment-foundation rev-parse HEAD)"
test "${#ROW_FOUNDATION_SHA}" -eq 40
test ! -e .worktrees/exp-row-bakeoff
test -z "$(git branch --list codex/exp-row-bakeoff)"
git worktree add .worktrees/exp-row-bakeoff -b codex/exp-row-bakeoff "$ROW_FOUNDATION_SHA"
```

If the target path or branch exists, stop and review it; never silently reuse, delete, or overwrite it.

- [ ] **Step 2: Merge only successful lane tips while preserving their identities**

Review each lane diff and validation verdict. Record each exact clean lane tip, then integrate eligible branches with explicit non-fast-forward merge commits so every `ProducerIdentity.producer_revision` remains an ancestor of the bake-off branch; do not cherry-pick, squash, or rewrite lane commits. Because ownership is disjoint, any conflict is evidence that ownership was violated and must be resolved by returning to the responsible lane, not by an ad hoc integration edit.

For every integrated lane, require `git merge-base --is-ancestor <LANE_SHA> HEAD`, then run `git diff --exit-code <LANE_SHA> HEAD -- <that lane's exclusive source/test paths>`. The second check must be empty after later lane merges and bake-off work, proving the code behind the lane artifact identity remains byte-identical. Record these booleans in the private comparison binding and recheck before each development, validation, or test run.

- [ ] **Step 3: Write combination and precedence tests first**

Canonically enumerate the finite valid hierarchical factorial set over OCR evidence/candidates/selector plus candidate/selector toggles for profile and merchant in current/OCR contexts, subject to the dependency rules above and capabilities actually integrated. Candidate inference is cached once by exact identity/evidence fingerprint, so evaluating combinations never retrains or reruns OCR. This includes evidence-only OCR × profile/tagger interactions and isolates OCR raw-candidate lift, OCR-selector lift, and downstream consumer lift; do not manufacture stopped capabilities. Inject fake optional producers/selectors to prove all cases, sources, text gold, applicable atom gold, variants, serialized proof envelopes, lane verification bindings, producer identities, support lineages, and protected fingerprints are passed explicitly. Reject a combination that enables an absent lane/capability/context, any selector without its matching context-level candidates, OCR candidates without OCR evidence, an OCR selector without OCR candidates, an OCR-context consumer without OCR evidence, an augmented profile/merchant OCR context with a missing/reordered internal current batch or incomplete OCR batch set, bindings/references for absent lanes, missing/duplicate bindings or references, false pin/repeat/privacy flags, a model-required-but-unverified binding, identity/proof/lineage mismatch, absolute/traversing/symlink-escaping artifact paths, wrong model pin, merchant binding/model identity mismatch, and hidden/global loading. Explicitly accept and test `candidate_contexts={OCR_VARIANT}` with positive augmented headroom and zero current-only headroom; enabling that augmented candidate/selector arm must not require `use_*_current_candidates`. Round-trip batches through canonical bytes and select in a fresh process/fake object with no producer-call state; prove the three OCR states independently: variants-only never admits OCR batches/predictions, candidate mode admits batches but never calls the selector, and selector mode does both. Test that one raw producer without a selector always abstains, two strategies under the same identity or lineage still count once, and only an enabled validated selector or agreement across both two distinct validated candidate-producer identities and two distinct closed support lineages can clear the support floor. In particular, OCR's existing `extract_description()` result plus profile `CURRENT_DESCRIPTION_PROOF` alone must abstain even though their producer identities differ. Add same-text current+OCR groundings with different valid atom sets: after consensus, selection must choose the unique current-evidence grounding independent of input order; with no current grounding it chooses the first unique grounding in frozen OCR-policy config order, and it abstains if the selected fingerprint itself has competing atom sets. The composition contract is:

For code attestation, use fake Git inventories to prove that an artifact cannot omit an owned file, add a path outside the fixed roots, hide a newly tracked file, change a mode, substitute a symlink/submodule, or exploit concatenation ambiguity; independently recompute the length-prefixed tree digest and require exact path-set equality at the lane revision and current HEAD. Separately mutate shared `contracts.py`, `metrics.py`, and an imported production module and prove the foundation attestation rejects each at comparison, final replay, and test even though all lane attestations remain valid.

For selector lifecycle, test OCR and profile cases whose development policy declares a selector but whose validation result disables every context: the artifact-declared identity is verified, the enabled binding identity is `None`, selector contexts/capability are empty, no selector object is constructed or called, and safe evidence/candidate capabilities remain available. Also test partial context enablement and reject any enabled identity unequal to the declaration.

1. OCR may add a separate evidence candidate; it never replaces digital/page evidence.
2. OCR has three separable states: evidence-only exposes variants to downstream consumers but admits no OCR candidate; candidate mode additionally admits the frozen raw OCR candidate batches but no selector prediction; selector mode additionally runs the validation-cleared consensus selector. Enforce selector ⇒ candidates ⇒ evidence so the factorial can measure each increment without confounding it.
3. Profile evidence ranks applicable extraction strategies; it never selects a hard exclusive route.
4. The merchant tagger labels atoms from each candidate source.
5. A baseline-semantic-complete case with no frozen recovery trigger always abstains at the top-level composition guard, even when multiple raw candidates agree. The guard uses only frozen baseline observables, never gold/control status.
6. Within one evidence fingerprint, equal text backed by different atom sets is competing support and forces abstention; never choose an atom set by ordering. Across distinct evidence fingerprints, equal rendered text may count as agreement only when every candidate is independently grounded, and atom exactness is scored separately against each fingerprint's optional reviewed partition. After exact-text consensus, choose the output grounding by a fixed proof-independent evidence priority: the unique current-evidence grounding first, otherwise the first unique OCR grounding in frozen policy config order. Input order, proof score, confidence, and gold cannot affect this arbitration.
7. A selector-disabled raw producer can inform interactions but can never propose by itself. Final composition requires either an enabled, validation-cleared selector selecting that exact candidate or agreement on the text from at least two distinct validated candidate-producer identities **and** at least two distinct proof-derived `CandidateSupportLineage` values. Raw strategies/configurations under one identity or lineage are correlated and count once; OCR existing-description extraction and profile current-description proof share `EXISTING_DESCRIPTION_PROOF`. A lone raw batch, or two differently named wrappers around the same lineage, always abstains.
8. Subject to that support floor, a proposal is emitted only when one merchant text survives and the fixed rule above yields exactly one grounding for the selected fingerprint; any remaining text or within-fingerprint atom disagreement means abstain. Private composed artifacts retain the ordered supporting envelope fingerprints and chosen grounding so the decision can be replayed, while `MerchantPrediction` carries the one canonical evidence fingerprint/atom set.
9. No combination can alter the baseline financial fingerprint or status.

Before any bake-off development/validation label is opened, implement and test one deterministic selection function over the paired aggregate results. An experimental arm is eligible only when both split runs and all lane bindings pass every pin/privacy/identity/grounding/protected-outcome/determinism hard gate, both splits have zero wrong proposals and zero wrong control changes, development has no loss in exact cases versus baseline, and validation has at least one recovered baseline failure with strictly greater exact cases than baseline. Among eligible arms, choose lexicographically by: most validation recovered failures; most development recovered failures; most validation exact-atom proposals; fewest total validation proposals; fewest enabled standalone selectors; fewest enabled raw-candidate producers; prefer no OCR evidence; then the canonical `LaneCombination` boolean tuple with `False < True`. Use integer counts only. Tests cover order independence, every rejection condition, exact ties, unavailable capabilities, and the all-ineligible case. If no experimental arm qualifies, record `continue_experiment/no_safe_combination`, do not create `bakeoff_policy.py`, and leave sealed test inputs unopened.

- [ ] **Step 4: Verify and commit the generic bake-off runner before private execution**

```bash
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/bakeoff.py src/ccparser/experiments/row_recovery/__main__.py tests/experiments/row_recovery/test_bakeoff.py
git commit -m "test: freeze row recovery bakeoff runner"
git status --short
```

Expected: all gates pass and the worktree is clean. Construct the comparison binding only from this exact revision and the already verified lane bindings; a code change invalidates it.

- [ ] **Step 5: Run development and validation bake-offs twice**

Before opening development/validation labels, enumerate baseline plus every available-lane combination in a `FrozenBakeoffBinding`, record explicit pinned lane artifact references and exact development/validation `SplitRunInputBinding` records, independently review/pin it, and use these exact command shapes. Every CLI path/pin must equal its selected run-input record:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation current atom-gold SHA-256}"
: "${ROW_BAKEOFF_COMPARISON_BINDING_SHA256:?set the independently reviewed comparison binding SHA-256}"
: "${ROW_BAKEOFF_COMPARISON_REVISION:?set the reviewed clean bake-off runner revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery bakeoff compare \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
  --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/bakeoff/approvals/comparison.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --cache-root "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/bakeoff/development-a" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/development-a/bakeoff" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
  --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
  --expected-binding-sha256 "$ROW_BAKEOFF_COMPARISON_BINDING_SHA256" \
  --expected-bakeoff-revision "$ROW_BAKEOFF_COMPARISON_REVISION" \
  --worktree-root . \
  --split development

PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery bakeoff compare \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
  --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/bakeoff/approvals/comparison.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --cache-root "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/bakeoff/validation-a" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/validation-a/bakeoff" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
  --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
  --expected-binding-sha256 "$ROW_BAKEOFF_COMPARISON_BINDING_SHA256" \
  --expected-bakeoff-revision "$ROW_BAKEOFF_COMPARISON_REVISION" \
  --worktree-root . \
  --split validation
```

When OCR is available, add the exact independently pinned split-specific variant-atom-gold path/pin as `--variant-atom-gold` and `--expected-variant-atom-gold-sha256`; omit both together otherwise. Repeat with new empty `development-b`/`validation-b` run directories and empty lane caches named by the binding. Require byte-identical canonical outputs, compute incremental contribution against every immediate simpler enabled subset, then invoke only the pre-committed deterministic selection function from Step 3. It returns one already bound combination or `None`; no manual override, new arm, or post-result tie-break is permitted. On `None`, record the aggregate no-safe-combination verdict and stop before Step 6 with test still sealed.

- [ ] **Step 6: Commit the chosen non-sensitive combination**

First add focused tests that the absent `bakeoff_policy.py` must expose exactly the chosen pre-registered `LaneCombination` and composition schema and that the private binding must match them. Run the focused test and observe RED because the policy module does not exist. Implement only those non-sensitive constants, run focused GREEN and all tracked gates, and commit. Do not precompute the final binding identity before the commit.

```bash
/root/creditcard/.venv/bin/pytest -q tests/experiments/row_recovery/test_bakeoff.py
/root/creditcard/.venv/bin/ruff format .
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git status --short
git add src/ccparser/experiments/row_recovery/bakeoff_policy.py src/ccparser/experiments/row_recovery/bakeoff.py tests/experiments/row_recovery/test_bakeoff.py
git commit -m "test: freeze row recovery bakeoff policy"
git status --short
```

From that exact clean final-policy revision, derive the new split-neutral `COMPOSED` identity and construct an independently reviewed/pinned `bakeoff/approvals/final-comparison.json` containing only the chosen combination, verified lane references, and development/validation run inputs. Replay the chosen combination twice on both splits before unsealing test:

```bash
set -euo pipefail
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256:?set the independently reviewed development prepared-inventory SHA-256}"
: "${ROW_VALIDATION_PREPARED_INVENTORY_SHA256:?set the independently reviewed validation prepared-inventory SHA-256}"
: "${ROW_DEVELOPMENT_ATOM_GOLD_SHA256:?set the independently reviewed development current atom-gold SHA-256}"
: "${ROW_VALIDATION_ATOM_GOLD_SHA256:?set the independently reviewed validation current atom-gold SHA-256}"
: "${ROW_BAKEOFF_FINAL_COMPARISON_BINDING_SHA256:?set the independently reviewed final comparison binding SHA-256}"
: "${ROW_BAKEOFF_FINAL_REVISION:?set the reviewed clean final bake-off-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_BAKEOFF_FINAL_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery bakeoff replay \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/development.jsonl" \
    --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/bakeoff/approvals/final-comparison.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --cache-root "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/bakeoff/final-development-$ROW_BAKEOFF_FINAL_REPEAT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/final-development-$ROW_BAKEOFF_FINAL_REPEAT/bakeoff" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_DEVELOPMENT_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_DEVELOPMENT_ATOM_GOLD_SHA256" \
    --expected-binding-sha256 "$ROW_BAKEOFF_FINAL_COMPARISON_BINDING_SHA256" \
    --expected-bakeoff-revision "$ROW_BAKEOFF_FINAL_REVISION" \
    --worktree-root . \
    --split development

  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery bakeoff replay \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
    --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/validation.jsonl" \
    --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/bakeoff/approvals/final-comparison.json" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --cache-root "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/bakeoff/final-validation-$ROW_BAKEOFF_FINAL_REPEAT" \
    --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/final-validation-$ROW_BAKEOFF_FINAL_REPEAT/bakeoff" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-prepared-inventory-sha256 "$ROW_VALIDATION_PREPARED_INVENTORY_SHA256" \
    --expected-current-atom-gold-sha256 "$ROW_VALIDATION_ATOM_GOLD_SHA256" \
    --expected-binding-sha256 "$ROW_BAKEOFF_FINAL_COMPARISON_BINDING_SHA256" \
    --expected-bakeoff-revision "$ROW_BAKEOFF_FINAL_REVISION" \
    --worktree-root . \
    --split validation
done
```

If the chosen combination uses OCR, add the exact split-specific variant-atom-gold path and pin to each command; omit both otherwise. Require A/B byte identity per split and semantic parity with the exact chosen arm from Step 5 after excluding only expected bake-off revision, composed identity, binding digest, and run/cache path fields. Candidate texts/atom sets, chosen grounding, dispositions, oracle counts, aggregate metrics, upstream identities, and all safety flags must otherwise match. Do not construct a test binding until this replay succeeds. Any later code/configuration edit invalidates the final identity and replay and requires repeating this step before test preparation.

- [ ] **Step 7: Prepare and annotate the sealed test from frozen code**

Create a detached, clean worktree at the exact recorded preparation revision rather than using the later bake-off HEAD. Stop if the target already exists; never reuse or remove it silently:

```bash
: "${ROW_PREPARATION_REVISION:?set the exact reviewed preparation revision}"
test ! -e .worktrees/row-test-preparation
git worktree add --detach .worktrees/row-test-preparation "$ROW_PREPARATION_REVISION"
git -C .worktrees/row-test-preparation status --short
test "$(git -C .worktrees/row-test-preparation rev-parse HEAD)" = "$ROW_PREPARATION_REVISION"
```

From `.worktrees/row-test-preparation`, the primary agent runs label-free preparation twice. The CLI emits only pass/fail verification booleans for test and withholds diagnostics that could guide tuning:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_PREPARATION_REVISION:?set the exact reviewed preparation revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
for ROW_TEST_PREPARATION_REPEAT in a b; do
  PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli prepare \
    --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
    --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
    --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/test-$ROW_TEST_PREPARATION_REPEAT" \
    --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
    --expected-producer-revision "$ROW_PREPARATION_REVISION" \
    --worktree-root . \
    --split test
done
```

If either run fails, record `no_test_verdict` and do not inspect details, change code, or retune. Otherwise require byte-identical candidates, have an independent reviewer pin the common inventory, and promote without recomputation:

```bash
: "${ROW_TEST_PREPARED_CANDIDATE_SHA256:?set the independently reviewed repeated test candidate SHA-256}"
PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery.preparation_cli promote \
  --candidate-a "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/test-a" \
  --candidate-b "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared-candidates/test-b" \
  --output-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared/test" \
  --expected-inventory-sha256 "$ROW_TEST_PREPARED_CANDIDATE_SHA256"
```

Only now may the primary agent and authorized reviewers open test text gold and the pinned `prepared/test/` cases. Create `MerchantAtomGold` against exact current-evidence fingerprints, perform the same independent disagreement review and `load_atom_gold()` validation as development/validation, and independently pin `atom-gold/current/test.jsonl`. This may classify final oracle stages but cannot change code, models, policy, capability set, or combination.

- [ ] **Step 8: Freeze the test binding and execute the sealed comparison twice**

Construct a new test binding containing baseline plus exactly the committed chosen combination, its canonical composition-selector identity, the exact clean bake-off revision, the same lane artifacts/code attestations, and exactly one test `SplitRunInputBinding` with the newly approved dataset/prepared/current-gold pins (variant gold absent unless separately reviewed after prediction freeze). Independently review/pin it. The primary agent alone supplies matching pins; the `test` subcommand rejects more than baseline plus the chosen combination and has no policy-selection option:

```bash
: "${ROW_PRIVATE_SOURCE_ROOT:?set the trusted private source root}"
: "${ROW_INVENTORY_SHA256:?set the independently reviewed inventory SHA-256}"
: "${ROW_TEST_PREPARED_INVENTORY_SHA256:?set the independently reviewed test prepared-inventory SHA-256}"
: "${ROW_TEST_ATOM_GOLD_SHA256:?set the independently reviewed test current atom-gold SHA-256}"
: "${ROW_BAKEOFF_TEST_BINDING_SHA256:?set the independently reviewed frozen test binding SHA-256}"
: "${ROW_BAKEOFF_TEST_REVISION:?set the reviewed clean frozen-policy revision}"
CCPARSER_ROW_EXPERIMENT_ROOT=/root/creditcard/artifacts/row-experiments
PYTHONPATH=src /root/creditcard/.venv/bin/python -m ccparser.experiments.row_recovery bakeoff test \
  --dataset-root "$CCPARSER_ROW_EXPERIMENT_ROOT/dataset" \
  --prepared-root "$CCPARSER_ROW_EXPERIMENT_ROOT/prepared" \
  --current-atom-gold "$CCPARSER_ROW_EXPERIMENT_ROOT/atom-gold/current/test.jsonl" \
  --binding "$CCPARSER_ROW_EXPERIMENT_ROOT/bakeoff/approvals/test.json" \
  --trusted-source-root "$ROW_PRIVATE_SOURCE_ROOT" \
  --cache-root "$CCPARSER_ROW_EXPERIMENT_ROOT/cache/bakeoff/test-a" \
  --run-dir "$CCPARSER_ROW_EXPERIMENT_ROOT/runs/test-a/bakeoff" \
  --expected-inventory-sha256 "$ROW_INVENTORY_SHA256" \
  --expected-prepared-inventory-sha256 "$ROW_TEST_PREPARED_INVENTORY_SHA256" \
  --expected-current-atom-gold-sha256 "$ROW_TEST_ATOM_GOLD_SHA256" \
  --expected-binding-sha256 "$ROW_BAKEOFF_TEST_BINDING_SHA256" \
  --expected-bakeoff-revision "$ROW_BAKEOFF_TEST_REVISION" \
  --worktree-root . \
  --split test
```

Repeat into a new empty `test-b` directory and require identical complete canonical bytes. Do not compare alternative configurations or retune from test outcomes. OCR variant atom exactness is explicitly unevaluated on test unless the primary agent separately reviews and pins a test variant partition after predictions freeze; that optional review cannot change the policy or primary exact-text result.

- [ ] **Step 9: Record the decision**

Create `docs/experiments/row-recovery-decision.md` containing only non-sensitive aggregate metrics, pin/repeat/privacy verification booleans, exact code branch SHAs, the exact tested code revision (the parent before this docs-only commit), oracle findings, rejected alternatives, and uncertainty. Record one held-out verdict for `ExperimentLane.COMPOSED`: `stop`, `continue_experiment`, or `eligible_for_promotion_plan`. Record each component lane only as `stopped_before_bakeoff`, `no_incremental_validation_contribution`, or `contributed_to_tested_composition`, with its validation capability/context set; a component is never called test-eligible from this single composed test. Keep dataset, prediction, model, and private-policy hashes out of the tracked decision record.

- [ ] **Step 10: Verify and commit the public decision record only**

```bash
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git diff --exit-code -- src tests
git status --short
git add docs/experiments/row-recovery-decision.md
git commit -m "docs: record row recovery experiment decision"
```

### Task 10: Decide whether to design a production promotion

- [ ] **Step 1: Stop if the composed policy does not clear the gates**

Document which oracle ceiling, wrong-change, grounding, invariance, generalization, or determinism gate failed. Preserve the experiment branches and aggregate decision record; do not weaken the gate or retune on sealed test labels.

- [ ] **Step 2: If the composed policy clears the gates, write a new production design and implementation plan**

The promotion target is the exact tested `COMPOSED` policy and its included capabilities, not an inferred per-lane winner. The promotion plan must use shadow comparison first, define the exact production seam, preserve abstention, include rollback, add focused regression tests, and explicitly address performance and optional model artifact distribution. It must not copy the experiment runner wholesale into the parser. A later desire to promote one component independently requires a new pre-registered held-out comparison (or frozen leave-one-lane-out test arms); validation ablations plus this one composed test are insufficient attribution.

- [ ] **Step 3: Apply repository acceptance policy only to promoted production code**

After TDD implementation and all tracked gates, commit the candidate, keep the worktree clean, pin the full SHA and private inventory/baseline digests, and run the formal private `verify` workflow. Any later code/configuration change invalidates that attestation.

## Final Review Checklist

- [ ] Every known failure and every control belongs to exactly one source-family split.
- [ ] Development/validation/test inventory hashes are independently recorded.
- [ ] The test source/case manifests, underlying test sources, prepared cases, labels, annotations, atom gold, and predictions were not read by lane agents.
- [ ] All three lanes started from one exact foundation SHA.
- [ ] Shared foundation files were not edited independently on lane branches.
- [ ] Every candidate is exact-source grounded or abstains.
- [ ] Every financial/status/reconciliation fingerprint is unchanged.
- [ ] Exact merchant text is primary everywhere; exact atom set is primary for every reviewed evidence fingerprint, with the unevaluated denominator explicit.
- [ ] Controls and failure cases are evaluated together.
- [ ] Repeated canonical artifacts are byte-identical.
- [ ] Public logs and docs contain aggregate information only.
- [ ] No experiment result is described as corpus acceptance.
- [ ] Production promotion, if warranted, has a separate reviewed plan.
