import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { Role, User } from "../api/types";
import { useAuth } from "../hooks/useAuth";
import { formatRelative } from "../components/runs";

export function AdminUsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/api/users"),
  });
  const [creating, setCreating] = useState(false);

  const updateUser = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api.patch<User>(`/api/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const deleteUser = useMutation({
    mutationFn: (id: string) => api.del<void>(`/api/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Users</h1>
          <p className="text-sm text-slate-500 mt-1">
            Admins can add, deactivate, and remove users. Members create projects; viewers are read-only.
          </p>
        </div>
        <button onClick={() => setCreating((p) => !p)} className="btn-primary">
          {creating ? "Cancel" : "+ Invite user"}
        </button>
      </div>

      {creating && <CreateUserForm onDone={() => setCreating(false)} />}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="card">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-6 py-2 font-medium">Email</th>
                <th className="px-6 py-2 font-medium">Name</th>
                <th className="px-6 py-2 font-medium">Role</th>
                <th className="px-6 py-2 font-medium">Active</th>
                <th className="px-6 py-2 font-medium">Last login</th>
                <th className="px-6 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(users ?? []).map((u) => {
                const isSelf = u.id === me?.id;
                return (
                  <tr key={u.id} className="border-t border-slate-200">
                    <td className="px-6 py-3">{u.email}</td>
                    <td className="px-6 py-3">{u.name || <span className="text-slate-400">-</span>}</td>
                    <td className="px-6 py-3">
                      <select
                        className="input py-1"
                        value={u.role}
                        disabled={isSelf}
                        onChange={(e) =>
                          updateUser.mutate({
                            id: u.id,
                            body: { role: e.target.value as Role },
                          })
                        }
                      >
                        <option value="admin">admin</option>
                        <option value="member">member</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td className="px-6 py-3">
                      <label className="inline-flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={u.is_active}
                          disabled={isSelf}
                          onChange={(e) =>
                            updateUser.mutate({ id: u.id, body: { is_active: e.target.checked } })
                          }
                        />
                        <span className="text-xs">{u.is_active ? "yes" : "no"}</span>
                      </label>
                    </td>
                    <td className="px-6 py-3 text-slate-600">
                      {u.last_login_at ? formatRelative(u.last_login_at) : <span className="text-slate-400">never</span>}
                    </td>
                    <td className="px-6 py-3">
                      {!isSelf && (
                        <button
                          className="text-red-600 text-xs hover:underline"
                          onClick={() => {
                            if (confirm(`Delete user ${u.email}? This cannot be undone.`)) {
                              deleteUser.mutate(u.id);
                            }
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {updateUser.isError && (
        <p className="text-sm text-red-600">
          {updateUser.error instanceof ApiError ? updateUser.error.message : "Update failed"}
        </p>
      )}
    </div>
  );
}

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: () => api.post<User>("/api/users", { email, name, password, role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      onDone();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Create failed"),
  });

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        setError("");
        create.mutate();
      }}
      className="card p-6 space-y-4"
    >
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className="label">Email</label>
          <input type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="label">Password (min 8)</label>
          <input
            type="password" required minLength={8}
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label className="label">Role</label>
          <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="admin">admin</option>
            <option value="member">member</option>
            <option value="viewer">viewer</option>
          </select>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onDone} className="btn-secondary">Cancel</button>
        <button type="submit" disabled={create.isPending} className="btn-primary">
          {create.isPending ? "Creating..." : "Create user"}
        </button>
      </div>
    </form>
  );
}
