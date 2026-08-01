# Visual-Gold v2 Candidate Design

**Status:** Approved conversational design; implementation remains blocked until the user
reviews this written specification and the charter amendment below is committed.

**Date:** 2026-08-01

## Purpose

Create a more semantically reliable gold-label candidate for the 2,503 frozen training rows by
using blind, independent visual inspection of the exact row crops with bounded source-page
fallback. The candidate exists to measure defects in the current supervision and, after a
separate future promotion decision, support a fairer comparison of the four row-extraction
experiments.

The current reviewed gold remains authoritative during this work. Visual-gold v2 is a parallel
candidate and does not overwrite, mutate, or silently replace it.

## Scope

This design authorizes:

- one deterministic 100-row training pilot;
- two independent blind visual reviews of every pilot row;
- visual adjudication of pilot disagreements;
- aggregate pilot agreement and annotation-defect measurements;
- full blind dual review and disagreement adjudication for the remaining 2,403 training rows
  only if the pilot gates pass; and
- a frozen, private, ignored visual-gold v2 candidate covering all 2,503 training rows.

This design does not authorize:

- validation or held-out labeling;
- promotion of the candidate to authoritative gold;
- experiment selection from training-set results;
- changes to frozen row detection, row identity, crop geometry, document splits, or source
  artifacts;
- production integration;
- a generalized review controller, workflow service, receipt system, or provenance subsystem;
  or
- use of existing gold, accepted parser output, or experiment predictions as reviewer hints.

## Terms and authority

**Frozen row** means the existing immutable row identity, crop, positioned atoms, row geometry,
column bands, adjacency, and split membership.

**Visual-gold v2 candidate** means the final adjudicated training labels produced under this
protocol. Candidate status gives the artifact no authority over existing experiment results.

**Reviewer A** and **Reviewer B** are separate clean visual-review contexts. They receive the same
source evidence but cannot see each other's output, existing gold, accepted parser values, or
experiment predictions.

**Reviewer C** is a fresh visual adjudication context that sees the source evidence and the exact
semantic differences between A and B. It adjudicates only disagreements and may retain
`ambiguous` when the evidence lacks one defensible answer.

The learned visual reviewers are used to generate a candidate, not authoritative values. A later
promotion requires a separate user-approved charter amendment.

## Inputs and privacy

The fixed input population is exactly the 2,503 rows in the existing training split. Review uses:

- the exact row crop;
- frozen atom text, atom identity, source, confidence, and bounding box;
- row geometry, role-free column boundaries, and reciprocal adjacency;
- an opaque row identity; and
- a bounded source-page rendering only when the crop alone cannot determine column meaning,
  currency, year, ownership, or contamination.

Source filenames, existing gold, accepted parser fields, and predictions from all four experiments
are omitted from reviewer material. Baseline row type may be used only by the deterministic pilot
selector as a hidden coverage stratum; it is never shown to a reviewer.
Semantic roles stored on frozen column bands are also omitted; reviewers may see boundaries but
not parser-assigned field meanings.

All crops, contexts, labels, review outputs, disagreements, and derived financial content remain
under the ignored private artifact tree. Tracked reports contain aggregate counts and rates only.

## Label contract

Each review produces the existing `GoldRow` structure rather than a new schema family:

- one row type: `primary_transaction`, `continuation`, `structural`, or `ambiguous`;
- the ambiguity flag required by that row type;
- every uniquely visible field in the existing closed field-role vocabulary;
- a typed canonical value for every field; and
- exact same-row support through frozen atom IDs, a bounded image region, or both.

The existing annotation handbook applies with these candidate-specific clarifications:

1. Description and ancillary text use natural human reading order. Hebrew and other RTL text is
   not serialized by increasing X coordinate. Mixed-direction numeric and Latin spans retain their
   visible internal order.
2. Frozen atom segmentation is evidence, not canonical text. A visually continuous number or word
   is not given artificial spaces merely because the frozen stream split it.
3. Crop-first review is mandatory. Bounded page context is opened only when necessary and its use
   is recorded as a non-sensitive boolean.
4. A reviewer does not invent a value from filenames, totals, reconciliation, current gold, parser
   output, or another row. If crop plus allowed context still has multiple defensible readings, the
   row is `ambiguous` and fieldless.
5. Missing or unreadable source artifacts are review failures, not ambiguous labels. The affected
   batch stops until the fixed artifact is available.

## Pilot selection

The 100-row pilot is selected once with a fixed version string and stable hash ordering. It is
locked before either reviewer sees a crop.

The selector requires:

- 50 hidden-baseline primary rows, 48 hidden-baseline continuation rows, the sole hidden-baseline
  structural row, and the sole hidden-baseline ambiguous row;
- 10 rows whose frozen atoms come from OCR and 90 whose atoms come from digital text;
- at least 15 rows with 1–3 atoms, at least 25 with 4–9 atoms, and the balance with 10 or more
  atoms; and
- broad document coverage, with no more than two selected rows from one document unless a stated
  quota is otherwise impossible.

Selection fails closed if the fixed population cannot satisfy these constraints. The selector may
use hidden baseline type only for coverage and must not serialize it into reviewer material.

