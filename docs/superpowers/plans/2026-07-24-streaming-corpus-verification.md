# Streaming Corpus Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace corpus-sized gate retention with a disk-spooled, one-statement-at-a-time verifier that produces the exact existing aggregate JSON, CSV, counts, and manifest digests.

**Architecture:** Extract sink-driven directory conversion behind a small internal parser interface. The public parser keeps its collecting adapter, while the corpus gate uses a secure ordinal spool, shared streaming serializers, and incremental manifest projection so completed runs retain only aggregate metadata.

**Tech Stack:** Python 3.13, Pydantic v2 immutable models, concurrent.futures, descriptor-relative POSIX filesystem operations, hashlib SHA-256, pytest, Ruff, and mypy.

## Global Constraints

- Use Python 3.13 and the repository virtual environment at .venv.
- Follow red-green-refactor for every production behavior: write a focused failing test, run it and confirm the expected failure, implement the minimum behavior, and rerun focused tests.
- Preserve the public parse_directory() signature, returned BatchResult, exception types, JSON schema, CSV schema, ordering, diagnostics, and atomic output behavior.
- Preserve exact aggregate results.json and transactions.csv bytes; per-document parity alone is insufficient.
- Preserve deterministic relative-POSIX source order, trusted descriptor roots, four independent corpus runs, empty per-run caches, protected membership, clean reviewed commit, toolchain, worker count, strict retained reconciliation, quarantine classification, determinism, baseline parity, and performance_checked=true.
- With jobs=1, no gate-owned reference may keep a prior StatementResult or any BatchResult live while the next document is parsed.
- Use Decimal for every financial value; do not introduce binary floating-point financial arithmetic.
- Do not add document-, issuer-, filename-, path-, hash-, merchant-, amount-, total-, or date-specific production branches.
- Keep documents, statement spools, baseline candidates, outputs, caches, memory reports, and all derived private data in ignored local paths.
- Never emit private source names, hashes, financial values, per-document diagnostics, or per-document measurements in logs, tests, commits, or public reports.
- Preserve the version-1 CorpusBaseline and RunManifest schemas and the closed, deterministic reason-code order.
- Before claiming corpus acceptance, use a clean committed full SHA and complete the protected private record/review/pin/verify workflow. Tracked tests alone are not corpus acceptance.

---

## File Map

- Modify src/ccparser/parser.py: expose the internal sink-driven conversion seam, bounded scheduler, shared batch disposition, and unchanged public collecting adapter.
- Modify src/ccparser/output.py: add byte-identical streaming JSON/CSV encoders and streamed atomic pair publication.
- Create src/ccparser/corpus_spool.py: own secure ordinal statement records, stable identity checks, canonical validation, and cleanup.
- Modify src/ccparser/corpus_gate.py: add incremental structural projection, compact CompletedCorpusRun, and the streaming LocalCorpusRunner.
- Create tests/test_directory_conversion.py: characterize the sink interface, bounded scheduling, liveness, ordering, path safety, and privacy-safe failures.
- Modify tests/test_parser.py: prove the public collecting adapter is unchanged.
- Modify tests/test_output.py: differential streaming serialization and atomic rollback coverage.
- Create tests/test_corpus_spool.py: secure spool lifecycle, corruption, ordering, and cleanup coverage.
- Modify tests/test_corpus_gate.py: differential manifest projection, compact run validation, streaming runner integration, tamper detection, and four-run policy coverage.
- Modify no public models, CLI options, CSV columns, baseline fields, or private corpus files.

### Task 1: Add sink-driven bounded directory conversion

**Files:**
- Modify: src/ccparser/parser.py:5-36, 228-364
- Create: tests/test_directory_conversion.py
- Modify: tests/test_parser.py:1020-1485

**Interfaces:**
- Consumes: parse_statement(), iter_regular_pdf_files(), DirectoryRootPolicy, ParserInputError, ParserRuntimeError, and MAX_WORKERS.
- Produces:

