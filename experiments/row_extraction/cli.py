"""Privacy-safe command line boundary for frozen row extraction experiments."""

from __future__ import annotations

import hashlib
import os
import resource
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from time import perf_counter_ns
from typing import Annotated, Literal, Never, cast

import fitz  # type: ignore[import-untyped]
import typer
from pydantic import BaseModel, ValidationError

from ccparser.evidence import TesseractOcr, extract_pdf
from ccparser.evidence import ocr as ocr_module
from ccparser.evidence.models import Word
from ccparser.output import _canonical_json_value_content
from experiments.row_extraction.annotations import validate_annotations
from experiments.row_extraction.baselines import (
    AcceptedBaselineArmFactory,
    ConditionalPageOcrArmFactory,
    ForcedPageOcrArmFactory,
    PageEvidenceRecord,
    PageWord,
    page_arm_config_id,
)
from experiments.row_extraction.bundle import prepare_bundle
from experiments.row_extraction.codecs import _canonical_record_bytes, read_jsonl, write_jsonl
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    DatasetSplit,
    FrozenRow,
    GoldRow,
    OcrReference,
    RowPrediction,
)
from experiments.row_extraction.crops import CropRecord
from experiments.row_extraction.metrics import score_predictions
from experiments.row_extraction.report import ReportContext, privacy_safe_report
from experiments.row_extraction.runner import (
    InventoryRoots,
    JsonlPredictionSink,
    MeasuredArmFactory,
    PreparationMeasurements,
    ResourceInventory,
    ResourceInventoryEntry,
    ResourceSpec,
    RunMeasurements,
    assert_repeated_output,
    build_resource_inventory,
    run_arm,
)
from experiments.row_extraction.split import SplitManifest

type _Mode = Literal[
    "accepted-baseline",
    "conditional-page-ocr",
    "forced-page-ocr",
]
type _PageMode = Literal["conditional-page-ocr", "forced-page-ocr"]
type _Launch = Callable[..., subprocess.CompletedProcess[bytes]]

_INVENTORY_VERSION = "row-resource-inventory-v1"
_ROW_SEQUENCE_VERSION = "canonical-jsonl-v1"
_PAGE_EVIDENCE_VERSION: Literal["fixed-page-evidence-v1"] = "fixed-page-evidence-v1"
_CONDITIONAL_CONFIG = "production-conditional-page-evidence-v1"
_FORCED_CONFIG = "production-forced-whole-page-tesseract-v1"
_WORKTREE = Path(__file__).resolve().parents[2]

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Prepare, validate, execute, and score private frozen-row artifacts.",
)


class CliContractError(ValueError):
    """A command cannot satisfy its public, privacy-safe contract."""


def _abort(code: str) -> Never:
    typer.echo(code, err=True)
    raise typer.Exit(code=1) from None


def _run_safely(code: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        _abort(code)


def _canonical_model_bytes(model: BaseModel) -> bytes:
    return _canonical_json_value_content(model.model_dump(mode="json")) + b"\n"


def _write_model(path: Path, model: BaseModel) -> tuple[int, int]:
    if path.exists():
        raise CliContractError("output already exists")
    payload = _canonical_model_bytes(model)
    temporary: Path | None = None
    owned_temporary: tuple[int, int] | None = None
    owned_target: tuple[int, int] | None = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            temporary_stat = os.fstat(output.fileno())
            if not stat.S_ISREG(temporary_stat.st_mode):
                raise CliContractError("temporary output is not a regular file")
            owned_temporary = (temporary_stat.st_dev, temporary_stat.st_ino)
            output.write(payload)
        os.link(temporary, path, follow_symlinks=False)
        owned_target = owned_temporary
        before = path.stat(follow_symlinks=False)
        content = path.read_bytes()
        after = path.stat(follow_symlinks=False)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if (
            owned_target is None
            or not stat.S_ISREG(after.st_mode)
            or (after.st_dev, after.st_ino) != owned_target
            or before_identity != after_identity
            or content != payload
        ):
            raise CliContractError("published output identity changed")
        if owned_temporary is not None:
            _unlink_owned_output(temporary, owned_temporary)
            owned_temporary = None
        published = True
        return owned_target
    except FileExistsError:
        raise CliContractError("output already exists") from None
    except BaseException:
        raise
    finally:
        if temporary is not None and owned_temporary is not None:
            _unlink_owned_output(temporary, owned_temporary)
        if not published and owned_target is not None:
            _unlink_owned_output(path, owned_target)


def _read_model[Model: BaseModel](path: Path, model: type[Model]) -> Model:
    try:
        payload = path.read_bytes()
        value = model.model_validate_json(payload)
    except (OSError, ValidationError, ValueError):
        raise CliContractError("invalid private model") from None
    if payload != _canonical_model_bytes(value):
        raise CliContractError("private model is not canonical")
    return value


def _stream_identity(path: Path, *, artifact_type: str = "jsonl") -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                byte_size += len(block)
    except OSError:
        raise CliContractError("private artifact is unavailable") from None
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=digest.hexdigest(),
        version=_ROW_SEQUENCE_VERSION,
        byte_size=byte_size,
    )


def _records_identity(records: Iterable[BaseModel], *, artifact_type: str) -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    for record in records:
        content = _canonical_record_bytes(record)
        digest.update(content)
        byte_size += len(content)
    return ArtifactIdentity(
        artifact_type=artifact_type,
        sha256=digest.hexdigest(),
        version=_ROW_SEQUENCE_VERSION,
        byte_size=byte_size,
    )


def _read_records[Model: BaseModel](path: Path, model: type[Model]) -> tuple[Model, ...]:
    try:
        return tuple(read_jsonl(path, model))
    except (OSError, ValidationError, ValueError):
        raise CliContractError("invalid private record stream") from None


