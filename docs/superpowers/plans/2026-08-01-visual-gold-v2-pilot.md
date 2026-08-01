# Visual-Gold v2 Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and measure one frozen, blind, dual-reviewed 100-row visual-gold v2 training pilot without exposing current gold or experiment predictions to reviewers.

**Architecture:** Keep the current `FrozenRow` and `GoldRow` contracts. Add only a subset annotation validator, deterministic pilot selection and sanitized review packets, deterministic crop/page-context rendering, and a privacy-safe agreement/defect comparator. All row images, packets, reviewer labels, disagreements, adjudication, and derived values stay in the ignored private artifact tree; Git receives only code, tests, protocol text, and aggregate counts/rates.

**Tech Stack:** Python 3.13, Pydantic v2, PyMuPDF, existing canonical JSONL codecs, pytest, Ruff, mypy, Codex visual inspection.

## Global Constraints

- Implement only the 100-row pilot authorized by `docs/superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md`.
- Do not review the remaining 2,403 training rows in this plan. A passing pilot may name that work as the next extraction task, but it requires a separate implementation plan.
- Do not change any of the four extractors, frozen row identity, row geometry, atoms, split membership, existing gold, or Round 1 results.
- Do not add a CLI, generalized controller, workflow service, schema family, receipt chain, attestation, replay, cache, or production integration.
- Do not add eligible exact-row scoring yet. It is unnecessary to answer the pilot hypothesis and belongs to a later plan only after the pilot passes.
- Reviewers may inspect only sanitized packets, exact crops, and the pre-rendered page context when necessary. They must not inspect current gold, accepted parser values, baseline type, semantic column roles, or any experiment prediction.
- Use `Decimal` for every rate and threshold. Aggregate tracked output must contain no row identity, filename, atom text, canonical value, transaction value, or financial data.
- Run the focused test first after every red/green change. Before every code or tracked-report commit, run all four required repository gates:

  ```bash
  .venv/bin/ruff format --check .
  .venv/bin/ruff check .
  .venv/bin/mypy src
  .venv/bin/pytest -q
  ```

- If a required measurement is not produced, stop instead of adding support work.

## Private Artifact Layout

Use this ignored layout under the existing private row-experiment root:

```text
visual-gold-v2/
  pilot-v1/
    packets.jsonl
    crops/
    page-contexts/
    reviewer-a.jsonl
    reviewer-b.jsonl
    comparison.jsonl
    reviewer-c.jsonl
    adjudicated-gold.jsonl
    current-gold-defects.jsonl
```

`packets.jsonl` may contain opaque document/row identities because it is private. None of these files may be staged or committed.

---

### Task 1: Commit the pilot authority and exact review protocol

**Task contract**

```text
Scope answer: YES — this authorizes and defines a measured 100-row extraction-supervision pilot.
Experiment: shared evaluation
Extraction hypothesis: Two independent crop-first visual reviews can agree on row type at least 95% and on exact field values at least 90%, showing that a visually reconstructed candidate is stable enough to measure current-label defects.
Measurement: pre-adjudication row-type agreement, field exact agreement, evidence-support agreement, and annotation validity
Fixed inputs: the frozen 2,503-row training split, existing frozen row artifacts, approved visual-gold v2 design, and no validation/test rows
Smallest allowed files: docs/superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-visual-gold-v2-protocol.md
Required output: committed charter amendment and runnable written pilot protocol with predeclared gates
Stop condition: stop if the authority cannot be amended without changing an extractor, opening held-out data, or creating shared workflow infrastructure
```

**Files:**

- Modify: `docs/superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md`
- Modify: `docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md`
- Modify: `docs/experiments/row-extraction-program-status.md`
- Create: `docs/experiments/row-extraction-visual-gold-v2-protocol.md`

- [ ] Change the visual-gold v2 design status from “Approved conversational design; implementation remains blocked…” to “Approved for the 100-row pilot on 2026-08-01; promotion and full-review execution remain conditional.” Do not alter the approved substance.

- [ ] Append the exact “Proposed charter amendment” from the approved design to the charter. Explicitly state that current gold remains authoritative and that learned visual reviewers produce only a parallel candidate.

