export type ReviewStatus =
  | "match"
  | "mismatch"
  | "review required"
  | "approved"
  | "rejected"
  | "paused"
  | "ambiguous";

export type ExplicitCandidateRelation = {
  relation_id?: string;
  relation_kind?: string;
  relation_authority?: string;
  direction?: "outbound" | "inbound" | "undirected" | string;
  source_candidate_id?: string | null;
  source_semantic_unit_id?: string | null;
  source_node_id?: string | null;
  target_candidate_id?: string | null;
  target_semantic_unit_id?: string | null;
  target_node_id?: string | null;
  target_locator?: string | null;
  resolution_status?: string;
  resolved?: boolean;
  blocking?: boolean;
  raw_value?: string;
  confidence?: number;
  provenance?: {
    source_authority?: string;
    source_fields?: string[];
    evidence_fragment_ids?: string[];
    evidence_spans?: string[];
  };
  evidence_fragment_ids?: string[];
  evidence_spans?: string[];
};

export type ReconciliationRecord = {
  reconciliation_id?: string;
  source_candidate_ids?: string[];
  source_relation_ids?: string[];
  classification?: string;
  promotion_effect?: string;
  review_required?: boolean;
  notes?: string | null;
};

export type GraphEdgePayload = {
  edge_id?: string;
  from_id?: string;
  to_id?: string;
  edge_kind?: string;
  metadata?: Record<string, unknown>;
};

export type SemanticEnrichmentHints = {
  notes?: string | null;
  tags?: string[];
};

export type SemanticEnrichment = {
  enrichment_hints?: SemanticEnrichmentHints;
};

export type CandidateRecord = {
  id: string;
  title: string;
  candidateType: string;
  xmlStructuralClass: string;
  pdfEvidenceClass: string;
  candidateSemanticClass: string;
  reviewIssueClass: string;
  reviewSourceEmphasis: string;
  confidence: number;
  baseStatus: ReviewStatus;
  needsHumanReview: boolean;
  matched: boolean;
  page: number | null;
  fragmentId: string;
  nodeId: string | null;
  xmlPath: string;
  xmlFullPath: string;
  xmlParentNodeId: string | null;
  xmlRootNodeId: string | null;
  xmlAncestorNodeIds: string[];
  xmlAncestorTags: string[];
  xmlContextPathSignature: string | null;
  xmlContextDescriptor: Record<string, unknown> | null;
  xmlText: string;
  pdfText: string;
  bbox: number[];
  issues: string[];
  xmlOnlyTerms: string[];
  pdfOnlyTerms: string[];
  rawXmlOnlyTerms: string[];
  rawPdfOnlyTerms: string[];
  ignoredStructuralTerms: string[];
  candidateRelations: ExplicitCandidateRelation[];
  reconciliationRecords: ReconciliationRecord[];
  graphEdges: GraphEdgePayload[];
  semanticEnrichment: SemanticEnrichment | null;
  enrichmentHints: SemanticEnrichmentHints | null | undefined;
  dependsOn: string[];
};

export type CandidateWithDisplayStatus = CandidateRecord & {
  displayStatus: ReviewStatus;
};

export type SortKey =
  | "priority"
  | "status"
  | "confidence_desc"
  | "confidence_asc"
  | "issue_class"
  | "source_emphasis"
  | "relation_review"
  | "relation_authority";

export type RelationFilterKey = "all" | "review_required" | "resolved" | "xml_explicit";

export type ReviewUnitInput = {
  candidate_id: string;
  title: string;
  candidate_type: string;
  xml_structural_class?: string;
  pdf_evidence_class?: string;
  candidate_semantic_class?: string;
  review_issue_class?: string;
  review_source_emphasis?: string;
  confidence: number;
  base_status: ReviewStatus | string;
  needs_human_review?: boolean;
  matched: boolean;
  page?: number | null;
  fragment_id: string;
  node_id?: string | null;
  xml_path: string;
  xml_full_path?: string;
  xml_parent_node_id?: string | null;
  xml_root_node_id?: string | null;
  xml_ancestor_node_ids?: string[];
  xml_ancestor_tags?: string[];
  xml_context_path_signature?: string | null;
  xml_context_descriptor?: Record<string, unknown> | null;
  xml_text: string;
  pdf_text: string;
  bbox: number[];
  issues: string[];
  xml_only_terms: string[];
  pdf_only_terms: string[];
  raw_xml_only_terms?: string[];
  raw_pdf_only_terms?: string[];
  ignored_structural_terms?: string[];
  semantic_enrichment?: SemanticEnrichment;
  candidate_relations?: ExplicitCandidateRelation[];
  reconciliation_records?: ReconciliationRecord[];
  graph_edges?: GraphEdgePayload[];
  enrichment_hints?: SemanticEnrichmentHints;
};

