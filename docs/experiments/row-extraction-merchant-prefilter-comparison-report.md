# Merchant Comparison Before Future-Billing Exclusion

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved this fixed comparison under the
[design](../superpowers/specs/2026-09-12-merchant-prefilter-comparison-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-prefilter-comparison.md), and charter
amendment committed at `33953e7` before private candidate generation.

## Result

Making the saved future-billing candidate evidence available to the existing
merchant rule improves exact merchant matches from **10/24 to 13/24**, with
**three gains and zero losses**. The positive-net-gain hypothesis is supported
on this fixed training seed. All four previously unmatched references now align
and have a unique description; three are exact and one remains a text mismatch.

| Metric | Saved reading-order comparator | Before future-billing filter |
| --- | ---: | ---: |
| Exact merchants | 10/24 (41.7%) | 13/24 (54.2%) |
| Aligned references | 20/24 | 24/24 |
| Unique description output | 18/24 (75.0%) | 22/24 (91.7%) |
| Alignment failures | 4 | 0 |
| Omissions | 1 | 1 |
| Ambiguous outputs | 1 | 1 |
| Partial text | 2 | 2 |
| Other text mismatches | 6 | 7 |
| Extra text | 0 | 0 |

The exact-match increase is **12.5 percentage points**. Among the 20 previously
aligned cases, outputs, assignments, and score categories are all unchanged.
The candidate retains the original 24-case denominator.

## Fixed method

Use the saved initial discovery candidates from the completed exclusion trace,
not a new discovery run. Two initial tables provide 46 ordered rows on the
one affected digital page: 38 existing rows and the eight-row table already
identified as future billing. Its singleton rediscoveries are not duplicated.

The frozen deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4` supplies pure row/column summaries,
atom projection, row identity and gap calculation, the profile classifier,
and the existing description rule. Only the eight excluded rows receive new
diagnostic inputs. Existing row records and all 127 saved predictions remain
unchanged. New rows receive predecessor/successor context from the 46-row
candidate order and no accepted baseline type.

The tight profile classifier uses `Decimal("0.50")`. It classifies all eight
new rows as primary transactions and produces eight description proposals through
the existing pre-financial-rejection probe. The fixed Hebrew/Latin reading-order
rule orders their source atoms; no geometry fallback occurs. Every selected atom
retains its saved source text, box, mode, and confidence.

All eight new diagnostic predictions remain **IGNORE** for billing and contain
only merchant-description proposals. The saved production future-billing
exclusion remains intact. No parser normalization, reconciliation, financial
acceptance, PDF reading, text extraction, OCR, discovery rerun, or model call
was performed.

References enter only after proposal generation. A separate candidate alignment
uses the unchanged geometric rule against all 46 candidate row boxes for the
four original null cases. The other 20 assignments remain fixed. The original
alignment file is preserved, including its four historical nulls.

## Slices and remaining failures

| Fixed slice | Exact before | Exact candidate | Unique output before | Unique output candidate |
| --- | ---: | ---: | ---: | ---: |
| Digital pages | 7/16 | 10/16 | 10/16 | 14/16 |
| OCR pages | 3/8 | 3/8 | 8/8 | 8/8 |
| Four previously filtered references | 0/4 | 3/4 | 0/4 | 4/4 |

The candidate leaves **11 non-exact cases**: nine text mismatches, one omission,
and one ambiguous output. Of the text mismatches, four are on digital pages and
five are on OCR pages. The omission and ambiguous output are both digital.
This comparison does not diagnose their remaining causes or judge reference
correctness from model disagreement.

## Interpretation for the reference dataset

The fixed source-reviewed seed now supports candidate alignment for all 24
cases. This confirms that separating merchant recognition from current-cycle
billing inclusion resolves the earlier geometric access problem without
removing reviewed references or changing production scope.

The candidate is the best measured merchant diagnostic at **13/24**. The
historical **10/24** comparator and all its artifacts remain preserved. The gain
comes from access to previously excluded evidence; no new recognition or
reading-order rule was introduced. It does not establish that recognition quality
improved on previously accessible rows, or that all printed transactions should
be included in the financial output.

This is one saved-page evidence extension alongside unchanged predictions for
the other cases, not a uniform rerun of the full production parser. It is not a
new frozen-arm ranking, a validation result, a held-out result, or a population
accuracy estimate. The 24 references remain a small training calibration set
reviewed by one human; this experiment does not independently certify them as gold.

## Validation and artifacts

Eight invented-input tests reached the expected stub failures before the adapter
was implemented and now pass. They cover source-evidence preservation, duplicate
and missing-row rejection, page isolation, primary/continuation ownership,
orphan ambiguity, typed residuals, and retaining billing exclusion. The private
three-file implementation passes Ruff formatting, lint, and strict mypy.

Independent NFC/whitespace equality checks agree on all 48 before/after exact-match
outcomes and the three gains with zero losses. An independent PyMuPDF rectangle
calculation agrees with all four candidate assignments. The combined prediction
file has the original prediction bytes as its unchanged prefix, followed only
by eight excluded merchant diagnostics. All 14 protected original files remain
byte-identical, and the frozen checkout is unchanged.

Required repository verification passes: Ruff format/check, mypy on 48 source
files, and **3,766 tests passed** in 100.30 seconds.
No production code changed. This is not private-corpus verification or production
acceptance; no merge was performed.

Private candidate rows, predictions, diagnostic alignment, case scores, and
verification records remain under ignored
`artifacts/merchant-prefilter-comparison-v1/`. No private text, identities,
coordinates, source images, or financial values are published or committed.

## Stop and next recommendation

The single comparison is complete. **STOP** under this authorization. The next
recommended extraction task is a bounded error analysis of the 11 remaining
non-exact cases against the existing human-marked merchant regions, distinguishing
text errors from evidence selection and ownership problems before choosing the
next extraction change. No new labels or sample expansion are required for that
analysis. It has not begun.

```text
Scope: YES — measures merchant recognition before future-billing exclusion
Experiment: row-profiles
Measurement: exact merchant match, coverage, and paired gains/losses
Result: 13/24 versus 10/24; 3 gains, 0 losses; coverage 22/24; hypothesis supported
Next extraction task: STOP
```