- [ ] Replace the program status active phase with “Visual-gold v2 100-row training pilot.” Set the next allowed task to this pilot and copy the task contract above into the status document.

- [ ] Write the candidate protocol with these fixed definitions:

  - selector version: `visual-gold-v2-pilot-v1`;
  - source class: a row is OCR-source when at least one frozen atom has `source="ocr"`; otherwise all atoms must be digital; an empty or unknown-source row fails selection;
  - exact quota stages: structural 1, ambiguous 1, OCR primary 10, 1–3-atom continuation 15, 4–9-atom continuation 10, 4–9-atom digital primary 14, 10+-atom continuation 23, and 10+-atom digital primary 26;
  - stable row order key: SHA-256 of UTF-8 `version + "\\0" + document_id + "\\0" + row_id`, then `(document_id, row_id)` as a collision tie-breaker;
  - no more than two selected rows per document; any unsatisfied stage fails closed;
  - Reviewer A and B blind prompt, with page context opened only when crop evidence is insufficient;
  - Reviewer C disagreement-only prompt;
  - natural human RTL/mixed-direction canonicalization rules;
  - row-type denominator 100 and threshold `Decimal("0.95")`;
  - field-slot union denominator and threshold `Decimal("0.90")`;
  - evidence support measured over roles present in both reviews, separately for atom-ID tuples and source regions;
  - exact private filenames from “Private Artifact Layout” above;
  - fail/stop behavior and the exact Metric-or-Stop report template at the end of this plan.

- [ ] Confirm no private identity or value entered the diff:

  ```bash
  git diff --check
  git diff -- docs/superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md docs/experiments/row-extraction-program-status.md docs/experiments/row-extraction-visual-gold-v2-protocol.md
  ```

- [ ] Run the four repository gates and commit:

  ```bash
  git add docs/superpowers/specs/2026-08-01-visual-gold-v2-candidate-design.md docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md docs/experiments/row-extraction-program-status.md docs/experiments/row-extraction-visual-gold-v2-protocol.md
  git commit -m "docs: authorize visual gold v2 pilot"
  ```

---

### Task 2: Validate an exact labeled subset against the full frozen population

**Task contract**

```text
Scope answer: YES — this makes the named pilot annotation-valid without requiring labels for unselected rows.
Experiment: shared evaluation
Extraction hypothesis: Pilot labels can be validated against frozen geometry, evidence, and reciprocal adjacency while leaving nonpilot labels unread.
Measurement: annotation validity and exact selected-row coverage
Fixed inputs: complete frozen training rows, exactly 100 selected row identities, and one blind reviewer label per selected identity
Smallest allowed files: experiments/row_extraction/annotations.py; tests/experiments/row_extraction/test_annotations.py
Required output: a focused subset validator that returns privacy-safe coverage counts or fails closed
Stop condition: stop if subset validity requires reading current gold or weakening same-row evidence, geometry, canonical-value, or reciprocal-adjacency checks
```

**Files:**

- Modify: `tests/experiments/row_extraction/test_annotations.py`
- Modify: `experiments/row_extraction/annotations.py`

- [ ] Add failing tests for this exact public interface:

  ```python
  def validate_annotation_subset(
      population: Iterable[FrozenRow],
      selected_rows: Iterable[FrozenRow],
      labels: Iterable[GoldRow],
  ) -> AnnotationSummary:
      ...
  ```

  Cover: exact one-label-per-selected-row coverage; unknown/missing/duplicate selected identity; selected row differing from the population record; labels outside the selected set; all existing field/canonical/geometry checks; and a continuation whose unselected predecessor exists in the population and points back reciprocally.

- [ ] Add a test proving subset continuation validation does not require or read the predecessor’s gold label, plus fail-closed tests for missing and nonreciprocal frozen predecessors.

- [ ] Run the focused test and confirm the expected import/test failure:

  ```bash
  .venv/bin/pytest -q tests/experiments/row_extraction/test_annotations.py
  ```

- [ ] Implement `validate_annotation_subset` by reusing `_index_rows`, field support, field relationships, and summary construction. Factor only the smallest private helpers needed. Do not change `validate_annotations` complete-dataset behavior.

