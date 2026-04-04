import { describe, expect, it } from "vitest";

import {
  filterCandidatesByRelationState,
  mapCandidateObjectToCandidate,
  mapReviewUnitToCandidate,
  sortCandidates,
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
});
