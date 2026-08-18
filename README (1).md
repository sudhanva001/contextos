# 🧠 ContextOS

**ContextOS** turns any GitHub repository into something you can ask questions about in plain
English. Paste a repo URL, and ContextOS clones it, reads through the code and docs, and lets
you chat with it — with answers tailored to whether you're a developer, a product manager, or a
non-technical stakeholder, and every answer cited back to the exact file and line it came from.

Under the hood it's a retrieval-augmented generation (RAG) pipeline: the repo is parsed into
function/class/doc-level chunks, embedded, and stored in Postgres with `pgvector`. Questions are
answered by combining semantic similarity search with keyword search, reranking the results, and
handing the most relevant chunks to an LLM along with a role-specific system prompt — so it
answers from what's actually in the repo instead of guessing.

## ⚙️ Stack

- 🐍 **Backend**: FastAPI, SQLAlchemy, PostgreSQL + pgvector, Redis, Celery
- ⚛️ **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Query, Zustand
- 🤖 **LLM**: Groq (free, OpenAI-compatible API) — swappable for real OpenAI by changing one env var
- 🔎 **Embeddings**: local, free, CPU-based (`sentence-transformers`, `all-MiniLM-L6-v2`) — no API
  key or billing required
- 🐳 **Infra**: Docker Compose (db, redis, backend, worker, frontend)

## 🚀 Quick start

### 1. Prerequisites
- 🐳 Docker Desktop installed and running

### 2. Get a free Groq API key
Go to **https://console.groq.com/keys**, sign up (no credit card), and create a key. It starts
with `gsk_`.

### 3. Create a GitHub OAuth App
Go to **https://github.com/settings/developers** → New OAuth App:
- Homepage URL: `http://localhost:5173`
- Authorization callback URL: `http://localhost:5173/auth/callback`

Copy the Client ID and generate a Client Secret.

### 4. Configure environment variables
Edit `backend/.env`:
```
OPENAI_API_KEY=gsk_your-groq-key-here
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
JWT_SECRET=some-long-random-string-you-make-up
```

### 5. Run it
```bash
docker compose up --build
```

### 6. Use it 🎉
Open **http://localhost:5173**, sign in with GitHub, paste a repository URL, wait for ingestion
to finish, and start asking questions.

## 🔬 How it works

1. **📥 Ingestion** — shallow-clones the repo (`depth=1`), walks its files (skipping binaries and
   anything in `.gitignore`), scans for and redacts secrets (API keys, tokens, private keys)
   before anything is stored, extracts functions/classes/docstrings per language, and embeds each
   chunk locally. Progress runs as a Celery background job and is polled by the frontend.

2. **🔍 Query** — a question is embedded and matched against stored chunks two ways: vector cosine
   similarity (`pgvector`) and PostgreSQL full-text search. Scores are normalized and fused (60%
   semantic / 40% keyword by default), then reranked. The top chunks are assembled into a
   role-specific prompt (developer / PM / stakeholder) along with recent conversation history and
   sent to the LLM. If retrieval confidence is below threshold, ContextOS says it doesn't know
   rather than guessing.

3. **💬 Answers** come back with cited sources (file + line range), a confidence score, and
   suggested follow-up questions — cached in Redis for 15 minutes so identical questions don't
   re-hit the LLM.

## 📁 Project layout

```
backend/app/
  auth/        🔐 GitHub OAuth + JWT issuing/verification
  ingestion/   📥 cloning, parsing/chunking, secret scanning, local embeddings, Celery task
  query/       🔍 hybrid retrieval, reranking, context assembly, RAG generation, caching
  api/         🌐 FastAPI routers (repos, query, users, auth)
  models.py    🗄️ SQLAlchemy models (users, repos, files, chunks, conversations, ...)
frontend/src/
  pages/       🖥️ Dashboard, RepoView, ChatPage, Login, AuthCallback
  components/  🧩 Layout
  lib/         📡 typed API client
  store/       🗂️ Zustand auth store
```

## 🔁 Switching back to real OpenAI

By default ContextOS uses Groq (chat) and a local model (embeddings) so it runs for free. To use
OpenAI instead:

```
OPENAI_API_KEY=sk-your-real-openai-key
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
```

⚠️ Note: embeddings would need to be switched back to an OpenAI embedding model too (and
`EMBEDDING_DIM` updated to match), since the current schema is sized for the local model's
384-dimensional vectors.

## 🧹 Resetting

If you change `EMBEDDING_DIM` or otherwise need a clean slate:

```bash
docker compose down -v   # wipes the database
```

You'll also need to clear your browser's stored session for `localhost:5173` afterward, since old
JWTs will reference users that no longer exist.

## ⚠️ Known limitations of this MVP

- 🧩 Code parsing uses regex-based heuristics per language rather than full tree-sitter grammars.
- 📊 The reranker is a lightweight lexical-overlap heuristic, not a trained cross-encoder.
- 🔑 Secret scanning uses regex patterns and isn't a substitute for a dedicated tool like `gitleaks`.
- 🗄️ No automatic DB migrations (Alembic) yet — schema changes require a fresh volume.

## 📄 License

MIT