- [ ] For a subset continuation, require a fixed predecessor in `population`, matching document identity, and reciprocal `predecessor.next_row_id == row.row_id`; do not assert semantic chain termination because predecessor labels are intentionally absent.

- [ ] Export the new function, rerun the focused test, then run all four repository gates.

- [ ] Commit only the validator and tests:

  ```bash
  git add experiments/row_extraction/annotations.py tests/experiments/row_extraction/test_annotations.py
  git commit -m "feat: validate visual gold subsets"
  ```

---

### Task 3: Render deterministic bounded page context

**Task contract**

```text
Scope answer: YES — this supplies bounded visual evidence needed to disambiguate row extraction labels.
Experiment: shared evaluation
Extraction hypothesis: A deterministic one-page context image can resolve crop-only uncertainty without changing the exact row crop.
Measurement: runnable visual evidence artifact with fixed page and row geometry
Fixed inputs: selected FrozenRow source PDF, page number, row bbox, and render version
Smallest allowed files: experiments/row_extraction/crops.py; tests/experiments/row_extraction/test_crops.py
Required output: deterministic context render record and image for a selected row
Stop condition: stop if context requires changing source PDFs, row boxes, or adding a rendering/controller subsystem
```

**Files:**

- Modify: `tests/experiments/row_extraction/test_crops.py`
- Modify: `experiments/row_extraction/crops.py`

- [ ] Add failing tests for:

  ```python
  class PageContextRecord(_FrozenModel):
      document_id: str
      row_id: str
      page_number: int
      row_bbox: BBox
      relative_path: str
      sha256: str
      width: int
      height: int

  def render_page_context(row: FrozenRow, private_root: Path) -> PageContextRecord:
      ...
  ```

  Require a 150-DPI RGB PPM of exactly the source page, deterministic bytes, an opaque path based only on document/row identity, and the unchanged row bbox in the record. Test absent page, invalid row bbox, and source-render failure.

- [ ] Run the focused crop tests and confirm failure:

  ```bash
  .venv/bin/pytest -q tests/experiments/row_extraction/test_crops.py
  ```

- [ ] Implement with the existing `_atomic_write` and PyMuPDF handling. Do not modify `render_reference_crop`; do not pad, recrop, or replace the exact 300-DPI row image.

- [ ] Rerun focused tests and all four repository gates.

- [ ] Commit:

  ```bash
  git add experiments/row_extraction/crops.py tests/experiments/row_extraction/test_crops.py
  git commit -m "feat: render visual review page context"
  ```

---

### Task 4: Select and materialize sanitized pilot packets

**Task contract**

```text
Scope answer: YES — this fixes the 100 rows and source evidence used to measure blind extraction-label agreement.
Experiment: shared evaluation
Extraction hypothesis: A deterministic 100-row training sample can meet the declared row-type, source, atom-count, and document-coverage strata without reviewer leakage.
Measurement: exact selector quota counts and reviewer-material leakage checks
Fixed inputs: all and only the frozen 2,503 training rows and selector version visual-gold-v2-pilot-v1
Smallest allowed files: experiments/row_extraction/visual_gold_pilot.py; tests/experiments/row_extraction/test_visual_gold_pilot.py
Required output: deterministic 100-row membership and private sanitized review packets with exact crops and context paths
Stop condition: stop if any quota cannot be satisfied under the two-rows-per-document cap or if packets require baseline type, semantic band roles, current gold, parser values, or predictions
```

**Files:**

- Create: `tests/experiments/row_extraction/test_visual_gold_pilot.py`
- Create: `experiments/row_extraction/visual_gold_pilot.py`

- [ ] Add failing selector tests for this interface:

  ```python
  PILOT_SELECTOR_VERSION = "visual-gold-v2-pilot-v1"

  class PilotSelectionError(ValueError):
      ...

  def select_visual_gold_pilot(
      rows: Sequence[FrozenRow],
  ) -> tuple[FrozenRow, ...]:
      ...
  ```

  Build a synthetic feasible population and assert: 100 unique training rows; row-type counts 50/48/1/1; OCR/digital counts 10/90; at least 15 rows with 1–3 atoms; at least 25 with 4–9; all others 10+; maximum two rows per document; byte-for-byte stable membership after input permutation.

