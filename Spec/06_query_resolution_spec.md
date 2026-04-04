# Query Resolution Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This specification defines how human and agent queries are transformed into:
- interpreted intent
- explicit scope
- canonical candidate and relationship selection
- normalized answer items
- auditable machine and human outputs

## Core Principle
Queries are resolved, not searched.

The query layer must construct an answer from:
- explicit scope
- canonical corpus objects
- scoped relationships
- overlays, notes, and exceptions
- evidence traces

Plain text retrieval alone is not sufficient for normative answers.

## Inputs
- `QueryRequest` validated by `Spec/schemas/query_request.schema.json`
- canonical corpus graph objects from `Spec/02_corpus_canonicalization_spec.md`
- resolved scope object from `Spec/03_scope_resolution_spec.md`
- controlled vocabularies from `Spec/05_ontology_and_vocabularies_spec.md`

## Outputs
- `QueryResult` validated by `Spec/schemas/query_result.schema.json`
- optional human-readable answer derived from the machine result

## Query Flow

### Stage 1. Query interpretation
The system must normalize the incoming question into:
- primary intent
- target domain
- target element family if stated
- expected answer family if inferable

### Stage 2. Scope resolution
The system must produce a `ResolvedQueryScope` before normative answer assembly.

### Stage 3. Governing path discovery
Using the resolved scope, the system must identify:
- governing clauses
- governing tables
- governing row and cell intersections
- relevant definitions
- relevant notes, footnotes, and exceptions
- applicable overlays

### Stage 4. Constraint synthesis
The system must synthesize one or more `AnswerItem` objects from the governing path rather than returning raw snippets.

### Stage 5. Result assembly
The system must assemble:
- top-level status
- answer items
- assumptions
- conflicts
- evidence traces
- concise human summary

## Query Intents
The primary query intent must use one of the controlled values:
- `direct_normative_value`
- `direct_normative_summary`
- `comparison`
- `applicability_check`
- `exception_lookup`
- `definition_lookup`
- `follow_up_filter`
- `scope_confirmation`

## Answer Families
The query layer may emit one or more answer items, but each item must belong to one of:
- `direct_normative_value`
- `scoped_summary`
- `comparison`
- `follow_up_filtered`
- `insufficient_scope`

## Required Query Rules
- Must validate the incoming request schema before interpretation.
- Must validate the resolved scope schema before governing-path traversal.
- Must cite canonical candidate IDs and relationship IDs for every normative answer item.
- Must emit assumptions as structured objects, not prose-only notes.
- Must emit conflicts when contradictions or insufficient grounding affect answer safety.
- Must preserve baseline and overlay provenance where overlays apply.

## Governing Path Discovery Rules
The governing path must be built in this order:

1. Select the applicable edition and jurisdiction.
2. Resolve the applicable corpus mapping objects such as location to climate zone.
3. Identify clauses that route the question to tables, exceptions, or definitions.
4. Resolve the relevant table family.
5. Resolve row and cell applicability.
6. Apply note, footnote, exception, and overlay narrowing rules.
7. Build answer items only from the surviving governing path.

## Table Query Rules
If a normative answer depends on a table:
- the query layer must traverse normalized row and cell objects, not raw table text
- row and column inheritance must be explicit in the answer trace
- note and footnote precedence must be applied before an answer item is accepted
- if multiple construction branches remain plausible, the result must not collapse them into a single value

## Answer Status Rules

### `accepted`
Allowed only when:
- essential scope is resolved
- the governing path is unambiguous enough for the requested answer family
- no high-severity conflict remains on the governing path
- evidence traces are complete

### `accepted_with_assumptions`
Allowed only when:
- the answer is still materially useful
- assumptions are explicit and structured
- no assumption with `critical` impact remains hidden

### `requires_scope_confirmation`
Required when:
- the missing information is known and user-supplied clarification would resolve it

### `insufficient_grounding`
Required when:
- the corpus graph is incomplete or the evidence path is not strong enough to answer safely

### `conflict_present`
Required when:
- a contradiction remains active in the governing path

## Human Answer Rules
The human-readable answer must be derived from the machine result and must include:
- scope basis
- values or conclusions
- assumptions if present
- conflict or insufficiency notice if present
- evidence-backed explanation

The human answer must not introduce claims absent from the machine result.

## Follow-Up Query Rule
Follow-up queries may reuse earlier `AnswerItem` or `ResolvedQueryScope` outputs only when:
- the reused objects are explicitly referenced
- the inherited scope remains valid
- no newly supplied scope contradicts the prior state

## Flagship Example: Melbourne / Class 2 / R-Value
For the question "In a Class 2 building in Melbourne what are the required R-Values?":

The query layer must not return a single answer unless the governing path proves only one branch applies.

At minimum it must:
- resolve `Melbourne -> Victoria -> climate zone 6`
- resolve `Class 2`
- state the compliance-path basis
- determine whether the user is asking for all envelope elements or a narrower subset
- determine whether multiple roof or framing branches remain open
- cite the governing clause and table objects
- include note, footnote, exception, and overlay effects in the answer trace

If construction form remains unresolved, the result should either:
- return multiple conditionally scoped answer items, or
- require scope confirmation

## Machine Contract Requirements
The top-level machine result must validate against:
- `Spec/schemas/query_result.schema.json`

The machine result must contain:
- `status`
- `scope`
- `answer_items`
- `assumptions`
- `conflicts`
- `definitions_used`
- `exceptions_considered`
- `confidence`

## Reliability Hand-Off
The query layer is not release-ready unless it passes the query and audit gates defined in:
- `Spec/07_reliability_and_coverage_spec.md`

The query layer must also be exercised through the flagship fixture packs defined in:
- `Spec/08_golden_fixtures_spec.md`
