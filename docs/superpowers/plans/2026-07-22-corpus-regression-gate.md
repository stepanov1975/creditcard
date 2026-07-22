# Corpus Regression Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-safe, commit-bound corpus gate that can record only a fully passing deterministic baseline and reject later correctness, provenance, corpus, or performance regressions.

**Architecture:** `corpus_gate.py` owns immutable manifest models, pure projections/comparisons, protocol-driven execution, and baseline lifecycle. The existing Typer CLI supplies a thin `verify-corpus` boundary. Private inputs and artifacts stay below already ignored paths; tracked tests use synthetic `BatchResult` values and injected adapters.

**Tech Stack:** Python 3.13, Pydantic 2, Typer, pytest 9, standard-library hashing/subprocess/path APIs.

## Global Constraints

- Use Python 3.13 and `/root/creditcard/.venv`.
- Follow red-green-refactor for every production behavior.
- Do not expose source names, paths, hashes, raw text, dates, merchants, amounts, or totals in gate console output.
- Keep the approved membership inventory, source hashes, manifests, parser outputs, caches, and financial aggregates in ignored private storage.
- Do not change files outside `/root/creditcard`.
- Before any test or command that may use system temporary storage, run `export TMPDIR="$PWD/.superpowers/private/tmp"` and `mkdir -p "$TMPDIR"`; every temporary file must stay inside this worktree.
- Any failure or interruption observed before the atomic commit must preserve the
  accepted baseline. After commit, the candidate is accepted and no later operation
  may report publication failure; process death may lose acknowledgement of a
  completed atomic replacement.
- Exit 0 means complete acceptance; exit 1 means input/runtime failure; exit 2 means completed acceptance failure.

## File Structure

- Create `src/ccparser/corpus_gate.py`: immutable models, reason vocabulary, projections, comparisons, adapters, and orchestration.
- Create `tests/test_corpus_gate.py`: pure comparison, validation, lifecycle, privacy, and orchestration tests.
- Modify `src/ccparser/cli.py`: one thin `verify-corpus` command and aggregate printer.
- Modify `src/ccparser/parser.py`: explicit trusted descriptor-root parsing policy.
- Modify `src/ccparser/paths.py`: policy-aware traversal that preserves only exact
  validated process-fd directory roots.
- Modify `src/ccparser/evidence/ocr.py` and `src/ccparser/output.py` only as required
  to retain lexical capability roots for cache/output operations.
- Modify `tests/test_cli.py`: CLI wiring, redaction, and exit-code coverage.
- Modify `README.md`: private local record/verify workflow without corpus-specific values.

---

### Task 1: Typed snapshots and exact structural projections

**Files:**
- Create: `src/ccparser/corpus_gate.py`
- Create: `tests/test_corpus_gate.py`

**Interfaces:**
- Consumes: `BatchResult`, `canonical_json_bytes()`, `transactions_csv_bytes()`.
- Produces: `CorpusCounts`, `RunManifest`, `project_run()` and `digest_membership()`.

- [ ] **Step 1: Write failing projection tests**

Add synthetic builders and tests that prove every protected dimension affects the corresponding digest while private values never enter aggregate count models:

```python
def test_project_run_tracks_structure_presence_evidence_and_ambiguity() -> None:
    batch = _batch(transaction=_transaction(with_fx=True, ambiguities=("candidate",)))

    manifest = project_run(batch, elapsed_seconds=Decimal("1.25"))

    assert manifest.counts.documents == 1
    assert manifest.counts.transactions == 1
    assert manifest.counts.ambiguous_transactions == 1
    assert FieldCount(path="foreign_exchange.exchange_rate", count=1) in (
        manifest.counts.present_fields
    )
    assert manifest.evidence_provenance_digest
    assert manifest.ambiguity_digest


def test_membership_digest_is_order_independent_but_duplicate_sensitive() -> None:
    assert digest_membership(("a", "b")) == digest_membership(("b", "a"))
    assert digest_membership(("a", "a", "b")) != digest_membership(("a", "b"))
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```bash
.venv/bin/pytest -q tests/test_corpus_gate.py
```

Expected: collection fails because `ccparser.corpus_gate` does not exist.

- [ ] **Step 3: Implement immutable projection models and hashing**

Implement the following public-internal contracts using frozen Pydantic models with `extra="forbid"`, sorted immutable collections, and canonical JSON hashing. Every digest field is exactly 64 lowercase hexadecimal characters; every commit SHA is exactly 40 lowercase hexadecimal characters:

```python
class FieldCount(_GateModel):
    path: PresentFieldPath
    count: int = Field(ge=0)


