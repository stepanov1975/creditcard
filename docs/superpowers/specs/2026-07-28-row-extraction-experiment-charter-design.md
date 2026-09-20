# Transaction-Row Extraction Experiment Charter

**Status:** Approved design authority for the transaction-row extraction experiment
program.

**Authority date:** 2026-07-28

**Last amended:** 2026-09-20

**Accepted comparison anchor:**
`dee4b071ad65231da13825f2f7c74a488ca96c7c`

> **BINDING FOCUS LOCK:** The
> [row-extraction focus-lock design](2026-07-30-row-extraction-focus-lock-design.md)
> narrows the work authorized by this charter. The
> [live program status](../../experiments/row-extraction-program-status.md) is
> authoritative for the sole active phase and next allowed task. Stages 4-6 are
> suspended, the held-out test remains unopened, and marker-first projection,
> controller, provenance, cascade, and production-integration work is frozen.

## Authority and Purpose

This document is the single authoritative design for experiments intended to improve
transaction-row recognition and field extraction in this repository. It exists to prevent
scope drift, preserve fair comparisons, and make every experimental result traceable to one
of four predeclared questions.

The program has exactly four experiments:

1. per-row OCR;
2. deterministic row-type classification with type-specific extraction;
3. a lightweight text model over positioned OCR/PDF evidence tokens; and
4. a lightweight row-image or image-plus-text model.

The accepted pipeline, conditional and forced whole-page OCR baselines, shared data and
metrics, and the final calibrated cascade are comparison infrastructure. They are not
additional experiments.

This charter supersedes conflicting experiment-program intent in earlier uncommitted plans
or experiment branches. Those artifacts remain preserved as historical material, but they
do not authorize work. The research notes cited by this charter provide evidence, not scope.
Repository instructions in `AGENTS.md` and direct user instructions remain higher authority.

## Binding Focus-Lock Authority

The four experiments below remain defined exactly as approved; the focus lock does not add,
remove, combine, or redefine an experiment. It restricts current work to one of these outcomes:

- a runnable implementation of one of the four approved extraction approaches;
- a named extraction-metric measurement or delta;
- a supported or falsified extraction hypothesis; or
- a quantified extraction error category that determines the next experiment.

A task may change one approved extractor, measure a named extraction metric on frozen
document-disjoint development or validation data, or analyze a measured extraction error.
Shared evaluation work is allowed only when an existing local measurement cannot run without
the smallest immediate change. It must not create a reusable controller, schema family, CLI,
receipt chain, or workflow subsystem.

Completed locked-comparison controller and CLI architecture, provenance envelopes, handoff
re-freezing, receipts, replay prevention, attestations, path/inode/cache-independence machinery,
marker-first or other locked-input projection features, cascade execution, locked-test
orchestration, private-corpus controller redesign, and production integration are preserved as
read-only historical evidence. Continuing any of that infrastructure requires direct user
approval followed by a committed charter amendment; approval may not be inferred from a general
request to continue the experiment program.

The live program status is the only authority for which phase is active. Historical stage,
plan, runbook, branch, and artifact state does not authorize a different phase or task.

## Goal

Measure which general, local approach most reliably extracts exact structured credit-card
transaction fields when transaction rows can already be separated reasonably well but text
and fields inside those rows are unreliable, especially merchant descriptions.

The program must produce:

The list below preserves the program's end-state design; it is not current work authorization.
Cascade and locked-test language is preserved historical end-state design and grants no current
authority. Held-out access requires a measured validation gain plus new explicit user approval and
a committed charter amendment.

- a reproducible, private, document-disjoint evaluation dataset;
- independent implementations of all four experiments;
- common baseline and metric implementations;
- comparative measurements and error analysis;
- a confidence-based cascade that abstains on unsupported cases;
- an evidence-backed recommendation; and
- only after a measured winner exists, a minimal production integration plan.

Production integration is not part of the experiment program itself.

## Mandatory Scope Test

Before work starts, every root task, plan task, and subagent prompt must record this block:

```text
Scope answer: YES — <how this changes or measures extraction>
Experiment: <row-ocr | row-profiles | row-text | row-vision | shared evaluation>
Extraction hypothesis: <falsifiable statement>
Measurement: <named metric or predeclared extraction error category>
Fixed inputs: <rows, split, labels, or frozen artifacts>
Smallest allowed files: <exact paths>
Required output: <metric delta, hypothesis result, error count, or runnable extractor>
Stop condition: <condition that ends this task without adding support work>
```

`Experimental invariant`, `reproducibility`, `future integration`, or `trust hardening` alone are
not valid measurements. If this block cannot be completed concretely, the task must not begin.
If the answer changes to `no` while work is underway, the worker must stop, preserve any in-scope
evidence, and return to this charter.

## Metric-or-Stop Rule

At task completion, report:

```text
Scope: YES — <reason>
Experiment: <arm or shared evaluation>
Measurement: <metric or error category>
Result: <delta, supported/falsified hypothesis, quantified finding, or runnable extractor>
Next extraction task: <one task or STOP>
```

If one completed task yields none of the required outputs, stop the program task. Do not create a
second support task to rescue it.

## Definitions

**Shared foundation** means the frozen row observations, private labels and split manifest,
common contracts, metrics, baseline adapters, runner, and privacy-safe reporting used by all
experiments.

**Fixed row** means one row identity and bounding box produced by the accepted comparison
anchor. Holding rows fixed also holds the row count and row membership fixed. An experiment
may not add, remove, split, merge, or move a row.

**Experiment** means one of the four numbered, independent hypotheses in this charter. A
baseline, ablation of an experiment, metric, runner, or cascade is not another experiment.

**Proposal** means a typed candidate field backed by positioned evidence. A proposal is not
an accepted transaction value until deterministic validation succeeds.

**Abstention** means declining to emit an unsupported row or field while recording a stable
reason. Abstention is not an extraction error hidden as an empty string, and it is not a
positive proof that a row should be ignored.

**Locked test** means the document-disjoint test partition that cannot be used for feature,
configuration, model, calibration, threshold, or cascade selection.

**Production integration** means any change to the normal parser path or its public output.
No experiment branch may perform it.

## Non-Negotiable Invariants

1. Row detection remains fixed for the complete four-experiment comparison.
2. Every experiment consumes the same reviewed row identities and document partitions.
3. All rows, pages, and revisions from one source document remain in one partition.
4. Near-duplicate statement revisions and detected layout families remain in one partition.
5. No experiment uses filenames, paths, hashes, document ordinals, merchants, exact dates,
   exact amounts, printed totals, or template identities as predictive features.
6. Every financial number is parsed and compared with `Decimal`, never binary floating point.
7. Learned models propose types or exact evidence spans. They do not author authoritative
   merchant strings, dates, currencies, amounts, signs, or installment values.
8. Reconciliation may reject a candidate. It may not select among candidates or repair a
   prediction merely because the resulting total balances.
9. Private documents, crops, labels, outputs, caches, model artifacts, and derived values stay
   in ignored local paths.
10. The locked test is evaluated only after all four lane dispositions are frozen, including
    every eligible configuration/calibration rule and every valid terminal-stop handoff.
11. The cascade is built only from the locked predictions of validation-eligible frozen
    lanes; every validation-stopped lane remains visible as a required noncandidate
    disposition.
12. Production `src/` behavior remains unchanged until the program has issued a measured
    recommendation and a separate integration design has been approved.
13. A numeric validation or promotion gate requires at least one row that is representable
    by the frozen output/label contract after ambiguity and supervision masks are applied.
    Zero eligible rows is a typed `VALIDATION_STOPPED`, non-evaluable outcome; it is not a
    measured tie, loss, or zero-effect estimate, and uncertainty intervals remain unavailable.
14. A matched ablation pair must have identical data-tier identity, initialization, schedule,
    features, head, optimizer, and runtime except for the one declared ablation. Any additional
    difference invalidates paired promotion evidence even if each artifact is reproducible.
15. Label encoders must report effective row- and field-supervision eligibility. Successfully
    constructing a fully masked target does not make that row eligible for field evaluation.

## Shared Foundation

### Comparison anchor

The accepted comparison anchor is the exact source tree at
`dee4b071ad65231da13825f2f7c74a488ca96c7c`. The shared foundation records the complete
runtime identity relevant to extraction, including Python, PyMuPDF, Tesseract, language
packs, commands, worker count, and configuration.

Baseline outputs and performance measurements are stored privately. Tracked documentation
must not contain document names, merchant text, dates, amounts, totals, row images, private
artifact hashes, or other derived financial values.

### Frozen row observations

The foundation materializes one compact private observation per fixed row. Each observation
contains only what the four experiments need:

- opaque document identity and immutable split role;
- fixed page number, row identity, row bounding box, and column bands;
- positioned digital and accepted OCR words, glyphs, cells, and evidence atom identities;
- source-quality and geometry measurements;
- a versioned row-render recipe and private crop location;
- accepted-anchor row and transaction outcomes for baseline comparison; and
- version identifiers for every transformation.

The compact bundle exists so configuration sweeps do not repeatedly parse complete PDFs or
serialize the production evidence-rich batch output. Bundle creation may observe the
accepted row detector; it may not change the detector.

### Gold annotations

Accepted-anchor output is a baseline proposal, not ground truth. Private review notes may
bootstrap annotation, but every validation and test label used for scoring must be reviewed
against source evidence under one versioned handbook.

The handbook defines:

- primary transaction, continuation, structural/nontransaction, and ambiguous rows;
- exact expected transaction fields;
- exact evidence atom or image-region support for every present field;
- absent-field semantics;
- continuation ownership;
- field-level ambiguity; and
- error categories used in analysis.

Ambiguous source evidence remains explicitly ambiguous and is excluded from claims that
require a unique gold value. It must not be coerced into a convenient training label.

