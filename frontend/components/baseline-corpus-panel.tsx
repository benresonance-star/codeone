"use client";

type BaselineCorpusArrayEvidence = {
  fragment_id?: string;
  page?: number | null;
  text?: string;
  bbox?: number[];
};

type BaselineCorpusObjectEvidence = {
  primary_fragment_id?: string;
  primary_page?: number | null;
  has_pdf_evidence?: boolean;
  evidence_packet_count?: number;
};

type BaselineCorpusItem = {
  candidate_id?: string;
  semantic_unit_id?: string;
  title?: string;
  candidate_type?: string;
  candidate_semantic_class?: string;
  xml_structural_class?: string;
  semantic_class?: string;
  baseline_category?: string;
  base_status?: string;
  status?: string;
  validation_state?: string;
  matched?: boolean;
  page?: number | null;
  fragment_id?: string;
  node_id?: string | null;
  text_preview?: string;
  xml_text?: string;
  pdf_text?: string;
  evidence?: BaselineCorpusObjectEvidence | BaselineCorpusArrayEvidence[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeBaselinePayload(payload: unknown): { summary: Record<string, unknown>; items: BaselineCorpusItem[] } {
  if (payload === undefined || payload === null) {
    return { summary: {}, items: [] };
  }
  if (Array.isArray(payload)) {
    return { summary: {}, items: payload as BaselineCorpusItem[] };
  }
  if (!isRecord(payload)) {
    return { summary: {}, items: [] };
  }
  const rawItems = payload.items ?? payload.baseline_items;
  const items = Array.isArray(rawItems) ? (rawItems as BaselineCorpusItem[]) : [];
  const summary =
    (isRecord(payload.summary) ? payload.summary : null) ??
    (isRecord(payload.counts) ? payload.counts : null) ??
    {};
  return { summary, items };
}

export function extractBaselineCorpus(payload: {
  review_workspace?: Record<string, unknown> | null;
  lineage?: Record<string, unknown> | null;
  raw_metrics?: Record<string, unknown> | null;
}): { summary: Record<string, unknown>; items: BaselineCorpusItem[] } {
  const rw = payload.review_workspace;
  const lin = payload.lineage;
  const raw = payload.raw_metrics;

  const fromRw =
    rw && (rw.foundational_baseline_corpus ?? rw.baseline_corpus ?? rw.baselineCorpus);
  const fromLin =
    lin && (lin.foundational_baseline_corpus ?? lin.baseline_corpus ?? lin.baselineCorpus);
  const fromRaw =
    raw && (raw.foundational_baseline_corpus ?? raw.baseline_corpus ?? raw.baselineCorpus);

  const primary = fromRw ?? fromLin ?? fromRaw;
  if (primary !== undefined && primary !== null) {
    return normalizeBaselinePayload(primary);
  }

  const flat =
    (rw && (rw.baseline_items ?? rw.baselineItems)) ??
    (lin && (lin.baseline_items ?? lin.baselineItems)) ??
    (raw && (raw.baseline_items ?? raw.baselineItems));
  if (Array.isArray(flat)) {
    return { summary: {}, items: flat as BaselineCorpusItem[] };
  }

  return { summary: {}, items: [] };
}

function numSummary(summary: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = summary[key];
    if (typeof value === "number" && !Number.isNaN(value)) {
      return value;
    }
  }
  return null;
}

function strSummary(summary: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = summary[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
}

function clip(text: string, max: number): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= max) {
    return normalized;
  }
  return `${normalized.slice(0, max)}...`;
}

function itemTitle(row: BaselineCorpusItem, index: number): string {
  return clip(row.title ?? row.node_id ?? row.candidate_id ?? `Baseline item ${index + 1}`, 120);
}

function itemClass(row: BaselineCorpusItem): string {
  return row.semantic_class ?? row.candidate_semantic_class ?? row.xml_structural_class ?? row.candidate_type ?? "—";
}

function itemStatus(row: BaselineCorpusItem): string {
  return row.validation_state ?? row.base_status ?? row.status ?? "—";
}

function primaryEvidence(row: BaselineCorpusItem): {
  fragment_id?: string;
  page?: number | null;
  text?: string;
  has_pdf_evidence?: boolean;
  evidence_packet_count?: number;
} | null {
  if (Array.isArray(row.evidence)) {
    const evidence = row.evidence[0];
    if (!evidence) {
      return null;
    }
    return {
      fragment_id: evidence.fragment_id,
      page: evidence.page,
      text: evidence.text,
      has_pdf_evidence: Boolean(evidence.fragment_id),
    };
  }
  if (isRecord(row.evidence)) {
    return {
      fragment_id: typeof row.evidence.primary_fragment_id === "string" ? row.evidence.primary_fragment_id : undefined,
      page: typeof row.evidence.primary_page === "number" ? row.evidence.primary_page : null,
      has_pdf_evidence: Boolean(row.evidence.has_pdf_evidence),
      evidence_packet_count:
        typeof row.evidence.evidence_packet_count === "number" ? row.evidence.evidence_packet_count : undefined,
    };
  }
  return null;
}

function itemMatched(row: BaselineCorpusItem): boolean | null {
  if (typeof row.matched === "boolean") {
    return row.matched;
  }
  const evidence = primaryEvidence(row);
  if (typeof evidence?.has_pdf_evidence === "boolean") {
    return evidence.has_pdf_evidence;
  }
  return null;
}

