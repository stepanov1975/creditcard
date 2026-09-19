# Remaining Merchant Seed Source-Adjudication Report

**Status:** COMPLETE — STOP. Human decisions measured on 2026-09-19.

**Authority:** The user's “proceed” approves the completed remaining-case repeat
audit's recommendation to adjudicate its four changed cases. The
[design](../superpowers/specs/2026-09-19-merchant-remaining-adjudication-design.md)
and charter allowance were committed at `4a2393c` before private preparation.

## Result

All **four adjudications resolve a present merchant and transaction owner** under
the submitted human decisions. Each is confirmed, source-checked and accompanied
by a reason. There are zero absent, ambiguous, missing or unreviewed cases, and
all four source-issue fields are `none`. The all-four-resolution hypothesis is
**supported** by the human source review.

| Component | Matches first reading | Matches second reading | Matches neither |
| --- | ---: | ---: | ---: |
| Merchant text | 4/4 | 3/4 | 0/4 |
| Merchant region set | 3/4 | 4/4 | 0/4 |
| Transaction region set | 0/4 | 3/4 | 1/4 |

Agreement columns overlap where both earlier versions match. Text uses the
unchanged NFC plus collapsed-whitespace equality. Region comparisons ignore
rectangle order and preserve duplicate multiplicity, with merchant and
transaction sets compared separately.

The disputed OCR text is resolved in favor of the **first reading**. All other
merchant texts match both readings. No third merchant transcription is supplied.
All merchant-region sets match the second reading; one OCR case's merchant
regions differ from the first reading.

All four final transaction-region sets differ from the first reading. Two OCR
cases and the digital case match the second reading; the remaining OCR case
supplies a transaction-region set different from both earlier versions. This
is a human geometry correction, not independently measured extraction improvement.

Both source modes are resolved: **3/3 OCR and 1/1 digital**. Resolution is based
on the user's source adjudication, not independent semantic certification.
The decisions are retained separately; neither reference version is updated,
and the saved **17/24 v2 extraction score remains unchanged**. No prediction is
read or rescored.

## Prepared review

The local worksheet contains exactly **four cases: three OCR and one digital**.
Selection is the union of text and region changes in the completed 13-case audit:
one case with changed text and regions and three with changed regions only.
Preparation recomputes the changes from both human submissions and checks them
against the saved audit; a separate packet check independently reproduces the
selection. There is no new sampling or prediction access.

The worksheet shows **eight prior human readings, eight corresponding region
sets and all eight prior-note fields**. Four notes are nonempty. Prior notes
are displayed as plain text under their own reading; they do not fill the final
reason or alter the review instructions. Two existing full-page images are
embedded byte for byte, with local links to the original PDF copies.

The existing full-page viewer retains independently toggleable purple and green
overlays for the first and second readings. Merchant regions have shaded fills
and thicker borders; transaction regions are unfilled outlines. Region labels
identify reading and role. Final draft regions use blue for the transaction and
amber for merchant text.

At handoff all four final decisions started blank, with no regions, an unreviewed status,
no source-check confirmation and no decision confirmation. Either prior merchant
and its regions can be copied into an editable draft. Copying leaves the decision
unconfirmed and does not copy the prior note into the final reason. The reviewer
may enter a different reading, redraw regions or record absence, unresolved
ambiguity or a missing target. Every confirmed decision requires a source check,
a reason and valid regions under the existing answer contract.

The private worksheet is
`artifacts/merchant-remaining-adjudication-v1/review.html`. It retains local draft
save/load and exports **`merchant-remaining-adjudication-answers.json`**. Its new
answer-file version rejects all four earlier seed/review/adjudication versions.
At handoff the user was asked to check each case against the source, resolve its
text and regions or record uncertainty, explain the decision, confirm it and
return the saved JSON.

## Verification

- Preparation and independent packet checks agree on the exact four-case union,
  review order, three/one source-mode counts, and source-page membership.
- All eight merchant readings, region sets and note fields exactly match the
  two human submissions. Both embedded images match the original bytes and
  dimensions, and both source PDF identities match the selected documents.
- At handoff all four final decisions were blank and unconfirmed. All eight possible
  copies of earlier readings remain drafts requiring source checks and reasons.
  Blank drafts round-trip through export/import; earlier answer versions fail.
