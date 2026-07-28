# Row-text models, calibration, and conservative abstention

**Research date:** 2026-07-28
**Code baseline reviewed:** `dee4b071ad65231da13825f2f7c74a488ca96c7c`
**Scope:** transaction-row recognition and field extraction from already-local OCR/PDF
tokens. This note does not inspect or report any private document, annotation, cache,
output, merchant, amount, or other financial datum.

## Executive conclusion

The safest useful model for this parser is not a generative document model. It is a
small discriminative *advisor* that labels existing rows or existing evidence atoms,
followed by the parser's current deterministic, evidence-backed extractors.

The recommended evaluation order is:

1. A hashed character/token-shape linear row classifier, with approximately 2.5 MiB
   of float64 coefficients for five classes and `2**16` hashed features, plus small
   metadata.
2. A linear-chain CRF over existing OCR tokens, using text-shape, normalized geometry,
   inferred column role, OCR confidence, and neighboring-token features. Its serialized
   model size is data-dependent and must be measured, but the current
   `python-crfsuite` 0.9.12 Linux wheel is about 1.2 MiB and supports Python 3.13.
3. Only if those baselines leave material, reproducible headroom: token-classification
   challengers such as Hebrew `dicta-il/dictabert-tiny` (44.9M parameters) and English
   MobileBERT (25.3M), or one 134M-parameter multilingual DistilBERT.

The model should predict a closed structural vocabulary such as
`primary_transaction`, `continuation`, `header_or_total`,
`nontransaction_table_row`, and `other`. Existing deterministic code should subtype a
continuation into the current `ContinuationKind`/`RowTag` vocabulary and should remain
the only component allowed to parse dates, `Decimal` amounts, currencies, installment
fractions, descriptions, or FX details.

Acceptance must be selective. A row is emitted only when all of the following hold:

- the model's calibrated prediction is a unique accepted type;
- the applicable deterministic extractor's hard geometry and syntax contracts pass;
- every emitted value is backed by existing `EvidenceLedger` atom IDs; and
- the row-level prediction of *complete exact extraction* clears a threshold selected
  on a document-disjoint calibration set.

Otherwise the parser abstains. It emits no guessed field, adds an explicit diagnostic,
and lets the existing reconciliation/status logic produce `unreconciled`. A model must
never turn uncertainty into `not_statement`, and it must never force `reconciled`.

## Why this shape fits accepted main

The accepted code already contains most of the safety boundary a learned recognizer
needs:

- `src/ccparser/layout/models.py` makes positioned `Cell`, `Row`, `ColumnSpec`,
  `TableSchema`, and `TableRegion` immutable. Their current `confidence` values describe
  source/layout quality; they are not calibrated probabilities that a semantic label or
  extracted row is correct.
- `src/ccparser/layout/rows.py` clusters positioned words deterministically and records
  reading direction. `src/ccparser/layout/columns.py` infers a closed `ColumnRole`
  vocabulary from headers, profiles, and geometry.
- `src/ccparser/layout/regions.py` recognizes headers, primary transaction shapes, and
  bounded continuation patterns. `src/ccparser/layout/row_tags.py` and
  `src/ccparser/layout/continuations.py` already expose closed structural states and
  exact scanner effects. These are the natural target vocabulary and hard constraints,
  not strings for a model to invent.
- `src/ccparser/normalization_fields.py` requires one proven billed-amount cell, parses
  through deterministic money code, rejects ambiguous rows, and explicitly ignores a
  noncontributing zero row. A learned type must not bypass those rules.
- `src/ccparser/normalization_description.py` removes typed non-description content,
  validates positioned clusters, distinguishes processor references, and merges only
  bounded continuation evidence. A token label may propose atoms to this module, but
  may not directly return description text.
- `src/ccparser/semantic_evidence.py` provides the strongest integration seam. An
  `EvidenceLedger` deterministically converts exact glyph/word/cell evidence into
  addressable atoms and supports explicit ownership claims. Learned field proposals
  should therefore be sets of existing atom IDs, never generated strings.
- `src/ccparser/normalize.py` already represents row outcomes as accept, ignore, or
  reject dispositions. Rejected rows increment `rows_not_emitted`; diagnostics then
  make reconciliation `unreconciled`. This is a ready-made abstention path.
