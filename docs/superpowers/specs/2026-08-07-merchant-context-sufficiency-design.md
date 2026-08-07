# Merchant Context Sufficiency Experiment Design

**Status:** Approved conversational design; implementation remains blocked until this written
specification is reviewed and the experiment charter and live program status are amended.

**Date:** 2026-08-07

## Purpose

Determine the smallest source context that produces the best source-grounded merchant attribution
for an otherwise fixed extraction process. The experiment replaces reviewer-versus-reviewer
agreement as the outcome with accuracy against an independently established transaction-level
reference.

The prior visual-gold pilot remains a completed failed pilot and historical evidence. Its 42
description differences revealed a systematic role-policy difference, not an accuracy ranking:
one reviewer generally selected a broader continuation description while the other selected a
narrower merchant span and often classified the remainder as ancillary or exchange-rate text.
Core financial fields agreed. No prior reviewer is treated as correct, no stopped label stream is
adjudicated or repaired, and the failed agreement gate is not reinterpreted as an accuracy result.

## Authority and stop boundary

The binding live status is currently `STOP`. This design records the user's direct request for a
different experiment question, but does not by itself reactivate the program or authorize code,
artifact generation, or source review.

After this specification is reviewed, the smallest required authority change is a committed
amendment to:

- `docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md`; and
- `docs/experiments/row-extraction-program-status.md`.

That amendment may authorize only the fixed training experiment described here. Validation,
held-out evaluation, production integration, relabeling of the stopped pilot, and generalized
review or orchestration infrastructure remain closed.

## Task contract

```text
Scope answer: YES — this defines and measures how source context changes transaction-level merchant attribution.
Experiment: shared evaluation
Extraction hypothesis: A bounded transaction neighborhood plus visible table headers matches full-page merchant accuracy, while an isolated row crop does not.
Measurement: transaction-level merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired accuracy delta by context tier
Fixed inputs: the frozen 100 training pilot row identities and source evidence only; all arms use the same reference cases, model, prompt, and decoding; validation, held-out data, current gold, accepted parser output, and experiment predictions remain closed
Smallest allowed files: CONTEXT.md; docs/superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md; docs/superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md; docs/experiments/row-extraction-program-status.md; experiments/row_extraction/merchant_context.py; tests/experiments/row_extraction/test_merchant_context.py; docs/experiments/row-extraction-merchant-context-report.md; and artifacts/merchant-context-sufficiency-v1/** (ignored private artifacts only)
Required output: a supported or falsified context-sufficiency hypothesis and the smallest context tier attaining the best observed safe merchant accuracy
Stop condition: stop before implementation if merchant-bearing evidence is not operationally referenceable, an independent reference cannot be frozen before arm execution, an arm would expose prohibited labels or predictions, or the authority amendments are not committed
```

## Product accuracy contract

An accurate transaction has two release-critical properties:

1. its core financial fields and group membership are exact; and
2. its merchant is attributed to the correct source transaction.

Ancillary transaction metadata is useful but is not part of the merchant-accuracy outcome. A
category, location, processor/reference, exchange-rate narrative, or fee narrative does not make
a transaction inaccurate when the core financial identity and merchant attribution are exact.
Conversely, arithmetic reconciliation cannot excuse an omitted, borrowed, or invented merchant.

This experiment does not change current production reconciliation or output behavior. It narrows
the extraction measurement to the product outcome the user identified and leaves any production
policy change to a separate design.

## Operational merchant rule

For this experiment, **merchant-bearing evidence** is the smallest ordered source span needed to
identify the merchant for one transaction. It may cross from a primary row into owned continuation
rows. It is determined from positioned visual evidence, not from a merchant database or known-name
list.

The reference includes:

- visible merchant-name text and a visually inseparable merchant suffix;
- a processor-formatted merchant payload only when the payload is part of the printed merchant
  identity; and
- continuation text only when it extends the same merchant identity.

The reference excludes text that is independently identifiable as category, location,
processor/reference, transaction type, installment detail, exchange-rate narrative, fee
narrative, date, amount, or currency. Location or processor text is included only when source
layout makes it inseparable from, and necessary to, the printed merchant identity. If source
evidence supports more than one defensible merchant span or transaction owner, the case is marked
ambiguous rather than guessed.

Canonical merchant text preserves visible character order and punctuation. Scoring may normalize
Unicode to NFC and collapse layout-only whitespace; it performs no spelling correction, alias
mapping, punctuation deletion, transliteration, or external entity resolution.

## Fixed evaluation cases

The experiment reuses exactly the 100 frozen training row identities from the stopped pilot. This
reuses sample coverage without reusing either reviewer's labels. Source filenames, current gold,
accepted parser output, experiment predictions, and the prior Reviewer A/B values remain hidden.

