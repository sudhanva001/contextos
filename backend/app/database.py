from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _register_pgvector(dbapi_connection, connection_record):
    """Ensure the pgvector extension + adapter is available on every new connection."""
    try:
        from pgvector.psycopg2 import register_vector

        register_vector(dbapi_connection)
    except Exception:
        # pgvector extension may not be created yet on first boot; init_db() handles that.
        pass


def init_db() -> None:
    """Create the pgvector extension, then create all tables. Called once on startup."""
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()

    Base.metadata.create_all(bind=engine)

    # HNSW index for fast approximate nearest-neighbor search on chunk embeddings.
    with engine.connect() as conn:
        conn.exec_driver_sql(
            """
            CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
            ON chunks USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.exec_driver_sql(
            """
            CREATE INDEX IF NOT EXISTS chunks_content_tsv_idx
            ON chunks USING gin (to_tsvector('english', content))
            """
        )
        conn.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
