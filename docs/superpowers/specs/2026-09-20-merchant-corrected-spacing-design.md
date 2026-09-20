# Merchant Corrected-Output Spacing Diagnostic

**Status:** COMPLETE — STOP. Both cases are whitespace-only errors with unique
identity-order witnesses and no unresolved cases. The hypothesis is supported;
exact accuracy remains 19/24. See the
[report](../../experiments/row-extraction-merchant-corrected-spacing-report.md).

The user's “proceed” approves the completed tolerance report's recommendation
to classify whitespace differences and compare saved witnesses with recorded order.

```text
Scope answer: YES — quantifies remaining merchant extraction errors after glyph correction
Experiment: row-profiles
Extraction hypothesis: Both changed reviewed digital outputs differ from their references only in whitespace, and each unique corrected-block witness equals recorded order
Measurement: whitespace-only cases, unique identity-order witnesses and unresolved cases
Fixed inputs: two changed digital training outputs, 24 v3 references, 144 saved scores, saved corrected blocks and two saved witnesses
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-corrected-spacing-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-corrected-spacing-report.md; artifacts/merchant-corrected-spacing-v1/**
Required output: quantified whitespace-only and identity-order counts with a supported, falsified or unresolved hypothesis
Stop condition: stop after this two-case diagnostic or saved-result reproduction failure; no predictions, source access, labels, larger search or second task
```

## Fixed measurement

Commit this authority before measurement. Reuse the existing corrected-witness
input loader to reconstruct all 113 glyph outputs from 373 saved decisions and
reproduce 96 scores. Verify the strict-order and tolerance outputs still equal
the saved glyph outputs, and reproduce the remaining 48 scores with the fixed
24 references and alignment. Do not load native pages or original PDFs.

Select exactly the same two reviewed digital training outputs changed by glyph
correction. Classify their saved strings with the existing NFC/Unicode-whitespace
character diagnostic. A non-exact string with equal non-whitespace sequences
is a whitespace-only error. Preserve all other character-error categories.

Reproduce the two saved whole-block witnesses with the existing nine-occurrence
cap and normalization guards. Compare each unique witness with occurrence order
`0, 1, ..., n-1`. Count unique identity, unique different-order, multiple, absent
and unresolved witnesses separately. No reference-guided string becomes a new
prediction. Check the projection of recorded blocks against saved output.

The hypothesis is supported only if both cases are whitespace-only and both
unique witnesses equal recorded order. A resolved counterexample falsifies it;
otherwise any unresolved case leaves it unresolved.

## Verification and stop

Use the existing independent regex projection, subset counting and normalization
audit to check both classifications and identity-order results. Independently
check all 144 score records. Run relevant existing classifier/witness tests;
no new extraction behavior or algorithm is introduced. Check saved inputs and
the frozen checkout remain unchanged, and run all four repository gates before
tracked commits.

Keep private strings, identities, code and logs in ignored
`artifacts/merchant-corrected-spacing-v1/`. Publish aggregate counts only.
Accuracy remains the saved metric: this diagnostic cannot improve predictions.
Stop after measurement. Any spacing candidate is a separate, unexecuted
recommendation; no validation, held-out, source extraction or production work
is active.
