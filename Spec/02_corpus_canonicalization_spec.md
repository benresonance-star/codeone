# Corpus Canonicalization Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This specification defines how raw NCC source artifacts become a stable, queryable corpus graph.

It exists to close the gap between:
- source-valid XML and PDF ingestion
- stable canonical candidates
- deterministic query-time traversal

Without this layer, the system can preserve source fidelity and still answer incorrectly because the governing clause, table, row, note, footnote, or jurisdictional overlay was never normalized into a stable graph.

## Inputs
- validated NCC XML artifacts
- validated NCC PDF artifacts
- validated glossary artifacts
- validation outputs defined by the source contracts

## Outputs
The corpus canonicalization layer publishes:
- stable canonical corpus identifiers
- canonical hierarchy objects
- canonical xref targets
- normalized table, row, cell, note, and footnote objects
- jurisdiction and amendment overlays
- completeness metrics required for traversal readiness

This layer does not answer questions directly. It prepares the substrate that makes reliable query answering possible.

## Canonical Corpus Object Families

| Family | Description |
|---|---|
| `DocumentUnit` | Volume, section, part, clause, subclause, callout, glossary entry, schedule, appendix, or similar legal/document unit. |
| `TableUnit` | Table as a first-class object attached to a governing document unit. |
| `TableRowUnit` | Stable row object with row-level scope and note attachment semantics. |
| `TableCellUnit` | Stable cell object with row/column header inheritance and footnote binding. |
| `NoteUnit` | Normalized note/callout/annotation with explicit attachment scope. |
| `ReferenceLink` | Canonical xref record from source-local pointer to stable target ID. |
| `JurisdictionOverlay` | State or territory modification that replaces, adds, narrows, or exempts a baseline requirement. |
| `AmendmentOverlay` | Edition or amendment delta applied over a baseline object. |
| `CompletenessRecord` | Coverage and unresolved-item counters required for publication gates. |

## Stable Identifier Policy
Every published object in the canonical corpus graph must have a stable identifier derived from source semantics rather than transient parser state.

### Identifier rules
- IDs must be deterministic for the same NCC edition and source content.
- IDs must survive non-substantive rebuilds.
- IDs must encode object family and semantic location.
- IDs must not depend on publisher-local temporary file names.
- IDs may include a short hash suffix only when required to disambiguate otherwise identical semantic paths.

### Recommended ID patterns
- `ncc:{edition}:volume:{volumeId}`
- `ncc:{edition}:part:{partId}`
- `ncc:{edition}:clause:{clauseNumber}`
- `ncc:{edition}:subclause:{clauseNumber}:{subclauseNumber}`
- `ncc:{edition}:table:{tableNumber}`
- `ncc:{edition}:table_row:{tableNumber}:r{rowOrdinal}`
- `ncc:{edition}:table_cell:{tableNumber}:r{rowOrdinal}:c{colOrdinal}`
- `ncc:{edition}:glossary:{entrySlug}`
- `ncc:{edition}:overlay:{jurisdiction}:{targetId}`

### Required identity fields
Each canonical object must retain:
- `canonical_id`
- `edition_id`
- `object_type`
- `source_locators`
- `hierarchy_path`
- `governing_parent_id`
- `status`

## Hierarchy Normalization
The corpus layer must normalize the legal and document hierarchy even when XML roots vary by source family.

### Minimum hierarchy model
- edition
- volume
- part
- section if present
- clause
- subclause
- paragraph or list item where semantically required
- table
- row
- cell
- note or footnote
- glossary entry

### Hierarchy rules
- Each non-root object must identify one governing parent.
- A table must be attached to the clause, part, or appendix that legally governs it.
- Rows and cells must not float independently of their table.
- Notes and callouts must preserve both visual attachment and legal attachment.
- If visual proximity and legal attachment disagree, both signals must be preserved and a canonical attachment decision must be recorded.

## Cross-Reference Remapping
The source XML corpus contains publisher-local `href` targets that are not stable repository identifiers.

The canonicalization layer must remap every traversable source reference into a canonical target.

### Reference remapping process
1. Parse the raw source reference as-is.
2. Extract the strongest available target signal:
   - semantic number such as clause or table number
   - XML fragment identifier
   - source file identity
   - explicit target type
3. Attempt deterministic resolution against canonical objects.
4. Record the result as a `ReferenceLink`.
5. Publish unresolved links only with an explicit unresolved status and reason code.

### `ReferenceLink` minimum fields
- `reference_id`
- `source_object_id`
- `source_href_raw`
- `reference_type`
- `target_object_id`
- `resolution_status`
- `resolution_basis`
- `confidence`

### Resolution status values
- `resolved`
- `resolved_with_alias`
- `ambiguous`
- `unresolved`
- `blocked_by_missing_target`