- [ ] Add tests for nontraining input, empty atoms, duplicate identity, missing rare stratum, insufficient category quota, and document-cap conflict. Also prove that a mixed digital/OCR row is classified as OCR-source because at least one atom is OCR. Error messages must contain no row text, filename, or canonical value.

- [ ] Run the new test and confirm failure:

  ```bash
  .venv/bin/pytest -q tests/experiments/row_extraction/test_visual_gold_pilot.py
  ```

- [ ] Implement the exact staged quotas and stable hash from Task 1. Track per-document counts across stages. Return selected rows in final stable-hash order. Fail closed on any unsatisfied invariant.

- [ ] Add failing tests for immutable narrow packet records:

  ```python
  class VisualReviewPacket(_FrozenModel):
      document_id: str
      row_id: str
      page_number: int
      row_bbox: BBox
      previous_row_id: str | None
      next_row_id: str | None
      column_boundaries: tuple[BBox, ...]
      atoms: tuple[EvidenceAtom, ...]
      crop_relative_path: str
      crop_sha256: str
      page_context_relative_path: str
      page_context_sha256: str

  class VisualReviewDecision(_FrozenModel):
      label: GoldRow
      page_context_used: bool

  def build_review_packet(
      row: FrozenRow,
      crop: CropRecord,
      context: PageContextRecord,
  ) -> VisualReviewPacket:
      ...
  ```

  Assert serialized packets omit `source_pdf`, `baseline_type`, every `ColumnBand.role`, current-gold fields, accepted values, and predictions. Assert crop/context identities and row geometry must match exactly.

- [ ] Add and test one narrow materializer:

  ```python
  def materialize_visual_gold_pilot(
      rows: Sequence[FrozenRow],
      private_root: Path,
  ) -> tuple[VisualReviewPacket, ...]:
      ...
  ```

  It must require a new/empty ignored `pilot-v1` directory, call the selector once, render exact crops and page contexts, write only `packets.jsonl` through `write_jsonl`, and return the same packets. It must not accept or read a gold/prediction path.

- [ ] Rerun the focused test and all four repository gates.

- [ ] Commit:

  ```bash
  git add experiments/row_extraction/visual_gold_pilot.py tests/experiments/row_extraction/test_visual_gold_pilot.py
  git commit -m "feat: materialize visual gold pilot"
  ```

---

### Task 5: Compare blind reviews and summarize current-gold defects

**Task contract**

```text
Scope answer: YES — this computes the predeclared extraction-supervision agreement and defect measurements.
Experiment: shared evaluation
Extraction hypothesis: Blind reviews meet 95% row-type and 90% exact-field agreement, and their adjudicated candidate reveals quantifiable current-label defect categories.
Measurement: row-type agreement, field exact agreement, atom-support agreement, source-region agreement, validity, and annotation-defect category counts
Fixed inputs: the locked 100 pilot identities, frozen rows, frozen Reviewer A/B labels, later adjudicated candidate labels, and current gold only after adjudication freeze
Smallest allowed files: experiments/row_extraction/visual_gold_agreement.py; tests/experiments/row_extraction/test_visual_gold_agreement.py
Required output: privacy-safe aggregate agreement/gate result plus private disagreement identities and aggregate current-gold defect counts
Stop condition: stop if the metrics require changing labels, using predictions, exposing private values, or adding a reusable scoring/reporting subsystem
```

**Files:**

- Create: `tests/experiments/row_extraction/test_visual_gold_agreement.py`
- Create: `experiments/row_extraction/visual_gold_agreement.py`

