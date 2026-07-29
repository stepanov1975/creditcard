# State of the art for fixed transaction-row recognition and field extraction

**Assessment date:** 2026-07-29

**Comparison anchor:** `dee4b071ad65231da13825f2f7c74a488ca96c7c`

**Scope:** recognition and evidence-grounded field extraction after transaction row
identities and bounding boxes have been frozen. No private documents, labels, crops,
predictions, or financial values were inspected.

## Bottom line

The strongest evidence does **not** identify one universal end-to-end document model for
this problem. It supports a compact, staged comparison in which recognition, row semantics,
field-span selection, deterministic value parsing, and selective acceptance remain separate.
That is exactly the four-arm design in the approved
[experiment charter](../superpowers/specs/2026-07-28-row-extraction-experiment-charter-design.md):

1. tune Tesseract on each already-detected row;
2. test a closed deterministic row-type classifier with type-specific, evidence-backed
   extraction;
3. train a hashed linear row classifier and linear-chain tagger over the existing positioned
   evidence atoms; and
4. test whether a MobileNetV3-Small-class pixel encoder adds information over a matched
   pixels-off control.

The recommendation is therefore to execute those four experiments unchanged and rank them
by complete-row exactness and selective risk, not by OCR similarity or token F1 alone. Build
the cascade only from frozen validation-eligible outputs. No learned component should emit an
authoritative merchant string or financial value: it should select exact evidence spans, and
the existing deterministic renderers and parsers should either validate them or abstain.

This is a recommendation about experiment order, not a measured winner. The accepted parser,
conditional page OCR, and forced page OCR remain controls rather than extra experiments.

## Repository fit

The current pipeline makes the row-crop experiment unusually low-risk and informative:

- [`evidence/ocr.py`](../../src/ccparser/evidence/ocr.py) already renders an arbitrary PDF
  `clip` with PyMuPDF, runs pinned local Tesseract passes, returns positioned TSV words in PDF
  coordinates, and content-addresses results. It currently uses `heb+eng`, 300 DPI, and PSM 6.
- [`evidence/pdf.py`](../../src/ccparser/evidence/pdf.py) invokes ordinary OCR conditionally on
  the whole page; its separate currency repair is the only targeted crop path.
- [`layout/rows.py`](../../src/ccparser/layout/rows.py) turns positioned words into physical
  rows and cells. Re-running it without constraints would change the experimental input, so
  every arm must assign evidence to the frozen rows instead.
- [`normalization_description.py`](../../src/ccparser/normalization_description.py) already
  distinguishes description evidence from typed non-description evidence, competing
  clusters, processor references, and continuations. A learned span is best used as a proposal
  to this deterministic boundary, not as a replacement text generator.
- The common experiment contract records exact atom or image-region support, decisions,
  reasons, and exact-row confidence. That is the right seam for all four arms and for an
  abstention-first cascade.

## Assessment by experiment arm

