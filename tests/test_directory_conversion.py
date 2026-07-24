from __future__ import annotations

import gc
import threading
import traceback
import weakref
from collections.abc import Mapping
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

import ccparser.parser as parser_module
from ccparser.models import StatementResult, Status
from ccparser.parser import (
    MAX_WORKERS,
    BatchDisposition,
    ParserInputError,
    ParserRuntimeError,
    convert_directory_statements,
    summarize_batch_statuses,
)


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

    assert summary.resolved_output_dir == output_dir
    assert summary.source_count == 2
    assert delivered == [(0, "nested/a.pdf"), (1, "z.pdf")]


def test_convert_directory_empty_input_delivers_nothing(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    delivered: list[tuple[int, StatementResult]] = []

    summary = convert_directory_statements(
        input_dir,
        tmp_path / "output",
        statement_parser=_minimal_statement_parser,
        result_sink=lambda ordinal, result: delivered.append((ordinal, result)),
    )

    assert summary.source_count == 0
    assert delivered == []


@pytest.mark.parametrize("jobs", (0, -1, 1.5, True))
def test_convert_directory_validates_positive_integer_jobs(
    tmp_path: Path,
    jobs: object,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    with pytest.raises(ParserInputError, match="jobs"):
        convert_directory_statements(
            input_dir,
            tmp_path / "output",
            jobs=jobs,  # type: ignore[arg-type]
            result_sink=lambda ordinal, result: None,
        )


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


def test_jobs_one_releases_each_result_before_parsing_the_next(
    tmp_path: Path,
) -> None:
    previous: weakref.ReferenceType[StatementResult] | None = None

    def parse(
        path: Path,
        strict: bool = False,
        *,
        cache_dir: Path | None = None,
    ) -> StatementResult:
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


def test_bounded_concurrent_conversion_never_has_more_outstanding_futures_than_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for ordinal in range(MAX_WORKERS + 3):
        (input_dir / f"{ordinal:02}.pdf").write_bytes(str(ordinal).encode())
    lock = threading.Lock()
    submitted = 0
    delivered = 0
    maximum_outstanding = 0
    configured_workers: list[int] = []

    class TrackingExecutor:
        def __init__(self, max_workers: int) -> None:
            configured_workers.append(max_workers)
            self._executor = RealThreadPoolExecutor(max_workers=max_workers)

        def __enter__(self) -> Self:
            self._executor.__enter__()
            return self

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback_value: TracebackType | None,
        ) -> bool | None:
            return self._executor.__exit__(exception_type, exception, traceback_value)

        def submit(
            self,
            function: object,
            source: Path,
        ) -> Future[StatementResult]:
            nonlocal submitted, maximum_outstanding
            with lock:
                submitted += 1
                maximum_outstanding = max(maximum_outstanding, submitted - delivered)
            assert callable(function)
            return self._executor.submit(function, source)

        def map(
            self,
            function: object,
            sources: tuple[Path, ...],
        ) -> tuple[StatementResult, ...]:
            futures = tuple(self.submit(function, source) for source in sources)
            return tuple(future.result() for future in futures)

    def consume(ordinal: int, result: StatementResult, /) -> None:
        nonlocal delivered
        del ordinal, result
        with lock:
            delivered += 1

    monkeypatch.setattr(parser_module, "ThreadPoolExecutor", TrackingExecutor)

    summary = convert_directory_statements(
        input_dir,
        tmp_path / "output",
        jobs=10_000,
        cache_dir=tmp_path / "cache",
        statement_parser=_minimal_statement_parser,
        result_sink=consume,
    )

    assert summary.source_count == MAX_WORKERS + 3
    assert configured_workers == [MAX_WORKERS]
    assert maximum_outstanding == MAX_WORKERS


def test_bounded_scheduler_releases_completed_future_before_refilling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_references: list[weakref.ReferenceType[Future[StatementResult]]] = []
    maximum_live_futures = 0

    class RetentionTrackingExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def submit(
            self,
            function: object,
            source: Path,
        ) -> Future[StatementResult]:
            nonlocal maximum_live_futures
            assert callable(function)
            future: Future[StatementResult] = Future()
            future.set_result(function(source))
            future_references.append(weakref.ref(future))
            gc.collect()
            maximum_live_futures = max(
                maximum_live_futures,
                sum(reference() is not None for reference in future_references),
            )
            return future

    monkeypatch.setattr(parser_module, "ThreadPoolExecutor", RetentionTrackingExecutor)

    convert_directory_statements(
        _three_pdf_directory(tmp_path),
        tmp_path / "output",
        jobs=2,
        cache_dir=tmp_path / "cache",
        statement_parser=_minimal_statement_parser,
        result_sink=lambda ordinal, result: None,
    )

    assert maximum_live_futures == 2


def test_fast_completion_is_delivered_and_refills_before_slow_ordinal(
    tmp_path: Path,
) -> None:
    input_dir = _three_pdf_directory(tmp_path)
    zero_started = threading.Event()
    release_zero = threading.Event()
    one_completed = threading.Event()
    one_delivered = threading.Event()
    two_started = threading.Event()
    delivered: list[int] = []
    caller_thread_ids: list[int] = []
    sink_thread_ids: list[int] = []
    failures: list[BaseException] = []

    def parse(
        path: Path,
        strict: bool = False,
        *,
        cache_dir: Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        if path.name == "a.pdf":
            zero_started.set()
            if not release_zero.wait(timeout=15):
                raise AssertionError("ordinal zero was not released")
        elif path.name == "b.pdf":
            one_completed.set()
        else:
            two_started.set()
        return _result_for(path)

    def consume(ordinal: int, result: StatementResult, /) -> None:
        del result
        delivered.append(ordinal)
        sink_thread_ids.append(threading.get_ident())
        if ordinal == 1:
            one_delivered.set()

    def convert() -> None:
        caller_thread_ids.append(threading.get_ident())
        try:
            convert_directory_statements(
                input_dir,
                tmp_path / "output",
                jobs=2,
                cache_dir=tmp_path / "cache",
                statement_parser=parse,
                result_sink=consume,
            )
        except BaseException as error:
            failures.append(error)

    coordinator = threading.Thread(target=convert)
    coordinator.start()
    try:
        zero_was_started = zero_started.wait(timeout=5)
        one_was_completed = one_completed.wait(timeout=5)
        one_was_delivered = one_delivered.wait(timeout=5)
        two_was_started = two_started.wait(timeout=5)
    finally:
        release_zero.set()
        coordinator.join(timeout=5)

    assert zero_was_started
    assert one_was_completed
    assert one_was_delivered
    assert two_was_started
    assert not coordinator.is_alive()
    assert failures == []
    assert delivered[0] == 1
    assert set(sink_thread_ids) == set(caller_thread_ids)


@pytest.mark.parametrize("failure_stage", ("creation", "execution"))
def test_convert_directory_wraps_executor_failures_without_private_causes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    class FailingExecutor:
        def __init__(self, max_workers: int) -> None:
            del max_workers
            if failure_stage == "creation":
                raise RuntimeError("private executor creation detail")

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def submit(self, function: object, source: Path) -> Future[StatementResult]:
            del function, source
            raise RuntimeError("private executor execution detail")

        def map(
            self,
            function: object,
            sources: tuple[Path, ...],
        ) -> tuple[StatementResult, ...]:
            del function, sources
            raise RuntimeError("private executor execution detail")

    monkeypatch.setattr(parser_module, "ThreadPoolExecutor", FailingExecutor)

    with pytest.raises(
        ParserRuntimeError,
        match="directory statement processing failed",
    ) as caught:
        convert_directory_statements(
            _three_pdf_directory(tmp_path),
            tmp_path / "output",
            jobs=2,
            cache_dir=tmp_path / "cache",
            statement_parser=_minimal_statement_parser,
            result_sink=lambda ordinal, result: None,
        )

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert "private executor" not in rendered