- `src/ccparser/models.py` requires positive charge values, negative credit values,
  paired original amount/currency, exact provenance objects, and finite `Decimal`
  values. The model should not weaken these public invariants.
- `src/ccparser/parser.py::_is_exact_unambiguous` requires exact reconciliation, no
  normalization or reconciliation diagnostics, and no transaction ambiguity before it
  returns `reconciled`. `unsupported` is currently the disposition for ambiguous
  document discovery, while `not_statement` is reserved for positive discovery that the
  input is not a statement. Row-model abstention after statement discovery therefore
  belongs under `unreconciled`.

The main semantic warning is that current `confidence` fields are averages of OCR,
cell, row, or region quality. Reusing them as calibrated probabilities would silently
change their contract. Any learned probability should initially live in a new internal,
versioned prediction object, with the model artifact hash, calibration artifact hash,
label vocabulary version, score, and diagnostic reason.

## What should be learned, and what should remain deterministic

### A hierarchical row vocabulary

A small private corpus is unlikely to support all eight `ContinuationKind` values as
balanced model classes. Use a low-cardinality first-stage vocabulary:

| Learned type | Meaning | Deterministic next step |
|---|---|---|
| `primary_transaction` | A row that may begin exactly one transaction | Run the existing billed/date/description/original/FX/installment extractors; reject if any required contract fails |
| `continuation` | A row that cannot create a transaction by itself | Run the existing bounded continuation scanner to choose a `ContinuationKind`; reject if no unique kind passes |
| `header_or_total` | Structural header, repeated header, or printed total | Existing header/total logic must independently prove it; never normalize as a transaction |
| `nontransaction_table_row` | Zero row, points/rate ledger row, summary, or other in-table nontransaction | Existing deterministic rule decides ignore versus reject |
| `other` | Outside the supported transaction grammar | Abstain |

Do not learn `charge` versus `credit`: accepted main derives it exactly from the signed
`Decimal`. Do not learn installment numbers, currencies, dates, or amounts: use their
current parsers. Do not learn `reconciled`: reconciliation is an end-to-end audit, not a
row label.

The classifier may use only general, document-independent signals already available at
runtime: normalized token/character n-grams; character-class shapes; token count;
digit/letter/currency/date/money/installment indicators; source confidence; normalized
`x`/`y` bands; row height/gaps; inferred column-role occupancy; header distance; and
neighboring row shapes. It must not use a source filename, path, hash, merchant, exact
amount, total, statement date, document ordinal, or memorized document/template ID as a
feature.

### Token labels are proposals, not values

If row classification alone is insufficient, label the OCR tokens/evidence atoms with a
small BIO-style vocabulary:

`DATE`, `DESCRIPTION`, `BILLED_AMOUNT`, `ORIGINAL_AMOUNT`, `CURRENCY`, `INSTALLMENT`,
`FX_RATE`, `ANCILLARY`, and `O`.

The decoder must then enforce type-specific rules:

- `primary_transaction` requires exactly one billed amount in the deterministically
  proven billed band and a nonzero parsed `Decimal`.
- A date proposal must still pass the existing isolated/fragmented date grammar and
  year-context resolution.
- Description atoms must pass the current typed-nondescription, processor-reference,
  and competing-cluster checks.
- Original amount and original currency are emitted only as a complete, compatible
  pair from source evidence.
- Installment fields require one valid `current/total` value with
  `1 <= current <= total`.
- FX values remain optional and must pass current ownership, currency, rate, percentage,
  and fee checks.
- A continuation may add permitted evidence to a preceding accepted transaction but
  can never create a transaction or billed amount.
- Any overlapping ownership, multiple candidate for a singleton field, illegal BIO
  transition, non-renderable atom subset, or failed semantic validator causes that field
  to be absent or the row to be rejected. It never triggers best-effort text synthesis.

