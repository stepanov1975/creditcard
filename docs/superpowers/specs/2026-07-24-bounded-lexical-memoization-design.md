# Bounded Lexical Memoization Design

**Status:** Approved for implementation

## Goal

Reduce full-corpus conversion time by reusing repeated pure lexical computations while
preserving extraction, discovery, normalization, reconciliation, evidence, diagnostics,
JSON, and CSV behavior exactly.

## Problem

Privacy-safe local profiling found that conversion repeatedly tokenizes the same short
strings and repeatedly parses the same text-and-currency-hint pairs as monetary lexemes.
These calls occur inside discovery and per-transaction semantic validation, so their cost
is multiplied by candidate table scans and normalization passes. Directory parsing uses
threads; repeated Python work therefore also increases interpreter-lock contention.

OCR, PDF rendering, and output publication are not the primary target of this change.
Changing worker type or count would trade CPU behavior against cold-cache OCR concurrency
and would interact with the protected corpus gate's bound runtime. Discovery-region
restructuring could remove additional repeated work, but it changes more interfaces and is
not needed for the first measured improvement.

## Design

### Phrase tokenization

`ccparser.text_tokens.phrase_tokens()` keeps its existing public signature and return type.
Its implementation delegates to a private bounded `functools.lru_cache` keyed by:

- the complete source string; and
- `ignore_acronym_quotes`.

The cached value is the existing immutable `tuple[str, ...]`. The normalization,
case-folding, format-control handling, punctuation boundaries, Hebrew clitic behavior, and
acronym-quote policy do not change. The cache holds at most 8,192 entries.

### Monetary lexical parsing

`ccparser.money._parse_lexical()` becomes a bounded `functools.lru_cache` keyed by:

- the complete source string; and
- the complete optional currency hint.

The cached value is the existing frozen `_LexicalAmount`, including its exact `Decimal`,
currency, and diagnostic tuple. Marker handling, sign rules, grouping validation,
currency conflicts, and public `is_money_shaped()` and `parse_amount()` behavior do not
change. The cache holds at most 4,096 entries.

### Lifetime, memory, and concurrency

Both caches are process-local, bounded, and contain only values already processed locally.
They do not write document text to disk or change canonical output. Standard-library LRU
cache synchronization makes shared access safe for the existing thread pool; duplicate
work on simultaneous first misses is acceptable because both computations are pure.

The limits are large enough to retain the strongly repeated working set observed during a
statement conversion while placing a fixed ceiling on retained entries in long-lived
processes. Eviction can only cause recomputation, never a semantic change.

## Functional invariants

- Every cache key includes every argument that can affect the result.
- Cached return values remain immutable.
- No financial operation uses binary floating point; monetary results remain `Decimal`.
- No filename, path, hash, date, merchant, amount, total, or document-specific behavior is
  introduced.
- Cache hits and misses produce value-equal parser models and byte-identical canonical JSON
  and CSV.
- Worker selection, OCR cache behavior, and private corpus gate behavior remain unchanged.

## Test strategy

Focused tests will be added before production changes and observed failing for repeated
work:

1. Repeating the same phrase-token request performs the uncached normalization once.
2. The acronym-quote flag creates an independent phrase-token cache key.
3. Repeating the same monetary text and hint performs lexical parsing once.
4. Distinct currency hints create independent monetary cache keys and retain their existing
   results.

Existing lexical, money, FX, discovery, normalization, reconciliation, parser, and output
tests remain the behavioral regression boundary. The required Ruff, mypy, and complete
pytest gates will run after implementation.

## Performance and corpus verification

The ignored local profiler will rerun the same anonymous representative conversion before
and after the change and require value-equal discovery and normalization outputs. A warm
diagnostic batch run may be used to confirm improved throughput, but it is not corpus
acceptance.

Because this change affects discovery and normalization, full corpus acceptance still
requires a reviewed committed SHA, a clean worktree, protected membership and baseline
pins, repeated empty-cache runs, matching toolchain and worker count, baseline parity, and
`performance_checked=true` from the formal private gate. Tracked tests alone will not be
reported as a corpus pass.
