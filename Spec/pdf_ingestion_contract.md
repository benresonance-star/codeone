# PDF Ingestion Validation Contract
## NCC PDF Ingestion Constraint Manual
### Version 1.12.0

---

# Purpose

This contract defines the mandatory validation rules for NCC PDF ingestion outputs before they are allowed to progress to the semantic layer.

It is intended to be:
- human-readable
- agent-enforceable
- backend-enforceable
- versioned and externalized

This is a validation contract, not guidance.

---

# Representation model

PDF and XML are different representations of the same NCC information.

The PDF is the primary rendered and spatial source for the NCC ingestion system.
The XML is the primary structural source for the NCC ingestion system.

The PDF must therefore be suitable for:
- deterministic text extraction
- fragment and bounding-box capture
- visible table capture
- metadata traceability
- reliable XML relationship mapping
- downstream candidate extraction and later semantic progression

Current staged runtime model:
- full paired-validation mode remains XML-led: XML semantic units define the candidate inventory
- a temporary PDF-only review mode may derive candidate inventory directly from assembled PDF clauses and fallback structured blocks, while XML remains optional secondary reference context
- PDF evidence packets are gathered against those XML semantic units
- a `CandidateObject` engine reconciles XML structure and PDF evidence
- a `CandidateRelation` engine extracts explicit XML links plus text-resolved, text-unresolved, and layout-inferred dependencies over the same candidate inventory
- a reconciliation stage compares object and relation outputs and emits reviewable reconciliation records before any staged-authority relation classes can affect promotion
- **Clause Semantic Enrichment** attaches optional semantic metadata to those same candidate records (explicit relations, glossary links, applicability conditions, implicit relation candidates, graph edges, enrichment hints) after extraction and before or alongside validation; it does not replace candidate identity or validation state
- review units are UI-facing projections of candidate objects (and may surface enrichment fields when present)
- canonical snippets may only be promoted from validated candidates

If PDF validation fails, the system must stop before candidate extraction and semantic compilation.

PDF extraction may be strategy-driven rather than globally uniform.
The ingestion system may select different extractor modes for different NCC document classes or section families when that improves structural fidelity without changing the validation contract itself.

---

# Status model

The PDF validation result must use these meanings consistently:

- `PASS`: all blocking rules pass and no warnings remain
- `PASS_WITH_WARNINGS`: all blocking rules pass and only bounded warning outcomes remain
- `REVIEW_REQUIRED`: the PDF output requires review before candidate extraction and semantic progression
- `FAIL`: validation completed but the PDF output did not satisfy contract requirements
- `BLOCKED`: one or more blocking rules prevent progression to the candidate and semantic layers

For PDF validation:
- `PASS` and `PASS_WITH_WARNINGS` may allow progression to the candidate extraction layer
- `REVIEW_REQUIRED` must not progress automatically
- `FAIL` and `BLOCKED` must not progress

Schema compatibility note:
- the current result schema still uses `can_progress_to_semantic_layer`
- until a dedicated candidate-stage gate field is introduced, that field should be interpreted as permission to enter the candidate stage, not permission to create canonical snippets directly

---

# Thresholds

The executable contract defines these thresholds and assumptions:

- minimum text-based ratio: `0.99`
- section-level split is required
- maximum missing bounding boxes: `0`
- maximum untyped fragments: `0`
- maximum invalid tables: `0`
- minimum alignment confidence for warning-level acceptance: `0.9`
- preferred alignment confidence for clean pass: `0.95`
- maximum unresolved alignments allowed with warnings: `5`
- maximum low-confidence alignments allowed with warnings: `5`
- minimum overall quality score: `0.95`

Operational assumptions:
- extractor selection may be routed by document strategy
- Docling text-first mode remains the default baseline unless a strategy explicitly selects a stronger mode
- table-heavy PDFs may enable Docling table-structure mode when benchmark evidence shows materially better table recovery
- extractor-mode changes must not weaken blocking rules for structure, alignment, metadata, or quality
- persisted `document_family_id` values must remain deterministic and storage-safe even when paired PDF and XML names are long

---

# Strategy-driven extraction

Validation is contract-driven, but extraction is allowed to be strategy-aware.

This means the system may:
- keep a conservative default extraction mode for general documents
- enable a table-aware extraction mode for known table-heavy PDFs
- preserve the same downstream validation rules regardless of which extractor mode was selected

Current expected behavior:
- general text-centric NCC sections may use Docling text-first mode
- glossary and definitions sections may use glossary-oriented extraction and repair logic
- known table-heavy clause-parity sections, such as Section J energy-efficiency material, may use Docling table-structure mode

The contract does not require one extractor mode for all PDFs.
It requires that the chosen mode produce structurally usable, traceable, and alignable output.

---

