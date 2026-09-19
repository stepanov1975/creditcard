# Merchant Geometry Spacing Experiment Report

**Status:** COMPLETE — STOP. Measured on 2026-09-19.

**Authority:** The user's “proceed” approved the v3 error report's recommendation.
The [design](../superpowers/specs/2026-09-19-merchant-spacing-design.md) and charter
allowance were committed at `eb2d3c9` before private candidate generation.

## Result

The one fixed geometry-spacing candidate remains **17/24 exact (70.8%)**, with
**zero gains and zero losses**. It changes two reviewed digital outputs by
removing one inserted separator each; neither becomes exact. Both spacing-only
digital mismatches remain. The hypothesis of increased exact match without losses
is **falsified**. There is no measured reason to adopt this candidate.

| Slice | Baseline exact | Candidate exact | Gains / losses | Changed outputs | Removed separators | Spacing-only errors before / after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 17/24 | 17/24 | 0 / 0 | 2 | 2 | 2 / 2 |
| Digital | 11/16 | 11/16 | 0 / 0 | 2 | 2 | 2 / 2 |
| OCR | 6/8 | 6/8 | 0 / 0 | 0 | 0 | 0 / 0 |

Both views retain **24/24 alignment and unique-output coverage**. Every case
category is unchanged: 17 exact, two partial texts and five other mismatches.
There are no alignment failures, omissions, ambiguous outputs or extra-text
categories. The same v3 references and saved assignments were used throughout.

This result tests one heuristic, not all possible spacing methods. It does not
locate the remaining whitespace differences inside versus between source atoms,
or establish that another gap threshold would solve them. No threshold sweep,
second candidate or reference-guided correction was attempted.

## Fixed candidate and generation

The candidate is a small runnable merchant renderer under ignored
`artifacts/merchant-spacing-v1/spacing.py`. It consumes the already selected atoms
in their recorded order. It removes only the inserted separator between adjacent
same-source atoms when their touching edge characters are letters with the same
strong direction, their boxes overlap vertically by at least 80% of the smaller
height, and the nonnegative directional gap is at most 0.20 times the smaller
estimated character width. The design fixes the width estimate and all abstention
conditions. These thresholds were declared before private generation.

Explicit whitespace and every source character remain unchanged. The rule does
not split atoms, alter internal whitespace, reorder text, change ownership or
select additional evidence. Invalid geometry, overlapping/reversed boxes,
punctuation/digit boundaries, mixed directions and other uncertain boundaries
retain the existing separator.

Generation read only the 135 saved rows/proposals, assembly outputs/statuses and
recorded assembly order. All **113 owner outputs** were reconstructed first.
Candidate outputs were saved before opening any v3 references, case scores,
alignment or source-mode selection. No source page, merchant region or prior
case diagnosis entered candidate generation. No PDF extraction, OCR, model,
classification or new assembly decision ran.

Across all 113 saved owner groups, **six outputs changed**, with **eight inserted
separators removed**; the other 107 outputs remained unchanged. Only two changed
outputs belong to the reviewed 24-case set. The unreviewed outputs provide no
accuracy evidence and were not assigned scores.

| Boundary decision across all saved groups | Count |
| --- | ---: |
| Gap too wide | 170 |
| Overlapping boxes or incompatible physical order | 21 |
| Unsupported letter direction or nonletter edge | 60 |
| Separator removed | 8 |
| Different line | 1 |
| Total boundaries | 260 |

All saved owner groups were comparable and had one nonempty output in this run.
Output multiplicity, source atoms, source text, ownership and recorded order are
preserved. The baseline files and frozen deterministic checkout remain unchanged.

## Verification and limitations

- Eighteen invented-input tests pass after focused red/green cycles at the ordered-
  atom renderer seam. They cover narrow/wide gaps, inclusive gap and line-overlap
  thresholds, Hebrew/LTR direction, overlap/order abstention, invalid boxes,
  explicit and internal whitespace, combining characters, punctuation/digits,
  mixed source/direction, empty/singleton input and source-data preservation.
- All 113 baseline owner outputs reconstruct exactly from saved proposals or
  recorded assembly order. All 24 saved v3 scores reproduce before comparison.
- A separate implementation using decimal geometry agrees on **260 boundary
  decisions**, **eight removed separators** and all candidate strings. It confirms
  preservation of **373 selected atom occurrences**, their order and non-whitespace
  characters across all 113 groups.
- An independent scorer agrees on **48 case outcomes**, exact rates, coverage,
  gains/losses, transitions, changed-output counts and spacing-only counts in all
  three source slices.
- Six generation inputs, nine scoring inputs and 15 verification inputs remain
  unchanged; these sets overlap. No source documents were read.
- Private formatting, lint and strict mypy pass. All required repository gates
  pass: Ruff formatting, Ruff lint, mypy over 48 source files and **3,766 tests**.

This is one experiment on a small training seed with one human reviewer, not
document-disjoint validation or production acceptance. Private references,
outputs, source identities and boundary records remain local and ignored. Only
aggregate documentation is tracked. No production code or frozen branch changed;
no private-corpus acceptance, merge or push is claimed.

## Next recommendation

Quantify **within-atom versus between-atom whitespace discrepancies in the two
remaining spacing-only digital cases**, using unchanged saved text and recorded
atom boundaries. Preserve ambiguous attributions where normalization or overlapping
source records prevent a unique attribution. This would establish whether the
current atom geometry can support another spacing rule before choosing a further
extractor change.
It is a recommendation for separate approval and has not been performed here.

The single-candidate comparison is complete. **STOP**. No tuning, second
candidate, additional diagnosis, label change, sample expansion or held-out
access is active.

```text
Scope: YES — tested a general merchant spacing change in row-profiles
Experiment: row-profiles
Measurement: exact merchant match, paired gains/losses, coverage and spacing-only errors
Result: 17/24 to 17/24 exact; zero gains/losses; two reviewed outputs changed; two spacing-only errors remain; 24/24 aligned unique outputs; hypothesis falsified
Next extraction task: STOP
```
