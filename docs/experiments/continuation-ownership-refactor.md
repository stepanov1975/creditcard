# Continuation ownership deepening

Status: COMPLETE — implemented, reviewed and corpus-verified; merged into local `main`.
The original refactor was authorized by the user's “implement 1” instruction on
2026-09-21; the later “run final review and merge if green” instruction authorized
verification and integration after the original implementation objective.

```text
Scope answer: YES — preserve merchant-field extraction while concentrating continuation ownership
Experiment: row-profiles
Extraction hypothesis: One ownership assembly preserves exact merchant fields, transaction ownership, row diagnostics and reconciliation for same-page chains and cross-page detail handoffs
Measurement: synthetic exact merchant fields, evidence ownership, transaction identifiers, diagnostic ordering and reconciliation; existing rejection controls
Fixed inputs: invented positioned rows and existing tracked synthetic tests only; no private evaluation inputs or frozen scored cases
Smallest allowed files: src/ccparser/normalization_continuations.py, src/ccparser/normalize.py, tests/test_normalize.py, CONTEXT.md, this report and linked status/knowledge summaries
Required output: runnable bounded refactor with a focused red/green ownership test and passing repository gates
Stop condition: implementation and verification complete, or a real dependency; no production merge or baseline promotion
```

## Plan and test seams

1. Characterize a wrapped merchant chain followed by a cross-page detail handoff
   at `normalize_statement`, preserving full text, evidence, identifiers and diagnostics.
2. Test group-level continuation ownership assembly at its caller-facing interface;
   confirm the expected failure before implementing it. Assemble each same-page
   chain once, then attach proven cross-page details, retaining existing guards.
3. Have statement normalization consume assembled ownership and its diagnostics.
   Run focused and full repository verification, review the diff, and commit locally.

The selected recommendation and task-level authorization cover these test seams.
Existing continuation geometry and financial interpretation remain unchanged.
No adapter family, scanner-state redesign, corpus infrastructure, fresh evaluation,
private-corpus acceptance claim or production integration is part of this refactor.
Private-corpus verification is required before a later acceptance claim or merge.

## Result

The new `assemble_continuation_ownership` interface accepts a discovered group and
returns immutable region/row ownership, with attached continuation diagnostics.
Each same-page chain is walked once. Cross-page details are retagged on copies,
attached to the established owner and removed from later primary-row processing.
Statement normalization no longer maintains handoff identity maps, reconstructs
chains or interprets continuation diagnostic tags. It still owns financial
interpretation, result emission and transaction numbering.

The existing geometric predicate stays in description extraction; scanner
recognition, thresholds and state were not redesigned. The original prefix guard
checks source rows, including tags on consumed continuation rows, so assembly
cannot conceal a late leading-detail tag and enable a previously rejected handoff.

The wrapped-chain/cross-page characterization passes on the original implementation.
The new ownership-interface test first failed with the expected missing-module
error, then passed after implementation. A separate guard regression first failed
on the candidate and passed after restoring the source-row prefix check.

Focused normalization and description verification: **389 tests passed**. A
temporary differential harness ran the normalization suite against both the
original `e7dc34d` implementation and the candidate: **278 complete normalization
outputs match**, including transactions, evidence, diagnostics, IDs and reconciliation;
all **312 tests** passed in that comparison run. These are synthetic compatibility
results, not extraction gains. No private documents or frozen predictions were used.

All **3,827 repository tests pass** (104.45 seconds), together with Ruff format,
Ruff lint and mypy (49 source files). The first sandboxed full run passed 3,817
and failed ten corpus-gate tests whose fixtures require process tracing and sealed
filesystem access; the complete rerun with those local permissions passed unchanged.
The private corpus gate was not executed by these synthetic tests.

Fresh-document accuracy is **NOT MEASURED**. Private-corpus VERIFY is not part of this result; this candidate
must pass that gate before any acceptance claim or later merge. Next: predeclare a fresh-document merchant-field ownership evaluation; before any
later integration, verify this committed candidate through the private corpus gate.


## Final review, acceptance and integration

The final review compared `cb0788acf56ebd46570cbb431cc6131885f194ab` with
`e7dc34d448e6d92a69956bd5580a695f5c9e2654`. Separate Standards and Spec reviewers
both reported **zero actionable findings**. The Spec reviewer independently passed
six focused ownership/handoff tests. The previously completed **3,827-test** full
suite, Ruff and mypy results apply to the unchanged implementation.

Formal private-corpus **VERIFY passed** for that exact clean reviewed candidate,
using its own source, four workers, the existing independently pinned membership
and accepted baseline, two fresh retained runs and two fresh quarantine runs:

```text
status=passed mode=verify retained=104 reconciled=104 quarantined=5 elapsed_seconds=1615.090111617 performance_checked=true
```

The reviewed SHA and clean worktree were checked before invocation, within the
gate and immediately after success. Both protected pins and controller configuration
remained unchanged. Baseline parity, repeated determinism, complete toolchain and
worker identity, retained reconciliation, quarantine acceptance and performance
all passed. No RECORD, baseline promotion, membership change or held-out access
was performed. Detailed evidence stays in ignored
`artifacts/continuation-ownership-acceptance/`.

Local `main` was fast-forwarded from `e7dc34d` to the exact verified candidate
`cb0788a`. This acceptance record and the linked knowledge/status updates are
subsequent documentation-only changes; no attested parser, test or configuration
changed. No remote push was performed.

Scope: final review and regression acceptance of continuation-ownership deepening.
Measurement: protected-corpus parity and performance with deterministic repeats.
Result: PASS and local merge complete. Fresh-document merchant accuracy remains
NOT MEASURED. Next: predeclare the fresh-document merchant-field ownership evaluation,
preserving the existing frozen evaluations and human-review dependencies.
