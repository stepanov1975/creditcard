# Local data retention and cleanup

Decisions from the 2026-09-20 inventory. This is housekeeping policy for this
cleanup, not a new experiment, garbage collector or corpus-controller design.

## Keep, clean, or defer

| Category | Decision | Reason |
| --- | --- | --- |
| `documents/`, `unrelated/` | Keep | Original retained/quarantine corpus and membership evidence. |
| Membership inventory, independent pins, accepted baseline and reviewed candidates | Keep protected | Acceptance authority; a repeated filename or older date does not make it disposable. Pins may live outside this checkout. |
| `artifacts/` | Keep | Frozen rows, outputs, reference versions, human submissions, candidate implementations, diagnostics and corpus runs. Saved scores depend on earlier versions. |
| `.superpowers/` | Keep | Includes substantial private experiment state. Private local scripts may be the only implementations of later merchant candidates and diagnostics. |
| `.worktrees/` and external registered worktrees | Keep | Frozen lanes, unmerged code, private artifacts and one dirty detached checkout. See the branch inventory. |
| `.venv/`, OCR/model caches and toolchain artifacts | Keep | Runtime identity, expensive reconstruction and potential private acceptance dependencies. Ordinary cache naming is insufficient evidence here. |
| `review/`, `.review-tmp-extraction/`, `.agents/`, `.codex/` | Keep | Review/configuration state has not been proven redundant; do not infer disposability from a temporary-looking name. |
| `src/`, `tests/`, `experiments/`, scripts and configuration | Keep | No runtime dead-code proof or behavior change is part of this task. Frozen infrastructure is explicitly retained. |
| Historical designs, plans, reports, research and old live status | Keep as evidence | Referenced authority and negative results remain useful. The evidence index and separate status history remove them from the daily reading path. |
| Root `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.coverage` | Remove after checks | Rebuildable local verification outputs; no tracked files. Future checks recreate caches. |
| `__pycache__/` under root `src/`, `tests/`, `experiments/`, `scripts/` | Remove after checks | Rebuildable bytecode only; no environment or historical worktree traversal. |

Large private areas were inventoried by filesystem metadata only. Document bytes,
merchant strings, labels, protected pin values and case-level output were not
opened or copied for this cleanup. Disk allocation and apparent file size differ;
large directory totals alone are not a deletion plan. The modest cache cleanup is
not presented as reclaiming the much larger private artifact trees.

## Preconditions for later artifact retirement

For a concrete candidate, first identify all consumers, including private scripts,
not just tracked imports. Determine whether it contains source data, reference
versions, original human submissions, runnable experiment code, accepted baseline
or membership authority, or failed-run evidence needed to explain a result.

Retire a whole private run only after proving that no retained result depends on
it, identifying an independently preserved replacement where appropriate, checking
that no process uses it, and reviewing that exact removal scope with the owner.
Do not modify protected inventories or accepted baselines to make cleanup easier.
Do not use broad `git clean -fdx`, recursive deletion of private roots, or forceful
worktree removal. This cleanup creates no recurring deletion process.

For historical branches, preserve unique commits and all ignored worktree state
before considering removal. A clean tracked Git status or a merged branch is
insufficient: ignored files do not live in Git. This task intentionally retains
all branch refs and all registered worktrees.

## Execution and recovery

The [cleanup plan](2026-09-20-cleanup-plan.md#execution-record) records exact cache
scope, verification and aggregate removed bytes. Recreate tool caches by rerunning
the normal development checks; recreate bytecode by importing/running the code.
A removed coverage file requires a new coverage run if coverage data is needed.
No source evidence or historical result requires recovery.