class CorpusCounts(_GateModel):
    documents: int = Field(ge=0)
    reconciled: int = Field(ge=0)
    unreconciled: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    not_statement: int = Field(ge=0)
    groups: int = Field(ge=0)
    row_results: int = Field(ge=0)
    transactions: int = Field(ge=0)
    ambiguous_transactions: int = Field(ge=0)
    ambiguity_occurrences: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    present_fields: tuple[FieldCount, ...]


class CorpusMembership(_GateModel):
    document_count: int = Field(ge=0)
    source_multiset_digest: Digest


class CorpusMembershipInventory(_GateModel):
    version: Literal[1]
    retained: CorpusMembership
    quarantine: CorpusMembership


class RunManifest(_GateModel):
    elapsed_seconds: Decimal = Field(ge=0)
    counts: CorpusCounts
    json_digest: Digest
    csv_digest: Digest
    ordered_status_digest: Digest
    group_structure_digest: Digest
    transaction_identity_digest: Digest
    field_presence_digest: Digest
    evidence_provenance_digest: Digest
    ambiguity_digest: Digest


def digest_membership(source_hashes: Iterable[str]) -> CorpusMembership:
    ordered = tuple(sorted(source_hashes))
    return CorpusMembership(
        document_count=len(ordered),
        source_multiset_digest=_digest_json(ordered),
    )


def project_run(batch: BatchResult, *, elapsed_seconds: Decimal) -> RunManifest:
    json_content = canonical_json_bytes(batch)
    csv_content = transactions_csv_bytes(batch)
    projections = _project_structural_dimensions(batch)
    return RunManifest(
        elapsed_seconds=elapsed_seconds,
        counts=projections.counts,
        json_digest=_digest_bytes(json_content),
        csv_digest=_digest_bytes(csv_content),
        ordered_status_digest=_digest_json(projections.ordered_statuses),
        group_structure_digest=_digest_json(projections.group_structure),
        transaction_identity_digest=_digest_json(projections.transaction_identities),
        field_presence_digest=_digest_json(projections.field_presence),
        evidence_provenance_digest=_digest_json(projections.evidence_provenance),
        ambiguity_digest=_digest_json(projections.ambiguities),
    )
```

The implementation must count every `EvidenceReference` attached to transactions and structured FX fields. `present_fields` uses a closed path vocabulary defined in the module; it does not inspect arbitrary model keys reflectively.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/test_corpus_gate.py
.venv/bin/mypy src/ccparser/corpus_gate.py
```

Expected: all gate tests pass and mypy reports no errors.

- [ ] **Step 5: Commit the projection core**

```bash
git add src/ccparser/corpus_gate.py tests/test_corpus_gate.py
git commit -m "feat: project privacy-safe corpus manifests"
```

### Task 2: Closed comparison policy

**Files:**
- Modify: `src/ccparser/corpus_gate.py`
- Modify: `tests/test_corpus_gate.py`

**Interfaces:**
- Consumes: `RunManifest`, `CorpusBaseline`.
- Produces: `CorpusGateReason`, `compare_independent_runs()`, `compare_with_baseline()`.

- [ ] **Step 1: Add one-dimension-at-a-time failing comparison tests**

Cover status, membership, transaction/group ordering, field removal, evidence change, ambiguity growth, JSON-only drift, CSV-only drift, toolchain mismatch, and same-toolchain runtime regression:

```python
@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("json_digest", CorpusGateReason.JSON_DRIFT),
        ("csv_digest", CorpusGateReason.CSV_DRIFT),
        ("transaction_identity_digest", CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT),
        ("evidence_provenance_digest", CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT),
        ("ambiguity_digest", CorpusGateReason.AMBIGUITY_DRIFT),
    ),
)
def test_independent_run_difference_has_exact_reason(field: str, reason: CorpusGateReason) -> None:
    first = _run_manifest()
    second = first.model_copy(update={field: "f" * 64})
    assert compare_independent_runs(first, second) == (reason,)


def test_runtime_is_enforced_only_for_matching_toolchain_and_jobs() -> None:
    baseline = _baseline(elapsed="10", jobs=4, toolchain="a")
    slower = _baseline(elapsed="13", jobs=4, toolchain="a")
    assert CorpusGateReason.RUNTIME_REGRESSION in compare_with_baseline(baseline, slower)
    assert CorpusGateReason.RUNTIME_REGRESSION not in compare_with_baseline(
        baseline, slower.model_copy(update={"toolchain": _toolchain("b")})
    )


def test_baseline_comparison_rejects_membership_change() -> None:
    baseline = _baseline(retained_membership=_membership(count=3, digest="a" * 64))
    candidate = _baseline(retained_membership=_membership(count=2, digest="b" * 64))
    assert compare_with_baseline(baseline, candidate) == (
        CorpusGateReason.MEMBERSHIP_DRIFT,
    )
```

- [ ] **Step 2: Confirm failures**

Run `.venv/bin/pytest -q tests/test_corpus_gate.py`.

Expected: failures because the reason vocabulary and comparison functions are absent.

- [ ] **Step 3: Implement the closed policy**

Define `CorpusGateReason(StrEnum)` with this closed vocabulary and deterministic declaration order:

```python
class CorpusGateReason(StrEnum):
    INVALID_CONFIGURATION = "invalid_configuration"
    PATH_OUTSIDE_REPOSITORY = "path_outside_repository"
    UNSAFE_PATH_TOPOLOGY = "unsafe_path_topology"
    PRIVATE_PATH_NOT_IGNORED = "private_path_not_ignored"
    CORPUS_SYMLINK = "corpus_symlink"
    RUN_PATH_NOT_EMPTY = "run_path_not_empty"
    DIRTY_REPOSITORY = "dirty_repository"
    REPOSITORY_CHANGED = "repository_changed"
    TOOLCHAIN_UNAVAILABLE = "toolchain_unavailable"
    TOOLCHAIN_CHANGED = "toolchain_changed"
    INVENTORY_INVALID = "inventory_invalid"
    BASELINE_MISSING = "baseline_missing"
    BASELINE_INVALID = "baseline_invalid"
    PARSER_RUNTIME_FAILED = "parser_runtime_failed"
    MEMBERSHIP_DRIFT = "membership_drift"
    RETAINED_NOT_RECONCILED = "retained_not_reconciled"
    QUARANTINE_MISCLASSIFIED = "quarantine_misclassified"
    COUNTS_DRIFT = "counts_drift"
    JSON_DRIFT = "json_drift"
    CSV_DRIFT = "csv_drift"
    STATUS_DRIFT = "status_drift"
    GROUP_STRUCTURE_DRIFT = "group_structure_drift"
    TRANSACTION_STRUCTURE_DRIFT = "transaction_structure_drift"
    FIELD_PRESENCE_DRIFT = "field_presence_drift"
    EVIDENCE_PROVENANCE_DRIFT = "evidence_provenance_drift"
    AMBIGUITY_DRIFT = "ambiguity_drift"
    RUNTIME_REGRESSION = "runtime_regression"
```

Add the comparison-layer models with focused validation tests for malformed digests, unsorted cache-version tuples, unsupported manifest versions, and negative runtime/tolerance values:

```python
class CorpusGateMode(StrEnum):
    VERIFY = "verify"
    RECORD = "record"


class ToolchainFingerprint(_GateModel):
    python_version: str
    package_version: str
    pymupdf_version: str
    tesseract_version: str
    ocr_pipeline_version: str
    ocr_cache_versions: tuple[str, ...]
    command_digest: Digest
    digest: Digest


class CorpusPairManifest(_GateModel):
    membership: CorpusMembership
    first: RunManifest
    second: RunManifest
    worst_elapsed_seconds: Decimal = Field(ge=0)


class CorpusBaseline(_GateModel):
    version: Literal[1]
    commit_sha: CommitSha
    jobs: int = Field(gt=0)
    runtime_tolerance_ratio: Decimal = Field(ge=0)
    toolchain: ToolchainFingerprint
    retained: CorpusPairManifest
    quarantine: CorpusPairManifest
```

