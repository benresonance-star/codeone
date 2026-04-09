import { describe, expect, it } from "vitest";

import {
  childPdfClauseCandidatesForParent,
  filterCandidatesByRelationState,
  immediateStructuralParentCandidateId,
  mapCandidateObjectToCandidate,
  mapReviewUnitToCandidate,
  pdfClauseCandidateIdFromAnchorBlockId,
  sortCandidates,
  structuralPathLabel,
  type CandidateObjectInput,
  type CandidateWithDisplayStatus,
  type ReviewUnitInput,
} from "./candidate-review-workspace-logic";

function candidate(overrides: Partial<CandidateWithDisplayStatus>): CandidateWithDisplayStatus {
  return {
    id: "candidate:a",
    title: "Alpha",
    candidateType: "rule",
    xmlStructuralClass: "rule",
    pdfEvidenceClass: "paragraph",
    candidateSemanticClass: "rule",
    reviewIssueClass: "clean_match",
    reviewSourceEmphasis: "balanced",
    confidence: 0.95,
    baseStatus: "match",
    displayStatus: "match",
    needsHumanReview: false,
    matched: true,
    page: 1,
    fragmentId: "frag_1",
    nodeId: "node_1",
    xmlPath: "/clause[@id='node_1']",
    xmlFullPath: "/ncc/part/clause[@id='node_1']",
    xmlParentNodeId: "part_1",
    xmlRootNodeId: "part_1",
    xmlAncestorNodeIds: ["part_1"],
    xmlAncestorTags: ["part"],
    xmlContextPathSignature: "/ncc/part/clause",
    xmlContextDescriptor: null,
    xmlText: "Alpha clause",
    pdfText: "Alpha clause",
    bbox: [0, 0, 1, 1],
    issues: [],
    xmlOnlyTerms: [],
    pdfOnlyTerms: [],
    rawXmlOnlyTerms: [],
    rawPdfOnlyTerms: [],
    ignoredStructuralTerms: [],
    candidateRelations: [],
    reconciliationRecords: [],
    graphEdges: [],
    semanticEnrichment: null,
    enrichmentHints: null,
    dependsOn: [],
    assembledClause: null,
    displayProjection: null,
    ...overrides,
  };
}

