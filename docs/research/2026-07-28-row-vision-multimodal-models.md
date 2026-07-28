# Lightweight row-vision and multimodal models for transaction-field extraction

**Research date:** 2026-07-28
**Accepted implementation anchor:** `dee4b071ad65231da13825f2f7c74a488ca96c7c`

## Scope and conclusion

This note evaluates local models only for a **fixed transaction-row image boundary** and
the OCR/digital-text evidence already inside that boundary. It does not evaluate page
classification, table detection, row discovery, or cloud APIs. No private documents,
images, annotations, outputs, caches, or financial data were inspected.

The best first vision experiment is a purpose-built, grounded atom/span classifier:

1. keep the accepted parser's `Row.bbox`, cells, words, glyphs, and evidence atoms fixed;
2. encode small image crops with `mobilenet_v3_small`;
3. combine the visual embedding with the atom's normalized geometry, OCR confidence,
   character-shape features, and existing typed candidates; and
4. predict a field role for an existing atom or contiguous atom span.

This is substantially smaller and safer than an end-to-end document model. Torchvision's
official MobileNetV3-small weights have 2,542,856 parameters, a 9.8 MB file, and 0.06
GFLOPS ([model documentation](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.mobilenet_v3_small.html)).
The architecture can always return exact accepted evidence rather than generated text.
Use uninitialized weights or separately clear the terms of a chosen pretrained-weight
artifact: torchvision code is BSD-3-Clause, while its repository warns that individual
pretrained weights can inherit restrictions from their training data
([license](https://github.com/pytorch/vision/blob/main/LICENSE)).

The mandatory control should be even simpler: a linear, CRF, or compact tree model over
the same existing candidates, geometry, and OCR features, without pixels. If that control
matches the visual model, the image branch has not earned its dependency or latency.

For a pretrained layout-aware comparison, LiLT with a multilingual InfoXLM text branch is
the most relevant candidate, subject to a Hebrew tokenization and held-out accuracy audit.
Florence-2-base is worth a zero-shot proposal-only calibration. BROS and TrOCR are useful
English/numeric ablations. Donut, Dessurt, and small general-purpose VLMs should remain
research controls: they are autoregressive, not natively tied to the parser's evidence
atoms, and their relevant pretraining is English-centric or omits Hebrew.

## Fit with the accepted parser

At the accepted SHA, [`layout/models.py`](../../src/ccparser/layout/models.py) represents
a row as immutable positioned cells, and [`layout/rows.py`](../../src/ccparser/layout/rows.py)
constructs rows deterministically from positioned words. The semantic layer builds a
stable `EvidenceLedger` over glyph, word, and cell atoms and preserves their bounding
boxes ([`semantic_evidence.py`](../../src/ccparser/semantic_evidence.py)). Normalization
then parses and validates dates, `Decimal` amounts, currencies, descriptions, and related
claims from those atoms ([`normalize.py`](../../src/ccparser/normalize.py)).

That is already the right safety boundary. A row model should emit only:

- an atom ID or contiguous ordered atom-span ID range;
- a field role such as transaction date, conversion date, merchant/description, billed
  amount, billed currency, original amount, original currency, installment, or FX field;
- a calibrated confidence; and
- the exact model, weights, preprocessing, and feature-schema identifiers.

It should not emit an authoritative string or number. Even when a generative model is
tested, its string is only a proposal: it must map uniquely back to an exact evidence span
before the existing parser is allowed to parse it. No match or multiple matches means
abstention. This prevents an image model from inventing a merchant, digit, sign, decimal
point, date, or currency.

## Candidate comparison

Sizes below describe the cited released artifact or model card, not peak process memory.
Peak RSS and row latency must be measured on the intended CPU and pinned runtime.

| Candidate | Input and grounding | Published/released footprint | License | Local row experiment |
|---|---|---:|---|---|
| Custom MobileNetV3-small atom scorer | Fixed row/atom crops plus exact OCR atoms and geometry; labels atoms/spans | 2.54M parameters, 9.8 MB, 0.06 GFLOPS | Torchvision code BSD-3-Clause; review any selected weights | **First vision experiment.** Small, CPU-oriented, exactly grounded, and trainable on hundreds to low thousands of labeled rows. |
| Compact non-vision classifier | Existing candidate types, text-shape, confidence, column/row geometry | Project-specific; expected far below neural encoders | Project code | **Mandatory control.** Establish whether pixels add signal beyond present evidence. |
| LiLT-RoBERTa / LiLT-InfoXLM | OCR text plus normalized boxes; token classification | Official release archives: 293 MB English, 846 MB multilingual; layout-only module 21 MB; model cards describe roughly 0.1B/0.3B | MIT | Best pretrained layout-aware comparison. Prefer multilingual only after Hebrew audit; footprint is not genuinely tiny. |
| Multilingual MiniLM + new 2-D head | OCR tokens, boxes, and candidate features; token classification | 12 layers, hidden size 384; 21M transformer + 96M embeddings; 471 MB released weights | MIT | Practical custom text/layout baseline. XLM-R vocabulary can encode Hebrew, but the card's 16-language evaluation does not establish Hebrew quality. |
| BROS-base | OCR text plus boxes; token/entity relations | Under 110M parameters; 438 MB FP32 artifact | Apache-2.0 | Good English/numeric layout ablation; uncased English BERT vocabulary makes mixed Hebrew a poor primary path. |
| TrOCR-small-printed | A cropped printed text line image; generated text | 61.4M/62M parameters; 246 MB safetensors | MIT | Targeted OCR rescorer for Latin/numeric lines only. It does not assign field roles or provide evidence grounding. |
| Florence-2-base | Row image; prompted OCR or OCR-with-region output | 0.23B parameters; 463 MB FP16 safetensors | MIT | Promising zero-shot OCR-with-region calibration. Still autoregressive and has no transaction-field ontology or documented Hebrew accuracy. |
| LayoutLMv3-base | Page/row image plus OCR text and boxes; token classification | About 133M parameters; 501 MB safetensors | CC BY-NC-SA 4.0 | Technically strong multimodal benchmark, but non-commercial terms require legal clearance and make it a poor default product dependency. |
| Donut-base | Image only; generated structured text/JSON | 143M parameters; about 809 MB weights | MIT | Research-only generative control. No native link to evidence atoms and no Hebrew pretraining. Fine-tuning is feasible; reproducing pretraining is not. |
| Dessurt | Image plus task string; generated text/JSON | 127M parameters, 1152 x 768 input in the paper | MIT | Architectural control, not first implementation: custom older stack/checkpoints, English-centric pretraining, and autoregressive grounding risk. |
| SmolVLM-256M-Instruct | Image plus prompt; generated response | 256M parameters; 513 MB safetensors; card reports under 1 GB GPU RAM for one-image inference | Apache-2.0 | Low-priority general-VLM negative control. English-only card, aggressive visual-token compression, and no exact grounding. |

### Layout-aware OCR-token encoders

**LiLT.** LiLT separates layout learning from the textual encoder and was explicitly
designed so the layout branch can be combined with monolingual or multilingual language
models. The paper reports cross-language document-understanding experiments
([ACL paper](https://aclanthology.org/2022.acl-long.534/)); the
[official repository](https://github.com/jpWang/LiLT) is MIT-licensed and publishes the
English, multilingual InfoXLM, and layout-only checkpoints. Hugging Face provides current
token-classification integration for both the
[English model](https://huggingface.co/SCUT-DLVCLab/lilt-roberta-en-base) and
[multilingual model](https://huggingface.co/SCUT-DLVCLab/lilt-infoxlm-base). The original
standalone setup pins an old PyTorch/detectron2 stack; the Transformers implementation is
the more plausible experiment path. Before labeling data, test the exact tokenizer on
representative *synthetic or non-private* Hebrew/Latin/numeric strings for fragmentation,
directionality, and lossless offset alignment. Tokenizer coverage alone is not semantic
validation.

**BROS.** BROS consumes OCR text and boxes, learns relative layout, and includes key
information extraction and ordered receipt-item tasks
([paper](https://arxiv.org/abs/2108.04539),
[official Apache-2.0 code](https://github.com/clovaai/bros)). The
[base checkpoint](https://huggingface.co/naver-clova-ocr/bros-base-uncased) uses a
12-layer, 768-hidden, 12-head configuration with a 30,522-token uncased BERT vocabulary
and a 512-token limit; its
[artifact tree](https://huggingface.co/naver-clova-ocr/bros-base-uncased/tree/6b72069fdf31969a1f952f36425bdff0526abb70)
shows the 438 MB FP32 weights. Its direct receipt-item pedigree is attractive, but the
English vocabulary is a decisive limitation for merchant text in Hebrew.

**LayoutLMv3.** LayoutLMv3 jointly masks text and image patches and is available as a
multimodal token classifier ([paper](https://arxiv.org/abs/2204.08387),
[official documentation](https://github.com/microsoft/unilm/blob/master/layoutlmv3/README.md)).
The [base model card](https://huggingface.co/microsoft/layoutlmv3-base) describes the
12-layer, 768-hidden, 224-pixel-image, 512-token model, and its
[501 MB artifact](https://huggingface.co/microsoft/layoutlmv3-base/blob/main/model.safetensors).
The official project and model use CC BY-NC-SA 4.0, so this should not become a production
dependency without an explicit license decision.

**Multilingual MiniLM plus geometry.** Microsoft's
[Multilingual-MiniLM-L12-H384](https://huggingface.co/microsoft/Multilingual-MiniLM-L12-H384)
is not a document model, but its small-width encoder can be combined with learned 2-D box
embeddings and the existing deterministic candidate features. The official
[MiniLM repository](https://github.com/microsoft/unilm/blob/master/minilm/README.md) is
MIT-licensed; the
[artifact tree](https://huggingface.co/microsoft/Multilingual-MiniLM-L12-H384/tree/main)
shows a 471 MB weight file. The large multilingual vocabulary dominates disk size, so
this is computationally narrower rather than a truly small download.

### Image-to-text and general multimodal generators

**Donut.** Donut removes the OCR stage and generates serialized structured output from an
image ([MIT-licensed implementation](https://github.com/clovaai/donut),
[base model](https://huggingface.co/naver-clova-ix/donut-base)). The
[paper](https://arxiv.org/pdf/2111.15664) reports 143M parameters and pretraining on 11M
IIT-CDIP pages plus 2M synthetic documents for 200,000 steps using 64 A100 GPUs. Its
synthetic languages are English, Chinese, Japanese, and Korean, not Hebrew. The released
[artifact tree](https://huggingface.co/naver-clova-ix/donut-base/tree/2e6cedf3ccdc848355cf109e41c8193250593527)
is about 814 MB including roughly 809 MB of weights. Fine-tuning an existing checkpoint
on row crops is possible, but attempting comparable pretraining on private statements is
neither necessary nor credible.

**Dessurt.** Dessurt accepts an image and a task string and generates arbitrary text; its
paper demonstrates reading, locating, and form/receipt-style parsing without a separate
OCR system ([paper](https://arxiv.org/pdf/2203.16618),
[MIT-licensed code](https://github.com/herobd/dessurt)). The paper's pretraining used six
Tesla P100 GPUs, document images, Wikipedia-derived synthetic data, handwriting, and form
tasks. It is useful evidence that task-conditioned document generation can work, but its
older custom runtime and non-Hebrew pretraining make it less reproducible here than a
grounded classifier.

**Florence-2.** The
[Florence-2-base model card](https://huggingface.co/microsoft/Florence-2-base) exposes both
`<OCR>` and `<OCR_WITH_REGION>` prompts, with the latter returning text and quadrilateral
regions. The MIT-licensed 0.23B model has a
[463 MB FP16 artifact](https://huggingface.co/microsoft/Florence-2-base/tree/5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac)
and was pretrained as part of FLD-5B, described as 5.4B annotations over 126M images. The
[official fine-tuning accelerator](https://github.com/microsoft/dstoolkit-finetuning-florence-2)
demonstrates custom visual-task adaptation. Start with a zero-shot, exact-match calibration;
do not invest in adaptation unless it correctly preserves characters and regions on the
target scripts.

**TrOCR.** The
[TrOCR paper](https://arxiv.org/abs/2109.10282) and
[official MIT-licensed implementation](https://github.com/microsoft/unilm/blob/master/trocr/README.md)
treat OCR as image-to-sequence generation. The
[small printed checkpoint](https://huggingface.co/microsoft/trocr-small-printed) is 62M
parameters, was fine-tuned on SROIE, and has a
[246 MB safetensors artifact](https://huggingface.co/microsoft/trocr-small-printed/tree/main).
It may rescore ambiguous numeric or Latin crops, but it neither understands transaction
roles nor establishes Hebrew recognition.

**SmolVLM.** The Apache-2.0
[SmolVLM-256M-Instruct card](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct)
describes an English image-text model with 64 visual tokens per 512 x 512 patch and
one-image inference under 1 GB GPU RAM; its
[artifact tree](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct/tree/b20c4d6da157f5fe46e994ed0daf86571afb731c)
contains 513 MB safetensors weights. Those are impressive general-VLM constraints, but
visual compression and generative output are the wrong defaults for digit-exact financial
fields.

### OCR and small visual-only supporting options

PaddleOCR is a possible OCR-front-end comparison, not a transaction-field model. Current
[PP-OCRv6 documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md)
lists recognition models from 4.4 MB to 73.3 MB and claims 49-50-language coverage, but
the documentation inspected does not explicitly establish Hebrew accuracy. The project
code is Apache-2.0 ([repository](https://github.com/PaddlePaddle/PaddleOCR)). Its older
[PP-Structure KIE path](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/kie/README.md)
uses LayoutXLM/VI-LayoutXLM and cached/custom OCR, but pins a legacy Paddle stack and marks
the KIE model material CC BY-NC-SA 4.0. Do not replace the known local OCR baseline merely
from a language-count claim; benchmark character-level fidelity first.

FUDGE is useful architectural precedent for a small visual-only entity/link graph that
does not depend on a language model ([paper](https://arxiv.org/abs/2105.08194)). Its
[official implementation](https://github.com/herobd/Visual-Template-Free-Form-Parsing) is
GPL-3.0 and uses an old custom stack, so its ideas are more useful here than its code.

## Deterministic shadow experiment

### Frozen inputs and private labels

- Freeze the exact accepted SHA, model artifact SHA-256, feature schema, OCR artifacts,
  row IDs, and current `Row.bbox` values before a run.
- Render every row with a versioned transform: fixed DPI, padding, interpolation,
  colorspace, orientation, and clipping behavior. Store only private crops/caches.
- Transform existing glyph/word/cell boxes into row coordinates without changing their
  atom IDs. Labels name exact atom IDs and roles, not copied financial values in tracked
  files.
- Split by source document or template family, never randomly by row. Otherwise rows from
  one statement leak typography, merchant repetition, and column geometry into both train
  and test sets.
- Freeze train, calibration, and held-out test membership before comparing models. Use the
  calibration set for thresholds; report the held-out set only after choices are fixed.

### Model variants

| ID | Variant | Private labeled-row scales | Question answered |
|---|---|---:|---|
| A | Linear/CRF/tree over current candidate, geometry, confidence, and character-shape features | 50, 100, 250, 500, 1,000+ | How much is recoverable without pixels or a large dependency? |
| B | MobileNetV3-small local atom crops + A's features; atom/span role head | 100, 250, 500, 1,000+ | Do pixels disambiguate roles while preserving exact evidence? |
| C | Multilingual MiniLM + learned 2-D boxes + candidate features | 250, 500, 1,000+ | Does multilingual context beat compact deterministic features? |
| D | LiLT-InfoXLM token classifier | 250, 500, 1,000+ | Does pretrained document layout justify its footprint? |
| E | Florence-2 `<OCR_WITH_REGION>`, zero-shot first; adapter only after script audit | 0; then 1,000+ | Can a small general model propose correct text/regions without field authority? |
| F | TrOCR-small-printed on ambiguous numeric/Latin line crops | 100, 500 | Can targeted OCR repair improve candidates without changing row logic? |
| G | Donut row-to-JSON, greedy decoding, proposal-only | 500, 1,000+ plus generic synthetic rows | What is lost or gained by OCR-free generation and exact-match rejection? |
| H | LayoutLMv3-base, only if license-cleared | 250, 500, 1,000+ | Research ceiling for joint image/text/layout encoding. |

Fifty rows are useful only for plumbing and gross overfit checks. Hundreds of rows can
support the compact grounded models if every field has adequate positives and hard
negatives. A 1,000+ row tier is a more credible starting point for fine-tuning pretrained
encoders. OCR-free Hebrew generation likely needs thousands of reviewed row crops plus
generic synthetic bidirectional-text augmentation; that still does not reproduce the
large-scale pretraining of Donut, Dessurt, or Florence-2. Synthetic data may vary fonts,
layouts, currencies, dates, signs, and bidi text, but real reviewed rows remain the only
acceptance set.

### Metrics

Report by model and labeled-row tier:

- exact atom-span precision, recall, and F1 for every field role;
- exact field match, including exact `Decimal` equality for amounts and exact parsed dates
  and currencies;
- merchant exact match and normalized character error rate as separate measures;
- whole-row exact match;
- coverage, abstention, and **false-accept count** at each confidence threshold;
- selective risk/coverage curves and calibration error;
- disagreements with the current parser, broken down into model win, parser win, both
  wrong, and unreviewed;
- p50/p95 warm single-row CPU latency, cold-start latency, peak RSS, installed dependency
  size, and model download size on the selected machine; and
- byte-identical canonical shadow output across repeated runs.

Accuracy averaged over easy fields is not the decision metric. The promotion metric is
zero or an explicitly reviewed near-zero false-accept rate at useful incremental coverage,
because one hallucinated amount can be more damaging than many abstentions.

### Acceptance cascade

1. The accepted parser remains authoritative; all new outputs are shadow-only initially.
2. A proposal must resolve to one unique, non-overlapping evidence atom span inside the
   frozen row and compatible existing column/role region.
3. Existing date, currency, `Decimal`, role-contract, ambiguity, and evidence-claim logic
   must accept the exact span.
4. Calibrated confidence must clear a threshold fixed on a document-separated calibration
   set. For the first promotion, also require agreement with an independently shaped model
   or deterministic rule.
5. Re-run existing transaction reconciliation. Reject any proposal that changes row
   identity, creates conflicting claims, or prevents required reconciliation.
6. Abstain on disagreement, low confidence, ambiguous evidence matching, or malformed
   generated output. The first production experiment may fill an unresolved field but must
   not override an already accepted exact value.
7. Only after implementation, use the repository's tracked verification and the private
   corpus `verify` gate from a clean, independently pinned commit. This research note is
   **not corpus verification**.

### Repeatability controls

Use inference-only evaluation mode, greedy decoding with no sampling for generators,
fixed batch ordering and thread counts, pinned CPU/runtime/library versions, hashed model
and tokenizer artifacts, and `torch.use_deterministic_algorithms(True)` where the selected
operators support it. PyTorch's official
[reproducibility guidance](https://docs.pytorch.org/docs/stable/notes/randomness) warns that
complete reproducibility is not guaranteed across releases, platforms, or CPU/GPU even
with identical seeds, and its
[deterministic-algorithm API](https://docs.pytorch.org/docs/2.9/generated/torch.use_deterministic_algorithms.html)
can raise errors or reduce performance. Therefore repeatability is an empirical gate:
repeat the frozen run and compare canonical bytes; do not infer it from a seed.

## Dependency and implementation decision

The accepted project currently has only Pydantic, PyMuPDF, and Typer as runtime
dependencies. Every neural path would introduce at least a tensor runtime and image
preprocessing, while Transformers candidates also add tokenizer/model dependencies and
large artifacts. Keep experiments in a separate optional environment or extras group; do
not burden normal parsing until a model passes the incremental-coverage, false-accept,
latency, memory, license, and repeatability gates.

The original research repositories do **not** establish compatibility with this project's
Python 3.13 environment:

- LiLT's official recipe uses Python 3.7, PyTorch 1.7.1, torchvision 0.8.2, CUDA 11.0,
  and detectron2 0.5 ([official installation](https://github.com/jpWang/LiLT#installation)).
- LayoutLMv3's official recipe uses Python 3.7, PyTorch 1.10.0 with CUDA 11.1,
  torchvision 0.11.1, and a matching detectron2 wheel
  ([official installation](https://github.com/microsoft/unilm/blob/master/layoutlmv3/README.md#installation)).
- Donut's official recipe uses Python 3.7 and says `donut-python==1.0.1` was tested with
  PyTorch 1.11.0/CUDA 11.3, torchvision 0.12.0, PyTorch Lightning 1.6.4,
  Transformers 4.11.3, and timm 0.5.4. The same README warns of configuration problems
  caused by newer dependency versions
  ([official installation](https://github.com/clovaai/donut#software-installation)).

Transformers now exposes separate implementations of several candidates, but that does
not make a particular Python 3.13/PyTorch/Transformers combination proven. Build the first
experiment with current, mutually compatible CPU wheels in an isolated lock file, record
every resolved version and artifact hash, and run a load/forward/determinism smoke test.
Do not copy the archival CUDA stacks into the parser environment.

Recommended order:

1. annotate exact private atom spans on frozen rows and build variant A;
2. add MobileNetV3-small variant B and retain it only if pixels improve held-out selective
   risk at acceptable CPU cost;
3. audit Hebrew tokenization, then compare MiniLM and LiLT on the same split;
4. run Florence-2, TrOCR, and Donut only as proposal-only controls; and
5. do not integrate LayoutLMv3, Paddle KIE assets, or GPL FUDGE code without an explicit
   license decision.

This order directly tests whether row imagery improves transaction-field extraction while
preserving the parser's strongest property: every accepted financial value is exact,
deterministic, locally derived, and traceable to immutable document evidence.
