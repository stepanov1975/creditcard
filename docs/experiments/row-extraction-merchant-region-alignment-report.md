# Merchant-Region Alignment Comparison

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved this fixed measurement comparison
under the [design](../superpowers/specs/2026-09-12-merchant-region-alignment-design.md)
and the immediate shared-evaluation allowance committed at `9601a1f` before
candidate alignment and scoring.

## Result

Merchant-region-supported alignment raises unique merchant-output coverage from
**23/24 to 24/24**, but exact matches remain **13/24**, with **zero gains and zero
losses**. The hypothesis that this measurement correction would increase exact
matches without losses is **falsified** on the fixed training seed.

Only one assignment changes: the previously omitted reference now maps to a row
with a merchant description. That description still differs from the reference.
All other 23 assignments and their case outputs are unchanged. Every reference
now has one nonempty output; the remaining 11 failures are text mismatches.

| Metric | Original alignment | Merchant-region alignment |
| --- | ---: | ---: |
| Exact merchants | 13/24 (54.2%) | 13/24 (54.2%) |
| Aligned references | 24/24 | 24/24 |
| Unique description output | 23/24 (95.8%) | 24/24 (100%) |
| Alignment failures | 0 | 0 |
| Omissions | 1 | 0 |
| Ambiguous outputs | 0 | 0 |
| Partial text | 2 | 2 |
| Other text mismatches | 8 | 9 |
| Extra text | 0 | 0 |

The exact-match delta is zero percentage points. Unique-output coverage increases
by approximately 4.17 percentage points. No extraction output was regenerated or
edited; the change is solely which saved owner the evaluator associates with
one reference.

## Fixed measurement rule

For every reference, the matcher considers its selected page's saved rows and
requires at least one alphabetic source atom strongly supported by an existing
human-marked merchant region. Strong support uses the unchanged rule: the center
is inside a region and at least half the atom area is inside one region.

Eligible rows keep the original transaction-overlap score, including its
half-row-height requirement. Unique-best selection and collision handling are
unchanged. Ties or references choosing the same row cannot be rescued with a
second-choice assignment. No prediction type, output availability, expected
merchant text, financial value, or source identity is used to determine eligibility
or ranking. Source text is used only to test for an alphabetic character.

The predicate applies to all 24 references. Twenty-three have one positive
eligible candidate; one has multiple positive eligible candidates. There are no
equal-best ties, collision failures, or references without a positive candidate.

The existing 127 original rows plus eight diagnostic rows provide the source
evidence. Original native-point and additional display-point geometry retain
their existing normalization conventions. The matcher receives only region
geometry, row boxes, and source atoms. It does not receive reference merchant
text, predictions, or outputs.

A separate candidate alignment is saved. The original alignment, all labels,
source atoms, predictions, explicit ownership, assembly outputs, classifications,
and billing decisions remain unchanged. Both alignments are scored against the
same saved outputs with the unchanged NFC/whitespace scorer and 24-case
denominator. This is a local measurement correction, not a recognition change
or a new frozen-arm comparison.

## Digital and OCR slices

| Fixed slice | Exact before | Exact candidate | Unique output before | Unique output candidate |
| --- | ---: | ---: | ---: | ---: |
| Digital pages | 10/16 | 10/16 | 15/16 | 16/16 |
| OCR pages | 3/8 | 3/8 | 8/8 | 8/8 |

The one assignment change is digital. Neither slice gains or loses an exact
match. The candidate leaves six digital and five OCR text mismatches. This
comparison does not diagnose their character-level causes or adjudicate whether
the reference or extracted text is correct.

## Verification and private artifacts

Twenty-one invented-input tests reached the expected unimplemented-filter
failures before implementation and then passed. They cover alphabetic source
eligibility, center/area boundaries, invalid geometry, unchanged ranking and
half-row-height requirements, per-reference filtering, preserved source atoms,
ties, and collision abstention without fallback. All four private Python files
pass Ruff formatting/lint and strict mypy.

All 24 original scores and assignments reproduce before candidate alignment.
Independent point-space geometry agrees with all 24 original and 24 candidate
assignments. Independent normalized equality agrees with all 48 before/after
exact-match outcomes, zero gains/losses, and coverage of 23/24 versus 24/24.
All 1,719 source row/atom boxes used in verification are finite with positive
area. A separate read-only code review found no actionable defects.

All 12 protected input files, six selected source copies, and the frozen checkout
remain unchanged. Source copies are read only for identity and selected-page
geometry. No text extraction, rendering, OCR, model call, classification, arm
prediction, or assembly rerun occurs. Private scores, candidate alignment, and
verification remain under ignored `artifacts/merchant-region-alignment-v1/`;
only aggregate documentation is tracked.

Required repository gates pass: Ruff formatting/lint, mypy on 48 source files,
and **3,766 tests passed** in 98.88 seconds. No production code changed; this
is not private-corpus verification or production acceptance. No merge was
performed.

## Golden-dataset implication and next recommendation

All 24 reviewed references now have a comparable saved merchant output under
the candidate alignment. The earlier access and output-assembly failures no
longer obscure which cases have textual disagreement. Exact accuracy remains
13/24, and the 11 remaining discrepancies must not be resolved by automatically
copying model outputs into the references.

The next recommended task is **a blind second transcription of those 11 merchant
regions**, using the existing reviewed source pages without showing previous
answers or model suggestions. Measure agreement with the preserved original
references, and resolve any transcription ambiguity explicitly before further
tuning or dataset expansion. This would audit reference consistency; a second
pass by the same reviewer is not an independent multi-reviewer gold certification.
No review packet or new transcription has been created in this comparison.

The authorized comparison is complete. **STOP**. No tuning, second candidate,
reference repair, new labels, expansion, gold promotion, validation/test access,
or production integration is authorized by this completed task.

```text
Scope: YES — measures merchant recognition with source-supported reference alignment
Experiment: shared evaluation
Measurement: alignment coverage, exact merchant match, unique-output coverage, and paired gains/losses
Result: exact 13/24 to 13/24; unique output 23/24 to 24/24; 0 gains, 0 losses; measured-accuracy hypothesis falsified
Next extraction task: STOP
```