- [ ] Add failing tests for immutable comparison output with two layers:

  ```python
  class DisagreementKind(StrEnum):
      ROW_TYPE = "row_type"
      AMBIGUITY = "ambiguity"
      FIELD_PRESENCE = "field_presence"
      CANONICAL_VALUE = "canonical_value"
      ATOM_SUPPORT = "atom_support"
      SOURCE_REGION = "source_region"

  class VisualReviewDisagreement(_FrozenModel):
      document_id: str
      row_id: str
      kinds: tuple[DisagreementKind, ...]

  class VisualAgreementSummary(_FrozenModel):
      row_count: int
      row_type_matches: int
      row_type_agreement: Decimal
      eligible_field_slots: int
      exact_field_matches: int
      field_exact_agreement: Decimal
      joint_field_slots: int
      atom_support_matches: int
      atom_support_agreement: Decimal
      source_region_matches: int
      source_region_agreement: Decimal
      valid: bool
      row_type_gate_passed: bool
      field_exact_gate_passed: bool
      pilot_passed: bool

  def compare_visual_reviews(
      selected_rows: Sequence[FrozenRow],
      reviewer_a: Sequence[VisualReviewDecision],
      reviewer_b: Sequence[VisualReviewDecision],
  ) -> tuple[VisualAgreementSummary, tuple[VisualReviewDisagreement, ...]]:
      ...
  ```

- [ ] Test these exact rules: all 100 identities required once per reviewer; validate each reviewer through `validate_annotation_subset`; row type includes all 100; field denominator is the union of asserted roles per row; missing/present disagrees; canonical values compare exactly; atom tuple and source region compare separately only for jointly asserted roles; thresholds are inclusive at 0.95 and 0.90; `pilot_passed` requires validity and both semantic gates.

- [ ] Test that `VisualAgreementSummary.model_dump_json()` contains only aggregate counts, rates, and booleans. It must not contain identities, field roles, canonical values, atom IDs, source regions, filenames, or row text. Disagreements remain private and may contain only opaque identities plus enum categories, never A/B values.

- [ ] Run the focused test and confirm failure:

  ```bash
  .venv/bin/pytest -q tests/experiments/row_extraction/test_visual_gold_agreement.py
  ```

- [ ] Implement the comparator with `Decimal` ratios and deterministic identity/category ordering. Do not reuse experiment scoring or read predictions.

- [ ] Add failing tests for current-gold defect summaries:

  ```python
  class AnnotationDefectCategory(StrEnum):
      ROW_TYPE = "row_type"
      FIELD_PRESENCE = "field_presence"
      RTL_MIXED_ORDER = "rtl_mixed_order"
      SEGMENTATION = "segmentation"
      CANONICAL_VALUE_OTHER = "canonical_value_other"
      EVIDENCE_SUPPORT = "evidence_support"

  class CurrentGoldDefect(_FrozenModel):
      document_id: str
      row_id: str
      categories: tuple[AnnotationDefectCategory, ...]

  class AnnotationDefectSummary(_FrozenModel):
      compared_rows: int
      differing_rows: int
      row_type_defects: int
      field_presence_defects: int
      rtl_mixed_order_defects: int
      segmentation_defects: int
      canonical_value_other_defects: int
      evidence_support_defects: int

  def summarize_current_gold_defects(
      selected_rows: Sequence[FrozenRow],
      current_gold: Sequence[GoldRow],
      candidate_gold: Sequence[GoldRow],
      classifications: Sequence[CurrentGoldDefect],
  ) -> AnnotationDefectSummary:
      ...
  ```

  Require exact selected coverage in current and candidate gold, classifications exactly for differing rows, at least one category per differing row, and structural categories consistent with deterministic differences. RTL/segmentation/other canonical categories are manually assigned only after visual inspection. Reject a classification for an equal row.

- [ ] Implement, rerun the focused test, and run all four repository gates.

- [ ] Commit:

  ```bash
  git add experiments/row_extraction/visual_gold_agreement.py tests/experiments/row_extraction/test_visual_gold_agreement.py
  git commit -m "feat: measure visual gold pilot agreement"
  ```

---

### Task 6: Materialize and freeze the private pilot inputs

**Task contract**

