# Merchant LTR Glyph Reconstruction Candidate

**Status:** COMPLETE — STOP. The predeclared hypothesis is **falsified**: exact
merchant accuracy remains **19/24**, with **zero gains and zero losses** against
the punctuation-spacing baseline. Two reviewed outputs change, but neither
becomes an exact match. No post-score tuning was performed.

The [design](../superpowers/specs/2026-09-20-merchant-ltr-glyph-candidate-design.md)
was committed at `d27f0dc` before generation. This experiment follows the
[source-order trace](row-extraction-merchant-source-order-trace-report.md), which
located reversed LTR blocks in native word extraction and found usable glyph
positions for the three traced blocks.

## Fixed candidate

The candidate reconstructs eligible digital LTR atom text by increasing glyph
horizontal-center position. It requires a unique native-word geometry match,
unchanged native word text, uniquely owned single-character digital glyphs,
exact character-inventory preservation, a common vertical band, distinct centers
and stable NFC text. Unsupported Unicode, source or geometry conditions retain
the original text. The rule receives no reference labels.

All 113 baseline owner outputs were reconstructed first. Generation then applied
the same rule to all 373 selected atom occurrences, preserving owner membership,
atom IDs, atom order and every saved separator decision. Predictions were saved
before references, alignment or score files were read by the generation process.

| Atom decision | Occurrences |
| --- | ---: |
| LTR geometry reconstruction changes text | 19 |
| LTR geometry reconstruction preserves text | 127 |
| Not LTR | 178 |
| Not digital | 49 |
| Total | 373 |

All 146 eligible LTR occurrences passed the native-word, glyph-inventory and
geometry guards. Seven of 113 owner outputs change. Four existing digital seed
pages were extracted; the two OCR source pages were not opened. No OCR or model
calls were made.

## Exact merchant results

| Slice | Baseline exact | Candidate exact | Gains | Losses | Changed outputs |
| --- | ---: | ---: | ---: | ---: | ---: |
| All reviewed cases | 19/24 | 19/24 | 0 | 0 | 2 |
| Digital | 13/16 | 13/16 | 0 | 0 | 2 |
| OCR | 6/8 | 6/8 | 0 | 0 | 0 |

Aligned unique-output coverage stays **24/24**. All 19 existing exact cases
remain exact. The full score-category transitions are 19 exact-to-exact, two
partial-to-partial and three other-mismatch-to-other-mismatch. The two changed
reviewed outputs remain in the other-mismatch category.

This result shows that the fixed glyph reconstruction alone is insufficient with
the saved atom order and spacing. It does not establish which remaining ordering
or spacing change would produce a complete match. No residual-error query or
second candidate was run after scoring.

## Verification and next measurement

- Reproduced all 72 prior scores and scored the candidate on all 24 unchanged
  v3 training references and their fixed alignment.
- Independent Decimal geometry, sorted-inventory and output reconstruction
  checks agree on all 373 decisions and all 113 owner outputs.
- Independent score checks agree on all 96 saved scores and all/digital/OCR
  aggregate comparisons. Eighteen combined inputs remain unchanged.
- Fourteen invented-input candidate tests pass, alongside Ruff formatting/lint,
  strict private-script typing, repository mypy and all 3,766 repository tests.
- The frozen extractor checkout, prior predictions and labels remain unchanged.

The candidate remains runnable privately in ignored
`artifacts/merchant-ltr-glyph-v1/`, alongside decisions, native evidence, scores,
commands and verification. Only aggregates are tracked. This training-seed result
does not establish independent validation performance or production acceptance;
the punctuation-spacing baseline remains the current best measured view.

The unexecuted recommendation is to test intact corrected-block ordering
witnesses for the two changed reviewed cases, preserving the glyph reconstruction
and ignoring whitespace. That would measure whether block ordering can explain
the remaining mismatch. No follow-on phase or second candidate is active.

```text
Scope: YES — tests a source-based LTR merchant reconstruction candidate
Experiment: row-profiles
Measurement: exact merchant matches, paired gains/losses and aligned unique-output coverage
Result: hypothesis falsified; 19/24 to 19/24, zero gains/losses, coverage 24/24
Next extraction task: STOP
```
