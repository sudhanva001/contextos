import logging

from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    """
    Lazily load the local embedding model. Runs entirely on CPU, no API key or billing
    required at inference time (the model weights are downloaded once, on first use, from
    Hugging Face's public model hub and then cached on disk inside the container).
    """
    global _model
    if _model is None:
        logger.info("Loading local embedding model %s (first run downloads ~90MB)", settings.EMBEDDING_MODEL)
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts locally, in batches, truncating long inputs."""
    if not texts:
        return []

    model = get_embedding_model()
    truncated = [t[: settings.MAX_CHUNK_CHARS] for t in texts]

    embeddings: list[list[float]] = []
    batch_size = settings.EMBEDDING_BATCH_SIZE
    for i in range(0, len(truncated), batch_size):
        batch = truncated[i : i + batch_size]
        vectors = model.encode(batch, convert_to_numpy=True, show_progress_bar=False)
        embeddings.extend([v.tolist() for v in vectors])
        logger.info("Embedded batch %d-%d of %d", i, i + len(batch), len(truncated))

    return embeddings


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
