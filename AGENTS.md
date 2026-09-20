# Repository Instructions

These instructions apply to the entire repository.

## Project knowledge and current state

Start with the [knowledge guide](docs/knowledge/README.md), then read only what
is relevant:

- [Domain vocabulary](CONTEXT.md) and
  [architecture and engineering lessons](docs/knowledge/architecture.md).
- [Experiment findings](docs/knowledge/experiment-findings.md), including
  branch-only results and the distinction between reference and extractor gains.
- [Live experiment status](docs/experiments/row-extraction-program-status.md)
  for the sole active phase and next allowed task; summaries do not override it.
- [Evidence index](docs/knowledge/evidence-index.md) for historical reports,
  designs, plans, and research. Old unchecked plans are not an active backlog.
- [Branch inventory](docs/maintenance/branch-inventory.md) and
  [data retention](docs/maintenance/data-retention.md) before deleting local data
  or retiring a branch/worktree.

Keep these summaries concise. Record detailed phase evidence in its report and
update the live status; do not grow another chronological diary in this file.

## Development workflow

- Use Python 3.13 and the repository virtual environment at `.venv`.
- Follow test-driven development for every production behavior: add a focused
  failing test, confirm the expected failure, implement the minimal fix, then
  rerun the focused and full suites.
- Keep modules small, typed, deterministic, and focused on one responsibility.
- Do not add filename-, path-, hash-, date-, merchant-, amount-, total-, or
  document-specific branches to make corpus cases pass. Fix the general
  extraction, geometry, semantic, or reconciliation rule instead.
- Use `Decimal` for all financial arithmetic. Never use binary floating point
  for transaction amounts or totals.
- Keep document contents and derived financial data local and out of Git.

## Required verification

Run all of the following before committing changes:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

- Use `.venv/bin/ruff format .` to format Python files.
- Resolve Ruff and mypy findings; do not suppress them unless the suppression is
  narrowly scoped and accompanied by a comment explaining an unavoidable
  third-party typing limitation.
- Add complete type annotations to public and internal functions. Avoid `Any`
  where a concrete protocol, model, or union can express the contract.

## Task-level authorization and persistence

User approval covers the full named objective and its necessary, reversible
subtasks: planning, immediate adapters, synthetic tests, input preparation,
execution, verification, documentation and local commits. Continue through these
steps without requesting approval at every phase or ending after each small task.
A “proceed” applies to the latest concrete objective in context. Do not infer a
larger objective when the user explicitly limits the request to design or review.

Maintain one active objective with a short plan and its current dependencies.
Intermediate milestones do not require new user approval or a new authority
commit. Update the existing task record rather than creating a chain of tiny
approval documents. Commit the initial experiment definition before accessing
new evaluation inputs; amend it before a substantive method/sample change.

Pause only for required human input, missing credentials/data, an unrecoverable
failure, or a material scope change. Human references must come from the declared
reviewers; do not fabricate them to avoid a pause. Complete independent work
while waiting and resume the same approved task when inputs arrive, without
asking for permission again.

Separate authorization is still required for opening protected held-out data,
changing accepted gold or protected corpus membership/baselines, destructive
retirement of unique evidence, external disclosure, production integration or
merge, and frozen infrastructure redesign. Preserve all privacy, testing and
private-corpus acceptance requirements below.

## Row-extraction experiment focus

The [focus design](docs/superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md)
and charter retain the extraction scope. The
[live status](docs/experiments/row-extraction-program-status.md) records the one
active objective, progress, dependencies and next action; it is not a new
permission gate at each subtask. The task-level policy above supersedes old
“stop after this task” and “separate approval for the next phase” wording when
those phases are necessary parts of the user's now-approved objective.
Historical results remain immutable; this policy does not reactivate unrelated
stopped experiments or authorize post-score tuning on evaluation data.

Work should improve one of the four approved extractors, measure a named
extraction metric, or quantify an extraction error. The smallest preparation,
review artifact and adapter needed for that measurement belong to the same task.
Do not build reusable controllers, CLI/schema families, receipt chains, workflow
subsystems or unrelated hardening. Preserve frozen comparison/provenance,
cascade, held-out orchestration and production-integration work as history.

Record once at the start of the experiment objective:

```text
Scope answer: YES — <how this changes or measures extraction>
Experiment: <row-ocr | row-profiles | row-text | row-vision | shared evaluation>
Extraction hypothesis: <falsifiable statement>
Measurement: <named metric or error category>
Fixed inputs: <population, split, labels, selection rule or frozen artifacts>
Smallest allowed files: <bounded implementation and output paths>
Required output: <metric delta, hypothesis result, error count or runnable extractor>
Stop condition: <objective completion, real dependency or invalid experiment>
```

