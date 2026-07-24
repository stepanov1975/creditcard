# Bounded-Memory Corpus Verification Design

## Goal

Make the private corpus gate process statement results with bounded memory while
preserving its full correctness, determinism, provenance, membership, output, and
performance guarantees.

With `jobs=1`, the verifier must keep at most one corpus statement model live at a
time. It must still prove byte-for-byte parity for the same aggregate
`results.json` and `transactions.csv` produced for the complete ordered corpus.

## Context

The existing parser already converts documents sequentially when `jobs=1`, but
`parse_directory()` retains every `StatementResult` in one `BatchResult`. The gate
then retains two complete corpus batches while independently projecting and
serializing them. Measurements on the private retained corpus show that one batch
model occupies roughly 1.7 GiB and whole-batch canonicalization raises one run's
peak to roughly 4 GiB. Retaining the first run while canonicalizing the second
raises the gate to roughly 6 GiB.

Individual measured reports peak around 116--161 MiB. The problem is therefore
corpus-sized retention and serialization, not the memory required to convert one
report.

## Constraints

- Preserve the public `parse_directory()` interface, returned `BatchResult`, JSON
  schema, CSV schema, ordering, diagnostics, and atomic output behavior.
- Preserve exact aggregate JSON and CSV bytes in the corpus gate. Per-document
  parity alone is insufficient.
- Preserve deterministic relative-POSIX source order, including nested paths.
- Preserve all four independent gate runs: two retained and two quarantine runs,
  each with its own initially empty output and OCR cache directories.
- Preserve protected membership, clean reviewed commit, toolchain, worker-count,
  strict retained reconciliation, quarantine classification, deterministic repeat,
  accepted-baseline, and runtime checks.
- Keep private documents, statement models, spool records, outputs, and derived
  values in ignored private paths. Never log source names, hashes, financial values,
  or per-document diagnostics.
- Preserve existing gate reason codes and their deterministic policy order.
- Follow the repository's test-driven workflow for every production change.

## Considered Approaches

### Disk-spooled streaming corpus runner

Share deterministic directory conversion between the public batch parser and the
gate. The public adapter continues collecting statements in memory. The gate adapter
writes each completed statement to a private ordinal spool and releases the model,
then assembles and verifies the aggregate outputs with constant-memory passes.

This is the selected approach. It preserves the complete corpus contract while
making live model memory proportional to the configured worker count rather than
the corpus size.

### One isolated CLI invocation per document

Run the full CLI against 109 one-file staging directories and combine the results.
This gives strong process-level memory reclamation, but it changes relative source
names, directory traversal, aggregate status and diagnostics, output atomicity,
worker semantics, and runtime composition. Reconstructing the original aggregate
contract would require a second custom pipeline while process startup would become a
material part of the performance result. It is rejected.

### Retain one batch or serialization at a time

Drop the first `BatchResult` before starting the second run, or compare only files
after each run. This removes overlapping corpus graphs but still requires one
roughly 1.7 GiB batch and a roughly 4 GiB whole-batch serialization peak. It does not
provide a safe margin on the current worker and is rejected.

## Architecture

### Shared ordered directory conversion module

Extract the internal directory-conversion mechanics currently owned by
`parse_directory()` behind one small internal interface. The module owns:

- input, output, and cache path validation;
- deterministic regular-PDF discovery;
- relative source-name assignment;
- bounded worker scheduling;
- parser exception translation; and
- delivery of each `(source_ordinal, StatementResult)` to a caller-provided sink.

The scheduler submits no more than `jobs` documents at once. It consumes completed
futures promptly instead of allowing ordered executor buffering to retain later
results behind one slow earlier document. Completion order is allowed to vary;
source ordinals are authoritative for every output and digest.

Two adapters make this a real seam:

1. The existing public parser adapter collects results by ordinal, constructs the
   unchanged `BatchResult`, and calls the existing public output path.
2. The corpus gate adapter writes each result under its ordinal and immediately
   releases the model.

The shared module is internal and introduces no new public import. `parse_statement()`
remains the single semantic engine for an individual PDF.

### Private statement spool

For each corpus run, the gate creates a mode-0700 spool directory beneath that run's
already ignored, descriptor-bound work directory. Each statement is written as
canonical JSON to an exclusively created, mode-0600 regular file named only by a
zero-padded source ordinal. Spool paths never contain a private source name or hash.
After writing, the gate flushes and fsyncs the record, captures its size and SHA-256,
changes it to mode 0400, and closes it. Every later read must match that sealed
identity before and after consumption.

