# Main integration and full-corpus evaluation

Status: AWAITING_BASELINE_PROMOTION_APPROVAL — date conflicts fixed; full
diagnostic passes; formal acceptance and merge remain pending.
The user requested integration of the accumulated work and
a full-corpus evaluation before further extractor improvements on 2026-09-21.

## Candidate and plan

The reviewed implementation is `ed31951e9e8e34846376bb7a9268e32fcb8738be`.
This task record and the live-status update freeze the evaluation candidate in
the next commit. Production code remains unchanged during evaluation.

1. Confirm branch ancestry, clean status, required checks and protected inputs.
   Local and remote main both point to `661c200`; the implementation branch is
   99 commits ahead with no divergence. Its production changes are limited to
   four parser modules and their synthetic tests; other changes preserve
   experiment evidence and consolidate project knowledge.
2. Run the candidate's private gate in `verify` mode, with independently pinned
   membership and accepted baseline, four workers, fresh output/cache directories,
   and the exact reviewed candidate SHA checked before and after execution.
   Require 104 retained/reconciled documents, five quarantined documents,
   deterministic output, baseline/toolchain parity and checked performance.
3. Quantify any failures using local output and aggregate reports. If the formal
   gate cannot finish, complete a full diagnostic parse where possible and label
   it separately. Keep document identities, contents and financial values private.
4. Merge to main only after corpus acceptance. If verification fails, preserve
   the candidate and complete a concrete evaluation report before requesting any
   necessary decision. Do not alter the accepted baseline or protected membership
   to make verification pass, and do not resume extractor tuning in this task.

The controller's saved corpus and inventory paths are stale. The retained local
inventory matches its independently protected SHA-256, and the accepted baseline
also matches its protected pin. The current local corpus has 104 retained PDFs
and five quarantine PDFs; the gate must independently check their identities.
The protected controller, accepted files and their pins remain unchanged.

## Interpretation

The user's follow-up “proceed” authorizes resolving the reported date conflicts
and preparing the concrete output/runtime baseline review within this objective.
First reproduce and minimize the failure at `discover_statement`, then add
synthetic regression tests and a general metadata correction. Bounded production
files are `src/ccparser/discovery.py` and its focused tests; normalization tests
verify the downstream effect. Run all tracked checks, commit the candidate, and
measure the ten known failures and the full protected corpus. Preserve the old
baseline, membership and frozen merchant experiments. Do not promote a baseline
to conceal an unexplained difference or merge without successful formal VERIFY.

This is the repository acceptance check requested for integration, not a new
merchant-reference experiment. A balanced statement alone does not establish
complete merchant correctness. Earlier source-reviewed samples and predictions
remain frozen, human ownership reviews remain pending, and protected evaluation
labels are not opened. Any intentional output differences still need reviewed
baseline promotion under the existing acceptance policy before a merge can be
claimed corpus-verified.

## Completed evaluation

The exact clean candidate was
`88f500d0bc1ce5f34695914b350958febbb44804`, which adds only this task's plan/status
to the reviewed implementation. VERIFY completed all four independent runs with
four workers and fresh caches in **1,900.99 seconds** of controller wall time.
The candidate SHA/worktree and both independently protected pins were unchanged
before and after execution. Membership validation succeeded; the accepted
inventory, baseline and controller configuration were not modified.

| Measurement | Accepted baseline | Candidate run 1 | Candidate run 2 |
| --- | --- | --- | --- |
| Retained documents | 104 | 104 | 104 |
| Reconciled retained documents | 104 | 94 | 94 |
| Unreconciled retained documents | 0 | 10 | 10 |
| Emitted transactions | 2,231 | 2,231 | 2,231 |
| Quarantine classified `not_statement` | 5 | 5 | 5 |

Retained JSON/CSV bytes match between candidate runs, as do quarantine JSON/CSV
bytes. Neither population matches the accepted baseline bytes. Streaming JSON
counts independently agree with CSV counts without loading a whole corpus model.

The gate returned exit 2 with these reasons:
`retained_not_reconciled`, `counts_drift`, `json_drift`, `csv_drift`, `status_drift`,
`field_presence_drift`, `runtime_context_drift`. The count difference includes
reconciliation statuses; corpus membership and transaction count did not change.

## What changed, and what predates this branch

All **2,233 CSV row identities** match the accepted output, comprising 2,231
transactions and two rows for statements without transactions. No output rows
were added or removed. All shared financial, date, category, installment and FX
fields are unchanged. **196 descriptions across 42 documents differ**. The
candidate also has a `merchant` column absent from the accepted CSV; all 2,231
transactions have a nonempty merchant. These are output differences, not measured
merchant accuracy gains.

The ten failed documents all report
`conflicting_discovered_metadata:statement_date`. A separate diagnostic used an
archived copy of current main (`661c200840fbc1fbcb81385f085073617e73e449`), those
same ten documents, four workers and a fresh cache after the formal gate ended.
It reproduced **10/10 failures** in 65.93 seconds. Its **132 transaction CSV rows
are identical to the candidate's corresponding rows in every field**. Thus these
failures predate this integration branch; they are differences from the older
accepted baseline, not new failures caused by the recent merchant corrections.
This ten-document diagnostic is not a full-main corpus attestation.

Status changes affect 132 CSV rows. Batch diagnostic propagation changes the
diagnostic column on all 2,233 rows; this does not represent 2,233 independent
failures. Complete source-level change files remain private.

