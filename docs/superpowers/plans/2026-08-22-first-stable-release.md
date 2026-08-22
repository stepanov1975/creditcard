# First Stable Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an attested, source-based GitHub `v0.1.0` release with a narrow support contract, tracked CI, clean-install verification, and formal private-corpus acceptance.

**Architecture:** Keep parser behavior frozen and add only release documentation, one GitHub Actions quality workflow, and one self-contained clean-source installation verifier. Prepare the candidate in an isolated release worktree, verify the exact clean commit locally and on GitHub, fast-forward `main` to that commit, run the protected private-corpus gate, and tag and publish that same SHA.

**Tech Stack:** Python 3.13, Python standard-library release verification, PyMuPDF, Tesseract Hebrew/English, Ruff, mypy, pytest, GitHub Actions, Git, and GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-08-22-first-stable-release-design.md`

## Global Constraints

- Use Python 3.13 and `/root/creditcard/.venv` from the isolated worktree.
- Create `codex/release-v0.1.0` in an isolated worktree from the commit containing this plan; leave the primary worktree's modified and untracked files untouched.
- Support Linux, Python 3.13, Tesseract Hebrew/English, the documented `ccparse` CLI, and documented JSON/CSV schemas.
- Treat Python imports and internal call interfaces as unsupported implementation details for `v0.1.0`.
- Publish an annotated Git tag and GitHub source release only; do not publish a wheel, container, or PyPI package.
- Do not change parser, extraction, OCR, semantic evidence, reconciliation, or JSON/CSV behavior during release preparation.
- If verification exposes a parser or output defect, stop and handle it as separate test-first work before restarting acceptance.
- Do not continue the stopped row-extraction program or treat historical plans as release work.
- Keep statements, corpus inputs, pins, baselines, outputs, caches, and financial data in ignored local paths.
- Never print or publish private source names, hashes, text, diagnostics, transactions, financial values, artifact paths, or protected pins.
- Before each tracked release commit run `/root/creditcard/.venv/bin/ruff format --check .`, `/root/creditcard/.venv/bin/ruff check .`, `/root/creditcard/.venv/bin/mypy src`, and `/root/creditcard/.venv/bin/pytest -q`.
- Do not claim corpus acceptance until protected `verify` succeeds at the exact clean candidate SHA with 104 retained, 104 reconciled, 5 quarantined, and `performance_checked=true`.
- Any tracked code/configuration change after private verification invalidates the attestation and restarts tracked and private acceptance.
- Never record or rewrite the accepted baseline to make this candidate pass.
- Preserve the immutable `v0.1.0` tag after publication; later corrections use a new patch version.

## File Structure

- Create `.github/workflows/quality.yml`: public tracked gates for pushes and pull requests.
- Create `SUPPORT.md`: platform, domain, compatibility, and versioning contract.
- Modify `README.md`: stable source-install instructions and support/release links.
- Create `docs/releases/v0.1.0.md`: final GitHub release body committed before acceptance.
- Create `scripts/verify_release_install.py`: clean-archive installation and synthetic CLI smoke verifier.
- Do not modify `src/ccparser/`, `experiments/`, parser tests, or experiment documentation.

---

### Task 1: Create the isolated release worktree

**Files:**
- Read: `docs/superpowers/specs/2026-08-22-first-stable-release-design.md`
- Read: `docs/superpowers/plans/2026-08-22-first-stable-release.md`
- Create worktree: `.worktrees/release-v0.1.0`

**Interfaces:**
- Consumes: the exact commit containing the approved design and this plan.
- Produces: branch `codex/release-v0.1.0` in an isolated worktree.
- Preserves: every modified and untracked file in the primary worktree.

- [ ] **Step 1: Invoke the isolation skill**

Use `superpowers:using-git-worktrees` and follow its environment and safety checks.

- [ ] **Step 2: Confirm primary state without changing it**

Run from `/root/creditcard`:

```bash
git status --short --branch
git rev-parse HEAD
git branch --list codex/release-v0.1.0
git worktree list --porcelain
```

Expected: existing user changes remain visible; `HEAD` contains the design and plan; no conflicting branch/worktree exists. If one exists, inspect and stop rather than deleting it.

- [ ] **Step 3: Create and verify the worktree**

Use the exact command selected by the isolation skill, targeting branch `codex/release-v0.1.0` and `/root/creditcard/.worktrees/release-v0.1.0`. Then run there:

```bash
git status --short --branch
git log -1 --oneline
test -f docs/superpowers/specs/2026-08-22-first-stable-release-design.md
test -f docs/superpowers/plans/2026-08-22-first-stable-release.md
```

Expected: a clean release branch containing both approved documents. Do not copy ignored corpus/artifact directories into it.

### Task 2: Document the stable release contract

**Files:**
- Create: `SUPPORT.md`
- Modify: `README.md`
- Create: `docs/releases/v0.1.0.md`

**Interfaces:**
- Consumes: approved support, artifact, compatibility, acceptance, and versioning decisions.
- Produces: a support policy and final release body usable by `gh release create --notes-file` without post-attestation edits.
- Preserves: existing CLI, status, output, privacy, and corpus-gate documentation.

- [ ] **Step 1: Create `SUPPORT.md`**

Include:

```markdown
# Support policy

