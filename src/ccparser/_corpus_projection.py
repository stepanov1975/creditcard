"""Incremental structural projection policy for corpus manifests."""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from ccparser.models import (
    EvidenceReference,
    StatementResult,
    Status,
    Transaction,
    TransactionCategory,
)
from ccparser.output import _canonical_json_value_bytes

type PresentFieldPath = Literal[
    "category",
    "conversion_date",
    "description",
    "foreign_exchange.exchange_rate",
    "foreign_exchange.fee_discount",
    "foreign_exchange.fee_percentage",
    "foreign_exchange.gross_fee",
    "foreign_exchange.net_fee",
    "installment_current",
    "installment_total",
    "original_amount",
    "original_currency",
    "posting_date",
    "transaction_date",
]
type _GroupProjection = tuple[str, str, str, tuple[str, ...]]
type _TransactionIdentity = tuple[str, tuple[str, ...]]
type _EvidenceReferenceProjection = tuple[int, tuple[float, float, float, float], str]
type _EvidenceSiteProjection = tuple[str, tuple[_EvidenceReferenceProjection, ...]]


@dataclass(frozen=True, slots=True)
class StructuralCounts:
    """Neutral scalar counts produced by one structural projection pass."""

    documents: int
    reconciled: int
    unreconciled: int
    unsupported: int
    not_statement: int
    groups: int
    row_results: int
    transactions: int
    ambiguous_transactions: int
    ambiguity_occurrences: int
    evidence_references: int
    present_fields: tuple[tuple[PresentFieldPath, int], ...]


@dataclass(frozen=True, slots=True)
class StructuralProjection:
    """Counts and canonical structural digests for a statement stream."""

    counts: StructuralCounts
    ordered_status_digest: str
    group_structure_digest: str
    transaction_identity_digest: str
    field_presence_digest: str
    evidence_provenance_digest: str
    ambiguity_digest: str


@dataclass(frozen=True, slots=True)
class _StatementStructuralProjection:
    status: str
    groups: tuple[_GroupProjection, ...]
    transaction_identities: tuple[_TransactionIdentity, ...]
    field_presence: tuple[tuple[PresentFieldPath, ...], ...]
    evidence_provenance: tuple[tuple[_EvidenceSiteProjection, ...], ...]
    ambiguities: tuple[tuple[str, ...], ...]
    row_results: int
    evidence_references: int


class _CanonicalArrayDigest:
    """Incrementally hash the canonical JSON grammar for one array."""

    def __init__(self, prefix: bytes = b"[", suffix: bytes = b"]\n") -> None:
        self._digest = sha256()
        self._digest.update(prefix)
        self._suffix = suffix
        self._has_value = False

    def append(self, value: object) -> None:
        if self._has_value:
            self._digest.update(b",")
        self._digest.update(_canonical_json_value_bytes(value)[:-1])
        self._has_value = True

    def hexdigest(self) -> str:
        completed = self._digest.copy()
        completed.update(self._suffix)
        return completed.hexdigest()


def _digest_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _transaction_present_fields(transaction: Transaction) -> tuple[PresentFieldPath, ...]:
    present: list[PresentFieldPath] = []
    if transaction.category is not TransactionCategory.UNKNOWN:
        present.append("category")
    if transaction.conversion_date is not None:
        present.append("conversion_date")
    if transaction.description is not None:
        present.append("description")
    if transaction.installment_current is not None:
        present.append("installment_current")
    if transaction.installment_total is not None:
        present.append("installment_total")
    if transaction.original_amount is not None:
        present.append("original_amount")
    if transaction.original_currency is not None:
        present.append("original_currency")
    if transaction.posting_date is not None:
        present.append("posting_date")
    if transaction.transaction_date is not None:
        present.append("transaction_date")

    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            present.append("foreign_exchange.exchange_rate")
        if details.fee_discount is not None:
            present.append("foreign_exchange.fee_discount")
        if details.fee_percentage is not None:
            present.append("foreign_exchange.fee_percentage")
        if details.gross_fee is not None:
            present.append("foreign_exchange.gross_fee")
        if details.net_fee is not None:
            present.append("foreign_exchange.net_fee")
    return tuple(sorted(present))


def _project_evidence_reference(
    reference: EvidenceReference,
) -> _EvidenceReferenceProjection:
    raw_text_digest = _digest_bytes(
        unicodedata.normalize("NFC", reference.raw_text).encode("utf-8")
    )
    return reference.page_number, reference.bbox, raw_text_digest


def _project_evidence_site(
    path: str,
    references: tuple[EvidenceReference, ...],
) -> _EvidenceSiteProjection:
    return path, tuple(_project_evidence_reference(reference) for reference in references)


