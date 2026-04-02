"use client";

import { FormEvent, useMemo, useState } from "react";

import { ValidationViewer } from "../components/validation-viewer";

type IngestionResponse = {
  summary: {
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
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [xmlFile, setXmlFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<IngestionResponse | null>(null);

  const summaryText = useMemo(() => {
    if (!response) {
      return "Upload a PDF and XML pair to validate the linked NCC representations.";
    }
    return `XML: ${response.summary.xml_status} | PDF: ${response.summary.pdf_status} | Can Progress: ${response.summary.can_progress}`;
  }, [response]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!pdfFile || !xmlFile) {
      setError("Choose both a PDF and an XML file.");
      return;
    }

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("pdf", pdfFile);
    formData.append("xml", xmlFile);

    try {
      const result = await fetch(`${API_BASE_URL}/api/ingestions/validate`, {
        method: "POST",
        body: formData,
      });

      if (!result.ok) {
        const payload = await result.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Validation request failed.");
      }

      const payload = (await result.json()) as IngestionResponse;
      setResponse(payload);
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <section className="panel">
        <h1>NCC Ingestion Console</h1>
        <p>
          Run the hardened XML and PDF contracts together and inspect whether the paired document can
          progress toward the semantic layer.
        </p>
        <p>{summaryText}</p>
      </section>

      <section className="panel">
        <form className="grid" onSubmit={onSubmit}>
          <div>
            <label htmlFor="pdf">PDF document</label>
            <input id="pdf" type="file" accept=".pdf" onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)} />
          </div>
          <div>
            <label htmlFor="xml">XML source</label>
            <input id="xml" type="file" accept=".xml" onChange={(event) => setXmlFile(event.target.files?.[0] ?? null)} />
          </div>
          <button type="submit" disabled={loading}>
            {loading ? "Validating..." : "Validate ingestion"}
          </button>
          {error ? <p style={{ color: "#fca5a5" }}>{error}</p> : null}
        </form>
      </section>

      {response ? (
        <div className="grid">
          <ValidationViewer title="XML Validation" result={response.results.xml_validation} />
          <ValidationViewer title="PDF Validation" result={response.results.pdf_validation} />
          <section className="panel">
            <h2>Raw Metrics</h2>
            <pre>{JSON.stringify(response.raw_metrics, null, 2)}</pre>
          </section>
        </div>
      ) : null}
    </main>
  );
}
