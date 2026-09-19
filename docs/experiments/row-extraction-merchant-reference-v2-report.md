# Adjudicated Merchant Reference v2 Report

**Status:** COMPLETE — STOP. Measured on 2026-09-19.

**Authority:** The user's “proceed” approves the preceding recommendation to
create a separate 24-case adjudicated training reference and rescore the same
saved outputs. The [design](../superpowers/specs/2026-09-19-merchant-reference-v2-design.md)
and charter allowance were committed at `87a9c69` before materialization.

## Result

The unchanged saved extraction outputs match **17/24 v2 references (70.8%)**,
versus **13/24 original references (54.2%)**. There are **four paired gains and
zero losses**, a change of **16.7 percentage points**. All four gains come from
corrected merchant reference text. Reapplying the unchanged matcher with the
corrected regions changes **zero assignments and zero outcomes**.

| Fixed scoring view | Exact merchants | Aligned | Unique output | Partial text | Other mismatch |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original text and original alignment | 13/24 | 24/24 | 24/24 | 2 | 9 |
| V2 text, original alignment | 17/24 | 24/24 | 24/24 | 2 | 5 |
| V2 text, recomputed alignment | 17/24 | 24/24 | 24/24 | 2 | 5 |

All three views have zero alignment failures, omissions, ambiguous outputs, and
extra-text cases. Four original `other_mismatch` cases become exact; the other
20 categories remain unchanged. The final seven mismatches comprise two partial
texts and five other mismatches. These are scorer categories, not diagnoses of
extraction mechanisms or independently proven reference correctness.

| Source mode | Original exact | V2 exact, fixed alignment | V2 exact, recomputed alignment | Text gains / losses | Alignment gains / losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Digital | 10/16 | 11/16 | 11/16 | 1 / 0 | 0 / 0 |
| OCR | 3/8 | 6/8 | 6/8 | 3 / 0 | 0 / 0 |

Digital cases retain one partial text and four other mismatches; OCR cases
retain one partial text and one other mismatch. Both slices retain full
alignment and unique-output coverage, with zero changed assignments.

The predeclared reference-update hypothesis is **supported**: at least one
exact/nonexact outcome changes between consecutive fixed views. This measures
a correction to the reference used for evaluation, not improved extraction.
Text-first then alignment attribution follows the declared order; it is not
an independent causal estimate. No extraction, assembly, OCR, model, or new
prediction ran.

## Separate reference version

The new private `artifacts/merchant-gold-seed-v2/human-reference.jsonl` uses the
existing reference shape. It preserves all 24 case identities, order, source
documents, pages, training membership, and non-reference fields. Six adjudicated
records receive the final merchant text and merchant/transaction regions;
the other **18 original record lines are preserved byte for byte**.

All six decisions pass the existing worksheet contract and are confirmed
present, source-checked, and accompanied by a reason. Four cases have changed
merchant text, and five have changed merchant and transaction region sets;
their union is the six projected records. Human text is copied without
normalization; only scoring uses the unchanged NFC/whitespace normalization.

A private case-to-review-depth mapping records **13 single readings, five
agreeing repeat readings with unchanged regions, and six source adjudications**.
Original metadata, including the original seed-version field and notes, remains
origin metadata; the accompanying README explains that distinction. The final
human reasons and all three answer submissions remain in their existing
separate private locations. No original reference or answer file is overwritten.

This is a same-reviewer training calibration seed. Repeat review was selected
from the original extraction disagreements; the 13 originally matching cases
have only one reading. The dataset therefore is not independently certified
gold, a held-out benchmark, or evidence of general production accuracy.

## Verification

- All **24 original assignments and scores reproduce** before the new score is
  reported, using exactly 127 original rows plus eight saved diagnostic rows and
  the unchanged assembly outputs.
- Nine invented-input tests failed at the unimplemented projection and then
  passed. They check metadata preservation, exact human-text copying, isolation
  from input mutation, and rejection of incomplete decisions or missing regions.
- Independent projection checks confirm all six decisions, 18 byte-identical
  records, 24 metadata/membership checks, and all 24 review-depth assignments.
- An independent computation in PDF point coordinates agrees with **48
  assignments** across both reference versions. All 1,719 row/atom boxes are
  valid. Source PDFs are read only for identity and page geometry.
- A separately expressed scorer agrees with **all 72 case categories and exact
  outcomes**, category totals and paired gains/losses in all three source slices.
- Input checks preserve nine projection inputs, 13 comparison inputs, and 14
  verification inputs, with overlap between those sets. All six source copies
  and the frozen deterministic checkout remain unchanged.
- Private Python formatting, lint, and strict mypy checks pass. Required
  repository checks pass: Ruff formatting (195 files), Ruff lint, mypy (48 source
  files), and **3,766 tests in 99.12 seconds**. No tracked production behavior
  changed. This is not private-corpus acceptance.

All source identities, regions, merchant strings, case outcomes, and dataset
files remain under ignored local paths. Only aggregate documentation is tracked.
No merge or push was performed.

## Next recommendation

The next useful gold-quality task is a **blind second reading of the remaining
13 single-read training cases**, with prior answers and model outputs hidden.
This would measure repeat consistency beyond cases selected for extraction
disagreement. It would still be the same reviewer's evidence, not independent
semantic certification. This recommendation is not executed or authorized by
the completed comparison; no new review worksheet was created.

The fixed three-view comparison is complete. **STOP**. No new predictions,
tuning, sample expansion, held-out access, accepted-gold promotion, or production
integration is authorized.

```text
Scope: YES — measures unchanged saved merchant outputs against adjudicated references
Experiment: shared evaluation
Measurement: exact merchant match, alignment coverage, unique-output coverage, and paired gains/losses
Result: 13/24 to 17/24 exact; four text-reference gains, zero losses; zero alignment changes; 24/24 aligned and uniquely emitted; reference-update hypothesis supported
Next extraction task: STOP
```