# Hard constraints

## C1 — PDF quality

The PDF must:
- be text-based
- be parseable enough for deterministic extraction
- meet the minimum text-based ratio

Outcome:
- block progression if the PDF is not sufficiently text-based

## C2 — Splitting

The PDF must be split to the required section-level scope before canonical ingestion proceeds.

Current broad-part behavior:
- section-level splitting remains the default contract expectation
- when the paired XML is a structural `part` wrapper rather than a clause-complete body, validation may scope the extracted PDF fragment set to the relevant part heading and intro or wrapper region before running parity checks
- this scoping does not relax the contract; it prevents broad wrapper XML from being compared against obviously out-of-scope PDF content

Outcome:
- block progression if the PDF is not split or is split to the wrong scope

## C3 — Block structure

Each extracted fragment must preserve:
- a stable fragment identifier
- a page reference
- a bounding box
- a fragment type

Outcome:
- block progression if any required fragment structure is missing

## C4 — Table structure

Extracted tables must preserve enough structure for downstream use:
- row presence
- usable header information where expected
- stable table identity
- row-level text that can be converted into reviewable fragment evidence when the table is structurally usable

The extraction system may change runtime mode to improve table fidelity, but the output still counts as invalid if rows are empty, headers are unusable where required, or table structure cannot support downstream parity and review.

Current row-level behavior:
- extracted table rows may be emitted as additional PDF fragments using stable ids such as `{table_id}__row_{n}`
- row fragments should preserve page provenance and a row-bounded bounding box when source table geometry is available
- narrow table XML artifacts may synthesize XML-side `__row_` nodes so parity can occur at row granularity instead of only whole-table granularity

Current linkage behavior:
- extracted tables must still appear in `table_validation` even when no XML-side table node has been linked yet
- when no XML table link exists, XML linkage fields should be omitted rather than populated with null placeholders
- absence of a table link does not by itself imply that table extraction failed; it means table-to-XML mapping is not yet explicit for that artifact

Outcome:
- block progression if extracted tables are structurally unusable

## C5 — XML alignment

PDF fragments must align to the paired XML representation with sufficient confidence.

The XML side must already be allowed to progress to the alignment layer before the PDF side can claim a trustworthy alignment result.
Successful alignment opens the path to candidate extraction; it does not authorize direct canonical snippet generation.

Current alignment behavior:
- when both a broad table or container node and a specific row node are plausible targets, alignment should prefer the more specific row-level node rather than defaulting to the earlier broad container
- row-level preference is especially important for narrow table XMLs that are being reviewed against a large PDF section
- focused review for narrow artifacts should keep row-level review items and may discard aggregate title or container entries once row matches exist

Outcome:
- `PASS` when the XML gate is open, unresolved alignments are `0`, low-confidence alignments are `0`, and average alignment confidence is at least `0.95`
- `PASS_WITH_WARNINGS` when the XML gate is open, average alignment confidence is at least `0.9`, unresolved alignments are at most `5`, and low-confidence alignments are at most `5`
- `BLOCKED` when the XML gate is closed, average confidence is below `0.9`, or unresolved / low-confidence alignments exceed the configured bounds

## C6 — Metadata

Fragments must carry enough metadata to support:
- clause traceability
- page provenance
- XML relationship lookup

Outcome:
- block progression if required traceability metadata is missing

Clarification:
- unresolved alignments are part of `C5_XML_ALIGNMENT`, not by themselves evidence that fragment metadata is missing
- `C6_METADATA` should evaluate actual traceability fields such as fragment identity, page reference, source strategy, and bounding box completeness

## C7 — Quality threshold

The PDF validation process must produce an overall confidence score from `0` to `1`.

Minimum acceptable value:
- `0.95`

Outcome:
- block progression if the score is below `0.95`

---

# Required output

The PDF validation engine must emit a structured validation result that includes:
- per-rule results
- quantitative confidence and count metrics
- table validation results
- alignment summary
- warnings
- errors
- validation trace
- fragment-to-node trace samples
- approval record

The output should use the repo schema at `Spec/validation_result.schema.json`.
Where XML relationships are surfaced, `node_id` should be treated as the normalized XML-side identifier. Legacy `xml_node` naming may be accepted for compatibility where explicitly allowed by the schema.

Companion ingestion metadata may additionally surface:
- selected document strategy
- extractor strategy
- extractor options such as Docling runtime mode
- runtime notes explaining whether text-first or table-aware extraction was used
- additive Docling inspection payloads such as `docling_view.blocks`, `docling_view.tables`, and `docling_view.page_index` for source/output inspection UIs
- optional block-level style enrichments under block metadata, such as `style_summary` and `style_spans`, when a secondary PDF appearance pass is available
- candidate-stage readiness notes while the schema remains backward-compatible

