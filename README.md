# ccparser

`ccparser` is a local, conservative credit-card statement parser designed for
Hebrew and mixed right-to-left PDFs. It extracts positioned digital text, uses
Tesseract only when a page needs OCR, reconstructs transaction tables, and
reconciles every emitted transaction group against the total printed in the
document.

The parser does not guess through ambiguous layouts. A document is reported as
`reconciled` only when its transactions balance exactly with `Decimal`
arithmetic and no extraction ambiguity remains.

## Requirements

- Python 3.13
- Tesseract with Hebrew and English language data

On Debian or Ubuntu, install the system OCR dependencies with:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-heb
```

Create the environment and install the project:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Parse statements

Parse one PDF:

```bash
.venv/bin/ccparse parse statement.pdf --output-dir output
```

Parse every PDF below a directory, using four workers and an explicit local OCR
cache:

```bash
.venv/bin/ccparse parse documents \
  --output-dir output \
  --jobs 4 \
  --cache-dir .cache/ocr
```

Each run atomically writes two files:

- `results.json`: the complete deterministic result, including reconciliation,
  diagnostics, table structure, and positioned source evidence.
- `transactions.csv`: a flat UTF-8 CSV for downstream analysis. Amounts use
  plain decimal strings and dates use ISO `YYYY-MM-DD` form.

Foreign-currency transactions may include a nullable `foreign_exchange` JSON
object. Its exchange rate, fee percentage, gross fee, fee discount, and net fee
values each retain field-level page, bounding-box, and raw-text evidence. A net
fee derived exactly as gross fee minus discount has the
`gross_fee_minus_discount` derivation; directly printed fees use `printed`.

The CSV appends equivalent FX value, currency, derivation, source-page, and
source-bounding-box columns after the original columns. Existing JSON keys and
CSV columns retain their meanings and order. Consumers should ignore unknown
JSON keys and trailing CSV columns so additive schema extensions remain
compatible.

Document statuses are:

- `reconciled`: all groups match their printed totals exactly and contain no
  unresolved transaction ambiguity.
- `unreconciled`: a statement was parsed, but at least one ambiguity,
  diagnostic, or nonzero difference remains.
- `unsupported`: statement evidence was incomplete or could not be associated
  safely.
- `not_statement`: positive evidence identifies a supported unrelated document
  type.

Use `--strict` when automation should exit with code 2 unless the complete run
is `reconciled`. Invalid input or runtime failures exit with code 1.

Normalization also accounts for meaningful transaction-row evidence. Unassigned
merchant-boundary text, unexplained semantic text, and unresolved conversion-date
candidates remain attached to the billed transaction as ambiguities, so an exact
arithmetic total alone cannot produce a strict success. Explicit but unparseable
or contradictory exchange-rate and foreign-currency-fee evidence is likewise a
transaction ambiguity and prevents strict success.

## Audit a document directory

Audit is a dry run by default:

```bash
.venv/bin/ccparse audit documents --quarantine-dir unrelated
```

Apply the decisions with:

```bash
.venv/bin/ccparse audit documents --quarantine-dir unrelated --apply
```

Only documents supported by high-confidence positive non-statement evidence
are moved. Ambiguous documents remain in place for review. Applied moves are
recorded in `unrelated/manifest.json`, and an apply failure rolls back every
move from that invocation.

## Privacy and evidence

PDF bytes, OCR, parsing, and reconciliation stay on the local host. The default
OCR cache is `~/.cache/ccparser/ocr`; set `--cache-dir` to choose another local
location. Generated JSON and CSV contain financial data and raw source evidence,
so keep output and cache directories private and out of version control.

The parser retains page numbers, bounding boxes, and raw cell text for every
transaction. Hebrew display order is reconstructed from glyph geometry instead
of trusting the often-reversed PDF text stream.

## Private corpus regression gate

The tracked test suite uses synthetic fixtures and cannot attest to the private
document corpus. Parser, extraction, evidence, reconciliation, OCR, and output
changes therefore also require the private corpus gate before corpus acceptance
or merge. PDFs, membership data, baselines, run outputs, and caches remain local
under ignored paths and never enter Git.

The membership inventory is an independently established, protected acceptance
input for the previously approved complete retained and quarantine sets. Its
full-file SHA-256 is pinned separately where `record` cannot replace it. VERIFY
likewise requires the accepted baseline's separately protected full-file
SHA-256. Neither pin is inferred from the file being checked. A smaller passing
corpus or rewritten baseline therefore cannot silently become the acceptance
state. Keep the inventory and accepted baseline read-only during normal
operation and use a fresh, empty `artifacts/corpus-run-*` work directory for
every invocation.

`record` is an exceptional baseline promotion, not a routine way to make a
failed verification pass. Run it only after the intended behavior has been
reviewed and committed, with the worktree clean at that exact commit. Supply a
reviewed finite, non-negative decimal runtime tolerance explicitly:

```bash
PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus documents \
  --quarantine-dir unrelated \
  --membership-inventory artifacts/corpus-membership.json \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline artifacts/corpus-baseline-candidate-UNIQUE.json \
  --work-dir artifacts/corpus-run-record-UNIQUE \
  --mode record \
  --jobs 4 \
  --expected-commit-sha "$EXPECTED_REVIEWED_SHA" \
  --runtime-tolerance 0.20
