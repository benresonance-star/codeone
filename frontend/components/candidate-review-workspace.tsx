"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import {
  childPdfClauseCandidatesForParent,
  filterCandidatesByRelationState,
  immediateStructuralParentCandidateId,
  mapCandidateObjectToCandidate,
  mapReviewUnitToCandidate,
  renderedClausePageChipLabel,
  sortCandidates,
  structuralPathLabel,
  type AssembledClause,
  type CandidateDisplayProjection,
  type ClauseStyleSpan,
  type RenderedClauseBlock,
  type StructuralPathEntry,
} from "../lib/candidate-review-workspace-logic";

type ValidationItem = {
  fragment_id?: string;
  node_id?: string;
  xml_node?: string;
  message?: string;
};

type XmlNode = {
  node_id: string;
  clause_id: string;
  text: string;
  path: string;
  full_path?: string;
  parent_node_id?: string | null;
  root_node_id?: string | null;
  ancestor_node_ids?: string[];
  ancestor_tags?: string[];
  context_path_signature?: string | null;
  context_titles?: string[];
};

type PdfFragment = {
  fragment_id: string;
  page: number;
  text: string;
  bbox: number[];
};

type AlignmentRecord = {
  fragment_id: string;
  node_id?: string | null;
  confidence: number;
  matched: boolean;
  page?: number;
  bbox?: number[];
};

type CanonicalSnippet = {
  clause_id?: string;
  fragment_id?: string;
  content?: string;
  confidence?: number;
};

/** Mirrors Spec/Candidate_Extraction_Layer.md semantic_enrichment and pdf_ingestion_contract optional mirrors. */
type GlossaryLinkRef = {
  term_id?: string | null;
  label?: string;
  ref?: string | null;
};