def _is_ignored_or_external(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(_WORKTREE):
        return True
    completed = subprocess.run(
        ("git", "check-ignore", "--quiet", str(resolved)),
        cwd=_WORKTREE,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def _private_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise CliContractError("private root is invalid")
    resolved = path.resolve(strict=True)
    if not _is_ignored_or_external(resolved):
        raise CliContractError("private root is not ignored")
    return resolved


def _beneath(path: Path, root: Path) -> Path:
    if not path.is_absolute():
        raise CliContractError("private path must be absolute")
    resolved = path.resolve(strict=False)
    if resolved == root or not resolved.is_relative_to(root):
        raise CliContractError("private path escapes root")
    return resolved


def _input_file(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise CliContractError("private input is invalid")
    resolved = path.resolve(strict=True)
    if not _is_ignored_or_external(resolved):
        raise CliContractError("private input is not ignored")
    return resolved


def _input_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise CliContractError("private input directory is invalid")
    resolved = path.resolve(strict=True)
    if not _is_ignored_or_external(resolved):
        raise CliContractError("private input directory is not ignored")
    return resolved


def _new_file(path: Path, root: Path) -> Path:
    resolved = _beneath(path, root)
    if resolved.exists() or not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise CliContractError("output path is not new")
    return resolved


def _new_directory(path: Path, root: Path) -> Path:
    resolved = _beneath(path, root)
    if resolved.exists() or not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise CliContractError("output directory is not new")
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _split(value: str, *, allow_test: bool) -> DatasetSplit:
    try:
        split = DatasetSplit(value)
    except ValueError:
        raise CliContractError("invalid split") from None
    if split is DatasetSplit.TEST and not allow_test:
        raise CliContractError("test split is locked")
    return split


def _mode(value: str) -> _Mode:
    if value not in {
        "accepted-baseline",
        "conditional-page-ocr",
        "forced-page-ocr",
    }:
        raise CliContractError("invalid baseline mode")
    return cast(_Mode, value)


def _identity_matches(path: Path, identity: ArtifactIdentity) -> None:
    if _stream_identity(path) != identity:
        raise CliContractError("artifact identity mismatch")


def _file_entry(
    path: Path, category: Literal["model", "dependency", "cache"]
) -> ResourceInventoryEntry:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    after = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not path.is_file()
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or size != after.st_size
    ):
        raise CliContractError("inventory entry changed")
    return ResourceInventoryEntry(
        category=category,
        resolved_path=path.resolve(strict=True),
        sha256=digest.hexdigest(),
        byte_size=size,
        device=after.st_dev,
        inode=after.st_ino,
    )


def _inventory_payload(inventory: ResourceInventory) -> bytes:
    return _canonical_model_bytes(inventory)


def _inventory_identity(payload: bytes) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="resource-inventory",
        sha256=hashlib.sha256(payload).hexdigest(),
        version=_INVENTORY_VERSION,
        byte_size=len(payload),
    )


def _validate_inventory(inventory: ResourceInventory) -> None:
    expected = tuple(
        sorted(
            inventory.entries,
            key=lambda entry: (entry.category, str(entry.resolved_path), entry.sha256),
        )
    )
    if inventory.entries != expected:
        raise CliContractError("inventory is not canonical")
    seen_paths: set[Path] = set()
    seen_inodes: set[tuple[int, int]] = set()
    for entry in inventory.entries:
        current = _file_entry(entry.resolved_path, entry.category)
        identity = (entry.device, entry.inode)
        if current != entry or entry.resolved_path in seen_paths or identity in seen_inodes:
            raise CliContractError("inventory entry mismatch")
        seen_paths.add(entry.resolved_path)
        seen_inodes.add(identity)


def _read_inventory(path: Path) -> tuple[ResourceInventory, ArtifactIdentity]:
    inventory = _read_model(path, ResourceInventory)
    _validate_inventory(inventory)
    payload = path.read_bytes()
    return inventory, _inventory_identity(payload)


def _write_inventory(
    path: Path, inventory: ResourceInventory
) -> tuple[ArtifactIdentity, tuple[int, int]]:
    _validate_inventory(inventory)
    owned = _write_model(path, inventory)
    return _inventory_identity(path.read_bytes()), owned


def _owned_inventory_output(path: Path, expected: ArtifactIdentity) -> tuple[int, int]:
    before = path.stat(follow_symlinks=False)
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise CliContractError("resource inventory publication is invalid")
    _inventory, actual = _read_inventory(path)
    after = path.stat(follow_symlinks=False)
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if actual != expected or before_identity != after_identity:
        raise CliContractError("resource inventory publication changed")
    return after.st_dev, after.st_ino


def _unlink_owned_output(path: Path, identity: tuple[int, int]) -> None:
    try:
        current = path.stat(follow_symlinks=False)
        if (
            not path.is_symlink()
            and stat.S_ISREG(current.st_mode)
            and (current.st_dev, current.st_ino) == identity
        ):
            path.unlink()
    except OSError:
        return


def _matches_owned_output(path: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        current = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity


def _union_inventory(
    model: ResourceInventory,
    dependency: ResourceInventory,
    cache_entries: Sequence[ResourceInventoryEntry] = (),
) -> ResourceInventory:
    if any(entry.category != "model" for entry in model.entries):
        raise CliContractError("model inventory category mismatch")
    if any(entry.category != "dependency" for entry in dependency.entries):
        raise CliContractError("dependency inventory category mismatch")
    if not dependency.entries:
        raise CliContractError("dependency inventory is empty")
    entries = (*model.entries, *dependency.entries, *cache_entries)
    if len({(entry.device, entry.inode) for entry in entries}) != len(entries):
        raise CliContractError("inventory categories overlap")
    return ResourceInventory(
        version="row-resource-inventory-v1",
        entries=tuple(
            sorted(
                entries,
                key=lambda entry: (
                    entry.category,
                    str(entry.resolved_path),
                    entry.sha256,
                ),
            )
        ),
    )


def _page_config(mode: _PageMode) -> str:
    return _CONDITIONAL_CONFIG if mode == "conditional-page-ocr" else _FORCED_CONFIG


def _page_factory_config(mode: _PageMode) -> str:
    return page_arm_config_id(_page_config(mode))


def _validate_mode_model_inventory(mode: _Mode, inventory: ResourceInventory) -> None:
    if mode == "accepted-baseline":
        if inventory.entries:
            raise CliContractError("accepted baseline model inventory is not empty")
    elif not inventory.entries:
        raise CliContractError("page baseline model inventory is empty")


def _page_word(ordinal: int, word: Word) -> PageWord:
    return PageWord(
        ordinal=ordinal,
        text=word.text,
        bbox=word.bbox,
        source=word.source,
        confidence=word.confidence,
    )


@contextmanager
def _count_tesseract_launches() -> Iterator[list[int]]:
    original = cast(_Launch, ocr_module._launch_tesseract)
    count = [0]

    def counted(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        count[0] += 1
        return original(*args, **kwargs)

    ocr_module._launch_tesseract = counted
    try:
        yield count
    finally:
        ocr_module._launch_tesseract = original


_OCR_PASS_SUFFIXES = (
    ".primary.tsv",
    ".supplemental.tsv",
    ".numeric.tsv",
    ".currency.tsv",
)


def _ocr_cache_artifacts(cache_dir: Path) -> frozenset[Path]:
    try:
        cache_entries = tuple(cache_dir.rglob("*"))
    except OSError:
        raise CliContractError("OCR cache is unavailable") from None
    if any(path.is_symlink() for path in cache_entries):
        raise CliContractError("OCR cache contains a symlink")
    artifacts = frozenset(
        path
        for path in cache_entries
        if any(path.name.endswith(suffix) for suffix in _OCR_PASS_SUFFIXES)
    )
    cache_files = frozenset(path for path in cache_entries if path.is_file())
    if artifacts != cache_files or any(not path.is_file() for path in artifacts):
        raise CliContractError("OCR cache pass artifact is invalid")
    return artifacts


class _ObservedTesseractOcr(TesseractOcr):
    def __init__(self, cache_dir: Path) -> None:
        super().__init__(cache_dir)
        self.cache_dir = cache_dir
        self._requested_artifacts: set[Path] = set()
        self.word_request_count = 0
        self.currency_request_count = 0

    @property
    def requested_artifacts(self) -> frozenset[Path]:
        return frozenset(self._requested_artifacts)

    def _word_artifacts(
        self,
        source_sha256: str,
        page_index: int,
        clip: BBox | None,
    ) -> frozenset[Path]:
        recognition_key = self.cache_key(source_sha256, page_index, clip)
        return frozenset(
            (
                self.cache_dir / f"{recognition_key}.primary.tsv",
                self.cache_dir / f"{recognition_key}.supplemental.tsv",
                self.cache_dir / f"{self._numeric_cache_key(recognition_key)}.numeric.tsv",
            )
        )

    def _currency_artifacts(
        self,
        source_sha256: str,
        page_index: int,
        clip: BBox,
    ) -> frozenset[Path]:
        recognition_key = self.cache_key(source_sha256, page_index, clip)
        return frozenset(
            (self.cache_dir / f"{self._currency_cache_key(recognition_key)}.currency.tsv",)
        )

    def _validate_request(
        self,
        before: frozenset[Path],
        expected: frozenset[Path],
        prior_requested: frozenset[Path],
    ) -> None:
        after = _ocr_cache_artifacts(self.cache_dir)
        nested_requested = self.requested_artifacts - prior_requested
        requested = expected | nested_requested
        if after - before != requested - before or not requested <= after:
            raise CliContractError("OCR cache key binding mismatch")
        self._requested_artifacts.update(expected)

    def extract_words(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox | None = None,
    ) -> tuple[Word, ...]:
        before = _ocr_cache_artifacts(self.cache_dir)
        prior_requested = self.requested_artifacts
        expected = self._word_artifacts(source_sha256, page_index, clip)
        words = super().extract_words(pdf_bytes, source_sha256, page_index, clip)
        self._validate_request(before, expected, prior_requested)
        self.word_request_count += 1
        return words

    def extract_currency_symbol(
        self,
        pdf_bytes: bytes,
        source_sha256: str,
        page_index: int,
        clip: BBox,
    ) -> Word | None:
        before = _ocr_cache_artifacts(self.cache_dir)
        prior_requested = self.requested_artifacts
        expected = self._currency_artifacts(source_sha256, page_index, clip)
        word = super().extract_currency_symbol(pdf_bytes, source_sha256, page_index, clip)
        self._validate_request(before, expected, prior_requested)
        self.currency_request_count += 1
        return word


def _verify_ocr_cache(
    cache_dir: Path,
    *,
    page_count: int,
    forced: bool,
    requested_artifacts: frozenset[Path],
    word_request_count: int,
) -> int:
    artifacts = _ocr_cache_artifacts(cache_dir)
    if artifacts != requested_artifacts:
        raise CliContractError("OCR cache key binding mismatch")
    recognition_count = len(artifacts)
    if word_request_count > page_count or (forced and word_request_count != page_count):
        raise CliContractError("OCR page cache mismatch")
    return recognition_count + int(recognition_count > 0)


def _selected_rows(path: Path, split: DatasetSplit) -> tuple[FrozenRow, ...]:
    all_rows = _read_records(path, FrozenRow)
    all_identities = tuple((row.document_id, row.row_id) for row in all_rows)
    rows = tuple(row for row in all_rows if row.split is split)
    if not rows or len(all_identities) != len(set(all_identities)):
        raise CliContractError("selected row stream is invalid")
    return rows


def _validated_row_sources(
    rows: Sequence[FrozenRow],
) -> dict[str, ResourceInventoryEntry]:
    document_paths: dict[str, set[Path]] = {}
    path_documents: dict[Path, set[str]] = {}
    for row in rows:
        source = _input_file(row.source_pdf)
        document_paths.setdefault(row.document_id, set()).add(source)
        path_documents.setdefault(source, set()).add(row.document_id)

    entries = {path: _file_entry(path, "cache") for path in sorted(path_documents)}
    inode_documents: dict[tuple[int, int], set[str]] = {}
    for path, documents in path_documents.items():
        entry = entries[path]
        inode_documents.setdefault((entry.device, entry.inode), set()).update(documents)
    if (
        any(len(paths) != 1 for paths in document_paths.values())
        or any(len(documents) != 1 for documents in path_documents.values())
        or any(len(documents) != 1 for documents in inode_documents.values())
    ):
        raise CliContractError("document source mapping changed")

    sources: dict[str, ResourceInventoryEntry] = {}
    for document_id, paths in document_paths.items():
        path = next(iter(paths))
        entry = entries[path]
        if entry.sha256 != document_id:
            raise CliContractError("document identity mismatch")
        sources[document_id] = entry
    return sources


def _verify_source_binding(source: ResourceInventoryEntry) -> Path:
    current = _file_entry(source.resolved_path, "cache")
    if current != source:
        raise CliContractError("document source changed")
    return source.resolved_path


def _conditional_records(
    rows: Sequence[FrozenRow],
    sources: dict[str, ResourceInventoryEntry],
    provider: TesseractOcr,
    runtime: ArtifactIdentity,
) -> tuple[PageEvidenceRecord, ...]:
    required: dict[tuple[str, int], FrozenRow] = {}
    for row in rows:
        required.setdefault((row.document_id, row.page_number), row)
    pages: dict[tuple[str, int], PageEvidenceRecord] = {}
    for document_id, source_binding in sources.items():
        source = _verify_source_binding(source_binding)
        evidence = extract_pdf(source, provider)
        if evidence.source_sha256 != document_id:
            raise CliContractError("document identity mismatch")
        _verify_source_binding(source_binding)
        for page in evidence.pages:
            key = (document_id, page.page_number)
            if key not in required:
                continue
            pages[key] = PageEvidenceRecord(
                document_id=document_id,
                page_number=page.page_number,
                page_bbox=(0.0, 0.0, page.width, page.height),
                mode="conditional-page-ocr",
                evidence_version=_PAGE_EVIDENCE_VERSION,
                config_id=_CONDITIONAL_CONFIG,
                runtime_identity=runtime,
                words=tuple(_page_word(index, word) for index, word in enumerate(page.words)),
            )
    if set(pages) != set(required):
        raise CliContractError("page evidence is incomplete")
    return tuple(pages[key] for key in required)


def _forced_records(
    rows: Sequence[FrozenRow],
    sources: dict[str, ResourceInventoryEntry],
    provider: TesseractOcr,
    runtime: ArtifactIdentity,
) -> tuple[PageEvidenceRecord, ...]:
    required: dict[tuple[str, int], Path] = {}
    for row in rows:
        source = sources[row.document_id].resolved_path
        key = (row.document_id, row.page_number)
        previous = required.setdefault(key, source)
        if previous != source:
            raise CliContractError("document page source mapping changed")
    records: list[PageEvidenceRecord] = []
    for (document_id, page_number), source in required.items():
        _verify_source_binding(sources[document_id])
        pdf_bytes = source.read_bytes()
        if hashlib.sha256(pdf_bytes).hexdigest() != document_id:
            raise CliContractError("document identity mismatch")
        _verify_source_binding(sources[document_id])
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if page_number > document.page_count:
                raise CliContractError("page evidence is incomplete")
            page = document[page_number - 1]
            page_bbox = (
                float(page.rect.x0),
                float(page.rect.y0),
                float(page.rect.x1),
                float(page.rect.y1),
            )
        words = provider.extract_words(pdf_bytes, document_id, page_number - 1)
        records.append(
            PageEvidenceRecord(
                document_id=document_id,
                page_number=page_number,
                page_bbox=page_bbox,
                mode="forced-page-ocr",
                evidence_version=_PAGE_EVIDENCE_VERSION,
                config_id=_FORCED_CONFIG,
                runtime_identity=runtime,
                words=tuple(_page_word(index, word) for index, word in enumerate(words)),
            )
        )
    return tuple(records)


def _prepare_page_evidence(
    *,
    private_root: Path,
    rows_path: Path,
    split: DatasetSplit,
    mode: _PageMode,
    runtime_path: Path,
    cache_dir: Path,
    output: Path,
    identity_output: Path,
    model_inventory_path: Path,
    dependency_inventory_path: Path,
    inventory_output: Path,
    preparation_output: Path,
) -> None:
    root = _private_root(private_root)
    rows_file = _input_file(rows_path)
    runtime = _read_model(_input_file(runtime_path), ArtifactIdentity)
    model_path = _input_file(_beneath(model_inventory_path, root))
    dependency_path = _input_file(_beneath(dependency_inventory_path, root))
    model, model_identity = _read_inventory(model_path)
    dependency, dependency_identity = _read_inventory(dependency_path)
    _validate_mode_model_inventory(mode, model)
    selected = _selected_rows(rows_file, split)
    sources = _validated_row_sources(selected)
    cache = _new_directory(cache_dir, root)
    evidence_output = _beneath(output, root)
    evidence_identity_output = _beneath(identity_output, root)
    if (
        evidence_output.parent != cache
        or evidence_identity_output.parent != cache
        or evidence_output == evidence_identity_output
        or evidence_output.exists()
        or evidence_identity_output.exists()
    ):
        raise CliContractError("page evidence outputs must be new cache children")
    inventory_path = _new_file(inventory_output, root)
    preparation_path = _new_file(preparation_output, root)
    if (
        inventory_path.is_relative_to(cache)
        or preparation_path.is_relative_to(cache)
        or inventory_path == preparation_path
    ):
        raise CliContractError("preparation outputs overlap the cache")
    cache.mkdir()
    owned_evidence_identity: tuple[int, int] | None = None
    owned_inventory: tuple[int, int] | None = None
    owned_preparation: tuple[int, int] | None = None
    start = perf_counter_ns()
    start_rss = _rss_bytes()
    try:
        provider = _ObservedTesseractOcr(cache)
        with _count_tesseract_launches() as launches:
            records = (
                _conditional_records(selected, sources, provider, runtime)
                if mode == "conditional-page-ocr"
                else _forced_records(selected, sources, provider, runtime)
            )
        expected_launches = _verify_ocr_cache(
            cache,
            page_count=len({(row.document_id, row.page_number) for row in selected}),
            forced=mode == "forced-page-ocr",
            requested_artifacts=provider.requested_artifacts,
            word_request_count=provider.word_request_count,
        )
        if launches[0] != expected_launches:
            raise CliContractError("OCR subprocess count mismatch")
        evidence_identity = write_jsonl(evidence_output, records)
        owned_evidence_identity = _write_model(evidence_identity_output, evidence_identity)
        cache_paths = tuple(sorted(cache.rglob("*")))
        if any(
            path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in cache_paths
        ):
            raise CliContractError("page evidence cache contains an invalid entry")
        cache_entries = tuple(_file_entry(path, "cache") for path in cache_paths if path.is_file())
        combined = _union_inventory(model, dependency, cache_entries)
        combined_identity, owned_inventory = _write_inventory(inventory_path, combined)
        end = perf_counter_ns()
        if end <= start:
            raise CliContractError("preparation clock did not advance")
        preparation = PreparationMeasurements(
            experiment_id=mode,
            config_id=_page_factory_config(mode),
            row_sequence_identity=_records_identity(selected, artifact_type="frozen-row-sequence"),
            row_count=len(selected),
            split=split,
            cache_policy="new-empty-v1",
            resource_basis="end-to-end-method",
            preparation_ns=end - start,
            peak_rss_bytes=max(start_rss, _rss_bytes()),
            subprocess_count=launches[0],
            worker_count=1,
            runtime_identity=runtime,
            arm_manifest_identity=evidence_identity,
            resource_inventory_path=inventory_path,
            resource_inventory_identity=combined_identity,
        )
        if model_identity != _inventory_identity(_inventory_payload(model)) or (
            dependency_identity != _inventory_identity(_inventory_payload(dependency))
        ):
            raise CliContractError("inventory identity changed")
        owned_preparation = _write_model(preparation_path, preparation)
    except BaseException:
        if not evidence_identity_output.exists() or _matches_owned_output(
            evidence_identity_output, owned_evidence_identity
        ):
            shutil.rmtree(cache, ignore_errors=True)
        if owned_inventory is not None:
            _unlink_owned_output(inventory_path, owned_inventory)
        if owned_preparation is not None:
            _unlink_owned_output(preparation_path, owned_preparation)
        raise


def _rss_bytes() -> int:
    value = (
        int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        + int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    ) * 1024
    if value <= 0:
        raise CliContractError("RSS measurement is unavailable")
    return value


def _validate_bundle(destination: Path, manifest: SplitManifest) -> None:
    identities = (
        ("rows", FrozenRow),
        ("accepted_predictions", RowPrediction),
        ("crop_index", CropRecord),
    )
    streams: dict[str, tuple[BaseModel, ...]] = {}
    for name, model in identities:
        stream = destination / f"{name}.jsonl"
        records = _read_records(stream, model)
        identity = _read_model(destination / f"{name}.identity.json", ArtifactIdentity)
        _identity_matches(stream, identity)
        streams[name] = records
    rows = cast(tuple[FrozenRow, ...], streams["rows"])
    predictions = cast(tuple[RowPrediction, ...], streams["accepted_predictions"])
    crops = cast(tuple[CropRecord, ...], streams["crop_index"])
    row_identities = tuple((row.document_id, row.row_id) for row in rows)
    prediction_identities = tuple(
        (prediction.document_id, prediction.row_id) for prediction in predictions
    )
    crop_identities = tuple((crop.document_id, crop.row_id) for crop in crops)
    if (
        not rows
        or len(row_identities) != len(set(row_identities))
        or len(prediction_identities) != len(set(prediction_identities))
        or len(crop_identities) != len(set(crop_identities))
        or set(row_identities) != set(prediction_identities)
        or set(row_identities) != set(crop_identities)
        or any(
            prediction.experiment_id != "accepted-baseline"
            or prediction.config_id != "accepted-anchor"
            for prediction in predictions
        )
    ):
        raise CliContractError("bundle identity bijection mismatch")
    rows_by_identity = {(row.document_id, row.row_id): row for row in rows}
    if any(
        prediction.predicted_type
        is not rows_by_identity[(prediction.document_id, prediction.row_id)].baseline_type
        for prediction in predictions
    ):
        raise CliContractError("bundle accepted prediction type mismatch")
    crop_root = destination / "crops"
    for crop in crops:
        row = rows_by_identity[(crop.document_id, crop.row_id)]
        relative = Path(crop.relative_path)
        crop_path = (crop_root / relative).resolve(strict=False)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or crop_path == crop_root
            or not crop_path.is_relative_to(crop_root)
            or crop_path.is_symlink()
            or not crop_path.is_file()
            or crop.row_bbox != row.bbox
            or _file_entry(crop_path, "cache").sha256 != crop.sha256
        ):
            raise CliContractError("bundle crop index mismatch")
    expected = {membership.document_id: membership.split for membership in manifest.memberships}
    actual: dict[str, DatasetSplit] = {}
    for row in rows:
        prior = actual.setdefault(row.document_id, row.split)
        if prior is not row.split:
            raise CliContractError("document spans frozen splits")
    if any(expected.get(document_id) is not split for document_id, split in actual.items()):
        raise CliContractError("bundle membership mismatch")


def _prepare(private_root: Path, documents: Path, split_manifest: Path, output_dir: Path) -> None:
    root = _private_root(private_root)
    document_root = _input_directory(documents)
    manifest = _read_model(_input_file(_beneath(split_manifest, root)), SplitManifest)
    destination = _new_directory(output_dir, root)
    candidates = tuple(path for path in document_root.rglob("*") if path.suffix.lower() == ".pdf")
    if not candidates or any(path.is_symlink() or not path.is_file() for path in candidates):
        raise CliContractError("document source set is invalid")
    identified = tuple(
        (_file_entry(path.resolve(strict=True), "cache").sha256, path) for path in candidates
    )
    if len({identity for identity, _path in identified}) != len(identified):
        raise CliContractError("document source identity is duplicated")
    sources = tuple(path for _identity, path in sorted(identified))
    split_by_document = {
        membership.document_id: membership.split for membership in manifest.memberships
    }
    if {identity for identity, _path in identified} != set(split_by_document):
        raise CliContractError("document source membership mismatch")
    attempted_sidecars: set[Path] = set()
    owned_sidecars: dict[Path, tuple[int, int]] = {}
    try:
        bundle = prepare_bundle(sources, destination, split_by_document)
        for name, identity in (
            ("rows", bundle.rows),
            ("accepted_predictions", bundle.accepted_predictions),
            ("crop_index", bundle.crop_index),
        ):
            stream = destination / f"{name}.jsonl"
            if _stream_identity(stream) != identity:
                raise CliContractError("prepared bundle identity mismatch")
            sidecar = destination / f"{name}.identity.json"
            attempted_sidecars.add(sidecar)
            owned_sidecars[sidecar] = _write_model(sidecar, identity)
        _validate_bundle(destination, manifest)
    except BaseException:
        if all(
            not sidecar.exists() or _matches_owned_output(sidecar, owned_sidecars.get(sidecar))
            for sidecar in attempted_sidecars
        ):
            shutil.rmtree(destination, ignore_errors=True)
        raise


@app.command("prepare")
def prepare_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    documents: Annotated[Path, typer.Option("--documents")],
    split_manifest: Annotated[Path, typer.Option("--split-manifest")],
    output_dir: Annotated[Path, typer.Option("--output-dir")],
) -> None:
    """Prepare the complete accepted fixed-row bundle."""

    _run_safely(
        "ROW_CLI_PREPARE_ERROR",
        lambda: _prepare(private_root, documents, split_manifest, output_dir),
    )


def _prepare_inventory(
    private_root: Path, roots: Path, output: Path, identity_output: Path
) -> None:
    root = _private_root(private_root)
    roots_model = _read_model(_input_file(_beneath(roots, root)), InventoryRoots)
    inventory_path = _new_file(output, root)
    identity_path = _new_file(identity_output, root)
    if identity_path == inventory_path:
        raise CliContractError("inventory outputs overlap")
    inventory = build_resource_inventory(roots_model)
    owned_inventory: tuple[int, int] | None = None
    owned_identity: tuple[int, int] | None = None
    try:
        identity, owned_inventory = _write_inventory(inventory_path, inventory)
        owned_identity = _write_model(identity_path, identity)
    except BaseException:
        if owned_inventory is not None:
            _unlink_owned_output(inventory_path, owned_inventory)
        if owned_identity is not None:
            _unlink_owned_output(identity_path, owned_identity)
        raise


@app.command("prepare-inventory")
def prepare_inventory_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    roots: Annotated[Path, typer.Option("--roots")],
    output: Annotated[Path, typer.Option("--output")],
    identity_output: Annotated[Path, typer.Option("--identity-output")],
) -> None:
    """Create one canonical model or dependency inventory."""

    _run_safely(
        "ROW_CLI_INVENTORY_ERROR",
        lambda: _prepare_inventory(private_root, roots, output, identity_output),
    )


