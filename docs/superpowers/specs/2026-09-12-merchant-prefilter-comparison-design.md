# Merchant Comparison Before Future-Billing Exclusion

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to test merchant recognition before the future-billing filter,
retaining all 24 references and production billing decisions. Commit this
authority before private candidate generation.

```text
Scope answer: YES — measures merchant recognition when saved future-billing candidate evidence is available before billing exclusion
Experiment: row-profiles
Extraction hypothesis: Adding merchant proposals from the saved pre-filter candidate table yields a positive net exact-match gain against 10/24 on the same references
Measurement: normalized merchant exact match, paired gains/losses, output coverage, alignment failures, omissions, and ambiguity
Fixed inputs: 24 unchanged training references, 127 frozen rows and reading-order predictions, one saved excluded eight-row candidate table, and the frozen tight profile rule
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-prefilter-comparison-design.md; docs/superpowers/plans/2026-09-12-merchant-prefilter-comparison.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-prefilter-comparison-report.md; artifacts/merchant-prefilter-comparison-v1/**
Required output: paired merchant metric delta and supported or falsified positive-gain hypothesis
Stop condition: score the one fixed candidate on all 24 references and stop; no tuning, alternate candidates, label changes, or support subsystem
```

## Fixed candidate

Read the saved exclusion trace and one-page native evidence from the completed
diagnostics. Use only initial table candidates marked as future billing by that
trace: one eight-row table. Do not duplicate its eight singleton rediscoveries.
Use every row in the selected table, without reference-guided selection or crops.
The frozen deterministic checkout remains
`a2ed73aa58a4e4d8c76f918657d083fa922537d4`.

Adapt saved candidate rows to the existing row contract using the frozen pure
row/column summary and atom projection functions. Preserve their source word
text, geometry, column roles, and source confidence. Use the existing row-ID
function for diagnostic identity. This is temporary input to the merchant rule,
not a new frozen bundle, historical replay, or replacement benchmark.

For the affected page, the saved initial candidate order has 46 rows: 38 already
present plus eight excluded rows. Keep existing rows and predictions unchanged.
Give only the eight new diagnostic rows predecessor/successor context from that
flat candidate order, using the existing gap calculation. Assign no accepted
baseline type; use `ambiguous` as the diagnostic placeholder. Classification is
computed from evidence by the frozen profile classifier with tight continuation
gap `Decimal("0.50")`, never from reference text or the placeholder type.

Apply the existing pre-financial-rejection description probe and fixed
Hebrew/Latin reading-order permutation. Primary rows own their description;
continuations use the classifier's existing immediate-predecessor ownership;
ambiguous or structural rows produce no description. The eight new rows retain
`IGNORE` with an explicit future-billing diagnostic reason. No financial field
proposals, parser normalization, reconciliation, or acceptance promotion is run.

Combine those diagnostic descriptions with the 127 saved reading-order
predictions, without rewriting the originals. This isolates access to the saved
excluded table's merchant evidence. Do not rerun discovery, read PDFs, render,
OCR, invoke models, or process other pages.

## Fixed comparison

Keep the original 24-case alignment and scores as the baseline. In a separate
candidate alignment, preserve the 20 existing matched assignments and use the
unchanged geometric alignment rule for the four saved null cases on the affected
page. Compare against all 46 candidate row boxes so ties or ownership collisions
remain failures. References enter only this scoring stage, after proposals exist.
No human merchant region or text may enter the classifier or description rule.

Score all 24 references with the existing NFC/whitespace normalization, exact
match, omission, ambiguity, partial/extra text, and other-mismatch categories.
Report output coverage, aligned cases, paired gains/losses, and digital/OCR
slices. Also report the fixed four-case filtered subset and whether any of the
20 previously aligned cases changes output, assignment, or exactness. Do not
reduce the denominator or claim a merchant from geometry alone.

A positive net exact-match gain supports the hypothesis. Zero or negative net
gain falsifies it on this fixed training comparison. Preserve separate reported
historical and candidate scores even if the candidate improves. This is an
extension of accessible candidate evidence for merchant measurement, not evidence
that production billing inclusion should change or a new frozen-arm ranking.

## Minimal implementation, validation, and stop

Only disposable private adaptation, candidate scoring, and invented-input tests
under ignored `artifacts/merchant-prefilter-comparison-v1/` are authorized. Test
source-evidence preservation, continuation ownership, duplicate-row rejection,
and retaining future-billing exclusion before implementing new behavior. Reuse
existing models, pure atom helpers, classifier, description rule, renderer,
reading order, and scorer; add no shared API, schema family, bundle builder,
controller, CLI, provenance machinery, or handoff re-freezing.

Keep all private source contents, identities, coordinates, predictions, and
financial data local and out of Git and tool output. Catch errors privately and
publish aggregate counts only. Check original rows, labels, matches, and scores
remain unchanged. Run repository gates and focused verification before commits.

Stop after this one fixed comparison, including a quantified failure if the
candidate cannot be measured. No tuning, second candidate, scope correction of
labels, new annotation, sample expansion, gold promotion, validation/test access,
or production integration is authorized.
