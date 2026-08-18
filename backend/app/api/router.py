from fastapi import APIRouter

from app.api import query, repos, users
from app.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router.router)
api_router.include_router(repos.router)
api_router.include_router(query.router)
api_router.include_router(users.router)


@api_router.get("/v1/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok"}