@app.command("prepare-page-evidence")
def prepare_page_evidence_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    rows: Annotated[Path, typer.Option("--rows")],
    split: Annotated[str, typer.Option("--split")],
    mode: Annotated[str, typer.Option("--mode")],
    runtime_identity: Annotated[Path, typer.Option("--runtime-identity")],
    cache_dir: Annotated[Path, typer.Option("--cache-dir")],
    output: Annotated[Path, typer.Option("--output")],
    identity_output: Annotated[Path, typer.Option("--identity-output")],
    model_inventory: Annotated[Path, typer.Option("--model-inventory")],
    dependency_inventory: Annotated[Path, typer.Option("--dependency-inventory")],
    inventory_output: Annotated[Path, typer.Option("--inventory-output")],
    preparation_output: Annotated[Path, typer.Option("--preparation-output")],
) -> None:
    """Prepare one typed, measured whole-page evidence stream."""

    def operation() -> None:
        selected_mode = _mode(mode)
        if selected_mode == "accepted-baseline":
            raise CliContractError("accepted mode has no page preparation")
        _prepare_page_evidence(
            private_root=private_root,
            rows_path=rows,
            split=_split(split, allow_test=False),
            mode=selected_mode,
            runtime_path=runtime_identity,
            cache_dir=cache_dir,
            output=output,
            identity_output=identity_output,
            model_inventory_path=model_inventory,
            dependency_inventory_path=dependency_inventory,
            inventory_output=inventory_output,
            preparation_output=preparation_output,
        )

    _run_safely("ROW_CLI_PAGE_EVIDENCE_ERROR", operation)