describe("candidate review workspace logic", () => {
  it("filters review-required candidates from relation and reconciliation signals", () => {
    const reviewFromRelation = candidate({
      id: "candidate:review-relation",
      candidateRelations: [{ relation_authority: "text_unresolved", resolution_status: "unresolved" }],
    });
    const reviewFromReconciliation = candidate({
      id: "candidate:review-reconciliation",
      reconciliationRecords: [{ review_required: true }],
    });
    const resolvedOnly = candidate({
      id: "candidate:resolved",
      candidateRelations: [{ relation_authority: "text_resolved", resolution_status: "resolved" }],
    });

    const filtered = filterCandidatesByRelationState(
      [reviewFromRelation, reviewFromReconciliation, resolvedOnly],
      "review_required"
    );

    expect(filtered.map((item) => item.id)).toEqual([
      "candidate:review-relation",
      "candidate:review-reconciliation",
    ]);
  });

  it("sorts by relation authority so xml-explicit candidates lead the queue", () => {
    const xmlExplicit = candidate({
      id: "candidate:xml",
      title: "XML explicit",
      candidateRelations: [{ relation_authority: "xml_explicit", resolution_status: "resolved" }],
    });
    const textResolved = candidate({
      id: "candidate:text-resolved",
      title: "Text resolved",
      candidateRelations: [{ relation_authority: "text_resolved", resolution_status: "resolved" }],
    });
    const textUnresolved = candidate({
      id: "candidate:text-unresolved",
      title: "Text unresolved",
      candidateRelations: [{ relation_authority: "text_unresolved", resolution_status: "unresolved" }],
    });

    const sorted = sortCandidates([textResolved, textUnresolved, xmlExplicit], "relation_authority");

    expect(sorted.map((item) => item.id)).toEqual([
      "candidate:xml",
      "candidate:text-resolved",
      "candidate:text-unresolved",
    ]);
  });

  it("sorts relation-review candidates by unresolved relation pressure first", () => {
    const highestPressure = candidate({
      id: "candidate:highest",
      title: "Highest",
      displayStatus: "review required",
      candidateRelations: [
        { relation_authority: "text_unresolved", resolution_status: "unresolved" },
        { relation_authority: "manual_review_required", resolution_status: "review_required" },
      ],
    });
    const reconciliationOnly = candidate({
      id: "candidate:reconciliation",
      title: "Reconciliation",
      displayStatus: "review required",
      reconciliationRecords: [{ review_required: true }],
    });
    const resolved = candidate({
      id: "candidate:resolved",
      title: "Resolved",
      candidateRelations: [{ relation_authority: "text_resolved", resolution_status: "resolved" }],
    });

    const sorted = sortCandidates([resolved, reconciliationOnly, highestPressure], "relation_review");

    expect(sorted.map((item) => item.id)).toEqual([
      "candidate:highest",
      "candidate:reconciliation",
      "candidate:resolved",
    ]);
  });

  it("maps candidate objects with defaults, dependencies, and enrichment mirrors", () => {
    const input: CandidateObjectInput = {
      candidate_id: "candidate:unit:C3D15",
      xml_node_id: "C3D15",
      title: "Division of public corridors",
      candidate_type: "rule",
      xml_structural_class: "rule",
      candidate_semantic_class: "rule",
      xml_path: "/clause[@id='C3D15']",
      review: {
        base_status: "mismatch",
        needs_human_review: true,
        issue_class: "validation",
        source_emphasis: "xml",
        issues: ["dependency needs review"],
        xml_only_terms: ["corridors"],
        pdf_only_terms: ["hallways"],
      },
      evidence: [
        {
          fragment_id: "frag_ref",
          page: 2,
          bbox: [0, 0, 2, 2],
          text: "Refer to C3D15.",
          confidence: 0.91,
          pdf_evidence_class: "paragraph",
        },
      ],
      candidate_relations: [{ relation_authority: "text_resolved", resolution_status: "resolved" }],
      reconciliation_records: [{ review_required: true }],
      depends_on: ["candidate:unit:C3D16"],
    };

    const mapped = mapCandidateObjectToCandidate(input);

    expect(mapped.fragmentId).toBe("frag_ref");
    expect(mapped.baseStatus).toBe("mismatch");
    expect(mapped.needsHumanReview).toBe(true);
    expect(mapped.candidateRelations).toHaveLength(1);
    expect(mapped.reconciliationRecords).toHaveLength(1);
    expect(mapped.dependsOn).toEqual(["candidate:unit:C3D16"]);
  });

  it("prefers backend primary page semantics over primary evidence page", () => {
    const input: CandidateObjectInput = {
      candidate_id: "candidate:pdf_clause:multi_page",
      title: "Multi-page clause",
      candidate_type: "rule",
      candidate_semantic_class: "rule",
      page: 3,
      evidence: [
        {
          fragment_id: "frag_4",
          page: 4,
          bbox: [0, 0, 2, 2],
          text: "continued on next page",
          confidence: 0.91,
          pdf_evidence_class: "paragraph",
        },
      ],
      review: {
        base_status: "match",
        needs_human_review: false,
        issue_class: "clean_match",
        source_emphasis: "pdf",
        issues: [],
        xml_only_terms: [],
        pdf_only_terms: [],
      },
      assembled_clause: {
        clause_candidate_id: "assembled_clause:multi_page",
        start_page: 3,
        end_page: 4,
        pages: [3, 4],
        rendered_blocks: [],
      },
      display_projection: {
        title: "Multi-page clause",
        rendered_blocks: [],
        page_context: {
          start_page: 3,
          end_page: 4,
          pages: [3, 4],
        },
      },
    };

    const mapped = mapCandidateObjectToCandidate(input);

    expect(mapped.page).toBe(3);
    expect(mapped.displayProjection?.page_context).toEqual({
      start_page: 3,
      end_page: 4,
      pages: [3, 4],
    });
  });

  it("maps review units from backend payload fields into candidate records", () => {
    const input: ReviewUnitInput = {
      candidate_id: "candidate:unit:clause_ref_source",
      title: "Refer to C3D15",
      candidate_type: "rule",
      xml_structural_class: "rule",
      pdf_evidence_class: "paragraph",
      candidate_semantic_class: "rule",
      review_issue_class: "mixed_mismatch",
      review_source_emphasis: "mixed",
      confidence: 0.88,
      base_status: "unknown_status",
      needs_human_review: true,
      matched: true,
      page: 1,
      fragment_id: "frag_ref",
      node_id: "clause_ref_source",
      xml_path: "/clause[@id='clause_ref_source']",
      xml_text: "Refer to C3D15",
      pdf_text: "Refer to C3D15",
      bbox: [0, 0, 1, 1],
      issues: ["needs relation review"],
      xml_only_terms: ["xml"],
      pdf_only_terms: ["pdf"],
      candidate_relations: [{ relation_authority: "xml_explicit", resolution_status: "resolved" }],
      reconciliation_records: [{ review_required: false }],
    };

    const mapped = mapReviewUnitToCandidate(input);

    expect(mapped.baseStatus).toBe("review required");
    expect(mapped.reviewIssueClass).toBe("mixed_mismatch");
    expect(mapped.reviewSourceEmphasis).toBe("mixed");
    expect(mapped.candidateRelations[0]?.relation_authority).toBe("xml_explicit");
    expect(mapped.nodeId).toBe("clause_ref_source");
  });

  it("maps PDF-only candidate objects without XML lineage as first-class records", () => {
    const input: CandidateObjectInput = {
      candidate_id: "candidate:pdf_clause:clause_1",
      semantic_unit_id: "pdf_clause:clause_1",
      xml_node_id: null,
      title: "A1 A building must provide safe egress.",
      candidate_type: "rule",
      candidate_semantic_class: "rule",
      source: {
        pdf_fragment_id: "clause_1",
      },
      proposed: {
        content: "A1 A building must provide safe egress.",
      },
      evidence: [
        {
          fragment_id: "clause_1",
          page: 1,
          bbox: [0, 0, 1, 1],
          text: "A1 A building must provide safe egress.",
          confidence: 0.95,
          pdf_evidence_class: "paragraph",
        },
      ],
      review: {
        base_status: "match",
        needs_human_review: false,
        issue_class: "clean_match",
        source_emphasis: "pdf",
        issues: [],
        xml_only_terms: [],
        pdf_only_terms: [],
      },
      assembled_clause: {
        clause_candidate_id: "pdf_clause:clause_1",
        title_or_lead: "A1 A building must provide safe egress.",
        rendered_blocks: [],
      },
      display_projection: {
        title: "A1 A building must provide safe egress.",
        rendered_blocks: [],
        parent_heading_label: "Part A1",
        parent_heading_text: "Interpreting the NCC",
        parent_heading_title: "Part A1 Interpreting the NCC",
        structural_path: [
          {
            kind: "part",
            label: "Part A1",
            text: "Interpreting the NCC",
            title: "Part A1 Interpreting the NCC",
            block_id: "docling_1_10",
            candidate_id: "candidate:pdf_clause:docling_1_10",
          },
        ],
      },
    };

    const mapped = mapCandidateObjectToCandidate(input);

    expect(mapped.nodeId).toBeNull();
    expect(mapped.xmlPath).toBe("No XML node linked yet");
    expect(mapped.pdfText).toBe("A1 A building must provide safe egress.");
    expect(mapped.reviewSourceEmphasis).toBe("pdf");
    expect(mapped.assembledClause?.clause_candidate_id).toBe("pdf_clause:clause_1");
    expect(mapped.displayProjection?.parent_heading_label).toBe("Part A1");
    expect(mapped.displayProjection?.structural_path?.[0]?.candidate_id).toBe("candidate:pdf_clause:docling_1_10");
  });

  it("derives the parent heading candidate id from the anchor block id", () => {
    expect(pdfClauseCandidateIdFromAnchorBlockId("docling_1_10")).toBe("candidate:pdf_clause:docling_1_10");
    expect(pdfClauseCandidateIdFromAnchorBlockId("")).toBeNull();
  });

  it("finds child pdf clause candidates for a parent heading candidate", () => {
    const parent = candidate({
      id: "candidate:pdf_clause:docling_1_10",
      displayProjection: {
        title: "Part A1 Interpreting the NCC",
      },
    });
    const child = candidate({
      id: "candidate:pdf_clause:docling_1_11",
      displayProjection: {
        title: "A1G1 Scope of NCC Volume One",
        parent_heading_block_id: "docling_1_10",
      },
    });
    const unrelated = candidate({
      id: "candidate:pdf_clause:docling_2_10",
      displayProjection: {
        title: "Part B1 Something Else",
        parent_heading_block_id: "docling_2_01",
      },
    });

    const children = childPdfClauseCandidatesForParent([parent, child, unrelated], parent.id);

    expect(children.map((item) => item.id)).toEqual(["candidate:pdf_clause:docling_1_11"]);
  });

  it("falls back to structural path when deriving the immediate parent candidate id", () => {
    expect(
      immediateStructuralParentCandidateId({
        structural_path: [
          {
            title: "Part A1 Interpreting the NCC",
            candidate_id: "candidate:pdf_clause:docling_1_10",
          },
        ],
      })
    ).toBe("candidate:pdf_clause:docling_1_10");
  });

  it("formats structural ancestry into a compact label", () => {
    expect(
      structuralPathLabel([
        { title: "Part A1 Interpreting the NCC" },
        { title: "Section A" },
      ])
    ).toBe("Part A1 Interpreting the NCC > Section A");
    expect(structuralPathLabel([])).toBeNull();
  });
});
