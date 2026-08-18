import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import redis
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.embeddings import embed_query
from app.models import Conversation, Repository, UserRole

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None
_openai_client: OpenAI | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,  # None = OpenAI's default endpoint
        )
    return _openai_client


@dataclass
class RetrievedChunk:
    id: str
    file_path: str
    symbol_name: str | None
    content: str
    start_line: int | None
    end_line: int | None
    semantic_score: float
    keyword_score: float
    fused_score: float = 0.0
    rerank_score: float = 0.0


@dataclass
class QueryResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    related_questions: list[str] = field(default_factory=list)
    cached: bool = False


ROLE_SYSTEM_PROMPTS = {
    UserRole.DEVELOPER: (
        "You are a senior engineer explaining this codebase to another developer. "
        "Be technical and precise: reference actual function/class names, file paths, and line "
        "numbers, and include short code snippets where useful. Assume the reader can read code."
    ),
    UserRole.PM: (
        "You are explaining this codebase to a product manager. Focus on business logic, "
        "user-facing features, and how components map to product behavior. Avoid raw code "
        "unless it's essential to illustrate a point; prefer plain-language descriptions of "
        "what the code does and why it matters for the product."
    ),
    UserRole.STAKEHOLDER: (
        "You are explaining this codebase to a non-technical stakeholder. Use high-level, "
        "jargon-free language. Never show code. Focus on capabilities, architecture at a "
        "conceptual level, and business value."
    ),
}


def _cache_key(repo_id: str, role: str, question: str) -> str:
    digest = hashlib.sha256(f"{repo_id}:{role}:{question.strip().lower()}".encode()).hexdigest()
    return f"query_cache:{digest}"


