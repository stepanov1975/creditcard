"""Paired document-level uncertainty for row-extraction comparisons."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from pydantic import Field

from experiments.row_extraction.contracts import _FrozenModel

_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_LOW_PERCENTILE_NUMERATOR = 25
_HIGH_PERCENTILE_NUMERATOR = 975
_PERCENTILE_DENOMINATOR = 1000


class StatisticsError(ValueError):
    """Document-level uncertainty inputs violate the frozen comparison contract."""


class PairedInterval(_FrozenModel):
    effect: Decimal
    low: Decimal
    high: Decimal
    samples: int = Field(gt=0)


def _mean(values: Sequence[Decimal]) -> Decimal:
    with localcontext(_DECIMAL_CONTEXT):
        return sum(values, start=Decimal(0)) / Decimal(len(values))


def _validate(
    first: Mapping[str, Decimal],
    second: Mapping[str, Decimal],
    seed: str,
    samples: int,
) -> tuple[str, ...]:
    if not first or not second:
        raise StatisticsError("paired bootstrap requires at least one document")
    if set(first) != set(second):
        raise StatisticsError("paired bootstrap requires identical document IDs")
    if not seed:
        raise StatisticsError("paired bootstrap requires a nonempty seed")
    if samples <= 0:
        raise StatisticsError("paired bootstrap requires a positive sample count")
    if any(not key for key in first):
        raise StatisticsError("paired bootstrap requires nonempty document IDs")
    if any(
        not isinstance(value, Decimal) or not value.is_finite()
        for values in (first, second)
        for value in values.values()
    ):
        raise StatisticsError("paired bootstrap requires finite Decimal contributions")
    return tuple(sorted(first))


def paired_document_bootstrap(
    first: Mapping[str, Decimal],
    second: Mapping[str, Decimal],
    seed: str,
    samples: int,
) -> PairedInterval:
    """Bootstrap ``first - second`` document-macro effects with exact decimals.

    A positive effect and positive interval endpoints favor ``first``.
    """

    document_ids = _validate(first, second, seed, samples)
    with localcontext(_DECIMAL_CONTEXT):
        differences = tuple(first[key] - second[key] for key in document_ids)
    effect = _mean(differences)
    generator = random.Random(hashlib.sha256(seed.encode("utf-8")).digest())
    distribution = [
        _mean(tuple(differences[generator.randrange(len(document_ids))] for _ in document_ids))
        for _ in range(samples)
    ]
    distribution.sort()
    last_index = samples - 1
    low_index = last_index * _LOW_PERCENTILE_NUMERATOR // _PERCENTILE_DENOMINATOR
    high_index = last_index * _HIGH_PERCENTILE_NUMERATOR // _PERCENTILE_DENOMINATOR
    return PairedInterval(
        effect=effect,
        low=distribution[low_index],
        high=distribution[high_index],
        samples=samples,
    )


__all__ = ["PairedInterval", "StatisticsError", "paired_document_bootstrap"]