function evidenceLabel(row: BaselineCorpusItem): string {
  const evidence = primaryEvidence(row);
  const parts = [
    evidence?.fragment_id ? `fragment ${evidence.fragment_id}` : null,
    typeof evidence?.page === "number" ? `p.${evidence.page}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : row.fragment_id ? `fragment ${row.fragment_id}` : "—";
}

export function BaselineCorpusPanel(payload: {
  review_workspace?: Record<string, unknown> | null;
  lineage?: Record<string, unknown> | null;
  raw_metrics?: Record<string, unknown> | null;
}) {
  const { summary, items } = extractBaselineCorpus(payload);

  const matchedFromItems = items.filter((item) => itemMatched(item) === true).length;
  const unmatchedFromItems = items.filter((item) => itemMatched(item) === false).length;
  const totalDeclared = numSummary(summary, "included_item_count", "total_items", "total", "count", "n_items");
  const matchedDeclared = numSummary(summary, "matched_count", "matched", "aligned");
  const unmatchedDeclared = numSummary(summary, "unmatched_count", "unmatched", "gaps");
  const eligible = numSummary(summary, "eligible_semantic_unit_count", "eligible_count");
  const coverage = numSummary(summary, "coverage_ratio");
  const notes = strSummary(summary, "notes", "description", "label");

  const total = totalDeclared ?? items.length;
  const matched = matchedDeclared ?? (items.length ? matchedFromItems : null);
  const unmatched = unmatchedDeclared ?? (items.length ? unmatchedFromItems : null);
  const payloadSource =
    payload.review_workspace &&
    (payload.review_workspace.foundational_baseline_corpus ??
      payload.review_workspace.baseline_corpus ??
      payload.review_workspace.baseline_items)
      ? "review_workspace"
      : payload.lineage &&
          (payload.lineage.foundational_baseline_corpus ??
            payload.lineage.baseline_corpus ??
            payload.lineage.baseline_items)
        ? "lineage"
        : payload.raw_metrics &&
            (payload.raw_metrics.foundational_baseline_corpus ??
              payload.raw_metrics.baseline_corpus ??
              payload.raw_metrics.baseline_items)
          ? "raw_metrics"
          : items.length
            ? "derived"
            : "none";

  return (
    <section className="panel baseline-corpus-panel">
      <div className="workspace-header">
        <div>
          <h2>Baseline corpus</h2>
          <p className="muted">
            Foundational baseline items used for robustness validation. Populated from
            `foundational_baseline_corpus` when the backend emits the additive baseline slice.
          </p>
          {notes ? <p className="muted">{notes}</p> : null}
        </div>
      </div>

      <div className="workspace-summary baseline-summary">
        <div className="summary-card">
          <strong>Total items</strong>
          <span>{total}</span>
        </div>
        <div className="summary-card">
          <strong>Matched</strong>
          <span>{matched ?? "—"}</span>
        </div>
        <div className="summary-card">
          <strong>Unmatched</strong>
          <span>{unmatched ?? "—"}</span>
        </div>
        <div className="summary-card">
          <strong>Eligible units</strong>
          <span>{eligible ?? "—"}</span>
          <span className="summary-subtext">{coverage != null ? `Coverage ${coverage}` : "Coverage n/a"}</span>
        </div>
        <div className="summary-card">
          <strong>Payload source</strong>
          <span>{payloadSource}</span>
          <span className="summary-subtext">
            {summary.truncated === true ? "Slice truncated for display" : "Deterministic baseline slice"}
          </span>
        </div>
      </div>

      {!items.length ? (
        <div className="empty-state">
          No baseline corpus items are present in this response yet.
        </div>
      ) : (
        <div className="baseline-table-wrap">
          <table className="baseline-table">
            <thead>
              <tr>
                <th scope="col">Title / id</th>
                <th scope="col">Category</th>
                <th scope="col">Class</th>
                <th scope="col">Status</th>
                <th scope="col">Matched</th>
                <th scope="col">Evidence / page</th>
                <th scope="col">XML text</th>
                <th scope="col">PDF text</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row, index) => {
                const matchedValue = itemMatched(row);
                const evidence = primaryEvidence(row);
                return (
                  <tr key={row.candidate_id ?? row.semantic_unit_id ?? row.node_id ?? `baseline-${index}`}>
                    <td>
                      <div className="baseline-cell-title">{itemTitle(row, index)}</div>
                      {row.candidate_id ? <div className="muted baseline-cell-id">{row.candidate_id}</div> : null}
                    </td>
                    <td>{row.baseline_category ?? "—"}</td>
                    <td>{itemClass(row)}</td>
                    <td>{itemStatus(row)}</td>
                    <td>
                      {matchedValue === null ? (
                        "—"
                      ) : (
                        <span className={`status ${matchedValue ? "pass" : "warn"}`}>{matchedValue ? "yes" : "no"}</span>
                      )}
                    </td>
                    <td>
                      <div>{evidenceLabel(row)}</div>
                      <div className="muted">
                        {typeof evidence?.page === "number" ? `Page ${evidence.page}` : "—"}
                        {typeof evidence?.evidence_packet_count === "number"
                          ? ` · ${evidence.evidence_packet_count} packet(s)`
                          : ""}
                      </div>
                    </td>
                    <td>
                      <div className="baseline-snippet">{clip(row.xml_text ?? row.text_preview ?? "", 220) || "—"}</div>
                    </td>
                    <td>
                      <div className="baseline-snippet">{clip(row.pdf_text ?? evidence?.text ?? "", 220) || "—"}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
