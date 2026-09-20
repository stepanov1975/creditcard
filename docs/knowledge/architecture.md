# Architecture and engineering lessons

This describes the merchant-gold-seed checkout at `6c500cc`, not the different
semantic/observation implementations preserved on side branches. Public contracts
are in [README](../../README.md) and [SUPPORT](../../SUPPORT.md); terminology is in
[CONTEXT](../../CONTEXT.md).

## Current parser boundaries

| Stage | Code | Responsibility |
| --- | --- | --- |
| CLI and orchestration | [cli.py](../../src/ccparser/cli.py), [parser.py](../../src/ccparser/parser.py) | Validate inputs, coordinate extraction/discovery/normalization, select conservative status, bound batch concurrency. |
| Positioned source evidence | [evidence](../../src/ccparser/evidence), [geometry.py](../../src/ccparser/geometry.py) | Digital words/glyphs, selective local Tesseract OCR, source identity and page coordinates. |
| Table and row discovery | [discovery.py](../../src/ccparser/discovery.py), [layout](../../src/ccparser/layout) | Regions, columns, rows, row tags and continuation relationships. |
| Field normalization | [normalize.py](../../src/ccparser/normalize.py), `normalization_*.py`, [fx.py](../../src/ccparser/fx.py), [original_amount.py](../../src/ccparser/original_amount.py) | Dates, merchant/description, billed and original amounts, installments and FX evidence. |
| Semantic ownership | [semantic_evidence.py](../../src/ccparser/semantic_evidence.py), [normalization_semantics.py](../../src/ccparser/normalization_semantics.py) | Attribute meaningful evidence and retain ambiguity instead of discarding unexplained text. |
| Exact reconciliation | [reconcile.py](../../src/ccparser/reconcile.py), [decimal_math.py](../../src/ccparser/decimal_math.py) | Exact group totals, currency/minor-unit checks and occurrence membership. |
| Publication | [output.py](../../src/ccparser/output.py), [_output_publication.py](../../src/ccparser/_output_publication.py) | Deterministic JSON/CSV and atomic output publication. |
| Corpus acceptance | [corpus_gate.py](../../src/ccparser/corpus_gate.py), [corpus_spool.py](../../src/ccparser/corpus_spool.py) | Protected membership/baseline verification, repeated runs and bounded-memory output handling. |
| Research | [experiments/row_extraction](../../experiments/row_extraction) | Frozen evaluation and historical experiments; not a production integration layer. |

The parser can retry numeric OCR on OCR-required pages after an unsuccessful
normalization. It adopts the repaired result only if it is exactly reconciled and
unambiguous. This existing production recovery is distinct from the stopped
row-extraction experiments.

## Contracts worth preserving

- **Money is exact.** Use `Decimal` for financial arithmetic. Preserve billed
  currency, direction, original currency/amount and source-backed FX components;
  do not choose values simply because they make a total balance.
- **Balanced is insufficient.** `reconciled` requires groups with exact totals and
  no unresolved extraction ambiguity. Unsupported evidence, conflicting dates,
  merchant boundaries and unexplained semantic fragments must remain visible.
- **Merchant and description differ.** Current output has nullable `merchant`
  separately from the broader `description`. Do not import a side branch's older
  merchant-only description terminology as the current JSON contract.
- **Evidence survives normalization.** Page, bounding box and raw text support
  financial fields and merchant attribution. Continuations need an owner; nearby
  text alone is not ownership proof. Repeated text can represent distinct source
  occurrences and must not be collapsed indiscriminately.
- **Logical text order needs geometry.** Native PDF word order and glyph order
  can both be wrong. Mixed RTL/LTR, punctuation and spacing are separate issues;
  a global reversal or whitespace deletion is not a general repair.
- **Conservative failures are useful output.** `unsupported`, `unreconciled` and
  positive `not_statement` classifications are distinct. The CLI's `--strict`
  exits 2 for a non-reconciled run; invalid input/runtime failures exit 1.
  The internal `parse_statement(strict=...)` currently discards that argument;
  Python APIs are not the supported compatibility surface.
- **Compatibility is explicit.** Existing JSON meanings and CSV column order
  remain stable; consumers tolerate unknown JSON keys/trailing CSV columns.
  Published release tags are immutable.

## Verification and operational lessons

Use Python 3.13 in `.venv`, synthetic tracked fixtures, focused failing tests
before production behavior changes, then all four gates in AGENTS.md. This
housekeeping change modifies documentation only and adds no production behavior.

Tracked tests do not prove private corpus acceptance. For a parsing/evidence/output
change, acceptance or merge additionally requires the reviewed committed SHA,
a clean candidate worktree before/inside/after verification, independently pinned
membership and baseline, 104 retained and reconciled documents, five quarantine
results, deterministic repeats, toolchain/worker parity and
`performance_checked=true`. Follow the complete [operating commands](../../README.md#private-corpus-regression-gate)
and [binding policy](../../AGENTS.md#private-corpus-acceptance-policy).

Keep corpus output private; normal parser output can expose source names. Treat a
cold-cache timeout as no verdict. Use constant-memory hashing for large output
comparisons after validating the baseline pin. A diagnostic parse or byte parity
alone does not replace formal verification. Never record a new baseline merely
to absorb a regression. Lexical memoization and streaming were bounded performance
changes, not permission to weaken evidence or acceptance; see the
[evidence index](evidence-index.md).

The [release notes](../releases/v0.1.0.md) record acceptance for the exact published
release. They do not attest to the current dirty documentation worktree or to
experimental merchant outputs.