export type CandidateObjectInput = {
  candidate_id: string;
  xml_node_id?: string | null;
  title?: string;
  candidate_type?: string;
  xml_structural_class?: string;
  candidate_semantic_class?: string;
  xml_path?: string;
  xml_full_path?: string;
  xml_parent_node_id?: string | null;
  xml_root_node_id?: string | null;
  xml_ancestor_node_ids?: string[];
  xml_ancestor_tags?: string[];
  xml_context_path_signature?: string | null;
  xml_context_descriptor?: Record<string, unknown> | null;
  xml_text?: string;
  confidence?: {
    overall?: number;
  };
  source?: {
    pdf_fragment_id?: string | null;
  };
  proposed?: {
    content?: string;
  };
  evidence?: Array<{
    fragment_id?: string;
    page?: number | null;
    bbox?: number[];
    text?: string;
    confidence?: number;
    pdf_evidence_class?: string;
  }>;
  review?: {
    base_status?: ReviewStatus | string;
    needs_human_review?: boolean;
    issue_class?: string;
    source_emphasis?: string;
    issues?: string[];
    xml_only_terms?: string[];
    pdf_only_terms?: string[];
    raw_xml_only_terms?: string[];
    raw_pdf_only_terms?: string[];
    ignored_structural_terms?: string[];
  };
  semantic_enrichment?: SemanticEnrichment;
  candidate_relations?: ExplicitCandidateRelation[];
  reconciliation_records?: ReconciliationRecord[];
  graph_edges?: GraphEdgePayload[];
  enrichment_hints?: SemanticEnrichmentHints;
  depends_on?: string[];
};

function issueClassPriority(value: string): number {
  switch (value) {
    case "validation":
      return 1;
    case "low_confidence":
      return 2;
    case "mixed_mismatch":
      return 3;
    case "xml_mismatch":
      return 4;
    case "pdf_mismatch":
      return 5;
    default:
      return 6;
  }
}

function sourceEmphasisPriority(value: string): number {
  switch (value) {
    case "mixed":
      return 0;
    case "xml":
      return 1;
    case "pdf":
      return 2;
    default:
      return 3;
  }
}

function statusPriority(value: ReviewStatus): number {
  switch (value) {
    case "review required":
      return 0;
    case "mismatch":
      return 1;
    case "ambiguous":
      return 2;
    case "paused":
      return 3;
    case "match":
      return 4;
    case "approved":
      return 5;
    case "rejected":
      return 6;
    default:
      return 7;
  }
}

export function normalizeReviewStatus(value: ReviewStatus | string): ReviewStatus {
  switch (value) {
    case "match":
    case "mismatch":
    case "review required":
    case "approved":
    case "rejected":
    case "paused":
    case "ambiguous":
      return value;
    default:
      return "review required";
  }
}

export function relationReviewCount(candidate: CandidateWithDisplayStatus): number {
  return candidate.candidateRelations.filter((relation) =>
    ["unresolved", "ambiguous", "review_required", "review required"].includes(relation.resolution_status ?? "")
  ).length;
}

export function resolvedRelationCount(candidate: CandidateWithDisplayStatus): number {
  return candidate.candidateRelations.filter((relation) => relation.resolution_status === "resolved").length;
}

export function authoritativeRelationCount(candidate: CandidateWithDisplayStatus): number {
  return candidate.candidateRelations.filter((relation) => relation.relation_authority === "xml_explicit").length;
}

export function relationAuthorityPriority(candidate: CandidateWithDisplayStatus): number {
  if (authoritativeRelationCount(candidate) > 0) {
    return 0;
  }
  if (candidate.candidateRelations.some((relation) => relation.relation_authority === "text_resolved")) {
    return 1;
  }
  if (candidate.candidateRelations.some((relation) => relation.relation_authority === "text_unresolved")) {
    return 2;
  }
  return 3;
}