### Publication rule
No query-critical document family may be considered traversal-ready if its unresolved reference rate exceeds the threshold defined in `Spec/07_reliability_and_coverage_spec.md`.

## Table Normalization
Tables are first-class governing structures and must not be treated as opaque blobs.

### Canonical table model
Each table must publish:
- table metadata
- ordered rows
- ordered columns
- row headers
- column headers
- body cells
- table-level notes
- row-level notes
- cell-level footnotes
- precedence rules

### Row normalization rules
- Each row receives a stable row ID.
- A row inherits the table's governing scope unless narrowed explicitly.
- Row markers and note markers must be preserved as explicit attachment signals.
- Row ordering is semantic and must be persisted.

### Cell normalization rules
- Each cell receives a stable cell ID.
- Header inheritance must be materialized, not recomputed ad hoc at query time.
- A cell may inherit one or more row headers and one or more column headers.
- Cell-level footnotes must attach to the cell unless a deterministic widening rule is specified.

### Note precedence rules
The canonicalization layer must explicitly distinguish:
- table-level note
- row-level note
- column-level note
- cell-level footnote
- external clause note affecting a table

Precedence must be recorded so the query layer does not widen a local note into a global rule.

### Derived constraint units
If a table answer depends on an intersection of row scope, column scope, and note scope, the corpus layer may publish a derived `ConstraintProjection` object for deterministic query use. Such projections must remain traceable back to their originating row, column, cell, and note objects.

## Callouts, Notes, And Informational Blocks
Callouts and notes must not be flattened into plain text paragraphs.

Each note-like object must retain:
- note type
- attachment target
- attachment basis
- normative effect classification
- evidence span references

### Normative effect classification
- `informational`
- `interpretive`
- `qualifying`
- `exception_like`
- `unknown`

This classification is advisory until promoted by the ontology and validation rules, but it must be persisted at canonicalization time.

## Jurisdiction And Amendment Overlays
Jurisdiction and amendment handling must be modeled explicitly rather than buried inside clause text.

### Overlay object requirements
Each overlay must include:
- `overlay_id`
- `overlay_type`
- `jurisdiction`
- `edition_id`
- `target_object_id`
- `operation`
- `replacement_or_delta_payload`
- `effective_status`

### Allowed overlay operations
- `replace`
- `insert_after`
- `insert_before`
- `narrow_scope`
- `broaden_scope`
- `exempt`
- `annotate_only`

### Overlay rules
- Baseline and overlay objects must remain separately queryable.
- Query-time resolution must never silently discard the baseline or the overlay provenance.
- Overlay application order must be deterministic and edition-aware.

## Publication Gates
The corpus canonicalization layer may publish a document family as `query_ready` only when:
- stable IDs were generated for all query-relevant objects
- canonical hierarchy is reconstructible
- query-critical references are resolved within allowed tolerance
- table notes and footnotes are normalized explicitly
- jurisdiction overlays are attached to valid targets
- completeness metrics are available

## Completeness Metrics
Every canonicalization run must emit a `CompletenessRecord` with at least:
- clause coverage rate
- table coverage rate
- table row normalization rate
- table cell normalization rate
- note attachment resolution rate
- footnote attachment resolution rate
- xref resolution rate
- overlay target resolution rate
- unresolved object counts by family
- unresolved object counts by document family

## Minimum Query-Critical Families
The following families are query-critical and must satisfy stricter thresholds:
- envelope and fabric tables
- glossary definitions referenced by energy-efficiency questions
- climate and jurisdiction mapping tables
- clauses that route to tables
- notes and exceptions modifying those tables or clauses

## Example: Melbourne / Class 2 / R-Value
For the question "In a Class 2 building in Melbourne what are the required R-Values?", canonicalization must make the following path deterministic:

1. Location mapping object for `Melbourne -> Victoria -> climate zone 6`.
2. Clause object for the governing roof/wall/floor provisions.
3. Table object referenced by the governing clause for climate zone 6.
4. Row and cell objects representing the building element and construction condition.
5. Note or exception objects that qualify those row and cell values.
6. Any jurisdiction overlay that changes the baseline result.

If any one of those steps is missing, the query layer must not present a definitive answer.

## Non-Goals
This layer does not:
- infer missing legal scope from user intent
- classify the user's building for them
- choose a compliance pathway
- synthesize final human-readable answers

Those responsibilities belong to:
- `Spec/03_scope_resolution_spec.md`
- `Spec/06_query_resolution_spec.md`

## Required Downstream Contracts
The following documents depend on this spec:
- `Spec/04_data_model_spec.md`
- `Spec/05_ontology_and_vocabularies_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/07_reliability_and_coverage_spec.md`

Any change to canonical IDs, xref status semantics, or table normalization semantics must update those dependent documents in the same change.
