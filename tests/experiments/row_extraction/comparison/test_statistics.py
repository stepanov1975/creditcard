from decimal import Decimal

import pytest

from experiments.row_extraction.comparison.statistics import (
    StatisticsError,
    paired_document_bootstrap,
)


def test_paired_bootstrap_samples_complete_documents() -> None:
    interval = paired_document_bootstrap(
        first={"doc-a": Decimal("1"), "doc-b": Decimal("0")},
        second={"doc-a": Decimal("0"), "doc-b": Decimal("0")},
        seed="comparison-v1",
        samples=1000,
    )

    assert interval.effect == Decimal("0.5")
    assert interval.low == Decimal("0")
    assert interval.high == Decimal("1")
    assert interval.samples == 1000


def test_paired_bootstrap_is_deterministic_and_does_not_mutate_inputs() -> None:
    first = {"doc-a": Decimal("0.25"), "doc-b": Decimal("0.75")}
    second = {"doc-a": Decimal("0.5"), "doc-b": Decimal("0.5")}

    one = paired_document_bootstrap(first, second, seed="fixed", samples=101)
    two = paired_document_bootstrap(first, second, seed="fixed", samples=101)

    assert one.model_dump_json() == two.model_dump_json()
    assert first == {"doc-a": Decimal("0.25"), "doc-b": Decimal("0.75")}
    assert second == {"doc-a": Decimal("0.5"), "doc-b": Decimal("0.5")}


@pytest.mark.parametrize(
    ("first", "second", "seed", "samples", "message"),
    [
        ({}, {}, "fixed", 10, "at least one document"),
        (
            {"doc-a": Decimal("1")},
            {"doc-b": Decimal("1")},
            "fixed",
            10,
            "identical document IDs",
        ),
        (
            {"doc-a": Decimal("NaN")},
            {"doc-a": Decimal("1")},
            "fixed",
            10,
            "finite Decimal",
        ),
        (
            {"doc-a": Decimal("1")},
            {"doc-a": Decimal("1")},
            "",
            10,
            "nonempty seed",
        ),
        (
            {"doc-a": Decimal("1")},
            {"doc-a": Decimal("1")},
            "fixed",
            0,
            "positive sample count",
        ),
    ],
)
def test_paired_bootstrap_rejects_invalid_uncertainty_inputs(
    first: dict[str, Decimal],
    second: dict[str, Decimal],
    seed: str,
    samples: int,
    message: str,
) -> None:
    with pytest.raises(StatisticsError, match=message):
        paired_document_bootstrap(first, second, seed=seed, samples=samples)
