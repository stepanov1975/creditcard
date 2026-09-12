# Merchant-Region OCR Experiment

**Status:** Approved by the user's “proceed” on 2026-09-12 following the concrete
recommendation to test local OCR confined to extractor-selected merchant regions.
Commit this design and charter amendment before private candidate execution.

```text
Scope answer: YES — measures whether merchant-focused OCR improves extraction
Experiment: row-ocr
Extraction hypothesis: OCR of extractor-selected merchant regions yields a positive net exact-match gain over 10/24
Measurement: merchant exact matches, paired gains/losses, coverage, and crop/recognition failures
Fixed inputs: 24 training references, saved alignment, 127 rows, 108 description proposals, six source pages, frozen OCR settings
Smallest allowed files: docs/superpowers/specs/2026-09-12-merchant-region-ocr-design.md; docs/superpowers/plans/2026-09-12-merchant-region-ocr.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; docs/experiments/row-extraction-merchant-region-ocr-report.md; artifacts/merchant-region-ocr-v1/**
Required output: paired exact-match delta and hypothesis result
Stop condition: stop after one fixed comparison, without tuning, new labels, or sample expansion
```

## Fixed inputs and comparator

Reuse all 24 human-reviewed training references, saved alignment (20 matched
owners and four failures), 127 frozen observations from the selected six pages,
and the reading-order candidate's 108 description proposals. Reproduce the saved
10/24 comparator, with 18/24 unique descriptions, before scoring the OCR result.
Do not rerun selection, alignment, previous extraction, or the reading-order sweep.

The recognition process reads only frozen observations, existing proposals,
selected source PDF copies, and frozen OCR configuration/model files. Human text,
human regions, saved case scores, and alignment are available only to the separate
local scorer. Apply OCR to all 108 proposals, including those outside reviewed
slots, without selecting by correctness or human boundaries.

## One fixed OCR candidate

For each existing description proposal, form the axis-aligned union of its
selected atoms' original page-space boxes. Require every selected box to be finite
and nonempty. Convert the union with the source page's rotation matrix to displayed
page coordinates and require full containment in the page. Do not expand, clip,
repair, merge with another proposal, or substitute a human-marked region.

Use the frozen OCR arm's existing `render_clip` and `TesseractRecognizer` directly:
300 DPI, zero padding, PSM 6, internal Otsu, OEM 1, and the pinned baseline model
packs. Preserve the baseline recognizer's existing three streams (Hebrew+English,
English, numeric-whitelisted English) and existing fusion. No model download,
new dependency, parameter sweep, or additional recognition method is authorized.

Reuse the fixed directional-run permutation from the completed reading-order
experiment on the new OCR atoms, then the existing proposal renderer. Do not
reverse text inside atoms or use the reference to choose an output. The comparison
tests this fixed merchant-region OCR pipeline against the saved deterministic
reading-order descriptions; it does not isolate cropping from recognition relative
to that comparator.

Preserve each original proposal's transaction owner and all original row
classifications, financial decisions, and reasons. OCR atom text/boxes and the
proposal region are newly observed evidence. Mark private candidates as row-ocr
with this experiment's config identity; leave exact-row confidence unset and use
zero uncalibrated proposal score, which does not enter merchant scoring.

If a proposal has invalid/outside geometry, rendering fails, recognition fails,
or OCR returns no atoms, record its failure category and an empty text slot.
Never fall back to the deterministic string or remove the slot to resolve an
existing multi-proposal ambiguity. Rows with no original description remain
without one. All 24 cases stay in scoring, including alignment failures.

A missing/mismatched required source, frozen checkout, model/configuration, or
unavailable OCR executable ends the attempt before recognition with a quantified
failure category. Do not replace inputs or launch another method. Per-proposal
crop/recognition failures count as this candidate's unavailable output, without
retry or a parameter change.

## Measurement and verification

Report all-case and aligned exact merchants, paired gains/losses and net change
against 10/24, OCR/digital page slices, unique-description coverage, omissions,
ambiguous outputs, alignment failures, and crop/render/recognition/empty-output
counts across all 108 proposals and the reviewed owners. The hypothesis is
supported only if paired net exact matches are positive; otherwise it is falsified
on the fixed seed. A prerequisite stop leaves accuracy NOT MEASURED.

Use existing NFC/collapsed-whitespace comparison and Decimal rates. Verify the
saved baseline case by case and independently recompute candidate scores from
saved OCR evidence. Test union geometry, rotation and containment, refusal to
expand/clip invalid regions, empty OCR handling, reading order, and retained
ownership/ambiguity using invented inputs before private execution.

Keep disposable scripts/tests, crops, OCR caches, predictions, and case details
only under ignored `artifacts/merchant-region-ocr-v1/`. Only privacy-safe aggregate
docs are committed. No private text or pixels enter model tools or external
services. Historical source trees stay read-only; this bounded diagnostic does
not change the OCR lane's historical validation-stopped disposition.

Stop after the one scored comparison and return live status to STOP. No tuning,
new labels, seed expansion, gold promotion, validation/test access, production
integration, or reusable controller/schema/CLI/workflow is authorized. This small
single-reviewer training seed is calibration evidence, not independent gold
verification, production accuracy, or private-corpus acceptance.
