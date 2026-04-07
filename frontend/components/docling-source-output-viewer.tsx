"use client";

import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react";

export type DoclingViewBlock = {
  block_id: string;
  page: number;
  bbox: number[];
  block_type: string;
  text: string;
  table_id?: string | null;
  section_hint?: string | null;
  heading_level?: number | null;
  source_strategy?: string;
  metadata?: Record<string, unknown>;
};

export type DoclingViewTable = {
  table_id: string;
  rows: string[][];
  headers_present: boolean;
  related_block_id?: string | null;
  bbox?: number[];
  metadata?: Record<string, unknown>;
};

export type DoclingViewPageIndex = {
  page: number;
  block_count: number;
  table_count: number;
  block_types: string[];
  block_ids: string[];
  table_ids: string[];
};

export type DoclingViewPayload = {
  blocks: DoclingViewBlock[];
  tables: DoclingViewTable[];
  strategy?: {
    runtime_strategy?: string;
    runtime_mode?: string;
    extraction_profile?: string;
    notes?: string[];
  } | null;
  page_index: DoclingViewPageIndex[];
};

type DoclingBlockStyleSummary = {
  source?: string;
  font_name?: string | null;
  font_size_pt?: number | null;
  text_color_rgb?: number[] | null;
  text_color_hex?: string | null;
  is_bold?: boolean;
  is_italic?: boolean;
  confidence?: number | null;
  span_count?: number | null;
};

type DoclingBlockStyleSpan = {
  start: number;
  end: number;
  bbox?: number[];
  font_name?: string | null;
  font_size_pt?: number | null;
  text_color_rgb?: number[] | null;
  text_color_hex?: string | null;
  is_bold?: boolean;
  is_italic?: boolean;
};

function formatBbox(bbox: number[] | undefined): string {
  if (!bbox?.length) {
    return "n/a";
  }
  return bbox.map((value) => Number(value).toFixed(2)).join(", ");
}

function prettyBlockType(blockType: string): string {
  return blockType.replace(/_/g, " ");
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

function asBoolean(value: unknown): boolean {
  return value === true;
}

function asRgb(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 3) {
    return null;
  }
  const parsed = value.map((entry) => asNumber(entry));
  if (parsed.some((entry) => entry === null)) {
    return null;
  }
  return parsed.map((entry) => Number(entry));
}

function getBlockStyleSummary(block: DoclingViewBlock): DoclingBlockStyleSummary | null {
  const metadata = asRecord(block.metadata);
  const summary = asRecord(metadata?.style_summary);
  if (!summary) {
    return null;
  }
  return {
    source: typeof summary.source === "string" ? summary.source : undefined,
    font_name: typeof summary.font_name === "string" ? summary.font_name : null,
    font_size_pt: asNumber(summary.font_size_pt),
    text_color_rgb: asRgb(summary.text_color_rgb),
    text_color_hex: typeof summary.text_color_hex === "string" ? summary.text_color_hex : null,
    is_bold: asBoolean(summary.is_bold),
    is_italic: asBoolean(summary.is_italic),
    confidence: asNumber(summary.confidence),
    span_count: asNumber(summary.span_count),
  };
}

function getBlockStyleSpans(block: DoclingViewBlock): DoclingBlockStyleSpan[] {
  const metadata = asRecord(block.metadata);
  const styleSpans = metadata?.style_spans;
  if (!Array.isArray(styleSpans)) {
    return [];
  }
  const parsed: DoclingBlockStyleSpan[] = [];
  styleSpans.forEach((entry) => {
    const span = asRecord(entry);
    if (!span) {
      return;
    }
    const start = asNumber(span.start);
    const end = asNumber(span.end);
    if (start === null || end === null || end <= start) {
      return;
    }
    parsed.push({
      start,
      end,
      bbox: Array.isArray(span.bbox) ? span.bbox.map((value) => Number(value)) : undefined,
      font_name: typeof span.font_name === "string" ? span.font_name : null,
      font_size_pt: asNumber(span.font_size_pt),
      text_color_rgb: asRgb(span.text_color_rgb),
      text_color_hex: typeof span.text_color_hex === "string" ? span.text_color_hex : null,
      is_bold: asBoolean(span.is_bold),
      is_italic: asBoolean(span.is_italic),
    });
  });
  return parsed.sort((left, right) => left.start - right.start);
}