A document-disjoint sample is independently reviewed twice and adjudicated before model
selection. Agreement is reported per row type and field.

### Document partitions

The target partition ratio is 60% development/train, 20% calibration/validation, and 20%
locked test. Group constraints take precedence over exact ratios:

- all observations from a document share one partition;
- near-duplicate revisions share one partition; and
- layout-family groups inferred only for evaluation share one partition.

The split manifest is frozen privately before configuration selection. Development data may
use grouped cross-validation. Calibration/validation data selects OCR configurations,
models, calibrators, thresholds, and cascade policy. The locked test produces one final
comparison after all decisions are frozen.

### Common prediction contract

Every experiment returns the same conceptual result for a fixed row:

- experiment and configuration identity;
- predicted row type;
- zero or more typed field proposals;
- exact supporting evidence atom IDs or image regions;
- raw score and, where applicable, separately calibrated exact-row confidence;
- deterministic validation disposition;
- abstention reasons;
- runtime and resource observations; and
- no generated authoritative financial value.

Shared deterministic renderers derive proposed strings from exact evidence and pass typed
values through the repository's date, currency, installment, and `Decimal` parsers. A field
with no unique support remains absent or causes row abstention according to the annotation
and validation contract.

## Shared Baselines

Every experiment is compared with the same baselines:

1. accepted pipeline output from the comparison anchor;
2. the accepted conditional whole-page OCR behavior;
3. forced whole-page OCR assigned to fixed rows and fixed column bands; and
4. applicable no-learning or no-image controls defined within each experiment.

Forced whole-page OCR may change recognized words, but it may not change fixed row identities
or boxes. Baseline results are materialized through the common prediction contract so metric
code has one path.

## Experiment 1: Per-Row OCR

### Question

Does recognizing each fixed transaction row independently improve exact merchant and field
extraction over accepted and forced whole-page OCR without increasing omissions,
hallucinations, or cross-column ownership errors?

### Fixed inputs

- row identities and row bounding boxes;
- document partitions and gold annotations;
- accepted column bands for the recognition-only comparison; and
- the accepted full-page OCR output.

### Allowed variables

- row-crop padding under a versioned point-to-pixel rule;
- rendering scale/DPI;
- deterministic preprocessing;
- Tesseract page-segmentation mode and language order;
- pinned trained-data variants;
- whole-row versus fixed-field crops; and
- recognition-only versus fixed-row cell reconstruction as separately reported modes.

The sweep is sequential, not an unconstrained Cartesian search. Each stage selects on
development and calibration data before the next stage begins.

### Outputs

Positioned OCR tokens and field proposals mapped back into the fixed row coordinate system,
with crop/configuration identity, OCR confidence, latency, resource use, and abstention
reasons.

### Stop conditions

Stop rather than expand scope if improvements require changing row detection, adding a
document-specific OCR rule, or adding a heavyweight neural OCR dependency. A neural OCR
comparison requires a charter amendment; it is not implicit in experiment 1.

## Experiment 2: Deterministic Row Types and Extraction

### Question

Does a closed, issuer-neutral row-type classifier with type-specific deterministic
extraction improve exact row outcomes and reduce merchant-field ownership errors?

### Fixed inputs

- the same fixed rows, accepted evidence, splits, and labels;
- no learned weights; and
- no merchant, document, date, amount, or template lookup tables.

### Row-type vocabulary

The first-stage vocabulary remains low-cardinality:

- primary transaction;
- continuation;
- structural or nontransaction row; and
- ambiguous/unsupported.

Existing deterministic continuation logic may subtype a proven continuation. A classifier
may not convert ambiguity into a primary transaction.

### Allowed signals

Only general text shape, Unicode script, positioned geometry, inferred column occupancy,
date/money/currency/installment shape, source confidence, and neighboring row structure are
allowed.

### Outputs

A deterministic row type, applicable extraction strategy, exact evidence-backed field
proposals, and explicit ambiguity or abstention reasons.

### Stop conditions

Stop if a residual case can be solved only with a document-, merchant-, filename-, amount-,
date-, total-, or corpus-specific branch. Such a case is recorded in error analysis, not
encoded as a rule.

## Experiment 3: Lightweight Text Model

### Question

Can a small local discriminative model over positioned OCR/PDF tokens identify merchant and
other field spans more accurately than deterministic extraction while remaining fully
evidence-grounded and selectively calibrated?

### Required controls

- deterministic row-type and field extraction from experiment 2;
- a text/shape-only model; and
- a text/shape-plus-geometry model.

### Initial model scope

The primary implementation is a small hashed linear classifier and/or linear-chain sequence
tagger. It predicts the closed row vocabulary and BIO-style roles over existing evidence
tokens. Candidate roles include date, description, billed amount, original amount, currency,
installment, FX detail, ancillary evidence, and outside.

The model artifact remains private. Features must not expose or memorize complete merchant
strings or financial values in tracked files.

### Outputs

Row-type scores, exact token/evidence spans for field roles, sequence legality, calibrated
exact-row confidence, and abstention reasons. The model never emits free-form field values.

### Stop conditions

Stop before introducing transformer or generative text models unless the compact models have
been measured, residual errors are demonstrably textual/semantic, and the user approves a
charter amendment naming the added model, dependency footprint, and question.

## Experiment 4: Lightweight Image or Image-Plus-Text Model

### Question

Do row pixels add held-out information for merchant and field-span recognition beyond the
same text, geometry, and deterministic candidate features?

### Required controls

- the best non-visual feature set from experiment 3 or an equivalent frozen control;
- identical splits, labels, candidates, and calibration procedure; and
- an ablation that removes pixels while keeping the prediction head and nonvisual inputs
  comparable.

### Initial model scope

The primary visual model is a compact MobileNetV3-small-class row or atom-crop encoder
combined with normalized geometry, OCR confidence, Unicode/token-shape features, and existing
candidate signals. It predicts row types or exact evidence atom/span roles.

It does not generate merchant text or transaction JSON. A visual proposal must resolve to one
unique evidence span or deterministically recognized crop before existing field validators
may accept it.

### Outputs

Grounded field-span proposals, row-type scores, pixel-ablation results, calibrated exact-row
confidence, latency, peak memory, artifact size, and repeatability measurements.

### Stop conditions

Stop if pixels do not improve document-held-out selective risk over the nonvisual control.
LiLT, LayoutLM, Florence, Donut, TrOCR, VLMs, or other larger pretrained models are not
implicit follow-ups. Each requires a user-approved charter amendment after the lightweight
result exists.

## Common Measurements

All four experiments report the following on identical eligible observations:

- complete transaction-row exact match;
- merchant exact match and predeclared normalized match;
- transaction date, posting/conversion date where applicable, billed amount, original
  amount, currency, charge/credit kind, installment, and FX-field accuracy;
- field omission rate;
- field hallucination/fabrication rate;
- unsupported-evidence and ownership-collision rate;
- OCR character and word error rate where ground truth exists;
- row-type precision, recall, macro F1, and confusion matrix;
- confidence calibration, Brier/log loss, and reliability diagnostics;
- risk-coverage curve, area under the risk-coverage curve, and coverage at predeclared risk
  thresholds;
- abstention rate and abstention error composition;
- p50/p95 row latency, cold start, throughput, subprocess count, peak RSS, model bytes,
  dependency footprint, and cache bytes;
- byte-identical repeated canonical predictions under a pinned runtime; and
- document-macro and row-micro results by predeclared row type, source mode, script mix,
  acquisition quality, and error category where privacy-safe sample sizes permit.

Confidence is calibrated for the event that the complete emitted row is exactly correct. OCR
confidence, token marginals, geometry confidence, and reconciliation are not substitutes for
that event.

Uncertainty intervals and comparisons resample documents, not rows. The final recommendation
uses paired document-level comparisons and reports practical effect sizes alongside
uncertainty.

### Same-run resource and determinism invariant

Resource observations must describe the exact execution whose canonical prediction artifact
they accompany. A prior prediction execution may not be measured and attached to a later run.
Every measured run is bound before execution to the ordered row-sequence identity/count and
split; frozen arm, runtime, model, and dependency identities; one-worker policy; and a new empty
cache root. The shared runner constructs a fresh arm, measures cold start, fixed-row execution,
memory, subprocesses, footprints, and cache growth, and publishes that execution's predictions
and measurements together.

Recognition or evidence genuinely computed before fixed-row extraction—currently conditional
and forced page OCR—uses a typed preparation record bound to the exact resulting evidence,
rows, runtime, inventories, and empty cache. Reports keep preparation, fixed-row execution, and
end-to-end cost separate. Offline model training is not inference preparation.

The locked comparison performs one measured prediction generation per shared baseline and
eligible frozen lane, then one fresh independent generation solely to verify deterministic
canonical bytes. It does not perform a resource-only prediction generation first. Both page
baseline generations repeat their own preparation from independent empty caches. Validation-
stopped lanes are not opened on locked data.

The accepted-pipeline control is accuracy-only because the shared bundle contains its already-
materialized predictions. Any measured replay cost is labeled `materialized-adapter`, is not
claimed as production extraction cost, and is excluded from resource Pareto dominance. The
conditional/forced page baselines and all four experiments are labeled `end-to-end-method` and
remain comparable on resource axes within the phase definitions above.

## Error Taxonomy

Every wrong or abstained locked-test outcome is assigned one primary cause and optional
secondary causes from a frozen taxonomy:

- OCR substitution, insertion, deletion, or segmentation;
- crop truncation or neighboring-row contamination;
- mixed-direction or Unicode-order error;
- word-box or column-assignment drift;
- row-type error;
- continuation ownership error;
- merchant-span boundary or typed-nondescription error;
- date parsing or year-context error;
- amount, separator, sign, kind, or currency error;
- optional-field ownership error;
- calibration/threshold false acceptance;
- correct abstention on ambiguous evidence; or
- annotation ambiguity or defect.