```text
Scope answer: YES — this creates the fixed evidence set on which blind extraction-label agreement is measured.
Experiment: shared evaluation
Extraction hypothesis: The real frozen training population satisfies every predeclared selector and leakage invariant.
Measurement: real pilot quota counts, exact row count, and runnable visual packets
Fixed inputs: the private frozen rows JSONL for all 2,503 training rows and selector version visual-gold-v2-pilot-v1
Smallest allowed files: ignored private visual-gold-v2/pilot-v1/packets.jsonl; ignored crops; ignored page contexts
Required output: exactly 100 immutable private packets satisfying every quota
Stop condition: stop on missing source artifact, selector failure, render failure, packet leakage, nonignored output location, or any count other than 100
```

- [ ] Confirm the output root is ignored before creating it:

  ```bash
  git check-ignore --quiet "$ROW_EXPERIMENT_PRIVATE/visual-gold-v2"
  ```

- [ ] Read only the frozen rows stream, filter to `DatasetSplit.TRAIN`, assert the total is exactly 2,503, and call `materialize_visual_gold_pilot`. Do not load current gold or predictions in the process. Use a short one-off invocation of the public functions; do not add a CLI or checked-in runner.

- [ ] Independently read `packets.jsonl` with `read_jsonl(..., VisualReviewPacket)` and assert exactly 100 unique identities, quota counts, file existence, and matching crop/context SHA-256 values. This check may use the original frozen rows only to recompute hidden strata; do not serialize those strata.

- [ ] Record the packet artifact digest privately, freeze the directory against accidental edits using ordinary file permissions if supported, and confirm Git shows no private artifact:

  ```bash
  git status --short
  ```

- [ ] If any invariant fails, write no labels, report the measured failure category, and stop the program task.

---

### Task 7: Run Reviewer A’s blind visual pass

**Task contract**

```text
Scope answer: YES — this produces one independent extraction-label candidate for every pilot row.
Experiment: shared evaluation
Extraction hypothesis: Crop-first visual inspection can assign a valid GoldRow to every selected row without current-label or prediction hints.
Measurement: Reviewer A validity and exact 100-row coverage
Fixed inputs: frozen pilot packets/crops/page contexts and the committed visual-gold v2 protocol; no current gold or predictions
Smallest allowed files: ignored private visual-gold-v2/pilot-v1/reviewer-a.jsonl
Required output: exactly 100 valid VisualReviewDecision records
Stop condition: stop on missing/unreadable evidence, protocol leakage, invalid label, or incomplete/duplicate identity; use ambiguous only for genuine visual uncertainty
```

- [ ] Start Reviewer A in a clean, isolated review context. Give it only the protocol, `packets.jsonl`, crops, and page-context directory. Explicitly forbid repository searches for gold, baseline outputs, parser results, or predictions.

- [ ] Review fixed batches 001–010 in packet order, ten rows per batch. For every row: inspect the crop at original resolution; open page context only when necessary; create a complete `GoldRow`; record `page_context_used`; immediately validate the accumulated batch with `validate_annotation_subset`.

- [ ] After each batch, atomically append/freeze a private batch file. At pass completion, canonicalize the ten batches into `reviewer-a.jsonl` in packet order and remove no source batch until the combined file validates.

- [ ] Validate exact coverage, no unknown/duplicate identity, every field/canonical/evidence rule, and 100% subset validity. Freeze Reviewer A output before Reviewer B output is compared or disclosed.

- [ ] Do not commit any review output.

---

### Task 8: Run Reviewer B’s independent blind visual pass

**Task contract**

```text
Scope answer: YES — this supplies the independent replicate needed to measure extraction-label stability.
Experiment: shared evaluation
Extraction hypothesis: A second clean crop-first review independently reproduces row types and exact fields at the predeclared rates.
Measurement: Reviewer B validity and exact 100-row coverage
Fixed inputs: the same frozen pilot packets/crops/page contexts and protocol; no Reviewer A output, current gold, or predictions
Smallest allowed files: ignored private visual-gold-v2/pilot-v1/reviewer-b.jsonl
Required output: exactly 100 valid VisualReviewDecision records created without access to Reviewer A
Stop condition: stop on missing/unreadable evidence, cross-review leakage, invalid label, or incomplete/duplicate identity; use ambiguous only for genuine visual uncertainty
```

