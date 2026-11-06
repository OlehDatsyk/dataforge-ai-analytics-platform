"""Workspaces, members, projects, and the audit trail."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ROLE_RANK, WorkspaceContext, admin_context, client_ip, current_user, editor_context, workspace_context
from ..models import AuditLog, Dataset, Project, User, Workspace, WorkspaceMember
from ..services import storage
from ..services.activity import audit

router = APIRouter(tags=["Workspaces"])


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberAdd(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"


class MemberUpdate(BaseModel):
    role: Literal["admin", "member", "viewer"]


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/workspaces")
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at)).all()
    return [{"id": m.workspace.id, "name": m.workspace.name, "role": m.role} for m in members]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = Workspace(name=body.name.strip(), created_by=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    audit(db, "workspace.created", workspace_id=workspace.id, user_id=user.id, entity_type="workspace", entity_id=workspace.id, ip=client_ip(request))
    db.commit()
    return {"id": workspace.id, "name": workspace.name, "role": "owner"}


@router.patch("/workspaces/current")
def rename_workspace(body: WorkspaceBody, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    ctx.workspace.name = body.name.strip()
    audit(db, "workspace.renamed", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="workspace", entity_id=ctx.id, ip=client_ip(request))
    db.commit()
    return {"id": ctx.id, "name": ctx.workspace.name, "role": ctx.role}


@router.delete("/workspaces/current")
def delete_workspace(request: Request, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    ctx.require("owner")
    memberships = db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == ctx.user.id))
    if memberships <= 1:
        raise HTTPException(status_code=409, detail="You cannot delete your only workspace.")
    for dataset in db.scalars(select(Dataset).where(Dataset.workspace_id == ctx.id)).all():
        storage.delete_dataset_files(ctx.id, dataset.id)
    audit(db, "workspace.deleted", user_id=ctx.user.id, entity_type="workspace", entity_id=ctx.id, detail={"name": ctx.workspace.name}, ip=client_ip(request))
    db.delete(ctx.workspace)
    db.commit()
    return {"ok": True}


@router.get("/workspaces/current/members")
def list_members(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.id).order_by(WorkspaceMember.created_at)).all()
    return [{"id": m.id, "user_id": m.user_id, "email": m.user.email, "full_name": m.user.full_name, "role": m.role, "joined_at": m.created_at} for m in members]


@router.post("/workspaces/current/members", status_code=201)
def add_member(body: MemberAdd, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise HTTPException(status_code=404, detail="No account uses that email. The person must register first.")
    if db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.id, WorkspaceMember.user_id == user.id)):
        raise HTTPException(status_code=409, detail="That person is already a member.")
    member = WorkspaceMember(workspace_id=ctx.id, user_id=user.id, role=body.role)
    db.add(member)
    audit(db, "member.added", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="user", entity_id=user.id, detail={"role": body.role}, ip=client_ip(request))
    db.commit()
    return {"id": member.id, "user_id": user.id, "email": user.email, "full_name": user.full_name, "role": member.role}


def _member(db: Session, ctx: WorkspaceContext, member_id: str) -> WorkspaceMember:
    member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == ctx.id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if ROLE_RANK[member.role] >= ROLE_RANK["owner"] or (member.role == "admin" and ctx.role != "owner"):
        raise HTTPException(status_code=403, detail="You cannot change this member.")
    return member


@router.patch("/workspaces/current/members/{member_id}")
def update_member(member_id: str, body: MemberUpdate, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    member = _member(db, ctx, member_id)
    member.role = body.role
    audit(db, "member.role_changed", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="user", entity_id=member.user_id, detail={"role": body.role}, ip=client_ip(request))
    db.commit()
    return {"id": member.id, "role": member.role}


@router.delete("/workspaces/current/members/{member_id}")
def remove_member(member_id: str, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    member = _member(db, ctx, member_id)
    audit(db, "member.removed", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="user", entity_id=member.user_id, ip=client_ip(request))
    db.delete(member)
    db.commit()
    return {"ok": True}


@router.get("/projects")
def list_projects(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Project, func.count(Dataset.id)).outerjoin(Dataset, Dataset.project_id == Project.id).where(Project.workspace_id == ctx.id).group_by(Project.id).order_by(Project.name)
    ).all()
    return [{"id": p.id, "name": p.name, "dataset_count": count} for p, count in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectBody, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    name = body.name.strip()
    if db.scalar(select(Project).where(Project.workspace_id == ctx.id, Project.name == name)):
        raise HTTPException(status_code=409, detail="A project with this name already exists.")
    project = Project(workspace_id=ctx.id, name=name)
    db.add(project)
    db.commit()
    return {"id": project.id, "name": project.name, "dataset_count": 0}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(Project.id == project_id, Project.workspace_id == ctx.id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    db.delete(project)  # its datasets remain and return to "no project"
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(limit: int = 100, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    rows = db.execute(
        select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).where(AuditLog.workspace_id == ctx.id).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500))
    ).all()
    return [{"id": log.id, "action": log.action, "entity_type": log.entity_type, "entity_id": log.entity_id, "detail": log.detail, "ip_address": log.ip_address, "user_email": email, "created_at": log.created_at} for log, email in rows]
