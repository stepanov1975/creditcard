# Transaction-Row Extraction Experiment Charter

**Status:** Approved design authority for the transaction-row extraction experiment
program.

**Authority date:** 2026-07-28

**Last amended:** 2026-09-12

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