Each selected row is an **anchor**. The independent reference groups anchors that belong to the
same visible source transaction and marks structural or genuinely ambiguous anchors. Every unique
unambiguous transaction represented by at least one anchor is one primary scoring case. This makes
the primary denominator transaction-level and prevents a transaction from receiving extra weight
merely because both its primary and continuation rows were selected.

At inference time, the extractor receives only an opaque anchor marker and the evidence allowed by
that arm. It must return the merchant for the transaction owning that anchor, or abstain. Reference
grouping is used only during scoring. Nontransaction anchors and ambiguous reference cases are
reported separately and do not enter the merchant-accuracy denominator.

If the private frozen artifacts cannot establish the exact 100 identities without reopening
current gold or either review stream, the experiment stops. The sample is not regenerated.

## Independent accuracy reference

The transaction reference is frozen before any context-arm output is generated. A source reviewer
uses original-resolution full-page evidence, the operational merchant rule above, and no current
gold, parser values, previous reviewer values, or experiment predictions. For each anchor, the
reference records:

- transaction or nontransaction disposition;
- ownership among represented anchors;
- the ordered merchant-bearing atom IDs when the frozen atoms faithfully represent the visible
  text, and/or a tight source region with a visual transcription when they do not;
- canonical merchant text; and
- `unambiguous` or `ambiguous` status with a reason category.

A separate verification pass checks source support, transaction ownership, and application of the
merchant rule. The extraction process under test cannot author, verify, or amend this reference.
Any challenge is resolved against the source and written rule before freezing the reference.
Reference-review agreement is neither an experiment metric nor a gate; disagreement is work to
resolve or evidence that the case must remain ambiguous. There is no A/B performance comparison
and no majority vote.

The reference is valid only if every asserted merchant character is source-supported, every
unambiguous anchor has one transaction owner, and private values remain in ignored local
artifacts. Failure to establish a unique reference reduces the eligible denominator and is counted
as reference ambiguity; it never licenses a guess.

## Context arms

All six arms are nested. Every visible region is represented by both original-resolution pixels
and the corresponding frozen atom text and boxes. Every arm uses the same role-free column
boundaries, opaque anchor marker, rendering scale, model snapshot, extraction prompt, output
contract, decoding settings, and isolated fresh execution. The only independent variable is the
spatial extent of source context; no arm is handicapped by losing a modality available to another.

| Arm | Evidence available |
| --- | --- |
| `C0 row` | The exact row crop, same-row atoms and boxes, row geometry, and role-free column boundaries. |
| `C1 adjacent-rows` | `C0` plus the immediately preceding and following frozen rows and their positioned evidence. No row types or semantic roles are shown. |
| `C2 local-neighborhood` | `C1` plus the second preceding and following rows when present. |
| `C3 header-neighborhood` | `C2` plus the visible table-header region and its positioned evidence. |
| `C4 table-region` | `C3` plus the complete detected table region and positioned evidence on the anchor page. |
| `C5 full-page` | `C4` plus the complete anchor page and all positioned source evidence on that page. |

The anchor marker is identical in every arm and cannot cover text. Missing neighbors and headers
remain missing; an arm does not synthesize them. Context stops at the page boundary. A case needing
another page to establish one merchant is reference-ambiguous for this experiment. The
materializer fails closed rather than truncating, downsampling, or silently dropping an arm's
declared evidence to fit an execution limit.

Arm execution order is deterministically balanced across cases, and each arm runs in a clean
context so an earlier arm cannot teach a later arm. Prompts name neither the arm nor the expected
effect. The extraction output contains only a merchant assertion with exact evidence support,
`nontransaction`, or `abstain`; ancillary fields and core financial fields are not requested.

## Measurements

The primary unit is one unambiguous reference transaction. **Merchant attribution** is correct
when all represented anchors resolve to the reference transaction, the assertion contains the
complete reference merchant-bearing evidence in order, all asserted characters are source-
supported, and it includes no merchant evidence owned by another transaction. Extra source-
grounded ancillary text from the same transaction does not make the attribution wrong, but it
prevents an exact merchant-bearing-text match. This distinction makes the right merchant
release-critical without promoting category, processor, location, or fee narrative to the same
status.

**Exact merchant-bearing text** additionally requires the assertion's ordered support and
canonical text to equal the reference under the permitted normalization, with no ancillary text
included.

Every arm reports exact integer counts and `Decimal` rates for:

- **merchant-attribution accuracy**: correct reference transactions divided by eligible reference
  transactions;
- **exact merchant-bearing-text rate**: exact canonical merchant text with exact ordered source
  support divided by eligible reference transactions;
- **omission rate**: eligible transactions answered with no merchant or abstention;
- **wrong-merchant count**: assertions owned by a different source transaction or contaminated
  with another transaction's merchant text;
