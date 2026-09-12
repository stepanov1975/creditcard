# Merchant Discovery Exclusion Trace

**Status:** Complete — STOP.

**Authority:** The user's “proceed” approved this bounded trace under the
[design](../superpowers/specs/2026-09-12-merchant-discovery-exclusion-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-discovery-exclusion.md), and charter
amendment committed at `290efb2` before private execution.

## Finding

**All four reference regions are covered by a candidate table that the parser
explicitly excludes as future billing.** The filter hypothesis is supported for
4/4 cases. Discovery first finds two candidate tables with 46 rows, then removes
the eight-row future-billing table and retains the other 38 rows.

The trace reproduces the saved one-page discovery object exactly. No new source
extraction, OCR, rule change, or reference correction was performed. The best
measured merchant comparator remains **10/24**, with the original four alignment
failures preserved.

## Measured decisions

| Observation | Cases with eligible row coverage |
| --- | ---: |
| Initial candidate tables | 4/4 |
| Candidate marked as future billing | 4/4 |
| Singleton candidates from the excluded table | 4/4 |
| Candidate cleared as transaction history | 0/4 |
| Accepted rows in rejected scans | 0/4 |
| Scan stopped directly on a target row | 0/4 |
| Final discovered rows | 0/4 |

The observer captured one initial-region detection call, 29 header/inherited
scans with three recognized headers, and ten future-billing predicate calls.
Nine predicates returned true: the eight-row candidate table and eight singleton
candidates. The resulting 16 filtered row observations represent **eight distinct
row boxes**, not 16 distinct missing rows. The singleton fallback applies the
same future-billing exclusion, so it does not restore this table.

The transaction-history filter did not fire. No case remains unresolved under
the predeclared exclusion categories: all four are `future_billing_filter`.
This attributes the observed exclusion; it is not a new human annotation of
transaction eligibility.

## Rule and intended scope

In the frozen deterministic checkout at
`a2ed73aa58a4e4d8c76f918657d083fa922537d4`,
`src/ccparser/discovery.py::_is_future_billing_region` selects the nearest
preceding same-page row above the candidate header. The predicate requires a
positive heading height, a gap no greater than two heading heights, and a match
to the existing future-billing heading vocabulary. `discover_statement` removes
matching table regions and also filters matching singleton candidates.

An independent check of both initial candidates agrees with their observed
filter decisions using the existing strict whole-phrase matcher and direct
heading/gap comparisons. One candidate meets these conditions; the other does
not. The observed exclusion does not depend on the looser compact/prefix phrase
fallback. Source heading text and geometric values remain private.

The frozen regression
`test_explicit_future_billing_table_is_outside_current_cycle_scope` explicitly
expects future-billing transactions to be excluded from current-cycle output.
Both its English and Hebrew synthetic cases pass. This supports the conclusion
that the observed filter implements intended parser scope rather than an
accidental loss in OCR or row construction. It does not independently certify
the scope of every human-marked transaction.

## Implication for the merchant reference dataset

The [seed instructions](../superpowers/specs/2026-09-12-merchant-gold-seed-design.md)
ask for the first four complete transactions beginning on each page, in visible
reading order. The actual review worksheet follows that instruction. Neither
restricts review to transactions billed in the current cycle.

The merchant seed and the parser's current-cycle inclusion policy therefore have
different scope for these four cases. Their absence from final table rows should
not be treated as demonstrated inability to read merchant-bearing evidence. No
finding here establishes that the user's merchant transcriptions are wrong.

Keep all 24 reviewed references and the historical 10/24 comparison unchanged.
The recommended next comparison measures merchant recognition before the
future-billing filter, while keeping current-cycle inclusion as a separate parser
decision. Report its coverage and paired exact-match changes against the fixed
10/24 comparator. Do not remove four references or shrink the denominator to
improve the score, and do not change production billing inclusion to make the
merchant benchmark pass.

This remains a small training calibration set with one human reviewer. No
held-out accuracy, population accuracy, independently certified gold, or
production acceptance claim follows.

## Validation and retained evidence

- Eleven invented-input attribution tests were observed failing before the
  implementation and now pass. They include unrelated filter hits, overlap
  eligibility, and unresolved outcomes.
- The four-file private observer/analysis passes Ruff formatting, lint, and
  strict mypy. It observes returns without changing arguments or decisions.
- The observed discovery object exactly equals the saved one-page result.
  Independent predicate checks agree for both initial tables; no second
  discovery execution was needed for that check.
- All 13 protected original files remain byte-identical, including saved source
  evidence/discovery, references, frozen rows, alignment, and merchant scores.
  The frozen checkout remains unchanged.
- Required repository gates pass: Ruff format/check, mypy on 48 source files,
  and **3,766 tests passed** in 100.32 seconds. The two named frozen
  future-billing regression cases also pass.

Private trace records, case diagnostics, and input checks remain under ignored
`artifacts/merchant-discovery-exclusion-v1/`. No private text, identities,
coordinates, source images, or financial values are committed or printed.
No production code changed; this is not private-corpus verification and no merge
was performed.

## Stop and next recommendation

The single trace is complete. **STOP** under this authorization. The next
recommended extraction task is one merchant comparison using candidates before
the future-billing filter on the same 24 references, preserving production
transaction decisions and measuring paired gains/losses against 10/24.
That comparison has not begun.

```text
Scope: YES — quantifies the discovery rule excluding four merchant references
Experiment: shared evaluation
Measurement: candidate coverage and explicit-filter case counts
Result: future-billing filtering explains 4/4 exclusions; hypothesis supported
Next extraction task: STOP
```
