import logging
import os
import pathlib
import shutil
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

import git

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.ingestion import parser
from app.ingestion.embeddings import embed_texts
from app.models import Chunk, File, IngestionJob, IngestionStatus, Repository

logger = logging.getLogger(__name__)


def parse_repo_name(github_url: str) -> str:
    path = urlparse(github_url).path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path.split("/")[-1] or path


def _load_gitignore_patterns(repo_root: str) -> list[str]:
    gitignore_path = os.path.join(repo_root, ".gitignore")
    if not os.path.exists(gitignore_path):
        return []
    with open(gitignore_path, encoding="utf-8", errors="ignore") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    parts = pathlib.PurePosixPath(rel_path).parts
    if any(part in parser.DEFAULT_IGNORED_DIRS for part in parts):
        return True
    for pattern in patterns:
        clean = pattern.rstrip("/")
        if pathlib.PurePosixPath(rel_path).match(clean) or clean in parts:
            return True
    return False


def clone_repository(github_url: str, dest_dir: str) -> str:
    """Shallow clone (depth=1) the repository into dest_dir."""
    logger.info("Cloning %s (depth=1) into %s", github_url, dest_dir)
    git.Repo.clone_from(github_url, dest_dir, depth=1, single_branch=True)
    return dest_dir


def walk_repository_files(repo_root: str) -> list[str]:
    """Return relative paths of all text (non-binary, non-ignored) files under the size cap."""
    patterns = _load_gitignore_patterns(repo_root)
    results: list[str] = []

    for root, dirs, files in os.walk(repo_root):
        rel_root = os.path.relpath(root, repo_root)
        dirs[:] = [d for d in dirs if not _is_ignored(os.path.join(rel_root, d), patterns)]

        for fname in files:
            rel_path = os.path.normpath(os.path.join(rel_root, fname)).replace("\\", "/")
            if _is_ignored(rel_path, patterns):
                continue
            if parser.is_binary_path(rel_path):
                continue
            full_path = os.path.join(root, fname)
            try:
                if os.path.getsize(full_path) > parser.MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue
            results.append(rel_path)

    return results


def _update_job(db, job: IngestionJob, **fields) -> None:
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


@celery_app.task(bind=True, name="ingest_repository")
def ingest_repository_task(self, repository_id: str, job_id: str) -> None:
    db = SessionLocal()
    tmp_dir = tempfile.mkdtemp(prefix="contextos_repo_")

    try:
        repo: Repository = db.query(Repository).filter(Repository.id == repository_id).one()
        job: IngestionJob = db.query(IngestionJob).filter(IngestionJob.id == job_id).one()

        _update_job(
            db, job,
            status=IngestionStatus.CLONING, current_step="Cloning repository",
            started_at=datetime.now(timezone.utc), celery_task_id=self.request.id,
        )
        repo.status = IngestionStatus.CLONING
        db.commit()

        clone_repository(repo.github_url, tmp_dir)

        _update_job(db, job, status=IngestionStatus.PARSING, current_step="Scanning files")
        repo.status = IngestionStatus.PARSING
        db.commit()

        rel_paths = walk_repository_files(tmp_dir)
        job.files_total = len(rel_paths)
        db.commit()

        language_counts: dict[str, int] = {}
        secret_findings_count = 0
        pending_chunks: list[tuple[str, parser.CodeChunk]] = []  # (file_id, chunk)

        for idx, rel_path in enumerate(rel_paths):
            full_path = os.path.join(tmp_dir, rel_path)
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            findings = parser.scan_for_secrets(rel_path, content)
            if findings:
                secret_findings_count += len(findings)
                content = parser.redact_secrets(content)
                logger.warning("Redacted %d potential secret(s) in %s", len(findings), rel_path)

            language = parser.detect_language(rel_path)
            if language:
                language_counts[language] = language_counts.get(language, 0) + 1

            file_row = File(
                repository_id=repo.id,
                path=rel_path,
                language=language,
                size_bytes=len(content.encode("utf-8")),
            )
            db.add(file_row)
            db.flush()  # get file_row.id without committing

            for chunk in parser.chunk_source_file(rel_path, content, language):
                pending_chunks.append((file_row.id, chunk))

            job.files_processed = idx + 1
            job.progress_pct = int(((idx + 1) / max(len(rel_paths), 1)) * 60)  # parsing = 0-60%
            if idx % 25 == 0:
                db.commit()

        db.commit()

        _update_job(
            db, job,
            status=IngestionStatus.EMBEDDING,
            current_step=f"Generating embeddings for {len(pending_chunks)} chunks",
            progress_pct=60,
        )
        repo.status = IngestionStatus.EMBEDDING
        db.commit()

        batch_size = settings.EMBEDDING_BATCH_SIZE
        for i in range(0, len(pending_chunks), batch_size):
            batch = pending_chunks[i : i + batch_size]
            texts = [c.content for _, c in batch]
            vectors = embed_texts(texts)

            for (file_id, chunk), vector in zip(batch, vectors):
                db.add(
                    Chunk(
                        file_id=file_id,
                        repository_id=repo.id,
                        chunk_type=chunk.chunk_type,
                        symbol_name=chunk.symbol_name,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        metadata_=chunk.metadata,
                        embedding=vector,
                    )
                )
            db.commit()

            job.progress_pct = 60 + int(((i + len(batch)) / max(len(pending_chunks), 1)) * 40)
            db.commit()

        repo.language_stats = language_counts
        repo.name = repo.name or parse_repo_name(repo.github_url)
        repo.summary = _build_repo_summary(repo.name, language_counts, len(rel_paths))
        repo.status = IngestionStatus.COMPLETE
        db.commit()

        _update_job(
            db, job,
            status=IngestionStatus.COMPLETE, current_step="Complete", progress_pct=100,
            completed_at=datetime.now(timezone.utc),
        )

        if secret_findings_count:
            logger.warning(
                "Repository %s ingested with %d redacted secret(s)", repo.id, secret_findings_count
            )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingestion failed for repository %s", repository_id)
        db.rollback()
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if repo:
            repo.status = IngestionStatus.FAILED
        if job:
            job.status = IngestionStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        db.close()


def _build_repo_summary(name: str, language_counts: dict[str, int], file_count: int) -> str:
    if not language_counts:
        top_langs = "no recognized source languages"
    else:
        ranked = sorted(language_counts.items(), key=lambda kv: kv[1], reverse=True)
        top_langs = ", ".join(f"{lang} ({count} files)" for lang, count in ranked[:5])
    return f"{name}: {file_count} files ingested. Primary languages: {top_langs}."
