# Merchant Proposals Before Row Rejection: Results

**Date:** 2026-09-12
**Status:** `COMPLETE — STOP`

Calling the existing deterministic description rule before financial-field
rejection exposed **8 exact merchant matches out of 24**, compared with none in
the frozen profile's accepted output. The hypothesis is **supported on this fixed
seed**: 8 paired gains, 0 losses. The merchant rule itself was not changed.

The [design](../superpowers/specs/2026-09-12-merchant-pre-rejection-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-pre-rejection.md), and charter
amendment were committed at `7470f4d` before the private measurement.

## Fixed comparison

The probe used the same 127 training-page observations, frozen `tight` profile
classifications, 24 single-human-review merchant references, and saved 20/24
transaction alignment as the [previous comparison](row-extraction-merchant-seed-comparison-report.md).
The four alignment failures remain unchanged.

The frozen `_description_atoms` and `_proposal` helpers ran directly, preserving
column selection, typed-residual filtering, atom order, merchant ambiguity rules,
and continuation ownership. Structural/ambiguous classifications stayed ineligible.
Diagnostic proposals retained the original prediction's decision and reasons;
none was converted into an accepted transaction. All 127 original classifications,
decisions, and reasons remained unchanged.

Scoring reused the previous NFC/whitespace-only exact matcher and owner aggregation.
More than one proposal for an owner stayed ambiguous; no merging or gold-assisted
selection was introduced.

| Measurement | Frozen accepted profile output | Before financial rejection |
| --- | ---: | ---: |
| Exact merchant matches / 24 | 0 | 8 (33.3%) |
| Exact merchant matches / 20 aligned | 0 | 8 (40%) |
| Unique descriptions available / 24 | 1 (4.2%) | 18 (75%) |
| Omissions among aligned cases | 19 | 1 |
| Ambiguous owner outputs | 0 | 1 |
| Alignment failures | 4 | 4 |
| Extra-text mismatches | 0 | 0 |
| Partial-text mismatches | 0 | 1 |
| Other text mismatches | 1 | 9 |

The exact-match delta is +8/24, or +33.3 percentage points. Unique-description
coverage increases by 17/24, or +70.8 percentage points. Increased availability
and exact correctness are separate outcomes.

| Seed slice | Cases | Aligned | Exact before rejection | Exact in control |
| --- | ---: | ---: | ---: | ---: |
| OCR pages | 8 | 8 | 3 | 0 |
| Digital-only pages | 16 | 12 | 5 | 0 |

## Evidence hidden by rejection

All **19 currency-blocked owner rows** had a description proposal under the
unchanged merchant rule. Eight of those owner proposals exactly matched the human
merchant reference. The remaining matched owner retained its ambiguous row type
and yielded no diagnostic description.

Nineteen available owner proposals become eighteen unique owner outputs after
continuation aggregation: one owner has multiple proposals and therefore remains
ambiguous. This explains why direct owner availability and final unique coverage
have different counts.

Across all 127 selected-page rows, 108 had a description proposal and 19 remained
ineligible by row type. Only the 24 reviewed cases were scored for merchant accuracy.
No OCR or other extraction arm was rerun.

The result establishes that row-wide financial rejection hid useful merchant
evidence in this seed. It does not justify accepting transactions with unresolved
financial fields. A merchant diagnostic can expose evidence while the original
transaction remains rejected.

## Next useful measurement

Before requesting more labels, use the existing human-marked merchant regions to
measure whether the **ten nonmatching descriptions** selected the wrong source
evidence or contain incorrect text within the intended evidence. Keep the one
ambiguous output, one row-type omission, and four alignment failures separate.
This would target the remaining merchant problem after isolating financial rejection.

That is a recommendation for a separately scoped phase; it has not been started.
No merchant rules, labels, alignment, sample membership, production behavior,
validation/test access, or historical lane dispositions changed here.

## Verification and limits

All four repository gates passed: Ruff formatting, Ruff lint, mypy over `src`,
and 3,766 repository tests. These checks are not a private-corpus acceptance run.

Eight invented-input tests passed after the initial focused run failed because
the probe module did not yet exist. They cover financial rejection with preserved
transaction decisions, atom order, continuation ownership, missing owners,
ineligible row classifications, ambiguous or absent description evidence, and
multiple-proposal ambiguity. Ruff and strict mypy passed for both private files.

A separate local calculation verified exact-text counts, category totals,
denominators, and paired gains/losses. The control reproduced every prior profile
case outcome. All original source observations, profile predictions, reference
and alignment bytes remained unchanged; the original user-answer file also
remains byte-identical. The historical checkout remained clean at its frozen SHA.

Private evidence, diagnostic proposals, and case scores stayed local and ignored.
No private text or pixels entered model tools, external services, or Git. The
reference remains a single-reviewer calibration candidate; these are training
diagnostics, not independently audited semantic accuracy, validation improvement,
or private-corpus acceptance.

```text
Scope: YES — measured merchant evidence hidden by deterministic row rejection
Experiment: row-profiles
Measurement: pre-rejection merchant exact matches, proposal coverage, omissions, ambiguity, and paired gains/losses
Result: 8/24 exact versus 0/24 in frozen accepted profile output; +8 gains and 0 losses; all 19 currency-blocked owners had merchant proposals; original transaction decisions unchanged
Next extraction task: STOP
```
