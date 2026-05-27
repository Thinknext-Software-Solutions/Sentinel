import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { RunDetail } from "../api/types";
import { RunStatusBadge, formatDuration, formatRelative } from "../components/runs";

export function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: run, isLoading } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<RunDetail>(`/api/runs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => {
      const r = q.state.data;
      if (!r) return 3_000;
      return r.status === "queued" || r.status === "running" ? 3_000 : false;
    },
  });

  if (isLoading) return <p className="text-slate-500 text-sm">Loading...</p>;
  if (!run) return <p className="text-red-600">Run not found.</p>;

  const isInFlight = run.status === "queued" || run.status === "running";

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/projects/${run.project_id}`} className="text-sm text-slate-500 hover:text-slate-900">
          &larr; Back to project
        </Link>
      </div>

      <header className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <RunStatusBadge status={run.status} />
            <span className="text-sm text-slate-500">
              {formatRelative(run.created_at)}
            </span>
          </div>
          <h1 className="text-xl font-semibold text-slate-900 break-all">{run.target_url}</h1>
        </div>
        <dl className="text-right text-sm">
          <div>
            <dt className="text-slate-500">Cost</dt>
            <dd className="text-slate-900 tabular-nums font-medium">${run.cost_usd.toFixed(2)}</dd>
          </div>
          <div className="mt-2 text-xs text-slate-500">
            {run.input_tokens.toLocaleString()} in / {run.output_tokens.toLocaleString()} out
          </div>
        </dl>
      </header>

      {isInFlight && (
        <div className="card p-4 border-amber-300 bg-amber-50 text-amber-800 text-sm">
          Run is {run.status}. This page refreshes every few seconds.
        </div>
      )}

      {run.error_message && (
        <div className="card p-4 border-red-300 bg-red-50 text-red-800 text-sm whitespace-pre-wrap">
          <p className="font-semibold mb-1">Error</p>
          {run.error_message}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Scenarios" value={`${run.scenarios_passed} / ${run.scenarios_total}`} accent={run.scenarios_total > 0 && run.scenarios_passed === run.scenarios_total ? "good" : run.scenarios_total === 0 ? "neutral" : "bad"} />
        <Stat label="Visual diffs" value={`${run.visual_diffs_count}`} accent={run.visual_diffs_count === 0 ? "good" : "bad"} />
        <Stat label="A11y violations" value={`${run.a11y_violations_count}`} accent={run.a11y_violations_count === 0 ? "good" : "bad"} />
        <Stat label="Cost" value={`$${run.cost_usd.toFixed(2)}`} accent="neutral" />
      </div>

      <ScenariosSection scenarios={run.scenarios} />
      <VisualDiffsSection diffs={run.visual_diffs} />
      <A11ySection violations={run.a11y_violations} />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent: "good" | "bad" | "neutral" }) {
  const color =
    accent === "good"
      ? "text-emerald-700 border-emerald-200 bg-emerald-50"
      : accent === "bad"
        ? "text-red-700 border-red-200 bg-red-50"
        : "text-slate-700 border-slate-200 bg-slate-50";
  return (
    <div className={`rounded-md border p-4 ${color}`}>
      <div className="text-xs uppercase tracking-wide opacity-75">{label}</div>
      <div className="text-2xl font-semibold mt-1 tabular-nums">{value}</div>
    </div>
  );
}

function ScenariosSection({ scenarios }: { scenarios: RunDetail["scenarios"] }) {
  if (scenarios.length === 0) {
    return (
      <div className="card p-6">
        <h2 className="text-base font-semibold text-slate-900 mb-2">Scenarios</h2>
        <p className="text-sm text-slate-500">None yet.</p>
      </div>
    );
  }
  return (
    <div className="card">
      <div className="px-6 py-4 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">Scenarios</h2>
      </div>
      <ul className="divide-y divide-slate-200">
        {scenarios.map((s) => (
          <li key={s.id} className="px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-medium text-slate-900">
                  {s.passed ? <span className="text-emerald-600 mr-2">✓</span> : <span className="text-red-600 mr-2">✗</span>}
                  {s.name}
                </p>
                {s.description && <p className="text-sm text-slate-500 mt-1">{s.description}</p>}
              </div>
              <span className="text-xs text-slate-500 tabular-nums">{formatDuration(s.duration_seconds)}</span>
            </div>
            {s.failures.length > 0 && (
              <ul className="mt-3 space-y-2">
                {s.failures.map((f, idx) => (
                  <li key={idx} className="text-sm bg-red-50 border border-red-200 rounded p-3 text-red-900">
                    <p className="font-medium">Step {f.step_index}: {f.step_description}</p>
                    <p className="text-xs mt-1 whitespace-pre-wrap">{f.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function VisualDiffsSection({ diffs }: { diffs: RunDetail["visual_diffs"] }) {
  if (diffs.length === 0) return null;
  return (
    <div className="card">
      <div className="px-6 py-4 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">Visual diffs</h2>
      </div>
      <ul className="divide-y divide-slate-200">
        {diffs.map((d) => (
          <li key={d.id} className="px-6 py-4 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-900">{d.name}</span>
              <span className="badge-yellow">
                {d.percent_changed.toFixed(2)}% changed (threshold {d.threshold.toFixed(2)}%)
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function A11ySection({ violations }: { violations: RunDetail["a11y_violations"] }) {
  if (violations.length === 0) return null;
  return (
    <div className="card">
      <div className="px-6 py-4 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">Accessibility violations</h2>
      </div>
      <ul className="divide-y divide-slate-200">
        {violations.map((v) => (
          <li key={v.id} className="px-6 py-4 text-sm">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-slate-900">
                  <span className={`mr-2 ${v.impact === "critical" || v.impact === "serious" ? "text-red-600" : "text-amber-600"}`}>
                    [{v.impact}]
                  </span>
                  {v.rule_id}
                </p>
                <p className="text-slate-700 mt-1">{v.description}</p>
                {v.sample_selector && (
                  <code className="block mt-2 text-xs bg-slate-50 border border-slate-200 rounded px-2 py-1 text-slate-700">
                    {v.sample_selector}
                  </code>
                )}
              </div>
              <span className="badge-slate shrink-0">{v.nodes_affected} node{v.nodes_affected === 1 ? "" : "s"}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
