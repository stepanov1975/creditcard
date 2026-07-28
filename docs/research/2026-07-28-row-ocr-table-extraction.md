# Fixed-row OCR and transaction-field extraction

**Research date:** 2026-07-28
**Code baseline:** `dee4b071ad65231da13825f2f7c74a488ca96c7c`
**Scope:** recognition and field extraction from transaction rows whose detection is held fixed. No private documents, outputs, caches, or financial values were inspected.

## Recommendation

Start with a staged Tesseract ablation on already-detected row crops. The highest-value variables are page-segmentation mode (`7` and `13` versus current `6`), a small white border, 300 versus 400/450 DPI, language order, and Tesseract 5's built-in thresholding. Keep the accepted row boxes fixed; first keep column bands fixed too, then separately measure whether new word boxes improve or damage column ownership. This is the smallest experiment that fits the present architecture, preserves local processing, and can return the word boxes required by downstream geometry.

Do **not** begin with a table-structure model. TabSniper, Table Transformer, and PP-Structure primarily improve table/row/column detection, which this evaluation deliberately freezes. A neural OCR comparator is worthwhile only after the Tesseract matrix; Surya 2 is the most credible Hebrew-capable comparator found, but its 650M-parameter generative model, inference server, block-level HTML output, model-weight license, and determinism burden make it a poor first production candidate.

## What the accepted implementation implies

- `src/ccparser/evidence/pdf.py` invokes ordinary OCR only when page-level digital extraction is judged poor, and invokes it for the **whole page**. The only current crop OCR route is the separate isolated-currency-glyph path.
- `src/ccparser/evidence/ocr.py` already accepts an arbitrary PDF `clip`, renders it with PyMuPDF at 300 DPI and `alpha=False`, records the pixmap origin, parses TSV word boxes back into display points, and content-addresses recognition. This makes it a sound renderer/coordinate foundation for an experiment; the missing seam is a post-row-detection caller.
- The current primary pass is `heb+eng --oem 1 --psm 6`; an English PSM 6 pass and a whitelisted numeric PSM 6 pass can replace only strongly overlapping, demonstrably stronger numeric tokens. That conservative fusion policy should remain the baseline safety contract.
- `src/ccparser/layout/rows.py` deduplicates words, clusters physical lines by y/height, groups words into cells by height-relative x gaps, and orders cells using a dominant-direction heuristic. Re-running this step with new words would change row detection, so the experiment must instead assign recognized words to frozen row identities.
- `src/ccparser/layout/columns.py` assigns cells to columns by x center and also infers repeated x bands from cell geometry. Recognition is therefore not “text only”: a shifted or merged OCR box can change field ownership even if its transcription improves.

The clean isolation is consequently two-level:

1. **Recognition-only:** fixed row boxes and fixed accepted column bands; associate each returned word to a field by its center.
2. **Recognition-plus-cell-geometry:** fixed row boxes, but rebuild cells/column association inside each frozen row. This shows whether word geometry transfers safely without allowing row count or row boundaries to move.

## Primary-source findings

### Tesseract crop configuration is the actionable path

Tesseract's official quality guide says it works best at at least 300 DPI, performs Otsu binarization internally, and in version 5 added Adaptive Otsu and Sauvola options. It also warns that tightly cropped text may fail without a small border, while an excessively large border can produce an “empty page” result. For small regions it explicitly recommends selecting a suitable PSM: `7` is a single text line and `13` is a raw line, whereas the current `6` assumes a uniform text block ([quality guide](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)). A frozen physical transaction row is therefore much closer to PSM 7/13's declared input contract than to PSM 6.

The same guide warns that Tesseract has difficulty extracting tables without custom segmentation/layout analysis and suggests disabling dictionary DAWGs for receipts, price lists, or codes when normal sentence priors are harmful. Here the table segmentation already exists, so the useful transfer is crop recognition—not Tesseract table recovery. Dictionary disabling should be a late, field-specific test because it may help dates/amounts while harming Hebrew merchant descriptions.

