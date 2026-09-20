# Merchant Corrected-Block Ordering Witness Measurement

**Status:** APPROVED — measurement pending.

The user's “proceed” approves the completed LTR glyph candidate report's
recommendation to test intact corrected-block ordering in its two changed
reviewed cases.

```text
Scope answer: YES — measures whether corrected-block order explains the remaining errors in two changed merchant outputs
Experiment: row-profiles
Extraction hypothesis: At least one changed case has a reference-matching order using every corrected block exactly once, ignoring whitespace
Measurement: witness cases, matching identity-order counts and unresolved limits
Fixed inputs: two changed digital training cases, saved LTR decisions and outputs, v3 references and 96 saved scores
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-corrected-order-witness-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-corrected-order-witness-report.md; artifacts/merchant-corrected-order-witness-v1/**
Required output: quantified witness counts and a supported, falsified or unresolved hypothesis
Stop condition: stop after the two-case measurement or saved-result reproduction failure; no new candidate, label edits, source access or larger search
```

## Fixed inputs

Reproduce all 96 saved scores: 72 for the three previous output views and 24
for the saved LTR glyph candidate. Reconstruct all 113 candidate owner outputs
from its 373 saved atom decisions and the unchanged separator decisions.
Check each saved occurrence against the original owner, ordinal and selected
atom identity; preserve its saved corrected text. No glyph regeneration is
needed: that source-only candidate was independently verified in its phase.

Select exactly the two reviewed outputs changed relative to punctuation spacing.
Require both to be digital training cases with unchanged `other_mismatch` scores.
The remaining digital error, unchanged reviewed outputs and OCR cases are outside
this diagnostic. Existing source artifacts, references and checkout stay read-only.
No PDFs, pixels, new extraction, OCR, models or held-out data may be accessed.

## Predeclared diagnostic

Reuse the existing pure `whole_atom_witness` query without changing it. Retain
each corrected atom occurrence as a distinct block, including duplicates and
empty projections. Project each block and the reference with NFC followed by
removal of Unicode whitespace; preserve all remaining code points and their
within-block order. Check that concatenating recorded block projections equals
the projection of the saved candidate output. Otherwise report unresolved
recorded projection.

For at most **nine occurrences**, enumerate every identity permutation using
every block exactly once. Never split, reverse, rewrite, omit or duplicate a
block. Preserve the existing normalization guards: for every order, projection
of the raw concatenation must equal concatenation of block projections, and the
projected concatenation must already be NFC. Any unstable order makes that
case unresolved. Cases above nine occurrences remain unresolved; do not increase
the cap.

Report witness-case counts, zero/one/multiple matching identity-order counts,
occurrence counts, permutations checked and unresolved limits. Keep only a
representative index permutation privately, not a label-derived prediction.
Duplicate-text occurrences can produce multiple identity orders with identical
rendered text. The whitespace-free diagnostic does not change exact-match scores.

The hypothesis is supported if at least one resolved case has a witness,
falsified if both resolve with none, and otherwise unresolved. A witness proves
only that intact corrected blocks admit an arrangement matching the reference
projection; it does not identify a source-only ordering rule or settle spacing.

## Verification and stop

Commit authority before measurement. Reuse the 13 existing invented-input
witness tests with all caches directed to the new private directory. Verify
counts using the existing independent prefix/subset dynamic program and
recursive normalization audit; check any representative index order against
the original saved strings. No new query implementation is needed.

Keep disposable measurement glue, results and logs in ignored
`artifacts/merchant-corrected-order-witness-v1/`. Check that read inputs and
the frozen checkout are unchanged. Publish aggregates only. Run the four
repository gates before tracked commits. End this phase after the measurement;
any subsequent source-order candidate is a separate task. No shared framework,
production change or corpus-acceptance claim is authorized.
