"""Report generation and export."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import WorkspaceContext, client_ip, editor_context, get_ready_dataset, get_version, version_schema, workspace_context
from ..models import DataProfile, Dataset, Report
from ..services import storage
from ..services.activity import audit, notify, record_analysis
from ..services.exports import tables_to_csv, tables_to_xlsx
from ..services.report_pdf import render_pdf
from ..services.reports import REPORT_TYPES, ReportError, build_report, report_tables

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportRequest(BaseModel):
    dataset_id: str
    report_type: str
    title: str | None = Field(default=None, max_length=200)
    questions: list[str] | None = Field(default=None, max_length=5)


def _summary(report: Report, dataset_name: str | None = None) -> dict:
    return {"id": report.id, "title": report.title, "report_type": report.report_type, "report_type_label": REPORT_TYPES.get(report.report_type, report.report_type), "dataset_id": report.dataset_id, "dataset_name": dataset_name, "status": report.status, "is_demo": report.content.get("is_demo", False), "created_at": report.created_at}


@router.get("/types")
def report_types(_ctx: WorkspaceContext = Depends(workspace_context)):
    return [{"id": key, "label": label} for key, label in REPORT_TYPES.items()]


@router.get("")
def list_reports(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    rows = db.execute(select(Report, Dataset.name).join(Dataset, Dataset.id == Report.dataset_id).where(Report.workspace_id == ctx.id).order_by(Report.created_at.desc())).all()
    return [_summary(r, name) for r, name in rows]


@router.post("", status_code=201)
def create_report(body: ReportRequest, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    dataset = get_ready_dataset(db, ctx, body.dataset_id)
    version = get_version(db, dataset)
    stored = db.scalar(select(DataProfile).where(DataProfile.version_id == version.id))
    try:
        content = build_report(body.report_type, title=(body.title or "").strip() or None, workspace_name=ctx.workspace.name, dataset_name=dataset.name, version_number=version.version_number,
                               is_demo=dataset.is_demo, schema=version_schema(db, version), path=storage.resolve_ref(version.storage_ref), profile=stored.profile, quality=stored.quality, questions=body.questions)
    except ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = Report(workspace_id=ctx.id, dataset_id=dataset.id, created_by=ctx.user.id, title=content["title"], report_type=body.report_type, content=content)
    db.add(report)
    db.flush()
    dataset.last_analysed_at = utcnow()
    record_analysis(db, workspace_id=ctx.id, dataset_id=dataset.id, user_id=ctx.user.id, name=report.title, analysis_type="report", link=f"/reports/{report.id}", summary={"type": body.report_type})
    notify(db, ctx.id, ctx.user.id, f"Report ready: {report.title}", kind="success", link=f"/reports/{report.id}")
    audit(db, "report.generated", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="report", entity_id=report.id, detail={"type": body.report_type}, ip=client_ip(request))
    db.commit()
    return _summary(report, dataset.name)


def _get_report(db: Session, ctx: WorkspaceContext, report_id: str) -> Report:
    report = db.scalar(select(Report).where(Report.id == report_id, Report.workspace_id == ctx.id))
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.get("/{report_id}")
def get_report(report_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    report = _get_report(db, ctx, report_id)
    return {**_summary(report), "content": report.content}


@router.delete("/{report_id}")
def delete_report(report_id: str, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    report = _get_report(db, ctx, report_id)
    audit(db, "report.deleted", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="report", entity_id=report.id, ip=client_ip(request))
    db.delete(report)
    db.commit()
    return {"ok": True}


@router.get("/{report_id}/export/{file_format}")
def export_report(report_id: str, file_format: Literal["pdf", "csv", "xlsx"], request: Request, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    report = _get_report(db, ctx, report_id)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", report.title)[:80] or "report"
    audit(db, "report.exported", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="report", entity_id=report.id, detail={"format": file_format}, ip=client_ip(request))
    db.commit()
    if file_format == "pdf":
        body, media = render_pdf(report.content), "application/pdf"
    elif file_format == "csv":
        body, media = tables_to_csv(report_tables(report.content)).encode("utf-8-sig"), "text/csv; charset=utf-8"
    else:
        body, media = tables_to_xlsx(report_tables(report.content)), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}.{file_format}"'})
