# Merchant Discovery Coverage Trace Report

**Date:** 2026-09-12  
**Status:** `COMPLETE — STOP: original snapshot unavailable`  
**Authority:** [Design](../superpowers/specs/2026-09-12-merchant-discovery-coverage-design.md),
[plan](../superpowers/plans/2026-09-12-merchant-discovery-coverage.md), and charter
amendment committed at `8675770` before the targeted private availability check.

The original discovery snapshot needed for the affected page was not retained
in the bundle or identified in the checked artifact inventory: **0/1 required
snapshots available**. Historical discovery-to-frozen row loss is **NOT MEASURED**.
The hypothesis that freezing omitted an overlapping discovery row is neither
supported nor falsified by this availability result.

## What was checked

The targeted check confirmed the same **four unmatched training references** on
one page and its **38 frozen rows**. The original bundle contains three derived
data streams—rows, accepted predictions, and a crop index—plus their identity
files and rendered crops. It contains no full discovery snapshot or retained
preparation staging directory.

The checked local artifact root contains **18 separate `results.json` files**:
16 under corpus-run roots and two under control-run output roots. These are
separate runs, not original discovery objects retained by bundle preparation.
No discovery-named JSON snapshot was found. No separate result payload was opened
or used as a substitute, and no unrelated statement or reviewer data was decoded.
This is an availability finding within the checked local artifacts, not a claim
that no external backup could exist.

## Historical code evidence

At historical foundation revision `c70895aa8a0cfb08137299c4e6fa8e56023b3e40`,
`prepare_bundle` calls `parse_statement` and keeps the result in memory. It writes
rows, accepted-prediction projections, and crop records, then removes temporary
parts. It does not serialize the full `StatementResult` or its discovery object.

`rows_from_statement` iterates every row in the discovered table regions and
copies each row's page number and box into a frozen row. There is no row-selection
filter in that conversion; count and duplicate-identity checks reject inconsistent
inputs. This code makes an upstream discovery/region limitation more plausible
than a filtering step during freezing. That is a **code-based inference**, not
an independently measured account of this page's historical discovery result.

| Required measurement | Result |
| --- | --- |
| Original discovery snapshots available | 0/1 pages |
| Original discovery row count | NOT MEASURED |
| Rows omitted during freezing | NOT MEASURED |
| Original discovery coverage of four reference regions | NOT MEASURED |
| Unchanged frozen page population | 38 rows |
| New extraction runs | 0 |

The previous finding remains: the four marked regions overlap no frozen rows or
atoms, with coordinate checks agreeing. Their semantic correctness and the exact
upstream reason for missing coverage remain unresolved. The best measured
merchant result stays **10/24**, including these four alignment failures.

## Stop and next recommendation

The predeclared missing-snapshot stop applies. No historical metadata was
reconstructed, no later parser result was substituted, and no archival or
controller infrastructure was added.

Recommended next measurement: run one new local discovery diagnostic on the same
source page and quantify row coverage against the four unchanged reference
regions. Clearly identify it as a new diagnostic run, without calling it the lost
original or replacing the frozen dataset. This is a separate proposed extraction
measurement and has not begun.

## Verification

The required repository gates passed: Ruff format/check, mypy over `src`, and
**3,766 repository tests**. The private inventory script also passed Ruff and
strict mypy, then completed its targeted availability check. No new production
behavior or geometry-comparison helper was added, so no additional behavioral
tests were needed for this inventory-only stop.

Original target references, submitted answers, frozen rows, alignment, and merchant
summary bytes remained unchanged. Only aggregate documentation is committed;
private target identities and the inventory remain ignored under
`artifacts/merchant-discovery-coverage-v1/`. No production parser code changed,
no private-corpus gate ran, and no corpus-acceptance claim is made.

```text
Scope: YES — quantified original-discovery availability for the four-case extraction coverage trace
Experiment: shared evaluation
Measurement: original-discovery availability and discovery/frozen row coverage loss
Result: 0/1 original snapshots available; historical row-loss hypothesis NOT MEASURED; four unresolved references and 38 frozen rows retained, merchant score unchanged at 10/24
Next extraction task: STOP
```