function hasEnhancedStyleData(block: DoclingViewBlock): boolean {
  return Boolean(getBlockStyleSummary(block) || getBlockStyleSpans(block).length);
}

function styleSpanCss(span: DoclingBlockStyleSpan): CSSProperties {
  const css: CSSProperties = {};
  if (span.text_color_hex) {
    css.color = span.text_color_hex;
  }
  if (span.font_name) {
    css.fontFamily = `"${span.font_name}", "Segoe UI", sans-serif`;
  }
  if (span.font_size_pt) {
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

function renderStyledBlockText(block: DoclingViewBlock) {
  const styleSpans = getBlockStyleSpans(block);
  if (!styleSpans.length) {
    return <div className="docling-block-text docling-enhanced-block-text">{block.text}</div>;
  }

  const fragments: ReactNode[] = [];
  let cursor = 0;
  styleSpans.forEach((span, index) => {
    const start = Math.max(cursor, span.start);
    const end = Math.min(block.text.length, span.end);
    if (start > cursor) {
      fragments.push(<span key={`${block.block_id}-plain-${index}-${cursor}`}>{block.text.slice(cursor, start)}</span>);
    }
    if (end > start) {
      fragments.push(
        <span key={`${block.block_id}-styled-${index}-${start}`} className="docling-inline-style-span" style={styleSpanCss(span)}>
          {block.text.slice(start, end)}
        </span>
      );
    }
    cursor = Math.max(cursor, end);
  });
  if (cursor < block.text.length) {
    fragments.push(<span key={`${block.block_id}-plain-tail-${cursor}`}>{block.text.slice(cursor)}</span>);
  }
  return <div className="docling-block-text docling-enhanced-block-text">{fragments}</div>;
}

export function DoclingSourceOutputViewer({
  file,
  doclingView,
  onRelinkPdf,
  onRunDocling,
  canRunDocling = false,
  isRunningDocling = false,
  doclingStatusMessage = null,
  doclingError = null,
}: {
  file: File | null;
  doclingView: DoclingViewPayload | null;
  onRelinkPdf?: () => void;
  onRunDocling?: () => void;
  canRunDocling?: boolean;
  isRunningDocling?: boolean;
  doclingStatusMessage?: string | null;
  doclingError?: string | null;
}) {
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [activeOutputTab, setActiveOutputTab] = useState<"docling" | "enhanced">("docling");
  const pdfUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  const hasViewerShell = Boolean(file || doclingView);

  useEffect(() => {
    return () => {
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [pdfUrl]);

  useEffect(() => {
    const firstBlock = doclingView?.blocks[0] ?? null;
    if (!firstBlock) {
      setSelectedBlockId(null);
      setSelectedPage(null);
      return;
    }
    setSelectedBlockId((current) => (current && doclingView?.blocks.some((block) => block.block_id === current) ? current : firstBlock.block_id));
    setSelectedPage((current) => current ?? firstBlock.page);
  }, [doclingView]);

  const selectedBlock = useMemo(
    () => doclingView?.blocks.find((block) => block.block_id === selectedBlockId) ?? null,
    [doclingView, selectedBlockId]
  );

  const selectedPageNumber = selectedBlock?.page ?? selectedPage ?? doclingView?.page_index[0]?.page ?? null;
  const iframeSrc = useMemo(() => {
    if (!pdfUrl) {
      return null;
    }
    return selectedPageNumber ? `${pdfUrl}#page=${selectedPageNumber}` : pdfUrl;
  }, [pdfUrl, selectedPageNumber]);

  const pageGroups = useMemo(() => {
    const blocksByPage = new Map<number, DoclingViewBlock[]>();
    const tablesByRelatedBlock = new Map<string, DoclingViewTable[]>();
    const tablesByPage = new Map<number, DoclingViewTable[]>();

    doclingView?.blocks.forEach((block) => {
      const pageBlocks = blocksByPage.get(block.page) ?? [];
      pageBlocks.push(block);
      blocksByPage.set(block.page, pageBlocks);
    });

    doclingView?.tables.forEach((table) => {
      const relatedBlockId = String(table.related_block_id ?? "");
      if (relatedBlockId) {
        const relatedTables = tablesByRelatedBlock.get(relatedBlockId) ?? [];
        relatedTables.push(table);
        tablesByRelatedBlock.set(relatedBlockId, relatedTables);
        return;
      }
      const page = Number(table.metadata?.page ?? 0);
      const pageTables = tablesByPage.get(page) ?? [];
      pageTables.push(table);
      tablesByPage.set(page, pageTables);
    });

    return (doclingView?.page_index ?? []).map((pageEntry) => ({
      ...pageEntry,
      blocks: blocksByPage.get(pageEntry.page) ?? [],
      looseTables: tablesByPage.get(pageEntry.page) ?? [],
      tablesByRelatedBlock,
    }));
  }, [doclingView]);

  const hasEnhancedTabData = useMemo(() => doclingView?.blocks.some((block) => hasEnhancedStyleData(block)) ?? false, [doclingView]);

  return (
    <section className="panel-muted docling-reader-panel">
      <div className="section-header compact">
        <div>
          <span className="eyebrow">Extraction inspection</span>
          <h3>Docling Source/Output Viewer</h3>
          <p className="muted">
            Compare the rendered PDF source with the Docling-derived block stream. Selection is block-led today so the
            same `block_id`, page, and bbox contract can power a later overlay layer.
          </p>
        </div>
        {onRunDocling ? (
          <button type="button" className="button-secondary" onClick={onRunDocling} disabled={!canRunDocling}>
            {isRunningDocling ? "Running Docling..." : "Run Docling"}
          </button>
        ) : null}
      </div>

      {!hasViewerShell ? (
        <div className="empty-state">Select a PDF and run Docling to inspect the rendered source beside the extracted output. Add XML as well if you want the full paired validation flow.</div>
      ) : (
        <>
          <div className="docling-reader-meta">
            <div>
              <strong>Runtime strategy</strong>: {doclingView?.strategy?.runtime_strategy ?? "waiting for validation"}
            </div>
            <div>
              <strong>Runtime mode</strong>: {doclingView?.strategy?.runtime_mode ?? "waiting for validation"}
            </div>
            <div>
              <strong>Blocks</strong>: {doclingView?.blocks.length ?? 0}
            </div>
            <div>
              <strong>Tables</strong>: {doclingView?.tables.length ?? 0}
            </div>
            <div>
              <strong>Pages</strong>: {doclingView?.page_index.length ?? 0}
            </div>
            <div>
              <strong>Selected page</strong>: {selectedPageNumber ?? "n/a"}
            </div>
          </div>

          {doclingView?.page_index.length ? (
            <div className="docling-page-chip-row" aria-label="Docling pages">
              {doclingView.page_index.map((pageEntry) => {
                const isActive = pageEntry.page === selectedPageNumber;
                return (
                  <button
                    key={`docling-page-${pageEntry.page}`}
                    type="button"
                    className={`button-secondary docling-page-chip ${isActive ? "active" : ""}`}
                    onClick={() => {
                      setSelectedPage(pageEntry.page);
                      const firstPageBlock = doclingView.blocks.find((block) => block.page === pageEntry.page);
                      if (firstPageBlock) {
                        setSelectedBlockId(firstPageBlock.block_id);
                      }
                    }}
                  >
                    Page {pageEntry.page}
                  </button>
                );
              })}
            </div>
          ) : null}

          <div className="xml-reader-grid">
            <section className="xml-reader-pane" aria-label="PDF source preview">
              <div className="xml-reader-pane-header">
                <h4>Source</h4>
                <p className="muted">
                  The left pane stays iframe-based for now. Selecting a Docling block jumps to its page and preserves
                  bbox metadata for a later overlay upgrade.
                </p>
              </div>
              <div className="docling-source-meta">
                <div>
                  <strong>Active PDF</strong>:{" "}
                  {file ? <code className="baseline-inline-code">{file.name}</code> : <span className="muted">No local PDF attached</span>}
                </div>
                <div>
                  <strong>Selected block</strong>: {selectedBlock?.block_id ?? "n/a"}
                </div>
                <div>
                  <strong>Selected bbox</strong>: <code className="baseline-inline-code">{formatBbox(selectedBlock?.bbox)}</code>
                </div>
              </div>
              <div className="pdf-reader-frame-shell">
                {iframeSrc ? (
                  <iframe className="pdf-frame" src={iframeSrc} title="Docling source PDF preview" />
                ) : (
                  <div className="empty-state">
                    The Docling output is available, but the PDF source is only viewable from this browser session.
                    {onRelinkPdf ? (
                      <>
                        {" "}
                        <button type="button" className="button-secondary" onClick={onRelinkPdf}>
                          Relink PDF
                        </button>
                      </>
                    ) : null}
                  </div>
                )}
              </div>
            </section>

            <section className="xml-reader-pane" aria-label="Docling output preview">
              <div className="xml-reader-pane-header">
                <h4>{activeOutputTab === "enhanced" ? "Enhanced output" : "Docling output"}</h4>
                <p className="muted">
                  {activeOutputTab === "enhanced"
                    ? "The enhanced tab re-renders the same Docling blocks with PyMuPDF-derived span styling for color, font, bold, and italic."
                    : "Blocks are grouped by page and remain selectable by `block_id`, page, and bbox to match the PDF evidence contract."}
                </p>
              </div>
              {isRunningDocling || doclingStatusMessage ? (
                <div className="alert alert-info docling-status-banner" role="status" aria-live="polite">
                  {isRunningDocling ? "Docling is validating this document and assembling the output view..." : doclingStatusMessage}
                </div>
              ) : null}
              {doclingError ? (
                <div className="alert alert-error docling-status-banner" role="alert">
                  {doclingError}
                </div>
              ) : null}
              <div className="docling-output-tabs" role="tablist" aria-label="Docling output views">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeOutputTab === "docling"}
                  className={`button-secondary docling-output-tab ${activeOutputTab === "docling" ? "active" : ""}`}
                  onClick={() => setActiveOutputTab("docling")}
                >
                  Docling output
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeOutputTab === "enhanced"}
                  className={`button-secondary docling-output-tab ${activeOutputTab === "enhanced" ? "active" : ""}`}
                  onClick={() => setActiveOutputTab("enhanced")}
                >
                  Enhanced (PyMuPDF)
                </button>
              </div>
              {activeOutputTab === "enhanced" && !hasEnhancedTabData ? (
                <div className="empty-state">
                  PyMuPDF style metadata is not available for this document yet. The raw Docling tab still shows the
                  extracted block stream.
                </div>
              ) : null}
              <div className="xml-reader-rows docling-output-rows">
                {!doclingView ? (
                  <div className="empty-state">
                    Run validation or load a retained workspace to populate the Docling output. The split shell is
                    visible now so the PDF source can stay side by side with the extraction results once they arrive.
                  </div>
                ) : (
                  pageGroups.map((pageEntry) => (
                    <section key={`docling-page-group-${pageEntry.page}`} className="docling-page-group">
                      <div className="docling-page-group-header">
                        <strong>Page {pageEntry.page}</strong>
                        <div className="docling-page-group-badges">
                          <span className="xml-reader-badge">{pageEntry.block_count} blocks</span>
                          <span className="xml-reader-badge">{pageEntry.table_count} tables</span>
                        </div>
                      </div>
                      {pageEntry.blocks.map((block) => {
                        const isSelected = selectedBlockId === block.block_id;
                        const relatedTables = pageEntry.tablesByRelatedBlock.get(block.block_id) ?? [];
                        const styleSummary = getBlockStyleSummary(block);
                        return (
                          <div key={block.block_id} className="docling-block-stack">
                            <button
                              type="button"
                              className={`docling-block-card ${isSelected ? "is-selected" : ""}`}
                              onClick={() => {
                                setSelectedBlockId(block.block_id);
                                setSelectedPage(block.page);
                              }}
                            >
                              <div className="docling-block-header">
                                <strong>{block.section_hint || prettyBlockType(block.block_type)}</strong>
                                <div className="docling-block-badges">
                                  <span className="xml-reader-badge xml-reader-badge-accent">{prettyBlockType(block.block_type)}</span>
                                  <span className="xml-reader-badge">p.{block.page}</span>
                                  {block.heading_level ? <span className="xml-reader-badge">h{block.heading_level}</span> : null}
                                  {block.table_id ? <span className="xml-reader-badge">table-linked</span> : null}
                                </div>
                              </div>
                              {activeOutputTab === "enhanced" ? (
                                <>
                                  {styleSummary ? (
                                    <div className="docling-style-summary">
                                      {styleSummary.text_color_hex ? (
                                        <span className="docling-style-chip">
                                          <span
                                            className="docling-color-swatch"
                                            style={{ backgroundColor: styleSummary.text_color_hex }}
                                            aria-hidden="true"
                                          />
                                          {styleSummary.text_color_hex}
                                        </span>
                                      ) : null}
                                      {styleSummary.font_name ? <span className="docling-style-chip">{styleSummary.font_name}</span> : null}
                                      {styleSummary.font_size_pt ? (
                                        <span className="docling-style-chip">{styleSummary.font_size_pt.toFixed(1)}pt</span>
                                      ) : null}
                                      {styleSummary.is_bold ? <span className="docling-style-chip">bold</span> : null}
                                      {styleSummary.is_italic ? <span className="docling-style-chip">italic</span> : null}
                                      {styleSummary.confidence ? (
                                        <span className="docling-style-chip">match {Math.round(styleSummary.confidence * 100)}%</span>
                                      ) : null}
                                    </div>
                                  ) : (
                                    <div className="docling-style-empty muted">
                                      No PyMuPDF styling matched this block, so it is shown as plain text.
                                    </div>
                                  )}
                                  {renderStyledBlockText(block)}
                                </>
                              ) : (
                                <div className="docling-block-text">{block.text}</div>
                              )}
                              <div className="docling-block-meta">
                                <code className="baseline-inline-code">{block.block_id}</code>
                                <code className="baseline-inline-code">{formatBbox(block.bbox)}</code>
                              </div>
                            </button>

                            {relatedTables.map((table) => (
                              <details key={table.table_id} className="docling-table-card">
                                <summary>
                                  <span>Table {table.table_id}</span>
                                  <span className="muted">{table.rows.length} rows</span>
                                </summary>
                                <div className="docling-table-shell">
                                  <table className="docling-table-grid">
                                    <tbody>
                                      {table.rows.map((row, rowIndex) => (
                                        <tr key={`${table.table_id}-row-${rowIndex}`}>
                                          {row.map((cell, cellIndex) => {
                                            const CellTag = table.headers_present && rowIndex === 0 ? "th" : "td";
                                            return <CellTag key={`${table.table_id}-cell-${rowIndex}-${cellIndex}`}>{cell}</CellTag>;
                                          })}
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </details>
                            ))}
                          </div>
                        );
                      })}
                      {pageEntry.looseTables.map((table) => (
                        <details key={`loose-${table.table_id}`} className="docling-table-card">
                          <summary>
                            <span>Table {table.table_id}</span>
                            <span className="muted">{table.rows.length} rows</span>
                          </summary>
                          <div className="docling-table-shell">
                            <table className="docling-table-grid">
                              <tbody>
                                {table.rows.map((row, rowIndex) => (
                                  <tr key={`${table.table_id}-loose-row-${rowIndex}`}>
                                    {row.map((cell, cellIndex) => {
                                      const CellTag = table.headers_present && rowIndex === 0 ? "th" : "td";
                                      return <CellTag key={`${table.table_id}-loose-cell-${rowIndex}-${cellIndex}`}>{cell}</CellTag>;
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </details>
                      ))}
                    </section>
                  ))
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </section>
  );
}
