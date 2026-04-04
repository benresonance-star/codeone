import { ConsoleNavigation } from "../../components/console-navigation";
import { SchemaReviewPanel } from "../../components/schema-review-panel";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function SchemaReviewPage() {
  return (
    <main>
      <ConsoleNavigation />
      <section className="panel hero-panel">
        <div className="hero-grid">
          <div className="hero-copy">
            <span className="eyebrow">Schema operations</span>
            <h1>XML Schema Review</h1>
            <p className="hero-lead">
              Upload an XML batch for temporary clustering, compare it with the repo baseline corpus, and promote
              trusted families into the approved runtime registry.
            </p>
            <p className="muted">
              Uploaded batches are temporary discovery jobs. They are not mixed into per-file ingestion retention.
            </p>
          </div>
          <div className="hero-stats" aria-label="Schema review overview">
            <div className="summary-card">
              <strong>Batch mode</strong>
              <span>Multi-file XML upload</span>
            </div>
            <div className="summary-card">
              <strong>Repo baseline</strong>
              <span>`Spec/**/*.xml` corpus scan</span>
            </div>
            <div className="summary-card">
              <strong>Runtime source</strong>
              <span>Approved registry only</span>
            </div>
          </div>
        </div>
      </section>
      <SchemaReviewPanel apiBaseUrl={API_BASE_URL} />
    </main>
  );
}
