# Row-Extraction Program Status

**Status:** Binding live record for the row-extraction experiment program.

**Updated:** 2026-09-20

**Authority:** [`AGENTS.md`](../../AGENTS.md), the
[experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md),
and the
[focus-lock design](../superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md).

Round 1 is frozen at the audited branch heads below. The held-out test remains unopened. No
tracked document, crop, label, output, cache, model artifact, private artifact identity, or
derived financial value is recorded here.

## Current phase: document-disjoint merchant evaluation design

**Status:** DESIGN COMPLETE — STOP. The user's “proceed” approved the
[design-only task](../superpowers/specs/2026-09-20-merchant-document-disjoint-evaluation-design.md).
It specifies a six-document pilot outside the merchant seed, source-only prediction
generation, blinded full-page reference review, fixed comparators and paired
metrics including discovery omissions and ownership errors.

No new sample, document, reference or prediction was opened or created.
Evaluation results are **NOT MEASURED**. The design records two execution risks:
saved loaders are seed-specific, and the old score uses merchant-region-assisted
alignment. It proposes a minimal fixed-rule input adapter and transaction-only
primary alignment for a future separately approved run, not production changes.

Execution is not authorized. Existing validation and held-out partitions stay
closed; the proposed pilot uses other existing training documents and must not
be described as an untouched project test set. No follow-on support task is active.

Next extraction task: STOP.

## Latest measured extraction result

The [unchanged-order spacing candidate](row-extraction-merchant-unchanged-order-spacing-report.md),
reported at `2cefcb2`, remains **21/24 exact**, up from 19/24 with two gains and
zero losses against four baselines, and unchanged 24/24 coverage. Digital is
15/16 and OCR 6/8. All 144 prior scores reproduce; independent checks agree on
113 outputs and 168 scores. Thirty-six focused checks and 3,766 repository tests
passed. The candidate and its inputs are preserved without further tuning.

This reviewed training-seed result is not validation accuracy or private-corpus
acceptance. The proposed new-document evaluation has not run.

## Knowledge and history

Read the [distilled experiment findings](../knowledge/experiment-findings.md)
for Round 1, branch-only Round 2, gold/context failures, and merchant results.
The [historical status snapshot](row-extraction-program-history.md) preserves
the complete earlier phase record; [the evidence index](../knowledge/evidence-index.md)
links the original reports and designs. No historical phase is reactivated.

## Frozen Round 1 status

| Lane | Audited branch head | Frozen validation disposition and outcome |
| --- | --- | --- |
| evaluation/controller | `409dbcd7994ba1532fcbe8b165f12ebcc1c37cd4` | Read-only anchor for the completed Round 1 comparison/controller work. |
| OCR | `9bc582c6876d4e2adba7e19cf2ba1968c5ab2625` | `VALIDATION_STOPPED`, `ocr_stage_validation_failed`, zero exact matches, with hallucinated or unsupported fields. |
| deterministic profiles | `a2ed73aa58a4e4d8c76f918657d083fa922537d4` | `FROZEN_ELIGIBLE`, all validation rows abstained, zero exact matches. |
| text | `d573b7f8d5239ca3ff92cbc7bf5475f5ced2ab0a` | `VALIDATION_STOPPED`, `no_text_candidate_met_validation_gate`, single-label supervision cannot represent overlapping evidence ownership, all abstained, zero exact matches. |
| vision | `40f748395c07bb4d2da6658b92087be471681264` | `VALIDATION_STOPPED`, `no_pixel_gain`, zero eligible validation rows under the frozen contract, diagnostic output all abstained, zero exact matches. |

Accepted baseline: zero exact matches with partial acceptance; page-OCR controls abstained. These
are privacy-safe validation outcomes, not held-out measurements and not private-corpus acceptance.

## Frozen side work

Preserve, but do not continue:

- all four Round 1 lane implementations, configurations, handoffs, and artifacts at the audited
  heads above;
- locked-comparison controller or CLI architecture and provenance-envelope or handoff re-freezing
  work;
- receipts, replay prevention, attestations, and path/inode/cache-independence machinery;
- marker-first or other locked-input projection features;
- cascade execution and locked-test orchestration, including charter Stages 4-6;
- private-corpus controller redesign and repository acceptance-gate work; and
- production integration or integration design.

Historical branches, plans, runbooks, and artifacts are read-only evidence. An unchecked task or
an existing implementation does not reactivate it. An infrastructure exception requires direct
user approval followed by a committed charter amendment.

The repository private-corpus acceptance policy is a separate production acceptance gate. It is
not an experiment task, extraction measurement, or substitute for the Metric-or-Stop Rule.
