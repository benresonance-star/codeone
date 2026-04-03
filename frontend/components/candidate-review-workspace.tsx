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
};

type ReviewStatus =
  | "match"
  | "mismatch"
  | "review required"
  | "approved"
  | "rejected"
  | "paused"
  | "ambiguous";

type CandidateRecord = {
  id: string;
  title: string;
  candidateType: string;
  confidence: number;
  baseStatus: ReviewStatus;
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
};

type IngestionResponseLike = {
  summary?: {
    document_family_id?: string | null;
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
};

type CandidateReviewWorkspaceProps = {
  response: IngestionResponseLike;
  pdfFile: File | null;
};

type FilterKey = "review" | "all" | "approved" | "rejected";

const FILTER_LABELS: Record<FilterKey, string> = {
  review: "Review Queue",
  all: "All Candidates",
  approved: "Approved",
  rejected: "Rejected",
};

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

  if (normalizedPath.includes("xref") || normalizedPath.includes("reference")) {
    return "reference";
  }
  if (normalizedPath.includes("definition") || normalizedText.includes(" means ")) {
    return "definition";
  }
  if (normalizedPath.includes("table")) {
    return "table";
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

function buildCandidates(response: IngestionResponseLike): CandidateRecord[] {
  const xmlNodes = response.lineage?.xml_nodes ?? [];
  const pdfFragments = response.lineage?.pdf_fragments ?? [];
  const alignments = response.lineage?.alignments ?? [];
  const canonicalSnippets = response.lineage?.canonical_snippets ?? [];

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

      candidates.push({
        id: `candidate:${fragment.fragment_id}`,
        title: formatTitle(xmlText, pdfText, fragment.fragment_id),
        candidateType: detectCandidateType(node?.path ?? "", xmlText),
        confidence: alignment.confidence,
        baseStatus,
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
      } satisfies CandidateRecord);

      return candidates;
    }, []);
}

