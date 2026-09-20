# Merchant Whole-Atom Ordering Witness Measurement

**Status:** COMPLETE — STOP. The predeclared hypothesis is **falsified** on the
two selected digital training cases: neither can match the non-whitespace
reference by reordering intact selected atoms.

The [design](../superpowers/specs/2026-09-20-merchant-atom-order-witness-design.md)
was committed before measurement. This diagnostic follows the
[character-error measurement](row-extraction-merchant-character-errors-report.md),
which found equal non-whitespace character inventories but different sequences
in two remaining digital merchant errors.

## Measurement

Use every selected atom occurrence exactly once, preserving its text and internal
order. Project each atom and reference with NFC and removal of Unicode whitespace.
Enumerate every identity permutation, with a predeclared maximum of nine atoms.
Verify the recorded projections reproduce the saved prediction and check
normalization stability for every enumerated order. Equal-text and empty-text
occurrences retain their identities.

| Selected case size | Identity orders checked | Matching orders | Verdict |
| --- | ---: | ---: | --- |
| Four atom occurrences | 24 | 0 | No intact-atom witness |
| Three atom occurrences | 6 | 0 | No intact-atom witness |
| Total | 30 | 0 | 0/2 cases have a witness |

All seven selected atom occurrences were retained. Neither case hit the size
limit, recorded-projection guard or normalization guard. Both unique-witness and
multiple-witness case counts are zero. No representative witness exists to save.

## Interpretation

Whole-atom reordering alone cannot explain these two errors under the fixed atom
selection and projection. This does not identify a particular within-atom defect,
prove that reversing text would help, or independently certify the reference.
Changes to atom contents or boundaries would be a separate hypothesis.

Merchant accuracy stays **19/24 exact**, with 24 aligned unique outputs. These
are selected training cases from the reviewed seed; the diagnostic supplies no
validation estimate or new extraction candidate. The missing-only digital case
and both OCR failures were outside this measurement.

## Verification

- Reproduced all 72 saved scores and all three previous digital classifications.
- Independently obtained both counts using prefix/subset dynamic programming;
  recursively checked normalization for all 30 orders.
- Thirteen invented-input tests pass, covering duplicate identities, empty
  projections, intact-block limits, Unicode normalization and retained controls.
- Ruff formatting/lint, strict typing for private scripts, repository mypy and
  all 3,766 repository tests pass.
- Fourteen saved inputs and the frozen extractor checkout remain unchanged.
  No source documents were opened, predictions generated or labels changed.

Private scripts, case results, aggregate results, commands and verification live
in ignored `artifacts/merchant-atom-order-witness-v1/`. Only aggregates are tracked.
This is a local diagnostic, not production corpus acceptance.

The unexecuted recommendation is to quantify within-atom directional-order
signatures in these same two saved cases before proposing any text transformation.
No follow-on measurement, candidate or source access is active.

```text
Scope: YES — measures the intact-atom ordering explanation for two fixed merchant errors
Experiment: row-profiles
Measurement: whole-atom witness cases and matching identity-order counts
Result: hypothesis falsified; 0/2 witness cases across all 30 orders, with no unresolved cases
Next extraction task: STOP
```
