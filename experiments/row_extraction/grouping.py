"""Content-neutral structure profiles and reviewed document partition freezing."""

from __future__ import annotations

import hashlib
import itertools
import math
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self, cast

import fitz  # type: ignore[import-untyped]
from pydantic import ConfigDict, Field, model_validator

from ccparser.models import StatementResult, TableRegionSummary
from ccparser.output import _canonical_json_value_content
from ccparser.parser import parse_statement
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    DatasetSplit,
    _FrozenModel,
)
from experiments.row_extraction.split import DocumentGroup, SplitManifest, assign_splits

_GRID_SIZE = 64
_PROFILE_VERSION: Literal["row-structure-profile-v1"] = "row-structure-profile-v1"
_REVIEW_VERSION: Literal["reviewed-row-grouping-v1"] = "reviewed-row-grouping-v1"
type GridBBox = tuple[int, int, int, int]
type GridBand = tuple[int, int]
type RelationKind = Literal["duplicate", "layout"]


class GroupingContractError(ValueError):
    """Structure evidence cannot be frozen into leakage-safe partitions."""


class _PrivateModel(_FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def _canonical_payload(value: object) -> bytes:
    return _canonical_json_value_content(value)


def _payload_digest(value: object) -> str:
    return hashlib.sha256(_canonical_payload(value)).hexdigest()


def _records_identity(records: Sequence[_PrivateModel]) -> ArtifactIdentity:
    digest = hashlib.sha256()
    byte_size = 0
    for record in records:
        content = _canonical_payload(record.model_dump(mode="json")) + b"\n"
        digest.update(content)
        byte_size += len(content)
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=digest.hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=byte_size,
    )


def _valid_grid_bbox(value: GridBBox) -> bool:
    x0, y0, x1, y1 = value
    return 0 <= x0 < x1 <= _GRID_SIZE and 0 <= y0 < y1 <= _GRID_SIZE


class RegionSkeleton(_PrivateModel):
    bbox: GridBBox
    header: GridBBox
    column_edges: tuple[int, ...] = Field(min_length=2)
    row_bands: tuple[GridBand, ...]

    @model_validator(mode="after")
    def canonical_geometry(self) -> Self:
        if not _valid_grid_bbox(self.bbox) or not _valid_grid_bbox(self.header):
            raise ValueError("region grid bbox is invalid")
        if self.column_edges != tuple(sorted(set(self.column_edges))) or any(
            value < 0 or value > _GRID_SIZE for value in self.column_edges
        ):
            raise ValueError("column edges must be canonical")
        if self.row_bands != tuple(sorted(set(self.row_bands))) or any(
            not 0 <= start < end <= _GRID_SIZE for start, end in self.row_bands
        ):
            raise ValueError("row bands must be canonical")
        return self


def _region_sort_key(
    region: RegionSkeleton,
) -> tuple[GridBBox, GridBBox, tuple[int, ...], tuple[GridBand, ...]]:
    return region.bbox, region.header, region.column_edges, region.row_bands


class PageSkeleton(_PrivateModel):
    page_number: int = Field(gt=0)
    size_points: tuple[int, int]
    requires_ocr: bool
    image_area_bucket: int = Field(ge=0, le=3)
    image_boxes: tuple[GridBBox, ...]
    vector_rule_boxes: tuple[GridBBox, ...]
    regions: tuple[RegionSkeleton, ...]

    @model_validator(mode="after")
    def canonical_geometry(self) -> Self:
        if any(value <= 0 for value in self.size_points):
            raise ValueError("page size must be positive")
        for label, values in (
            ("image boxes", self.image_boxes),
            ("vector rule boxes", self.vector_rule_boxes),
        ):
            if values != tuple(sorted(set(values))) or any(
                not _valid_grid_bbox(value) for value in values
            ):
                raise ValueError(f"{label} must be canonical")
        if self.regions != tuple(sorted(self.regions, key=_region_sort_key)):
            raise ValueError("regions must be canonical")
        return self


def _duplicate_payload(pages: Sequence[PageSkeleton]) -> object:
    return {
        "version": _PROFILE_VERSION,
        "pages": tuple(page.model_dump(mode="json") for page in pages),
    }


