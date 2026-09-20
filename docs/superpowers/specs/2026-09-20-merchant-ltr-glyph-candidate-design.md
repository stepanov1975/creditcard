# Merchant LTR Glyph Reconstruction Candidate

**Status:** APPROVED — preparing one fixed experimental candidate.

The user's “proceed” approves the source-order trace report's recommendation to
test a guarded LTR reconstruction candidate on the reviewed 24-case training seed.

```text
Scope answer: YES — tests a glyph-position reconstruction candidate for merchant extraction
Experiment: row-profiles
Extraction hypothesis: Guarded LTR glyph reconstruction increases exact merchant matches above 19/24 without losing an existing exact match
Measurement: exact merchant matches, paired gains/losses and aligned unique-output coverage
Fixed inputs: 24 reviewed training references, 135 saved rows, 113 saved owner outputs and source pages from the frozen six-page seed
Smallest allowed files: docs/superpowers/specs/2026-09-20-merchant-ltr-glyph-candidate-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-ltr-glyph-candidate-report.md; artifacts/merchant-ltr-glyph-v1/**
Required output: runnable experimental candidate and exact-match delta with gains and losses
Stop condition: stop after one fixed candidate is generated and scored or reproduction fails; do not tune after scoring, edit labels, open held-out data or integrate into production
```

## Frozen generation inputs

Commit authority before generation. Reconstruct all 113 saved owner outputs from
the 135 frozen rows, saved proposal ownership, atom order and punctuation-spacing
boundary decisions. Preserve all 373 selected atom occurrences and every owner.
The source selection remains the existing six-page training seed. Extract only
its four digital pages from verified local seed copies using the frozen extractor;
do not open the two OCR source pages or run OCR, models or full-document parsing.

Generate every owner output before loading any reference, alignment or score file.
The same rule applies to every selected atom occurrence, with no case-, document-,
merchant- or answer-specific branch. Save the candidate before scoring it. All
prior artifacts and the frozen checkout stay unchanged.

## One predeclared rule

The test seam is `reconstruct_ltr(atom, page)`, returning text, a decision and
source indices. Preserve the original text unless every applicable guard passes:

1. The atom is digital, has at least one `L` bidi-class character and no `R`/`AL`
   characters. Its nonempty text is NFC and contains no whitespace, Unicode marks
   (`M*`) or control/format/unassigned characters (`C*`). A native page is available.
2. Exactly one native word matches the saved atom bounding box within **0.0001
   PDF points** per coordinate, and its unmodified text equals the saved atom text.
   Match geometry first; do not select among words using text or reference labels.
3. Select non-whitespace glyphs with centers inside the word. Each is digital,
   contains one code point and belongs to exactly one native word. Their exact
   character multiset equals the atom's, including punctuation, case and digits.
4. Glyph boxes are finite and positive, their common vertical overlap is at least
   **80%** of the smallest glyph height, and adjacent horizontal centers differ
   by more than **0.0001 points**. Sort by increasing horizontal center. The
   resulting text must remain NFC and preserve the exact character multiset.

Use the resulting text only as this candidate's rendering of that source atom.
Do not rewrite saved atoms or IDs. Keep saved owner membership, atom order and
every separator decision unchanged; do not rerun spacing rules on corrected text.
OCR and RTL atoms retain their saved text. Report successful changes, successful
unchanged reconstructions and every fallback reason across all occurrences.

## Measurement and verification

After generation, reproduce all 72 saved scores for the original, letter-spacing
and punctuation-spacing views. Score the new view on the same 24 v3 references
and fixed alignment. Report exact-match counts, paired gains/losses, transitions,
changed outputs and aligned unique-output coverage for all/digital/OCR slices.
The hypothesis is supported only with more than 19 exact matches, zero losses
against the punctuation baseline and unchanged 24/24 alignment/output coverage.

Use invented-input red/green tests for the candidate seam, including correct and
reversed LTR text, RTL/OCR exclusions, duplicate ownership, missing glyphs, Unicode
guards and ambiguous geometry. Independently reconstruct outputs using Decimal
geometry checks and independently verify score categories and aggregates. Retain
all private evidence, decisions and outputs only in ignored
`artifacts/merchant-ltr-glyph-v1/`; publish aggregates only.

Run the four repository gates before tracked commits. This is an experimental
training-seed result, not independent validation or production corpus acceptance.
Stop after one generation/score or reproduction failure. No post-score tuning,
second candidate, label change, new review, wider selection, held-out access,
controller work or production integration is authorized.
