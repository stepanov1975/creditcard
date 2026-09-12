# Reliable structured extraction from heterogeneous financial statements

**Decision-oriented literature review, current through 2026-07-27**

## Scope and method

This note reviews primary research and official project/model sources relevant to extracting typed transactions from heterogeneous credit-card and bank-statement PDFs and images. It is tailored to this repository's documented design: positioned digital text first, OCR only when necessary, geometry-aware row reconstruction, source evidence and ambiguity reporting, exact `Decimal` reconciliation, conservative abstention, and local processing ([repository overview](../../README.md), [parser design](../superpowers/specs/2026-07-18-credit-card-parser-design.md), [semantic-evidence design](../superpowers/specs/2026-07-20-semantic-evidence-completeness-design.md)).

The review prioritizes archival papers and official artifacts. Preprints and model-team benchmarks are included because much of the 2025–2026 frontier is not yet archival, but they are identified as such. “State of the art” below always means a result reported on a named benchmark version under that paper's protocol, never a universal ranking. No private or ignored corpus content was opened, copied, or evaluated for this review.

The target is stricter than generic PDF-to-Markdown or key-value extraction. A useful system must recover every transaction row, preserve exact dates/descriptions/amounts and debit-credit semantics, connect each value to evidence, handle continuation and cross-page structure, satisfy statement arithmetic, emit the repository schema deterministically, and decline unsupported cases. None of the reviewed public benchmarks tests that complete contract for mixed Hebrew/Latin, right-to-left statements.

## Executive answer: does this repository use the state of the art?

**It uses several of the strongest ideas for high-assurance financial extraction, but it is not a demonstrated state-of-the-art system.** The accepted implementation is unusually strong at exact source preservation, local processing, explicit provenance, deterministic arithmetic, reconciliation, and fail-closed behavior. It is comparatively weak at learned layout generalization, maintaining multiple extraction hypotheses, calibrated selective acceptance, and independently measuring performance on unseen layout families and acquisition degradations.

There is no public benchmark from which to conclude that any alternative is better on this exact Hebrew/mixed-RTL contract. The papers establish a narrower conclusion: a learned proposal stage beneath independent, evidence-grounded acceptance is the **most defensible next hypothesis to test**, not an already proven replacement and not yet a reason to refactor production interfaces.

### Revision boundary used in this assessment

Two repository states must not be conflated:

- Accepted `main` is `dee4b071ad65231da13825f2f7c74a488ca96c7c`. It is the production control assessed below.
- The clean `codex/semantic-contract-fixes` worktree is `dd8d3090659c9bed2a81fd0fb8ad227c2e88d075`, 44 commits ahead of `main`. It materially improves semantic contracts but is unmerged work in progress.

No private-corpus gate was run for this research. The WIP branch has no formal corpus attestation, and its own `docs/superpowers/specs/2026-07-25-semantic-import-readiness-design.md` says its intentional status/output changes require a separately reviewed and pinned baseline promotion. Fresh tracked checks in the WIP worktree passed Ruff formatting, Ruff lint, and mypy; pytest reached 3,148 passes and five sealed-runtime corpus-gate failures caused by this sandbox's Git-internals/ptrace restrictions. That is not a full-suite or corpus-pass claim.

### What is actually implemented

Accepted `main` is an issuer-neutral parser **within a bounded Hebrew/mixed-RTL credit-card domain**, not a generic bank-ledger parser. Its public column model has transaction dates, descriptions, billed/original amounts, currencies, FX, location, and installments, but no debit/credit columns, running balance, opening balance, or closing balance ([column roles](../../src/ccparser/layout/models.py)). Supporting ordinary bank statements would require another statement-family interpreter and another reconciliation invariant, not a few more lexical markers.

The implemented path is:

```text
immutable PDF bytes
  -> PyMuPDF glyphs, words, vectors, images, and page-quality evidence
  -> page-selective local Tesseract OCR when embedded evidence is weak
  -> deterministic row/column/region reconstruction
  -> deterministic statement discovery and semantic normalization
  -> positioned field/row evidence plus exact Decimal reconciliation
  -> canonical JSON/CSV or conservative non-success status
```

This is supported directly by the parser's injected stage protocols and orchestration ([parser](../../src/ccparser/parser.py)), PDF evidence extraction ([PDF evidence](../../src/ccparser/evidence/pdf.py)), OCR commands ([OCR](../../src/ccparser/evidence/ocr.py)), discovery ([discovery](../../src/ccparser/discovery.py)), normalization ([normalization](../../src/ccparser/normalize.py)), and exact reconciliation ([reconciliation](../../src/ccparser/reconcile.py)). There is no learned table/layout/document model or issuer adapter; Tesseract is the only learned inference component.

### Repository-to-frontier scorecard

| Capability | Accepted `main` | Assessment against current evidence |
|---|---|---|
| Preserve born-digital text and geometry | Yes; immutable bytes, positioned glyph/word evidence, vector rules | **Strong/aligned.** Rasterizing or regenerating healthy PDF text would throw away useful evidence. |
| Selective local OCR | Yes; page-quality routing plus targeted numeric/currency repair, with official Hebrew Tesseract data | **Strong foundation, not proven optimal.** New OCR systems warrant script-specific shadow tests, not a global migration. |
| Layout/table understanding | Hand-built geometry, lexical profiles, and bounded rules | **Material gap.** Learned table/row proposals may generalize better to unseen layouts and degraded captures, but public table scores do not prove that here. |
| Multiple hypotheses and global selection | Primarily one deterministic interpretation with bounded repair passes | **Gap.** A factorized ambiguity graph or proposal sidecar could preserve OCR/row/ownership alternatives until global constraints are applied. |
| Source grounding and auditability | Positioned evidence survives through cells, rows, fields, and reconciliation | **Strong and worth preserving.** Many end-to-end model outputs are weaker here. |
| Semantic completeness | Accounting success and semantic completeness are separable on accepted `main` | **Confirmed correctness gap.** WIP adds an explicit semantic-completeness contract, but it is not accepted yet. |
| Financial proof | Exact context-independent `Decimal` arithmetic and printed-total reconciliation | **Strong/aligned, but necessary only.** Reconciliation cannot detect every omitted/duplicated offsetting row or wrong non-amount field. |
| Abstention | Conservative statuses and ambiguity handling | **Strong/aligned.** Model self-confidence must not weaken it. |
| Calibrated acceptance | Fixed heuristic scores/margins, not empirically calibrated document risk | **Gap.** Measure false-accept risk versus coverage by route/layout/script; do not call raw confidence calibrated. |
| Generalization evidence | Strong deterministic private regression-gate design | **Partial.** Regression parity is not the same as a predeclared source/template/time holdout or degradation benchmark. No formal private run was performed here. |
| Maintainability | Deep public parser, but substantial rule volume and cross-module private imports | **Growing risk.** `main` has about 32.7k production lines; the WIP grows to about 36.8k. Several core rule modules remain 2.3k–3.8k lines. This suggests diminishing locality, not by itself proof of corpus overfitting. |

