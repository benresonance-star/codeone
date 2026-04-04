# Reliability And Coverage Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This specification defines when the NCC system is reliable enough to support human and agentic queries.

Reliability is not measured only by whether a few fixtures pass. It is measured by the combination of:
- source fidelity
- canonicalization completeness
- scope-resolution correctness
- query-answer grounding
- contradiction visibility
- corpus coverage

## Core Rule
No release may claim high-reliability query support unless it passes both:
- scenario correctness gates
- corpus coverage gates

Fixture correctness without corpus coverage is insufficient.

All thresholds in this document are owned by policy version:
- `ncc_query_reliability_policy_v1`

## Reliability Layers

| Layer | Focus |
|---|---|
| L1 | Source fidelity and extraction integrity |
| L2 | Candidate and corpus canonicalization integrity |
| L3 | Scope resolution integrity |
| L4 | Relationship and overlay integrity |
| L5 | Query result integrity |
| L6 | Auditability and human control |

## Required KPIs

### L1. Source fidelity
- XML validation pass rate
- PDF validation pass rate
- source-locator completeness rate

### L2. Canonicalization coverage
- stable ID generation rate
- canonical hierarchy completeness rate
- xref resolution rate
- table normalization rate
- row normalization rate
- cell normalization rate
- note attachment resolution rate
- footnote attachment resolution rate
- overlay target resolution rate

### L3. Scope coverage
- location to jurisdiction mapping coverage
- location to climate zone mapping coverage
- building class synonym coverage
- compliance path default eligibility coverage
- unresolved essential scope rate for flagship query families

### L4. Relationship integrity
- relationship evidence completeness rate
- required scope-anchor completeness rate
- contradiction detection rate on seeded conflict fixtures
- unresolved overlay conflict rate

### L5. Query reliability
- accepted answer precision on golden fixtures
- accepted_with_assumptions precision
- false definitive answer rate
- requires_scope_confirmation precision
- insufficient_grounding precision
- answer-to-source replay success rate

### L6. Human control
- review-item generation recall on seeded ambiguity fixtures
- override preservation rate
- stable identifier persistence across non-substantive rebuilds

## Query Family Coverage Matrix
Reliability must be measured by query family, not only by aggregate score.

Minimum query families:
- direct normative value
- normative summary
- applicability check
- exception lookup
- comparison
- follow-up filter

## Corpus Coverage Gates
The following gates must be reported for each release candidate:

| Gate | Description |
|---|---|
| `coverage_clauses_query_critical` | Percent of query-critical clauses canonicalized and traversal-ready. |
| `coverage_tables_query_critical` | Percent of query-critical tables normalized at table, row, and cell level. |
| `coverage_notes_query_critical` | Percent of query-critical notes and footnotes attached with explicit scope. |
| `coverage_xrefs_query_critical` | Percent of query-critical references resolved to canonical targets. |
| `coverage_scope_mappings` | Percent of supported locations and class synonyms mapped deterministically. |
| `coverage_overlays_query_critical` | Percent of applicable jurisdiction overlays attached to valid baseline targets. |

## Release Threshold Classes

### Experimental
Allowed when:
- fixture correctness is improving
- corpus coverage is incomplete
- user-facing answers are explicitly marked as non-authoritative

### Controlled beta
Allowed when:
- flagship fixtures pass
- false definitive answer rate is at or below `0.02`
- query-critical corpus coverage meets the beta thresholds in this document

### High-reliability production
Allowed only when:
- flagship query families meet the production thresholds in this document
- query-critical coverage metrics are at or above production release threshold
- answer replay and contradiction visibility meet the production gates in this document

## Default Threshold Table

