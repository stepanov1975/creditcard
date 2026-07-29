from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import fitz  # type: ignore[import-untyped]
import pytest
from pydantic import BaseModel, ValidationError

from ccparser.models import (
    DiscoveryRowSummary,
    DiscoveryTableSchemaSummary,
    StatementDiscoverySummary,
    StatementResult,
    Status,
    TableRegionSummary,
)
from experiments.row_extraction.codecs import _canonical_record_bytes
from experiments.row_extraction.contracts import ArtifactIdentity, DatasetSplit
from experiments.row_extraction.grouping import (
    CandidateRelation,
    DocumentStructureProfile,
    GroupingContractError,
    PageSkeleton,
    RegionSkeleton,
    ReviewedGrouping,
    ReviewedPartition,
    ReviewerAttestation,
    _page_image_boxes,
    candidate_relations,
    freeze_grouping,
    grouping_review_digest,
    image_area_bucket,
    profile_atlas,
    profile_documents,
    profile_statement_geometry,
    structure_profile,
)


def _document(index: int) -> str:
    return f"{index:064x}"


def _identity(value: str) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=value * 64,
        version="canonical-jsonl-v1",
        byte_size=1,
    )


def _records_identity(records: tuple[BaseModel, ...]) -> ArtifactIdentity:
    content = b"".join(_canonical_record_bytes(record) for record in records)
    return ArtifactIdentity(
        artifact_type="jsonl",
        sha256=hashlib.sha256(content).hexdigest(),
        version="canonical-jsonl-v1",
        byte_size=len(content),
    )


def _region(*, rows: tuple[tuple[int, int], ...] = ((20, 24),)) -> RegionSkeleton:
    return RegionSkeleton(
        bbox=(2, 12, 62, 58),
        header=(2, 12, 62, 18),
        column_edges=(2, 13, 49, 62),
        row_bands=rows,
    )


def _page(
    *,
    requires_ocr: bool = False,
    rows: tuple[tuple[int, int], ...] = ((20, 24),),
) -> PageSkeleton:
    return PageSkeleton(
        page_number=1,
        size_points=(612, 792),
        requires_ocr=requires_ocr,
        image_area_bucket=0,
        image_boxes=(),
        vector_rule_boxes=((2, 11, 62, 12),),
        regions=(_region(rows=rows),),
    )


def _profile(
    index: int,
    *,
    requires_ocr: bool = False,
    rows: tuple[tuple[int, int], ...] = ((20, 24),),
) -> DocumentStructureProfile:
    return structure_profile(
        document_id=_document(index),
        pages=(_page(requires_ocr=requires_ocr, rows=rows),),
    )


def _profile_with_size(index: int) -> DocumentStructureProfile:
    page = _page().model_copy(update={"size_points": (300 + index * 20, 792)})
    return structure_profile(document_id=_document(index), pages=(page,))


def _partition(*documents: str) -> ReviewedPartition:
    return ReviewedPartition.from_documents(documents)


def _reviewed(
    profiles: tuple[DocumentStructureProfile, ...],
    *,
    profile_identity: ArtifactIdentity | None = None,
    proposal_identity: ArtifactIdentity | None = None,
    duplicate_partitions: tuple[ReviewedPartition, ...] | None = None,
    layout_partitions: tuple[ReviewedPartition, ...] | None = None,
) -> ReviewedGrouping:
    profile_id = profile_identity or _records_identity(profiles)
    proposal_id = proposal_identity or _records_identity(candidate_relations(profiles))
    documents = tuple(profile.document_id for profile in profiles)
    duplicate = tuple(
        sorted(
            duplicate_partitions or tuple(_partition(value) for value in documents),
            key=lambda item: item.document_ids,
        )
    )
    layout = tuple(
        sorted(
            layout_partitions or tuple(_partition(value) for value in documents),
            key=lambda item: item.document_ids,
        )
    )
    digest = grouping_review_digest(profile_id, proposal_id, duplicate, layout)
    return ReviewedGrouping(
        version="reviewed-row-grouping-v1",
        profile_identity=profile_id,
        proposal_identity=proposal_id,
        duplicate_partitions=duplicate,
        layout_partitions=layout,
        reviewer_attestations=(
            ReviewerAttestation(reviewer_id="1" * 64, reviewed_sha256=digest),
            ReviewerAttestation(reviewer_id="2" * 64, reviewed_sha256=digest),
        ),
    )


