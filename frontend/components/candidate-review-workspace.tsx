"use client";

import { useEffect, useMemo, useState } from "react";

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
  xml_text: string;
  pdf_text: string;
  bbox: number[];
  issues: string[];
  xml_only_terms: string[];
  pdf_only_terms: string[];
  raw_xml_only_terms?: string[];
  raw_pdf_only_terms?: string[];
  ignored_structural_terms?: string[];
};

type ReviewDecision = {
  candidate_id: string;
  decision_status: ReviewStatus;
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
  xmlText: string;
  pdfText: string;
  bbox: number[];
  issues: string[];
  xmlOnlyTerms: string[];
  pdfOnlyTerms: string[];
  rawXmlOnlyTerms: string[];
  rawPdfOnlyTerms: string[];
  ignoredStructuralTerms: string[];
};

type CandidateWithDisplayStatus = CandidateRecord & {
  displayStatus: ReviewStatus;
};

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
    pdf_fragments?: PdfFragment[];
    alignments?: AlignmentRecord[];
    canonical_snippets?: CanonicalSnippet[];
  };
  review_workspace?: {
    mode?: string;
    reason?: string;
    xml_nodes?: XmlNode[];
    pdf_fragments?: PdfFragment[];
    alignments?: AlignmentRecord[];
    canonical_snippets?: CanonicalSnippet[];
    review_units?: ReviewUnit[];
    alignment_total?: number;
    alignment_displayed?: number;
    candidate_total?: number;
    candidate_surfaced?: number;
    candidate_needs_review?: number;
  };
};

type CandidateReviewWorkspaceProps = {
  response: IngestionResponseLike;
  pdfFile: File | null;
  apiBaseUrl: string;
  onRelinkPdf: () => void;
};

type FilterKey = "review" | "all" | "approved" | "rejected";
type SortKey = "priority" | "confidence_desc" | "confidence_asc" | "issue_class" | "source_emphasis";

const FILTER_LABELS: Record<FilterKey, string> = {
  review: "Review Queue",
  all: "All Candidates",
  approved: "Approved",
  rejected: "Rejected",
};

const SORT_LABELS: Record<SortKey, string> = {
  priority: "Priority",
  confidence_desc: "Confidence (high to low)",
  confidence_asc: "Confidence (low to high)",
  issue_class: "Mismatch / Error Type",
  source_emphasis: "PDF / XML Source",
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

function issueClassPriority(value: string): number {
  switch (value) {
    case "unmatched":
      return 0;
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

function sortCandidates(candidates: CandidateWithDisplayStatus[], sortKey: SortKey): CandidateWithDisplayStatus[] {
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
    return (
      statusPriority(left.displayStatus) - statusPriority(right.displayStatus) ||
      issueClassPriority(left.reviewIssueClass) - issueClassPriority(right.reviewIssueClass) ||
      left.confidence - right.confidence ||
      left.title.localeCompare(right.title)
    );
  });
  return sorted;
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

function formatWorkspaceLabel(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  return value.replace(/_/g, " ");
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
    xmlOnlyTerms: candidate.xmlOnlyTerms,
    pdfOnlyTerms: candidate.pdfOnlyTerms,
    rawXmlOnlyTerms: candidate.rawXmlOnlyTerms,
    rawPdfOnlyTerms: candidate.rawPdfOnlyTerms,
    ignoredStructuralTerms: candidate.ignoredStructuralTerms,
    issues: candidate.issues,
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

function mapReviewUnitToCandidate(unit: ReviewUnit): CandidateRecord {
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
    xmlText: unit.xml_text,
    pdfText: unit.pdf_text,
    bbox: unit.bbox ?? [],
    issues: unit.issues ?? [],
    xmlOnlyTerms: unit.xml_only_terms ?? [],
    pdfOnlyTerms: unit.pdf_only_terms ?? [],
    rawXmlOnlyTerms: unit.raw_xml_only_terms ?? unit.xml_only_terms ?? [],
    rawPdfOnlyTerms: unit.raw_pdf_only_terms ?? unit.pdf_only_terms ?? [],
    ignoredStructuralTerms: unit.ignored_structural_terms ?? [],
  };
}

function normalizeReviewStatus(value: ReviewStatus | string): ReviewStatus {
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
      xmlText,
      pdfText,
      bbox: alignment.bbox ?? fragment.bbox ?? [],
      issues,
      xmlOnlyTerms,
      pdfOnlyTerms,
      rawXmlOnlyTerms: xmlOnlyTerms,
      rawPdfOnlyTerms: pdfOnlyTerms,
      ignoredStructuralTerms: [],
    });

    return candidates;
  }, []);
}