## Supported in v0.1.x

`ccparser` v0.1.x supports local Linux execution with Python 3.13 and
Tesseract Hebrew and English data. Its bounded domain is Hebrew and mixed
right-to-left credit-card statements.

The supported compatibility surface is the documented `ccparse` CLI, process
exit codes, JSON keys and meanings, and CSV columns and meanings. JSON
consumers must ignore unknown keys; CSV consumers must ignore trailing
columns. Python modules and call interfaces are implementation details.

## Conservative result contract

The parser does not promise every issuer or layout. Ambiguous, incomplete, or
contradictory evidence produces a conservative non-success status. A
`reconciled` result requires exact `Decimal` reconciliation and no unresolved
extraction ambiguity. Other platforms and general bank statements are
unsupported.

## Versioning

`0.1.x` preserves supported CLI/output contracts. `0.2.0` is reserved for
additive capabilities or intentional contract revisions. Published tags are
immutable; corrections receive a new patch version.

## Reporting defects

Use GitHub issues with synthetic reproductions. Never attach private
statements, outputs, caches, financial data, source identities, or protected
corpus artifacts.
```

- [ ] **Step 2: Create `docs/releases/v0.1.0.md`**

Include:

```markdown
# ccparser v0.1.0

`v0.1.0` is the first stable source release within the bounded support domain.
It performs local Hebrew/mixed-RTL statement parsing, selective Tesseract OCR,
positioned evidence retention, deterministic JSON/CSV output, and exact
`Decimal` reconciliation.

## Supported environment

- Linux
- Python 3.13
- Tesseract Hebrew and English data

The supported interface is the documented CLI and JSON/CSV contracts. Python
module APIs are internal; see `SUPPORT.md`.

## Install from the source release

```bash
python3.13 -m venv .venv
.venv/bin/pip install .
```

## Acceptance

Publication means the exact tag passed Ruff, mypy, pytest, clean-source install
and CLI smoke verification, and protected corpus `verify`: 104 retained, 104
reconciled, 5 quarantined, accepted deterministic baseline/toolchain/worker
parity, and `performance_checked=true`.

## Limitations