This follows the traditional conditional-random-field formulation of discriminative
sequence labeling, where arbitrary input features and label-transition structure are
modeled without generating the observation text ([Lafferty, McCallum, and Pereira,
2001](https://repository.upenn.edu/handle/20.500.14332/6188)).
The maintained `python-crfsuite` binding accepts per-token feature dictionaries and
exposes token-label marginals; version 0.9.12 declares Python 3.13 support
([PyPI](https://pypi.org/project/python-crfsuite/),
[API](https://python-crfsuite.readthedocs.io/en/latest/pycrfsuite.html)).

## Concrete local model candidates

Sizes below distinguish trainable parameter payload from package/dependency size. Raw
payload estimates use four bytes per fp32 parameter, two per fp16 parameter, and one per
int8 parameter; an actual artifact also includes a classification head, tokenizer,
scales, and metadata. Every candidate artifact must be measured and hashed after
training/quantization rather than accepted from an estimate.

| Candidate | Approximate model payload | Runtime/training dependencies | Fit for this parser |
|---|---:|---|---|
| Hashed char/token-shape multinomial linear classifier, `2**16` features, five labels | 327,680 coefficients: 2.50 MiB at float64 or 1.25 MiB at float32, plus intercept/metadata | `scikit-learn`, NumPy, SciPy, joblib; no neural runtime | **First row-type baseline.** Fast CPU inference, auditable feature weights, fixed memory, no vocabulary containing private strings. Calibrate out-of-fold scores. |
| Linear-chain CRF over OCR tokens or over the sequence of rows | Data-dependent sparse artifact; record `Tagger.info()` statistics and exact file bytes. `python-crfsuite` 0.9.12's manylinux wheel is about 1.2 MiB | `python-crfsuite>=0.9.12`; optional scikit-learn only for external evaluation/calibration | **First sequence-labeling baseline.** Uses neighbor/transition structure and arbitrary general features; supports marginals. The model file can contain lexical features, so keep it local and scan it for private strings before any distribution. |
| `dicta-il/dictabert-tiny` Hebrew encoder with token head | 44.9M parameters; about 171 MiB fp32, 86 MiB fp16, or 43 MiB int8 | PyTorch, Transformers, tokenizer; optional ONNX Runtime | Hebrew neural challenger. Its official model card reports 44.9M parameters and Hebrew pretraining ([model card](https://huggingface.co/dicta-il/dictabert-tiny)); it has no document-layout pretraining, so normalized geometry must enter through an added feature/head path or remain in deterministic postvalidation. |
| MobileBERT English encoder with token head | 25.3M parameters; about 97 MiB fp32, 48 MiB fp16, or 24 MiB int8 | PyTorch + Transformers, or exported ONNX Runtime | English neural challenger only. The model is explicitly English/uncased, and Transformers provides a token-classification head ([paper](https://arxiv.org/abs/2004.02984), [official checkpoint](https://huggingface.co/google/mobilebert-uncased), [token-classification API](https://huggingface.co/docs/transformers/model_doc/mobilebert)). |
| Multilingual DistilBERT with token head | 134M parameters; about 511 MiB fp32, 256 MiB fp16, or 128 MiB int8 | PyTorch + Transformers, or ONNX Runtime | Single-checkpoint multilingual challenger. The card reports six layers, 134M parameters, 104-language Wikipedia pretraining, and roughly twice mBERT's speed ([model card](https://huggingface.co/distilbert/distilbert-base-multilingual-cased)). It is substantially larger than its six-layer depth suggests because of its multilingual vocabulary. |
| LayoutLM Base | 113M parameters; about 431 MiB fp32 before head | PyTorch + Transformers; OCR words and normalized bounding boxes | Layout-aware ceiling, not the first integration. Microsoft reports 113M parameters and English document pretraining ([model card](https://huggingface.co/microsoft/layoutlm-base-uncased)). It matches positioned tokens, but not Hebrew pretraining and not this statement grammar. |

The two language-specific neural experts total about 70.2M parameters (about 268 MiB
fp32 or 67 MiB int8) before heads and tokenizers. That can be smaller than one
multilingual checkpoint but requires a deterministic language router and tests for
mixed Hebrew/English rows. The CRF/linear alternatives avoid that routing problem
because Unicode character classes, shape features, geometry, and issuer-neutral syntax
can be shared.

Useful but lower-priority research references are:

- LayoutLMv3 jointly masks text and image content and supports token classification,
  demonstrating that OCR text, boxes, and page appearance can improve document
  information extraction ([paper](https://arxiv.org/abs/2204.08387),
  [Transformers implementation](https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/layoutlmv3.md)).
  It is a much larger dependency and inference change than this experiment needs.
- LiLT decouples layout from the language encoder and reports cross-lingual structured
  document transfer ([ACL paper](https://aclanthology.org/2022.acl-long.534/),
  [official code](https://github.com/jpWang/LiLT)). This is conceptually attractive for
  Hebrew/English layouts, but the official environment pins old PyTorch/Detectron2-era
  dependencies and still needs a suitable text encoder. It is a research ceiling, not a
  Python 3.13 deployment candidate without substantial revalidation.
- Microsoft Table Transformer demonstrates a separate visual table-structure path and
  publishes 110 MB weights, but its official inference still needs separately extracted
  text for textual output ([official project](https://github.com/microsoft/table-transformer)).
  Accepted main already has a deep issuer-neutral geometry pipeline; use Table
  Transformer only if evaluation isolates table-boundary/row-geometry failure as the
  remaining error, not for semantic transaction typing.

End-to-end generators should not be in the initial comparison. Donut, for example,
trains document tasks as autoregressive JSON prediction
([paper](https://arxiv.org/abs/2111.15664),
[official implementation](https://github.com/clovaai/donut)). That is valuable research,
but an autoregressive decoder does not, by construction, guarantee that every output
substring is a lossless rendering of accepted main's evidence atoms. A discriminative
labeler plus deterministic renderer can provide that guarantee.

## Reproducible evaluation protocol

### 1. Freeze annotation semantics before fitting

Create a private, versioned annotation handbook with:

- the five row types above;
- deterministic continuation subtypes mapped to current `ContinuationKind` values;
- token/evidence BIO labels if token classification is evaluated;
- an explicit `ambiguous` annotation option that is not coerced into a model class;
- exact field values and exact supporting evidence atom IDs;
- exact reasons for rows that should be ignored versus rows that require abstention;
  and
- a statement-level list of expected parser status and exact reconciliation outcome.

Double-annotate a document-disjoint sample, adjudicate disagreements without looking at
model predictions, and report agreement per row type and per field. Annotation
ambiguity is a lower bound on learnable performance and must not be hidden inside
`other`.

### 2. Split by document, never by row or page

All pages, regions, rows, continuation rows, and token atoms from one source document
must remain in one partition. `GroupKFold` guarantees nonoverlapping groups, while
`StratifiedGroupKFold` attempts to preserve class balance under that constraint
([scikit-learn group cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)).

Use three immutable roles:

- **development/train:** model fitting and feature decisions;
- **calibration:** temperature/sigmoid/isotonic fitting, conformal scores, and all
  abstention thresholds; and
- **locked test:** one final report only.

If the corpus is too small for one stable three-way split, use nested grouped
cross-validation for development estimates but still reserve a final document-exclusive
test set. Inside an outer training fold, produce out-of-fold predictions with inner
document groups; fit calibration only to those predictions. The ordinary default CV in
`CalibratedClassifierCV` is stratified by row label, not by document, so pass explicit
group-derived split indices. Scikit-learn also warns that a calibrator must be fitted on
data independent of classifier fitting ([calibration guide](https://scikit-learn.org/stable/modules/calibration.html)).

Near-duplicate revisions or repeated exports of one statement must be clustered and
kept in one partition. For a harder transfer report, add a separate leave-one-template-
family or leave-one-issuer-family-out evaluation, but do not substitute it for the
ordinary document-disjoint test. Any family label or similarity index remains private
evaluation metadata and is never a production feature.

Persist privately:

- an immutable split manifest of opaque document IDs;
- its SHA-256;
- label-vocabulary and feature-schema versions;
- model, tokenizer, quantizer, and calibrator versions/hashes;
- Python/platform/dependency lock;
- random seeds and deterministic backend settings; and
- the exact command and configuration that generated each artifact.

### 3. Evaluate separable layers and the whole parser

**Row-type recognition**

- per-class precision, recall, and F1;
- macro F1 and a full confusion matrix;
- primary-transaction false-positive rate;
- continuation-to-primary and primary-to-continuation error rates;
- sequence-legality rate; and
- both row-micro and document-macro aggregates.

**Token/field recognition**

- token macro F1 as a diagnostic;
- exact evidence-span/entity F1 as the main labeling metric;
- exact normalized field accuracy for dates, `Decimal` amounts, currencies,
  descriptions, installment pairs, and FX fields;
- evidence precision/recall over atom IDs;
- ownership collision and unclaimed-evidence rates; and
- the rate at which the learned proposal is correctly rejected by deterministic rules.

**Row extraction**

- exact match of the complete transaction tuple;
- transaction precision, recall, and F1;
- wrong billed-amount rate, wrong sign/kind rate, and fabricated-field rate;
- optional-field precision and recall, always reporting absent-vs-wrong separately;
- row abstention coverage and selective risk; and
- the number of accepted rows containing any ambiguity diagnostic, which should be zero
  for the strict operating point.

**End to end**

- exact transaction-set match per document;
- printed-total and group association correctness;
- exact reconciliation rate and status confusion matrix;
- `reconciled` false-positive count (a critical zero-tolerance outcome);
- JSON/CSV byte determinism; and
- cold/warm CPU latency, peak RSS, artifact bytes, and dependency footprint.

Resample documents, not rows, for confidence intervals. Report metrics by source mode
(digital text versus OCR), language/script, page count, row length, OCR-confidence band,
and supported structural type, but define the slices before opening locked-test results.
Do not report a slice so small that it leaks private corpus composition.

### 4. Baselines and ablations

Every candidate should run on exactly the same document folds:

1. accepted deterministic main at the reviewed SHA;
2. deterministic main plus a purely rule-derived row type (no learned component);
3. text/shape-only linear model;
4. text/shape + geometry/column-role linear model;
5. CRF without lexical n-grams;
6. full CRF;
7. optional neural text-only token classifier; and
8. optional neural text + normalized layout features.

This isolates whether gains come from text, sequence transitions, or geometry. A model
does not pass because its token F1 is higher; it passes only if end-to-end exact-row
precision, risk at the chosen coverage, statuses, reconciliation safety, determinism,
and resource bounds improve without a protected-regression failure.

### 5. Do not tune through reconciliation

Exact reconciliation is a valuable terminal validator, but using the printed total to
search among alternative learned parses can select a numerically matching wrong subset.
Do not choose features, checkpoints, labels, calibration methods, or row candidates by
their locked-test reconciliation. At runtime, preserve accepted main's use of
reconciliation as an audit: it may reject or downgrade a parse, never manufacture or
choose unsupported evidence to make the numbers add up.

## Calibration and selective prediction

### Calibrate the event that matters

Token softmax, CRF marginals, OCR confidence, and row geometry confidence answer
different questions. The production gate needs:

> `P(the entire emitted row is exactly correct | model scores and deterministic checks)`

Construct that as a binary meta-outcome on document-disjoint, out-of-fold predictions:
one only when the row type, required fields, every emitted optional field, evidence atom
ownership, and transaction tuple all exactly match; zero otherwise. Inputs to the
calibrator can include the top row-type logit/margin, minimum required-field score,
model entropy, OCR/geometry quality, deterministic diagnostic indicators, and the count
of competing candidates. Do not multiply field probabilities and call the result a row
probability; their errors are dependent.

For neural multiclass logits, temperature scaling is a strong low-variance baseline.
Guo et al. found a single learned temperature effective across their studied modern
networks ([ICML paper](https://proceedings.mlr.press/v70/guo17a.html)). For sparse linear
or CRF scores, compare sigmoid calibration with temperature scaling. Use isotonic only
when the independent calibration sample is large enough; scikit-learn explicitly warns
that isotonic tends to overfit far below 1,000 calibration samples and documents
sigmoid, isotonic, and temperature options
([`CalibratedClassifierCV`](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV.html)).

On calibration and locked test, report:

- multiclass and exact-row negative log loss;
- Brier score;
- reliability diagrams and expected calibration error with fixed, predeclared bins;
- maximum and classwise calibration error as diagnostics;
- calibration slope/intercept for exact-row correctness; and
- the same measures per predeclared language/source slice where sample size permits.

Brier/log loss mix calibration and discrimination, so neither alone proves reliability;
scikit-learn makes the same distinction in its calibration guide. Thresholds must be
chosen on calibration data after the calibrator is frozen. Any model, OCR, feature,
label, or deterministic-rule change invalidates that calibration.

### Risk-coverage is the acceptance metric

For a threshold `t`, define:

- `coverage(t) = accepted annotated rows / eligible annotated rows`; and
- `selective risk(t) = wrong accepted rows / accepted rows`.

Plot the full risk-coverage curve, report area under the risk-coverage curve, and report
coverage at several predeclared maximum-risk targets. The selective-classification
literature explicitly treats abstention as a risk/coverage tradeoff and gives finite-
sample threshold-selection methods ([Geifman and El-Yaniv,
NeurIPS 2017](https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html)).
For each candidate threshold, report a one-sided exact binomial upper bound on accepted
row error, with documents as the bootstrap/reporting cluster. Do not describe an
empirical zero-error calibration sample as zero future risk.

Use a strict acceptance conjunction rather than score alone:

```text
accept row
  iff calibrated_exact_row_probability >= threshold
  and row type is a unique supported label
  and deterministic type-specific extractor succeeds
  and required evidence ownership is complete and nonoverlapping
  and no ambiguity or model-abstention diagnostic exists
else abstain
```

An ignored row is not an abstention. `IGNORE_ROW` remains appropriate only when a
deterministic rule positively proves a supported noncontributing row. Model uncertainty,
multiple plausible types, or missing required evidence maps to `REJECT_ROW` and an
explicit diagnostic.

### Where conformal methods help—and where they do not

Split conformal classification can wrap any frozen classifier. A simple label set is
formed from held-out true-label nonconformity scores; adaptive prediction sets improve
set efficiency while retaining marginal coverage
([Romano, Sesia, and Candès, NeurIPS
2020](https://proceedings.neurips.cc/paper/2020/hash/244edd7e85dc81602b7615cd705545f5-Abstract.html)).
For this parser, the safe decision rule is: proceed only when the conformal row-type set
is a singleton *and* all deterministic gates pass; an empty or multi-label set means
abstain.

Conformal risk control generalizes this idea to monotone losses and can bound expected
risk for a nested family of prediction rules ([Angelopoulos et al., ICLR
2024](https://research.google/pubs/conformal-risk-control/),
[official code](https://github.com/aangelopoulos/conformal-risk)). A later experiment
could calibrate one global acceptance threshold against document-level loss such as
`any wrong emitted required field`. Risk-controlling prediction sets similarly use a
holdout set to control expected loss from a black-box predictor
([Bates et al.](https://www.gsb.stanford.edu/faculty-research/publications/distribution-free-risk-controlling-prediction-sets)).

Important limits apply:

- Standard guarantees require exchangeability between calibration and future examples.
  Rows within a statement are dependent, so treating every row as an independent
  calibration point overstates the sample size. Use the document as the independent
  unit. If simultaneous within-document coverage is required, calibrate a per-document
  maximum nonconformity score; expect conservative sets.
- Coverage is marginal, not a guarantee for every row type, issuer/template, language,
  OCR mode, or optional field. Rare continuation types can be badly covered while the
  aggregate target holds.
- A conformal row-type set does not guarantee exact extracted amounts/descriptions.
  Deterministic field validation and the exact-row selective gate remain necessary.
- Under covariate shift, ordinary conformal coverage can fail. Weighted conformal
  methods require the train/test likelihood ratio to be known or accurately estimated
  ([Tibshirani et al., NeurIPS
  2019](https://papers.neurips.cc/paper_files/paper/2019/hash/8fb21ee7a2207526da55a679f0332de2-Abstract.html));
  that is a strong requirement for an unseen issuer or layout.
- Small document-level calibration sets yield coarse quantiles and low coverage at
  stringent risk. Cross-validation variants can use data more efficiently, but add
  complexity and do not remove transfer assumptions. Do not add conformal machinery
  unless its held-out risk-coverage curve beats the simpler calibrated threshold.

## Parser status and failure semantics

The model should preserve these observable meanings:

| Situation | Status/result behavior |
|---|---|
| Positive evidence says the document is not a statement | `not_statement`; row model should not run or alter this decision |
| Statement discovery itself is ambiguous/unsupported | `unsupported`; no transactions |
| Statement discovered, but any candidate transaction row has an ambiguous/multi-label/low-confidence model result or a failed deterministic extraction | row `REJECT_ROW` + diagnostic; statement `unreconciled` |
| A deterministic rule proves an allowed noncontributing structural row | `IGNORE_ROW`; not counted as model abstention |
| All rows are exact, unambiguous, evidence-complete, and every group reconciles exactly | existing code may return `reconciled`; the model cannot override the gate |
| Model artifact missing, hash mismatch, vocabulary mismatch, calibrator mismatch, or unsupported runtime | fail closed before learned predictions are used; do not silently substitute uncalibrated scores |

Recommended diagnostics are stable reason codes, not raw text or values:
`row_model_abstained`, `row_model_multiple_types`, `row_model_unsupported_type`,
`row_model_calibration_mismatch`, `row_model_evidence_contract_failed`, and
`row_model_artifact_mismatch`. Keep probabilities and artifact metadata out of public
financial output unless a versioned public contract is deliberately designed.

## Public-data transfer limits

Public benchmarks can test tooling but cannot establish statement-corpus acceptance:

- CORD publishes 1,000 Indonesian receipts with OCR boxes/text and hierarchical semantic
  labels ([official project](https://github.com/clovaai/cord)). It is useful for checking
  token-label code, but receipt item lines and language do not represent bilingual
  credit-card statement continuation/FX semantics.
- SROIE contains roughly 1,000 whole receipt images and tasks for localization, OCR, and
  four-field key extraction ([competition paper](https://arxiv.org/abs/2103.10213)). It
  does not label transaction rows or statement reconciliation groups.
- PubTables-1M provides almost one million annotated scientific-document tables with
  rows, columns, cells, words, and functional headers
  ([paper](https://openaccess.thecvf.com/content/CVPR2022/html/Smock_PubTables-1M_Towards_Comprehensive_Table_Extraction_From_Unstructured_Documents_CVPR_2022_paper.html),
  [official project](https://github.com/microsoft/table-transformer)). It can exercise
  table geometry, but scientific table rows are not financial transaction roles.
- LayoutLM/LayoutLMv3 results on form, receipt, and document benchmarks demonstrate
  representation capacity, not calibration or exactness on this parser's OCR provider,
  Hebrew/English mix, field grammar, evidence accounting, or statuses.

Other non-transferable factors include OCR engine/version, digital-versus-raster source,
tokenization, reading direction, page scale, statement template, class prevalence,
annotation policy, and changes to deterministic normalization. A probability calibrator
is tied to the complete pipeline that produced its inputs. Quantization, model
fine-tuning, label changes, feature changes, OCR repair, and threshold changes all
require fresh document-disjoint calibration and evaluation.

No public benchmark or tracked unit test can attest private-corpus behavior. A future
production change affecting these paths would still need the repository's clean,
committed, independently pinned private verification gate after tracked tests; this
research note records no corpus result or acceptance claim.

## A minimal go/no-go experiment

1. Privately label a document-disjoint development sample with the five row types and
   exact evidence-backed row outcomes.
2. Implement no production integration. In an isolated evaluation harness, derive only
   general features from the existing `Row`, `ColumnSpec`, and `EvidenceLedger` objects.
3. Train the deterministic-rule baseline, hashed linear model, and CRF on identical
   grouped folds.
4. Generate out-of-fold exact-row outcomes, fit sigmoid/temperature calibration, and
   select several acceptance thresholds without test access.
5. Freeze/hashes all artifacts; evaluate once on the locked document test set.
6. Compare exact-row precision, primary false positives, risk-coverage, end-to-end
   reconciliation/status errors, byte determinism, latency, RSS, and artifact size.
7. Continue to neural challengers only if the CRF/linear models cannot meet a
   predeclared coverage target at the required upper risk bound and the residual errors
   are demonstrably semantic rather than deterministic geometry/OCR failures.
8. Reject the learned approach if it merely shifts errors, needs document-specific
   features, emits any unsupported string/value, weakens status semantics, or cannot
   reproduce identical outputs from pinned artifacts.

This experiment answers the real design question with minimal transfer risk: whether a
small local discriminative model can recognize enough ambiguous row structure to
increase conservative coverage while accepted main remains the sole authority for
financial values, evidence, reconciliation, and abstention.