function buildCandidates(response: IngestionResponseLike): CandidateRecord[] {
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
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [currentPage, setCurrentPage] = useState(1);
  const [statusOverrides, setStatusOverrides] = useState<Record<string, ReviewStatus>>({});
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [savingCandidateId, setSavingCandidateId] = useState<string | null>(null);

  const runId = response.summary?.ingestion_run_id ?? null;
  const decisionsPersisted = Boolean(runId);
  const workspaceMode = response.review_workspace?.mode ?? null;
  const workspaceReason = response.review_workspace?.reason ?? null;
  const alignmentDisplayed = response.review_workspace?.alignment_displayed ?? 0;
  const alignmentTotal = response.review_workspace?.alignment_total ?? 0;
  const candidateCreated = response.review_workspace?.candidate_total ?? alignmentTotal;
  const candidateSurfaced = response.review_workspace?.candidate_surfaced ?? alignmentDisplayed;
  const candidateNeedsReview = response.review_workspace?.candidate_needs_review ?? 0;

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

  const filteredCandidates = useMemo(() => {
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

  const sortedCandidates = useMemo(() => sortCandidates(filteredCandidates, sortKey), [filteredCandidates, sortKey]);
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
  }, [filter, sortKey]);

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

  const selectedSnippetJson = useMemo(() => buildSnippetJson(selectedSnippet), [selectedSnippet]);

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
      { label: "Link status", value: selectedCandidate.nodeId ? "Linked to XML node" : "No XML node linked" },
      {
        label: "Approval state",
        value: selectedSnippet ? "Promoted snippet exists" : "No promoted snippet yet",
      },
      { label: "Display status", value: selectedCandidate.displayStatus },
      { label: "Base status", value: selectedCandidate.baseStatus },
      { label: "Matched", value: String(selectedCandidate.matched) },
      { label: "Confidence", value: selectedCandidate.confidence.toFixed(3) },
      { label: "Candidate page", value: selectedCandidate.page ? String(selectedCandidate.page) : "n/a" },
      { label: "BBox", value: formatBbox(selectedCandidate.bbox) },
    ];
  }, [selectedCandidate, selectedSnippet]);

  const xmlComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    return [
      { label: "XML path", value: selectedCandidate.xmlPath },
      { label: "Missing in PDF", value: formatList(selectedCandidate.xmlOnlyTerms) },
      { label: "Raw XML-only terms", value: formatList(selectedCandidate.rawXmlOnlyTerms) },
      { label: "XML text length", value: String(cleanText(selectedCandidate.xmlText).length) },
    ];
  }, [selectedCandidate]);

  const pdfComparisonRows = useMemo<ComparisonRow[]>(() => {
    if (!selectedCandidate) {
      return [];
    }
    return [
      { label: "Fragment id", value: selectedCandidate.fragmentId },
      { label: "Page", value: selectedCandidate.page ? String(selectedCandidate.page) : "n/a" },
      { label: "Missing in XML", value: formatList(selectedCandidate.pdfOnlyTerms) },
      { label: "Raw PDF-only terms", value: formatList(selectedCandidate.rawPdfOnlyTerms) },
      { label: "PDF text length", value: String(cleanText(selectedCandidate.pdfText).length) },
    ];
  }, [selectedCandidate]);

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
      { label: "Missing in XML", value: formatList(selectedCandidate.pdfOnlyTerms) },
      { label: "Missing in PDF", value: formatList(selectedCandidate.xmlOnlyTerms) },
      { label: "Ignored structural terms", value: formatList(selectedCandidate.ignoredStructuralTerms) },
      { label: "Issue summary", value: selectedCandidate.issues[0] ?? "No review issues flagged" },
    ];
  }, [selectedCandidate]);

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
      </div>

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
              </button>
            ))
          ) : (
            <div className="empty-state">No candidates in this view yet.</div>
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

                <section className="comparison-section">
                  <div className="section-header compact">
                    <div>
                      <h4>Candidate Comparison</h4>
                      <p className="muted">
                        Structured comparison first, with raw JSON available below for inspection.
                      </p>
                    </div>
                  </div>
                  <div className="comparison-grid">
                    <div className="evidence-panel">
                      <h4>Candidate Object</h4>
                      {renderComparisonRows(candidateComparisonRows)}
                    </div>
                    <div className="evidence-panel">
                      <h4>XML Evidence</h4>
                      {renderComparisonRows(xmlComparisonRows)}
                      <div className="evidence-text comparison-evidence-text">
                        {selectedCandidate.xmlText
                          ? renderHighlightedText(
                              selectedCandidate.xmlText,
                              selectedCandidate.xmlOnlyTerms,
                              "token-xml-only"
                            )
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
                      {selectedSnippet ? (
                        <>
                          {renderComparisonRows(snippetComparisonRows)}
                          <div className="evidence-text comparison-evidence-text">
                            {cleanText(selectedSnippet.content) || "Snippet content is not available."}
                          </div>
                        </>
                      ) : (
                        <div className="empty-state comparison-empty-state">
                          No promoted snippet for this candidate yet.
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
                    <summary>Open candidate JSON</summary>
                    <pre>{JSON.stringify(selectedCandidateJson, null, 2)}</pre>
                  </details>
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