def _prepare_run_spec(
    *,
    private_root: Path,
    rows: Path,
    split: DatasetSplit,
    mode: _Mode,
    arm_manifest_identity: Path,
    runtime_identity: Path,
    model_inventory: Path,
    dependency_inventory: Path,
    cache_root: Path,
    inventory_output: Path,
    output: Path,
) -> None:
    root = _private_root(private_root)
    selected = _selected_rows(_input_file(rows), split)
    manifest = _read_model(_input_file(arm_manifest_identity), ArtifactIdentity)
    if manifest.artifact_type != "jsonl" or manifest.version != _ROW_SEQUENCE_VERSION:
        raise CliContractError("arm manifest identity has wrong type")
    runtime = _read_model(_input_file(runtime_identity), ArtifactIdentity)
    model_path = _input_file(_beneath(model_inventory, root))
    dependency_path = _input_file(_beneath(dependency_inventory, root))
    models, model_identity = _read_inventory(model_path)
    dependencies, dependency_identity = _read_inventory(dependency_path)
    _validate_mode_model_inventory(mode, models)
    _union_inventory(models, dependencies)
    cache = _new_directory(cache_root, root)
    combined_output = _new_file(inventory_output, root)
    spec_output = _new_file(output, root)
    if any(
        _paths_overlap(first, second)
        for first, second in (
            (combined_output, spec_output),
            (combined_output, cache),
            (spec_output, cache),
        )
    ):
        raise CliContractError("run specification outputs overlap")
    if mode == "accepted-baseline":
        experiment_id = "accepted-baseline"
        config_id = "accepted-anchor"
        basis: Literal["end-to-end-method", "materialized-adapter"] = "materialized-adapter"
    else:
        experiment_id = mode
        config_id = _page_factory_config(mode)
        basis = "end-to-end-method"
    spec = ResourceSpec(
        experiment_id=experiment_id,
        config_id=config_id,
        row_sequence_identity=_records_identity(selected, artifact_type="frozen-row-sequence"),
        expected_row_count=len(selected),
        split=split,
        cache_policy="new-empty-v1",
        resource_basis=basis,
        worker_count=1,
        runtime_identity=runtime,
        arm_manifest_identity=manifest,
        private_root=root,
        model_inventory_path=model_path,
        model_inventory_identity=model_identity,
        dependency_inventory_path=dependency_path,
        dependency_inventory_identity=dependency_identity,
        cache_root=cache,
        resource_inventory_output=combined_output,
    )
    _write_model(spec_output, spec)


