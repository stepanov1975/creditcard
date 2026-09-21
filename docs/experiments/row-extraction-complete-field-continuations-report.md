# Complete merchant-field continuation improvement

Status: IN_PROGRESS. Authorized by the user's 2026-09-21 instruction to proceed
with complete merchant-field capture, continuations and missing transactions.

## Objective and fixed scope

```text
Scope answer: YES — preserve merchant continuation evidence and downstream transaction discovery
Experiment: row-profiles
Extraction hypothesis: Geometrically owned merchant continuations survive token shape and cell splitting without absorbing separate financial columns
Measurement: complete merchant text and emitted transaction counts on synthetic positioned evidence, with ownership rejection controls
Fixed inputs: synthetic pages/rows only; full printed-field contract; no private evaluation, validation or held-out inputs
Smallest allowed files: normalization_description.py, layout/regions.py, focused normalization/discovery tests, this report and linked status/knowledge summaries
Required output: runnable deterministic fixes, failing-before/passing-after synthetic regressions, full verification results
Stop condition: bounded fixes and verification complete, or a real dependency; no frozen-evaluation tuning or production merge
```

The previous 89-case evaluation remains frozen and awaiting human ownership
confirmation. Its aggregate error categories motivate this work, but neither its
source documents nor case predictions are development inputs. This work will not
claim a new-document accuracy delta or alter its references, predictions or scores.
Accepted gold, corpus membership/baselines and frozen infrastructure are unchanged.

## Plan

1. Reproduce loss through existing public `discover_statement` and
   `normalize_statement` interfaces using invented positioned words. Use
   `is_description_continuation` for focused ownership controls as needed.
2. Accept complete continuation text inside a proven description column even
   when numeric/currency-shaped or split into multiple cells; preserve ownership,
   page, gap and structural boundaries. Change only rules shown defective by a
   focused failing regression, one slice at a time.
3. Verify downstream transactions survive continuation handling. Preserve rejection
   of separate amount/date fields, true future-billing sections and unrelated text.
   Do not relax future-billing filters without a separately demonstrated defect.
4. Run focused suites and all repository gates; record actual before/after results
   and limitations, update the knowledge summary and commit the reviewed candidate.
   Do not merge or claim private-corpus acceptance without its formal gate.

The user authorizes necessary synthetic tests as part of the whole objective;
these existing public test boundaries require no separate subtask approval.
