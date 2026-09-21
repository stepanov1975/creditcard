# Merchant field ownership correction

Status: IN_PROGRESS. Authorized by the user's 2026-09-21 instruction to proceed.

```text
Scope answer: YES — correct geometric merchant ownership and continuation loss
Experiment: row-profiles
Extraction hypothesis: Positioned column ownership prevents outside-field text inclusion, and merchant-only leading lines survive a following conversion-detail block
Measurement: exact synthetic merchant fields, transaction counts, evidence ownership and financial reconciliation; boundary/detail rejection controls
Fixed inputs: invented positioned pages/rows only; existing complete-field contract; no private scored pages, validation or held-out inputs
Smallest allowed files: normalization_description.py, layout/regions.py, existing description/normalization/layout tests, this report and linked status/knowledge summaries
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
3. Develop one failing test and minimal general correction at a time. Run focused
   ownership controls and all required repository gates. Record actual synthetic
   results, limitations and next measurement, then commit the candidate.

The user's task-level authorization includes these existing public test seams;
no additional subtask approval is required. Frozen evaluation artifacts and human
ownership dependencies remain unchanged. Aggregate findings motivate these rules,
but their scored documents are not development inputs. Success on synthetic cases
does not establish a gain on those documents or fresh-document accuracy.
