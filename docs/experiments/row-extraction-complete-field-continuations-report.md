# Complete merchant-field continuation improvement

Status: COMPLETE — bounded implementation and synthetic verification finished. Authorized by the user's 2026-09-21 instruction to proceed
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

## Implementation and measured result

Three general defects were reproduced before their fixes:

- Discovery rejected numeric-only, currency-shaped, amount-shaped, date-shaped
  and installment-shaped continuation text even when the whole cell was inside
  the description column. Such cells now retain their field ownership. The
  existing alignment tolerance is not extended to typed fragments crossing the
  field boundary.
- Discovery checked transaction shape on the immediately preceding line. A
  second owned continuation has no date or billed amount, so discovery stopped
  before reaching later transactions. It now checks the original regular row
  for transaction shape and the latest accepted line for adjacency. A leading
  fragment cannot provide that owner.
- Normalization required exactly one description cell on a continuation. It now
  keeps multiple cells when all belong to the description field; extra cells
  outside that field still require separate ownership evidence. Discovery already
  projects split words into header bands, so it needed no new cell-merging rule.

The final synthetic matrix contains **29 positive complete-field cases**: seven
text shapes, one/two continuation lines, unsplit/split positioned words, plus one
normalization case with separately supplied continuation cells. It checks complete
merchant/description text, both transactions and exact reconciliation. **Nine
negative controls** check date/amount columns, left/right boundary crossings,
distant text, an unowned leading fragment and extra date/amount/unknown columns.
The leading fragment conservatively leaves discovery ambiguous rather than
attributing it to a later transaction.

Replaying these same tests against the original source at `aa19181` gives
**9/29 positive cases passing and 9/9 rejection controls passing**. The candidate
passes **29/29 and 9/9**, respectively: **20 corrected synthetic cases, zero control
regressions**. These are development regressions, not sampled accuracy estimates.
Both original and candidate logs/XML are ignored under
`artifacts/complete-field-continuations-v1/`. The replay uses an isolated original
source tree; no tracked checkout or frozen private artifacts were changed.

The four focused suites pass **728 tests**, including the existing future-billing
exclusion tests. No future-billing rule was changed. No private evaluation pages,
validation inputs or held-out data were opened, and the old 89-case score remains
unchanged. Fresh-document accuracy is **NOT MEASURED**. The synthetic hypothesis
is supported for the tested cases; generalization remains unmeasured.

The next evaluation step is a predeclared fresh sample after freezing this
candidate, with source-reviewed complete-field references. The old ownership
packet remains available for human confirmation; its pending review does not
prevent recording this completed implementation. Production merge and corpus
acceptance require the separate formal private-corpus gate, which was not run.

## Final verification

Repository Ruff formatting and lint, mypy, and all **3,802 tests** pass
(100.26 seconds). Independent aggregation of the baseline/candidate test XML
confirms 9/29 to 29/29 positive cases and unchanged 9/9 rejection controls.
All changed documentation links resolve. Only general source rules, synthetic
tests and aggregate documentation are tracked. Private-corpus verification was
not run; no merge, baseline promotion or corpus-acceptance claim was made.
