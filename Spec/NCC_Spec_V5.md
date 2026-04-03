# NCC Ingestion & Agentic Compliance System  
## Full Specification (with Embedded Validation Contract)  
### Version 5.2.0

---

# 1. PURPOSE

This system ingests, structures, evaluates, and reports on the National Construction Code (NCC) with:

- deterministic execution  
- full traceability  
- agent-safe reasoning  
- strict validation gates  

The system must ensure:

No invalid data enters the canonical layer.

---

# 2. CORE PRINCIPLES

- Deterministic structure over interpretation  
- Explicit uncertainty  
- Contract-driven execution  
- Modular architecture  
- Validation before progression  
- Traceability to source  
- Controlled learning  

---

# 3. SYSTEM LAYERS

Source Layer  
Ingestion Layer  
Validation Contract Layer (critical)  
Alignment Layer  
Candidate Extraction Layer  
Candidate Validation Layer  
Semantic Layer  
Operational Layer  
Evaluation Layer  
Agent Layer  
UI Layer  
Reporting Layer  
Diff Layer  
Learning Layer  

---

# 4. VALIDATION CONTRACT SYSTEM

## Definition

The PDF Ingestion Validation Contract is a non-bypassable rule system that:

- validates all ingestion outputs  
- blocks invalid data  
- standardizes ingestion quality  
- constrains both humans and agents  

---

## Location

/Spec/pdf_ingestion_contract.md  
/Spec/pdf_ingestion_contract.json  
/Spec/validation_result.schema.json  

---

## Enforcement Flow

XML + PDF → Ingestion + Validation Contracts → Pass → Alignment Layer  
                                              → Fail → STOP  

Alignment Layer → Candidate Extraction Layer → Candidate Validation Layer  
Candidate Validation Layer → Promote → Semantic Layer  
Candidate Validation Layer → Reject / Review → STOP  

---

## Contract Source Of Truth

The authoritative PDF validation contract is externalized in:

- `/Spec/pdf_ingestion_contract.json`
- `/Spec/pdf_ingestion_contract.md`
- `/Spec/validation_result.schema.json`

Those files define:

- deterministic rule thresholds and outcomes
- XML/PDF relationship expectations
- required PDF validation output structure
- gate behavior for progression into downstream candidate-stage processing

---

# 5. INGESTION PIPELINE

1. Load PDF  
2. Extract blocks  
3. Classify blocks  
4. Extract tables  
5. Attach metadata  
6. Run validation contracts  
7. If fail → STOP  
8. Align XML  
9. Generate candidates  
10. Validate candidates  
11. If candidate validation fails → STOP  
12. Promote validated candidates to semantic snippets  
13. Store  

---

# 6. CANONICAL DATA MODEL

All canonical snippets must originate from validated candidate objects.
No semantic object may be created directly from aligned source data.

---

# 7. AGENT CONSTRAINTS

Agents must:
- obey validation contract  
- produce or consume candidates before canonical snippets  
- not bypass rules  
- not hallucinate data  

---

# 8. UI REQUIREMENTS

UI must:
- display validation results  
- display candidate objects with XML/PDF traceability  
- surface in-flight validation progress while a run is executing  
- accept transitional lineage-backed review payloads until the first-class candidate runtime is fully implemented  
- highlight errors  
- allow corrections  
- re-run validation  

---

# 9. SYSTEM ARCHITECTURE

Frontend:
- React
- Next.js
- TypeScript

Backend:
- FastAPI
- PostgreSQL
- Redis

Persistence identifiers:
- `document_family_id` must be deterministic for a given PDF/XML pair
- when the natural paired-name identifier is too long for storage constraints, the system may shorten it with a stable hash suffix rather than fail ingestion

---

# 10. DATABASE

- snippets  
- candidates  
- candidate_validation_results  
- candidate_relations  
- source_documents  
- alignments  
- contexts  
- evaluations  
- snapshots  

---

# 11. TESTING

- validation tests  
- ingestion tests  
- failure simulation  

---

# 12. FINAL RULE

If validation fails, alignment must not progress.
If candidate validation fails, semantic promotion must not progress.

---

# END SPEC
