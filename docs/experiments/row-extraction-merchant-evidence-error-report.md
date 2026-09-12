# Merchant Evidence Error Analysis

**Date:** 2026-09-12
**Status:** `COMPLETE — STOP`

All ten fixed mismatches had their selected evidence inside the human-marked
merchant regions under the predeclared support rule: **30 strongly supported atom
records, zero outside atoms, and zero boundary-sensitive atoms**. The hypothesis
that at least one mismatch contained wholly outside selected evidence is
**falsified for these ten cases**.

Two mismatches contain the expected words in a different order. Neither spacing
nor invisible format-control characters alone explains any mismatch. The result
points toward text ordering and other text/evidence issues within the marked
regions, rather than an observed selection of wholly unrelated regions. It does
not independently certify the human boxes or prove every merchant span complete.

The [design](../superpowers/specs/2026-09-12-merchant-evidence-error-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-evidence-errors.md), and charter
amendment were committed at `a2f24b7` before private measurement.

## Fixed inputs

The selection contains exactly the ten saved nonmatching descriptions from the
[pre-rejection measurement](row-extraction-merchant-pre-rejection-report.md): one
partial-text mismatch and nine other mismatches. Five are from OCR pages and five
from digital-only pages. Case identities were saved before region/text analysis.

The eight exact cases, one ambiguous output, one row-type omission, and four
alignment failures were excluded from this error-only analysis. This is not a
new accuracy denominator. The existing pre-rejection result remains **8/24 exact**.

Each selected case resolved to exactly one unchanged description proposal with
the same rendered text and owner as its saved output. The analysis used its
declared atom records, the original frozen source row, the human merchant region,
and dimensions/rotation from the identity-matched local source PDF. No source
page was rendered, no new text was extracted, and no extractor or OCR was rerun.

## Evidence-location results

Strong support required the atom center to lie in a human merchant region and at
least 50% of the atom's area to intersect one such region. Overlapping regions
were not summed. Outside meant zero positive-area intersection with every region.

| Measurement | Result |
| --- | ---: |
| Cases with all selected atoms strongly supported | 10/10 |
| Strongly supported selected atom records | 30/30 |
| Cases with wholly outside selected evidence | 0 |
| Boundary-sensitive selected atom records | 0 |
| Unusable selected geometry | 0 |
| Evidence from a different source page | 0 |
| Cases with additional unselected strongly supported atom records | 2 |
| Additional unselected strongly supported atom records | 4 |

One digital-page case has three unselected in-region records; one OCR-page case
has one. These counts concern the proposal's own frozen source row only. They
are possible missing evidence, not confirmed omitted words: overlapping or
duplicate records can represent the same printed content. No alternative
prediction was generated from them.

| Page mode | Cases | Strong selected atoms | Unselected in-region records |
| --- | ---: | ---: | ---: |
| Digital-only | 5 | 16 | 3 |
| OCR | 5 | 14 | 1 |

## Text results

All diagnostics use the existing NFC and whitespace normalization. The saved
strings, exact-match scores, and evidence order remain unchanged.

| Diagnostic signature | Cases |
| --- | ---: |
| Same token multiset, different word order | 2 |
| Equal after deleting whitespace only | 0 |
| Equal after removing Unicode format-control characters only | 0 |

Both word-order cases are on digital-only pages. They already contain the
reference words with identical multiplicities; the sequence differs. The other
eight mismatches are not explained by these three signatures. Region support
alone cannot distinguish character recognition, internal character order,
segmentation, duplicated evidence, or reference transcription differences.

| Error-only slice | Character edits | Reference code points | Character error rate |
| --- | ---: | ---: | ---: |
| Ten mismatches | 113 | 174 | 64.94% |
| Five digital-page mismatches | 55 | 81 | 67.90% |
| Five OCR-page mismatches | 58 | 93 | 62.37% |

Rates are summed Levenshtein edits divided by summed normalized reference code
points. They are conditional on these already-failing cases; they do not measure
character error rate across the full seed or production corpus.

## Recommended next extraction task

Test a **general reading-order rule for Hebrew/Latin evidence tokens** using the
same frozen merchant evidence and all 24 references. The two measured word-order
failures provide a concrete target. Score all cases to detect regressions in the
eight existing exact matches; do not reorder words by consulting expected text.

This is a recommendation for a separately approved phase. No reading-order fix,
label change, sample expansion, validation/test access, or production integration
has been started. The two cases with unselected evidence and other unexplained
text mismatches remain recorded; they do not authorize additional work here.

## Verification and limits

All four repository gates passed: Ruff formatting, Ruff lint, mypy over `src`,
and 3,766 repository tests. These are tracked checks, not private-corpus acceptance.

Thirteen invented-input tests passed after the initial run failed because the
analysis module did not yet exist. They cover geometry support and boundary rules,
invalid boxes, overlapping regions, category precedence, text signatures, and edit
distance. Ruff and strict mypy passed for both private files, with two narrowly
documented PyMuPDF constructor typing limitations.

Independent local verification used PDF rectangle intersection operations to
check all 30 selected atoms and a full edit-distance matrix to check all ten
text comparisons. It confirmed selection membership, support, text signatures,
and the 113/174 character-error calculation. All original input artifact bytes
and user-answer bytes remained unchanged.

Private identities, evidence, text, and case diagnostics remain local and ignored.
No private text or pixels entered model tools, external services, or Git. The
reference remains a single-human-review calibration candidate, with no independent
semantic source audit. No production behavior changed and no private-corpus
acceptance is claimed.

```text
Scope: YES — quantified remaining merchant errors against human-marked evidence
Experiment: row-profiles
Measurement: merchant-region support, unselected in-region evidence, text signatures, and character error rate
Result: 10/10 cases have strongly supported selected evidence; 0 outside atoms falsify the outside-selection hypothesis; 2 word-order signatures; 4 unselected in-region records across 2 cases
Next extraction task: STOP
```
