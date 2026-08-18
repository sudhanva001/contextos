# ContextOS

AI-powered platform for understanding GitHub repositories through natural-language Q&A, using
retrieval-augmented generation (RAG) tailored to your role — developer, PM, or non-technical
stakeholder.

## Stack

- **Backend**: FastAPI, SQLAlchemy, PostgreSQL + pgvector, Redis, Celery
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Query, Zustand
- **AI**: OpenAI `gpt-4o-mini` (queries) + `text-embedding-3-small` (embeddings), hybrid
  semantic + keyword retrieval with heuristic reranking

## Quick start

1. Copy environment variables and fill in secrets:
   ```bash
   cp backend/.env.example backend/.env   # if you keep a template separate from .env
   ```
   At minimum, set `OPENAI_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `JWT_SECRET`
   in `backend/.env`. Create a GitHub OAuth App at
   https://github.com/settings/developers with callback URL
   `http://localhost:5173/auth/callback`.

2. Start everything:
   ```bash
   docker compose up --build
   ```

3. Open the app:
   - Frontend: http://localhost:5173
   - Backend docs (Swagger): http://localhost:8000/docs

## How it works

1. **Ingestion** — submit a GitHub URL. The backend shallow-clones the repo, walks its files
   (skipping binaries and anything in `.gitignore`), scans for and redacts secrets, extracts
   functions/classes/docstrings per language, and embeds each chunk with OpenAI, storing vectors
   in Postgres via `pgvector`. Progress is tracked through a Celery job and polled by the frontend.

2. **Query** — a question is embedded and matched against stored chunks two ways: cosine
   similarity search (pgvector) and PostgreSQL full-text search. Scores are normalized and fused
   (60% semantic / 40% keyword by default), then lightly reranked. The top chunks are assembled
   into a role-specific prompt (developer / PM / stakeholder) along with recent conversation
   history, and sent to the LLM. If retrieval confidence is below threshold, ContextOS says it
   doesn't know rather than guessing.

3. **Answers** come back with cited sources (file + line range), a confidence score, and
   suggested follow-up questions — cached in Redis for 15 minutes to avoid repeat LLM calls on
   identical questions.

## Project layout

```
backend/app/
  auth/        GitHub OAuth + JWT
  ingestion/   cloning, parsing/chunking, secret scanning, embeddings, Celery task
  query/       hybrid retrieval, reranking, context assembly, RAG generation
  api/         FastAPI routers
frontend/src/
  pages/       Dashboard, RepoView, ChatPage, Login
  components/  Layout
  lib/         typed API client
  store/       Zustand auth store
```

## Notes / known limitations of this MVP

- Code parsing uses regex-based heuristics per language rather than full tree-sitter grammars;
  it extracts function/class boundaries reasonably well but isn't a real parser.
- The reranker is a lightweight lexical-overlap heuristic, not a trained cross-encoder — swap in
  `ms-marco-MiniLM` (e.g. via `sentence-transformers`) for higher-quality reranking.
- Secret scanning uses regex patterns and redacts matches before embedding/storage; it isn't a
  substitute for a dedicated secret-scanning service like `gitleaks` or `trufflehog`.
