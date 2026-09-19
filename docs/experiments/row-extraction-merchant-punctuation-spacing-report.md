# Merchant Punctuation-Aware Spacing Results

**Status:** COMPLETE — STOP, 2026-09-19.

Authority: [experiment design](../superpowers/specs/2026-09-19-merchant-punctuation-spacing-design.md),
committed at `3b2eca1` before candidate generation.

## Result

The single candidate increases exact merchant matches from **17/24 to 19/24**
(70.8% to 79.2%), with **two gains and zero losses** against both the original
v3 output and the previous geometry-spacing output. All 17 existing exact cases
remain exact. Both spacing-only errors become exact, and alignment and unique
output coverage remain **24/24**. The gain-without-loss hypothesis is supported.

| Slice | Cases | Original v3 exact | Prior spacing exact | New candidate exact | Gains / losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| All | 24 | 17 | 17 | 19 | 2 / 0 |
| Digital | 16 | 11 | 11 | 13 | 2 / 0 |
| OCR | 8 | 6 | 6 | 6 | 0 / 0 |

The paired gains/losses are identical against both prior views. All categories
other than the two corrected digital mismatches retain their counts:

| Score category | Either prior view | Candidate |
| --- | ---: | ---: |
| Exact | 17 | 19 |
| Partial text | 2 | 2 |
| Other mismatch | 5 | 3 |
| Alignment failure, omission, ambiguity or extra text | 0 | 0 |
| Spacing-only mismatch signature | 2 | 0 |

The spacing-only row overlaps the other-mismatch category. The five remaining
errors comprise three digital cases (one partial, two other mismatches) and two
OCR cases (one partial, one other mismatch).

## Change and generation

The candidate preserves the previous letter-spacing decisions and extends the
rule only where a punctuation edge previously caused `unsupported_direction`.
It infers direction from the nearest strong letters on either side within the
same saved owner sequence. Matching context direction, valid comparable boxes,
at least 80% vertical overlap and a nonnegative gap at most 20% of the smaller
estimated character width permit removal of the inserted separator. Other
boundaries retain their separator. No source character or atom order is edited.

Generation used only the six saved evidence/assembly inputs and reconstructed
all **113 owner outputs** from **135 saved rows/proposals** before scoring opened
references. The rule was applied to every comparable owner, without case labels,
merchant identities, attachment-category selection or per-document exceptions.
Its design was informed by prior training-seed diagnostics, so this separation
of generation and scoring does not make the evaluation independent.

Across all 113 owner groups, 17 output strings change from the original assembly.
The rule removes 30 inserted separators: eight from the unchanged letter rule
and 22 from its punctuation extension. These are generation counts; most owner
groups are not covered by the 24 reviewed references and have no accuracy verdict.

Within the reviewed seed, four outputs change from original v3 and two change
from the previous spacing candidate. All changes are digital. Eight separators
are removed from original v3, of which six are new punctuation joins correcting
the two spacing-only cases. OCR outputs are unchanged in this seed.

## Verification and limits

- All 48 prior case scores reproduce; the new candidate contributes 24 scores.
- Independent decimal/rational geometry checks agree on **260 boundary
  decisions**, including all 22 punctuation joins, and reconstruct all 113
  candidate outputs while preserving 373 selected source-atom occurrences.
- Independent scoring agrees on all **72 scores**, all three source slices,
  paired comparisons, category transitions, coverage and separator counts.
- Nineteen invented renderer tests pass, covering context direction, threshold
  boundaries, RTL order, source-character preservation, geometry/source failures,
  explicit whitespace and unchanged non-punctuation behavior. Core rendering and
  retained-boundary decisions were implemented after expected failing tests.
- Ruff formatting/lint, strict typing of five private scripts, repository mypy
  and all **3,766 repository tests** pass. Six generation inputs, 11 scoring
  inputs and 17 verification inputs remain unchanged; these sets overlap. The
  frozen checkout remains unchanged.

Private outputs, labels and diagnostics stay local and ignored under
`artifacts/merchant-punctuation-spacing-v1/`. No source PDFs or pixels were read,
and no new extraction, OCR or model calls were made. No reference labels or
production source changed; no private-corpus acceptance is claimed.

This is a small, correlated training seed with repeated reads by one reviewer.
It demonstrates a seed improvement, not document-disjoint validation or reliable
accuracy on all generated owner groups. Keep the candidate experimental.

## Recommendation and stop

One possible next extraction task is to **quantify character-order versus
missing/extra-character mismatches in the three remaining digital cases**, using
the saved candidate, atoms and v3 references. That would determine whether a
general ordering or text-content experiment is warranted. This recommendation
has not been executed; the candidate is unchanged after the result.

This comparison stops here. No second candidate, threshold tuning, new labels,
wider sample, held-out evaluation or production integration is active.

```text
Scope: YES — tests punctuation-aware merchant spacing on the fixed seed
Experiment: row-profiles
Measurement: exact merchant match, paired gains/losses, coverage and spacing-only errors
Result: 17/24 to 19/24 exact, two gains and zero losses, 24/24 coverage, spacing-only errors reduced from two to zero
Next extraction task: STOP
```
