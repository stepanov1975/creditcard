# Merchant Unchanged-Order Spacing Results

**Status:** COMPLETE — STOP. Measured on 2026-09-20.

**Authority:** The [fixed design](../superpowers/specs/2026-09-20-merchant-unchanged-order-spacing-design.md)
and charter amendment were committed at `9246999` before implementation and
measurement. The user's “proceed” approved this one candidate only.

## Result

Exact merchant matches increase from **19/24 to 21/24 (87.5%)**, with **two gains
and zero losses against each of four saved baselines**. Alignment and unique-output
coverage remain **24/24**. The predeclared hypothesis is **supported**.

| Source slice | Saved baseline exact | Candidate exact | Gains / losses | Aligned unique outputs |
| --- | ---: | ---: | ---: | ---: |
| All | 19/24 | 21/24 | 2 / 0 | 24/24 |
| Digital | 13/16 | 15/16 | 2 / 0 | 16/16 |
| OCR | 6/8 | 6/8 | 0 / 0 | 8/8 |

The paired counts are identical against punctuation spacing, saved LTR glyph
correction, strict block ordering and LTR tolerance. In each comparison, the two
changed reviewed outputs move from `other_mismatch` to `exact`; the existing 19
exact cases stay exact. The remaining three cases are two partial texts and one
other mismatch. No alignment failure, omission, ambiguous output or extra-text
case is introduced. Reference values, alignment and scorer are unchanged, so
these two gains are extraction gains rather than reference corrections.

## Candidate behavior

The rule removes the unchanged-order rendering bypass while retaining the
existing source, geometry, direction, punctuation and NFC guards. Original atoms
support native matching; the previously saved glyph correction supplies text.
It applies to every saved owner group without using reviewed-case membership.
No new threshold was chosen or source box changed.

| Generation measurement | Count |
| --- | ---: |
| Saved training rows | 135 |
| Owner outputs reconstructed and emitted | 113 |
| Saved atom occurrences retained | 373 |
| Eligible groups rendered in unchanged order | 38 |
| Reordered groups | 0 |
| Changed owner outputs versus saved glyph outputs | 4 |
| Tolerance joins | 8 |
| Groups falling back for excessive overlap | 3 |
| Groups excluded for direction / singleton / OCR source | 52 / 2 / 18 |

Two of the four changed owner outputs are among the 24 reviewed references; both
become exact. The other two are not scored by this reference set, so no accuracy
claim is made for them. Three groups fail the existing -0.0001 adjacent-gap guard
and retain their saved output. Their thresholds were not adjusted after scoring.

All predictions were saved before reference access. Generation used the existing
saved evidence and four native-page snapshots, with zero source PDFs, OCR calls,
models or new native extraction. Ownership, within-atom glyph text, financial
fields and production parser behavior remain unchanged.

## Verification

- Observed the expected synthetic failure: an eligible identity-order pair
  retained a space instead of joining. The independent checker also failed the
  corresponding identity-order expectations before its bypass was removed.
- **36 synthetic checks pass**, covering unchanged-order rendering, positive and
  negative gaps, punctuation, inclusive tolerance, excessive overlap, required
  spaces, source ambiguity, preserved glyph corrections and occurrences, NFC
  fallback, and prior changed-order behavior.
- All **144 saved scores reproduce** before scoring the candidate. Separate source
  checks and rational tolerance arithmetic agree on **113 owner decisions and
  outputs**. Independent normalization/scoring agrees on all **168 records**,
  three source slices and four baseline comparisons per slice. The unchanged
  existing punctuation-spacing primitive is shared by candidate and checker.
- Twelve saved inputs are preserved during generation; the combined verification
  checks preserve 24 inputs including the completed candidate output. The frozen
  deterministic checkout remains unchanged.
- Private Ruff formatting/lint and strict mypy pass for seven Python files.
  All four repository gates pass: Ruff format/lint, mypy over 48 source files,
  and **3,766 tests in 98.89 seconds**.

Private code, outputs, case scores and logs remain under ignored
`artifacts/merchant-unchanged-order-spacing-v1/`. Only aggregates are tracked.
This repeatedly inspected, same-reviewer training seed does not establish
validation accuracy, population accuracy or private-corpus acceptance.

## Stop and next decision

Stop here with the completed candidate preserved. No post-score tuning or second
candidate ran. Before further optimization or integration, the recommended next
separately approved task is to design a document-disjoint merchant evaluation
sample with source-page references reviewed without predictions. That evaluation
has not been designed or executed; no new documents, labels or validation inputs
were opened. No production integration is active.

```text
Scope: YES — measures a source-only merchant spacing candidate on the fixed training seed
Experiment: row-profiles
Measurement: exact merchant matches, paired gains/losses, coverage and changed outputs
Result: 19/24 to 21/24 exact; two gains and zero losses against four baselines; 24/24 coverage; hypothesis supported
Next extraction task: STOP
```