@app.command("prepare-run-spec")
def prepare_run_spec_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    rows: Annotated[Path, typer.Option("--rows")],
    split: Annotated[str, typer.Option("--split")],
    mode: Annotated[str, typer.Option("--mode")],
    arm_manifest_identity: Annotated[Path, typer.Option("--arm-manifest-identity")],
    runtime_identity: Annotated[Path, typer.Option("--runtime-identity")],
    model_inventory: Annotated[Path, typer.Option("--model-inventory")],
    dependency_inventory: Annotated[Path, typer.Option("--dependency-inventory")],
    cache_root: Annotated[Path, typer.Option("--cache-root")],
    inventory_output: Annotated[Path, typer.Option("--inventory-output")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Write one identity-bound static measured-run specification."""

    _run_safely(
        "ROW_CLI_RUN_SPEC_ERROR",
        lambda: _prepare_run_spec(
            private_root=private_root,
            rows=rows,
            split=_split(split, allow_test=False),
            mode=_mode(mode),
            arm_manifest_identity=arm_manifest_identity,
            runtime_identity=runtime_identity,
            model_inventory=model_inventory,
            dependency_inventory=dependency_inventory,
            cache_root=cache_root,
            inventory_output=inventory_output,
            output=output,
        ),
    )


def _validate(private_root: Path, rows: Path, labels: Path, ocr_references: Path | None) -> None:
    _private_root(private_root)
    row_records = _read_records(_input_file(rows), FrozenRow)
    label_records = _read_records(_input_file(labels), GoldRow)
    references = (
        () if ocr_references is None else _read_records(_input_file(ocr_references), OcrReference)
    )
    summary = validate_annotations(row_records, label_records, references)
    typer.echo(_canonical_model_bytes(summary).decode("utf-8"), nl=False)


@app.command("validate")
def validate_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    rows: Annotated[Path, typer.Option("--rows")],
    labels: Annotated[Path, typer.Option("--labels")],
    ocr_references: Annotated[Path | None, typer.Option("--ocr-references")] = None,
) -> None:
    """Validate complete reviewed annotations and print aggregate counts only."""

    _run_safely(
        "ROW_CLI_VALIDATE_ERROR",
        lambda: _validate(private_root, rows, labels, ocr_references),
    )


def _run_baseline(
    *,
    private_root: Path,
    mode: _Mode,
    rows: Path,
    split: DatasetSplit,
    baseline_input: Path,
    baseline_identity: Path,
    resource_spec: Path,
    preparation: Path | None,
    predictions_output: Path,
    run_output: Path,
) -> None:
    root = _private_root(private_root)
    selected = _selected_rows(_input_file(rows), split)
    baseline_path = _input_file(baseline_input)
    manifest_identity = _read_model(_input_file(baseline_identity), ArtifactIdentity)
    _identity_matches(baseline_path, manifest_identity)
    spec = _read_model(_input_file(resource_spec), ResourceSpec)
    if spec.private_root.resolve(strict=True) != root or spec.split is not split:
        raise CliContractError("resource specification binding mismatch")
    model_inventory_path = _input_file(_beneath(spec.model_inventory_path, root))
    model_inventory, model_inventory_identity = _read_inventory(model_inventory_path)
    if model_inventory_identity != spec.model_inventory_identity:
        raise CliContractError("resource specification model inventory mismatch")
    _validate_mode_model_inventory(mode, model_inventory)
    predictions_path = _new_file(predictions_output, root)
    measurements_path = _new_file(run_output, root)
    cache_path = spec.cache_root.resolve(strict=False)
    publication_paths = (
        predictions_path,
        measurements_path,
        spec.resource_inventory_output.resolve(strict=False),
    )
    if len(set(publication_paths)) != len(publication_paths) or any(
        _paths_overlap(output, cache_path) for output in publication_paths
    ):
        raise CliContractError("run outputs overlap")
    if mode == "accepted-baseline":
        if preparation is not None:
            raise CliContractError("accepted baseline forbids preparation")
        predictions = _read_records(baseline_path, RowPrediction)
        complete_rows = _read_records(_input_file(rows), FrozenRow)
        complete_row_ids = tuple((row.document_id, row.row_id) for row in complete_rows)
        complete_prediction_ids = tuple(
            (prediction.document_id, prediction.row_id) for prediction in predictions
        )
        rows_by_identity = {(row.document_id, row.row_id): row for row in complete_rows}
        if (
            len(complete_row_ids) != len(set(complete_row_ids))
            or len(complete_prediction_ids) != len(set(complete_prediction_ids))
            or set(complete_row_ids) != set(complete_prediction_ids)
            or any(
                prediction.predicted_type
                is not rows_by_identity[(prediction.document_id, prediction.row_id)].baseline_type
                for prediction in predictions
            )
        ):
            raise CliContractError("complete accepted bundle identity mismatch")
        factory: MeasuredArmFactory = AcceptedBaselineArmFactory(
            selected,
            predictions,
            manifest_identity,
            row_sequence_identity=spec.row_sequence_identity,
            runtime_identity=spec.runtime_identity,
            model_inventory_identity=spec.model_inventory_identity,
            dependency_inventory_identity=spec.dependency_inventory_identity,
            cache_root=spec.cache_root,
        )
        preparation_record = None
    else:
        if preparation is None:
            raise CliContractError("page baseline requires preparation")
        pages = _read_records(baseline_path, PageEvidenceRecord)
        preparation_record = _read_model(_input_file(preparation), PreparationMeasurements)
        factory_type = (
            ConditionalPageOcrArmFactory
            if mode == "conditional-page-ocr"
            else ForcedPageOcrArmFactory
        )
        factory = factory_type(
            selected,
            pages,
            manifest_identity,
            row_sequence_identity=spec.row_sequence_identity,
            runtime_identity=spec.runtime_identity,
            model_inventory_identity=spec.model_inventory_identity,
            dependency_inventory_identity=spec.dependency_inventory_identity,
            cache_root=spec.cache_root,
        )
    sink = JsonlPredictionSink(predictions_path)
    measurements = run_arm(
        selected,
        factory,
        sink,
        spec,
        preparation_record,
    )
    owned_inventory: tuple[int, int] | None = None
    try:
        owned_inventory = _owned_inventory_output(
            spec.resource_inventory_output,
            measurements.resource_inventory_identity,
        )
        _write_model(measurements_path, measurements)
    except BaseException:
        with suppress(BaseException):
            sink.abort()
        if owned_inventory is not None:
            _unlink_owned_output(spec.resource_inventory_output, owned_inventory)
        raise


@app.command("run-baseline")
def run_baseline_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    mode: Annotated[str, typer.Option("--mode")],
    rows: Annotated[Path, typer.Option("--rows")],
    split: Annotated[str, typer.Option("--split")],
    baseline_input: Annotated[Path, typer.Option("--baseline-input")],
    baseline_identity: Annotated[Path, typer.Option("--baseline-identity")],
    resource_spec: Annotated[Path, typer.Option("--resource-spec")],
    predictions_output: Annotated[Path, typer.Option("--predictions-output")],
    run_output: Annotated[Path, typer.Option("--run-output")],
    preparation: Annotated[Path | None, typer.Option("--preparation")] = None,
) -> None:
    """Execute one identity-bound measured shared baseline."""

    _run_safely(
        "ROW_CLI_RUN_BASELINE_ERROR",
        lambda: _run_baseline(
            private_root=private_root,
            mode=_mode(mode),
            rows=rows,
            split=_split(split, allow_test=False),
            baseline_input=baseline_input,
            baseline_identity=baseline_identity,
            resource_spec=resource_spec,
            preparation=preparation,
            predictions_output=predictions_output,
            run_output=run_output,
        ),
    )


def _score(
    *,
    private_root: Path,
    rows: Path,
    labels: Path,
    predictions: Path,
    ocr_references: Path | None,
    context: Path,
    run: Path,
    output: Path,
) -> None:
    root = _private_root(private_root)
    report_path = _new_file(output, root)
    all_rows = _read_records(_input_file(rows), FrozenRow)
    all_labels = _read_records(_input_file(labels), GoldRow)
    references = (
        () if ocr_references is None else _read_records(_input_file(ocr_references), OcrReference)
    )
    validate_annotations(all_rows, all_labels, references)
    run_record = _read_model(_input_file(run), RunMeasurements)
    context_record = _read_model(_input_file(context), ReportContext)
    selected = tuple(row for row in all_rows if row.split is run_record.split)
    selected_ids = {(row.document_id, row.row_id) for row in selected}
    selected_labels = tuple(
        label for label in all_labels if (label.document_id, label.row_id) in selected_ids
    )
    selected_references = tuple(
        reference
        for reference in references
        if (reference.document_id, reference.row_id) in selected_ids
    )
    prediction_path = _input_file(predictions)
    prediction_records = _read_records(prediction_path, RowPrediction)
    prediction_identity = _stream_identity(prediction_path)
    if (
        prediction_identity.sha256 != run_record.predictions_sha256
        or _records_identity(selected, artifact_type="frozen-row-sequence")
        != run_record.row_sequence_identity
        or len(selected) != run_record.row_count
        or any(
            prediction.experiment_id != run_record.experiment_id
            or prediction.config_id != run_record.config_id
            for prediction in prediction_records
        )
    ):
        raise CliContractError("score run binding mismatch")
    metrics = score_predictions(
        selected,
        selected_labels,
        prediction_records,
        selected_references,
    )
    report = privacy_safe_report(metrics, run_record, context_record)
    payload = _canonical_json_value_content(report) + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=report_path.parent,
            prefix=f".{report_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as destination:
            temporary = Path(destination.name)
            destination.write(payload)
        temporary.replace(report_path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


@app.command("score")
def score_command(
    private_root: Annotated[Path, typer.Option("--private-root")],
    rows: Annotated[Path, typer.Option("--rows")],
    labels: Annotated[Path, typer.Option("--labels")],
    predictions: Annotated[Path, typer.Option("--predictions")],
    context: Annotated[Path, typer.Option("--context")],
    run: Annotated[Path, typer.Option("--run")],
    output: Annotated[Path, typer.Option("--output")],
    ocr_references: Annotated[Path | None, typer.Option("--ocr-references")] = None,
) -> None:
    """Score one measured run and write only its aggregate report."""

    _run_safely(
        "ROW_CLI_SCORE_ERROR",
        lambda: _score(
            private_root=private_root,
            rows=rows,
            labels=labels,
            predictions=predictions,
            ocr_references=ocr_references,
            context=context,
            run=run,
            output=output,
        ),
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()


__all__ = ["app", "assert_repeated_output", "main"]
