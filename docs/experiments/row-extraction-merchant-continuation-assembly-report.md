# Merchant Primary/Continuation Assembly Comparison

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved this fixed comparison under the
[design](../superpowers/specs/2026-09-12-merchant-continuation-assembly-design.md)
and charter amendment committed at `4b9a14a` before candidate generation.

## Result

Primary/continuation assembly increases unique merchant-output coverage from
**22/24 to 23/24**, while exact matches remain **13/24**, with **zero gains and
zero losses**. The hypothesis that assembly would increase exact matches without
losses is **falsified** on this fixed training seed.

The one reviewed ambiguous output becomes a single description, but that text
still differs from the reference. The other 23 reviewed outputs are unchanged.

| Metric | Saved pre-filter comparator | Assembly candidate |
| --- | ---: | ---: |
| Exact merchants | 13/24 (54.2%) | 13/24 (54.2%) |
| Aligned references | 24/24 | 24/24 |
| Unique description output | 22/24 (91.7%) | 23/24 (95.8%) |
| Alignment failures | 0 | 0 |
| Omissions | 1 | 1 |
| Ambiguous outputs | 1 | 0 |
| Partial text | 2 | 2 |
| Other text mismatches | 7 | 8 |
| Extra text | 0 | 0 |

The exact-match delta is zero percentage points; coverage increases by roughly
4.17 percentage points. Coverage alone does not satisfy the declared hypothesis.
After assembly, the 11 non-exact cases consist of ten text mismatches and one
omission. This comparison does not diagnose the assembled text's remaining error.

## Fixed extraction rule

The candidate consumes the existing 135 saved predictions and their 135 training
rows: 127 original rows plus eight pre-filter diagnostic rows. It groups merchant
description proposals by their existing owner. Single-proposal outputs retain
their original text, spacing, and order. Rows without outputs remain without
outputs.

A group is eligible for assembly only when exactly one proposal comes from its
primary-transaction owner and the remaining proposals each come from a distinct
continuation row explicitly naming that owner. All contributing rows must share
the document, page, and render version. Empty descriptions, invalid atom geometry,
or shared positioned observations leave the original output list unchanged.

Eligible groups use all their selected atom occurrences. The existing fixed
geometry/Unicode directional-run helper orders those atoms in page reading order,
then their unchanged source text is joined with spaces. Temporary occurrence
indices distinguish row-local atom IDs; private ordered row/atom references allow
checking that every original occurrence was preserved. No evidence is added,
edited, inferred, or deduplicated.

Across all saved predictions, there are **113 owner groups**. The candidate
preserves 110 single-proposal groups and assembles three groups containing six
source rows and 15 selected atom occurrences. Only one assembled owner belongs to
the 24 reviewed references. The other two groups have no merchant-quality verdict
in this comparison.

The candidate is generated and saved before references, human regions, or prior
case scores are opened. References enter only for reproducing the baseline and
scoring the saved candidate with unchanged NFC/whitespace normalization and
candidate alignment. The original predictions, classifications, ownership,
decisions, reasons, and billing inclusion are preserved, including the ignored
future-billing diagnostics.

## Digital and OCR slices

| Fixed slice | Exact before | Exact candidate | Unique output before | Unique output candidate |
| --- | ---: | ---: | ---: | ---: |
| Digital pages | 10/16 | 10/16 | 14/16 | 15/16 |
| OCR pages | 3/8 | 3/8 | 8/8 | 8/8 |

The only reviewed output change occurs on a digital page. Neither slice gains
or loses an exact match. No OCR or other source recognition runs in this task.

## Validation and limits

Seventeen invented-input tests reached the expected unimplemented-helper failures
before implementation and then passed. They cover primary/continuation assembly,
geometry and Hebrew reading order, unchanged singletons and omissions, source-local
atom IDs, explicit ownership, missing primary evidence, incompatible document/page/
render geometry, empty descriptions, overlapping observations, and invalid boxes.
All four private Python files pass Ruff and strict mypy.

All 24 saved baseline scores and outputs reproduce. Independent normalized
equality checks agree on all 48 before/after exact-match outcomes, zero gains and
losses, and coverage of 22/24 versus 23/24. Independent evidence accounting checks
all 113 owner groups and preservation of all 15 assembled atom occurrences, their
source rows, and their explicit ownership. All 11 protected input files and the
frozen checkout remain unchanged. A separate read-only code review found no
actionable defects in the candidate or measurement.

Required repository verification passes: Ruff formatting and lint, mypy on 48
source files, and **3,766 tests passed** in 99.62 seconds. No production code was
changed. This is not private-corpus verification or production acceptance, and
no merge was performed.

Private source code, candidate outputs, ordered evidence references, scores, and
verification records remain under ignored
`artifacts/merchant-continuation-assembly-v1/`. Only aggregate documentation is
tracked. No private document content, identities, geometry values, or financial
data are published.

The seed remains 24 training references reviewed by one human. The coverage gain
shows that output assembly can expose a merchant description already present in
saved evidence. It does not establish improved recognition, correct reference
transcription, independently verified gold, held-out accuracy, or population
performance. Keep the original 13/24 comparator and preserve this candidate as
the measured coverage result; do not promote it as an exact-accuracy improvement.

## Stop and next recommendation

The single candidate comparison is complete. **STOP** under this authorization.
The next recommended extraction task is a bounded trace of the remaining omission
through its saved row alignment and classification, quantifying why the merchant
evidence found in other saved rows is inaccessible to the aligned row. Keep its
reference, assignment, and outputs fixed during that diagnosis. This recommendation
has not been executed.

No tuning, alternate candidate, new extraction, label repair, new labels,
expansion, gold promotion, validation/test access, or production integration is
authorized by this completed comparison.

```text
Scope: YES — measures merchant assembly from explicitly owned continuation evidence
Experiment: row-profiles
Measurement: exact merchant match, unique-output coverage, and paired gains/losses
Result: exact 13/24 to 13/24; coverage 22/24 to 23/24; 0 gains, 0 losses; accuracy hypothesis falsified
Next extraction task: STOP
```