def _layout_payload(pages: Sequence[PageSkeleton]) -> object:
    page_span = "single" if len(pages) == 1 else "multi"
    return {
        "version": _PROFILE_VERSION,
        "page_span": page_span,
        "pages": tuple(
            {
                "aspect": _aspect_grid(page.size_points),
                "regions": tuple(
                    {
                        "bbox": region.bbox,
                        "header": region.header,
                        "column_edges": region.column_edges,
                    }
                    for region in page.regions
                ),
            }
            for page in pages
        ),
    }


class DocumentStructureProfile(_PrivateModel):
    version: Literal["row-structure-profile-v1"]
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[PageSkeleton, ...] = Field(min_length=1)
    duplicate_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    layout_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def self_authenticating_profile(self) -> Self:
        expected_numbers = tuple(range(1, len(self.pages) + 1))
        if tuple(page.page_number for page in self.pages) != expected_numbers:
            raise ValueError("profile pages must be canonical and contiguous")
        if self.duplicate_fingerprint != _payload_digest(_duplicate_payload(self.pages)):
            raise ValueError("duplicate fingerprint does not match geometry")
        if self.layout_fingerprint != _payload_digest(_layout_payload(self.pages)):
            raise ValueError("layout fingerprint does not match geometry")
        return self


def structure_profile(
    *, document_id: str, pages: Sequence[PageSkeleton]
) -> DocumentStructureProfile:
    """Build a self-authenticating profile from already content-neutral geometry."""

    canonical_pages = tuple(sorted(pages, key=lambda page: page.page_number))
    return DocumentStructureProfile(
        version=_PROFILE_VERSION,
        document_id=document_id,
        pages=canonical_pages,
        duplicate_fingerprint=_payload_digest(_duplicate_payload(canonical_pages)),
        layout_fingerprint=_payload_digest(_layout_payload(canonical_pages)),
    )


class CandidateRelation(_PrivateModel):
    kind: RelationKind
    left_document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_pair(self) -> Self:
        if self.left_document_id >= self.right_document_id:
            raise ValueError("candidate document pair must be canonical")
        return self


def candidate_relations(
    profiles: Sequence[DocumentStructureProfile],
) -> tuple[CandidateRelation, ...]:
    """Propose only pairs with exact content-neutral structural fingerprints."""

    ledger: dict[str, DocumentStructureProfile] = {}
    for profile in profiles:
        validated = DocumentStructureProfile.model_validate(profile.model_dump(mode="python"))
        if validated.document_id in ledger:
            raise GroupingContractError("document profile must be unique")
        ledger[validated.document_id] = validated
    proposals: list[CandidateRelation] = []
    for kind in ("duplicate", "layout"):
        by_fingerprint: dict[str, list[str]] = {}
        for document_id, profile in ledger.items():
            fingerprint = (
                profile.duplicate_fingerprint if kind == "duplicate" else profile.layout_fingerprint
            )
            by_fingerprint.setdefault(fingerprint, []).append(document_id)
        for fingerprint, document_ids in by_fingerprint.items():
            for left, right in itertools.combinations(sorted(document_ids), 2):
                proposals.append(
                    CandidateRelation(
                        kind=kind,
                        left_document_id=left,
                        right_document_id=right,
                        fingerprint=fingerprint,
                    )
                )
    return tuple(
        sorted(
            proposals,
            key=lambda item: (
                0 if item.kind == "duplicate" else 1,
                item.left_document_id,
                item.right_document_id,
            ),
        )
    )


def _partition_id(document_ids: Sequence[str]) -> str:
    return _payload_digest({"documents": tuple(document_ids)})


class ReviewedPartition(_PrivateModel):
    partition_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_partition(self) -> Self:
        if self.document_ids != tuple(sorted(set(self.document_ids))) or any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.document_ids
        ):
            raise ValueError("reviewed document IDs must be canonical")
        if self.partition_id != _partition_id(self.document_ids):
            raise ValueError("reviewed partition identity mismatch")
        return self

    @classmethod
    def from_documents(cls, document_ids: Iterable[str]) -> ReviewedPartition:
        canonical = tuple(sorted(set(document_ids)))
        return cls(partition_id=_partition_id(canonical), document_ids=canonical)


