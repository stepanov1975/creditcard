# Fully Reviewed Merchant Reference v3 Report

**Status:** COMPLETE — STOP. Measured on 2026-09-19.

**Authority:** The user's “proceed” approved the completed remaining-adjudication
report's recommendation. The
[design](../superpowers/specs/2026-09-19-merchant-reference-v3-design.md) and charter
allowance were committed at `c8afa7d` before private materialization.

## Result

The fully reviewed v3 training reference is complete. The unchanged saved outputs
remain **17/24 exact (70.8%)**, with **zero gains, zero losses and zero changed
assignments** relative to v2. All 24 cases retain alignment and unique outputs.

| Fixed scoring view | Exact merchants | Aligned | Unique output | Partial text | Other mismatch |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 text and v2 alignment | 17/24 | 24/24 | 24/24 | 2 | 5 |
| V3 text, fixed v2 alignment | 17/24 | 24/24 | 24/24 | 2 | 5 |
| V3 text, recomputed alignment | 17/24 | 24/24 | 24/24 | 2 | 5 |

Every view has zero alignment failures, omissions, ambiguous outputs and extra
text. In every paired comparison, 17 exact, two partial-text and five other-
mismatch categories remain unchanged. Both consecutive comparisons and the total
comparison have zero gains and losses.

| Source mode | V2 exact | V3 text, fixed alignment | V3 text, recomputed alignment | Partial text | Other mismatch |
| --- | ---: | ---: | ---: | ---: | ---: |
| Digital | 11/16 | 11/16 | 11/16 | 1 | 4 |
| OCR | 6/8 | 6/8 | 6/8 | 1 | 1 |

Each slice retains full alignment and unique-output coverage, with no assignment
changes or paired gains/losses. The predeclared hypothesis that corrected text
or regions change at least one exact/nonexact outcome is **falsified**. This
zero score effect does not negate the additional review: v3 now incorporates all
human decisions and records the completed review depth.

Attribution follows the declared text-first order. No extraction, assembly,
classification, OCR, discovery, rendering or model call ran; no extractor improved.

## Reference and review depth

The separate private `artifacts/merchant-gold-seed-v3/human-reference.jsonl`
incorporates the four remaining confirmed, source-checked decisions with reasons.
Only merchant text and merchant/transaction region fields may change in those
records. The other **20 v2 record lines remain byte-identical**. All 24 case
identities, order, document/page membership, training split and other fields are
preserved. Original seed-version, note and review metadata retain their original
meaning; the directory identifies v3 and its README explains that distinction.

No normalized merchant text changes relative to v2. One merchant-region set
and four transaction-region sets change. These region changes produce no changed
assignments under the unchanged matcher.

The simple private review-depth mapping now records:

- **14 agreeing repeat readings**, with matching normalized text and region sets.
- **Ten source adjudications** covering all changed readings or regions.
- **Zero single readings** remaining.

The earlier 11-case and remaining 13-case repeat audits partition all 24 cases.
Their six-case and four-case adjudication sets are disjoint and cover exactly
their disagreements. All ten decisions pass their existing worksheet contracts.
The four new decisions are projected with the existing tested helper. V1, v2,
older review-depth snapshots and all human submissions remain unchanged.

“Fully reviewed” describes completed second readings and disagreement resolution
by the **same reviewer**. The sample contains 24 cases from six training documents,
including 16 digital and eight OCR cases. It is a calibration seed, not independent
semantic certification, a held-out benchmark or a population-accuracy estimate.
The seven residual scorer mismatches are not yet diagnoses of extraction mechanisms.

## Verification

- Reproduced all **24 saved v2 assignments and scores** using the same 127 original
  rows, eight diagnostic rows and saved assembly outputs.
- Reused the unchanged projection helper; all **nine existing invented-input
  projection tests pass**. No new production behavior was introduced.
- Checked all 24 repeat-text comparisons and 48 repeat-region comparisons against
  the saved audits, the two audit partitions, all adjudication mappings and the
  complete v2 projection before writing v3.
- Independent checks confirm four projections, 20 unchanged lines, all 24 metadata,
  membership and review-depth assignments, and all 14 agreeing repeats.
- An independent computation in PDF point coordinates agrees with **48 assignments**
  across v2 and v3; all 1,719 row/atom boxes are valid. PDFs were read only for
  identity and page geometry.
- A separately expressed scorer agrees on **72 case outcomes**, category counts,
  transitions, paired gains/losses and assignment changes in all three source slices.
- Preserved 18 projection inputs, 16 comparison inputs and 20 verification inputs
  (overlapping sets), all six source copies and the frozen deterministic checkout.
- Private Python formatting, lint and strict mypy pass. Repository verification
  passes: Ruff formatting (195 files), Ruff lint, mypy (48 source files) and
  **3,766 tests**. No tracked production code changed; this is not private-corpus
  acceptance. No merge or push was performed.

All reference contents, source identities, regions, merchant strings and case
outcomes remain in ignored local paths. Only aggregate documentation is tracked.

## Next recommendation

Quantify the **seven residual merchant mismatches against v3 using the saved
source evidence**, distinguishing missing or incorrect source text from selection
or assembly errors, and retaining an unresolved category when attribution is not
supported. That bounded error count can identify the next extractor experiment.
The recommendation is not executed or authorized by this completed comparison.

The fixed comparison is complete. **STOP**. No new predictions, tuning, sample
expansion, further review, held-out access, gold promotion or integration is active.

```text
Scope: YES — measures unchanged saved merchant extraction against the completed human review
Experiment: shared evaluation
Measurement: exact merchant match, alignment coverage, unique-output coverage, and paired gains/losses
Result: 17/24 exact in all three views; zero gains/losses or assignment changes; 24/24 aligned and uniquely emitted; reference-update hypothesis falsified
Next extraction task: STOP
```
