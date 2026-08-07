"""Private merchant-context contracts and aggregate reference validation."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import math
import os
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from pathlib import Path
from typing import Self

import fitz  # type: ignore[import-untyped]  # PyMuPDF does not publish typing metadata.
from pydantic import ConfigDict, Field, ValidationError, model_validator

from experiments.row_extraction.codecs import write_jsonl
from experiments.row_extraction.contracts import (
    BBox,
    DatasetSplit,
    EvidenceAtom,
    FrozenRow,
    _FrozenModel,
)
from experiments.row_extraction.visual_gold_pilot import select_visual_gold_pilot

type _RowIdentity = tuple[str, str]
type _TransactionIdentity = tuple[str, str]
type _TransactionPayload = tuple[
    str,
    tuple[str, ...],
    str,
    tuple[str, ...],
    tuple[BBox, ...],
]

_PILOT_ANCHOR_COUNT = 100
_MATERIALIZER_VERSION = "merchant-context-materializer-v1"
_PRIVATE_ROOT_NAME = "merchant-context-sufficiency-v1"
_RENDER_DPI = 300
_RENDER_SCALE = _RENDER_DPI / 72
_CANVAS_MARGIN = 4
_CANVAS_NEUTRAL = 238
_ANCHOR_MARKER = (255, 0, 255)


class MerchantContextError(ValueError):
    """A private merchant-context artifact failed content-free validation."""


class _PrivateModel(_FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ContextTier(StrEnum):
    C0_ROW = "c0_row"
    C1_ADJACENT_ROWS = "c1_adjacent_rows"
    C2_LOCAL_NEIGHBORHOOD = "c2_local_neighborhood"
    C3_HEADER_NEIGHBORHOOD = "c3_header_neighborhood"
    C4_TABLE_REGION = "c4_table_region"
    C5_FULL_PAGE = "c5_full_page"


CONTEXT_TIERS = tuple(ContextTier)


class ContextImage(_PrivateModel):
    source_bbox: BBox
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class MerchantContextRow(_PrivateModel):
    row_id: str = Field(min_length=1)
    bbox: BBox
    atoms: tuple[EvidenceAtom, ...]


class MerchantContextPacket(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    page_number: int = Field(gt=0)
    anchor_bbox: BBox
    column_boundaries: tuple[BBox, ...]
    rows: tuple[MerchantContextRow, ...]
    images: tuple[ContextImage, ...] = Field(min_length=1)


class MerchantContextIndex(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    tier: ContextTier
    batch_id: str = Field(pattern=r"^[0-9a-f]{64}$")


MERCHANT_CONTEXT_PROMPT = (
    "Identify the merchant for the transaction that owns the highlighted anchor row. "
    "Use only the supplied pixels and positioned atoms. Return exactly one "
    "MerchantAssertion JSON object for each packet. Include the complete merchant-bearing "
    "source text and its exact atom IDs and/or source regions. Do not include category, "
    "location, processor/reference, exchange-rate, fee, date, amount, currency, or "
    "installment text unless it is visually inseparable from and necessary to the printed "
    "merchant identity. Return nontransaction only for source evidence that is not a "
    "transaction; otherwise abstain when one supported merchant and owner cannot be "
    "established. Never guess, repair spelling, use a merchant database, or borrow text "
    "from another transaction."
)


class ReferenceDisposition(StrEnum):
    TRANSACTION = "transaction"
    NONTRANSACTION = "nontransaction"
    AMBIGUOUS = "ambiguous"


class AssertionDisposition(StrEnum):
    MERCHANT = "merchant"
    NONTRANSACTION = "nontransaction"
    ABSTAIN = "abstain"


class MerchantErrorCategory(StrEnum):
    INSUFFICIENT_CONTEXT_OR_MISSING_HEADER = "insufficient_context_or_missing_header"
    CONTINUATION_OWNERSHIP = "continuation_ownership"
    MERCHANT_SPAN_BOUNDARY = "merchant_span_boundary"
    MERCHANT_VERSUS_ANCILLARY = "merchant_versus_ancillary"
    MIXED_DIRECTION_OR_READING_ORDER = "mixed_direction_or_reading_order"
    OCR_OR_ATOM_SEGMENTATION = "ocr_or_atom_segmentation"
    NEIGHBORING_TRANSACTION_CONTAMINATION = "neighboring_transaction_contamination"
    UNSUPPORTED_MERCHANT_TEXT = "unsupported_merchant_text"
    CORRECT_ABSTENTION_ON_AMBIGUOUS_EVIDENCE = "correct_abstention_on_ambiguous_evidence"
    REFERENCE_AMBIGUITY_OR_DEFECT = "reference_ambiguity_or_defect"


def canonical_merchant_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _ids_are_canonical(values: tuple[str, ...]) -> bool:
    return all(values) and len(values) == len(set(values))


def _merchant_text_is_canonical(text: str | None) -> bool:
    return text is not None and bool(text) and canonical_merchant_text(text) == text


class MerchantReference(_PrivateModel):
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    disposition: ReferenceDisposition
    owner_row_id: str | None
    owned_row_ids: tuple[str, ...]
    merchant_text: str | None
    atom_ids: tuple[str, ...]
    source_regions: tuple[BBox, ...]
    ambiguity_category: MerchantErrorCategory | None

    @model_validator(mode="after")
    def has_valid_disposition_shape(self) -> Self:
        if self.disposition is ReferenceDisposition.TRANSACTION:
            if (
                self.owner_row_id is None
                or not self.owner_row_id
                or not _ids_are_canonical(self.owned_row_ids)
                or self.owner_row_id not in self.owned_row_ids
                or self.anchor_row_id not in self.owned_row_ids
                or not _merchant_text_is_canonical(self.merchant_text)
                or (not self.atom_ids and not self.source_regions)
                or self.ambiguity_category is not None
            ):
                raise ValueError("invalid transaction merchant reference")
        elif self.disposition is ReferenceDisposition.NONTRANSACTION:
            if (
                self.owner_row_id is not None
                or self.owned_row_ids
                or self.merchant_text is not None
                or self.atom_ids
                or self.source_regions
                or self.ambiguity_category is not None
            ):
                raise ValueError("invalid nontransaction merchant reference")
        elif (
            self.owner_row_id is not None
            or self.owned_row_ids
            or self.merchant_text is not None
            or self.atom_ids
            or self.source_regions
            or self.ambiguity_category is None
        ):
            raise ValueError("invalid ambiguous merchant reference")
        if self.atom_ids and not _ids_are_canonical(self.atom_ids):
            raise ValueError("invalid merchant reference atom IDs")
        return self


class MerchantAssertion(_PrivateModel):
    context_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor_row_id: str = Field(min_length=1)
    disposition: AssertionDisposition
    owner_row_id: str | None
    merchant_text: str | None
    atom_ids: tuple[str, ...]
    source_regions: tuple[BBox, ...]

    @model_validator(mode="after")
    def has_valid_disposition_shape(self) -> Self:
        if self.disposition is AssertionDisposition.MERCHANT:
            if (
                self.owner_row_id is None
                or not self.owner_row_id
                or not _merchant_text_is_canonical(self.merchant_text)
                or (not self.atom_ids and not self.source_regions)
            ):
                raise ValueError("invalid merchant assertion")
        elif (
            self.owner_row_id is not None
            or self.merchant_text is not None
            or self.atom_ids
            or self.source_regions
        ):
            raise ValueError("invalid empty merchant assertion")
        if self.atom_ids and not _ids_are_canonical(self.atom_ids):
            raise ValueError("invalid merchant assertion atom IDs")
        return self


class MerchantErrorLabel(_PrivateModel):
    tier: ContextTier
    document_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_row_id: str = Field(min_length=1)
    primary: MerchantErrorCategory
    secondary: tuple[MerchantErrorCategory, ...] = ()

    @model_validator(mode="after")
    def has_unique_secondary_categories(self) -> Self:
        if len(self.secondary) != len(set(self.secondary)) or self.primary in self.secondary:
            raise ValueError("invalid merchant error categories")
        return self


class MerchantReferenceSummary(_FrozenModel):
    anchor_count: int = Field(ge=0)
    eligible_transaction_count: int = Field(ge=0)
    ambiguous_anchor_count: int = Field(ge=0)
    nontransaction_anchor_count: int = Field(ge=0)


class MerchantErrorCount(_FrozenModel):
    category: MerchantErrorCategory
    count: int = Field(ge=0)


class MerchantTierSummary(_FrozenModel):
    tier: ContextTier
    eligible_transactions: int = Field(ge=0)
    correct_attributions: int = Field(ge=0)
    merchant_accuracy: Decimal
    exact_text_matches: int = Field(ge=0)
    exact_text_rate: Decimal
    omissions: int = Field(ge=0)
    wrong_merchants: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    ownership_errors: int = Field(ge=0)
    nontransaction_anchors: int = Field(ge=0)
    correct_nontransaction_anchors: int = Field(ge=0)
    errors: tuple[MerchantErrorCount, ...]
    safe: bool


class MerchantPairedDelta(_FrozenModel):
    tier: ContextTier
    comparator: ContextTier
    attribution_gains: int = Field(ge=0)
    attribution_losses: int = Field(ge=0)
    exact_text_gains: int = Field(ge=0)
    exact_text_losses: int = Field(ge=0)


class MerchantContextSummary(_FrozenModel):
    anchor_count: int = Field(ge=0)
    eligible_transaction_count: int = Field(ge=0)
    reference_ambiguity_count: int = Field(ge=0)
    nontransaction_anchor_count: int = Field(ge=0)
    tiers: tuple[MerchantTierSummary, ...]
    paired_deltas: tuple[MerchantPairedDelta, ...]
    recommended_tier: ContextTier | None
    hypothesis_supported: bool
    hypothesis_falsified: bool
    context_interference: bool


def _identity(row: FrozenRow | MerchantReference | MerchantAssertion) -> _RowIdentity:
    row_id = row.row_id if isinstance(row, FrozenRow) else row.anchor_row_id
    return row.document_id, row_id


def _validated_references(
    references: Sequence[MerchantReference],
) -> tuple[MerchantReference, ...]:
    try:
        return tuple(
            MerchantReference.model_validate(reference.model_dump()) for reference in references
        )
    except ValidationError:
        raise MerchantContextError("merchant reference contract mismatch") from None


def _row_index(
    population: Sequence[FrozenRow],
) -> dict[str, dict[str, FrozenRow | None]]:
    result: dict[str, dict[str, FrozenRow | None]] = {}
    for row in population:
        document_rows = result.setdefault(row.document_id, {})
        if row.row_id in document_rows:
            document_rows[row.row_id] = None
        else:
            document_rows[row.row_id] = row
    return result


def _is_contained(region: BBox, container: BBox) -> bool:
    region_x0, region_y0, region_x1, region_y1 = region
    container_x0, container_y0, container_x1, container_y1 = container
    return (
        all(math.isfinite(value) for value in (*region, *container))
        and region_x0 < region_x1
        and region_y0 < region_y1
        and container_x0 <= region_x0
        and container_y0 <= region_y0
        and region_x1 <= container_x1
        and region_y1 <= container_y1
    )


def _validate_transaction_evidence(
    reference: MerchantReference,
    rows_by_document: dict[str, dict[str, FrozenRow | None]],
) -> _TransactionPayload:
    if reference.owner_row_id is None or reference.merchant_text is None:
        raise MerchantContextError("merchant reference contract mismatch")
    document_rows = rows_by_document.get(reference.document_id, {})
    owned_rows = tuple(document_rows.get(row_id) for row_id in reference.owned_row_ids)
    if any(row is None for row in owned_rows):
        raise MerchantContextError("merchant reference evidence mismatch")
    concrete_rows = tuple(row for row in owned_rows if row is not None)
    atom_counts = Counter(atom.atom_id for row in concrete_rows for atom in row.atoms)
    if any(atom_counts[atom_id] != 1 for atom_id in reference.atom_ids):
        raise MerchantContextError("merchant reference evidence mismatch")
    if any(
        not any(_is_contained(region, row.bbox) for row in concrete_rows)
        for region in reference.source_regions
    ):
        raise MerchantContextError("merchant reference evidence mismatch")
    return (
        reference.owner_row_id,
        reference.owned_row_ids,
        reference.merchant_text,
        reference.atom_ids,
        reference.source_regions,
    )


def validate_merchant_reference(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    references: Sequence[MerchantReference],
) -> MerchantReferenceSummary:
    """Validate one frozen private reference and return aggregate-only counts."""

    selected_identities = tuple(_identity(row) for row in selected_rows)
    selected_identity_set = set(selected_identities)
    if (
        len(selected_rows) != _PILOT_ANCHOR_COUNT
        or len(selected_identity_set) != _PILOT_ANCHOR_COUNT
    ):
        raise MerchantContextError("merchant reference coverage mismatch")
    if any(row.split is not DatasetSplit.TRAIN for row in selected_rows):
        raise MerchantContextError("merchant reference requires training anchors")
    try:
        expected_identities = {_identity(row) for row in select_visual_gold_pilot(population)}
    except Exception:
        raise MerchantContextError("merchant reference pilot membership mismatch") from None
    if selected_identity_set != expected_identities:
        raise MerchantContextError("merchant reference pilot membership mismatch")

    validated_references = _validated_references(references)
    reference_identities = tuple(_identity(reference) for reference in validated_references)
    if (
        len(validated_references) != _PILOT_ANCHOR_COUNT
        or len(set(reference_identities)) != _PILOT_ANCHOR_COUNT
        or set(reference_identities) != selected_identity_set
    ):
        raise MerchantContextError("merchant reference coverage mismatch")

    rows_by_document = _row_index(population)
    transaction_payloads: dict[_TransactionIdentity, _TransactionPayload] = {}
    reference_payloads: dict[_RowIdentity, _TransactionPayload] = {}
    ownership_claims: dict[_RowIdentity, tuple[_TransactionIdentity, _TransactionPayload]] = {}
    ambiguous_anchor_count = 0
    nontransaction_anchor_count = 0
    for reference in validated_references:
        if reference.disposition is ReferenceDisposition.AMBIGUOUS:
            ambiguous_anchor_count += 1
            continue
        if reference.disposition is ReferenceDisposition.NONTRANSACTION:
            nontransaction_anchor_count += 1
            continue
        payload = _validate_transaction_evidence(reference, rows_by_document)
        transaction_identity = (reference.document_id, payload[0])
        previous_payload = transaction_payloads.setdefault(transaction_identity, payload)
        if previous_payload != payload:
            raise MerchantContextError("merchant reference transaction mismatch")
        reference_payloads[_identity(reference)] = payload
        claim = transaction_identity, payload
        for owned_row_id in reference.owned_row_ids:
            owned_identity = reference.document_id, owned_row_id
            previous_claim = ownership_claims.setdefault(owned_identity, claim)
            if previous_claim != claim:
                raise MerchantContextError("merchant reference ownership mismatch")

    for owned_identity, (transaction_identity, payload) in ownership_claims.items():
        if owned_identity not in selected_identity_set:
            continue
        owned_payload = reference_payloads.get(owned_identity)
        if (
            owned_payload is None
            or (owned_identity[0], owned_payload[0]) != transaction_identity
            or owned_payload != payload
        ):
            raise MerchantContextError("merchant reference ownership mismatch")

    return MerchantReferenceSummary(
        anchor_count=len(selected_rows),
        eligible_transaction_count=len(transaction_payloads),
        ambiguous_anchor_count=ambiguous_anchor_count,
        nontransaction_anchor_count=nontransaction_anchor_count,
    )


class _TransactionScore(tuple[bool, bool, bool, bool, bool, bool]):
    """Private tuple-like score kept out of aggregate output models."""

    __slots__ = ()

    def __new__(
        cls,
        attribution: bool,
        exact_text: bool,
        omission: bool,
        wrong_merchant: bool,
        hallucination: bool,
        ownership_error: bool,
    ) -> Self:
        return tuple.__new__(
            cls,
            (
                attribution,
                exact_text,
                omission,
                wrong_merchant,
                hallucination,
                ownership_error,
            ),
        )

    @property
    def attribution(self) -> bool:
        return bool(self[0])

    @property
    def exact_text(self) -> bool:
        return bool(self[1])

    @property
    def omission(self) -> bool:
        return bool(self[2])

    @property
    def wrong_merchant(self) -> bool:
        return bool(self[3])

    @property
    def hallucination(self) -> bool:
        return bool(self[4])

    @property
    def ownership_error(self) -> bool:
        return bool(self[5])


def _validated_packets(
    packets: Sequence[MerchantContextPacket],
) -> tuple[MerchantContextPacket, ...]:
    try:
        return tuple(
            MerchantContextPacket.model_validate(packet.model_dump()) for packet in packets
        )
    except ValidationError:
        raise MerchantContextError("merchant context contract mismatch") from None


def _validated_index_records(
    index_records: Sequence[MerchantContextIndex],
) -> tuple[MerchantContextIndex, ...]:
    try:
        return tuple(
            MerchantContextIndex.model_validate(index.model_dump()) for index in index_records
        )
    except ValidationError:
        raise MerchantContextError("merchant context contract mismatch") from None


def _validated_assertions(
    assertions: Sequence[MerchantAssertion],
) -> tuple[MerchantAssertion, ...]:
    try:
        return tuple(
            MerchantAssertion.model_validate(assertion.model_dump()) for assertion in assertions
        )
    except ValidationError:
        raise MerchantContextError("merchant assertion contract mismatch") from None


def _validated_error_labels(
    error_labels: Sequence[MerchantErrorLabel],
) -> tuple[MerchantErrorLabel, ...]:
    try:
        return tuple(
            MerchantErrorLabel.model_validate(label.model_dump()) for label in error_labels
        )
    except ValidationError:
        raise MerchantContextError("merchant error contract mismatch") from None


def _packet_atom_texts(packet: MerchantContextPacket) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for row in packet.rows:
        for atom in row.atoms:
            if atom.atom_id in result:
                result[atom.atom_id] = None
            else:
                result[atom.atom_id] = atom.text
    return result


def _assertion_evidence_is_available(
    assertion: MerchantAssertion, packet: MerchantContextPacket
) -> bool:
    atom_texts = _packet_atom_texts(packet)
    if any(atom_texts.get(atom_id) is None for atom_id in assertion.atom_ids):
        return False
    available_regions = (
        *(row.bbox for row in packet.rows),
        *(image.source_bbox for image in packet.images),
    )
    return all(
        any(_is_contained(region, available) for available in available_regions)
        for region in assertion.source_regions
    )


def _assertion_text_is_atom_supported(
    assertion: MerchantAssertion, packet: MerchantContextPacket
) -> bool:
    if assertion.disposition is not AssertionDisposition.MERCHANT:
        return True
    if assertion.merchant_text is None or not assertion.atom_ids:
        return False
    atom_texts = _packet_atom_texts(packet)
    texts = tuple(atom_texts.get(atom_id) for atom_id in assertion.atom_ids)
    if any(text is None for text in texts):
        return False
    concrete_texts = tuple(text for text in texts if text is not None)
    return canonical_merchant_text(" ".join(concrete_texts)) == assertion.merchant_text


def _assertion_text_is_source_supported(
    assertion: MerchantAssertion, packet: MerchantContextPacket
) -> bool:
    return bool(assertion.source_regions) or _assertion_text_is_atom_supported(assertion, packet)


def _regions_overlap(first: BBox, second: BBox) -> bool:
    return max(first[0], second[0]) < min(first[2], second[2]) and max(first[1], second[1]) < min(
        first[3], second[3]
    )


def _rate(numerator: int, denominator: int) -> Decimal:
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        if denominator == 0:
            return Decimal(0)
        return Decimal(numerator) / Decimal(denominator)


def _paired_delta(
    tier: ContextTier,
    comparator: ContextTier,
    attribution_sets: dict[ContextTier, set[_TransactionIdentity]],
    exact_sets: dict[ContextTier, set[_TransactionIdentity]],
) -> MerchantPairedDelta:
    tier_attributions = attribution_sets[tier]
    comparator_attributions = attribution_sets[comparator]
    tier_exact = exact_sets[tier]
    comparator_exact = exact_sets[comparator]
    return MerchantPairedDelta(
        tier=tier,
        comparator=comparator,
        attribution_gains=len(tier_attributions - comparator_attributions),
        attribution_losses=len(comparator_attributions - tier_attributions),
        exact_text_gains=len(tier_exact - comparator_exact),
        exact_text_losses=len(comparator_exact - tier_exact),
    )


def score_merchant_context(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    packets: Sequence[MerchantContextPacket],
    index_records: Sequence[MerchantContextIndex],
    references: Sequence[MerchantReference],
    assertions: Sequence[MerchantAssertion],
    error_labels: Sequence[MerchantErrorLabel],
) -> MerchantContextSummary:
    """Score all fixed context tiers once and return aggregate-only measurements."""

    reference_summary = validate_merchant_reference(population, selected_rows, references)
    validated_references = _validated_references(references)
    validated_packets = _validated_packets(packets)
    validated_indexes = _validated_index_records(index_records)
    validated_assertions = _validated_assertions(assertions)
    expected_count = _PILOT_ANCHOR_COUNT * len(CONTEXT_TIERS)

    if len(validated_packets) != expected_count or len(validated_indexes) != expected_count:
        raise MerchantContextError("merchant context coverage mismatch")
    packet_by_context = {packet.context_id: packet for packet in validated_packets}
    index_by_context = {index.context_id: index for index in validated_indexes}
    if (
        len(packet_by_context) != expected_count
        or len(index_by_context) != expected_count
        or packet_by_context.keys() != index_by_context.keys()
    ):
        raise MerchantContextError("merchant context coverage mismatch")

    selected_identities = {_identity(row) for row in selected_rows}
    actual_tier_anchors = {
        (index.tier, (packet.document_id, packet.anchor_row_id))
        for context_id, index in index_by_context.items()
        for packet in (packet_by_context[context_id],)
    }
    expected_tier_anchors = {
        (tier, identity) for tier in CONTEXT_TIERS for identity in selected_identities
    }
    if len(actual_tier_anchors) != expected_count or actual_tier_anchors != expected_tier_anchors:
        raise MerchantContextError("merchant context coverage mismatch")

    assertion_by_context = {assertion.context_id: assertion for assertion in validated_assertions}
    if (
        len(validated_assertions) != expected_count
        or len(assertion_by_context) != expected_count
        or assertion_by_context.keys() != index_by_context.keys()
    ):
        raise MerchantContextError("merchant assertion coverage mismatch")

    assertions_by_tier_anchor: dict[
        tuple[ContextTier, _RowIdentity], tuple[MerchantAssertion, MerchantContextPacket]
    ] = {}
    for context_id, index in index_by_context.items():
        packet = packet_by_context[context_id]
        assertion = assertion_by_context[context_id]
        if (
            assertion.document_id != packet.document_id
            or assertion.anchor_row_id != packet.anchor_row_id
        ):
            raise MerchantContextError("merchant assertion context mismatch")
        if not _assertion_evidence_is_available(assertion, packet):
            raise MerchantContextError("merchant assertion evidence mismatch")
        assertions_by_tier_anchor[(index.tier, _identity(assertion))] = assertion, packet

    transaction_references: dict[_TransactionIdentity, list[MerchantReference]] = {}
    nontransaction_references: list[MerchantReference] = []
    for reference in validated_references:
        if reference.disposition is ReferenceDisposition.NONTRANSACTION:
            nontransaction_references.append(reference)
        elif reference.disposition is ReferenceDisposition.TRANSACTION:
            if reference.owner_row_id is None:
                raise MerchantContextError("merchant reference contract mismatch")
            transaction_references.setdefault(
                (reference.document_id, reference.owner_row_id), []
            ).append(reference)

    row_transaction_owners: dict[_RowIdentity, _TransactionIdentity] = {}
    for transaction, owned_references in transaction_references.items():
        reference = owned_references[0]
        for owned_row_id in reference.owned_row_ids:
            row_transaction_owners[(reference.document_id, owned_row_id)] = transaction

    merchant_atom_owners: dict[tuple[str, str], set[_TransactionIdentity]] = {}
    merchant_region_owners: dict[tuple[str, BBox], set[_TransactionIdentity]] = {}
    for transaction, owned_references in transaction_references.items():
        reference = owned_references[0]
        for atom_id in reference.atom_ids:
            merchant_atom_owners.setdefault((reference.document_id, atom_id), set()).add(
                transaction
            )
        for region in reference.source_regions:
            merchant_region_owners.setdefault((reference.document_id, region), set()).add(
                transaction
            )

    preliminary_scores: dict[ContextTier, dict[_TransactionIdentity, _TransactionScore]] = {
        tier: {} for tier in CONTEXT_TIERS
    }
    atom_backed_exact_transactions: set[tuple[ContextTier, _TransactionIdentity]] = set()
    for tier in CONTEXT_TIERS:
        for transaction, owned_references in transaction_references.items():
            reference = owned_references[0]
            if reference.owner_row_id is None or reference.merchant_text is None:
                raise MerchantContextError("merchant reference contract mismatch")
            assertion_packets = tuple(
                assertions_by_tier_anchor[(tier, _identity(owned_reference))]
                for owned_reference in owned_references
            )
            foreign_evidence = False
            for assertion, _ in assertion_packets:
                foreign_evidence = foreign_evidence or any(
                    owners and transaction not in owners
                    for atom_id in assertion.atom_ids
                    for owners in (
                        merchant_atom_owners.get((assertion.document_id, atom_id), set()),
                    )
                )
                foreign_evidence = foreign_evidence or any(
                    transaction not in owners and _regions_overlap(asserted_region, merchant_region)
                    for asserted_region in assertion.source_regions
                    for (document_id, merchant_region), owners in merchant_region_owners.items()
                    if document_id == assertion.document_id
                )

            source_supported = all(
                _assertion_text_is_source_supported(assertion, packet)
                for assertion, packet in assertion_packets
            )
            merchant_assertion_packets = tuple(
                (assertion, packet)
                for assertion, packet in assertion_packets
                if assertion.disposition is AssertionDisposition.MERCHANT
            )
            all_merchant = all(
                assertion.disposition is AssertionDisposition.MERCHANT
                for assertion, _ in assertion_packets
            )
            owner_correct = all(
                assertion.owner_row_id == reference.owner_row_id
                for assertion, _ in merchant_assertion_packets
            )
            complete_text = all(
                assertion.merchant_text is not None
                and reference.merchant_text in assertion.merchant_text
                for assertion, _ in merchant_assertion_packets
            )
            attribution = (
                all_merchant
                and owner_correct
                and complete_text
                and source_supported
                and not foreign_evidence
            )
            exact_text = attribution and all(
                assertion.merchant_text == reference.merchant_text
                and assertion.atom_ids == reference.atom_ids
                and assertion.source_regions == reference.source_regions
                for assertion, _ in assertion_packets
            )
            if exact_text and all(
                _assertion_text_is_atom_supported(assertion, packet)
                for assertion, packet in assertion_packets
            ):
                atom_backed_exact_transactions.add((tier, transaction))
            omission = any(
                assertion.disposition is not AssertionDisposition.MERCHANT
                for assertion, _ in assertion_packets
            )
            hallucination = any(
                assertion.disposition is AssertionDisposition.MERCHANT
                and not _assertion_text_is_source_supported(assertion, packet)
                for assertion, packet in assertion_packets
            )
            ownership_error = not owner_correct or foreign_evidence
            different_transaction_owner = any(
                asserted_transaction is not None and asserted_transaction != transaction
                for assertion, _ in merchant_assertion_packets
                if assertion.owner_row_id is not None
                for asserted_transaction in (
                    row_transaction_owners.get((assertion.document_id, assertion.owner_row_id)),
                )
            )
            wrong_merchant = foreign_evidence or different_transaction_owner
            score = _TransactionScore(
                attribution,
                exact_text,
                omission,
                wrong_merchant,
                hallucination,
                ownership_error,
            )
            preliminary_scores[tier][transaction] = score

    validated_errors = _validated_error_labels(error_labels)
    error_by_tier_transaction = {
        (label.tier, (label.document_id, label.owner_row_id)): label for label in validated_errors
    }
    final_scores: dict[ContextTier, dict[_TransactionIdentity, _TransactionScore]] = {
        tier: {} for tier in CONTEXT_TIERS
    }
    for tier, preliminary_tier_scores in preliminary_scores.items():
        for transaction, score in preliminary_tier_scores.items():
            label = error_by_tier_transaction.get((tier, transaction))
            categories = set() if label is None else {label.primary, *label.secondary}
            atom_backed_exact = (tier, transaction) in atom_backed_exact_transactions
            unsupported_text = (
                MerchantErrorCategory.UNSUPPORTED_MERCHANT_TEXT in categories
                and not atom_backed_exact
            )
            neighboring_transaction_contamination = (
                MerchantErrorCategory.NEIGHBORING_TRANSACTION_CONTAMINATION in categories
                and not atom_backed_exact
            )
            attribution = (
                score.attribution
                and not unsupported_text
                and not neighboring_transaction_contamination
            )
            ancillary_substitution = (
                MerchantErrorCategory.MERCHANT_VERSUS_ANCILLARY in categories and not attribution
            )
            final_scores[tier][transaction] = _TransactionScore(
                attribution,
                score.exact_text and attribution,
                score.omission,
                score.wrong_merchant
                or ancillary_substitution
                or neighboring_transaction_contamination,
                score.hallucination or unsupported_text,
                score.ownership_error or neighboring_transaction_contamination,
            )

    expected_error_keys = {
        (tier, transaction)
        for tier, tier_scores in final_scores.items()
        for transaction, score in tier_scores.items()
        if not score.exact_text
    }
    if (
        len(error_by_tier_transaction) != len(validated_errors)
        or error_by_tier_transaction.keys() != expected_error_keys
    ):
        raise MerchantContextError("merchant error coverage mismatch")

    correct_sets = {
        tier: {transaction for transaction, score in tier_scores.items() if score.attribution}
        for tier, tier_scores in final_scores.items()
    }
    exact_sets = {
        tier: {transaction for transaction, score in tier_scores.items() if score.exact_text}
        for tier, tier_scores in final_scores.items()
    }

    tier_summaries: list[MerchantTierSummary] = []
    for tier in CONTEXT_TIERS:
        errors = tuple(
            label
            for (label_tier, _), label in error_by_tier_transaction.items()
            if label_tier is tier
        )
        error_counts = Counter(
            category for label in errors for category in (label.primary, *label.secondary)
        )
        scores = tuple(final_scores[tier].values())

        correct_nontransactions = sum(
            assertions_by_tier_anchor[(tier, _identity(reference))][0].disposition
            is AssertionDisposition.NONTRANSACTION
            for reference in nontransaction_references
        )
        correct_count = len(correct_sets[tier])
        exact_count = len(exact_sets[tier])
        wrong_count = sum(score.wrong_merchant for score in scores)
        hallucination_count = sum(score.hallucination for score in scores)
        tier_summaries.append(
            MerchantTierSummary(
                tier=tier,
                eligible_transactions=reference_summary.eligible_transaction_count,
                correct_attributions=correct_count,
                merchant_accuracy=_rate(
                    correct_count, reference_summary.eligible_transaction_count
                ),
                exact_text_matches=exact_count,
                exact_text_rate=_rate(exact_count, reference_summary.eligible_transaction_count),
                omissions=sum(score.omission for score in scores),
                wrong_merchants=wrong_count,
                hallucinations=hallucination_count,
                ownership_errors=sum(score.ownership_error for score in scores),
                nontransaction_anchors=reference_summary.nontransaction_anchor_count,
                correct_nontransaction_anchors=correct_nontransactions,
                errors=tuple(
                    MerchantErrorCount(category=category, count=error_counts[category])
                    for category in MerchantErrorCategory
                    if error_counts[category]
                ),
                safe=wrong_count == 0 and hallucination_count == 0,
            )
        )

    paired_deltas = tuple(
        _paired_delta(tier, CONTEXT_TIERS[index - 1], correct_sets, exact_sets)
        for index, tier in enumerate(CONTEXT_TIERS)
        if index > 0
    ) + tuple(
        _paired_delta(tier, ContextTier.C5_FULL_PAGE, correct_sets, exact_sets)
        for tier in CONTEXT_TIERS[:-1]
    )
    safe_tiers = tuple(summary.tier for summary in tier_summaries if summary.safe)
    has_eligible_transactions = reference_summary.eligible_transaction_count > 0
    if has_eligible_transactions and safe_tiers:
        attribution_best = tuple(
            tier
            for tier in safe_tiers
            if not any(correct_sets[tier] < correct_sets[other_tier] for other_tier in safe_tiers)
        )
        if any(
            correct_sets[tier] != correct_sets[attribution_best[0]] for tier in attribution_best[1:]
        ):
            recommended_tier = None
        else:
            exact_best = tuple(
                tier
                for tier in attribution_best
                if not any(
                    exact_sets[tier] < exact_sets[other_tier] for other_tier in attribution_best
                )
            )
            if any(exact_sets[tier] != exact_sets[exact_best[0]] for tier in exact_best[1:]):
                recommended_tier = None
            else:
                recommended_tier = exact_best[0]
    else:
        recommended_tier = None

    full_page_attributions = correct_sets[ContextTier.C5_FULL_PAGE]
    full_page_exact = exact_sets[ContextTier.C5_FULL_PAGE]
    bounded_tiers = CONTEXT_TIERS[: CONTEXT_TIERS.index(ContextTier.C3_HEADER_NEIGHBORHOOD) + 1]
    safe_tier_set = set(safe_tiers)
    hypothesis_supported = has_eligible_transactions and any(
        tier in safe_tier_set
        and correct_sets[tier] == full_page_attributions
        and exact_sets[tier] == full_page_exact
        for tier in bounded_tiers
    )
    context_interference = has_eligible_transactions and any(
        tier in safe_tier_set
        and (
            full_page_attributions < correct_sets[tier]
            or (full_page_attributions == correct_sets[tier] and full_page_exact < exact_sets[tier])
        )
        for tier in CONTEXT_TIERS[:-1]
    )
    hypothesis_falsified = (
        has_eligible_transactions
        and not hypothesis_supported
        and all(
            tier not in safe_tier_set
            or bool(full_page_attributions - correct_sets[tier])
            or bool(full_page_exact - exact_sets[tier])
            for tier in bounded_tiers
        )
    )
    return MerchantContextSummary(
        anchor_count=reference_summary.anchor_count,
        eligible_transaction_count=reference_summary.eligible_transaction_count,
        reference_ambiguity_count=reference_summary.ambiguous_anchor_count,
        nontransaction_anchor_count=reference_summary.nontransaction_anchor_count,
        tiers=tuple(tier_summaries),
        paired_deltas=paired_deltas,
        recommended_tier=recommended_tier,
        hypothesis_supported=hypothesis_supported,
        hypothesis_falsified=hypothesis_falsified,
        context_interference=context_interference,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def render_merchant_context_report(summary: MerchantContextSummary) -> str:
    """Render one privacy-safe aggregate Markdown result."""

    if not isinstance(summary, MerchantContextSummary):
        raise TypeError("merchant context report requires an aggregate summary")
    try:
        aggregate = MerchantContextSummary.model_validate(summary.model_dump())
    except ValidationError:
        raise MerchantContextError("merchant context summary contract mismatch") from None

    if aggregate.hypothesis_supported:
        outcome = "supported hypothesis"
    elif aggregate.hypothesis_falsified:
        outcome = "falsified hypothesis"
    elif aggregate.context_interference:
        outcome = "context interference"
    else:
        outcome = "validation stopped"
    recommended = (
        aggregate.recommended_tier.value if aggregate.recommended_tier is not None else "none"
    )
    interference = "true" if aggregate.context_interference else "false"
    result = (
        f"{outcome}; smallest best safe tier: {recommended}; context interference: {interference}"
    )
    lines = [
        "# Merchant Context Sufficiency Result",
        "",
        "## Task contract",
        "",
        (
            "Scope answer: YES — this changes or measures how spatial source context affects "
            "transaction-level merchant attribution."
        ),
        "Experiment: shared evaluation",
        (
            "Extraction hypothesis: A bounded transaction neighborhood plus visible table "
            "headers matches full-page merchant accuracy, while an isolated row crop does not."
        ),
        (
            "Measurement: transaction-level merchant-attribution accuracy, exact "
            "merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination "
            "count, ownership-error count, and paired accuracy delta by context tier"
        ),
        (
            "Fixed inputs: the frozen 100 training pilot row identities and source evidence "
            "only; all arms use the same reference cases, model, prompt, and decoding; "
            "validation, held-out data, current gold, accepted parser output, Reviewer A/B "
            "values, and experiment predictions remain closed"
        ),
        (
            "Smallest allowed files: CONTEXT.md; "
            "docs/superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md; "
            "docs/superpowers/plans/2026-08-07-merchant-context-sufficiency.md; "
            "docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; "
            "docs/experiments/row-extraction-program-status.md; "
            "experiments/row_extraction/merchant_context.py; "
            "tests/experiments/row_extraction/test_merchant_context.py; "
            "docs/experiments/row-extraction-merchant-context-report.md; and "
            "artifacts/merchant-context-sufficiency-v1/** (ignored private artifacts only)"
        ),
        (
            "Required output: a supported or falsified context-sufficiency hypothesis and the "
            "smallest context tier attaining the best observed safe merchant accuracy"
        ),
        (
            "Stop condition: stop before arm execution if merchant-bearing evidence is not "
            "operationally referenceable, an independent reference cannot be frozen first, an "
            "arm would expose prohibited data, or any declared context is truncated; stop "
            "after the single scoring run"
        ),
        "",
        "## Aggregate reference diagnostics",
        "",
        f"Reference ambiguity count: {aggregate.reference_ambiguity_count}",
        "",
        "## Aggregate arm results",
        "",
        (
            "| Tier | Eligible | Correct | Accuracy | Exact | Exact rate | Omissions | "
            "Omission rate | Wrong merchants | Hallucinations | Ownership errors | "
            "Nontransactions correct/total | Safe | Errors |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|",
    ]
    for tier in aggregate.tiers:
        error_text = ", ".join(f"{error.category.value}={error.count}" for error in tier.errors)
        lines.append(
            "| "
            + " | ".join(
                (
                    tier.tier.value,
                    str(tier.eligible_transactions),
                    str(tier.correct_attributions),
                    _decimal_text(tier.merchant_accuracy),
                    str(tier.exact_text_matches),
                    _decimal_text(tier.exact_text_rate),
                    str(tier.omissions),
                    _decimal_text(_rate(tier.omissions, tier.eligible_transactions)),
                    str(tier.wrong_merchants),
                    str(tier.hallucinations),
                    str(tier.ownership_errors),
                    (f"{tier.correct_nontransaction_anchors}/{tier.nontransaction_anchors}"),
                    "yes" if tier.safe else "no",
                    error_text or "none",
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Paired aggregate deltas",
            "",
            (
                "| Tier | Comparator | Attribution gains | Attribution losses | Exact gains | "
                "Exact losses |"
            ),
            "|---|---|---:|---:|---:|---:|",
        )
    )
    lines.extend(
        (
            f"| {delta.tier.value} | {delta.comparator.value} | "
            f"{delta.attribution_gains} | {delta.attribution_losses} | "
            f"{delta.exact_text_gains} | {delta.exact_text_losses} |"
        )
        for delta in aggregate.paired_deltas
    )
    lines.extend(
        (
            "",
            "## Result",
            "",
            f"Result: {result}",
            "",
            "## Limitations",
            "",
            "- This aggregate represents the single frozen scoring run.",
            "- Ambiguous references are excluded from merchant-accuracy denominators.",
            "- This experiment measures extraction only and does not change production parsing.",
            "",
            "## Metric-or-Stop",
            "",
            (
                "Scope: YES — measured the effect of nested source context on "
                "transaction-level merchant attribution"
            ),
            "Experiment: shared evaluation",
            (
                "Measurement: merchant-attribution accuracy, exact merchant-bearing-text rate, "
                "omission rate, wrong-merchant count, hallucination count, ownership-error "
                "count, and paired context-tier deltas"
            ),
            f"Result: {result}",
            "Next extraction task: STOP",
            "",
        )
    )
    return "\n".join(lines)


type _ContextPair = tuple[MerchantContextIndex, MerchantContextPacket]
type _RootClaim = tuple[Path, Path, int]

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def _opaque_digest(*parts: str) -> str:
    digest = hashlib.sha256()
    digest.update(_MATERIALIZER_VERSION.encode())
    for part in parts:
        encoded = part.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _bbox_is_valid(bbox: BBox) -> bool:
    x0, y0, x1, y1 = bbox
    return all(math.isfinite(value) for value in bbox) and x0 < x1 and y0 < y1


def _bbox_contains(outer: BBox, inner: BBox) -> bool:
    return (
        _bbox_is_valid(outer)
        and _bbox_is_valid(inner)
        and outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _bbox_union(bboxes: Sequence[BBox]) -> BBox:
    if not bboxes or any(not _bbox_is_valid(bbox) for bbox in bboxes):
        raise MerchantContextError("merchant context geometry unavailable")
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _page_bbox(anchor: FrozenRow) -> BBox:
    try:
        if not anchor.source_pdf.is_file():
            raise OSError
        with fitz.open(anchor.source_pdf) as document:
            if anchor.page_number > document.page_count:
                raise IndexError
            rect = document[anchor.page_number - 1].rect
            page_bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
    except Exception:
        raise MerchantContextError("merchant context geometry unavailable") from None
    if not _bbox_is_valid(page_bbox) or not _bbox_contains(page_bbox, anchor.bbox):
        raise MerchantContextError("merchant context geometry unavailable")
    return page_bbox


def _row_sort_key(row: FrozenRow) -> tuple[float, float, float, float, str]:
    return (*row.bbox, row.row_id)


def _population_index(
    population: Sequence[FrozenRow], anchor: FrozenRow
) -> tuple[dict[tuple[str, str], FrozenRow], tuple[FrozenRow, ...]]:
    rows_by_identity: dict[tuple[str, str], FrozenRow] = {}
    for row in population:
        identity = _identity(row)
        if identity in rows_by_identity:
            raise MerchantContextError("merchant context population mismatch")
        rows_by_identity[identity] = row
    population_anchor = rows_by_identity.get(_identity(anchor))
    if population_anchor != anchor:
        raise MerchantContextError("merchant context population mismatch")
    document_rows = tuple(row for row in population if row.document_id == anchor.document_id)
    if any(row.source_pdf != anchor.source_pdf for row in document_rows):
        raise MerchantContextError("merchant context population mismatch")
    page_rows = tuple(
        sorted(
            (row for row in document_rows if row.page_number == anchor.page_number),
            key=_row_sort_key,
        )
    )
    return rows_by_identity, page_rows


def _reciprocal_neighbor(
    row: FrozenRow,
    *,
    previous: bool,
    rows_by_identity: dict[tuple[str, str], FrozenRow],
    anchor: FrozenRow,
) -> FrozenRow | None:
    neighbor_id = row.previous_row_id if previous else row.next_row_id
    if neighbor_id is None:
        return None
    neighbor = rows_by_identity.get((row.document_id, neighbor_id))
    if (
        neighbor is None
        or neighbor.page_number != anchor.page_number
        or neighbor.source_pdf != anchor.source_pdf
    ):
        return None
    reciprocal_id = neighbor.next_row_id if previous else neighbor.previous_row_id
    if reciprocal_id != row.row_id:
        return None
    return neighbor


def _neighbor_rows(
    anchor: FrozenRow,
    rows_by_identity: dict[tuple[str, str], FrozenRow],
    distance: int,
) -> tuple[FrozenRow, ...]:
    predecessors: list[FrozenRow] = []
    current = anchor
    for _ in range(distance):
        neighbor = _reciprocal_neighbor(
            current,
            previous=True,
            rows_by_identity=rows_by_identity,
            anchor=anchor,
        )
        if neighbor is None:
            break
        predecessors.append(neighbor)
        current = neighbor

    successors: list[FrozenRow] = []
    current = anchor
    for _ in range(distance):
        neighbor = _reciprocal_neighbor(
            current,
            previous=False,
            rows_by_identity=rows_by_identity,
            anchor=anchor,
        )
        if neighbor is None:
            break
        successors.append(neighbor)
        current = neighbor

    return (*reversed(predecessors), anchor, *successors)


def _role_free_schema(row: FrozenRow) -> tuple[BBox, ...]:
    return tuple(band.bbox for band in row.column_bands)


def _rows_are_visible(rows: Sequence[FrozenRow], regions: Sequence[BBox], page_bbox: BBox) -> bool:
    return all(
        _bbox_contains(page_bbox, row.bbox)
        and any(_bbox_contains(region, row.bbox) for region in regions)
        and all(
            _bbox_contains(page_bbox, atom.bbox)
            and any(_bbox_contains(region, atom.bbox) for region in regions)
            for atom in row.atoms
        )
        for row in rows
    )


def _context_materials(
    anchor: FrozenRow,
    rows_by_identity: dict[tuple[str, str], FrozenRow],
    page_rows: tuple[FrozenRow, ...],
    page_bbox: BBox,
) -> tuple[tuple[tuple[FrozenRow, ...], tuple[BBox, ...]], ...]:
    c0_rows = (anchor,)
    c0_regions = (anchor.bbox,)
    c1_rows = _neighbor_rows(anchor, rows_by_identity, 1)
    c1_regions = (_bbox_union(tuple(row.bbox for row in c1_rows)),)
    c2_rows = _neighbor_rows(anchor, rows_by_identity, 2)
    c2_region = _bbox_union(tuple(row.bbox for row in c2_rows))
    c2_regions = (c2_region,)

    schema = _role_free_schema(anchor)
    c3_regions: tuple[BBox, ...] = c2_regions
    c4_rows = c2_rows
    c4_regions: tuple[BBox, ...] = c3_regions
    if schema:
        table_region = _bbox_union(schema)
        c4_rows = tuple(row for row in page_rows if _role_free_schema(row) == schema)
        first_table_row_top = min(row.bbox[1] for row in c4_rows)
        header_region = (
            table_region[0],
            table_region[1],
            table_region[2],
            first_table_row_top,
        )
        if _bbox_is_valid(header_region):
            c3_regions = (*c2_regions, header_region)
        c4_regions = (table_region,)
        c2_identities = {_identity(row) for row in c2_rows}
        if not c2_identities <= {_identity(row) for row in c4_rows} or any(
            not any(_bbox_contains(region, prior) for region in c4_regions) for prior in c3_regions
        ):
            raise MerchantContextError("merchant context geometry unavailable")

    materials = (
        (c0_rows, c0_regions),
        (c1_rows, c1_regions),
        (c2_rows, c2_regions),
        (c2_rows, c3_regions),
        (c4_rows, c4_regions),
        (page_rows, (page_bbox,)),
    )
    if any(
        not all(_bbox_contains(page_bbox, region) for region in regions)
        or not _rows_are_visible(rows, regions, page_bbox)
        for rows, regions in materials
    ):
        raise MerchantContextError("merchant context geometry unavailable")
    return materials


def _set_rgb_pixel(samples: bytearray, width: int, x: int, y: int) -> None:
    if x < 0 or y < 0 or x >= width or 3 * width * y >= len(samples):
        return
    offset = 3 * (width * y + x)
    samples[offset : offset + 3] = bytes(_ANCHOR_MARKER)


def _draw_anchor_marker(
    samples: bytearray,
    width: int,
    height: int,
    source_x: int,
    source_y: int,
    source_bbox: BBox,
    anchor_bbox: BBox,
) -> None:
    if not _bbox_contains(source_bbox, anchor_bbox):
        return
    anchor_pixels = (fitz.Rect(anchor_bbox) * fitz.Matrix(_RENDER_SCALE, _RENDER_SCALE)).irect
    anchor_left = _CANVAS_MARGIN + anchor_pixels.x0 - source_x
    anchor_top = _CANVAS_MARGIN + anchor_pixels.y0 - source_y
    anchor_right = _CANVAS_MARGIN + anchor_pixels.x1 - source_x
    anchor_bottom = _CANVAS_MARGIN + anchor_pixels.y1 - source_y
    marker_left = anchor_left - 1
    marker_top = anchor_top - 1
    marker_right = anchor_right
    marker_bottom = anchor_bottom
    for x in range(marker_left, marker_right + 1):
        _set_rgb_pixel(samples, width, x, marker_top)
        _set_rgb_pixel(samples, width, x, marker_bottom)
    for y in range(marker_top, marker_bottom + 1):
        _set_rgb_pixel(samples, width, marker_left, y)
        _set_rgb_pixel(samples, width, marker_right, y)
    if marker_bottom >= height or marker_right >= width:
        raise MerchantContextError("merchant context geometry unavailable")


def _render_context_image(
    *,
    source_pdf: Path,
    page_number: int,
    source_bbox: BBox,
    anchor_bbox: BBox,
    image_root: Path,
    relative_path: str,
) -> ContextImage:
    try:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError
        with fitz.open(source_pdf) as document:
            if page_number > document.page_count:
                raise IndexError
            page = document[page_number - 1]
            page_rect = page.rect
            page_bbox = (
                float(page_rect.x0),
                float(page_rect.y0),
                float(page_rect.x1),
                float(page_rect.y1),
            )
            if not _bbox_contains(page_bbox, source_bbox) or not _bbox_contains(
                page_bbox, anchor_bbox
            ):
                raise ValueError
            source = page.get_pixmap(
                matrix=fitz.Matrix(_RENDER_SCALE, _RENDER_SCALE),
                colorspace=fitz.csRGB,
                clip=fitz.Rect(source_bbox),
                alpha=False,
            )
        if source.width <= 0 or source.height <= 0 or source.n != 3:
            raise ValueError
        width = source.width + 2 * _CANVAS_MARGIN
        height = source.height + 2 * _CANVAS_MARGIN
        samples = bytearray([_CANVAS_NEUTRAL]) * (width * height * 3)
        source_samples = memoryview(source.samples)
        source_stride = source.width * 3
        for y in range(source.height):
            source_start = y * source_stride
            target_start = 3 * (width * (y + _CANVAS_MARGIN) + _CANVAS_MARGIN)
            samples[target_start : target_start + source_stride] = source_samples[
                source_start : source_start + source_stride
            ]
        _draw_anchor_marker(
            samples,
            width,
            height,
            source.x,
            source.y,
            source_bbox,
            anchor_bbox,
        )
        canvas = fitz.Pixmap(fitz.csRGB, width, height, bytes(samples), False)
        canvas.set_dpi(_RENDER_DPI, _RENDER_DPI)
        png_bytes = canvas.tobytes("png")
        destination = image_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(png_bytes)
            temporary_path.replace(destination)
        except BaseException:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
    except MerchantContextError:
        raise
    except Exception:
        raise MerchantContextError("merchant context geometry unavailable") from None
    return ContextImage(
        source_bbox=source_bbox,
        relative_path=relative_path,
        sha256=hashlib.sha256(png_bytes).hexdigest(),
        width=width,
        height=height,
    )


def materialize_anchor_contexts(
    population: Sequence[FrozenRow], anchor: FrozenRow, image_root: Path
) -> tuple[_ContextPair, ...]:
    """Materialize all six fixed spatial contexts for one opaque anchor."""

    page_bbox = _page_bbox(anchor)
    rows_by_identity, page_rows = _population_index(population, anchor)
    materials = _context_materials(anchor, rows_by_identity, page_rows, page_bbox)
    column_boundaries = _role_free_schema(anchor)
    result: list[_ContextPair] = []
    for tier, (rows, regions) in zip(CONTEXT_TIERS, materials, strict=True):
        context_id = _opaque_digest("context", anchor.document_id, anchor.row_id, tier.value)
        batch_id = _opaque_digest("batch", tier.value)
        images: list[ContextImage] = []
        for ordinal, region in enumerate(regions):
            image_id = _opaque_digest(
                "image",
                anchor.document_id,
                anchor.row_id,
                tier.value,
                str(ordinal),
                *(format(value, ".17g") for value in region),
            )
            relative_path = f"{context_id}/{image_id}.png"
            images.append(
                _render_context_image(
                    source_pdf=anchor.source_pdf,
                    page_number=anchor.page_number,
                    source_bbox=region,
                    anchor_bbox=anchor.bbox,
                    image_root=image_root,
                    relative_path=relative_path,
                )
            )
        packet = MerchantContextPacket(
            context_id=context_id,
            document_id=anchor.document_id,
            anchor_row_id=anchor.row_id,
            page_number=anchor.page_number,
            anchor_bbox=anchor.bbox,
            column_boundaries=column_boundaries,
            rows=tuple(
                MerchantContextRow(row_id=row.row_id, bbox=row.bbox, atoms=row.atoms)
                for row in rows
            ),
            images=tuple(images),
        )
        result.append(
            (
                MerchantContextIndex(
                    context_id=context_id,
                    tier=tier,
                    batch_id=batch_id,
                ),
                packet,
            )
        )
    return tuple(result)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _has_repository_marker(path: Path) -> bool:
    for ancestor in (path, *path.parents):
        marker = ancestor / ".git"
        try:
            marker_status = marker.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise MerchantContextError("merchant context repository status unavailable") from None
        if stat.S_ISREG(marker_status.st_mode) or stat.S_ISLNK(marker_status.st_mode):
            return True
        if not stat.S_ISDIR(marker_status.st_mode):
            continue
        try:
            (marker / "HEAD").lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise MerchantContextError("merchant context repository status unavailable") from None
        return True
    return False


def _is_ordinary_outside_git(repository: subprocess.CompletedProcess[str]) -> bool:
    if repository.returncode != 128 or repository.stdout.strip():
        return False
    errors = repository.stderr.splitlines()
    if errors == ["fatal: not a git repository (or any of the parent directories): .git"]:
        return True
    mount_prefix = "fatal: not a git repository (or any parent up to mount point "
    boundary_error = "Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set)."
    if len(errors) != 2 or errors[1] != boundary_error:
        return False
    mount_error = errors[0]
    if not mount_error.startswith(mount_prefix) or not mount_error.endswith(")"):
        return False
    return Path(mount_error[len(mount_prefix) : -1]).is_absolute()


def _root_is_outside_git_or_ignored(private_root: Path) -> bool:
    probe_directory = _nearest_existing_parent(private_root.parent)
    has_repository_marker = _has_repository_marker(probe_directory)
    git_environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    git_environment.update({"LANG": "C", "LANGUAGE": "C", "LC_ALL": "C"})
    try:
        repository = subprocess.run(
            ("git", "-C", str(probe_directory), "rev-parse", "--show-toplevel"),
            check=False,
            capture_output=True,
            text=True,
            env=git_environment,
        )
    except OSError:
        raise MerchantContextError("merchant context repository status unavailable") from None
    if repository.returncode != 0:
        if not has_repository_marker and _is_ordinary_outside_git(repository):
            return True
        raise MerchantContextError("merchant context repository status unavailable")
    try:
        if not repository.stdout.strip():
            raise ValueError
        repository_root = Path(repository.stdout.strip()).resolve(strict=True)
        if not repository_root.is_dir():
            raise ValueError
    except (OSError, ValueError):
        raise MerchantContextError("merchant context repository status unavailable") from None
    resolved_root = private_root.resolve(strict=False)
    try:
        resolved_root.relative_to(repository_root)
    except ValueError:
        return True
    try:
        ignored = subprocess.run(
            (
                "git",
                "-C",
                str(repository_root),
                "check-ignore",
                "--quiet",
                "--",
                str(resolved_root),
            ),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=git_environment,
        )
    except OSError:
        raise MerchantContextError("merchant context repository status unavailable") from None
    if ignored.returncode not in {0, 1}:
        raise MerchantContextError("merchant context repository status unavailable")
    return ignored.returncode == 0


def _validate_private_root(private_root: Path) -> None:
    if not private_root.is_absolute():
        raise MerchantContextError("merchant context root must be absolute")
    if private_root.name != _PRIVATE_ROOT_NAME:
        raise MerchantContextError("merchant context root name mismatch")
    for candidate in (private_root, *private_root.parents):
        if candidate.is_symlink():
            raise MerchantContextError("merchant context root must not be a symlink")
    if not _root_is_outside_git_or_ignored(private_root):
        raise MerchantContextError("merchant context root must be outside Git or ignored")
    if private_root.exists():
        if not private_root.is_dir() or any(private_root.iterdir()):
            raise MerchantContextError("merchant context root must be empty")
        raise MerchantContextError("merchant context root already exists")


def _release_root_claim(claim_path: Path, claim_file_descriptor: int) -> None:
    release_failed = False
    try:
        claim_status = os.fstat(claim_file_descriptor)
    except OSError:
        claim_status = None
        release_failed = True
    try:
        os.close(claim_file_descriptor)
    except OSError:
        release_failed = True
    if claim_status is not None:
        try:
            path_status = claim_path.stat(follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError:
            release_failed = True
        else:
            if (path_status.st_dev, path_status.st_ino) == (
                claim_status.st_dev,
                claim_status.st_ino,
            ):
                try:
                    claim_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    release_failed = True
            else:
                release_failed = True
    try:
        claim_path.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        release_failed = True
    else:
        release_failed = True
    if release_failed:
        raise MerchantContextError("merchant context root claim release failed")


def _cleanup_staging_root(staging_root: Path) -> None:
    try:
        shutil.rmtree(staging_root)
    except FileNotFoundError:
        pass
    except OSError:
        raise MerchantContextError("merchant context staging cleanup failed") from None
    try:
        staging_root.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise MerchantContextError("merchant context staging cleanup failed") from None
    raise MerchantContextError("merchant context staging cleanup failed")


def _rename_noreplace(staging_root: Path, private_root: Path) -> tuple[int, int]:
    renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(staging_root),
        _AT_FDCWD,
        os.fsencode(private_root),
        _RENAME_NOREPLACE,
    )
    return result, ctypes.get_errno()


def _publish_private_root(staging_root: Path, private_root: Path) -> None:
    try:
        result, error_number = _rename_noreplace(staging_root, private_root)
    except (AttributeError, OSError):
        raise MerchantContextError("merchant context root publication failed") from None
    if result == 0:
        return
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise MerchantContextError("merchant context root already exists")
    raise MerchantContextError("merchant context root publication failed")


def _claim_private_root(private_root: Path) -> _RootClaim:
    claim_path = private_root.with_name(f".{private_root.name}.claim")
    claim_file_descriptor: int | None = None
    staging_root: Path | None = None
    try:
        private_root.parent.mkdir(parents=True, exist_ok=True)
        claim_file_descriptor = os.open(
            claim_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except FileExistsError:
        raise MerchantContextError("merchant context root already exists") from None
    except OSError:
        raise MerchantContextError("merchant context root claim failed") from None

    try:
        _validate_private_root(private_root)
        staging_root = Path(
            tempfile.mkdtemp(
                prefix=f".{private_root.name}.",
                suffix=".staging",
                dir=private_root.parent,
            )
        )
        resolved_staging_root = staging_root.resolve(strict=True)
        _validate_private_root(private_root)
        if resolved_staging_root.parent != private_root.parent.resolve(strict=True):
            raise MerchantContextError("merchant context root claim failed")
        if not _root_is_outside_git_or_ignored(resolved_staging_root):
            raise MerchantContextError(
                "merchant context staging root must be outside Git or ignored"
            )
        staging_root = resolved_staging_root
    except BaseException:
        assert claim_file_descriptor is not None
        try:
            if staging_root is not None:
                _cleanup_staging_root(staging_root)
        finally:
            _release_root_claim(claim_path, claim_file_descriptor)
        raise
    assert claim_file_descriptor is not None
    assert staging_root is not None
    return staging_root, claim_path, claim_file_descriptor


def _validate_selected_pilot(
    population: Sequence[FrozenRow], selected_rows: Sequence[FrozenRow]
) -> tuple[FrozenRow, ...]:
    selected = tuple(selected_rows)
    selected_identities = tuple(_identity(row) for row in selected)
    if (
        len(selected) != _PILOT_ANCHOR_COUNT
        or len(set(selected_identities)) != _PILOT_ANCHOR_COUNT
        or any(row.split is not DatasetSplit.TRAIN for row in selected)
    ):
        raise MerchantContextError("merchant context pilot membership mismatch")
    try:
        expected = tuple(select_visual_gold_pilot(population))
    except Exception:
        raise MerchantContextError("merchant context pilot membership mismatch") from None
    if {_identity(row) for row in expected} != set(selected_identities):
        raise MerchantContextError("merchant context pilot membership mismatch")
    population_by_identity = {_identity(row): row for row in population}
    if any(population_by_identity.get(_identity(row)) != row for row in selected):
        raise MerchantContextError("merchant context pilot membership mismatch")
    return tuple(sorted(selected, key=_identity))


def materialize_merchant_contexts(
    population: Sequence[FrozenRow],
    selected_rows: Sequence[FrozenRow],
    private_root: Path,
) -> tuple[_ContextPair, ...]:
    """Write six opaque batches and the private tier index exactly once."""

    _validate_private_root(private_root)
    selected = _validate_selected_pilot(population, selected_rows)
    staging_root, claim_path, claim_file_descriptor = _claim_private_root(private_root)
    try:
        pairs = tuple(
            pair
            for anchor in selected
            for pair in materialize_anchor_contexts(
                population,
                anchor,
                staging_root / "images",
            )
        )
        ordered = tuple(sorted(pairs, key=lambda pair: (pair[0].batch_id, pair[0].context_id)))
        if len(ordered) != len(CONTEXT_TIERS) * _PILOT_ANCHOR_COUNT or len(
            {index.context_id for index, _ in ordered}
        ) != len(ordered):
            raise MerchantContextError("merchant context coverage mismatch")
        packet_root = staging_root / "packets"
        packet_root.mkdir()
        write_jsonl(
            staging_root / "context-index.jsonl",
            (index for index, _ in ordered),
        )
        batch_ids = tuple(sorted({index.batch_id for index, _ in ordered}))
        if len(batch_ids) != len(CONTEXT_TIERS):
            raise MerchantContextError("merchant context coverage mismatch")
        for batch_id in batch_ids:
            batch_packets = tuple(packet for index, packet in ordered if index.batch_id == batch_id)
            if len(batch_packets) != _PILOT_ANCHOR_COUNT:
                raise MerchantContextError("merchant context coverage mismatch")
            write_jsonl(packet_root / f"{batch_id}.jsonl", batch_packets)
        _publish_private_root(staging_root, private_root)
    except BaseException as error:
        try:
            _cleanup_staging_root(staging_root)
        finally:
            _release_root_claim(claim_path, claim_file_descriptor)
        if isinstance(error, MerchantContextError):
            raise
        raise MerchantContextError("merchant context materialization failed") from None
    _release_root_claim(claim_path, claim_file_descriptor)
    return ordered
