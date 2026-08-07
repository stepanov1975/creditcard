# Row-Extraction Program Status

**Status:** Binding live record for the row-extraction experiment program.

**Updated:** 2026-08-07

**Authority:** [`AGENTS.md`](../../AGENTS.md), the
[experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md),
and the
[focus-lock design](../superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md).

Round 1 is frozen at the audited branch heads below. The held-out test remains unopened. No
tracked document, crop, label, output, cache, model artifact, private artifact identity, or
derived financial value is recorded here.

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

## Active phase: merchant context sufficiency

**Status:** `ACTIVE` — the user approved one training-only shared-evaluation experiment to measure
the smallest source context that produces the best safe transaction-level merchant attribution.

The binding design is
[`2026-08-07-merchant-context-sufficiency-design.md`](../superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md).
It reuses exactly the 100 frozen pilot row identities as opaque anchors without using either
reviewer's labels. An independent transaction reference must be frozen from source evidence before
any arm runs. Current gold, accepted parser output, previous reviewer values, experiment
predictions, validation, and held-out data remain closed.

The six nested context arms use identical pixels, positioned atom text and boxes, role-free column
boundaries, model, prompt, decoding, and output contract. Only spatial context changes from the
exact anchor row through the full page. Any wrong-merchant or hallucination event makes an arm
unsafe. Among safe arms, the decision maximizes correct merchant attribution, then exact
merchant-bearing text, then selects the smallest context tier.

**Measurement:** transaction-level merchant-attribution accuracy, exact merchant-bearing-text
rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, reference
ambiguity, and paired gains and losses by context tier.

**Next extraction task:** implement and run the single fixed merchant-context sufficiency
experiment, report the supported or falsified hypothesis and smallest best safe tier, then `STOP`
unless the user separately authorizes one next extraction task.

No reusable controller, CLI family, schema family, receipt chain, workflow subsystem, replacement
pilot, validation run, held-out access, or production integration is authorized.

## Completed visual-gold pilot stop

**Status:** Historical `STOP` — the visual-gold v2 100-row training pilot failed its binding
pre-adjudication field-exact agreement gate.

**Aggregate result:** annotation validity was 100%; row-type agreement was 98/100 (`0.98`) and
passed; field-exact agreement was 386/473 (`0.8160676532769556025369978858`) and failed the
inclusive `0.90` gate. Diagnostic atom-support agreement was 384/414
(`0.9275362318840579710144927536`), and source-region agreement was 376/414
(`0.9082125603864734299516908213`).

The binding stop occurred before adjudication and before current-gold inspection. No labels,
thresholds, prompts, canonicalization, comparison logic, or extractors may be changed to rescue
this pilot, and no replacement pilot or support task may be launched under the current authority.

The pilot remains stopped. The active context-sufficiency experiment does not adjudicate, relabel,
rescue, or continue it.

The aggregate pilot report is
[`row-extraction-visual-gold-v2-pilot-report.md`](row-extraction-visual-gold-v2-pilot-report.md).

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
