# Remaining Digital Merchant Character-Error Results

**Status:** COMPLETE — STOP, 2026-09-20.

Authority: [measurement design](../superpowers/specs/2026-09-20-merchant-character-errors-design.md),
committed at `c238a9c` before private measurement.

## Result

Of the three remaining digital mismatches, **two have identical non-whitespace
character inventories but different sequences**. The third lacks **four character
occurrences: three letters and one punctuation mark**. There are no extra
occurrences in any case. The order-only-signature hypothesis is **supported**.

| Disjoint signature | Cases | Partial-text cases | Other-mismatch cases |
| --- | ---: | ---: | ---: |
| Identical non-whitespace sequence | 0 | 0 | 0 |
| Order-only: same inventory, different sequence | 2 | 0 | 2 |
| Missing-only inventory | 1 | 1 | 0 |
| Extra-only inventory | 0 | 0 | 0 |
| Mixed missing/extra inventory | 0 | 0 | 0 |
| **Total** | **3** | **1** | **2** |

The missing-only prediction is a subsequence of its reference: its existing
non-whitespace characters retain reference order. Neither order-only prediction
is a subsequence of its reference, and no reference is a subsequence of its
prediction. These checks use NFC-normalized strings with Unicode whitespace
removed; case, punctuation, numbers, marks and format controls are retained.

| Occurrence difference | Missing | Extra |
| --- | ---: | ---: |
| Letters | 3 | 0 |
| Punctuation | 1 | 0 |
| All other Unicode major categories | 0 | 0 |
| **Total** | **4** | **0** |

## Interpretation

The two equal-inventory cases are compatible with a permutation of their
existing characters. This does not identify a general ordering rule, locate the
problem within or between atoms, or prove that reference and extraction differ
only because of an ordering bug. No reordered merchant output or candidate was generated.

The four missing occurrences are absent from the selected output. This does not
establish that they are absent from all source evidence, nor distinguish an
extraction omission from a selection/assembly problem or a residual reference
issue. The inventory count preserves repeated occurrences rather than merely
counting distinct character values.

The full seed remains **19/24 exact**, with 24 aligned unique outputs. Digital
remains 13/16 and OCR 6/8. The two OCR failures are outside this measurement.
No new accuracy gain is claimed. The reviewed training seed is small and uses
repeat reads by the same person; this is not independent validation.

## Verification and stop

- All **72 saved scores** reproduce: 17/24 in each prior view and 19/24 in the
  punctuation candidate. Selection is exactly three digital errors: one partial
  text and two other mismatches.
- All three selected candidate strings and their original assembly strings
  reconstruct from the saved source atoms, proposal ownership, assembly order
  and recorded separator decisions.
- An independent sorted-inventory comparison verifies each classification and
  occurrence count. Longest-common-subsequence checks verify all six directional
  subsequence claims. Independent regex normalization reproduces all 72 scores.
- Sixteen invented-input tests pass, with expected initial failures for the core
  classification behavior. Ruff formatting/lint, strict typing of four private
  scripts, repository mypy and all **3,766 repository tests** pass.
- All 13 measurement inputs and the frozen checkout remain unchanged. No source
  PDF, image, new extraction, OCR or model was used. Labels and predictions were
  unchanged.
  Private classifications and scripts remain ignored under
  `artifacts/merchant-character-errors-v1/`.

One possible next extraction task is to **count exact non-whitespace witnesses
obtainable by reordering intact selected atoms in the two order-only cases**.
That would test whether a whole-atom ordering explanation is sufficient, without
changing characters or generating a new candidate. Failure to find a witness
would remain unresolved rather than prove a particular within-atom defect.
This recommendation has not been executed.

This classification stops here. No further diagnostic, repair rule, new labels,
wider sample, held-out access or production integration is active.

```text
Scope: YES — quantifies remaining digital merchant character-error signatures
Experiment: row-profiles
Measurement: character-order, inventory differences and subsequence case counts
Result: two order-only cases and one missing-only case with four missing occurrences; zero extras; hypothesis supported; accuracy unchanged at 19/24
Next extraction task: STOP
```