The taxonomy may be clarified before the locked test, but categories may not be added after
opening locked results merely to make an experiment appear better.

## Cascade

The cascade and locked-test language in this section is preserved historical end-state design and
grants no current authority to construct or run the cascade or open the locked test. Held-out
access requires a measured validation gain plus new explicit user approval and a committed charter
amendment.

The cascade is a post-comparison consumer of frozen predictions, not a fifth experiment. It
is designed only after all four experiments have produced frozen validation dispositions and
every validation-eligible lane has produced its one central locked-test output.

The initial cascade order is selected on calibration/validation data and must obey:

1. preserve an already exact, unambiguous accepted result;
2. consider only proposals with unique source support;
3. run deterministic syntax, type, geometry, ownership, and `Decimal` validation;
4. apply a separately frozen exact-row confidence threshold;
5. use independently shaped agreement only if its rule was frozen before the locked test;
6. use reconciliation only as a terminal rejection check; and
7. abstain on disagreement, overlap, unsupported values, low confidence, or failed
   validation.

The cascade cannot override a supported accepted value merely to improve aggregate metrics.
Its primary comparison is incremental exact coverage at a fixed or lower accepted-row error
risk.

## Isolation and Parallel Work

The charter and shared foundation are developed in
`codex/row-extraction-evaluation`. After the foundation is reviewed and committed, each
experiment starts from that exact foundation commit in an isolated worktree and branch:

- `codex/row-extraction-ocr`;
- `codex/row-extraction-profiles`;
- `codex/row-extraction-text`; and
- `codex/row-extraction-vision`.

Each lane owns one experiment directory and its focused tests. Shared contracts, bundle
formats, split membership, gold labels, and metrics are read-only to experiment lanes. A lane
that needs a shared-contract change must stop and return a proposal to the foundation branch;
it may not change the contract locally.

Private artifacts use separate ignored directories per lane. Parallel workers may not write
the same cache, output, manifest, model, report, or worktree. Subagents receive only their
lane's scope block, interfaces, exact allowed paths, measurements, and stop conditions.

## Program Stages and Gates

### Stage 0: Charter

Deliver this approved, self-reviewed, committed charter and its primary-source research
notes. No experiment code is allowed before this gate.

### Stage 1: Shared foundation

Implement and review private bundle preparation, annotation validation, immutable document
splits, common contracts, baselines, metrics, privacy-safe reports, and deterministic runner.
Freeze a foundation commit before branching experiments.

Gate: all four planned experiments can consume the same synthetic test observation and
private bundle contract without modifying it.

### Stage 2: Four independent experiments

Run experiments 1 through 4 in separate worktrees. Experiments may run in parallel after the
foundation gate. Each lane uses TDD for deterministic behavior and commits focused changes.

Gate: each lane produces validation predictions, configuration/artifact identities, resource
measurements, and an error report through the shared contract. A charter stop condition
produces a typed terminal-stop handoff with its validation evidence; it does not disappear.
An empty contract-representable validation cohort is such a stop and must not be converted
into numeric comparative evidence.

### Stage 3: Configuration freeze

Select one predeclared configuration per eligible experiment using development and calibration
data. Freeze models, OCR settings, preprocessing, calibrators, thresholds, worker counts, and
runtime identity. Preserve any valid terminal-stop handoff unchanged.

Gate: no lane has inspected locked-test metrics.
Every learned or matched-ablation handoff also proves a nonempty effective validation cohort
and exact paired provenance; otherwise it remains validation-stopped.

### Stage 4: Locked comparison — SUSPENDED

This historical stage is not authorized by the current focus lock. It may resume only after a
measured validation gain and the explicit held-out approval recorded in the focus-lock sequence.

Run all shared baselines and every validation-eligible frozen experiment once on the locked
test under the same runner. Repeat canonical prediction generation to measure determinism.
Produce the comparative metric and error-analysis report. A lane that triggered its
predeclared validation stop is reported as validation-stopped and is not opened on locked
data, promoted into the cascade, or treated as a locked-test candidate.

Gate: exactly four lane dispositions exist: a complete locked result or a valid terminal-stop
handoff with validation measurements. A missing lane cannot be silently removed from the
comparison, and a stopped lane cannot be described as a locked result.

### Stage 5: Cascade — SUSPENDED

This historical stage is not authorized while the focus lock is active.

Build and evaluate the confidence-based cascade from eligible frozen candidate outputs and a
validation-selected policy. Do not include validation-stopped lanes, and do not retrain or
retune an experiment using cascade or locked-test results.

### Stage 6: Recommendation — SUSPENDED

This historical stage is not authorized while the focus lock is active.

Recommend the strongest measured option, a bounded combination, or no production change.
The recommendation must identify gains, regressions, uncertainty, failure slices, resource
cost, determinism, and abstention behavior.

### Stage 7: Separate integration decision

Only an evidence-backed winner may trigger a new production-integration design. Integration
requires explicit user approval, production TDD, full tracked verification, and the private
corpus acceptance process from a clean committed candidate. Experiment success alone is not
corpus acceptance.

## Required Checkpoint Report

Every lane checkpoint contains exactly these substantive sections:

1. scope answer and program component;
2. hypothesis tested;
3. fixed inputs and exact configuration;
4. files changed;
5. tests and verification evidence;
6. measurements without private contents;
7. error categories and limitations; and
8. next in-scope action or stop decision.

Do not report unrelated architecture proposals, security work, or speculative follow-ups.

## Explicitly Forbidden Work

The following are outside this program and must not be researched, designed, implemented,
reviewed, or used as a reason to delay an experiment:

- C5a0-P, C5aA, or C5a0-R;
- trusted-worker or pre-import controller architecture;
- deployment attestations;
- cryptographic signatures or crypto dependencies;
- native ptrace/seccomp controller machinery;
- private-corpus acceptance redesign;
- release-bundle or toolchain-authority formalization;
- security-design continuation from `codex/row-preparation-runtime`;
- table or row detection changes during the fixed-row comparison;
- document-, issuer-, template-, merchant-, filename-, path-, hash-, amount-, date-, total-,
  or corpus-specific extraction branches;
- cloud document processing or transmission of source/derived financial data;
- production parser integration before the measured recommendation gate;
- a fifth experiment introduced by renaming a baseline, ablation, cascade, model family, or
  infrastructure task; and
- heavyweight model escalation without a user-approved charter amendment.

Ordinary privacy-preserving experiment code, ignored local artifacts, dependency pinning,
cache keys, and reproducibility metadata are allowed when they directly support a named
experiment measurement. They must remain proportional to that measurement and may not grow
into infrastructure architecture.

## Amendment Procedure

This charter may change only when a direct user instruction approves the changed scope.

An amendment is required before any of the following:

- adding, removing, combining, or redefining an experiment;
- changing fixed row detection or locked split membership;
- changing gold-label semantics after locked-test access;
- adding a heavyweight or generative model family;
- allowing a learned model to generate authoritative values;
- changing the role of reconciliation from rejection to selection;
- modifying production behavior; or
- entering any currently forbidden direction.

The worker must first write a concise proposed amendment containing the reason, affected
experiment, metric, comparison impact, privacy/dependency impact, and invalidated results.
No code or artifact migration may begin until the user approves it. The approved amendment
is committed to this document before work resumes.

Bug fixes that preserve the frozen contract and dependency/configuration corrections within
an already approved lane do not require an amendment, but they invalidate affected
measurements and require reruns.

## Testing and Verification

- Follow Python 3.13 and use the repository virtual environment.
- Follow red-green-refactor TDD for every deterministic behavior.
- Keep functions typed, deterministic, and focused.
- Use synthetic, non-sensitive fixtures in tracked tests.
- Keep private labels, crops, model artifacts, outputs, caches, and reports ignored.
- Run focused tests for every lane change and the required repository verification before
  committing a completed implementation task.
- A sandbox-specific failure in explicitly forbidden controller code is recorded as an
  inherited environment limitation and is not investigated within this program.
- Never claim field accuracy from reconciliation counts, parser status, or tracked tests.
- Never claim private-corpus acceptance without the repository's formal clean-commit verify
  gate after a separately approved production candidate exists.

## Research Basis

The charter's bounded candidates and transfer limits are documented in:

- [`2026-07-28-row-ocr-table-extraction.md`](../../research/2026-07-28-row-ocr-table-extraction.md);
- [`2026-07-28-row-text-models-calibration.md`](../../research/2026-07-28-row-text-models-calibration.md);
  and
- [`2026-07-28-row-vision-multimodal-models.md`](../../research/2026-07-28-row-vision-multimodal-models.md).

These notes may suggest later challengers, but a suggestion is not authorization. This
charter's four experiment definitions and amendment procedure control execution.

## Subordinate Execution Plans

The cascade and locked-test language in this section and the linked plans is preserved historical
end-state design and grants no current authority. Held-out access requires a measured validation
gain plus new explicit user approval and a committed charter amendment.

The implementation plans below translate this charter into TDD tasks. They are subordinate
to this charter: if a plan conflicts with the charter, execution stops and the plan is
corrected; the conflict never silently amends the program.

- [shared fixed-row and evaluation foundation](../plans/2026-07-28-row-extraction-shared-foundation.md);
- [experiment 1: per-row OCR](../plans/2026-07-28-row-targeted-ocr-experiment.md);
- [experiment 2: deterministic row types](../plans/2026-07-28-deterministic-row-type-experiment.md);
- [experiment 3: lightweight text model](../plans/2026-07-28-row-text-field-model-experiment.md);
- [experiment 4: lightweight vision/image-plus-text model](../plans/2026-07-28-row-vision-field-model-experiment.md); and
- [central comparison, cascade, and recommendation](../plans/2026-07-28-row-extraction-comparison-cascade.md).

Only the central comparison plan may open the locked test. Experiment lanes end at a frozen
validation handoff. Baselines and the cascade remain comparison infrastructure, never extra
experiments.

