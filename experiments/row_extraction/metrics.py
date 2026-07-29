"""Deterministic shared metrics for fixed transaction-row extraction experiments."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext

from pydantic import Field, ValidationError

from experiments.row_extraction.contracts import (
    Decision,
    FieldProposal,
    FieldRole,
    GoldRow,
    OcrReference,
    RowPrediction,
    RowType,
    _FrozenModel,
)
from experiments.row_extraction.evidence import (
    EvidenceContractError,
    render_proposal,
    resolve_proposal,
)

type _Identity = tuple[str, str]
type _ReferenceKey = tuple[str, str, FieldRole]
type _Outcome = tuple[Decimal, bool]

_DECIMAL_PRECISION = 28
_CALIBRATION_BIN_COUNT = 10
_LOG_LOSS_EPSILON = Decimal("1e-15")
_RISK_TARGETS = (Decimal("0.001"), Decimal("0.005"), Decimal("0.01"))

DESCRIPTION_NORMALIZATION_VERSION = "description-nfc-casefold-whitespace-v1"


class ScoringInputError(ValueError):
    """Scoring input violates the common contract without exposing private values."""


class FieldMetric(_FrozenModel):
    role: FieldRole
    eligible_rows: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    normalized_matches: int = Field(ge=0)
    omissions: int = Field(ge=0)
    hallucinations: int = Field(ge=0)
    exact_rate: Decimal
    normalized_rate: Decimal
    omission_rate: Decimal
    hallucination_rate: Decimal


class RowTypeMetric(_FrozenModel):
    row_type: RowType
    precision: Decimal
    recall: Decimal
    f1: Decimal
    support: int = Field(ge=0)


class ConfusionCell(_FrozenModel):
    gold: RowType
    predicted: RowType
    count: int = Field(ge=0)


class CalibrationBin(_FrozenModel):
    lower: Decimal
    upper: Decimal
    count: int = Field(ge=0)
    mean_confidence: Decimal | None
    empirical_accuracy: Decimal | None


class RiskCoveragePoint(_FrozenModel):
    threshold: Decimal
    coverage: Decimal
    selective_risk: Decimal
    accepted_rows: int = Field(ge=0)


class RiskTargetCoverage(_FrozenModel):
    target_risk: Decimal
    coverage: Decimal


class MetricReport(_FrozenModel):
    row_count: int = Field(ge=0)
    exact_rows: int = Field(ge=0)
    exact_row_rate: Decimal
    row_type_correct: int = Field(ge=0)
    row_type_accuracy: Decimal
    row_type_macro_f1: Decimal
    row_types: tuple[RowTypeMetric, ...]
    row_type_confusion: tuple[ConfusionCell, ...]
    fields: Mapping[FieldRole, FieldMetric]
    accepted_rows: int = Field(ge=0)
    abstained_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    ignored_rows: int = Field(ge=0)
    unsupported_evidence: int = Field(ge=0)
    ownership_collisions: int = Field(ge=0)
    ocr_cer: Decimal | None
    ocr_wer: Decimal | None
    calibration_bins: tuple[CalibrationBin, ...]
    brier_score: Decimal | None
    log_loss: Decimal | None
    expected_calibration_error: Decimal | None
    risk_coverage: tuple[RiskCoveragePoint, ...]
    area_under_risk_coverage: Decimal | None
    coverage_at_risk: tuple[RiskTargetCoverage, ...]


class _FieldCounts:
    def __init__(self) -> None:
        self.eligible_rows = 0
        self.exact_matches = 0
        self.normalized_matches = 0
        self.omissions = 0
        self.hallucinations = 0


def _ratio(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        return Decimal(numerator) / Decimal(denominator)


def _sum(values: Sequence[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        return sum(values, start=Decimal(0))


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return _ratio(_sum(values), len(values))


def _identity(record: GoldRow | RowPrediction | OcrReference) -> _Identity:
    return record.document_id, record.row_id


def _validated[ContractModel: (GoldRow, RowPrediction, OcrReference)](
    record: ContractModel,
    model: type[ContractModel],
    message: str,
) -> ContractModel:
    try:
        validated = model.model_validate(record.model_dump(mode="python"))
    except (AttributeError, TypeError, ValidationError, ValueError) as error:
        raise ScoringInputError(message) from error
    return validated


def _bbox_is_valid(bbox: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = bbox
    return all(math.isfinite(value) for value in bbox) and x0 < x1 and y0 < y1


def _validate_gold(record: GoldRow) -> GoldRow:
    validated = _validated(record, GoldRow, "invalid gold input")
    roles = tuple(field.role for field in validated.fields)
    if len(roles) != len(set(roles)):
        raise ScoringInputError("invalid gold input")
    if any(
        field.source_region is not None and not _bbox_is_valid(field.source_region)
        for field in validated.fields
    ):
        raise ScoringInputError("invalid gold input")
    return validated


def _validate_prediction(record: RowPrediction) -> RowPrediction:
    validated = _validated(record, RowPrediction, "invalid prediction input")
    confidence = validated.exact_row_confidence
    finite_scores = (
        (confidence is None or math.isfinite(confidence))
        and all(math.isfinite(atom.confidence) for atom in validated.evidence_atoms)
        and all(math.isfinite(proposal.raw_score) for proposal in validated.proposals)
    )
    finite_boxes = all(_bbox_is_valid(atom.bbox) for atom in validated.evidence_atoms) and all(
        proposal.source_region is None or _bbox_is_valid(proposal.source_region)
        for proposal in validated.proposals
    )
    if not finite_scores or not finite_boxes:
        raise ScoringInputError("invalid prediction input")
    return validated


def _validate_reference(record: OcrReference) -> OcrReference:
    validated = _validated(record, OcrReference, "invalid OCR reference input")
    if not _bbox_is_valid(validated.source_region):
        raise ScoringInputError("invalid OCR reference input")
    return validated


def _index_gold(gold: Sequence[GoldRow]) -> dict[_Identity, GoldRow]:
    indexed: dict[_Identity, GoldRow] = {}
    for raw_record in gold:
        record = _validate_gold(raw_record)
        identity = _identity(record)
        if identity in indexed:
            raise ScoringInputError("duplicate gold identity")
        indexed[identity] = record
    return indexed


def _index_predictions(predictions: Sequence[RowPrediction]) -> dict[_Identity, RowPrediction]:
    indexed: dict[_Identity, RowPrediction] = {}
    for raw_record in predictions:
        record = _validate_prediction(raw_record)
        identity = _identity(record)
        if identity in indexed:
            raise ScoringInputError("duplicate prediction identity")
        indexed[identity] = record
    return indexed


def _canonical_owner(prediction: RowPrediction, proposal: FieldProposal) -> str:
    return prediction.row_id if proposal.owner_row_id is None else proposal.owner_row_id


def _resolved_fields(
    prediction: RowPrediction,
) -> tuple[dict[FieldRole, str], frozenset[FieldRole], int, int]:
    if prediction.decision is not Decision.ACCEPT:
        return {}, frozenset(), 0, 0

    grouped: dict[FieldRole, list[FieldProposal]] = {}
    for proposal in prediction.proposals:
        grouped.setdefault(proposal.role, []).append(proposal)

    resolved: dict[FieldRole, str] = {}
    present: set[FieldRole] = set()
    unsupported = 0
    ownership_collisions = 0
    for role in FieldRole:
        proposals = grouped.get(role, [])
        if not proposals:
            continue
        present.add(role)
        if any(
            proposal.owner_row_id is not None and not proposal.owner_row_id.strip()
            for proposal in proposals
        ):
            unsupported += 1
            continue
        if len(proposals) != 1:
            unsupported += 1
            owners = {_canonical_owner(prediction, proposal) for proposal in proposals}
            ownership_collisions += int(len(owners) > 1)
            continue
        try:
            resolved[role] = resolve_proposal(prediction, proposals[0]).canonical_value
        except EvidenceContractError:
            unsupported += 1
    return resolved, frozenset(present), unsupported, ownership_collisions


def _normalize_description(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).casefold()
    return unicodedata.normalize("NFC", " ".join(normalized.split()))


def _field_metrics(
    gold: Mapping[_Identity, GoldRow],
    predictions: Mapping[_Identity, RowPrediction],
) -> tuple[dict[FieldRole, FieldMetric], dict[_Identity, bool], int, int]:
    counts = {role: _FieldCounts() for role in FieldRole}
    exact_outcomes: dict[_Identity, bool] = {}
    unsupported_evidence = 0
    ownership_collisions = 0

    for identity in sorted(gold):
        label = gold[identity]
        prediction = predictions[identity]
        expected = {field.role: field for field in label.fields}
        resolved, present, unsupported, collisions = _resolved_fields(prediction)
        unsupported_evidence += unsupported
        ownership_collisions += collisions

        fields_exact = not unsupported and set(present) == set(expected)
        for role in FieldRole:
            metric = counts[role]
            gold_field = expected.get(role)
            if gold_field is not None:
                metric.eligible_rows += 1
                if role not in present:
                    metric.omissions += 1
                predicted_value = resolved.get(role)
                if predicted_value == gold_field.canonical_value:
                    metric.exact_matches += 1
                    metric.normalized_matches += 1
                elif predicted_value is not None:
                    metric.hallucinations += 1
                    if role is FieldRole.DESCRIPTION and _normalize_description(
                        predicted_value
                    ) == _normalize_description(gold_field.canonical_value):
                        metric.normalized_matches += 1
                if predicted_value != gold_field.canonical_value:
                    fields_exact = False
            elif role in present:
                metric.hallucinations += 1
                fields_exact = False

        exact_outcomes[identity] = (
            prediction.decision is Decision.ACCEPT
            and prediction.predicted_type is label.row_type
            and fields_exact
        )

    result: dict[FieldRole, FieldMetric] = {}
    row_count = len(gold)
    for role in FieldRole:
        count = counts[role]
        result[role] = FieldMetric(
            role=role,
            eligible_rows=count.eligible_rows,
            exact_matches=count.exact_matches,
            normalized_matches=count.normalized_matches,
            omissions=count.omissions,
            hallucinations=count.hallucinations,
            exact_rate=_ratio(count.exact_matches, count.eligible_rows),
            normalized_rate=_ratio(count.normalized_matches, count.eligible_rows),
            omission_rate=_ratio(count.omissions, count.eligible_rows),
            hallucination_rate=_ratio(count.hallucinations, row_count),
        )
    return result, exact_outcomes, unsupported_evidence, ownership_collisions


def _row_type_metrics(
    gold: Mapping[_Identity, GoldRow],
    predictions: Mapping[_Identity, RowPrediction],
) -> tuple[tuple[RowTypeMetric, ...], tuple[ConfusionCell, ...], int, Decimal]:
    confusion = {
        (gold_type, predicted_type): 0 for gold_type in RowType for predicted_type in RowType
    }
    for identity, label in gold.items():
        confusion[(label.row_type, predictions[identity].predicted_type)] += 1

    metrics: list[RowTypeMetric] = []
    correct = 0
    for row_type in RowType:
        true_positive = confusion[(row_type, row_type)]
        predicted_count = sum(confusion[(gold_type, row_type)] for gold_type in RowType)
        support = sum(confusion[(row_type, predicted_type)] for predicted_type in RowType)
        precision = _ratio(true_positive, predicted_count)
        recall = _ratio(true_positive, support)
        f1 = _ratio(2 * true_positive, predicted_count + support)
        metrics.append(
            RowTypeMetric(
                row_type=row_type,
                precision=precision,
                recall=recall,
                f1=f1,
                support=support,
            )
        )
        correct += true_positive

    cells = tuple(
        ConfusionCell(gold=gold_type, predicted=predicted_type, count=confusion[key])
        for key in confusion
        for gold_type, predicted_type in (key,)
    )
    macro_f1 = _ratio(_sum(tuple(metric.f1 for metric in metrics)), len(RowType))
    return tuple(metrics), cells, correct, macro_f1


def _decimal_confidence(value: float | Decimal) -> Decimal:
    confidence = Decimal(str(value))
    if not confidence.is_finite() or not Decimal(0) <= confidence <= Decimal(1):
        raise ScoringInputError("invalid confidence input")
    return confidence


def risk_coverage(
    outcomes: Sequence[tuple[float | Decimal, bool]],
    *,
    total_rows: int | None = None,
) -> tuple[RiskCoveragePoint, ...]:
    """Return tie-grouped selective risk points in descending confidence order."""

    converted: list[_Outcome] = []
    for confidence, exact in outcomes:
        if type(exact) is not bool:
            raise ScoringInputError("invalid risk outcome input")
        converted.append((_decimal_confidence(confidence), exact))
    denominator = len(converted) if total_rows is None else total_rows
    if denominator < len(converted) or denominator < 0:
        raise ScoringInputError("invalid risk coverage denominator")
    if denominator == 0:
        return ()

    converted.sort(key=lambda outcome: outcome[0], reverse=True)
    accepted = 0
    wrong = 0
    points: list[RiskCoveragePoint] = []
    index = 0
    while index < len(converted):
        threshold = converted[index][0]
        tied: list[_Outcome] = []
        while index < len(converted) and converted[index][0] == threshold:
            tied.append(converted[index])
            index += 1
        accepted += len(tied)
        wrong += sum(not exact for _, exact in tied)
        points.append(
            RiskCoveragePoint(
                threshold=threshold,
                coverage=_ratio(accepted, denominator),
                selective_risk=_ratio(wrong, accepted),
                accepted_rows=accepted,
            )
        )
    return tuple(points)


def _calibration(
    outcomes: Sequence[_Outcome],
) -> tuple[
    tuple[CalibrationBin, ...],
    Decimal | None,
    Decimal | None,
    Decimal | None,
]:
    grouped: list[list[_Outcome]] = [[] for _ in range(_CALIBRATION_BIN_COUNT)]
    for confidence, exact in outcomes:
        index = min(int(confidence * _CALIBRATION_BIN_COUNT), _CALIBRATION_BIN_COUNT - 1)
        grouped[index].append((confidence, exact))

    bins: list[CalibrationBin] = []
    for index, members in enumerate(grouped):
        confidences = tuple(confidence for confidence, _ in members)
        accuracy = _ratio(sum(exact for _, exact in members), len(members)) if members else None
        bins.append(
            CalibrationBin(
                lower=_ratio(index, _CALIBRATION_BIN_COUNT),
                upper=_ratio(index + 1, _CALIBRATION_BIN_COUNT),
                count=len(members),
                mean_confidence=_mean(confidences),
                empirical_accuracy=accuracy,
            )
        )
    if not outcomes:
        return tuple(bins), None, None, None

    brier_terms = tuple((confidence - Decimal(int(exact))) ** 2 for confidence, exact in outcomes)
    log_terms: list[Decimal] = []
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        for confidence, exact in outcomes:
            observed_probability = confidence if exact else Decimal(1) - confidence
            log_terms.append(-max(observed_probability, _LOG_LOSS_EPSILON).ln())

    ece_terms = tuple(
        _ratio(bin_.count, len(outcomes))
        * abs((bin_.empirical_accuracy or Decimal(0)) - (bin_.mean_confidence or Decimal(0)))
        for bin_ in bins
        if bin_.count
    )
    return (
        tuple(bins),
        _mean(brier_terms),
        _mean(tuple(log_terms)),
        _sum(ece_terms),
    )


def _area_under_curve(points: Sequence[RiskCoveragePoint]) -> Decimal | None:
    if not points:
        return None
    area = Decimal(0)
    previous_coverage = Decimal(0)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        for point in points:
            area += (point.coverage - previous_coverage) * point.selective_risk
            previous_coverage = point.coverage
    return area


def _coverage_at_risk(
    points: Sequence[RiskCoveragePoint],
) -> tuple[RiskTargetCoverage, ...]:
    return tuple(
        RiskTargetCoverage(
            target_risk=target,
            coverage=max(
                (point.coverage for point in points if point.selective_risk <= target),
                default=Decimal(0),
            ),
        )
        for target in _RISK_TARGETS
    )


def _edit_distance[EditItem](
    reference: Sequence[EditItem],
    hypothesis: Sequence[EditItem],
) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_item in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hypothesis_index] + 1,
                    previous[hypothesis_index - 1] + int(reference_item != hypothesis_item),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> Decimal:
    """Return code-point edit distance divided by ``max(1, len(reference))``."""

    return _ratio(_edit_distance(reference, hypothesis), max(1, len(reference)))


def word_error_rate(reference: str, hypothesis: str) -> Decimal:
    """Return whitespace-token edit distance divided by ``max(1, reference words)``."""

    reference_words = tuple(reference.split())
    hypothesis_words = tuple(hypothesis.split())
    return _ratio(
        _edit_distance(reference_words, hypothesis_words),
        max(1, len(reference_words)),
    )


def _regions_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return min(first[2], second[2]) > max(first[0], second[0]) and min(first[3], second[3]) > max(
        first[1], second[1]
    )


def _proposal_matches_reference(
    prediction: RowPrediction,
    proposal: FieldProposal,
    reference: OcrReference,
) -> bool:
    if proposal.source_region is not None:
        return proposal.source_region == reference.source_region
    ledger = {atom.atom_id: atom for atom in prediction.evidence_atoms}
    return all(
        atom_id in ledger and _regions_overlap(ledger[atom_id].bbox, reference.source_region)
        for atom_id in proposal.atom_ids
    )


def _ocr_rates(
    references: Sequence[OcrReference],
    gold: Mapping[_Identity, GoldRow],
    predictions: Mapping[_Identity, RowPrediction],
) -> tuple[Decimal | None, Decimal | None]:
    indexed: dict[_ReferenceKey, OcrReference] = {}
    full_identities: set[tuple[str, str, FieldRole, tuple[float, float, float, float]]] = set()
    for raw_reference in references:
        reference = _validate_reference(raw_reference)
        identity = _identity(reference)
        label = gold.get(identity)
        if label is None or reference.role not in {field.role for field in label.fields}:
            raise ScoringInputError("unknown OCR reference identity")
        full_identity = (
            reference.document_id,
            reference.row_id,
            reference.role,
            reference.source_region,
        )
        if full_identity in full_identities:
            raise ScoringInputError("duplicate OCR reference identity")
        full_identities.add(full_identity)
        key = (reference.document_id, reference.row_id, reference.role)
        if key in indexed:
            raise ScoringInputError("ambiguous OCR reference identity")
        indexed[key] = reference

    character_edits = 0
    character_units = 0
    word_edits = 0
    word_units = 0
    eligible = 0
    for key in sorted(indexed, key=lambda item: (item[0], item[1], item[2].value)):
        reference = indexed[key]
        prediction = predictions[_identity(reference)]
        proposals = tuple(
            proposal for proposal in prediction.proposals if proposal.role is reference.role
        )
        if len(proposals) != 1 or not _proposal_matches_reference(
            prediction, proposals[0], reference
        ):
            continue
        try:
            hypothesis = render_proposal(prediction, proposals[0])
        except EvidenceContractError:
            continue
        eligible += 1
        reference_words = tuple(reference.verbatim_text.split())
        hypothesis_words = tuple(hypothesis.split())
        character_edits += _edit_distance(reference.verbatim_text, hypothesis)
        character_units += max(1, len(reference.verbatim_text))
        word_edits += _edit_distance(reference_words, hypothesis_words)
        word_units += max(1, len(reference_words))
    if not eligible:
        return None, None
    return _ratio(character_edits, character_units), _ratio(word_edits, word_units)


def score_predictions(
    gold: Sequence[GoldRow],
    predictions: Sequence[RowPrediction],
    ocr_references: Sequence[OcrReference] = (),
) -> MetricReport:
    """Score one complete prediction set without consulting any external truth source."""

    gold_by_id = _index_gold(gold)
    predictions_by_id = _index_predictions(predictions)
    if set(gold_by_id) != set(predictions_by_id):
        raise ScoringInputError("prediction identities do not match gold identities")

    fields, exact_outcomes, unsupported, collisions = _field_metrics(gold_by_id, predictions_by_id)
    row_types, confusion, row_type_correct, macro_f1 = _row_type_metrics(
        gold_by_id, predictions_by_id
    )
    exact_rows = sum(exact_outcomes.values())
    row_count = len(gold_by_id)

    confidence_outcomes = tuple(
        (
            _decimal_confidence(prediction.exact_row_confidence),
            exact_outcomes[identity],
        )
        for identity, prediction in sorted(predictions_by_id.items())
        if prediction.exact_row_confidence is not None
    )
    calibration_bins, brier, log_loss, ece = _calibration(confidence_outcomes)
    selective_outcomes = tuple(
        (
            _decimal_confidence(prediction.exact_row_confidence),
            exact_outcomes[identity],
        )
        for identity, prediction in sorted(predictions_by_id.items())
        if prediction.decision is Decision.ACCEPT and prediction.exact_row_confidence is not None
    )
    selective_points = risk_coverage(selective_outcomes, total_rows=row_count)
    ocr_cer, ocr_wer = _ocr_rates(ocr_references, gold_by_id, predictions_by_id)

    decisions = tuple(prediction.decision for prediction in predictions_by_id.values())
    return MetricReport(
        row_count=row_count,
        exact_rows=exact_rows,
        exact_row_rate=_ratio(exact_rows, row_count),
        row_type_correct=row_type_correct,
        row_type_accuracy=_ratio(row_type_correct, row_count),
        row_type_macro_f1=macro_f1,
        row_types=row_types,
        row_type_confusion=confusion,
        fields=fields,
        accepted_rows=decisions.count(Decision.ACCEPT),
        abstained_rows=decisions.count(Decision.ABSTAIN),
        rejected_rows=decisions.count(Decision.REJECT),
        ignored_rows=decisions.count(Decision.IGNORE),
        unsupported_evidence=unsupported,
        ownership_collisions=collisions,
        ocr_cer=ocr_cer,
        ocr_wer=ocr_wer,
        calibration_bins=calibration_bins,
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=ece,
        risk_coverage=selective_points,
        area_under_risk_coverage=_area_under_curve(selective_points),
        coverage_at_risk=_coverage_at_risk(selective_points),
    )