def test_structure_profile_is_content_neutral_and_fingerprints_geometry() -> None:
    profile = _profile(1)
    repeated = structure_profile(document_id=_document(1), pages=(_page(),))
    row_revision = _profile(2, rows=((20, 24), (26, 30)))

    assert profile == repeated
    assert profile.duplicate_fingerprint != row_revision.duplicate_fingerprint
    assert profile.layout_fingerprint == row_revision.layout_fingerprint
    serialized = json.dumps(profile.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "filename",
        "source_pdf",
        "metadata",
        "text",
        "font",
        "merchant",
        "amount",
        "date",
        "baseline_type",
        "split",
    ):
        assert forbidden not in serialized


def test_structure_profile_rejects_noncanonical_or_forged_geometry() -> None:
    profile = _profile(1)
    values = profile.model_dump(mode="python")
    values["duplicate_fingerprint"] = "f" * 64

    with pytest.raises(ValidationError, match="duplicate fingerprint"):
        DocumentStructureProfile.model_validate(values)

    with pytest.raises(ValidationError, match="canonical"):
        PageSkeleton(
            page_number=1,
            size_points=(612, 792),
            requires_ocr=False,
            image_area_bucket=0,
            image_boxes=((3, 3, 4, 4), (1, 1, 2, 2)),
            vector_rule_boxes=(),
            regions=(),
        )


def test_page_skeleton_requires_total_region_order_for_quantized_ties() -> None:
    first = _region(rows=((20, 24),))
    second = _region(rows=((26, 30),))
    canonical = tuple(
        sorted(
            (first, second),
            key=lambda region: (
                region.bbox,
                region.header,
                region.column_edges,
                region.row_bands,
            ),
        )
    )

    PageSkeleton(
        page_number=1,
        size_points=(612, 792),
        requires_ocr=False,
        image_area_bucket=0,
        image_boxes=(),
        vector_rule_boxes=(),
        regions=canonical,
    )

    with pytest.raises(ValidationError, match="regions must be canonical"):
        PageSkeleton(
            page_number=1,
            size_points=(612, 792),
            requires_ocr=False,
            image_area_bucket=0,
            image_boxes=(),
            vector_rule_boxes=(),
            regions=tuple(reversed(canonical)),
        )


def test_candidate_relations_are_exact_canonical_fingerprint_matches() -> None:
    first = _profile(1)
    second = _profile(2)
    layout_only = _profile(3, rows=((20, 24), (26, 30)))
    different = _profile(4, requires_ocr=True)

    proposals = candidate_relations((different, layout_only, second, first))

    assert first.layout_fingerprint == different.layout_fingerprint
    assert proposals == (
        CandidateRelation(
            kind="duplicate",
            left_document_id=_document(1),
            right_document_id=_document(2),
            fingerprint=first.duplicate_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(1),
            right_document_id=_document(2),
            fingerprint=first.layout_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(1),
            right_document_id=_document(3),
            fingerprint=first.layout_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(1),
            right_document_id=_document(4),
            fingerprint=first.layout_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(2),
            right_document_id=_document(3),
            fingerprint=first.layout_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(2),
            right_document_id=_document(4),
            fingerprint=first.layout_fingerprint,
        ),
        CandidateRelation(
            kind="layout",
            left_document_id=_document(3),
            right_document_id=_document(4),
            fingerprint=first.layout_fingerprint,
        ),
    )