Tesseract supports `LANG1+LANG2`, but its official examples show that language order can change both output and runtime ([command-line guide](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)). Test `heb+eng` against `eng+heb`; do not assume they are interchangeable. Official model sets also encode a real speed/accuracy tradeoff: `tessdata_best` is slower and float-based, `tessdata_fast` is fastest, and `tessdata` uses integerized LSTM models while retaining legacy data ([data-files guide](https://tesseract-ocr.github.io/tessdoc/Data-Files.html)). Any comparison must pin and hash `heb.traineddata` and `eng.traineddata`, not only the Tesseract executable version.

PyMuPDF's documented `Page.get_pixmap(dpi=..., clip=..., alpha=False)` behavior matches the accepted renderer: `clip` restricts rendering, `dpi` selects resolution, and `alpha=False` pre-clears empty space white while saving memory ([PyMuPDF `Page.get_pixmap`](https://pymupdf.readthedocs.io/en/latest/page.html#Page.get_pixmap)). Expanding a PDF clip maps naturally through the existing pixmap origin. Adding a synthetic raster border instead requires subtracting the border width, scaled by `72 / dpi`, when mapping TSV pixels back to page points.

### RTL and bilingual rows need logical-text and geometry tests

Unicode stores bidirectional text in logical order; only presentation is reordered. Digits are weak-direction characters within an RTL context, so a mixed Hebrew/Latin/date/amount string cannot be validated by how a terminal happens to display it ([Unicode Bidirectional Algorithm, UAX #9](https://www.unicode.org/reports/tr9/)). Compare normalized code-point sequences and field values, then test display separately.

This matters directly to `layout/rows.py`: its direction decision is coarse at the group and row level, while a transaction row can contain an RTL description, LTR Latin merchant tokens, LTR digits, neutral punctuation, and currency symbols. The evaluation set must include these combinations and preserve NFC normalization and format-character handling. Language-order ablations must also report token boxes, not just concatenated rendered strings.

### Bank-statement research supports geometry-first assignment, but mostly changes row detection

TabSniper is directly bank-statement-specific. It describes long, dense, multi-line transaction tables; detects row and column objects; forms cells by row/column intersection; and assigns OCR words to cells by coordinate overlap. It also uses balance checks after extraction and splits long tables before structure recognition ([TabSniper paper](https://arxiv.org/abs/2412.12827)). Those observations support this repository's geometry and reconciliation approach. They do **not** establish that TabSniper will improve recognition with rows held fixed: its principal contribution is specialized table detection/structure recognition, BankTabNet is not published as a ready local model in the paper, and its reported failure case includes tilted scans.

Microsoft's official Table Transformer repository makes the same separation explicit: TATR is an object detector and needs OCR or PDF text as a separate input to produce text-bearing HTML/CSV. Its public structure weights are 110 MB and are trained on PubTables-1M and/or FinTabNet, not bank statements or Hebrew ([Table Transformer repository](https://github.com/microsoft/table-transformer)). It becomes relevant only if a later evaluation is allowed to change column/cell structure.

Paddle's table pipeline likewise combines three models—text detection, text recognition, and SLANet cell/structure prediction—and its published table models are Chinese/English ([PP-Structure table pipeline](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/README.md)). PP-OCRv5 has compact multilingual recognition models, but the official supported-language/model table omits Hebrew; its Arabic and Latin models are separate, so it does not supply one pretrained Hebrew+Latin row recognizer ([PP-OCRv5 multilingual models](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md)). This is a hard transfer limit for the present corpus, not a tuning detail.

A 2026 Malaysian bank-statement study evaluates date, description, debit, credit, and balance per column with exact and normalized-edit-distance measures. It reports that general vision models struggle with multi-line descriptions, inconsistent dates, and merged cells, while its fastest/strongest approach exploits standardized per-bank templates ([AI-BAAM](https://arxiv.org/html/2510.16066v4)). The field-wise metrics transfer; the template-specific solution does not. Issuer/template branches are explicitly disallowed by this repository, and the paper's six Malaysian banks do not establish Hebrew or Israeli-card-statement generalization.

### Neural recognizers are bounded comparators

- **Surya 2:** the official repository reports a 650M-parameter document VLM, a 91-language benchmark including Hebrew, local `vllm` or `llama.cpp` backends, full-page or per-block OCR, and block HTML/bboxes rather than TSV word boxes ([repository and runtime](https://github.com/datalab-to/surya), [language results](https://github.com/datalab-to/surya/blob/master/static/docs/multilingual.md)). Use it only as a fixed **cell-crop text** comparator unless an adapter can supply auditable word geometry. Code is Apache-2.0, but model weights have a modified license with commercial thresholds.
- **docTR:** its current API cleanly separates word detection from recognition and can transcribe pre-cropped word images ([model-selection docs](https://mindee.github.io/doctr/latest/using_doctr/using_models.html)). Recent releases add Hebrew vocabulary definitions, but a vocabulary definition is not evidence that the default pretrained checkpoint learned Hebrew bank text. A valid comparator would need a pinned Hebrew-capable checkpoint and documented evaluation, plus PyTorch.
- **EasyOCR:** its useful `recognize` API treats the whole image as one box when no boxes are provided, but the official supported-language list still omits Hebrew ([API](https://www.jaided.ai/easyocr/documentation/), [supported languages](https://jaided.ai/easyocr/)). Do not spend an experiment slot on its stock models.
- **TrOCR/PARSeq:** these are genuine cropped-line/word recognizers, but official public checkpoints are English receipt/scene-text oriented. TrOCR ranges from 62M to 558M parameters and returns a transcription, not the word boxes needed here ([official TrOCR repository](https://github.com/microsoft/unilm/tree/master/trocr)); PARSeq's reference pretrained charsets are 36/62/94-character Latin sets ([official PARSeq repository](https://github.com/baudm/parseq)). Neither is a stock Hebrew+Latin replacement.

## Concrete experiment matrix

Run stages sequentially and carry forward only winners; do not evaluate the full Cartesian product.

| Stage | Fixed inputs | Variable and levels | Primary question / stop rule |
|---|---|---|---|
| 0. Baseline capture | Accepted row IDs, row bboxes, schema/column bands, source/render SHA, accepted three-pass words | Current full-page 300-DPI PSM 6 output | Establish raw/normalized field values, TSV hashes, runtime/RSS/cache bytes. No row may be added, dropped, merged, or split later. |
| 1. Crop contract | Same rows and columns; 300 DPI; `heb+eng`; raw RGB | PSM `6`, `7`, `13`; white border `0`, `5`, `10` px | Find a line-mode/padding pair that improves field exactness without increasing missing or cross-column words. The 10 px level comes from Tesseract guidance; it is a test point, not a constant to hard-code. |
| 2. Language order | Best stage-1 crop; same packs and model revision | `heb+eng`, `eng+heb`; keep English-only supplemental | Measure Hebrew, Latin merchant, numeric, and runtime effects independently. Reject an order that improves aggregate text while regressing exact amounts/dates. |
| 3. Scale | Best prior configuration | 300, 400, 450 DPI | Determine whether small glyphs benefit beyond the already recommended 300 DPI. Stop if the higher setting has no stratified exact-field gain or breaches time/RSS/cache limits. |
| 4. Binarization | Best prior configuration | Existing raw/internal Otsu; pinned Tesseract Adaptive Otsu; pinned Sauvola | Test uneven/noisy scans without adding OpenCV. Record every `thresholding_*` parameter emitted by the exact binary; never rely on defaults across versions. |
| 5. Field-targeted crops | Frozen row and accepted column intersections | Date/amount cells: English PSM `7` and `13`, existing numeric whitelist; descriptions stay bilingual | Test whether isolation repairs numerics without allowing an OCR candidate to invent, truncate, or move a value. Fuse only on strong geometry plus strictly stronger syntactic evidence, matching the accepted conservative policy. |
| 6. Traineddata | Winning Tesseract config | Accepted pinned packs versus pinned `tessdata_best` `heb`+`eng` | Buy accuracy only if field-level gain survives repeated runs and the latency/RSS/cache cost is acceptable. Model files must be SHA-256 pinned. |
| 7. Neural audit | Small, stratified fixed-cell set; no production integration | Surya 2 greedy/temperature-zero on CPU or one pinned GPU backend | Estimate the ceiling on Hebrew descriptions. Reject as an integration candidate if output cannot be mapped to auditable fixed fields, repeated bytes differ, or footprint/latency dominates the gain. |

Each stage should report:

- raw exact match and NFC-normalized edit distance per field role;
- exact normalized date, exact `Decimal` amount, sign/currency preservation, and parse-failure rate;
- whole-transaction exact match and reconciliation outcome, without using reconciliation to hide a wrong field;
- missing/extra tokens, duplicated tokens, and words whose centers leave their accepted column;
- row-bbox identity (must be byte-for-byte unchanged), word-box drift/overlap, and the recognition-only versus rebuilt-cell results;
- wall time, OCR subprocess count, peak RSS, rendered-image bytes, cache bytes, and cold/warm behavior;
- two independent empty-cache runs whose raw TSV/model outputs and canonical extracted outputs are byte-identical.

Stratify at least by OCR-only versus digital-plus-OCR evidence, physical single-line versus logical multi-line transaction, Hebrew-only versus mixed-script description, low-confidence numeric/date evidence, and scan quality. Use tracked synthetic/public fixtures for development. A later private-corpus run must follow the repository's protected gate; this note makes no corpus-acceptance claim.

## Dependencies and footprint

| Candidate | Incremental dependency / artifact | Expected footprint and integration cost |
|---|---|---|
| Tesseract PSM/language/threshold changes | None beyond the existing binary and packs | Lowest. More expensive operationally: three passes per row would turn 3 page calls into roughly `3 × row_count` calls, so batch only after demonstrating value. |
| Synthetic white border | Prefer a tiny, deterministic image operation; Pillow if a new library is accepted | Small package cost, but coordinate offsets and encoded bytes must enter the cache key. Expanding the PDF clip avoids a dependency but includes neighboring content rather than guaranteed white space. |
| `tessdata_best` | Two additional pinned traineddata files | Modest disk/RAM, potentially material CPU latency; official docs call it the slowest model set. |
| OpenCV preprocessing | `opencv-python-headless` plus NumPy | Tens of MB and a larger native/reproducibility surface. Defer until built-in thresholding fails. Deskewing also requires inverse box transforms. |
| docTR | `python-doctr`, PyTorch, model weights | Hundreds of MB runtime/weights depending on models; Hebrew checkpoint validation or training required. |
| Surya 2 | `surya-ocr`, ~650M-param weights, `vllm` + Docker/NVIDIA toolkit or `llama.cpp` | GB-class artifact/runtime, server lifecycle, generative adapter, and model-license review. |
| Table Transformer | PyTorch/Torchvision/Conda environment, 110 MB structure weights, separate OCR | Solves an excluded problem and adds geometry post-processing; no initial experiment. |
| PaddleOCR/PP-Structure | `paddleocr`, a chosen inference backend, optional `doc-parser` group and multiple models | Clean environment is recommended by its docs for backend conflicts; stock Hebrew support is absent. |

## Determinism and acceptance risks

- **Cache identity:** include source SHA, page, exact unclamped/clamped clip, DPI, pixel padding, preprocessing parameters/version, full command, language order, Tesseract and Leptonica versions, traineddata SHA-256 values, and fusion version. Neural experiments also need repository commit, weight SHA, tokenizer, backend/container digest, device, dtype, decode parameters, and batch/worker count.
- **Pixel rounding:** specify one rule for point-to-pixel expansion and page-bound clamping. Padding before versus after rasterization is not equivalent. Map synthetic-border boxes back by removing the exact integer pixel offset before multiplying by `72 / dpi`.
- **Concurrency:** keep subprocess/model worker count fixed and test repeated empty-cache runs. Per-row concurrency changes memory pressure and may expose non-atomic cache assumptions even when individual recognition is stable.
- **Neural backends:** PyTorch explicitly does not guarantee identical results across releases, platforms, or CPU/GPU even with identical seeds; deterministic algorithms can also reduce performance ([PyTorch reproducibility notes](https://docs.pytorch.org/docs/stable/notes/randomness)). Treat any Torch/VLM candidate as a new toolchain identity and require byte-level repeat evidence on the exact acceptance host.
- **RTL:** retain logical Unicode strings and geometry separately. Strip or preserve bidi format characters only under an explicit normalization contract; never reverse an entire Hebrew-containing field or numeric token as a display workaround.
- **False confidence:** OCR confidence scores are engine-specific and not calibrated financial correctness. Amount/date syntax, box overlap, column ownership, and reconciliation are corroboration; none alone authorizes replacement.

Any production change that follows this research affects OCR/extraction/output behavior. It therefore needs focused red-green tests, all tracked gates, a clean committed candidate, and the full independently pinned private `verify` gate before corpus acceptance. No model, padding, date, amount, merchant, or issuer-specific exception should be introduced to make individual documents pass.

## Transfer limits

1. Frozen rows cannot recover a completely missed transaction or repair wrong row boundaries. Results measure recognition/field extraction conditional on accepted row detection.
2. Rows derived from baseline OCR create survivorship bias: the hardest rows may be absent. Report this explicitly rather than interpreting conditional accuracy as end-to-end recall.
3. A physical OCR line is not always a logical transaction. Multi-line description attachment remains a downstream semantic problem and is outside this experiment unless its row identity is already fixed.
4. Public table benchmarks are largely English scientific/financial tables; TabSniper and AI-BAAM use different bank domains. None proves transfer to bilingual Hebrew credit-card statements.
5. Cloud bank-statement parsers are not candidates: for example, Azure's `prebuilt-bankStatement.us` sends documents to an API and is explicitly US-specific ([official model documentation](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/bank-statement)). This repository requires document contents and derived financial data to remain local.
6. High template-specific results do not justify issuer/path branches. Only general crop, recognition, geometry, semantic, and reconciliation rules transfer to this repository.