## Acceptance Criteria for This Charter

The charter is ready for implementation planning only when all of the following are true:

- exactly four experiments are named and bounded;
- baselines and cascade are explicitly non-experiments;
- row detection and dataset partitions are fixed;
- shared and lane-owned responsibilities are unambiguous;
- every experiment has a question, inputs, outputs, controls, and stop conditions;
- common metrics cover exactness, omission, hallucination, calibration, abstention,
  resources, determinism, and error slices;
- forbidden context-drift directions are explicit;
- new directions require a user-approved committed amendment;
- production integration is a separate post-evidence decision; and
- no private corpus contents or derived financial values are recorded in the charter.

## Proposed charter amendment

**Reason:** The current frozen supervision contains measured RTL/order, segmentation, ambiguity,
and crop-context concerns that can prevent the four extraction arms from being compared against
semantically adequate targets.

**Affected experiment:** Shared evaluation only. The four extraction implementations remain frozen.

**Authorized change:** Generate one parallel visual-gold v2 candidate for the 2,503 training rows
using a 100-row blind dual-review pilot followed, only on passing agreement gates, by blind dual
review and disagreement adjudication of the remaining rows. Learned visual reviewers may generate
candidate values under this protocol. Existing gold remains authoritative.

**Measurement:** Pre-adjudication row-type agreement, field exact agreement, evidence-support
agreement, annotation ambiguity/defect counts, ambiguity rate, and eligible exact-row rate.

**Comparison impact:** Round 1 results remain historical and valid only against their original gold.
Training scores against the candidate are diagnostic and cannot select a winner. Promotion or
validation labeling requires separate approval.

**Privacy and dependency impact:** All images, contexts, reviewer outputs, labels, and financial
content remain in ignored local artifacts. No new package, hosted service, or heavyweight model
dependency is introduced; review uses the available Codex visual capability in isolated contexts.

**Invalidated results:** None while the artifact remains a candidate. If a later amendment promotes
visual-gold v2, every score computed against old gold is invalidated and must be rerun under the
promoted version.

**Held-out boundary:** Validation and held-out data remain unopened by this task.

## Approved amendment: merchant context sufficiency

**Approval date:** 2026-08-07

**Reason:** The stopped visual-gold pilot measured systematic reviewer policy differences rather
than merchant accuracy. All core financial roles agreed, while description disagreements were
concentrated in whether continuation text was merchant-bearing or ancillary. The product goal
requires correct merchant attribution, so the next measurement must test which source context
produces the best transaction-level merchant result against an independent reference.

**Affected experiment:** Shared evaluation only. The four extraction implementations and all
Round 1 results remain frozen.

**Authorized change:** Run exactly one training-only merchant-context sufficiency experiment under
the approved
[design](2026-08-07-merchant-context-sufficiency-design.md). Reuse the 100 frozen pilot row
identities as opaque anchors without reusing or adjudicating either reviewer stream. Freeze an
independently source-adjudicated transaction reference before arm execution. Compare the six
nested `C0 row` through `C5 full-page` context tiers using the same model, prompt, decoding, pixel
representation, positioned-text representation, and output contract; only spatial context may
change.

**Measurement:** Transaction-level merchant-attribution accuracy, exact merchant-bearing-text
rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, reference
ambiguity, and paired gains and losses by context tier. The result must support or falsify the
predeclared context-sufficiency hypothesis and identify the smallest best safe tier or report that
no safe tier exists.

**Decision rule:** Any wrong-merchant or hallucination event makes an arm unsafe. Among safe arms,
maximize the correctly attributed transaction set, then the exact merchant-bearing-text set, then
choose the smallest tier. Ancillary category, location, processor/reference, exchange-rate, and
fee text does not become release-critical merchant evidence merely because reviewers classified
it differently.

**Comparison impact:** The failed visual-gold pilot remains stopped and is not rescued, relabeled,
adjudicated, or reinterpreted as an accuracy result. This training measurement cannot select a
production change or justify held-out access. Existing Round 1 comparisons remain historical.

**Privacy and dependency impact:** Source images, atoms, reference values, merchant text, arm
outputs, and financial data remain ignored and local. Tracked outputs contain aggregate counts and
rates only. No new package, hosted service, heavyweight model, reusable controller, CLI family,
schema family, receipt chain, attestation system, or workflow subsystem is authorized.

**Invalidated results:** None. The new result answers a different predeclared question and does
not alter prior labels, predictions, or scores.

**Stop boundary:** Stop before arm execution if the independent reference cannot be frozen without
current gold, accepted parser output, previous reviewer values, or experiment predictions. Stop
after the one frozen scoring run with the Metric-or-Stop report. No failed arm, missing
convenience, or inconclusive outcome authorizes a rescue task.

**Held-out boundary:** Validation and held-out data remain unopened. Any validation measurement,
production integration, or production acceptance work requires separate direct user approval and
a committed amendment.

## Approved amendment: human-reviewed merchant gold seed

**Approval date:** 2026-09-12. The user approved proceeding with the concrete seed
recommendation after confirming they can review a small initial set.

**Reason:** Existing measurements show unresolved merchant-definition differences
and a detected-table context blocker. A human-established reference from complete
source pages is needed before further extractor comparison.

**Affected experiment:** Shared evaluation only. The four extraction arms and
both historical stopped pilots remain unchanged.

**Authorized change:** Execute the single bounded task in the
[seed design](2026-09-12-merchant-gold-seed-design.md) and
[plan](../plans/2026-09-12-merchant-gold-seed.md): select six training pages from
six documents, with two OCR and four digital-only pages, and prepare four blank
transaction review slots per page. Render complete source pages independently of
detected table geometry. The human establishes transaction ownership, merchant
text, supporting regions, and ambiguity from source evidence. Keep the new seed
separate from prior row labels; coincident source-page overlap does not permit
reading or changing prior reviewer streams.

**Small immediate evaluation exception:** A disposable local HTML worksheet and
one-off preparation/check scripts may be generated only under ignored
`artifacts/merchant-gold-seed-v1/` for this fixed packet. They may display source
pages, collect human evidence regions/text, and import/export answers locally.
No reusable annotation application, controller, server, new package, cloud service,
schema family, or production interface is authorized.

**Measurement:** Source availability and complete-page materialization counts;
after human review, reference eligibility, merchant absence/ambiguity, missing
slots, and boundary/ownership issue counts. The predeclared hypothesis is at least
20 supported unambiguous merchant references among 24 fixed slots. Until review,
reference results are `NOT MEASURED`; packet preparation is not golden-label
acceptance or extraction accuracy.

**Privacy:** All source copies, images, private identities, worksheets, answers,
and derived values stay local and ignored. No private content is sent to model
tools or external services. Public reports contain aggregate counts only.

**Stop boundary:** No relabeling of the failed pilot, no resampling to improve an
outcome, no generated model labels in the first human pass, and no expansion beyond
the fixed seed. At handoff the sole active state is `AWAITING_HUMAN_REVIEW`.
Continue only on the user's source decisions; do not create support work while
waiting. Missing selected source or an unavailable required measurement ends the
attempt with its quantified category.

**Future boundary:** Broader annotation, independent reviewer recruitment,
synthetic generation, context arms, extraction runs, gold promotion, validation,
held-out evaluation, and production integration need separate direct approval.

## Approved amendment: merchant seed comparison

**Approval date:** 2026-09-12. The user explicitly approved the recommendation to
compare existing extraction methods against the 24 reviewed merchant references
before expanding the dataset.

**Authorized change:** Execute the one diagnostic training comparison in the
[comparison design](2026-09-12-merchant-seed-comparison-design.md) and
[plan](../plans/2026-09-12-merchant-seed-comparison.md). Replay the accepted-anchor
projection and invoke the existing frozen profile configuration and pre-existing
OCR baseline on the six selected pages. Record text/vision candidate unavailability
without training or choosing a rejected model. Historical validation dispositions
remain unchanged.

**Small immediate evaluation exception:** The existing row-level gold scorer
cannot consume the new independent transaction-region references. Permit only
one-off local geometry alignment, evidence rendering, and merchant scoring code,
its OCR invocation helper, and invented-input checks under ignored
`artifacts/merchant-seed-comparison-v1/`. This is not permission to extend the
historical controller, create a reusable workflow, or convert/promote gold.

**Measurement:** Normalized merchant exact matches, coverage, omissions,
row-alignment failures, lexical mismatch categories, and paired exact-match gains
and losses relative to the accepted projection. All 24 cases remain visible.

**Privacy and stop boundary:** Sources, reference text, and predictions stay local
and ignored. No private content enters model tools or external services. Stop
after the comparison and report. No method tuning, new labels, sample expansion,
gold promotion, validation/test access, or production integration is authorized.

## Approved amendment: merchant proposals before row rejection

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to measure deterministic merchant extraction before whole-row
rejection, after currency ambiguity blocked 19 of 20 matched owner rows.

**Authorized change:** Execute the single diagnostic measurement in the
[design](2026-09-12-merchant-pre-rejection-design.md) and
[plan](../plans/2026-09-12-merchant-pre-rejection.md). Invoke the frozen profile's
existing description helper before financial checks, keeping classification,
ownership, merchant rules, and original transaction decisions unchanged. Reuse
the same 24 references, saved alignment, 127 observations, and prior scorer.

**Immediate measurement allowance:** A disposable private probe and focused
invented-input tests under ignored `artifacts/merchant-pre-rejection-v1/` may
call the existing helper and score diagnostic proposals. No historical or
production source changes, reusable controller, CLI, or schema family are needed
or authorized.

**Measurement and stop boundary:** Report exact-match and coverage deltas,
omissions, ambiguous outputs, and merchant availability on currency-blocked
owners. More proposals alone do not support the accuracy hypothesis. Stop after
the fixed measurement. Sources, labels, alignment, model inputs, transaction
acceptance, sample membership, validation/test access, and production integration
remain unchanged. Private evidence and results stay local and out of Git and
external model tools.

