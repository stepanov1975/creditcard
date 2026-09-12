# Golden dataset assessment and research

**Assessment date:** 2026-09-12. Public primary literature was searched through this
date. Methods and limitations were inspected, not only abstracts. No private
document content was submitted to external services. Recommendations are untested;
this note does not restart the stopped extraction program.

```text
Scope answer: YES — supports analysis of the already measured supervision/merchant-definition errors that prevent comparison of extraction methods
Experiment: shared evaluation
Extraction hypothesis: The recorded failures are partly label-policy and context-construction problems rather than evidence that merchant extraction cannot improve
Measurement: existing predeclared field-presence, canonical-value, source-region and context-truncation error categories; no new extraction scores
Fixed inputs: committed aggregate pilot/context reports plus public primary literature; private labels and validation/held-out data remain closed
Smallest allowed files: docs/research/2026-09-12-golden-dataset-assessment.md
Required output: a cited interpretation of the quantified existing error categories and clearly marked untested recommendations
Stop condition: stop after this assessment; no labels, artifacts, code, support subsystem, authority changes, or experimental execution
```

## Assessment of the work already completed

**Recommendation:** establish a small, independently reviewed merchant reference
from source pages before expanding labeling or resuming extractor comparisons.
The user confirmed during this assessment that they can review a small seed set.
The practical bottleneck is defining and verifying the target, then ensuring its
source evidence is available. The existing reports do not establish an accuracy
ceiling for merchant extraction.

This assessment reads committed reports, protocols, and relevant implementation;
it does not reopen the private labels or independently repeat their source audit.
The latest code and documentation commits do not reactivate the research program.
The [live program record](../experiments/row-extraction-program-status.md) remains
the authority, even where older design-status banners describe approval stages
that predate the committed amendments and completed attempts.

| Recorded work | What it establishes | What it does not establish |
| --- | --- | --- |
| Four Round 1 arms frozen; no exact validation matches under their respective dispositions | The frozen comparison failed to demonstrate a usable extraction gain | That all four methods are inherently incapable, or that every extracted field was wrong |
| Visual-gold v2: 100 training rows, 100% annotation validity, 98/100 row-type matches | The records conformed to the annotation contract; row-type decisions were mostly consistent | Source correctness of the field values |
| Field exact agreement: 386/473; therefore 87/473 disagreements, or 18.39% | Substantial disagreement in the union of asserted field roles | 81.61% extraction accuracy, merchant accuracy, or the error rate of either reviewer |
| 57 rows with disagreement records; categories include 36 field-presence and 26 canonical-value disagreements | Semantic disagreement requires investigation as well as geometric disagreement | Independent counts that can be summed; categories overlap |
| Follow-up design records 42 description differences and agreement on core financial roles | The recorded diagnosis points to broad description versus narrower merchant/ancillary policy | A source-verified verdict that either reviewer's merchant choice was correct |
| Merchant context eligibility: 17/100; 83/100 unavailable | The prescribed six-context materialization could not run on the selected inputs | That merchants on those 83 anchors are unreadable or unlabelable from the source page |

Counts come from the [visual pilot report](../experiments/row-extraction-visual-gold-v2-pilot-report.md),
the [merchant context design](../superpowers/specs/2026-08-07-merchant-context-sufficiency-design.md),
and the [context failure report](../experiments/row-extraction-merchant-context-report.md).
The disagreement percentage above was recomputed using Python 3.13 and `Decimal`
from the published aggregate integers only.

Several choices were sound and should be retained: document-disjoint splits,
source evidence for labels, separate candidate and accepted gold, source review
that hides parser predictions, explicit uncertainty, and preservation of failed
results. Stopping the historical pilot at its declared gate was correct under its
protocol. The follow-up's transaction-level merchant definition was a useful
conceptual improvement. Its independent reference, however, was never created.
Existing accepted gold still exists; the replacement candidate was not completed
or promoted, and its defect rate was not measured.

Four design limitations explain why repeating the same attempt is unlikely to
be the best use of effort:

1. **The target mixed description with merchant identity.** The frozen
   [field vocabulary](../../experiments/row_extraction/contracts.py) has
   `description` and `ancillary`, but no merchant field. The pilot employed
   learned visual reviewers in separate contexts, not two independent human
   experts. Agreement between those contexts measures consistency, not source
   truth. The later merchant-specific contract addresses this distinction;
   we should carry its operational definition forward.
2. **The reference inherited limitations of the extractor inputs.** The
   [handbook](../experiments/row-extraction-annotation-handbook.md) requires
   same-row evidence, fixed continuation adjacency, and largely nonoverlapping
   support. These rules are useful for a frozen-row comparison but cannot fully
   describe a merchant reference independently of faulty row segmentation. A
   full-page reference may need multiple regions or ownership beyond a crop.
   Sampling only detected rows also cannot reveal transactions missed entirely
   by row detection.
3. **One uncertain field erases all clear fields under the old contract.** The
   handbook makes an ambiguous row fieldless. That prevents separate assessment
   of an exact amount and an uncertain merchant. This is a representational
   limitation; no aggregate here quantifies how many labels it affected.
4. **Reference creation was coupled to an unproven context experiment.** In
   [`_context_materials`](../../experiments/row_extraction/merchant_context.py),
   the C4 region is the union of frozen column-schema boxes. C4 must also contain
   C2/C3 regions and their rows/atoms. Reported C4 failures were 79 visibility,
   4 missing-neighborhood, and 38 nesting failures, overlapping to 83 anchors.
   Other tiers, including the full page, had zero reported visibility failures.
   That makes detector-derived C4 geometry the immediate blocker in the report;
   it does not prove a full-page reference run would succeed. Simply padding C4
   or dropping it would change the frozen experiment and is not authorized.

Exact source-region agreement was diagnostic, not the failed semantic gate.
Relaxing box comparison alone would therefore not have made this pilot pass.
The 100-row pilot was deliberately stratified, including 50 primary and 48
continuation rows; it is not a random sample of 100 independent transactions.

## Evidence from recent annotation research

### ReceiptBench: separate capabilities and inspect every field

Wang et al., ACL **July 2026**, first preprint **May 21, 2026**, distinguish
perception, normalization, semantic reasoning, and structure. Their annotation
process uses ten batches, expert sampling, format/consistency checks, and revision
of an entire batch when any inspected field falls below its acceptance threshold.
This is more informative than one agreement average across unlike fields.

