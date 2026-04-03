"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { CandidateReviewWorkspace } from "../components/candidate-review-workspace";
import { ValidationViewer } from "../components/validation-viewer";

type IngestionResponse = {
  summary: {
    ingestion_run_id?: string | null;
    ingestion_run_status?: string | null;
    document_family_id?: string | null;
    pdf_source_document_id?: string | null;
    xml_source_document_id?: string | null;
    xml_status: string;
    pdf_status: string;
    can_progress: boolean;
    paired_document_id?: string | null;
  };
  results: {
    xml_validation: Record<string, any>;
    pdf_validation: Record<string, any>;
  };
  raw_metrics: Record<string, any>;
  lineage?: {
    xml_nodes?: {
      node_id: string;
      clause_id: string;
      text: string;
      path: string;
    }[];
    pdf_fragments?: {
      fragment_id: string;
      page: number;
      text: string;
      bbox: number[];
    }[];
    alignments?: {
      fragment_id: string;
      node_id?: string | null;
      confidence: number;
      matched: boolean;
      page?: number;
      bbox?: number[];
    }[];
    canonical_snippets?: {
      clause_id?: string;
      fragment_id?: string;
    }[];
  };
};

type RunRecord = {
  ingestion_run_id: string;
  document_family_id: string;
  status: string;
  can_progress: boolean;
  invalidated_reason?: string | null;
  created_at: string;
  invalidated_at?: string | null;
  purged_at?: string | null;
  pdf_source_document_id: string;
  xml_source_document_id: string;
  counts: Record<string, number>;
};

