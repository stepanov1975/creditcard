# Merchant Unchanged-Order Spacing Candidate

**Status:** COMPLETE — STOP. Exact matches increased from 19/24 to 21/24,
with two gains, zero losses against four baselines and unchanged 24/24 coverage.
The hypothesis is supported. See the
[report](../../experiments/row-extraction-merchant-unchanged-order-spacing-report.md).

The user's “proceed” approves the latest corrected-spacing diagnostic's
recommendation: use the existing tolerance-aware renderer for eligible groups
regardless of whether their occurrence order changes. This approves only this
candidate, not a new dataset, another diagnostic chain or production integration.

```text
Scope answer: YES — tests whether rendering unchanged-order eligible groups improves merchant extraction
Experiment: row-profiles
Extraction hypothesis: Applying the existing tolerance-aware renderer regardless of order change increases exact merchant matches above 19/24 with zero losses and unchanged coverage
Measurement: merchant exact matches, paired gains/losses, aligned unique-output coverage, and changed-output counts
Fixed inputs: 135 saved training rows, 113 owner groups, 373 saved glyph decisions, four saved native pages, and 24 v3 references
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-unchanged-order-spacing-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-unchanged-order-spacing-report.md; artifacts/merchant-unchanged-order-spacing-v1/**
Required output: one saved source-only candidate and measured exact-match deltas
Stop condition: stop after one generation and score, or saved-result reproduction failure; no post-score tuning, second candidate, new labels, validation access, or production integration
```

## Fixed rule and test seam

Use the existing callable shape `(original, corrected, keys, boundaries,
comparable, page) -> OrderedText`. Test this rendering seam with invented source
atoms and native evidence. It is the same source-only seam as the approved
[tolerance candidate](2026-09-20-merchant-ltr-tolerance-design.md).

Apply the following rule to all 113 owner groups, with no reviewed-case selection:

1. Preserve the existing multiple-occurrence, digital-source, source-convention,
   NFC/text, LTR and line/center eligibility guards and exact saved-output
   fallbacks. Preserve saved glyph correction, ownership, occurrence identities
   and output cardinality.
2. Admit `unchanged_order` alongside `overlapping_blocks` and `reordered` to the
   existing source-evidence check. Require consistent strict left/center/right
   order at the existing 0.0001 tolerance, unique native-word matching and exact
   glyph inventories, distinct keys/native words, and disjoint glyph indices.
   Original atoms determine native matching; corrected atoms provide output text.
3. Require each increasing-order adjacent gap to be at least -0.0001. Preserve
   the saved output for any source/geometry failure. Do not change a box or fit
   any threshold to reference values.
4. Apply the existing punctuation-aware renderer and tolerance substitutions
   to every eligible group, including identity order. Negative gaps in
   [-0.0001, 0) join only where the existing rule returned `overlap_or_order` or
   `punctuation_overlap_or_order`; all other separator decisions stay unchanged.
   Positive-gap behavior and unresolved punctuation direction stay unchanged.
5. Preserve the saved output if the result is not NFC. Otherwise return the
   rendered text with original occurrence identities, recording whether order
   changed separately from whether text changed. No within-atom edit beyond the
   previously saved glyph correction is allowed.

The only intended extraction change is removing the unchanged-order bypass.
Source guards now apply to newly admitted identity-order groups as well. Keep
private code small by reusing existing loaders, metrics and rendering primitives;
do not change historical scripts or construct a reusable framework.

## Generation and scoring

Commit this authority before implementing or measuring the candidate. Preserve
and commit the preceding documentation cleanup separately. Before generation,
reconstruct all 113 glyph outputs from 373 saved decisions. The generation process
may read only saved label-free evidence/order inputs and the four saved native
pages; it must not read labels, scores, reviewed membership or ordering witnesses.
Save all candidate outputs before loading any references. Do not reopen PDFs or
run OCR, models or native extraction.

Then reproduce all 144 saved score records, including the tolerance candidate's
24 scores, against fixed training-only v3 references and alignment. A mismatch
stops this task without a new score. Score the 24 unchanged references once,
comparing punctuation spacing, glyph correction, strict block ordering and
LTR tolerance. Report exact matches, paired gains/losses, category transitions,
changed outputs and aligned unique-output coverage for all/digital/OCR slices.
Also report eligible/rendered owners, reordered owners, changed owner outputs,
separator decisions and tolerance joins across the complete candidate.

The hypothesis is supported only if exact matches exceed 19/24, no baseline
loses an exact case, and aligned unique-output coverage remains 24/24. Otherwise
it is falsified. This is a repeatedly inspected training seed, not validation
accuracy or a population estimate.

## Verification and stop

Observe focused synthetic test failures before the change. Cover unchanged-order
positive/negative gaps, punctuation, the inclusive tolerance boundary, excessive
overlap, missing/ambiguous/shared source evidence, eligibility fallbacks, retained
glyph corrections and repeated occurrences, and NFC fallback. Reuse existing
changed-order regressions. Independently replay source ordering and tolerance
arithmetic and all candidate outputs; independently normalize/score every saved
record and check each aggregate slice. Sharing the existing unchanged spacing
primitive is allowed and must be disclosed.

Keep code, logs, predictions and case scores under ignored
`artifacts/merchant-unchanged-order-spacing-v1/`; publish aggregates only. Verify
saved inputs and the frozen deterministic checkout remain unchanged. Run private
format/lint/type checks and all four repository gates before tracked commits.
Stop after the single comparison, even if it succeeds. No post-score tuning,
second candidate, new labels, sample expansion, validation/held-out access,
shared infrastructure or production integration is authorized.
