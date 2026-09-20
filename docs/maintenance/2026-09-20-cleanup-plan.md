# Repository knowledge and cleanup plan

Written before implementation on 2026-09-20. Base: merchant-gold-seed at
`6c500cc11d8abef809527e491605b322b9c34cf6`.

## Scope and acceptance

This is the user's explicitly requested repository housekeeping and knowledge
consolidation, not a row-extraction experiment. It runs no extraction, opens no
labels, changes no production behavior, and does not reactivate stopped work.
The focus lock, charter, protected corpus policy, and all source evidence remain
in force. No new extraction metric or corpus acceptance is claimed.

The result must provide a short reading path from AGENTS.md, retain traceable
historical evidence, capture results unique to side branches, and remove only
identified reproducible local leftovers. No source or test deletion is justified
merely by age, lack of imports, or a stopped experiment.

## Inventory findings

- 13 local branches, three remote branch heads, one published annotated release
  tag, and 14 registered worktrees. Remote heads were checked directly and match
  the available remote-tracking refs.
- The latest branch is clean. One detached external worktree has five changed
  or untracked entries; preserve it without modification.
- There are 140 tracked documentation files under docs. The live experiment
  status has accumulated a long reverse-chronological history.
- Round 2 outcomes and older semantic/preparation designs exist on side branches.
  Several frozen branches have commits absent from the latest branch; they are
  not safe deletion candidates.
- Most disk usage is private artifacts, private experiment workspace state, and
  historical worktrees. Age and repeated run names do not prove redundancy.
  Ordinary Python/test/linter/type-check caches are reproducible leftovers.

## Ordered implementation

1. **Distill knowledge.** Add `docs/knowledge/README.md`, `architecture.md`,
   `experiment-findings.md`, and `evidence-index.md`. Cover current contracts,
   code boundaries, Round 1 and branch-only Round 2, failed gold/context attempts,
   merchant reference versions and results, negative findings, and limits.
   Link every measured conclusion to its report or immutable branch revision.
2. **Separate present from history.** Keep the existing authoritative path
   `docs/experiments/row-extraction-program-status.md` as a short live record.
   Preserve its original complete text in
   `docs/experiments/row-extraction-program-history.md`, clearly marked historical.
   Preserve current STOP, frozen heads, authority links, and latest unexecuted
   recommendation. Do not relocate binding designs, reports, or old plans.
3. **Make navigation explicit.** Link the compact knowledge set and live status
   from AGENTS.md and README.md. Keep the full existing AGENTS.md policies.
   Make the old research/plan material discoverable as evidence, not a task queue.
4. **Record retention decisions.** Add `docs/maintenance/branch-inventory.md`
   with every branch head, ancestry, unique work, detached worktree findings,
   release tag, and disposition. Add `docs/maintenance/data-retention.md` with
   private-data categories, protected inputs, disposable-cache scope, and exact
   prerequisites for any later destructive cleanup. Include branch-only documents
   and a retrieval recipe without copying private data into Git.
5. **Clean verified leftovers.** After verification, remove only root-worktree
   `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.coverage`, and `__pycache__`
   directories under `src`, `tests`, `experiments`, and `scripts`, after checking
   they contain no tracked files and are not symlinks. Preserve environments,
   OCR/model caches, source documents, private scripts/results, all worktrees,
   branches, release references, and unclassified local review files.
6. **Verify and report.** Check local Markdown destinations and code links;
   check branch-only citations with Git; confirm preserved status text and STOP;
   run the four repository gates. Record aggregate cleanup counts and bytes,
   final tracked diff, and limits in this plan. No commit, merge, private-corpus
   rerun, network publication, or experiment execution is needed for these docs.

## Stop condition

Stop once navigation, summaries, inventories, and safe cache cleanup are complete
and verified. Deferred destructive deletion is a recorded retention decision,
not authorization to build cleanup machinery or resume frozen infrastructure.

## Execution record

Implemented the knowledge guide, architecture and findings summaries, complete
evidence index, branch inventory, retention guide, and AGENTS/README navigation.
The live status shrank from 1,050 to 81 lines; its original text remains verbatim
in the history snapshot. All existing AGENTS development/acceptance policies
remain unchanged. The experiment remains stopped.

Coverage: 13 local branches, three verified remote heads, the release tag, 14
worktrees, and all 140 original tracked documentation paths. The branch inventory
adds retrieval links for 14 branch-only documents. Findings include the previously
missing Round 2 terminal outcomes. Private areas were reviewed by metadata and
existing aggregate reports, not by reopening source documents, labels or held-out
inputs.

Completed verification:

- 229 local Markdown destinations and five heading anchors resolve.
- All 15 immutable Git citations resolve locally.
- Original status text is preserved verbatim and existing AGENTS policies match.
- Ruff format: 195 files already formatted; Ruff lint passes.
- Mypy: no issues in 48 source files.
- The sandboxed full suite returned 3,756 passes and ten corpus-gate failures.
  All ten passed outside the sandbox (1.28 seconds), consistent with filesystem
  and process-tracing restrictions. The full unrestricted rerun passed: **3,766 tests in 99.62 seconds**.

Only Markdown is changed: three modified and eight new files. No branch head,
production source, tests, configuration, private evidence or historical worktree
was modified. No commit, merge, push or private-corpus acceptance claim is made.

Cache cleanup completed after all checks: removed **17 cache targets,
256 files, 26,953,395 apparent bytes (9,138,176 allocated file bytes)**.
The targets were the four named root verification outputs and 13 bytecode
directories under the four approved source/test/script roots. Before deletion,
all targets were rechecked for tracked-file membership and symlinks; bytecode
directories contained only `.pyc` files. Every target is now absent.

No old private artifact was declared redundant without proof. Large private
trees and all worktrees remain retained under the documented policy; this task
does not claim a full private-data deduplication or source-content audit. The
bounded plan is complete; no destructive follow-on or experiment is active.