export function sortCandidates(candidates: CandidateWithDisplayStatus[], sortKey: SortKey): CandidateWithDisplayStatus[] {
  const sorted = [...candidates];
  sorted.sort((left, right) => {
    if (sortKey === "confidence_desc") {
      return (
        right.confidence - left.confidence ||
        statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
        left.title.localeCompare(right.title)
      );
    }
    if (sortKey === "confidence_asc") {
      return (
        left.confidence - right.confidence ||
        statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
        left.title.localeCompare(right.title)
      );
    }
    if (sortKey === "issue_class") {
      return (
        issueClassPriority(left.reviewIssueClass) - issueClassPriority(right.reviewIssueClass) ||
        statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
        left.confidence - right.confidence ||
        left.title.localeCompare(right.title)
      );
    }
    if (sortKey === "source_emphasis") {
      return (
        sourceEmphasisPriority(left.reviewSourceEmphasis) - sourceEmphasisPriority(right.reviewSourceEmphasis) ||
        statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
        left.confidence - right.confidence ||
        left.title.localeCompare(right.title)
      );
    }
    if (sortKey === "relation_review") {
      return (
        relationReviewCount(right) - relationReviewCount(left) ||
        right.reconciliationRecords.filter((record) => record.review_required).length -
          left.reconciliationRecords.filter((record) => record.review_required).length ||
        statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
        left.title.localeCompare(right.title)
      );
    }
    if (sortKey === "relation_authority") {
      return (
        relationAuthorityPriority(left) - relationAuthorityPriority(right) ||
        authoritativeRelationCount(right) - authoritativeRelationCount(left) ||
        resolvedRelationCount(right) - resolvedRelationCount(left) ||
        left.title.localeCompare(right.title)
      );
    }
    return (
      statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
      issueClassPriority(left.reviewIssueClass) - issueClassPriority(right.reviewIssueClass) ||
      left.confidence - right.confidence ||
      left.title.localeCompare(right.title)
    );
  });
  return sorted;
}

export function filterCandidatesByRelationState(
  candidates: CandidateWithDisplayStatus[],
  relationFilter: RelationFilterKey
): CandidateWithDisplayStatus[] {
  if (relationFilter === "all") {
    return candidates;
  }
  if (relationFilter === "review_required") {
    return candidates.filter(
      (candidate) =>
        relationReviewCount(candidate) > 0 ||
        candidate.reconciliationRecords.some((record) => record.review_required)
    );
  }
  if (relationFilter === "resolved") {
    return candidates.filter((candidate) => resolvedRelationCount(candidate) > 0);
  }
  return candidates.filter((candidate) => authoritativeRelationCount(candidate) > 0);
}

export function mapReviewUnitToCandidate(unit: ReviewUnitInput): CandidateRecord {
  return {
    id: unit.candidate_id,
    title: unit.title,
    candidateType: unit.candidate_type,
    xmlStructuralClass: unit.xml_structural_class ?? unit.candidate_type,
    pdfEvidenceClass: unit.pdf_evidence_class ?? "unknown",
    candidateSemanticClass: unit.candidate_semantic_class ?? unit.candidate_type,
    reviewIssueClass: unit.review_issue_class ?? "clean_match",
    reviewSourceEmphasis: unit.review_source_emphasis ?? "balanced",
    confidence: unit.confidence,
    baseStatus: normalizeReviewStatus(unit.base_status),
    needsHumanReview: unit.needs_human_review ?? false,
    matched: unit.matched,
    page: unit.page ?? null,
    fragmentId: unit.fragment_id,
    nodeId: unit.node_id ?? null,
    xmlPath: unit.xml_path,
    xmlFullPath: unit.xml_full_path ?? unit.xml_path,
    xmlParentNodeId: unit.xml_parent_node_id ?? null,
    xmlRootNodeId: unit.xml_root_node_id ?? null,
    xmlAncestorNodeIds: unit.xml_ancestor_node_ids ?? [],
    xmlAncestorTags: unit.xml_ancestor_tags ?? [],
    xmlContextPathSignature: unit.xml_context_path_signature ?? null,
    xmlContextDescriptor: unit.xml_context_descriptor ?? null,
    xmlText: unit.xml_text,
    pdfText: unit.pdf_text,
    bbox: unit.bbox ?? [],
    issues: unit.issues ?? [],
    xmlOnlyTerms: unit.xml_only_terms ?? [],
    pdfOnlyTerms: unit.pdf_only_terms ?? [],
    rawXmlOnlyTerms: unit.raw_xml_only_terms ?? unit.xml_only_terms ?? [],
    rawPdfOnlyTerms: unit.raw_pdf_only_terms ?? unit.pdf_only_terms ?? [],
    ignoredStructuralTerms: unit.ignored_structural_terms ?? [],
    candidateRelations: unit.candidate_relations ?? [],
    reconciliationRecords: unit.reconciliation_records ?? [],
    graphEdges: unit.graph_edges ?? [],
    semanticEnrichment: unit.semantic_enrichment ?? null,
    enrichmentHints: unit.enrichment_hints ?? null,
    dependsOn: [],
  };
}

