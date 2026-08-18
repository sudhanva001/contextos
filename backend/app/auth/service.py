from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_EMAILS_URL = "https://api.github.com/user/emails"


class AuthError(Exception):
    pass


def build_github_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
        "scope": "read:user user:email repo",
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_github_user(code: str) -> dict:
    """Exchange the OAuth code for a GitHub access token, then fetch the profile."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_REDIRECT_URI,
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise AuthError(f"GitHub token exchange failed: {token_data}")

        gh_headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        user_resp = await client.get(GITHUB_USER_URL, headers=gh_headers)
        user_resp.raise_for_status()
        profile = user_resp.json()

        email = profile.get("email")
        if not email:
            emails_resp = await client.get(GITHUB_USER_EMAILS_URL, headers=gh_headers)
            if emails_resp.status_code == 200:
                emails = emails_resp.json()
                primary = next((e for e in emails if e.get("primary")), None)
                email = (primary or (emails[0] if emails else {})).get("email")

        return {
            "github_id": str(profile["id"]),
            "github_login": profile["login"],
            "email": email,
            "avatar_url": profile.get("avatar_url"),
            "github_access_token": access_token,
        }


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(user_id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: str) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")
    return payload["sub"]


def get_or_create_user(db: Session, github_profile: dict) -> User:
    user = db.query(User).filter(User.github_id == github_profile["github_id"]).first()
    if user is None:
        user = User(
            github_id=github_profile["github_id"],
            github_login=github_profile["github_login"],
            email=github_profile.get("email"),
            avatar_url=github_profile.get("avatar_url"),
        )
        db.add(user)
    else:
        user.github_login = github_profile["github_login"]
        user.email = github_profile.get("email") or user.email
        user.avatar_url = github_profile.get("avatar_url") or user.avatar_url
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user_id = decode_token(credentials.credentials, expected_type="access")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Reset daily quota if the reset window has passed.
    now = datetime.now(timezone.utc)
    if now - user.daily_query_reset_at > timedelta(days=1):
        user.daily_query_count = 0
        user.daily_query_reset_at = now
        db.commit()

    return user


def enforce_daily_quota(user: User, db: Session) -> None:
    if user.daily_query_count >= settings.DAILY_QUERY_QUOTA:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily query quota of {settings.DAILY_QUERY_QUOTA} reached. Try again tomorrow.",
        )
    user.daily_query_count += 1
    db.commit()
