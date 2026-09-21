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

## Current objective: fresh-sample continuation evaluation

**Status:** AWAITING_HUMAN_REVIEW for output ownership only. All **16 references
and six page censuses are human-confirmed**, without edits. The
[fresh-sample report](row-extraction-continuation-fresh-sample-report.md) records
**16/16 unique transaction matches but 0/16 exact complete merchant fields in both
versions**. All output strings are identical: zero gains/losses, no omissions,
ties, collisions or unassigned emissions. The four empty pages stay empty.

AI source review finds **16 separate outside-field indicators and six omitted
merchant continuations**, with no observed wrong-transaction borrowing. All six
omissions coincide with subordinate-detail diagnostics; that path is excluded
from description extraction. The next development priority is geometric field
boundaries and merchant cells within mixed merchant/detail rows, using synthetic
inputs and a separate evaluation—not tuning these scored pages.

The local `artifacts/merchant-continuation-fresh-v1/evaluation/` directory contains
comparison CSV/JSON, AI findings and `merchant-continuation-results-review.zip`.
Next dependency for formal ownership counts:
`merchant-continuation-fresh-ownership-answers.json`, covering the two pages with
transactions. Reference transcription and all six censuses are complete; do not
request them again. The packet prefills AI judgments and labels full transaction
context separately from merchant evidence.

Text accuracy is **0/16** for each version. Formal human-ownership-verified accuracy
is **NOT MEASURED**, with an exact numerator bounded above by zero; ownership review
cannot create a text gain. The two-mode hypothesis remains **INCONCLUSIVE** because
no OCR transaction references were sampled. No parser was rerun or tuned; frozen
references, predictions and the earlier 89-case evaluation remain unchanged.

## Completed implementation: complete merchant-field continuations

**Status:** COMPLETE — the authorized, bounded continuation/discovery fixes are
implemented and verified. The
[implementation report](row-extraction-complete-field-continuations-report.md)
records synthetic complete-field cases improving from **9/29 to 29/29**, with
**9/9 rejection controls preserved**. Numeric/currency/date-shaped field text,
multiple wrapped lines and split continuation cells now retain their ownership;
downstream transaction discovery survives those continuations. No future-billing
filter changed. All **3,802 repository tests**, Ruff format/lint and mypy pass.

No scored private cases were development inputs. Fresh-document accuracy is
**NOT MEASURED** and private-corpus verification was not run. The next measurement
requires a predeclared fresh sample with source-reviewed references and this
candidate frozen before scoring. No production merge is authorized by these tests.

The earlier evaluation below remains **AWAITING_HUMAN_REVIEW** with its ownership
confirmation dependency outstanding. Its sample, predictions and scores remain
frozen; the implementation authorization did not supply human confirmations.

## Frozen document-disjoint evaluation: human dependency

**Status:** AWAITING_HUMAN_REVIEW — merchant references are now frozen from the
user's returned v2 answers: all **89 entries and all six page censuses confirmed**,
with no value, region or membership edits. This is an AI-assisted,
single-human-reviewed pilot; N = P = 89 and A = U = 0.

The [evaluation report](row-extraction-merchant-document-disjoint-evaluation-report.md)
records **49/89 text-exact matches in each frozen view**, zero gains/losses and
identical outputs on every reference case. Geometry aligns 85 references; four
have no qualifying row overlap. All aligned cases have unique output. Nineteen
saved output owners remain unassigned. Digital text equality is 39/73; OCR is
10/16. These results do not measure the later production parser fix.

AI visual ownership review is complete for all 89 cases: 62 select evidence from
the correct merchant field, 23 include a same-transaction indicator outside it,
and four have no matched output. Among the 62, 49 are text exact, 12 omit field
text and one has an OCR transcription mismatch. Fifteen of the 23 outside-field
cases also omit a continuation line. No wrong-transaction evidence was observed.
These are AI findings pending human confirmation, not formal verified scores.

The ignored `artifacts/merchant-document-disjoint-v1/evaluation/ai-ownership-review/`
directory contains `FINDINGS.md`, per-case CSV/JSON and
`merchant-ownership-ai-reviewed.zip`. Every case has an AI suggestion and explanation,
with locked references, anonymous output and source overlays. Human confirmations
remain false. The user can correct these findings instead of repeating the review
from an empty worksheet.

Next dependency: `merchant-ownership-audit-v1-answers.json`, confirming ownership
judgments and all six pages. Then finish verified scoring and the fixed eligibility
decision. Ownership-verified accuracy is **NOT MEASURED** and the hypothesis remains
**INCONCLUSIVE** pending that audit. Human field-transcription review is complete;
do not request it again. Frozen predictions, source membership and accepted gold
remain unchanged; no validation or held-out inputs were opened.

The user's subsequent 2026-09-21 production-fix request corrects merchant trimming
in `normalization_description.py`: preserve all field text and owned continuations,
including codes, and retain separate date/amount/metadata ownership. This work
uses synthetic regressions and does not alter frozen predictions or accepted gold.
The correction passes 340 focused tests, all 3,766 repository tests, Ruff
format/lint and mypy. See [current parser behavior](../knowledge/architecture.md).
The private-corpus gate was not run; new-sample accuracy remains unmeasured.
Prediction-evidence ownership review is still the evaluation dependency.

## Earlier completed seed result

The [unchanged-order spacing candidate](row-extraction-merchant-unchanged-order-spacing-report.md),
reported at `2cefcb2`, remains **21/24 exact**, up from 19/24 with two gains and
zero losses against four baselines, and unchanged 24/24 coverage. Digital is
15/16 and OCR 6/8. All 144 prior scores reproduce; independent checks agree on
113 outputs and 168 scores. Thirty-six focused checks and 3,766 repository tests
passed. The candidate and its inputs are preserved without further tuning.

This reviewed training-seed result is not validation accuracy or private-corpus
acceptance. The new-document evaluation has human-confirmed references and awaits ownership review.

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
