# Merchant Whole-Atom Ordering Witness Measurement

**Status:** COMPLETE — STOP. Both cases have zero witnesses; the hypothesis is
falsified. See the [report](../../experiments/row-extraction-merchant-atom-order-witness-report.md).

The user's “proceed” approves the completed character-error report's
recommendation to test reordering intact selected atoms in the two order-only cases.

```text
Scope answer: YES — measures whether intact-atom reordering can explain the two remaining order-only merchant errors
Experiment: row-profiles
Extraction hypothesis: At least one of the two order-only cases has an exact non-whitespace reference witness using every selected atom once without within-atom edits
Measurement: cases with whole-atom permutation witnesses, matching identity-order counts and unresolved limits
Fixed inputs: two saved order-only digital cases, v3 references, 72 saved scores and selected source atoms in recorded order
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-atom-order-witness-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-atom-order-witness-report.md; artifacts/merchant-atom-order-witness-v1/**
Required output: quantified whole-atom witness counts and a supported, falsified or unresolved hypothesis
Stop condition: stop after the two-case witness measurement or saved-result reproduction failure; do not increase limits, generate a candidate, edit labels or access new sources
```

## Fixed inputs

Reproduce all 72 saved scores and the three previous digital classifications.
Select exactly the two saved `order_only_signature` cases, both digital training
cases currently scored `other_mismatch`. The missing-only digital case and both
OCR failures are excluded. Verify selected atoms, original ownership and recorded
order against saved evidence and reconstruct the existing output strings.

Existing candidate/reference data and the frozen checkout stay unchanged. No
source PDFs, pixels, new extraction, OCR, models, label edits, new review, broader
sample or held-out access are authorized.

## Predeclared diagnostic

The public diagnostic seam is `whole_atom_witness(texts, reference)`. Each input
atom occurrence retains its ordinal identity, including occurrences with equal
text. Project each atom and the reference with NFC followed by removal of Unicode
whitespace, preserving all other code points and their within-atom order.
Require the concatenated projections in recorded order to equal the projection
of the saved prediction; otherwise report unresolved normalization attribution.

For at most **nine selected atom occurrences**, enumerate all identity permutations,
using each occurrence exactly once. Compare concatenated atom projections to the
reference projection. Never split, reverse or rewrite text inside an atom, drop
an occurrence, borrow unselected evidence or choose a different owner. The test
ignores whitespace and makes no merchant exact-match claim.

Check normalization stability for every enumerated order: projecting the raw
concatenated source strings must equal concatenating their projections, and the
projected concatenation must itself be NFC. If any order violates this boundary
condition, report the case as unresolved instead of claiming a complete witness
count. If the case exceeds nine occurrences, report unresolved without raising
the limit. These guards avoid mistaking cross-atom composition for intact-block
ordering. Count zero-text projections as retained occurrences, not deletions.

For fully resolved cases, report the exact number of matching identity orders,
plus zero/one/multiple-witness case counts. Duplicate-text occurrences can make
identity-order counts exceed the number of visibly distinct arrangements; this
is not evidence that alternative rendered merchant strings exist. Keep only a
representative index permutation privately as diagnostic evidence, not a corrected
merchant output or label-derived extraction rule. Report permutation counts and
atom-occurrence counts, without private identities or text.

The hypothesis is supported if at least one resolved case has a witness, falsified
if both resolve with none, and otherwise unresolved. A negative result only rules
out the fixed intact-atom permutation explanation; it does not prove a particular
within-atom defect or certify the human reference independently.

## Verification and stop

Commit authority before private measurement. Use invented-input red/green tests
at the diagnostic seam for reversed block order, equal inventories without a
block witness, duplicate occurrences, empty/whitespace projections, NFC, retained
controls and the fixed atom/normalization limits. Independently verify counts with
prefix/subset dynamic programming and verify stored index witnesses against the
original strings. Recheck source membership, prior scores and classifications.

Keep scripts and private results only in ignored
`artifacts/merchant-atom-order-witness-v1/`. Publish aggregates only and run the
four repository gates before tracked commits. Stop after the measurement or
saved-result reproduction failure. No second diagnostic, search-limit adjustment,
candidate, shared controller/schema/CLI or production integration is active.