```

Replace both `UNIQUE` values with new run identifiers and replace the example
tolerance with the reviewed threshold. The two uppercase variables must come
from protected controller configuration, not from the current inventory or
current `HEAD`. RECORD requires a nonexistent baseline-candidate path and
publishes it without replacement; it cannot overwrite the accepted baseline.
It also never regenerates or changes `artifacts/corpus-membership.json`. After
reviewing the candidate, calculate its full-file SHA-256 without printing it and
store both its selected path and digest in protected controller configuration.

Routine acceptance uses `verify` from the clean, reviewed commit. Verification
omits `--runtime-tolerance` because it uses the value stored in the accepted
baseline:

```bash
PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus documents \
  --quarantine-dir unrelated \
  --membership-inventory artifacts/corpus-membership.json \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline artifacts/corpus-baseline.json \
  --baseline-sha256 "$APPROVED_CORPUS_BASELINE_SHA256" \
  --work-dir artifacts/corpus-run-verify-UNIQUE \
  --mode verify \
  --jobs 4 \
  --expected-commit-sha "$EXPECTED_REVIEWED_SHA"
```

The candidate-local `PYTHONPATH` is required. The command moves the complete
acceptance run into a fresh `python -I -S` worker, explicitly adds only the
candidate source and required installed dependency roots, and rejects an
imported parser package that is not the package in the active Git worktree.

On success, the command emits exactly one aggregate attestation line containing
pass status, mode, retained/reconciled/quarantined counts, elapsed time, and an
explicit performance status. A successful verify reports
`performance_checked=true`; record mode reports `performance_checked=false`
because it establishes the baseline. On failure, its one line contains only
fail/error status and closed reason codes. It never emits source names, source
hashes, document contents, diagnostics, transactions, or financial values.
Exit code 0 from verify means the retained and quarantine acceptance policies
passed and the authenticated baseline, complete toolchain fingerprint, worker
count, and runtime bound were enforced. The toolchain fingerprint binds exact
installed dependency bytes, Python runtime flags, native mappings and relevant
environment, PyMuPDF's binding and engine, and the exact Git, Tesseract,
traineddata, and OCR-config bytes. Git and Tesseract execute through sealed
copies of their ELF interpreter and shared-library closure. A selective Linux
seccomp/ptrace broker rejects any later executable mapping outside that sealed
closure before it can execute. This gate therefore requires Linux 5.3 or newer
with procfs, memfd sealing, ptrace, and seccomp enabled; unavailable kernel
controls fail closed. Exit code 1 is an input or runtime failure, and exit code
2 is a completed acceptance failure.

These controls are a deterministic regression boundary, not a sandbox for
hostile native code or a hostile same-UID process. The broker's Python
interpreter and standard library are covered by the surrounding toolchain
fingerprint and before/after checks, but are not themselves launched from a
sealed closure; an already executing approved native tool can also use Linux
process-memory interfaces such as `/proc/self/mem` to alter its private pages.
Loaded-origin checks rely on trusted interpreter/import machinery and static
pre/post byte identities; they do not authenticate a deliberately forged live
Python object graph or transient in-process self-modification.
Run the private gate on a trusted, single-purpose worker with no concurrent
same-UID processes when protection from active local tampering is required.

An automated private controller must confirm both before invocation and again
immediately after success that `git rev-parse HEAD` equals its independently
pinned full reviewed SHA and that the worktree is clean. It passes that same SHA
to `--expected-commit-sha`; the gate checks it at its initial and final
boundaries. The controller must likewise supply the independently pinned
inventory-file and accepted-baseline SHA-256 values and require exit code 0,
`mode=verify`, exactly 104 retained documents, exactly 104 reconciled documents,
and exactly 5 quarantined documents. The workflow must additionally require
`performance_checked=true`. A toolchain or worker-count mismatch fails verify
with `runtime_context_drift`.

## Development

Repository-wide instructions are in [`AGENTS.md`](AGENTS.md). The required
verification gates are:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```
