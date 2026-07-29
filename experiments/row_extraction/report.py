"""Privacy-safe aggregate reports for fixed-row extraction experiments."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel
from experiments.row_extraction.metrics import MetricReport
from experiments.row_extraction.runner import RunMeasurements


class ReportContractError(ValueError):
    """Aggregate report inputs do not describe the same measured run."""


class ReportContext(_FrozenModel):
    experiment_id: str = Field(min_length=1)
    config_id: str = Field(min_length=1)
    measurement_protocol: Literal["row-resource-measurement-v1"]
    runtime_identity: ArtifactIdentity
    python_version: str = Field(min_length=1)
    public_runtime_versions: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def canonical_public_versions(self) -> Self:
        names = tuple(name for name, _version in self.public_runtime_versions)
        if (
            any(
                not name.strip()
                or not version.strip()
                or name != name.strip()
                or version != version.strip()
                for name, version in self.public_runtime_versions
            )
            or names != tuple(sorted(names))
            or len(names) != len(set(names))
            or not self.python_version.strip()
            or self.python_version != self.python_version.strip()
        ):
            raise ValueError("public runtime versions must be sorted and unique")
        return self


def privacy_safe_report(
    metrics: MetricReport,
    run: RunMeasurements,
    context: ReportContext,
) -> dict[str, object]:
    """Return only public aggregate measurements after identity reconciliation."""

    try:
        metrics = MetricReport.model_validate(metrics.model_dump(mode="python"))
        run = RunMeasurements.model_validate(run.model_dump(mode="python"))
        context = ReportContext.model_validate(context.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise ReportContractError("invalid report input") from None

    if (
        run.experiment_id != context.experiment_id
        or run.config_id != context.config_id
        or run.measurement_protocol != context.measurement_protocol
        or run.runtime_identity != context.runtime_identity
    ):
        raise ReportContractError("report context mismatch") from None
    if metrics.row_count != run.row_count:
        raise ReportContractError("report row count mismatch") from None

    return {
        "experiment_id": run.experiment_id,
        "config_id": run.config_id,
        "measurement_protocol": run.measurement_protocol,
        "split": run.split.value,
        "cache_policy": run.cache_policy,
        "resource_basis": run.resource_basis,
        "metrics": metrics.model_dump(mode="json"),
        "resources": {
            "preparation_ns": run.preparation_ns,
            "total_ns": run.total_ns,
            "end_to_end_ns": run.end_to_end_ns,
            "cold_start_ns": run.cold_start_ns,
            "p50_ns": run.p50_ns,
            "p95_ns": run.p95_ns,
            "throughput_rows_per_second": str(run.throughput_rows_per_second),
            "peak_rss_bytes": run.peak_rss_bytes,
            "model_bytes": run.model_bytes,
            "dependency_bytes": run.dependency_bytes,
            "cache_bytes": run.cache_bytes,
            "subprocess_count": run.subprocess_count,
            "worker_count": run.worker_count,
        },
        "runtime": {
            "python_version": context.python_version,
            "public_versions": dict(context.public_runtime_versions),
        },
    }


__all__ = [
    "ReportContext",
    "ReportContractError",
    "privacy_safe_report",
]
