# Merchant v3 Residual Error Analysis Report

**Status:** COMPLETE — STOP. Measured on 2026-09-19.

**Authority:** The user's “proceed” approved the completed v3 comparison's
recommendation. The [design](../superpowers/specs/2026-09-19-merchant-v3-error-analysis-design.md)
and charter allowance were committed at `c70ed3b` before private measurement.

## Result

Of the seven residual merchant mismatches, **two OCR cases lack required
characters in their saved region evidence**. **Five digital cases remain
unresolved**, including **two spacing-only mismatches**. No exact whole-atom
witness was found under the predeclared search. The recoverable-text hypothesis
is **falsified for that bounded search**; this does not prove that selection or
assembly could not be improved by another general rule.

| Disjoint error category | All | Digital | OCR |
| --- | ---: | ---: | ---: |
| Selection/assembly failure with exact witness | 0 | 0 | 0 |
| Source-text mismatch: required character inventory unavailable | 2 | 0 | 2 |
| Missing source evidence | 0 | 0 | 0 |
| Unresolved attribution | 5 | 5 | 0 |
| Total mismatches | 7 | 5 | 2 |

All **29 selected atom records** are strongly supported by the reviewed merchant
regions: 22 digital and seven OCR. None is outside, boundary-sensitive or
geometrically unusable. Two cases have additional eligible unselected records,
one digital and one OCR, but those records do not establish an exact witness.
All witness-selection and witness-row flags are zero because there are no witnesses.

| Overlapping text signature | All | Digital | OCR |
| --- | ---: | ---: | ---: |
| Same words with changed order | 0 | 0 | 0 |
| Equal after deleting whitespace only | 2 | 2 | 0 |
| Equal after removing format-control characters only | 0 | 0 | 0 |

The two spacing signatures remain in the unresolved category: the measurement
does not establish whether their whitespace discrepancy originates inside source
atoms, between atoms, or in a residual reference issue. It supplies a concrete
target for a spacing experiment without changing normalization or awarding gains.

The full seed remains **17/24 exact (70.8%)**, with 24 aligned unique outputs,
two partial-text and five other mismatches. Digital remains 11/16 exact and OCR
6/8. All saved outputs and labels are unchanged. No new prediction ran.

## Interpretation and method

The seven cases were selected only after reproducing all 24 v3 scores. Each saved
output was reconstructed from its recorded proposal atoms or saved assembly order.
The diagnosis used the same 135 rows, fixed alignment, human merchant regions and
existing evidence; PDF copies supplied only identity and page geometry.

Exact witnesses were queried in strongly located atoms without strong overlap
with another reviewed merchant. The unchanged geometry/Hebrew reading-order helper
ordered each row's eligible atoms and one page-wide stream deduplicated by the
declared observation identity. Only contiguous whole-atom spans were compared,
using unchanged NFC/whitespace normalization. No character reversal, word
permutation, atom splitting, punctuation repair or label-driven candidate output
was allowed. **189 spans** were checked across the fixed streams; this includes
repeated spans present in both a row stream and the page stream.

For source-text mismatch, the reference needed more occurrences of a code point
than all nonempty strong and boundary records together supplied. Raw duplicate
records were included, making availability a generous upper bound. Both OCR
failures meet this condition. This shows insufficiency of the saved text relative
to v3, not a uniquely identified OCR recognition cause: omitted evidence or a
residual annotation error could also explain it. The five digital failures have
sufficient character inventories but no exact witness, so they remain unresolved.

The reference is a 24-case training seed reviewed twice and adjudicated by the
same person. These counts do not independently certify labels, establish population
accuracy, or replace document-disjoint validation. The error-only denominator is
seven; the unchanged accuracy denominator is 24.

## Verification

- Eleven invented-input tests pass after three red/green cycles at the diagnostic
  classification seam. They cover whole-atom spans, NFC/whitespace, no within-atom
  substring shortcuts, missing text/characters, multiplicity, raw duplicate
  availability, uncertain ordering and incomplete geometry precedence.
- All **24 baseline scores and saved output strings reproduce**, with selected
  atoms traced back to the unchanged row evidence and existing ownership/order.
- A separate checker agrees on all seven categories and text signatures, all
  streams and **189 span comparisons**, and **2,230 point-space atom checks**.
  Atom checks include the same page evidence checked against different cases.
- All category totals, support counts, witness flags, text signatures and
  unselected-evidence counts agree for the overall, digital and OCR slices.
- Eleven measurement inputs and 13 verification inputs remain unchanged, with
  overlap between these sets. All six selected source copies remain unchanged;
  the independent checker reads the five source pages containing these errors.
  The frozen deterministic checkout is unchanged.
- Private formatting, lint and strict mypy pass. Required repository gates pass:
  Ruff formatting, Ruff lint, mypy over 48 source files and **3,766 tests**.

Only aggregate documentation is tracked. Evidence, strings, regions, source
identities and case-level diagnoses remain in ignored local artifacts. No
production behavior changed, no private-corpus acceptance is claimed, and no
merge or push was performed.

## Next recommendation

Evaluate **one general geometry-based merchant spacing rule in the row-profiles
arm**, targeting the two measured spacing-only digital failures. Generate its
outputs from saved evidence without reference text, then score all 24 fixed v3
cases to detect gains and regressions. Preserve character content and abstain
where the existing geometry cannot support a spacing decision. This is a
recommendation for separate approval, not a candidate implemented by this task.

The seven-case measurement is complete. **STOP**. No further diagnostic, extractor
change, predictions, review, label update, expansion or held-out access is active.

```text
Scope: YES — quantifies seven residual merchant extraction errors against v3
Experiment: shared evaluation
Measurement: selection/assembly, source-text, missing-evidence and unresolved error counts
Result: 0 exact-witness selection/assembly failures, 2 OCR source-text mismatches, 0 missing-evidence cases, 5 unresolved digital cases including 2 spacing-only signatures; bounded witness hypothesis falsified; score unchanged at 17/24
Next extraction task: STOP
```