This is not a universal issuer/layout or bank-statement parser. Ambiguity
intentionally returns a non-success status. Non-Linux platforms are best
effort. No wheel, container, or PyPI artifact is published.
```

The acceptance paragraph is a publication invariant. Commit it before acceptance but do not publish the tag/release unless every stated gate succeeds.

- [ ] **Step 3: Update `README.md`**

After the editable development-install block, add tagged-source instructions using `.venv/bin/pip install .`, then link `SUPPORT.md` and `docs/releases/v0.1.0.md`. Preserve all existing status, privacy, and corpus-gate text.

- [ ] **Step 4: Verify and commit documentation**

Run:

```bash
git diff --check
rg -n "Linux|Python 3.13|Tesseract|ccparse|JSON|CSV|internal|v0.1.0" SUPPORT.md docs/releases/v0.1.0.md README.md
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add SUPPORT.md README.md docs/releases/v0.1.0.md
git diff --cached --check
git commit -m "docs: define v0.1.0 support contract"
```

Expected: all tracked gates pass and only these three documentation files are committed.

### Task 3: Add public tracked quality CI

**Files:**
- Create: `.github/workflows/quality.yml`

**Interfaces:**
- Consumes: `pyproject.toml` development extras and the four tracked gates.
- Produces: least-privilege `quality` CI for pushes and pull requests.
- Preserves: private corpus isolation; no private inputs, pins, outputs, caches, or secrets.

- [ ] **Step 1: Create `.github/workflows/quality.yml`**

```yaml
name: Quality

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install OCR dependencies
        run: |
          sudo apt-get update
          sudo apt-get install --yes tesseract-ocr tesseract-ocr-eng tesseract-ocr-heb

      - name: Install project
        run: |
          python -m venv .venv
          .venv/bin/pip install --disable-pip-version-check --editable '.[dev]'

      - name: Check formatting
        run: .venv/bin/ruff format --check .

      - name: Lint
        run: .venv/bin/ruff check .

      - name: Type check
        run: .venv/bin/mypy src

      - name: Test
        run: .venv/bin/pytest -q
```

Do not add secrets, artifact upload, dependency caches, corpus commands, private paths, or write permissions.

- [ ] **Step 2: Inspect, verify, and commit CI**

Run:

```bash
git diff --check
rg -n "contents: read|python-version:|tesseract-ocr-heb|ruff format|ruff check|mypy src|pytest -q" .github/workflows/quality.yml
rg -n "secret|artifact|verify-corpus|documents/|artifacts/" .github/workflows/quality.yml
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add .github/workflows/quality.yml
git diff --cached --check
git commit -m "ci: run tracked quality gates"
```

Expected: the privacy scan returns no matches, all gates pass, and only the workflow is committed. GitHub execution in Task 5 is authoritative CI validation.

### Task 4: Add clean-source installation and CLI smoke verification

**Files:**
- Create: `scripts/verify_release_install.py`

**Interfaces:**
- Consumes: clean Git `HEAD`, Linux/Python 3.13, `git`, Tesseract `eng`/`heb`, and `pyproject.toml`.
- Produces: exit 0 after installing `git archive HEAD` into a fresh venv and exercising installed help, parse, strict-exit, and audit commands on generated synthetic data.
- Preserves: private and tracked statements; all smoke data stays in a temporary directory.

- [ ] **Step 1: Create `scripts/verify_release_install.py`**

```python
#!/usr/bin/env python3
"""Verify that a clean source archive installs and exposes the supported CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path
from typing import Final

_TIMEOUT_SECONDS: Final = 180.0
_PDF_PROGRAM: Final = """
import sys
from pathlib import Path
import fitz

