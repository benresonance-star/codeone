"use client";

import { useEffect, useMemo } from "react";

export function PdfUploadViewer({ file }: { file: File | null }) {
  const pdfUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => {
    return () => {
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [pdfUrl]);

  return (
    <section className="panel-muted pdf-reader-panel">
      <div className="section-header compact">
        <div>
          <span className="eyebrow">Session-only viewer</span>
          <h3>PDF Reader</h3>
          <p className="muted">
            Preview the currently selected PDF from validate pair before running ingestion. The embedded reader stays
            local to this browser session.
          </p>
        </div>
      </div>

      {!file ? (
        <div className="empty-state">Select a PDF document above to preview the original file before validation.</div>
      ) : (
        <>
          <div className="pdf-reader-meta">
            <div>
              <strong>Active file</strong>: <code className="baseline-inline-code">{file.name}</code>
            </div>
            <div>
              <strong>Size</strong>: {(file.size / 1024).toFixed(file.size >= 1024 ? 1 : 0)} KB
            </div>
            <div>
              <strong>Type</strong>: {file.type || "application/pdf"}
            </div>
          </div>

          <div className="pdf-reader-frame-shell">
            {pdfUrl ? <iframe className="pdf-frame" src={pdfUrl} title="Embedded PDF reader" /> : null}
          </div>
        </>
      )}
    </section>
  );
}
