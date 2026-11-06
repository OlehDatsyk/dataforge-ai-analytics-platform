"""Audit log, notifications, and the analysis history shown on the dashboard."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AnalysisResult, AuditLog, Notification


def audit(
    db: Session,
    action: str,
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """Record an operation. Details hold identifiers and counts only, never dataset contents."""
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
            ip_address=ip,
        )
    )


def notify(
    db: Session, workspace_id: str, user_id: str | None, title: str, *, kind: str = "info", body: str | None = None, link: str | None = None
) -> None:
    if user_id:
        db.add(Notification(workspace_id=workspace_id, user_id=user_id, title=title, kind=kind, body=body, link=link))


def record_analysis(
    db: Session,
    *,
    workspace_id: str,
    dataset_id: str | None,
    user_id: str | None,
    name: str,
    analysis_type: str,
    link: str | None = None,
    summary: dict | None = None,
    status: str = "completed",
) -> None:
    db.add(
        AnalysisResult(
            workspace_id=workspace_id,
            dataset_id=dataset_id,
            created_by=user_id,
            name=name[:300],
            analysis_type=analysis_type,
            link=link,
            summary=summary or {},
            status=status,
        )
    )
