# Merchant Seed Comparison Design

**Status:** Approved by the user's “approved” on 2026-09-12, in response to the
concrete recommendation to compare existing extraction methods against the 24
reviewed references before expanding the dataset. Commit this design and the
charter amendment before running or scoring methods. No further approval is
needed for this bounded comparison.

## Question and scope

```text
Scope answer: YES — measures existing merchant extraction against the reviewed seed
Experiment: shared evaluation
Extraction hypothesis: At least one existing local extraction method produces more exact merchant matches than the accepted parser baseline on the 24 seed cases
Measurement: normalized merchant exact-match rate, coverage, omissions, row-alignment failures, and paired exact-match delta
Fixed inputs: the 24 reviewed training references, their six frozen source pages, and existing unmodified extraction methods
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-seed-comparison-design.md; docs/superpowers/plans/2026-09-12-merchant-seed-comparison.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-seed-comparison-report.md; artifacts/merchant-seed-comparison-v1/**
Required output: merchant scores and paired differences, or quantified method/input eligibility failures
Stop condition: stop after the fixed comparison; do not tune methods, change labels, expand the sample, or access validation/test data
```

This is a diagnostic training measurement on a single-reviewer calibration seed,
not model selection, independent gold certification, or corpus acceptance.
Existing gold, the failed annotation pilots, and the held-out test stay closed.

## Fixed methods

Use these definitions, selected before comparing any output with human text:

| Method | Fixed implementation/configuration | Treatment |
| --- | --- | --- |
| Accepted parser baseline | Stored accepted-anchor evidence projections corresponding to the original frozen rows, anchor `dee4b071ad65231da13825f2f7c74a488ca96c7c` | Replay selected training-page records only. This measures the existing projection, not a new run of the current production release. |
| Deterministic profiles | `a2ed73aa58a4e4d8c76f918657d083fa922537d4`; frozen handoff configuration `tight`, continuation gap `0.50` | Invoke the unmodified arm directly. |
| Row OCR | `9bc582c6876d4e2adba7e19cf2ba1968c5ab2625`; existing 300-DPI, zero-padding, whole-row, PSM 6, `heb+eng`, internal-Otsu, fixed-column baseline configuration | Invoke the unmodified arm directly with the existing pinned local language packs. Its historical validation stop remains in force; this is a diagnostic rerun. |
| Text | `d573b7f8d5239ca3ff92cbc7bf5475f5ced2ab0a`; no validation-eligible frozen candidate | Report unavailable for this frozen comparison, not zero merchant accuracy. Do not train or pick among rejected candidates. |
| Vision | `40f748395c07bb4d2da6658b92087be471681264`; no validation-eligible frozen candidate | Report unavailable for this frozen comparison, not zero merchant accuracy. Do not train or pick among rejected candidates. |

The OCR baseline is a pre-existing configuration, not a new winner selected on
this seed. No sweep, new model, API call, package installation, production change,
or historical controller invocation is authorized. Historical source checkouts
are read-only. Private one-off measurement scripts may invoke their arm APIs.

## Inputs and transaction alignment

Read the six selected training-page observations from the original frozen row
bundle. Filter by the seed's document identities before decoding records, then
by page and training membership. Replay only baseline predictions belonging to
those rows. Do not decode unrelated predictions, old gold, or reviewer streams.
Check selected local source copies against their already frozen document IDs.
Neither reference text nor merchant evidence rectangles may enter an extractor.

Transform each frozen row box into normalized full-page display coordinates,
including the PDF page's rotation. Match each human transaction region to frozen
rows on its page using geometry only. A candidate requires positive horizontal
intersection and vertical intersection covering at least half of the frozen row
height. Select the unique highest intersection-over-union candidate; equal best
scores are ambiguous. With multiple human owner rectangles, use the maximum IoU
over those rectangles. If two seed cases choose the same row, both are alignment
failures. No rematching, box changes, text-assisted matching, or threshold changes
are permitted after outcomes are observed. A source/coordinate failure is a
reported input failure; it cannot be rescued by changing detection.

Run each available arm on every frozen row of the six selected pages, so existing
continuation ownership can be represented without supplying human row boundaries
to the arm. The arm receives its original `FrozenRow`, without annotations. Keep
the original row identities, row boxes, columns, atoms, and source references.

## Merchant scoring

These implementations expose a description role, not a separate minimal merchant
role. Measure their existing description output against the human merchant target
without trimming, alias mapping, transliteration, reversal, case folding, or
spelling correction. Exact matching applies NFC followed by collapsing Unicode
whitespace to single spaces on both sides; preserve punctuation and letter case.

Use only proposals from an `accept` prediction. Resolve description proposals
from their declared atoms in declared order with the existing evidence renderer.
Associate them with `owner_row_id`, or their own row identity when that is absent.
There must be exactly one description proposal for a matched owner. Zero is an
omission; more than one is an ambiguous output, without concatenation or choosing
the proposal closest to gold. Count nonaccepted owner predictions separately.

Report for each runnable method:

- fixed-denominator exact matches out of 24 and exact rate among geometrically
  aligned references, with alignment coverage shown separately;
- emitted unique-description coverage, omissions, ambiguous outputs, and
  nonaccepted owner prediction counts;
- disjoint lexical mismatch categories: reference is a proper substring of output
  (extra text), output is a proper substring of reference (partial text), or other
  mismatch. These are string diagnostics, not human-adjudicated error causes;
- separate OCR-page (8 cases) and digital-only-page (16 cases) counts; and
- paired gains, losses, and net exact-match delta against the accepted baseline.

The hypothesis is supported if either available challenger has a strictly
positive paired net exact-match count. It is falsified for the evaluated methods
if both deltas are nonpositive. Missing methods remain unmeasured. A result with
no aligned references cannot support or falsify merchant accuracy. Alignment
failures stay in the 24-case success denominator but are not asserted to be wrong
merchant text. No population estimate, significance claim, or confidence interval
is justified by this small, clustered, deliberately stratified training sample.

## Verification and completion

The previous scorer consumes old `GoldRow` labels and row-level descriptions;
it cannot score these independent source-region transaction references directly.
The smallest immediate exception is a disposable local measurement script, its
OCR invocation helper, and focused invented-input tests under ignored
`artifacts/merchant-seed-comparison-v1/`. No reusable controller, CLI family,
schema family, workflow system, or gold conversion is authorized.

Check geometry collision/tie failures, normalization, proposal ownership,
abstention handling, and paired score arithmetic on invented inputs before the
private run. Preserve private inputs and outputs locally; print only aggregates.
Use `Decimal` for reported rate arithmetic and any financial arithmetic. Test
failures may be corrected in this smallest measurement code before scoring;
method failures are recorded without changing the method or adding support work.

Run the repository's four verification commands before tracked commits. Publish
the aggregate report and return the live phase to `STOP`. The result may recommend
one next extraction task, but does not authorize tuning, further labeling, gold
promotion, validation access, or production integration automatically.