def _transaction_evidence_provenance(
    transaction: Transaction,
) -> tuple[_EvidenceSiteProjection, ...]:
    sites = [_project_evidence_site("evidence", transaction.evidence)]
    details = transaction.foreign_exchange
    if details is not None:
        if details.exchange_rate is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.exchange_rate",
                    details.exchange_rate.evidence,
                )
            )
        if details.fee_discount is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_discount",
                    details.fee_discount.evidence,
                )
            )
        if details.fee_percentage is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.fee_percentage",
                    details.fee_percentage.evidence,
                )
            )
        if details.gross_fee is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.gross_fee",
                    details.gross_fee.evidence,
                )
            )
        if details.net_fee is not None:
            sites.append(
                _project_evidence_site(
                    "foreign_exchange.net_fee",
                    details.net_fee.evidence,
                )
            )
    return tuple(sorted(sites, key=lambda item: item[0]))


def _project_statement(statement: StatementResult) -> _StatementStructuralProjection:
    transaction_identities: list[_TransactionIdentity] = []
    field_presence: list[tuple[PresentFieldPath, ...]] = []
    evidence_provenance: list[tuple[_EvidenceSiteProjection, ...]] = []
    ambiguities: list[tuple[str, ...]] = []
    evidence_reference_count = 0

    for transaction in statement.transactions:
        transaction_identities.append(
            (transaction.transaction_id, transaction.reconciliation_group_ids)
        )
        field_presence.append(_transaction_present_fields(transaction))
        transaction_evidence = _transaction_evidence_provenance(transaction)
        evidence_provenance.append(transaction_evidence)
        evidence_reference_count += sum(len(references) for _, references in transaction_evidence)
        ambiguities.append(transaction.ambiguities)

    return _StatementStructuralProjection(
        status=statement.status.value,
        groups=tuple(
            (group.group_id, group.currency, group.status.value, group.transaction_ids)
            for group in statement.groups
        ),
        transaction_identities=tuple(transaction_identities),
        field_presence=tuple(field_presence),
        evidence_provenance=tuple(evidence_provenance),
        ambiguities=tuple(ambiguities),
        row_results=len(statement.row_results),
        evidence_references=evidence_reference_count,
    )


def project_statement_stream(
    batch_status: Status,
    statements: Iterable[StatementResult],
) -> StructuralProjection:
    """Project one source-ordered statement stream with bounded memory."""

    ordered_status_digest = _CanonicalArrayDigest(
        prefix=b"[" + _canonical_json_value_bytes(batch_status.value)[:-1] + b",[",
        suffix=b"]]\n",
    )
    group_structure_digest = _CanonicalArrayDigest()
    transaction_identity_digest = _CanonicalArrayDigest()
    field_presence_digest = _CanonicalArrayDigest()
    evidence_provenance_digest = _CanonicalArrayDigest()
    ambiguity_digest = _CanonicalArrayDigest()
    statuses: Counter[str] = Counter()
    present_field_counts: Counter[PresentFieldPath] = Counter()
    documents = 0
    groups = 0
    row_results = 0
    transactions = 0
    ambiguous_transactions = 0
    ambiguity_occurrences = 0
    evidence_references = 0

    for statement in statements:
        projection = _project_statement(statement)
        del statement
        documents += 1
        statuses[projection.status] += 1
        groups += len(projection.groups)
        row_results += projection.row_results
        transactions += len(projection.transaction_identities)
        ambiguous_transactions += sum(bool(value) for value in projection.ambiguities)
        ambiguity_occurrences += sum(len(value) for value in projection.ambiguities)
        evidence_references += projection.evidence_references
        present_field_counts.update(
            path for transaction_fields in projection.field_presence for path in transaction_fields
        )

        ordered_status_digest.append(projection.status)
        group_structure_digest.append(projection.groups)
        transaction_identity_digest.append(projection.transaction_identities)
        field_presence_digest.append(projection.field_presence)
        evidence_provenance_digest.append(projection.evidence_provenance)
        ambiguity_digest.append(projection.ambiguities)
        del projection

    return StructuralProjection(
        counts=StructuralCounts(
            documents=documents,
            reconciled=statuses[Status.RECONCILED.value],
            unreconciled=statuses[Status.UNRECONCILED.value],
            unsupported=statuses[Status.UNSUPPORTED.value],
            not_statement=statuses[Status.NOT_STATEMENT.value],
            groups=groups,
            row_results=row_results,
            transactions=transactions,
            ambiguous_transactions=ambiguous_transactions,
            ambiguity_occurrences=ambiguity_occurrences,
            evidence_references=evidence_references,
            present_fields=tuple(
                (path, present_field_counts[path]) for path in sorted(present_field_counts)
            ),
        ),
        ordered_status_digest=ordered_status_digest.hexdigest(),
        group_structure_digest=group_structure_digest.hexdigest(),
        transaction_identity_digest=transaction_identity_digest.hexdigest(),
        field_presence_digest=field_presence_digest.hexdigest(),
        evidence_provenance_digest=evidence_provenance_digest.hexdigest(),
        ambiguity_digest=ambiguity_digest.hexdigest(),
    )


__all__ = ["StructuralCounts", "StructuralProjection", "project_statement_stream"]
