# Remaining Merchant Seed Source-Adjudication Report

**Status:** AWAITING_HUMAN_ADJUDICATION. Prepared on 2026-09-19.

**Authority:** The user's “proceed” approves the completed remaining-case repeat
audit's recommendation to adjudicate its four changed cases. The
[design](../superpowers/specs/2026-09-19-merchant-remaining-adjudication-design.md)
and charter allowance were committed at `4a2393c` before private preparation.

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

All four final decisions start blank, with no regions, an unreviewed status,
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
The user should check each case against the source, resolve its text and regions
or record uncertainty, explain the decision, confirm it and return the saved JSON.

## Verification

- Preparation and independent packet checks agree on the exact four-case union,
  review order, three/one source-mode counts, and source-page membership.
- All eight merchant readings, region sets and note fields exactly match the
  two human submissions. Both embedded images match the original bytes and
  dimensions, and both source PDF identities match the selected documents.
- All four final decisions are blank and unconfirmed. All eight possible
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

## Pending measurement

**Resolved-reference counts, unresolved ambiguity, adjudicated agreement and
hypothesis are NOT MEASURED.** No final human decisions have been supplied for
this four-case review. Packet preparation does not establish reference resolution.

After the user returns the four decisions, retain them separately and validate
them against the existing answer contract. Measure confirmed present/absent,
ambiguous/missing/unreviewed counts and final text/region agreement with each
prior reading, including digital/OCR slices. Apply the predeclared all-four
resolution hypothesis without automatically choosing or promoting a reading.

Both reference versions, the existing review-depth snapshot and the saved
**17/24 v2 score** remain unchanged. Source adjudication by the same reviewer
does not establish independent semantic accuracy.

The sole active phase is paused at **AWAITING_HUMAN_ADJUDICATION**. Receive and
measure the fixed four decisions, then STOP. No label promotion, new extraction,
prediction rescoring, sample expansion, further review, held-out access or
production integration is authorized.
