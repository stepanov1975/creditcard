# Merchant LTR Tolerance Candidate

**Status:** APPROVED — generation pending.

The user's “proceed” approves the overlap report's recommendation to test the
existing coordinate tolerance consistently in block ordering and spacing.

```text
Scope answer: YES — tests whether consistent geometry tolerance improves merchant extraction
Experiment: row-profiles
Extraction hypothesis: Tolerance-aware LTR ordering and spacing increases exact matches above 19/24 with zero losses against the saved baselines and unchanged coverage
Measurement: merchant exact matches, paired gains/losses and aligned unique-output coverage
Fixed inputs: 135 saved training rows, 113 owner groups, 373 saved glyph decisions, four saved native pages and 24 v3 references
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-ltr-tolerance-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-ltr-tolerance-report.md; artifacts/merchant-ltr-tolerance-v1/**
Required output: one saved source-only candidate and measured exact-match deltas
Stop condition: stop after one generation and score or saved-result reproduction failure; no post-score tuning, second candidate, new extraction or label changes
```

## Fixed rule

The callable seam is `order_with_tolerance(original, corrected, keys, boundaries,
comparable, page)`. It returns the existing ordered-text result shape: text,
occurrence-index order, separator decisions and a status. `original` provides
unaltered source atoms; `corrected` differs only in the previously saved glyph
text. Keys identify occurrences; labels and saved witness orders are not inputs.

Apply the same rule to all 113 saved owner groups:

1. Reuse the previous candidate's source-convention, multiple-occurrence, digital,
   text, LTR and common-line/center guards. Preserve its exact fallback for these
   failures and for already ordered groups. Retain all corrected atom text,
   identities, ownership and output cardinality.
2. For groups previously blocked by overlap or otherwise requiring reordering,
   recompute the source-only overlap diagnostic from original atoms and saved
   native evidence. Require `consistent_source_order`: strict left-edge, center
   and right-edge orders agree using the existing 0.0001 tie tolerance; native
   words match uniquely; glyph inventories match; no atom/native-word identity
   repeats and no glyph indices are shared within the group. Any unresolved or
   conflicting evidence preserves the saved glyph output. If the resulting order
   is unchanged, preserve that output exactly.
3. In increasing horizontal order, require every adjacent gap to be at least
   **-0.0001**, computed from the saved decimal coordinate representations.
   A more negative gap preserves the saved output. This is the existing source
   matching/ordering tolerance, not a fitted overlap-ratio threshold.
4. Render changed-order groups with the existing punctuation-aware spacing rule.
   For a negative gap in **[-0.0001, 0)** only, replace `overlap_or_order` with a
   joined separator, and `punctuation_overlap_or_order` with a punctuation-joined
   separator. These statuses already establish the relevant direction, source,
   line and punctuation conditions. Mark replacements with distinct tolerance
   decision codes. Leave every other separator decision unchanged, including
   positive gaps and unresolved punctuation direction. Do not change any box.
5. Preserve the saved output if the newly assembled string is not NFC. Otherwise
   return the reordered string, with every occurrence and non-whitespace code
   point retained. No within-atom edit beyond saved glyph correction is allowed.

Original native-word matching uses original text, while new output assembly uses
the saved corrected text. Retain the earlier glyph correction without reopening
PDFs or recomputing it. The source-only diagnostic function may be reused, but
its saved group measurements, witness orders, reviewed membership and labels
must not be read during generation.

## Generation and measurement

Commit authority before implementation. Reconstruct all 113 saved glyph outputs
from 373 decisions. Load only the saved native-page snapshots and label-free
evidence/order artifacts. Save the complete candidate before reading references
or saved scores. No new source extraction, OCR or model calls are allowed.

Then reproduce all **120** prior scores and score the unchanged **24** reviewed
v3 training references with fixed alignment and the existing metric. Compare
against punctuation spacing, glyph correction and the strict block-order
candidate. Report exact counts/rates, paired gains/losses, transitions, changed
outputs and coverage for all cases, digital and OCR. Report candidate eligibility,
reordered-owner, changed-output and tolerance-join counts.

The hypothesis is supported only if exact matches exceed 19/24, no saved baseline
loses an exact case, and aligned unique-output coverage remains 24/24. Otherwise
it is falsified. Reproduction failure stops the task without a new score. This
training-seed experiment makes no validation or corpus-acceptance claim.

## Verification and stop

Use invented-input red/green tests at the candidate seam for tiny negative gaps,
the inclusive tolerance boundary, excessive overlap, existing spacing behavior,
exact fallbacks, strict order, independent native evidence, saved glyph text and
normalization. Independently replay ordering and separator decisions with separate
arithmetic/source checks, and verify all outputs, scores and aggregate slices.

Keep disposable code, outputs and logs in ignored
`artifacts/merchant-ltr-tolerance-v1/`; publish aggregates only. Check old inputs
and the frozen checkout remain unchanged and run all four repository gates before
tracked commits. Stop after the one candidate and its evaluation. No post-score
repair, second candidate, label change, held-out access, shared framework or
production integration is active.
