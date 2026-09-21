# Merchant field ownership correction

Status: COMPLETE — implementation and repository verification finished. Authorized by the user's
2026-09-21 instruction to proceed. Initial plan committed at `9095916`.

```text
Scope answer: YES — correct geometric merchant ownership and continuation loss
Experiment: row-profiles
Extraction hypothesis: Positioned column ownership prevents outside-field text inclusion, and merchant-only leading lines survive a following conversion-detail block
Measurement: exact synthetic merchant fields, transaction counts, evidence ownership and financial reconciliation; boundary/detail rejection controls
Fixed inputs: invented positioned pages/rows only; existing complete-field contract; no private scored pages, validation or held-out inputs
Smallest allowed files: normalization_description.py, normalize.py ownership adapter, layout/regions.py and its existing row_tags.py adapter, existing description/normalization/layout tests, this report and linked status/knowledge summaries
Required output: runnable general fixes with failing-before/passing-after regressions and full repository verification
Stop condition: bounded corrections and verification complete, or a real dependency; no frozen-evaluation rescore, production merge or baseline promotion
```

## Plan

1. Reproduce cross-column inclusion at the existing public `extract_description`
   and `normalize_statement` seams. Respect independently positioned evidence in
   a separate column even when cell clustering places it with the merchant.
   Preserve codes and marker-looking text inside the merchant field.
2. Reproduce merchant-only leading continuation lines swallowed by a subsequent
   conversion-detail block through `discover_statement` and `normalize_statement`.
   Preserve their field ownership without incorporating separate fee/conversion
   explanations, following transactions or disconnected lines.
3. Develop one failing test and minimal general correction at a time. Use the
   existing public `detect_table_regions` seam for a conservative ownership control. Run focused
   ownership controls and all required repository gates. Record actual synthetic
   results, limitations and next measurement, then commit the candidate.

The user's task-level authorization includes these existing public test seams;
no additional subtask approval is required. Frozen evaluation artifacts and human
ownership dependencies remain unchanged. Aggregate findings motivate these rules,
but their scored documents are not development inputs. Success on synthetic cases
does not establish a gain on those documents or fresh-document accuracy.

## Implementation and synthetic result

Two general ownership corrections are implemented:

- Description extraction respects whole positioned clusters contained in one
  separate UNKNOWN column and outside the description column. It assigns those
  clusters ancillary ownership even if a larger cell's center lands in the
  merchant column. It retains the same letters, numbers and currency-shaped text
  when they are inside the merchant field; it does not infer business identity.
- A bounded conversion-detail block can include leading merchant continuations.
  Discovery preserves their ownership when they fit the description column/primary
  merchant extent and a subsequent wider, explicitly marked detail establishes
  the boundary. Once detail starts, later narrow note lines stay detail. An
  existing row-tag adapter conveys that ownership to description extraction and
  excludes those merchant rows from FX interpretation. Otherwise a numeric code
  was incorrectly reconsidered as an unparsed fee. No fee parser was redesigned.

Date-shaped merchant text is admitted under that same ownership proof. When no
separate detail boundary is found, it cannot silently become discarded detail.
Existing detail-only blocks retain their interpretation. Block lengths, adjacency,
billed fields, next-transaction requirements and financial arithmetic are unchanged.

The final matrix has **11 positive cases** (three outside-column indicators and
eight complete continuation cases) and **six controls** (three inside-field
preservation cases, two detail-only blocks and an unproven date/detail boundary).
Continuations cover reference numbers, date-shaped text, a name containing “Fee”,
and one/two wrapped lines. End-to-end cases also check both transactions, original
and billed amounts, note-tail exclusion and exact reconciliation.

Replaying these tests against `c596caea4a99cca45744f5e16571f318168bbadd` produces
**0/11 positive passes and 6/6 control passes**. The candidate passes **11/11 and
6/6**: **11 corrected synthetic cases, zero control regressions**. The same tests
run against an isolated archived source tree and the candidate; XML, logs and
aggregate JSON are ignored under `artifacts/field-ownership-v1/`. No private
documents or saved evaluation predictions were opened or rescored. The focused
description, normalization, region and row-tag suites pass **592 tests**.

## Limits and next measurement

The synthetic hypothesis is supported for these layouts. The first correction
requires a resolved separate UNKNOWN column; it does not discover an indicator
band hidden inside an inferred description column. The second requires a leading
merchant portion followed by a distinct detail boundary; it does not resolve every
mixed row or visually ambiguous note. These are deliberately bounded rules, not
evidence that the frozen pilot's 16 indicators and six omissions are corrected.

Fresh-document accuracy is **NOT MEASURED**. Next: freeze this candidate, predeclare
a separate fresh sample and complete-field/ownership measurement, then evaluate
against source-reviewed references. Existing human ownership packets remain
pending, with their scored artifacts unchanged. Private-corpus verification was
not run; no merge, accepted-gold change, corpus promotion or acceptance claim is
part of this result.

## Final verification

Ruff format/lint, mypy and all **3,819 repository tests** pass (102.83 seconds).
Independent comparison of the 17 matching test identities in baseline/candidate
XML confirms 11 gains and zero losses. Changed-document links resolve and the
Git whitespace check passes. Only general parser rules, invented tests and
aggregate documentation are tracked; the private acceptance gate remains unrun.
