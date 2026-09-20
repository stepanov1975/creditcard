# Merchant Source-Order Trace

**Status:** COMPLETE — STOP. The predeclared hypothesis is **supported** for
all three selected atoms: their reversed character sequence is already present
in native digital word extraction and passes unchanged through every traced
downstream boundary.

The [design](../superpowers/specs/2026-09-20-merchant-source-order-trace-design.md)
was committed at `6a6d13b` before private measurement. The trace follows the
[directional-signature measurement](row-extraction-merchant-atom-direction-report.md)
on the same two digital training cases.

## Stage attribution

Both cases belong to one selected source page. Two native extractions of that
page produced identical evidence. The local reproduction command returned its
expected failure signal, detecting the reverse-only signature in all three
uniquely geometry-matched native words. No repair was implemented.

| Observed boundary | Exact matches to the saved reversed atom |
| --- | ---: |
| Native digital word extraction | 3/3 |
| Canonical layout word | 3/3 |
| Logical-row word evidence | 3/3 |
| Replayed row-to-atom projection | 3/3 |
| Saved frozen atom | 3/3 |
| Saved proposal evidence | 3/3 |

All three traces completed; none required a wider geometry tolerance or remained
unresolved. Each replayed atom matches the complete saved atom, including its
identity and metadata. Later evidence selection and assembly do not introduce
the within-atom reversal observed here.

The frozen code explains why it persists: `ccparser.evidence.pdf._extract_words`
copies native word text, and
`ccparser.layout.text.canonical_words_for_layout` currently applies lossless
glyph-based canonicalization only to RTL digital words. These LTR words pass
through that function unchanged. `experiments.row_extraction.bundle._row_atoms`
preserves the word text when constructing evidence atoms.

This establishes the earliest observed boundary in this trace. It does not
determine whether the original PDF encoding or the text decoder produced that
sequence; no byte-level PDF authoring claim follows from it.

## Glyph-order evidence

All 17 selected glyphs have unique word ownership, valid geometry and an exact
character-inventory match to their native word. The predeclared horizontal-center
and vertical-overlap guards pass for all three words.

| Glyph sequence | Equals saved word | Equals reversed saved word | Present in reference |
| --- | ---: | ---: | ---: |
| Native extraction order | 3/3 | 0/3 | 0/3 |
| Increasing horizontal-center order | 0/3 | 3/3 | 3/3 |

Source positions therefore provide an independent ordering signal for all three
blocks, without choosing glyph order from the human reference. Reference text
enters only the subsequent containment comparison. No transformed blocks were
assembled into a merchant prediction.

## Verification and implication

- Reproduced 72 saved scores, three digital classifications, two whole-atom
  results and all seven directional signatures.
- Independent Decimal geometry checks and boundary comparisons agree on all
  three traces, 18 text-boundary comparisons, 17 glyphs and 27 aggregate fields.
- Ten invented-input tests cover stage attribution, intervening changes, failed
  projection, proposal disagreement and ambiguous or invalid glyph geometry.
- Ruff formatting/lint, strict private-script typing, repository mypy and all
  3,766 repository tests pass.
- Seventeen protected inputs, including the source copy, and the frozen checkout
  remain unchanged. One source page was extracted twice; no OCR, model calls,
  label edits or new merchant predictions occurred.

Accuracy remains **19/24 exact**, with 24 aligned unique outputs. This local
diagnosis provides no new validation or production corpus-acceptance result.
Scripts, source evidence, commands and private comparisons are in ignored
`artifacts/merchant-source-order-trace-v1/`.

The unexecuted recommendation is to test a lossless glyph-position reconstruction
candidate for LTR digital words against the reviewed 24-case seed, measuring exact
merchant gains and regressions. The rule should use source geometry and inventory
guards, without reference-dependent decisions. No candidate or follow-on phase
is active.

```text
Scope: YES — locates the stage carrying three reversed merchant atoms
Experiment: row-profiles
Measurement: first observed reversal stage and unchanged downstream atom counts
Result: hypothesis supported; 3/3 native reversals persist unchanged, and glyph geometry yields reference substrings for all three
Next extraction task: STOP
```
