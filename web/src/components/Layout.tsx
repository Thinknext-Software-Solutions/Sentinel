import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export function Layout() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 rounded-md text-sm font-medium ${
      isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
    }`;

  return (
    <div className="min-h-full flex flex-col">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="text-base font-semibold text-slate-900">
              Sentinel <span className="text-slate-400">Studio</span>
            </Link>
            <nav className="flex items-center gap-1">
              <NavLink to="/projects" className={linkClass}>Projects</NavLink>
              <NavLink to="/runs" className={linkClass}>Runs</NavLink>
              {user?.role === "admin" && (
                <NavLink to="/admin/users" className={linkClass}>Users</NavLink>
              )}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">
              {user?.name || user?.email} <span className="badge-slate badge ml-1">{user?.role}</span>
            </span>
            <button onClick={handleSignOut} className="btn-secondary">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  );
}