export function mapCandidateObjectToCandidate(candidate: CandidateObjectInput): CandidateRecord {
  const primaryEvidence = candidate.evidence?.[0];
  return {
    id: candidate.candidate_id,
    title: candidate.title ?? candidate.candidate_id,
    candidateType: candidate.candidate_type ?? candidate.candidate_semantic_class ?? "ambiguous",
    xmlStructuralClass: candidate.xml_structural_class ?? candidate.candidate_type ?? "ambiguous",
    pdfEvidenceClass: primaryEvidence?.pdf_evidence_class ?? "unknown",
    candidateSemanticClass: candidate.candidate_semantic_class ?? candidate.candidate_type ?? "ambiguous",
    reviewIssueClass: candidate.review?.issue_class ?? "clean_match",
    reviewSourceEmphasis: candidate.review?.source_emphasis ?? "balanced",
    confidence: candidate.confidence?.overall ?? primaryEvidence?.confidence ?? 0,
    baseStatus: normalizeReviewStatus(candidate.review?.base_status ?? "review required"),
    needsHumanReview: candidate.review?.needs_human_review ?? false,
    matched: Boolean(primaryEvidence),
    page: primaryEvidence?.page ?? null,
    fragmentId: primaryEvidence?.fragment_id ?? `xml_only:${candidate.xml_node_id ?? candidate.candidate_id}`,
    nodeId: candidate.xml_node_id ?? null,
    xmlPath: candidate.xml_path ?? "No XML node linked yet",
    xmlFullPath: candidate.xml_full_path ?? candidate.xml_path ?? "No XML node linked yet",
    xmlParentNodeId: candidate.xml_parent_node_id ?? null,
    xmlRootNodeId: candidate.xml_root_node_id ?? null,
    xmlAncestorNodeIds: candidate.xml_ancestor_node_ids ?? [],
    xmlAncestorTags: candidate.xml_ancestor_tags ?? [],
    xmlContextPathSignature: candidate.xml_context_path_signature ?? null,
    xmlContextDescriptor: candidate.xml_context_descriptor ?? null,
    xmlText: candidate.xml_text ?? "",
    pdfText: primaryEvidence?.text ?? candidate.proposed?.content ?? "",
    bbox: primaryEvidence?.bbox ?? [],
    issues: candidate.review?.issues ?? [],
    xmlOnlyTerms: candidate.review?.xml_only_terms ?? [],
    pdfOnlyTerms: candidate.review?.pdf_only_terms ?? [],
    rawXmlOnlyTerms: candidate.review?.raw_xml_only_terms ?? candidate.review?.xml_only_terms ?? [],
    rawPdfOnlyTerms: candidate.review?.raw_pdf_only_terms ?? candidate.review?.pdf_only_terms ?? [],
    ignoredStructuralTerms: candidate.review?.ignored_structural_terms ?? [],
    candidateRelations: candidate.candidate_relations ?? [],
    reconciliationRecords: candidate.reconciliation_records ?? [],
    graphEdges: candidate.graph_edges ?? [],
    semanticEnrichment: candidate.semantic_enrichment ?? null,
    enrichmentHints: candidate.enrichment_hints ?? null,
    dependsOn: candidate.depends_on ?? [],
  };
}
