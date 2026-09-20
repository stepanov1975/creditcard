# Merchant LTR Block-Ordering Candidate

**Status:** COMPLETE — STOP. No owner group is reordered; exact matches remain
19/24 with zero gains or losses. The hypothesis is falsified. See the
[report](../../experiments/row-extraction-merchant-ltr-block-order-report.md).

The user's “proceed” approves the completed corrected-block witness report's
recommendation to test source-only horizontal ordering while retaining glyph
correction. Reference-matching permutations from that diagnostic are excluded
from candidate generation.

```text
Scope answer: YES — tests whether geometric block ordering improves merchant extraction
Experiment: row-profiles
Extraction hypothesis: Horizontal ordering of unambiguous LTR blocks increases exact matches above 19/24 with zero losses against both saved baselines and unchanged coverage
Measurement: merchant exact matches, paired gains and losses, and aligned unique-output coverage
Fixed inputs: 135 saved training rows, 113 owner groups, 373 saved glyph decisions, existing spacing rule and 24 v3 references
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-ltr-block-order-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-ltr-block-order-report.md; artifacts/merchant-ltr-block-order-v1/**
Required output: one saved source-only candidate and measured exact-match deltas
Stop condition: stop after one generation and score, or saved-result reproduction failure; no post-score tuning, new source access, label edits or second candidate
```

## Fixed candidate

The callable seam is `order_ltr_blocks(atoms, boundaries, comparable)`, returning
text, occurrence-index order, boundary decisions and a status. Atoms carry saved
glyph-corrected text and original source geometry. The existing corrected text
and saved separator decisions reconstruct the fallback output exactly.

Apply this one rule to every saved owner group before loading references:

1. Require comparable source conventions: one document, page, render version
   and original/additional-row evidence convention across the group.
2. Require at least two atom occurrences, all digital. Every block must be
   nonempty, NFC, and contain no whitespace, mark or control-category code point.
3. Across the complete group, strong bidirectional classes must be exactly
   `{L}`. Neutral punctuation and digits may accompany LTR letters; groups with
   RTL letters, mixed strong directions or no LTR letters retain their output.
4. Reuse the existing horizontal-order guard: finite positive boxes, common
   vertical overlap of at least 0.8 of the smallest height and horizontal centers
   separated by more than 0.0001. Require adjacent boxes in the resulting order
   not to overlap horizontally. Sort by increasing horizontal center.
5. If eligibility fails or the index order is unchanged, return the saved
   corrected output and its original separators exactly. Otherwise preserve each
   occurrence and its text, and render the reordered atoms with the existing
   punctuation-aware spacing function unchanged. This re-evaluates spacing for
   new neighbors; it introduces no new spacing threshold or character repair.
6. If the resulting text is not NFC, retain the original output. Preserve every
   non-whitespace code point and occurrence multiplicity; original evidence
   objects remain unchanged.

Do not inspect source documents, glyph pages, witness orders, reference labels,
saved scores or prior case selections during generation. Read only the existing
label-free row/proposal/order artifacts and saved glyph decisions/output strings.
Reconstruct all 113 prior outputs from 373 decisions before saving one complete
candidate. Preserve row membership, ownership and output cardinality. No literal
merchant, path, hash, date, amount or document-specific predictive branch is allowed.

## Scoring and hypothesis

After saving all predictions, reproduce all 96 previous scores. Score the 24
unchanged v3 training references using the existing exact-match metric and fixed
alignment. Compare with both punctuation spacing and glyph correction: report
exact counts/rates, paired gains/losses, score transitions and unique-output
coverage for all cases, digital and OCR. Report generation eligibility/fallback
counts and how many owner orders and rendered outputs change.

The hypothesis is supported only if exact matches exceed 19/24, neither baseline
loses an exact case and aligned unique-output coverage stays 24/24. Otherwise it
is falsified; a failed saved-result reproduction stops the task without scoring
a new candidate. These are training-seed results, not validation or acceptance.

## Verification and stop

Commit authority before implementation or measurement. Use invented-input
red/green tests at the callable seam: spatial ordering, preserved corrected text
and occurrence multiplicity, unchanged output fallback, source/direction/text
eligibility, geometry ambiguity, existing spacing and normalization guards.
Add one failing behavior and its minimal implementation per cycle.

Independently replay the ordering decisions with rational geometry and check
rendered outputs, all scores and aggregate slices. Reuse the already verified
spacing behavior and saved glyph correction; do not regenerate either rule.
Check protected inputs and the frozen checkout remain unchanged. Keep private
code, predictions and logs in ignored `artifacts/merchant-ltr-block-order-v1/`;
publish aggregates only. Run all four repository gates before tracked commits.

Stop after this single candidate and its evaluation. No post-score repair,
second candidate, new sources, OCR/models, label changes, held-out data, shared
framework or production integration is authorized.
