# CANDIDATE EXTRACTION LAYER

## First-class mandatory system stage

---

# 1. DEFINITION

The Candidate Extraction Layer is a mandatory system layer that transforms:

Validated XML
+ XML semantic units
+ gathered PDF evidence
→ Structured Candidate Objects

A candidate is a proposed semantic object derived from XML-seeded semantic units plus gathered PDF evidence, not yet accepted into the canonical system.

This layer ensures that:
- semantic interpretation is staged and inspectable  
- transformation decisions are explicit  
- agents are constrained before committing to canonical structures  

This layer is normative within the NCC system architecture and sits between the Alignment Layer and the Semantic Layer defined in `Spec/NCC_Spec_V5.md`.
The layer operates as a dual-engine runtime:
- a `CandidateObject` engine that reconciles XML-seeded units with gathered PDF evidence into workflow-bearing candidate facts
- a `CandidateRelation` engine that extracts explicit, resolved, unresolved, and inferred links over those same units
- a reconciliation stage that compares both outputs before validation and promotion decisions rely on them

A **Clause Semantic Enrichment** stage runs after candidate objects are extracted from XML-seeded units and PDF evidence, and before candidate validation and promotion; it adds inspectable semantic metadata (relations, glossary links, applicability, graph-oriented edges) without replacing the validated candidate as the authority for workflow state.
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

XML (validated) + PDF (validated)
                ↓
        XML Semantic Units
                ↓
        Gather PDF Evidence
                ↓
   CandidateObject Engine
                ↓
  CandidateRelation Engine
                ↓
    Reconciliation Layer
                ↓
  Clause Semantic Enrichment (staged)
                ↓
   Candidate Validation Layer
                ↓
Semantic Layer (canonical snippets)

No direct Alignment → Semantic path is permitted.
Alignment remains evidence-gathering input, not the long-term candidate identity model.

**Clause Semantic Enrichment** is a mandatory ordering constraint, not an optional post-processing step: enrichment outputs must attach to existing candidate identities and must not substitute a parallel “shadow” candidate state for validation or promotion. Enrichment may refine labels and propose graph-oriented links; it does not relax the requirement that validation and promotion operate on the same candidate records produced by extraction.

---

# 3b. DUAL-ENGINE RUNTIME MODEL

The Candidate Extraction Layer must expose two coordinated but distinct runtime engines:

- `CandidateObject` engine:
  builds workflow-bearing semantic facts from XML semantic units plus PDF evidence
- `CandidateRelation` engine:
  extracts first-class links such as explicit XML references, clause-to-clause references, glossary relations, applicability dependencies, exceptions, and other reviewable semantic edges
- reconciliation stage:
  compares object and relation outputs, records mismatches or unresolved dependencies, and emits inspectable review artifacts before promotion decisions are made

The runtime must not collapse these engines into a single opaque enrichment pass. Relations may be attached to candidate records for convenience, but relation extraction remains a first-class output with its own authority, evidence, and resolution state.

---

# 4. CORE RULE

No canonical snippet may be created directly from aligned source data.  
All snippets must originate from validated candidate objects.

The relation engine may enrich, challenge, or constrain those candidate objects, but it may not silently replace them.

---

# 4b. STAGED AUTHORITY MODEL

The dual-engine model uses staged authority rather than immediate shared authority:

- `CandidateObject` remains the primary workflow-bearing authority for initial validation and promotion
- `CandidateRelation` is first-class for reasoning, traceability, and dependency capture from day one
- reconciliation outputs may immediately create review requirements and unresolved dependency records
- specific relation classes may later become promotion-relevant once their extraction and resolution rules are stable

Initial relation classes most likely to move into promotion-relevant status are:
- clause references
- exceptions
- notes with normative effect
- applicability dependencies

Until a relation class is explicitly promoted into blocking behavior, unresolved relation findings must remain inspectable and reviewable rather than silently ignored.

---

# 5. CANDIDATE OBJECT SCHEMA

