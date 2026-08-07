from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

import fitz
import pytest
from pydantic import BaseModel, ValidationError

import experiments.row_extraction.merchant_context as merchant_context
from experiments.row_extraction.contracts import (
    ArtifactIdentity,
    BBox,
    ColumnBand,
    DatasetSplit,
    FieldRole,
    FrozenRow,
)
from experiments.row_extraction.merchant_context import (
    CONTEXT_TIERS,
    AssertionDisposition,
    ContextTier,
    MerchantAssertion,
    MerchantContextError,
    MerchantErrorCategory,
    MerchantReference,
    MerchantReferenceSummary,
    ReferenceDisposition,
    canonical_merchant_text,
    validate_merchant_reference,
)
from tests.experiments.row_extraction.factories import evidence_atom, frozen_row


def test_canonical_merchant_text_changes_only_nfc_and_layout_whitespace() -> None:
    assert canonical_merchant_text("  Cafe\u0301\n  Store  ") == "Café Store"
    assert canonical_merchant_text("A-B, Ltd.") == "A-B, Ltd."


def test_transaction_reference_requires_one_owner_and_source_support() -> None:
    reference = MerchantReference(
        document_id="a" * 64,
        anchor_row_id="continuation",
        disposition=ReferenceDisposition.TRANSACTION,
        owner_row_id="primary",
        owned_row_ids=("primary", "continuation"),
        merchant_text="SYNTHETIC MERCHANT",
        atom_ids=("merchant-1",),
        source_regions=(),
        ambiguity_category=None,
    )
    assert reference.owner_row_id == "primary"

    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {
                **reference.model_dump(),
                "owner_row_id": None,
                "atom_ids": (),
                "source_regions": (),
            }
        )


def test_transaction_reference_rejects_duplicate_or_unowned_support_ids() -> None:
    payload = {
        "document_id": "a" * 64,
        "anchor_row_id": "continuation",
        "disposition": ReferenceDisposition.TRANSACTION,
        "owner_row_id": "primary",
        "owned_row_ids": ("primary", "continuation"),
        "merchant_text": "SYNTHETIC MERCHANT",
        "atom_ids": ("merchant-1",),
        "source_regions": (),
        "ambiguity_category": None,
    }

    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {
                **payload,
                "owned_row_ids": ("primary", "continuation", "continuation"),
            }
        )
    with pytest.raises(ValidationError):
        MerchantReference.model_validate(
            {**payload, "owned_row_ids": ("continuation", "secondary")}
        )
    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "atom_ids": ("merchant-1", "merchant-1")})


def test_nontransaction_and_ambiguous_references_cannot_carry_merchant_values() -> None:
    with pytest.raises(ValidationError):
        MerchantReference(
            document_id="a" * 64,
            anchor_row_id="row",
            disposition=ReferenceDisposition.NONTRANSACTION,
            owner_row_id=None,
            owned_row_ids=(),
            merchant_text="SECRET MERCHANT",
            atom_ids=(),
            source_regions=(),
            ambiguity_category=None,
        )

    with pytest.raises(ValidationError):
        MerchantReference(
            document_id="a" * 64,
            anchor_row_id="row",
            disposition=ReferenceDisposition.AMBIGUOUS,
            owner_row_id=None,
            owned_row_ids=(),
            merchant_text=None,
            atom_ids=(),
            source_regions=(),
            ambiguity_category=None,
        )


def test_reference_rejects_noncanonical_or_empty_merchant_text() -> None:
    payload = {
        "document_id": "a" * 64,
        "anchor_row_id": "row",
        "disposition": ReferenceDisposition.TRANSACTION,
        "owner_row_id": "row",
        "owned_row_ids": ("row",),
        "atom_ids": ("merchant-1",),
        "source_regions": (),
        "ambiguity_category": None,
    }

    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "merchant_text": "  MERCHANT  "})
    with pytest.raises(ValidationError):
        MerchantReference.model_validate({**payload, "merchant_text": " \n "})