- **hallucination count**: asserted merchant characters without source support;
- **ownership-error count**: anchor-to-transaction assignments that disagree with the reference;
- **reference-ambiguity count** and nontransaction-anchor accuracy as diagnostics; and
- paired per-transaction gains and losses against the preceding tier and `C5 full-page`.

Core financial agreement from the stopped pilot is retained only as historical context. It is not
recounted, and ancillary field differences are not failures in this experiment.

## Decision rule

“Best” is evaluated lexicographically:

1. an arm with any wrong-merchant or hallucination event is unsafe and cannot be recommended;
2. among safe arms, maximize the set of correctly attributed reference transactions;
3. among arms with the same correctly attributed set, maximize the exact merchant-bearing-text
   set; and
4. among arms with both sets equal, select the smallest context tier.

The predeclared context-sufficiency hypothesis is supported only if `C3 header-neighborhood` or a
smaller arm is safe and has exactly the same correctly attributed and exact-text transaction sets
as `C5 full-page`. It is falsified if every such arm loses at least one attribution or exact-text
success that `C5` achieves, or introduces a wrong-merchant or hallucination event.

`C5` is the full-page comparison ceiling, not presumed truth. If another safe arm has a strict
paired attribution or exact-text gain over `C5` without a loss earlier in the decision order, the
result is reported as a context-interference finding and that smaller arm may be the best observed
tier. If every arm is unsafe, the result is “no safe context tier” and the program stops. If only
`C5` attains the best safe result, full-page context is the answer; no additional context or rescue
experiment is implied.

Because the fixed sample is training-only, the selected tier is a measured development result,
not a production or held-out accuracy claim. Any validation run requires a later explicit user
approval and charter amendment.

## Error analysis

Every incorrect or abstained transaction receives exactly one primary predeclared category and
optional secondary categories:

- insufficient context or missing header;
- continuation ownership error;
- merchant-span boundary error;
- merchant-versus-ancillary role error;
- mixed-direction or reading-order error;
- OCR or atom segmentation error;
- neighboring-transaction contamination;
- unsupported merchant text;
- correct abstention on ambiguous visible evidence; or
- reference ambiguity or defect.

The result reports privacy-safe aggregate counts only. Error categories may explain a measured
delta but cannot be changed after arm outputs are opened.

## Minimal implementation boundary

After written-spec review and the committed authority amendment, implementation may add only:

- one narrow private reference protocol for these 100 frozen anchors;
- one deterministic materializer for the six fixed context tiers;
- one fixed-output extraction prompt and validator;
- one transaction-level scorer for the named measurements;
- focused synthetic tests for nesting, leakage, scoring, and privacy; and
- one privacy-safe aggregate experiment report and live-status update.

It must reuse existing frozen row, atom, geometry, and private-artifact conventions. It must not
add a reusable controller, CLI family, schema family, receipt chain, attestation system, cache
architecture, model-selection framework, or production integration. A missing convenience cannot
justify a second support task.

## Verification

Implementation follows repository test-driven development. Focused failing tests must first prove:

- every tier is a strict evidence superset of the preceding tier without semantic labels;
- prohibited current gold, parser output, previous reviews, and predictions cannot enter material;
- reference grouping is unavailable to an arm and used only by the scorer;
- duplicate anchors are scored once at transaction level;
- merchant normalization is limited to NFC and layout-whitespace collapse;
- wrong-merchant and hallucination events make an arm unsafe;
- the lexicographic decision selects the smallest arm with the same attribution and exact-text
  sets; and
- tracked reports cannot serialize private identities, merchant text, financial values, or source
  artifact paths.

Before committing implementation, run Ruff format checking, Ruff lint, mypy, the focused tests,
and the full tracked test suite. This shared-evaluation experiment does not alter production
parsing, so it cannot claim private-corpus acceptance and does not run the private corpus gate.

## Privacy

Rows, page images, atoms, labels, merchant strings, document identities, outputs, and derived
financial data stay under the ignored private artifact tree. Tracked files may contain only this
protocol, code and synthetic fixtures, aggregate counts/rates, the supported-or-falsified result,
and the next allowed task. Public logs must not print private paths, opaque identities, or row-level
values.

## Completion and stop

The experiment completes with exactly one frozen scoring run and the following report:

```text
Scope: YES — measured the effect of nested source context on transaction-level merchant attribution
Experiment: shared evaluation
Measurement: merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired context-tier deltas
Result: <supported or falsified hypothesis; exact aggregate arm results; smallest best safe tier or no safe tier>
Next extraction task: <one user-authorized extraction task or STOP>
```

Stop without adding support work when the reference cannot be frozen independently, leakage is
detected, fixed source evidence is unavailable, all arms are unsafe, the required aggregate result
cannot be produced, or the one authorized run completes. No failed arm is reprompted, relabeled,
or rerun to manufacture a better result.
