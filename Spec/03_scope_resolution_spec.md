# Scope Resolution Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This specification defines how the system resolves user language and agent requests into explicit NCC legal scope.

It exists because reliable answers require more than retrieving relevant clauses. They require a deterministic statement of:
- what edition applies
- which jurisdiction applies
- which compliance pathway applies
- which building class or subclass applies
- which climate zone applies
- which construction conditions or assumptions apply
- which notes, exceptions, and overlays narrow the result

## Core Rule
Scope must be resolved explicitly before a definitive normative answer may be emitted.

If an essential scope dimension is unresolved, the system must either:
- answer with explicit assumptions
- request scope confirmation
- refuse definitive answer output

Silent guessing is prohibited.

## Scope Dimensions

| Dimension | Description | Example |
|---|---|---|
| `edition` | Governing NCC edition or amendment baseline. | `NCC 2022` |
| `jurisdiction` | State or territory context. | `Victoria` |
| `location` | User-supplied place name or project location. | `Melbourne` |
| `climate_zone` | Climate zone for thermal design. | `6` |
| `building_class` | NCC class or subclass. | `Class 2` |
| `building_use_context` | Relevant occupancy or use nuance if present. | `apartment building` |
| `compliance_path` | DTS, Performance Solution, or mixed. | `DTS` |
| `building_element` | The object the answer applies to. | `roof/ceiling` |
| `construction_form` | Construction details that affect governing values. | `pitched roof with flat ceiling` |
| `framing_type` | Framing-related scope. | `metal framed` |
| `material_context` | Material-specific qualifiers. | `insulated sandwich panel` |
| `overlay_context` | Applicable state or amendment overlay. | `NSW replace clause` |
| `exception_context` | Exceptions or non-default paths that narrow applicability. | `thermal break required` |

## Essential Scope For Normative Value Queries
For direct normative-value questions such as R-Value queries, the following dimensions are essential unless the corpus explicitly proves they are irrelevant:
- `edition`
- `jurisdiction`
- `building_class`
- `compliance_path`
- `building_element`

The following are conditionally essential:
- `climate_zone`
- `construction_form`
- `framing_type`
- `material_context`
- `overlay_context`

## Resolution Authority Levels
Each resolved scope field must carry an authority state.

### Allowed authority values
- `explicit_user`
- `explicit_system_default`
- `derived_from_corpus`
- `derived_from_mapping`
- `assumed_for_partial_answer`
- `unresolved`

### Rules
- `explicit_user` outranks every other authority.
- `derived_from_corpus` and `derived_from_mapping` are acceptable for definitive answers when the derivation path is reproducible.
- `assumed_for_partial_answer` is allowed only for `accepted_with_assumptions`.
- `unresolved` on an essential field requires `requires_scope_confirmation` or `insufficient_grounding`.

## Resolution Order
Scope must be resolved in the following order:

1. Edition
2. Jurisdiction
3. Location
4. Climate zone
5. Building class
6. Compliance path
7. Building element and domain target
8. Construction-form qualifiers
9. Overlay and exception applicability

This order is mandatory because later dimensions may depend on earlier ones.

## Deterministic Resolution Rules

### 1. Edition resolution
- Use the user-supplied edition if present and supported.
- Otherwise use the system default edition configured for the active corpus.
- If multiple editions are active and no default is configured, mark `edition` unresolved.

### 2. Jurisdiction resolution
- Prefer explicit jurisdiction from the user.
- If only location is provided, map location to jurisdiction using canonical corpus mapping objects.
- If the location is ambiguous across jurisdictions, mark jurisdiction unresolved and surface candidate matches.

### 3. Location to climate zone
- A location must never be converted to climate zone by free-text heuristics alone.
- Climate zone must be derived from a canonical corpus mapping object or remain unresolved.
- If the location maps to multiple climate zones depending on subregion granularity, that ambiguity must be surfaced.

### 4. Building class resolution
- Use explicit NCC class values when provided.
- If the user provides plain-language occupancy terms, map them to NCC class only through a controlled interpretation table or explicit user confirmation.
- If a safe mapping cannot be justified, set `building_class` unresolved.

### 5. Compliance path resolution
- Default to `DTS` only when the user did not specify a path and the question is phrased as a standard prescriptive requirement question.
- If the user asks a Performance Solution question, the system must not silently answer from DTS clauses.
- The compliance path and its authority state must always be exposed.

### 6. Construction-form resolution
- Construction qualifiers must be derived from explicit query terms or follow-up answers.
- If table selection depends on construction form and the query does not specify it, the system must not collapse multiple table families into one definitive value.

### 7. Overlay resolution
- Jurisdiction overlays must be evaluated only after edition and jurisdiction are resolved.
- Overlay application must preserve the baseline clause and the overlay source in the answer trace.

## Scope Refusal Rules
The system must refuse definitive output when any of the following conditions hold:
- essential scope field unresolved
- candidate governing paths differ materially by unresolved scope
- multiple table families remain plausible
- overlay applicability is unresolved
- contradiction remains unresolved in a query-critical path

## Scope Resolution Output
The query layer must consume a `ResolvedQueryScope` object validated against:
- `Spec/schemas/resolved_query_scope.schema.json`

Each scope field must include:
- value
- authority
- provenance
- resolution_notes where needed

## Required Mapping Families
The scope layer depends on canonical mapping objects for:
- location to jurisdiction
- location to climate zone
- user synonyms to NCC building class
- user synonyms to building element families
- compliance path intent cues

If a mapping family does not exist, the system must not claim deterministic resolution for that dimension.

## Assumptions
Assumptions are first-class outputs, not prose-only warnings.

Each assumption must record:
- `assumption_id`
- `scope_dimension`
- `assumed_value`
- `reason`
- `impact_level`

### Impact levels
- `low`
- `medium`
- `high`
- `critical`

If a `high` or `critical` assumption affects a governing table or clause selection, the result cannot be `accepted`.

## Example: Melbourne / Class 2 / R-Value
For the question "In a Class 2 building in Melbourne what are the required R-Values?", the minimum scope resolution path is:

1. Resolve `edition` to the active edition, for example `NCC 2022`.
2. Resolve `location = Melbourne`.
3. Derive `jurisdiction = Victoria` from the location mapping object.
4. Derive `climate_zone = 6` from the climate mapping object.
5. Resolve `building_class = Class 2`.
6. Default `compliance_path = DTS` only if no contrary signal exists.
7. Determine whether the question seeks all envelope elements or a narrower element family.
8. Determine whether multiple construction forms remain possible.

If the query does not specify whether the roof is pitched, flat, metal framed, sandwich-panel based, or otherwise qualified, the system may return:
- multiple answer items with explicit condition columns, or
- `requires_scope_confirmation`

It must not collapse those branches into a single R-Value.

## Follow-Up Query Rule
Follow-up questions may inherit prior scope only when:
- the prior scope object is still valid
- the inherited dimensions are recorded explicitly
- the user has not contradicted them

Implicit conversational carryover without a stored scope object is prohibited for normative answers.

## Non-Goals
This layer does not:
- resolve candidate graph edges
- normalize raw tables
- decide whether evidence is sufficient by itself

Those concerns belong to:
- `Spec/02_corpus_canonicalization_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/07_reliability_and_coverage_spec.md`

## Change Discipline
Any change to:
- required scope dimensions
- authority values
- answer status thresholds tied to scope
- location or building-class mapping policy

must update:
- `Spec/05_ontology_and_vocabularies_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/schemas/resolved_query_scope.schema.json`
- `Spec/schemas/query_result.schema.json`
