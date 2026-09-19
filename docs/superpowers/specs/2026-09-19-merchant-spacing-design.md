# Merchant Geometry Spacing Experiment

**Status:** APPROVED — preparing one fixed candidate.

The user's “proceed” approves the completed v3 error analysis's recommendation
to test one general merchant spacing rule on all 24 fixed training cases.

```text
Scope answer: YES — tests a general merchant spacing change in the row-profiles extractor
Experiment: row-profiles
Extraction hypothesis: Geometry-based spacing increases exact merchant matches without losing any of the 17 existing matches
Measurement: exact merchant match, paired gains/losses, alignment coverage, unique-output coverage, and spacing-only error count
Fixed inputs: 24 v3 training references, 135 saved rows/proposals, recorded atom selections/order, fixed alignment, and assembly outputs
Smallest allowed files: docs/superpowers/specs/2026-09-19-merchant-spacing-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-spacing-report.md; artifacts/merchant-spacing-v1/**
Required output: one runnable spacing candidate and its fixed 24-case metric delta
Stop condition: stop after one predeclared candidate comparison or baseline reproduction failure; no threshold tuning, label changes, expansion, or production integration
```

## Single predeclared rule

Implement a disposable row-profiles merchant renderer over already selected atoms
in their recorded order. Its public test seam accepts that ordered atom sequence
and returns rendered text plus boundary decisions. It has no reference, case,
merchant identity, filename, amount, date, document identity or diagnostic inputs.

The baseline joins selected atom strings with one ASCII space. Remove that inserted
separator only when every condition below holds:

- Both boxes are finite with positive width/height and both atom texts are nonempty.
- Neither the previous atom's final character nor the next atom's initial character
  is whitespace; explicit whitespace within or at the edges of atoms is preserved.
- The two touching text-edge characters are letters with the same Unicode strong
  direction: `L` for left-to-right, or `R`/`AL` for right-to-left. Other boundaries
  retain their separator, including digits, punctuation and mixed directions.
- The atoms have the same evidence-source kind and at least 80% vertical overlap
  relative to the smaller height.
- Their horizontal boxes follow that letter direction in the saved text order,
  with a nonnegative gap (overlapping boxes abstain).
- The gap is at most **0.20 times the smaller estimated character width**. Estimate
  each width as its box width divided by the number of non-whitespace code points
  whose Unicode category is neither Mark nor Other. Require a positive count.

These are fixed conservative heuristic thresholds, not calibrated estimates.
Do not sweep or adjust them after seeing private results. Preserve every source
character, including whitespace within atoms, and all selected atom identities,
order, ownership and output multiplicity. Uncertain boundaries retain the baseline
separator. This abstains from a spacing change, not from emitting the saved output.
No within-atom editing, character splitting, glyph inference, new OCR or PDF text
extraction is allowed. This rule may leave both targeted spacing signatures unsolved.

## Generation before scoring

Commit authority before private generation. Read only the 127 original rows, eight
additional rows, saved proposals, baseline assembly outputs/statuses and recorded
assembled order while generating the candidate. Do not read references, region
labels, case identities, alignment, source pages or prior case diagnoses at this
stage. Apply the rule to every comparable unique-output owner group, not just the
reviewed cases. Require selected source rows to share document, page and render
version; cross-row evidence also must use the same original/additional coordinate
convention. Those identity checks are comparability gates, never predictive features.

Reconstruct the baseline from recorded atom order without rerunning classification,
selection or assembly. Keep ambiguous/empty output groups and incomparable groups
unchanged. Save candidate outputs and boundary decisions before opening labels.
No classifier, ownership, financial or billing rule changes.

## Fixed evaluation

Then reproduce all 24 saved v3 scores: 17 exact, two partial text and five other
mismatches, with full alignment and unique-output coverage. Score the saved
candidate using the same assignments, NFC/whitespace normalization and scorer.
Compare overall and digital/OCR slices; report exact match, paired gains/losses,
coverage, category transitions, changed outputs, removed separators and the
spacing-only mismatch count. The hypothesis is supported only if exact count
increases and there are zero exact-match losses; otherwise falsified.

This is a training-seed experiment with one human reviewer, not validation or
production acceptance. No second candidate, threshold tuning, fallback chosen
from labels or reference modification is allowed after the result.

## Verification and stop

Use invented-input red/green tests for narrow/wide gaps, inclusive thresholds,
RTL/LTR direction, line separation, overlap, invalid boxes, explicit whitespace,
punctuation/digits, mixed source/direction and exact source-character preservation.
Independently check boundary decisions, source selection/order, output strings,
all scores and aggregate slices. Keep all private data and disposable scripts
under ignored `artifacts/merchant-spacing-v1/`. Publish aggregates only and run
the four repository gates before tracked commits.

Stop on failure to reconstruct saved outputs or reproduce v3 scores. Stop after
this one comparison. Do not modify frozen branches or production source, build
shared controllers/evaluators/schema/CLI, expand the sample, access held-out data,
create new review, promote gold, integrate into production, merge or push.
