import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import service
from app.database import get_db

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class GithubUrlResponse(BaseModel):
    authorize_url: str
    state: str


class CallbackRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/github", response_model=GithubUrlResponse)
def get_github_oauth_url() -> GithubUrlResponse:
    state = secrets.token_urlsafe(24)
    return GithubUrlResponse(authorize_url=service.build_github_authorize_url(state), state=state)


@router.post("/callback", response_model=TokenResponse)
async def github_callback(body: CallbackRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        profile = await service.exchange_code_for_github_user(body.code)
    except service.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user = service.get_or_create_user(db, profile)
    access_token = service.create_access_token(user.id)
    refresh_token = service.create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "github_login": user.github_login,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "default_role": user.default_role.value,
        },
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(body: RefreshRequest) -> RefreshResponse:
    user_id = service.decode_token(body.refresh_token, expected_type="refresh")
    return RefreshResponse(access_token=service.create_access_token(user_id))