A diagnostic using the gate's existing isolated inspector finds only
`python_runtime_digest` differs from the accepted runtime fingerprint. Python and
dependency versions, dependency byte records, worker count and all other recorded
fingerprint components match. The accepted digest does not retain its underlying
runtime payload, so this comparison does not identify the exact changed runtime
attribute. **Performance acceptance was not checked**, because matching runtime
context is required. The elapsed wall time is not a valid speed-regression score.

## Result files and integration decision

Ignored `artifacts/main-integration-evaluation/` contains the gate log/result,
repeatability and CSV comparison JSON, independent JSON count check, isolated
runtime comparison, archived-main diagnostic, and three focused review files:

- `document-summary.csv`: 104 document statuses and change counts;
- `failed-documents.csv`: ten statement-date failures, all reproduced on main;
- `description-changes.csv`: 196 before/after description values.

The detailed private CSV also includes all field differences. Source documents,
outputs, caches, protected pins and financial values remain outside Git. Local
and remote main are unchanged; no merge or push was performed.

The [acceptance policy](../../AGENTS.md#private-corpus-acceptance-policy) requires:
“If the private gate was not run successfully, report the change as not
corpus-verified and do not merge it.” A reviewed baseline promotion alone cannot
accept ten unreconciled retained documents.

Next: resolve the pre-existing statement-date metadata conflicts, then review
the intentional complete-merchant/output-schema changes and the current runtime
for a separately authorized baseline promotion. Preserve the accepted baseline;
record any approved replacement at a new path, independently pin it after review,
and obtain a clean full VERIFY before fast-forwarding main. No parser tuning,
baseline promotion or new merchant experiment was performed during this task.

The required tracked checks remain green: Ruff format/lint, mypy and **3,819
tests** on the unchanged implementation. This task adds only plan/result/status
documentation to tracked files. Earlier merchant reference and ownership reviews
remain frozen with their existing human dependencies.

## Date-conflict remediation

The cached discovery reproduction fails in about four seconds. All ten affected
documents expose two to four distinct charge-total dates under the same label;
these are payment-group dates, not conflicting statement identities. Remove
that label from the statement-date vocabulary, preserving explicit statement
labels and their existing conflict rejection. No date value, document identity,
geometry exception or reconciliation threshold is special-cased.

Four synthetic combinations (one/multiple charge dates, with/without an explicit
statement date) fail under the old vocabulary and pass after the correction.
A contradictory-explicit-date control still fails reconciliation as intended.
The existing inline metadata example now uses a statement-level label rather
than asserting the incorrect charge-date interpretation. Cached document
discovery/normalization now reconciles **10/10 documents and 132 transactions**;
this diagnostic is not full corpus acceptance.

All **3,824 tests**, Ruff format/lint and mypy pass for this correction.

Next: freeze the tested correction, run the complete retained/quarantine
diagnostic with fresh caches, compare all emitted fields and prepare the concrete
baseline-promotion review. The accepted baseline and its independent pin remain
unchanged. Formal VERIFY remains required after any approved baseline promotion.

## Corrected full-corpus diagnostic

The clean committed correction `0e3e68520957d07c85df7011fbb222ce97f60025`
completed a fresh-cache, four-worker diagnostic over the unchanged independently
pinned membership. All **104 retained documents reconcile**, with **2,231
transactions**; all **five quarantine documents are `not_statement`**. Retained
execution took 714.25 seconds and quarantine 26.21 seconds. These diagnostic
timings are not a formal performance comparison. The exact SHA, clean worktree,
membership and accepted baseline pins were checked before and after the run.

All 2,233 CSV row identities match both the frozen candidate and the authenticated
accepted output. Compared with the frozen candidate, only status (132 rows) and
propagated diagnostics (2,233 rows) change; every transaction field is identical.
Compared with the accepted baseline, only the added merchant field (2,231 rows)
and description (196 rows across 42 documents) differ. No financial, transaction
date, installment, FX, category, row identity or status difference remains.

The streaming JSON comparison confirms that only the ten documents' status and
diagnostics, batch status/diagnostics, and 30 statement-date metadata values
change. Those 30 values were all supported by charge-total labels; the other
56 statement dates remain unchanged. Transaction objects, normalization rows,
groups, geometry, printed totals and date-year context are identical to the
frozen candidate. Quarantine JSON and CSV are byte-identical to that candidate.
An independent streaming count confirms the diagnostic CSV counts.

The 196 description changes comprise 20 extensions, 136 shortenings and 40 other
text/order changes. These are the accumulated field-ownership changes, not the
date correction. The private before/after review file groups them accordingly;
this classification does not establish source-adjudicated merchant accuracy.

## Concrete remaining decision

The private `artifacts/main-integration-evaluation/date-fix/` packet contains
diagnostic results, CSV/JSON comparisons, the description review and the proposed
promotion procedure. No accepted baseline, membership, gold reference or protected
evaluation label was changed. Main remains unchanged.

Baseline promotion requires explicit authorization under
[AGENTS.md](../../AGENTS.md#task-level-authorization-and-persistence): “Separate
authorization is still required for ... changing accepted gold or protected
corpus membership/baselines”. This is the remaining policy dependency, not a
request to approve another implementation subtask.

The prepared action is to RECORD at the new, nonexistent private path
`.superpowers/private/corpus-baseline-main-integration-date-fix.json`, preserving
the old baseline and independent membership pin. Retain four workers and the
existing `0.20` runtime tolerance. Review the repeated recorded output against
this diagnostic and the preserved baseline, then independently pin the new
baseline in the private controller. Require full VERIFY on that same clean,
reviewed revision with repeated fresh caches and `performance_checked=true`.
Only then fast-forward main. Unexpected output, count or performance differences
remain failures; no acceptance threshold is weakened.
