"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { BaselineCorpusPanel } from "../components/baseline-corpus-panel";
import { CandidateReviewWorkspace } from "../components/candidate-review-workspace";
import { ConsoleNavigation } from "../components/console-navigation";
import { PdfUploadViewer } from "../components/pdf-upload-viewer";
import { ReviewMetricsStrip } from "../components/review-metrics-strip";
import { ValidationViewer } from "../components/validation-viewer";
import { XmlUploadViewer } from "../components/xml-upload-viewer";

type IngestionResponse = {
  summary: {
    ingestion_run_id?: string | null;
    ingestion_run_status?: string | null;
    document_family_id?: string | null;
    created_at?: string | null;
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
    /** Additive: foundational baseline corpus for robustness validation (optional). */
    baseline_corpus?: unknown;
    baseline_items?: unknown[];
    foundational_baseline_corpus?: unknown;
    candidate_quality?: Record<string, unknown>;
    graph_readiness?: Record<string, unknown>;
  };
  review_workspace?: {
    mode?: string;
    reason?: string;
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
    review_units?: {
      candidate_id: string;
      title: string;
      candidate_type: string;
      confidence: number;
      base_status: string;
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
    }[];
    alignment_total?: number;
    alignment_displayed?: number;
    /** Additive: baseline corpus bundle or list (optional). */
    baseline_corpus?: unknown;
    baseline_items?: unknown[];
    foundational_baseline_corpus?: unknown;
    candidate_quality?: Record<string, unknown>;
    candidate_quality_metrics?: Record<string, unknown>;
    graph_readiness?: Record<string, unknown>;
    robustness_validation?: Record<string, unknown>;
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

type PurgeDialogState = {
  targetType: "run" | "family";
  targetId: string;
  label: string;
  summary: PurgeSummary;
};

type RestoreStatus = "idle" | "restoring" | "restored" | "none" | "stale" | "failed";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const LAST_RUN_STORAGE_KEY = "codeone:last-loaded-run-id";

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
  const [purgeDialog, setPurgeDialog] = useState<PurgeDialogState | null>(null);
  const [purgeDialogLoading, setPurgeDialogLoading] = useState(false);
  const [workspaceLoadingRunId, setWorkspaceLoadingRunId] = useState<string | null>(null);
  const [workspaceRestoreMessage, setWorkspaceRestoreMessage] = useState<string | null>(null);
  const [restoreStatus, setRestoreStatus] = useState<RestoreStatus>("idle");
  const [showInactiveRuns, setShowInactiveRuns] = useState(false);
  const [hiddenRunIds, setHiddenRunIds] = useState<string[]>([]);
  const [validationStartedAt, setValidationStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [reviewOutputTab, setReviewOutputTab] = useState<"candidates" | "baseline" | "validation">("candidates");
  const abortControllerRef = useRef<AbortController | null>(null);
  const pdfRelinkInputRef = useRef<HTMLInputElement | null>(null);

  const summaryText = useMemo(() => {
    if (loading) {
      return `Validating ${pdfFile?.name ?? "selected PDF"} against ${xmlFile?.name ?? "selected XML"}...`;
    }
    if (!response) {
      return "Upload a PDF and XML pair to validate the linked NCC representations.";
    }
    return `XML: ${response.summary.xml_status} | PDF: ${response.summary.pdf_status} | Can Progress: ${response.summary.can_progress}`;
  }, [loading, pdfFile, response, xmlFile]);

  const activeRunCount = useMemo(
    () => runs.filter((run) => run.status === "active").length,
    [runs]
  );

  const inactiveRuns = useMemo(
    () => runs.filter((run) => ["invalidated", "purged"].includes(run.status)),
    [runs]
  );

  const manuallyHiddenRuns = useMemo(
    () => inactiveRuns.filter((run) => hiddenRunIds.includes(run.ingestion_run_id)),
    [hiddenRunIds, inactiveRuns]
  );

  const visibleRuns = useMemo(
    () =>
      runs.filter((run) => {
        if (run.status === "active") {
          return true;
        }
        if (!["invalidated", "purged"].includes(run.status)) {
          return true;
        }
        if (!showInactiveRuns) {
          return false;
        }
        return !hiddenRunIds.includes(run.ingestion_run_id);
      }),
    [hiddenRunIds, runs, showInactiveRuns]
  );

  const latestRun = runs[0] ?? null;
  const loadedRunId = response?.summary.ingestion_run_id ?? null;
  const isAutoRestoring = !response && (restoreStatus === "idle" || restoreStatus === "restoring");

  useEffect(() => {
    void refreshRuns();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restoreWorkspaceOnStartup(): Promise<void> {
      const storedRunId = readStoredLastRunId();
      if (!storedRunId) {
        if (!cancelled) {
          setRestoreStatus("none");
        }
        return;
      }

      if (!cancelled) {
        setRestoreStatus("restoring");
        setWorkspaceRestoreMessage(null);
      }

      const result = await loadWorkspace(storedRunId, { quietOnFailure: true });
      if (cancelled) {
        return;
      }

      if (result.ok) {
        setRestoreStatus("restored");
        setWorkspaceRestoreMessage("Automatically reopened the last retained workspace after refresh.");
        return;
      }

      if (result.stale) {
        clearStoredLastRunId();
        setRestoreStatus("stale");
        setWorkspaceRestoreMessage("The last retained workspace is no longer available, so the console opened without it.");
        return;
      }

      setRestoreStatus("failed");
      setWorkspaceRestoreMessage("Automatic workspace restore did not complete. Use `Load workspace` after the backend is reachable.");
    }

    void restoreWorkspaceOnStartup();

    return () => {
      cancelled = true;
    };
    // The startup restore runs once on mount; later workspace loads are user-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setReviewOutputTab("candidates");
  }, [response?.summary.ingestion_run_id]);

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

  function persistLastRunId(runId: string | null | undefined): void {
    if (!runId) {
      clearStoredLastRunId();
      return;
    }
    window.localStorage.setItem(LAST_RUN_STORAGE_KEY, runId);
  }

  function clearStoredLastRunId(): void {
    window.localStorage.removeItem(LAST_RUN_STORAGE_KEY);
  }

  function readStoredLastRunId(): string | null {
    return window.localStorage.getItem(LAST_RUN_STORAGE_KEY);
  }

  function clearWorkspaceForAffectedRuns(runIds: string[], message: string): void {
    const affectedRunIds = new Set(runIds.filter(Boolean));
    if (affectedRunIds.size === 0) {
      return;
    }

    const activeRunId = response?.summary.ingestion_run_id ?? null;
    const storedRunId = readStoredLastRunId();
    const shouldClearActiveWorkspace = Boolean(activeRunId && affectedRunIds.has(activeRunId));
    const shouldClearStoredRun = Boolean(storedRunId && affectedRunIds.has(storedRunId));

    if (!shouldClearActiveWorkspace && !shouldClearStoredRun) {
      return;
    }

    if (shouldClearStoredRun) {
      clearStoredLastRunId();
    }

    if (shouldClearActiveWorkspace) {
      setResponse(null);
      setPdfFile(null);
      setXmlFile(null);
      setWorkspaceRestoreMessage(message);
      setRestoreStatus("stale");
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
      const payload = (await result.json()) as { ingestion_run_id?: string | null };
      clearWorkspaceForAffectedRuns(
        payload.ingestion_run_id ? [payload.ingestion_run_id] : [runId],
        "The current review workspace was cleared because this run was invalidated."
      );
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

  async function prepareRunPurge(run: RunRecord) {
    setActionError(null);
    setPurgeDialogLoading(true);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/runs/${run.ingestion_run_id}/dry-run`);
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to preview purge.");
      }
      const summary = (await result.json()) as PurgeSummary;
      setPurgeDialog({
        targetType: "run",
        targetId: run.ingestion_run_id,
        label: run.document_family_id,
        summary,
      });
    } catch (previewError) {
      setActionError(previewError instanceof Error ? previewError.message : "Unknown error");
    } finally {
      setPurgeDialogLoading(false);
    }
  }

  async function prepareFamilyPurge(run: RunRecord) {
    setActionError(null);
    setPurgeDialogLoading(true);
    try {
      const result = await fetch(`${API_BASE_URL}/api/purge/source-documents/${run.pdf_source_document_id}/dry-run`);
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to preview family purge.");
      }
      const summary = (await result.json()) as PurgeSummary;
      setPurgeDialog({
        targetType: "family",
        targetId: run.pdf_source_document_id,
        label: run.document_family_id,
        summary,
      });
    } catch (previewError) {
      setActionError(previewError instanceof Error ? previewError.message : "Unknown error");
    } finally {
      setPurgeDialogLoading(false);
    }
  }

  async function confirmPurge() {
    if (!purgeDialog) {
      return;
    }

    setActionError(null);
    setPurgeDialogLoading(true);
    try {
      const result =
        purgeDialog.targetType === "run"
          ? await fetch(`${API_BASE_URL}/api/purge/runs/${purgeDialog.targetId}`, { method: "POST" })
          : await fetch(`${API_BASE_URL}/api/purge/source-documents/${purgeDialog.targetId}`, {
              method: "POST",
            });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to purge target.");
      }
      const payload = (await result.json()) as PurgeSummary;

      setPurgePreview(payload);
      setPurgeDialog(null);
      clearWorkspaceForAffectedRuns(
        payload.run_ids,
        purgeDialog.targetType === "family"
          ? "The current review workspace was cleared because this document family was purged."
          : "The current review workspace was cleared because this run was purged."
      );
      await refreshRuns();
    } catch (purgeError) {
      setActionError(purgeError instanceof Error ? purgeError.message : "Unknown error");
    } finally {
      setPurgeDialogLoading(false);
    }
  }

  async function loadWorkspace(
    runId: string,
    options?: {
      quietOnFailure?: boolean;
    }
  ): Promise<{ ok: boolean; stale: boolean }> {
    const quietOnFailure = Boolean(options?.quietOnFailure);
    setActionError(null);
    setWorkspaceRestoreMessage(null);
    setWorkspaceLoadingRunId(runId);
    try {
      const result = await fetch(`${API_BASE_URL}/api/ingestions/runs/${runId}`);
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        const detail = payload.detail ?? "Failed to load retained workspace.";
        const stale = result.status === 404 || result.status === 409;
        throw Object.assign(new Error(detail), { stale });
      }
      const payload = (await result.json()) as IngestionResponse;
      setResponse(payload);
      setPdfFile(null);
      setXmlFile(null);
      persistLastRunId(payload.summary.ingestion_run_id);
      return { ok: true, stale: false };
    } catch (loadError) {
      const stale =
        loadError instanceof Error &&
        "stale" in loadError &&
        typeof (loadError as Error & { stale?: unknown }).stale === "boolean"
          ? Boolean((loadError as Error & { stale?: boolean }).stale)
          : false;

      if (stale) {
        clearStoredLastRunId();
      }
      if (!quietOnFailure) {
        setActionError(loadError instanceof Error ? loadError.message : "Unknown error");
      }
      return { ok: false, stale };
    } finally {
      setWorkspaceLoadingRunId(null);
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
      persistLastRunId(payload.summary.ingestion_run_id);
      setRestoreStatus("restored");
      setWorkspaceRestoreMessage(null);
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

  function handleRelinkPdf(): void {
    pdfRelinkInputRef.current?.click();
  }

  function handleRelinkPdfSelection(event: ChangeEvent<HTMLInputElement>): void {
    const nextFile = event.target.files?.[0] ?? null;
    if (nextFile) {
      setPdfFile(nextFile);
    }
    event.target.value = "";
  }

  function hideRun(runId: string) {
    setHiddenRunIds((current) => (current.includes(runId) ? current : [...current, runId]));
  }

  function unhideRun(runId: string) {
    setHiddenRunIds((current) => current.filter((id) => id !== runId));
  }

  function restoreHiddenRuns() {
    setHiddenRunIds([]);
  }

  return (
    <main>
      <input
        ref={pdfRelinkInputRef}
        type="file"
        accept=".pdf"
        onChange={handleRelinkPdfSelection}
        style={{ display: "none" }}
      />
      <ConsoleNavigation />
      <section className="panel hero-panel">
        <div className="hero-grid">
          <div className="hero-copy">
            <span className="eyebrow">NCC document operations</span>
            <h1>NCC Ingestion Console</h1>
            <p className="hero-lead">
              Run the hardened XML and PDF contracts together, inspect candidate-backed review evidence,
              and manage retained ingestion runs from a single operator console.
            </p>
            <p className="muted">{summaryText}</p>
          </div>
          <div className="hero-stats" aria-label="Console overview">
            <div className="summary-card">
              <strong>Active Runs</strong>
              <span>{activeRunCount}</span>
            </div>
            <div className="summary-card">
              <strong>Current Pair</strong>
              <span>{pdfFile && xmlFile ? "Ready" : "Awaiting files"}</span>
            </div>
            <div className="summary-card">
              <strong>Latest Family</strong>
              <span>{latestRun?.document_family_id ?? "No runs yet"}</span>
              <span className="summary-subtext">{formatDateTime(latestRun?.created_at)}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="panel intake-panel">
        <div className="section-header">
          <div>
            <span className="eyebrow">Validate pair</span>
            <h2>Load a PDF and XML source</h2>
            <p className="muted">
              Start a new ingestion run, then review the candidate workspace and structured validation output
              below.
            </p>
          </div>
        </div>
        <div className="intake-layout">
          <form className="grid intake-form" onSubmit={onSubmit} aria-busy={loading}>
            <div className="field-shell">
              <label htmlFor="pdf">PDF document</label>
              <input
                id="pdf"
                type="file"
                accept=".pdf"
                disabled={loading}
                onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <div className="field-shell">
              <label htmlFor="xml">XML source</label>
              <input
                id="xml"
                type="file"
                accept=".xml"
                disabled={loading}
                onChange={(event) => setXmlFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <div className="action-row">
              <button type="submit" disabled={loading}>
                {loading ? "Validating..." : "Validate ingestion"}
              </button>
              {loading ? (
                <button type="button" className="button-secondary" onClick={cancelValidation}>
                  Cancel validation
                </button>
              ) : null}
            </div>
            {error ? (
              <p className="alert alert-error" role="alert">
                {error}
              </p>
            ) : null}
          </form>
          <aside className="intake-sidebar panel-muted">
            <h3>Run readiness</h3>
            <div className="detail-list">
              <div>
                <strong>PDF</strong>: {pdfFile?.name ?? "Not selected"}
              </div>
              <div>
                <strong>XML</strong>: {xmlFile?.name ?? "Not selected"}
              </div>
              <div>
                <strong>Latest response</strong>: {response ? response.summary.pdf_status : "No response yet"}
              </div>
              <div>
                <strong>Run timestamp</strong>: {formatDateTime(response?.summary.created_at)}
              </div>
            </div>
          </aside>
        </div>
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
                  <strong>Previous results</strong>: {response ? "Still visible below for comparison." : "No earlier run loaded."}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <XmlUploadViewer files={xmlFile ? [xmlFile] : []} />
      <PdfUploadViewer file={pdfFile} />

      {response ? (
        <>
          <div className="review-output-intro">
            <section className="section-header review-output-heading">
              <div>
                <span className="eyebrow">Review output</span>
                <h2>Current validation and candidate review</h2>
                <p className="muted">
                  Loaded run {response.summary.ingestion_run_id ?? "n/a"} recorded{" "}
                  {formatDateTime(response.summary.created_at)}.
                </p>
                {workspaceRestoreMessage ? <p className="muted">{workspaceRestoreMessage}</p> : null}
              </div>
            </section>
            <div className="review-output-tabs" role="tablist" aria-label="Review output views">
              <button
                type="button"
                role="tab"
                className={`review-tab ${reviewOutputTab === "candidates" ? "active" : ""}`}
                aria-selected={reviewOutputTab === "candidates"}
                onClick={() => setReviewOutputTab("candidates")}
              >
                Candidate review
              </button>
              <button
                type="button"
                role="tab"
                className={`review-tab ${reviewOutputTab === "baseline" ? "active" : ""}`}
                aria-selected={reviewOutputTab === "baseline"}
                onClick={() => setReviewOutputTab("baseline")}
              >
                Baseline corpus
              </button>
              <button
                type="button"
                role="tab"
                className={`review-tab ${reviewOutputTab === "validation" ? "active" : ""}`}
                aria-selected={reviewOutputTab === "validation"}
                onClick={() => setReviewOutputTab("validation")}
              >
                Validation and metrics
              </button>
            </div>
          </div>

          <div className="review-output-panels">
            {reviewOutputTab === "candidates" ? (
              <CandidateReviewWorkspace
                response={response}
                pdfFile={pdfFile}
                apiBaseUrl={API_BASE_URL}
                onRelinkPdf={handleRelinkPdf}
              />
            ) : null}

            {reviewOutputTab === "baseline" ? (
              <BaselineCorpusPanel
                review_workspace={response.review_workspace as Record<string, unknown> | undefined}
                lineage={response.lineage as Record<string, unknown> | undefined}
                raw_metrics={response.raw_metrics}
              />
            ) : null}

            {reviewOutputTab === "validation" ? (
              <div className="grid results-grid review-validation-stack">
                <ValidationViewer title="XML Validation" result={response.results.xml_validation} />
                <ValidationViewer title="PDF Validation" result={response.results.pdf_validation} />
                <ReviewMetricsStrip
                  raw_metrics={response.raw_metrics}
                  review_workspace={response.review_workspace as Record<string, unknown> | undefined}
                />
                <section className="panel">
                  <div className="section-header compact">
                    <div>
                      <h2>Raw metrics</h2>
                      <p className="muted">Full reference diagnostics for debugging and schema-level inspection.</p>
                    </div>
                  </div>
                  <details className="detail-disclosure" open>
                    <summary>Open raw metrics JSON</summary>
                    <pre>{JSON.stringify(response.raw_metrics, null, 2)}</pre>
                  </details>
                </section>
              </div>
            ) : null}
          </div>
        </>
      ) : isAutoRestoring ? (
        <section className="panel">
          <div className="section-header compact">
            <div>
              <span className="eyebrow">Review output</span>
              <h2>Restoring retained workspace</h2>
              <p className="muted">
                Reopening the last retained workspace after refresh. If the saved run is still available, the
                review console and retained PDF preview will return automatically.
              </p>
            </div>
          </div>
        </section>
      ) : (
        <section className="panel">
          <div className="section-header compact">
            <div>
              <span className="eyebrow">Review output</span>
              <h2>No workspace loaded</h2>
              <p className="muted">
                Validate a new PDF/XML pair above, or reopen a retained run from the retention list below using
                `Load workspace`. The console will also try to reopen the last retained workspace after refresh
                when that run is still available.
              </p>
              {workspaceRestoreMessage ? <p className="muted">{workspaceRestoreMessage}</p> : null}
            </div>
          </div>
        </section>
      )}

      <section className="panel">
        <div className="section-header">
          <div>
            <span className="eyebrow">Retention</span>
            <h2>Retention Controls</h2>
            <p className="muted">
              Retention keeps ingestion runs available for review after validation. Use the controls below based
              on whether you are organizing the console, marking a run invalid, or removing retained derived
              records.
            </p>
          </div>
          <button type="button" className="button-secondary" onClick={() => void refreshRuns()} disabled={runLoading}>
            {runLoading ? "Refreshing..." : "Refresh runs"}
          </button>
        </div>
        <div className="retention-toolbar">
          <div className="retention-toggle-group" role="toolbar" aria-label="Retention visibility controls">
            <button
              type="button"
              className="button-secondary"
              aria-pressed={showInactiveRuns}
              onClick={() => setShowInactiveRuns((current) => !current)}
            >
              {showInactiveRuns ? "Hide non-active runs" : `Show non-active runs (${inactiveRuns.length})`}
            </button>
            {manuallyHiddenRuns.length ? (
              <button type="button" className="button-secondary" onClick={restoreHiddenRuns}>
                Unhide all ({manuallyHiddenRuns.length})
              </button>
            ) : null}
          </div>
          <p className="muted retention-toolbar-note">
            Active runs are always visible. Invalidated and purged runs stay hidden until you choose to reveal
            them.
          </p>
        </div>
        <div className="grid retention-guide">
          <div className="summary-card">
            <strong>Hide</strong>
            <span>UI only</span>
            <span className="summary-subtext">Removes non-active runs from this session view only.</span>
          </div>
          <div className="summary-card">
            <strong>Invalidate</strong>
            <span>Backend status change</span>
            <span className="summary-subtext">Marks a run invalid while keeping retained evidence available.</span>
          </div>
          <div className="summary-card">
            <strong>Purge</strong>
            <span>Destructive cleanup</span>
            <span className="summary-subtext">Deletes retained derived lineage after preview and confirmation.</span>
          </div>
        </div>
        {manuallyHiddenRuns.length ? (
          <details className="detail-disclosure retention-hidden-summary">
            <summary>Hidden items in this session ({manuallyHiddenRuns.length})</summary>
            <div className="grid retention-hidden-list">
              {manuallyHiddenRuns.map((run) => (
                <div key={run.ingestion_run_id} className="retention-hidden-item">
                  <div className="retention-hidden-meta">
                    <div>
                      <strong>{run.document_family_id}</strong>
                      <p className="muted">{run.ingestion_run_id}</p>
                    </div>
                    <span
                      className={`status ${
                        run.status === "active" ? "pass" : run.status === "invalidated" ? "warn" : "fail"
                      }`}
                    >
                      {run.status}
                    </span>
                  </div>
                  <div className="action-row">
                    <button type="button" className="button-secondary" onClick={() => unhideRun(run.ingestion_run_id)}>
                      Unhide
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </details>
        ) : null}
        {actionError ? (
          <p className="alert alert-error" role="alert">
            {actionError}
          </p>
        ) : null}
        <div className="grid retention-grid">
          {!runs.length ? (
            <div className="empty-state">
              No ingestion runs yet. Validate a PDF and XML pair above to create the first retained run.
            </div>
          ) : null}
          {runs.length > 0 && !visibleRuns.length ? (
            <div className="empty-state">
              No retention items are visible right now. Reveal non-active runs or unhide hidden items to see
              more.
            </div>
          ) : null}
          {visibleRuns.map((run) => (
            <div
              key={run.ingestion_run_id}
              className={`panel retention-card ${loadedRunId === run.ingestion_run_id ? "retention-card-loaded" : ""}`}
            >
              <div className="workspace-header">
                <div>
                  <h3>{run.document_family_id}</h3>
                  <p className="muted">{run.ingestion_run_id}</p>
                </div>
                <div className="retention-status-stack">
                  {loadedRunId === run.ingestion_run_id ? <span className="status pass">loaded</span> : null}
                  <span className={`status ${run.status === "active" ? "pass" : run.status === "invalidated" ? "warn" : "fail"}`}>
                    {run.status}
                  </span>
                </div>
              </div>
              <div className="detail-list">
                <div>
                  <strong>Run Created</strong>: {formatDateTime(run.created_at)}
                </div>
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
              <div className="action-row">
                <button
                  type="button"
                  className="button-secondary"
                  onClick={() => void loadWorkspace(run.ingestion_run_id)}
                  disabled={run.status === "purged" || workspaceLoadingRunId === run.ingestion_run_id}
                >
                  {workspaceLoadingRunId === run.ingestion_run_id ? "Loading..." : loadedRunId === run.ingestion_run_id ? "Loaded workspace" : "Load workspace"}
                </button>
                <button type="button" className="button-secondary" onClick={() => void invalidateRun(run.ingestion_run_id)} disabled={run.status !== "active"}>
                  Invalidate
                </button>
                {run.status !== "active" ? (
                  <button type="button" className="button-secondary" onClick={() => hideRun(run.ingestion_run_id)}>
                    Hide
                  </button>
                ) : null}
                <button type="button" className="button-secondary" onClick={() => void previewRunPurge(run.ingestion_run_id)}>
                  Dry-run purge
                </button>
                <button type="button" className="button-danger" onClick={() => void prepareRunPurge(run)} disabled={purgeDialogLoading}>
                  Purge run
                </button>
                <button type="button" className="button-secondary" onClick={() => void previewFamilyPurge(run.pdf_source_document_id)}>
                  Dry-run family purge
                </button>
                <button type="button" className="button-danger" onClick={() => void prepareFamilyPurge(run)} disabled={purgeDialogLoading}>
                  Purge family
                </button>
              </div>
            </div>
          ))}
        </div>
        {purgePreview ? (
          <details className="detail-disclosure">
            <summary>Latest purge summary</summary>
            <pre>{JSON.stringify(purgePreview, null, 2)}</pre>
          </details>
        ) : null}
      </section>

      {purgeDialog ? (
        <div className="dialog-backdrop" role="presentation">
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="purge-dialog-title">
            <span className="eyebrow">Destructive action</span>
            <h2 id="purge-dialog-title">
              Confirm {purgeDialog.targetType === "run" ? "run purge" : "family purge"}
            </h2>
            <p>
              You are about to purge lineage records for <strong>{purgeDialog.label}</strong>. Raw inputs are
              retained, but derived records listed below will be marked purged.
            </p>
            <div className="grid two-column">
              <div className="summary-card">
                <strong>Target</strong>
                <span>{purgeDialog.summary.target_id}</span>
              </div>
              <div className="summary-card">
                <strong>Affected runs</strong>
                <span>{purgeDialog.summary.run_ids.length}</span>
              </div>
            </div>
            <details className="detail-disclosure" open>
              <summary>Preview purge scope</summary>
              <pre>{JSON.stringify(purgeDialog.summary, null, 2)}</pre>
            </details>
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={() => setPurgeDialog(null)} disabled={purgeDialogLoading}>
                Cancel
              </button>
              <button type="button" className="button-danger" onClick={() => void confirmPurge()} disabled={purgeDialogLoading}>
                {purgeDialogLoading ? "Purging..." : "Confirm purge"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
