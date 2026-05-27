import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ApiError } from "../api/client";

export function LoginPage() {
  const { user, signIn, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (loading) return null;
  if (user) {
    const target = (location.state as { from?: { pathname: string } } | null)?.from?.pathname || "/";
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signIn(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || "Sign in failed");
      } else {
        setError("Sign in failed");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <form onSubmit={handleSubmit} className="card p-8 w-full max-w-md space-y-5">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Sentinel Studio</h1>
          <p className="text-sm text-slate-500 mt-1">Sign in to continue.</p>
        </div>

        <div>
          <label htmlFor="email" className="label">Email</label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
          />
        </div>

        <div>
          <label htmlFor="password" className="label">Password</label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
          />
        </div>

        {error && (
          <p className="text-sm text-red-600" role="alert">{error}</p>
        )}

        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? "Signing in..." : "Sign in"}
        </button>

        <p className="text-xs text-slate-500 text-center">
          Don&apos;t have an account? Ask an admin to create one (`sentinel server init` creates the first).
        </p>
      </form>
    </div>
  );
}