def test_page_skeleton_rejects_fine_grained_image_area_bucket() -> None:
    values = _page().model_dump(mode="python")
    values["image_area_bucket"] = 4

    with pytest.raises(ValidationError, match="less than or equal to 3"):
        PageSkeleton.model_validate(values)


def test_page_image_boxes_ignore_zero_area_image_geometry() -> None:
    class ImagePage:
        def get_image_info(self, *, hashes: bool, xrefs: bool) -> tuple[dict[str, object], ...]:
            assert not hashes
            assert not xrefs
            return (
                {"bbox": (2.0, 2.0, 2.0, 4.0)},
                {"bbox": (3.0, 3.0, 5.0, 3.0)},
                {"bbox": (10.0, 10.0, 20.0, 20.0)},
            )

    boxes = _page_image_boxes(
        cast(fitz.Page, ImagePage()),
        (0.0, 0.0, 100.0, 100.0),
    )

    assert boxes == ((6, 6, 13, 13),)


@pytest.mark.parametrize(
    ("boxes", "expected"),
    (
        ((), 0),
        (((0, 0, 1, 1),), 1),
        (((0, 0, 16, 64),), 1),
        (((0, 0, 17, 64),), 2),
        (((0, 0, 48, 64),), 2),
        (((0, 0, 49, 64),), 3),
        (((0, 0, 64, 64),), 3),
    ),
)
def test_image_area_bucket_has_fixed_coarse_boundaries(
    boxes: tuple[tuple[int, int, int, int], ...], expected: int
) -> None:
    assert image_area_bucket(boxes) == expected


def test_profile_atlas_is_deterministic_geometry_only_svg() -> None:
    profiles = (_profile(2, requires_ocr=True), _profile(1))

    content, identity = profile_atlas(profiles)
    repeated, repeated_identity = profile_atlas(tuple(reversed(profiles)))

    assert content == repeated
    assert identity == repeated_identity
    assert content.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    assert b"<text" not in content
    assert identity.artifact_type == "row-structure-atlas"
    assert identity.version == "geometry-svg-v1"
    for forbidden in (
        b"secret",
        b"merchant",
        b"amount",
        b"filename",
        b"metadata",
        _document(1).encode(),
        profiles[0].layout_fingerprint.encode(),
    ):
        assert forbidden not in content