## Approved amendment: merchant evidence error analysis

**Approval date:** 2026-09-12. The user approved the concrete recommendation to
inspect the ten remaining nonmatching descriptions using existing merchant regions.

**Authorized change:** Execute the [design](2026-09-12-merchant-evidence-error-design.md)
and [plan](../plans/2026-09-12-merchant-evidence-errors.md): analyze only the ten
saved pre-rejection text mismatches, comparing declared evidence boxes with human
merchant regions and measuring text-order, spacing, format-control, and character
edit diagnostics. No new prediction or annotation is generated.

**Immediate measurement allowance:** A disposable analysis script and focused
invented-input tests under ignored `artifacts/merchant-evidence-errors-v1/` may
read the existing private artifacts and source PDF page geometry. No rendering,
new PDF text extraction, OCR, new shared schema, CLI, controller, or external
content transmission is authorized.

**Measurement and stop boundary:** Report region-support categories, possible
unselected evidence records, text signatures, and character error rate. Preserve
all labels, predictions, exact-match outcomes, alignment, source observations,
and transaction decisions. Stop after the fixed error analysis. Validation/test
access, sample expansion, gold promotion, and production integration remain closed.

## Approved amendment: merchant reading-order experiment

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to test a general Hebrew/Latin reading-order rule on the same
merchant evidence and all 24 references, measuring gains and regressions.

**Authorized change:** Execute the single fixed candidate in the
[design](2026-09-12-merchant-reading-order-design.md) and
[plan](../plans/2026-09-12-merchant-reading-order.md). Reorder existing description
atoms using line geometry and Unicode direction, preserving text, membership,
ownership, all original transaction decisions, and historical source trees.

**Immediate measurement allowance:** A disposable private candidate and
invented-input tests under ignored `artifacts/merchant-reading-order-v1/` may
consume saved pre-rejection predictions and reuse the existing renderer/scorer.
No shared infrastructure, new schema, CLI, controller, library, source extraction,
OCR, or external content transmission is authorized.

**Measurement and stop boundary:** Report exact-match delta, paired gains/losses,
coverage, OCR/digital slices, and resolution of the two saved word-order errors.
Require at least two gains and zero losses to support the hypothesis. Score all
24 fixed training references once and stop; no answer-driven tuning, sample
expansion, gold promotion, validation/test access, or production integration.

## Approved amendment: merchant-region OCR experiment

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to test local OCR confined to extractor-selected merchant regions
against the improved 10/24 deterministic comparator on the same 24-case seed.

**Authorized change:** Execute the single candidate in the
[design](2026-09-12-merchant-region-ocr-design.md) and
[plan](../plans/2026-09-12-merchant-region-ocr.md). Render the union of each saved
merchant proposal's atom boxes and invoke the existing frozen OCR baseline
recognizer, then apply the already fixed reading-order rule to the new atoms.
Human-marked regions and merchant text must not guide prediction.

**Immediate measurement allowance:** Disposable private crop/recognition code,
a scorer, and invented-input tests under ignored `artifacts/merchant-region-ocr-v1/`
may invoke existing rendering/OCR helpers and read the six selected local source
copies. No historical source edit, new model/dependency, reusable controller,
shared schema, CLI, workflow, or external content transmission is authorized.
The OCR lane's historical validation stop remains unchanged.

**Measurement and stop boundary:** Score all 24 references against the fixed
10/24 comparator, report paired gains/losses, coverage, slice outcomes, and crop
or recognition failures. A positive net exact-match gain supports the hypothesis.
Stop after one fixed comparison. No tuning, retry with changed settings, new
labels, expansion, gold promotion, validation/test access, or production integration.

## Approved amendment: merchant alignment-error diagnosis

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to investigate the four reviewed transactions with no matching
frozen row, distinguishing coordinate/alignment failure from missing row coverage.

**Authorized measurement:** Execute the single diagnostic in the
[design](2026-09-12-merchant-alignment-errors-design.md) and
[plan](../plans/2026-09-12-merchant-alignment-errors.md). Reproduce saved alignment,
check its coordinate calculation independently, and quantify row-box exclusion
and in-region atom evidence for the four saved failures.

**Immediate measurement allowance:** Disposable geometry analysis and invented
input tests under ignored `artifacts/merchant-alignment-errors-v1/` may read the
existing reference regions, selected row/atom boxes, six source-page geometries,
and review-image headers. No new rendering, text extraction, OCR, external content
transmission, historical code edits, or reusable shared infrastructure is authorized.

**Measurement and stop boundary:** Report alignment-failure categories,
coordinate agreement, and transaction/merchant atom support. Preserve original
labels, rows, matches, predictions, and merchant scores. Stop after this fixed
diagnosis; no rematching, threshold changes, geometry repair, new labels, sample
expansion, gold promotion, validation/test access, or production integration.

## Approved amendment: merchant discovery coverage trace

**Approval date:** 2026-09-12. The user's “proceed” approved comparing the affected
page's original discovery metadata with its 38 frozen rows and four unmatched
human regions to locate discovery versus freezing coverage loss.

**Authorized measurement:** Execute the [design](2026-09-12-merchant-discovery-coverage-design.md)
and [plan](../plans/2026-09-12-merchant-discovery-coverage.md). Check for a retained
original discovery snapshot bound to bundle preparation before measuring missing
rows and reference coverage. Read historical preparation code as contextual evidence.

**Immediate allowance and stop boundary:** A disposable local availability or
geometry check may write only under ignored `artifacts/merchant-discovery-coverage-v1/`.
If original discovery metadata is unavailable, report its 0/1-page availability
and the historical loss as NOT MEASURED, then stop. Do not substitute a later run,
reconstruct original evidence, or create archive/controller infrastructure.

Preserve the four reference cases, matches, frozen rows, and merchant scores.
No new extraction, OCR, rendering, labels, expansion, gold promotion,
validation/test access, or production integration is authorized. Private evidence
and identities remain local and out of Git and external tools.

## Approved amendment: new one-page merchant discovery diagnostic

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to run one new local page-discovery diagnostic against the four
fixed unmatched reference regions. This authorization is separate from the
completed historical trace, which stopped when its original snapshot was absent.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-page-discovery-design.md) and
[plan](../plans/2026-09-12-merchant-page-discovery.md). Use frozen native PDF
extraction helpers on only the affected digital training page, followed by the
frozen logical-row and discovery functions. Score native-evidence, logical-row,
and discovered-row coverage of the unchanged four regions against zero frozen
coverage; distinguish all results from historical evidence.

**Immediate allowance:** A disposable private selected-page adapter, geometry
measurement, and invented-input tests may write only under ignored
`artifacts/merchant-page-discovery-v1/`. Preserve the source page's geometry and
number; no other page evidence, rendering, OCR, external service, historical
source edit, shared infrastructure, or controller is authorized.

**Stop boundary:** Stop after one new native-text diagnostic with covered-case
counts and its hypothesis result. Preserve all original inputs, matches, labels,
merchant scores, and transaction decisions. No tuning, rematching, new labels,
expansion, gold promotion, validation/test access, or production integration.

## Approved amendment: merchant discovery exclusion trace

**Approval date:** 2026-09-12. The user's “proceed” approved tracing the discovery
rule that excludes logical rows covering four fixed unmatched references,
distinguishing intended filtering from missed transaction regions.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-discovery-exclusion-design.md) and
[plan](../plans/2026-09-12-merchant-discovery-exclusion.md). Observe one unchanged
discovery execution on the saved one-page native evidence. Require exact saved
output parity, then count candidate coverage and the existing exclusion decisions.

**Immediate allowance and stop boundary:** A disposable private observer,
attribution, and invented-input tests may write only under ignored
`artifacts/merchant-discovery-exclusion-v1/`. No frozen code edits, changed
returns or settings, new source extraction/OCR, alternate runs, shared tracing
library, controller, or workflow subsystem is authorized. Stop after the fixed
trace with a filter hypothesis result and quantified exclusions or uncertainty.

Preserve all references, original artifacts, matches, merchant scores, and
transaction decisions. No reference repair, new labels, expansion, gold
promotion, validation/test access, or production integration is authorized.

## Approved amendment: merchant comparison before future-billing exclusion

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to compare merchant recognition before the future-billing filter
on the same 24 references, keeping production billing decisions unchanged.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-prefilter-comparison-design.md) and
[plan](../plans/2026-09-12-merchant-prefilter-comparison.md). Apply the frozen tight
profile classifier, existing description probe, and fixed reading-order rule to
all eight rows of the saved excluded candidate table. Combine their diagnostic
merchant proposals with unchanged historical predictions and measure paired
exact-match/coverage changes against 10/24.

**Immediate allowance:** A disposable private row adapter, scorer, and
invented-input tests may write only under ignored
`artifacts/merchant-prefilter-comparison-v1/`. Existing pure summary/atom functions
and contracts may be reused without invoking bundle preparation, controller,
handoff, or provenance workflows. A separate diagnostic alignment may cover the
four original null cases; original alignment, rows, labels, and scores stay fixed.

**Stop boundary:** Score the one fixed candidate on all 24 references and stop.
No source extraction, discovery rerun, OCR, alternate candidate, rule tuning,
financial acceptance, new labels, expansion, gold promotion, validation/test
access, or production integration is authorized. Private data stays local.

## Approved amendment: residual merchant error analysis

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to analyze the remaining 11 failures against existing merchant
regions, distinguishing text errors from selection and ownership problems.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-residual-errors-design.md) and
[plan](../plans/2026-09-12-merchant-residual-errors.md). Reproduce the current
24-case scores, then inspect only the nine text mismatches, one omission, and
one ambiguous output. Measure proposal/retained-atom region support, ownership
conflicts, saved omission gates, text signatures, and character error rate.