**Limit:** The data is 98% English, and the authors' reported annotation accuracy
is their audit result, not an independent audit of our task. Their semantic LLM
judge, equivalence of zero and empty values, and floating-point monetary tolerances
should not be copied into exact, source-grounded merchant/financial scoring.
[Publication](https://aclanthology.org/2026.acl-long.2135/),
[inspected methods, §§3.1–3.4](https://arxiv.org/html/2605.22413v1).

### Human review of model suggestions can still contaminate gold

Schroeder, Roy, and Kabbara, ACL Findings **July 2025**, ran a preregistered study
with 350 annotators and 7,000 annotations. Unassisted annotation was compared with
three presentations of LLM suggestions. Exposure changed the label distribution
toward the model and increased its apparent evaluated performance; assistance did
not make annotators faster. Their methods explicitly retained an unassisted control.

**Limit:** These were subjective English conversation labels, not visible merchant
text. The study supports preserving an independent reference subset; it does not
quantify anchoring for Hebrew experts or establish that all assisted transcription
is unreliable. [Paper, §§4–5 and §8](https://aclanthology.org/2025.findings-acl.1323.pdf).

### Guideline repair helps only some disagreement causes

Bibal et al., CoMeDi **January 2025**, iteratively generated improved entity
annotation guidelines and tested them with eight staff annotators. The revealing
result is Table 1: all-entity Fleiss' kappa improved only **0.488 → 0.499**. The
abstract's **0.593 → 0.840** improvement applies after excluding ambiguity,
knowledge, and attention problems, leaving **11 of 39 entities**.

**Limit:** A small WNUT-17 case study. It motivates separating unclear policy,
insufficient evidence, lack of expertise, and mistakes. It does not justify
silently removing difficult cases or expecting rubric changes alone to solve
extraction. [Paper, §4.3.1 and Table 1](https://aclanthology.org/2025.comedi-1.13.pdf).

### Agreement depends on the question annotators are asked

Dsouza and Kovatchev, CoMeDi **January 2025**, annotated 720 paired-response
instances under individual-rating and preference tasks, using the same human
annotators across formulations. Overall agreement was comparable, but individual
labels and the cases producing disagreement differed. Combining the annotations
did not reliably resolve ambiguity.

**Limit:** Instructions deliberately left response quality open to interpretation;
this was RLHF preference annotation, not OCR. The relevant inference is that
agreement cannot establish whether two reviewers used the intended merchant
definition. [Paper, §§3–4](https://aclanthology.org/2025.comedi-1.3.pdf).

### olmOCR: check concrete properties instead of one serialization

Poznanski, Soldaini, and Lo, **October 22, 2025**, describe evaluation through
checks for text presence/absence, reading order, and table-cell relationships.
Equivalent document representations can pass the same checks even when edit
distance differs. The original benchmark checks were manually verified. Their
synthetic training method renders generated HTML and derives labels from that
same HTML, giving exact truth for the generated image.

**Limit:** English document linearization; a finite set of checks can miss other
errors. Synthetic source truth validates the synthetic document, not fidelity to
the original real document. Neither replaces complete merchant references.
[Paper, §§2–3](https://arxiv.org/html/2510.19817v1).

### MinerU2.5-Pro: disagreement is useful for annotation triage

Wang et al., first preprint **April 6, 2026**, compare heterogeneous models,
assign difficulty groups, refine difficult outputs through rendered-image
comparison, and route remaining hard cases to experts. The paper also identifies
output-matching biases in OmniDocBench v1.5 and changes its evaluation protocol.

**Limit:** This is principally a training-data strategy. Consensus pseudo-labels
and targeted expert corrections do not establish independent test truth, and
model disagreement alone cannot reveal shared errors. No reported benchmark
score establishes Hebrew merchant accuracy. [Paper, §§3.2–3.4 and §5](https://arxiv.org/html/2604.04771v1).

## Additional recent sources and a directly relevant earlier precedent

**MMLongBench-Doc-V2, August 4, 2026, preprint.** This revision reports 106
annotation corrections with source-page explanations, separating wrong answers,
defective or ambiguous questions, incomplete answers, and corpus defects. It also
changes the answer metric, making scores incomparable with the original version.
The audit was triggered by one system's failures, not a random sample; its
correction rate is not an unbiased noise estimate. For this project, retain
source-grounded correction reasons and explicit version boundaries. Its LLM
semantic judge is not a suitable authority for exact merchant strings or money.
[Paper, §§3 and 6](https://arxiv.org/html/2608.03397v1).

**VAREX, March 16, 2026, preprint.** Synthetic values are written into PDF form
widgets, so value truth is known, but model-generated schema mappings still need
validation. Following automated and model screening, experts review flagged
documents and a random unflagged sample. The latter found six missed errors in
approximately 660 fields. This directly motivates auditing apparent agreements.
English government forms differ from Hebrew statements; deterministic inserted
values do not guarantee correct rendering or field ownership.
[Paper, §§3.1 and 3.3](https://arxiv.org/html/2603.15118v1).

**PureDocBench, May 8, 2026, preprint.** The authors report 2,580 confirmed errors
among 21,353 scored OmniDocBench blocks. Their audit uses two OCR witnesses and
human examination of escalations, but leaves 8,685 matching blocks automatically
screened rather than manually checked. The new benchmark derives images and
annotations from HTML/CSS source, with human quality checks. These are authors'
findings, not our independent audit. Source-derived synthetic truth can isolate
recognition failures but cannot establish real merchant semantics. The author
repository records a June 14 ground-truth update, reinforcing that generated
benchmarks also require correction.
[Paper, §2.1 and Appendix A](https://arxiv.org/html/2605.07492v1),
[author repository](https://github.com/zhihengli-casia/puredocbench).

**DocAtlas, May 12, 2026, preprint.** Core text/layout annotations come from
document sources and rendering rather than learned OCR. Its synthetic RTL
pipeline explicitly includes Hebrew, with bidirectional layout control and
position logging. This is a relevant future method for generating known-truth
Hebrew/Latin continuation and reading-order cases. It is not evidence that
synthetic statement layouts reproduce our corpus, or that its models correctly
identify merchants. Native editable source is needed for the native-document
route; our PDFs cannot simply be treated as if those sources were available.
[Paper, §3.2 and Appendix 7.5](https://arxiv.org/html/2605.12623v1).

**DocILE, 2023, established task-design precedent.** Fields carry page, location,
type, and text; line-item fields also carry an item ID. Fields may span lines,
overlap, or cover parts of words. This supports representing transaction ownership
separately from physical row segmentation. The benchmark uses English business
documents, so its accuracy is not a Hebrew merchant result.
[Paper, §§3.3 and 4](https://arxiv.org/html/2302.05658v2).

These sources span different tasks and maturity levels. Their methodological
ideas are relevant, but none supplies validated gold for this private corpus.
The latest directly relevant correction study found in this search is from
August 2026; this is a targeted review, not a claim to exhaust every publication.

## Proposed route, adapted to the user's small review budget

The following is a recommendation for a new, explicitly authorized phase. It is
not an execution plan that supersedes the current STOP. Approximate sample sizes
are planning choices, not research-derived guarantees of quality or statistical
power.

**First deliverable: a 20–30-transaction calibration reference.** Select a bounded
set from existing training documents, with coverage of Hebrew/Latin mixing,
digital and OCR pages, wrapped merchants, location/category continuations,
processor text, and credits/installments where present. Selection must be
specified before inspecting outcomes. Keep it separate from a later evaluation
sample and preserve all existing document splits. Do not relabel the stopped
pilot or promote its reviewers' outputs.

Use the complete source page as the default review view, with zoom and necessary
document context. The human identifies the transaction and its merchant evidence
from the page. Frozen row IDs can be retained as anchors when useful, but their
geometry does not determine what the reviewer is allowed to see. A missing source
page is a source failure; a bad detected table box is an extractor limitation.
Neither becomes an invented merchant label.

For this small seed, the user's first judgment should be made with parser/model
answers hidden. After recording it, a separately produced candidate can expose
possible omissions or boundary differences for source-based resolution. This is
one human-established reference with an additional check, not independent
human–human validation. A second fluent reviewer would strengthen it; if none is
available, record that limitation and recheck a random subset without showing the
previous answer. Another model does not supply equivalent human independence.

The user should make three concrete decisions per transaction: which printed
spans name its merchant, which transaction owns those spans, and whether the
evidence permits one answer. Present narrow boundary choices only after the
initial source reading, and retain an explicit ambiguous option. Model tools can
prepare proposed transcriptions and evidence regions locally; cloud upload of
private source/derived data remains outside this recommendation's authority.
No new annotation service or review controller is needed for the seed.

**Represent the label in separable parts.** Reuse the existing merchant-reference
concept as far as possible; avoid designing a broad new schema family. Any
necessary change to the frozen label contract must be explicit and versioned.

| Part | Meaning |
| --- | --- |
| Transaction owner and source regions | Which transaction the text belongs to, including continuation evidence |
| Source transcription | What is visibly printed, preserving Hebrew/Latin order and punctuation |
| Merchant span | The minimal source-supported merchant-bearing portion under the written policy |
| Broader description/ancillary evidence | Retained separately when useful; not forced into the merchant target |
| Field status | Present with one value, absent, or ambiguous; unreadable/missing source is distinguished from absence |

Merchant identity here means the identity printed on the statement. Corporate
entity resolution, alias merging, transliteration, and merchant databases are
separate enrichment tasks. Uncertainty about a merchant should not erase a clear
financial field. Retaining those clear fields would require a revised reference
contract; it must not silently change the historical `GoldRow` semantics.

Use calibration to resolve merchant-versus-location, processor payload, suffix,
and continuation cases. Then freeze a short rulebook with source-independent
illustrative examples. Disagreements after that point are resolved from the
source and rulebook, or retained as ambiguity. Do not demand agreement before
doing the adjudication needed to create the reference. If the policy remains
incoherent, report the cause and stop expansion; do not lower the old pilot gate
or claim the stopped pilot passed.

**Only after calibration: expand to a modest reference set.** A reasonable next
size is approximately 100–200 unique transactions spread across multiple
training documents, labeled completely on selected pages. Report the actual
page/transaction counts; do not truncate pages merely to hit a round number.
Complete-page review reveals missed transactions that anchor-only sampling cannot.
Keep this diagnostic training reference separate from any later independently
authorized validation or test labeling.

Model-assisted drafts can reduce transcription work during expansion, but draft
labels are proposals. Every label claimed as gold needs source review; labels
accepted through consensus without that review remain provisional or silver.
If the user can review only the seed, keep the gold set small and measure assisted
quality on an independent human-reviewed sample before deciding how to expand.
Review disagreements and a random, preselected share of agreements; also retain
representative easy cases. Uncertainty-based sampling is useful for discovering
errors, but its scores must not be reported as population accuracy.

**Measure reference quality before extractor performance.** Report source
availability, represented transaction count, merchant ambiguity, omission,
unsupported text, incorrect ownership, and boundary-policy disagreement. A small
zero-error audit is a count, not proof of 99% accuracy. For later comparisons,
report paired outcomes on the same references and uncertainty accounting for
transactions clustered within documents.

After the reference and scoring rules are frozen, distinguish these outcomes:

- Merchant attribution accuracy: complete merchant-bearing evidence belongs to
  the correct transaction, with no invented or borrowed merchant text.
- Exact merchant text: exact under NFC and layout-whitespace normalization;
  preserve punctuation and visible spelling. Source-grounded extra ancillary
  text fails this narrower metric, even if attribution is correct.
- Source transcription/reading-order errors and support-region/ownership errors,
  reported separately so benign box-coordinate choices do not obscure semantics.
- Ambiguity and extractor abstention coverage, alongside omissions, wrong
  merchants, and unsupported assertions. Never improve a headline score by
  silently shrinking the eligible population.
- Exact core financial fields, using `Decimal`, assessed separately from merchant
  quality; full accurate-transaction results require both. Arithmetic checks can
  detect inconsistencies but cannot choose merchant labels or prove completeness.

The existing six-tier context experiment can be reconsidered only after a
reference exists and a new protocol is authorized. A simpler later comparison
could start with row, transaction neighborhood, and full page. Removing C4 from
the historical run would not be a continuation of the same experiment.

**Optional later supplement: generated Hebrew stress cases.** Once real examples
establish the policy, render invented structured transactions into RTL layouts
with known merchant strings, continuation ownership, and financial values. Vary
line wrapping, mixed Latin/numeric spans, spacing, and image degradation while
keeping source truth fixed. These cases can isolate OCR, ordering, and boundary
failures cheaply. Keep them separate from real-document gold, use invented data,
and validate that the renderer actually displays the intended content. Do not
build a synthetic generator before the real seed produces a usable reference.

## Scope boundary and completion

The [focus lock](../superpowers/specs/2026-07-30-row-extraction-focus-lock-design.md)
and live status forbid launching a replacement pilot or support task under the
old authority. Executing the proposal requires direct approval of the bounded
new phase and a committed charter/live-status amendment. The user's willingness
to review a seed informs this recommendation; it is not approval for unrelated
infrastructure, old-pilot relabeling, or held-out access.

This task changed this research note only. No private documents, labels, model
outputs, authority files, or production code were changed. No new extraction
scores or private-corpus acceptance are claimed. Production tests were not needed
for this documentation-only assessment; local-link and whitespace checks are the
relevant verification.

```text
Scope: YES — analyzed the recorded merchant-supervision and context-truncation failures
Experiment: shared evaluation
Measurement: field-presence, canonical-value, source-region and context-truncation error categories
Result: recorded field disagreement is 87/473 (18.39%); C4-related context failure affects 83/100 anchors; these findings do not measure merchant accuracy; research-informed next-phase recommendations are untested
Next extraction task: STOP
```