def test_reviewed_grouping_requires_two_independent_matching_attestations() -> None:
    profiles = (_profile(1), _profile(2))
    reviewed = _reviewed(profiles)
    values = reviewed.model_dump(mode="python")

    values["reviewer_attestations"] = (values["reviewer_attestations"][0],)
    with pytest.raises(ValidationError, match="exactly two"):
        ReviewedGrouping.model_validate(values)

    values = reviewed.model_dump(mode="python")
    values["reviewer_attestations"] = (
        values["reviewer_attestations"][0],
        values["reviewer_attestations"][0],
    )
    with pytest.raises(ValidationError, match="independent"):
        ReviewedGrouping.model_validate(values)

    values = reviewed.model_dump(mode="python")
    values["reviewer_attestations"][0]["reviewed_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="review digest"):
        ReviewedGrouping.model_validate(values)


def test_reviewed_grouping_requires_canonical_exact_partition_cover() -> None:
    profiles = (_profile(1), _profile(2))
    reviewed = _reviewed(profiles)
    values = reviewed.model_dump(mode="python")
    values["layout_partitions"] = (values["layout_partitions"][0],)

    with pytest.raises(ValidationError, match="same document universe"):
        ReviewedGrouping.model_validate(values)


def test_freeze_grouping_emits_one_group_per_document_and_split_deterministically() -> None:
    profiles = tuple(_profile_with_size(index) for index in range(1, 11))
    proposals = candidate_relations(profiles)
    duplicate = (
        _partition(_document(1), _document(2)),
        *(_partition(_document(index)) for index in range(3, 11)),
    )
    layout = (
        _partition(_document(2), _document(3)),
        *(_partition(_document(index)) for index in (1, *range(4, 11))),
    )
    reviewed = _reviewed(
        profiles,
        duplicate_partitions=duplicate,
        layout_partitions=layout,
    )

    groups, manifest = freeze_grouping(
        tuple(reversed(profiles)),
        tuple(reversed(proposals)),
        reviewed,
        profile_identity=reviewed.profile_identity,
        proposal_identity=reviewed.proposal_identity,
        seed="row-extraction-v1",
    )
    repeated_groups, repeated_manifest = freeze_grouping(
        profiles,
        proposals,
        reviewed,
        profile_identity=reviewed.profile_identity,
        proposal_identity=reviewed.proposal_identity,
        seed="row-extraction-v1",
    )

    assert groups == repeated_groups
    assert manifest == repeated_manifest
    assert len(groups) == len(profiles)
    assert all(len(group.document_ids) == 1 for group in groups)
    assert groups[0].stratum == "digital:single"
    assert manifest.split_for(_document(1)) is manifest.split_for(_document(3))
    assert {membership.split for membership in manifest.memberships} == {
        DatasetSplit.TRAIN,
        DatasetSplit.VALIDATION,
        DatasetSplit.TEST,
    }


def test_freeze_grouping_allows_two_review_rejection_of_exact_geometry_proposal() -> None:
    profiles = (
        _profile(1),
        _profile(2),
        *(_profile_with_size(index) for index in range(3, 11)),
    )
    proposals = candidate_relations(profiles)
    reviewed = _reviewed(profiles)

    groups, _manifest = freeze_grouping(
        profiles,
        proposals,
        reviewed,
        profile_identity=reviewed.profile_identity,
        proposal_identity=reviewed.proposal_identity,
        seed="seed",
    )

    assert groups[0].duplicate_group != groups[1].duplicate_group
    assert groups[0].layout_group != groups[1].layout_group


def test_freeze_grouping_rejects_profile_identity_mismatch() -> None:
    profiles = (_profile(1), _profile(2))
    proposals = candidate_relations(profiles)

    reviewed_together = _reviewed(
        profiles,
        duplicate_partitions=(_partition(_document(1), _document(2)),),
        layout_partitions=(_partition(_document(1), _document(2)),),
    )
    with pytest.raises(GroupingContractError, match="profile identity mismatch"):
        freeze_grouping(
            profiles,
            proposals,
            reviewed_together,
            profile_identity=_identity("c"),
            proposal_identity=reviewed_together.proposal_identity,
            seed="seed",
        )


def test_freeze_grouping_rejects_identity_that_does_not_hash_profile_content() -> None:
    profiles = (_profile(1), _profile(2))
    proposals = candidate_relations(profiles)
    forged_identity = _identity("a")
    reviewed = _reviewed(profiles, profile_identity=forged_identity)

    with pytest.raises(GroupingContractError, match="profile content identity mismatch"):
        freeze_grouping(
            profiles,
            proposals,
            reviewed,
            profile_identity=forged_identity,
            proposal_identity=reviewed.proposal_identity,
            seed="seed",
        )


def test_freeze_grouping_uses_modality_and_page_span_only_for_stratum() -> None:
    digital = _profile(1)
    ocr_pages = (
        _page(requires_ocr=True),
        _page(requires_ocr=True).model_copy(update={"page_number": 2}),
    )
    ocr = structure_profile(document_id=_document(2), pages=ocr_pages)
    hybrid = structure_profile(
        document_id=_document(3),
        pages=(
            _page(),
            _page(requires_ocr=True).model_copy(update={"page_number": 2}),
        ),
    )
    profiles = (
        digital,
        ocr,
        hybrid,
        *(_profile_with_size(index) for index in range(4, 11)),
    )
    reviewed = _reviewed(profiles)

    groups, _manifest = freeze_grouping(
        profiles,
        candidate_relations(profiles),
        reviewed,
        profile_identity=reviewed.profile_identity,
        proposal_identity=reviewed.proposal_identity,
        seed="seed",
    )

    assert {next(iter(group.document_ids)): group.stratum for group in groups} == {
        _document(1): "digital:single",
        _document(2): "ocr:multi",
        _document(3): "mixed:multi",
        **{_document(index): "digital:single" for index in range(4, 11)},
    }


def test_freeze_grouping_stops_when_reviewed_components_cannot_fill_every_split() -> None:
    profiles = tuple(_profile_with_size(index) for index in range(1, 11))
    documents = tuple(profile.document_id for profile in profiles)
    combined = (ReviewedPartition.from_documents(documents),)
    reviewed = _reviewed(
        profiles,
        duplicate_partitions=combined,
        layout_partitions=combined,
    )

    with pytest.raises(
        GroupingContractError,
        match="every split must contain at least one document",
    ):
        freeze_grouping(
            profiles,
            candidate_relations(profiles),
            reviewed,
            profile_identity=reviewed.profile_identity,
            proposal_identity=reviewed.proposal_identity,
            seed="seed",
        )


def test_grouping_models_do_not_accept_paths_or_semantic_extensions(tmp_path: Path) -> None:
    values = _profile(1).model_dump(mode="python")
    values["source_path"] = tmp_path / "private.pdf"

    with pytest.raises(ValidationError, match="Extra inputs"):
        DocumentStructureProfile.model_validate(values)


def _empty_discovery_result(source: Path) -> StatementResult:
    document_id = hashlib.sha256(source.read_bytes()).hexdigest()
    return StatementResult(
        status=Status.NOT_STATEMENT,
        transactions=(),
        groups=(),
        source_sha256=document_id,
        discovery=StatementDiscoverySummary(
            classification="synthetic",
            confidence=1.0,
        ),
    )


def _table_region(
    bbox: tuple[float, float, float, float],
    header_bbox: tuple[float, float, float, float],
) -> TableRegionSummary:
    header = DiscoveryRowSummary(
        page_number=1,
        bbox=header_bbox,
        cells=(),
        confidence=1.0,
    )
    return TableRegionSummary(
        page_number=1,
        bbox=bbox,
        header_evidence=(),
        column_roles=(),
        row_count=0,
        header=header,
        rows=(),
        table_schema=DiscoveryTableSchemaSummary(
            page_number=1,
            bbox=bbox,
            columns=(),
            header_cells=(),
            sample_cells=(),
            confidence=1.0,
        ),
        confidence=1.0,
    )


def test_profile_statement_geometry_uses_page_structure_without_semantic_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "secret-merchant-and-amount.pdf"
    with fitz.open() as document:
        document.new_page(width=320, height=480)
        document.save(source)
    result = _empty_discovery_result(source)

    profile = profile_statement_geometry(source, result)

    assert profile.document_id == result.source_sha256
    assert profile.pages[0].size_points == (320, 480)
    assert profile.pages[0].regions == ()
    assert "secret-merchant-and-amount" not in profile.model_dump_json()


def test_profile_statement_geometry_sorts_regions_after_grid_quantization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=640, height=640)
        document.save(source)
    document_id = hashlib.sha256(source.read_bytes()).hexdigest()
    raw_first_but_canonical_second = _table_region(
        (10.0, 10.0, 19.0, 110.0),
        (12.0, 50.0, 18.0, 60.0),
    )
    raw_second_but_canonical_first = _table_region(
        (11.0, 10.0, 18.0, 110.0),
        (12.0, 20.0, 18.0, 30.0),
    )
    result = StatementResult(
        status=Status.NOT_STATEMENT,
        transactions=(),
        groups=(),
        source_sha256=document_id,
        discovery=StatementDiscoverySummary(
            classification="synthetic",
            table_regions=(
                raw_first_but_canonical_second,
                raw_second_but_canonical_first,
            ),
            confidence=1.0,
        ),
    )

    profile = profile_statement_geometry(source, result)

    assert profile.pages[0].regions == tuple(
        sorted(profile.pages[0].regions, key=lambda region: (region.bbox, region.header))
    )


