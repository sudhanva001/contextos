from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.database import get_db
from app.models import Conversation, User

router = APIRouter(prefix="/v1", tags=["users"])


class MeResponse(BaseModel):
    id: str
    github_login: str
    email: str | None
    avatar_url: str | None
    default_role: str
    daily_query_count: int


class ConversationSummary(BaseModel):
    id: str
    repository_id: str
    role: str
    title: str | None
    updated_at: str
    turn_count: int


@router.get("/users/me", response_model=MeResponse)
def get_me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id, github_login=user.github_login, email=user.email,
        avatar_url=user.avatar_url, default_role=user.default_role.value,
        daily_query_count=user.daily_query_count,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    repository_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConversationSummary]:
    query = db.query(Conversation).filter(Conversation.user_id == user.id)
    if repository_id:
        query = query.filter(Conversation.repository_id == repository_id)
    conversations = query.order_by(Conversation.updated_at.desc()).all()

    return [
        ConversationSummary(
            id=c.id, repository_id=c.repository_id, role=c.role.value, title=c.title,
            updated_at=c.updated_at.isoformat(), turn_count=len(c.history or []) // 2,
        )
        for c in conversations
    ]


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    convo = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == user.id
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "id": convo.id, "repository_id": convo.repository_id, "role": convo.role.value,
        "title": convo.title, "history": convo.history,
    }