**Immediate allowance:** Disposable private analysis and invented-input tests
may write only under ignored `artifacts/merchant-residual-errors-v1/`. Existing
geometry, renderer, scorer, and text helpers may be reused. Source copies may
be read only for identity and selected-page geometry. No new extraction,
rendering, OCR, model call, shared schema/controller, or workflow is authorized.

**Stop boundary:** Stop after the fixed 11-case analysis with quantified error
categories and its hypothesis result. Preserve all predictions, references,
alignments, transaction decisions, and the 13/24 score. No tuning, new candidate,
reference repair, labels, expansion, gold promotion, validation/test access, or
production integration is authorized.

## Approved amendment: merchant primary/continuation assembly

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to test assembly of primary and explicitly owned continuation
merchant descriptions on the same 24 references, following the residual analysis.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-continuation-assembly-design.md). Use all 135 saved
pre-filter predictions and their rows. Assemble only eligible primary/continuation
description groups using unchanged evidence and the existing page reading order;
measure exact merchant match, unique-output coverage, and paired gains/losses
against 13/24. Candidate generation must not read labels or human regions.

**Immediate allowance and stop boundary:** A disposable private assembly helper,
invented-input tests, and one comparison may write only under ignored
`artifacts/merchant-continuation-assembly-v1/`. No shared schema, controller, CLI,
source extraction, OCR, discovery, model call, or frozen-arm modification is
authorized. Preserve original predictions, evidence, ownership, alignment,
references, and billing decisions. Stop after one candidate comparison; no tuning,
new labels, expansion, gold promotion, validation/test access, or production
integration is authorized. Private data stays local and out of Git.

## Approved amendment: merchant omission alignment and evidence routing

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to trace the remaining omission through its saved row alignment
and classification, following the completed primary/continuation assembly test.

**Authorized measurement:** Execute the
[design](2026-09-12-merchant-omission-routing-design.md). Reproduce the saved
scores and affected page's alignment, then quantify the omission's alignment
ranking, strongly located merchant-record routing, classifier proofs, and saved
probe gate. Reconstruct frozen profile/classification evidence only for the
aligned row, merchant-bearing rows, and their direct owners; require saved-type
parity. Source access is limited to identity and selected-page geometry.

**Immediate allowance and stop boundary:** A disposable private trace,
invented-input tests, and immediate checks may write only under ignored
`artifacts/merchant-omission-routing-v1/`. No new prediction, field extraction,
rematching, OCR, source-text extraction, model call, generic tracer, shared schema,
controller, or workflow is authorized. Preserve references, outputs, alignment,
classification, ownership, and billing decisions. Stop after the one trace with
a quantified omission finding and hypothesis result or reproduction disagreement.
No tuning, new labels, expansion, gold promotion, validation/test access, or
production integration is authorized. Private data stays local and out of Git.

## Approved amendment: merchant-region alignment comparison

**Approval date:** 2026-09-12. The user's “proceed” approved the concrete
recommendation to compare merchant-region-supported alignment on the same 24
references after the omission-routing trace.

**Immediate shared-evaluation allowance:** The existing transaction-box matcher
cannot attribute one reference's merchant recognition to its retained merchant
evidence. Execute the [design](2026-09-12-merchant-region-alignment-design.md) with
one disposable source-atom eligibility predicate: require strongly located
alphabetic evidence in the marked merchant region, then preserve transaction
overlap ranking, unique-best selection, and collision handling. Apply it to all
24 references, preserving the original alignment, labels, predictions, and output
ownership. Score only the unchanged saved assembly outputs.

**Authorized measurement and stop boundary:** Measure alignment coverage, exact
merchant match, unique-output coverage, and paired gains/losses against 13/24.
Private helpers, invented-input tests, and immediate checks may write only under
ignored `artifacts/merchant-region-alignment-v1/`. Source access is limited to
identity and selected-page geometry. Stop after one fixed comparison. No reusable
evaluator, schema, controller, CLI, workflow, new prediction, OCR, source extraction,
rule tuning, reference repair, labels, expansion, gold promotion, validation/test
access, or production integration is authorized. Private data stays local.

## Approved amendment: blind merchant repeat-transcription audit

**Approval date:** 2026-09-13. The user's “proceed” approves the concrete
recommendation for a blind second transcription of the 11 remaining merchant
disagreements, following the completed merchant-region alignment comparison.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-13-merchant-blind-review-design.md). Reuse the existing seed
worksheet and source-page images to collect a second source reading with previous
answers and model suggestions hidden. A disposable local worksheet adaptation,
private case mapping, and immediate checks may write only under ignored
`artifacts/merchant-blind-review-v1/`. This allowance is necessary to measure
reference inconsistency; it does not authorize a reusable annotation subsystem.

**Authorized measurement and stop boundary:** Measure repeat-transcription exact
agreement, changed-reference count, ambiguity, and ownership/boundary issues on
the fixed 11 training cases. Preserve original labels, images, predictions,
alignment, and outputs. Pause at handoff for the human answers; report the
measurement and stop when they arrive. No automated transcription, new source
rendering, reference replacement, expansion, gold promotion, extraction tuning,
validation/test access, or production integration is authorized. All private
data stays local and out of Git.

## Approved amendment: six-case merchant source adjudication

**Approval date:** 2026-09-13. The user's “proceed” approves the concrete
recommendation to adjudicate the six cases with changed text or regions after
the completed blind repeat-transcription audit.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-13-merchant-adjudication-design.md). Adapt the existing disposable
local worksheet to show both human readings and their regions with the existing
source pages. Leave final decisions unselected and model outputs hidden. Permit
editable draft copying, explicit source-check confirmation, and a reason for
each human decision. This minimum adaptation and its checks may write only under
ignored `artifacts/merchant-adjudication-v1/`; no reusable workflow is authorized.

**Authorized measurement and stop boundary:** Measure resolved references,
unresolved ambiguity, and adjudicated text/region agreement with each previous
reading for the fixed six training cases. Preserve both original submissions,
references, source images, and predictions. Pause for human decisions, retain
them separately, then measure resolution and stop. No automated adjudication,
reference promotion, source rendering, OCR, model call, prediction rescoring,
expansion, validation/test access, or production integration is authorized.

## Approved amendment: adjudicated merchant reference v2 comparison

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-reference-v2-report.md) records
17/24 exact against v2 versus 13/24 against v1, with four text-reference gains,
zero losses, and no assignment changes. The allowance below is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the concrete
recommendation to create a separate adjudicated 24-case training reference and
re-score the same saved merchant outputs after the six-case adjudication.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-reference-v2-design.md). Project the six confirmed
human decisions into a separate existing-shape reference file, preserving the
other 18 records and v1. Record the existing review-depth distinctions privately.
Use the unchanged scorer and merchant-region matcher for three views: original
reference/alignment, updated text with original alignment, and updated reference
with alignment recomputed from corrected regions. This is the minimum local
measurement needed to distinguish text and region effects on the saved outputs.

**Authorized measurement and stop boundary:** Measure exact merchant match,
alignment coverage, unique-output coverage, and paired gains/losses on the fixed
24 training cases and 135 saved rows. Private projection, immediate checks, and
comparison artifacts may write only under ignored `artifacts/merchant-gold-seed-v2/`.
Preserve original labels, predictions, outputs, billing decisions, and frozen
branches. Stop after this comparison; no new extraction, OCR, model call,
reusable evaluator/controller/schema/CLI, reference tuning, new labels, expansion,
validation/test access, accepted-gold promotion, or production integration is
authorized. All private contents remain local and out of Git.

## Approved amendment: remaining merchant seed blind repeat reading

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-remaining-blind-review-report.md)
records 12/13 exact repeats, one changed OCR transcription, and four cases with
changed regions. No reference replacement occurred. The allowance is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed v2
reference comparison's concrete recommendation to repeat-read the remaining
13 single-read cases, with prior answers and extraction outputs hidden.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-remaining-blind-review-design.md). Select the exact
13 single-read cases from the existing 24-case training reference, verifying
the complement of the earlier 11-case audit. Adapt the existing disposable local
blind-review form and reuse source-page images and target regions. Preparation,
checks and eventual answers may write only under ignored
`artifacts/merchant-remaining-blind-review-v1/`.

**Authorized measurement and pause/stop boundary:** Measure repeat-transcription
exact agreement, changed-reference counts, uncertainty, explicit boundary/ownership
issues, and region changes for those 13 cases. Pause for human answers, retain
them separately, then measure and stop. Preserve both references, all prior
submissions, review-depth metadata, predictions, and the saved 17/24 score.
No prediction access, new extraction, OCR, source rendering, hosted service,
reusable review infrastructure, adjudication, reference replacement, expansion,
validation/test access, accepted-gold promotion, or production integration is
authorized. All private contents remain local and out of Git.

## Approved amendment: remaining merchant seed source adjudication

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-remaining-adjudication-report.md)
records four resolved-present references, all matching the first merchant text,
with zero unresolved cases. No reference replacement occurred. The allowance
is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed
remaining-case repeat audit's recommendation to adjudicate its four cases with
changed text or regions, with both human readings, regions and notes visible.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-remaining-adjudication-design.md). Use exactly three
OCR cases and one digital case from the completed 13-case audit. Adapt the existing
disposable adjudication form to display the prior human notes as text and reuse
the existing source-page images. Preparation, checks and returned decisions may
write only under ignored `artifacts/merchant-remaining-adjudication-v1/`.

**Authorized measurement and pause/stop boundary:** Measure resolved-reference
counts, unresolved ambiguity, and final text/region agreement with both prior
readings. Pause for four human decisions, retain them separately, then measure
and stop. Preserve both reference versions, existing review-depth metadata, all
earlier submissions and the saved 17/24 score. No prediction access, new extraction,
OCR, source rendering, hosted service, reusable review infrastructure, automatic
adjudication, reference replacement, sample expansion, further review, held-out
access, accepted-gold promotion or production integration is authorized. All
private contents remain local and out of Git.