- [ ] Start Reviewer B in a different clean, isolated review context. Do not provide Reviewer A’s task, output path contents, summaries, or decisions.

- [ ] Review fixed batches 001–010 in packet order, ten rows per batch. For every row: inspect the crop at original resolution; open page context only when necessary; create a complete `GoldRow`; record `page_context_used`; immediately validate the accumulated batch with `validate_annotation_subset`.

- [ ] Atomically freeze each batch, combine into `reviewer-b.jsonl` in packet order, and validate exact 100-row coverage and 100% subset validity.

- [ ] Do not commit any review output.

---

### Task 9: Measure A/B agreement and enforce the pilot gates

**Task contract**

```text
Scope answer: YES — this directly tests whether visually reconstructed extraction supervision is stable enough to continue.
Experiment: shared evaluation
Extraction hypothesis: Reviewer A and B achieve at least 95% row-type and 90% field exact agreement with 100% validity.
Measurement: row-type agreement, field exact agreement, atom-support agreement, source-region agreement, and validity
Fixed inputs: frozen reviewer-a.jsonl, frozen reviewer-b.jsonl, locked 100 pilot rows, and no current gold/predictions
Smallest allowed files: ignored private comparison.jsonl; docs/experiments/row-extraction-visual-gold-v2-pilot-report.md; docs/experiments/row-extraction-program-status.md
Required output: gate result and privacy-safe aggregate counts/rates
Stop condition: if validity is below 100%, row-type agreement is below 95%, or field exact agreement is below 90%, record the result and STOP before adjudication or further review
```

- [ ] Run `compare_visual_reviews` exactly once on the frozen A/B files. Write the private disagreement list to `comparison.jsonl`; keep A/B values out of it.

- [ ] Verify that the aggregate serialization contains only counts, `Decimal` rates, and booleans. Record row-type, field exact, atom-support, and source-region numerators/denominators/rates.

- [ ] If any gate fails, create `docs/experiments/row-extraction-visual-gold-v2-pilot-report.md` with aggregate results only; update program status to `STOP`; run the four repository gates; commit the two tracked docs; emit the exact Metric-or-Stop report; and end this plan. Do not adjudicate, change labels, choose new thresholds, or launch a replacement pilot.

- [ ] If all gates pass, freeze `comparison.jsonl` and continue. Do not inspect current gold yet.

---

### Task 10: Adjudicate only A/B disagreements and freeze the pilot candidate

**Task contract**

```text
Scope answer: YES — this converts measured blind disagreements into one visual extraction-label candidate.
Experiment: shared evaluation
Extraction hypothesis: A fresh source-grounded adjudicator can resolve A/B differences without defaulting to either reviewer or current gold.
Measurement: adjudicated annotation validity, ambiguity count, and exact 100-row coverage
Fixed inputs: frozen packets/source images, frozen A/B outputs, and private disagreement identities; current gold and predictions remain hidden
Smallest allowed files: ignored private reviewer-c.jsonl; ignored private adjudicated-gold.jsonl
Required output: exactly 100 valid candidate GoldRow records, copying exact A/B agreements and independently adjudicating every disagreement
Stop condition: stop on missing evidence, unclassified disagreement, invalid adjudication, or incomplete coverage; retain ambiguous when no unique visual answer exists
```

- [ ] Build `adjudicated-gold.jsonl` by copying only rows where A and B labels are exactly equal. Do not copy a merely semantic match when evidence support differs; those rows require Reviewer C.

- [ ] Start Reviewer C in a fresh context. Provide source packets/images and, for disagreement rows only, the exact A/B semantic/evidence differences. Do not provide current gold, accepted parser values, predictions, or reviewer identities as quality signals.

- [ ] Reviewer C inspects every disagreement crop and opens page context only when necessary. It writes one `VisualReviewDecision` per disagreement to `reviewer-c.jsonl`, choosing a source-supported answer or `ambiguous` and fieldless when no unique answer exists.

- [ ] Merge the exact agreements and C decisions in locked packet order. Run `validate_annotation_subset` over all 100 candidate rows. Require 100 labels, 100% validity, no unknown/duplicate identity, and complete disagreement coverage.