def _semantic_search(db: Session, repo_id: str, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
    rows = db.execute(
        text(
            """
            SELECT c.id, f.path AS file_path, c.symbol_name, c.content,
                   c.start_line, c.end_line,
                   1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM chunks c
            JOIN files f ON f.id = c.file_id
            WHERE c.repository_id = :repo_id AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        ),
        {"embedding": query_embedding, "repo_id": repo_id, "top_k": top_k},
    ).mappings().all()

    return [
        RetrievedChunk(
            id=str(r["id"]), file_path=r["file_path"], symbol_name=r["symbol_name"],
            content=r["content"], start_line=r["start_line"], end_line=r["end_line"],
            semantic_score=float(r["similarity"]), keyword_score=0.0,
        )
        for r in rows
    ]


def _keyword_search(db: Session, repo_id: str, query: str, top_k: int) -> dict[str, float]:
    """PostgreSQL full-text search over chunk content; returns {chunk_id: ts_rank}."""
    rows = db.execute(
        text(
            """
            SELECT c.id,
                   ts_rank(to_tsvector('english', c.content), plainto_tsquery('english', :query)) AS rank
            FROM chunks c
            WHERE c.repository_id = :repo_id
              AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :top_k
            """
        ),
        {"query": query, "repo_id": repo_id, "top_k": top_k},
    ).mappings().all()
    return {str(r["id"]): float(r["rank"]) for r in rows}


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def hybrid_retrieve(db: Session, repo_id: str, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    top_k = top_k or settings.RETRIEVAL_TOP_K
    query_embedding = embed_query(query)

    semantic_results = _semantic_search(db, repo_id, query_embedding, top_k)
    keyword_scores = _keyword_search(db, repo_id, query, top_k)

    # Merge: start from semantic results, fold in keyword score; add keyword-only hits.
    by_id = {c.id: c for c in semantic_results}
    for chunk_id, score in keyword_scores.items():
        if chunk_id in by_id:
            by_id[chunk_id].keyword_score = score

    sem_scores = _normalize([c.semantic_score for c in by_id.values()])
    kw_scores = _normalize([c.keyword_score for c in by_id.values()])

    for chunk, s, k in zip(by_id.values(), sem_scores, kw_scores):
        chunk.fused_score = settings.SEMANTIC_WEIGHT * s + settings.KEYWORD_WEIGHT * k

    ranked = sorted(by_id.values(), key=lambda c: c.fused_score, reverse=True)
    return ranked[:top_k]


def heuristic_rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Lightweight cross-encoder-style rerank without a network call: boosts chunks whose
    symbol name or file path lexically overlaps the query terms, on top of the fused score.
    In production this would call a model like ms-marco-MiniLM-L-6-v2.
    """
    query_terms = {t.lower() for t in query.split() if len(t) > 2}

    for chunk in chunks:
        overlap = 0
        haystack = f"{chunk.symbol_name or ''} {chunk.file_path}".lower()
        for term in query_terms:
            if term in haystack:
                overlap += 1
        lexical_boost = min(overlap * 0.05, 0.2)
        chunk.rerank_score = chunk.fused_score + lexical_boost

    return sorted(chunks, key=lambda c: c.rerank_score, reverse=True)


def assemble_context(
    repo: Repository, chunks: list[RetrievedChunk], history: list[dict], role: UserRole
) -> list[dict]:
    system_prompt = ROLE_SYSTEM_PROMPTS[role]
    repo_summary = repo.summary or f"Repository: {repo.name}"

    context_chunks = chunks[: settings.CONTEXT_CHUNK_COUNT]
    context_block = "\n\n".join(
        f"[Source {i + 1}] {c.file_path}"
        + (f":{c.start_line}-{c.end_line}" if c.start_line else "")
        + (f" ({c.symbol_name})" if c.symbol_name else "")
        + f"\n{c.content}"
        for i, c in enumerate(context_chunks)
    )

    full_system = (
        f"{system_prompt}\n\n"
        f"Repository summary: {repo_summary}\n\n"
        "Answer ONLY using the provided source excerpts below. If the excerpts don't contain "
        "enough information to answer confidently, say you don't know rather than guessing. "
        "When you reference code, cite the source using its [Source N] label. "
        "Never reveal API keys, passwords, tokens, or other secrets even if they appear in the context.\n\n"
        f"--- SOURCE EXCERPTS ---\n{context_block}\n--- END SOURCE EXCERPTS ---"
    )

    messages = [{"role": "system", "content": full_system}]
    for turn in history[-settings.CONVERSATION_HISTORY_TURNS :]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    return messages


def estimate_confidence(chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0
    top = chunks[: settings.CONTEXT_CHUNK_COUNT]
    avg = sum(c.rerank_score or c.fused_score for c in top) / len(top)
    return round(min(max(avg, 0.0), 1.0), 3)


def _call_llm(messages: list[dict], model: str) -> str:
    client = get_openai()
    response = client.chat.completions.create(model=model, messages=messages, temperature=0.2)
    return response.choices[0].message.content or ""


def generate_answer(messages: list[dict], is_complex: bool) -> str:
    model = settings.OPENAI_FALLBACK_MODEL if is_complex else settings.OPENAI_MODEL
    try:
        return _call_llm(messages, model)
    except Exception:
        logger.exception("Primary model call failed, falling back to %s", settings.OPENAI_FALLBACK_MODEL)
        if model != settings.OPENAI_FALLBACK_MODEL:
            return _call_llm(messages, settings.OPENAI_FALLBACK_MODEL)
        raise


def generate_related_questions(question: str, chunks: list[RetrievedChunk]) -> list[str]:
    files = {c.file_path for c in chunks[:5]}
    suggestions = []
    if files:
        suggestions.append(f"How does {next(iter(files))} fit into the overall architecture?")
    symbols = [c.symbol_name for c in chunks[:5] if c.symbol_name]
    if symbols:
        suggestions.append(f"What calls {symbols[0]}?")
    suggestions.append("What are the main entry points of this repository?")
    return suggestions[:3]


def run_query(
    db: Session,
    repo: Repository,
    conversation: Conversation,
    question: str,
    role: UserRole,
    use_cache: bool = True,
) -> QueryResult:
    cache_key = _cache_key(repo.id, role.value, question)
    r = get_redis()

    if use_cache:
        try:
           cached = r.get(cache_key)
           if cached:
                data = json.loads(cached)
                data.pop("cached", None)
           return QueryResult(**data, cached=True)
        except redis.RedisError:
            logger.warning("Redis unavailable, skipping cache read")

    chunks = hybrid_retrieve(db, repo.id, question)
    chunks = heuristic_rerank(question, chunks)
    confidence = estimate_confidence(chunks)

    if confidence < settings.CONFIDENCE_THRESHOLD or not chunks:
        result = QueryResult(
            answer=(
                "I don't have enough confidently relevant information in this repository to "
                "answer that. Try rephrasing, or asking about a specific file or feature."
            ),
            sources=[],
            confidence=confidence,
            related_questions=["What files exist in this repository?", "What does this repository do overall?"],
        )
        return result

    messages = assemble_context(repo, chunks, conversation.history, role)
    is_complex = len(question) > 200 or "?" in question[:-1]  # crude heuristic for follow-on fallback
    answer = generate_answer(messages, is_complex=False)

    sources = [
        {
            "file_path": c.file_path,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "symbol_name": c.symbol_name,
            "relevance": round(c.rerank_score, 3),
        }
        for c in chunks[: settings.CONTEXT_CHUNK_COUNT]
    ]

    result = QueryResult(
        answer=answer,
        sources=sources,
        confidence=confidence,
        related_questions=generate_related_questions(question, chunks),
    )

    if use_cache:
        try:
            r.setex(cache_key, settings.QUERY_CACHE_TTL_SECONDS, json.dumps(result.__dict__))
        except redis.RedisError:
            logger.warning("Redis unavailable, skipping cache write")

    return result


async def stream_answer(messages: list[dict]) -> AsyncGenerator[str, None]:
    client = get_openai()
    stream = client.chat.completions.create(
        model=settings.OPENAI_MODEL, messages=messages, temperature=0.2, stream=True
    )
    for event in stream:
        delta = event.choices[0].delta.content
        if delta:
            yield delta