def test_profile_documents_orders_by_content_identity_and_collapses_exact_bytes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    duplicate = tmp_path / "duplicate.pdf"
    with fitz.open() as document:
        document.new_page(width=320, height=480)
        document.save(first)
    with fitz.open() as document:
        document.new_page(width=640, height=480)
        document.save(second)
    duplicate.write_bytes(first.read_bytes())
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_paths: list[Path] = []

    def parser(
        source: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict
        assert cache_dir is not None
        cache_paths.append(Path(cache_dir))
        return _empty_discovery_result(Path(source))

    profiles = profile_documents(
        (second, duplicate, first),
        cache_root,
        parser=parser,
    )

    assert tuple(item.document_id for item in profiles) == tuple(
        sorted(
            {
                hashlib.sha256(first.read_bytes()).hexdigest(),
                hashlib.sha256(second.read_bytes()).hexdigest(),
            }
        )
    )
    assert len(cache_paths) == 2
    assert {path.name for path in cache_paths} == {item.document_id for item in profiles}


@pytest.mark.parametrize("mutation", ("rewrite", "replace"))
def test_profile_documents_rejects_source_mutation_or_replacement(
    tmp_path: Path, mutation: str
) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=320, height=480)
        document.save(source)
    accepted = _empty_discovery_result(source)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    def parser(
        value: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del strict, cache_dir
        path = Path(value)
        if mutation == "rewrite":
            path.write_bytes(path.read_bytes() + b"changed")
        else:
            replacement = tmp_path / "replacement.pdf"
            with fitz.open() as document:
                document.new_page(width=320, height=480)
                document.save(replacement)
            replacement.replace(path)
        return accepted

    with pytest.raises(GroupingContractError, match="source changed during profiling"):
        profile_documents((source,), cache_root, parser=parser)


def test_profile_documents_rechecks_collapsed_exact_byte_aliases(tmp_path: Path) -> None:
    representative = tmp_path / "representative.pdf"
    alias = tmp_path / "alias.pdf"
    with fitz.open() as document:
        document.new_page(width=320, height=480)
        document.save(representative)
    alias.write_bytes(representative.read_bytes())
    accepted = _empty_discovery_result(representative)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    def parser(
        value: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        del value, strict, cache_dir
        alias.write_bytes(alias.read_bytes() + b"changed")
        return accepted

    with pytest.raises(GroupingContractError, match="source changed during profiling"):
        profile_documents((representative, alias), cache_root, parser=parser)


def test_profile_documents_finally_rechecks_sources_from_earlier_identity_groups(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    with fitz.open() as document:
        document.new_page(width=320, height=480)
        document.save(first)
    with fitz.open() as document:
        document.new_page(width=640, height=480)
        document.save(second)
    ordered = tuple(
        path
        for _digest, path in sorted(
            (
                (hashlib.sha256(first.read_bytes()).hexdigest(), first),
                (hashlib.sha256(second.read_bytes()).hexdigest(), second),
            )
        )
    )
    accepted = {path: _empty_discovery_result(path) for path in ordered}
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    calls = 0

    def parser(
        value: str | Path,
        strict: bool = False,
        *,
        cache_dir: str | Path | None = None,
    ) -> StatementResult:
        nonlocal calls
        del strict, cache_dir
        source = Path(value)
        calls += 1
        if calls == 2:
            ordered[0].write_bytes(ordered[0].read_bytes() + b"late-change")
        return accepted[source]

    with pytest.raises(GroupingContractError, match="source changed during profiling"):
        profile_documents(ordered, cache_root, parser=parser)
