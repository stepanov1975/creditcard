# Residual Merchant Error Analysis

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved the fixed analysis under the
[design](../superpowers/specs/2026-09-12-merchant-residual-errors-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-residual-errors.md), and charter
amendment committed at `cf781cc` before private measurement.

## Result

The 11 remaining failures separate into **nine text mismatches within the marked
regions, one output with multiple owned proposals, and one omission with retained
alphabetic evidence elsewhere on its page**. The retained-evidence hypothesis is
supported by both the omission and the ambiguous-output case. All 24 saved scores
reproduce, and the exact merchant score remains **13/24**.

| Disjoint category | Digital | OCR | Total |
| --- | ---: | ---: | ---: |
| Single output, text mismatch, selected evidence strongly supported | 4 | 5 | 9 |
| Multiple owned description proposals | 1 | 0 | 1 |
| Omission with strongly located alphabetic evidence | 1 | 0 | 1 |
| Outside, boundary-sensitive, or unusable selected geometry | 0 | 0 | 0 |

Across the nine single outputs and the two proposals in the ambiguous case,
**35/35 selected atom occurrences** have strong support in both their merchant
and transaction regions. The single-output mismatches account for 29 occurrences;
the ambiguous case accounts for six. There are no selected atoms from another
source page and no unusable page-atom records in this analysis.

Strong support means an atom's center lies inside a marked region and at least
half its area lies inside one region. It establishes location, not text accuracy,
reference correctness, or complete evidence selection.

## Omission and ownership

The omitted case's aligned row is classified **ambiguous**, retains the
`ambiguous_row_type` reason, and is stopped by the saved **`ineligible_row_type`**
description-probe gate. It has no description proposal and no strongly located
merchant atoms in the owner row. Other saved rows on the same page contain
**four strongly located alphabetic atom records** in its merchant region.

This is evidence-access or ownership work to investigate, rather than evidence
that no merchant text was recognized anywhere. The four records are not four
certified missing words. This analysis does not rematch the reference, reclassify
the row, or establish which other row should own the merchant.

The ambiguous output consists of **two proposals**, one from the primary owner
and one from its explicitly assigned continuation row. Both proposals are wholly
supported by the merchant region; all six selected atoms are also strongly
supported by the transaction region. Neither proposal alone equals the reference.
They share **zero identical positioned observations**, using text, box, source,
and confidence as the observation key.

This supports testing assembly of primary and continuation merchant text. It does
not prove that concatenation will produce the reference. No proposal was chosen,
combined, discarded, or rescored here; the case remains ambiguous.

## Text mismatches

| Fixed mismatching slice | Cases | Character edits | Reference code points | Micro character error rate |
| --- | ---: | ---: | ---: | ---: |
| Digital | 4 | 15 | 67 | 22.39% |
| OCR | 5 | 58 | 93 | 62.37% |
| Combined | 9 | 73 | 160 | 45.625% |

These are **conditional error rates for the nine mismatches**, not whole-seed or
population error rates. Edit distance uses NFC plus collapsed whitespace and
Levenshtein code-point edits; rates use `Decimal` arithmetic.

One digital mismatch is spacing-only. Counts for word-order-only,
format-control-only, NFKC/whitespace-only, and punctuation-deletion-only equality
are all zero. These potentially overlapping signatures are diagnostic checks;
none changes the official scorer or establishes a new exact match.

Two text-mismatch cases also have **four unselected strongly located atom
records in their owner rows**, two of them alphabetic. Three records occur in a
digital case and one nonalphabetic record in an OCR case. Together with the four
records elsewhere on the omission's page, there are eight unselected strongly
located records across three residual cases. Record counts preserve duplicates
and do not certify missing semantic content.

All selected evidence in the nine cases is in-region. Their remaining differences
can still involve incomplete selection, recognition, within-atom ordering,
serialization, or reference transcription. This measurement does not distinguish
all of those causes and does not justify automatic label correction.

## Fixed inputs and validation

The analysis uses the unchanged 127 original rows, eight pre-filter diagnostic
rows, 135 saved predictions, candidate alignment, existing marked regions, and
24 human references. Only the 11 predeclared failures enter error analysis; the
13 exact cases serve only as score-reproduction controls. Source copies are read
for identity and selected-page geometry, with native-point normalization for
original rows and display-point normalization for the eight additional rows.
No source text extraction, rendering, OCR, discovery, classification, model call,
or new prediction runs.

The new category and signature helpers have **28 invented-input tests** observed
failing before implementation and passing afterward. All four private Python
files pass Ruff and strict mypy. Independent rectangle calculations agree on
all 35 selected atoms against both region types and all **2,871 page-atom/region
checks**, including repeated records across different reference cases. Independent
full-matrix edit calculations agree on all nine distances and reference lengths;
independent normalized equality agrees with all 24 exact-match outcomes.

All 12 protected input files and six local source copies remain unchanged, as
does the frozen checkout. Required repository verification passes: Ruff format
and lint, mypy on 48 source files, and **3,766 tests passed** in 100.14 seconds.

Private analysis, case diagnostics, and verification remain under ignored
`artifacts/merchant-residual-errors-v1/`. Only aggregate documentation is tracked.
No production code changed; this is not private-corpus verification or production
acceptance, and no merge was performed.

## Interpretation and next recommendation

The reviewed seed is now useful for separating text disagreement from output
assembly and access problems. It remains a small training calibration set reviewed
by one human, not independently certified gold or a held-out estimate. Preserve
all 24 references and the 13/24 score.

The next recommended extraction task is **one primary/continuation merchant
assembly experiment** on the same 24 references: combine only description evidence
already explicitly owned by the same transaction, in page reading order, and
measure exact merchant match, unique-output coverage, and paired gains/losses
against 13/24. Preserve evidence text, ownership, alignment, and billing decisions;
use no reference-conditioned rule. This recommendation has not been executed.

The authorized diagnostic is complete. **STOP**. New extraction candidates,
label repair, new labels, expansion, gold promotion, validation/test access, and
production integration are outside this completed task.

```text
Scope: YES — quantifies residual merchant text, selection, and ownership errors
Experiment: row-profiles
Measurement: retained-evidence support, ownership conflicts, omission gates, text signatures, and character error rate
Result: 9 in-region text mismatches, 1 multiple-proposal output, 1 omission with retained evidence; hypothesis supported; score unchanged at 13/24
Next extraction task: STOP
```
