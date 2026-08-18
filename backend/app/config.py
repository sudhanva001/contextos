from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    APP_NAME: str = "ContextOS"
    DEBUG: bool = True
    ENV: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://contextos:contextos@db:5432/contextos"
    REDIS_URL: str = "redis://redis:6379/0"

    # LLM (chat) — defaults to Groq's free, OpenAI-compatible API so no billing is required.
    # To use real OpenAI instead: set OPENAI_BASE_URL="" and OPENAI_API_KEY to a paid key.
    OPENAI_API_KEY: str = ""  # used as the bearer token for whichever OPENAI_BASE_URL is set below
    OPENAI_BASE_URL: str = "https://api.groq.com/openai/v1"
    OPENAI_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_FALLBACK_MODEL: str = "llama-3.1-8b-instant"

    # Embeddings — local, free, no API key needed (runs on CPU via sentence-transformers).
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # GitHub OAuth
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:5173/auth/callback"

    # JWT
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # RAG / retrieval tuning
    SEMANTIC_WEIGHT: float = 0.6
    KEYWORD_WEIGHT: float = 0.4
    RETRIEVAL_TOP_K: int = 20
    CONTEXT_CHUNK_COUNT: int = 8
    CONFIDENCE_THRESHOLD: float = 0.6
    CONVERSATION_HISTORY_TURNS: int = 10

    # Limits
    DAILY_QUERY_QUOTA: int = 100
    QUERY_CACHE_TTL_SECONDS: int = 900  # 15 min
    EMBEDDING_BATCH_SIZE: int = 100
    MAX_CHUNK_CHARS: int = 8000

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
