import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { Project, Run } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { RunStatusBadge, formatRelative } from "../components/runs";

export function ProjectDetailPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "member";
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.get<Project>(`/api/projects/${id}`),
    enabled: !!id,
  });

  const { data: runs } = useQuery({
    queryKey: ["projects", id, "runs"],
    queryFn: () => api.get<Run[]>(`/api/projects/${id}/runs?limit=50`),
    enabled: !!id,
    refetchInterval: 5_000,
  });

  const triggerRun = useMutation({
    mutationFn: () => api.post<Run>(`/api/projects/${id}/runs`, {}),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["projects", id, "runs"] });
      navigate(`/runs/${run.id}`);
    },
  });

  const deleteProject = useMutation({
    mutationFn: () => api.del<void>(`/api/projects/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate("/projects", { replace: true });
    },
  });

  if (isLoading) return <p className="text-slate-500 text-sm">Loading...</p>;
  if (!project) return <p className="text-red-600">Project not found.</p>;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/projects" className="text-sm text-slate-500 hover:text-slate-900">
          &larr; Projects
        </Link>
      </div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{project.name}</h1>
          <p className="text-sm text-slate-500 mt-1">
            <span className="badge-slate mr-2">{project.slug}</span>
            <a href={project.base_url} target="_blank" rel="noopener" className="underline hover:text-slate-900">
              {project.base_url}
            </a>
          </p>
          {project.description && (
            <p className="text-sm text-slate-700 mt-3">{project.description}</p>
          )}
        </div>
        {canEdit && (
          <div className="flex gap-2">
            <button onClick={() => triggerRun.mutate()} disabled={triggerRun.isPending} className="btn-primary">
              {triggerRun.isPending ? "Starting..." : "Run now"}
            </button>
          </div>
        )}
      </div>

      {triggerRun.isError && (
        <p className="text-sm text-red-600">
          {triggerRun.error instanceof ApiError ? triggerRun.error.message : "Failed to start run"}
        </p>
      )}

      <ProjectConfigCard project={project} canEdit={canEdit} />

      <RunsSection runs={runs ?? []} />

      {canEdit && (
        <div className="pt-8 border-t border-slate-200">
          <button
            onClick={() => {
              if (confirm(`Delete project "${project.name}"? This deletes all runs and history.`)) {
                deleteProject.mutate();
              }
            }}
            className="btn-danger"
          >
            Delete project
          </button>
        </div>
      )}
    </div>
  );
}

function ProjectConfigCard({ project, canEdit }: { project: Project; canEdit: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [yaml, setYaml] = useState(project.config_yaml);
  const [provider, setProvider] = useState(project.llm_provider);
  const [model, setModel] = useState(project.llm_model);
  const [explore, setExplore] = useState(project.explore_links);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: (body: object) => api.patch<Project>(`/api/projects/${project.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", project.id] });
      setEditing(false);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Save failed"),
  });

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    save.mutate({
      config_yaml: yaml,
      llm_provider: provider,
      llm_model: model,
      explore_links: explore,
    });
  };

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-slate-900">Configuration</h2>
        {canEdit && (
          <button onClick={() => setEditing((e) => !e)} className="btn-secondary">
            {editing ? "Cancel" : "Edit"}
          </button>
        )}
      </div>
      {!editing ? (
        <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt className="text-slate-500">LLM provider</dt>
            <dd className="text-slate-900">{project.llm_provider || <em className="text-slate-400">user default</em>}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Model</dt>
            <dd className="text-slate-900">{project.llm_model || <em className="text-slate-400">provider default</em>}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Multi-page exploration</dt>
            <dd className="text-slate-900">{project.explore_links ? "on (up to 4 same-origin links)" : "off"}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-slate-500 mb-1">sentinel.yaml override</dt>
            <dd>
              {project.config_yaml ? (
                <pre className="bg-slate-50 border border-slate-200 rounded p-3 text-xs overflow-auto">{project.config_yaml}</pre>
              ) : (
                <span className="text-slate-400 italic text-sm">none (uses defaults)</span>
              )}
            </dd>
          </div>
        </dl>
      ) : (
        <form onSubmit={onSave} className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="label">LLM provider</label>
              <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="">user default</option>
                <option value="anthropic">anthropic</option>
                <option value="openai">openai</option>
                <option value="google">google</option>
                <option value="claude_code">claude_code</option>
                <option value="ollama">ollama</option>
              </select>
            </div>
            <div>
              <label className="label">Model</label>
              <input className="input" value={model} onChange={(e) => setModel(e.target.value)} placeholder="provider default" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={explore} onChange={(e) => setExplore(e.target.checked)} />
            Multi-page exploration (up to 4 same-origin links)
          </label>
          <div>
            <label className="label">sentinel.yaml override (optional)</label>
            <textarea
              className="input font-mono text-xs"
              rows={8}
              value={yaml}
              onChange={(e) => setYaml(e.target.value)}
              placeholder="Leave empty to use defaults."
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
            <button type="submit" disabled={save.isPending} className="btn-primary">
              {save.isPending ? "Saving..." : "Save changes"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function RunsSection({ runs }: { runs: Run[] }) {
  return (
    <div className="card">
      <div className="px-6 py-4 border-b border-slate-200">
        <h2 className="text-base font-semibold text-slate-900">Recent runs</h2>
      </div>
      {runs.length === 0 ? (
        <p className="p-6 text-sm text-slate-500">No runs yet. Click <strong>Run now</strong> above.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-6 py-2 font-medium">Status</th>
              <th className="px-6 py-2 font-medium">When</th>
              <th className="px-6 py-2 font-medium">Scenarios</th>
              <th className="px-6 py-2 font-medium">A11y</th>
              <th className="px-6 py-2 font-medium">Visual</th>
              <th className="px-6 py-2 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-slate-200 hover:bg-slate-50">
                <td className="px-6 py-3">
                  <Link to={`/runs/${r.id}`}><RunStatusBadge status={r.status} /></Link>
                </td>
                <td className="px-6 py-3 text-slate-600">
                  <Link to={`/runs/${r.id}`}>{formatRelative(r.created_at)}</Link>
                </td>
                <td className="px-6 py-3">
                  {r.scenarios_total > 0 ? `${r.scenarios_passed} / ${r.scenarios_total}` : "-"}
                </td>
                <td className="px-6 py-3">
                  {r.a11y_violations_count > 0 ? (
                    <span className="badge-yellow">{r.a11y_violations_count}</span>
                  ) : "-"}
                </td>
                <td className="px-6 py-3">
                  {r.visual_diffs_count > 0 ? (
                    <span className="badge-yellow">{r.visual_diffs_count}</span>
                  ) : "-"}
                </td>
                <td className="px-6 py-3 tabular-nums">${r.cost_usd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