type ExplicitCandidateRelation = {
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

type ImplicitRelationCandidate = {
  suggested_relation_kind?: string;
  target_candidate_id?: string | null;
  target_semantic_unit_id?: string | null;
  confidence?: number;
  rationale?: string | null;
};

type GraphEdgePayload = {
  edge_id?: string;
  from_id?: string;
  to_id?: string;
  edge_kind?: string;
  metadata?: Record<string, unknown>;
};

type SemanticEnrichment = {
  enrichment_run_id?: string | null;
  enrichment_version?: string | null;
  glossary_links?: GlossaryLinkRef[];
  applicability_conditions?: string[];
  candidate_relations?: ExplicitCandidateRelation[];
  implicit_relation_candidates?: ImplicitRelationCandidate[];
  graph_edges?: GraphEdgePayload[];
  field_authority?: Record<string, string>;
  per_field_counts?: Record<string, number>;
  enrichment_hints?: {
    notes?: string | null;
    tags?: string[];
  };
};

type ReconciliationRecord = {
  reconciliation_id?: string;
  source_candidate_ids?: string[];
  source_relation_ids?: string[];
  classification?: string;
  promotion_effect?: string;
  review_required?: boolean;
  notes?: string | null;
};

type ReviewStatus =
  | "match"
  | "mismatch"
  | "review required"
  | "approved"
  | "rejected"
  | "paused"
  | "ambiguous";

type ReviewUnit = {
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
  enrichment_hints?: SemanticEnrichment["enrichment_hints"];
};

type ReviewDecision = {
  candidate_id: string;
  decision_status: ReviewStatus;
};

type CandidateObject = {
  candidate_id: string;
  semantic_unit_id?: string;
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
  enrichment_hints?: SemanticEnrichment["enrichment_hints"];
  depends_on?: string[];
  assembled_clause?: AssembledClause | null;
  display_projection?: CandidateDisplayProjection | null;
};

type CandidateRecord = {
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
  enrichmentHints: SemanticEnrichment["enrichment_hints"] | null;
  dependsOn: string[];
  assembledClause: AssembledClause | null;
  displayProjection: CandidateDisplayProjection | null;
};

type CandidateWithDisplayStatus = CandidateRecord & {
  displayStatus: ReviewStatus;
};

type ContextFilter =
  | {
      mode: "parent" | "root" | "pdf_parent" | "pdf_root";
      value: string;
    }
  | null;

type ComparisonRow = {
  label: string;
  value: string;
};

type IngestionResponseLike = {
  summary?: {
    ingestion_run_id?: string | null;
    document_family_id?: string | null;
    created_at?: string | null;
    can_progress?: boolean;
    enrichment_drift_advisory?: string | null;
  };
  results?: {
    xml_validation?: {
      warnings?: ValidationItem[];
      errors?: ValidationItem[];
    };
    pdf_validation?: {
      warnings?: ValidationItem[];
      errors?: ValidationItem[];
    };
  };
  lineage?: {
    xml_nodes?: XmlNode[];
    xml_semantic_units?: Array<Record<string, unknown>>;
    pdf_fragments?: PdfFragment[];
    alignments?: AlignmentRecord[];
    pdf_evidence_packets?: Array<Record<string, unknown>>;
    pdf_clause_candidates?: AssembledClause[];
    candidate_objects?: CandidateObject[];
    canonical_snippets?: CanonicalSnippet[];
    candidate_relations?: ExplicitCandidateRelation[];
    reconciliation_records?: ReconciliationRecord[];
    graph_edges?: GraphEdgePayload[];
  };
  review_workspace?: {
    mode?: string;
    reason?: string;
    xml_nodes?: XmlNode[];
    xml_semantic_units?: Array<Record<string, unknown>>;
    pdf_fragments?: PdfFragment[];
    pdf_evidence_packets?: Array<Record<string, unknown>>;
    pdf_clause_candidates?: AssembledClause[];
    alignments?: AlignmentRecord[];
    candidates?: CandidateObject[];
    canonical_snippets?: CanonicalSnippet[];
    review_units?: ReviewUnit[];
    alignment_total?: number;
    alignment_displayed?: number;
    candidate_total?: number;
    candidate_surfaced?: number;
    candidate_needs_review?: number;
    candidate_relations?: ExplicitCandidateRelation[];
    reconciliation_records?: ReconciliationRecord[];
    graph_edges?: GraphEdgePayload[];
    enrichment_counts?: Record<string, number>;
  };
};

type CandidateReviewWorkspaceProps = {
  response: IngestionResponseLike;
  pdfFile: File | null;
  apiBaseUrl: string;
  onRelinkPdf: () => void;
};

type FilterKey = "review" | "all" | "approved" | "rejected";
type RelationFilterKey = "all" | "review_required" | "resolved" | "xml_explicit";
type SortKey =
  | "priority"
  | "confidence_desc"
  | "confidence_asc"
  | "issue_class"
  | "source_emphasis"
  | "relation_review"
  | "relation_authority";

const FILTER_LABELS: Record<FilterKey, string> = {
  review: "Review Queue",
  all: "All Candidates",
  approved: "Approved",
  rejected: "Rejected",
};

const RELATION_FILTER_LABELS: Record<RelationFilterKey, string> = {
  all: "All relation states",
  review_required: "Needs dependency review",
  resolved: "Has resolved dependencies",
  xml_explicit: "XML-explicit only",
};

const SORT_LABELS: Record<SortKey, string> = {
  priority: "Priority",
  confidence_desc: "Confidence (high to low)",
  confidence_asc: "Confidence (low to high)",
  issue_class: "Mismatch / Error Type",
  source_emphasis: "PDF / XML Source",
  relation_review: "Dependency Review Priority",
  relation_authority: "Relation Authority",
};

const CANDIDATE_PAGE_SIZE = 8;

function deriveReviewIssueClass(
  alignment: AlignmentRecord,
  xmlOnlyTerms: string[],
  pdfOnlyTerms: string[],
  linkedIssue: boolean
): string {
  if (!alignment.matched || !alignment.node_id) {
    return "unmatched";
  }
  if (linkedIssue) {
    return "validation";
  }
  if (alignment.confidence < 0.9) {
    return "low_confidence";
  }
  if (xmlOnlyTerms.length > 0 && pdfOnlyTerms.length > 0) {
    return "mixed_mismatch";
  }
  if (xmlOnlyTerms.length > 0) {
    return "xml_mismatch";
  }
  if (pdfOnlyTerms.length > 0) {
    return "pdf_mismatch";
  }
  return "clean_match";
}

function deriveReviewSourceEmphasis(xmlOnlyTerms: string[], pdfOnlyTerms: string[]): string {
  if (xmlOnlyTerms.length > 0 && pdfOnlyTerms.length > 0) {
    return "mixed";
  }
  if (xmlOnlyTerms.length > 0) {
    return "xml";
  }
  if (pdfOnlyTerms.length > 0) {
    return "pdf";
  }
  return "balanced";
}

function cleanText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeToken(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function compareTexts(xmlText: string, pdfText: string) {
  const xmlTerms = Array.from(
    new Set(
      cleanText(xmlText)
        .split(/\s+/)
        .map(normalizeToken)
        .filter(Boolean)
    )
  );
  const pdfTerms = Array.from(
    new Set(
      cleanText(pdfText)
        .split(/\s+/)
        .map(normalizeToken)
        .filter(Boolean)
    )
  );

  const pdfSet = new Set(pdfTerms);
  const xmlSet = new Set(xmlTerms);

  return {
    xmlOnlyTerms: xmlTerms.filter((term) => !pdfSet.has(term)).slice(0, 10),
    pdfOnlyTerms: pdfTerms.filter((term) => !xmlSet.has(term)).slice(0, 10),
  };
}

function detectCandidateType(xmlPath: string, xmlText: string): string {
  const normalizedPath = xmlPath.toLowerCase();
  const normalizedText = xmlText.toLowerCase();

  if (normalizedPath.includes("/title")) {
    return "title";
  }
  if (normalizedPath.includes("/num")) {
    return "context_key";
  }
  if (normalizedPath.includes("/note") || normalizedPath.includes("/intro-part") || normalizedPath.includes("/subtitle")) {
    return "note";
  }
  if (normalizedPath.includes("table")) {
    return "table";
  }
  if (normalizedPath.includes("xref") || normalizedPath.includes("reference")) {
    return "reference";
  }
  if (normalizedPath.includes("definition") || normalizedText.includes(" means ")) {
    return "definition";
  }
  return "rule";
}

function formatTitle(xmlText: string, pdfText: string, fragmentId: string): string {
  const source = cleanText(xmlText) || cleanText(pdfText);
  return source ? source.slice(0, 96) : fragmentId;
}

function buildEvidenceAlerts(
  alignment: AlignmentRecord,
  xmlOnlyTerms: string[],
  pdfOnlyTerms: string[],
  linkedIssue: boolean
): string[] {
  const issues: string[] = [];

  if (!alignment.matched || !alignment.node_id) {
    issues.push("No XML clause met the alignment threshold for this fragment.");
  }
  if (alignment.confidence < 0.9) {
    issues.push("Alignment confidence is below the temporary auto-pass threshold.");
  }
  if (linkedIssue) {
    issues.push("Validation warnings or errors reference this candidate.");
  }
  if (xmlOnlyTerms.length > 0) {
    issues.push(`XML-only terms detected: ${xmlOnlyTerms.slice(0, 4).join(", ")}.`);
  }
  if (pdfOnlyTerms.length > 0) {
    issues.push(`PDF-only terms detected: ${pdfOnlyTerms.slice(0, 4).join(", ")}.`);
  }

  return issues;
}

function deriveBaseStatus(alignment: AlignmentRecord, issues: string[], approved: boolean): ReviewStatus {
  if (approved) {
    return "approved";
  }
  if (!alignment.matched || !alignment.node_id || alignment.confidence < 0.85) {
    return "review required";
  }
  if (issues.some((issue) => issue.includes("XML-only") || issue.includes("PDF-only"))) {
    return "mismatch";
  }
  return "match";
}

function statusClass(status: ReviewStatus): string {
  switch (status) {
    case "match":
    case "approved":
      return "status pass";
    case "mismatch":
    case "review required":
    case "paused":
    case "ambiguous":
      return "status warn";
    default:
      return "status fail";
  }
}

function renderHighlightedText(text: string, emphasisTerms: string[], className: string) {
  const emphasisSet = new Set(emphasisTerms);
  return cleanText(text)
    .split(/(\s+)/)
    .map((part, index) => {
      if (!part.trim()) {
        return <span key={`${part}-${index}`}>{part}</span>;
      }
      const normalized = normalizeToken(part);
      return (
        <span key={`${part}-${index}`} className={emphasisSet.has(normalized) ? className : undefined}>
          {part}
        </span>
      );
    });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatProjectionValue(value: unknown): string {
  if (value == null) {
    return "n/a";
  }
  if (typeof value === "string") {
    return value || "n/a";
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "n/a";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((entry) => formatProjectionValue(entry)).join(", ") : "none";
  }
  return JSON.stringify(value);
}

function styleSpanCss(span: ClauseStyleSpan) {
  const css: Record<string, string | number> = {};
  if (span.text_color_hex) {
    css.color = span.text_color_hex;
  }
  if (span.font_name) {
    css.fontFamily = `"${span.font_name}", "Segoe UI", sans-serif`;
  }
  if (typeof span.font_size_pt === "number") {
    css.fontSize = `${Math.max(11, Math.min(Math.round((span.font_size_pt * 4) / 3), 28))}px`;
  }
  if (span.is_bold) {
    css.fontWeight = 700;
  }
  if (span.is_italic) {
    css.fontStyle = "italic";
  }
  return css;
}

function renderStyledClauseText(block: RenderedClauseBlock) {
  const styleSpans = Array.isArray(block.style_spans) ? block.style_spans : [];
  if (!styleSpans.length) {
    return block.content_text || block.text;
  }
  const fragments: ReactNode[] = [];
  const sourceText = block.content_text || block.text;
  let cursor = 0;
  styleSpans.forEach((span, index) => {
    const start = Math.max(cursor, Math.min(asNumber(span.start) ?? cursor, sourceText.length));
    const end = Math.max(start, Math.min(asNumber(span.end) ?? start, sourceText.length));
    if (start > cursor) {
      fragments.push(<span key={`${block.block_id}-plain-${index}-${cursor}`}>{sourceText.slice(cursor, start)}</span>);
    }
    if (end > start) {
      fragments.push(
        <span key={`${block.block_id}-styled-${index}-${start}`} style={styleSpanCss(span)}>
          {sourceText.slice(start, end)}
        </span>
      );
    }
    cursor = end;
  });
  if (cursor < sourceText.length) {
    fragments.push(<span key={`${block.block_id}-tail-${cursor}`}>{sourceText.slice(cursor)}</span>);
  }
  return fragments;
}

function formatWorkspaceLabel(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  return value.replace(/_/g, " ");
}

function dedupeByKey<T>(items: T[], keyBuilder: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = keyBuilder(item);
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function formatRelationLabel(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  return value.replace(/_/g, " ");
}

function relationTone(value: string | null | undefined): "authoritative" | "review" | "neutral" {
  if (!value) {
    return "neutral";
  }
  if (value === "xml_explicit" || value === "xml_authoritative") {
    return "authoritative";
  }
  if (value.includes("unresolved") || value.includes("review") || value.includes("heuristic")) {
    return "review";
  }
  return "neutral";
}

function relationStatusTone(value: string | null | undefined): "pass" | "warn" | "fail" {
  if (!value) {
    return "warn";
  }
  if (value === "resolved" || value === "match") {
    return "pass";
  }
  if (value === "unresolved" || value === "ambiguous" || value === "review_required" || value === "review required") {
    return "warn";
  }
  return "fail";
}

function truncateText(value: string | null | undefined, limit = 140): string {
  const text = cleanText(value);
  if (!text) {
    return "n/a";
  }
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function summarizePages(values: Array<number | null | undefined>): string {
  const pages = Array.from(new Set(values.filter((value): value is number => typeof value === "number" && value > 0))).sort(
    (left, right) => left - right
  );

  if (!pages.length) {
    return "n/a";
  }
  if (pages.length === 1) {
    return `Page ${pages[0]} only`;
  }
  const isContiguous = pages.every((page, index) => index === 0 || page === pages[index - 1] + 1);
  if (isContiguous) {
    return `Pages ${pages[0]}-${pages[pages.length - 1]}`;
  }
  if (pages.length <= 4) {
    return `Pages ${pages.join(", ")}`;
  }
  return `Pages ${pages[0]}, ${pages[1]}, ... ${pages[pages.length - 1]}`;
}

function describeCandidateStatus(candidate: CandidateRecord): string {
  switch (candidate.baseStatus) {
    case "approved":
      return "This candidate is already approved and promoted into the approved-snippet path.";
    case "match":
      return "This candidate is aligned cleanly enough to read as a match, but it has not been promoted into the approved snippet set.";
    case "mismatch":
      return "This candidate aligned to an XML node, but text differences were detected and it still needs operator review.";
    case "review required":
      return "This candidate did not meet the current auto-pass threshold and needs manual review before it can be trusted.";
    default:
      return "This candidate is still in the review workflow and needs operator attention.";
  }
}

function formatBbox(bbox: number[]): string {
  if (!bbox.length) {
    return "n/a";
  }
  return bbox.join(", ");
}

function formatList(values: string[]): string {
  if (!values.length) {
    return "none";
  }
  return values.join(", ");
}

function summarizeXmlLineage(candidate: CandidateWithDisplayStatus): string {
  if (candidate.xmlAncestorTags.length) {
    return [...candidate.xmlAncestorTags, candidate.candidateType].join(" > ");
  }
  return candidate.xmlContextPathSignature ?? candidate.xmlFullPath ?? candidate.xmlPath;
}

function summarizeSidebarXmlContext(candidate: CandidateWithDisplayStatus): string {
  const contextParts = [
    candidate.xmlParentNodeId ? `Parent ${candidate.xmlParentNodeId}` : null,
    candidate.xmlRootNodeId ? `Root ${candidate.xmlRootNodeId}` : null,
  ].filter(Boolean);
  if (contextParts.length) {
    return contextParts.join(" | ");
  }
  return candidate.xmlContextPathSignature ?? candidate.xmlPath;
}

function buildCandidateJson(candidate: CandidateWithDisplayStatus): Record<string, unknown> {
  return {
    candidateId: candidate.id,
    title: candidate.title,
    candidateType: candidate.candidateType,
    xmlStructuralClass: candidate.xmlStructuralClass,
    pdfEvidenceClass: candidate.pdfEvidenceClass,
    candidateSemanticClass: candidate.candidateSemanticClass,
    reviewIssueClass: candidate.reviewIssueClass,
    reviewSourceEmphasis: candidate.reviewSourceEmphasis,
    fragmentId: candidate.fragmentId,
    nodeId: candidate.nodeId,
    baseStatus: candidate.baseStatus,
    displayStatus: candidate.displayStatus,
    needsHumanReview: candidate.needsHumanReview,
    matched: candidate.matched,
    confidence: candidate.confidence,
    page: candidate.page,
    bbox: candidate.bbox,
    xmlPath: candidate.xmlPath,
    xmlFullPath: candidate.xmlFullPath,
    xmlParentNodeId: candidate.xmlParentNodeId,
    xmlRootNodeId: candidate.xmlRootNodeId,
    xmlAncestorNodeIds: candidate.xmlAncestorNodeIds,
    xmlAncestorTags: candidate.xmlAncestorTags,
    xmlContextPathSignature: candidate.xmlContextPathSignature,
    xmlContextDescriptor: candidate.xmlContextDescriptor,
    xmlOnlyTerms: candidate.xmlOnlyTerms,
    pdfOnlyTerms: candidate.pdfOnlyTerms,
    rawXmlOnlyTerms: candidate.rawXmlOnlyTerms,
    rawPdfOnlyTerms: candidate.rawPdfOnlyTerms,
    ignoredStructuralTerms: candidate.ignoredStructuralTerms,
    issues: candidate.issues,
    dependsOn: candidate.dependsOn,
    candidateRelations: candidate.candidateRelations,
    reconciliationRecords: candidate.reconciliationRecords,
    graphEdges: candidate.graphEdges,
    semanticEnrichment: candidate.semanticEnrichment,
    enrichmentHints: candidate.enrichmentHints,
    assembledClause: candidate.assembledClause,
    displayProjection: candidate.displayProjection,
  };
}

function buildSnippetJson(snippet: CanonicalSnippet | null): Record<string, unknown> | null {
  if (!snippet) {
    return null;
  }
  return {
    clauseId: snippet.clause_id ?? null,
    fragmentId: snippet.fragment_id ?? null,
    content: snippet.content ?? null,
    confidence: snippet.confidence ?? null,
  };
}

function renderComparisonRows(rows: ComparisonRow[]) {
  return (
    <div className="comparison-field-list">
      {rows.map((row) => (
        <div key={row.label} className="comparison-field-row">
          <strong>{row.label}</strong>
          <span>{row.value}</span>
        </div>
      ))}
    </div>
  );
}

function buildLegacyCandidates(response: IngestionResponseLike): CandidateRecord[] {
  const workspace = response.review_workspace ?? response.lineage;
  const xmlNodes = workspace?.xml_nodes ?? [];
  const pdfFragments = workspace?.pdf_fragments ?? [];
  const alignments = workspace?.alignments ?? [];
  const canonicalSnippets = workspace?.canonical_snippets ?? [];

  const xmlById = new Map(xmlNodes.map((node) => [node.node_id, node]));
  const fragmentById = new Map(pdfFragments.map((fragment) => [fragment.fragment_id, fragment]));
  const approvedPairs = new Set(
    canonicalSnippets
      .filter((snippet) => snippet.fragment_id && snippet.clause_id)
      .map((snippet) => `${snippet.fragment_id}:${snippet.clause_id}`)
  );

  const linkedIssues = new Set<string>();
  for (const item of [
    ...(response.results?.xml_validation?.warnings ?? []),
    ...(response.results?.xml_validation?.errors ?? []),
    ...(response.results?.pdf_validation?.warnings ?? []),
    ...(response.results?.pdf_validation?.errors ?? []),
  ]) {
    if (item.fragment_id) {
      linkedIssues.add(`fragment:${item.fragment_id}`);
    }
    if (item.node_id) {
      linkedIssues.add(`node:${item.node_id}`);
    }
    if (item.xml_node) {
      linkedIssues.add(`node:${item.xml_node}`);
    }
  }

  return alignments.reduce<CandidateRecord[]>((candidates, alignment) => {
    const fragment = fragmentById.get(alignment.fragment_id);
    if (!fragment) {
      return candidates;
    }

    const node = alignment.node_id ? xmlById.get(alignment.node_id) : undefined;
    const xmlText = node?.text ?? "";
    const pdfText = fragment.text ?? "";
    const { xmlOnlyTerms, pdfOnlyTerms } = compareTexts(xmlText, pdfText);
    const hasLinkedIssue =
      linkedIssues.has(`fragment:${fragment.fragment_id}`) ||
      (alignment.node_id ? linkedIssues.has(`node:${alignment.node_id}`) : false);
    const approved = Boolean(alignment.node_id && approvedPairs.has(`${fragment.fragment_id}:${alignment.node_id}`));
    const issues = buildEvidenceAlerts(alignment, xmlOnlyTerms, pdfOnlyTerms, hasLinkedIssue);
    const baseStatus = deriveBaseStatus(alignment, issues, approved);
    const candidateType = detectCandidateType(node?.path ?? "", xmlText);
    const reviewIssueClass = deriveReviewIssueClass(alignment, xmlOnlyTerms, pdfOnlyTerms, hasLinkedIssue);
    const reviewSourceEmphasis = deriveReviewSourceEmphasis(xmlOnlyTerms, pdfOnlyTerms);

    candidates.push({
      id: `candidate:${fragment.fragment_id}`,
      title: formatTitle(xmlText, pdfText, fragment.fragment_id),
      candidateType,
      xmlStructuralClass: candidateType,
      pdfEvidenceClass: "unknown",
      candidateSemanticClass: candidateType,
      reviewIssueClass,
      reviewSourceEmphasis,
      confidence: alignment.confidence,
      baseStatus,
      needsHumanReview: ["review required", "mismatch", "paused", "ambiguous"].includes(baseStatus),
      matched: alignment.matched,
      page: alignment.page ?? fragment.page ?? null,
      fragmentId: fragment.fragment_id,
      nodeId: alignment.node_id ?? null,
      xmlPath: node?.path ?? "No XML node linked yet",
      xmlFullPath: node?.full_path ?? node?.path ?? "No XML node linked yet",
      xmlParentNodeId: node?.parent_node_id ?? null,
      xmlRootNodeId: node?.root_node_id ?? null,
      xmlAncestorNodeIds: node?.ancestor_node_ids ?? [],
      xmlAncestorTags: node?.ancestor_tags ?? [],
      xmlContextPathSignature: node?.context_path_signature ?? null,
      xmlContextDescriptor: null,
      xmlText,
      pdfText,
      bbox: alignment.bbox ?? fragment.bbox ?? [],
      issues,
      xmlOnlyTerms,
      pdfOnlyTerms,
      rawXmlOnlyTerms: xmlOnlyTerms,
      rawPdfOnlyTerms: pdfOnlyTerms,
      ignoredStructuralTerms: [],
      candidateRelations: [],
      reconciliationRecords: [],
      graphEdges: [],
      semanticEnrichment: null,
      enrichmentHints: null,
      dependsOn: [],
      assembledClause: null,
      displayProjection: null,
    });

    return candidates;
  }, []);
}

function buildCandidates(response: IngestionResponseLike): CandidateRecord[] {
  const candidateObjects = response.review_workspace?.candidates ?? response.lineage?.candidate_objects ?? [];
  if (candidateObjects.length > 0) {
    return candidateObjects.map(mapCandidateObjectToCandidate);
  }
  const explicitUnits = response.review_workspace?.review_units ?? [];
  if (explicitUnits.length > 0) {
    return explicitUnits.map(mapReviewUnitToCandidate);
  }
  return buildLegacyCandidates(response);
}

export function CandidateReviewWorkspace({
  response,
  pdfFile,
  apiBaseUrl,
  onRelinkPdf,
}: CandidateReviewWorkspaceProps) {
  const [filter, setFilter] = useState<FilterKey>("review");
  const [relationFilter, setRelationFilter] = useState<RelationFilterKey>("all");
  const [contextFilter, setContextFilter] = useState<ContextFilter>(null);
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [currentPage, setCurrentPage] = useState(1);
  const [statusOverrides, setStatusOverrides] = useState<Record<string, ReviewStatus>>({});
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [rawInspectorTab, setRawInspectorTab] = useState<"candidate" | "evidence" | "clause" | "xml">("candidate");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [savingCandidateId, setSavingCandidateId] = useState<string | null>(null);

  const runId = response.summary?.ingestion_run_id ?? null;
  const decisionsPersisted = Boolean(runId);
  const workspaceMode = response.review_workspace?.mode ?? null;
  const workspaceReason = response.review_workspace?.reason ?? null;
  const isPdfOnlyWorkspace = workspaceMode === "pdf_only";
  const hasXmlReference = Boolean((response.review_workspace?.xml_nodes ?? response.lineage?.xml_nodes ?? []).length);
  const alignmentDisplayed = response.review_workspace?.alignment_displayed ?? 0;
  const alignmentTotal = response.review_workspace?.alignment_total ?? 0;
  const candidateCreated = response.review_workspace?.candidate_total ?? alignmentTotal;
  const candidateSurfaced = response.review_workspace?.candidate_surfaced ?? alignmentDisplayed;
  const candidateNeedsReview = response.review_workspace?.candidate_needs_review ?? 0;
  const workspaceRelationCount = response.review_workspace?.candidate_relations?.length ?? response.lineage?.candidate_relations?.length ?? 0;
  const workspaceReconciliationCount =
    response.review_workspace?.reconciliation_records?.length ?? response.lineage?.reconciliation_records?.length ?? 0;
  const workspaceReviewReconciliationCount =
    (response.review_workspace?.enrichment_counts?.review_required_reconciliations as number | undefined) ?? 0;

  useEffect(() => {
    if (pdfFile) {
      const nextUrl = URL.createObjectURL(pdfFile);
      setPdfUrl(nextUrl);
      return () => URL.revokeObjectURL(nextUrl);
    }
    setPdfUrl(null);
    return undefined;
  }, [pdfFile]);

  useEffect(() => {
    let cancelled = false;
    setStatusOverrides({});
    setDecisionError(null);

    if (!runId) {
      return undefined;
    }

    const loadDecisions = async () => {
      setDecisionsLoading(true);
      try {
        const result = await fetch(`${apiBaseUrl}/api/ingestions/runs/${runId}/review-decisions`);
        if (!result.ok) {
          const payload = await result.json().catch(() => ({}));
          throw new Error(payload.detail ?? "Failed to load saved review decisions.");
        }
        const payload = (await result.json()) as { decisions?: ReviewDecision[] };
        if (cancelled) {
          return;
        }
        const nextOverrides = Object.fromEntries(
          (payload.decisions ?? []).map((decision) => [decision.candidate_id, decision.decision_status])
        ) as Record<string, ReviewStatus>;
        setStatusOverrides(nextOverrides);
      } catch (loadError) {
        if (!cancelled) {
          setDecisionError(loadError instanceof Error ? loadError.message : "Unknown error");
        }
      } finally {
        if (!cancelled) {
          setDecisionsLoading(false);
        }
      }
    };

    void loadDecisions();
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, runId]);

  const candidates = useMemo(() => buildCandidates(response), [response]);
  const candidateCreatedCount = candidateCreated || candidates.length;
  const candidateSurfacedCount = candidateSurfaced || candidates.length;
  const candidatesWithStatus = useMemo<CandidateWithDisplayStatus[]>(
    () =>
      candidates.map((candidate) => ({
        ...candidate,
        displayStatus: statusOverrides[candidate.id] ?? candidate.baseStatus,
      })),
    [candidates, statusOverrides]
  );

  const statusFilteredCandidates = useMemo(() => {
    switch (filter) {
      case "approved":
        return candidatesWithStatus.filter((candidate) => candidate.displayStatus === "approved");
      case "rejected":
        return candidatesWithStatus.filter((candidate) => candidate.displayStatus === "rejected");
      case "review":
        return candidatesWithStatus.filter((candidate) =>
          ["review required", "mismatch", "paused", "ambiguous"].includes(candidate.displayStatus)
        );
      default:
        return candidatesWithStatus;
    }
  }, [candidatesWithStatus, filter]);

  const filteredCandidates = useMemo(() => {
    if (!contextFilter) {
      return statusFilteredCandidates;
    }
    return statusFilteredCandidates.filter((candidate) => {
      if (contextFilter.mode === "parent") {
        return candidate.xmlParentNodeId === contextFilter.value;
      }
      if (contextFilter.mode === "root") {
        return candidate.xmlRootNodeId === contextFilter.value;
      }
      if (contextFilter.mode === "pdf_parent") {
        return immediateStructuralParentCandidateId(candidate.displayProjection) === contextFilter.value;
      }
      return candidate.displayProjection?.structural_path?.[0]?.candidate_id?.trim() === contextFilter.value;
    });
  }, [contextFilter, statusFilteredCandidates]);

  const relationFilteredCandidates = useMemo(() => {
    return filterCandidatesByRelationState(filteredCandidates, relationFilter);
  }, [filteredCandidates, relationFilter]);

  const sortedCandidates = useMemo(
    () => sortCandidates(relationFilteredCandidates, sortKey),
    [relationFilteredCandidates, sortKey]
  );
  const sortedAllCandidates = useMemo(() => sortCandidates(candidatesWithStatus, sortKey), [candidatesWithStatus, sortKey]);
  const totalPages = Math.max(1, Math.ceil(sortedCandidates.length / CANDIDATE_PAGE_SIZE));
  const currentPageSafe = Math.min(currentPage, totalPages);
  const paginatedCandidates = useMemo(
    () =>
      sortedCandidates.slice(
        (currentPageSafe - 1) * CANDIDATE_PAGE_SIZE,
        currentPageSafe * CANDIDATE_PAGE_SIZE
      ),
    [currentPageSafe, sortedCandidates]
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [contextFilter, filter, relationFilter, sortKey]);

  useEffect(() => {
    if (!paginatedCandidates.length) {
      setSelectedCandidateId(null);
      return;
    }
    if (!selectedCandidateId || !paginatedCandidates.some((candidate) => candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(paginatedCandidates[0].id);
    }
  }, [paginatedCandidates, selectedCandidateId]);

  useEffect(() => {
    if (currentPage !== currentPageSafe) {
      setCurrentPage(currentPageSafe);
    }
  }, [currentPage, currentPageSafe]);

  const selectedCandidate =
    paginatedCandidates.find((candidate) => candidate.id === selectedCandidateId) ?? paginatedCandidates[0] ?? null;

  useEffect(() => {
    setRawInspectorTab("candidate");
  }, [selectedCandidate?.id]);

  useEffect(() => {
    if (rawInspectorTab === "xml" && !hasXmlReference) {
      setRawInspectorTab("candidate");
    }
  }, [hasXmlReference, rawInspectorTab]);

  const workspaceRelations = useMemo(
    () => response.review_workspace?.candidate_relations ?? response.lineage?.candidate_relations ?? [],
    [response]
  );
  const workspaceReconciliations = useMemo(
    () => response.review_workspace?.reconciliation_records ?? response.lineage?.reconciliation_records ?? [],
    [response]
  );
  const dependencyMix = useMemo(
    () => ({
      xmlExplicit: workspaceRelations.filter((relation) => relation.relation_authority === "xml_explicit").length,
      textResolved: workspaceRelations.filter((relation) => relation.relation_authority === "text_resolved").length,
      textUnresolved: workspaceRelations.filter((relation) => relation.relation_authority === "text_unresolved").length,
      manualReview: workspaceRelations.filter((relation) => relation.relation_authority === "manual_review_required").length,
      reconciliationReview: workspaceReconciliations.filter((record) => record.review_required).length,
    }),
    [workspaceReconciliations, workspaceRelations]
  );

  const selectedRelations = useMemo(() => {
    if (!selectedCandidate) {
      return [];
    }
    const localRelations = selectedCandidate.candidateRelations ?? [];
    const scopedWorkspaceRelations = workspaceRelations.filter(
      (relation) =>
        relation.source_candidate_id === selectedCandidate.id ||
        (selectedCandidate.nodeId && relation.source_node_id === selectedCandidate.nodeId)
    );
    return dedupeByKey([...localRelations, ...scopedWorkspaceRelations], (relation) =>
      String(
        relation.relation_id ??
          `${relation.source_candidate_id ?? relation.source_node_id ?? "src"}:${relation.target_locator ?? relation.target_node_id ?? "tgt"}`
      )
    );
  }, [selectedCandidate, workspaceRelations]);

  const selectedReconciliations = useMemo(() => {
    if (!selectedCandidate) {
      return [];
    }
    const localRecords = selectedCandidate.reconciliationRecords ?? [];
    const scopedWorkspaceRecords = workspaceReconciliations.filter((record) =>
      (record.source_candidate_ids ?? []).includes(selectedCandidate.id)
    );
    return dedupeByKey([...localRecords, ...scopedWorkspaceRecords], (record) =>
      String(record.reconciliation_id ?? JSON.stringify(record))
    );
  }, [selectedCandidate, workspaceReconciliations]);

  const selectedRelationSummary = useMemo(
    () => ({
      total: selectedRelations.length,
      authoritative: selectedRelations.filter((relation) => relation.relation_authority === "xml_explicit").length,
      resolved: selectedRelations.filter((relation) => relation.resolution_status === "resolved").length,
      review: selectedRelations.filter((relation) =>
        ["unresolved", "ambiguous", "review_required", "review required"].includes(
          relation.resolution_status ?? ""
        )
      ).length,
    }),
    [selectedRelations]
  );

  const workspaceSnippets = useMemo(
    () => response.review_workspace?.canonical_snippets ?? response.lineage?.canonical_snippets ?? [],
    [response]
  );

  const selectedSnippet = useMemo(() => {
    if (!selectedCandidate) {
      return null;
    }
    if (selectedCandidate.nodeId) {
      const exactSnippet = workspaceSnippets.find(
        (snippet) =>
          snippet.fragment_id === selectedCandidate.fragmentId && snippet.clause_id === selectedCandidate.nodeId
      );
      if (exactSnippet) {
        return exactSnippet;
      }
    }
    return (
      workspaceSnippets.find((snippet) => snippet.fragment_id === selectedCandidate.fragmentId) ?? null
    );
  }, [selectedCandidate, workspaceSnippets]);

  const selectedCandidateJson = useMemo(
    () => (selectedCandidate ? buildCandidateJson(selectedCandidate) : null),
    [selectedCandidate]
  );

  const candidateSourceObjects = response.review_workspace?.candidates ?? response.lineage?.candidate_objects ?? [];
  const evidencePackets = response.review_workspace?.pdf_evidence_packets ?? response.lineage?.pdf_evidence_packets ?? [];
  const workspaceXmlNodes = response.review_workspace?.xml_nodes ?? response.lineage?.xml_nodes ?? [];

  const selectedCandidateSourceObject = useMemo(
    () =>
      selectedCandidate ? candidateSourceObjects.find((candidate) => candidate.candidate_id === selectedCandidate.id) ?? null : null,
    [candidateSourceObjects, selectedCandidate]
  );

  const selectedEvidencePacket = useMemo(() => {
    if (!selectedCandidateSourceObject) {
      return null;
    }
    const semanticUnitId = selectedCandidateSourceObject.semantic_unit_id ?? null;
    const nodeId = selectedCandidateSourceObject.xml_node_id ?? null;
    return (
      evidencePackets.find((packet) => {
        const record = asRecord(packet);
        if (!record) {
          return false;
        }
        if (semanticUnitId && record.unit_id === semanticUnitId) {
          return true;
        }
        return Boolean(nodeId && record.node_id === nodeId);
      }) ?? null
    );
  }, [evidencePackets, selectedCandidateSourceObject]);

  const selectedXmlNodeRecord = useMemo(
    () =>
      selectedCandidate
        ? workspaceXmlNodes.find((node) => node.node_id === selectedCandidate.nodeId) ?? null
        : null,
    [selectedCandidate, workspaceXmlNodes]
  );

  const selectedAssembledClause = useMemo(
    () => selectedCandidateSourceObject?.assembled_clause ?? selectedCandidate?.assembledClause ?? null,
    [selectedCandidate, selectedCandidateSourceObject]
  );

  const selectedSnippetJson = useMemo(() => buildSnippetJson(selectedSnippet), [selectedSnippet]);

  const selectedDisplayProjection = useMemo(
    () => selectedCandidateSourceObject?.display_projection ?? selectedCandidate?.displayProjection ?? null,
    [selectedCandidate, selectedCandidateSourceObject]
  );

  const selectedStructuralPathEntries = useMemo<StructuralPathEntry[]>(
    () => selectedDisplayProjection?.structural_path ?? [],
    [selectedDisplayProjection]
  );

  const selectedStructuralPathText = useMemo(
    () => structuralPathLabel(selectedStructuralPathEntries),
    [selectedStructuralPathEntries]
  );

  const selectedRootStructuralCandidateId = useMemo(
    () => selectedStructuralPathEntries[0]?.candidate_id?.trim() || null,
    [selectedStructuralPathEntries]
  );

  const selectedParentHeadingCandidateId = useMemo(
    () => immediateStructuralParentCandidateId(selectedDisplayProjection),
    [selectedDisplayProjection]
  );

  const selectedParentHeadingCandidate = useMemo(
    () =>
      selectedParentHeadingCandidateId
        ? candidatesWithStatus.find((candidate) => candidate.id === selectedParentHeadingCandidateId) ?? null
        : null,
    [candidatesWithStatus, selectedParentHeadingCandidateId]
  );

  const selectedChildHeadingCandidates = useMemo(
    () => (selectedCandidate ? childPdfClauseCandidatesForParent(candidatesWithStatus, selectedCandidate.id) : []),
    [candidatesWithStatus, selectedCandidate]
  );

  const parentLineageCount = useMemo(() => {
    if (isPdfOnlyWorkspace) {
      if (!selectedParentHeadingCandidateId) {
        return 0;
      }
      return candidatesWithStatus.filter(
        (candidate) => immediateStructuralParentCandidateId(candidate.displayProjection) === selectedParentHeadingCandidateId
      ).length;
    }
    if (!selectedCandidate?.xmlParentNodeId) {
      return 0;
    }
    return candidatesWithStatus.filter((candidate) => candidate.xmlParentNodeId === selectedCandidate.xmlParentNodeId).length;
  }, [candidatesWithStatus, isPdfOnlyWorkspace, selectedCandidate, selectedParentHeadingCandidateId]);

  const rootLineageCount = useMemo(() => {
    if (isPdfOnlyWorkspace) {
      if (!selectedRootStructuralCandidateId) {
        return 0;
      }
      return candidatesWithStatus.filter(
        (candidate) => candidate.displayProjection?.structural_path?.[0]?.candidate_id?.trim() === selectedRootStructuralCandidateId
      ).length;
    }
    if (!selectedCandidate?.xmlRootNodeId) {
      return 0;
    }
    return candidatesWithStatus.filter((candidate) => candidate.xmlRootNodeId === selectedCandidate.xmlRootNodeId).length;
  }, [candidatesWithStatus, isPdfOnlyWorkspace, selectedCandidate, selectedRootStructuralCandidateId]);

  const projectionAddedFieldRows = useMemo<ComparisonRow[]>(() => {
    const addedFields = asRecord(selectedDisplayProjection?.added_fields);
    if (!addedFields) {
      return [];
    }
    return Object.entries(addedFields).map(([label, value]) => ({
      label: label.replace(/_/g, " "),
      value: formatProjectionValue(value),
    }));
  }, [selectedDisplayProjection]);

  const projectionReviewSignalRows = useMemo<ComparisonRow[]>(() => {
    const reviewSignals = asRecord(selectedDisplayProjection?.review_signals);
    if (!reviewSignals) {
      return [];
    }
    return Object.entries(reviewSignals).map(([label, value]) => ({
      label: label.replace(/_/g, " "),
      value: formatProjectionValue(value),
    }));
  }, [selectedDisplayProjection]);

  const projectionSourceRows = useMemo<ComparisonRow[]>(() => {
    const sourceProvenance = asRecord(selectedDisplayProjection?.source_provenance);
    if (!sourceProvenance) {
      return [];
    }
    return Object.entries(sourceProvenance).map(([label, value]) => ({
      label: label.replace(/_/g, " "),
      value: formatProjectionValue(value),
    }));
  }, [selectedDisplayProjection]);

  const projectionPageContextRows = useMemo<ComparisonRow[]>(() => {
    const pageContext = asRecord(selectedDisplayProjection?.page_context);
    if (!pageContext) {
      return [];
    }
    const rows: ComparisonRow[] = [];
    if ("start_page" in pageContext) {
      rows.push({ label: "Start page", value: formatProjectionValue(pageContext.start_page) });
    }
    if ("end_page" in pageContext) {
      rows.push({ label: "End page", value: formatProjectionValue(pageContext.end_page) });
    }
    if ("pages" in pageContext) {
      rows.push({ label: "Candidate pages", value: formatProjectionValue(pageContext.pages) });
    }
    if ("primary_volume_label" in pageContext) {
      rows.push({ label: "Volume", value: formatProjectionValue(pageContext.primary_volume_label) });
    }
    if ("primary_ncc_page_number" in pageContext) {
      rows.push({ label: "NCC page", value: formatProjectionValue(pageContext.primary_ncc_page_number) });
    }
    if ("ncc_page_numbers" in pageContext) {
      rows.push({ label: "NCC pages", value: formatProjectionValue(pageContext.ncc_page_numbers) });
    }
    if ("running_header_texts" in pageContext) {
      rows.push({ label: "Running header", value: formatProjectionValue(pageContext.running_header_texts) });
    }
    if ("running_footer_texts" in pageContext) {
      rows.push({ label: "Running footer", value: formatProjectionValue(pageContext.running_footer_texts) });
    }
    return rows.filter((row) => row.value && row.value !== "n/a");
  }, [selectedDisplayProjection]);

  const projectionHeaderBlocks = useMemo<RenderedClauseBlock[]>(() => {
    const explicitBlocks = selectedDisplayProjection?.header_blocks ?? [];
    if (explicitBlocks.length) {
      return explicitBlocks;
    }
    return (selectedDisplayProjection?.rendered_blocks ?? []).filter((block) => block.render_role === "header");
  }, [selectedDisplayProjection]);

  const projectionMarginaliaBlocks = useMemo<RenderedClauseBlock[]>(() => {
    const explicitBlocks = selectedDisplayProjection?.marginalia_blocks ?? [];
    if (explicitBlocks.length) {
      return explicitBlocks;
    }
    return (selectedDisplayProjection?.rendered_blocks ?? []).filter((block) => block.render_role === "annotation");
  }, [selectedDisplayProjection]);

  const projectionBodyBlocks = useMemo<RenderedClauseBlock[]>(() => {
    const renderedBlocks = selectedDisplayProjection?.rendered_blocks ?? [];
    if (!renderedBlocks.length) {
      return [];
    }
    return renderedBlocks.filter((block) => !["header", "annotation"].includes(block.render_role ?? ""));
  }, [selectedDisplayProjection]);

  const rawInspectorTabs = useMemo(
    () =>
      [
        { key: "candidate", label: "Candidate" },
        { key: "evidence", label: "Evidence" },
        { key: "clause", label: "Assembled Clause" },
        ...(hasXmlReference ? [{ key: "xml", label: isPdfOnlyWorkspace ? "XML Reference" : "XML Node" }] : []),
      ] as Array<{ key: "candidate" | "evidence" | "clause" | "xml"; label: string }>,
    [hasXmlReference, isPdfOnlyWorkspace]
  );

  const rawInspectorPayload = useMemo(() => {
    switch (rawInspectorTab) {
      case "evidence":
        return selectedEvidencePacket ?? { state: "no_evidence_packet" };
      case "clause":
        return selectedAssembledClause ?? { state: "no_assembled_clause" };
      case "xml":
        return selectedXmlNodeRecord ?? { state: "no_matched_xml_node" };
      default:
        return selectedCandidateSourceObject ?? selectedCandidateJson ?? { state: "no_candidate" };
    }
  }, [
    rawInspectorTab,
    selectedAssembledClause,
    selectedCandidateJson,
    selectedCandidateSourceObject,
    selectedEvidencePacket,
    selectedXmlNodeRecord,
  ]);

  const candidateComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    return [
      { label: "Semantic class", value: selectedCandidate.candidateSemanticClass },
      { label: "XML structural class", value: selectedCandidate.xmlStructuralClass },
      { label: "PDF evidence class", value: selectedCandidate.pdfEvidenceClass },
      { label: "Issue class", value: selectedCandidate.reviewIssueClass.replace(/_/g, " ") },
      { label: "Source emphasis", value: selectedCandidate.reviewSourceEmphasis },
      {
        label: "Link status",
        value: isPdfOnlyWorkspace
          ? selectedCandidate.nodeId
            ? "PDF-native candidate with XML reference"
            : "PDF-native candidate"
          : selectedCandidate.nodeId
            ? "Linked to XML node"
            : "No XML node linked",
      },
      {
        label: "Approval state",
        value: isPdfOnlyWorkspace
          ? "Snippet promotion disabled in PDF-only review"
          : selectedSnippet
            ? "Promoted snippet exists"
            : "No promoted snippet yet",
      },
      { label: "Display status", value: selectedCandidate.displayStatus },
      { label: "Base status", value: selectedCandidate.baseStatus },
      { label: "Depends on", value: selectedCandidate.dependsOn.length ? selectedCandidate.dependsOn.join(", ") : "none" },
      { label: "Relations", value: String(selectedRelationSummary.total) },
      { label: "Reconciliation records", value: String(selectedReconciliations.length) },
      { label: "Matched", value: String(selectedCandidate.matched) },
      { label: "Confidence", value: selectedCandidate.confidence.toFixed(3) },
      { label: "Start page", value: selectedCandidate.page ? String(selectedCandidate.page) : "n/a" },
      { label: "BBox", value: formatBbox(selectedCandidate.bbox) },
      {
        label: "Page context volume",
        value: formatProjectionValue(asRecord(selectedDisplayProjection?.page_context)?.primary_volume_label),
      },
      {
        label: "Page context NCC page",
        value: formatProjectionValue(asRecord(selectedDisplayProjection?.page_context)?.primary_ncc_page_number),
      },
      {
        label: "Page span",
        value: formatProjectionValue(asRecord(selectedDisplayProjection?.page_context)?.pages),
      },
    ];
  }, [
    isPdfOnlyWorkspace,
    selectedCandidate,
    selectedDisplayProjection,
    selectedReconciliations.length,
    selectedRelationSummary.total,
    selectedSnippet,
  ]);

  const xmlComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    return [
      { label: isPdfOnlyWorkspace ? "Reference XML path" : "XML path", value: selectedCandidate.xmlPath },
      { label: isPdfOnlyWorkspace ? "Reference full XML path" : "Full XML path", value: selectedCandidate.xmlFullPath },
      { label: "Context signature", value: selectedCandidate.xmlContextPathSignature ?? "n/a" },
      { label: "Parent node", value: selectedCandidate.xmlParentNodeId ?? "n/a" },
      { label: "Root node", value: selectedCandidate.xmlRootNodeId ?? "n/a" },
      { label: "Ancestor tags", value: formatList(selectedCandidate.xmlAncestorTags) },
      { label: "Missing in PDF", value: formatList(selectedCandidate.xmlOnlyTerms) },
      { label: "Raw XML-only terms", value: formatList(selectedCandidate.rawXmlOnlyTerms) },
      { label: "XML text length", value: String(cleanText(selectedCandidate.xmlText).length) },
    ];
  }, [isPdfOnlyWorkspace, selectedCandidate]);

  const pdfComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    const evidencePage = asRecord(selectedCandidateSourceObject?.evidence?.[0])?.page;
    return [
      { label: "Fragment id", value: selectedCandidate.fragmentId },
      {
        label: "Primary evidence page",
        value: typeof evidencePage === "number" ? String(evidencePage) : "n/a",
      },
      { label: "Missing in XML", value: formatList(selectedCandidate.pdfOnlyTerms) },
      { label: "Raw PDF-only terms", value: formatList(selectedCandidate.rawPdfOnlyTerms) },
      { label: "PDF text length", value: String(cleanText(selectedCandidate.pdfText).length) },
    ];
  }, [selectedCandidate, selectedCandidateSourceObject]);

  const snippetComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedSnippet) {
      return [];
    }
    return [
      { label: "Clause id", value: selectedSnippet.clause_id ?? "n/a" },
      { label: "Fragment id", value: selectedSnippet.fragment_id ?? "n/a" },
      { label: "Confidence", value: typeof selectedSnippet.confidence === "number" ? selectedSnippet.confidence.toFixed(3) : "n/a" },
      { label: "Snippet length", value: String(cleanText(selectedSnippet.content).length) },
    ];
  }, [selectedSnippet]);

  const mismatchSummaryRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    return [
      { label: "Blocked by validation issue", value: selectedCandidate.issues.some((issue) => issue.includes("Validation warnings or errors")) ? "Yes" : "No" },
      { label: isPdfOnlyWorkspace ? "PDF-only additions" : "Missing in XML", value: formatList(selectedCandidate.pdfOnlyTerms) },
      { label: isPdfOnlyWorkspace ? "Reference XML-only terms" : "Missing in PDF", value: formatList(selectedCandidate.xmlOnlyTerms) },
      { label: "Ignored structural terms", value: formatList(selectedCandidate.ignoredStructuralTerms) },
      { label: "Issue summary", value: selectedCandidate.issues[0] ?? "No review issues flagged" },
    ];
  }, [isPdfOnlyWorkspace, selectedCandidate]);

  const selectedQueueIndex = useMemo(() => {
    if (!selectedCandidate) {
      return null;
    }
    const index = sortedCandidates.findIndex((candidate) => candidate.id === selectedCandidate.id);
    return index >= 0 ? index + 1 : null;
  }, [selectedCandidate, sortedCandidates]);

  const counts = useMemo(
    () => ({
      review: candidatesWithStatus.filter((candidate) =>
        ["review required", "mismatch", "paused", "ambiguous"].includes(candidate.displayStatus)
      ).length,
      match: candidatesWithStatus.filter((candidate) => candidate.displayStatus === "match").length,
      approved: candidatesWithStatus.filter((candidate) => candidate.displayStatus === "approved").length,
      rejected: candidatesWithStatus.filter((candidate) => candidate.displayStatus === "rejected").length,
      all: candidatesWithStatus.length,
    }),
    [candidatesWithStatus]
  );

  const needsHumanReviewCount = counts.review;

  useEffect(() => {
    if (filter === "review" && counts.review === 0 && counts.all > 0) {
      setFilter("all");
    }
  }, [counts.all, counts.review, filter]);

  const candidatePageSummary = useMemo(
    () => summarizePages(candidates.map((candidate) => candidate.page)),
    [candidates]
  );

  const scopeSummary = useMemo(() => {
    if (!candidates.length) {
      return "No candidate pages are available yet.";
    }
    if (candidatePageSummary.endsWith("only")) {
      return `The current candidate set is drawing evidence from ${candidatePageSummary.toLowerCase()}. This reflects the active reviewable fragment set, not necessarily the entire PDF.`;
    }
    return `The current candidate set spans ${candidatePageSummary.toLowerCase()}.`;
  }, [candidatePageSummary, candidates]);

  const hasScopedSubset = candidateCreatedCount > candidateSurfacedCount && candidateSurfacedCount > 0;

  async function updateStatus(nextStatus: ReviewStatus) {
    if (!selectedCandidate) {
      return;
    }

    const candidateId = selectedCandidate.id;
    const previousStatus = statusOverrides[candidateId];
    setDecisionError(null);
    setStatusOverrides((current) => ({
      ...current,
      [candidateId]: nextStatus,
    }));

    if (!runId) {
      return;
    }

    setSavingCandidateId(candidateId);
    try {
      const result = await fetch(`${apiBaseUrl}/api/ingestions/runs/${runId}/review-decisions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          candidate_id: candidateId,
          fragment_id: selectedCandidate.fragmentId,
          node_id: selectedCandidate.nodeId,
          decision_status: nextStatus,
        }),
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to save review decision.");
      }
    } catch (saveError) {
      setStatusOverrides((current) => {
        const next = { ...current };
        if (previousStatus) {
          next[candidateId] = previousStatus;
        } else {
          delete next[candidateId];
        }
        return next;
      });
      setDecisionError(saveError instanceof Error ? saveError.message : "Unknown error");
    } finally {
      setSavingCandidateId(null);
    }
  }

  function jumpToCandidate(candidateId: string) {
    const targetIndex = sortedAllCandidates.findIndex((candidate) => candidate.id === candidateId);
    if (targetIndex < 0) {
      return;
    }
    setFilter("all");
    setRelationFilter("all");
    setContextFilter(null);
    setCurrentPage(Math.floor(targetIndex / CANDIDATE_PAGE_SIZE) + 1);
    setSelectedCandidateId(candidateId);
  }

  return (
    <section className="panel">
      <div className="workspace-header">
        <div>
          <h2>Candidate Review Workspace</h2>
          <p>
            Transitional review workspace backed by explicit review units from the backend, with lightweight
            persisted reviewer decisions for early human-in-the-loop testing.
          </p>
          <p className="muted">
            Mode: {formatWorkspaceLabel(workspaceMode)} | Reason: {formatWorkspaceLabel(workspaceReason)}
          </p>
          <p className="muted">Run recorded {formatDateTime(response.summary?.created_at)}.</p>
        </div>
        <span className={`status ${response.summary?.can_progress ? "pass" : "warn"}`}>
          {response.summary?.can_progress ? "Can Progress" : "Review Flow Active"}
        </span>
      </div>

      <div className="workspace-summary">
        <div className="summary-card">
          <strong>Document Family</strong>
          <span>{response.summary?.document_family_id ?? "n/a"}</span>
        </div>
        <div className="summary-card">
          <strong>Workspace Mode</strong>
          <span>{formatWorkspaceLabel(workspaceMode)}</span>
        </div>
        <div className="summary-card">
          <strong>Candidates Created</strong>
          <span>{candidateCreatedCount}</span>
          <span className="summary-subtext">Validation pass total</span>
        </div>
        <div className="summary-card">
          <strong>Candidates Surfaced</strong>
          <span>{candidateSurfacedCount}</span>
          <span className="summary-subtext">Current workspace population</span>
        </div>
        <div className="summary-card">
          <strong>Needs Human Review</strong>
          <span>{needsHumanReviewCount}</span>
          <span className="summary-subtext">Subset needing operator attention</span>
        </div>
        <div className="summary-card">
          <strong>Matched</strong>
          <span>{counts.match}</span>
        </div>
        <div className="summary-card">
          <strong>Approved</strong>
          <span>{counts.approved}</span>
        </div>
        <div className="summary-card">
          <strong>Rejected</strong>
          <span>{counts.rejected}</span>
        </div>
        <div className="summary-card">
          <strong>Candidate Pages</strong>
          <span>{candidatePageSummary}</span>
        </div>
        <div className="summary-card">
          <strong>Relations Surfaced</strong>
          <span>{workspaceRelationCount}</span>
          <span className="summary-subtext">Run-level dependency ledger</span>
        </div>
        <div className="summary-card">
          <strong>Reconciliation Records</strong>
          <span>{workspaceReconciliationCount}</span>
          <span className="summary-subtext">
            {workspaceReviewReconciliationCount
              ? `${workspaceReviewReconciliationCount} still need review`
              : "No review escalations surfaced"}
          </span>
        </div>
      </div>

      <section className="panel-muted dependency-diagnostics-strip">
        <div className="dependency-diagnostics-copy">
          <strong>Dependency diagnostics</strong>
          <p className="muted">
            This run blends authoritative XML relations with text-derived references. Use this strip to understand the
            dependency mix before filtering the queue.
          </p>
        </div>
        <div className="dependency-diagnostics-grid">
          <div className="dependency-diagnostic-card dependency-diagnostic-card-authoritative">
            <span className="dependency-diagnostic-label">XML explicit</span>
            <strong>{dependencyMix.xmlExplicit}</strong>
            <span className="summary-subtext">Authoritative structural links</span>
          </div>
          <div className="dependency-diagnostic-card dependency-diagnostic-card-resolved">
            <span className="dependency-diagnostic-label">Text resolved</span>
            <strong>{dependencyMix.textResolved}</strong>
            <span className="summary-subtext">Prose references mapped to known targets</span>
          </div>
          <div className="dependency-diagnostic-card dependency-diagnostic-card-review">
            <span className="dependency-diagnostic-label">Text unresolved</span>
            <strong>{dependencyMix.textUnresolved}</strong>
            <span className="summary-subtext">Ambiguous or unresolved prose dependencies</span>
          </div>
          <div className="dependency-diagnostic-card dependency-diagnostic-card-neutral">
            <span className="dependency-diagnostic-label">Manual review</span>
            <strong>{dependencyMix.manualReview}</strong>
            <span className="summary-subtext">Explicitly review-routed relation records</span>
          </div>
          <div className="dependency-diagnostic-card dependency-diagnostic-card-review">
            <span className="dependency-diagnostic-label">Reconciliation review</span>
            <strong>{dependencyMix.reconciliationReview}</strong>
            <span className="summary-subtext">Records still escalated for reviewer attention</span>
          </div>
        </div>
      </section>

      {decisionsLoading ? <p className="muted">Loading persisted reviewer decisions...</p> : null}
      <p className="muted">
        {decisionsPersisted
          ? `Reviewer decisions persist to ingestion run ${runId}.`
          : "Reviewer decisions are local-only until the backend returns an ingestion run id."}
      </p>
      {decisionError ? (
        <p className="alert alert-error" role="alert">
          {decisionError}
        </p>
      ) : null}
      <div className="panel-muted workspace-explainer">
        <p>
          <strong>Current review scope</strong>: {scopeSummary}
        </p>
        <p>
          <strong>Outcome guide</strong>: Surfaced candidates are the items included in this workspace. Review Queue
          is only the subset still needing human attention. Matched means a candidate aligned cleanly, even if it
          still appears in the surfaced workspace for visibility.
        </p>
        {hasScopedSubset ? (
          <p className="muted">
            This workspace is showing {candidateSurfacedCount} surfaced candidates out of {candidateCreatedCount} created by
            validation, so you are looking at a narrowed review slice rather than every extracted fragment.
          </p>
        ) : null}
        <p className="muted">
          Confidence `1.0` candidates can still appear here when they are surfaced for comparison or traceability,
          but they should not count toward `Needs Human Review` unless another issue forces review.
        </p>
        {!counts.approved ? (
          <p className="muted">
            No approved candidates are visible in this run yet. A candidate can still be a clean match without
            appearing in the approved-snippet section.
          </p>
        ) : null}
        <p className="muted">
          The left panel is filterable, sortable, and paginated so larger surfaced candidate sets stay manageable.
        </p>
      </div>

      <div className="filter-row" role="toolbar" aria-label="Candidate filters">
        {(Object.keys(FILTER_LABELS) as FilterKey[]).map((key) => (
          <button
            key={key}
            type="button"
            className={`filter-chip ${filter === key ? "active" : ""}`}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {FILTER_LABELS[key]}
          </button>
        ))}
        {contextFilter ? (
          <button
            type="button"
            className="filter-chip active"
            aria-pressed="true"
            onClick={() => setContextFilter(null)}
          >
            Clear {contextFilter.mode.startsWith("pdf_") ? "PDF" : "XML"}{" "}
            {contextFilter.mode.endsWith("parent") ? "parent" : "root"} filter: {contextFilter.value}
          </button>
        ) : null}
      </div>

      <div className="workspace-layout">
        <aside className="candidate-sidebar">
          <div className="panel-muted candidate-sidebar-controls">
            <div className="candidate-sidebar-header">
              <div>
                <strong>{FILTER_LABELS[filter]}</strong>
                <p className="muted">
                  {sortedCandidates.length} candidates in this view, page {currentPageSafe} of {totalPages}.
                </p>
              </div>
            </div>
            <div className="candidate-sort-row">
              <label htmlFor="candidate-sort">Sort surfaced candidates</label>
              <select
                id="candidate-sort"
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value as SortKey)}
              >
                {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                  <option key={key} value={key}>
                    {SORT_LABELS[key]}
                  </option>
                ))}
              </select>
              <p className="muted candidate-sort-note">Active sort: {SORT_LABELS[sortKey]}.</p>
            </div>
            <div className="candidate-sort-row">
              <label htmlFor="relation-filter">Dependency filter</label>
              <select
                id="relation-filter"
                value={relationFilter}
                onChange={(event) => setRelationFilter(event.target.value as RelationFilterKey)}
              >
                {(Object.keys(RELATION_FILTER_LABELS) as RelationFilterKey[]).map((key) => (
                  <option key={key} value={key}>
                    {RELATION_FILTER_LABELS[key]}
                  </option>
                ))}
              </select>
              <p className="muted candidate-sort-note">Active dependency filter: {RELATION_FILTER_LABELS[relationFilter]}.</p>
            </div>
          </div>
          {paginatedCandidates.length ? (
            paginatedCandidates.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                className={`candidate-list-item ${selectedCandidate?.id === candidate.id ? "selected" : ""}`}
                title={candidate.title}
                onClick={() => setSelectedCandidateId(candidate.id)}
              >
                <div className="candidate-list-top">
                  <strong>{candidate.title}</strong>
                  <span className={statusClass(candidate.displayStatus)}>{candidate.displayStatus}</span>
                </div>
                <div className="candidate-meta">
                  <span>{candidate.candidateType}</span>
                  <span>Page {candidate.page ?? "n/a"}</span>
                  <span>Confidence {candidate.confidence.toFixed(3)}</span>
                  <span>{candidate.reviewIssueClass.replace(/_/g, " ")}</span>
                  <span>{candidate.reviewSourceEmphasis}</span>
                </div>
                <div className="candidate-diagnostics-row">
                  <span className="diagnostic-chip">
                    {candidate.candidateRelations.length} relation{candidate.candidateRelations.length === 1 ? "" : "s"}
                  </span>
                  <span className="diagnostic-chip">
                    {candidate.reconciliationRecords.length} reconciliation{candidate.reconciliationRecords.length === 1 ? "" : "s"}
                  </span>
                  {candidate.dependsOn.length ? (
                    <span className="diagnostic-chip diagnostic-chip-accent">
                      depends on {candidate.dependsOn.length}
                    </span>
                  ) : null}
                </div>
                <div className="candidate-lineage-summary">
                  <span className="candidate-lineage-breadcrumb">{summarizeXmlLineage(candidate)}</span>
                  <span className="candidate-lineage-meta">{summarizeSidebarXmlContext(candidate)}</span>
                </div>
              </button>
            ))
          ) : (
            <div className="empty-state candidate-empty-state">
              <p>
                {filter === "review" && counts.all > 0
                  ? "No candidates currently need human review. Switch to All Candidates to inspect the full surfaced set."
                  : "No candidates in this view yet."}
              </p>
              {filter !== "all" && counts.all > 0 ? (
                <button type="button" className="button-secondary" onClick={() => setFilter("all")}>
                  Show All Candidates
                </button>
              ) : null}
            </div>
          )}
          {sortedCandidates.length > CANDIDATE_PAGE_SIZE ? (
            <div className="panel-muted candidate-pagination">
              <span>
                Page {currentPageSafe} of {totalPages}
              </span>
              <div className="candidate-pagination-actions">
                <button
                  type="button"
                  className="button-secondary"
                  disabled={currentPageSafe <= 1}
                  onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={currentPageSafe >= totalPages}
                  onClick={() => setCurrentPage((current) => Math.min(totalPages, current + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </aside>

        <div className="candidate-main">
          {selectedCandidate ? (
            <>
              <section className="panel subsection">
                <div className="workspace-header">
                  <div>
                    <h3>{selectedCandidate.title}</h3>
                    <p>
                      Type: {selectedCandidate.candidateType} | Fragment: {selectedCandidate.fragmentId} | Node:{" "}
                      {selectedCandidate.nodeId ?? "unlinked"}
                    </p>
                    <p className="muted">
                      Queue item {selectedQueueIndex ?? "n/a"} of {sortedCandidates.length} in{" "}
                      {FILTER_LABELS[filter]}.
                    </p>
                    <p className="muted">{describeCandidateStatus(selectedCandidate)}</p>
                    <div className="candidate-context-cluster">
                      <span className="candidate-context-chip">
                        {isPdfOnlyWorkspace
                          ? parentLineageCount > 1
                            ? `${parentLineageCount} candidates share parent ${selectedParentHeadingCandidate?.title ?? selectedParentHeadingCandidateId ?? "n/a"}`
                            : selectedParentHeadingCandidate?.title ?? selectedParentHeadingCandidateId
                              ? `Only candidate under parent ${selectedParentHeadingCandidate?.title ?? selectedParentHeadingCandidateId}`
                              : "No parent lineage id available"
                          : parentLineageCount > 1
                            ? `${parentLineageCount} candidates share parent ${selectedCandidate.xmlParentNodeId ?? "n/a"}`
                            : selectedCandidate.xmlParentNodeId
                              ? `Only candidate under parent ${selectedCandidate.xmlParentNodeId}`
                              : "No parent lineage id available"}
                      </span>
                      <span className="candidate-context-chip">
                        {isPdfOnlyWorkspace
                          ? rootLineageCount > 1
                            ? `${rootLineageCount} candidates share root ${selectedStructuralPathEntries[0]?.title ?? selectedRootStructuralCandidateId ?? "n/a"}`
                            : selectedStructuralPathEntries[0]?.title ?? selectedRootStructuralCandidateId
                              ? `Only candidate under root ${selectedStructuralPathEntries[0]?.title ?? selectedRootStructuralCandidateId}`
                              : "No root lineage id available"
                          : rootLineageCount > 1
                            ? `${rootLineageCount} candidates share root ${selectedCandidate.xmlRootNodeId ?? "n/a"}`
                            : selectedCandidate.xmlRootNodeId
                              ? `Only candidate under root ${selectedCandidate.xmlRootNodeId}`
                              : "No root lineage id available"}
                      </span>
                    </div>
                  </div>
                  <span className={statusClass(selectedCandidate.displayStatus)}>
                    {selectedCandidate.displayStatus}
                  </span>
                </div>

                <div className="action-row">
                  <button
                    type="button"
                    disabled={!decisionsPersisted || savingCandidateId === selectedCandidate.id}
                    onClick={() => void updateStatus("approved")}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={!decisionsPersisted || savingCandidateId === selectedCandidate.id}
                    onClick={() => void updateStatus("rejected")}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={!decisionsPersisted || savingCandidateId === selectedCandidate.id}
                    onClick={() => void updateStatus("paused")}
                  >
                    Pause
                  </button>
                  <button
                    type="button"
                    disabled={!decisionsPersisted || savingCandidateId === selectedCandidate.id}
                    onClick={() => void updateStatus("ambiguous")}
                  >
                    Mark Ambiguous
                  </button>
                  <button
                    type="button"
                    disabled={!decisionsPersisted || savingCandidateId === selectedCandidate.id}
                    onClick={() => void updateStatus(selectedCandidate.baseStatus)}
                  >
                    Revert to suggested status
                  </button>
                </div>

                {savingCandidateId === selectedCandidate.id ? (
                  <p className="muted">Saving reviewer decision...</p>
                ) : null}
                {!decisionsPersisted ? (
                  <p className="muted">
                    Decision actions are disabled until this result is associated with a persisted ingestion run.
                  </p>
                ) : null}

                {isPdfOnlyWorkspace ? (
                  <section className="panel-muted candidate-lineage-panel">
                    <div className="section-header compact">
                      <div>
                        <h4>PDF Review Context</h4>
                        <p className="muted">
                          This workspace is anchored to PDF-native candidates. XML, when present, is shown only as
                          secondary reference context.
                        </p>
                      </div>
                    </div>
                    <div className="detail-list">
                      <div>
                        <strong>Reference XML available</strong>: {hasXmlReference ? "Yes" : "No"}
                      </div>
                      <div>
                        <strong>Candidate fragment</strong>: {selectedCandidate.fragmentId}
                      </div>
                      <div>
                        <strong>Candidate page</strong>: {selectedCandidate.page ?? "n/a"}
                      </div>
                    </div>
                  </section>
                ) : (
                  <section className="panel-muted candidate-lineage-panel">
                    <div className="section-header compact">
                      <div>
                        <h4>XML Context</h4>
                        <p className="muted">
                          Breadcrumbs and lineage keep this candidate anchored to its XML parent and root context.
                        </p>
                      </div>
                    </div>
                    <div className="detail-list">
                      <div>
                        <strong>Context breadcrumb</strong>: {summarizeXmlLineage(selectedCandidate)}
                      </div>
                      <div>
                        <strong>Ancestor node ids</strong>: {formatList(selectedCandidate.xmlAncestorNodeIds)}
                      </div>
                      <div>
                        <strong>Full XML path</strong>:{" "}
                        <code className="baseline-inline-code">{selectedCandidate.xmlFullPath}</code>
                      </div>
                    </div>
                    <div className="action-row candidate-context-actions">
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={isPdfOnlyWorkspace ? !selectedParentHeadingCandidateId : !selectedCandidate.xmlParentNodeId}
                        onClick={() =>
                          isPdfOnlyWorkspace
                            ? selectedParentHeadingCandidateId
                              ? setContextFilter({ mode: "pdf_parent", value: selectedParentHeadingCandidateId })
                              : undefined
                            : selectedCandidate.xmlParentNodeId
                              ? setContextFilter({ mode: "parent", value: selectedCandidate.xmlParentNodeId })
                              : undefined
                        }
                      >
                        Same parent ({parentLineageCount || 0})
                      </button>
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={isPdfOnlyWorkspace ? !selectedRootStructuralCandidateId : !selectedCandidate.xmlRootNodeId}
                        onClick={() =>
                          isPdfOnlyWorkspace
                            ? selectedRootStructuralCandidateId
                              ? setContextFilter({ mode: "pdf_root", value: selectedRootStructuralCandidateId })
                              : undefined
                            : selectedCandidate.xmlRootNodeId
                              ? setContextFilter({ mode: "root", value: selectedCandidate.xmlRootNodeId })
                              : undefined
                        }
                      >
                        Same root ({rootLineageCount || 0})
                      </button>
                      {contextFilter ? (
                        <button type="button" className="button-secondary" onClick={() => setContextFilter(null)}>
                          Clear context filter
                        </button>
                      ) : null}
                    </div>
                  </section>
                )}

                <section className="panel-muted relation-ledger-panel">
                  <div className="section-header compact">
                    <div>
                      <h4>Dependency and Reconciliation</h4>
                      <p className="muted">
                        {isPdfOnlyWorkspace
                          ? "XML-derived relation, reconciliation, and promotion signals are downgraded in PDF-only mode."
                          : "A compact ledger of authoritative XML links, text-derived references, and review-stage reconciliation outcomes for this candidate."}
                      </p>
                    </div>
                  </div>
                  <div className="relation-summary-grid">
                    <div className="summary-card relation-summary-card">
                      <strong>Total relations</strong>
                      <span>{selectedRelationSummary.total}</span>
                      <span className="summary-subtext">All surfaced links for this candidate</span>
                    </div>
                    <div className="summary-card relation-summary-card">
                      <strong>XML explicit</strong>
                      <span>{selectedRelationSummary.authoritative}</span>
                      <span className="summary-subtext">Authoritative structural references</span>
                    </div>
                    <div className="summary-card relation-summary-card">
                      <strong>Resolved</strong>
                      <span>{selectedRelationSummary.resolved}</span>
                      <span className="summary-subtext">Targets mapped to known candidates</span>
                    </div>
                    <div className="summary-card relation-summary-card">
                      <strong>Needs review</strong>
                      <span>{selectedRelationSummary.review}</span>
                      <span className="summary-subtext">Unresolved or ambiguous dependencies</span>
                    </div>
                  </div>
                  <div className="comparison-grid relation-ledger-grid">
                    <div className="evidence-panel relation-panel">
                      <h4>Candidate Relations</h4>
                      {selectedRelations.length ? (
                        <div className="relation-card-list">
                          {selectedRelations.map((relation) => (
                            <article key={relation.relation_id ?? `${relation.source_candidate_id}-${relation.target_locator}`}>
                              <div className="relation-card-header">
                                <strong>{formatRelationLabel(relation.relation_kind)}</strong>
                                <div className="relation-pill-row">
                                  <span className={`relation-pill relation-pill-${relationTone(relation.relation_authority)}`}>
                                    {formatRelationLabel(relation.relation_authority)}
                                  </span>
                                  <span className={`status ${relationStatusTone(relation.resolution_status)}`}>
                                    {formatRelationLabel(relation.resolution_status)}
                                  </span>
                                </div>
                              </div>
                              <div className="comparison-field-list relation-field-list">
                                <div className="comparison-field-row">
                                  <strong>Target</strong>
                                  <span>{relation.target_locator ?? relation.target_node_id ?? relation.target_candidate_id ?? "n/a"}</span>
                                </div>
                                <div className="comparison-field-row">
                                  <strong>Target candidate</strong>
                                  <span>{relation.target_candidate_id ?? "n/a"}</span>
                                </div>
                                <div className="comparison-field-row">
                                  <strong>Confidence</strong>
                                  <span>
                                    {typeof relation.confidence === "number" ? relation.confidence.toFixed(3) : "n/a"}
                                  </span>
                                </div>
                                <div className="comparison-field-row">
                                  <strong>Provenance</strong>
                                  <span>{formatRelationLabel(relation.provenance?.source_authority)}</span>
                                </div>
                              </div>
                              <p className="relation-card-note">
                                {truncateText(
                                  relation.provenance?.evidence_spans?.[0] ?? relation.raw_value ?? relation.target_locator
                                )}
                              </p>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="empty-state comparison-empty-state">
                          No relation records are attached to this candidate yet.
                        </div>
                      )}
                    </div>
                    <div className="evidence-panel relation-panel">
                      <h4>Reconciliation Records</h4>
                      {selectedReconciliations.length ? (
                        <div className="relation-card-list">
                          {selectedReconciliations.map((record) => (
                            <article
                              key={record.reconciliation_id ?? JSON.stringify(record)}
                              className={record.review_required ? "relation-card-review" : undefined}
                            >
                              <div className="relation-card-header">
                                <strong>{formatRelationLabel(record.classification)}</strong>
                                <div className="relation-pill-row">
                                  <span className={`status ${record.review_required ? "warn" : "pass"}`}>
                                    {record.review_required ? "review required" : "tracked"}
                                  </span>
                                </div>
                              </div>
                              <div className="comparison-field-list relation-field-list">
                                <div className="comparison-field-row">
                                  <strong>Promotion effect</strong>
                                  <span>{formatRelationLabel(record.promotion_effect)}</span>
                                </div>
                                <div className="comparison-field-row">
                                  <strong>Relation ids</strong>
                                  <span>{record.source_relation_ids?.join(", ") ?? "n/a"}</span>
                                </div>
                                <div className="comparison-field-row">
                                  <strong>Candidate ids</strong>
                                  <span>{record.source_candidate_ids?.join(", ") ?? "n/a"}</span>
                                </div>
                              </div>
                              <p className="relation-card-note">{truncateText(record.notes)}</p>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="empty-state comparison-empty-state">
                          No reconciliation records are surfaced for this candidate.
                        </div>
                      )}
                    </div>
                  </div>
                </section>

                <section className="comparison-section">
                  <div className="section-header compact">
                    <div>
                      <h4>Candidate Inspector</h4>
                      <p className="muted">
                        Raw backend payloads stay on the left, while a clause-like rendering keeps source text,
                        added fields, and review signals separated on the right.
                      </p>
                    </div>
                  </div>
                  <div className="candidate-inspector-grid">
                    <div className="evidence-panel candidate-raw-panel">
                      <div className="candidate-raw-panel-header">
                        <h4>Raw JSON</h4>
                        <div className="candidate-raw-tab-row">
                          {rawInspectorTabs.map((tab) => (
                            <button
                              key={tab.key}
                              type="button"
                              className={rawInspectorTab === tab.key ? "button-secondary active" : "button-secondary"}
                              onClick={() => setRawInspectorTab(tab.key as "candidate" | "evidence" | "clause" | "xml")}
                            >
                              {tab.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <pre className="candidate-raw-json">{JSON.stringify(rawInspectorPayload, null, 2)}</pre>
                    </div>

                    <div className="evidence-panel candidate-rendered-panel">
                      <div className="section-header compact">
                        <div>
                          <h4>Rendered Clause</h4>
                          <p className="muted">
                            Clause-like projection grounded in assembled PDF blocks, with derived metadata surfaced
                            separately for review.
                          </p>
                        </div>
                      </div>

                      <section className="panel-muted clause-render-panel">
                        <div className="section-header compact">
                          <div>
                            <h5>Source Clause</h5>
                            <p className="muted">
                              {selectedDisplayProjection?.clause_path?.length
                                ? `Path: ${selectedDisplayProjection.clause_path.join(" > ")}`
                                : "No numbered clause path was inferred for this candidate."}
                            </p>
                          </div>
                          {selectedDisplayProjection?.clause_label ? (
                            <span className="candidate-context-chip">{selectedDisplayProjection.clause_label}</span>
                          ) : null}
                        </div>
                        {(selectedDisplayProjection?.clause_code || selectedDisplayProjection?.heading_text) ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Clause code</strong>
                              <span>{selectedDisplayProjection?.clause_code ?? "n/a"}</span>
                            </div>
                            <div className="comparison-field-row">
                              <strong>Heading</strong>
                              <span>{selectedDisplayProjection?.heading_text ?? "n/a"}</span>
                            </div>
                          </div>
                        ) : null}
                        {selectedStructuralPathText ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Structural path</strong>
                              <span>{selectedStructuralPathText}</span>
                              <div className="candidate-context-cluster">
                                {selectedStructuralPathEntries.map((entry, index) => {
                                  const entryCandidateId = entry.candidate_id?.trim();
                                  const entryLabel = entry.title ?? entry.label ?? entry.text ?? `Level ${index + 1}`;
                                  return entryCandidateId ? (
                                    <button
                                      key={`${entryCandidateId}:${index}`}
                                      type="button"
                                      className="button-secondary parent-jump-button"
                                      onClick={() => jumpToCandidate(entryCandidateId)}
                                    >
                                      {entryLabel}
                                    </button>
                                  ) : (
                                    <span key={`${entryLabel}:${index}`} className="candidate-context-chip">
                                      {entryLabel}
                                    </span>
                                  );
                                })}
                              </div>
                            </div>
                          </div>
                        ) : null}
                        {selectedDisplayProjection?.parent_heading_title ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Parent part</strong>
                              <span>{selectedDisplayProjection.parent_heading_label ?? selectedDisplayProjection.parent_heading_title}</span>
                            </div>
                            <div className="comparison-field-row">
                              <strong>Parent heading</strong>
                              <span>{selectedDisplayProjection.parent_heading_text ?? selectedDisplayProjection.parent_heading_title}</span>
                            </div>
                            {selectedParentHeadingCandidate ? (
                              <div className="comparison-field-row">
                                <strong>Parent candidate</strong>
                                <span>{selectedParentHeadingCandidate.title}</span>
                                <button
                                  type="button"
                                  className="button-secondary parent-jump-button"
                                  onClick={() => jumpToCandidate(selectedParentHeadingCandidate.id)}
                                >
                                  Jump to parent part
                                </button>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {selectedChildHeadingCandidates.length ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Child clauses</strong>
                              <span>
                                {selectedChildHeadingCandidates.length} clause
                                {selectedChildHeadingCandidates.length === 1 ? "" : "s"} linked to this part
                              </span>
                              <div className="candidate-context-cluster">
                                {selectedChildHeadingCandidates.map((candidate) => (
                                  <button
                                    key={candidate.id}
                                    type="button"
                                    className="button-secondary parent-jump-button"
                                    onClick={() => jumpToCandidate(candidate.id)}
                                  >
                                    {candidate.displayProjection?.clause_code ?? candidate.title}
                                  </button>
                                ))}
                              </div>
                            </div>
                          </div>
                        ) : null}
                        {projectionMarginaliaBlocks.length ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Annotations</strong>
                              <span>{projectionMarginaliaBlocks.map((block) => block.text).join(" | ")}</span>
                            </div>
                          </div>
                        ) : null}
                        {projectionPageContextRows.length ? (
                          <div className="comparison-field-list relation-field-list">
                            <div className="comparison-field-row">
                              <strong>Volume</strong>
                              <span>
                                {projectionPageContextRows.find((row) => row.label === "Volume")?.value ?? "n/a"}
                              </span>
                            </div>
                            <div className="comparison-field-row">
                              <strong>NCC page</strong>
                              <span>
                                {projectionPageContextRows.find((row) => row.label === "NCC page")?.value ?? "n/a"}
                              </span>
                            </div>
                          </div>
                        ) : null}
                        {projectionHeaderBlocks.length ? (
                          <div className="rendered-clause-block-list">
                            {projectionHeaderBlocks.map((block, index) => {
                              const pageChip = renderedClausePageChipLabel(
                                block,
                                index > 0 ? projectionHeaderBlocks[index - 1] : null
                              );
                              return (
                                <div
                                  key={`${block.block_id}-${block.render_role ?? "block"}`}
                                  className={`rendered-clause-block rendered-clause-block-${block.render_role ?? "continuation"} rendered-clause-depth-${block.relative_depth ?? 0}`}
                                >
                                  {pageChip ? <span className="rendered-clause-page-chip">{pageChip}</span> : null}
                                  {block.label ? <span className="rendered-clause-label">{block.label}</span> : null}
                                  <div className="rendered-clause-text">{renderStyledClauseText(block)}</div>
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                        <div className="rendered-clause-block-list">
                          {projectionBodyBlocks.length ? (
                            projectionBodyBlocks.map((block, index) => {
                              const pageChip = renderedClausePageChipLabel(
                                block,
                                index > 0 ? projectionBodyBlocks[index - 1] : null
                              );
                              return (
                                <div
                                  key={`${block.block_id}-${block.render_role ?? "block"}`}
                                  className={`rendered-clause-block rendered-clause-block-${block.render_role ?? "continuation"} rendered-clause-depth-${block.relative_depth ?? 0}`}
                                >
                                  {pageChip ? <span className="rendered-clause-page-chip">{pageChip}</span> : null}
                                  {block.label ? <span className="rendered-clause-label">{block.label}</span> : null}
                                  <div className="rendered-clause-text">{renderStyledClauseText(block)}</div>
                                </div>
                              );
                            })
                          ) : (selectedDisplayProjection?.rendered_blocks ?? []).length ? (
                            (selectedDisplayProjection?.rendered_blocks ?? []).map((block, index, blocks) => {
                              const pageChip = renderedClausePageChipLabel(block, index > 0 ? blocks[index - 1] : null);
                              return (
                                <div
                                  key={`${block.block_id}-${block.render_role ?? "block"}`}
                                  className={`rendered-clause-block rendered-clause-block-${block.render_role ?? "continuation"} rendered-clause-depth-${block.relative_depth ?? 0}`}
                                >
                                  {pageChip ? <span className="rendered-clause-page-chip">{pageChip}</span> : null}
                                  {block.label ? <span className="rendered-clause-label">{block.label}</span> : null}
                                  <div className="rendered-clause-text">{renderStyledClauseText(block)}</div>
                                </div>
                              );
                            })
                          ) : (
                            <div className="empty-state comparison-empty-state">
                              No clause projection is available yet for this candidate.
                            </div>
                          )}
                        </div>
                      </section>

                      <div className="comparison-grid candidate-rendered-metadata-grid">
                        <div className="evidence-panel">
                          <h4>Added Fields</h4>
                          {projectionAddedFieldRows.length ? (
                            renderComparisonRows(projectionAddedFieldRows)
                          ) : (
                            <p className="muted">No added fields were attached to this projection.</p>
                          )}
                        </div>
                        <div className="evidence-panel">
                          <h4>Review Signals</h4>
                          {projectionReviewSignalRows.length ? (
                            renderComparisonRows(projectionReviewSignalRows)
                          ) : (
                            <p className="muted">No review signals were attached to this projection.</p>
                          )}
                        </div>
                        <div className="evidence-panel">
                          <h4>Page Context</h4>
                          {projectionPageContextRows.length ? (
                            renderComparisonRows(projectionPageContextRows)
                          ) : (
                            <p className="muted">No page-frame context is attached to this projection.</p>
                          )}
                        </div>
                        <div className="evidence-panel">
                          <h4>Source Provenance</h4>
                          {projectionSourceRows.length ? (
                            renderComparisonRows(projectionSourceRows)
                          ) : (
                            <p className="muted">No source provenance is available for this projection.</p>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="section-header compact">
                    <div>
                      <h4>Candidate Comparison</h4>
                      <p className="muted">
                        {isPdfOnlyWorkspace
                          ? "PDF-native evidence remains primary below, with XML shown only when a reference file was supplied."
                          : "Structured XML, PDF, and snippet comparison remains available below."}
                      </p>
                    </div>
                  </div>
                  <div className="comparison-grid">
                    <div className="evidence-panel">
                      <h4>Candidate Object</h4>
                      {renderComparisonRows(candidateComparisonRows)}
                    </div>
                    <div className="evidence-panel">
                      <h4>{isPdfOnlyWorkspace ? "XML Reference" : "XML Evidence"}</h4>
                      {renderComparisonRows(xmlComparisonRows)}
                      <div className="evidence-text comparison-evidence-text">
                        {selectedCandidate.xmlText
                          ? renderHighlightedText(
                              selectedCandidate.xmlText,
                              selectedCandidate.xmlOnlyTerms,
                              "token-xml-only"
                            )
                          : isPdfOnlyWorkspace
                            ? "No XML reference was supplied for this run."
                            : "No XML node linked yet."}
                      </div>
                    </div>
                    <div className="evidence-panel">
                      <h4>PDF Evidence</h4>
                      {renderComparisonRows(pdfComparisonRows)}
                      <div className="evidence-text comparison-evidence-text">
                        {renderHighlightedText(
                          selectedCandidate.pdfText,
                          selectedCandidate.pdfOnlyTerms,
                          "token-pdf-only"
                        )}
                      </div>
                    </div>
                    <div className="evidence-panel">
                      <h4>Promoted Snippet</h4>
                      {selectedSnippet && !isPdfOnlyWorkspace ? (
                        <>
                          {renderComparisonRows(snippetComparisonRows)}
                          <div className="evidence-text comparison-evidence-text">
                            {cleanText(selectedSnippet.content) || "Snippet content is not available."}
                          </div>
                        </>
                      ) : (
                        <div className="empty-state comparison-empty-state">
                          {isPdfOnlyWorkspace
                            ? "Snippet promotion is disabled in PDF-only review mode."
                            : "No promoted snippet for this candidate yet."}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="grid two-column">
                    <div className="evidence-panel">
                      <h4>Mismatch / Comparison Summary</h4>
                      {renderComparisonRows(mismatchSummaryRows)}
                    </div>
                    <div className="evidence-panel">
                      <h4>Review Issues</h4>
                      {selectedCandidate.issues.length ? (
                        <ul className="issue-list">
                          {selectedCandidate.issues.map((issue, index) => (
                            <li key={`${selectedCandidate.id}-${index}`}>{issue}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">No review issues flagged for this candidate.</p>
                      )}
                    </div>
                  </div>
                  <details className="detail-disclosure">
                    <summary>Open promoted snippet JSON</summary>
                    <pre>{JSON.stringify(selectedSnippetJson ?? { state: "no_promoted_snippet" }, null, 2)}</pre>
                  </details>
                </section>
              </section>

              <section className="panel subsection">
                <div className="section-header compact">
                  <div>
                    <h3>Original PDF Preview</h3>
                    <p className="muted">
                      The review workspace restores automatically after refresh. The PDF preview is local to this
                      browser session, so use `Relink PDF` to reattach the original file when needed.
                    </p>
                  </div>
                  <button type="button" className="button-secondary" onClick={onRelinkPdf}>
                    Relink PDF
                  </button>
                </div>
                {pdfUrl ? (
                  <iframe
                    className="pdf-frame"
                    src={`${pdfUrl}#page=${selectedCandidate.page ?? 1}`}
                    title="Embedded PDF preview"
                  />
                ) : (
                  <p className="muted">
                    No PDF is currently linked in this browser session. Use `Relink PDF` to choose the original
                    file and restore the embedded preview for page-linked review.
                  </p>
                )}
              </section>
            </>
          ) : (
            <section className="panel subsection">
              <h3>No candidates available</h3>
              <p className="muted">Run validation first to populate the transitional candidate workspace.</p>
            </section>
          )}
        </div>
      </div>

      <section className="panel subsection">
        <h3>Approved Candidates</h3>
        {candidatesWithStatus.filter((candidate) => candidate.displayStatus === "approved").length ? (
          <div className="approved-grid">
            {candidatesWithStatus
              .filter((candidate) => candidate.displayStatus === "approved")
              .map((candidate) => (
                <div key={candidate.id} className="approved-card">
                  <strong>{candidate.title}</strong>
                  <span>{candidate.candidateType}</span>
                  <span>
                    Page {candidate.page ?? "n/a"} | Confidence {candidate.confidence.toFixed(3)}
                  </span>
                </div>
              ))}
          </div>
        ) : (
          <p className="muted">No approved candidates yet.</p>
        )}
      </section>
    </section>
  );
}
