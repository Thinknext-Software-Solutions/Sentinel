import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Project } from "../api/types";
import { useAuth } from "../hooks/useAuth";

export function ProjectsPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "member";

  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/api/projects"),
  });

  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
          <p className="text-sm text-slate-500 mt-1">
            Each project is a named app to test, with its own URL and config.
          </p>
        </div>
        {canEdit && (
          <button onClick={() => setCreating((p) => !p)} className="btn-primary">
            {creating ? "Cancel" : "+ New project"}
          </button>
        )}
      </div>

      {creating && <CreateProjectForm onDone={() => setCreating(false)} />}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : !projects || projects.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="text-slate-500">No projects yet.</p>
          {canEdit && (
            <button onClick={() => setCreating(true)} className="btn-primary mt-4">
              Create your first project
            </button>
          )}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link to={`/projects/${p.id}`} key={p.id} className="card p-5 hover:border-slate-400 transition-colors block">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-base font-semibold text-slate-900">{p.name}</h3>
                <span className="badge-slate">{p.slug}</span>
              </div>
              <p className="text-xs text-slate-500 mt-1 truncate">{p.base_url}</p>
              {p.description && (
                <p className="text-sm text-slate-600 mt-3 line-clamp-2">{p.description}</p>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateProjectForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  const mutation = useMutation({
    mutationFn: (body: object) => api.post<Project>("/api/projects", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      onDone();
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Failed to create");
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    mutation.mutate({ slug, name, base_url: baseUrl, description });
  };

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className="label" htmlFor="proj-slug">Slug</label>
          <input
            id="proj-slug" className="input" required
            placeholder="my-app"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            pattern="^[a-z0-9][a-z0-9-]*$"
          />
          <p className="text-xs text-slate-500 mt-1">Lowercase letters, digits, hyphens.</p>
        </div>
        <div>
          <label className="label" htmlFor="proj-name">Name</label>
          <input
            id="proj-name" className="input" required
            placeholder="My App"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
      </div>
      <div>
        <label className="label" htmlFor="proj-url">Base URL</label>
        <input
          id="proj-url" className="input" required type="url"
          placeholder="https://example.com"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </div>
      <div>
        <label className="label" htmlFor="proj-desc">Description (optional)</label>
        <textarea
          id="proj-desc" className="input" rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onDone} className="btn-secondary">Cancel</button>
        <button type="submit" disabled={mutation.isPending} className="btn-primary">
          {mutation.isPending ? "Creating..." : "Create project"}
        </button>
      </div>
    </form>
  );
}