def test_assertion_contract_has_only_merchant_nontransaction_or_abstain() -> None:
    assertion = MerchantAssertion(
        context_id="b" * 64,
        document_id="a" * 64,
        anchor_row_id="row",
        disposition=AssertionDisposition.ABSTAIN,
        owner_row_id=None,
        merchant_text=None,
        atom_ids=(),
        source_regions=(),
    )
    assert assertion.model_dump(mode="json")["disposition"] == "abstain"
    with pytest.raises(ValidationError):
        MerchantAssertion.model_validate({**assertion.model_dump(), "prediction": "SECRET"})

    with pytest.raises(ValidationError):
        MerchantAssertion.model_validate(
            {
                **assertion.model_dump(),
                "disposition": AssertionDisposition.MERCHANT,
                "merchant_text": "SYNTHETIC MERCHANT",
                "atom_ids": ("merchant-1",),
            }
        )


def reference_fixture() -> tuple[
    tuple[FrozenRow, ...],
    tuple[FrozenRow, ...],
    tuple[MerchantReference, ...],
]:
    rows = tuple(
        frozen_row(
            document_id=f"{index:064x}",
            row_id=f"row-{index:03d}",
            atoms=(
                evidence_atom(
                    atom_id=f"merchant-{index:03d}",
                    text="SECRET MERCHANT",
                    bbox=(20.0, 20.0, 80.0, 30.0),
                ),
                evidence_atom(
                    atom_id=f"ancillary-{index:03d}",
                    text="ANCILLARY",
                    bbox=(90.0, 20.0, 130.0, 30.0),
                ),
            ),
        )
        for index in range(100)
    )
    references: list[MerchantReference] = []
    for index, row in enumerate(rows):
        if index == 98:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.AMBIGUOUS,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=MerchantErrorCategory.REFERENCE_AMBIGUITY_OR_DEFECT,
                )
            )
        elif index == 99:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.NONTRANSACTION,
                    owner_row_id=None,
                    owned_row_ids=(),
                    merchant_text=None,
                    atom_ids=(),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
        else:
            references.append(
                MerchantReference(
                    document_id=row.document_id,
                    anchor_row_id=row.row_id,
                    disposition=ReferenceDisposition.TRANSACTION,
                    owner_row_id=row.row_id,
                    owned_row_ids=(row.row_id,),
                    merchant_text="SECRET MERCHANT",
                    atom_ids=(f"merchant-{index:03d}",),
                    source_regions=(),
                    ambiguity_category=None,
                )
            )
    return rows, rows, tuple(references)


def test_reference_validation_is_aggregate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    population, selected, references = reference_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    summary = validate_merchant_reference(population, selected, references)

    assert summary == MerchantReferenceSummary(
        anchor_count=100,
        eligible_transaction_count=98,
        ambiguous_anchor_count=1,
        nontransaction_anchor_count=1,
    )
    serialized = summary.model_dump_json()
    assert "SECRET MERCHANT" not in serialized
    assert selected[0].document_id not in serialized
    assert selected[0].row_id not in serialized


def _shared_transaction_fixture() -> tuple[
    tuple[FrozenRow, ...],
    tuple[FrozenRow, ...],
    tuple[MerchantReference, ...],
]:
    population, selected, references = reference_fixture()
    shared_document = selected[0].document_id
    selected = (
        selected[0],
        selected[1].model_copy(update={"document_id": shared_document}),
        *selected[2:],
    )
    population = selected
    shared_payload = {
        "document_id": shared_document,
        "owner_row_id": selected[0].row_id,
        "owned_row_ids": (selected[0].row_id, selected[1].row_id),
        "merchant_text": "SECRET MERCHANT",
        "atom_ids": ("merchant-000",),
        "source_regions": (),
    }
    references = (
        references[0].model_copy(update=shared_payload),
        references[1].model_copy(update=shared_payload),
        *references[2:],
    )
    return population, selected, references


def test_reference_validation_counts_unique_transaction_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    summary = validate_merchant_reference(population, selected, references)

    assert summary.eligible_transaction_count == 97