{
  "candidate_id": "string",
  "semantic_unit_id": "string",
  "candidate_type": "candidate_semantic_class (compatibility alias)",

  "classification": {
    "xml_structural_class": "rule | title | table | definition | reference | note | context_key | ambiguous",
    "pdf_evidence_class": "paragraph | heading | list_item | table_row | table_cell | unknown",
    "candidate_semantic_class": "rule | title | table | definition | reference | note | context_key | ambiguous"
  },

  "source": {
    "xml_node_id": "string",
    "pdf_fragment_id": "string or null",
    "alignment_confidence": "number"
  },

  "evidence": [
    {
      "fragment_id": "string",
      "page": "number",
      "bbox": ["number", "number", "number", "number"],
      "text": "string",
      "confidence": "number",
      "pdf_evidence_class": "paragraph | heading | list_item | table_row | table_cell | unknown"
    }
  ],

  "proposed": {
    "snippet_id": "string",
    "display_name": "string",
    "description": "string",
    "content": "string"
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

  "notes": "string or null",

  "semantic_enrichment": {
    "enrichment_run_id": "string or null",
    "enrichment_version": "string or null",

    "glossary_links": [
      {
        "term_id": "string or null",
        "label": "string",
        "ref": "string or null"
      }
    ],

    "applicability_conditions": ["string"],

    "candidate_relations": [
      {
        "relation_id": "string",
        "relation_kind": "string",
        "relation_authority": "xml_explicit | text_resolved | text_unresolved | layout_inferred | manual_review_required",
        "direction": "outbound | inbound | undirected",
        "target_candidate_id": "string or null",
        "target_semantic_unit_id": "string or null",
        "target_locator": "string or null",
        "resolution_status": "resolved | unresolved | ambiguous | review_required",
        "confidence": "number",
        "evidence_fragment_ids": ["string"],
        "evidence_spans": ["string"],
        "provenance": {
          "source_authority": "xml_authoritative | pdf_grounded | heuristic | manual_review",
          "source_fields": ["string"]
        }
      }
    ],

    "implicit_relation_candidates": [
      {
        "suggested_relation_kind": "string",
        "target_candidate_id": "string or null",
        "target_semantic_unit_id": "string or null",
        "confidence": "number",
        "rationale": "string or null"
      }
    ],

    "graph_edges": [
      {
        "edge_id": "string",
        "from_id": "string",
        "to_id": "string",
        "edge_kind": "string",
        "metadata": "object"
      }
    ],

    "enrichment_hints": {
      "notes": "string or null",
      "tags": ["string"]
    },

    "field_authority": {
      "candidate_relations": "xml_authoritative | mixed | heuristic",
      "applicability_conditions": "structured_scope_pending | heuristic | mixed",
      "graph_edges": "projection_only"
    }
  }
}

---

# 5b. FIRST-CLASS RELATION AND RECONCILIATION RECORDS

These artifacts are runtime peers of candidate objects even when emitted inside candidate-scoped envelopes or lineage payloads:

`CandidateRelation`

{
  "relation_id": "string",
  "relation_kind": "string",
  "relation_authority": "xml_explicit | text_resolved | text_unresolved | layout_inferred | manual_review_required",
  "source_candidate_id": "string",
  "target_candidate_id": "string or null",
  "source_semantic_unit_id": "string",
  "target_semantic_unit_id": "string or null",
  "target_locator": "string or null",
  "resolution_status": "resolved | unresolved | ambiguous | review_required",
  "confidence": "number",
  "provenance": {
    "source_authority": "xml_authoritative | pdf_grounded | heuristic | manual_review",
    "source_fields": ["string"],
    "evidence_fragment_ids": ["string"],
    "evidence_spans": ["string"]
  }
}

`ReconciliationRecord`

{
  "reconciliation_id": "string",
  "source_candidate_ids": ["string"],
  "source_relation_ids": ["string"],
  "classification": "match | gap | contradiction | overreach | review_required",
  "promotion_effect": "none | advisory_only | blocks_selected_relation_classes | blocks_all",
  "review_required": "boolean",
  "notes": "string or null"
}

---

# 5c. ENRICHMENT DRIFT RISK (ADVISORY)

Agents, UI layers, and runtime stages that consume enriched candidate payloads should treat **validated candidate state** (including validation outcome, review decisions, and promotion eligibility) as the operational source of truth for whether a candidate may progress.

Semantic enrichment—including explicit relations, glossary links, applicability conditions, implicit relation candidates, and graph edges—is **advisory** with respect to workflow gates: it must not be used to bypass, silently override, or “repair” validated candidate state without an explicit, inspectable reconciliation step. Implementations should warn operators and agent authors when enrichment-derived structure could diverge from stored candidate validation (for example, proposed edges that conflict with rejected or ambiguous candidates). This warning is **not** a new blocking rule in the validation contract; it exists to reduce accidental drift away from the candidate-first pipeline toward ad hoc graph or glossary semantics.

---

# 6. THREE-SCHEMA MODEL

Candidate extraction must reconcile three different but linked schemas:

- XML structural schema:
  the XML element name, path, ancestry, and normalized node identity
- PDF evidence schema:
  the rendered PDF evidence class, page provenance, bounding box, and fragment identity
- Candidate semantic schema:
  the system's proposed semantic interpretation for downstream validation and graph use

The candidate semantic schema must not be treated as a direct copy of either XML or PDF.
It is a reconciled layer.

Current rule:
- XML structural class is primary for semantic typing when a valid XML node is linked
- PDF evidence class remains first-class and must be retained for review, debugging, and future graph queries
- workflow state such as `draft`, `validated`, `rejected`, or `promoted` is separate from semantic class and must not be overloaded into `candidate_type`
- relation authority is separate again: a relation may be XML-explicit, text-resolved, text-unresolved, layout-inferred, or manual-review-required without changing the candidate object's semantic class by itself

---

# 7. CANDIDATE TYPES

- rule
- title
- table
- definition
- reference
- note
- context_key
- ignore
- ambiguous

---

# 8. CANDIDATE LIFECYCLE

draft → validated → promoted  
       ↘ rejected  

---

# 9. CANDIDATE VALIDATION

All candidates must be validated before promotion.

Validation must check:
- required fields present  
- valid candidate_type  
- source references exist  
- alignment confidence acceptable  
- no conflicting dependencies  
- any reconciliation records marked as blocking for the currently promoted relation classes

---

# 10. PROMOTION RULES

A candidate may only be promoted if:
- validation_state = pass  
- confidence ≥ threshold  
- no blocking dependencies  
- not ambiguous  
- no staged-authority relation finding has escalated into a blocking reconciliation outcome for that candidate

---

# 11. AGENT CONSTRAINTS

Agents MUST:
- produce candidates before snippets  
- assign candidate types  
- preserve XML structural class and PDF evidence class alongside the candidate semantic class  
- include source references  
- include confidence values  
- treat candidate validation as a hard gate before promotion  

Agents MUST NOT:
- create snippets directly  
- skip validation  

---

# 12. UI REQUIREMENTS

UI must allow:
- view candidate with XML + PDF  
- inspect XML structural class, PDF evidence class, and candidate semantic class side by side  
- promote  
- reject  
- split  
- merge  
- mark ambiguous  

---

# 13. STORAGE

- xml_semantic_units
- pdf_evidence_packets
- candidates  
- candidate_validation_results  
- candidate_relations  
- reconciliation_records
- semantic_enrichment_attachments (or embedded `semantic_enrichment` on candidate records)
- enrichment_graph_edge_store (logical store for `graph_edges` materialized from candidates)
- candidate_review_projections
- classification facets for XML, PDF, and candidate semantic layers  

---

# 14. CANDIDATE ROBUSTNESS AND GRAPH-READINESS (RUNTIME)

Backend ingestion may emit additive, inspectable payloads on `lineage` and `review_workspace`:

- **`candidate_quality`**: counts for the current run—semantic units, PDF evidence packets, candidate objects, review units, promoted canonical snippets, and foundational baseline slice eligibility, inclusion, and coverage ratio. Carries `schema_version` and `generated_at`.
- **`graph_readiness`**: deterministic summary with `ready_for_graph_handoff` and a `gates` list (`gate_id`, `passed`, `detail`). Gates are conservative and advisory; they do not replace PDF/XML validation or candidate promotion rules.
- **`foundational_baseline_corpus`**: deterministic slice (sorted, capped) over lower-risk categories such as definitions/glossary, titles and context keys, notes, and interpretive paths (for example intro or title bands). Items expose candidate/node identifiers, baseline category, status, text preview, and evidence summary for UI tabs.
- **`pdf_clause_candidates` / `assembled_clause` / `display_projection`**: review-oriented PDF clause projections may be emitted for UI inspection. In temporary `pdf_only` review mode, they may define candidate identity before XML reconciliation is restored as the primary inventory driver.
- **style-aware PDF codification**: when a secondary appearance pass is available, structured PDF blocks may carry additive `metadata.style_codification` signals such as relative font size, emphasis, heading-likeness, likely-running-chrome detection, page-frame exemptions, and structural-heading kind/title. These signals are review-facing and inspectable; they refine PDF-native clause assembly and ancestry without replacing candidate identity.
- **explicit PDF structural ancestry**: `assembled_clause` and `display_projection` may carry `parent_heading_clause_id`, `parent_heading_block_id`, `parent_heading_label`, `parent_heading_text`, `parent_heading_title`, and `structural_path`. `structural_path` is an ordered ancestry stack whose entries may expose `kind`, `label`, `text`, `title`, `block_id`, and `candidate_id` where available.
- **page-span and page-frame context**: PDF-native projections may additionally expose `start_page`, `end_page`, `pages`, and `page_context` so multi-page clauses and running page metadata remain inspectable in review mode.

**Authority vs heuristic:** Top-level `explicit_relations`, `glossary_links`, `applicability_conditions`, and `implicit_relation_candidates` are unchanged. Each enriched candidate may include nested `semantic_enrichment` with `field_authority`—explicit XML-sourced relations are `xml_authoritative`; text-resolved relations are `mixed`; glossary links, applicability extraction, and implicit text hints are marked as heuristic unless separately promoted. `enrichment_summary` may include the same `field_authority` map for aggregate use.

**Representative validation matrix:** Candidate robustness should be exercised across at least these document slices before graph hardening:
- front matter / orientation material
- structure and title-heavy wrappers
- glossary / definitions schedules
- narrow clause material
- narrow table / row-heavy material
- mixed-content sections with explicit references

For each slice, operators should inspect:
- semantic unit count vs expected XML inventory
- evidence packet coverage
- candidate count and review count
- foundational baseline coverage where applicable
- unresolved explicit-relation count
- unresolved text-resolved or text-unresolved relation count
- promotion refusal when validation remains unresolved

**Boundary discipline:** Robustness validation should continue treating the pipeline stages as separate and inspectable:
- semantic unit creation defines inventory only
- PDF evidence gathering attaches traceable support only
- candidate extraction creates workflow-bearing candidate state
- temporary `pdf_only` review may derive those candidate records from structured PDF clauses first, but this remains a review-stage projection rather than a canonical promotion authority change
- in that `pdf_only` mode, parent/root lineage for review may be derived from PDF structural ancestry (`parent_heading_*` and `structural_path`) rather than XML node lineage
- relation extraction and reconciliation create inspectable dependency state without replacing candidate identity
- semantic enrichment annotates those same candidates without replacing them
- canonical promotion remains downstream of candidate validation

**Graph-readiness acceptance:** Treat `graph_readiness.ready_for_graph_handoff` as the runtime precondition summary for downstream graph tooling. `true` means all listed gates passed; `false` means at least one gate failed. This is not permission to skip candidate validation or canonical promotion.

---

# 15. GRAPH-READY FACETS

Candidate storage and review payloads should preserve graph-ready facets including:

- candidate_id
- candidate_semantic_class
- xml_structural_class
- pdf_evidence_class
- document_family_id
- ingestion_run_id
- xml_node_id
- pdf_fragment_id
- alignment_confidence
- validation_state
- review_decision_status
- depends_on
- glossary link identifiers (when present)
- applicability condition summaries (when present)
- explicit relation endpoints (`candidate_relations`)
- reconciliation classifications and promotion effects (`reconciliation_records`)
- implicit relation candidates (for review, not authoritative until validated)
- graph edge endpoints (`graph_edges`) for future graph queries
- when assembled PDF clauses are emitted for review:
  - `clause_code`
  - `heading_text`
  - `header_blocks`
  - `body_blocks`
  - `marginalia_blocks`

Review-projection rule:
- editorial annotations such as bracketed amendment notes must remain marginalia metadata and must not replace the candidate title when a recoverable clause header tuple is available

---

# 16. TRACEABILITY

PDF ↔ XML → Candidate → Snippet → Evaluation → Output

Schema compatibility note:
- existing validation result schemas may continue using current gate field names during the transition
- gate naming compatibility must not be interpreted as permission to bypass the candidate stage
- a future schema revision may introduce explicit candidate-stage gate fields once the implementation layer is promoted from planned to active

---

# 17. FINAL RULE

The Candidate Extraction Layer is mandatory and non-bypassable.
