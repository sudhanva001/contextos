from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.database import get_db
from app.ingestion.service import ingest_repository_task, parse_repo_name
from app.models import File, IngestionJob, IngestionStatus, Repository, User

router = APIRouter(prefix="/v1/repos", tags=["repositories"])


class RepoCreateRequest(BaseModel):
    github_url: str

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        if "github.com" not in v:
            raise ValueError("Must be a GitHub repository URL")
        return v.rstrip("/")


class RepoResponse(BaseModel):
    id: str
    name: str
    github_url: str
    status: str
    summary: str | None
    language_stats: dict
    created_at: str

    class Config:
        from_attributes = True


class FileResponse(BaseModel):
    id: str
    path: str
    language: str | None
    size_bytes: int
    summary: str | None

    class Config:
        from_attributes = True


class RepoStatusResponse(BaseModel):
    repository: RepoResponse
    job: dict | None


def _to_repo_response(repo: Repository) -> RepoResponse:
    return RepoResponse(
        id=repo.id, name=repo.name, github_url=repo.github_url, status=repo.status.value,
        summary=repo.summary, language_stats=repo.language_stats or {},
        created_at=repo.created_at.isoformat(),
    )


@router.get("", response_model=list[RepoResponse])
def list_repos(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RepoResponse]:
    repos = db.query(Repository).filter(Repository.owner_id == user.id).order_by(Repository.created_at.desc()).all()
    return [_to_repo_response(r) for r in repos]


@router.post("", response_model=RepoResponse, status_code=201)
def submit_repo(
    body: RepoCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RepoResponse:
    existing = db.query(Repository).filter(
        Repository.owner_id == user.id, Repository.github_url == body.github_url
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Repository already submitted", headers={"X-Repo-Id": existing.id})

    repo = Repository(
        owner_id=user.id,
        organization_id=user.organization_id,
        github_url=body.github_url,
        name=parse_repo_name(body.github_url),
        status=IngestionStatus.PENDING,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    job = IngestionJob(repository_id=repo.id, status=IngestionStatus.PENDING)
    db.add(job)
    db.commit()
    db.refresh(job)

    ingest_repository_task.delay(repo.id, job.id)

    return _to_repo_response(repo)


@router.get("/{repo_id}", response_model=RepoStatusResponse)
def get_repo_status(
    repo_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RepoStatusResponse:
    repo = db.query(Repository).filter(Repository.id == repo_id, Repository.owner_id == user.id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.repository_id == repo.id)
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    job_dict = None
    if job:
        job_dict = {
            "status": job.status.value,
            "progress_pct": job.progress_pct,
            "current_step": job.current_step,
            "files_processed": job.files_processed,
            "files_total": job.files_total,
            "error_message": job.error_message,
        }

    return RepoStatusResponse(repository=_to_repo_response(repo), job=job_dict)


@router.get("/{repo_id}/files", response_model=list[FileResponse])
def list_repo_files(
    repo_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FileResponse]:
    repo = db.query(Repository).filter(Repository.id == repo_id, Repository.owner_id == user.id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    files = db.query(File).filter(File.repository_id == repo.id).order_by(File.path).all()
    return [FileResponse.model_validate(f) for f in files]
