"""Dashboard metrics, activity, global search, and notifications."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import WorkspaceContext, workspace_context
from ..models import AIConversation, AnalysisResult, AnomalyResult, Dataset, Notification, Report, Visualisation

router = APIRouter(tags=["Overview"])
RANGES = {"24h": (timedelta(hours=24), "hour"), "7d": (timedelta(days=7), "day"), "30d": (timedelta(days=30), "day")}


@router.get("/overview")
def overview(activity_range: Literal["24h", "7d", "30d"] = "7d", ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """All figures are direct counts of this workspace's records."""
    workspace = ctx.id

    def count(model, *conditions) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.workspace_id == workspace, *conditions)) or 0

    window, unit = RANGES[activity_range]
    now = utcnow()
    since = now - window
    timestamps = db.scalars(select(AnalysisResult.created_at).where(AnalysisResult.workspace_id == workspace, AnalysisResult.created_at >= since)).all()
    buckets: dict[str, int] = {}
    if unit == "hour":
        cursor = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
        for i in range(24):
            buckets[(cursor + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00")] = 0
    else:
        days = window.days
        cursor = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        for i in range(days):
            buckets[(cursor + timedelta(days=i)).strftime("%Y-%m-%d")] = 0
    for stamp in timestamps:
        key = stamp.strftime("%Y-%m-%dT%H:00") if unit == "hour" else stamp.strftime("%Y-%m-%d")
        if key in buckets:
            buckets[key] += 1

    datasets = db.scalars(select(Dataset).where(Dataset.workspace_id == workspace).order_by(Dataset.created_at.desc()).limit(6)).all()
    analyses = db.execute(
        select(AnalysisResult, Dataset.name).outerjoin(Dataset, Dataset.id == AnalysisResult.dataset_id).where(AnalysisResult.workspace_id == workspace).order_by(AnalysisResult.created_at.desc()).limit(8)
    ).all()
    records = db.scalar(select(func.coalesce(func.sum(Dataset.row_count), 0)).where(Dataset.workspace_id == workspace, Dataset.status == "ready")) or 0
    return {
        "metrics": {
            "total_datasets": count(Dataset),
            "records_analysed": int(records),
            "total_analyses": count(AnalysisResult),
            "active_reports": count(Report),
            "detected_anomalies": count(AnomalyResult, AnomalyResult.status.in_(["open", "investigating"])),
            "recent_activity": count(AnalysisResult, AnalysisResult.created_at >= now - timedelta(days=1)),
            "demo_datasets": count(Dataset, Dataset.is_demo.is_(True)),
        },
        "activity": {"range": activity_range, "unit": unit, "points": [{"period": k, "count": v} for k, v in buckets.items()]},
        "datasets": [
            {"id": d.id, "name": d.name, "file_format": d.file_format, "row_count": d.row_count, "column_count": d.column_count, "created_at": d.created_at, "status": d.status, "last_analysed_at": d.last_analysed_at, "is_demo": d.is_demo, "source_type": d.source_type}
            for d in datasets
        ],
        "analyses": [
            {"id": a.id, "name": a.name, "dataset_name": name, "dataset_id": a.dataset_id, "analysis_type": a.analysis_type, "status": a.status, "created_at": a.created_at, "link": a.link}
            for a, name in analyses
        ],
    }


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=100), ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """Search names and titles of workspace items. Dataset contents are not searched here."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    results = []
    for dataset in db.scalars(select(Dataset).where(Dataset.workspace_id == ctx.id, or_(Dataset.name.ilike(pattern, escape="\\"), Dataset.original_filename.ilike(pattern, escape="\\"))).limit(6)).all():
        results.append({"type": "Dataset", "title": dataset.name, "link": f"/explorer?dataset={dataset.id}"})
    for report in db.scalars(select(Report).where(Report.workspace_id == ctx.id, Report.title.ilike(pattern, escape="\\")).limit(5)).all():
        results.append({"type": "Report", "title": report.title, "link": f"/reports/{report.id}"})
    for viz in db.scalars(select(Visualisation).where(Visualisation.workspace_id == ctx.id, Visualisation.name.ilike(pattern, escape="\\")).limit(5)).all():
        results.append({"type": "Visualisation", "title": viz.name, "link": f"/visualisations?saved={viz.id}"})
    for chat in db.scalars(select(AIConversation).where(AIConversation.workspace_id == ctx.id, AIConversation.user_id == ctx.user.id, AIConversation.title.ilike(pattern, escape="\\")).limit(5)).all():
        results.append({"type": "Conversation", "title": chat.title, "link": f"/analyst?conversation={chat.id}"})
    return results


@router.get("/notifications")
def notifications(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.workspace_id == ctx.id, Notification.user_id == ctx.user.id).order_by(Notification.created_at.desc()).limit(30)).all()
    return {
        "unread": sum(1 for n in rows if n.read_at is None),
        "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "read": n.read_at is not None, "created_at": n.created_at} for n in rows],
    }


@router.post("/notifications/read-all")
def read_all(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.workspace_id == ctx.id, Notification.user_id == ctx.user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"ok": True}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.workspace_id == ctx.id, Notification.user_id == ctx.user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    item.read_at = utcnow()
    db.commit()
    return {"ok": True}
