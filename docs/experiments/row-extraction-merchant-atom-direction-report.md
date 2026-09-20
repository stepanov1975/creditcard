# Merchant Within-Atom Directional Signatures

**Status:** COMPLETE — STOP. The predeclared hypothesis is **supported**: both
selected cases contain an atom absent forward but present reversed in the
non-whitespace reference. Three of seven selected atom occurrences have this
signature; the other four are palindromic and match in both directions.

The [design](../superpowers/specs/2026-09-20-merchant-atom-direction-design.md)
was committed at `c6b5cb5` before measurement. This diagnostic follows the
[whole-atom witness measurement](row-extraction-merchant-atom-order-witness-report.md),
which ruled out rearranging intact atoms alone for these two saved digital
training errors.

## Measurement

Project each atom and its reference with NFC followed by removal of Unicode
whitespace. Count overlapping reference substrings forward and with the atom's
code points reversed, retaining repeated source occurrences. Reversal remains
unresolved for the predeclared normalization, mark or format-control exclusions.

| Reference containment | Atom occurrences |
| --- | ---: |
| Forward only | 0 |
| Reversed only | 3 |
| Both directions | 4 |
| Neither direction | 0 |
| Empty projection | 0 |
| Unresolved | 0 |

Both selected cases contain reverse-only atoms. All four both-direction atoms
are palindromic, so they provide no directional distinction. There are four
forward substring occurrences and seven reversed substring occurrences in total.
These counts do not assign nonoverlapping reference spans.

All **seven atoms have only LTR strong-direction characters**. None contains RTL
strong-direction characters or transitions between LTR and RTL. The selected
projections contain two punctuation characters, no decimal digits, no Unicode
marks and no format controls. Every normalization guard passes.

## Interpretation

The measured signature points toward LTR character ordering inside atoms as a
cause worth investigating. It provides no evidence of mixed strong directions
inside these blocks. The four palindromic blocks cannot reveal their ordering.

This is reference-conditioned substring evidence, not a general correction rule.
It does not establish where a reversal arose, prove that reversing selected
blocks reconstructs a complete merchant, certify reference correctness or justify
reversing all LTR text. No transformed blocks were assembled into predictions.

Merchant accuracy remains **19/24 exact**, with 24 aligned unique outputs. The
two cases come from the reviewed training seed; no validation, broader population
accuracy or production corpus acceptance claim follows from this measurement.

## Verification

- Reproduced 72 saved scores, three prior digital classifications and both
  previous whole-atom witness results.
- Independent escaped-lookahead substring counting and Unicode profiling agree
  on all seven signatures, 84 signature fields and 29 aggregate fields.
- Thirteen invented-input tests cover overlapping matches, palindromes, empty
  projections, mixed directions, normalization, marks and retained controls.
- Ruff formatting/lint, strict private-script typing, repository mypy and all
  3,766 repository tests pass.
- Fifteen saved inputs and the frozen extractor checkout remain unchanged.
  No source documents were opened, labels edited or new predictions generated.

Scripts, commands and private results are in ignored
`artifacts/merchant-atom-direction-v1/`. Only aggregates are tracked.

The unexecuted recommendation is a focused source-order trace to measure where
the three reverse-only LTR atoms acquire their order in the deterministic
extractor. A correction should depend on source evidence. No trace, correction,
new source access or follow-on phase is active.

```text
Scope: YES — quantifies within-atom ordering signatures in two fixed merchant errors
Experiment: row-profiles
Measurement: reference containment by atom direction and reversal eligibility
Result: hypothesis supported; three reverse-only LTR atoms across both cases, four palindromic atoms, none unresolved
Next extraction task: STOP
```
