"use client";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cardEntries(block: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(block)
    .filter(([, value]) => typeof value === "number" || typeof value === "boolean" || (typeof value === "string" && value.length < 64))
    .map(([key, value]) => [key, String(value)]);
}

export function ReviewMetricsStrip(payload: {
  raw_metrics?: Record<string, unknown> | null;
  review_workspace?: Record<string, unknown> | null;
}) {
  const raw = payload.raw_metrics ?? {};
  const rw = payload.review_workspace ?? {};

  const candidateQuality =
    (isRecord(rw.candidate_quality) && rw.candidate_quality) ||
    (isRecord(rw.candidate_quality_metrics) && rw.candidate_quality_metrics) ||
    (isRecord(raw.candidate_quality) && raw.candidate_quality) ||
    (isRecord(raw.candidate_quality_metrics) && raw.candidate_quality_metrics) ||
    null;
  const graphReadiness =
    (isRecord(rw.graph_readiness) && rw.graph_readiness) ||
    (isRecord(rw.robustness_validation) && rw.robustness_validation) ||
    (isRecord(raw.graph_readiness) && raw.graph_readiness) ||
    (isRecord(raw.robustness_validation) && raw.robustness_validation) ||
    (isRecord(raw.candidate_robustness_validation) && raw.candidate_robustness_validation) ||
    null;

  if (!candidateQuality && !graphReadiness) {
    return null;
  }
  const candidateQualityEntries = candidateQuality ? cardEntries(candidateQuality) : [];
  const graphReadinessEntries = graphReadiness ? cardEntries(graphReadiness) : [];
  const gates = Array.isArray(graphReadiness?.gates) ? graphReadiness.gates : [];

  return (
    <section className="panel review-metrics-panel">
      <div className="section-header compact">
        <div>
          <h3>Candidate robustness metrics</h3>
          <p className="muted">Run-level counts and graph-readiness gates derived from the candidate pipeline.</p>
        </div>
      </div>

      {candidateQualityEntries.length ? (
        <>
          <h4 className="review-metrics-heading">Candidate quality</h4>
          <div className="workspace-summary">
            {candidateQualityEntries.map(([key, value]) => (
              <div key={key} className="summary-card">
                <strong>{key.replace(/_/g, " ")}</strong>
                <span>{value}</span>
              </div>
            ))}
          </div>
        </>
      ) : null}

      {graphReadinessEntries.length ? (
        <>
          <h4 className="review-metrics-heading">Graph readiness</h4>
          <div className="workspace-summary">
            {graphReadinessEntries.map(([key, value]) => (
              <div key={key} className="summary-card">
                <strong>{key.replace(/_/g, " ")}</strong>
                <span>{value}</span>
              </div>
            ))}
          </div>
        </>
      ) : null}

      {gates.length ? (
        <div className="baseline-table-wrap">
          <table className="baseline-table">
            <thead>
              <tr>
                <th scope="col">Gate</th>
                <th scope="col">Passed</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {gates.map((gate, index) => {
                const gateRecord = isRecord(gate) ? gate : {};
                const passed = gateRecord.passed === true;
                const failed = gateRecord.passed === false;
                return (
                  <tr key={String(gateRecord.gate_id ?? index)}>
                    <td>{String(gateRecord.gate_id ?? `gate_${index + 1}`)}</td>
                    <td>
                      {failed || passed ? (
                        <span className={`status ${passed ? "pass" : "warn"}`}>{passed ? "pass" : "fail"}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{String(gateRecord.detail ?? "—")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {candidateQuality ? (
        <details className="detail-disclosure">
          <summary>Full candidate quality JSON</summary>
          <pre>{JSON.stringify(candidateQuality, null, 2)}</pre>
        </details>
      ) : null}

      {graphReadiness ? (
        <details className="detail-disclosure">
          <summary>Full graph readiness JSON</summary>
          <pre>{JSON.stringify(graphReadiness, null, 2)}</pre>
        </details>
      ) : null}
    </section>
  );
}