- Four new invented-input tests fail against the unadapted form and pass after
  adaptation. The ten existing checks continue to pass: **14 tests total**.
  The new tests cover answer identity and prior-note display, including literal
  markup-like text, navigation between cases, empty-note placeholders, and a
  final reason that remains separate from a copied human reading.
- Prior-note event behavior is exercised with a minimal simulated DOM using
  the actual form script and invented data. This is not a real-browser layout,
  pointer interaction or rendering test. No private source pixels are inspected
  by the model.
- Packet checks verify allowed fields, exact HTML/template/script assembly,
  required controls, an unchecked source-confirmation box, safe text insertion,
  local resources and the connection-blocking content security policy.
- Preparation preserves 16 protected inputs; packet verification preserves
  16 inputs, with overlap between the sets. Original references, submissions,
  mappings, images and review-depth metadata remain unchanged.

Private Python formatting, lint and strict mypy checks pass, as do JavaScript
syntax checks and the 14 form tests. Required repository checks pass: Ruff
formatting (195 files), Ruff lint, mypy (48 source files), and **3,766 tests in
100.01 seconds**. Tracked production code remains unchanged. No private-corpus
acceptance, merge or push is claimed.

The HTML embeds its source images and can be opened in a browser. Full-source
PDF links depend on the existing local workspace copies. Private readings,
notes, identities, geometry and eventual decisions remain under ignored local
paths; only aggregate documentation is tracked.

## Submitted-decision measurement and verification

The uploaded `merchant-remaining-adjudication-answers.json` is preserved byte
for byte in the ignored adjudication directory. The existing worksheet validator
accepts all four fixed identities, statuses, source checks, reasons, confirmation
flags and region sets. Notes and reasons remain human annotation data.

Selection still matches the four-case union in the saved 13-case repeat audit.
All eight displayed prior readings, region sets and notes match their preserved
submissions exactly. Original training membership and the v2 single-read snapshot
are checked against the private mapping. No resampling occurs.

The fixed all-four hypothesis helper is adapted from the earlier six-case rule.
Eight focused tests fail before its implementation and then pass, alongside ten
existing agreement/status tests: **18 Python tests total**. They cover a complete
four-case resolution, absence/ambiguity/missing outcomes, incomplete responses,
and rejection of an incorrect denominator. All **14 form tests** also pass.

An independent calculation using separately expressed text normalization and
Decimal coordinate multisets agrees with **eight text-pair and 16 region-pair
comparisons**. All aggregate resolution and agreement fields agree for the
overall, digital and OCR slices. Uploaded-byte equality also passes.

Measurement preserves 12 protected inputs, including both reference versions,
the existing review-depth snapshot, the human submissions and review packet.
Independent verification preserves six inputs, overlapping those above. No source
rendering, OCR, text extraction, model call, prediction access, reference overwrite
or review-depth update occurs. Private Python formatting, lint and strict mypy
checks pass. Required repository checks pass: Ruff formatting (195 files), Ruff
lint, mypy (48 source files), and **3,766 tests in 99.80 seconds**. Tracked
production code remains unchanged. This is not private-corpus acceptance;
no merge or push was performed.

## Golden-dataset implication and next recommendation

The remaining four changed cases now have explicit source-checked decisions.
Together with the completed earlier adjudication and repeat audits, this finishes
the human review steps for the current 24-case seed. The evidence remains from
one reviewer, not an independent or held-out gold benchmark.

The next recommended task is to **create a separate fully reviewed v3 training
reference and rescore the unchanged saved outputs**. Incorporate these four
decisions, preserve the other 20 v2 records and both older versions, and record
the completed review depths: 14 agreeing repeat readings and ten source
adjudications. Separate text-reference effects from alignment effects caused by
updated regions, as in the previous comparison. No new review worksheet is
needed for these resolved cases.

This recommendation has not been executed or authorized by the completed
adjudication: no v3 reference or new score was created. The four-decision
measurement is complete. **STOP**. No label promotion, new extraction, prediction
rescoring, expansion, further review, held-out access or production integration
is active.

```text
Scope: YES — resolves measured merchant-reference text and region disagreements
Experiment: shared evaluation
Measurement: resolved-reference count, unresolved ambiguity count, and adjudicated text/region agreement with each prior reading
Result: 4/4 resolved-present references; zero unresolved cases; all text matches the first reading; one transaction-region set matches neither prior version; all-four-resolution hypothesis supported
Next extraction task: STOP
```