class ReviewerAttestation(_PrivateModel):
    reviewer_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def grouping_review_digest(
    profile_identity: ArtifactIdentity,
    proposal_identity: ArtifactIdentity,
    duplicate_partitions: Sequence[ReviewedPartition],
    layout_partitions: Sequence[ReviewedPartition],
) -> str:
    """Bind both independent reviews to the same complete partition decision."""

    return _payload_digest(
        {
            "version": _REVIEW_VERSION,
            "profile_identity": profile_identity.model_dump(mode="json"),
            "proposal_identity": proposal_identity.model_dump(mode="json"),
            "duplicate_partitions": tuple(
                item.model_dump(mode="json") for item in duplicate_partitions
            ),
            "layout_partitions": tuple(item.model_dump(mode="json") for item in layout_partitions),
        }
    )


def _partition_universe(partitions: Sequence[ReviewedPartition]) -> tuple[str, ...]:
    documents = tuple(value for partition in partitions for value in partition.document_ids)
    if len(documents) != len(set(documents)):
        raise ValueError("reviewed partitions must be disjoint")
    return tuple(sorted(documents))


class ReviewedGrouping(_PrivateModel):
    version: Literal["reviewed-row-grouping-v1"]
    profile_identity: ArtifactIdentity
    proposal_identity: ArtifactIdentity
    duplicate_partitions: tuple[ReviewedPartition, ...] = Field(min_length=1)
    layout_partitions: tuple[ReviewedPartition, ...] = Field(min_length=1)
    reviewer_attestations: tuple[ReviewerAttestation, ...]

    @model_validator(mode="after")
    def complete_independent_review(self) -> Self:
        for partitions in (self.duplicate_partitions, self.layout_partitions):
            if partitions != tuple(sorted(partitions, key=lambda item: item.document_ids)):
                raise ValueError("reviewed partitions must be canonical")
        if _partition_universe(self.duplicate_partitions) != _partition_universe(
            self.layout_partitions
        ):
            raise ValueError("reviewed partitions must cover the same document universe")
        if len(self.reviewer_attestations) != 2:
            raise ValueError("review requires exactly two attestations")
        reviewer_ids = tuple(item.reviewer_id for item in self.reviewer_attestations)
        if len(set(reviewer_ids)) != 2:
            raise ValueError("review attestations must be independent")
        if reviewer_ids != tuple(sorted(reviewer_ids)):
            raise ValueError("review attestations must be canonical")
        expected = grouping_review_digest(
            self.profile_identity,
            self.proposal_identity,
            self.duplicate_partitions,
            self.layout_partitions,
        )
        if any(item.reviewed_sha256 != expected for item in self.reviewer_attestations):
            raise ValueError("review digest mismatch")
        return self


def _partition_map(
    partitions: Sequence[ReviewedPartition],
) -> dict[str, ReviewedPartition]:
    return {
        document_id: partition for partition in partitions for document_id in partition.document_ids
    }


def _stratum(profile: DocumentStructureProfile) -> str:
    modalities = {page.requires_ocr for page in profile.pages}
    modality = "mixed" if len(modalities) > 1 else "ocr" if True in modalities else "digital"
    page_span = "single" if len(profile.pages) == 1 else "multi"
    return f"{modality}:{page_span}"


def _component_id(kind: RelationKind, partition: ReviewedPartition) -> str:
    return _payload_digest({"kind": kind, "partition": partition.partition_id})


