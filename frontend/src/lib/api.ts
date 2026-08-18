import { useAuthStore } from "../store/authStore";

const BASE_URL = "/v1";

export type UserRole = "developer" | "pm" | "stakeholder";

export interface RepoStatus {
  id: string;
  name: string;
  github_url: string;
  status: "pending" | "cloning" | "parsing" | "embedding" | "complete" | "failed";
  summary: string | null;
  language_stats: Record<string, number>;
  created_at: string;
}

export interface RepoFile {
  id: string;
  path: string;
  language: string | null;
  size_bytes: number;
  summary: string | null;
}

export interface QuerySource {
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  symbol_name: string | null;
  relevance: number;
}

export interface QueryResponse {
  conversation_id: string;
  answer: string;
  sources: QuerySource[];
  confidence: number;
  related_questions: string[];
  cached: boolean;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { accessToken, refreshToken, setTokens, logout } = useAuthStore.getState();

  const doFetch = async (token: string | null) =>
    fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });

  let res = await doFetch(accessToken);

  if (res.status === 401 && refreshToken) {
    const refreshRes = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (refreshRes.ok) {
      const { access_token } = await refreshRes.json();
      setTokens(access_token, refreshToken);
      res = await doFetch(access_token);
    } else {
      logout();
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? "Request failed");
  }
  return res.json();
}

export const api = {
  auth: {
    getGithubUrl: () => request<{ authorize_url: string; state: string }>("/auth/github", { method: "POST" }),
    callback: (code: string) =>
      request<{ access_token: string; refresh_token: string; user: any }>("/auth/callback", {
        method: "POST",
        body: JSON.stringify({ code }),
      }),
  },
  repos: {
    list: () => request<RepoStatus[]>("/repos"),
    submit: (github_url: string) =>
      request<RepoStatus>("/repos", { method: "POST", body: JSON.stringify({ github_url }) }),
    get: (id: string) => request<{ repository: RepoStatus; job: any }>(`/repos/${id}`),
    files: (id: string) => request<RepoFile[]>(`/repos/${id}/files`),
  },
  query: {
    ask: (payload: { repository_id: string; question: string; role: UserRole; conversation_id?: string }) =>
      request<QueryResponse>("/query", { method: "POST", body: JSON.stringify(payload) }),
  },
  conversations: {
    list: (repository_id?: string) =>
      request<any[]>(`/conversations${repository_id ? `?repository_id=${repository_id}` : ""}`),
    get: (id: string) => request<any>(`/conversations/${id}`),
  },
  me: () => request<any>("/users/me"),
};

export { ApiError };
