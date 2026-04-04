# Source Contracts Index

## Purpose
This directory is the normative index for source-ingestion contracts.

The underlying XML and PDF contracts remain at their current repository paths for compatibility with existing tooling. This index exists so the restructured specification set has a stable place to describe them without moving files that may already be referenced by code or tests.

## Authoritative Files

| Concern | File | Status |
|---|---|---|
| XML source validation | `Spec/xml_source_contract.md` | Normative |
| XML machine contract | `Spec/xml_source_contract.json` | Normative |
| PDF ingestion validation | `Spec/pdf_ingestion_contract.md` | Normative |
| PDF machine contract | `Spec/pdf_ingestion_contract.json` | Normative |
| Cross-stage validation result | `Spec/validation_result.schema.json` | Normative |
| XML validation result | `Spec/xml_validation_result.schema.json` | Normative |

## Ownership Boundary
The source contracts own:
- raw source preservation requirements
- extraction validation rules
- pass / warning / review / fail gate semantics
- source-level schema expectations

They do not own:
- canonical corpus graph normalization
- query-time scope resolution
- query result contracts
- answer reliability KPIs

Those concerns are owned by:
- `Spec/02_corpus_canonicalization_spec.md`
- `Spec/03_scope_resolution_spec.md`
- `Spec/06_query_resolution_spec.md`
- `Spec/07_reliability_and_coverage_spec.md`

## Compatibility Rule
Existing automation may continue to reference the original root-level contract file paths. The presence of this index must not be interpreted as permission to relocate or rename those files without a coordinated migration.
