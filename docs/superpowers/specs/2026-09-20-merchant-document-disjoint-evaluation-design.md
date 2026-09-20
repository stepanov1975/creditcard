# Document-Disjoint Merchant Evaluation Design

**Status:** ACTIVE — execution approved on 2026-09-20.

The user explicitly authorized full-task execution and removal of per-subtask
approval gates. This supersedes the previous design-only disposition. Follow the
updated AGENTS task-level policy; complete preparation, generation, review,
adjudication, scoring and reporting as one objective. Two independent human
reviewers were available under the original protocol. The user subsequently
authorized AI-prefilled source readings followed by their own corrections; the
amendment below governs reference preparation. Human confirmation remains required.

```text
Scope answer: YES — evaluates the frozen merchant candidate on document-disjoint training pages
Experiment: shared evaluation
Extraction hypothesis: The frozen spacing candidate improves exact merchant extraction without losses, ownership regressions, or reduced coverage
Measurement: reference eligibility, exact-match delta, coverage, discovery omissions, and ownership errors
Fixed inputs: frozen candidate and comparators; six documents selected under these committed rules; existing training membership only
Smallest allowed files: docs/knowledge/README.md; AGENTS.md; docs/superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/superpowers/specs/2026-09-20-merchant-document-disjoint-evaluation-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-document-disjoint-evaluation-report.md; artifacts/merchant-document-disjoint-v1/**
Required output: completed fixed comparison, or a prepared human-review packet with quantified eligibility and a clear outstanding dependency
Stop condition: finish the evaluation; pause only for human reference review, unavailable inputs, or a substantive change to the frozen experiment
```

## Question and limits

Does the completed spacing rule improve exact, correctly owned merchant output
on documents outside the six-document calibration seed? The
[completed comparison](../../experiments/row-extraction-merchant-unchanged-order-spacing-report.md)
measured 19/24 to 21/24 with zero losses. It used repeatedly inspected training
references and reference-region-assisted alignment. It does not establish a
production accuracy gain or a general page-to-transaction extractor.

This proposed six-document pilot measures transfer of the fixed merchant rules.
It uses existing **training** membership, so it is document-disjoint from the
merchant seed, not a new untouched test set for the whole project. The older row
arms may have used these training documents. Existing validation and held-out
partitions remain closed. Report this distinction with every result.

## Freeze three views before any new reference is seen

| View | Fixed implementation | Purpose |
| --- | --- | --- |
| Primary comparator | `artifacts/merchant-ltr-tolerance-v1/tolerance.py:order_with_tolerance`, existing glyph correction and original saved separator rules | Isolate the effect of removing the unchanged-order rendering bypass; scored 19/24 on the old seed. |
| Candidate | `artifacts/merchant-unchanged-order-spacing-v1/rerender.py:render_eligible_groups`, completed under authority `9246999` and reported at `2cefcb2` | Apply the completed rule unchanged; scored 21/24 on the old seed. |
| Secondary comparator | `artifacts/merchant-punctuation-spacing-v1/punctuation.py:render_punctuation_spacing` on original atoms/order | Compare the combined glyph/spacing changes with the earlier 19/24 view; not an additional candidate. |