def freeze_grouping(
    profiles: Sequence[DocumentStructureProfile],
    proposals: Sequence[CandidateRelation],
    reviewed: ReviewedGrouping,
    *,
    profile_identity: ArtifactIdentity,
    proposal_identity: ArtifactIdentity,
    seed: str,
) -> tuple[tuple[DocumentGroup, ...], SplitManifest]:
    """Validate two-review decisions, emit groups, and assign the frozen split."""

    try:
        canonical_profiles = tuple(
            sorted(
                (
                    DocumentStructureProfile.model_validate(item.model_dump(mode="python"))
                    for item in profiles
                ),
                key=lambda item: item.document_id,
            )
        )
        canonical_proposals = tuple(
            sorted(
                (
                    CandidateRelation.model_validate(item.model_dump(mode="python"))
                    for item in proposals
                ),
                key=lambda item: (
                    0 if item.kind == "duplicate" else 1,
                    item.left_document_id,
                    item.right_document_id,
                ),
            )
        )
        reviewed = ReviewedGrouping.model_validate(reviewed.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError):
        raise GroupingContractError("invalid grouping input") from None
    if reviewed.profile_identity != profile_identity:
        raise GroupingContractError("profile identity mismatch")
    if reviewed.proposal_identity != proposal_identity:
        raise GroupingContractError("proposal identity mismatch")
    if profile_identity != _records_identity(canonical_profiles):
        raise GroupingContractError("profile content identity mismatch")
    if proposal_identity != _records_identity(canonical_proposals):
        raise GroupingContractError("proposal content identity mismatch")
    documents = tuple(item.document_id for item in canonical_profiles)
    if len(documents) != len(set(documents)) or not documents:
        raise GroupingContractError("document profiles must form a nonempty unique universe")
    if _partition_universe(reviewed.duplicate_partitions) != documents:
        raise GroupingContractError("reviewed grouping universe mismatch")
    if canonical_proposals != candidate_relations(canonical_profiles):
        raise GroupingContractError("candidate proposals do not match exact fingerprints")

    duplicate_map = _partition_map(reviewed.duplicate_partitions)
    layout_map = _partition_map(reviewed.layout_partitions)
    groups = tuple(
        DocumentGroup(
            document_ids=frozenset({profile.document_id}),
            duplicate_group=_component_id("duplicate", duplicate_map[profile.document_id]),
            layout_group=_component_id("layout", layout_map[profile.document_id]),
            stratum=_stratum(profile),
        )
        for profile in canonical_profiles
    )
    try:
        manifest = assign_splits(groups, seed=seed)
    except ValueError:
        raise GroupingContractError("split assignment failed") from None
    if {membership.split for membership in manifest.memberships} != set(DatasetSplit):
        raise GroupingContractError("every split must contain at least one document")
    return groups, manifest


