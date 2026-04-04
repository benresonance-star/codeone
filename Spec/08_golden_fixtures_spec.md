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

## Minimum Initial Build Order
1. `fixture_clean_clause_01`
2. `fixture_candidate_split_01`
3. `fixture_table_note_row_01`
4. `fixture_definition_scope_01`
5. `fixture_exception_chain_01`
6. `fixture_contradiction_01`
7. `fixture_rvalue_query_real_01`
8. `fixture_rvalue_query_branching_01`
9. `fixture_override_01`

## Release Requirement
The system is not considered ready for serious user-facing NCC query support unless the real R-Value fixture family passes honestly.

Passing means:
- correct top-level status
- explicit scope handling
- correct branch handling
- complete answer trace
- no silent guessing

## Dependencies
These fixtures must align with:
- `Spec/03_scope_resolution_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/07_reliability_and_coverage_spec.md`
- `Spec/schemas/*.schema.json`
