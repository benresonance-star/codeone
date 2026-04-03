# PDF Ingestion Validation Contract
## NCC PDF Ingestion Constraint Manual
### Version 1.4.0

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

The extraction system may change runtime mode to improve table fidelity, but the output still counts as invalid if rows are empty, headers are unusable where required, or table structure cannot support downstream parity and review.

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
- candidate-stage readiness notes while the schema remains backward-compatible

Companion ingestion responses may additionally surface a transitional review payload for UI review workspaces, including:
- `lineage.xml_nodes`
- `lineage.pdf_fragments`
- `lineage.alignments`
- `lineage.canonical_snippets`

Current-state expectation for lineage-oriented review payloads:
- the review payload exists to support candidate review and traceability before the first-class candidate runtime is fully implemented
- `document_family_id` may be truncated and suffixed with a deterministic hash when needed to stay within persistence limits
- storage-safe identifier shortening must not make the family identifier nondeterministic for the same PDF/XML pair

Current-state expectation for UI validation feedback:
- the UI may show in-flight validation progress, selected file names, elapsed time, and request-cancel affordances while the backend request is still running
- temporary progress feedback is operational UI state, not a contract-level validation outcome

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
