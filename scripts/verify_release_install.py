#!/usr/bin/env python3
"""Verify that a clean source archive installs and exposes the supported CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
from pathlib import Path
from typing import Final

_TIMEOUT_SECONDS: Final = 180.0
_PDF_PROGRAM: Final = """
import sys
from pathlib import Path
import fitz

target = Path(sys.argv[1])
document = fitz.open()
page = document.new_page(width=300, height=200)
page.insert_text(
    (24, 48),
    "Synthetic release smoke document alpha beta gamma delta epsilon zeta",
    fontsize=11,
)
document.save(target)
document.close()
"""


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    expected_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    if completed.returncode != expected_exit:
        verb = command[1] if len(command) > 1 else ""
        raise RuntimeError(
            f"release smoke command failed with exit {completed.returncode}: {command[0]} {verb}"
        )
    return completed


def _require_runtime() -> None:
    if sys.version_info[:2] != (3, 13) or sys.platform != "linux":
        raise RuntimeError("release verification requires Linux and Python 3.13")
    for command in ("git", "tesseract"):
        if shutil.which(command) is None:
            raise RuntimeError(f"release verification requires {command}")
    languages = _run(("tesseract", "--list-langs"), cwd=Path.cwd()).stdout.splitlines()
    if not {"eng", "heb"}.issubset({item.strip() for item in languages}):
        raise RuntimeError("release verification requires Tesseract eng and heb")


def _executable(environment: Path, name: str) -> Path:
    executable = environment / "bin" / name
    if not executable.is_file():
        raise RuntimeError(f"fresh environment did not install {name}")
    return executable


def _exercise_cli(candidate: Path, environment: Path, work: Path) -> None:
    python = _executable(environment, "python")
    ccparse = _executable(environment, "ccparse")
    input_dir = work / "input"
    input_dir.mkdir()
    source = input_dir / "synthetic.pdf"
    _run((str(python), "-c", _PDF_PROGRAM, str(source)), cwd=candidate)

    for arguments in (("--help",), ("parse", "--help"), ("audit", "--help")):
        _run((str(ccparse), *arguments), cwd=candidate)

    output = work / "output"
    parsed = _run(
        (str(ccparse), "parse", str(source), "--output-dir", str(output)),
        cwd=candidate,
    )
    if "status=unsupported" not in parsed.stdout:
        raise RuntimeError("synthetic parse did not conservatively abstain")
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    if payload["status"] != "unsupported":
        raise RuntimeError("synthetic JSON status is not unsupported")
    if not (output / "transactions.csv").is_file():
        raise RuntimeError("synthetic parse did not write transactions.csv")

    _run(
        (
            str(ccparse),
            "parse",
            str(source),
            "--output-dir",
            str(work / "strict-output"),
            "--strict",
        ),
        cwd=candidate,
        expected_exit=2,
    )

    quarantine = work / "quarantine"
    audited = _run(
        (
            str(ccparse),
            "audit",
            str(input_dir),
            "--quarantine-dir",
            str(quarantine),
        ),
        cwd=candidate,
    )
    expected = "documents=1 keep=0 review=1 quarantine=0 moved=0"
    if expected not in audited.stdout:
        raise RuntimeError("synthetic audit did not preserve the review boundary")
    if not source.is_file() or quarantine.exists():
        raise RuntimeError("dry-run audit mutated the synthetic input")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _require_runtime()
    status = _run(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        cwd=root,
    )
    if status.stdout:
        raise RuntimeError("release checkout is not clean")

    with tempfile.TemporaryDirectory(prefix="ccparser-release-smoke-") as temporary:
        work = Path(temporary)
        archive = work / "candidate.tar"
        candidate = work / "candidate"
        candidate.mkdir()
        _run(
            ("git", "archive", "--format=tar", f"--output={archive}", "HEAD"),
            cwd=root,
        )
        with tarfile.open(archive, mode="r:") as source_archive:
            source_archive.extractall(candidate, filter="data")

        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _executable(environment, "python")
        _run(
            (
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(candidate),
            ),
            cwd=candidate,
        )
        _exercise_cli(candidate, environment, work)

    print("release_install_smoke=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
