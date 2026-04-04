"use client";

import { ChangeEvent, useEffect, useId, useMemo, useState } from "react";

type RegistryType = "observed" | "approved" | "uploaded";
type SchemaScope = "family" | "tag";
type PresentationMode = "human" | "raw";

type SchemaEntry = Record<string, any>;

type RegistryPayload = {
  registry_type: "observed" | "approved";
  registry_version?: string | null;
  generated_at?: string | null;
  scanned_file_count?: number | null;
  family_count?: number | null;
  tag_count?: number | null;
  families: SchemaEntry[];
  tags: SchemaEntry[];
  scan_errors?: { file?: string; error?: string }[];
  repo_sync?: Record<string, any>;
  tag_repo_sync?: Record<string, any>;
};

type BatchPayload = {
  batch_job_id: string;
  generated_at?: string | null;
  uploaded_file_count: number;
  scanned_file_count: number;
  family_count: number;
  tag_count: number;
  families: SchemaEntry[];
  tags: SchemaEntry[];
  scan_errors?: { file?: string; error?: string }[];
  approved_registry_version?: string | null;
  approved_tag_registry_version?: string | null;
  observed_registry_version?: string | null;
  observed_family_count?: number | null;
  observed_tag_count?: number | null;
  observed_merge_applied?: boolean;
  repo_sync?: Record<string, any>;
  tag_repo_sync?: Record<string, any>;
};

type DetailPayload = {
  registry_type: RegistryType;
  registry_version?: string | null;
  scope: SchemaScope;
  item: SchemaEntry;
  batch_job_id?: string | null;
};

const architectureSteps = [
  {
    title: "1. Root family discovery",
    descriptor:
      "The scan groups each XML file by its root fingerprint so reviewers can see recurring document shapes before anything is approved.",
    example:
      "Example file starts as `page > title | section`, so the root family row captures the page-level shape and the files that share it.",
  },
  {
    title: "2. Reusable tag extraction",
    descriptor:
      "The same scan walks the full tree and extracts reusable descendant tags like `title` and `xref`, keeping a stable tag fingerprint while logging every observed parent and path context.",
    example:
      "The running example records `title` at `page/title`, `page/section/title`, and `page/section/table-reference/title` so one tag can still be traced to different contexts.",
  },
  {
    title: "3. Approval registry",
    descriptor:
      "Reviewers approve root families and reusable tags separately. The approved registry stores human-readable ids plus the raw hashes that runtime matching relies on.",
    example:
      "Approving the page family and the `title` tag means later scans can flag an exact match as approved and a same-name but different-shape tag as a variant.",
  },
  {
    title: "4. Ingestion lineage",
    descriptor:
      "During ingestion, every emitted XML candidate keeps its root, parent, ancestor tags, and full path so extracted evidence never loses its structural anchor.",
    example:
      "A paragraph candidate keeps `/page[@id='page_1']/section[@id='sec_1']/p[@id='p_1']`, while its nested `xref` still contributes reusable tag context during review.",
  },
] as const;

const architectureMermaidDefinition = `
flowchart LR
  source["XML source file<br/>page -> title + section"] --> family["Root family discovery<br/>Fingerprint groups recurring page shapes"]
  family --> tags["Reusable tag extraction<br/>title and xref get stable tag fingerprints"]
  tags --> approval["Approval registry<br/>Human ids + raw hashes are promoted"]
  approval --> lineage["Ingestion lineage<br/>Candidates keep root, parent, and full path"]
  source -. running example .-> tags
  tags -. title contexts .-> lineage
`;

function countEntries(value: unknown): Array<{ label: string; count: string }> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is { tag?: unknown; path?: unknown; count?: unknown } => typeof item === "object" && item !== null)
    .map((item) => ({
      label: summaryValue("tag" in item ? item.tag : item.path),
      count: summaryValue(item.count),
    }));
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

function statusTone(value: string | null | undefined): "pass" | "warn" | "fail" {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized === "approved") {
    return "pass";
  }
  if (normalized === "variant") {
    return "warn";
  }
  return "fail";
}

function summaryValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "n/a";
  }
  return String(value);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function objectEntries(value: unknown): Array<[string, string]> {
  if (!value || Array.isArray(value) || typeof value !== "object") {
    return [];
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, entryValue]) => [key, summaryValue(entryValue)] as [string, string])
    .sort(([left], [right]) => left.localeCompare(right));
}

