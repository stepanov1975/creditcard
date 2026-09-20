# Branch and worktree inventory

Reviewed 2026-09-20 against merchant-gold-seed at `6c500cc11d8abef809527e491605b322b9c34cf6`. Counts describe that pre-cleanup base, not future branch tips.

All 13 local branch histories and tracked-file differences were inspected. The
three live remote heads were checked with `git ls-remote --heads --tags origin`
and exactly matched the local remote-tracking refs. No remote-only branches were
found. No refs were fetched, moved, merged, deleted or pushed.

## Local branches

“Only latest / only branch” counts commits on each side of the merge base;
it is an ancestry count, not proof of semantic equivalence or patch redundancy.

| Branch | Full head | Only latest / only branch | Disposition |
| --- | --- | --- | --- |
| `codex/merchant-gold-seed` | `6c500cc11d8abef809527e491605b322b9c34cf6` | 0 / 0 | Latest merchant reference, measurements and documentation; cleanup applied here. |
| `codex/release-v0.1.0` | `909f91bd3dc643fd8566925a81f10f1522ccf9bc` | 85 / 0 | Published release; ancestor of latest. Retain immutable release evidence. |
| `codex/row-experiment-deterministic` | `a2ed73aa58a4e4d8c76f918657d083fa922537d4` | 147 / 8 | Frozen Round 1 profiles; unique extractor and handoff work. Preserve. |
| `codex/row-experiment-foundation` | `fcaf40e0337b06ca8c26e906d22ca03683f52762` | 174 / 69 | Unmerged combined preparation/observation foundation. Frozen; preserve. |
| `codex/row-experiment-ocr` | `9bc582c6876d4e2adba7e19cf2ba1968c5ab2625` | 147 / 5 | Frozen Round 1 OCR; unique extractor and failed validation evidence. Preserve. |
| `codex/row-experiment-text` | `d573b7f8d5239ca3ff92cbc7bf5475f5ced2ab0a` | 147 / 15 | Frozen Round 1 text; unique tagging/calibration and stop evidence. Preserve. |
| `codex/row-experiment-vision` | `40f748395c07bb4d2da6658b92087be471681264` | 147 / 13 | Frozen Round 1 vision; unique matched models and no-gain evidence. Preserve. |
| `codex/row-extraction-round2` | `295c4ab5a422d1aed92bb73c35fa43ca63f34ddb` | 131 / 9 | All four Round 2 implementations and terminal results. Preserve. |
| `codex/row-observation-core` | `e2287b40f1dd772487482e9d7bc0bc7cee37be96` | 174 / 57 | Unmerged immutable snapshot and observation/direction-proof work. Frozen; preserve. |
| `codex/row-preparation-runtime` | `6d7c7ba83b23d6cff05265e9fffd0e7ba58ed508` | 174 / 63 | Unmerged worker/bootstrap authority work and amendments. Frozen; preserve. |
| `codex/row-prepared-contracts` | `19058757679777e3116827ddd1d4d700f298759a` | 174 / 60 | Unmerged private artifact and split-sealing contracts. Frozen; preserve. |
| `codex/semantic-contract-fixes` | `dd8d3090659c9bed2a81fd0fb8ad227c2e88d075` | 174 / 44 | Unmerged semantic ownership/date/description changes. Not current production behavior. Preserve. |
| `main` | `661c200840fbc1fbcb81385f085073617e73e449` | 79 / 0 | Default branch; ancestor of latest. Retain. |

## Remote and release references

| Reference | Target commit |
| --- | --- |
| `origin/main` | `661c200840fbc1fbcb81385f085073617e73e449` |
| `origin/codex/merchant-gold-seed` | `6c500cc11d8abef809527e491605b322b9c34cf6` |
| `origin/codex/release-v0.1.0` | `909f91bd3dc643fd8566925a81f10f1522ccf9bc` |
| `v0.1.0` (annotated tag) | `909f91bd3dc643fd8566925a81f10f1522ccf9bc` |

The annotated tag object is `d3492f67c858e472d90b049216c08c137ee39d94`.
The separate frozen evaluation/controller anchor is
`409dbcd7994ba1532fcbe8b165f12ebcc1c37cd4`; it is not the foundation branch tip.

## Worktrees

All 14 registered worktrees were inspected using Git status without opening
private source documents or labels. The 12 branch-attached worktrees were clean
at inventory time. The active root becomes dirty with this documentation cleanup.

| Detached worktree | HEAD | Initial state |
| --- | --- | --- |
| `/root/.codex/worktrees/07d4/creditcard` | `a93280fd04c2f296a8d984eee878c0211cc225da` | Five changed/untracked entries; leave untouched. |
| `/root/.codex/worktrees/5a0c/creditcard` | `dee4b071ad65231da13825f2f7c74a488ca96c7c` | Clean tracked/untracked status; retain historical checkout. |

