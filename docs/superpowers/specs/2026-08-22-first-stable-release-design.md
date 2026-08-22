# First Stable Release Design

**Status:** Approved conversational design; implementation remains blocked until the user reviews
this written specification.

**Date:** 2026-08-22

## Purpose

Create the first relatively stable, usable release of `ccparser` before resuming parser or
row-extraction improvements. The release establishes an immutable production baseline, a narrow
support promise, repeatable tracked verification, and formal private-corpus acceptance.

## Decision

Publish `v0.1.0` as an annotated Git tag and GitHub source release. Do not publish to PyPI in this
release. PyPI distribution can be considered after the source release has established a stable
baseline and the additional publishing and artifact-provenance requirements are designed.

The release is stable only within its documented bounded domain. It does not claim universal
credit-card, issuer, layout, operating-system, or general bank-statement support.

## Supported Contract

`v0.1.0` supports:

- Linux;
- Python 3.13;
- Tesseract with Hebrew and English language data;
- local parsing of Hebrew and mixed right-to-left credit-card statements;
- the documented `ccparse` command-line interface; and
- the documented JSON and CSV output schemas.

The parser retains its conservative contract: ambiguous or incomplete evidence must not be
silently guessed into a reconciled result. The documented status model and exact `Decimal`
reconciliation remain part of the supported behavior.

Python package modules and internal call interfaces are not public API in `v0.1.0`. JSON consumers
must tolerate unknown keys, and CSV consumers must tolerate trailing columns, as already documented,
so later additive schema extensions remain possible.

Platforms other than Linux are best-effort and unsupported. The release does not promise that every
issuer or layout in the bounded language domain is recognized.

## Release Artifact

The public artifact is the source archive associated with the annotated `v0.1.0` Git tag and its
GitHub release. Release notes must include:

- the supported environment and domain;
- source installation and system dependency instructions;
- CLI usage and output locations;
- the compatibility boundary between public CLI/schema contracts and internal Python APIs;
- known limitations and conservative non-success statuses; and
- a privacy-safe statement of the release acceptance result.

No binary, container, wheel publication, or PyPI release is required for `v0.1.0`.

## Scope Boundaries

Release preparation may change only release documentation, tracked CI, packaging metadata when a
clean-install test demonstrates an immediate defect, and tests needed to verify those release
concerns.

Release preparation must not change parser, extraction, OCR, semantic evidence, reconciliation, or
output behavior merely to improve the release. If acceptance exposes a behavioral defect, release
preparation stops. The defect is handled as a separate test-first fix, with all affected acceptance
work repeated afterward.

The row-extraction experiment program remains stopped under its binding status and focus lock. Its
historical branches, plans, implementations, and artifacts are not release work, an active backlog,
or a source of production changes. Restarting that program requires a separately approved charter
amendment and one measurable extraction task.

## Work Isolation and Existing Changes

Implementation occurs on `codex/release-v0.1.0` in an isolated worktree created from the approved
design commit. Existing modified and untracked files in the primary worktree remain untouched and
must not enter the release implicitly.

Only intended release files are staged and committed. Before acceptance begins, the release
worktree must be clean and its complete commit SHA recorded as the candidate identity.

## Tracked Continuous Integration

Add GitHub Actions for pushes and pull requests. CI uses Python 3.13 and runs the repository's four
tracked gates:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

The workflow installs the documented project development dependencies and the required Tesseract
Hebrew and English system packages. It does not receive or access private statements, membership
inventories, accepted baselines, corpus outputs, caches, or protected pins.

The private-corpus gate remains on a trusted Linux worker because it needs private data, protected
configuration, and the required ptrace, seccomp, procfs, and sealed-runtime capabilities.

## Installation and Smoke Verification

Before corpus acceptance, verify installation from a clean checkout or source archive in a fresh
Python 3.13 environment using the documented system dependencies. The smoke check must establish
that:

- project installation succeeds using the documented command;
- `ccparse --help` starts successfully;
- tracked synthetic inputs can exercise the documented parse and audit entry points without using
  private documents; and
- output paths and exit-code behavior agree with the documented CLI contract.

A smoke failure blocks the release. Correct a packaging-only defect with the smallest test-backed
change; treat any parser behavior defect as separate work under the release scope boundary.

## Acceptance Sequence

The candidate commit passes the following sequence without source or configuration changes between
steps:

1. Confirm the release worktree is clean and record its complete Git commit SHA.
2. Run Ruff formatting, Ruff lint, strict mypy, and the complete tracked pytest suite locally.
3. Require the same tracked gates to pass in GitHub Actions for the candidate commit.
4. Complete the clean-install and CLI smoke verification.
5. Run the formal private-corpus gate in `verify` mode against that exact clean candidate, using the
   independently protected membership-inventory and accepted-baseline SHA-256 pins.
6. Require the privacy-safe aggregate result to report:
   - `status=passed`;
   - `mode=verify`;
   - exactly 104 retained documents;
   - exactly 104 reconciled documents;
   - exactly 5 quarantined documents; and
   - `performance_checked=true`.
7. Require deterministic baseline parity, the accepted toolchain fingerprint and worker count, and
   every other repository private-corpus acceptance invariant.
8. Immediately after success, confirm again that `HEAD` is the same complete SHA and the release
   worktree remains clean.

Any code or configuration change invalidates prior tracked verification and private-corpus
attestation. All applicable gates must then run again.

The accepted baseline must never be rewritten to make a failing candidate pass. Baseline recording
remains a separate, exceptional, explicitly reviewed promotion process and is not part of routine
release preparation.

## Failure Handling

No stable release is published when a required gate fails or when private acceptance inputs, pins,
or trusted-worker capabilities are unavailable. Such a candidate may be described internally as a
release candidate, but it must not receive the stable `v0.1.0` release.

Failures are classified before changes are proposed:

- a tracked CI or local gate failure blocks acceptance;
- an installation failure permits only the smallest packaging-focused correction;
- a parser or output failure becomes a separate test-first defect fix;
- a private-corpus mismatch is diagnosed without revealing document identities or financial data;
  and
- an environmental or capability failure yields no corpus verdict and is rerun only on a suitable
  trusted worker.

## Publication

After every acceptance step succeeds, create the annotated `v0.1.0` tag on the exact attested
candidate SHA and publish the GitHub release from that tag. The tag and release must not point to a
post-attestation commit.

The release notes report only privacy-safe aggregate acceptance information. They must not contain
document names, hashes, text, diagnostics, transactions, financial values, private artifact paths,
or protected inventory/baseline digests.

If a defect is discovered after publication, preserve the `v0.1.0` tag and prepare a new patch
release. Do not move or replace the published stable tag.

## Post-Release Improvement Track

The `v0.1.0` tag becomes the immutable comparison and acceptance baseline for subsequent work.

- Use `0.1.x` for backward-compatible fixes that preserve the supported CLI and schema contracts.
- Reserve `0.2.0` for additive capabilities or intentionally revised contracts.
- Track release defects and improvement proposals as GitHub issues.
- Develop each improvement on a focused branch with test-driven changes and measurements
  proportionate to its risk.
- Require the formal private-corpus gate for every later change that can affect parsing,
  extraction, semantic evidence, reconciliation, OCR, or JSON/CSV output.
- Compare relevant extraction or performance improvements against the immutable stable baseline;
  do not treat tracked tests alone as corpus acceptance.

## Completion Criteria

The first stable release is complete only when:

- the approved release documentation and CI are committed;
- local and GitHub tracked gates pass at the exact candidate SHA;
- clean installation and CLI smoke verification pass;
- formal private-corpus verification passes at that same clean SHA;
- the annotated `v0.1.0` tag points to that SHA;
- the GitHub release is published with the required scope and limitations; and
- no private document content or derived financial data is committed or disclosed.