| Arm | Primary-source evidence | Direct implication here | Transfer limit / stop rule |
|---|---|---|---|
| 1. Per-row OCR | Tesseract's official guide recommends at least 300 DPI, a reasonable small border for tight crops, and a page-segmentation mode appropriate to a small region; PSM 7 is a single line and PSM 13 a raw line. Tesseract 5 also exposes Adaptive Otsu and Sauvola thresholding ([Tesseract quality guide](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)). PyMuPDF natively supports `dpi`, `clip`, and `alpha=False` in `Page.get_pixmap` ([PyMuPDF API](https://pymupdf.readthedocs.io/en/latest/page.html#pymupdf.Page.get_pixmap)). | Run the predeclared sequential sweep over padding, PSM 6/7/13, scale, language order, preprocessing, traineddata, and whole-row versus fixed-field crops. Preserve fixed row boxes and initially preserve column bands. Measure OCR CER/WER **and** structured-field outcomes because better text can still create wrong ownership. | A crop cannot recover a row the accepted detector missed. Stop before neural OCR or row redetection. The current official PP-OCRv5 language table does not list Hebrew ([official model list](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md)), so its small-model results do not establish a drop-in Hebrew recognizer. |
| 2. Deterministic row types | Bank-statement-specific TabSniper explicitly categorizes tables before structure recognition and reports that dense, long, multi-line transaction tables differ from public table corpora ([TabSniper](https://arxiv.org/abs/2412.12827)). Receipt and form systems such as BROS likewise separate OCR tokens/boxes from entity and ordered-item extraction ([official BROS repository](https://github.com/clovaai/bros)). | The closed vocabulary—primary transaction, continuation, structural, ambiguous—provides a cheap, deterministic routing test. Type-specific extractors may use only general shape, script, geometry, column occupancy, syntax, confidence, and neighbor structure; they must return exact atom-backed spans and preserve ambiguity. | The literature does not prove that hand-built row typing will beat learning on this corpus. TabSniper's main gain is table detection/structure recognition, which is frozen here. Stop on any issuer, template, merchant, filename, date, amount, total, or corpus-specific branch. |
| 3. Lightweight text model | Linear-chain CRFs were designed for discriminative sequence labeling with observation features and label-transition structure ([Lafferty, McCallum, Pereira](https://repository.upenn.edu/handle/20.500.14332/6188)); the maintained binding accepts per-token feature mappings and exposes marginals ([python-crfsuite API](https://python-crfsuite.readthedocs.io/en/latest/pycrfsuite.html)). Larger layout-aware models confirm that text plus boxes is useful: BROS consumes OCR text/bounding boxes and extracts ordered receipt items, while LiLT couples a transferable layout branch to a textual encoder and publishes 293 MB English and 846 MB multilingual checkpoints ([LiLT repository](https://github.com/jpWang/LiLT)). | Start with the chartered hashed text/shape row classifier and CRF BIO tagger, comparing text/shape against text/shape-plus-geometry on identical atoms. Decode only legal, contiguous, uniquely owned spans. This tests the useful document-model hypothesis without importing a transformer, tokenizer alignment risk, or generative output. | CRF marginals are not complete-row correctness probabilities. LiLT/BROS/LayoutLM-style benchmark gains do not establish Hebrew credit-card transfer, and their footprint is far beyond the initial lane. Stop before transformers or generated field values unless compact residual errors justify a user-approved amendment. |
| 4. Lightweight image or image-plus-text | Torchvision's MobileNetV3-Small implementation is a 2.54M-parameter, CPU-oriented backbone ([Torchvision report](https://pytorch.org/blog/torchvision-mobilenet-v3-implementation/)). Multimodal document encoders show that pixels can help receipt/form token labeling: LayoutLMv3 jointly pretrains text and image representations and reports a 133M-parameter base model across FUNSD, CORD, DocVQA, RVL-CDIP, and PubLayNet ([Microsoft research summary](https://www.microsoft.com/en-us/research/articles/layoutlmv3), [paper](https://arxiv.org/abs/2204.08387)). | Use the same nonvisual tensors, head, labels, splits, and calibration for pixels-on and pixels-zeroed models. Predict row types and atom/span roles, not JSON or strings. Retain the arm only if pixels improve document-held-out selective risk over both matched controls at acceptable latency, memory, artifact size, and repeatability. | ImageNet efficiency does not imply document-field accuracy, and LayoutLMv3's much larger benchmark result is only a ceiling. Stop with `STOP_NO_PIXEL_GAIN` if pixels do not add held-out value; do not escalate automatically to a pretrained document transformer or VLM. |

## What recent document models change—and what they do not

Recent work strengthens the case for keeping a heavyweight ceiling visible, but does not
change the approved initial experiments:

- The 2026 PP-OCRv5 paper reports that a specialized roughly 5M-parameter recognizer can rival
  much larger VLMs on its OCR benchmarks ([CVPR 2026 paper](https://arxiv.org/abs/2603.24373)).
  This supports trying specialized recognition before a general VLM. Its official multilingual
  checkpoints still do not establish Hebrew support.
- Surya 2 is a credible later Hebrew-capable OCR ceiling: its official project reports a 650M
  parameter VLM, full-page and block OCR, and 90.9% on its internal Hebrew slice
  ([repository](https://github.com/datalab-to/surya), [91-language table](https://github.com/datalab-to/surya/blob/master/static/docs/multilingual.md)). But it emits block HTML/JSON through a `vllm` or `llama.cpp` server, uses model weights under a modified license, and its published result is not transaction-field exactness or this corpus. It therefore requires a charter amendment and cannot displace arm 1.
- The 2026 ReceiptBench paper decomposes real-world receipt understanding into perception,
  normalization, semantic reasoning, and structure parsing ([paper](https://arxiv.org/abs/2605.22413)). That decomposition supports this program's separate recognition, proposal,
  validation, and cascade layers. Its MLLM training and receipt tasks do not establish exact,
  grounded Hebrew credit-card extraction.
- Table Transformer requires OCR or PDF text as a separate input to produce text-bearing
  output, and its released models predict table structure rather than transcriptions
  ([official repository](https://github.com/microsoft/table-transformer)). TabSniper likewise
  concentrates on table detection, row/column structure, and cell formation. These are relevant
  only to a future row-detection study, not this fixed-row comparison.

Accordingly, none of these systems creates a fifth experiment. They are transfer evidence or
possible later ceilings after the four-arm result, not implicit follow-ups.

## Calibration, abstention, and the cascade

The acceptance confidence must estimate the event that the **entire emitted transaction row is
exactly correct**. OCR confidence, a row-type posterior, token marginals, or a minimum field
score does not estimate that event by itself.

Use document-disjoint out-of-fold predictions to fit a low-variance calibrator on complete-row
correctness. Temperature scaling is a strong neural-logit baseline
([Guo et al.](https://proceedings.mlr.press/v70/guo17a.html)); sigmoid calibration is the
natural small-data comparator for sparse linear/CRF score vectors. Select thresholds only on
the validation partition, and report risk versus coverage plus fixed operating points. The
selective-classification literature defines precisely this reject/error tradeoff and provides
finite-sample threshold-selection procedures
([Geifman and El-Yaniv](https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html)).

Conformal risk control can control the expectation of a predeclared monotone loss for a frozen
predictor ([ICLR 2024 paper](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html), [official code](https://github.com/aangelopoulos/conformal-risk)). It is not a shortcut here: rows inside one statement are dependent, a small document-level calibration set produces coarse thresholds, and ordinary guarantees rely on exchangeability. Use the document as the independent calibration/reporting unit. Add conformal machinery only if it improves held-out risk/coverage over the simpler frozen threshold; do not add it because the method has a formal guarantee under different assumptions.

The cascade should therefore accept only when all of the following are true:

1. a frozen lane proposes one supported row type and uniquely supported, nonoverlapping spans;
2. deterministic syntax, geometry, ownership, Unicode, date, currency, `Decimal`, sign, and
   installment validators pass;
3. separately calibrated complete-row confidence clears its frozen threshold; and
4. terminal reconciliation does not reject the candidate.

Any disagreement, ambiguous support, failed validator, low confidence, or unsupported row
must abstain. Reconciliation may reject; it may not choose or repair a proposal.

## Required measurements and decision rule

The charter's common measurements match the research evidence and should not be diluted.
The primary ranking is:

1. complete transaction-row exact match;
2. merchant exact and predeclared normalized match;
3. exact typed fields, omissions, hallucinations, unsupported ownership, and false accepts;
4. selective risk/coverage at predeclared operating points, with calibration diagnostics;
5. paired document-level effect sizes and uncertainty; and
6. latency, throughput, peak RSS, artifact/dependency/cache bytes, and byte-identical repeats.

CER/WER and span F1 are diagnostic. They cannot promote an arm that regresses complete-row
exactness, amount/date/currency correctness, ownership, or accepted-row risk. Report all
results by row type and the frozen error taxonomy. Model/configuration selection uses
development and validation only; the locked test is opened once after every lane disposition,
calibrator, threshold, and cascade rule is frozen.

## Explicit transfer limits

1. **Conditional problem:** fixed rows cannot recover a missing transaction or wrong row box.
   The result estimates extraction quality conditional on the accepted detector.
2. **Survivorship bias:** rows materialized from accepted evidence may underrepresent the
   hardest OCR failures. Do not call row-level gains end-to-end recall gains.
3. **Domain mismatch:** PubTables-1M, FinTabNet, FUNSD, CORD, SROIE, XFUND, and receipt
   benchmarks differ from Hebrew/mixed-script credit-card rows, field ontology, and exactness
   requirements.
4. **Language mismatch:** multilingual coverage or tokenizer support is not demonstrated
   Hebrew transaction accuracy. Mixed Hebrew, Latin, digits, punctuation, and currency must
   be measured locally in logical Unicode order; Unicode defines bidirectional text as logical
   storage plus presentation reordering ([Unicode Bidirectional Algorithm](https://www.unicode.org/reports/tr9/)).
5. **Metric mismatch:** OCR similarity, table-structure scores, entity F1, or generated-JSON
   validity do not imply exact merchant text or exact `Decimal` fields.
6. **Grounding mismatch:** generative OCR/document models can return text without a unique
   mapping to existing evidence atoms. Unsupported output must never become authoritative.
7. **Calibration shift:** a calibrated score becomes stale when OCR, labels, features, model,
   deterministic rules, or document distribution changes. Refit and re-evaluate on
   document-disjoint data.
8. **Repeatability:** PyTorch does not guarantee identical results across releases, platforms,
   or CPU/GPU backends even with identical seeds
   ([official reproducibility note](https://docs.pytorch.org/docs/stable/notes/randomness.html)).
   The acceptance criterion is empirical byte-identical output on the pinned runtime.

## Authoritative recommendation

Proceed with the existing four-lane plans without adding a model or changing row detection:

- execute the controlled Tesseract row-crop sweep first;
- implement the deterministic row-type/type-specific arm as the no-learning structural test;
- fit the hashed linear + CRF text arm on exact evidence atoms;
- run the matched MobileNetV3 pixels-on/pixels-off test only after the nonvisual feature
  contract is frozen; and
- compare frozen lane outputs, then fit the abstention-first cascade on validation data.

The likely production shape, if measurements justify any change, is a small evidence-grounded
advisor in front of the existing deterministic validators—not an end-to-end generator. Which
advisor earns that role remains deliberately unresolved until the four arms are measured.

## Prior repository research reviewed

- [Fixed-row OCR and transaction-field extraction](2026-07-28-row-ocr-table-extraction.md)
- [Row-text models, calibration, and conservative abstention](2026-07-28-row-text-models-calibration.md)
- [Lightweight row-vision and multimodal models](2026-07-28-row-vision-multimodal-models.md)
