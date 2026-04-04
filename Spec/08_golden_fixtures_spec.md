# Golden Fixtures Specification

## Status
- Version: `1.0.0`
- Status: normative

## Purpose
This specification defines the fixture packs required to test the restructured NCC architecture end to end.

The fixture set must validate:
- source fidelity
- corpus canonicalization
- scope resolution
- relationship and overlay handling
- query answer safety

## Core Rule
Fixtures must test where the system is most likely to look correct while being wrong.

Each fixture pack must be:
- small enough to inspect manually
- explicit about expected outputs
- aligned to the schema and ontology layer
- designed to expose one dominant risk

## Standard Fixture Pack Structure

```text
tests/fixtures/<fixture_id>/
├── README.md
├── source/
│   ├── fixture.xml
│   ├── fixture.pdf
│   ├── glossary.json
│   └── mapping.json
├── expected/
│   ├── assertions.json
│   ├── canonical_candidates.json
│   ├── relationships.json
│   ├── overlays.json
│   ├── resolved_scope.json
│   ├── query_request.json
│   ├── query_result.json
│   └── human_answer.md
└── notes/
    ├── rationale.md
    └── edge_cases.md
```

## Required Fixture Families

### F1. Clean deterministic clause
Purpose:
- baseline correctness

Must prove:
- stable candidate resolution
- explicit reference resolution
- answer replay

### F2. Candidate boundary mismatch
Purpose:
- protect the candidate stability gate

Must prove:
- unresolved boundaries do not flow into query-ready graph objects

### F3. Table note and footnote scope
Purpose:
- protect row/cell-local meaning

Must prove:
- table note, row note, and cell footnote are not widened incorrectly

### F4. Definition scope trap
Purpose:
- prevent glossary overreach

Must prove:
- defined term meaning does not leak outside allowed scope

### F5. Exception and condition chain
Purpose:
- validate multi-hop normative reasoning

Must prove:
- exceptions, conditions, and definitions survive into the final answer path

### F6. Contradiction surfaced
Purpose:
- ensure honesty under conflict

Must prove:
- contradiction is visible in machine result and human answer

### F7. Real R-Value flagship fixture
Purpose:
- validate the flagship user query against real NCC-style structure

Must prove:
- clause to table routing
- location to climate-zone mapping
- row/cell note handling
- conditional branching
- safe refusal when unresolved construction scope changes the answer

### F8. Override preservation
Purpose:
- validate human correction without loss of machine history

Must prove:
- override changes publication state without deleting prior assertions or traces

### F9. Jurisdiction and climate ambiguity
Purpose:
- ensure ambiguous location mapping fails safely

Must prove:
- a single place-name query that could map to multiple jurisdictions or climate-zone paths does not produce a definitive normative answer
- the result either requests scope confirmation or returns explicitly separated candidate scopes

### F10. Performance-vs-DTS path trap
Purpose:
- prevent silent fallback from Performance-style questions to DTS-only answers

Must prove:
- Performance or hybrid-path intent is detected
- DTS-only material is not presented as an `accepted` answer for a Performance path without an explicit limitation or refusal

### F11. Follow-up contradiction
Purpose:
- prevent unsafe reuse of prior conversation scope

Must prove:
- a follow-up query that contradicts stored scope forces contradiction detection, scope refresh, or confirmation
- previously inherited answer items are not reused silently when new scope changes the governing path

### F12. Overlay conflict and precedence
Purpose:
- validate baseline-versus-overlay ordering and honest conflict handling

Must prove:
- overlay application order is explicit
- baseline and overlay traces remain separately visible
- unresolved overlay conflicts downgrade the result status

### F13. Building-class synonym trap
Purpose:
- prevent unsafe mapping from plain-language occupancy terms to NCC classes

Must prove:
- ambiguous plain-language building descriptions do not get silently promoted into a definitive `building_class`
- the engine requests confirmation or returns an explicitly provisional result

### F14. Multi-hop note-to-clause-to-table routing
Purpose:
- validate real multi-hop governing paths

Must prove:
- a note or callout can route interpretation from a selected table cell to a clause and then to a secondary governing table
- the final answer trace preserves that full dependency chain

## Real Flagship Fixture Requirements
The flagship fixture must not be a purely synthetic happy-path example. It must represent a real NCC-shaped query path.

### Fixture ID
- `fixture_rvalue_query_real_01`

### Minimum source shape
- one climate mapping table including `Melbourne -> Victoria -> climate zone 6`
- one governing clause that routes to climate-zone-specific tables
- one climate-zone-specific table family
- row and cell structure sufficient to distinguish at least two construction branches
- at least one note or callout that affects interpretation
- one optional exception or overlay branch

### Required NCC-shaped source characteristics
The flagship fixture must mirror real NCC document complexity rather than an oversimplified synthetic table:
- publisher-local or remapped xref structure
- clause-to-table routing similar to energy-efficiency provisions
- table-local note or desc-note structure
- at least one state-variation or overlay-like branch when relevant