Reasons from `INVALID_CONFIGURATION` through `PARSER_RUNTIME_FAILED` map to exit 1. Reasons from `MEMBERSHIP_DRIFT` through `RUNTIME_REGRESSION` map to exit 2. Implement comparisons in deterministic policy order:

```python
def compare_independent_runs(first: RunManifest, second: RunManifest) -> tuple[CorpusGateReason, ...]:
    checks = (
        (first.counts != second.counts, CorpusGateReason.COUNTS_DRIFT),
        (first.json_digest != second.json_digest, CorpusGateReason.JSON_DRIFT),
        (first.csv_digest != second.csv_digest, CorpusGateReason.CSV_DRIFT),
        (
            first.ordered_status_digest != second.ordered_status_digest,
            CorpusGateReason.STATUS_DRIFT,
        ),
        (
            first.group_structure_digest != second.group_structure_digest,
            CorpusGateReason.GROUP_STRUCTURE_DRIFT,
        ),
        (
            first.transaction_identity_digest != second.transaction_identity_digest,
            CorpusGateReason.TRANSACTION_STRUCTURE_DRIFT,
        ),
        (
            first.field_presence_digest != second.field_presence_digest,
            CorpusGateReason.FIELD_PRESENCE_DRIFT,
        ),
        (
            first.evidence_provenance_digest != second.evidence_provenance_digest,
            CorpusGateReason.EVIDENCE_PROVENANCE_DRIFT,
        ),
        (first.ambiguity_digest != second.ambiguity_digest, CorpusGateReason.AMBIGUITY_DRIFT),
    )
    return tuple(reason for failed, reason in checks if failed)
```

Baseline comparison must reject any exact membership, count, or digest change. The two-run retained runtime stored in `worst_elapsed_seconds` is `max(first.elapsed_seconds, second.elapsed_seconds)`. Verification uses only the tolerance recorded in the accepted baseline; it does not accept a replacement tolerance. Runtime uses `candidate_seconds > baseline_seconds * (Decimal(1) + baseline.runtime_tolerance_ratio)` only when toolchain digest and jobs match.

- [ ] **Step 4: Run focused and output tests**

```bash
.venv/bin/pytest -q tests/test_corpus_gate.py tests/test_output.py
```

Expected: pass.

- [ ] **Step 5: Commit comparison policy**

```bash
git add src/ccparser/corpus_gate.py tests/test_corpus_gate.py
git commit -m "feat: compare corpus runs conservatively"
```

### Task 3: Safe execution, toolchain fingerprint, and baseline lifecycle

**Files:**
- Modify: `src/ccparser/corpus_gate.py`
- Modify: `tests/test_corpus_gate.py`

**Interfaces:**
- Consumes: `parse_directory()`, safe path helpers, comparison functions.
- Produces: `CorpusGateConfig`, `CorpusGateDependencies`, `run_corpus_gate()`.

- [ ] **Step 1: Write failing lifecycle and topology tests**

Use injected fakes; never invoke real PDFs in tracked tests:

```python
def test_record_failure_never_replaces_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "artifacts" / "baseline.json"
    baseline.parent.mkdir()
    baseline.write_bytes(b"accepted")
    dependencies = _dependencies(retained_status=Status.UNRECONCILED)

    with pytest.raises(CorpusGateAcceptanceError) as caught:
        run_corpus_gate(_config(tmp_path, baseline), CorpusGateMode.RECORD, dependencies=dependencies)

    assert caught.value.reasons == (CorpusGateReason.RETAINED_NOT_RECONCILED,)
    assert baseline.read_bytes() == b"accepted"


def test_four_runs_receive_distinct_empty_caches(tmp_path: Path) -> None:
    runner = RecordingRunner()
    run_corpus_gate(_config(tmp_path), CorpusGateMode.RECORD, dependencies=_dependencies(runner))
    assert len(set(runner.cache_dirs)) == 4
    assert all(was_empty for was_empty in runner.cache_was_empty)
```

Add cases for missing/corrupt/unknown-version baseline, dirty repository before and after, unignored destinations, every path-overlap pair, symlink members, source mutation, toolchain mutation, parser failure, and output mismatch.

