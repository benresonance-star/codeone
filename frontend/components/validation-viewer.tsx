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

function summarizeProgress(result: ValidationResult): string {
  if (result.gate_decision?.can_progress_to_alignment_layer || result.gate_decision?.can_progress_to_semantic_layer) {
    return "Ready";
  }
  return result.gate_decision?.blocked ? "Blocked" : "Held for review";
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
  const traceSample = result.trace_sample ?? [];
  const ruleResults = result.rule_results ?? [];
  const highlightedRules =
    ruleResults.filter((rule: any) => rule.status !== "PASS").slice(0, 6) || ruleResults.slice(0, 6);

  return (
    <section className="panel validation-panel">
      <div className="workspace-header">
        <div>
          <h2>{title}</h2>
          <p className="muted">{result.document?.doc_id ?? "No document id available"}</p>
        </div>
        <span className={statusClass(result.overall_status)}>{result.overall_status}</span>
      </div>

      <div className="validation-kpis">
        <div className="summary-card">
          <strong>Quality</strong>
          <span>{result.confidence?.overall ?? "n/a"}</span>
        </div>
        <div className="summary-card">
          <strong>Gate</strong>
          <span>{summarizeProgress(result)}</span>
        </div>
        <div className="summary-card">
          <strong>Warnings</strong>
          <span>{warnings.length}</span>
        </div>
        <div className="summary-card">
          <strong>Errors</strong>
          <span>{errors.length}</span>
        </div>
        {result.alignment_summary ? (
          <div className="summary-card">
            <strong>Aligned</strong>
            <span>{result.alignment_summary.aligned}</span>
          </div>
        ) : null}
        {result.alignment_summary ? (
          <div className="summary-card">
            <strong>Unresolved</strong>
            <span>{result.alignment_summary.unresolved}</span>
          </div>
        ) : null}
      </div>

      <div className="grid two-column">
        <div className="metric-list validation-summary">
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

        <div className="metric-list validation-summary">
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

      <div className="section-header compact">
        <div>
          <h3>Priority Rule Results</h3>
          <p className="muted">The most important non-pass checks are surfaced first for operator review.</p>
        </div>
      </div>
      <div className="rule-grid">
        {highlightedRules.map((rule: any) => (
          <div key={rule.rule_id} className="rule-card">
            <strong>{rule.rule_id}</strong>
            <span className={statusClass(rule.status)}>{rule.status}</span>
          </div>
        ))}
      </div>

      <details className="detail-disclosure">
        <summary>Warnings ({warnings.length})</summary>
        <pre>{JSON.stringify(warnings, null, 2)}</pre>
      </details>

      <details className="detail-disclosure">
        <summary>Errors ({errors.length})</summary>
        <pre>{JSON.stringify(errors, null, 2)}</pre>
      </details>

      <details className="detail-disclosure">
        <summary>Trace Sample ({traceSample.length})</summary>
        <pre>{JSON.stringify(traceSample, null, 2)}</pre>
      </details>

      <details className="detail-disclosure">
        <summary>All Rule Results ({ruleResults.length})</summary>
        <pre>{JSON.stringify(ruleResults, null, 2)}</pre>
      </details>
    </section>
  );
}