The eleven other branch worktrees are under `.worktrees/`; the latest branch
is at the repository root and main has no registered checkout. Clean Git status
does not account for ignored private data, environments or model artifacts.
No worktree was removed or cleaned.

## Knowledge unique to side branches

Round 2 results are distilled in [experiment findings](../knowledge/experiment-findings.md).
Older semantic work distinguishes accounting equality from semantic completeness,
and adds source-backed date recovery and merchant/detail ownership proofs. Its
Python strictness and description contract differ from the current checkout;
do not describe those unmerged features as released behavior.

Observation/preparation work explored immutable source snapshots, capturing the
actual selected normalization decisions, exact overlapping memberships, split
sealing, and append-only artifact publication. Runtime work explored explicit
toolchain authority and isolated workers. These remain frozen historical designs,
not a roadmap to finish. The focus lock prohibits continuing their infrastructure.

The following Markdown documents are absent from the latest tree. Each link
uses one retained immutable revision containing that document; variants also
exist on related branches. Git retrieval works even if a commit is not on GitHub:

```bash
git show REVISION:docs/path/to/document.md
```

| Historical document | Retained revision |
| --- | --- |
| [Row-recovery annotation guide](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/experiments/row-recovery-annotation.md) (`docs/experiments/row-recovery-annotation.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Semantic Import Readiness Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-25-semantic-import-readiness.md) (`docs/superpowers/plans/2026-07-25-semantic-import-readiness.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Corpus Semantic Closure Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-26-corpus-semantic-closure.md) (`docs/superpowers/plans/2026-07-26-corpus-semantic-closure.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Append-Only Private Artifacts Amendment Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-append-only-private-artifacts-amendment.md) (`docs/superpowers/plans/2026-07-27-append-only-private-artifacts-amendment.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Row Observation Core Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-row-observation-core.md) (`docs/superpowers/plans/2026-07-27-row-observation-core.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Row Preparation Foundation Program Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-row-preparation-foundation-program.md) (`docs/superpowers/plans/2026-07-27-row-preparation-foundation-program.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Row Preparation Runtime Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-row-preparation-runtime.md) (`docs/superpowers/plans/2026-07-27-row-preparation-runtime.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Row Prepared Contracts Implementation Plan](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-row-prepared-contracts.md) (`docs/superpowers/plans/2026-07-27-row-prepared-contracts.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Trusted Worker Wire Protocol Amendment](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/plans/2026-07-27-trusted-worker-wire-protocol-amendment.md) (`docs/superpowers/plans/2026-07-27-trusted-worker-wire-protocol-amendment.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Semantic Import Readiness Design](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/specs/2026-07-25-semantic-import-readiness-design.md) (`docs/superpowers/specs/2026-07-25-semantic-import-readiness-design.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Corpus Semantic Closure Design](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/specs/2026-07-26-corpus-semantic-closure-design.md) (`docs/superpowers/specs/2026-07-26-corpus-semantic-closure-design.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Row Preparation Observation Design](https://github.com/stepanov1975/creditcard/blob/fcaf40e0337b06ca8c26e906d22ca03683f52762/docs/superpowers/specs/2026-07-27-row-preparation-observation-design.md) (`docs/superpowers/specs/2026-07-27-row-preparation-observation-design.md`) | `fcaf40e0337b06ca8c26e906d22ca03683f52762` |
| [Trusted Worker Toolchain Authority Amendment](https://github.com/stepanov1975/creditcard/blob/6d7c7ba83b23d6cff05265e9fffd0e7ba58ed508/docs/superpowers/plans/2026-07-27-trusted-worker-toolchain-locator-amendment.md) (`docs/superpowers/plans/2026-07-27-trusted-worker-toolchain-locator-amendment.md`) | `6d7c7ba83b23d6cff05265e9fffd0e7ba58ed508` |
| [Trusted Bootstrap Feasibility Decision](https://github.com/stepanov1975/creditcard/blob/6d7c7ba83b23d6cff05265e9fffd0e7ba58ed508/docs/superpowers/specs/2026-07-27-trusted-bootstrap-feasibility-decision.md) (`docs/superpowers/specs/2026-07-27-trusted-bootstrap-feasibility-decision.md`) | `6d7c7ba83b23d6cff05265e9fffd0e7ba58ed508` |

## Retirement decision

No branch deletion is justified by this inventory. Most side branches contain
unmerged commits and frozen evidence; main and the release are intentional refs.
Worktree paths may also be referenced by private scripts. Before any future
retirement, establish private dependency/backup coverage and preserve unique
commits with a durable ref. Never force-remove the dirty detached checkout.
See [data retention](data-retention.md) for the bounded cleanup actually performed.