## Approved amendment: fully reviewed merchant reference v3 comparison

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-reference-v3-report.md) records
17/24 exact in all three views, with zero gains/losses or assignment changes.
Review depth is complete: 14 agreeing repeats and ten adjudications. The allowance
below is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed
remaining-adjudication report's concrete recommendation for a separate fully
reviewed v3 reference and rescoring of the same saved outputs.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-reference-v3-design.md). Project the four remaining
human adjudications into a separate existing-shape reference; preserve the
other 20 v2 lines and all older versions. Update the existing private review-depth
mapping to 14 agreeing repeats and ten adjudications. This is the smallest local
update needed to measure the completed review's effect on saved extraction.

**Authorized measurement and stop boundary:** Reproduce the saved 17/24 v2
baseline, then measure v3 text with fixed v2 alignment and v3 text with recomputed
alignment. Use the unchanged scorer, matcher, 24 training cases, 135 saved rows
and assembly outputs. Report exact match, alignment and unique-output coverage,
paired gains/losses and digital/OCR slices. Private writes are limited to ignored
`artifacts/merchant-gold-seed-v3/`. Stop after the comparison or a baseline
reproduction failure. No extractor tuning, new predictions, OCR, models, source
rendering, reusable evaluation infrastructure, new labels, expansion, further
review, held-out access, accepted-gold promotion or production integration is
authorized. All private contents remain local and out of Git.

## Approved amendment: merchant v3 residual error analysis

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-v3-error-analysis-report.md)
records two OCR source-text mismatches and five unresolved digital cases,
including two spacing-only signatures. No exact witness was found; the saved
score stays 17/24. The allowance below is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed v3
comparison's concrete recommendation to diagnose seven residual merchant errors.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-v3-error-analysis-design.md). Reproduce 24 v3 scores,
then classify the seven failures using fixed saved evidence, regions, proposals
and assembly order. The smallest disposable diagnostic may search exact
whole-atom witnesses and count character availability under the predeclared
rules; it must not create predictions or alter scoring.

**Authorized measurement and stop boundary:** Count selection/assembly failures,
source-text mismatches, missing source evidence and unresolved attribution, with
digital/OCR slices. Private writes are limited to ignored
`artifacts/merchant-v3-errors-v1/`. Stop after the counts or a baseline failure.
No extractor tuning, new predictions, OCR, models, rendering, label changes,
review, expansion, held-out access, reusable evaluation infrastructure, gold
promotion or production integration is authorized. All private data stays local.

## Approved amendment: merchant geometry spacing candidate

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-spacing-report.md) records
17/24 exact before and after, zero gains/losses and two changed reviewed outputs.
Both spacing-only errors remain; the hypothesis is falsified. The allowance
below is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed v3
error report's recommendation to test a general geometry-based merchant spacing
rule in the row-profiles arm.

**Bounded extractor allowance:** Execute the
[design](2026-09-19-merchant-spacing-design.md). Use the fixed narrow-gap rule
to remove only inserted separators between recorded selected atoms. Generate
all owner outputs before reading references; preserve text content, selections,
order, ownership, output multiplicity and every uncertain boundary. The small
private renderer and immediate comparison may write only under ignored
`artifacts/merchant-spacing-v1/`.

**Authorized measurement and stop boundary:** Reproduce the 17/24 v3 baseline
and measure one candidate on all 24 fixed cases using unchanged alignment and
scoring. Report exact match, gains/losses, coverage, spacing signatures and
digital/OCR slices. Stop after comparison or baseline failure. No threshold
tuning, second candidate, new OCR/models/source extraction, label changes,
review, expansion, held-out access, reusable infrastructure, frozen-branch edits
or production integration is authorized. All private data stays local.

## Approved amendment: merchant whitespace location measurement

**Disposition:** COMPLETE — STOP. The
[report](../../experiments/row-extraction-merchant-spacing-location-report.md)
records six extra inserted separators between atoms across two cases, with zero
within-atom or unresolved discrepancies. Both cases are separator-only repairable
in principle; the score remains 17/24. The allowance below is exhausted.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed spacing
experiment's concrete recommendation to locate its two remaining whitespace errors.

**Immediate shared-evaluation allowance:** Execute the
[design](2026-09-19-merchant-spacing-location-design.md). Reproduce the 48 saved
baseline/candidate scores, then map whitespace gaps to source-atom occurrences
and recorded separators for exactly two spacing-only digital cases. Use a small
disposable diagnostic, with no corrected output or new extraction candidate.

**Authorized measurement and stop boundary:** Count within-atom, between-atom,
mixed and unresolved errors and separator-only repairability, including whitespace
origin and the fixed before/after gap comparison. Private writes are limited to
ignored `artifacts/merchant-spacing-location-v1/`. Stop after the count or baseline
failure. No tuning, second candidate, new source extraction/OCR/models, label
changes, review, expansion, held-out access, reusable infrastructure or production
integration is authorized. All private data stays local.

## Approved amendment: merchant spacing retention-reason measurement

**Disposition:** COMPLETE — STOP. Authority was committed at `f1f6b18` before
measurement. All six errors share a recorded reason with four required control
separators; the reason-separation hypothesis is falsified. See the
[result report](../../experiments/row-extraction-merchant-spacing-reasons-report.md).
No follow-on task is active.

**Approval date:** 2026-09-19. The user's “proceed” approves the location report's
recommendation to compare reasons for six retained erroneous separators with
boundaries in 17 exact controls.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-19-merchant-spacing-reasons-design.md). Map the six saved gap
errors and the exact controls to existing atom boundaries; quantify required,
redundant and unresolved control separators by the unchanged saved reason codes.
The fixed Unicode edge-category breakdown is diagnostic only. Write private
scripts/results only under ignored `artifacts/merchant-spacing-reasons-v1/`.

**Authorized measurement and stop boundary:** Report error/control reason overlap,
boundary and case counts, digital/OCR slices and the declared hypothesis. Stop
after this comparison or failure to reproduce saved results. No candidate, new
threshold, source extraction/OCR/model, label change, review, expansion, held-out
access, reusable infrastructure or production integration is authorized.

## Approved amendment: merchant punctuation attachment and geometry measurement

**Disposition:** COMPLETE — STOP. Authority was committed at `0aaec40` before
measurement. All six erroneous punctuation boundaries pass the fixed geometry
checks and none of the three required controls passes. The hypothesis is
supported on this sample; no changed predictions were generated. See the
[report](../../experiments/row-extraction-merchant-punctuation-geometry-report.md).
No follow-on phase is active.

**Approval date:** 2026-09-19. The user's “proceed” approves the retention-reason
report's recommendation to compare punctuation attachment and geometry at six
incorrect boundaries and three required punctuation-bearing controls.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-19-merchant-punctuation-geometry-design.md), using saved atoms,
unchanged order, existing 80% line-overlap and 20% character-width thresholds,
and direction inferred from nearest strong letters on either side. Publish
attachment/geometry category counts and the declared hypothesis result only.
Keep private scripts and results in `artifacts/merchant-punctuation-geometry-v1/`.

**Stop boundary:** Stop after the nine-boundary comparison or saved-result
reproduction failure. No changed predictions, threshold tuning, new source
extraction/OCR/models, label changes, wider selection, held-out access, reusable
infrastructure or production integration are authorized.

## Approved amendment: merchant punctuation-aware spacing candidate

**Disposition:** COMPLETE — STOP. Authority was committed at `3b2eca1` before
generation. Exact merchant matches increase from 17/24 to 19/24 with two gains,
zero losses and full coverage. The hypothesis is supported on the fixed seed.
See the [report](../../experiments/row-extraction-merchant-punctuation-spacing-report.md).
No follow-on phase is active.

**Approval date:** 2026-09-19. The user's “proceed” approves the completed
punctuation-geometry report's candidate recommendation.

**Bounded extraction-change allowance:** Execute the
[design](2026-09-19-merchant-punctuation-spacing-design.md). Extend the existing
spacing rule at punctuation boundaries using nearest strong-letter context and
the unchanged 80% overlap / 20% character-width thresholds. Preserve source text,
selection, order, ownership and multiplicity. Generate across all comparable
saved owner groups before opening labels; reproduce 48 prior scores and evaluate
all 24 v3 seed cases. Publish exact-match deltas, paired gains/losses, coverage,
spacing-error counts and the declared hypothesis result.

**Stop boundary:** Private scripts/results stay in
`artifacts/merchant-punctuation-spacing-v1/`. Stop after one comparison or saved
result reproduction failure. No tuning, second candidate, new source extraction,
OCR/model access, label changes, review, expansion, held-out access, reusable
infrastructure or production integration is authorized.

## Approved amendment: remaining digital merchant character-error measurement

**Disposition:** COMPLETE — STOP. Authority was committed at `c238a9c` before
measurement. Two order-only signatures and one missing-only inventory case
support the hypothesis. Four occurrences are missing and none extra; the
candidate remains 19/24 exact. See the
[report](../../experiments/row-extraction-merchant-character-errors-report.md).
No follow-on phase is active.

**Approval date:** 2026-09-20. The user's “proceed” approves the completed
punctuation-spacing report's character-order versus inventory recommendation.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-20-merchant-character-errors-design.md). Reproduce all 72 saved
scores and classify the three remaining digital mismatches using NFC,
non-whitespace code-point inventories and subsequence signatures. Publish
category/occurrence counts and the declared hypothesis result. Keep private
scripts/results only in `artifacts/merchant-character-errors-v1/`.

**Stop boundary:** Stop after this classification or saved-result reproduction
failure. No candidate, new extraction/OCR/models, source documents, label changes,
new review, broader selection, held-out access, reusable infrastructure or
production integration is authorized.

