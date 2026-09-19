# Merchant Source-Adjudication Report

**Status:** COMPLETE — STOP. Human decisions received and measured on 2026-09-19.

**Authority:** The user's “proceed” approves the preceding six-case source
adjudication recommendation. The
[design](../superpowers/specs/2026-09-13-merchant-adjudication-design.md) and
charter allowance were committed at `309da14` before private preparation.

## Result

All **six adjudications resolve a present merchant and transaction owner** under
the submitted human decisions. Each has an explicit source-check confirmation
and a reason. There are zero reported ambiguities, absences, missing targets,
unreviewed cases, or declared source issues. The predeclared all-six-resolution
hypothesis is **supported** by the human source review.

All six adjudications match the **second reading** for merchant text, merchant
regions, and transaction regions. No third text or region version was introduced.

| Component | Matches first reading | Matches second reading | Matches neither |
| --- | ---: | ---: | ---: |
| Merchant text | 2/6 | 6/6 | 0/6 |
| Merchant region set | 1/6 | 6/6 | 0/6 |
| Transaction region set | 1/6 | 6/6 | 0/6 |

Agreement columns overlap where the two prior readings already matched. Text
uses the unchanged NFC plus collapsed-whitespace equality. Region comparisons
ignore rectangle list order and preserve duplicate multiplicity; merchant and
transaction regions are compared separately.

Compared with the first submission, the final decisions select **four changed
merchant strings**: one digital case and three OCR cases. They select changed
merchant and transaction region sets in **all five OCR cases**; the digital
case's regions match both earlier readings. All five OCR cases and the one
digital case are resolved; their decisions introduce no third variant.

Resolution reflects the user's source adjudication, not independent reviewer
agreement or independently measured semantic accuracy. Region changes alone are
not counted as proven ownership errors. The decisions are retained separately;
the original 24-reference dataset and its **13/24** extraction score are unchanged.
No prediction was rescored against the adjudications.

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

At handoff all six final decisions started blank, with no regions selected, unreviewed status,
no source-check confirmation, and no case confirmation. Either human reading
can be explicitly copied into an editable draft; this never confirms a result.
The reviewer can choose a different reading, redraw regions, or retain unresolved
ambiguity, absence, or a missing target. Every decision requires a source-check
confirmation and a short reason. Editing a decision invalidates its confirmation
and requires a new source check.

The worksheet retains local draft save/load and exports
`merchant-adjudication-answers.json`. Old seed or blind-review answer files are
rejected. The final submission is retained separately. Both previous
submissions, the original reference, and the **13/24** extraction score remain
unchanged. No automatic reference promotion occurs.

## Handoff verification

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

## Submitted-decision measurement and verification

The existing worksheet validator accepts all six submitted records against the
fixed target identities, statuses, regions, and confirmation requirements. The
uploaded file is preserved byte for byte under the ignored adjudication directory.
All 12 displayed prior readings and region sets are rechecked against their
preserved source submissions before comparison. Selection still agrees with the
six-case union from the repeat audit; there is no resampling.

Nine protected inputs, including all three answer files, the original reference,
worksheet, target mapping, and repeat-audit selection, remain unchanged during
measurement. No source rendering, OCR, model call, prediction access, extraction,
or label overwrite occurs. The reason text is retained as human annotation data.

Seventeen focused invented-input tests failed at the unimplemented helpers and
then passed. They cover shared/first/second/new agreement categories, preserved
absence and uncertainty categories, draft exclusion, and the fixed all-six
hypothesis. All five private Python files pass Ruff formatting/lint and strict
mypy checks.

A separate computation using independently expressed normalization and region
multisets agrees with all **12 text-pair and 24 region-pair comparisons**, all
aggregate agreement categories, and the six resolved-present outcomes. It also
checks that the stored submission matches the uploaded bytes.

Required repository gates pass: Ruff format (195 files), Ruff lint, mypy (48
source files), and **3,766 tests in 99.63 seconds**. No tracked production code
changed; this is not private-corpus acceptance. No merge or push was performed.
Private case results and aggregate measurement artifacts remain under ignored
`artifacts/merchant-adjudication-v1/`; only aggregate documentation is tracked.

## Golden-dataset implication and next recommendation

The six measured disagreements now have explicit, source-checked human decisions.
The existing seed remains training-only: 13 cases have one source reading, five
have matching repeat readings with unchanged regions, and six have this
adjudication. Those different review depths must remain visible; the 24 cases
are not an independently certified or held-out gold benchmark.

The next recommended task is to **create a separate version of the 24-case
training reference using the six adjudications and re-score the same saved
extraction outputs**. Preserve the original version, carry forward the other
18 cases, and report changes caused by corrected text and regions as a reference
update, not an extractor improvement. No new review worksheet is needed for the
six resolved disagreements. This recommendation has not been executed: no new
24-case reference or score has been created.

The authorized adjudication measurement is complete. **STOP**. Reference
promotion, prediction rescoring, extractor changes, expansion, validation/test
access, and production integration remain outside this completed task.

```text
Scope: YES — resolves measured merchant-reference text and region disagreements
Experiment: shared evaluation
Measurement: resolved-reference count, unresolved ambiguity count, and adjudicated text/region agreement with each prior reading
Result: 6/6 resolved-present references; zero unresolved cases; all six match the second reading's text and regions; all-six-resolution hypothesis supported
Next extraction task: STOP
```