The spool records retain the complete statement output because exact aggregate JSON,
CSV, and structural projections all depend on it. They are disk-backed and are read
one record at a time. A record is validated as canonical and schema-valid before it
is consumed. The spool is removed after the run manifest and output checks complete,
including on failures.

While parsing, the gate retains only bounded status counters and the current result.
It does not retain a statement tuple, a `BatchResult`, CSV rows, or corpus-sized
projection tuples.

### Streaming aggregate output

After every statement is spooled, derive batch status and diagnostics with the exact
existing rules. This second phase is necessary because batch diagnostics are not
known until every statement status is known, and each CSV row embeds batch
diagnostics.

Read spool records in ordinal order and stream both final outputs:

- JSON uses the same NFC normalization, recursively sorted keys, compact separators,
  UTF-8 encoding, and single final newline as `canonical_json_bytes()`.
- CSV uses the same UTF-8 BOM, column order, quoting, CRLF line endings, empty-row
  rules, transaction order, group lookup, and diagnostic ordering as
  `transactions_csv_bytes()`.

The output module exposes shared row iteration and canonical writing primitives so
the in-memory and streaming adapters cannot drift into separate serialization
policies. Existing public byte-returning functions remain unchanged at their
interfaces.

Both streamed outputs are rendered to temporary regular files, flushed, fsynced,
and published as an atomic pair with the existing rollback guarantee. A failure
cannot leave a new JSON file paired with an old or partial CSV file.

### Streaming run projection

Replace corpus-sized projection tuples with incremental canonical sequence hashing.
For each structural dimension, feed the exact canonical outer-array grammar and each
statement's canonical projection into SHA-256 in source order. The resulting digests
must equal `project_run()` for the equivalent in-memory `BatchResult`:

- ordered batch and statement statuses;
- reconciliation group structure;
- transaction identities and group membership;
- field presence;
- evidence provenance; and
- ambiguity structure.

Counts use scalar totals and the existing bounded set of field paths. JSON and CSV
digests are computed with constant-memory file hashing. A second canonical pass over
the sealed spool is compared with the published files, preserving the current
requirement that emitted outputs equal the canonical result rather than merely
trusting successful publication.

`CompletedCorpusRun` no longer owns a `BatchResult`. It contains only:

- the `RunManifest`;
- the aggregate batch status;
- membership snapshots immediately before and after conversion; and
- any small disposition data required to prove all retained documents reconciled or
  all quarantine documents were classified as non-statements.

The existing manifest and private baseline schema remain unchanged because their
observable semantics and digests remain unchanged.

## End-to-End Data Flow

For each of the two retained and two quarantine runs:

1. Validate bound path reachability and snapshot both the bound input and original
   corpus membership.
2. Start the parser-run timer.
3. Enumerate documents once in deterministic relative-path order.
4. Parse at most `jobs` documents concurrently; with `jobs=1`, parse exactly one at
   a time.
5. Assign the canonical relative source name, write the ordinal spool record, and
   release each `StatementResult`.
6. Derive aggregate batch status and diagnostics.
7. Stream, fsync, and atomically publish aggregate JSON and CSV.
8. Stop the parser-run timer and snapshot membership again.
9. Stream the manifest projections and independently check the published output
   digests against the canonical spool.
10. Remove the spool and return the compact completed-run value.

After all four runs, construct the candidate baseline and execute the existing
membership, count, status, determinism, accepted-baseline, toolchain, worker-count,
runtime, repository-state, and final-state policies without retaining corpus models.

The timed interval continues to represent end-to-end conversion through durable
output publication. Gate setup, membership snapshots, manifest comparison, and
toolchain comparison remain outside it.

## Error Handling and Security

- A statement parser exception aborts the run with
  `parser_runtime_failed`, matching current behavior.
- Retained reconciliation and quarantine classification mismatches do not fail
  early. All documents are converted so counts, membership, output, and aggregate
  acceptance reasons remain complete.
- Missing, non-regular, non-canonical, corrupt, reordered, duplicated, or
  schema-invalid spool records fail closed as `parser_runtime_failed`.
- Spool and temporary-output operations use descriptor-relative or already bound
  paths, no-follow semantics where supported, exclusive creation, restrictive
  permissions, and explicit regular-file checks.
- Output creation, flush, fsync, publication, rollback, cleanup, and descriptor close
  failures follow the current runtime-error boundary.
- Original and bound corpus membership snapshots remain required before and after
  every run, with final corpus, repository, and toolchain checks after all runs.
- No private record content appears in exceptions, aggregate CLI output, tracked
  fixtures, commit messages, or public logs.