Current-state expectation for additive PDF appearance enrichment:
- appearance enrichment is optional and additive; it must not replace structural extraction or weaken blocking validation rules
- when appearance enrichment joins a secondary PDF engine to Docling structural blocks, bbox comparison must normalize both coordinate ordering and coordinate origin before overlap checks are applied
- implementations must account for provenance bboxes that may be emitted in top-left or bottom-left page coordinates and convert them to a common page-space before style matching
- page-height-aware origin conversion is acceptable implementation detail so long as the resulting enrichment remains traceable to the original extracted block and page

Companion ingestion responses may additionally surface **candidate robustness** payloads (additive, backward-compatible): `lineage.candidate_quality` (unit/evidence/candidate/review/snippet/baseline coverage counts), `lineage.graph_readiness` (inspectable gates and `ready_for_graph_handoff`), and `lineage.foundational_baseline_corpus` (deterministic baseline slice for glossary/title/interpretive categories). The same keys may appear on `review_workspace` for UI tabs. Graph-readiness gates are conservative and deterministic; they do not override PDF or XML validation outcomes. See `Spec/Candidate_Extraction_Layer.md` section 14 for authority vs heuristic enrichment markers on candidates.

Companion ingestion responses may additionally surface a candidate-first review payload for UI review workspaces, including:
- `lineage.xml_nodes`
- `lineage.xml_semantic_units`
- `lineage.pdf_fragments`
- `lineage.pdf_clause_candidates`
- `lineage.alignments`
- `lineage.pdf_evidence_packets`
- `lineage.candidate_objects` (each object may include `semantic_enrichment` and/or top-level `candidate_relations`, `reconciliation_records`, `graph_edges`, and `enrichment_hints` mirrors per `Spec/Candidate_Extraction_Layer.md`)
- `lineage.canonical_snippets`
- `lineage.candidate_relations` (optional aggregate list of explicit cross-candidate relations for the run, when emitted)
- `lineage.reconciliation_records` (optional aggregate list of object-vs-relation reconciliation outcomes for the run)
- `lineage.graph_edges` (optional aggregate edge list for graph-oriented consumers)
- `review_workspace.candidates`
- `review_workspace.review_units`
- `review_workspace.candidate_relations` (optional workspace-level projection)
- `review_workspace.reconciliation_records` (optional workspace-level projection)
- `review_workspace.graph_edges` (optional workspace-level projection)
- `summary.ingestion_run_id`
- `summary.created_at`
- `summary.enrichment_drift_advisory` (optional human-readable advisory when enrichment could diverge from stored validation state; not a blocking gate)

Current-state expectation for lineage-oriented review payloads:
- the runtime should treat XML semantic units as the primary candidate inventory in full paired-validation mode, even when legacy alignment fields are still surfaced for compatibility
- a temporary review-only `pdf_only` mode may derive candidate identity from assembled PDF clauses and fallback structured blocks when XML is absent or intentionally downgraded to secondary context
- PDF evidence should be gathered per XML semantic unit rather than treating fragments as long-term candidate identity
- candidate objects and candidate relations should be retained as first-class lineage payloads and review-workspace payloads
- reconciliation records should make any object-vs-relation gaps, contradictions, or unresolved dependencies inspectable rather than burying them inside enrichment notes
- review units should be derived from candidate objects rather than emitted directly from fragment alignments
- the payload may operate in `full` or `focused` mode depending on XML artifact type and fragment volume
- focused narrow-artifact review may preferentially surface row-level XML nodes and row-level PDF fragments when those matches exist
- review units may surface a three-schema classification bundle:
  `xml_structural_class`, `pdf_evidence_class`, and `candidate_semantic_class`
- assembled PDF clause payloads may surface structured header fields such as:
  `clause_code`, `heading_text`, `header_blocks`, `body_blocks`, and `marginalia_blocks`
- when structured clause headers are available, PDF-native candidate titles should prefer `clause_code + heading_text` rather than editorial notes or marginal annotations
- editorial annotations such as bracketed amendment notes (for example `[New for 2022]`) should remain annotation metadata and must not become the candidate anchor or primary title
- review units may also surface triage facets such as `review_issue_class`, `review_source_emphasis`, and `needs_human_review`
- `candidate_type` should be treated as a compatibility alias for `candidate_semantic_class`
- XML structural class is the primary semantic typing signal when a linked XML node exists
- PDF evidence class remains first-class review metadata even when semantic typing is XML-led
- raw token deltas may be preserved separately from effective mismatch deltas so structural title tokens do not force rule-style mismatch outcomes
- the review workspace should distinguish:
  `candidate_total` for candidates created by validation,
  `candidate_surfaced` for candidates included in the current workspace,
  and `candidate_needs_review` for the subset still requiring human review