Accepted `main` also has a concrete semantic false-success boundary. Its tests require proven but unanchored two-digit dates to become `transaction_date=None` with no ambiguity while the statement remains `RECONCILED` ([accepted-main regression](../../tests/test_normalize.py#L4383-L4426)); the Python `strict` argument is explicitly discarded ([parser](../../src/ccparser/parser.py#L147-L160)). The WIP changes success to require semantic completeness, makes merchant description/details source-owned, recovers uniquely grounded year context in a targeted second pass, and implements typed strict failures. Those changes strengthen the verifier; they do not introduce a learned parser or solve the generalization question.

### Architectural conclusion

Do not replace the current parser with a full-page VLM, and do not continue an indefinite residual-case rule chase. Preserve the WIP's stronger semantic contract for review, then pause production fine-tuning long enough to locate the limiting subsystem and run proposal systems in shadow mode.

If an alternative earns integration, the target should look like this:

```text
positioned native/OCR evidence
  -> factorized proposals
       - current deterministic hypotheses
       - optional OCR/layout/table/VLM proposals
  -> independent verifier
       - source/value grounding and document/row coverage
       - semantic ownership and completeness
       - contradiction checks and exact family-specific arithmetic
  -> one uniquely supported canonical result, otherwise abstain/review
```

The proposal representation should remain internal. Do not create a broad `StatementCandidate` framework until two real proposal implementations reveal the smallest stable common contract.

## Decision

### Main path: preserve and deepen the hybrid, evidence-first parser

Given this repository's safety contract, the most defensible architecture to test and retain is:

1. preserve exact embedded PDF glyphs and geometry when available;
2. OCR only image-only or demonstrably weak regions;
3. use learned models, if added, to **propose** table regions, row boundaries, continuations, or semantic associations;
4. require every accepted value to map back to positioned source evidence;
5. validate types, row topology, statement semantics, and exact arithmetic independently of the proposer;
6. calibrate document-level acceptance on held-out private data and abstain when evidence or reconciliation is insufficient.

This is stronger than a preference based on engineering taste. Four unusually relevant studies point in the same direction, with important qualifications:

- **TabSniper** is the closest published bank-statement-specific work found. It combines DETR-style table detection/categorization, table-structure recognition, OCR, heuristics, and an opening/closing-balance checksum. Its private BankTabNet data cover long and multi-page bank tables, but the work does not provide an independently reproducible public bank-statement benchmark, and it reports failure on tilted mobile captures. Its public comparisons are against scientific/financial-report table datasets, not exact transaction schemas ([TabSniper, CODS-COMAD 2024](https://arxiv.org/abs/2412.12827)).
- A **WACV 2026** benchmark explicitly recommends a small supervised table detector followed by a zero-shot VLM for structure recognition. That is direct support for a hybrid cascade, but the experiment uses English, single-page documents with exactly one product table, excludes spanning cells and multi-row headers, evaluates detection and structure independently, and gives structure models the ground-truth crop. It therefore does not establish end-to-end row completeness, financial semantics, Hebrew/RTL robustness, or reconciliation ([Thomas et al., WACV 2026](https://openaccess.thecvf.com/content/WACV2026/html/Thomas_Zero-Shot_Table_Extraction_in_Business_Documents_A_Unified_Benchmark_with_WACV_2026_paper.html)).
- An archival **neurosymbolic transactional-document** study generates invoice/receipt candidates with local language/vision-language models and filters them by JSON syntax, verbatim OCR presence, and arithmetic domain constraints. Filtering raises F1 on the retained subset, but zero-shot domain filtering retains only 11.7–44.0% of documents in the reported configurations; even arithmetically valid outputs are not fully correct. The result supports validation plus abstention, not the claim that symbolic validity repairs a generator or proves completeness ([Hemmer et al., IJDAR 2025](https://doi.org/10.1007/s10032-025-00530-0); [open manuscript](https://arxiv.org/abs/2512.09666)).
- The **FinBalance** preprint finds that replaying generated journal entries through a deterministic ledger exposes a large gap between model-reported and recomputed balance sheets. Forced ledger feedback improves reported exact balance sheets by 30–33 percentage points in its ablations, while citation pressure barely changes document-linking errors. This strongly favors independent computation over asking a model to self-check. However, FinBalance is synthetic, reasons over clean OCR-style text, and explicitly does not measure end-to-end layout/OCR fidelity ([FinBalance, 2026 preprint](https://arxiv.org/abs/2606.15949)).

Taken together, these sources support **candidate generation + independent grounding/domain/arithmetic validation** more directly than they support a pure full-page VLM. They do not show that the hybrid is already solved: validation commonly converts uncertainty into rejection, and neither arithmetic coherence nor JSON validity proves that every source row was found.

### WIP research lane: bounded learned sidecars, not a replacement parser

Do not assume that a document VLM is the next-best intervention. The shadow comparison should include a deterministic ambiguity lattice or weighted constraint solver over OCR alternatives, row groupings, and semantic ownership; OCR ensemble/lattice voting; learned layout only; a learned quality/router model that decides when to invoke recovery; and human review for the low-coverage tail. If the distribution is deliberately narrow and stable, managed layout-family adapters are also a legitimate reliability/cost comparator even though they are less generic.

The following are justified experiments, ordered by likely value and safety:

1. **Row/table proposal sidecar.** Test a small table detector/structure model that emits only regions, row/column boundaries, header zones, and continuation hypotheses. The deterministic code remains the sole owner of characters, amounts, transaction objects, and acceptance.
2. **Layout-aware semantic sidecar.** Given exact PDF/OCR tokens plus bounding boxes, predict associations such as header-to-column, date-to-row, amount polarity, or continuation. Require token/bounding-box grounding and retain existing semantic-evidence rules.
3. **OCR shadow benchmark.** Compare the pinned Tesseract Hebrew path against other local OCR only on controlled Hebrew/Latin/numeric line crops and a reviewed private evaluation slice. Do not switch globally based on English/Chinese benchmark claims.
4. **Last-resort local document VLM.** Route only unsupported scans/captures to cropped, coarse-to-fine proposal generation. Enforce a schema during decoding, map every output value back to evidence, run exact reconciliation, and abstain on disagreement or unsupported scripts.
5. **Quality-aware review/label collection.** Use candidate confirmation and error-taxonomy-driven selection to spend annotation effort on uncertain or novel layouts, while maintaining fully labeled audit sets to detect missed rows.

Full-page OCR-free replacement is a watchlist item, not the main path. Current models are impressive at page-to-Markdown reconstruction, but their benchmark objectives generally tolerate mistakes that are unacceptable in a financial ledger; their strongest public tests are predominantly English/Chinese and report-level rather than Hebrew transaction-level.

## What the evidence says by subsystem

### 1. Digital text, OCR, and layout-aware encoders

For born-digital PDFs, exact glyph extraction has an information advantage: it preserves the PDF's character data and coordinates without rasterization or autoregressive regeneration. The learned literature does not provide evidence that an image model should replace valid embedded text. Layout-aware models instead show how to add semantic context to text plus position:

- LayoutLM introduced joint text-and-layout pretraining; LayoutLMv2 added visual features and spatial-aware attention; LayoutLMv3 unified text/image masking and word-patch alignment ([LayoutLM, KDD 2020](https://www.microsoft.com/en-us/research/publication/layoutlm-pre-training-of-text-and-layout-for-document-image-understanding/), [LayoutLMv2, ACL 2021](https://aclanthology.org/2021.acl-long.201/), [LayoutLMv3, ACM MM 2022](https://doi.org/10.1145/3503161.3548112)). These models still depend on OCR/text tokens and boxes for extraction tasks; they are evidence for enriching the repository's positioned-text representation, not discarding it.
- BROS models relative two-dimensional positions and text; XYLayoutLM uses XY-cut-derived reading order; LiLT decouples language and layout so a pretrained layout component can be paired with language models ([BROS, AAAI 2022](https://ojs.aaai.org/index.php/AAAI/article/view/21322), [XYLayoutLM, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/html/Gu_XYLayoutLM_Towards_Layout-Aware_Multimodal_Networks_for_Visually-Rich_Document_Understanding_CVPR_2022_paper.html), [LiLT, ACL 2022](https://aclanthology.org/2022.acl-long.534/)). Their multilingual evaluations do not establish Hebrew or bidirectional-table performance. XY-cut ordering is especially a hypothesis to test, not assume, on RTL pages.
- LayoutXLM's XFUND benchmark covers seven non-English languages but not Hebrew ([LayoutXLM/XFUND](https://arxiv.org/abs/2104.08836)). “Multilingual” in these papers therefore cannot be read as “supports this corpus.”
- DocLLM avoids an image encoder and injects bounding-box layout into a generative language model; LMDX encodes OCR layout for an LLM and constrains outputs to be localizable back to OCR tokens ([DocLLM, ACL 2024](https://aclanthology.org/2024.acl-long.463/), [LMDX, Findings ACL 2024](https://aclanthology.org/2024.findings-acl.899/)). LMDX's grounding idea is highly relevant, but its reported experiments use proprietary PaLM/Gemini models on forms/receipts and do not validate local Hebrew statements.

For OCR itself:

- Tesseract's official `tessdata_best` repository ships a `heb.traineddata` LSTM model, making it a verified local Hebrew option ([Tesseract `tessdata_best`](https://github.com/tesseract-ocr/tessdata_best), [official data-file documentation](https://github.com/tesseract-ocr/tessdoc/blob/main/Data-Files.md)). An OCR engine's confidence is a recognition score, not a calibrated probability that a complete and semantically correct transaction was extracted.
- TrOCR is an end-to-end transformer recognizer for cropped text; text detection and document structure are outside its task ([TrOCR, AAAI 2023](https://ojs.aaai.org/index.php/AAAI/article/view/26538)). It is a recognizer experiment, not a replacement for layout/row logic.
- PP-OCRv5 is an archival 5M-parameter specialist, and the June 2026 PP-OCRv6 preprint reports medium/small/tiny detection-recognition systems from 34.5M down to 1.5M end-to-end parameters ([PP-OCRv5, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Cui_PP-OCRv5_A_Specialized_5M-Parameter_Model_Rivaling_Billion-Parameter_Vision-Language_Models_on_CVPR_2026_paper.pdf), [PP-OCRv6, 2026 preprint](https://arxiv.org/abs/2606.13108)). PP-OCRv6 reports 83.2% recognition accuracy and 86.2% detection H-mean for its medium model on **in-house** benchmarks. Its 50-language model covers Chinese, English, Japanese, and Latin-script languages; its published list does not include Hebrew. These self-reported, non-statement results justify a controlled English/numeric shadow test, not a Hebrew OCR migration.

The practical conclusion is to keep digital text first and selective OCR second. If a learned OCR option is tested, evaluate exact character sequences and bounding boxes by script and region type, then evaluate the downstream document contract; do not infer the latter from recognition accuracy alone.

### 2. Tables, rows, and multi-page continuation

General table benchmarks have moved from table boxes toward cell structure, but their data domains matter:

- PubTables-1M provides almost one million scientific-article tables with canonicalized structure annotations and underpins Table Transformer, a DETR-style detector/structure recognizer ([PubTables-1M, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/papers/Smock_PubTables-1M_Towards_Comprehensive_Table_Extraction_From_Unstructured_Documents_CVPR_2022_paper.pdf), [official Table Transformer repository](https://github.com/microsoft/table-transformer)). It is large, public, and useful for initialization, but scientific table conventions differ from bank statements.
- FinTabNet/GTE provides detailed financial-report table annotations, not bank transaction statements ([Global Table Extractor/FinTabNet, WACV 2021](https://arxiv.org/abs/2005.00589)). “Financial” here means annual-report tables, so transfer to running balances, sign conventions, and long transaction descriptions is unproven.
- TableFormer decodes table structure and cell boxes while using programmatically extracted PDF text; UniTable uses a pixel-only unified structure/content/bounding-box objective; UniTabNet adds physical and logical decoders with visual guidance ([TableFormer, CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/papers/Nassar_TableFormer_Table_Structure_Understanding_With_Transformers_CVPR_2022_paper.pdf), [UniTable, 2024 preprint](https://arxiv.org/abs/2403.04822), [UniTabNet, Findings EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.355/)). Their reported table scores do not test transaction polarity, evidence, or statement arithmetic.

TabSniper is more directly informative. Its BankTabNet annotations include thousands of tables and tens of thousands of rows; it handles long tables by splitting training examples, uses OCR position to refine row separators, fills row/column gaps, normalizes header variants, reasons about debit/credit columns, and checks opening/closing balances ([TabSniper full paper](https://ar5iv.labs.arxiv.org/html/2412.12827v1)). The architecture closely resembles a useful sidecar for this repository. The limitations are decisive: BankTabNet is described as in-house, results cannot be independently reproduced on a public bank corpus, public comparisons use PubTables/FinTabNet, and tilted mobile images remain a reported failure mode.

The WACV 2026 business-document benchmark reinforces a component boundary. Fine-tuned DETR/YOLO models give more reliable table boxes and lower wrong/empty detections; zero-shot commercial VLMs lead its table-structure metrics. The authors' own pragmatic design is a lightweight detector followed by a VLM ([WACV 2026 paper](https://openaccess.thecvf.com/content/WACV2026/papers/Thomas_Zero-Shot_Table_Extraction_in_Business_Documents_A_Unified_Benchmark_with_WACV_2026_paper.pdf)). Yet the test has one product table per page and gives structure recognition a ground-truth crop. A repository experiment should therefore first ask whether a small model improves **row and continuation proposals over current geometry**, not whether its TEDS score looks strong.

QUEST offers a related quality lesson. It trains an XGBoost assessor on 21 structural/contextual features and their distributional transforms to predict extraction F1, then selects diverse pseudo-labels for iterative training. On the authors' private business set, the reported correlation with true F1 is 0.80 versus 0.22 for raw confidence; on DocILE it is 0.67 versus 0.46. Table-extraction F1 rises from 64 to 74 on the private set and 42 to 50 on DocILE ([QUEST, ICDAR 2025](https://doi.org/10.1007/978-3-032-04630-7_16); [open manuscript](https://arxiv.org/abs/2506.14568)). But the system handles single tables without spanning cells, needs labeled examples to train its assessor, and on DocILE selects only 11 unique pseudo-labeled documents from roughly 20,000 candidates over the reported iterations. This is evidence that structural quality features outperform raw model confidence within a domain, not evidence of domain-independent confidence.

### 3. OCR-free and end-to-end document models

OCR-free models remove an external OCR dependency by learning image-to-sequence conversion:

- Donut uses an image encoder and autoregressive decoder with synthetic document pretraining; Pix2Struct pretrains screenshot-to-simplified-HTML; Dessurt maps an image plus task string to arbitrary text ([Donut, ECCV 2022](https://mlanthology.org/eccv/2022/kim2022eccv-ocrfree/), [Pix2Struct, ICML 2023](https://proceedings.mlr.press/v202/lee23g.html), [Dessurt, 2022 preprint](https://arxiv.org/abs/2203.16618)). They demonstrate that an OCR-free route is viable, but their public tasks are receipts/forms/web screenshots rather than exact mixed-RTL transaction ledgers.
- UDOP unifies vision, text, and layout under prompted generation; mPLUG-DocOwl1.5 uses unified structure learning; GOT-OCR2.0 and KOSMOS-2.5 target broad OCR/markup generation ([UDOP, CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/html/Tang_Unifying_Vision_Text_and_Layout_for_Universal_Document_Processing_CVPR_2023_paper.html), [mPLUG-DocOwl1.5, Findings EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.175/), [GOT-OCR2.0, 2024 preprint](https://arxiv.org/abs/2409.01704), [KOSMOS-2.5, 2023 preprint](https://arxiv.org/abs/2309.11419)). These are useful proposal generators, but markup fidelity is not typed financial correctness.
- Qwen2.5-VL's report and model card describe structured extraction and grounded boxes/points; the 7B checkpoint is locally deployable under Apache 2.0 ([technical report](https://arxiv.org/abs/2502.13923), [official 7B model card](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)). No primary result found establishes exact Hebrew statement extraction.

Recent specialist parsers improve efficiency through decomposition:

- MinerU2.5 is a 1.2B preprint model that first analyzes layout at reduced resolution and then recognizes native-resolution crops. Its coarse-to-fine split is architecturally relevant because it bounds expensive generation to detected regions ([MinerU2.5, 2025 preprint](https://arxiv.org/abs/2509.22186)). Its reported strengths are page parsing, tables, formulas, and English/Chinese text; it does not evaluate the repository's transaction schema or Hebrew.
- PaddleOCR-VL-1.5 is a 0.9B preprint model reporting 94.5 on **OmniDocBench v1.5** and results on the authors' Real5 benchmark. Its language appendix lists 111 languages/scripts but does not list Hebrew ([PaddleOCR-VL-1.5, 2026 preprint](https://arxiv.org/abs/2601.21957)). PaddleOCR-VL-1.6 is the newer June 2026 preprint, reporting 96.33 on **OmniDocBench v1.6**, and is available for local deployment under Apache 2.0 ([PaddleOCR-VL-1.6 preprint](https://arxiv.org/abs/2606.03264), [official model card](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6)). The v1.5 and v1.6 headline numbers are not directly comparable without a common benchmark release and protocol.
- The June 2026 PP-OCRv6 results provide a useful counterweight to scaling: a specialist recognizer can outperform much larger VLMs on the model team's OCR benchmarks with far fewer parameters ([PP-OCRv6](https://arxiv.org/abs/2606.13108)). This supports routing narrow OCR work to a specialist rather than assuming a larger general model is safer.

These systems make a cropped fallback technically plausible. They do not justify accepting generated transactions without source matching, exact semantics, and reconciliation. Autoregressive output can normalize or invent plausible text; the PP-OCRv6 paper itself illustrates VLMs “correcting” visually present misspellings on its curated examples. That failure mode is particularly dangerous for merchant strings, identifiers, and amounts.

### 4. Schema-constrained decoding is necessary but insufficient

Constrained decoding can guarantee structural well-formedness:

- PICARD rejects tokens that would make an incremental SQL parse invalid; SynCode and XGrammar generalize efficient context-free/JSON grammar constraints ([PICARD, EMNLP 2021](https://aclanthology.org/2021.emnlp-main.779/), [SynCode, 2024 preprint](https://arxiv.org/abs/2403.01632), [XGrammar, MLSys 2025](https://proceedings.mlsys.org/paper_files/paper/2025/file/5c20ca4b0b20b0bd2f1d839dc605e70f-Paper-Conference.pdf)). The transferable result is that malformed syntax can be prevented during decoding rather than repaired later.
- Grammar-Aligned Decoding shows the counter-risk: a hard grammar can distort the model distribution and force grammatical but lower-quality continuations ([NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/2bdc2267c3d7d01523e2e17ac0a754f3-Abstract-Conference.html)).

A JSON schema can enforce field names, types, list nesting, and perhaps enumerations. It cannot prove that a value appears in the document, that a row was not skipped or duplicated, that a debit was not flipped to a credit, or that the transaction set reconciles. The correct stack is constrained generation **followed by** Pydantic/type validation, source grounding, semantic rules, and exact arithmetic. Schema validity must not be reported as extraction confidence.

### 5. Confidence, selective prediction, and abstention

Raw softmax/OCR/generation confidence is not an acceptance policy. Three lines of evidence matter:

- In a production invoice-extraction study, calibrating failure prediction increased automated coverage from 65.6% to 73.2% at the same reported error level in that deployment ([COMPSAC 2023](https://researchportal.helsinki.fi/en/publications/failure-prediction-in-2d-document-information-extraction-with-cal/)). This is direct evidence for calibration, but the numerical gain is deployment-specific.
- In reliable VQA, ordinary maximum-softmax selection answered under 7.5% of questions at 1% risk, while a learned selector raised coverage in the paper's setting; the recommended evaluation is a risk-coverage curve, not accuracy alone ([Reliable VQA, 2022 preprint](https://arxiv.org/abs/2204.13631)).
- Conformal risk control offers finite-sample expected-risk control for monotone losses under its assumptions, including exchangeability; shift-aware extensions still require explicit assumptions and calibration data ([Conformal Risk Control, ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html)). It is not a distribution-free promise under arbitrary bank/template drift.

QUEST's learned structural quality score and the neurosymbolic filter reinforce the same pattern: quality should be estimated from evidence/topology/domain invariants, and rejection coverage must be measured. The neurosymbolic paper is particularly cautionary: selecting only arithmetically valid candidates can improve retained-set F1 while leaving very low document accuracy and discarding most inputs ([Hemmer et al.](https://arxiv.org/abs/2512.09666)).

For this repository, acceptance should be a document-level decision based on at least:

- source/evidence coverage for every normalized value;
- row and continuation completeness signals;
- schema and semantic validity;
- exact reconciliation status;
- script/layout/source support;
- calibrated risk on a held-out group matching that route;
- disagreement between independent proposal paths.

Model disagreement is useful as a review signal, not as proof that a majority is correct. Calibration should be stratified by input route (digital/OCR/VLM), script, layout family, and acquisition mode; it should be refreshed when weights, OCR data, render DPI, prompts, or templates change.

### 6. Reconciliation and arithmetic reasoning

Financial-QA benchmarks show that arithmetic over tables and text remains a separate capability from extraction. FinQA supplies executable reasoning programs; TAT-QA combines tabular and textual evidence with arithmetic operators; MultiHiertt adds multiple hierarchical tables ([FinQA, EMNLP 2021](https://aclanthology.org/2021.emnlp-main.300/), [TAT-QA, ACL 2021](https://aclanthology.org/2021.acl-long.254/), [MultiHiertt, ACL 2022](https://aclanthology.org/2022.acl-long.454/)). They use financial reports, not raw bank statements, and therefore do not validate OCR or row extraction.

TabSniper directly applies a statement checksum using opening balance, debit/credit sums, and closing balance. FinBalance goes further: it distinguishes the balance sheet written by a model from the one obtained by replaying the model's entries through deterministic code, finding large discrepancies for several models and material improvement when ledger deltas are fed back ([TabSniper](https://arxiv.org/abs/2412.12827), [FinBalance](https://arxiv.org/abs/2606.15949)). These results support the repository's exact `Decimal` reconciliation as an independent acceptance gate.

Reconciliation is not a completeness proof. A balanced hallucinated set, duplicated opposite-sign pair, or paired compensating errors can pass a total. A correct total also does not prove descriptions, dates, currencies, or evidence. Conversely, an apparent mismatch can arise from fees, carried balances, installments, currency conversions, or OCR loss. The safe interpretation is:

> reconciliation failure is strong evidence to reject or investigate; reconciliation success is necessary for strict acceptance where the document exposes the required totals, but remains insufficient without complete grounded rows and semantic evidence.

### 7. Learning efficiently from a private corpus

If learned sidecars become useful, annotation strategy matters:

- FieldSwap replaces field-indicating phrases to synthesize examples of another field. Across five form-like datasets, the archival ICDE paper reports gains of 1–11 F1 points, especially with only 10–100 labeled documents ([FieldSwap, ICDE 2024](https://research.google/pubs/fieldswap-data-augmentation-for-effective-form-like-document-extraction/)). It is relevant to header/field classification, but it does not synthesize reliable transaction rows or arithmetic. Any use would need constraints preventing semantically or arithmetically impossible statements.
- Selective Labeling asks reviewers yes/no questions about model-proposed field candidates and uses active learning to choose uncertain cases. The archival EMNLP study reports roughly 10× lower labeling cost with negligible loss on three form-extraction domains ([Selective Labeling, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.233/)). It is attractive for confirming column/header associations. Because reviewers only see proposed candidates, it can under-label omissions; a separate fully annotated random audit set is essential for row recall and calibration.
- QUEST shows that quality-aware, diversity-filtered pseudo-labeling can improve table extraction with scarce annotations, but also that poor initial models may yield almost no acceptable pseudo-labels ([QUEST](https://doi.org/10.1007/978-3-032-04630-7_16)). Pseudo-labeling should never update the immutable acceptance inventory or become its own correctness proof.

The recommended labeling unit is not merely a field box. For this task it should preserve document/page/row identity, source spans and boxes, normalized typed values, continuation relationships, polarity/currency semantics, and reconciliation roles. Template-, source-, and time-held-out splits should be selected before augmentation.

## Benchmarks and transfer limits

### Public benchmarks answer adjacent questions, not the full product question

| Benchmark | What it tests well | Important transfer limit for this repository |
|---|---|---|
| PubTables-1M / FinTabNet | Table detection and structure at scale | Scientific papers and financial reports, not bank transaction semantics; no Hebrew/RTL claim |
| DocILE | Key information and line-item recognition in 6.7k business documents, plus seen/zero-/few-shot layouts | Invoices and purchase orders; 55 classes do not encode this statement contract ([DocILE, ICDAR 2023](https://arxiv.org/abs/2302.05658)) |
| VRDU | Rich, nested/repeated schemas and new-template generalization | Forms/registration documents; still shows new-template and repeated-entity difficulty ([VRDU, KDD 2023](https://research.google/pubs/vrdu-a-benchmark-for-visually-rich-document-understanding/)) |
| DocLayNet | Diverse layout segmentation across 80,863 human-annotated pages | Layout classes only; paper shows models trained on narrower academic corpora transfer poorly ([DocLayNet, KDD 2022](https://doi.org/10.1145/3534678.3539043)) |
| DUDE | Multi-domain, multi-page QA including lists, counts, and unanswerable questions | QA answers, not exhaustive transaction extraction ([DUDE, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/papers/Van_Landeghem_Document_Understanding_Dataset_and_Evaluation_DUDE_ICCV_2023_paper.pdf)) |
| READoc | Whole-PDF to semantic Markdown across 3,576 documents | Automatically constructed academic/GitHub/Zenodo pairs; not typed finance; its 2025 model panel already shows no paradigm dominates all capabilities ([READoc, Findings ACL 2025](https://aclanthology.org/2025.findings-acl.1128/)) |
| OmniDocBench | Fine-grained layout, text, formula, table, and reading-order parsing over nine document types | English/Chinese/mixed parsing; “financial reports” are not credit-card rows; a composite parsing score does not test reconciliation ([OmniDocBench, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Ouyang_OmniDocBench_Benchmarking_Diverse_PDF_Document_Parsing_with_Comprehensive_Annotations_CVPR_2025_paper.html)) |
| Real5-OmniDocBench | One-to-one physical reconstruction of 1,355 OmniDocBench v1.5 pages under scan, warp, screen-photo, illumination, and skew | 2026 preprint from the Paddle team, based on the same adjacent parsing task; useful robustness stress test but no statement schema/Hebrew ([Real5, 2026 preprint](https://arxiv.org/abs/2603.04205)) |
| CC-OCR / OCRBench v2 | Broad OCR, grounding, multilingual, KIE, and document parsing stress | Strong evidence that orientation, repeated text, grounding, and structured tasks remain hard; not exhaustive ledger extraction ([CC-OCR, ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Yang_CC-OCR_A_Comprehensive_and_Challenging_OCR_Benchmark_for_Evaluating_Large_ICCV_2025_paper.html), [OCRBench v2, NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/8c2e6bb15be1894b8fb4e0f9bcad1739-Abstract-Datasets_and_Benchmarks_Track.html)) |
| MPDocBench-Parse | Multi-page continuity, cross-page table merging, and hierarchy | 433 documents / 3,246 pages in English/Chinese; May 2026 preprint; does not test typed statement reconciliation ([MPDocBench-Parse](https://arxiv.org/abs/2605.22100)) |
| FinBalance | Cited journal entries, deterministic ledger replay, contradictions | Synthetic clean OCR text; accounting bundles rather than visual extraction; preprint |

READoc is useful because it compares pipelines, expert parsers, and general VLMs under one whole-document evaluation. Its reported results show strong domain dependence: specialist Nougat performs well on arXiv-like documents, pipeline tools offer broad capability, and the evaluated general VLMs trail on several structural metrics; the authors also acknowledge automatically generated pair noise ([READoc paper](https://aclanthology.org/2025.findings-acl.1128.pdf)). This argues against selecting a paradigm from a single leaderboard.

Real5 provides a valuable warning against pristine-PDF evaluation. It physically reconstructs every OmniDocBench v1.5 page into five variants and finds non-rigid warping and other capture conditions degrade models. Because it is a preprint from the same organization that develops the leading model reported in the paper, and because its source pages are still OmniDocBench rather than bank statements, it should be treated as a reproducible stress benchmark rather than independent product validation ([Real5](https://arxiv.org/abs/2603.04205)).

### Why field-level scores can mislead

An illustrative—not empirical—calculation shows the compounding problem. If 100 required rows were independently correct with probability 0.99, the probability of an entirely correct document would be (0.99^{100} \approx 36.6\%\). Real errors are not independent, but the example explains why 99% field/row accuracy can coexist with poor all-document acceptance. The primary metric must be strict document correctness and safe coverage, with field metrics used diagnostically.

### Required evaluation for any repository experiment

Use a frozen, privacy-safe manifest and report at least:

- exact document-level transaction-set match;
- row precision and recall, including duplicates, omissions, continuations, and cross-page rows;
- exact normalized date, description, currency, `Decimal` amount, and debit/credit direction;
- zero unsupported/fabricated accepted rows;
- source-grounding coverage and exact source-span/bounding-box agreement;
- statement-level strict reconciliation and reason-coded non-reconciliation;
- risk-coverage/selective accuracy, not only average confidence or F1;
- digital versus scanned/captured, Hebrew versus Latin/numeric, RTL/mixed-direction, table family, institution/template, and time slices;
- new-template/source-held-out performance with no near-duplicate leakage;
- deterministic repeated output under pinned weights, render settings, OCR data, decoding, and worker count;
- cold-cache latency, peak memory, artifact size, and CPU/GPU requirements.

Compare models with the same source pages, rendering, OCR inputs, normalization, and benchmark version. A model can improve TEDS by changing text normalization while becoming worse at exact source fidelity; diagnostics must separate region, row topology, text recognition, semantic normalization, and reconciliation.

Any experiment affecting parsing, extraction, semantic evidence, reconciliation, OCR, or JSON/CSV output remains subject to this repository's private corpus gate after a clean reviewed commit. Public benchmark success cannot replace that attestation.

## Privacy and local deployment

The repository's local-only policy materially changes the design space:

- Tesseract's Hebrew model is local and auditable as a pinned artifact ([official model repository](https://github.com/tesseract-ocr/tessdata_best)).
- Donut's official code is MIT-licensed; Qwen2.5-VL-7B and PaddleOCR-VL-1.6 model cards state Apache 2.0; PaddleOCR is Apache 2.0 ([Donut repository](https://github.com/clovaai/donut), [Qwen2.5-VL model card](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct), [PaddleOCR-VL-1.6 model card](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6), [PaddleOCR repository](https://github.com/PaddlePaddle/PaddleOCR)). Exact dependency and weight licenses still need review before distribution.
- A model running on local hardware is not automatically private or reproducible. Deployment should disable network calls/telemetry, pin weights and revision hashes, keep prompts/images/artifacts out of logs and Git, constrain caches to ignored local paths, and verify deterministic settings. Some GPU kernels and generative sampling remain nondeterministic unless controlled and tested.
- The WACV hybrid's best zero-shot TSR results use commercial APIs, and LMDX's strongest experiments use proprietary models. Their accuracy evidence does not override the local-processing constraint.

No reviewed primary source establishes strong Hebrew/RTL statement performance for the recent Paddle, MinerU, Donut, or Qwen document models. “Multilingual” must be checked against an explicit script/language list; PP-OCRv6 and PaddleOCR-VL-1.5 both omit Hebrew from their published lists. Local deployment therefore removes governance risk but not language-domain risk.

## Open-source landscape and shortlist

No released open-source package found is trustworthy as an authoritative generic bank-statement parser. The useful projects are component challengers. Versions below are the releases inspected at the 2026-07-27 cutoff; every model/runtime/weight license must be rechecked before adoption.

| Candidate | Recommendation | Safe experimental role | Important caveat |
|---|---|---|---|
| Current PyMuPDF + Tesseract route | Permanent control | Exact native evidence and verified local Hebrew OCR | Its document interpretation is rule-based; control status does not prove optimality. |
| [Camelot 2.0.0](https://github.com/camelot-dev/camelot/releases/tag/v2.0.0) | High-priority challenger | Born-digital table structure; optional Table Transformer proposal path while native/OCR tokens retain value ownership | MIT code; reported table metrics are not statement accuracy. |
| [Docling 2.115.0](https://github.com/docling-project/docling/releases/tag/v2.115.0), standard pipeline | High-priority challenger | Local layout, reading order, tables, and structured provenance behind an off-core adapter | MIT code and Python 3.13 support; selected model/OCR licenses and Hebrew quality still require audit. “Lossless JSON” is relative to Docling's conversion, not the source document. |
| [PaddleOCR 3.7.0 / PP-OCRv6](https://github.com/PaddlePaddle/PaddleOCR/releases/tag/v3.7.0) | Primary scan/OCR challenger | Tokens, polygons, and confidence supplied to repository-owned layout/semantics | Apache 2.0 and current CPython 3.13 wheels; headline gains are first-party in-house OCR results and published language coverage does not establish Hebrew. |
| [Granite-Docling 258M](https://huggingface.co/ibm-granite/granite-docling-258M) | One bounded generative lane | Small local page-to-DocTags differential proposal | Apache 2.0; primarily Latin/English and the model card warns about inaccurate output. FinTabNet TEDS is not ledger exactness. |
| [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) | Optional second VLM, capacity permitting | Cropped degraded-document fallback proposal | Apache 2.0 and compact, but current parsing/SOTA claims are model-team results on adjacent benchmarks; no Hebrew statement evidence. |
| [Table Transformer](https://github.com/microsoft/table-transformer) | Usually exercise through Camelot first | Reproducible table/row/column proposals | MIT and public assets, but PubTables-1M/FinTabNet are scientific/corporate-report tables and separate OCR is mandatory. |
| [Surya 2](https://github.com/datalab-to/surya) | Only after legal review | Geometry-rich OCR/layout/table differential | Code and weight terms differ; current model weights have modified OpenRAIL commercial thresholds. Its multilingual score is an internal benchmark. |
| [MinerU2.5-Pro](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) | Low-priority optional lane | Coarse-to-fine English/Chinese parsing comparison | Direct weights and full MinerU runtime have different license implications; published parsing scores are self-reported and not Hebrew/ledger results. |

If resources are constrained, run five lanes only: current control, Camelot, Docling standard, PP-OCRv6, and one pinned local VLM (Granite-Docling first). Keep ML dependencies out of the core environment initially by running revision-pinned offline sidecars.

The active [`sebastienrousseau/bankstatementparser`](https://github.com/sebastienrousseau/bankstatementparser) project is not a competitive accuracy reference. At inspected release v0.0.11, its PDF route concatenates `pypdf` text and sends documents above a 50-character threshold to a generic text LLM; shorter documents go to a generic vision LLM. The route is document-wide, its vision path caps input at five pages, its post-hoc text provenance does not independently ground amount/date/sign, and tracked PDF tests are synthetic or mocked. Its balance check is useful consistency logic, but balances and rows can originate in the same model response. It is suitable only as an adversarial low-safety baseline; README claims and stars are not comparative evidence ([orchestrator](https://github.com/sebastienrousseau/bankstatementparser/blob/v0.0.11/bankstatementparser/hybrid/orchestrator.py#L369-L413), [vision path](https://github.com/sebastienrousseau/bankstatementparser/blob/v0.0.11/bankstatementparser/hybrid/vision.py#L163-L223), [CI live-evaluation step](https://github.com/sebastienrousseau/bankstatementparser/blob/v0.0.11/.github/workflows/quality-gates.yml#L229-L267)).

TabSniper remains the closest research architecture but is not an installable dependency: no released code, weights, or BankTabNet annotations were found, and its bank data/results cannot be independently reproduced from public artifacts.

## Recommended experimental sequence

### Stage A — freeze the control and locate the limiting subsystem

Freeze a privacy-safe evaluation manifest and the current deterministic route. Record strict document correctness, safe coverage, rejection reasons, reconciliation, runtime, memory, and deterministic hashes. Do not expose source names or values in logs.

Before installing models, perform an **oracle error decomposition** on a blind slice containing unresolved failures plus randomly selected successes. Independently substitute reviewed-perfect (1) OCR tokens, (2) row/cell geometry, and (3) semantic ownership, running the remaining real pipeline after each substitution. This reveals whether OCR, structure, or semantics is actually limiting correctness. If perfect geometry barely helps, a table model is the wrong investment.

### Stage B — red-team the independent verifier

Mutation-test candidates that are plausible and sometimes still reconcile:

- offsetting missing/duplicated rows;
- swapped billed/original amounts or currencies;
- merchant/detail contamination;
- wrong inferred year;
- compensating sign changes;
- unowned high-salience atoms;
- projected/informational rows represented as posted transactions.

Do not add a generative proposal stream while any such mutation is accepted. A generator increases the verifier's attack surface.

### Stage C — run an off-core shadow bake-off

Without first adding a production abstraction, compare the accepted control, one Hebrew-capable OCR alternative/ensemble, one learned table/row system, and one pinned local VLM proposal route plus the hardened verifier. A direct-VLM result may be recorded as a deliberately lower-safety diagnostic baseline. Only after a proposal route wins should two concrete adapters justify a narrow production seam.

### Stage D — OCR shadow test

Run current Tesseract, `tessdata_best`, and at most one alternative local recognizer on the same preselected crops. Measure exact character match and bounding-box fidelity separately for Hebrew, Latin, digits, dates, decimal punctuation, currency symbols, and mixed-direction strings. Then run the whole parser in shadow mode; a recognizer wins only if strict document acceptance improves without new unsafe accepts.

### Stage E — table/row proposal sidecar

Prototype a TATR/TabSniper-style small model or comparable row detector whose typed interface is limited to:

```text
PageTableProposal {
  page_box,
  header_box,
  row_boxes[],
  column_boundaries[],
  continuation_links[],
  proposal_evidence,
  model_revision
}
```

Do not allow the model to emit transaction values. The parser reads characters from existing positioned tokens and can compare learned versus deterministic row hypotheses. Measure recall first: missing a row is usually costlier than offering an extra hypothesis that later evidence rejects.

### Stage F — grounded semantic sidecar

Train or prompt a small layout-aware model on token IDs/text plus boxes. It may classify or link evidence but must return token references. LMDX is the relevant conceptual precedent; LiLT/DocLLM show that useful layout modeling need not regenerate the page image. Evaluate on held-out institutions/templates and Hebrew/RTL slices.

### Stage G — local VLM fallback

Only after the oracle/verifier work and narrower OCR/layout/semantic experiments, test a local model such as Qwen2.5-VL or a specialist parser on rejected scan/capture cases. Use table/region crops, deterministic decoding where possible, JSON grammar constraints, and a proposal-only output. Require exact value-to-source alignment, row-count/topology checks, semantic evidence, `Decimal` reconciliation, and calibrated acceptance. Any value that cannot be grounded is an ambiguity, never a guessed transaction.

### Stage H — efficient private labeling

Use Selective Labeling-style yes/no review for candidate associations and QUEST-style error taxonomy to prioritize cases, but periodically fully annotate random documents. FieldSwap-like augmentation is appropriate only for field/header classification after domain rules verify the synthetic example. Keep generated training data separate from gold evaluation and the protected acceptance inventory.

### Promotion rule

Pre-register the decision rule before seeing results. A sidecar should be promoted only if it improves strict document-level safe coverage on source/template/time-held-out private data, introduces no accepted-output regression in the frozen evaluated set, preserves complete grounding and deterministic repeatability, stays within local privacy constraints, and passes the repository's full tracked and private gates. Report sample uncertainty: observing no errors in a small test set is not proof of zero production risk. A higher public TEDS, OCRBench, or OmniDocBench score is insufficient.

## Claim discipline and overall conclusion

There is no defensible universal “best OCR/document model” for this repository as of 2026-07-27. Results are conditional on task, benchmark version, language, input quality, normalization, model access, and whether the authors evaluate their own model on a benchmark they created. In particular:

- a table score does not measure transaction semantics;
- a financial-report result does not imply bank-statement accuracy;
- a multilingual result does not imply Hebrew or bidi-layout support;
- valid JSON does not imply source fidelity;
- arithmetic validity does not imply complete/correct extraction;
- a local model does not imply deterministic or private operation by default;
- a preprint/model-team leaderboard is promising evidence, not independent production validation.

The current evidence favors the repository's conservative architecture. The highest-value modernization is not an end-to-end generative rewrite; it is a set of small, replaceable learned proposal modules around a deterministic evidence and reconciliation core. TabSniper and WACV 2026 support that cascade at the table level; the IJDAR neurosymbolic paper supports source/domain filtering with explicit rejection; FinBalance supports deterministic replay over model self-consistency; QUEST supports structural quality features over raw confidence. Their limitations also dictate the safety contract: preserve exact source data, evaluate Hebrew/RTL privately, measure document-level risk and coverage, and let the system abstain.

## Dated primary-source table

Links below point to publisher/proceedings pages, official repositories/model cards, or author manuscripts. “Preprint” means the cited result was not archival as of 2026-07-27, even if its components or earlier versions were published elsewhere.

| Date / status | Primary source | Decision-relevant evidence | Main limitation here |
|---|---|---|---|
| 2020, KDD archival | [LayoutLM](https://www.microsoft.com/en-us/research/publication/layoutlm-pre-training-of-text-and-layout-for-document-image-understanding/) | Joint text/layout pretraining | OCR/token dependent; not Hebrew statements |
| 2021, ACL archival | [LayoutLMv2](https://aclanthology.org/2021.acl-long.201/) | Adds visual and spatial-aware pretraining | Form/receipt benchmarks, not ledger completeness |
| 2021, WACV archival | [GTE / FinTabNet](https://arxiv.org/abs/2005.00589) | Financial-report table detection and cell structure | Financial reports, not bank statements |
| 2021, EMNLP archival | [PICARD](https://aclanthology.org/2021.emnlp-main.779/) | Incremental constrained decoding | SQL syntax result; semantics still external |
| 2021, ACL archival | [TAT-QA](https://aclanthology.org/2021.acl-long.254/) | Symbolic arithmetic over finance tables/text | Prepared report evidence, not extraction |
| 2021, EMNLP archival | [FinQA](https://aclanthology.org/2021.emnlp-main.300/) | Executable finance-reasoning programs | Prepared reports, not raw statements |
| 2022, CVPR archival | [PubTables-1M / Table Transformer](https://openaccess.thecvf.com/content/CVPR2022/papers/Smock_PubTables-1M_Towards_Comprehensive_Table_Extraction_From_Unstructured_Documents_CVPR_2022_paper.pdf) | Large canonicalized table-structure data | Scientific articles |
| 2022, CVPR archival | [TableFormer](https://openaccess.thecvf.com/content/CVPR2022/papers/Nassar_TableFormer_Table_Structure_Understanding_With_Transformers_CVPR_2022_paper.pdf) | Joint structure and cell-box decoding | General table metrics only |
| 2022, ACL archival | [LiLT](https://aclanthology.org/2022.acl-long.534/) | Language-independent layout module concept | Evaluation languages exclude Hebrew |
| 2022, ECCV archival | [Donut](https://mlanthology.org/eccv/2022/kim2022eccv-ocrfree/) | OCR-free image-to-structured sequence | Generative fidelity and domain transfer unproven |
| 2022, KDD archival | [DocLayNet](https://doi.org/10.1145/3534678.3539043) | Diverse layout data expose academic-domain shift | Layout only |
| 2022, ACM MM archival | [LayoutLMv3](https://doi.org/10.1145/3503161.3548112) | Unified text/image masking | OCR boxes still used for IE |
| 2023, ICML archival | [Pix2Struct](https://proceedings.mlr.press/v202/lee23g.html) | OCR-free screenshot-to-markup pretraining | Web/document tasks, not exact finance |
| 2023, ICDAR archival | [DocILE](https://arxiv.org/abs/2302.05658) | Seen/zero-/few-shot layouts and line items | Invoice/PO classes, not statements |
| 2023, EMNLP archival | [Selective Labeling](https://aclanthology.org/2023.emnlp-main.233/) | Candidate confirmation plus active learning reduces label cost | Candidate bias can hide omissions |
| 2023, COMPSAC archival | [Calibrated failure prediction for document IE](https://researchportal.helsinki.fi/en/publications/failure-prediction-in-2d-document-information-extraction-with-cal/) | Calibration improves safe automation coverage in production invoices | Deployment-specific values |
| 2024, ACL archival | [DocLLM](https://aclanthology.org/2024.acl-long.463/) | Generative layout reasoning without image encoder | General DU benchmarks, not Hebrew |
| 2024, Findings ACL archival | [LMDX](https://aclanthology.org/2024.findings-acl.899/) | OCR-layout prompts with output localization | Proprietary models and adjacent datasets |
| 2024, ICDE archival | [FieldSwap](https://research.google/pubs/fieldswap-data-augmentation-for-effective-form-like-document-extraction/) | Low-data field augmentation | Does not preserve row/arithmetic semantics by itself |
| 2024, CODS-COMAD paper | [TabSniper](https://arxiv.org/abs/2412.12827) | Bank-specific hybrid pipeline, row logic, checksum | Private BankTabNet; no public independent bank evaluation |
| 2024, ICLR archival | [Conformal Risk Control](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html) | Expected-risk control under stated assumptions | Exchangeability/shift assumptions must be audited |
| 2024, NeurIPS archival | [Grammar-Aligned Decoding](https://proceedings.neurips.cc/paper_files/paper/2024/hash/2bdc2267c3d7d01523e2e17ac0a754f3-Abstract-Conference.html) | Hard grammar can distort generation | Not document-specific; cautionary mechanism |
| 2025, Findings ACL archival | [READoc](https://aclanthology.org/2025.findings-acl.1128/) | Whole-document comparison across pipelines, specialists, VLMs | Automatically constructed, nonfinancial ground truth |
| 2025, CVPR archival | [OmniDocBench](https://openaccess.thecvf.com/content/CVPR2025/html/Ouyang_OmniDocBench_Benchmarking_Diverse_PDF_Document_Parsing_with_Comprehensive_Annotations_CVPR_2025_paper.html) | Comprehensive parsing/error dimensions | EN/ZH/mixed; no typed statement semantics |
| 2025, ICDAR archival | [QUEST](https://doi.org/10.1007/978-3-032-04630-7_16) | Quality features beat raw confidence for pseudo-label selection | Single simple tables; domain-trained assessor |
| 2025, IJDAR archival | [Neurosymbolic transactional IE](https://doi.org/10.1007/s10032-025-00530-0) | Source-presence and arithmetic filters improve retained candidates | Large coverage loss; receipts/invoices; validity ≠ correctness |
| 2025-09, preprint | [MinerU2.5](https://arxiv.org/abs/2509.22186) | Efficient coarse-to-fine region parsing | Model-team benchmarks; no Hebrew/ledger task |
| 2025-10, preprint | [PaddleOCR-VL](https://arxiv.org/abs/2510.14528) | Compact multilingual page parser | Self-reported and adjacent task |
| 2026-01, preprint | [PaddleOCR-VL-1.5](https://arxiv.org/abs/2601.21957) | 0.9B parsing model and Real5 robustness work | Hebrew absent from published language list; v1.5 protocol |
| 2026-03, preprint | [Real5-OmniDocBench](https://arxiv.org/abs/2603.04205) | Controlled scan/warp/photo/lighting/skew stress | Paddle-team benchmark; inherits adjacent OmniDocBench task |
| 2026-03, WACV archival | [Zero-Shot Table Extraction in Business Documents](https://openaccess.thecvf.com/content/WACV2026/html/Thomas_Zero-Shot_Table_Extraction_in_Business_Documents_A_Unified_Benchmark_with_WACV_2026_paper.html) | Directly recommends small detector + VLM cascade | English, one page/table, ground-truth TSR crop, cloud VLMs |
| 2026, CVPR archival | [PP-OCRv5](https://openaccess.thecvf.com/content/CVPR2026/papers/Cui_PP-OCRv5_A_Specialized_5M-Parameter_Model_Rivaling_Billion-Parameter_Vision-Language_Models_on_CVPR_2026_paper.pdf) | Small specialist OCR remains competitive | No Hebrew statement result |
| 2026-05, preprint | [MPDocBench-Parse](https://arxiv.org/abs/2605.22100) | Tests cross-page continuity/merging | EN/ZH and generic parsing |
| 2026-06, preprint | [PaddleOCR-VL-1.6](https://arxiv.org/abs/2606.03264) | Newer compact local parser; v1.6 benchmark results | Self-reported, no Hebrew statement evidence |
| 2026-06, preprint | [PP-OCRv6](https://arxiv.org/abs/2606.13108) | 1.5M–34.5M specialist OCR; in-house comparison to large VLMs | In-house benchmarks; language list excludes Hebrew |
| 2026-06, preprint | [FinBalance](https://arxiv.org/abs/2606.15949) | Deterministic ledger replay exposes/fixes aggregation inconsistency | Synthetic clean OCR text; not visual extraction |
