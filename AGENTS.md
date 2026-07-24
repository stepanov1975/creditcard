# Repository Instructions

These instructions apply to the entire repository.

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

## Agent skills

### Issue tracker

Issues and PRDs are tracked as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context domain documentation layout. See `docs/agents/domain.md`.