export function SchemaReviewPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const mermaidChartId = useId().replace(/:/g, "");
  const [activeRegistry, setActiveRegistry] = useState<RegistryType>("uploaded");
  const [activeScope, setActiveScope] = useState<SchemaScope>("family");
  const [presentationMode, setPresentationMode] = useState<PresentationMode>("human");
  const [repoObserved, setRepoObserved] = useState<RegistryPayload | null>(null);
  const [approved, setApproved] = useState<RegistryPayload | null>(null);
  const [uploadedBatch, setUploadedBatch] = useState<BatchPayload | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [detail, setDetail] = useState<DetailPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [repoScanning, setRepoScanning] = useState(false);
  const [uploadScanning, setUploadScanning] = useState(false);
  const [approvingHash, setApprovingHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [architectureDiagramSvg, setArchitectureDiagramSvg] = useState<string | null>(null);
  const [architectureDiagramError, setArchitectureDiagramError] = useState<string | null>(null);

  const activePayload =
    activeRegistry === "uploaded" ? uploadedBatch : activeRegistry === "observed" ? repoObserved : approved;
  const repoSync =
    activeScope === "tag"
      ? activeRegistry === "uploaded"
        ? uploadedBatch?.repo_sync ?? {}
        : activePayload?.tag_repo_sync ?? {}
      : activePayload?.repo_sync ?? {};
  const activeEntries = activeScope === "family" ? activePayload?.families ?? [] : activePayload?.tags ?? [];
  const detailItem = detail?.item ?? null;
  const detailAllElementTags = stringArray(detailItem?.all_element_tags);
  const detailElementTagCounts = objectEntries(detailItem?.element_tag_counts);
  const detailAttributeCounts = objectEntries(detailItem?.attribute_name_counts);
  const detailLeafTags = stringArray(detailItem?.leaf_tags);
  const detailHighlightedPaths = objectEntries(detailItem?.highlighted_paths);
  const detailCommonPaths = Array.isArray(detailItem?.common_paths)
    ? detailItem.common_paths
        .filter(
          (item: unknown): item is { path?: unknown; count?: unknown } =>
            typeof item === "object" && item !== null
        )
        .map((item) => ({
          path: summaryValue(item.path),
          count: summaryValue(item.count),
        }))
    : [];
  const detailCommonParentTags = countEntries(detailItem?.common_parent_tags);
  const detailCommonStructuralParents = countEntries(detailItem?.common_structural_parents);
  const detailExamplePaths = stringArray(detailItem?.example_paths);
  const detailExampleTexts = stringArray(detailItem?.example_texts);

  const stats = useMemo(() => {
    const observedFamilies = repoObserved?.families ?? [];
    const approvedFamilies = approved?.families ?? [];
    const observedTags = repoObserved?.tags ?? [];
    const approvedTags = approved?.tags ?? [];
    const uploadedFamilies = uploadedBatch?.families ?? [];
    const uploadedTags = uploadedBatch?.tags ?? [];
    const observedApproved = observedFamilies.filter((family) => family.schema_approved).length;
    const observedVariants = observedFamilies.filter((family) => family.status === "variant").length;
    const observedUnknown = observedFamilies.filter((family) => family.status === "unknown").length;
    const observedApprovedTags = observedTags.filter((tag) => tag.schema_approved).length;
    const observedVariantTags = observedTags.filter((tag) => tag.status === "variant").length;
    return {
      uploadedFiles: uploadedBatch?.uploaded_file_count ?? selectedFiles.length,
      uploadedFamilies: uploadedFamilies.length,
      uploadedTags: uploadedTags.length,
      observedTotal: observedFamilies.length,
      observedApproved,
      observedVariants,
      observedUnknown,
      approvedTotal: approvedFamilies.length,
      observedTagTotal: observedTags.length,
      observedApprovedTags,
      observedVariantTags,
      approvedTagTotal: approvedTags.length,
      scannedFiles: repoObserved?.scanned_file_count ?? 0,
    };
  }, [approved, repoObserved, selectedFiles.length, uploadedBatch]);

  useEffect(() => {
    void refreshRegistries();
    // Initial registry load runs once; subsequent refreshes are triggered by explicit user actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function renderArchitectureDiagram(): Promise<void> {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "base",
          securityLevel: "strict",
          themeVariables: {
            background: "#0b1017",
            primaryColor: "#111a24",
            primaryTextColor: "#e8f0ff",
            primaryBorderColor: "#8fb8ff",
            lineColor: "#8fb8ff",
            secondaryColor: "#151d28",
            tertiaryColor: "#0f1620",
            fontFamily: "Roboto, Helvetica Neue, Arial, sans-serif",
          },
          flowchart: {
            curve: "basis",
            htmlLabels: true,
          },
        });
        const { svg } = await mermaid.render(`schema-lineage-${mermaidChartId}`, architectureMermaidDefinition);
        if (cancelled) {
          return;
        }
        setArchitectureDiagramSvg(svg);
        setArchitectureDiagramError(null);
      } catch {
        if (cancelled) {
          return;
        }
        setArchitectureDiagramSvg(null);
        setArchitectureDiagramError("The Mermaid diagram could not be rendered.");
      }
    }

    void renderArchitectureDiagram();
    return () => {
      cancelled = true;
    };
  }, [mermaidChartId]);

  async function refreshRegistries(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const [observedResult, approvedResult, observedTagsResult, approvedTagsResult] = await Promise.all([
        fetch(`${apiBaseUrl}/api/xml-schemas/families?registry_type=observed`),
        fetch(`${apiBaseUrl}/api/xml-schemas/families?registry_type=approved`),
        fetch(`${apiBaseUrl}/api/xml-schemas/tags?registry_type=observed`),
        fetch(`${apiBaseUrl}/api/xml-schemas/tags?registry_type=approved`),
      ]);
      if (!observedResult.ok || !approvedResult.ok || !observedTagsResult.ok || !approvedTagsResult.ok) {
        throw new Error("Failed to load schema registries.");
      }
      const [observedPayload, approvedPayload, observedTagsPayload, approvedTagsPayload] = (await Promise.all([
        observedResult.json(),
        approvedResult.json(),
        observedTagsResult.json(),
        approvedTagsResult.json(),
      ])) as [RegistryPayload, RegistryPayload, RegistryPayload, RegistryPayload];
      const nextObserved = {
        ...observedPayload,
        tag_count: observedTagsPayload.tag_count,
        tags: observedTagsPayload.tags ?? [],
        tag_repo_sync: observedTagsPayload.repo_sync ?? {},
      };
      const nextApproved = {
        ...approvedPayload,
        tag_count: approvedTagsPayload.tag_count,
        tags: approvedTagsPayload.tags ?? [],
        tag_repo_sync: approvedTagsPayload.repo_sync ?? {},
      };
      setRepoObserved(nextObserved);
      setApproved(nextApproved);
      if (detail) {
        if (detail.registry_type === "uploaded") {
          const nextItem = (detail.scope === "family" ? uploadedBatch?.families : uploadedBatch?.tags)?.find(
            (item) =>
              detail.scope === "family"
                ? String(item.fingerprint_hash ?? "") === String(detail.item.fingerprint_hash ?? "")
                : String(item.tag_fingerprint_hash ?? "") === String(detail.item.tag_fingerprint_hash ?? "")
          );
          if (nextItem) {
            setDetail({
              registry_type: "uploaded",
              registry_version: uploadedBatch?.batch_job_id ?? detail.batch_job_id ?? null,
              scope: detail.scope,
              item: nextItem,
              batch_job_id: uploadedBatch?.batch_job_id ?? detail.batch_job_id ?? null,
            });
          }
        } else {
          const detailKey =
            detail.scope === "family"
              ? detail.registry_type === "approved"
                ? String(detail.item.schema_family_id ?? "")
                : String(detail.item.fingerprint_hash ?? "")
              : detail.registry_type === "approved"
                ? String(detail.item.schema_tag_id ?? "")
                : String(detail.item.tag_fingerprint_hash ?? "");
          if (detailKey) {
            await loadRegistryDetail(detail.registry_type, detail.scope, detailKey, false);
          }
        }
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function onSelectFiles(event: ChangeEvent<HTMLInputElement>): void {
    const nextFiles = Array.from(event.target.files ?? []);
    setSelectedFiles(nextFiles);
  }

  async function runUploadedBatchScan(): Promise<void> {
    if (!selectedFiles.length) {
      setError("Choose one or more XML files to create an uploaded batch.");
      return;
    }
    setUploadScanning(true);
    setError(null);
    setInfoMessage(null);
    try {
      const formData = new FormData();
      selectedFiles.forEach((file) => formData.append("files", file));
      const result = await fetch(`${apiBaseUrl}/api/xml-schemas/batches/upload`, {
        method: "POST",
        body: formData,
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to scan uploaded XML batch.");
      }
      const payload = (await result.json()) as BatchPayload;
      setUploadedBatch(payload);
      await refreshRegistries();
      setActiveRegistry("observed");
      setActiveScope("tag");
      setDetail(null);
      if (payload.observed_merge_applied) {
        setInfoMessage(
          `Uploaded discoveries were merged into observed registry ${payload.observed_registry_version ?? "n/a"}. Observed tags now total ${payload.observed_tag_count ?? 0}.`
        );
      }
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Unknown error");
    } finally {
      setUploadScanning(false);
    }
  }

  async function runRepoCorpusScan(): Promise<void> {
    setRepoScanning(true);
    setError(null);
    try {
      const result = await fetch(`${apiBaseUrl}/api/xml-schemas/scan`, { method: "POST" });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Failed to scan XML corpus.");
      }
      await refreshRegistries();
      setActiveRegistry("observed");
      setDetail(null);
    } catch (scanError) {
      setError(scanError instanceof Error ? scanError.message : "Unknown error");
    } finally {
      setRepoScanning(false);
    }
  }

  async function loadRegistryDetail(
    registryType: Exclude<RegistryType, "uploaded">,
    scope: SchemaScope,
    entryKey: string,
    clearError = true
  ): Promise<void> {
    if (!entryKey) {
      return;
    }
    if (clearError) {
      setError(null);
    }
    try {
      const result = await fetch(
        `${apiBaseUrl}/api/xml-schemas/${scope === "family" ? "families" : "tags"}/${encodeURIComponent(entryKey)}?registry_type=${registryType}`
      );
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? `Failed to load schema ${scope} detail.`);
      }
      const payload = (await result.json()) as { registry_type: RegistryType; registry_version?: string | null; family?: SchemaEntry; tag?: SchemaEntry };
      setDetail({
        registry_type: payload.registry_type,
        registry_version: payload.registry_version,
        scope,
        item: scope === "family" ? payload.family ?? {} : payload.tag ?? {},
      });
    } catch (detailError) {
      if (clearError) {
        setError(detailError instanceof Error ? detailError.message : "Unknown error");
      }
    }
  }

  function openEntryDetail(registryType: RegistryType, scope: SchemaScope, item: SchemaEntry): void {
    if (registryType === "uploaded") {
      setDetail({
        registry_type: "uploaded",
        registry_version: uploadedBatch?.batch_job_id ?? null,
        scope,
        item,
        batch_job_id: uploadedBatch?.batch_job_id ?? null,
      });
      return;
    }
    const entryKey =
      scope === "family"
        ? registryType === "approved"
          ? String(item.schema_family_id ?? "")
          : String(item.fingerprint_hash ?? "")
        : registryType === "approved"
          ? String(item.schema_tag_id ?? "")
          : String(item.tag_fingerprint_hash ?? "");
    void loadRegistryDetail(registryType, scope, entryKey);
  }

  async function approveEntry(item: SchemaEntry): Promise<void> {
    const approvalKey = activeScope === "family" ? String(item.fingerprint_hash ?? "") : String(item.tag_fingerprint_hash ?? "");
    if (!approvalKey) {
      return;
    }
    setApprovingHash(approvalKey);
    setError(null);
    try {
      const result = await fetch(`${apiBaseUrl}/api/xml-schemas/${activeScope === "family" ? "approve" : "tags/approve"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(activeScope === "family"
            ? {
                fingerprint_hash: approvalKey,
                schema_family_id: item.suggested_schema_family_id ?? null,
              }
            : {
                tag_fingerprint_hash: approvalKey,
                schema_tag_id: item.suggested_schema_tag_id ?? null,
              }),
          parser_profile: item.suggested_parser_profile ?? null,
          registry_type: activeRegistry === "uploaded" ? "batch" : "observed",
          batch_job_id: activeRegistry === "uploaded" ? uploadedBatch?.batch_job_id ?? null : null,
        }),
      });
      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? `Failed to approve schema ${activeScope}.`);
      }
      await refreshRegistries();
      await loadRegistryDetail(
        "approved",
        activeScope,
        String(
          activeScope === "family"
            ? item.suggested_schema_family_id ?? item.nearest_approved_schema_family_id ?? ""
            : item.suggested_schema_tag_id ?? item.nearest_approved_schema_tag_id ?? ""
        ),
        false
      );
    } catch (approveError) {
      setError(approveError instanceof Error ? approveError.message : "Unknown error");
    } finally {
      setApprovingHash(null);
    }
  }

  return (
    <section className="panel schema-review-panel">
      <div className="section-header">
        <div>
          <span className="eyebrow">Schema review</span>
          <h2>Batch XML Schema Discovery</h2>
          <p className="muted">
            Upload temporary XML batches, compare them with the repo corpus baseline, and promote approved registry
            entries that runtime ingestion can trust.
          </p>
        </div>
        <div className="action-row schema-review-actions">
          <button type="button" className="button-secondary" onClick={() => void refreshRegistries()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh registries"}
          </button>
          <button type="button" onClick={() => void runRepoCorpusScan()} disabled={repoScanning}>
            {repoScanning ? "Scanning..." : "Scan repo corpus"}
          </button>
        </div>
      </div>

      <section className="panel-muted schema-upload-panel">
        <div className="section-header compact">
          <div>
            <h3>Uploaded batch results</h3>
            <p className="muted">
              Select multiple XML files to build a temporary scan job. The uploaded batch is not retained as part of
              ingestion history.
            </p>
          </div>
        </div>
        <div className="schema-upload-grid">
          <div className="field-shell">
            <label htmlFor="schema-batch-files">XML batch files</label>
            <input id="schema-batch-files" type="file" accept=".xml" multiple onChange={onSelectFiles} />
          </div>
          <div className="action-row schema-upload-actions">
            <button type="button" onClick={() => void runUploadedBatchScan()} disabled={uploadScanning || !selectedFiles.length}>
              {uploadScanning ? "Scanning upload..." : "Run uploaded batch scan"}
            </button>
            <div className="schema-upload-meta">
              <strong>{selectedFiles.length}</strong>
              <span>{selectedFiles.length === 1 ? "XML file selected" : "XML files selected"}</span>
            </div>
          </div>
        </div>
        {selectedFiles.length ? (
          <div className="schema-upload-filelist">
            {selectedFiles.slice(0, 8).map((file) => (
              <code key={`${file.name}-${file.size}`} className="baseline-inline-code">
                {file.name}
              </code>
            ))}
            {selectedFiles.length > 8 ? <span className="muted">+ {selectedFiles.length - 8} more files</span> : null}
          </div>
        ) : null}
      </section>

      <section className="panel-muted schema-architecture-panel">
        <div className="section-header compact">
          <div>
            <h3>How discovery becomes runtime lineage</h3>
            <p className="muted">
              This sketch follows one XML example from discovery through approval and into ingestion so family and tag
              registries feel connected instead of isolated screens.
            </p>
          </div>
        </div>
        <div className="schema-architecture-visual">
          {architectureDiagramSvg ? (
            <div
              className="schema-mermaid-shell"
              aria-label="Schema discovery to runtime lineage Mermaid diagram"
              dangerouslySetInnerHTML={{ __html: architectureDiagramSvg }}
            />
          ) : (
            <div className="schema-mermaid-fallback">
              <p className="muted">
                {architectureDiagramError ?? "Rendering Mermaid architecture sketch..."}
              </p>
              <pre className="schema-step-example">{architectureMermaidDefinition.trim()}</pre>
            </div>
          )}
        </div>
        <div className="schema-architecture-track" aria-label="Schema review architecture sketch">
          {architectureSteps.map((step, index) => (
            <div key={step.title} className="schema-architecture-step">
              <div className="schema-step-index">0{index + 1}</div>
              <h4>{step.title}</h4>
              <p>{step.descriptor}</p>
              <code className="schema-step-example">{step.example}</code>
            </div>
          ))}
        </div>
      </section>

      <div className="schema-review-summary">
        <div className="summary-card">
          <strong>Uploaded Files</strong>
          <span>{stats.uploadedFiles}</span>
          <span className="summary-subtext">Temporary browser batch selection</span>
        </div>
        <div className="summary-card">
          <strong>Uploaded Families</strong>
          <span>{stats.uploadedFamilies}</span>
          <span className="summary-subtext">Clustered from the current batch job</span>
        </div>
        <div className="summary-card">
          <strong>Uploaded Tags</strong>
          <span>{stats.uploadedTags}</span>
          <span className="summary-subtext">Reusable descendants extracted from the batch</span>
        </div>
        <div className="summary-card">
          <strong>Repo Families</strong>
          <span>{stats.observedTotal}</span>
          <span className="summary-subtext">
            {stats.observedVariants} variants, {stats.observedUnknown} unknown, {stats.observedApproved} aligned
          </span>
        </div>
        <div className="summary-card">
          <strong>Repo Tags</strong>
          <span>{stats.observedTagTotal}</span>
          <span className="summary-subtext">
            {stats.observedVariantTags} variants, {stats.observedApprovedTags} approved
          </span>
        </div>
        <div className="summary-card">
          <strong>Approved Sets</strong>
          <span>{activeScope === "family" ? stats.approvedTotal : stats.approvedTagTotal}</span>
          <span className="summary-subtext">
            {activeScope === "family" ? "Approved root families" : "Approved reusable tags"}
          </span>
        </div>
        <div className="summary-card">
          <strong>Repo Export</strong>
          <span>{summaryValue(repoSync.export_status ?? "unknown")}</span>
          <span className="summary-subtext">
            {summaryValue(
              repoSync.repo_path ??
                (activeScope === "family"
                  ? "data/schema-registry/approved_schema_registry.json"
                  : "data/schema-registry/approved_tag_schema_registry.json")
            )}
          </span>
        </div>
      </div>

      <section className="panel-muted schema-sync-panel">
        <div className="section-header compact">
          <div>
            <h3>Approved registry repo sync</h3>
            <p className="muted">
              The runtime-approved registry is exported to a checked-in repo artifact so it can be reviewed and pushed
              to GitHub.
            </p>
          </div>
        </div>
        <div className="detail-list">
          <div>
            <strong>Repo path</strong>: <code className="baseline-inline-code">{summaryValue(repoSync.repo_path)}</code>
          </div>
          <div>
            <strong>Status</strong>: {summaryValue(repoSync.export_status)}
          </div>
          <div>
            <strong>Drift detected</strong>: {summaryValue(repoSync.drift_detected)}
          </div>
          <div>
            <strong>Last exported</strong>: {formatDateTime(repoSync.last_exported_at)}
          </div>
          <div>
            <strong>Repo registry version</strong>: {summaryValue(repoSync.repo_registry_version)}
          </div>
        </div>
      </section>

      <div className="review-output-tabs" role="tablist" aria-label="Schema datasets">
        <button
          type="button"
          role="tab"
          className={`review-tab ${activeRegistry === "uploaded" ? "active" : ""}`}
          aria-selected={activeRegistry === "uploaded"}
          onClick={() => setActiveRegistry("uploaded")}
        >
          Uploaded batch results
        </button>
        <button
          type="button"
          role="tab"
          className={`review-tab ${activeRegistry === "observed" ? "active" : ""}`}
          aria-selected={activeRegistry === "observed"}
          onClick={() => setActiveRegistry("observed")}
        >
          Repo corpus registry
        </button>
        <button
          type="button"
          role="tab"
          className={`review-tab ${activeRegistry === "approved" ? "active" : ""}`}
          aria-selected={activeRegistry === "approved"}
          onClick={() => setActiveRegistry("approved")}
        >
          Approved registry
        </button>
      </div>

      <div className="review-output-tabs" role="tablist" aria-label="Schema scopes">
        <button
          type="button"
          role="tab"
          className={`review-tab ${activeScope === "family" ? "active" : ""}`}
          aria-selected={activeScope === "family"}
          onClick={() => {
            setActiveScope("family");
            setDetail(null);
          }}
        >
          Root family registry
        </button>
        <button
          type="button"
          role="tab"
          className={`review-tab ${activeScope === "tag" ? "active" : ""}`}
          aria-selected={activeScope === "tag"}
          onClick={() => {
            setActiveScope("tag");
            setDetail(null);
          }}
        >
          Global tag registry
        </button>
      </div>

      <div className="review-output-tabs" role="tablist" aria-label="Schema presentations">
        <button
          type="button"
          role="tab"
          className={`review-tab ${presentationMode === "human" ? "active" : ""}`}
          aria-selected={presentationMode === "human"}
          onClick={() => setPresentationMode("human")}
        >
          Human-readable view
        </button>
        <button
          type="button"
          role="tab"
          className={`review-tab ${presentationMode === "raw" ? "active" : ""}`}
          aria-selected={presentationMode === "raw"}
          onClick={() => setPresentationMode("raw")}
        >
          Raw JSON view
        </button>
      </div>

      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
      {infoMessage ? <p className="schema-detail-explainer">{infoMessage}</p> : null}

      <div className="schema-review-grid">
        {presentationMode === "human" ? (
          <>
            <div className="schema-table-wrap">
              {!activeEntries.length ? (
                <div className="empty-state">
                  {activeRegistry === "uploaded"
                    ? `No uploaded batch ${activeScope === "family" ? "families" : "tags"} yet. Select XML files above and run an uploaded batch scan.`
                    : activeRegistry === "observed"
                      ? `No repo corpus ${activeScope === "family" ? "schema families" : "schema tags"} yet. Run the repo scan to build the baseline registry.`
                      : `No approved schema ${activeScope === "family" ? "families" : "tags"} were loaded.`}
                </div>
              ) : (
                <>
                  <p className="schema-review-legend">
                    {activeScope === "family" ? (
                      <>
                        <strong>Family name</strong> is the matched or suggested registry id. The line below it is the
                        <strong> structural fingerprint</strong> built from the root tag, outputclass, namespaces, and
                        direct child tags. <strong>VARIANT</strong> means the family matched an approved root but drifted
                        from the preferred child structure.
                      </>
                    ) : (
                      <>
                        <strong>Tag id</strong> names the reusable descendant unit. Its fingerprint stays stable across
                        contexts like `section/title` and `table-reference/title`, while the detail panel records the
                        parent and path distributions that preserve traceability.
                      </>
                    )}
                  </p>
                  <table className="baseline-table schema-table">
                    <thead>
                      <tr>
                        <th>{activeScope === "family" ? "Schema family" : "Schema tag"}</th>
                        <th>Status</th>
                        <th>{activeScope === "family" ? "Root tag" : "Tag name"}</th>
                        <th>{activeScope === "family" ? "Outputclass" : "Parent contexts"}</th>
                        <th>{activeScope === "family" ? "Child signature" : "Path coverage"}</th>
                        <th>{activeScope === "family" ? "Files" : "Occurrences"}</th>
                        <th>Examples</th>
                        <th>Version</th>
                        <th>Registry</th>
                        <th>Last seen</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeEntries.map((item) => {
                        const key =
                          activeScope === "family"
                            ? activeRegistry === "approved"
                              ? String(item.schema_family_id ?? "")
                              : String(item.fingerprint_hash ?? "")
                            : activeRegistry === "approved"
                              ? String(item.schema_tag_id ?? "")
                              : String(item.tag_fingerprint_hash ?? "");
                        const entryLabel =
                          activeScope === "family"
                            ? activeRegistry === "approved"
                              ? String(item.schema_family_id ?? "n/a")
                              : String(item.suggested_schema_family_id ?? item.nearest_approved_schema_family_id ?? "unmapped")
                            : activeRegistry === "approved"
                              ? String(item.schema_tag_id ?? "n/a")
                              : String(item.suggested_schema_tag_id ?? item.nearest_approved_schema_tag_id ?? "unmapped");
                        const status = activeRegistry === "approved" ? "approved" : String(item.status ?? "unknown").toLowerCase();
                        const identifier =
                          activeScope === "family"
                            ? activeRegistry === "approved"
                              ? item.schema_family_id
                              : item.fingerprint_hash
                            : activeRegistry === "approved"
                              ? item.schema_tag_id
                              : item.tag_fingerprint_hash;
                        const lastSeen =
                          item.last_seen ??
                          (activeRegistry === "uploaded"
                            ? uploadedBatch?.generated_at
                            : activeRegistry === "observed"
                              ? repoObserved?.generated_at
                              : approved?.generated_at) ??
                          null;
                        const registryMarker =
                          activeRegistry === "uploaded"
                            ? uploadedBatch?.batch_job_id
                            : activeRegistry === "observed"
                              ? repoObserved?.registry_version
                              : approved?.registry_version;

                        return (
                          <tr key={key}>
                            <td>
                              <button
                                type="button"
                                className="schema-row-button"
                                onClick={() => openEntryDetail(activeRegistry, activeScope, item)}
                              >
                                <span className="baseline-cell-title">{entryLabel}</span>
                                <span className="baseline-cell-id">
                                  {activeRegistry === "approved" ? (
                                    identifier
                                  ) : (
                                    <>
                                      <span className="schema-fingerprint-prefix">
                                        {activeScope === "family" ? "Structural fingerprint (SHA-1)" : "Tag fingerprint (SHA-1)"}
                                      </span>
                                      {identifier}
                                    </>
                                  )}
                                </span>
                              </button>
                            </td>
                            <td>
                              <span className={`status ${statusTone(status)}`}>{status}</span>
                            </td>
                            <td>{summaryValue(activeScope === "family" ? item.root_tag ?? item.match_rules?.root_tags : item.tag_name ?? item.match_rules?.tag_names)}</td>
                            <td className="baseline-snippet">
                              {summaryValue(
                                activeScope === "family"
                                  ? item.outputclass ?? item.match_rules?.outputclass_hints
                                  : (item.common_parent_tags ?? []).map((parent: { tag?: string }) => parent.tag).slice(0, 3)
                              )}
                            </td>
                            <td className="baseline-snippet">
                              {summaryValue(
                                activeScope === "family"
                                  ? item.child_tag_signature ?? item.direct_child_tags
                                  : (item.common_paths ?? []).map((path: { path?: string }) => path.path).slice(0, 2)
                              )}
                            </td>
                            <td>{summaryValue(activeScope === "family" ? item.file_count ?? item.approved_fingerprint_hashes?.length : item.occurrence_count ?? item.approved_tag_fingerprint_hashes?.length)}</td>
                            <td className="baseline-snippet">
                              {summaryValue(
                                activeScope === "family"
                                  ? item.example_files?.slice?.(0, 2) ?? []
                                  : item.example_paths?.slice?.(0, 2) ?? item.example_texts?.slice?.(0, 1) ?? []
                              )}
                            </td>
                            <td>{summaryValue(activeScope === "family" ? item.schema_family_version : item.schema_tag_version)}</td>
                            <td>{summaryValue(registryMarker)}</td>
                            <td>{formatDateTime(lastSeen)}</td>
                            <td>
                              {activeRegistry !== "approved" && status !== "approved" ? (
                                <button
                                  type="button"
                                  className="button-secondary"
                                  onClick={() => void approveEntry(item)}
                                  disabled={approvingHash === identifier}
                                >
                                  {approvingHash === identifier ? "Approving..." : "Approve"}
                                </button>
                              ) : (
                                <span className="muted">View detail</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
            </div>

            <aside className="panel-muted schema-detail-panel">
              <h3>{activeScope === "family" ? "Schema family detail" : "Schema tag detail"}</h3>
              {!detail ? (
                <p className="muted">
                  Select a {activeScope === "family" ? "schema family" : "schema tag"} row to inspect its normalized
                  fingerprint, context summaries, and samples.
                </p>
              ) : (
                <>
                  <p className="schema-detail-explainer">
                    {detail.scope === "family"
                      ? "Family detail explains the approved or suggested registry id alongside the raw root fingerprint that runtime matching relies on."
                      : "Tag detail separates reusable tag identity from its observed contexts so the same tag can still be traced to section, table, and page-level use."}
                  </p>
                  <div className="detail-list">
                    <div>
                      <strong>Dataset</strong>:{" "}
                      {detail.registry_type === "uploaded"
                        ? "uploaded batch"
                        : detail.registry_type === "observed"
                          ? "repo corpus registry"
                          : "approved registry"}
                    </div>
                    <div>
                      <strong>{detail.registry_type === "uploaded" ? "Batch job" : "Registry version"}</strong>:{" "}
                      {detail.registry_version ?? "n/a"}
                    </div>
                    <div>
                      <strong>{detail.scope === "family" ? "Registry id" : "Tag id"}</strong>:{" "}
                      {summaryValue(
                        detail.scope === "family"
                          ? detailItem?.schema_family_id ?? detailItem?.suggested_schema_family_id
                          : detailItem?.schema_tag_id ?? detailItem?.suggested_schema_tag_id
                      )}
                    </div>
                    <div>
                      <strong>Nearest approved</strong>:{" "}
                      {summaryValue(
                        detail.scope === "family"
                          ? detailItem?.nearest_approved_schema_family_id
                          : detailItem?.nearest_approved_schema_tag_id
                      )}
                    </div>
                    <div>
                      <strong>Parser profile</strong>: {summaryValue(detailItem?.parser_profile ?? detailItem?.suggested_parser_profile)}
                    </div>
                    <div>
                      <strong>{detail.scope === "family" ? "Structural fingerprint (SHA-1)" : "Tag fingerprint (SHA-1)"}</strong>:{" "}
                      {summaryValue(detail.scope === "family" ? detailItem?.fingerprint_hash : detailItem?.tag_fingerprint_hash)}
                    </div>
                    {detail.scope === "family" ? (
                      <>
                        <div>
                          <strong>Tree nodes</strong>: {summaryValue(detailItem?.tree_node_count)}
                        </div>
                        <div>
                          <strong>Max depth</strong>: {summaryValue(detailItem?.max_depth)}
                        </div>
                      </>
                    ) : (
                      <>
                        <div>
                          <strong>Occurrences</strong>: {summaryValue(detailItem?.occurrence_count)}
                        </div>
                        <div>
                          <strong>Distinct files</strong>: {summaryValue(detailItem?.file_count)}
                        </div>
                      </>
                    )}
                  </div>

                  {detail.scope === "family" && (detailAllElementTags.length || detailCommonPaths.length || detailElementTagCounts.length) ? (
                    <details className="detail-disclosure" open>
                      <summary>Full-tree element summary</summary>
                      {detailAllElementTags.length ? (
                        <div className="schema-tag-cloud">
                          {detailAllElementTags.map((tag) => (
                            <code key={tag} className="baseline-inline-code">
                              {tag}
                            </code>
                          ))}
                        </div>
                      ) : (
                        <p className="muted">No descendant element summary recorded.</p>
                      )}
                      {detailLeafTags.length ? (
                        <p className="schema-detail-note">Leaf tags: {detailLeafTags.slice(0, 12).join(", ")}</p>
                      ) : null}
                    </details>
                  ) : null}

                  {detail.scope === "family" && detailElementTagCounts.length ? (
                    <details className="detail-disclosure" open>
                      <summary>Element counts</summary>
                      <div className="detail-list">
                        {detailElementTagCounts.slice(0, 20).map(([tag, count]) => (
                          <div key={tag}>
                            <strong>{tag}</strong>: {count}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detailCommonPaths.length ? (
                    <details className="detail-disclosure" open>
                      <summary>{detail.scope === "family" ? "Common XML paths" : "Observed context paths"}</summary>
                      <div className="detail-list">
                        {detailCommonPaths.map((item) => (
                          <div key={`${item.path}-${item.count}`}>
                            <code className="baseline-inline-code">{item.path}</code>: {item.count}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detail.scope === "tag" && detailCommonParentTags.length ? (
                    <details className="detail-disclosure" open>
                      <summary>Parent context profiles</summary>
                      <div className="detail-list">
                        {detailCommonParentTags.map((item) => (
                          <div key={`${item.label}-${item.count}`}>
                            <strong>{item.label}</strong>: {item.count}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detail.scope === "tag" && detailCommonStructuralParents.length ? (
                    <details className="detail-disclosure">
                      <summary>Nearest structural parents</summary>
                      <div className="detail-list">
                        {detailCommonStructuralParents.map((item) => (
                          <div key={`${item.label}-${item.count}`}>
                            <strong>{item.label}</strong>: {item.count}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detailAttributeCounts.length ? (
                    <details className="detail-disclosure">
                      <summary>Attribute usage</summary>
                      <div className="detail-list">
                        {detailAttributeCounts.slice(0, 20).map(([attribute, count]) => (
                          <div key={attribute}>
                            <strong>{attribute}</strong>: {count}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detail.scope === "family" && detailHighlightedPaths.length ? (
                    <details className="detail-disclosure">
                      <summary>Highlighted tag paths</summary>
                      <div className="detail-list">
                        {detailHighlightedPaths.map(([tag, paths]) => (
                          <div key={tag}>
                            <strong>{tag}</strong>: {paths}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {!!(detailItem?.match_reasons ?? []).length && (
                    <details className="detail-disclosure" open>
                      <summary>Drift and match reasons</summary>
                      <ul className="issue-list">
                        {(detailItem?.match_reasons ?? []).map((reason: string) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {(detailItem?.files ?? detailItem?.example_files)?.length ? (
                    <details className="detail-disclosure" open>
                      <summary>Sample files</summary>
                      <div className="detail-list">
                        {(detailItem?.files ?? detailItem?.example_files ?? []).slice(0, 10).map((file: string) => (
                          <div key={file}>
                            <code className="baseline-inline-code">{file}</code>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detail.scope === "tag" && detailExamplePaths.length ? (
                    <details className="detail-disclosure">
                      <summary>Example paths</summary>
                      <div className="detail-list">
                        {detailExamplePaths.map((path) => (
                          <div key={path}>
                            <code className="baseline-inline-code">{path}</code>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  {detail.scope === "tag" && detailExampleTexts.length ? (
                    <details className="detail-disclosure">
                      <summary>Example text</summary>
                      <div className="detail-list">
                        {detailExampleTexts.map((text) => (
                          <div key={text}>{text}</div>
                        ))}
                      </div>
                    </details>
                  ) : null}

                  <details className="detail-disclosure">
                    <summary>{detail.scope === "family" ? "Normalized fingerprint JSON" : "Approved tag/context JSON"}</summary>
                    <pre>{JSON.stringify(detailItem, null, 2)}</pre>
                  </details>
                </>
              )}
            </aside>
          </>
        ) : (
          <>
            <section className="panel-muted schema-detail-panel">
              <h3>{activeRegistry === "approved" ? "Approved registry JSON" : "Active registry JSON"}</h3>
              <p className="muted">
                Raw view mirrors the persisted registry artifact so reviewers can compare the human-friendly table with the
                exact JSON that runtime uses.
              </p>
              <pre>{JSON.stringify(activePayload ? (activeScope === "family" ? { ...activePayload, tags: [] } : { ...activePayload, families: [] }) : {}, null, 2)}</pre>
            </section>
            <aside className="panel-muted schema-detail-panel">
              <h3>Selected item JSON</h3>
              {!detail ? (
                <p className="muted">Select a row in the human-readable view to inspect a single family or tag payload here.</p>
              ) : (
                <pre>{JSON.stringify(detailItem, null, 2)}</pre>
              )}
            </aside>
          </>
        )}
      </div>

      {uploadedBatch?.scan_errors?.length ? (
        <details className="detail-disclosure">
          <summary>Uploaded batch scan errors ({uploadedBatch.scan_errors.length})</summary>
          <div className="detail-list">
            {uploadedBatch.scan_errors.map((item, index) => (
              <div key={`${item.file ?? "upload-scan-error"}-${index}`}>
                <strong>{item.file ?? "unknown file"}</strong>: {item.error ?? "Unknown parse error"}
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {repoObserved?.scan_errors?.length ? (
        <details className="detail-disclosure">
          <summary>Repo corpus scan errors ({repoObserved.scan_errors.length})</summary>
          <div className="detail-list">
            {repoObserved.scan_errors.map((item, index) => (
              <div key={`${item.file ?? "scan-error"}-${index}`}>
                <strong>{item.file ?? "unknown file"}</strong>: {item.error ?? "Unknown parse error"}
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