Also add these acceptance and containment cases:

- record mode rejects a missing or malformed approved membership inventory;
- record mode rejects a retained or quarantine membership that differs from the approved count or multiset digest, even when every supplied document otherwise passes;
- each run captures membership immediately before and after parsing, and mutation between any two of the four runs is rejected;
- retained, quarantine, inventory, baseline, work, output, and cache paths must resolve beneath `RepositoryState.root`;
- destination paths with a symlinked existing ancestor are rejected before any directory is created;
- record mode requires an explicit runtime tolerance, while verify mode rejects one supplied by the caller and uses the accepted baseline tolerance;
- the work directory must be absent or empty before a run, and all four output/cache pairs are distinct newly created children that did not exist at validation time.

- [ ] **Step 2: Confirm lifecycle tests fail**

Run `.venv/bin/pytest -q tests/test_corpus_gate.py`.

Expected: failures because orchestration interfaces are absent.

- [ ] **Step 3: Implement protocol-driven orchestration**

Use these exact contracts:

```python
class RepositoryState(_GateModel):
    root: Path
    commit_sha: CommitSha
    clean: bool


class CorpusGateConfig(_GateModel):
    retained_dir: Path
    quarantine_dir: Path
    membership_inventory_path: Path
    baseline_path: Path
    work_dir: Path
    jobs: int = Field(gt=0)
    runtime_tolerance_ratio: Decimal | None = Field(default=None, ge=0)


class CorpusGateAttestation(_GateModel):
    passed: bool
    mode: CorpusGateMode
    commit_abbreviation: str
    toolchain_abbreviation: str
    retained_counts: CorpusCounts
    quarantine_counts: CorpusCounts
    elapsed_seconds: Decimal = Field(ge=0)
    performance_checked: bool
    reason_codes: tuple[CorpusGateReason, ...]


@dataclass(frozen=True, slots=True)
class CompletedCorpusRun:
    batch: BatchResult
    manifest: RunManifest
    membership_before: CorpusMembership
    membership_after: CorpusMembership


class CorpusRunner(Protocol):
    def __call__(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        cache_dir: Path,
        strict: bool,
        jobs: int,
    ) -> CompletedCorpusRun:
        raise NotImplementedError


class RepositoryInspector(Protocol):
    def state(self) -> RepositoryState:
        raise NotImplementedError

    def is_ignored(self, path: Path) -> bool:
        raise NotImplementedError


class ToolchainInspector(Protocol):
    def fingerprint(self) -> ToolchainFingerprint:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CorpusGateDependencies:
    runner: CorpusRunner
    repository: RepositoryInspector
    toolchain: ToolchainInspector


def run_corpus_gate(
    config: CorpusGateConfig,
    mode: CorpusGateMode,
    *,
    dependencies: CorpusGateDependencies | None = None,
) -> CorpusGateAttestation:
    active_dependencies = dependencies or _default_dependencies()
    _validate_preconditions(config, mode, active_dependencies)
    candidate = _execute_candidate(config, active_dependencies)
    return _accept_or_reject(config, mode, candidate, active_dependencies)
```

`RepositoryState.root` is the project containment root: resolve `git rev-parse --git-common-dir` and use the parent of that `.git` directory. In a linked worktree this is intentionally broader than `git rev-parse --show-toplevel`, so read-only private corpora at the main project root and generated artifacts inside the linked worktree are both allowed while paths outside `/root/creditcard` remain forbidden. Git cleanliness and commit checks still execute against the active worktree, never the main checkout by accident.

The real runner snapshots and hashes corpus membership, times `parse_directory()`, reads the emitted canonical files, and returns the batch, `RunManifest`, and its immediately adjacent membership snapshots. Load `CorpusMembershipInventory` before running and require its retained and quarantine values to equal every per-run snapshot. Validate active-worktree Git state and toolchain before and after all four runs. Explicitly scan and reject symlink files/directories because `iter_regular_pdf_files()` intentionally skips them.