Subtasks inherit that contract; do not require a new contract or approval for
each test, script or report. Freeze sampling, references, candidate rules and
metrics at their declared boundaries. Fix ordinary implementation defects within
the approved rules; do not resample difficult cases, weaken thresholds or tune
extractors after seeing evaluation outcomes.

### Measure at objective completion

Report scope, experiment, measurement, result and the next action at the end of
the objective. A negative result is valid progress. Intermediate preparation
need not itself produce an extraction score. If blocked on human review, report
quantified preparation/eligibility, clearly mark accuracy NOT MEASURED, and keep
the task AWAITING_HUMAN_REVIEW rather than marking it complete or requiring a
fresh approval. STOP is for completed objectives, invalid experiments or a user
stop—not the default after every subtask. Infrastructure alone is not a result.

## Private corpus acceptance policy

The tracked verification gates are necessary but not sufficient for any change
that can affect parsing, extraction, semantic evidence, reconciliation, OCR, or
JSON/CSV output.

- Before claiming corpus acceptance or merging such a change, commit the
  reviewed candidate, leave its worktree clean, and run the private corpus gate
  in `verify` mode with the full expected reviewed SHA. Invoke the candidate's
  own source tree, and require the same SHA and a clean worktree before the run,
  inside the gate, and immediately after success. Any subsequent code or
  configuration change invalidates the attestation and requires both tracked
  verification and private verification again.
- Require the protected retained and quarantine membership, strict retained
  reconciliation, quarantine acceptance, an independently pinned accepted
  baseline SHA-256, baseline parity, and deterministic repeated runs. In verify
  mode, require `performance_checked=true`; a complete-toolchain or worker-count
  mismatch is an acceptance failure.
- Never claim a full-corpus or all-documents pass from `pytest` or the other
  tracked gates alone. If the private gate was not run successfully, report the
  change as not corpus-verified and do not merge it.
- Treat baseline `record` mode as an exceptional, explicitly reviewed promotion
  from a clean committed revision. RECORD must use a new nonexistent candidate
  path and must never overwrite the accepted baseline. After review, pin the
  candidate's full-file SHA-256 independently and require that pin in every
  VERIFY invocation. Do not record merely to accept a failing verification or
  an unexplained semantic, structural, evidence, output, or performance change.
- Treat the independently approved membership inventory as immutable. Pin its
  full-file SHA-256 separately where `record` cannot replace it, pass that pin to
  every gate invocation, and require the accepted aggregate counts to remain
  exactly 104 retained, 104 reconciled, and 5 quarantined. `record` must never
  create, regenerate, update, or replace the inventory or its independent pin.
- Keep the corpus, inventory, baseline, outputs, caches, and derived private data
  in ignored local paths. Do not add them or their sensitive values to Git,
  tracked fixtures, commit messages, or public logs.

### Full-corpus run lessons

- Treat a direct `ccparse parse` run as a diagnostic preflight, not corpus
  acceptance. A strict retained run should report exactly 104 documents and 104
  reconciled results, and the quarantine run should report exactly 5
  `not_statement` results, but those counts alone do not prove baseline parity,
  determinism, membership, toolchain identity, or performance.
- Capture parser output privately because the normal CLI output includes source
  names. Report only the privacy-safe aggregate line; never copy per-document
  names, diagnostics, transactions, or financial values into public logs.
- Give a cold-cache full-corpus run a realistic execution bound and treat an
  interrupted or timed-out run as no verdict. Reusing OCR artifacts produced by
  the same candidate is acceptable only to resume a diagnostic preflight. The
  formal gate must still perform its required independent empty-cache runs.
- Compare large canonical outputs with constant-memory SHA-256 checks after
  validating the accepted baseline's independent pin. Avoid loading an entire
  corpus `results.json` into an additional in-memory model merely to compare it;
  the retained corpus can exceed the worker's memory limit. Require both JSON
  and CSV bytes to match both accepted baseline runs.
- Make corpus-controller shell checks fail closed with `set -euo pipefail`,
  explicitly require every external command before use, and test every captured
  value before reporting success. A missing command inside a substitution must
  never fall through to a printed pass.
- Even exact diagnostic JSON/CSV parity is not a formal `verify` attestation.
  Before merging, still require the clean independently pinned commit, protected
  membership and baseline pins, repeated deterministic runs, matching toolchain
  and worker count, and `performance_checked=true`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context domain documentation layout. See `docs/agents/domain.md`.
