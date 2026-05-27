import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Run } from "../api/types";
import { RunStatusBadge, formatRelative } from "../components/runs";

export function RunsPage() {
  const { data: runs, isLoading } = useQuery({
    queryKey: ["recent-runs"],
    queryFn: () => api.get<Run[]>("/api/runs?limit=50"),
    refetchInterval: 5_000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Recent runs</h1>
        <p className="text-sm text-slate-500 mt-1">Across all projects, most recent first.</p>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : !runs || runs.length === 0 ? (
        <div className="card p-10 text-center text-slate-500">No runs yet.</div>
      ) : (
        <div className="card">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-6 py-2 font-medium">Status</th>
                <th className="px-6 py-2 font-medium">URL</th>
                <th className="px-6 py-2 font-medium">When</th>
                <th className="px-6 py-2 font-medium">Scenarios</th>
                <th className="px-6 py-2 font-medium">A11y</th>
                <th className="px-6 py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-t border-slate-200 hover:bg-slate-50">
                  <td className="px-6 py-3"><Link to={`/runs/${r.id}`}><RunStatusBadge status={r.status} /></Link></td>
                  <td className="px-6 py-3 max-w-md truncate"><Link to={`/runs/${r.id}`}>{r.target_url}</Link></td>
                  <td className="px-6 py-3 text-slate-600"><Link to={`/runs/${r.id}`}>{formatRelative(r.created_at)}</Link></td>
                  <td className="px-6 py-3">{r.scenarios_total > 0 ? `${r.scenarios_passed} / ${r.scenarios_total}` : "-"}</td>
                  <td className="px-6 py-3">{r.a11y_violations_count > 0 ? <span className="badge-yellow">{r.a11y_violations_count}</span> : "-"}</td>
                  <td className="px-6 py-3 tabular-nums">${r.cost_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
