# Merchant Reading-Order Experiment

**Status:** Approved by the user's “proceed” on 2026-09-12, following the concrete
recommendation to test general Hebrew/Latin reading order on the existing evidence.
Commit this design and charter amendment before private candidate execution.

```text
Scope answer: YES — tests whether reading order improves extracted merchant text
Experiment: row-profiles
Extraction hypothesis: Direction-aware ordering adds at least two exact merchant matches with zero losses
Measurement: merchant exact matches, paired gains/losses, coverage, and word-order errors resolved
Fixed inputs: 24 human references, saved alignment, 127 frozen rows and pre-rejection predictions
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-reading-order-design.md; docs/superpowers/plans/2026-09-12-merchant-reading-order.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-reading-order-report.md; artifacts/merchant-reading-order-v1/**
Required output: paired accuracy delta and hypothesis result
Stop condition: stop after this fixed comparison, without tuning against the answers
```

## Fixed population and comparator

Use all 24 human-reviewed training references, the unchanged 20 matched owners
and four alignment failures, the 127 saved selected-page observations, and all
127 saved pre-rejection predictions. The comparator is the completed diagnostic
pre-rejection extraction: 8/24 exact matches and 18/24 unique descriptions.
Reproduce its saved case scores before comparing the candidate. This is diagnostic
merchant extraction; the original transaction decisions remain unchanged.

The evidence analysis found two digital-page mismatches with the correct token
multiset in a different order. Count how many of those two become exact, while
measuring gains and losses across all 24 cases. Do not select only the two cases
for candidate application, or consult references to choose an ordering.

## One fixed candidate

Implement only the directional-run ordering portion of the frozen parser's
`layout/text.py` lossless word renderer, adapted to existing evidence atoms.
Do not carry over its deduplication or numeric-text repair. Apply it independently
to each DESCRIPTION proposal, preserving the exact atom-ID multiset, atom text,
evidence records, proposal ownership, region, score, classification, decision,
and reasons. Other field proposals are unchanged. Never merge proposals, reverse
characters inside an atom, split atoms, or accept a previously rejected row.

Use the frozen atom boxes without new source reads or coordinate reconstruction:

1. If any selected box is nonfinite or has nonpositive width/height, retain the
   entire proposal's original order and count a geometry fallback.
2. Visit atoms by vertical center, then left edge, then original proposal position.
   Assign each to the nearest existing line center within 0.6 times the larger of
   the atom/line heights, inclusively. Keep the first created line for equal
   distances. Extend the line box by union after assignment. Read lines in ascending
   top edge, with stable creation order for ties.
3. Within a line, count Unicode bidirectional classes R/AL versus L over all
   selected text. Strict RTL majority gives RTL base direction; otherwise LTR.
   Sort atoms by horizontal center, stably retaining original proposal position
   for identical centers.
4. Infer each atom's direction by the same strict R/AL versus L majority. A tie
   with EN/AN digits is LTR; otherwise it is neutral. Neutral atoms inherit the
   preceding physical run's direction, or the line base direction at line start.
5. Form contiguous same-direction runs in physical left-to-right order. Visit
   runs in reverse for an RTL base, forward for LTR. Visit atoms within RTL runs
   right-to-left, and within LTR runs left-to-right. Keep each atom's internal text
   exactly as saved. Render with the existing proposal renderer and scorer.

This is one deterministic hypothesis, not a full Unicode bidi implementation.
No sweep, alternative candidate, label-based fallback, source-specific branch,
new model, OCR call, dependency, or production change is authorized.

## Measurement and stop

Report normalized merchant exact matches on all 24 cases and the 20 aligned
cases, paired exact-match gains/losses, OCR/digital slices, unique-description
coverage, omission/ambiguity/alignment counts, and the two previously identified
word-order cases resolved. Record proposal-order changes and geometry fallbacks.
Use the existing NFC/whitespace scorer and Decimal rates without tolerance changes.
The hypothesis is supported only with at least two gains and zero losses;
otherwise it is falsified on this fixed seed. A failed required input binding
ends the run without a replacement task.

Write the disposable candidate, invented-input tests, and private predictions
only under ignored `artifacts/merchant-reading-order-v1/`. Verify permutation-only
changes, reproduce the baseline, and independently verify aggregate scoring.
Publish aggregate results only. Source identities, labels, predictions and other
private data remain local and out of Git and external model tools.

Stop after one scored comparison. The training seed has one human reviewer and
has already informed this hypothesis; its result is calibration evidence, not
independent generalization, gold promotion, validation, or corpus acceptance.
No sample expansion, validation/test access, or production integration is allowed.
