# PDF Ingestion Validation Contract
## NCC PDF Ingestion Constraint Manual
### Version 1.1.0

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
- downstream semantic progression

If PDF validation fails, the system must stop before semantic compilation.

---

# Status model

The PDF validation result must use these meanings consistently:

- `PASS`: all blocking rules pass and no warnings remain
- `PASS_WITH_WARNINGS`: all blocking rules pass and only bounded warning outcomes remain
- `REVIEW_REQUIRED`: the PDF output requires review before semantic progression
- `FAIL`: validation completed but the PDF output did not satisfy contract requirements
- `BLOCKED`: one or more blocking rules prevent progression to the semantic layer

For PDF validation:
- `PASS` and `PASS_WITH_WARNINGS` may allow progression to the semantic layer
- `REVIEW_REQUIRED` must not progress automatically
- `FAIL` and `BLOCKED` must not progress

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

Outcome:
- block progression if extracted tables are structurally unusable

## C5 — XML alignment

PDF fragments must align to the paired XML representation with sufficient confidence.

The XML side must already be allowed to progress to the alignment layer before the PDF side can claim a trustworthy alignment result.

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
- semantic compilation
- canonical snippet generation
- downstream compliance evaluation

---

# End contract
