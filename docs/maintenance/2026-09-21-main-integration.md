# Main integration and full-corpus evaluation

Status: EVALUATION_COMPLETE — MERGE_BLOCKED by corpus acceptance failures.
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