target = Path(sys.argv[1])
document = fitz.open()
page = document.new_page(width=300, height=200)
page.insert_text(
    (24, 48),
    "Synthetic release smoke document alpha beta gamma delta epsilon zeta",
    fontsize=11,
)
document.save(target)
document.close()
"""


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    expected_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    if completed.returncode != expected_exit:
        verb = command[1] if len(command) > 1 else ""
        raise RuntimeError(
            f"release smoke command failed with exit {completed.returncode}: "
            f"{command[0]} {verb}"
        )
    return completed


def _require_runtime() -> None:
    if sys.version_info[:2] != (3, 13) or sys.platform != "linux":
        raise RuntimeError("release verification requires Linux and Python 3.13")
    for command in ("git", "tesseract"):
        if shutil.which(command) is None:
            raise RuntimeError(f"release verification requires {command}")
    languages = _run(("tesseract", "--list-langs"), cwd=Path.cwd()).stdout.splitlines()
    if not {"eng", "heb"}.issubset({item.strip() for item in languages}):
        raise RuntimeError("release verification requires Tesseract eng and heb")


def _executable(environment: Path, name: str) -> Path:
    executable = environment / "bin" / name
    if not executable.is_file():
        raise RuntimeError(f"fresh environment did not install {name}")
    return executable


def _exercise_cli(candidate: Path, environment: Path, work: Path) -> None:
    python = _executable(environment, "python")
    ccparse = _executable(environment, "ccparse")
    input_dir = work / "input"
    input_dir.mkdir()
    source = input_dir / "synthetic.pdf"
    _run((str(python), "-c", _PDF_PROGRAM, str(source)), cwd=candidate)

    for arguments in (("--help",), ("parse", "--help"), ("audit", "--help")):
        _run((str(ccparse), *arguments), cwd=candidate)

    output = work / "output"
    parsed = _run(
        (str(ccparse), "parse", str(source), "--output-dir", str(output)),
        cwd=candidate,
    )
    if "status=unsupported" not in parsed.stdout:
        raise RuntimeError("synthetic parse did not conservatively abstain")
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    if payload["status"] != "unsupported":
        raise RuntimeError("synthetic JSON status is not unsupported")
    if not (output / "transactions.csv").is_file():
        raise RuntimeError("synthetic parse did not write transactions.csv")

    _run(
        (
            str(ccparse),
            "parse",
            str(source),
            "--output-dir",
            str(work / "strict-output"),
            "--strict",
        ),
        cwd=candidate,
        expected_exit=2,
    )

    quarantine = work / "quarantine"
    audited = _run(
        (
            str(ccparse),
            "audit",
            str(input_dir),
            "--quarantine-dir",
            str(quarantine),
        ),
        cwd=candidate,
    )
    expected = "documents=1 keep=0 review=1 quarantine=0 moved=0"
    if expected not in audited.stdout:
        raise RuntimeError("synthetic audit did not preserve the review boundary")
    if not source.is_file() or quarantine.exists():
        raise RuntimeError("dry-run audit mutated the synthetic input")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _require_runtime()
    status = _run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=root,
    )
    if status.stdout:
        raise RuntimeError("release checkout is not clean")

    with tempfile.TemporaryDirectory(prefix="ccparser-release-smoke-") as temporary:
        work = Path(temporary)
        archive = work / "candidate.tar"
        candidate = work / "candidate"
        candidate.mkdir()
        _run(
            ("git", "archive", "--format=tar", f"--output={archive}", "HEAD"),
            cwd=root,
        )
        with tarfile.open(archive, mode="r:") as source_archive:
            source_archive.extractall(candidate, filter="data")

        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _executable(environment, "python")
        _run(
            (
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(candidate),
            ),
            cwd=candidate,
        )
        _exercise_cli(candidate, environment, work)

    print("release_install_smoke=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

This is release tooling, not production parser behavior. It reads no private/ignored path.

- [ ] **Step 2: Format, inspect, verify, and commit**

Run the full tracked gates, then commit because `git archive HEAD` cannot test an uncommitted verifier:

```bash
/root/creditcard/.venv/bin/ruff format scripts/verify_release_install.py
/root/creditcard/.venv/bin/ruff check scripts/verify_release_install.py
rg -n "documents/|unrelated/|artifacts/|source_sha256|merchant|amount|total" scripts/verify_release_install.py
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
git add scripts/verify_release_install.py
git diff --cached --check
git commit -m "test: verify clean release installation"
/root/creditcard/.venv/bin/python scripts/verify_release_install.py
```

Expected: privacy scan has no matches, tracked gates pass, only the verifier is committed, and the final command prints `release_install_smoke=passed`. If install fails, diagnose a packaging-only defect; do not change parser behavior.

### Task 5: Verify the candidate and require GitHub CI

**Files:**
- Verify: all release files
- No new tracked files

**Interfaces:**
- Consumes: complete clean release branch.
- Produces: one SHA with passing local gates, smoke verification, and GitHub `Quality` on the release branch and `main`.
- Preserves: exact candidate tree/identity once verification begins.

- [ ] **Step 1: Audit scope and run fresh local verification**

```bash
git status --short --branch
git diff --name-status HEAD~3..HEAD
rg -n "ccparser\\.experiments|experiments\\.row_extraction|row_extraction" src/ccparser -g '*.py'
/root/creditcard/.venv/bin/ruff format --check .
/root/creditcard/.venv/bin/ruff check .
/root/creditcard/.venv/bin/mypy src
/root/creditcard/.venv/bin/pytest -q
/root/creditcard/.venv/bin/python scripts/verify_release_install.py
/root/creditcard/.venv/bin/python -c 'import pathlib, tomllib; assert tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"] == "0.1.0"'
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
```

Expected: only the five planned files changed, production import scan has no matches, every gate passes, and status prints nothing. Record the 40-character SHA as candidate identity.

- [ ] **Step 2: Push release branch without force and require CI**

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git push --set-upstream origin codex/release-v0.1.0
CCPARSER_QUALITY_RUN_ID="$(gh run list --workflow quality.yml --branch codex/release-v0.1.0 --limit 1 --json databaseId --jq '.[0].databaseId')"
test -n "$CCPARSER_QUALITY_RUN_ID"
gh run watch "$CCPARSER_QUALITY_RUN_ID" --exit-status
gh run view "$CCPARSER_QUALITY_RUN_ID" --json conclusion,headSha,jobs
```

Expected: branch CI succeeds and `headSha` equals the candidate. A failure blocks release; do not weaken a gate.

- [ ] **Step 3: Fast-forward main and require same-SHA CI**

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:main
git ls-remote origin refs/heads/main
CCPARSER_MAIN_RUN_ID="$(gh run list --workflow quality.yml --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
test -n "$CCPARSER_MAIN_RUN_ID"
gh run watch "$CCPARSER_MAIN_RUN_ID" --exit-status
gh run view "$CCPARSER_MAIN_RUN_ID" --json conclusion,headSha,jobs
```

Expected: fast-forward succeeds, remote `main` and both successful CI runs use the candidate SHA. If main advanced, stop; do not force push or silently merge.

### Task 6: Run formal private-corpus acceptance

**Files:**
- Read privately: ignored retained/quarantine directories, protected inventory/baseline
- Write privately: one fresh ignored run directory
- No tracked changes

**Interfaces:**
- Consumes: exact clean candidate on remote `main`, protected pins, accepted worker count, trusted Linux runtime.
- Produces: one privacy-safe passing aggregate attestation.
- Preserves: private inputs, accepted baseline, candidate tree/SHA, toolchain, and worker count.

- [ ] **Step 1: Validate prerequisites without printing sensitive values**

```bash
set -euo pipefail
CCPARSER_RELEASE_SHA="$(git rev-parse HEAD)"
export CCPARSER_RELEASE_SHA
test "${#CCPARSER_RELEASE_SHA}" -eq 40
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$CCPARSER_RELEASE_SHA"
: "${APPROVED_MEMBERSHIP_INVENTORY_SHA256:?protected membership pin is required}"
: "${APPROVED_CORPUS_BASELINE_SHA256:?protected baseline pin is required}"
test -d /root/creditcard/documents
test -d /root/creditcard/unrelated
test -f /root/creditcard/artifacts/corpus-membership.json
test -f /root/creditcard/artifacts/corpus-baseline.json
CCPARSER_CORPUS_RUN_DIR="$(/root/creditcard/.venv/bin/python -c 'import tempfile; print(tempfile.mkdtemp(prefix="corpus-run-verify-v0.1.0-", dir="/root/creditcard/artifacts"))')"
export CCPARSER_CORPUS_RUN_DIR
```

Do not echo pins, private contents, inventory/baseline content, or membership.

- [ ] **Step 2: Run protected verify from candidate source**

```bash
PYTHONPATH="$PWD/src" /root/creditcard/.venv/bin/ccparse verify-corpus \
  /root/creditcard/documents \
  --quarantine-dir /root/creditcard/unrelated \
  --membership-inventory /root/creditcard/artifacts/corpus-membership.json \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline /root/creditcard/artifacts/corpus-baseline.json \
  --baseline-sha256 "$APPROVED_CORPUS_BASELINE_SHA256" \
  --work-dir "$CCPARSER_CORPUS_RUN_DIR" \
  --mode verify \
  --jobs 4 \
  --expected-commit-sha "$CCPARSER_RELEASE_SHA"
```

Expected: exit 0 and one aggregate line with `status=passed`, `mode=verify`, `retained=104`, `reconciled=104`, `quarantined=5`, and `performance_checked=true`, plus enforced accepted baseline/toolchain/worker parity.

- [ ] **Step 3: Reconfirm candidate immediately after success**

```bash
test "$(git rev-parse HEAD)" = "$CCPARSER_RELEASE_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$CCPARSER_RELEASE_SHA"
```

Expected: all pass. Acceptance failure stops publication. Environmental interruption/capability failure is no verdict and may be rerun only in a new empty directory on a suitable worker. Never use `record` mode here.

### Task 7: Tag and publish v0.1.0

**Files:**
- Read: `docs/releases/v0.1.0.md`
- No tracked changes

**Interfaces:**
- Consumes: exact clean SHA with successful local, GitHub, install, and corpus gates.
- Produces: annotated tag `v0.1.0` and GitHub source release.
- Preserves: attested commit and immutable tag target.

- [ ] **Step 1: Final pre-tag checks**

```bash
test "$(git rev-parse HEAD)" = "$CCPARSER_RELEASE_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$CCPARSER_RELEASE_SHA"
test -z "$(git tag --list v0.1.0)"
test -z "$(git ls-remote --tags origin refs/tags/v0.1.0)"
test -f docs/releases/v0.1.0.md
```

Expected: no local/remote tag exists and candidate identity remains exact.

- [ ] **Step 2: Create, push, and verify annotated tag**

```bash
git tag --annotate v0.1.0 --message "ccparser v0.1.0"
test "$(git rev-list -n 1 v0.1.0)" = "$CCPARSER_RELEASE_SHA"
test "$(git cat-file -t v0.1.0)" = "tag"
git push origin refs/tags/v0.1.0
git ls-remote --tags origin refs/tags/v0.1.0 refs/tags/v0.1.0^{}
```

Expected: remote annotated tag dereferences to the accepted SHA. Never force-update it.

- [ ] **Step 3: Publish and verify GitHub release**

```bash
gh release create v0.1.0 \
  --verify-tag \
  --title "ccparser v0.1.0" \
  --notes-file docs/releases/v0.1.0.md
gh release view v0.1.0 --json tagName,name,isDraft,isPrerelease,targetCommitish,url
git status --short --branch
```

Expected: non-draft, non-prerelease `ccparser v0.1.0`; clean worktree; tag resolves to accepted SHA. If tag push succeeds but release creation fails, preserve the tag and retry only release creation.

- [ ] **Step 4: Report completion safely**

Report the public release URL, full tagged SHA, fresh tracked test count, `release_install_smoke=passed`, and only the safe corpus aggregate counts plus `performance_checked=true`. State that future improvements start from immutable `v0.1.0` via GitHub issues and focused branches. Do not report private identities, hashes, diagnostics, transactions, values, paths, or protected digests.