- [ ] Freeze `reviewer-c.jsonl` and `adjudicated-gold.jsonl`. Do not commit either artifact.

---

### Task 11: Compare frozen pilot candidate to current gold and report the result

**Task contract**

```text
Scope answer: YES — this quantifies whether current supervision differs from source-grounded extraction labels and identifies the defect categories.
Experiment: shared evaluation
Extraction hypothesis: The frozen visual candidate exposes measurable current-gold row-type, field-presence, RTL/order, segmentation, canonical-value, or evidence-support defects.
Measurement: annotation-defect category counts and ambiguity count, alongside the frozen pre-adjudication agreement rates
Fixed inputs: frozen adjudicated 100-row candidate, matching current training gold opened only now, frozen source evidence, and no experiment predictions
Smallest allowed files: ignored private current-gold-defects.jsonl; docs/experiments/row-extraction-visual-gold-v2-pilot-report.md; docs/experiments/row-extraction-program-status.md
Required output: privacy-safe aggregate defect report and one next extraction task or STOP
Stop condition: stop if current/candidate coverage differs, a semantic difference cannot be visually classified, private data would enter Git, or no named metric/error count is produced
```

- [ ] Only now load the 100 matching records from current `gold.jsonl`. Validate current and candidate coverage independently against the same selected rows.

- [ ] Deterministically identify differing rows. For every canonical-value difference, visually inspect source evidence and privately classify it as `rtl_mixed_order`, `segmentation`, or `canonical_value_other`. Add deterministic row-type, field-presence, and evidence-support categories where applicable. Write exactly one private `CurrentGoldDefect` for every differing row.

- [ ] Run `summarize_current_gold_defects`; verify the summary contains only aggregate counts. Do not report values, row IDs, document IDs, atom text, source names, hashes, or filenames.

- [ ] Create `docs/experiments/row-extraction-visual-gold-v2-pilot-report.md` with:

  - selector version and fixed population size;
  - A/B validity and coverage;
  - all agreement numerators, denominators, rates, and gate outcomes;
  - adjudicated ambiguity count/rate;
  - current-gold differing-row count/rate;
  - aggregate counts for every predeclared defect category;
  - explicit statement that current gold remains authoritative and no experiment was rescored;
  - explicit statement that the remaining 2,403 rows were not reviewed under this plan.

- [ ] Update program status. If the pilot passed and produced a valid candidate, set the one next extraction task to “Write and approve the implementation plan for blind dual review of the remaining 2,403 training rows under the frozen pilot protocol.” Otherwise set `STOP`.

- [ ] Search the tracked diff for private leakage, inspect it manually, then run all four repository gates:

  ```bash
  git diff --check
  git diff -- docs/experiments/row-extraction-visual-gold-v2-pilot-report.md docs/experiments/row-extraction-program-status.md
  .venv/bin/ruff format --check .
  .venv/bin/ruff check .
  .venv/bin/mypy src
  .venv/bin/pytest -q
  ```

- [ ] Confirm private artifacts are ignored and not staged. Commit only the aggregate report and status:

  ```bash
  git add docs/experiments/row-extraction-visual-gold-v2-pilot-report.md docs/experiments/row-extraction-program-status.md
  git commit -m "docs: report visual gold v2 pilot"
  ```

- [ ] Report exactly:

  ```text
  Scope: YES — measured blind visual reconstruction of extraction supervision on the fixed training pilot
  Experiment: shared evaluation
  Measurement: row-type agreement, field exact agreement, evidence-support agreement, validity, ambiguity, and annotation-defect categories
  Result: <aggregate gate result, rates, and defect counts from the committed report>
  Next extraction task: <write the remaining-2,403-row plan, or STOP>
  ```

## Plan Completion Boundary

This plan is complete when the 100-row pilot has either:

1. failed a predeclared gate and produced a committed aggregate stop report; or
2. passed, produced a valid frozen private adjudicated pilot candidate, produced a committed aggregate defect report, and named planning the remaining 2,403-row review as the only next extraction task.

It is not complete merely because the code and tests pass. It must produce the named real-pilot measurement, or stop under the Metric-or-Stop rule.