Resolve every configured path and existing ancestor before mutation as an advisory
precheck. Authoritative private-file reads and all destination creation/publication
must be repository-root-anchored and descriptor-relative, with no-follow component
opens. Destination ancestors must be current-EUID-owned and not group/other writable.
Work, baseline, and inventory paths must be Git-ignored; configured and derived paths
must not overlap in either direction. An existing work directory must be empty.
Record mode requires `runtime_tolerance_ratio` and publishes the baseline last from
an exclusively created, identity-verified temporary inode. Verify mode requires
`runtime_tolerance_ratio is None`, loads the tolerance from stable descriptor-read
baseline bytes, and never rewrites it.

The exact execution order is:

1. Inspect a clean repository state and fingerprint the toolchain.
2. Validate containment, ignored paths, non-overlap, non-symlink topology, an absent-or-empty work directory with absent run children, and the mode-specific tolerance contract.
3. Load the version-1 membership inventory and, in verify mode, the version-1 baseline.
4. Require current retained and quarantine memberships to match the inventory.
5. Run retained twice with `strict=True`, then quarantine twice with `strict=False`, using four distinct newly created output/cache pairs.
6. Require every retained statement to be `Status.RECONCILED` and every quarantine statement to be `Status.NOT_STATEMENT`.
7. Require each run's before/after memberships and a final membership snapshot to match the inventory; compare both independent pairs and the accepted baseline.
8. Reinspect the same clean commit and identical toolchain fingerprint.
9. Return the aggregate attestation, or pre-sync and atomically replace the accepted
   baseline as the final reported commit operation and then return it in record mode.

- [ ] **Step 4: Run gate, parser, and path suites**

```bash
.venv/bin/pytest -q tests/test_corpus_gate.py tests/test_parser.py tests/test_paths.py
.venv/bin/mypy src
```

Expected: pass.

- [ ] **Step 5: Commit orchestration**

```bash
git add src/ccparser/corpus_gate.py tests/test_corpus_gate.py
git commit -m "feat: run isolated corpus acceptance gates"
```

### Task 3A: Capability and publication hardening after independent review

**Files:**
- Modify: `src/ccparser/paths.py`
- Modify: `src/ccparser/parser.py`
- Modify: `src/ccparser/corpus_gate.py`
- Modify if required for lexical propagation: `src/ccparser/evidence/ocr.py`,
  `src/ccparser/output.py`
- Modify: `tests/test_paths.py`, `tests/test_parser.py`, `tests/test_corpus_gate.py`

**Interfaces:**
- Produces: `DirectoryRootPolicy` with a normal resolving default and one explicit
  trusted descriptor-root mode.
- Produces: stable repository-root-anchored private-file reads; trusted directory
  ancestry checks; a shared baseline-parent advisory lock; boundary reachability
  checks; inode-owned atomic publication.

- [ ] **Step 1: Add the real-parser capability-retention regression**

Open input, output, and cache directory descriptors beneath a private ancestor. Call
`parse_directory()` with exact `/proc/self/fd/N` roots and the explicit trusted policy.
Pause at traversal, rename/substitute the pathname ancestor, and assert the statement
parser reads only the staged approved bytes while cache markers and canonical JSON/CSV
appear only under the held output/cache descriptors. Run the single test and confirm
the existing resolver follows the substitute before implementing the policy.

- [ ] **Step 2: Preserve only validated descriptor roots**

The policy validates the exact lexical shape `/proc/self/fd/<decimal fd>`, compares
`os.stat(path)` with `os.fstat(fd)`, and requires a directory. Under this policy,
`parse_directory()` and `iter_regular_pdf_files()` keep roots and child source paths
lexical; normal calls retain resolved deterministic paths. Pass the lexical cache root
to `parse_statement()`/`TesseractOcr` and the lexical output root to
`write_batch_outputs()`.

- [ ] **Step 3: Add authoritative inventory/baseline read regressions**

Swap an inventory ancestor immediately before its read and swap the verify-baseline
name to an outside symlink immediately before its read. Both fail closed without
running the parser or consuming substitute bytes. Implement component-wise no-follow
parent opens, final no-follow regular-file opens, and complete fd reads that require
stable device, inode, size, and nanosecond mtime before model validation.

- [ ] **Step 4: Add ancestry, locking, reachability, and root-parent regressions**

