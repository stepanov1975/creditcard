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

## Current phase: merchant unchanged-order spacing candidate

**Status:** APPROVED — pending one generation and evaluation. The user's
“proceed” authorizes the [fixed design](../superpowers/specs/2026-09-20-merchant-unchanged-order-spacing-design.md).
Apply the existing tolerance-aware renderer to eligible saved groups even when
order is unchanged. Preserve glyph correction, ownership and all source guards.

Save the complete source-only candidate before reference access, reproduce all
144 saved scores, and compare the same 24 v3 training references against the
four saved 19/24 baselines. Coverage must remain 24/24, with no exact-match losses,
for a gain above 19/24 to support the hypothesis. No post-score tuning is allowed.

Next extraction task: execute this one approved candidate, report its result,
then STOP. No new labels, sample expansion, validation/held-out access, second
candidate or production integration is active.

The preceding [corrected-spacing diagnostic](row-extraction-merchant-corrected-spacing-report.md)
remains complete: two whitespace-only errors, two unique identity-order witnesses,
and unchanged accuracy of 19/24. Its full phase record is retained in history.

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