def _aspect_grid(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    denominator = max(width, height)
    return (
        max(1, round(width * _GRID_SIZE / denominator)),
        max(1, round(height * _GRID_SIZE / denominator)),
    )


def _grid_bbox(bbox: BBox, page_bbox: BBox) -> GridBBox:
    px0, py0, px1, py1 = page_bbox
    width = px1 - px0
    height = py1 - py0
    if width <= 0 or height <= 0 or any(not math.isfinite(value) for value in bbox):
        raise GroupingContractError("invalid structure geometry")
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        raise GroupingContractError("invalid structure geometry")

    def lower(value: float, origin: float, extent: float) -> int:
        return max(0, min(_GRID_SIZE - 1, math.floor((value - origin) * _GRID_SIZE / extent)))

    def upper(value: float, origin: float, extent: float) -> int:
        return max(1, min(_GRID_SIZE, math.ceil((value - origin) * _GRID_SIZE / extent)))

    result = (
        lower(x0, px0, width),
        lower(y0, py0, height),
        upper(x1, px0, width),
        upper(y1, py0, height),
    )
    if not _valid_grid_bbox(result):
        raise GroupingContractError("invalid quantized structure geometry")
    return result


def _region_skeleton(region: TableRegionSummary, page_bbox: BBox) -> RegionSkeleton:
    edges = tuple(
        sorted(
            {
                value
                for column in region.table_schema.columns
                for value in (
                    _grid_bbox(column.bbox, page_bbox)[0],
                    _grid_bbox(column.bbox, page_bbox)[2],
                )
            }
        )
    )
    if len(edges) < 2:
        region_box = _grid_bbox(region.bbox, page_bbox)
        edges = (region_box[0], region_box[2])
    bands = tuple(
        sorted(
            {
                (_grid_bbox(row.bbox, page_bbox)[1], _grid_bbox(row.bbox, page_bbox)[3])
                for row in region.rows
            }
        )
    )
    return RegionSkeleton(
        bbox=_grid_bbox(region.bbox, page_bbox),
        header=_grid_bbox(region.header.bbox, page_bbox),
        column_edges=edges,
        row_bands=bands,
    )


def _rect_tuple(value: object) -> BBox:
    rect = fitz.Rect(value)
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _page_image_boxes(page: fitz.Page, page_bbox: BBox) -> tuple[GridBBox, ...]:
    boxes: set[GridBBox] = set()
    for item in cast(
        Sequence[Mapping[str, object]], page.get_image_info(hashes=False, xrefs=False)
    ):
        bbox = item.get("bbox")
        if bbox is not None:
            boxes.add(_grid_bbox(_rect_tuple(bbox), page_bbox))
    return tuple(sorted(boxes))


def _page_rule_boxes(page: fitz.Page, page_bbox: BBox) -> tuple[GridBBox, ...]:
    boxes: set[GridBBox] = set()
    for item in cast(Sequence[Mapping[str, object]], page.get_drawings()):
        rect = item.get("rect")
        if rect is None:
            continue
        bbox = _rect_tuple(rect)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        boxes.add(_grid_bbox(bbox, page_bbox))
    return tuple(sorted(boxes))


def image_area_bucket(boxes: Sequence[GridBBox]) -> int:
    if any(not _valid_grid_bbox(box) for box in boxes):
        raise GroupingContractError("image area geometry is invalid")
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
    if area == 0:
        return 0
    normalized = min(_GRID_SIZE * _GRID_SIZE, area)
    if normalized <= (_GRID_SIZE * _GRID_SIZE) // 4:
        return 1
    if normalized <= 3 * (_GRID_SIZE * _GRID_SIZE) // 4:
        return 2
    return 3


def profile_atlas(
    profiles: Sequence[DocumentStructureProfile],
) -> tuple[bytes, ArtifactIdentity]:
    """Render a deterministic SVG containing geometry and no source values."""

    try:
        canonical = tuple(
            sorted(
                (
                    DocumentStructureProfile.model_validate(item.model_dump(mode="python"))
                    for item in profiles
                ),
                key=lambda item: item.document_id,
            )
        )
    except (AttributeError, TypeError, ValueError):
        raise GroupingContractError("invalid atlas profile") from None
    document_ids = tuple(item.document_id for item in canonical)
    if not canonical or len(document_ids) != len(set(document_ids)):
        raise GroupingContractError("atlas profiles must be nonempty and unique")
    pages = tuple(page for profile in canonical for page in profile.pages)
    columns = min(4, len(pages))
    rows = math.ceil(len(pages) / columns)
    tile = 80
    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{columns * tile}" '
            f'height="{rows * tile}" viewBox="0 0 {columns * tile} {rows * tile}">'
        ),
        '<g fill="none" stroke-width="0.8">',
    ]
    for index, page in enumerate(pages):
        offset_x = (index % columns) * tile + 8
        offset_y = (index // columns) * tile + 8
        aspect_x, aspect_y = _aspect_grid(page.size_points)
        scale_x = aspect_x / _GRID_SIZE
        scale_y = aspect_y / _GRID_SIZE
        elements.append(
            f'<g transform="translate({offset_x} {offset_y}) scale({scale_x:.6f} {scale_y:.6f})">'
        )
        elements.append('<rect x="0" y="0" width="64" height="64" stroke="#111"/>')
        for x0, y0, x1, y1 in page.image_boxes:
            elements.append(
                f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
                'stroke="#777" stroke-dasharray="2 1"/>'
            )
        for x0, y0, x1, y1 in page.vector_rule_boxes:
            elements.append(
                f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" stroke="#aaa"/>'
            )
        for region in page.regions:
            x0, y0, x1, y1 = region.bbox
            elements.append(
                f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" stroke="#005bbb"/>'
            )
            hx0, hy0, hx1, hy1 = region.header
            elements.append(
                f'<rect x="{hx0}" y="{hy0}" width="{hx1 - hx0}" height="{hy1 - hy0}" '
                'stroke="#ff8c00"/>'
            )
            for edge in region.column_edges:
                elements.append(
                    f'<line x1="{edge}" y1="{y0}" x2="{edge}" y2="{y1}" stroke="#00843d"/>'
                )
            for start, end in region.row_bands:
                elements.append(
                    f'<rect x="{x0}" y="{start}" width="{x1 - x0}" height="{end - start}" '
                    'stroke="#c8102e"/>'
                )
        elements.append("</g>")
    elements.extend(("</g>", "</svg>"))
    content = "".join(elements).encode("ascii")
    return content, ArtifactIdentity(
        artifact_type="row-structure-atlas",
        sha256=hashlib.sha256(content).hexdigest(),
        version="geometry-svg-v1",
        byte_size=len(content),
    )


def _page_requires_ocr(regions: Sequence[TableRegionSummary]) -> bool:
    sources = tuple(
        word.source
        for region in regions
        for row in (region.header, *region.rows)
        for word in (*row.words, *(word for cell in row.cells for word in cell.words))
    )
    return bool(sources) and any(source == "ocr" for source in sources)


def profile_statement_geometry(source: Path, result: StatementResult) -> DocumentStructureProfile:
    """Project only PDF and discovery geometry; never retain semantic parser fields."""

    initial = _source_snapshot(source)
    if result.source_sha256 is None or result.discovery is None:
        raise GroupingContractError("accepted discovery geometry is unavailable")
    if result.source_sha256 != initial.sha256:
        raise GroupingContractError("document identity changed during profiling")
    try:
        with fitz.open(source) as document:
            regions_by_page: dict[int, list[TableRegionSummary]] = {
                page_number: [] for page_number in range(1, document.page_count + 1)
            }
            for region in result.discovery.table_regions:
                if region.page_number not in regions_by_page:
                    raise GroupingContractError("discovery region page is unavailable")
                regions_by_page[region.page_number].append(region)
            pages: list[PageSkeleton] = []
            for page_number, page in enumerate(document, start=1):
                page_bbox = _rect_tuple(page.rect)
                image_boxes = _page_image_boxes(page, page_bbox)
                page_regions = tuple(
                    sorted(regions_by_page[page_number], key=lambda item: item.bbox)
                )
                region_skeletons = tuple(
                    sorted(
                        (_region_skeleton(region, page_bbox) for region in page_regions),
                        key=_region_sort_key,
                    )
                )
                pages.append(
                    PageSkeleton(
                        page_number=page_number,
                        size_points=(round(page.rect.width), round(page.rect.height)),
                        requires_ocr=_page_requires_ocr(page_regions),
                        image_area_bucket=image_area_bucket(image_boxes),
                        image_boxes=image_boxes,
                        vector_rule_boxes=_page_rule_boxes(page, page_bbox),
                        regions=region_skeletons,
                    )
                )
    except GroupingContractError:
        raise
    except Exception:
        raise GroupingContractError("document structure cannot be inspected") from None
    if _source_snapshot(source) != initial:
        raise GroupingContractError("source changed during profiling")
    return structure_profile(document_id=result.source_sha256, pages=pages)


class _StatementParser(Protocol):
    def __call__(
        self,
        path: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult: ...


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    device: int
    inode: int
    mode: int
    byte_size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


def _source_snapshot(path: Path) -> _SourceSnapshot:
    before = path.stat(follow_symlinks=False)
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise GroupingContractError("source is not a stable regular file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    after = path.stat(follow_symlinks=False)
    before_values = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_values = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_values != after_values:
        raise GroupingContractError("source changed during profiling")
    return _SourceSnapshot(*after_values, sha256=digest.hexdigest())


def profile_documents(
    sources: Iterable[Path],
    cache_root: Path,
    *,
    parser: _StatementParser = parse_statement,
) -> tuple[DocumentStructureProfile, ...]:
    """Profile a corpus in content-identity order with private per-document caches."""

    by_identity: dict[str, list[tuple[Path, _SourceSnapshot]]] = {}
    try:
        for source in sources:
            snapshot = _source_snapshot(source)
            by_identity.setdefault(snapshot.sha256, []).append((source, snapshot))
    except OSError:
        raise GroupingContractError("document corpus cannot be inspected") from None
    if not by_identity:
        raise GroupingContractError("document corpus is empty")
    source_ledger = tuple(alias for aliases in by_identity.values() for alias in aliases)

    def verify_aliases(aliases: Sequence[tuple[Path, _SourceSnapshot]]) -> None:
        if any(_source_snapshot(path) != expected for path, expected in aliases):
            raise GroupingContractError("source changed during profiling")

    profiles: list[DocumentStructureProfile] = []
    for document_id in sorted(by_identity):
        aliases = tuple(by_identity[document_id])
        source, _initial = aliases[0]
        verify_aliases(aliases)
        result = parser(source, cache_dir=cache_root / document_id)
        verify_aliases(aliases)
        if result.source_sha256 != document_id:
            raise GroupingContractError("document identity changed during profiling")
        profiles.append(profile_statement_geometry(source, result))
        verify_aliases(aliases)
    verify_aliases(source_ledger)
    return tuple(profiles)


__all__ = [
    "CandidateRelation",
    "DocumentStructureProfile",
    "GroupingContractError",
    "PageSkeleton",
    "RegionSkeleton",
    "ReviewedGrouping",
    "ReviewedPartition",
    "ReviewerAttestation",
    "candidate_relations",
    "freeze_grouping",
    "grouping_review_digest",
    "image_area_bucket",
    "profile_atlas",
    "profile_documents",
    "profile_statement_geometry",
    "structure_profile",
]
