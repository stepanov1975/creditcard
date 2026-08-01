# Visual-Gold v2 100-Row Pilot Report

**Status:** `STOP` — the pre-adjudication field-exact agreement gate failed.

**Updated:** 2026-08-01

## Task contract

```text
Scope answer: YES — this directly tests whether visually reconstructed extraction supervision is stable enough to continue.
Experiment: shared evaluation
Extraction hypothesis: Reviewer A and B achieve at least 95% row-type and 90% field exact agreement with 100% validity.
Measurement: row-type agreement, field exact agreement, atom-support agreement, source-region agreement, and validity
Fixed inputs: frozen Reviewer A and Reviewer B decision streams, locked 100 pilot rows, and no current gold/predictions
Smallest allowed files: one ignored private disagreement stream and the two authorized aggregate tracked reports
Required output: gate result and privacy-safe aggregate counts/rates
Stop condition: if validity is below 100%, row-type agreement is below 95%, or field exact agreement is below 90%, record the result and STOP before adjudication or further review
```

## Frozen pre-adjudication measurement

The comparison used the complete frozen 2,503-row training population as validation context.
The 100 selected rows were derived only from the locked packet identities. Both frozen reviewer
streams contained exactly 100 records.

| Measurement | Numerator | Denominator | Exact `Decimal` rate | Gate |
| --- | ---: | ---: | --- | --- |
| Row type | 98 | 100 | `0.98` | PASS (`>= 0.95`) |
| Field exact | 386 | 473 | `0.8160676532769556025369978858` | **FAIL** (`>= 0.90`) |
| Atom support | 384 | 414 | `0.9275362318840579710144927536` | Diagnostic only |
| Source region | 376 | 414 | `0.9082125603864734299516908213` | Diagnostic only |

Annotation validity was 100% (`valid=true`). The overall pilot gate failed because field-exact
agreement was below its inclusive threshold. Row-type agreement met its threshold. The frozen
comparison contains 57 disagreement records; aggregate disagreement-category counts are 2 row
type, 1 ambiguity, 36 field presence, 26 canonical value, 24 atom support, and 30 source region.

## Single-invocation and gate attestation

- `compare_visual_reviews(population, selected_rows, reviewer_a, reviewer_b)` was called exactly
  once on the frozen inputs.
- The returned summary was captured once and was not recomputed.
- The returned disagreement tuple was written once through the canonical atomic JSONL writer in
  the same one-off invocation, then reread as exactly 57 typed records.
- The predeclared gate was evaluated exactly once from the captured frozen summary.
- The comparison artifact is a regular file, ignored by Git, and read-only. No atomic temporary
  file remained. Input size, mode, inode, and modification-time metadata were unchanged.

## Serialization and privacy audit

The aggregate summary serialized exactly 15 fields: seven integer count fields, four `Decimal`
rate fields, and four boolean validity/gate fields. Its field set was exactly:
`row_count`, `row_type_matches`, `row_type_agreement`, `eligible_field_slots`,
`exact_field_matches`, `field_exact_agreement`, `joint_field_slots`,
`atom_support_matches`, `atom_support_agreement`, `source_region_matches`,
`source_region_agreement`, `valid`, `row_type_gate_passed`,
`field_exact_gate_passed`, and `pilot_passed`.

The private disagreement model contained exactly opaque document identity, opaque row identity,
and disagreement kinds. It had no Reviewer A/B value fields. Controller-visible comparison output
contained aggregate counts, rates, and booleans only. No current gold, accepted parser or baseline
output, predictions, source filenames, images, adjudication artifacts, or future-task artifacts
were read.

## Stop enforcement and self-review

- No adjudication was started and no Reviewer C or candidate-gold artifact was created.
- Current gold remained unopened.
- Labels, thresholds, prompts, canonicalization, comparison logic, and extractors were unchanged.
- No support task or replacement pilot was launched.
- The only tracked changes are this aggregate report and the program-status `STOP` update.
- The pre-existing unrelated untracked files were preserved.

## Metric-or-Stop

```text
Scope: YES — measured blind visual reconstruction of extraction supervision on the fixed training pilot
Experiment: shared evaluation
Measurement: row-type agreement, field exact agreement, evidence-support agreement, validity, ambiguity, and annotation-defect categories
Result: FAIL — validity 100%; row type 98/100 = 0.98; field exact 386/473 = 0.8160676532769556025369978858; atom support 384/414 = 0.9275362318840579710144927536; source region 376/414 = 0.9082125603864734299516908213; 1 ambiguity disagreement; annotation-defect categories were not measured because the binding stop occurred before current-gold inspection
Next extraction task: STOP
```
