"""Canonical preflight authoring from reviewed descriptors and identity sidecars."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, Never

import typer
from pydantic import ValidationError, field_validator

from experiments.row_extraction.contracts import ArtifactIdentity, _FrozenModel

from .cli_manifest import LockedComparisonCliManifestV1
from .cli_paths import require_private_containment
from .cli_state import (
    canonical_model_bytes,
    identity_for_bytes,
    stable_regular_bytes,
    write_bytes_exclusive,
)


class ManifestAuthoringError(ValueError):
    """Reviewed descriptors and sidecars cannot produce the controller manifest."""


def _fail(message: str) -> Never:
    raise ManifestAuthoringError(message)


def _absolute(value: Path) -> Path:
    if not value.is_absolute() or Path(os.path.normpath(os.fspath(value))) != value:
        raise ValueError("sidecar path must be absolute and normalized")
    return value


class LockedIdentitySidecarsV1(_FrozenModel):
    version: Literal["row-comparison-locked-identity-sidecars-v1"]
    rows: Path
    gold: Path
    accepted_predictions: Path
    optional_ocr_references: Path | None = None

    _absolute_rows = field_validator("rows")(_absolute)
    _absolute_gold = field_validator("gold")(_absolute)
    _absolute_accepted = field_validator("accepted_predictions")(_absolute)

    @field_validator("optional_ocr_references")
    @classmethod
    def absolute_optional(cls, value: Path | None) -> Path | None:
        return None if value is None else _absolute(value)


def _identity_sidecar(path: Path) -> tuple[ArtifactIdentity, bytes]:
    payload = stable_regular_bytes(path, "locked identity sidecar is invalid")
    try:
        value = ArtifactIdentity.model_validate_json(payload)
    except (ValidationError, ValueError):
        _fail("locked identity sidecar is invalid")
    if payload != canonical_model_bytes(value):
        _fail("locked identity sidecar is invalid")
    return value, payload


def author_cli_manifest(
    descriptor_path: Path,
    sidecars_path: Path,
    output_path: Path,
) -> LockedComparisonCliManifestV1:
    """Publish canonical controller JSON without dereferencing deferred locked data."""

    try:
        descriptor = LockedComparisonCliManifestV1.model_validate_json(
            stable_regular_bytes(descriptor_path, "manifest descriptor is invalid")
        )
        sidecars = LockedIdentitySidecarsV1.model_validate_json(
            stable_regular_bytes(sidecars_path, "locked sidecar descriptor is invalid")
        )
    except (ManifestAuthoringError, ValidationError, ValueError):
        _fail("manifest authoring input is invalid")
    try:
        for path in (
            descriptor_path,
            sidecars_path,
            output_path,
            sidecars.rows,
            sidecars.gold,
            sidecars.accepted_predictions,
            *(
                ()
                if sidecars.optional_ocr_references is None
                else (sidecars.optional_ocr_references,)
            ),
        ):
            require_private_containment(path, descriptor.private_root)
    except ValueError:
        _fail("manifest authoring path escapes private root")
    row_identity, _row_payload = _identity_sidecar(sidecars.rows)
    gold_identity, _gold_payload = _identity_sidecar(sidecars.gold)
    accepted_identity, accepted_payload = _identity_sidecar(sidecars.accepted_predictions)
    optional = (
        None
        if sidecars.optional_ocr_references is None
        else _identity_sidecar(sidecars.optional_ocr_references)[0]
    )
    locked = descriptor.locked_inputs
    declared_optional = locked.optional_ocr_references
    accepted_sidecar_pin = locked.accepted_predictions_identity_file
    actual_sidecar_identity = identity_for_bytes(
        accepted_payload,
        artifact_type=accepted_sidecar_pin.identity.artifact_type,
        version=accepted_sidecar_pin.identity.version,
    )
    if (
        row_identity != locked.rows.identity
        or gold_identity != locked.gold.identity
        or accepted_identity != locked.accepted_predictions.identity
        or (None if declared_optional is None else declared_optional.identity) != optional
        or sidecars.accepted_predictions != accepted_sidecar_pin.path
        or actual_sidecar_identity != accepted_sidecar_pin.identity
    ):
        _fail("locked identity sidecar binding mismatch")
    write_bytes_exclusive(output_path, descriptor.canonical_bytes())
    return descriptor


app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("author")
def author_command(
    descriptor: Annotated[Path, typer.Option("--descriptor")],
    locked_identity_sidecars: Annotated[Path, typer.Option("--locked-identity-sidecars")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Create the reviewed canonical manifest without opening locked content."""

    try:
        author_cli_manifest(descriptor, locked_identity_sidecars, output)
        typer.echo('{"complete":true}')
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        typer.echo("ROW_COMPARISON_MANIFEST_AUTHOR_ERROR", err=True)
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()


__all__ = [
    "LockedIdentitySidecarsV1",
    "ManifestAuthoringError",
    "app",
    "author_cli_manifest",
]
