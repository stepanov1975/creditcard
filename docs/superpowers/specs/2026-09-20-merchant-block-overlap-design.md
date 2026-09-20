# Merchant Block-Overlap Measurement

**Status:** APPROVED — measurement pending.

The user's “proceed” approves the completed block-order candidate report's
recommendation to quantify its seven overlap-rejected groups.

```text
Scope answer: YES — quantifies the overlap category that blocked merchant reordering
Experiment: row-profiles
Extraction hypothesis: At least one rejected group has consistent left-edge, center and right-edge ordering with distinct native words and disjoint glyph evidence despite overlapping boxes
Measurement: overlap ratios, duplicate/nested/crossing pair counts, ordering agreement and source-evidence ambiguity
Fixed inputs: seven saved overlap-rejected training groups, original atoms, saved native pages, fixed labels and 120 saved scores
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-block-overlap-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-block-overlap-report.md; artifacts/merchant-block-overlap-v1/**
Required output: quantified overlap categories and a supported, falsified or unresolved hypothesis
Stop condition: stop after the seven-group measurement or saved-result reproduction failure; no guard changes, new predictions, source extraction or broader selection
```

## Selection and immutable inputs

Reconstruct the 113 saved glyph outputs and block-order decisions, and reproduce
all 120 saved scores. Select exactly the seven owners whose saved and replayed
decision is `overlapping_blocks`. Keep every selected occurrence, original atom
geometry and ownership. Only these groups receive overlap analysis.

Use the four native-page evidence snapshots already saved by the glyph candidate
to attribute source words and glyphs. Do not open PDFs, render pixels or extract
new evidence. Old private artifacts and the frozen checkout remain read-only.
Labels may reproduce scores and identify reviewed membership, but cannot select
or reorder evidence in this measurement. Do not load reference-matching witnesses.

## Predeclared measurement

The diagnostic seam is `measure_overlap(atoms, keys, page)`, returning measurements
and source-attribution statuses without an extraction prediction. Use exact
rational arithmetic from the saved decimal coordinate representations.

For each selected group:

- Recheck finite positive boxes and the existing common-line/unique-center guards.
  Record whether left edges, centers and right edges give the same strict order;
  edge differences at or below the existing 0.0001 tolerance are ambiguous.
- Examine every unordered occurrence pair, not just adjacent pairs. For positive
  horizontal intersection, record overlap divided by the smaller block width and
  by the smaller average character width. Character counts exclude whitespace
  and Unicode mark/control categories. Undefined ratios remain unresolved.
- Classify horizontal intervals as coincident (both endpoints within 0.0001),
  nested (one interval contains the other), or crossing (partial intersection).
  Report repeated atom identities and equal-text pairs separately: equal text
  alone does not prove duplicated evidence.
- Match each original atom to exactly one saved native word using the existing
  0.0001 per-coordinate tolerance; require exact original text and digital source.
  Select non-whitespace native glyphs whose centers lie inside that word box.
  Require nonempty, single-code-point digital glyphs and exact character inventory.
  Missing/nonunique word matches or failed glyph checks remain unresolved.
- Count repeated native-word assignments and shared glyph indices across all
  occurrence pairs. A group has consistent independent source ordering only when
  all three strict orders agree, no atom/native-word identity repeats, all source
  matches resolve and glyph sets are pairwise disjoint. This is a diagnostic
  property, not proof that the resulting merchant string or spacing is correct.

Report group/occurrence/pair counts, overlap-ratio ranges, interval categories,
ordering agreement, attribution statuses, shared-evidence counts and reviewed
membership. Report no private identities, coordinates, words or glyph text.

The hypothesis is supported if at least one group meets every consistency
condition. Otherwise it is unresolved if a source/geometry attribution remains
unresolved, and falsified if all groups resolve but none meets the conditions.
Do not pick a new overlap cutoff or generate reordered merchant strings.

## Verification and stop

Commit authority before implementation or measurement. Use invented-input
red/green tests for overlap ratios, interval categories, order ambiguity,
duplicate identities, missing source matches and shared glyph evidence. Verify
the measurements separately using decimal arithmetic and direct source checks.
Reuse prior score and candidate verification logic without writing old outputs.

Keep disposable code, results and logs in ignored
`artifacts/merchant-block-overlap-v1/`. Check read inputs and the frozen checkout
remain unchanged. Publish aggregates only and run all four repository gates
before tracked commits. Stop after this measurement, with no second diagnostic,
candidate, label change, held-out access, shared framework or production change.
