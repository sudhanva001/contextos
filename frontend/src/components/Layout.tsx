import { LogOut } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

import { useAuthStore } from "../store/authStore";

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="min-h-screen bg-ink">
      <header className="border-b border-ink-line">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link to="/" className="font-display font-semibold text-lg tracking-tight">
            <span className="text-gold">Context</span>OS
          </Link>

          <div className="flex items-center gap-4">
            {user && (
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                {user.avatar_url && (
                  <img src={user.avatar_url} alt="" className="w-6 h-6 rounded-full border border-ink-line" />
                )}
                <span>{user.github_login}</span>
              </div>
            )}
            <button
              onClick={logout}
              className="text-text-muted hover:text-text-primary transition-colors"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
