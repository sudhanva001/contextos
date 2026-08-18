import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../lib/api";
import { useAuthStore } from "../store/authStore";

export default function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    if (!code) {
      setError("Missing authorization code from GitHub.");
      return;
    }

    api.auth
      .callback(code)
      .then(({ access_token, refresh_token, user }) => {
        setTokens(access_token, refresh_token);
        setUser(user);
        navigate("/", { replace: true });
      })
      .catch(() => setError("Sign-in failed. Please try again."));
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-ink">
      <p className="text-text-secondary">{error ?? "Signing you in…"}</p>
    </div>
  );
}