Representative source shapes should be taken from files such as:
- `Spec/NCC 2022/XMLs/13-2-3-roofs and ceilings.xml`
- `Spec/NCC 2022/XMLs/table-3-climate-zones-for-thermal-design.xml`
- `Spec/NCC 2022/XMLs/D3D24-doorways-and-doors.xml`

### Required query
- "What are the required minimum R-Values for a Class 2 building in Melbourne?"

### Required resolved-scope behavior
- `edition` explicit or system defaulted with provenance
- `jurisdiction = Victoria`
- `location = Melbourne`
- `climate_zone = 6`
- `building_class = Class 2`
- `compliance_path = DTS` only if defaulted under policy

### Required result behavior
The result must do one of the following:
- return multiple conditionally scoped answer items for the plausible branches, or
- return `requires_scope_confirmation`

It must not:
- collapse multiple construction branches into one value
- skip note or footnote scope
- present a definitive answer if the governing row/cell depends on unresolved construction detail

### Required answer trace
Each answer item must trace to:
- governing clause ID
- governing table ID
- selected row ID
- selected cell ID
- relevant note or exception ID
- source locators

## Branching Variant Fixture
To stop the system from overfitting the happy path, add:
- `fixture_rvalue_query_branching_01`

This variant must include:
- same top-level query family
- two plausible construction branches with different answers
- one unresolved branch-selection input

Expected result:
- `requires_scope_confirmation` or `accepted_with_assumptions`

## Additional Dominant-Risk Fixture Requirements

### Ambiguity fixture
Fixture ID:
- `fixture_location_ambiguity_01`

Must include:
- one place name or project description that admits more than one mapping path
- explicit expected candidate scopes

Expected result:
- `requires_scope_confirmation` or a deliberately split provisional response

### Performance path fixture
Fixture ID:
- `fixture_performance_path_trap_01`

Must include:
- one query whose wording indicates Performance Solution or hybrid compliance intent
- one DTS candidate path that would look plausible but is not sufficient

Expected result:
- no silent DTS `accepted` answer

### Follow-up contradiction fixture
Fixture ID:
- `fixture_followup_scope_contradiction_01`

Must include:
- one initial accepted or provisional answer
- one follow-up query that changes or contradicts a previously inherited scope dimension

Expected result:
- contradiction surfaced explicitly
- prior scope inheritance re-evaluated before answer construction

### Overlay precedence fixture
Fixture ID:
- `fixture_overlay_precedence_01`

Must include:
- one baseline rule
- one overlay or replacement branch
- one unresolved or competing precedence scenario

Expected result:
- baseline and overlay traces visible independently
- unresolved precedence downgrades top-level result status

### Building-class synonym fixture
Fixture ID:
- `fixture_building_class_synonym_trap_01`

Must include:
- one plain-language building description that plausibly maps to more than one NCC class path

Expected result:
- no silent class promotion without confirmation or explicit assumption

### Multi-hop routing fixture
Fixture ID:
- `fixture_multihop_note_clause_table_01`

Must include:
- a table selection
- a note or callout that redirects interpretation to a clause
- a secondary clause or table dependency

Expected result:
- answer trace contains the full multi-hop path

## Coverage Metadata
Each fixture must include metadata fields such as:
- `fixture_id`
- `primary_risk`
- `query_family`
- `query_critical`
- `expected_top_level_status`
- `required_coverage_gates`

## Fixture Authoring Rules
1. Write expected outputs before running the system.
2. Use schema-valid expected objects.
3. Include at least one answer-to-source replay path.
4. Keep ambiguity explicit rather than implied.
5. Include note and overlay behavior where they materially affect the answer.
6. Prefer actual NCC-shaped structures for flagship fixtures over oversimplified synthetic examples.
7. For query-critical fixtures, include enough structure to test replay from answer item to source locator.
8. When a fixture depends on stored prior context, expected outputs must include the prior scope or prior answer references used by the query contract.

## Minimum Initial Build Order
1. `fixture_clean_clause_01`
2. `fixture_candidate_split_01`
3. `fixture_table_note_row_01`
4. `fixture_definition_scope_01`
5. `fixture_exception_chain_01`
6. `fixture_contradiction_01`
7. `fixture_rvalue_query_real_01`
8. `fixture_rvalue_query_branching_01`
9. `fixture_location_ambiguity_01`
10. `fixture_performance_path_trap_01`
11. `fixture_followup_scope_contradiction_01`
12. `fixture_overlay_precedence_01`
13. `fixture_building_class_synonym_trap_01`
14. `fixture_multihop_note_clause_table_01`
15. `fixture_override_01`

## Release Requirement
The system is not considered ready for serious user-facing NCC query support unless the real R-Value fixture family passes honestly.

Passing means:
- correct top-level status
- explicit scope handling
- correct branch handling
- complete answer trace
- no silent guessing

The system is not considered high-trust unless the ambiguity, follow-up contradiction, overlay precedence, and Performance-path trap fixtures also pass honestly.

## Dependencies
These fixtures must align with:
- `Spec/03_scope_resolution_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/07_reliability_and_coverage_spec.md`
- `Spec/schemas/*.schema.json`
