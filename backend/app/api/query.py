from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.service import enforce_daily_quota, get_current_user
from app.database import get_db
from app.models import Conversation, IngestionStatus, Repository, User, UserRole
from app.query.service import assemble_context, generate_related_questions, heuristic_rerank, hybrid_retrieve, run_query, stream_answer

router = APIRouter(prefix="/v1/query", tags=["query"])


class QueryRequest(BaseModel):
    repository_id: str
    question: str
    role: UserRole = UserRole.DEVELOPER
    conversation_id: str | None = None
    stream: bool = False


class QueryResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[dict]
    confidence: float
    related_questions: list[str]
    cached: bool


def _get_repo_scoped(db: Session, repo_id: str, user: User) -> Repository:
    """Enforce tenant isolation: a user may only query repositories they own."""
    repo = db.query(Repository).filter(Repository.id == repo_id, Repository.owner_id == user.id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != IngestionStatus.COMPLETE:
        raise HTTPException(status_code=409, detail=f"Repository ingestion is {repo.status.value}, not ready for queries")
    return repo


def _get_or_create_conversation(
    db: Session, user: User, repo: Repository, conversation_id: str | None, role: UserRole
) -> Conversation:
    if conversation_id:
        convo = db.query(Conversation).filter(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return convo

    convo = Conversation(user_id=user.id, repository_id=repo.id, role=role, history=[])
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


@router.post("", response_model=QueryResponse)
def query_repository(
    body: QueryRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> QueryResponse:
    repo = _get_repo_scoped(db, body.repository_id, user)
    enforce_daily_quota(user, db)
    convo = _get_or_create_conversation(db, user, repo, body.conversation_id, body.role)

    result = run_query(db, repo, convo, body.question, body.role)

    convo.history = (convo.history or []) + [
        {"role": "user", "content": body.question},
        {"role": "assistant", "content": result.answer},
    ]
    if convo.title is None:
        convo.title = body.question[:80]
    db.commit()

    return QueryResponse(
        conversation_id=convo.id,
        answer=result.answer,
        sources=result.sources,
        confidence=result.confidence,
        related_questions=result.related_questions,
        cached=result.cached,
    )


@router.post("/stream")
async def query_repository_stream(
    body: QueryRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    repo = _get_repo_scoped(db, body.repository_id, user)
    enforce_daily_quota(user, db)
    convo = _get_or_create_conversation(db, user, repo, body.conversation_id, body.role)

    chunks = hybrid_retrieve(db, repo.id, body.question)
    chunks = heuristic_rerank(body.question, chunks)
    messages = assemble_context(repo, chunks, convo.history, body.role)
    related = generate_related_questions(body.question, chunks)

    async def event_generator():
        collected = []
        async for token in stream_answer(messages):
            collected.append(token)
            yield token

        full_answer = "".join(collected)
        convo.history = (convo.history or []) + [
            {"role": "user", "content": body.question},
            {"role": "assistant", "content": full_answer},
        ]
        if convo.title is None:
            convo.title = body.question[:80]
        db.commit()

    return StreamingResponse(event_generator(), media_type="text/plain")
