# Corpus Regression Prevention and Strict Recovery Design

## Goal

Prevent unverified corpus-pass claims and repair the parser until every one of the
104 retained local statements reconciles under the current semantic-evidence
strictness. The recovery must preserve all recovered transactions and provenance,
restore lost structured FX data, and remove the measured performance regression.

The corpus is an acceptance oracle, not a source of document-specific rules. Every
production change must be justified by a general extraction, geometry, semantic
ownership, or reconciliation rule and covered by a minimized synthetic test.

## Constraints

- Use Python 3.13 and the repository virtual environment at `.venv`.
- Develop every production behavior red-green-refactor.
- Keep financial arithmetic in `Decimal` and preserve exact reconciliation.
- Preserve the newer semantic-evidence completeness policy. Do not downgrade,
  suppress, or allowlist ambiguity diagnostics merely to make strict mode green.
- Do not branch on a filename, path, hash, document, issuer, merchant, date, amount,
  total, or corpus ordinal.
- Keep documents, source hashes, canonical parser output, and derived financial data
  in ignored private storage outside Git.
- Make no changes outside `/root/creditcard` during this recovery.
- Preserve the public JSON/CSV schema, ordering, evidence, and deterministic output.

## Established Baseline

Direct local artifacts prove that the same 104 source hashes once reconciled under
strict mode. The current cleanup branch processes the same documents but no longer
reconciles the complete retained corpus because recovered transactions retain
unresolved semantic ambiguity. This is a semantic ownership problem, not a
monetary-row loss.

The current cleanup branch also loses exchange-rate values and their provenance
because boundary-aware token matching rejects a supported Hebrew cue with an attached
grammatical prefix. Fresh-cache runtime regressed materially, primarily because
column-header scoring repeatedly tokenizes normalized headers and static cue
vocabularies.

## Considered Approaches

### Gate-first generalized repair

Build a reproducible corpus gate, classify ambiguity failures by stable semantic
reason, add minimized failing tests, repair one general rule at a time, and rerun the
gate after each cluster. Restore FX and performance behavior before final acceptance.

This is the selected approach. It preserves strictness and makes each improvement
auditable.

### Roll back strictness and reapply it

Return to the earlier permissive result and reintroduce semantic validation later.
This gives a fast green result but temporarily accepts unowned semantic evidence and
creates a second migration. It is rejected.

### Corpus exceptions or golden allowlists

Suppress known failures by source identity or observed content. This would make the
current corpus pass while breaking generality and hiding future failures. It is
rejected.

## Architecture

### Corpus gate

Add a focused `ccparser.corpus_gate` module and a `ccparse verify-corpus` command. The
module owns typed configuration, private baseline/attestation models, deterministic
comparison, toolchain fingerprinting, and privacy-safe summaries. The CLI owns option
validation and exit codes.

The command requires explicit paths for:

- the retained statement directory;
- the quarantined/non-statement directory;
- an ignored private baseline manifest;
- an ignored private work directory.

It refuses overlapping input/output/cache topology, symlinks masquerading as corpus
members, a dirty Git worktree, a missing baseline in verification mode, and any
pre-populated run cache. Raw parser output and per-document hashes are written only
below the private work directory.

Two modes are supported:

1. `verify` compares a new run with the last explicitly accepted private baseline.
2. `record` creates a baseline only after all strict, determinism, quarantine, and
   structural checks pass. It never records a failing run as accepted.

There is no permissive force flag. A legitimate output migration requires reviewing
the private delta and running `record` from a clean committed revision.

### Private baseline and attestation

The versioned private manifest records:

- exact Git commit and clean-worktree state;
- an order-independent digest of the retained and quarantined source-hash sets;
- Python, package, PyMuPDF, and Tesseract versions and OCR command/cache versions;
- canonical JSON and CSV digests for two independent runs;
- ordered statement-status and transaction-identity digests;
- aggregate document, status, group, row-result, transaction, ambiguity, and
  evidence-field-presence counts;
- elapsed time and configured runtime tolerance.

The manifest may contain source hashes and derived aggregates, so it remains ignored
and private. Console output contains only the commit abbreviation, toolchain digest,
aggregate counts, elapsed time, and pass/fail reason codes.

### Deterministic execution

Each retained-corpus verification performs two complete parses with separate newly
created empty OCR caches and output directories. Both runs must:

- process exactly the same expected corpus membership;
- reconcile every retained statement under strict semantics;
- produce byte-identical canonical JSON and CSV;
- preserve identical ordered statement, group, transaction, and evidence structure.

The quarantined corpus is parsed separately without strict mode. Every entry must be
`not_statement`, and its two runs must also be byte-identical.

Verification against the accepted baseline rejects:

- a status downgrade or corpus membership change;
- removed/reordered transactions or groups;
- a formerly non-null field becoming null;
- lost or changed evidence provenance;
- ambiguity growth;
- canonical JSON/CSV drift without an explicit new baseline;
- runtime exceeding the configured same-toolchain tolerance.

