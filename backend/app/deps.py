"""Request dependencies: authentication, CSRF, workspace authorisation, and tenant-scoped lookups."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, utcnow
from .models import Dataset, DatasetColumn, DatasetVersion, User, UserSession, Workspace, WorkspaceMember
from .security import CSRF_HEADER, SESSION_COOKIE, csrf_is_valid, hash_token, rate_limiter

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, bucket: str, limit: int) -> None:
    if not rate_limiter.allow(f"{bucket}:{client_ip(request)}", limit):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None or session.expires_at <= utcnow() or not session.user.is_active:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    if request.method in UNSAFE_METHODS and not csrf_is_valid(token, request.headers.get(CSRF_HEADER)):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")
    return session.user


@dataclass
class WorkspaceContext:
    user: User
    workspace: Workspace
    role: str

    @property
    def id(self) -> str:
        return self.workspace.id

    def require(self, minimum: str) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"This action requires the {minimum} role or higher.")


def workspace_context(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    x_workspace_id: str | None = Header(default=None),
) -> WorkspaceContext:
    """Resolve the workspace for this request. Only workspaces the user belongs to are reachable."""
    query = select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    if x_workspace_id:
        query = query.where(WorkspaceMember.workspace_id == x_workspace_id)
    member = db.scalars(query.order_by(WorkspaceMember.created_at)).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceContext(user=user, workspace=member.workspace, role=member.role)


def editor_context(ctx: WorkspaceContext = Depends(workspace_context)) -> WorkspaceContext:
    ctx.require("member")
    return ctx


def admin_context(ctx: WorkspaceContext = Depends(workspace_context)) -> WorkspaceContext:
    ctx.require("admin")
    return ctx


def get_dataset(db: Session, ctx: WorkspaceContext, dataset_id: str) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.workspace_id == ctx.id))
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


def get_ready_dataset(db: Session, ctx: WorkspaceContext, dataset_id: str) -> Dataset:
    dataset = get_dataset(db, ctx, dataset_id)
    if dataset.status != "ready" or not dataset.current_version_id:
        raise HTTPException(status_code=409, detail=f"Dataset is not ready (status: {dataset.status}).")
    return dataset


def get_version(db: Session, dataset: Dataset, version_id: str | None = None) -> DatasetVersion:
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == (version_id or dataset.current_version_id), DatasetVersion.dataset_id == dataset.id
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    return version


def version_schema(db: Session, version: DatasetVersion) -> list[dict]:
    rows = db.scalars(
        select(DatasetColumn).where(DatasetColumn.version_id == version.id).order_by(DatasetColumn.position)
    ).all()
    return [
        {"name": c.name, "type": c.data_type, "missing": c.missing_count, "unique": c.unique_count} for c in rows
    ]