## Memory and Performance Contract

Live statement-model memory is `O(jobs * largest_statement)` rather than
`O(corpus * retained_runs)`. With `jobs=1`, only one parsed statement and one bounded
serialization buffer may be live. Completed runs retain only manifests and small
status summaries.

The implementation does not promise that Python's allocator returns every arena to
the operating system between documents. It does guarantee that no gate-owned
reference keeps earlier statement or batch graphs reachable. The existing bounded
lexical caches remain process-wide and are not multiplied by the corpus size.

The private acceptance run will measure peak worker RSS diagnostically. For
`jobs=1`, the target is below 1 GiB on the current worker, leaving substantial margin
under its 8 GiB limit. Formal performance acceptance remains the existing
same-toolchain, same-worker-count retained-runtime comparison with
`performance_checked=true`.

## Testing Strategy

Every production behavior is developed red-green-refactor.

### Differential serialization and projection tests

For synthetic batches, compare the streaming path with the existing in-memory
oracle byte for byte and digest for digest. Cases include:

- empty input;
- one and many statements;
- nested relative source paths;
- reconciled, unreconciled, unsupported, non-statement, and mixed statuses;
- statements with no transactions;
- multiple groups and transactions;
- Unicode requiring NFC normalization;
- commas, quotes, carriage returns, and newlines in CSV fields;
- FX fields, evidence sites, field presence, and ambiguities; and
- aggregate diagnostics that must appear in every CSV row.

The test oracle remains `BatchResult`, `canonical_json_bytes()`,
`transactions_csv_bytes()`, and `project_run()`.

### Ordering and bounded-retention tests

- Deliberately complete worker futures out of order and require byte-identical
  source-order outputs and structural digests.
- Assert the scheduler never has more than `jobs` parser calls active.
- Use weak references or an injected lifetime tracker to prove consumed statement
  models become unreachable and that completed runs cannot retain a `BatchResult`.
- Exercise `jobs=1` explicitly as the formal low-memory configuration.

### Failure and compatibility tests

- Parser failure, spool create/write/read corruption, missing or duplicate ordinal,
  output render failure, second-file publication failure, rollback failure, and
  cleanup paths.
- Membership mutation before, during, and after conversion.
- Existing reason-code order, strict retained status, quarantine status, independent
  empty caches, and four-run orchestration.
- Existing public `parse_directory()` return values and JSON/CSV bytes remain
  unchanged.
- Privacy tests confirm that source names, hashes, statement contents, and values do
  not escape through filenames, logs, attestations, or error messages.

### Repository and private verification

Run the required tracked gates:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```

Because the change affects parsing orchestration, output, and corpus verification,
tracked tests are necessary but not sufficient. From the clean reviewed candidate
commit:

1. Run a private diagnostic with `jobs=1` and record privacy-safe peak RSS only.
2. Record a new, nonexistent baseline candidate; never overwrite the accepted
   baseline.
3. Review and independently pin the candidate and protected membership inventory.
4. Run formal `verify` from the same clean full SHA with the exact pins.
5. Require 104 retained documents, 104 reconciled results, 5 quarantine
   non-statements, exact baseline parity, deterministic repeated runs, matching
   toolchain and worker count, and `performance_checked=true`.

Any code or configuration change after attestation invalidates it and requires the
tracked and private gates again.

## Non-Goals

- Changing public parser result models or output schemas.
- Replacing the public in-memory `parse_directory()` return contract.
- Introducing document-specific acceptance rules.
- Running one Python or CLI process per document.
- Changing OCR cache identities, extraction semantics, reconciliation rules, or
  financial arithmetic.
- Publishing private per-document timing, memory, names, hashes, diagnostics, or
  values.

## Acceptance Criteria

- Streaming and in-memory aggregate JSON and CSV are byte-identical for all tracked
  differential cases and the protected corpus baseline.
- Every existing manifest digest and count is unchanged for equivalent input.
- With `jobs=1`, the gate keeps at most one statement result live and retains no
  corpus-sized model after a run.
- Public `parse_directory()` behavior and interfaces remain compatible.
- All existing membership, provenance, determinism, quarantine, toolchain,
  worker-count, runtime, and repository checks remain authoritative.
- Peak worker RSS for the private `jobs=1` diagnostic is below 1 GiB.
- Ruff format, Ruff lint, mypy, and all tests pass.
- Formal private verification succeeds from the clean, independently pinned
  candidate with `performance_checked=true`.
- No private corpus content or derived financial data enters Git or public output.