| Metric | Controlled beta | High-reliability production |
|---|---|---|
| `false_definitive_answer_rate` | `<= 0.02` | `<= 0.005` |
| `accepted_answer_precision` | `>= 0.95` | `>= 0.99` |
| `accepted_with_assumptions_precision` | `>= 0.90` | `>= 0.97` |
| `requires_scope_confirmation_precision` | `>= 0.90` | `>= 0.97` |
| `insufficient_grounding_precision` | `>= 0.90` | `>= 0.97` |
| `trace_completeness_on_accepted` | `>= 0.98` | `= 1.00` |
| `answer_to_source_replay_success_rate` | `>= 0.98` | `= 1.00` |
| `coverage_xrefs_query_critical` | `>= 0.97` | `>= 0.995` |
| `coverage_notes_query_critical` | `>= 0.97` | `>= 0.995` |
| `coverage_tables_query_critical` | `>= 0.97` | `>= 0.995` |
| `coverage_scope_mappings` | `>= 0.95` | `>= 0.99` |
| `coverage_overlays_query_critical` | `>= 0.95` | `>= 0.99` |
| `unresolved_essential_scope_rate_flagship_family` | `<= 0.10` | `<= 0.02` |
| `overlay_conflict_visibility_seeded` | `>= 0.95` | `= 1.00` |

If a separate policy file is introduced later, it must preserve a versioned name and every `QueryResult.replay_context.policy_version` must identify the active threshold policy.

## Flagship Query Scenario
The system must support a real flagship scenario rooted in actual NCC structure:

Question family:
- "In a Class 2 building in Melbourne what are the required R-Values?"

### What this scenario must exercise
- location to jurisdiction mapping
- location to climate zone mapping
- clause selection that routes to the correct table family
- climate-zone-specific table selection
- row and cell selection for building element and construction branch
- note and footnote scope handling
- exception and overlay handling
- refusal to collapse unresolved construction branches into a single value

### Minimum evidence path
The scenario must be replayable across:
- location mapping object
- governing clause object
- governing table object
- selected row and cell objects
- attached note or exception objects
- final answer item

## Required Reliability Tests

### Query safety tests
- The system must not emit `accepted` when climate zone is unresolved and changes table selection.
- The system must not emit `accepted` when construction form is unresolved and changes the governing row/cell.
- The system must not silently ignore a table note that narrows a selected row or cell.
- The system must not emit `accepted` for a Performance-style or hybrid-path query from a DTS-only path without explicit limitation handling.
- The system must not emit `accepted` when a follow-up query contradicts inherited scope and the governing path has not been rebuilt.
- The system must not emit `accepted` when a building-class synonym mapping remains materially ambiguous.

### Coverage regression tests
- A release must fail if xref resolution or note-attachment coverage regresses in a query-critical family beyond the tolerated threshold.
- A release must fail if a new overlay source is introduced without overlay target resolution metrics.
- A release must fail if `trace_completeness_on_accepted` drops below the threshold for the declared release class.
- A release must fail if `coverage_scope_mappings` drops below the threshold for a supported flagship query family.

### Audit tests
- Every accepted answer must replay from answer item to candidate IDs to relationship IDs to span IDs to source locators.
- Every accepted_with_assumptions answer must replay the same way plus list structured assumptions.
- Every follow-up answer must preserve replay context linking the current answer to the prior query or prior scope when inherited context is used.
- Every conflict-present result must identify the affected answer item or trace path.

## Required Reporting Object
Each evaluation run must emit a structured report containing:
- corpus coverage metrics
- fixture pass/fail results
- query-family precision metrics
- false definitive answer counts
- unresolved scope counts by family
- contradiction visibility counts
- trace completeness metrics
- release class evaluated
- policy version used

## Reliability Anti-Patterns
The system must be treated as unreliable if it exhibits any of the following:
- accepted answers built from unresolved xrefs
- accepted answers built from raw table text without normalized row/cell traversal
- accepted answers with hidden compliance-path defaults
- accepted answers where a high-impact assumption is present only in prose
- accepted answers that cannot replay to source locators
- release dashboards that report fixture success but omit corpus coverage
- accepted answers whose trace completeness is below the required threshold for the release class
- accepted answers that reuse prior scope without an explicit contradiction check when follow-up context is present

## Dependencies
This specification depends on:
- `Spec/02_corpus_canonicalization_spec.md`
- `Spec/03_scope_resolution_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/08_golden_fixtures_spec.md`

Any change to release gates or KPI semantics must update the relevant fixture packs and query schemas if user-facing statuses are affected.
