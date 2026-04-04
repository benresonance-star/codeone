# Ontology And Vocabularies Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This document defines the controlled vocabularies used across:
- candidate resolution
- corpus canonicalization
- scope resolution
- query resolution
- review and reliability outputs

The machine-readable source of truth is:
- `Spec/vocabularies/ncc_semantic_vocabularies.json`

This markdown file defines the meaning and usage rules for those values.

## Core Rule
No module may invent enum values outside the controlled vocabulary file for:
- candidate types
- relationship types
- scope dimensions
- scope authorities
- query intents
- answer statuses
- evidence authority classes
- review reason codes

## Candidate Types
Candidate types classify stable semantic or document objects.

### Usage rule
- Use candidate types for structural identity.
- Do not overload candidate type with workflow status.
- Do not use query result categories as candidate types.

## Relationship Types
Relationship types are grouped into five families:
- structural
- referential
- semantic
- normative
- table scope

### Structural relationships
Use for hierarchy and containment only.

### Referential relationships
Use when one object explicitly points to another.

### Semantic relationships
Use for definition and term-meaning attachment.

### Normative relationships
Use for prescriptive or legal effect.

### Table-scope relationships
Use when note, row, column, or cell scope changes the meaning of a table value.

### Relationship rule
A `ScopedRelationship` is invalid if its meaning depends on scope anchors and those anchors are omitted.

## Scope Dimensions
Scope dimensions define the explicit applicability context for both retrieval and answer synthesis.

### Required rule
- Scope dimensions must be represented as named fields, not flattened into free-text tags.
- If a question depends on a dimension that is not modeled, the result must not be marked `accepted`.

## Scope Authorities
Scope authority values explain where a scope field came from.

### Required rule
- Every resolved scope field must carry exactly one authority value.
- Fields with `assumed_for_partial_answer` or `unresolved` must influence result status.

## Query Intents
Query intents normalize user and agent requests into reusable answer paths.

### Required rule
- Query interpretation must resolve to one primary intent.
- Secondary intents may be recorded, but answer assembly must still choose one primary answer family.

## Answer Statuses

| Status | Meaning |
|---|---|
| `accepted` | Essential scope is resolved and the governing path is sufficiently grounded. |
| `accepted_with_assumptions` | A partial answer is allowed, but assumptions materially affect applicability. |
| `requires_scope_confirmation` | The system knows what additional scope is required and must ask for it. |
| `insufficient_grounding` | The corpus, evidence, or graph is not strong enough to answer safely. |
| `conflict_present` | Relevant contradiction remains active in the governing path. |

### Status rule
Status values are mutually exclusive at the top-level `QueryResult`.

## Evidence Authority Classes
Evidence authority classes describe how trustworthy an evidence path is.

### Required rule
- Authority class is not the same as confidence.
- A high-confidence heuristic does not outrank an authoritative mapping or canonical target.

## Review Reason Codes
Review reason codes must be stable so the team can:
- measure recurring failure modes
- prioritize review work
- tune extraction or query logic without changing reporting semantics

## Assumption Impact Levels
Impact levels determine how much an assumption degrades answer certainty.

### Required rule
- `high` or `critical` impact assumptions prevent `accepted`.
- Impact is judged by whether the assumption could change governing clause, table, row, or overlay selection.

## Conflict Severity Levels
Conflict severity indicates how serious a contradiction or insufficiency is for answer safety.

### Required rule
- A `high` or `critical` conflict on the governing path prevents `accepted`.

## Note Normative Effect Classes
These values classify whether a note-like object has practical legal effect on answer construction.

### Required rule
- The canonicalization layer may assign a provisional class.
- The query layer may consume that class only according to the rules in `Spec/06_query_resolution_spec.md`.

## Overlay Operations
Overlay operation values define how jurisdiction or amendment layers affect baseline content.

### Required rule
- Overlay operations must be explicit machine values, not inferred from prose at query time.
- Baseline and overlay outputs must remain separately traceable.

## Change Discipline
Any change to the machine-readable vocabulary file must update this document in the same change.

Any new schema under `Spec/schemas/` that introduces an enum must either:
- reuse an existing vocabulary value, or
- add the value to `Spec/vocabularies/ncc_semantic_vocabularies.json` and define it here.
