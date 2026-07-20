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
