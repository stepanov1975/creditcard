# Experiment findings

This is a synthesis of saved aggregate reports, not a new run. The
[live status](../experiments/row-extraction-program-status.md) records the current
objective and outstanding human dependencies.
Results below use different populations, targets and reference versions; they
must not be presented as one continuous accuracy curve.

## Four extraction approaches: no accepted winner

Round 1 compared per-row OCR, deterministic profiles, lightweight text and
lightweight image/text extraction. All had zero exact validation matches. Profiles
were frozen eligible but abstained everywhere; OCR stopped with unsupported or
hallucinated fields; text could not represent overlapping evidence with a
single-label target; vision had zero eligible validation rows and no pixel gain.
This does not mean every individual field was wrong. See the
[frozen outcome record](../experiments/row-extraction-program-history.md#frozen-round-1-status).

A supervision diagnosis and Round 2 are preserved on a side branch, not merged
into the latest implementation. Merchant description evidence matched 1,457/1,457
development descriptions and 16/16 validation descriptions. All 16 otherwise
eligible validation rows had overlapping amount/kind ownership under the old
single-label target. Deriving `kind` and masking ambiguous/unrepresentable fields
raised field-supervised rows from 345 to 1,487 in development and 0 to 16 in
validation. This repaired representability, not extraction accuracy.

Round 2 used 2,503 frozen development rows:

| Arm | Complete exact rows | Accepted / abstained | Finding |
| --- | --- | --- | --- |
| Text, both fixed candidates | 0 | 0 / 2,503 | No complete-row gain; no unsupported evidence, collisions or hallucinations. |
| OCR | 33 | 2,100 / 403 | 2,009 unsupported-evidence events, 253 ownership collisions, 6,379 field hallucinations; safety hypothesis failed. |
| Profiles, all three policies | 53 | 131 / 2,372 | Zero unsupported evidence, but 78 ownership collisions and 78 description hallucinations; safety hypothesis failed. |
| Vision, pixels on and off | 0 | 0 / 2,503 | No exact field matches; 7,761 omissions in each; pixels-off row typing was stronger (1,237 versus 1,198 correct). |

Source: [immutable Round 2 terminal record](https://github.com/stepanov1975/creditcard/blob/295c4ab5a422d1aed92bb73c35fa43ca63f34ddb/docs/experiments/row-extraction-program-status.md).
That commit is retained locally even if a remote link is unavailable; retrieve it
with `git show 295c4ab5a422d1aed92bb73c35fa43ca63f34ddb:docs/experiments/row-extraction-program-status.md`.
All four experiments stopped. No held-out result or accepted validation winner
followed. Infrastructure or a more elaborate model does not fix missing evidence,
unrepresentable targets or unsafe ownership by itself.

## Reference quality and available context come first

The [100-row visual-gold pilot](../experiments/row-extraction-visual-gold-v2-pilot-report.md)
had 100% annotation validity and 98/100 row-type agreement, but only 386/473
field-exact agreement (81.61%), below its 90% gate. It stopped before adjudication.
Agreement is reviewer consistency, not extraction accuracy or independent truth.
Overlapping disagreement categories cannot be summed as disjoint errors.

The [context experiment](../experiments/row-extraction-merchant-context-report.md)
could materialize only 17/100 anchors: 83 failed declared geometry/context
requirements. No reference, extraction arm or score was created. Merchant
accuracy and the best context tier were **not measured**. This failure does not
establish that the original full pages were unreadable.

The subsequent [merchant seed](../experiments/row-extraction-merchant-gold-seed-report.md)
contains 24 human-reviewed transactions on six training pages from six documents:
16 digital cases and eight OCR cases. A source-page reference can expose omissions
that a detected-row-only reference cannot. Keep failed alignment cases in the
denominator instead of filtering them away.

## Merchant results: distinguish extraction from reference changes

Official matching uses NFC and collapsed Unicode whitespace, preserving case,
punctuation and reading order. Whitespace-free signatures and reference-guided
ordering witnesses are diagnostics, not official exact matches.

| Step and evidence | Result | Interpretation |
| --- | --- | --- |
| [Seed comparison](../experiments/row-extraction-merchant-seed-comparison-report.md) | OCR 8/24; frozen profiles and stored parser projection 0/24; alignment 20/24 | Stored evidence projection is not a measurement of current production parser accuracy. Text/vision were unavailable, not scored as zero. |
| [Before row rejection](../experiments/row-extraction-merchant-pre-rejection-report.md) | Profiles merchant proposals 0 to 8/24; output coverage 1 to 18/24 | Whole-row currency rejection concealed usable merchant proposals; financial decisions stayed fixed. |
| [Reading order](../experiments/row-extraction-merchant-reading-order-report.md) | 8 to 10/24, two gains, no losses | Directional-run geometry helped on this seed. |
| [Region OCR](../experiments/row-extraction-merchant-region-ocr-report.md) | 10 to 8/24, zero gains, two losses | Re-OCR of selected crops was worse; retain the stronger comparator. |
| [Pre-filter comparison](../experiments/row-extraction-merchant-prefilter-comparison-report.md) | 10 to 13/24; alignment 24/24, unique output 22/24 | Merchant evidence excluded from billed-row discovery was useful diagnostically. This is not permission to bill future transactions. |
| [Continuation assembly](../experiments/row-extraction-merchant-continuation-assembly-report.md) | 13/24 unchanged; output coverage 22 to 23/24 | Coverage and exactness are separate. |
| [Region alignment](../experiments/row-extraction-merchant-region-alignment-report.md) | 13/24 unchanged; output coverage 23 to 24/24 | Reference-guided measurement, not an independently deployable alignment improvement. |
| [Reference v2](../experiments/row-extraction-merchant-reference-v2-report.md) | Same outputs: 13 to 17/24; no alignment changes | Four gains are corrected reference text, not better extraction. |
| [Reference v3](../experiments/row-extraction-merchant-reference-v3-report.md) | Same outputs: 17/24; no assignment changes | All cases now have second readings/resolution by the same reviewer: 14 agreeing repeats, ten adjudications. |
| [Geometry spacing](../experiments/row-extraction-merchant-spacing-report.md) | 17/24 unchanged | Changed outputs did not yield an exact-match gain. |
| [Punctuation spacing](../experiments/row-extraction-merchant-punctuation-spacing-report.md) | 17 to 19/24; two gains, no losses; coverage 24/24 | At this stage: 13/16 digital, 6/8 OCR. |
| [LTR glyph reconstruction](../experiments/row-extraction-merchant-ltr-glyph-candidate-report.md), [block ordering](../experiments/row-extraction-merchant-ltr-block-order-report.md), [tolerance](../experiments/row-extraction-merchant-ltr-tolerance-report.md) | Each remains 19/24 | No measured exact-match gain from these candidates. |
| [Unchanged-order spacing](../experiments/row-extraction-merchant-unchanged-order-spacing-report.md) | 19 to 21/24, two gains, no losses; coverage 24/24 | Completed seed result under the earlier reference definition. |
| [Document-disjoint complete-field pilot](../experiments/row-extraction-merchant-document-disjoint-evaluation-report.md) | All three frozen views have identical strings and 49/89 text matches; 85/89 aligned | Six human-confirmed training-page censuses. No text gain; AI ownership findings prepared for human confirmation. This does not measure the later production parser fix. |

The seed is small, repeatedly inspected training data from one reviewer. Fully
reviewed does not mean independently certified gold. None of these results is
validation accuracy, a population estimate or private-corpus acceptance.

The [fresh continuation evaluation](../experiments/row-extraction-continuation-fresh-sample-report.md)
now has 16 human-confirmed fields and six confirmed censuses. Both parsers match
all 16 transactions but have **0/16 exact merchant fields**, with identical outputs
and zero gain. AI review finds 16 outside-field indicators and six lost continuations
routed as subordinate detail. Ownership confirmation remains pending; no OCR
transaction references were sampled, so the two-mode hypothesis is inconclusive.

## What the error studies taught us

- **Honor ownership through downstream interpretation.** The bounded
  [field ownership correction](../experiments/row-extraction-field-ownership-report.md)
  fixes 11 synthetic failures with six controls preserved. Separate-column text
  must not enter the merchant via cell clustering, and merchant lines inside a
  detail block must not disappear or become fee evidence. Generalization to new
  documents remains unmeasured; the scored evaluations stay frozen.
- **Test continuation loss through discovery as well as normalization.** The
  [synthetic continuation fix](../experiments/row-extraction-complete-field-continuations-report.md)
  raises complete-field regressions from 9/29 to 29/29 with all nine rejection
  controls preserved. Token-shaped fields, multiple wrapped lines and split
  continuation cells are covered. This is development evidence, not new-document
  accuracy or a rescore of the frozen pilot.
- **Preserve the complete merchant field.** The six-document pilot's AI source
  review finds 23 outside-field indicators, 12 other incomplete fields and four
  unmatched transactions; 15 of the 23 also miss continuations. These provisional
  findings favor field selection and discovery work over more spacing changes.
  Codes and location words inside the merchant field must remain in the output.
- **Locate missing evidence before changing extraction.** Four seed failures had
  no overlapping frozen atoms. The historical discovery snapshot was unavailable,
  so historical freezing loss was not measurable. A separate fresh diagnostic
  traced all four exclusions to future-billing filtering. The distinction between
  a historical replay and a new diagnostic matters.
- **Separate source text, ownership, ordering and separators.** Some evidence was
  correctly located yet incorrectly rendered; an omission's merchant atoms belonged
  to a different primary owner under saved routing. Proximity alone would obscure
  the source of the failure.
- **Use controls before relaxing a rule.** Six incorrect separators shared a
  retention reason with four necessary control spaces. Punctuation geometry then
  distinguished six incorrect boundaries from three required punctuation controls
  on the declared sample. The resulting candidate gained two exact matches;
  simply dropping all spaces would have been unsupported.
- **Trace glyphs before reversing strings.** Of the three remaining digital
  failures at 19/24, two had equal non-whitespace character inventories and one
  lacked four characters. Intact-atom ordering could not solve the first two.
  Three reverse-only LTR atoms were already reversed in native word extraction,
  while glyph geometry supported their source order. Glyph correction changed
  text but alone did not improve exact match.
- **A blocked guard need not be the final error.** Seven owner groups had tiny,
  crossing box overlaps with consistent independent order. Relaxing the guard
  using the existing tolerance still changed no order or output because all seven
  were already ordered. The latest corrected-output diagnostic found both selected
  residual cases were whitespace-only and each had one identity-order witness.

The [detailed report index](evidence-index.md) retains intermediate findings,
including null and falsified results. Historical recommendations are not an active
backlog. The unchanged-order renderer result is already recorded above; consult
the live status for the next task rather than restarting an old recommendation.

## Research conclusions to carry forward

The existing [research notes](evidence-index.md#research) motivate source-grounded
outputs, document-disjoint evaluation, abstention calibrated to complete-row
correctness, matched pixels-on/off controls, and separate recognition/structure/
semantics measurements. Published OCR similarity or entity F1 is not exact
financial/merchant accuracy on Hebrew statements. Those notes are dated literature
assessments, not current model recommendations or evidence that a larger model
would work here. Cascade and integration proposals remain frozen.
