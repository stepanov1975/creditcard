# Merchant Evidence Error Measurement

**Status:** Approved by the user's “proceed” on 2026-09-12, following the concrete
recommendation to inspect the ten remaining text mismatches using the existing
human-marked merchant regions. Commit this design and charter amendment before
private measurement.

```text
Scope answer: YES — quantifies the remaining merchant extraction errors against human-marked evidence
Experiment: row-profiles
Extraction hypothesis: At least one of the ten fixed mismatches includes selected evidence wholly outside the human-marked merchant regions
Measurement: merchant-region support categories, unselected in-region evidence counts, text-order/spacing/control-character signatures, and character error rate
Fixed inputs: the ten mismatching pre-rejection cases, unchanged human merchant regions/text, frozen proposals and row observations, and source-page geometry
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-evidence-error-design.md; docs/superpowers/plans/2026-09-12-merchant-evidence-errors.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-evidence-error-report.md; artifacts/merchant-evidence-errors-v1/**
Required output: quantified evidence-location and text-mismatch categories that identify the next extraction task
Stop condition: stop after the fixed error analysis; do not change labels, predictions, extraction rules, alignment, or sample membership
```

## Fixed input selection

Select exactly the ten `before_financial_rejection` cases categorized as
`extra_text`, `partial_text`, or `other_mismatch` in the completed
[pre-rejection measurement](../../experiments/row-extraction-merchant-pre-rejection-report.md).
Freeze their existing identities in a new private selection file before analysis.
Do not include the eight exact matches, ambiguous output, row-type omission, or
four alignment failures. This is an error-only diagnostic sample, not a new
accuracy estimate or sample expansion.

Read the existing diagnostic proposals, 127 selected training-row observations,
24 human references, and unchanged saved alignment. Every selected case must have
exactly one owned description proposal, rendered identically to its saved output.
Use the original source row associated with that proposal, including continuation
ownership where present. Do not rerun an extractor or reconstruct a different
merchant candidate.

Read only page dimensions and rotation from the existing local seed PDF copies,
checking their frozen source identities. This supports the same point-to-normalized-
display coordinate mapping used for the existing alignment. Do not render pages,
extract new PDF text, call OCR, or send private content to model tools.

## Evidence-location measurement

Compare the proposal's declared atom boxes with the human merchant regions in
normalized full-page display coordinates. Keep the saved transaction alignment
unchanged; merchant-region overlap is diagnostic, not a new acceptance gate.

For each finite, nonempty selected atom rectangle:

- **Strong region support:** its center lies within at least one merchant region
  and the maximum intersection with any one region covers at least 50% of the
  atom's area. Use the maximum, not a sum across possibly overlapping regions.
- **Outside:** it has zero positive-area intersection with every merchant region.
- **Boundary-sensitive:** it has some intersection but does not meet the strong
  support rule. Do not force this into an ownership or recognition error.
- **Unusable geometry:** nonfinite/empty rectangles, or evidence on another source
  page. Record the category rather than applying an invented coordinate mapping.

Report atom counts and disjoint case categories, in this precedence: unusable
geometry; at least one outside atom; boundary-sensitive with no outside atom; all
selected atoms strongly supported. Also report the raw overlapping flags so the
precedence does not conceal outside evidence on a partially unusable case.

For the proposal's original frozen row, count unselected atom records that have
strong merchant-region support. These are possible missing evidence records, not
confirmed omitted words: the frozen representation can contain overlapping or
duplicate records. Do not deduplicate, select, merge, or render those records into
an alternative prediction. Evidence in other rows is outside this diagnostic count.

The hypothesis is supported when at least one fixed case has an outside selected
atom. If all comparable evidence is available and no case has an outside atom,
it is falsified. Incomplete geometry without an observed outside atom yields an
unresolved hypothesis plus its quantified failure count. Geometric support does
not prove semantic correctness or independently validate the human regions.

## Text diagnostics

Reuse the existing NFC plus collapsed-Unicode-whitespace normalization. Preserve
all saved predictions and exact-match outcomes. On the ten mismatches, measure:

- **Word-order signature:** normalized whitespace-delimited token multisets are
  identical but the normalized strings differ.
- **Spacing-only signature:** deleting all whitespace from the normalized strings
  makes them identical.
- **Format-control-only signature:** deleting Unicode category `Cf` characters
  from both strings and reapplying the existing normalization makes them identical.
- **Character error rate:** Levenshtein edit distance on normalized code points,
  summed across cases and divided by total reference code points with `Decimal`.
  Do not clip rates over one. Report edit totals/rates by geometry category and
  OCR/digital page slice.

These signatures may overlap. They are diagnostics, not corrections applied to
the scorer. A mismatch inside a well-supported region can reflect recognition,
serialization/order, duplicate evidence, or reference transcription. Do not call
it an OCR failure or hallucination without evidence that distinguishes those causes.

## Execution and stop boundary

Only a small local analysis script and invented-input tests may be written under
ignored `artifacts/merchant-evidence-errors-v1/`. Reuse existing prediction models,
normalization, evidence rendering, and frozen artifacts. No controller, new shared
schema, CLI family, model, dependency, or annotation interface is authorized.

Test inside/outside/boundary/invalid geometry, the inclusive 50% boundary,
overlapping-region handling, text signatures, and edit-distance arithmetic before
private execution. Report only aggregates publicly. Preserve source artifacts and
verify the saved scores remain unchanged. Run the repository's four gates before
tracked commits, publish the results, and return the live phase to `STOP`.
