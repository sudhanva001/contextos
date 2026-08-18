import { create } from "zustand";

interface AuthUser {
  id: string;
  github_login: string;
  avatar_url: string | null;
  default_role: string;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
  setTokens: (accessToken: string, refreshToken: string) => void;
  setUser: (user: AuthUser) => void;
  logout: () => void;
}

const STORAGE_KEY = "contextos_auth";

function loadPersisted(): Pick<AuthState, "accessToken" | "refreshToken" | "user"> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore corrupt storage
  }
  return { accessToken: null, refreshToken: null, user: null };
}

function persist(state: Pick<AuthState, "accessToken" | "refreshToken" | "user">) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export const useAuthStore = create<AuthState>((set, get) => ({
  ...loadPersisted(),
  setTokens: (accessToken, refreshToken) => {
    set({ accessToken, refreshToken });
    persist({ accessToken, refreshToken, user: get().user });
  },
  setUser: (user) => {
    set({ user });
    persist({ accessToken: get().accessToken, refreshToken: get().refreshToken, user });
  },
  logout: () => {
    set({ accessToken: null, refreshToken: null, user: null });
    sessionStorage.removeItem(STORAGE_KEY);
  },
}));