~~~python
class StatementResultSink(Protocol):
    def __call__(
        self,
        source_ordinal: int,
        result: StatementResult,
        /,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DirectoryConversionSummary:
    resolved_output_dir: Path
    source_count: int


@dataclass(frozen=True, slots=True)
class BatchDisposition:
    status: Status
    diagnostics: tuple[str, ...]
    document_count: int


def summarize_batch_statuses(
    status_counts: Mapping[Status, int],
) -> BatchDisposition: ...


def convert_directory_statements(
    path: str | Path,
    output_dir: str | Path,
    strict: bool = False,
    jobs: int | None = None,
    *,
    cache_dir: str | Path | None = None,
    statement_parser: StatementParser | None = None,
    result_sink: StatementResultSink,
    directory_root_policy: DirectoryRootPolicy = DirectoryRootPolicy.RESOLVE,
) -> DirectoryConversionSummary: ...
~~~

- Ordinals index the deterministic source tuple. Sink delivery may be completion ordered, but the sink runs only on the coordinator thread.
- At most min(MAX_WORKERS, requested jobs, source count) futures may exist.
- The returned summary contains no StatementResult.

- [ ] **Step 1: Write the sequential delivery and disposition tests**

Create tests/test_directory_conversion.py with synthetic PDF bytes and a statement parser that returns minimal immutable results. Cover nested relative names, zero-based ordinals, empty input, jobs validation, the four batch-status precedence cases, and exact diagnostics:

~~~python
def _result_for(path: Path) -> StatementResult:
    digest = sha256(path.read_bytes()).hexdigest()
    return StatementResult(
        status=Status.RECONCILED,
        transactions=(),
        groups=(),
        source_name=path.name,
        source_sha256=digest,
        statement_id=digest,
    )


def _minimal_statement_parser(
    path: Path,
    strict: bool = False,
    *,
    cache_dir: str | Path | None = None,
) -> StatementResult:
    del strict, cache_dir
    return _result_for(path)


def _three_pdf_directory(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (input_dir / name).write_bytes(name.encode())
    return input_dir


def test_convert_directory_delivers_relative_names_with_ordinals(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for relative in ("z.pdf", "nested/a.pdf"):
        source = input_dir / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(relative.encode())
    delivered: list[tuple[int, str | None]] = []

    summary = convert_directory_statements(
        input_dir,
        output_dir,
        jobs=1,
        cache_dir=cache_dir,
        statement_parser=_minimal_statement_parser,
        result_sink=lambda ordinal, result: delivered.append((ordinal, result.source_name)),
    )

    assert summary.source_count == 2
    assert delivered == [(0, "nested/a.pdf"), (1, "z.pdf")]


@pytest.mark.parametrize(
    ("counts", "expected"),
    (
        ({}, BatchDisposition(Status.UNSUPPORTED, ("no_pdf_files",), 0)),
        ({Status.RECONCILED: 2}, BatchDisposition(Status.RECONCILED, (), 2)),
        (
            {Status.RECONCILED: 1, Status.UNRECONCILED: 1},
            BatchDisposition(Status.UNRECONCILED, ("documents_not_reconciled:1",), 2),
        ),
        (
            {Status.NOT_STATEMENT: 2},
            BatchDisposition(Status.NOT_STATEMENT, ("documents_not_reconciled:2",), 2),
        ),
    ),
)
def test_summarize_batch_statuses_preserves_batch_policy(
    counts: Mapping[Status, int],
    expected: BatchDisposition,
) -> None:
    assert summarize_batch_statuses(counts) == expected
~~~

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_directory_conversion.py
~~~

Expected: collection fails because the new interfaces do not exist.

- [ ] **Step 3: Implement sequential conversion and shared disposition**

Move the current validation, normalization, topology, traversal, source-name, and error-translation rules behind convert_directory_statements(). Keep public exception classes in ccparser.parser so their identities and import paths do not change. Implement the empty/non-empty status policy from counts:

~~~python
def summarize_batch_statuses(
    status_counts: Mapping[Status, int],
) -> BatchDisposition:
    document_count = sum(status_counts.values())
    reconciled = status_counts.get(Status.RECONCILED, 0)
    unreconciled = status_counts.get(Status.UNRECONCILED, 0)
    not_statement = status_counts.get(Status.NOT_STATEMENT, 0)
    if document_count == 0:
        return BatchDisposition(Status.UNSUPPORTED, ("no_pdf_files",), 0)
    if reconciled == document_count:
        status = Status.RECONCILED
    elif unreconciled:
        status = Status.UNRECONCILED
    elif not_statement == document_count:
        status = Status.NOT_STATEMENT
    else:
        status = Status.UNSUPPORTED
    non_reconciled = document_count - reconciled
    diagnostics = (
        (f"documents_not_reconciled:{non_reconciled}",)
        if non_reconciled
        else ()
    )
    return BatchDisposition(status, diagnostics, document_count)
~~~

For jobs=1, deliver and explicitly delete each result before starting the next parse:

~~~python
for source_ordinal, source in enumerate(sources):
    result = parse_source(source)
    result_sink(source_ordinal, result)
    del result
~~~

- [ ] **Step 4: Run sequential tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_directory_conversion.py
~~~

Expected: all sequential/path/disposition tests pass.

- [ ] **Step 5: Write the bounded concurrency and liveness tests**

Use threading.Event and a lock, not sleeps. Block ordinal 0, let ordinal 1 complete, and prove ordinal 2 begins before ordinal 0 is released. Record weak references only in the sink and assert the prior jobs=1 result is unreachable when the next parser starts:

~~~python
def test_jobs_one_releases_each_result_before_parsing_the_next(
    tmp_path: Path,
) -> None:
    previous: weakref.ReferenceType[StatementResult] | None = None

    def parse(path: Path, strict: bool = False, *, cache_dir: Path | None = None) -> StatementResult:
        del strict, cache_dir
        if previous is not None:
            gc.collect()
            assert previous() is None
        return _result_for(path)

    def consume(ordinal: int, result: StatementResult, /) -> None:
        nonlocal previous
        del ordinal
        previous = weakref.ref(result)

    convert_directory_statements(
        _three_pdf_directory(tmp_path),
        tmp_path / "output",
        jobs=1,
        cache_dir=tmp_path / "cache",
        statement_parser=parse,
        result_sink=consume,
    )
~~~

Also cover executor construction/execution failures with redacted ParserRuntimeError and no chained private cause.

- [ ] **Step 6: Run the concurrency tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_directory_conversion.py -k "bounded or completion or releases or executor"
~~~

Expected: at least the fast-completion test fails because executor.map() waits in source order.

- [ ] **Step 7: Implement prompt bounded scheduling**

Use submit() plus wait(..., return_when=FIRST_COMPLETED), store only the pending futures, remove a future before delivering its result, and refill one slot after each delivery:

~~~python
pending: dict[Future[StatementResult], int] = {}
next_source = iter(enumerate(sources))

def submit_one(executor: ThreadPoolExecutor) -> bool:
    try:
        ordinal, source = next(next_source)
    except StopIteration:
        return False
    pending[executor.submit(parse_source, source)] = ordinal
    return True

with ThreadPoolExecutor(max_workers=worker_count) as executor:
    for _ in range(worker_count):
        submit_one(executor)
    while pending:
        completed, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
        for future in completed:
            ordinal = pending.pop(future)
            result = future.result()
            result_sink(ordinal, result)
            del result
            submit_one(executor)
~~~

Do not use executor.map(), do not submit the whole corpus, and retain the existing privacy-safe exception translation.

- [ ] **Step 8: Convert parse_directory() into the collecting adapter**

Collect by ordinal, never completion order, then use summarize_batch_statuses() and the unchanged write_batch_outputs() boundary:

~~~python
results_by_ordinal: dict[int, StatementResult] = {}

def collect(ordinal: int, result: StatementResult, /) -> None:
    results_by_ordinal[ordinal] = result

summary = convert_directory_statements(
    path,
    output_dir,
    strict,
    jobs,
    cache_dir=cache_dir,
    statement_parser=statement_parser,
    result_sink=collect,
    directory_root_policy=directory_root_policy,
)
statements = tuple(results_by_ordinal[index] for index in range(summary.source_count))
disposition = summarize_batch_statuses(Counter(item.status for item in statements))
batch = BatchResult(
    status=disposition.status,
    statements=statements,
    diagnostics=disposition.diagnostics,
)
write_batch_outputs(summary.resolved_output_dir, batch)
~~~

Update existing monkeypatch targets only where internals moved. Keep the public signature and __all__ unchanged.

- [ ] **Step 9: Run focused and full parser tests**

Run:

~~~bash
.venv/bin/pytest -q tests/test_directory_conversion.py tests/test_parser.py
~~~

Expected: all pass, including trusted descriptor roots, byte-identical sequential/concurrent output, path topology, and privacy-safe failures.

- [ ] **Step 10: Commit Task 1**

~~~bash
git add src/ccparser/parser.py tests/test_directory_conversion.py tests/test_parser.py
git commit -m "refactor: stream directory statement delivery"
~~~

### Task 2: Add byte-identical streaming JSON and CSV encoders

**Files:**
- Modify: src/ccparser/output.py:5-32, 81-289
- Modify: tests/test_output.py:1-303

**Interfaces:**
- Consumes: Status, StatementResult, existing canonical normalization, CSV_COLUMNS, and row projection policy.
- Produces:

~~~python
class BinaryWriter(Protocol):
    def write(self, content: bytes, /) -> int: ...


def write_canonical_batch_json_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None: ...


def write_transactions_csv_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None: ...
~~~

- Each iterable is single-use. Callers that need both formats supply a fresh iterator for each pass.

- [ ] **Step 1: Write differential stream tests**

For the existing rich _batch() fixture, an empty batch, a no-transaction statement, mixed statuses, decomposed Unicode, embedded commas/quotes/newlines, FX, evidence, and ambiguities, compare streamed bytes to the current complete-batch oracle:

~~~python
@pytest.mark.parametrize(
    "batch",
    (
        _batch(),
        BatchResult(status=Status.UNSUPPORTED, statements=(), diagnostics=("no_pdf_files",)),
        BatchResult(
            status=Status.UNSUPPORTED,
            statements=(
                StatementResult(
                    status=Status.UNSUPPORTED,
                    transactions=(),
                    groups=(),
                    diagnostics=("unsupported_layout",),
                ),
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
        BatchResult(
            status=Status.UNRECONCILED,
            statements=(
                StatementResult(status=Status.RECONCILED, transactions=(), groups=()),
                StatementResult(status=Status.UNRECONCILED, transactions=(), groups=()),
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
    ),
)
def test_streaming_json_and_csv_match_complete_batch_bytes(batch: BatchResult) -> None:
    json_stream = io.BytesIO()
    csv_stream = io.BytesIO()

    write_canonical_batch_json_stream(
        json_stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )
    write_transactions_csv_stream(
        csv_stream,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=iter(batch.statements),
    )

    assert json_stream.getvalue() == canonical_json_bytes(batch)
    assert csv_stream.getvalue() == transactions_csv_bytes(batch)
~~~

- [ ] **Step 2: Run the differential tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_output.py -k streaming
~~~

Expected: collection fails because both stream functions are missing.

- [ ] **Step 3: Implement the canonical JSON stream**

Split the existing canonical encoder into a no-newline value encoder plus the public newline wrapper. Emit the exact sorted top-level BatchResult key order:

~~~python
def _canonical_json_value_content(value: object) -> bytes:
    return json.dumps(
        _normalized_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json_value_bytes(value: object) -> bytes:
    return _canonical_json_value_content(value) + b"\n"


def write_canonical_batch_json_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None:
    destination.write(b'{"diagnostics":')
    destination.write(_canonical_json_value_content(diagnostics))
    destination.write(b',"statements":[')
    separator = b""
    for statement in statements:
        destination.write(separator)
        destination.write(
            _canonical_json_value_content(statement.model_dump(mode="json"))
        )
        separator = b","
    destination.write(b'],"status":')
    destination.write(_canonical_json_value_content(status.value))
    destination.write(b"}\n")
~~~

- [ ] **Step 4: Implement the shared CSV row iterator and byte stream**

Change _transaction_row() to accept batch_diagnostics rather than BatchResult. Replace the corpus-sized tuple returned by _csv_rows() with an iterator that tracks whether any statement was seen. Write the BOM once and encode each csv.DictWriter write directly:

~~~python
class _Utf8TextWriter:
    def __init__(self, destination: BinaryWriter) -> None:
        self._destination = destination

    def write(self, content: str, /) -> int:
        self._destination.write(content.encode("utf-8"))
        return len(content)


def write_transactions_csv_stream(
    destination: BinaryWriter,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: Iterable[StatementResult],
) -> None:
    destination.write(codecs.BOM_UTF8)
    writer = csv.DictWriter(
        _Utf8TextWriter(destination),
        fieldnames=CSV_COLUMNS,
        lineterminator="\r\n",
    )
    writer.writeheader()
    wrote_statement = False
    for statement in statements:
        wrote_statement = True
        groups = {group.group_id: group for group in statement.groups}
        if statement.transactions:
            for transaction in statement.transactions:
                writer.writerow(
                    _transaction_row(diagnostics, statement, transaction, groups)
                )
        else:
            writer.writerow(
                _empty_row(
                    status=statement.status.value,
                    diagnostics=_codes(diagnostics, statement.diagnostics),
                    statement=statement,
                )
            )
    if not wrote_statement:
        writer.writerow(
            _empty_row(status=status.value, diagnostics=_codes(diagnostics))
        )
~~~

Make transactions_csv_bytes() call the stream function through io.BytesIO so the streaming and in-memory policies cannot diverge.

- [ ] **Step 5: Run output tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_output.py
~~~

Expected: all canonical, non-finite, quoting, empty-row, and differential tests pass byte for byte.

- [ ] **Step 6: Commit Task 2**

~~~bash
git add src/ccparser/output.py tests/test_output.py
git commit -m "refactor: stream canonical batch encoders"
~~~

### Task 3: Publish streamed output pairs without corpus-sized buffers

**Files:**
- Modify: src/ccparser/output.py:279-356
- Modify: tests/test_output.py:304-end

**Interfaces:**
- Consumes: Task 2 stream encoders and a repeatable statement iterator factory.
- Produces:

~~~python
type BinaryRenderer = Callable[[BinaryIO], None]
type StatementResultFactory = Callable[[], Iterator[StatementResult]]


def write_output_pair_atomic(
    output_dir: str | Path,
    *,
    render_json: BinaryRenderer,
    render_csv: BinaryRenderer,
) -> None: ...


def write_streaming_batch_outputs(
    output_dir: str | Path,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: StatementResultFactory,
) -> None: ...
~~~

- Both complete temporary files must exist and be fsynced before either destination changes.
- Existing destinations must be restored exactly after any first/second publish or directory-fsync failure.
- This is handled-error rollback, matching the existing contract. Do not describe two
  destination renames as literal power-loss atomicity.

- [ ] **Step 1: Write exact publication and rollback tests**

Add tests that require two fresh iterator calls, exact equality with write_batch_outputs(), no corpus-sized read_bytes() inside the new writer, pre-render before mutation, and removal of every temporary/backup file. Parameterize prior destination state as neither file, JSON only, CSV only, and both files. Cover second replace failure, publish-directory fsync failure, rollback failure, and post-commit cleanup failure:

~~~python
def test_streaming_pair_writer_matches_batch_outputs(tmp_path: Path) -> None:
    batch = _batch()
    expected_dir = tmp_path / "expected"
    streamed_dir = tmp_path / "streamed"
    calls = 0

    def statements() -> Iterator[StatementResult]:
        nonlocal calls
        calls += 1
        yield from batch.statements

    write_batch_outputs(expected_dir, batch)
    write_streaming_batch_outputs(
        streamed_dir,
        status=batch.status,
        diagnostics=batch.diagnostics,
        statements=statements,
    )

    assert calls == 2
    assert (streamed_dir / "results.json").read_bytes() == (
        expected_dir / "results.json"
    ).read_bytes()
    assert (streamed_dir / "transactions.csv").read_bytes() == (
        expected_dir / "transactions.csv"
    ).read_bytes()


@pytest.mark.parametrize("prior_state", ("none", "json", "csv", "both"))
def test_atomic_pair_second_replace_failure_restores_prior_state_without_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_state: str,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    json_path = output_dir / "results.json"
    csv_path = output_dir / "transactions.csv"
    if prior_state in {"json", "both"}:
        json_path.write_bytes(b"old json\n")
    if prior_state in {"csv", "both"}:
        csv_path.write_bytes(b"old csv\r\n")
    before = (
        json_path.read_bytes() if json_path.exists() else None,
        csv_path.read_bytes() if csv_path.exists() else None,
    )
    original_replace = os.replace
    failed = False

    def fail_csv_replace(source: Path, destination: Path) -> None:
        nonlocal failed
        if Path(destination).name == "transactions.csv" and not failed:
            failed = True
            raise OSError("private replacement detail")
        original_replace(source, destination)

    monkeypatch.setattr(output_module.os, "replace", fail_csv_replace)
    with pytest.raises(OSError, match="replacement"):
        write_streaming_batch_outputs(
            output_dir,
            status=_batch().status,
            diagnostics=_batch().diagnostics,
            statements=lambda: iter(_batch().statements),
        )

    assert (
        json_path.read_bytes() if json_path.exists() else None,
        csv_path.read_bytes() if csv_path.exists() else None,
    ) == before
    assert not tuple(output_dir.glob(".*.tmp"))
    assert not tuple(output_dir.glob(".*.backup"))
~~~

- [ ] **Step 2: Run publication tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_output.py -k "streaming_pair"
~~~

Expected: collection fails because write_streaming_batch_outputs() is missing.

- [ ] **Step 3: Implement file-backed pre-render and rollback**

Create both temporary files in the destination directory with restrictive permissions. Render JSON and CSV directly into them, flush and fsync each, then publish. If old destinations exist, create exclusive same-directory hard-link backups rather than reading or moving them. Hard links pin the exact old inode while leaving each destination in place until its replacement. Track each state transition explicitly:

~~~python
@dataclass(slots=True)
class _PairPublication:
    json_had_previous: bool = False
    csv_had_previous: bool = False
    json_published: bool = False
    csv_published: bool = False


def write_streaming_batch_outputs(
    output_dir: str | Path,
    *,
    status: Status,
    diagnostics: tuple[str, ...],
    statements: StatementResultFactory,
) -> None:
    write_output_pair_atomic(
        output_dir,
        render_json=lambda stream: write_canonical_batch_json_stream(
            stream,
            status=status,
            diagnostics=diagnostics,
            statements=statements(),
        ),
        render_csv=lambda stream: write_transactions_csv_stream(
            stream,
            status=status,
            diagnostics=diagnostics,
            statements=statements(),
        ),
    )
~~~

write_output_pair_atomic() must:

1. classify each destination as absent or a no-follow regular file;
2. hard-link every existing destination to an exclusive backup and fsync the directory before destination mutation;
3. replace JSON, replace CSV, and fsync the directory; that fsync is the commit point;
4. before the commit point, restore backups or unlink destinations that were originally absent, attempt both restorations even if one fails, fsync, clean stages/backups, and preserve the primary exception;
5. after the commit point, remove backups/stages and fsync; a cleanup failure raises while leaving a consistent new/new pair and must not roll back after backups begin disappearing.

Make the compatibility write_batch_outputs(output_dir, batch) adapter delegate to
write_streaming_batch_outputs() with lambda: iter(batch.statements). Its public
interface and exact bytes remain unchanged, but it no longer materializes both new
corpus outputs or both previous outputs as byte strings.

- [ ] **Step 4: Run output tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_output.py
~~~

Expected: all existing and streamed atomic writer tests pass.

- [ ] **Step 5: Commit Task 3**

~~~bash
git add src/ccparser/output.py tests/test_output.py
git commit -m "feat: publish streamed batch outputs"
~~~

### Task 4: Add the secure ordinal statement spool

**Files:**
- Create: src/ccparser/corpus_spool.py
- Create: tests/test_corpus_spool.py

**Interfaces:**
- Consumes: canonical_json_bytes(StatementResult), StatementResult.model_validate_json(), SHA-256, and a trusted run output directory.
- Produces:

~~~python
class StatementSpoolError(RuntimeError):
    """Privacy-safe statement spool failure."""


@dataclass(frozen=True, slots=True)
class SealedStatementRecord:
    ordinal: int
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    digest: str


class StatementSpool:
    @classmethod
    def create(cls, parent: Path) -> StatementSpool: ...
    @property
    def path(self) -> Path: ...
    def append(self, ordinal: int, result: StatementResult, /) -> None: ...
    def seal(self, expected_count: int, /) -> None: ...
    def iter_statements(self) -> Iterator[StatementResult]: ...
    def close(self) -> None: ...
    def __enter__(self) -> StatementSpool: ...
    def __exit__(self, *exc_info: object) -> None: ...
~~~

- Record names are zero-padded ordinals only.
- append() supports out-of-order completion but rejects duplicates.
- seal(N) requires exactly the ordinal set range(N), makes later append illegal, and retains only record identities.
- Each read verifies regular-file type, owner, mode, link count, stable stat identity, size, SHA-256, schema validity, and canonical bytes before yielding one model.

- [ ] **Step 1: Write round-trip, order, mode, and lifetime tests**

~~~python
def _statement(source_name: str) -> StatementResult:
    return StatementResult(
        status=Status.RECONCILED,
        transactions=(),
        groups=(),
        source_name=source_name,
        source_sha256="a" * 64,
        statement_id="a" * 64,
    )


def test_spool_round_trips_out_of_order_records_in_ordinal_order(tmp_path: Path) -> None:
    first = _statement("nested/a.pdf")
    second = _statement("z.pdf")
    with StatementSpool.create(tmp_path) as spool:
        spool.append(1, second)
        spool.append(0, first)
        spool.seal(2)

        assert tuple(spool.iter_statements()) == (first, second)
        names = tuple(sorted(path.name for path in spool.path.iterdir()))
        assert names == ("00000000.json", "00000001.json")
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in spool.path.iterdir())

    assert not spool.path.exists()
~~~

Also test duplicate ordinals, missing ranges, append-after-seal, read-before-seal, and close idempotence.

- [ ] **Step 2: Run spool tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_spool.py
~~~

Expected: collection fails because ccparser.corpus_spool does not exist.

- [ ] **Step 3: Implement secure creation, append, seal, and read**

Open the parent and spool directories with O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC. Create the hidden spool directory mode 0700. Write each canonical record through O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode 0600; fsync, capture identity and digest, fchmod to 0400, verify the final stat, and close.

Use one generic privacy-safe boundary:

~~~python
def _spool_error() -> StatementSpoolError:
    return StatementSpoolError("statement spool operation failed")
~~~

Every external OSError, validation error, JSON error, or digest mismatch must be translated with from None. Never include the record content or caller path in the message.

During iter_statements(), read only one record into memory:

~~~python
for ordinal in range(self._expected_count):
    record = self._records[ordinal]
    content = self._read_stable_record(record)
    result = StatementResult.model_validate_json(content)
    if canonical_json_bytes(result) != content:
        raise _spool_error()
    yield result
    del result, content
~~~

- [ ] **Step 4: Write corruption and cleanup failure tests**

Mutate, replace, truncate, chmod, hard-link, delete, and symlink a sealed record. Every case must fail with exactly the generic error and no private contents. Inject append/read/close failures and require best-effort cleanup without recursive broad deletion.

~~~python
@pytest.mark.parametrize(
    "mutation",
    ("truncate", "replace", "chmod", "hardlink", "delete", "symlink"),
)
def test_spool_rejects_changed_sealed_records_privately(
    tmp_path: Path,
    mutation: str,
) -> None:
    spool = StatementSpool.create(tmp_path)
    spool.append(0, _statement("private/source.pdf"))
    spool.seal(1)
    record = next(spool.path.iterdir())
    if mutation == "truncate":
        record.chmod(0o600)
        record.write_bytes(b"private financial content")
    elif mutation == "replace":
        record.unlink()
        record.write_bytes(b"{}")
    elif mutation == "chmod":
        record.chmod(0o600)
    elif mutation == "hardlink":
        os.link(record, spool.path / "extra-link")
    elif mutation == "delete":
        record.unlink()
    else:
        record.unlink()
        record.symlink_to(tmp_path / "outside")

    with pytest.raises(StatementSpoolError) as caught:
        tuple(spool.iter_statements())

    assert str(caught.value) == "statement spool operation failed"
    assert "private" not in "".join(traceback.format_exception(caught.value))
    with suppress(StatementSpoolError):
        spool.close()
~~~

- [ ] **Step 5: Run spool tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_spool.py
~~~

Expected: all secure lifecycle and privacy tests pass.

- [ ] **Step 6: Commit Task 4**

~~~bash
git add src/ccparser/corpus_spool.py tests/test_corpus_spool.py
git commit -m "feat: spool corpus statements securely"
~~~

### Task 5: Project a streamed run without corpus-sized tuples

**Files:**
- Modify: src/ccparser/corpus_gate.py:80-115, 2830-3010
- Modify: tests/test_corpus_gate.py:5050-5260

**Interfaces:**
- Consumes: an iterator factory over source-ordered StatementResult values and already verified JSON/CSV digests.
- Produces:

~~~python
type StatementResultFactory = Callable[[], Iterator[StatementResult]]


def project_streamed_run(
    *,
    batch_status: Status,
    elapsed_seconds: Decimal,
    json_digest: str,
    csv_digest: str,
    statements: StatementResultFactory,
) -> RunManifest: ...
~~~

- The output must equal project_run() for every equivalent BatchResult.
- It may retain only scalar counters, the closed field-path Counter, hash objects, and the current statement projection.

- [ ] **Step 1: Write differential manifest tests**

Parametrize rich, empty, mixed-status, no-transaction, FX/evidence, and ambiguity batches. Reuse the existing _batch(), _transaction(), and _status_batch() fixtures already defined in tests/test_corpus_gate.py; construct the additional batches inline:

~~~python
@pytest.mark.parametrize(
    "batch",
    (
        _batch(),
        BatchResult(status=Status.UNSUPPORTED, statements=(), diagnostics=("no_pdf_files",)),
        BatchResult(
            status=Status.UNRECONCILED,
            statements=(
                _status_batch(Status.RECONCILED).statements[0],
                _status_batch(Status.UNRECONCILED).statements[0],
            ),
            diagnostics=("documents_not_reconciled:1",),
        ),
        _batch(transaction=_transaction(with_fx=True, ambiguities=("candidate",))),
    ),
)
def test_project_streamed_run_matches_complete_batch(batch: BatchResult) -> None:
    expected = project_run(batch, elapsed_seconds=Decimal("1.25"))

    actual = project_streamed_run(
        batch_status=batch.status,
        elapsed_seconds=Decimal("1.25"),
        json_digest=expected.json_digest,
        csv_digest=expected.csv_digest,
        statements=lambda: iter(batch.statements),
    )

    assert actual == expected
~~~

Add a single-use iterator test proving project_streamed_run() traverses statements once.

- [ ] **Step 2: Run differential tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_gate.py -k project_streamed
~~~

Expected: collection fails because project_streamed_run() is missing.

- [ ] **Step 3: Factor one-statement projection policy**

Extract a frozen _StatementStructuralProjection containing the six per-statement values plus count increments. Both _project_structural_dimensions() and project_streamed_run() must call the same helper so field/evidence policy is not duplicated:

~~~python
@dataclass(frozen=True, slots=True)
class _StatementStructuralProjection:
    status: str
    groups: tuple[_GroupProjection, ...]
    transaction_identities: tuple[_TransactionIdentity, ...]
    field_presence: tuple[tuple[PresentFieldPath, ...], ...]
    evidence_provenance: tuple[tuple[_EvidenceSiteProjection, ...], ...]
    ambiguities: tuple[tuple[str, ...], ...]
    row_results: int
    evidence_references: int
~~~

- [ ] **Step 4: Implement incremental canonical array hashing**

The hasher must feed exactly the same bytes as _canonical_json_value_bytes(tuple(values)). Each appended value is encoded without its final newline:

~~~python
class _CanonicalArrayDigest:
    def __init__(self, prefix: bytes = b"[", suffix: bytes = b"]\n") -> None:
        self._digest = sha256()
        self._digest.update(prefix)
        self._suffix = suffix
        self._has_value = False

    def append(self, value: object) -> None:
        if self._has_value:
            self._digest.update(b",")
        self._digest.update(_canonical_json_value_bytes(value)[:-1])
        self._has_value = True

    def hexdigest(self) -> str:
        completed = self._digest.copy()
        completed.update(self._suffix)
        return completed.hexdigest()
~~~

Use a specialized ordered-status prefix containing the canonical batch status and an inner array. Feed each other structural projection as one outer-array element. Aggregate counts with Counter and integers, then construct the unchanged RunManifest.

- [ ] **Step 5: Run projection tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_gate.py -k "project_run or project_streamed or structural_projection"
~~~

Expected: all complete-batch and streaming manifest tests pass exactly.

- [ ] **Step 6: Commit Task 5**

~~~bash
git add src/ccparser/corpus_gate.py tests/test_corpus_gate.py
git commit -m "refactor: project corpus manifests incrementally"
~~~

### Task 6: Integrate the compact streaming corpus runner

**Files:**
- Modify: src/ccparser/corpus_gate.py:80-90, 298-590, 3880-4040
- Modify: tests/test_corpus_gate.py:500-590, 2070-2190, 2550-2810

**Interfaces:**
- Consumes: convert_directory_statements(), summarize_batch_statuses(), StatementSpool, Task 2 encoders, Task 3 publication, and project_streamed_run().
- Changes CompletedCorpusRun to:

~~~python
@dataclass(frozen=True, slots=True)
class CompletedCorpusRun:
    batch_status: Status
    manifest: RunManifest
    membership_before: CorpusMembership
    membership_after: CorpusMembership
~~~

- LocalCorpusRunner accepts a StatementParser injection rather than a full directory parser:

~~~python
def __init__(
    self,
    *,
    statement_parser: StatementParser | None = None,
    monotonic_ns: _NanosecondClock | None = None,
) -> None: ...
~~~

- [ ] **Step 1: Change synthetic runner fixtures to the compact contract**

Update _RecordingRunner and custom runners in tests/test_corpus_gate.py first. Replace batch_overrides with batch_status_overrides and manifest_overrides. Use manifest counts rather than len(batch.statements). Add a test that CompletedCorpusRun has no batch field:

~~~python
def test_completed_corpus_run_cannot_retain_a_batch() -> None:
    fields = {field.name for field in dataclasses.fields(CompletedCorpusRun)}
    assert fields == {
        "batch_status",
        "manifest",
        "membership_before",
        "membership_after",
    }
~~~

- [ ] **Step 2: Run compact-contract tests and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_gate.py -k "completed_corpus_run or completed_runs_enforce or approved_document_count"
~~~

Expected: failures because CompletedCorpusRun still requires batch.

- [ ] **Step 3: Remove BatchResult retention from gate validation**

Change _validate_completed_execution() to enforce status policy from batch_status and manifest counts:

~~~python
if any(
    run.completed.batch_status is not Status.RECONCILED
    or run.completed.manifest.counts.reconciled
    != run.completed.manifest.counts.documents
    for run in retained_runs
):
    reasons.append(CorpusGateReason.RETAINED_NOT_RECONCILED)

if any(
    run.completed.batch_status is not Status.NOT_STATEMENT
    or run.completed.manifest.counts.not_statement
    != run.completed.manifest.counts.documents
    for run in quarantine_runs
):
    reasons.append(CorpusGateReason.QUARANTINE_MISCLASSIFIED)
~~~

The count policy compares only manifest counts.documents with approved membership. Do not retain or reconstruct a BatchResult.

- [ ] **Step 4: Write the streaming LocalCorpusRunner integration test**

Use three synthetic PDFs, a statement parser that completes out of order, a fresh output/cache pair, and a deterministic clock. Require exact oracle output bytes, exact project_run() manifest, adjacent membership snapshots, batch status, elapsed time, ordinal spool cleanup, and weak-reference release:

~~~python
def test_local_runner_streams_exact_outputs_without_retaining_batch(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    input_dir.mkdir()
    output_dir.mkdir()
    cache_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"a")
    (input_dir / "b.pdf").write_bytes(b"b")
    statements = (
        StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name="a.pdf",
            source_sha256=sha256(b"a").hexdigest(),
            statement_id=sha256(b"a").hexdigest(),
        ),
        StatementResult(
            status=Status.RECONCILED,
            transactions=(),
            groups=(),
            source_name="b.pdf",
            source_sha256=sha256(b"b").hexdigest(),
            statement_id=sha256(b"b").hexdigest(),
        ),
    )
    expected_batch = BatchResult(status=Status.RECONCILED, statements=statements)
    by_name = {statement.source_name: statement for statement in statements}

    def parse(
        path: Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        return by_name[path.name]

    clock = iter((1_000_000_000, 2_250_000_000))
    runner = LocalCorpusRunner(
        statement_parser=parse,
        monotonic_ns=lambda: next(clock),
    )

    completed = runner(
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        strict=True,
        jobs=1,
    )

    expected = project_run(expected_batch, elapsed_seconds=Decimal("1.25"))
    assert completed.batch_status is expected_batch.status
    assert completed.manifest == expected
    assert (output_dir / "results.json").read_bytes() == canonical_json_bytes(expected_batch)
    assert (output_dir / "transactions.csv").read_bytes() == transactions_csv_bytes(expected_batch)
    assert not tuple(output_dir.glob(".statement-spool*"))
~~~

- [ ] **Step 5: Run LocalCorpusRunner test and confirm RED**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_gate.py -k local_runner
~~~

Expected: failures because LocalCorpusRunner still calls parse_directory() and returns a retained batch.

- [ ] **Step 6: Implement the streaming runner**

Keep the current membership and timer boundaries. The timed region includes conversion and durable output publication; membership and manifest projection remain outside:

~~~python
membership_before = _snapshot_membership(input_dir, allow_descriptor_root=True)
start_nanoseconds = self._monotonic_ns()
with StatementSpool.create(output_dir) as spool:
    status_counts: Counter[Status] = Counter()

    def consume(ordinal: int, result: StatementResult, /) -> None:
        spool.append(ordinal, result)
        status_counts[result.status] += 1

    conversion = convert_directory_statements(
        input_dir,
        output_dir,
        strict,
        jobs,
        cache_dir=cache_dir,
        statement_parser=self._statement_parser,
        result_sink=consume,
        directory_root_policy=directory_root_policy,
    )
    spool.seal(conversion.source_count)
    disposition = summarize_batch_statuses(status_counts)
    if disposition.document_count != conversion.source_count:
        raise RuntimeError("statement sink count mismatch")
    write_streaming_batch_outputs(
        conversion.resolved_output_dir,
        status=disposition.status,
        diagnostics=disposition.diagnostics,
        statements=spool.iter_statements,
    )
    end_nanoseconds = self._monotonic_ns()
    membership_after = _snapshot_membership(input_dir, allow_descriptor_root=True)
    elapsed_seconds = Decimal(end_nanoseconds - start_nanoseconds) / Decimal(1_000_000_000)
    expected_json_digest, expected_csv_digest = _canonical_stream_digests(
        disposition,
        spool.iter_statements,
    )
    _require_file_digest(
        conversion.resolved_output_dir / "results.json",
        expected_json_digest,
    )
    _require_file_digest(
        conversion.resolved_output_dir / "transactions.csv",
        expected_csv_digest,
    )
    manifest = project_streamed_run(
        batch_status=disposition.status,
        elapsed_seconds=elapsed_seconds,
        json_digest=expected_json_digest,
        csv_digest=expected_csv_digest,
        statements=spool.iter_statements,
    )
~~~

_canonical_stream_digests() writes each Task 2 encoder into a SHA-256 BinaryWriter.
_require_file_digest() opens with O_RDONLY | O_NOFOLLOW | O_CLOEXEC, requires a
regular single-link file owned by the effective user, hashes fixed-size chunks,
checks the same stable device/inode/size/mtime identity before and after, and never
calls read_bytes().

Translate every parser, spool, serializer, output, digest, negative-clock, or cleanup failure to CorpusGateRuntimeError((PARSER_RUNTIME_FAILED,)) from None.

- [ ] **Step 7: Add emitted-output tamper, cleanup, and privacy tests**

Cover missing/mutated JSON and CSV after publication, corrupt spool record, parser failure at document N, output writer failure, spool close failure, negative clock, and trusted descriptor roots. Require generic reason codes, no partial accepted result, no private details, and best-effort spool cleanup.

~~~python
def _reconciled_statement_parser(
    path: str | Path,
    strict: bool = False,
    *,
    cache_dir: str | Path | None = None,
) -> StatementResult:
    del strict, cache_dir
    source = Path(path)
    digest = sha256(source.read_bytes()).hexdigest()
    return StatementResult(
        status=Status.RECONCILED,
        transactions=(),
        groups=(),
        source_name=source.name,
        source_sha256=digest,
        statement_id=digest,
    )


@pytest.mark.parametrize("filename", ("results.json", "transactions.csv"))
def test_local_runner_rejects_tampered_streamed_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for directory in (input_dir, output_dir, cache_dir):
        directory.mkdir()
    (input_dir / "statement.pdf").write_bytes(b"statement")
    original_write = corpus_gate_module.write_streaming_batch_outputs

    def write_then_tamper(
        path: str | Path,
        *,
        status: Status,
        diagnostics: tuple[str, ...],
        statements: Callable[[], Iterator[StatementResult]],
    ) -> None:
        original_write(
            path,
            status=status,
            diagnostics=diagnostics,
            statements=statements,
        )
        (Path(path) / filename).write_bytes(b"private tampered output")

    monkeypatch.setattr(
        corpus_gate_module,
        "write_streaming_batch_outputs",
        write_then_tamper,
    )
    runner = LocalCorpusRunner(statement_parser=_reconciled_statement_parser)

    with pytest.raises(CorpusGateRuntimeError) as caught:
        runner(
            input_dir=input_dir,
            output_dir=output_dir,
            cache_dir=cache_dir,
            strict=True,
            jobs=1,
        )

    assert caught.value.reasons == (CorpusGateReason.PARSER_RUNTIME_FAILED,)
    assert "private tampered" not in "".join(traceback.format_exception(caught.value))
    assert not tuple(output_dir.glob(".statement-spool*"))
~~~

- [ ] **Step 8: Run corpus gate tests and confirm GREEN**

Run:

~~~bash
.venv/bin/pytest -q tests/test_corpus_gate.py tests/test_corpus_spool.py tests/test_output.py tests/test_directory_conversion.py tests/test_parser.py
~~~

Expected: all pass. The gate still performs exactly four runs with the configured jobs, distinct empty outputs/caches, unchanged baseline comparison, and unchanged reason ordering.

- [ ] **Step 9: Commit Task 6**

~~~bash
git add src/ccparser/corpus_gate.py tests/test_corpus_gate.py
git commit -m "perf: bound corpus verification memory"
~~~

### Task 7: Run tracked verification and review the complete change

**Files:**
- Modify only files required by findings from the verification/review loop.

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: one clean reviewed candidate commit with all tracked gates passing.

- [ ] **Step 1: Run format and focused static checks**

~~~bash
.venv/bin/ruff format .
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
~~~

Expected: all commands exit 0.

- [ ] **Step 2: Run the complete test suite**

~~~bash
.venv/bin/pytest -q
~~~

Expected: all tests pass with no warnings or collection errors.

- [ ] **Step 3: Inspect retention and privacy mechanically**

~~~bash
rg -n "CompletedCorpusRun|BatchResult|read_bytes\\(|source_name|source_sha256" \
  src/ccparser/corpus_gate.py src/ccparser/corpus_spool.py
git diff --check
git status --short
~~~

Expected:

- CompletedCorpusRun has no BatchResult field.
- Corpus gate output verification does not read whole result files.
- Source names/hashes occur only inside canonical private statement content or existing projection policy, never spool filenames or public errors.
- git diff --check is clean.

- [ ] **Step 4: Request task and whole-branch reviews**

Use superpowers:requesting-code-review against the branch base. Resolve every Critical or Important finding test-first, rerun the covering tests, and repeat review until clean.

- [ ] **Step 5: Commit review fixes if needed**

~~~bash
git add src tests
git commit -m "fix: harden streaming corpus verification"
~~~

If no files changed, do not create an empty commit.

- [ ] **Step 6: Re-run all required tracked gates after the final code change**

~~~bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest -q
git status --short
~~~

Expected: all verification exits 0 and the worktree is clean.

### Task 8: Measure memory and complete private corpus acceptance

**Files:**
- Create only ignored private work directories, timing output, candidate baseline, and independent pin configuration.
- Do not modify tracked files.

**Interfaces:**
- Consumes: the clean full reviewed SHA from Task 7, protected corpus membership inventory and independent SHA-256, private retained/quarantine directories, and the candidate's own source tree.
- Produces: privacy-safe aggregate memory evidence, a separately reviewed and pinned new baseline, and a successful formal verify attestation.

- [ ] **Step 1: Prepare candidate-local ignored private inputs**

Load the existing protected controller without printing it. If implementation runs
in a linked worktree, mirror retained and quarantine files beneath that worktree with
hard links (never symlinks), and copy the approved membership inventory without
overwrite. Point all three path variables at locations beneath the candidate root:

~~~bash
set -a
. /root/creditcard/.superpowers/private/gate-controller.env
set +a
candidate_root="$(git rev-parse --show-toplevel)"
source_retained="$RETAINED_CORPUS_DIR"
source_quarantine="$QUARANTINE_CORPUS_DIR"
source_inventory="$APPROVED_MEMBERSHIP_INVENTORY_PATH"
mkdir -p "$candidate_root/documents" "$candidate_root/unrelated" \
  "$candidate_root/.superpowers/private"
test -z "$(find "$candidate_root/documents" -mindepth 1 -print -quit)"
test -z "$(find "$candidate_root/unrelated" -mindepth 1 -print -quit)"
cp -al -- "$source_retained/." "$candidate_root/documents/"
cp -al -- "$source_quarantine/." "$candidate_root/unrelated/"
test ! -e "$candidate_root/.superpowers/private/corpus-membership.json"
cp -- "$source_inventory" \
  "$candidate_root/.superpowers/private/corpus-membership.json"
RETAINED_CORPUS_DIR="$candidate_root/documents"
QUARANTINE_CORPUS_DIR="$candidate_root/unrelated"
APPROVED_MEMBERSHIP_INVENTORY_PATH="$candidate_root/.superpowers/private/corpus-membership.json"
test "$(sha256sum -- "$APPROVED_MEMBERSHIP_INVENTORY_PATH" | cut -d ' ' -f 1)" = \
  "$APPROVED_MEMBERSHIP_INVENTORY_SHA256"
git check-ignore --quiet "$RETAINED_CORPUS_DIR"
git check-ignore --quiet "$QUARANTINE_CORPUS_DIR"
git check-ignore --quiet "$APPROVED_MEMBERSHIP_INVENTORY_PATH"
~~~

Expected: all assertions exit 0. If those candidate-local paths already contain
approved private inputs, validate their membership and use them rather than copying
over them.

- [ ] **Step 2: Bind the exact clean candidate**

~~~bash
EXPECTED_REVIEWED_SHA="$(git rev-parse --verify HEAD)"
test -n "$EXPECTED_REVIEWED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test -n "$APPROVED_MEMBERSHIP_INVENTORY_SHA256"
~~~

Expected: every assertion exits 0. Never abbreviate EXPECTED_REVIEWED_SHA.

- [ ] **Step 3: Create new ignored record artifacts without overwrite**

~~~bash
record_work="$(mktemp -d -p .superpowers/private corpus-record.XXXXXX)"
candidate_dir="$(mktemp -d -p .superpowers/private corpus-candidate.XXXXXX)"
baseline_candidate="$candidate_dir/baseline.json"
memory_report="$candidate_dir/max-rss.txt"
test ! -e "$baseline_candidate"
git check-ignore --quiet "$record_work"
git check-ignore --quiet "$candidate_dir"
~~~

Expected: all paths are ignored and the baseline candidate does not exist.

- [ ] **Step 4: Record the new candidate at jobs=1 under a memory measurement**

Invoke the candidate's own ccparse source and the protected retained/quarantine paths. Capture all ordinary parser output privately. Use /usr/bin/time -v and retain its stderr only in memory_report:

~~~bash
/usr/bin/time -v -o "$memory_report" \
  env PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus "$RETAINED_CORPUS_DIR" \
    --quarantine-dir "$QUARANTINE_CORPUS_DIR" \
    --membership-inventory "$APPROVED_MEMBERSHIP_INVENTORY_PATH" \
    --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
    --baseline "$baseline_candidate" \
    --work-dir "$record_work" \
    --mode record \
    --jobs 1 \
    --expected-commit-sha "$EXPECTED_REVIEWED_SHA" \
    --runtime-tolerance 0.20 \
    >"$candidate_dir/record-output.txt"
~~~

Expected: exit 0 with the private aggregate attestation showing retained=104, reconciled=104, and quarantined=5. Do not copy per-document output into public logs.

- [ ] **Step 5: Enforce the diagnostic memory target**

Read only the Maximum resident set size line from memory_report, convert KiB to bytes with integer arithmetic, and require it below 1 GiB:

~~~bash
max_rss_kib="$(awk -F: '/Maximum resident set size/ {gsub(/^[[:space:]]+/, "", $2); print $2}' "$memory_report")"
test -n "$max_rss_kib"
test "$max_rss_kib" -lt 1048576
~~~

Expected: both assertions exit 0. Public reporting may state only the aggregate peak.

- [ ] **Step 6: Review and independently pin the baseline candidate**

Review the candidate through the private promotion process. Store its full-file SHA-256 outside the candidate as APPROVED_CORPUS_BASELINE_SHA256. Do not derive and trust the pin inside the record command:

~~~bash
test -f "$baseline_candidate"
test -n "$APPROVED_CORPUS_BASELINE_SHA256"
test "$(sha256sum -- "$baseline_candidate" | cut -d ' ' -f 1)" = \
  "$APPROVED_CORPUS_BASELINE_SHA256"
~~~

Expected: all assertions exit 0. Pause here if independent review/pin authority is not available.

- [ ] **Step 7: Verify with a fresh empty work directory**

~~~bash
verify_work="$(mktemp -d -p .superpowers/private corpus-verify.XXXXXX)"
git check-ignore --quiet "$verify_work"
env PYTHONPATH="$PWD/src" .venv/bin/ccparse verify-corpus "$RETAINED_CORPUS_DIR" \
  --quarantine-dir "$QUARANTINE_CORPUS_DIR" \
  --membership-inventory "$APPROVED_MEMBERSHIP_INVENTORY_PATH" \
  --membership-inventory-sha256 "$APPROVED_MEMBERSHIP_INVENTORY_SHA256" \
  --baseline "$baseline_candidate" \
  --baseline-sha256 "$APPROVED_CORPUS_BASELINE_SHA256" \
  --work-dir "$verify_work" \
  --mode verify \
  --jobs 1 \
  --expected-commit-sha "$EXPECTED_REVIEWED_SHA" \
  >"$candidate_dir/verify-output.txt"
~~~

Expected: exit 0 with status=passed, mode=verify, retained=104, reconciled=104, quarantined=5, and performance_checked=true.

- [ ] **Step 8: Reconfirm immutable candidate state**

~~~bash
test "$(git rev-parse --verify HEAD)" = "$EXPECTED_REVIEWED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(sha256sum -- "$baseline_candidate" | cut -d ' ' -f 1)" = \
  "$APPROVED_CORPUS_BASELINE_SHA256"
git check-ignore --quiet "$baseline_candidate"
git check-ignore --quiet "$record_work"
git check-ignore --quiet "$verify_work"
~~~

Expected: every assertion exits 0. Any tracked code/configuration change invalidates the attestation and requires Tasks 7-8 again.
