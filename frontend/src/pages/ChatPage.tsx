import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { api, QuerySource, UserRole } from "../lib/api";

interface Turn {
  role: "user" | "assistant";
  content: string;
  sources?: QuerySource[];
  confidence?: number;
  relatedQuestions?: string[];
}

const ROLES: { value: UserRole; label: string; description: string }[] = [
  { value: "developer", label: "Developer", description: "Technical detail, code refs" },
  { value: "pm", label: "PM", description: "Features & business logic" },
  { value: "stakeholder", label: "Stakeholder", description: "Plain-language overview" },
];

function SourceList({ sources }: { sources: QuerySource[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="mt-3 pt-3 border-t border-ink-line">
      <p className="text-xs text-text-muted mb-2 uppercase tracking-wide">Sources</p>
      <div className="space-y-1.5">
        {sources.map((s, i) => (
          <div key={i} className="flex items-baseline gap-2 text-xs">
            <span className="text-gold font-mono shrink-0">[{i + 1}]</span>
            <span className="font-mono text-text-secondary truncate">
              {s.file_path}
              {s.start_line && `:${s.start_line}${s.end_line && s.end_line !== s.start_line ? `-${s.end_line}` : ""}`}
            </span>
            {s.symbol_name && <span className="text-text-muted truncate">· {s.symbol_name}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { repoId } = useParams<{ repoId: string }>();
  const [role, setRole] = useState<UserRole>("developer");
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: repoData } = useQuery({
    queryKey: ["repo", repoId],
    queryFn: () => api.repos.get(repoId!),
    enabled: !!repoId,
  });

  const ask = useMutation({
    mutationFn: (question: string) =>
      api.query.ask({ repository_id: repoId!, question, role, conversation_id: conversationId }),
    onSuccess: (res) => {
      setConversationId(res.conversation_id);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: res.answer,
          sources: res.sources,
          confidence: res.confidence,
          relatedQuestions: res.related_questions,
        },
      ]);
    },
    onError: (err: Error) => {
      setTurns((t) => [...t, { role: "assistant", content: `Something went wrong: ${err.message}` }]);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, ask.isPending]);

  const submit = (question: string) => {
    if (!question.trim() || ask.isPending) return;
    setTurns((t) => [...t, { role: "user", content: question }]);
    ask.mutate(question);
    setInput("");
  };

  return (
    <div className="flex flex-col h-[calc(100vh-140px)]">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold truncate">{repoData?.repository.name ?? "Repository"}</h1>
        <div className="flex gap-1 bg-ink-raised rounded-md p-1">
          {ROLES.map((r) => (
            <button
              key={r.value}
              onClick={() => setRole(r.value)}
              title={r.description}
              className={`text-xs px-3 py-1.5 rounded transition-colors ${
                role === r.value ? "bg-gold text-ink font-medium" : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {turns.length === 0 && (
          <div className="card p-8 text-center text-text-secondary text-sm">
            Ask anything about this repository — architecture, a specific function, how a feature works.
          </div>
        )}

        {turns.map((turn, i) =>
          turn.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="bg-gold text-ink rounded-lg px-4 py-2.5 max-w-[75%] text-sm">{turn.content}</div>
            </div>
          ) : (
            <div key={i} className="card p-4 max-w-[85%]">
              <div className="prose-sm prose-invert text-sm leading-relaxed max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown>
              </div>
              {turn.sources && <SourceList sources={turn.sources} />}
              {turn.relatedQuestions && turn.relatedQuestions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {turn.relatedQuestions.map((q, qi) => (
                    <button
                      key={qi}
                      onClick={() => submit(q)}
                      className="text-xs text-teal-soft border border-teal/30 rounded-full px-3 py-1 hover:bg-teal/10 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        )}

        {ask.isPending && (
          <div className="card p-4 inline-flex items-center gap-2 text-text-muted text-sm">
            <Loader2 size={14} className="animate-spin" /> Thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(input);
        }}
        className="flex gap-2 mt-4"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this repository…"
          className="input-field flex-1"
        />
        <button type="submit" disabled={ask.isPending} className="btn-primary inline-flex items-center gap-2">
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
