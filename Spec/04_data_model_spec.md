# Data Model Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This document defines the repository-wide object model boundary between:
- source ingestion
- canonical corpus graph publication
- scope resolution
- query resolution
- review and reliability workflows

It does not replace the existing source contracts. It standardizes the object families that later stages depend on and identifies which ones must be backed by formal machine schemas.

## Core Design Rules
- Assertions remain append-only and preserve competing claims before resolution.
- Canonical graph objects must be stable, provenance-bearing, and safe for downstream traversal.
- Query-layer objects must validate against JSON Schemas under `Spec/schemas/`.
- Enumerations must come from `Spec/vocabularies/ncc_semantic_vocabularies.json`.
- Scope, evidence, and status are first-class fields, not narrative side notes.

## Object Families

| Object family | Purpose | Authority source |
|---|---|---|
| `Assertion` | Append-only record of a produced claim. | Existing ingestion and candidate-stage foundations. |
| `CanonicalCandidate` | Stable resolved document or semantic unit. | Existing candidate and semantic-layer foundations. |
| `GlossaryTag` | Scope-aware definition grounding. | Existing candidate and glossary foundations. |
| `ScopedRelationship` | Typed, evidenced, scoped connection between canonical objects. | Existing candidate/relation foundations plus ontology spec. |
| `SpanAnchor` | Trace from canonical meaning to source locators. | Existing foundations plus source contracts. |
| `DocumentUnit` / `TableUnit` / `TableRowUnit` / `TableCellUnit` / `NoteUnit` | Canonical corpus graph objects published by the corpus layer. | `Spec/02_corpus_canonicalization_spec.md` |
| `JurisdictionOverlay` / `AmendmentOverlay` | Overlay and delta objects. | `Spec/02_corpus_canonicalization_spec.md` |
| `ResolvedQueryScope` | Deterministic scope bundle for answer construction. | `Spec/03_scope_resolution_spec.md` and `Spec/schemas/resolved_query_scope.schema.json` |
| `QueryRequest` | Normalized incoming question contract. | `Spec/schemas/query_request.schema.json` |
| `AnswerItem` | One scoped, evidence-backed answer unit. | `Spec/schemas/answer_item.schema.json` |
| `Assumption` | First-class partial-answer assumption. | `Spec/schemas/assumption.schema.json` |
| `Conflict` | Contradiction or insufficiency object that affects answer status. | `Spec/schemas/conflict.schema.json` |
| `EvidenceTrace` | Structured answer-to-source replay object. | `Spec/schemas/evidence_trace.schema.json` |
| `QueryResult` | Machine-readable query output. | `Spec/schemas/query_result.schema.json` |
| `ReviewItem` / `OverrideRecord` | Human control loop objects. | Existing foundations plus ontology spec. |

## Schema Boundary
The following object families are mandatory schema-validated machine contracts:
- `QueryRequest`
- `ResolvedQueryScope`
- `Assumption`
- `EvidenceTrace`
- `Conflict`
- `AnswerItem`
- `QueryResult`

These objects must not be defined only by examples in markdown.

## Canonical Object Requirements
Every stable object used by downstream graph traversal must expose:
- stable identifier
- object family and subtype
- edition
- provenance
- status
- scope context if applicable
- evidence or traceability references

## Query Object Requirements
Every query-layer object must expose:
- schema version
- status semantics
- evidence trace references
- explicit assumptions where used
- explicit conflict records where relevant

## Relationship Boundary
Relationships remain richer than simple edges. A valid `ScopedRelationship` must preserve:
- relationship type
- from and to identifiers
- scope anchors where required
- condition anchors where required
- evidence references
- authority classification
- lifecycle status

The allowed types and their semantics are owned by `Spec/05_ontology_and_vocabularies_spec.md`.

## Status Boundary
Status fields must not drift across layers.

### Required rule
- candidate lifecycle statuses must not be reused as query result statuses
- query result statuses must not be reused as review queue statuses
- evidence authority classes must not be overloaded into confidence bands

## Machine Contract Index

| Schema | File |
|---|---|
| Query request | `Spec/schemas/query_request.schema.json` |
| Resolved query scope | `Spec/schemas/resolved_query_scope.schema.json` |
| Assumption | `Spec/schemas/assumption.schema.json` |
| Evidence trace | `Spec/schemas/evidence_trace.schema.json` |
| Conflict | `Spec/schemas/conflict.schema.json` |
| Answer item | `Spec/schemas/answer_item.schema.json` |
| Query result | `Spec/schemas/query_result.schema.json` |

## Compatibility With Existing Specs
This document intentionally does not restate the full field-level detail already covered in:
- `Spec/NCC_Spec_V5.md`
- `Spec/Candidate_Extraction_Layer.md`

Those documents remain the foundation for ingestion-first and candidate-first behavior. This document adds the missing normalized query-layer contract boundary and points to the authoritative schemas.

## Change Discipline
Any change to:
- object identity rules
- status semantics
- relationship type semantics
- query-layer schemas

must be accompanied by matching updates to:
- `Spec/05_ontology_and_vocabularies_spec.md`
- `Spec/vocabularies/ncc_semantic_vocabularies.json`
- affected schema files under `Spec/schemas/`