## Blind review and adjudication flow

For each selected row, Reviewer A and Reviewer B independently:

1. inspect the exact crop at original resolution;
2. decide whether bounded page context is necessary and inspect it when required;
3. choose the row type from visible source evidence;
4. record every uniquely supported field and canonical value;
5. map each field to exact atom IDs or a bounded source region; and
6. validate the label before moving to the next row.

The two outputs are frozen before comparison. A deterministic comparator identifies disagreements
in:

- row type or ambiguity;
- field-role presence;
- canonical value;
- atom-ID support; and
- source-region support.

Reviewer C sees only disagreements plus source evidence. It cannot default to A, B, or current gold.
When C cannot establish one unique answer, it records `ambiguous` rather than guessing.

Reviewer-A, reviewer-B, comparison, and adjudicated outputs remain separate private JSONL
artifacts. The implementation uses narrow batch files and existing contracts; it does not build a
reusable orchestration subsystem.

## Pilot measurements and gates

All agreement is measured before adjudication.

### Row-type agreement

The numerator is the number of pilot rows where A and B choose the same row type. The denominator
is all 100 pilot rows. Full review requires at least 95% agreement.

### Field exact agreement

For each row, the eligible field-role set is the union of roles asserted by A or B. A role agrees
only when both reviewers assert it and its canonical values are exactly equal. Missing-versus-
present is a disagreement. Rows where neither reviewer asserts any field do not add absent/absent
slots to the denominator. Full review requires at least 90% agreement across eligible field-role
slots.

### Evidence-support agreement

Exact atom-ID sequence and exact serialized source-region agreement are reported separately.
Evidence-support agreement is diagnostic and is not allowed to override the semantic gates.

### Validity gate

Every A, B, and adjudicated record must pass existing annotation validation. Coverage is exact:
one record per selected row and no unknown, missing, or duplicate identity. Atom support must be
same-row, source regions must lie inside the fixed crop, and continuation ownership must follow
the reciprocal frozen predecessor relation. Validity must be 100%.

If row-type agreement, field exact agreement, or validity misses its gate, the program stops before
reviewing the remaining 2,403 rows. The resulting agreement and disagreement counts satisfy the
experiment's Metric-or-Stop rule. Protocol revision would require a new user-approved task and a
fresh predeclared pilot; the failed pilot is never relabeled to manufacture a pass.

## Full training review

If the pilot passes, its adjudicated records become the first 100 candidate records. The same
frozen protocol is applied to the remaining 2,403 rows in fixed private batches. The protocol,
model family, prompts, canonical rules, and comparison logic do not change after pilot access.

Each batch fails closed on missing artifacts, invalid identities, invalid geometry, invalid labels,
or incomplete reviewer coverage. Visual uncertainty is handled through the label contract, not as
a batch failure. Aggregate progress may report only row counts, agreement rates, ambiguity rates,
and predeclared error-category counts.

After full adjudication, the candidate is frozen. Existing gold is then compared with it for the
first time. The comparison reports aggregate disagreements in row type, field presence, canonical
value, RTL/mixed-direction order, segmentation, and evidence support. Current gold never decides a
visual-gold v2 value.

## Candidate scoring

The candidate introduces one named metric needed for fair interpretation:

**Eligible exact-row rate** is the number of nonambiguous gold rows satisfying the existing exact-
row conditions divided by the number of nonambiguous gold rows. Ambiguous rows remain in the
dataset and their rate is reported separately; they are not automatic exact-row failures.

The candidate report also includes:

- row-type accuracy and macro F1;
- per-field exact and normalized agreement;
- omission and hallucination rates;
- ambiguity rate;
- crop truncation or contamination counts; and
- OCR CER/WER only for independently transcribed visual source regions.

Frozen atoms are input evidence and are never treated as the expected extracted output.

Training-set scores are development diagnostics only. They cannot select a winning experiment or
justify held-out access. A fair experiment selection requires a later separately approved
visual-gold v2 validation phase.

## Minimal implementation boundary

The implementation may add only:

- the candidate-specific visual annotation protocol;
- the deterministic pilot selector;
- narrow private review-batch materialization;
- deterministic A/B comparison and aggregate pilot reporting;
- focused validation tests; and
- the smallest shared metric change required to report eligible exact-row rate.

It must reuse existing `FrozenRow`, `GoldRow`, annotation validation, and metric contracts. It must
not add a reusable CLI family, controller, receipt chain, attestation system, replay mechanism,
cache architecture, or locked-test workflow.

## Verification

Focused synthetic tests must prove:

- deterministic pilot membership and quota enforcement;
- reviewer material omits baseline type, current gold, parser values, and predictions;
- comparison treats missing-versus-present fields as disagreement;
- canonical-value and evidence-support disagreement are reported separately;
- ambiguous gold is excluded only from the eligible exact-row denominator;
- all identity, geometry, ownership, and evidence-support checks fail closed; and
- private values do not enter tracked aggregate reports.

Before committing implementation, run the repository-required Ruff formatting, Ruff lint, mypy,
and full pytest gates. Private labels and reports remain ignored and are not staged.

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
