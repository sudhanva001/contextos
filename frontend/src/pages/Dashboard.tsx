import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, RepoStatus } from "../lib/api";

const STATUS_STYLES: Record<RepoStatus["status"], { label: string; className: string }> = {
  pending: { label: "Queued", className: "bg-ink-raised text-text-secondary" },
  cloning: { label: "Cloning", className: "bg-teal/20 text-teal" },
  parsing: { label: "Parsing", className: "bg-teal/20 text-teal" },
  embedding: { label: "Embedding", className: "bg-gold/20 text-gold" },
  complete: { label: "Ready", className: "bg-teal/20 text-teal-soft" },
  failed: { label: "Failed", className: "bg-red-900/40 text-red-300" },
};

function StatusBadge({ status }: { status: RepoStatus["status"] }) {
  const style = STATUS_STYLES[status];
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${style.className}`}>{style.label}</span>
  );
}

export default function Dashboard() {
  const [url, setUrl] = useState("");
  const queryClient = useQueryClient();

  const { data: repos, isLoading } = useQuery({
    queryKey: ["repos"],
    queryFn: api.repos.list,
    refetchInterval: 4000,
  });

  const submitRepo = useMutation({
    mutationFn: (github_url: string) => api.repos.submit(github_url),
    onSuccess: () => {
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["repos"] });
    },
  });

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
        <p className="text-text-secondary text-sm mt-1">
          Add a GitHub repository to start asking questions about it.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) submitRepo.mutate(url.trim());
        }}
        className="flex gap-2 mb-10"
      >
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repository"
          className="input-field flex-1"
        />
        <button type="submit" disabled={submitRepo.isPending} className="btn-primary inline-flex items-center gap-2">
          {submitRepo.isPending ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          Add repository
        </button>
      </form>
      {submitRepo.isError && (
        <p className="text-red-300 text-sm -mt-8 mb-8">{(submitRepo.error as Error).message}</p>
      )}

      {isLoading ? (
        <p className="text-text-muted text-sm">Loading…</p>
      ) : repos && repos.length > 0 ? (
        <div className="grid gap-3">
          {repos.map((repo) => (
            <Link
              key={repo.id}
              to={repo.status === "complete" ? `/repos/${repo.id}/chat` : `/repos/${repo.id}`}
              className="card p-5 flex items-center justify-between hover:border-gold-dim transition-colors group"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <h3 className="font-medium truncate">{repo.name}</h3>
                  <StatusBadge status={repo.status} />
                </div>
                <p className="text-text-muted text-sm mt-1 truncate">
                  {repo.summary ?? repo.github_url}
                </p>
              </div>
              <ArrowRight size={16} className="text-text-muted group-hover:text-gold transition-colors shrink-0 ml-4" />
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-10 text-center">
          <p className="text-text-secondary">No repositories yet. Add one above to get started.</p>
        </div>
      )}
    </div>
  );
}
