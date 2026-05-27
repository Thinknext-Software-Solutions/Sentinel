import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

interface Props {
  adminOnly?: boolean;
}

export function ProtectedRoute({ adminOnly = false }: Props) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full p-10 text-slate-500">
        Loading...
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (adminOnly && user.role !== "admin") {
    return (
      <div className="p-10 text-center">
        <h2 className="text-lg font-semibold text-slate-900">Access denied</h2>
        <p className="text-sm text-slate-500 mt-1">
          You need admin privileges to view this page.
        </p>
      </div>
    );
  }
  return <Outlet />;
}
