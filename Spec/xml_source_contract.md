# XML Source Validation Contract
## NCC XML Ingestion Constraint Manual
### Version 1.2.0

---

# Purpose

This contract defines the mandatory validation rules for NCC XML source files before they are allowed into the structural source layer.

It is intended to be:
- human-readable
- agent-enforceable
- backend-enforceable
- versioned and externalized

This is a validation contract, not guidance.

---

# Representation model

XML and PDF are different representations of the same NCC information.

The XML is the primary structural source for the NCC ingestion system.
The PDF is the primary rendered and spatial source for the NCC ingestion system.

The XML must therefore be suitable for:
- structural interpretation
- clause identity
- hierarchy validation
- reference resolution
- downstream XML-to-PDF alignment
- canonical snippet generation

If XML validation fails, the system must stop before alignment can be trusted and before semantic compilation can proceed.

---

# Status model

The XML validation result must use these meanings consistently:

- `PASS`: all blocking rules pass and no warnings or review-required outcomes remain
- `PASS_WITH_WARNINGS`: all blocking rules pass and only bounded warning outcomes remain
- `REVIEW_REQUIRED`: no blocking rule has fired, but the source must be reviewed before it can progress to alignment
- `FAIL`: validation completed but the source did not satisfy contract requirements
- `BLOCKED`: one or more blocking rules prevent progression to alignment and later stages

For XML validation:
- `PASS` and `PASS_WITH_WARNINGS` may allow progression to the alignment layer
- `REVIEW_REQUIRED` must not progress automatically
- `FAIL` and `BLOCKED` must not progress

---

# Thresholds

The executable contract defines these thresholds and assumptions:

- expected root elements: `ncc`, `NCC`, `part`, `clause`, `table-reference`, `image-reference`
- section or part context is required when applicable
- maximum empty required nodes before review becomes blocking: `2`
- maximum unresolved references allowed with warnings: `5`
- maximum definition link failures allowed with warnings: `5`
- maximum table structure issues allowed before blocking: `1`
- minimum quality score: `0.95`

---

# Hard constraints

## X1 — XML well-formedness

The XML must:
- parse successfully
- contain an expected root element
- use valid encoding
- contain no malformed tags or broken nesting

Current corpus note:
- legitimate NCC source files may use structural roots such as `part`, `clause`, `table-reference`, or `image-reference`
- those roots must not be treated as malformed simply because they are not wrapped in a single `ncc` document root

Outcome:
- block progression if any of these checks fail

## X2 — Required metadata

The XML must expose, either directly or through mapped metadata:
- NCC edition
- amendment or version
- volume
- section or part context where applicable

Current metadata inference behavior may derive these values from:
- root attributes where present
- structural children such as `num`, `sptc`, and `title`
- corpus defaults implied by NCC part or clause files
- conservative filename or body-text inference when structural fields are absent

Outcome:
- block progression if required metadata is missing

## X3 — Hierarchy integrity

The XML hierarchy must preserve valid NCC structure:
- section
- part
- clause
- subclause
- table, figure, and note where represented

The hierarchy must not contain:
- invalid parent-child relationships
- impossible nesting
- orphaned structural nodes

Outcome:
- block progression if any hierarchy integrity check fails

## X4 — Unique identities

The XML must provide stable unique identifiers for:
- clauses
- tables
- figures
- definitions where available
- other addressable nodes

Duplicate IDs are not allowed.

Outcome:
- block progression if duplicate IDs are found

## X5 — Content presence

Required structural nodes must contain usable content.
Examples:
- headings cannot be empty
- clause bodies cannot be empty unless explicitly allowed
- table containers must not be empty

Outcome:
- `PASS` when empty required nodes = `0`
- `REVIEW_REQUIRED` when empty required nodes are greater than `0` and less than or equal to `2`
- `BLOCKED` when empty required nodes are greater than `2`

## X6 — Reference resolution

Internal references must be:
- detected
- typed where possible
- resolved to existing XML targets where required

Unresolved references must be explicitly flagged.

Current reference-resolution note:
- only local XML targets should count toward unresolved-reference totals
- external publishing paths and non-local `href` targets must not be treated as missing local XML ids

Outcome:
- `PASS` when unresolved references = `0`
- `PASS_WITH_WARNINGS` when unresolved references are greater than `0` and less than or equal to `5`
- `BLOCKED` when unresolved references are greater than `5`

## X7 — Definition structure

Defined terms must be:
- identifiable
- scoped where possible
- linkable from referencing clauses where available

Broken definition links must be flagged.

Outcome:
- `PASS` when definition link failures = `0`
- `PASS_WITH_WARNINGS` when definition link failures are greater than `0` and less than or equal to `5`
- `BLOCKED` when definition link failures are greater than `5`

## X8 — Table structure readiness

If tables are represented in XML, they must preserve enough structure for downstream interpretation and XML-to-PDF relationship checks:
- row presence
- header presence where available
- cell grouping and notes where represented

Current table-alignment note:
- `table-reference` XML may synthesize row-level XML nodes such as `{table_id}__row_{n}` for downstream row-granular PDF alignment and focused review
- row-node synthesis is intended to improve parity and review precision for narrow table artifacts rather than change the XML source of truth

Outcome:
- `PASS` when table structure issues = `0`
- `REVIEW_REQUIRED` when table structure issues are greater than `0` and less than or equal to `1`
- `BLOCKED` when table structure issues are greater than `1`

## X9 — Candidate-backed snippet readiness

The XML must be sufficiently structured for downstream candidate extraction and candidate-backed canonical snippet generation.
This means the XML must preserve:
- stable clause identity
- hierarchical position
- node content
- references
- metadata needed for source traceability
- traceability metadata needed for later XML-to-PDF relationships

Outcome:
- block progression if snippet readiness or traceability completeness fails

Schema compatibility note:
- the current rule name remains `X9_SNIPPET_READINESS` for compatibility
- this should be interpreted as readiness for candidate extraction and later validated promotion into snippets, not direct snippet creation from XML alone

## X10 — Quality threshold

The XML validation process must produce an overall quality score from `0` to `1`.

Minimum acceptable quality score:
- `0.95`

Outcome:
- block progression if the score is below `0.95`

---

# Required output

The XML validation engine must emit a structured validation result that includes:
- per-rule results
- warnings
- errors
- gate decision for progression to the alignment layer
- confidence or quality information
- validation trace
- approval record
- optional trace samples for structural evidence

The output should share a common envelope with PDF validation where practical, while keeping XML-specific identity fields such as `node_id`.
Where cross-representation links are present, the shared identifier vocabulary should prefer `node_id` for XML-side identities and `fragment_id` for PDF-side identities.

Current-state expectation for XML-side lineage:
- broad `part` and `clause` XML may validate as `PASS_WITH_WARNINGS` or `REVIEW_REQUIRED` when the structure is trustworthy but still requires human review before automatic progression
- narrow table XML may surface additional synthesized row nodes in lineage or review payloads so PDF row fragments can align against them

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

If XML validation fails, the XML must not progress to:
- alignment
- candidate extraction
- candidate validation
- semantic compilation
- snippet generation

---

# End contract
