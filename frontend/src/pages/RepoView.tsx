import { useQuery } from "@tanstack/react-query";
import { FileCode, MessageSquare } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { api } from "../lib/api";

const LANGUAGE_COLORS: Record<string, string> = {
  python: "bg-teal",
  javascript: "bg-gold",
  typescript: "bg-teal-soft",
  java: "bg-gold-dim",
  go: "bg-teal",
  markdown: "bg-text-muted",
};

export default function RepoView() {
  const { repoId } = useParams<{ repoId: string }>();

  const { data } = useQuery({
    queryKey: ["repo", repoId],
    queryFn: () => api.repos.get(repoId!),
    enabled: !!repoId,
    refetchInterval: (query) => (query.state.data?.repository.status === "complete" ? false : 2500),
  });

  const { data: files } = useQuery({
    queryKey: ["repo-files", repoId],
    queryFn: () => api.repos.files(repoId!),
    enabled: !!repoId && data?.repository.status === "complete",
  });

  if (!data) return <p className="text-text-muted text-sm">Loading…</p>;

  const { repository, job } = data;
  const isReady = repository.status === "complete";
  const totalFiles = Object.values(repository.language_stats).reduce((a, b) => a + b, 0);

  return (
    <div>
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{repository.name}</h1>
          <p className="text-text-secondary text-sm mt-1">{repository.github_url}</p>
        </div>
        {isReady && (
          <Link to={`/repos/${repoId}/chat`} className="btn-primary inline-flex items-center gap-2">
            <MessageSquare size={16} />
            Ask a question
          </Link>
        )}
      </div>

      {!isReady && job && (
        <div className="card p-6 mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">{job.current_step ?? "Working…"}</span>
            <span className="text-sm text-text-muted">{job.progress_pct}%</span>
          </div>
          <div className="h-2 bg-ink-raised rounded-full overflow-hidden">
            <div
              className="h-full bg-gold transition-all duration-500"
              style={{ width: `${job.progress_pct}%` }}
            />
          </div>
          {job.files_total > 0 && (
            <p className="text-xs text-text-muted mt-2">
              {job.files_processed} / {job.files_total} files
            </p>
          )}
          {job.error_message && <p className="text-xs text-red-300 mt-2">{job.error_message}</p>}
        </div>
      )}

      {repository.summary && (
        <p className="text-text-secondary text-sm mb-6 leading-relaxed">{repository.summary}</p>
      )}

      {totalFiles > 0 && (
        <div className="flex flex-wrap gap-2 mb-8">
          {Object.entries(repository.language_stats).map(([lang, count]) => (
            <span key={lang} className="inline-flex items-center gap-1.5 text-xs text-text-secondary bg-ink-raised px-2.5 py-1 rounded-full">
              <span className={`w-1.5 h-1.5 rounded-full ${LANGUAGE_COLORS[lang] ?? "bg-text-muted"}`} />
              {lang} · {count}
            </span>
          ))}
        </div>
      )}

      {files && files.length > 0 && (
        <div className="card divide-y divide-ink-line">
          {files.map((f) => (
            <div key={f.id} className="p-3 flex items-center gap-3 text-sm">
              <FileCode size={14} className="text-text-muted shrink-0" />
              <span className="font-mono text-text-secondary truncate">{f.path}</span>
              {f.language && <span className="text-xs text-text-muted ml-auto shrink-0">{f.language}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
