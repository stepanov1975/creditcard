# Merchant Omission Alignment and Evidence-Routing Trace

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved the fixed trace under the
[design](../superpowers/specs/2026-09-12-merchant-omission-routing-design.md) and
charter amendment committed at `8c253ba` before private measurement.

## Result

The remaining omission has **four strongly located merchant atoms already selected
into another primary row's description**. That row ranks second under the current
geometric matcher. The aligned row ranks first but has **zero positive classifier
proofs**, no received description proposals, and the saved `ineligible_row_type`
probe gate. The hypothesis that retained merchant evidence is routed to a different
owner is **supported**.

All 24 saved scores reproduce. No assignment, output, prediction, or reference
changes: exact merchant matches remain **13/24**, unique-output coverage **23/24**,
and omissions **1/24**. No alternative owner is scored in this trace.

| Observation | Count or result |
| --- | --- |
| Saved rows on the selected page | 27 |
| Positive geometric candidates for the omitted reference | 7 |
| Candidates tied at the highest score | 1 |
| Aligned row's geometric rank | 1 |
| Merchant-bearing row's geometric rank | 2 |
| Strongly located merchant records | 4 |
| Distinct positioned merchant observations | 4 |
| Merchant-bearing source rows | 1 primary row |
| Merchant records in the aligned row | 0 |
| Merchant records selected for another owner | 4 |
| Other destination owners emitting a description | 1 |
| Description proposals received by the aligned row | 0 |

## Alignment and evidence location

The frozen matcher uses positive horizontal overlap, at least half a candidate
row's height in vertical overlap, and the largest intersection-over-union score
against the human transaction region. It does not require merchant evidence in
the selected row. The unique-best and collision rules reproduce all four saved
assignments on the selected page, including the omitted reference.

The page has 443 atom records. Four have strong support in the marked merchant
region and 439 are outside; none is boundary-sensitive or unusable. All four
strong records are alphabetic, distinct positioned observations, inside their
source row, and strongly supported by the marked transaction region as well.

The matched row is not empty: it has 19 nonempty text atoms and seven column
bands. None of its atoms has an assigned semantic role. Eleven atoms have strong
support in the broad transaction region and eight are outside; none has strong
support in the merchant region. Thus transaction-box overlap can select a row
without the merchant evidence relevant to this reference.

The merchant-bearing row has positive transaction-region overlap but ranks
second. It is neither the saved predecessor nor successor of the aligned row.
These measurements identify an alignment/evidence-access mismatch; geometry
alone does not independently certify semantic transaction ownership or establish
that the human transaction box should be changed.

## Classifier and saved routing

Reconstructing the unchanged tight profile rule gives the same saved type for
both traced rows. The aligned row is ambiguous because it has **no positive
proof**, not because multiple type proofs conflict.

Its profile contains no date, money, currency, installment, alphabetic-description,
header, or structural-label signal, and no occupied semantic roles. It has a
predecessor within the tight gap limit, but proximity alone is insufficient for
a continuation proof. Without billed-money evidence there is no primary proof;
without permitted content there is no continuation proof; without structural
signals there is no structural proof. The saved `ambiguous_row_type` reason and
`ineligible_row_type` description gate therefore agree with the frozen rules.

The merchant-bearing row has a unique primary-transaction proof. All four located
atoms appear in its saved description proposal, owned by that same primary row.
Its current assembly output is nonempty. It is not aligned to another reviewed
case, and its owner stays on the selected page. No record is selected for the
aligned owner or for multiple owners.

The description is consequently available under another saved owner but is not
reachable through this reference's current alignment. Primary/continuation
assembly cannot redirect it: that completed experiment intentionally preserves
explicit ownership. This trace does not reclassify, transfer evidence, infer a
continuation, or test whether the other description exactly matches the reference.

## Validation and artifacts

Eleven invented-input tests reached the expected unimplemented-helper failures
before implementation and then passed. They distinguish unselected evidence,
selection for the aligned or another owner, duplicate owner references, multiple
owners, and absent versus unique or conflicting classifier proofs. All four
private Python files pass Ruff formatting/lint and strict mypy.

The trace reproduces all 24 saved scores, all four selected-page assignments, and
both reconstructed classifier types. Independent point-space rectangle calculations
agree on all four assignments, all 27 row ranks, and all 443 atom-region checks.
Independent saved-proposal inspection confirms all four merchant atoms' routes to
the other primary owner. Read-only code review found no actionable defects.

All 13 protected input files, the one selected source copy, and the frozen checkout
remain unchanged. Source access was limited to identity and selected-page geometry;
there was no text extraction, rendering, OCR, discovery, field extraction, arm
prediction, or model call. Private trace records, profiles, alignment details, and
verification remain under ignored `artifacts/merchant-omission-routing-v1/`.
Only aggregate documentation is tracked.

Required repository verification passes: Ruff formatting/lint, mypy on 48 source
files, and **3,766 tests passed** in 99.12 seconds. No production code changed;
this is not private-corpus verification or production acceptance. No merge was
performed.

## Implication for the reference dataset and next recommendation

The seed has exposed a measurement issue: a merchant omission can arise when the
reference is geometrically matched to a row that does not carry its marked
merchant evidence, even when that evidence already has a description elsewhere.
This does not establish a recognition failure or justify correcting the human
merchant text. The 24 references remain a small single-reviewer training set,
without independent gold certification or held-out accuracy claims.

The next recommended task is **one fixed merchant-region alignment comparison**
across the same 24 references: require strongly located alphabetic source evidence
in the marked merchant region as candidate eligibility, then use the unchanged
transaction-overlap ranking and collision rule. Preserve the original alignment,
labels, predictions, and denominator; keep any candidate alignment separate.
Measure alignment coverage, exact merchant match, and paired gains/losses. This
would test a measurement correction, not improved source recognition. It has not
been executed and no accuracy gain from rematching is assumed.

The authorized trace is complete. **STOP**. No rematching, new prediction, rule
change, label repair, new labels, expansion, gold promotion, validation/test access,
or production integration is authorized by this completed task.

```text
Scope: YES — quantifies alignment, classification, and routing behind the merchant omission
Experiment: row-profiles
Measurement: alignment ranking, classifier proof conflicts, merchant-evidence routing, and omission-gate counts
Result: 4 merchant atoms routed to another primary owner at rank 2; aligned rank-1 row has no positive proof; hypothesis supported; score unchanged at 13/24
Next extraction task: STOP
```