Use the frozen deterministic arm at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4`, the existing before-rejection description
proposal rule, source-only pre-filter evidence, explicit continuation ownership,
reading-order and assembly rules as a **common input path**. Preserve the existing
LTR glyph reconstruction, native matching and source conventions. The three views
must receive identical original evidence, proposals and owner membership. Only
the declared rendering transformations differ. Billing decisions never change.

The saved generation scripts are seed-specific: they assert six pages, 135 rows,
113 owners and 373 occurrences and consume intermediate saved files. They are
not a runnable new-document evaluator. The current execution approval permits
only the immediate, disposable input adapter needed to invoke these existing
rules on the chosen pages. It must replace input locations/count assertions,
not infer a new discovery, ownership, ordering or OCR rule. It must reproduce
the old three views on the old seed and pass synthetic seam tests **before** new
page access. Keep private source versions with the existing experiment files;
no controller, CLI, receipt system, provenance redesign or dependency installation.

If the common evidence/proposal path cannot run without changing extraction
semantics, report an execution-readiness failure and STOP. Do not substitute the
current production parser or a newly tuned detector. Adapter feasibility and new
sample availability have not been measured by this design.

## Fixed document and page selection

Selection uses the existing training-document inventory, metadata and
source identity checks; never labels, predictions, merchant text or score-based
filters. Exclude the entire six seed documents, byte-identical copies, and every
document already used in source-visible merchant reference/glyph/spacing review.
Determine those exclusions from existing selection records, not their contents.
If the exposure inventory cannot establish exclusion, stop rather than claiming
unseen data. Unrecognized near-duplicates remain a stated limitation; do not
create a deduplication subsystem for this pilot.

Select **six distinct remaining training documents**: two with OCR-backed pages
in existing metadata, then four further documents with only digital-backed pages
in that metadata. This is document-level stratification, not a guarantee that the
chosen page will need OCR. Exclude unknown-mode documents and report their count.

Rank eligible documents by SHA-256 of UTF-8
`merchant-document-disjoint-v1`, NUL, document identity. Break digest ties by
identity. Take each stratum's first eligible documents without replacement. Source
unavailability, identity mismatch or insufficient membership stops selection;
do not replace a difficult document or borrow validation/test documents.

For each selected document, inspect page-count metadata only, then rank **all**
physical pages by SHA-256 of UTF-8 `merchant-document-disjoint-page-v1`, NUL,
document identity, NUL, decimal one-based page number. Break ties by page number
and select the first. Freeze the six selected identities/pages privately before
rendering or inspecting their contents. Including all physical pages avoids
conditioning the page population on a successful row detector. A selected page
with no transactions remains in the sample; do not swap it for a table page.

All transactions starting on each selected page belong to the reference census,
including ones absent from discovered rows and future-billing tables. Classify
billed versus future-billing sections separately using source-only review; this
merchant study must not imply that all reviewed transactions should be billed.
Count a continuation with its owner, never as another transaction. Source pages
elsewhere in that selected document may resolve ownership or continuations, but
do not add new transaction starts to the census. If cross-page support cannot be
represented by the frozen input path, record an omission; do not invent a new
assembly rule. No first-four or detected-row-only sampling is used.

Six sampled pages bound the transaction census, not the number of human
transactions; supporting context is limited to the same six documents.
If the review burden is unacceptable, stop with the unreviewed census count;
do not truncate or replace the sample after seeing outputs. The resulting pilot
may be uninformative because of empty pages or insufficient digital/OCR cases.

## AI-assisted reference review — user-authorized amendment

The user requested that the assistant read the source documents, prefill reference
answers and return editable result files for the user to correct. This explicitly
replaces the original two-independent-human, blank-first workflow. Record the tier
as **AI-assisted, single-human-reviewed pilot**, never independent certification.
Preserve the earlier blank packets as history; do not alter frozen selection,
extractors, predictions, matching or metrics.

Read source page images to enumerate every transaction start and transcribe its
merchant under [CONTEXT](../../../CONTEXT.md). Do not use the saved prediction
strings or boxes to generate references. Native PDF text may assist transcription
only after visual inspection, with every proposed reading checked against the
source image. Record transaction/merchant regions, billed/future section and
present / absent / ambiguous status. Preserve punctuation and case. Mark uncertain
readings and boundaries explicitly; do not guess missing characters.

Provide a prefilled local worksheet, editable JSON and readable tabular draft.
Label every case as an AI suggestion awaiting human confirmation and leave every
page census unconfirmed. The user can correct/add/remove cases and must confirm
all six page censuses, including omissions and empty pages. Preserve the initial
AI draft separately from human corrections. AI agreement is not human agreement.

Freeze the human-corrected reference and denominator before revealing prediction
differences or scoring. Do not revise references to agree with extraction output.
Unreviewed cases, incomplete census or unresolved ownership make the evaluation
inconclusive. Merchant absence is distinct from illegibility/ambiguity. No global
gold promotion occurs. Report the AI-assisted tier and anchoring risk with results.

## Generation, alignment and ownership audit

Generate and save all three complete prediction views from source evidence only,
with no reference strings, human merchant regions or reviewed owner assignments
as generation inputs. References may be prepared independently but stay closed
to generation. Preserve nulls, multiple outputs, failed discovery and unassigned
proposals. Do not drop a reference because the pipeline lacks a row or output.
Operational failures stop the run; ordinary extractor abstentions remain results.

After generation and reference freezing, use the original geometry-only
transaction matcher: positive horizontal intersection, vertical intersection at
least half the row height, unique greatest IoU across owner rectangles, with ties
and duplicate-row assignments unresolved. Transform coordinates using the saved
source convention and page rotation. No text-based matching, second-choice
collision rescue, or candidate-dependent rematching is permitted. Save one common
assignment for all views.

Do **not** use the seed's merchant-region eligibility filter for the primary
assignment: that filter previously changed which predicted owner was selected.
The resulting new-page scores are not directly comparable to 21/24; the paired
comparison between frozen views is the relevant measurement.

A source-only ownership check then compares the already assigned output's selected
evidence with the human owner/merchant support. It may flag a wrong owner, borrowed
text or unsupported output but may not change the assignment or select another
prediction. Have reviewers inspect evidence with method names hidden and reference
text locked. Report unresolved ownership separately; identical strings attached
to the wrong transaction cannot count as correct merchant extraction. Count extra
unassigned proposals separately. This audit is evaluation, not a deployable
ownership rule or an end-to-end production acceptance test.

## Metrics and decision fixed in advance

Report raw counts per document, all pages, observed digital/OCR/mixed evidence
mode, and billed/future-billing section. Empty pages remain in page counts. Use
`Decimal` for rates; never treat clustered transactions as independent documents.

Let N be all reference transaction starts, P the unambiguous present-merchant
references, A the confirmed absences and U the unresolved merchant references;
require N = P + A + U. Report all four counts. No zero denominator produces a
numeric rate; use NOT MEASURED.

For each view report:

- E: exact NFC-plus-collapsed-whitespace matches with unique output and verified
  correct ownership among P; exact rate E/P. Missing discovery, unmatched owners,
  abstention and wrong ownership remain failures in P, not exclusions.
- E/N as **verified exact-output yield**, not merchant accuracy; A and U cannot
  silently disappear. Report correct abstentions and false emissions on A, and
  abstentions/emissions on U without guessing their true merchant text.
- Aligned coverage and unique-output coverage on P and N, discovery omissions,
  geometry ties/collisions, output omissions, multiple outputs, wrong-owner,
  unsupported-evidence and unresolved-ownership counts, plus unassigned proposals.
- Paired exact gains/losses and net delta against both comparators; document-level
  gains/losses; text-only equality separately from ownership-verified equality.

The pilot supports the hypothesis only if the primary paired exact delta is
positive, no previously exact case is lost against either comparator, coverage is
not reduced, no additional wrong-owner/unsupported output or false emission on A
occurs, every page census is complete, and U and unresolved ownership are zero.
There must be at least one present-merchant case with digital evidence and one
with OCR evidence; otherwise the planned two-mode conclusion is inconclusive.
Observed regressions falsify the no-regression hypothesis. A complete, eligible
comparison with no positive delta falsifies the gain hypothesis on this pilot.
Insufficient references, unresolved audit, unavailable inputs or failed execution
are INCONCLUSIVE / NOT MEASURED, not zero accuracy or evidence of equivalence.

A supported result is a pilot signal, not a population estimate or statistical
proof. Publish per-document counts and denominators rather than a row-level
confidence interval. Do not tune any rule or choose a new candidate on this sample.
After outcomes are inspected it is no longer untouched evaluation data; any later
rule change needs another separately approved evaluation.

## Execution boundary and deliverable

The current task authorizes the concrete sample/review run and its smallest
immediate adapter. Keep private outputs in `artifacts/merchant-document-disjoint-v1/`.
Commit this initial authority before new page access. Human review is a real
handoff; prefill AI suggestions under the amendment above, but never mark them
human-confirmed automatically. Routine subtasks need no new approval.

Required output is one aggregate report with selection/exposure limits,
reference-review tier, census/ambiguity counts, three fixed-view results, paired
counts, ownership audit, and supported/falsified/inconclusive disposition. Require
synthetic tests for normalization, geometry collisions, absent/uncertain references,
missed-row denominators and ownership failures; independently check aggregation
and all four repository gates. Preserve source/reference files and frozen code.
No production merge or corpus acceptance follows from this pilot.

Keep the objective ACTIVE through routine milestones and AWAITING_HUMAN_REVIEW
when answers are needed. Resume the same task when they arrive. No automatic
follow-on experiment, tuning, validation/test access or integration is authorized.

## Historical design-only verification

Only the three declared Markdown files changed. All 95 local documentation links
checked across them resolve. Ruff format/lint and mypy pass; all 3,766 repository
tests pass (99.87 seconds). No private evaluation ran and no accuracy delta was
measured in this design task.
