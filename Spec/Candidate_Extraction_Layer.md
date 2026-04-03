# CANDIDATE EXTRACTION LAYER

## First-class mandatory system stage

---

# 1. DEFINITION

The Candidate Extraction Layer is a mandatory system layer that transforms:

Validated XML + Validated PDF + Alignment
→ Structured Candidate Objects

A candidate is a proposed semantic object derived from aligned source data, not yet accepted into the canonical system.

This layer ensures that:
- semantic interpretation is staged and inspectable  
- transformation decisions are explicit  
- agents are constrained before committing to canonical structures  

This layer is normative within the NCC system architecture and sits between the Alignment Layer and the Semantic Layer defined in `Spec/NCC_Spec_V5.md`.
Its contract language must stay consistent with `Spec/pdf_ingestion_contract.md` and `Spec/xml_source_contract.md`.

---

# 2. PURPOSE

The Candidate Extraction Layer exists to:

- prevent direct conversion from source → canonical snippets  
- provide a reviewable intermediate representation  
- enable validation of semantic intent  
- support human and agent collaboration  
- reduce downstream error propagation  

---

# 3. POSITION IN SYSTEM

XML (validated)
PDF (validated)
        ↓
Alignment (validated)
        ↓
Candidate Extraction Layer
        ↓
Candidate Validation Layer
        ↓
Semantic Layer (canonical snippets)

No direct Alignment → Semantic path is permitted.

---

# 4. CORE RULE

No canonical snippet may be created directly from aligned source data.  
All snippets must originate from validated candidate objects.

---

# 5. CANDIDATE OBJECT SCHEMA

{
  "candidate_id": "string",
  "candidate_type": "rule | table | definition | reference | context_key | ignore | ambiguous",

  "source": {
    "xml_node_id": "string",
    "pdf_fragment_id": "string",
    "alignment_confidence": "number"
  },

  "proposed": {
    "snippet_id": "string",
    "display_name": "string",
    "description": "string"
  },

  "status": "draft | validated | rejected | promoted",

  "confidence": {
    "overall": "number",
    "sources": {
      "alignment": "number",
      "structure": "number"
    }
  },

  "validation_state": "pending | pass | fail | requires_review",

  "depends_on": ["candidate_ids"],

  "notes": "string or null"
}

---

# 6. CANDIDATE TYPES

- rule
- table
- definition
- reference
- context_key
- ignore
- ambiguous

---

# 7. CANDIDATE LIFECYCLE

draft → validated → promoted  
       ↘ rejected  

---

# 8. CANDIDATE VALIDATION

All candidates must be validated before promotion.

Validation must check:
- required fields present  
- valid candidate_type  
- source references exist  
- alignment confidence acceptable  
- no conflicting dependencies  

---

# 9. PROMOTION RULES

A candidate may only be promoted if:
- validation_state = pass  
- confidence ≥ threshold  
- no blocking dependencies  
- not ambiguous  

---

# 10. AGENT CONSTRAINTS

Agents MUST:
- produce candidates before snippets  
- assign candidate types  
- include source references  
- include confidence values  
- treat candidate validation as a hard gate before promotion  

Agents MUST NOT:
- create snippets directly  
- skip validation  

---

# 11. UI REQUIREMENTS

UI must allow:
- view candidate with XML + PDF  
- promote  
- reject  
- split  
- merge  
- mark ambiguous  

---

# 12. STORAGE

- candidates  
- candidate_validation_results  
- candidate_relations  

---

# 13. TRACEABILITY

PDF ↔ XML → Candidate → Snippet → Evaluation → Output

Schema compatibility note:
- existing validation result schemas may continue using current gate field names during the transition
- gate naming compatibility must not be interpreted as permission to bypass the candidate stage
- a future schema revision may introduce explicit candidate-stage gate fields once the implementation layer is promoted from planned to active

---

# 14. FINAL RULE

The Candidate Extraction Layer is mandatory and non-bypassable.
