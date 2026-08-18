import { Github } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";

export default function Login() {
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    try {
      const { authorize_url, state } = await api.auth.getGithubUrl();
      sessionStorage.setItem("oauth_state", state);
      window.location.href = authorize_url;
    } catch {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-ink px-6">
      <div className="w-full max-w-sm text-center">
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 text-2xl font-display font-semibold tracking-tight">
            <span className="text-gold">Context</span>
            <span>OS</span>
          </div>
          <p className="mt-3 text-text-secondary text-sm">
            Ask a repository what it does. Get answers cited to the line.
          </p>
        </div>

        <button onClick={handleLogin} disabled={loading} className="btn-primary w-full inline-flex items-center justify-center gap-2">
          <Github size={18} />
          {loading ? "Redirecting…" : "Continue with GitHub"}
        </button>

        <p className="mt-6 text-xs text-text-muted">
          We read repository contents to answer your questions. Nothing is shared outside your account.
        </p>
      </div>
    </div>
  );
}
