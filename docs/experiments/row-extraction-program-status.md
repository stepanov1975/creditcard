# Row-Extraction Program Status

**Status:** Binding live record for the row-extraction experiment program.

**Updated:** 2026-09-21

**Authority:** [`AGENTS.md`](../../AGENTS.md), the
[experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md),
and the
[focus-lock design](../superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md).

Round 1 is frozen at the audited branch heads below. The held-out test remains unopened. No
tracked document, crop, label, output, cache, model artifact, private artifact identity, or
derived financial value is recorded here.

## Current objective: document-disjoint merchant evaluation

**Status:** AWAITING_HUMAN_REVIEW — corrected packet v2 is ready under the user's
2026-09-21 merchant-field clarification, committed as `bd4910d`. Every printed
character in the merchant position belongs to the field, including codes and
owned continuation text. See the [amended design](../superpowers/specs/2026-09-20-merchant-document-disjoint-evaluation-design.md)
and [domain definition](../../CONTEXT.md).

The [evaluation report](row-extraction-merchant-document-disjoint-evaluation-report.md)
records 89 unconfirmed entries, all with printed field text. Twenty-nine values
were corrected from the earlier semantic-trimming draft. Nine flags remain for
transcription or reading order, not business-name/reference-code separation.
The v2 worksheet, JSON and CSV are in ignored
`artifacts/merchant-document-disjoint-v1/merchant-field-review/`; the old packet
is preserved as superseded history. Use `merchant-review-prefilled-v2.zip`.

Next dependency: corrected v2 answers and six confirmed page censuses. Then
freeze references and complete ownership review and paired scoring. Accuracy is
NOT MEASURED. Earlier scores retain their historical reference definition and
are not measurements of this corrected complete-field contract. No parser
implementation, frozen prediction, validation/held-out input or accepted gold
was changed by this reference correction.

## Latest measured extraction result

The [unchanged-order spacing candidate](row-extraction-merchant-unchanged-order-spacing-report.md),
reported at `2cefcb2`, remains **21/24 exact**, up from 19/24 with two gains and
zero losses against four baselines, and unchanged 24/24 coverage. Digital is
15/16 and OCR 6/8. All 144 prior scores reproduce; independent checks agree on
113 outputs and 168 scores. Thirty-six focused checks and 3,766 repository tests
passed. The candidate and its inputs are preserved without further tuning.

This reviewed training-seed result is not validation accuracy or private-corpus
acceptance. The new-document evaluation is awaiting independent human references.

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
