from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

import ccparser.audit as audit_module
from ccparser.audit import AuditAction, AuditApplyError, audit_directory
from ccparser.discovery import DocumentClassification, StatementDiscovery
from ccparser.evidence import DocumentEvidence


def _discovery(
    classification: DocumentClassification,
    confidence: float,
    *reason_codes: str,
) -> StatementDiscovery:
    return StatementDiscovery(
        classification=classification,
        confidence=confidence,
        reason_codes=reason_codes,
    )


_STATEMENT = _discovery(
    DocumentClassification.STATEMENT,
    0.95,
    "transaction_table_with_compatible_total",
)
_FORM = _discovery(
    DocumentClassification.NOT_STATEMENT,
    0.95,
    "positive_non_statement_form_evidence",
)
_AMBIGUOUS = _discovery(
    DocumentClassification.AMBIGUOUS,
    0.3,
    "insufficient_positive_evidence",
)


def _dependencies(
    classifications: dict[bytes, StatementDiscovery],
) -> tuple[
    Callable[[Path], DocumentEvidence],
    Callable[[DocumentEvidence], StatementDiscovery],
]:
    by_sha = {
        hashlib.sha256(content).hexdigest(): discovery
        for content, discovery in classifications.items()
    }

    def extractor(path: Path) -> DocumentEvidence:
        content = path.read_bytes()
        if content == b"corrupt":
            raise ValueError("synthetic corrupt detail must not leak")
        return DocumentEvidence(source_sha256=hashlib.sha256(content).hexdigest(), pages=())

    def classifier(evidence: DocumentEvidence) -> StatementDiscovery:
        return by_sha[evidence.source_sha256]

    return extractor, classifier


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_audit_directory_dry_run_is_deterministic_positive_only_and_immutable(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = input_dir / "quarantine"
    _write(input_dir / "b-form.PDF", b"form")
    _write(input_dir / "a-statement.pdf", b"statement")
    _write(input_dir / "nested" / "unclear.pdf", b"unclear")
    _write(input_dir / ".cache" / "ignored.pdf", b"form")
    outside = tmp_path / "outside.pdf"
    _write(outside, b"form")
    (input_dir / "linked.pdf").symlink_to(outside)
    extractor, classifier = _dependencies(
        {b"form": _FORM, b"statement": _STATEMENT, b"unclear": _AMBIGUOUS}
    )

    report = audit_directory(
        input_dir,
        quarantine_dir,
        extractor=extractor,
        classifier=classifier,
    )

    assert tuple(decision.original_relative_path for decision in report.decisions) == (
        "a-statement.pdf",
        "b-form.PDF",
        "nested/unclear.pdf",
    )
    assert tuple(decision.action for decision in report.decisions) == (
        AuditAction.KEEP,
        AuditAction.QUARANTINE,
        AuditAction.REVIEW,
    )
    assert report.applied is False
    assert report.moved_count == 0
    assert not quarantine_dir.exists()
    assert (input_dir / "b-form.PDF").is_file()


def test_audit_directory_reviews_low_confidence_nonstatement_and_corrupt_pdf(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    _write(input_dir / "corrupt.pdf", b"corrupt")
    _write(input_dir / "weak.pdf", b"weak")
    weak = _discovery(
        DocumentClassification.NOT_STATEMENT,
        0.89,
        "positive_non_statement_form_evidence",
    )
    extractor, classifier = _dependencies({b"weak": weak})

    report = audit_directory(
        input_dir,
        tmp_path / "quarantine",
        extractor=extractor,
        classifier=classifier,
    )

    assert all(decision.action is AuditAction.REVIEW for decision in report.decisions)
    corrupt, weak_decision = report.decisions
    assert corrupt.reason_codes == ("extraction_error",)
    assert "synthetic" not in " ".join(corrupt.reason_codes)
    assert weak_decision.reason_codes == (
        "positive_non_statement_form_evidence",
        "non_statement_confidence_below_threshold",
    )


def test_audit_directory_reports_classifier_failure_without_error_detail(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _write(input_dir / "unknown.pdf", b"valid")
    extractor, _ = _dependencies({b"valid": _AMBIGUOUS})

    def failing_classifier(evidence: DocumentEvidence) -> StatementDiscovery:
        del evidence
        raise RuntimeError("sensitive classifier detail")

    report = audit_directory(
        input_dir,
        tmp_path / "quarantine",
        extractor=extractor,
        classifier=failing_classifier,
    )

    assert report.decisions[0].action is AuditAction.REVIEW
    assert report.decisions[0].reason_codes == ("classification_error",)


def test_audit_apply_moves_nested_duplicate_basenames_writes_canonical_manifest_and_is_idempotent(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = input_dir / "quarantine"
    _write(input_dir / "a" / "form.pdf", b"first-form")
    _write(input_dir / "b" / "form.pdf", b"second-form")
    _write(input_dir / "statement.pdf", b"statement")
    extractor, classifier = _dependencies(
        {b"first-form": _FORM, b"second-form": _FORM, b"statement": _STATEMENT}
    )

    first = audit_directory(
        input_dir,
        quarantine_dir,
        apply=True,
        extractor=extractor,
        classifier=classifier,
    )
    manifest_path = quarantine_dir / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    second = audit_directory(
        input_dir,
        quarantine_dir,
        apply=True,
        extractor=extractor,
        classifier=classifier,
    )

    assert first.applied is True
    assert first.moved_count == 2
    assert (quarantine_dir / "a" / "form.pdf").read_bytes() == b"first-form"
    assert (quarantine_dir / "b" / "form.pdf").read_bytes() == b"second-form"
    assert not (input_dir / "a" / "form.pdf").exists()
    assert second.moved_count == 0
    assert second.decisions == first.decisions
    assert manifest_path.read_bytes() == manifest_before
    payload = json.loads(manifest_before)
    assert tuple(entry["original_relative_path"] for entry in payload["entries"]) == (
        "a/form.pdf",
        "b/form.pdf",
    )
    canonical = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    assert manifest_before == canonical
    assert all(
        set(entry)
        == {
            "classification",
            "confidence",
            "original_relative_path",
            "quarantine_relative_path",
            "reason_codes",
            "sha256",
        }
        for entry in payload["entries"]
    )


def test_audit_apply_uses_collision_safe_destination_without_overwrite(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = input_dir / "quarantine"
    content = b"form-content"
    _write(input_dir / "nested" / "form.pdf", content)
    _write(quarantine_dir / "nested" / "form.pdf", b"unrelated-existing")
    extractor, classifier = _dependencies({content: _FORM})

    report = audit_directory(
        input_dir,
        quarantine_dir,
        apply=True,
        extractor=extractor,
        classifier=classifier,
    )

    expected_name = f"form-{hashlib.sha256(content).hexdigest()[:12]}.pdf"
    assert (quarantine_dir / "nested" / "form.pdf").read_bytes() == b"unrelated-existing"
    assert (quarantine_dir / "nested" / expected_name).read_bytes() == content
    quarantine_decision = next(
        decision for decision in report.decisions if decision.action is AuditAction.QUARANTINE
    )
    assert quarantine_decision.quarantine_relative_path == f"nested/{expected_name}"


def test_audit_apply_rolls_back_all_moves_from_call_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    _write(input_dir / "a.pdf", b"form-a")
    _write(input_dir / "b.pdf", b"form-b")
    extractor, classifier = _dependencies({b"form-a": _FORM, b"form-b": _FORM})
    real_move = audit_module._move_file
    calls = 0

    def failing_move(source: Path, destination: Path, expected_sha256: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic move failure")
        real_move(source, destination, expected_sha256)

    monkeypatch.setattr(audit_module, "_move_file", failing_move)

    with pytest.raises(AuditApplyError, match="audit apply failed"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=extractor,
            classifier=classifier,
        )

    assert (input_dir / "a.pdf").read_bytes() == b"form-a"
    assert (input_dir / "b.pdf").read_bytes() == b"form-b"
    assert not (quarantine_dir / "a.pdf").exists()
    assert not (quarantine_dir / "manifest.json").exists()


def test_audit_apply_aborts_if_source_mutates_after_classification(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    source = input_dir / "form.pdf"
    _write(source, b"form-before")

    def mutating_extractor(path: Path) -> DocumentEvidence:
        original = path.read_bytes()
        path.write_bytes(b"form-after")
        return DocumentEvidence(source_sha256=hashlib.sha256(original).hexdigest(), pages=())

    with pytest.raises(AuditApplyError, match="source changed before move"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=mutating_extractor,
            classifier=lambda evidence: _FORM,
        )

    assert source.read_bytes() == b"form-after"
    assert not (quarantine_dir / "manifest.json").exists()


def test_apply_source_hash_mismatch_is_fatal_before_any_move(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    _write(input_dir / "a-mismatch.pdf", b"mismatch")
    _write(input_dir / "b-form.pdf", b"form")

    def mismatching_extractor(path: Path) -> DocumentEvidence:
        content = path.read_bytes()
        source_hash = "0" * 64 if content == b"mismatch" else hashlib.sha256(content).hexdigest()
        return DocumentEvidence(source_sha256=source_hash, pages=())

    with pytest.raises(AuditApplyError, match="extraction source hash mismatch"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=mismatching_extractor,
            classifier=lambda evidence: _FORM,
        )

    assert (input_dir / "a-mismatch.pdf").is_file()
    assert (input_dir / "b-form.pdf").is_file()
    assert not quarantine_dir.exists()


def test_mutation_after_pre_move_hash_is_detected_before_source_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    source = input_dir / "form.pdf"
    _write(source, b"stable-form")
    extractor, classifier = _dependencies({b"stable-form": _FORM})
    real_copy = audit_module._copy_and_hash

    def mutating_copy(source_file: object, destination_file: object) -> str:
        copied_hash = real_copy(source_file, destination_file)
        source.write_bytes(b"mutated-during-move")
        return copied_hash

    monkeypatch.setattr(audit_module, "_copy_and_hash", mutating_copy)

    with pytest.raises(AuditApplyError, match="source changed during move"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=extractor,
            classifier=classifier,
        )

    assert source.read_bytes() == b"mutated-during-move"
    assert not (quarantine_dir / "form.pdf").exists()


def test_rollback_does_not_depend_on_cross_filesystem_os_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    _write(input_dir / "a.pdf", b"form-a")
    _write(input_dir / "b.pdf", b"form-b")
    extractor, classifier = _dependencies({b"form-a": _FORM, b"form-b": _FORM})
    real_move = audit_module._move_file
    real_replace = audit_module.os.replace
    calls = 0

    def failing_second_move(source: Path, destination: Path, expected_sha256: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic second move failure")
        real_move(source, destination, expected_sha256)

    def exdev_for_pdf(source: Path | str, destination: Path | str) -> None:
        if Path(source).suffix.casefold() == ".pdf":
            raise OSError(18, "cross-device link")
        real_replace(source, destination)

    monkeypatch.setattr(audit_module, "_move_file", failing_second_move)
    monkeypatch.setattr(audit_module.os, "replace", exdev_for_pdf)

    with pytest.raises(AuditApplyError, match="audit apply failed"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=extractor,
            classifier=classifier,
        )

    assert (input_dir / "a.pdf").read_bytes() == b"form-a"
    assert (input_dir / "b.pdf").read_bytes() == b"form-b"
    assert not (quarantine_dir / "a.pdf").exists()


def test_rollback_continues_after_audit_apply_error_restoring_earlier_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    _write(input_dir / "a.pdf", b"form-a")
    _write(input_dir / "b.pdf", b"form-b")
    _write(input_dir / "c.pdf", b"form-c")
    extractor, classifier = _dependencies({b"form-a": _FORM, b"form-b": _FORM, b"form-c": _FORM})
    real_move = audit_module._move_file
    calls = 0

    def failing_move(source: Path, destination: Path, expected_sha256: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic forward failure")
        if calls == 4:
            raise AuditApplyError("synthetic first restoration failure")
        real_move(source, destination, expected_sha256)

    monkeypatch.setattr(audit_module, "_move_file", failing_move)

    with pytest.raises(AuditApplyError, match="rollback could not restore every source"):
        audit_directory(
            input_dir,
            quarantine_dir,
            apply=True,
            extractor=extractor,
            classifier=classifier,
        )

    assert (input_dir / "a.pdf").read_bytes() == b"form-a"
    assert not (quarantine_dir / "a.pdf").exists()
    assert (quarantine_dir / "b.pdf").read_bytes() == b"form-b"
    assert (input_dir / "c.pdf").read_bytes() == b"form-c"


def test_sensitive_classifier_reason_is_redacted_from_report_and_manifest(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    quarantine_dir = tmp_path / "quarantine"
    _write(input_dir / "form.pdf", b"form")
    extractor, _ = _dependencies({b"form": _FORM})
    sensitive = "private-account-123456"
    discovery = _discovery(
        DocumentClassification.NOT_STATEMENT,
        0.99,
        "positive_non_statement_form_evidence",
        sensitive,
    )

    report = audit_directory(
        input_dir,
        quarantine_dir,
        apply=True,
        extractor=extractor,
        classifier=lambda evidence: discovery,
    )

    reasons = tuple(str(reason) for reason in report.decisions[0].reason_codes)
    manifest_bytes = (quarantine_dir / "manifest.json").read_bytes()
    assert sensitive not in reasons
    assert sensitive.encode() not in manifest_bytes
    assert "classifier_reason_redacted" in reasons


def test_audit_rejects_unsafe_containment_and_skips_quarantine_tree(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _write(input_dir / "source.pdf", b"statement")
    extractor, classifier = _dependencies({b"statement": _STATEMENT, b"form": _FORM})

    with pytest.raises(ValueError, match="quarantine directory must not contain input"):
        audit_directory(
            input_dir,
            input_dir,
            extractor=extractor,
            classifier=classifier,
        )

    quarantine_dir = input_dir / "quarantine"
    _write(quarantine_dir / "already-there.pdf", b"form")
    report = audit_directory(
        input_dir,
        quarantine_dir,
        extractor=extractor,
        classifier=classifier,
    )

    assert tuple(decision.original_relative_path for decision in report.decisions) == (
        "source.pdf",
    )