Runtime comparison is a hard gate only when the toolchain fingerprint and configured
worker count match. Deterministic unit tests additionally guard hot-path tokenization
call counts so a performance regression does not depend only on wall-clock timing.

## Strict Semantic Recovery

### Failure inventory

Add a private diagnostic projection that groups failures by stable ambiguity code,
layout role, evidence-atom disposition, and generalized geometry shape. It must not
print or persist merchant text, dates, amounts, source names, or document hashes in
console output.

For each cluster:

1. select the smallest representative privately;
2. reproduce its rule with minimized synthetic positioned evidence;
3. write a focused failing test;
4. repair the narrowest general semantic rule;
5. run the focused and affected suites;
6. rerun the corpus diagnostic projection and verify that no other cluster grows.

### Evidence ownership rules

The semantic ledger remains authoritative. High-confidence evidence may become
non-ambiguous only when it is:

- claimed by an emitted field with exact supporting provenance;
- claimed by a recognized ancillary semantic role proven by column/header and
  repeated-layout evidence;
- identified as a narrowly bounded layout artifact using source and geometry rules;
- retained as an explicit ambiguity.

No generic “ignore unknown text” or “claim remaining evidence” fallback is allowed.
Description boundaries, fragmented dates, category/location/reference fields,
continuation details, and supported FX details retain separate typed ownership paths.
Claims must remain non-overlapping unless the ledger explicitly permits compatible
shared provenance.

### Reconciliation

Reconciliation arithmetic and strict policy do not change. Transactions with genuine
ambiguity remain inspectable and keep the statement non-successful. The recovery
changes extraction or ownership only when the evidence uniquely supports it.

## FX Cue Repair

Retain token-boundary protection against substring false positives. Extend phrase
matching with an explicit, tested lexical policy for supported single-letter Hebrew
clitics attached to the first token of a cue. The matcher must not become a general
suffix/substring matcher.

Add an end-to-end synthetic case that passes through header role inference,
continuation tagging, FX extraction, normalization, JSON, and CSV. It must assert the
rate value and exact page/bounding-box provenance. Existing negative cases such as
embedded English substrings remain non-matches.

## Performance Repair

Tokenize each observed header once per scoring operation and tokenize static cue
vocabularies once at module load or immutable policy construction. Internal matchers
operate on token tuples rather than re-normalizing strings.

Add deterministic tests that count tokenization calls for a header-scoring operation
and prove the count is independent of vocabulary size after policy construction.
Retain a small same-process benchmark as diagnostic evidence, while the full corpus
gate enforces the accepted same-toolchain runtime tolerance.

## Error Handling

- Exit 0: every correctness, determinism, baseline, quarantine, and applicable
  performance check passes.
- Exit 1: invalid paths, unsafe topology, unavailable Git/toolchain metadata, corrupt
  baseline, or parser runtime failure.
- Exit 2: a completed run violates corpus acceptance or baseline parity.

Errors use a closed privacy-safe reason vocabulary. Raw exception text, paths, source
names, hashes, and document content are not emitted by the gate.

Interrupted runs leave their private work directory for diagnosis but never update
the accepted baseline. Baseline writes are atomic and occur last.

## Testing Strategy

Every production change follows red-green-refactor. Required tracked tests include:

- manifest validation, versioning, atomic writes, and corruption handling;
- empty-cache enforcement and safe path topology;
- clean-revision and toolchain fingerprint behavior through injected protocols;
- synthetic retained/quarantined batches for every gate failure reason;
- exact structural comparison, including non-null-to-null and provenance loss;
- two-run determinism and baseline record/verify flows;
- privacy-safe console output and exception redaction;
- minimized tests for every semantic ambiguity cluster repaired;
- attached-clitic positive and substring-negative FX cue cases;
- end-to-end FX value and provenance serialization;
- deterministic header-tokenization call-count coverage;
- all existing unit, Ruff, mypy, and coverage gates.

Private acceptance then runs:

1. the diagnostic projection to confirm zero unresolved retained-statement ambiguity;
2. two fresh-cache strict parses of all 104 retained PDFs;
3. two fresh-cache parses of the quarantined set;
4. canonical and structural parity against the newly accepted private baseline;
5. a same-toolchain runtime comparison against the pre-refactor baseline.

## Acceptance Criteria

- All tracked tests and repository quality gates pass.
- The gate itself is covered by synthetic tests and cannot record a failed baseline.
- Both fresh-cache retained-corpus runs report 104 documents, 104 reconciled, and no
  other status.
- The two retained JSON/CSV output pairs are byte-identical.
- Every quarantined document is `not_statement` in two byte-identical runs.
- No previously present transaction, field, FX value, or provenance is lost.
- All previously present exchange rates and their exact evidence are restored.
- Runtime returns within the accepted same-toolchain tolerance and the tokenization
  hot path no longer repeats normalization by vocabulary item.
- No production rule depends on private document identity or observed literal values.
- No private corpus data, source hashes, output, caches, or manifests enter Git.