type PurgeSummary = {
  target_type: string;
  target_id: string;
  document_family_id?: string | null;
  run_ids: string[];
  counts: Record<string, number>;
  purge_order: string[];
  raw_inputs_retained: boolean;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [xmlFile, setXmlFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<IngestionResponse | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [runLoading, setRunLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [purgePreview, setPurgePreview] = useState<PurgeSummary | null>(null);
  const [validationStartedAt, setValidationStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const summaryText = useMemo(() => {
    if (loading) {
      return `Validating ${pdfFile?.name ?? "selected PDF"} against ${xmlFile?.name ?? "selected XML"}...`;
    }
    if (!response) {
      return "Upload a PDF and XML pair to validate the linked NCC representations.";
    }
    return `XML: ${response.summary.xml_status} | PDF: ${response.summary.pdf_status} | Can Progress: ${response.summary.can_progress}`;
  }, [loading, pdfFile, response, xmlFile]);

  useEffect(() => {
    void refreshRuns();
  }, []);

  useEffect(() => {
    if (!loading || validationStartedAt === null) {
      setElapsedSeconds(0);
      return;
    }
    const updateElapsed = () => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - validationStartedAt) / 1000)));
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [loading, validationStartedAt]);

  async function refreshRuns() {
    setRunLoading(true);
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/ingestions/runs`);
      if (!result.ok) {
        throw new Error("Failed to load ingestion runs.");
      }
      const payload = (await result.json()) as { runs: RunRecord[] };
      setRuns(payload.runs);
    } catch (runsError) {
      setActionError(runsError instanceof Error ? runsError.message : "Unknown error");
    } finally {
      setRunLoading(false);
    }
  }

  async function invalidateRun(runId: string) {
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/ingestions/runs/${runId}/invalidate`, {
        method: "POST",
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to invalidate run.");
      }
      await refreshRuns();
    } catch (invalidateError) {
      setActionError(invalidateError instanceof Error ? invalidateError.message : "Unknown error");
    }
  }

  async function previewRunPurge(runId: string) {
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/runs/${runId}/dry-run`);
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to preview purge.");
      }
      setPurgePreview((await result.json()) as PurgeSummary);
    } catch (previewError) {
      setActionError(previewError instanceof Error ? previewError.message : "Unknown error");
    }
  }

  async function purgeRun(runId: string) {
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/runs/${runId}`, {
        method: "POST",
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to purge run.");
      }
      setPurgePreview((await result.json()) as PurgeSummary);
      await refreshRuns();
    } catch (purgeError) {
      setActionError(purgeError instanceof Error ? purgeError.message : "Unknown error");
    }
  }

  async function previewFamilyPurge(sourceDocumentId: string) {
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/source-documents/${sourceDocumentId}/dry-run`);
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to preview family purge.");
      }
      setPurgePreview((await result.json()) as PurgeSummary);
    } catch (previewError) {
      setActionError(previewError instanceof Error ? previewError.message : "Unknown error");
    }
  }

  async function purgeFamily(sourceDocumentId: string) {
    setActionError(null);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/source-documents/${sourceDocumentId}`, {
        method: "POST",
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to purge source document family.");
      }
      setPurgePreview((await result.json()) as PurgeSummary);
      await refreshRuns();
    } catch (purgeError) {
      setActionError(purgeError instanceof Error ? purgeError.message : "Unknown error");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pdfFile || !xmlFile) {
      setError("Choose both a PDF and an XML file.");
      return;
    }

    setLoading(true);
    setError(null);
    setResponse(null);
    setValidationStartedAt(Date.now());
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const formData = new FormData();
    formData.append("pdf", pdfFile);
    formData.append("xml", xmlFile);

    try {
      const result = await fetch(`${API_BASE_URL}/api/ingestions/validate`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Validation request failed.");
      }

      const payload = (await result.json()) as IngestionResponse;
      setResponse(payload);
      await refreshRuns();
    } catch (submissionError) {
      if (submissionError instanceof Error && submissionError.name === "AbortError") {
        setError("Validation cancelled.");
      } else {
        setError(submissionError instanceof Error ? submissionError.message : "Unknown error");
      }
    } finally {
      setLoading(false);
      setValidationStartedAt(null);
      abortControllerRef.current = null;
    }
  }

  function cancelValidation() {
    abortControllerRef.current?.abort();
  }

  return (
    <main>
      <section className="panel">
        <h1>NCC Ingestion Console</h1>
        <p>
            Run the hardened XML and PDF contracts together, inspect review candidates, and check whether
            the paired document can progress toward candidate-backed semantic processing.
        </p>
        <p>{summaryText}</p>
      </section>

      <section className="panel">
        <form className="grid" onSubmit={onSubmit} aria-busy={loading}>
          <div>
            <label htmlFor="pdf">PDF document</label>
            <input
              id="pdf"
              type="file"
              accept=".pdf"
              disabled={loading}
              onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <div>
            <label htmlFor="xml">XML source</label>
            <input
              id="xml"
              type="file"
              accept=".xml"
              disabled={loading}
              onChange={(event) => setXmlFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <button type="submit" disabled={loading}>
            {loading ? "Validating..." : "Validate ingestion"}
          </button>
          {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
        </form>
        {loading ? (
          <div className="validation-progress" aria-live="polite">
            <div className="validation-progress-header">
              <div>
                <h2>Validation in progress</h2>
                <p>
                  Running XML validation, PDF extraction, alignment, and transitional review payload assembly.
                  Exact stage progress is not yet available.
                </p>
              </div>
              <span className="status warn">Working</span>
            </div>
            <div className="progress-indicator" />
            <div className="grid two-column">
              <div className="metric-list">
                <div>
                  <strong>PDF</strong>: {pdfFile?.name ?? "n/a"}
                </div>
                <div>
                  <strong>XML</strong>: {xmlFile?.name ?? "n/a"}
                </div>
                <div>
                  <strong>Elapsed</strong>: {elapsedSeconds}s
                </div>
              </div>
              <div className="metric-list">
                <div>
                  <strong>Status</strong>: Waiting for the validation response from the backend.
                </div>
                <div>
                  <strong>Previous results</strong>: Hidden until the new request completes.
                </div>
              </div>
            </div>
            <div className="action-row" style={{ marginBottom: 0 }}>
              <button type="button" onClick={cancelValidation}>
                Cancel validation
              </button>
            </div>
          </div>
        ) : null}
      </section>

      {response ? (
        <>
          <CandidateReviewWorkspace response={response} pdfFile={pdfFile} />
          <div className="grid">
            <ValidationViewer title="XML Validation" result={response.results.xml_validation} />
            <ValidationViewer title="PDF Validation" result={response.results.pdf_validation} />
            <section className="panel">
              <h2>Raw Metrics</h2>
              <pre>{JSON.stringify(response.raw_metrics, null, 2)}</pre>
            </section>
          </div>
        </>
      ) : null}

      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <div>
            <h2>Retention Controls</h2>
            <p>Invalidate a bad run first, then preview or execute a lineage-based purge.</p>
          </div>
          <button type="button" onClick={() => void refreshRuns()} disabled={runLoading}>
            {runLoading ? "Refreshing..." : "Refresh runs"}
          </button>
        </div>
        {actionError ? <p style={{ color: "#fca5a5" }}>{actionError}</p> : null}
        <div className="grid">
          {runs.map((run) => (
            <div key={run.ingestion_run_id} className="panel" style={{ marginBottom: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div>
                  <h3>{run.document_family_id}</h3>
                  <p>{run.ingestion_run_id}</p>
                </div>
                <span className={`status ${run.status === "active" ? "pass" : run.status === "invalidated" ? "warn" : "fail"}`}>
                  {run.status}
                </span>
              </div>
              <div className="detail-list">
                <div>
                  <strong>Can Progress</strong>: {String(run.can_progress)}
                </div>
                <div>
                  <strong>Fragments</strong>: {run.counts.ingestion_fragments ?? 0}
                </div>
                <div>
                  <strong>Canonical Snippets</strong>: {run.counts.canonical_snippets ?? 0}
                </div>
                {run.invalidated_reason ? (
                  <div>
                    <strong>Reason</strong>: {run.invalidated_reason}
                  </div>
                ) : null}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                <button type="button" onClick={() => void invalidateRun(run.ingestion_run_id)} disabled={run.status !== "active"}>
                  Invalidate
                </button>
                <button type="button" onClick={() => void previewRunPurge(run.ingestion_run_id)}>
                  Dry-run purge
                </button>
                <button type="button" onClick={() => void purgeRun(run.ingestion_run_id)}>
                  Purge run
                </button>
                <button type="button" onClick={() => void previewFamilyPurge(run.pdf_source_document_id)}>
                  Dry-run family purge
                </button>
                <button type="button" onClick={() => void purgeFamily(run.pdf_source_document_id)}>
                  Purge family
                </button>
              </div>
            </div>
          ))}
        </div>
        {purgePreview ? (
          <>
            <h3>Purge Preview</h3>
            <pre>{JSON.stringify(purgePreview, null, 2)}</pre>
          </>
        ) : null}
      </section>
    </main>
  );
}