Reject baseline/work ancestry not owned by the effective UID or writable by group or
other. Hold a nonblocking advisory lock on the securely opened shared baseline parent.
At every run boundary, reopen work and baseline-parent paths beneath the repository
root and compare device/inode identity with held descriptors, rejecting accidental
relocation. Permit an ignored baseline directly under the repository root by
duplicating the root descriptor for its empty parent-relative tuple; continue to
reject a work directory equal to the repository root.

- [ ] **Step 5: Add temporary-inode and interruption regressions**

After exclusive temporary creation, substitute its name and prove publication and
cleanup never replace or unlink the substitute. Inject `BaseException` before replace
and at replace. A pre-commit interruption preserves old bytes; a deterministic replace
wrapper that commits and then raises is recognized by destination dev/ino and treated
as committed. Keep the temp fd open through replace, clear the local before a
best-effort no-throw close, and perform no post-success filesystem operation.

- [ ] **Step 6: Run focused and full verification**

```bash
.venv/bin/pytest -q tests/test_parser.py tests/test_paths.py tests/test_output.py \
  tests/test_evidence_ocr.py tests/test_corpus_gate.py
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Expected: every command exits zero. Document that same-effective-UID malicious rename
and signal-after-commit acknowledgement loss are outside enforceable guarantees.

### Task 4: CLI boundary and privacy-safe attestation

**Files:**
- Modify: `src/ccparser/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_corpus_gate()` and `CorpusGateMode`.
- Produces: `ccparse verify-corpus`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_verify_corpus_cli_prints_only_aggregate_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "run_corpus_gate", lambda *_args, **_kwargs: _attestation())
    result = runner.invoke(
        app,
        [
            "verify-corpus", "retained", "--quarantine-dir", "quarantine",
            "--membership-inventory", "artifacts/membership.json",
            "--baseline", "artifacts/baseline.json", "--work-dir", "artifacts/run",
            "--mode", "verify", "--jobs", "4",
        ],
    )
    assert result.exit_code == 0
    assert result.stdout == (
        "status=passed mode=verify retained=3 reconciled=3 "
        "quarantined=2 elapsed_seconds=1.25 performance_checked=true\n"
    )
```

Add exit-1 and exit-2 tests whose fake exceptions contain a filename, hash, merchant, and amount; assert none appears in output. Add option-contract tests proving record requires `--runtime-tolerance`, verify rejects it, and both modes require `--membership-inventory`.

- [ ] **Step 2: Confirm the command is absent**

Run `.venv/bin/pytest -q tests/test_cli.py -k verify_corpus`.

Expected: failures because Typer has no `verify-corpus` command.

- [ ] **Step 3: Implement validated CLI options and exit mapping**

Add `verify_corpus_command()` with explicit retained, quarantine, membership-inventory, baseline, work, mode, jobs, and optional runtime-tolerance options. Parse numeric strings without float conversion. Enforce the mode-specific tolerance contract before running. Catch typed gate input/runtime errors as exit 1 and typed acceptance errors as exit 2. Print only fields from `CorpusGateAttestation`.

- [ ] **Step 4: Run CLI and gate tests**

```bash
.venv/bin/pytest -q tests/test_cli.py tests/test_corpus_gate.py
```

Expected: pass.

- [ ] **Step 5: Commit CLI support**

```bash
git add src/ccparser/cli.py tests/test_cli.py
git commit -m "feat: expose corpus verification command"
```

### Task 5: Documentation and full gate-module verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: completed CLI.
- Produces: reproducible private `record` and `verify` operator workflow.

- [ ] **Step 1: Add generic ignored-path examples**

Document commands using `artifacts/corpus-membership.json`, `artifacts/corpus-baseline.json`, and a unique `artifacts/corpus-run-*` directory; do not include source hashes, transaction totals, or current corpus values. Explain that the ignored membership inventory is an independent acceptance input derived from the previously approved complete corpus, not something `record` regenerates. Explain that `record` is permitted only from a clean committed revision after review, requires `--runtime-tolerance`, and can never change the approved membership inventory. Verify omits the tolerance and uses the accepted value.

- [ ] **Step 2: Run all repository gates**

```bash
.venv/bin/ruff format .
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Expected: all commands pass.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md
git commit -m "docs: document private corpus attestations"
```
