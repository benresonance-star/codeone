"use client";

type ValidationResult = Record<string, any>;

function statusClass(status: string) {
  if (status.includes("PASS") && !status.includes("WARNING")) {
    return "status pass";
  }
  if (status.includes("WARNING") || status.includes("REVIEW")) {
    return "status warn";
  }
  return "status fail";
}

export function ValidationViewer({
  title,
  result,
}: {
  title: string;
  result: ValidationResult;
}) {
  const warnings = result.warnings ?? [];
  const errors = result.errors ?? [];

  return (
    <section className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <h2>{title}</h2>
          <p>{result.document?.doc_id}</p>
        </div>
        <span className={statusClass(result.overall_status)}>{result.overall_status}</span>
      </div>

      <div className="grid two-column">
        <div className="metric-list">
          <div>
            <strong>Quality</strong>: {result.confidence?.overall ?? "n/a"}
          </div>
          <div>
            <strong>Blocked</strong>: {String(result.gate_decision?.blocked)}
          </div>
          <div>
            <strong>Can Progress</strong>:{" "}
            {String(
              result.gate_decision?.can_progress_to_alignment_layer ??
                result.gate_decision?.can_progress_to_semantic_layer
            )}
          </div>
        </div>

        <div className="metric-list">
          {result.alignment_summary ? (
            <>
              <div>
                <strong>Aligned</strong>: {result.alignment_summary.aligned}
              </div>
              <div>
                <strong>Unresolved</strong>: {result.alignment_summary.unresolved}
              </div>
              <div>
                <strong>Average Confidence</strong>: {result.alignment_summary.average_confidence}
              </div>
            </>
          ) : null}
        </div>
      </div>

      <h3>Rule Results</h3>
      <div className="detail-list">
        {(result.rule_results ?? []).map((rule: any) => (
          <div key={rule.rule_id}>
            <strong>{rule.rule_id}</strong>: {rule.status}
          </div>
        ))}
      </div>

      <h3>Warnings</h3>
      <pre>{JSON.stringify(warnings, null, 2)}</pre>

      <h3>Errors</h3>
      <pre>{JSON.stringify(errors, null, 2)}</pre>

      <h3>Trace Sample</h3>
      <pre>{JSON.stringify(result.trace_sample ?? [], null, 2)}</pre>
    </section>
  );
}
