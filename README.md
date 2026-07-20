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
arithmetic total alone cannot produce a strict success.

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

## Development

Repository-wide instructions are in [`AGENTS.md`](AGENTS.md). The required
verification gates are:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
```
