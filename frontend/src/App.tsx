import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { useAuthStore } from "./store/authStore";
import AuthCallback from "./pages/AuthCallback";
import ChatPage from "./pages/ChatPage";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import RepoView from "./pages/RepoView";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const accessToken = useAuthStore((s) => s.accessToken);
  if (!accessToken) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/repos/:repoId" element={<RepoView />} />
        <Route path="/repos/:repoId/chat" element={<ChatPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
