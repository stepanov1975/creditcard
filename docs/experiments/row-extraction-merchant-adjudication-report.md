# Merchant Source-Adjudication Handoff

**Status:** AWAITING_HUMAN_ADJUDICATION — no adjudicated result has been submitted.

**Authority:** The user's “proceed” approves the preceding six-case source
adjudication recommendation. The
[design](../superpowers/specs/2026-09-13-merchant-adjudication-design.md) and
charter allowance were committed at `309da14` before private preparation.

## Prepared review

The worksheet contains the exact **six cases** with text or region changes in
the completed repeat-reading audit: **five OCR cases and one digital case**.
Three have changed text and regions, two have changed regions only, and one has
changed text only. Selection is reproduced from both submissions and agrees
with the saved audit. No new case or model output is selected.

Each case shows the first and second human merchant readings side by side,
with their original transaction and merchant region sets. Three existing
full-page source images are reused byte for byte. Independently toggleable
purple and green overlays show the two versions on the same page. Prior merchant
regions have shaded fills and thicker borders; prior transaction regions are
unfilled outlines. Hover and accessibility labels identify each box's reading and
role. Final draft transaction and merchant regions use blue and amber.

All six final decisions start blank, with no regions selected, unreviewed status,
no source-check confirmation, and no case confirmation. Either human reading
can be explicitly copied into an editable draft; this never confirms a result.
The reviewer can choose a different reading, redraw regions, or retain unresolved
ambiguity, absence, or a missing target. Every decision requires a source-check
confirmation and a short reason. Editing a decision invalidates its confirmation
and requires a new source check.

The worksheet retains local draft save/load and exports
`merchant-adjudication-answers.json`. Old seed or blind-review answer files are
rejected. The final submission will be retained separately. Both previous
submissions, the original reference, and the **13/24** extraction score remain
unchanged. No automatic reference promotion occurs.

## Verification

- All six selected cases agree with the saved union of text and region changes.
- All 12 displayed human readings and 12 corresponding region sets match their
  source submissions exactly. Private case mapping preserves both prior IDs.
- All three embedded page images match the existing image bytes and dimensions;
  local PDF links resolve, and the source identities match their selected copies.
- All six final decisions are blank and unconfirmed. All 12 possible copies of
  prior readings remain drafts requiring a source check and reason.
- Ten invented-input form tests pass. Nine exposed missing adjudication behavior
  before adaptation; the existing incomplete-draft behavior already passed.
  Tests cover unselected defaults, deep-copy independence, confirmation
  invalidation, mandatory source checks/reasons, revised readings, unresolved
  decisions, incomplete save/load, invalid regions, and incompatible old files.
- Packet checks verify the blank draft round trip, expected controls, no model
  output fields, local resources, and a connection-blocking content security
  policy. Prior human strings are displayed as text, not interpreted as markup.
- All 14 input files read or identity-checked during preparation are unchanged.
  No rendering, OCR, source-text extraction, new prediction, or prediction
  scoring occurs.

Read-only code review identified an overlay role distinction that was corrected:
prior merchant regions now have distinct fills and widths, and every rectangle
has a reading/role label. The reviewer confirmed the correction and found no
remaining actionable issue. Embedded case data was unchanged by the presentation
update; form and packet checks pass again.

Private Python formatting, lint, and strict type checks pass; JavaScript syntax
checks pass. The required repository checks pass: Ruff format (195 files), Ruff
lint, mypy (48 source files), and **3,766 tests in 99.52 seconds**. No tracked
production behavior changed. This is not private-corpus acceptance, and no
merge or push was performed.

Browser interactions have not been exercised in a real browser in this
environment. The worksheet was queued in the Codex file panel. Its HTML embeds
the selected source-page images and can be opened in a browser; broader PDF
context links refer to the existing local workspace copies.

All human readings, source pixels, geometry, mappings, and eventual decisions
remain under ignored local paths. Only aggregate documentation is tracked.

## Pending measurement

**Zero adjudications have been submitted.** Resolved-reference count, unresolved
ambiguity, agreement with each earlier version, and the all-six-resolution
hypothesis remain **NOT MEASURED**. Preparation is a handoff within this authorized
measurement, not an extraction improvement or a completed gold dataset.

After the six decisions arrive, retain them separately, validate the fixed case
coverage and confirmations, and measure the predeclared resolution categories
and agreement with each earlier reading. Missing or ambiguous decisions remain
explicit. A same-reviewer adjudication is not independent semantic certification.

The sole active phase is paused for these human decisions. No label replacement,
prediction rescoring, extractor change, expansion, validation/test access, or
production integration is authorized by this handoff.
