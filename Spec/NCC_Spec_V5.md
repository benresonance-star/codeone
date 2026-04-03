# NCC Ingestion & Agentic Compliance System  
## Full Specification (with Embedded Validation Contract)  
### Version 5.3.0

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

The PDF and XML ingestion validation contracts are non-bypassable rule systems that:

- validates all ingestion outputs  
- blocks invalid data  
- standardizes ingestion quality  
- constrains both humans and agents  

---

## Location

/Spec/pdf_ingestion_contract.md  
/Spec/pdf_ingestion_contract.json  
/Spec/xml_source_contract.md  
/Spec/xml_source_contract.json  
/Spec/validation_result.schema.json  

---

## Enforcement Flow

XML + PDF → Ingestion + Validation Contracts → Pass / Pass_With_Warnings → Alignment Layer  
                                              → Review_Required → HITL Review  
                                              → Fail / Blocked → STOP  

Alignment Layer → Candidate Extraction Layer → Candidate Validation Layer  
Candidate Validation Layer → Promote → Semantic Layer  
Candidate Validation Layer → Reject / Review → STOP  

---

## Contract Source Of Truth

The authoritative validation contracts are externalized in:

- `/Spec/pdf_ingestion_contract.json`
- `/Spec/pdf_ingestion_contract.md`
- `/Spec/xml_source_contract.json`
- `/Spec/xml_source_contract.md`
- `/Spec/validation_result.schema.json`

Those files define:

- deterministic rule thresholds and outcomes
- XML/PDF relationship expectations
- required PDF validation output structure
- gate behavior for progression into downstream candidate-stage processing

---

# 5. INGESTION PIPELINE

1. Load PDF and XML  
2. Extract blocks and tables  
3. Attach structural metadata  
4. Synthesize row-level XML nodes for narrow table artifacts where appropriate  
5. Synthesize row-sized PDF fragments from extracted tables where appropriate  
6. Run XML and PDF validation contracts  
7. If blocked → STOP  
8. If review required → hold for human review  
9. Scope broad part-wrapper PDF evidence before alignment when the XML only represents wrapper or intro content  
10. Align XML and PDF evidence  
11. Generate candidates  
12. Validate candidates  
13. If candidate validation fails → STOP  
14. Promote validated candidates to semantic snippets  
15. Store  

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
- surface focused review workspaces for narrow XML artifacts, including row-level review items for narrow table XMLs  
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

Current ingestion and review behavior:
- narrow table XMLs may align at row level through synthesized XML row nodes and row-sized PDF fragments
- focused review mode may reduce a large fragment set to only the most relevant row-level evidence for narrow artifacts
- broad NCC `part` XMLs should no longer be treated as malformed merely because they use corpus-native structural roots
- broad `part` wrapper XML pairings may narrow the PDF evidence set to the relevant part-introduction band before parity checks so they degrade to reviewable outcomes rather than failing for the wrong reasons

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
