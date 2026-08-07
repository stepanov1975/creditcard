# Merchant Context Sufficiency Experiment Report

**Status:** `STOP` — the first and only materialization attempt failed atomically before an
independent reference or any extraction arm was created.

**Date:** 2026-08-07

## Fixed execution population

The committed Task 3 implementation was run against the frozen training-only pilot selection.
The privacy-safe aggregate selection was `population_count=2503`, `selected_count=100`, and
`split=train`. The selected population was unique and complete.

## Pre-arm materialization result

The first and only materialization attempt stopped with the sanitized error `merchant context
geometry unavailable`. It left no private artifact tree. Aggregate read-only diagnosis found 17
materializable anchors and 83 anchors with unavailable geometry.

The declared context checks produced:

| Declared context check | Aggregate failure count |
| --- | ---: |
| `C0 row` visibility | 0 |
| `C1 adjacent-rows` visibility | 0 |
| `C2 local-neighborhood` visibility | 0 |
| `C3 header-neighborhood` visibility | 0 |
| `C4 table-region` visibility | 79 |
| `C4 table-region` missing required `C2` rows | 4 |
| `C4 table-region` not a superset of `C3` | 38 |
| `C5 full-page` visibility | 0 |

The `C4` visibility failures occurred because row and atom bounds fell outside the declared
detected table region. The diagnostic categories overlap; their union is 83 anchors, not their
sum. Continuing would therefore truncate or omit declared context, which meets the binding
fail-closed stop condition.

## Experiment outcome

- Hypothesis result: `NOT MEASURED`
- Smallest best safe context tier: `NOT MEASURED`
- Recommended context tier: `NOT MEASURED`
- Planned merchant-attribution measurements: `NOT MEASURED`

No independent reference was created. No extraction arm ran, no predictions or error labels were
created, and the scorer invocation count was 0. The predeclared context-sufficiency hypothesis is
neither supported nor falsified.

## Metric-or-Stop result

```text
Scope: YES — quantified whether the declared nested source contexts could be materialized without truncation for transaction-level merchant attribution
Experiment: shared evaluation
Measurement: transaction-level merchant-attribution accuracy, exact merchant-bearing-text rate, omission rate, wrong-merchant count, hallucination count, ownership-error count, and paired accuracy delta by context tier — NOT MEASURED
Result: Aggregate pre-arm STOP — population_count=2503, selected_count=100, split=train; context-materialization eligibility=17/100, declared-context truncation count=83/100, and geometry unavailable=83/100; no reference, arm, or score was produced, so hypothesis result and smallest/recommended tier are NOT MEASURED
Next extraction task: STOP
```

This is a training-only aggregate experiment stop. It is not a validation, held-out, production,
or private-corpus acceptance result.