- `candidate_total` should reflect semantic-unit-seeded candidate objects, not just surviving fragment alignments
- candidate identifiers should be stable and semantic-unit-led rather than using fragment ids as the long-term primary identity
- in temporary `pdf_only` review mode, candidate identifiers may use PDF-native ids such as `pdf_clause:{anchor_block_id}` and may omit `xml_node_id` without invalidating the review payload
- relation identifiers should be stable across lineage, workspace, and persisted review payloads for the same ingestion run
- `document_family_id` may be truncated and suffixed with a deterministic hash when needed to stay within persistence limits
- storage-safe identifier shortening must not make the family identifier nondeterministic for the same PDF/XML pair
- retained runs may be reloaded through an explicit run-detail API such as `GET /api/ingestions/runs/{run_id}`
- the reloaded run payload should restore validation outputs, XML semantic units, PDF evidence packets, candidate objects, review workspace state, and persisted reviewer decisions without recomputing extraction at request time
- when semantic enrichment is present, run payloads should preserve `semantic_enrichment` (or equivalent fields) on candidates and any emitted `candidate_relations` / `graph_edges` so downstream graph tooling and review UIs see a consistent candidate-first envelope
- candidate relations should surface relation authority and resolution metadata such as:
  - `relation_authority`
  - `target_locator`
  - `resolution_status`
  - `confidence`
  - `evidence_spans`
- reconciliation records should surface at least:
  - `classification`
  - `promotion_effect`
  - `review_required`
- staged-authority behavior should default to review visibility first: relation findings may create review items immediately, while only explicitly promoted relation classes may become promotion-relevant

**Enrichment drift risk (advisory):** Runtime stages, agents, and UI layers must not treat enrichment-only structures as a substitute for validated candidate state. Enrichment is advisory for workflow gates: validated candidate records and their validation outcomes remain authoritative for promotion. Operators and implementers should heed optional `summary.enrichment_drift_advisory` (or equivalent notes) when enrichment proposals could conflict with rejected, ambiguous, or not-yet-validated candidates. This advisory does **not** add a new hard blocking rule to PDF or candidate validation; it guards against accidental divergence from the candidate-first architecture.

Current-state expectation for UI validation feedback:
- the UI may show in-flight validation progress, selected file names, elapsed time, and request-cancel affordances while the backend request is still running
- temporary progress feedback is operational UI state, not a contract-level validation outcome
- after a refresh, the UI may reopen a retained workspace from persisted run data rather than forcing a fresh validation request
- a retained PDF file endpoint such as `GET /api/ingestions/runs/{run_id}/pdf` may still exist for retained artifacts, but the UI is not required to auto-embed that file after refresh
- the current review console may require an explicit `Relink PDF` action in the original preview panel so the operator can reattach the local PDF in the current browser session
- when the operator relinks the PDF locally, the embedded preview should preserve page-level candidate navigation, while exact in-page highlighting remains optional follow-on behavior
- the review sidebar may support filter tabs, explicit sort modes such as confidence, issue type, and XML/PDF emphasis, plus pagination for larger surfaced candidate sets
- the extraction inspection console may expose a Docling source/output viewer with PDF source on the left and Docling-derived output on the right
- the right-side Docling inspection pane may offer separate tabs for raw Docling output and an enhanced rendering backed by additive PDF style enrichment
- the enhanced rendering may visually apply extracted span-level font and color metadata, but this is additive UI behavior and must not replace the underlying Docling structural payload as the authoritative source-output view

Current-state expectation for `table_validation`:
- `table_id`, extraction counts, status, and confidence are required for emitted table entries
- `node_id` and `related_xml_node` are optional and should only be emitted when a concrete XML-side linkage exists

Future robust implementations to plan for:
- deterministic table-to-XML node linkage for extracted tables
- explicit table mapping states such as linked, unlinked, ambiguous, or review-required
- XML bundle support where a single PDF section corresponds to multiple XML files
- stronger lineage metadata that distinguishes extracted table identity from XML table identity
- explicit candidate-stage gate fields in the validation schema
- candidate promotion evidence that records which validated candidates produced canonical snippets
- explicit semantic-unit and evidence-packet schemas when the companion ingestion payloads are promoted from compatibility payloads to fully contract-bound runtime objects
- relation-class-specific escalation rules so clause references, exceptions, normative notes, and applicability dependencies can move from advisory to promotion-relevant on a controlled basis

---

# Enforcement

This contract must be:
- externalized in the repo
- loaded by backend validation services
- referenced by agents
- surfaced in the UI
- non-bypassable

---

# Final rule

If PDF validation fails, the PDF must not progress to:
- candidate extraction
- candidate validation
- semantic compilation
- canonical snippet generation
- downstream compliance evaluation

---

# End contract