export function CandidateReviewWorkspace({ response, pdfFile }: CandidateReviewWorkspaceProps) {
  const [filter, setFilter] = useState<FilterKey>("review");
  const [statusOverrides, setStatusOverrides] = useState<Record<string, ReviewStatus>>({});
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!pdfFile) {
      setPdfUrl(null);
      return undefined;
    }
    const nextUrl = URL.createObjectURL(pdfFile);
    setPdfUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [pdfFile]);

  const candidates = useMemo(() => buildCandidates(response), [response]);
  const candidatesWithStatus = useMemo(
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

  useEffect(() => {
    if (!filteredCandidates.length) {
      setSelectedCandidateId(null);
      return;
    }
    if (!selectedCandidateId || !filteredCandidates.some((candidate) => candidate.id === selectedCandidateId)) {
      setSelectedCandidateId(filteredCandidates[0].id);
    }
  }, [filteredCandidates, selectedCandidateId]);

  const selectedCandidate =
    filteredCandidates.find((candidate) => candidate.id === selectedCandidateId) ?? filteredCandidates[0] ?? null;

  const counts = useMemo(
    () => ({
      review: candidatesWithStatus.filter((candidate) =>
        ["review required", "mismatch", "paused", "ambiguous"].includes(candidate.displayStatus)
      ).length,
      approved: candidatesWithStatus.filter((candidate) => candidate.displayStatus === "approved").length,
      rejected: candidatesWithStatus.filter((candidate) => candidate.displayStatus === "rejected").length,
      all: candidatesWithStatus.length,
    }),
    [candidatesWithStatus]
  );

  function updateStatus(nextStatus: ReviewStatus) {
    if (!selectedCandidate) {
      return;
    }
    setStatusOverrides((current) => ({
      ...current,
      [selectedCandidate.id]: nextStatus,
    }));
  }

  return (
    <section className="panel">
      <div className="workspace-header">
        <div>
          <h2>Candidate Review Workspace</h2>
          <p>
            Transitional review workspace derived from current alignment output. This supports early
            human-in-the-loop testing before the full backend candidate runtime exists.
          </p>
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
          <strong>Review Queue</strong>
          <span>{counts.review}</span>
        </div>
        <div className="summary-card">
          <strong>Approved</strong>
          <span>{counts.approved}</span>
        </div>
        <div className="summary-card">
          <strong>Rejected</strong>
          <span>{counts.rejected}</span>
        </div>
      </div>

      <div className="filter-row">
        {(Object.keys(FILTER_LABELS) as FilterKey[]).map((key) => (
          <button
            key={key}
            type="button"
            className={`filter-chip ${filter === key ? "active" : ""}`}
            onClick={() => setFilter(key)}
          >
            {FILTER_LABELS[key]}
          </button>
        ))}
      </div>

      <div className="workspace-layout">
        <aside className="candidate-sidebar">
          {filteredCandidates.length ? (
            filteredCandidates.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                className={`candidate-list-item ${selectedCandidate?.id === candidate.id ? "selected" : ""}`}
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
                </div>
              </button>
            ))
          ) : (
            <div className="empty-state">No candidates in this view yet.</div>
          )}
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
                  </div>
                  <span className={statusClass(selectedCandidate.displayStatus)}>
                    {selectedCandidate.displayStatus}
                  </span>
                </div>

                <div className="action-row">
                  <button type="button" onClick={() => updateStatus("approved")}>
                    Approve
                  </button>
                  <button type="button" onClick={() => updateStatus("rejected")}>
                    Reject
                  </button>
                  <button type="button" onClick={() => updateStatus("paused")}>
                    Pause
                  </button>
                  <button type="button" onClick={() => updateStatus("ambiguous")}>
                    Mark Ambiguous
                  </button>
                  <button type="button" onClick={() => updateStatus(selectedCandidate.baseStatus)}>
                    Reset
                  </button>
                </div>

                <div className="grid two-column">
                  <div className="evidence-panel">
                    <h4>XML Evidence</h4>
                    <p className="muted">{selectedCandidate.xmlPath}</p>
                    <div className="evidence-text">
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
                    <p className="muted">
                      Page {selectedCandidate.page ?? "n/a"} | BBox{" "}
                      {selectedCandidate.bbox.length ? selectedCandidate.bbox.join(", ") : "n/a"}
                    </p>
                    <div className="evidence-text">
                      {renderHighlightedText(
                        selectedCandidate.pdfText,
                        selectedCandidate.pdfOnlyTerms,
                        "token-pdf-only"
                      )}
                    </div>
                  </div>
                </div>

                <div className="grid two-column">
                  <div className="evidence-panel">
                    <h4>Match / Mismatch Summary</h4>
                    <div className="detail-list">
                      <div>
                        <strong>Matched</strong>: {String(selectedCandidate.matched)}
                      </div>
                      <div>
                        <strong>Confidence</strong>: {selectedCandidate.confidence}
                      </div>
                      <div>
                        <strong>XML-only terms</strong>:{" "}
                        {selectedCandidate.xmlOnlyTerms.length
                          ? selectedCandidate.xmlOnlyTerms.join(", ")
                          : "none"}
                      </div>
                      <div>
                        <strong>PDF-only terms</strong>:{" "}
                        {selectedCandidate.pdfOnlyTerms.length
                          ? selectedCandidate.pdfOnlyTerms.join(", ")
                          : "none"}
                      </div>
                    </div>
                  </div>

                  <div className="evidence-panel">
                    <h4>Review Issues</h4>
                    {selectedCandidate.issues.length ? (
                      <ul className="issue-list">
                        {selectedCandidate.issues.map((issue) => (
                          <li key={issue}>{issue}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">No review issues flagged for this candidate.</p>
                    )}
                  </div>
                </div>
              </section>

              <section className="panel subsection">
                <h3>Original PDF Preview</h3>
                <p className="muted">
                  The original uploaded PDF is shown here for early review testing. Precise page jumping and
                  bbox highlighting are follow-on work.
                </p>
                {pdfUrl ? (
                  <iframe
                    className="pdf-frame"
                    src={`${pdfUrl}#page=${selectedCandidate.page ?? 1}`}
                    title="Uploaded PDF preview"
                  />
                ) : (
                  <p className="muted">Upload a PDF to enable the embedded preview.</p>
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
