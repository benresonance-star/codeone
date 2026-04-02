# NCC Ingestion & Agentic Compliance System  
## Full Specification (with Embedded Validation Contract)  
### Version 5.0.0

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

PDF → Ingestion → Validation Contract → Pass → Semantic Layer  
                                     → Fail → STOP  

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
- gate behavior for progression to the semantic layer

---

# 5. INGESTION PIPELINE

1. Load PDF  
2. Extract blocks  
3. Classify blocks  
4. Extract tables  
5. Align XML  
6. Attach metadata  
7. Run validation contract  
8. If fail → STOP  
9. If pass → store  

---

# 6. CANONICAL DATA MODEL

All snippets must originate from validated ingestion.

---

# 7. AGENT CONSTRAINTS

Agents must:
- obey validation contract  
- not bypass rules  
- not hallucinate data  

---

# 8. UI REQUIREMENTS

UI must:
- display validation results  
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

---

# 10. DATABASE

- snippets  
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

If validation fails, the system must stop.

---

# END SPEC