@pytest.mark.parametrize(
    "break_references",
    (
        lambda references: (*references[:-1], references[0]),
        lambda references: references[:-1],
        lambda references: (
            *references[:-1],
            references[-1].model_copy(update={"document_id": "f" * 64, "anchor_row_id": "unknown"}),
        ),
    ),
)
def test_reference_validation_rejects_duplicate_missing_or_unknown_anchors(
    monkeypatch: pytest.MonkeyPatch,
    break_references: Callable[[tuple[MerchantReference, ...]], tuple[MerchantReference, ...]],
) -> None:
    population, selected, references = reference_fixture()
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference coverage mismatch$"):
        validate_merchant_reference(population, selected, break_references(references))


def test_reference_validation_rejects_nontraining_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = reference_fixture()
    selected = (
        selected[0].model_copy(update={"split": DatasetSplit.VALIDATION}),
        *selected[1:],
    )
    population = selected
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(
        MerchantContextError, match=r"^merchant reference requires training anchors$"
    ):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_selector_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = reference_fixture()
    different = (
        *selected[:-1],
        selected[-1].model_copy(update={"row_id": "different-row"}),
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: different)

    with pytest.raises(
        MerchantContextError, match=r"^merchant reference pilot membership mismatch$"
    ):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_inconsistent_repeated_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    references = (
        references[0],
        references[1].model_copy(
            update={"merchant_text": "OTHER MERCHANT", "atom_ids": ("merchant-001",)}
        ),
        *references[2:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference transaction mismatch$"):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_shared_rows_with_different_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    references = (
        references[0],
        references[1].model_copy(
            update={"owner_row_id": selected[1].row_id, "atom_ids": ("merchant-001",)}
        ),
        *references[2:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference ownership mismatch$"):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_nonselected_row_claimed_by_different_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, selected, references = reference_fixture()
    shared_document = selected[0].document_id
    selected = (
        selected[0],
        selected[1].model_copy(update={"document_id": shared_document}),
        *selected[2:],
    )
    unselected_row = frozen_row(
        document_id=shared_document,
        row_id="unselected-owned-row",
        atoms=(evidence_atom(atom_id="unselected-atom"),),
    )
    population = (*selected, unselected_row)
    references = (
        references[0].model_copy(
            update={"owned_row_ids": (selected[0].row_id, unselected_row.row_id)}
        ),
        references[1].model_copy(
            update={
                "document_id": shared_document,
                "owned_row_ids": (selected[1].row_id, unselected_row.row_id),
            }
        ),
        *references[2:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference ownership mismatch$"):
        validate_merchant_reference(population, selected, references)


def test_reference_validation_rejects_transaction_claiming_nontransaction_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected, references = _shared_transaction_fixture()
    references = (
        references[0],
        references[1].model_copy(
            update={
                "disposition": ReferenceDisposition.NONTRANSACTION,
                "owner_row_id": None,
                "owned_row_ids": (),
                "merchant_text": None,
                "atom_ids": (),
                "source_regions": (),
                "ambiguity_category": None,
            }
        ),
        *references[2:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference ownership mismatch$"):
        validate_merchant_reference(population, selected, references)


@pytest.mark.parametrize(
    "reference_update",
    (
        {"owned_row_ids": ("row-000", "unknown-row")},
        {"atom_ids": ("unknown-atom",)},
        {"atom_ids": (), "source_regions": ((0.0, 0.0, 10.0, 5.0),)},
    ),
)
def test_reference_validation_rejects_unknown_or_outside_source_support(
    monkeypatch: pytest.MonkeyPatch,
    reference_update: dict[str, object],
) -> None:
    population, selected, references = reference_fixture()
    references = (
        references[0].model_copy(update=reference_update),
        *references[1:],
    )
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)

    with pytest.raises(MerchantContextError, match=r"^merchant reference evidence mismatch$"):
        validate_merchant_reference(population, selected, references)


def context_fixture(tmp_path: Path) -> tuple[tuple[FrozenRow, ...], FrozenRow]:
    source = tmp_path / "synthetic.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    rows: list[FrozenRow] = []
    for index in range(5):
        top = 80.0 + 25.0 * index
        row = frozen_row(
            document_id="a" * 64,
            row_id=f"row-{index}",
            source_pdf=source,
            bbox=(10.0, top, 190.0, top + 20.0),
            atoms=(
                evidence_atom(
                    atom_id=f"atom-{index}",
                    bbox=(20.0, top + 2.0, 80.0, top + 12.0),
                ),
            ),
        ).model_copy(
            update={
                "previous_row_id": f"row-{index - 1}" if index else None,
                "next_row_id": f"row-{index + 1}" if index < 4 else None,
                "column_bands": (
                    ColumnBand(
                        index=0,
                        role=FieldRole.DESCRIPTION,
                        bbox=(10.0, 40.0, 190.0, 240.0),
                    ),
                ),
            }
        )
        rows.append(row)
    return tuple(rows), rows[2]


def source_regions_cover(outer: tuple[BBox, ...], inner: tuple[BBox, ...]) -> bool:
    return all(
        any(
            candidate[0] <= region[0]
            and candidate[1] <= region[1]
            and region[2] <= candidate[2]
            and region[3] <= candidate[3]
            for candidate in outer
        )
        for region in inner
    )


def test_context_tiers_are_monotonic_and_change_only_spatial_extent(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)

    pairs = merchant_context.materialize_anchor_contexts(population, anchor, tmp_path / "images")
    records = tuple((index, packet) for index, packet in pairs)

    assert tuple(index.tier for index, _ in records) == CONTEXT_TIERS
    for smaller, larger in itertools.pairwise(records):
        _, smaller_packet = smaller
        _, larger_packet = larger
        assert source_regions_cover(
            tuple(image.source_bbox for image in larger_packet.images),
            tuple(image.source_bbox for image in smaller_packet.images),
        )
        assert {row.row_id for row in smaller_packet.rows} <= {
            row.row_id for row in larger_packet.rows
        }
    assert tuple(row.row_id for row in records[0][1].rows) == (anchor.row_id,)
    assert len(records[1][1].rows) == 3
    assert len(records[2][1].rows) == 5
    assert len(records[3][1].images) == 2
    assert tuple(image.source_bbox for image in records[4][1].images) == (
        (10.0, 40.0, 190.0, 240.0),
    )
    assert tuple(image.source_bbox for image in records[5][1].images) == ((0.0, 0.0, 200.0, 300.0),)


def test_context_neighbors_stop_at_page_edges_and_require_reciprocity(tmp_path: Path) -> None:
    population, _ = context_fixture(tmp_path)
    first = population[0]

    edge_pairs = merchant_context.materialize_anchor_contexts(
        population, first, tmp_path / "edge-images"
    )

    assert tuple(row.row_id for row in edge_pairs[1][1].rows) == ("row-0", "row-1")
    assert tuple(row.row_id for row in edge_pairs[2][1].rows) == (
        "row-0",
        "row-1",
        "row-2",
    )

    last_pairs = merchant_context.materialize_anchor_contexts(
        population, population[-1], tmp_path / "last-images"
    )
    assert tuple(image.source_bbox for image in last_pairs[3][1].images)[-1] == (
        10.0,
        40.0,
        190.0,
        80.0,
    )

    anchor = population[2]
    broken_predecessor = population[1].model_copy(
        update={"page_number": 2, "next_row_id": anchor.row_id}
    )
    nonreciprocal_successor = population[3].model_copy(update={"previous_row_id": "other"})
    crossed = (
        population[0],
        broken_predecessor,
        anchor,
        nonreciprocal_successor,
        population[4],
    )

    crossed_pairs = merchant_context.materialize_anchor_contexts(
        crossed, anchor, tmp_path / "crossed-images"
    )

    assert tuple(row.row_id for row in crossed_pairs[1][1].rows) == (anchor.row_id,)
    assert tuple(row.row_id for row in crossed_pairs[2][1].rows) == (anchor.row_id,)


def test_missing_header_leaves_undeclared_neighboring_tiers_equal(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)
    without_bands = tuple(row.model_copy(update={"column_bands": ()}) for row in population)
    anchor = without_bands[2]

    pairs = merchant_context.materialize_anchor_contexts(without_bands, anchor, tmp_path / "images")

    assert tuple(
        (image.source_bbox, image.sha256, image.width, image.height) for image in pairs[2][1].images
    ) == tuple(
        (image.source_bbox, image.sha256, image.width, image.height) for image in pairs[3][1].images
    )
    assert pairs[2][1].rows == pairs[3][1].rows
    assert tuple(
        (image.source_bbox, image.sha256, image.width, image.height) for image in pairs[3][1].images
    ) == tuple(
        (image.source_bbox, image.sha256, image.width, image.height) for image in pairs[4][1].images
    )
    assert pairs[3][1].rows == pairs[4][1].rows


def test_table_context_matches_ordered_role_free_column_geometry(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)
    shared_geometry = frozen_row(
        document_id=anchor.document_id,
        row_id="same-geometry-different-role",
        source_pdf=anchor.source_pdf,
        bbox=(10.0, 210.0, 190.0, 230.0),
        atoms=(evidence_atom(atom_id="same-geometry-atom", bbox=(20.0, 212.0, 80.0, 222.0)),),
    ).model_copy(
        update={
            "column_bands": (
                ColumnBand(
                    index=9,
                    role=FieldRole.BILLED_AMOUNT,
                    bbox=(10.0, 40.0, 190.0, 240.0),
                ),
            )
        }
    )
    different_geometry = shared_geometry.model_copy(
        update={
            "row_id": "different-geometry",
            "column_bands": (ColumnBand(index=0, role=None, bbox=(10.0, 40.0, 180.0, 240.0)),),
        }
    )

    pairs = merchant_context.materialize_anchor_contexts(
        (*population, shared_geometry, different_geometry),
        anchor,
        tmp_path / "images",
    )
    table_row_ids = {row.row_id for row in pairs[4][1].rows}
    page_row_ids = {row.row_id for row in pairs[5][1].rows}

    assert shared_geometry.row_id in table_row_ids
    assert different_geometry.row_id not in table_row_ids
    assert different_geometry.row_id in page_row_ids
    assert pairs[4][1].column_boundaries == ((10.0, 40.0, 190.0, 240.0),)


def test_review_packet_hides_tier_roles_labels_and_source_paths(tmp_path: Path) -> None:
    population, anchor = context_fixture(tmp_path)
    index, packet = merchant_context.materialize_anchor_contexts(
        population, anchor, tmp_path / "images"
    )[0]
    serialized = packet.model_dump_json()

    assert index.tier is ContextTier.C0_ROW
    assert index.context_id == packet.context_id
    for forbidden in (
        "c0_row",
        "baseline_type",
        "role",
        "source_pdf",
        "current_gold",
        "reviewer_a",
        "reviewer_b",
        "prediction",
        "SECRET_FILENAME",
    ):
        assert forbidden not in serialized


def test_context_renderer_preserves_300_dpi_rgb_pixels_and_marks_only_outside_anchor(
    tmp_path: Path,
) -> None:
    population, anchor = context_fixture(tmp_path)

    _, packet = merchant_context.materialize_anchor_contexts(
        population, anchor, tmp_path / "images"
    )[0]
    image = packet.images[0]
    image_path = tmp_path / "images" / image.relative_path
    rendered = fitz.Pixmap(image_path)
    with fitz.open(anchor.source_pdf) as document:
        source = document[0].get_pixmap(
            dpi=300,
            colorspace=fitz.csRGB,
            clip=fitz.Rect(anchor.bbox),
            alpha=False,
        )

    assert rendered.n == 3
    assert (rendered.xres, rendered.yres) == (300, 300)
    assert (rendered.width, rendered.height) == (source.width + 8, source.height + 8)
    assert (image.width, image.height) == (rendered.width, rendered.height)
    assert image.sha256 == hashlib.sha256(image_path.read_bytes()).hexdigest()
    magenta = (255, 0, 255)
    magenta_pixels = {
        (x, y)
        for y in range(rendered.height)
        for x in range(rendered.width)
        if rendered.pixel(x, y) == magenta
    }
    assert magenta_pixels
    assert all(
        x < 4 or y < 4 or x >= rendered.width - 4 or y >= rendered.height - 4
        for x, y in magenta_pixels
    )
    assert rendered.pixel(rendered.width // 2, rendered.height // 2) == source.pixel(
        source.width // 2, source.height // 2
    )


@pytest.mark.parametrize(
    "anchor_update",
    (
        {"bbox": (-1.0, 80.0, 190.0, 100.0)},
        {"bbox": (10.0, 80.0, 210.0, 100.0)},
        {"source_pdf": Path("missing.pdf")},
    ),
)
def test_materializer_fails_closed_when_declared_pixels_are_unavailable(
    tmp_path: Path,
    anchor_update: dict[str, object],
) -> None:
    population, anchor = context_fixture(tmp_path)
    changed_anchor = anchor.model_copy(update=anchor_update)
    changed_population = tuple(
        changed_anchor if row.row_id == anchor.row_id else row for row in population
    )

    with pytest.raises(MerchantContextError, match=r"^merchant context geometry unavailable$"):
        merchant_context.materialize_anchor_contexts(
            changed_population, changed_anchor, tmp_path / "images"
        )


def _high_level_fixture(tmp_path: Path) -> tuple[tuple[FrozenRow, ...], tuple[FrozenRow, ...]]:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        document.new_page(width=200, height=300)
        document.save(source)
    rows = tuple(
        frozen_row(
            document_id=f"{index:064x}",
            row_id=f"row-{index:03d}",
            source_pdf=source,
            bbox=(10.0, 80.0, 190.0, 100.0),
            atoms=(
                evidence_atom(
                    atom_id=f"atom-{index:03d}",
                    bbox=(20.0, 82.0, 80.0, 92.0),
                ),
            ),
        ).model_copy(
            update={
                "column_bands": (ColumnBand(index=0, role=None, bbox=(10.0, 40.0, 190.0, 240.0)),)
            }
        )
        for index in range(100)
    )
    return rows, rows


def _install_fast_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    def render_context_image(
        *,
        source_pdf: Path,
        page_number: int,
        source_bbox: BBox,
        anchor_bbox: BBox,
        image_root: Path,
        relative_path: str,
    ) -> merchant_context.ContextImage:
        del source_pdf, page_number, anchor_bbox
        image_path = image_root / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        content = b"synthetic opaque image"
        image_path.write_bytes(content)
        return merchant_context.ContextImage(
            source_bbox=source_bbox,
            relative_path=relative_path,
            sha256=hashlib.sha256(content).hexdigest(),
            width=1,
            height=1,
        )

    monkeypatch.setattr(merchant_context, "_render_context_image", render_context_image)


def test_materialize_writes_six_opaque_batches_and_one_private_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected = _high_level_fixture(tmp_path)
    private_root = tmp_path / "merchant-context-sufficiency-v1"
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)
    _install_fast_renderer(monkeypatch)

    materialized = merchant_context.materialize_merchant_contexts(
        population, selected, private_root
    )

    assert len(materialized) == 600
    assert len({index.context_id for index, _ in materialized}) == 600
    assert tuple((index.batch_id, index.context_id) for index, _ in materialized) == tuple(
        sorted((index.batch_id, index.context_id) for index, _ in materialized)
    )
    batch_files = tuple(sorted((private_root / "packets").glob("*.jsonl")))
    assert len(batch_files) == 6
    assert all(len(path.stem) == 64 and path.stem.isalnum() for path in batch_files)
    batches = tuple(
        tuple(json.loads(line) for line in path.read_text().splitlines()) for path in batch_files
    )
    assert all(len(batch) == 100 for batch in batches)
    assert sum((len(batch) for batch in batches), start=0) == 600
    assert len((private_root / "context-index.jsonl").read_text().splitlines()) == 600
    public_bytes = b"".join(path.read_bytes() for path in batch_files)
    for forbidden in (
        *(tier.value.encode() for tier in CONTEXT_TIERS),
        b"baseline_type",
        b'"role"',
        b"source_pdf",
        b"current_gold",
        b"reviewer_a",
        b"reviewer_b",
        b"prediction",
    ):
        assert forbidden not in public_bytes
    for batch in batches:
        for packet in batch:
            for image in packet["images"]:
                relative = Path(image["relative_path"])
                assert len(relative.parts) == 2
                assert len(relative.parts[0]) == 64
                assert len(relative.stem) == 64
                assert (private_root / "images" / relative).is_file()

    expected_prompt = (
        b"Identify the merchant for the transaction that owns the highlighted anchor row. "
        b"Use only the supplied pixels and positioned atoms. Return exactly one "
        b"MerchantAssertion JSON object for each packet. Include the complete merchant-bearing "
        b"source text and its exact atom IDs and/or source regions. Do not include category, "
        b"location, processor/reference, exchange-rate, fee, date, amount, currency, or "
        b"installment text unless it is visually inseparable from and necessary to the printed "
        b"merchant identity. Return nontransaction only for source evidence that is not a "
        b"transaction; otherwise abstain when one supported merchant and owner cannot be "
        b"established. Never guess, repair spelling, use a merchant database, or borrow text "
        b"from another transaction."
    )
    assert {merchant_context.MERCHANT_CONTEXT_PROMPT.encode() for _ in batch_files} == {
        expected_prompt
    }


def test_materialize_cleans_the_private_root_after_a_failed_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population, selected = _high_level_fixture(tmp_path)
    private_root = tmp_path / "merchant-context-sufficiency-v1"
    monkeypatch.setattr(merchant_context, "select_visual_gold_pilot", lambda rows: selected)
    _install_fast_renderer(monkeypatch)
    original_write_jsonl = merchant_context.write_jsonl

    def fail_after_write(path: Path, records: Iterable[BaseModel]) -> ArtifactIdentity:
        original_write_jsonl(path, records)
        raise OSError("synthetic write failure")

    monkeypatch.setattr(merchant_context, "write_jsonl", fail_after_write)

    with pytest.raises(MerchantContextError, match=r"^merchant context materialization failed$"):
        merchant_context.materialize_merchant_contexts(population, selected, private_root)

    assert not private_root.exists()


def test_materialize_rejects_unsafe_roots_with_sanitized_errors(
    tmp_path: Path,
) -> None:
    nonempty = tmp_path / "nonempty" / "merchant-context-sufficiency-v1"
    nonempty.mkdir(parents=True)
    (nonempty / "private.txt").write_text("private")
    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "symlink" / "merchant-context-sufficiency-v1"
    symlink.parent.mkdir()
    symlink.symlink_to(target, target_is_directory=True)

    cases = (
        (
            Path("merchant-context-sufficiency-v1"),
            "merchant context root must be absolute",
        ),
        (
            tmp_path / "wrong-name",
            "merchant context root name mismatch",
        ),
        (
            symlink,
            "merchant context root must not be a symlink",
        ),
        (
            nonempty,
            "merchant context root must be empty",
        ),
    )
    for root, message in cases:
        with pytest.raises(MerchantContextError, match=rf"^{message}$") as error:
            merchant_context.materialize_merchant_contexts((), (), root)
        assert str(root) not in str(error.value)

    repository = tmp_path / "repository"
    tracked_root = repository / "merchant-context-sufficiency-v1"
    tracked_root.mkdir(parents=True)
    placeholder = tracked_root / "placeholder"
    placeholder.write_text("tracked")
    subprocess.run(("git", "init", "-q", str(repository)), check=True)
    subprocess.run(("git", "-C", str(repository), "add", str(placeholder)), check=True)
    placeholder.unlink()

    with pytest.raises(
        MerchantContextError,
        match=r"^merchant context root must be outside Git or ignored$",
    ) as error:
        merchant_context.materialize_merchant_contexts((), (), tracked_root)
    assert str(tracked_root) not in str(error.value)