## Approved amendment: merchant whole-atom ordering witness measurement

**Disposition:** COMPLETE — STOP. All 30 identity orders across two cases yield
zero intact-atom witnesses; no case is unresolved. The hypothesis is falsified.
See the [report](../../experiments/row-extraction-merchant-atom-order-witness-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the character-error
report's recommendation to test intact-atom reorder witnesses.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-20-merchant-atom-order-witness-design.md). Reproduce saved scores
and classifications; test only the two order-only digital cases with all selected
atom occurrences used once. Keep NFC/non-whitespace projections and a fixed
nine-atom limit; report unresolved normalization or size limits. Publish witness
case counts, identity-order counts and the declared hypothesis result. Private
scripts/results stay in `artifacts/merchant-atom-order-witness-v1/`.

**Stop boundary:** Stop after this measurement or saved-result reproduction
failure. No larger search, second diagnostic, candidate, new source access,
extraction/OCR/models, label changes, review, broader selection, held-out access,
reusable infrastructure or production integration is authorized.


## Approved amendment: merchant within-atom directional signatures

**Disposition:** COMPLETE — STOP. Three reverse-only LTR atoms occur across both
cases; four others are palindromic and none is unresolved. The hypothesis is
supported. See the [report](../../experiments/row-extraction-merchant-atom-direction-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the whole-atom witness
report's recommendation to examine character ordering inside the selected atoms.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-20-merchant-atom-direction-design.md). Reproduce previous scores,
classifications and witness results. Measure forward/reversed reference substring
counts and Unicode direction profiles for the same seven atom occurrences in two
cases. Retain declared unresolved cases and publish aggregates. Private scripts
and results stay in `artifacts/merchant-atom-direction-v1/`.

**Stop boundary:** Stop after this measurement or reproduction failure. No
transformed merchant assembly, candidate scoring, new source access,
extraction/OCR/models, label changes, broader selection, held-out access,
reusable infrastructure or production integration is authorized.


## Approved amendment: merchant source-order trace

**Disposition:** COMPLETE — STOP. All three reversals are present at native word
extraction and persist unchanged downstream. Glyph geometry yields the reference
substrings for all three; the hypothesis is supported. See the
[report](../../experiments/row-extraction-merchant-source-order-trace-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the directional-signature
report's recommendation to locate the source of the reversed LTR atom ordering.

**Bounded extraction-error allowance:** Execute the
[design](2026-09-20-merchant-source-order-trace-design.md). Trace only the three
reverse-only atoms in the same two cases through frozen native word extraction,
layout and evidence projection. Read only their local source pages; use declared
geometry and glyph guards and retain unresolved cases. Publish stage-attribution
and glyph-order counts. Private scripts/results stay in
`artifacts/merchant-source-order-trace-v1/`.

**Stop boundary:** Stop after the trace or saved-result reproduction failure.
No extraction fix, new merchant predictions, models/OCR, label edits, broader
selection, held-out access, reusable infrastructure or production integration
is authorized.

## Approved amendment: merchant LTR glyph reconstruction candidate

**Disposition:** COMPLETE — STOP. Exact matches remain 19/24 with zero gains and
zero losses. Two reviewed outputs change without becoming exact; the hypothesis
is falsified. See the
[report](../../experiments/row-extraction-merchant-ltr-glyph-candidate-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the source-order trace
report's recommendation to test guarded LTR glyph reconstruction.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-ltr-glyph-candidate-design.md). Apply the fixed
source-geometry rule to all 373 selected atom occurrences in 113 saved owner
outputs. Preserve ownership, order and spacing. Read only the four existing
seed digital source pages; save predictions before loading reference labels.
Reproduce prior scores and compare all 24 reviewed cases against the 19/24
punctuation baseline, including gains, losses and coverage. Private scripts and
results stay in `artifacts/merchant-ltr-glyph-v1/`.

**Stop boundary:** Stop after one generation/score or reproduction failure. No
post-score tuning, second candidate, OCR/models, label changes, broader selection,
held-out access, reusable infrastructure or production integration is authorized.

## Approved amendment: merchant corrected-block ordering witnesses

**Disposition:** COMPLETE — STOP. Both cases have exactly one matching
corrected-block order across 30 identity permutations, with no unresolved
cases. The hypothesis is supported; exact accuracy stays 19/24. See the
[report](../../experiments/row-extraction-merchant-corrected-order-witness-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the completed LTR
glyph candidate report's recommendation to test corrected-block ordering.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-corrected-order-witness-design.md). Reproduce 96
saved scores and reconstruct the saved candidate's 113 outputs from its 373
atom decisions. Query only the two changed reviewed digital training cases with
the existing intact-block permutation test, nine-occurrence cap and normalization
guards. Preserve corrected block contents and all occurrence identities. Publish
witness counts and unresolved limits. Private glue and results stay in
`artifacts/merchant-corrected-order-witness-v1/`.

**Stop boundary:** Stop after this measurement or saved-result reproduction
failure. No new source access, candidate, label edits, larger search, broader
selection, held-out access, reusable infrastructure or production integration
is authorized.

## Approved amendment: merchant LTR block-ordering candidate

**Disposition:** COMPLETE — STOP. No groups reorder; exact matches remain 19/24
with zero gains/losses against both baselines and 24/24 coverage. The hypothesis
is falsified. See the
[report](../../experiments/row-extraction-merchant-ltr-block-order-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the completed
corrected-block witness report's recommendation to test geometric LTR ordering.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-ltr-block-order-design.md). Apply one predeclared
source-only ordering rule to all 113 saved groups, preserving glyph correction
and using the existing spacing rule for new adjacencies. Save all predictions
before loading labels; reproduce 96 saved scores and score the 24 training
references against both 19/24 baselines, including gains, losses and coverage.
Keep private work in `artifacts/merchant-ltr-block-order-v1/`.

**Stop boundary:** Stop after one generation/score or reproduction failure.
No post-score tuning, second candidate, new source access, labels, OCR/models,
broader selection, held-out access, reusable infrastructure or production
integration is authorized.

## Approved amendment: merchant block-overlap measurement

**Disposition:** COMPLETE — STOP. All seven groups have consistent edge/center
order and distinct source evidence. Twenty-two crossing overlaps are at most
about 0.00723% of average character width; no group is unresolved. The hypothesis
is supported. See the
[report](../../experiments/row-extraction-merchant-block-overlap-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the block-order
candidate report's recommendation to quantify the seven rejected groups.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-block-overlap-design.md). Reproduce 120 scores and
saved candidate decisions. Measure normalized overlap, interval categories,
strict edge/center ordering and native-word/glyph attribution in exactly seven
saved groups. Use saved native pages only; keep private work in
`artifacts/merchant-block-overlap-v1/`.

**Stop boundary:** Stop after measurement or reproduction failure. No guard
changes, new predictions, source extraction, labels, broader selection, held-out
access, reusable infrastructure or production integration is authorized.

## Approved amendment: merchant LTR tolerance candidate

**Disposition:** COMPLETE — STOP. Exact matches remain 19/24, with zero gains or
losses and 24/24 coverage. All seven formerly blocked groups are already ordered;
no tolerance joins occur. The hypothesis is falsified. See the
[report](../../experiments/row-extraction-merchant-ltr-tolerance-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the overlap report's
recommendation to test consistent geometry tolerance in ordering and spacing.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-ltr-tolerance-design.md). Apply one predeclared rule
with the existing coordinate tolerance and distinct source-evidence guards to
all 113 saved groups. Preserve glyph correction and ownership; save predictions
before labels, reproduce 120 prior scores and score 24 training references against
three saved baselines. Private work stays in `artifacts/merchant-ltr-tolerance-v1/`.

**Stop boundary:** Stop after one generation/score or reproduction failure.
No post-score tuning, second candidate, new source extraction, label changes,
held-out access, reusable infrastructure or production integration is authorized.

## Approved amendment: merchant corrected-output spacing diagnostic

**Disposition:** COMPLETE — STOP. Both cases are whitespace-only errors with
unique identity-order witnesses; none is unresolved. The hypothesis is supported
and exact accuracy remains 19/24. See the
[report](../../experiments/row-extraction-merchant-corrected-spacing-report.md).

**Approval date:** 2026-09-20. The user's “proceed” approves the completed
tolerance report's recommendation to classify the two corrected digital errors.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-corrected-spacing-design.md). Reproduce 144 saved
scores and reconstruct saved outputs. Measure whitespace-only differences and
identity-order witnesses in exactly two changed reviewed digital training cases,
using existing pure classifiers, saved strings and recorded indices. Keep private
work in `artifacts/merchant-corrected-spacing-v1/`.

**Stop boundary:** Stop after this diagnostic or reproduction failure. No new
predictions, source/native-page access, label changes, broader selection, larger
search, held-out access, reusable infrastructure or production integration is
authorized.

## Approved amendment: merchant unchanged-order spacing candidate

**Disposition:** APPROVED — pending one generation and evaluation.

**Approval date:** 2026-09-20. The user's “proceed” approves only the recommended
spacing candidate after the completed corrected-output diagnostic.

**Bounded extraction allowance:** Execute the
[design](2026-09-20-merchant-unchanged-order-spacing-design.md). Apply the existing
tolerance-aware renderer to all eligible saved owner groups even when order is
unchanged, retaining source-evidence and normalization guards, glyph correction
and ownership. Save the complete source-only candidate before labels; reproduce
144 saved scores and compare the same 24 v3 training references against four
saved baselines. Private code/results stay in
`artifacts/merchant-unchanged-order-spacing-v1/`.

**Stop boundary:** Stop after one generation/score or reproduction failure.
No post-score tuning, second candidate, new source extraction, label changes,
sample expansion, validation/held-out access, shared framework or production
integration is authorized.
