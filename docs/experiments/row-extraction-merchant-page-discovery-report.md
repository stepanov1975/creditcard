# New One-Page Merchant Discovery Diagnostic

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved this new diagnostic under the
[design](../superpowers/specs/2026-09-12-merchant-page-discovery-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-page-discovery.md), and charter
amendment committed at `4d8d1a1` before private source extraction.

## Finding

All four unmatched reference regions have native PDF evidence and eligible
logical rows, but **zero of four have a discovered table row**. The new run's
38 discovered row boxes exactly match the 38 frozen row boxes as multisets.
This localizes the geometric coverage gap to the transition from logical rows
to discovered table rows in this new diagnostic.

The hypothesis that a fresh native-text discovery run would recover at least one
eligible row is **falsified on these fixed four cases**: coverage remains 0/4,
with a delta of zero covered references. It does not establish whether discovery
incorrectly excludes transactions or correctly filters material outside its
intended transaction scope.

## Fixed run and results

The unchanged deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4` supplied the native PDF evidence helpers,
logical-row builder, and discovery function. Exactly one selected digital training
page was extracted with its actual page number and display coordinates. Native
evidence was extracted before the reference regions entered scoring. No other
page evidence, rendering, OCR, normalization, or reconciliation was run.

| Stage | Records on page | References with positive-area overlap | References with eligible row overlap |
| --- | ---: | ---: | ---: |
| Native words | 655 | 4/4 | — |
| Native glyphs | 3,169 | 4/4 | — |
| Logical rows | 81 | 4/4 | 4/4 |
| Discovered table rows | 38 | 0/4 | 0/4 |
| Frozen comparator rows | 38 | 0/4 | 0/4 |

Eligibility uses the unchanged positive-horizontal-overlap and half-row-height
rule. All four cases fall into the predeclared category
`logical_without_eligible_discovered_row`. Discovery returned one table region.
The new/frozen row-box multiset comparison has **38 shared, zero new-only, and
zero frozen-only rows**.

There are 70 native-word/reference overlaps, 366 glyph/reference overlaps, and
five logical-row/reference overlaps with the transaction regions. The merchant
regions also contain overlapping native evidence in all four cases: 25
word/reference and 123 glyph/reference overlaps. These are record/reference
pair counts, not merchant transcriptions, distinct merchants, or correctness
scores. Text was neither manually inspected nor matched to the reference strings.

All measured evidence and row boxes have valid geometry. The frozen quality rule
does not request OCR for this page. That flag does not certify text accuracy.

## Interpretation and limitations

The earlier absence of frozen evidence is explained, in this new run, by the
logical-row-to-table-discovery transition. Native evidence is available under
all four transaction and merchant regions. OCR is therefore not the immediate
coverage bottleneck measured here.

This is one new run with one-page context and native text only. Other-page
context, currency OCR, and parser repair steps are absent. Exact agreement with
the frozen row boxes does not make it the missing original discovery snapshot
or prove the historical reason for exclusion. Geometry alone does not establish
that the marked regions are valid current-statement transactions, or that the
native merchant text is correct.

The four original alignment failures remain unchanged. The best measured merchant
comparator remains **10/24 exact**, with no new merchant score claimed. No label
was repaired or promoted, and no sample or split was expanded.

## Validation and artifacts

Twenty invented-input tests cover selected-page extraction, actual page-number
preservation, zero/90-degree coordinates, invalid page selection and dimensions,
overlap boundaries, multi-region counting, and first-absent-stage attribution.
They were exercised against failing stubs before the implementation and now pass.
The private three-file diagnostic passes Ruff formatting, lint, and strict mypy.

An independent PyMuPDF rectangle calculation agrees on all **16 stage/case
comparisons**, with zero geometry disagreements and no additional extraction.
All 11 protected original input files remain byte-identical, including source,
references, frozen rows, saved alignment, and merchant outputs/scores. The frozen
checkout remains unchanged.

Required repository verification passes: Ruff format/check, mypy on 48 source
files, and **3,766 tests passed** in 99.69 seconds. No production code changed.
This is not private-corpus verification or production acceptance; no merge is
requested or performed.

The disposable adapter, tests, run script, new evidence/discovery snapshots,
case diagnostics, input hashes, and aggregate summary remain local under ignored
`artifacts/merchant-page-discovery-v1/`. No private text, identities, coordinates,
page pixels, or financial values are published in this report or committed.

## Stop and next recommendation

The authorized single diagnostic is complete. **STOP**; no tuning, alternative
run, new assignments, or support infrastructure follows under this authorization.

The next recommended extraction task is a bounded trace of why discovery excludes
the logical rows covering these four fixed references. Distinguish intentional
non-transaction filtering from missed transaction regions before proposing a
general extraction-rule change or requesting any reference correction.

```text
Scope: YES — measures coverage loss for four unresolved transaction regions
Experiment: shared evaluation
Measurement: eligible discovered-row coverage and logical-to-discovery exclusion
Result: 0/4 discovered versus 4/4 logical coverage; delta 0; recovery hypothesis falsified
Next extraction task: STOP
```
