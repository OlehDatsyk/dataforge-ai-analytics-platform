"""Anomaly Detection: scans, results, review status, record inspection, and chart data."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..db import get_db, new_id, utcnow
from ..deps import WorkspaceContext, client_ip, editor_context, get_ready_dataset, get_version, version_schema, workspace_context
from ..models import AnomalyResult, AnomalyRun, Dataset
from ..services import storage
from ..services.activity import audit, notify, record_analysis
from ..services.anomaly import run_detection
from ..services.frames import NUMERIC_TYPES, json_safe, read_frame
from ..services.query_engine import Filter, column_map, connect, fetch_rows, quote, run_query

router = APIRouter(prefix="/anomalies", tags=["Anomaly Detection"])


class ScanRequest(BaseModel):
    dataset_id: str
    columns: list[str] | None = Field(default=None, max_length=100)


class StatusUpdate(BaseModel):
    status: Literal["open", "investigating", "expected", "resolved"]


def _run_payload(run: AnomalyRun, dataset_name: str | None = None) -> dict:
    return {"id": run.id, "dataset_id": run.dataset_id, "dataset_name": dataset_name, "version_id": run.version_id, "status": run.status, "summary": run.summary, "created_at": run.created_at}


def _result_payload(item: AnomalyResult) -> dict:
    return {k: getattr(item, k) for k in ("id", "run_id", "dataset_id", "row_id", "period", "column_name", "kind", "method", "observed", "observed_value", "expected_low", "expected_high", "baseline", "score", "severity", "explanation", "status", "created_at")}


@router.post("/run", status_code=201)
def run_scan(body: ScanRequest, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    dataset = get_ready_dataset(db, ctx, body.dataset_id)
    version = get_version(db, dataset)
    schema = version_schema(db, version)
    names = column_map(schema)
    for name in body.columns or []:
        if name not in names:
            raise HTTPException(status_code=422, detail=f"Column '{name}' does not exist in this dataset.")
    frame = read_frame(storage.resolve_ref(version.storage_ref), keep_row_id=True)
    detected = run_detection(frame, schema, columns=body.columns)
    run = AnomalyRun(id=new_id(), workspace_id=ctx.id, dataset_id=dataset.id, version_id=version.id, created_by=ctx.user.id, config={"columns": body.columns}, summary=detected["summary"])
    db.add(run)
    db.flush()
    for finding in detected["findings"]:
        db.add(AnomalyResult(run_id=run.id, workspace_id=ctx.id, dataset_id=dataset.id, **finding))
    dataset.last_analysed_at = utcnow()
    total = detected["summary"]["total"]
    record_analysis(db, workspace_id=ctx.id, dataset_id=dataset.id, user_id=ctx.user.id, name=f"Anomaly scan: {dataset.name}", analysis_type="anomaly_scan", link=f"/anomalies?dataset={dataset.id}", summary={"total": total})
    notify(db, ctx.id, ctx.user.id, f"Anomaly scan finished: {dataset.name}", kind="warning" if detected["summary"]["by_severity"]["high"] else "info", body=f"{total:,} items flagged for review.", link=f"/anomalies?dataset={dataset.id}")
    audit(db, "anomaly.scan", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"flagged": total}, ip=client_ip(request))
    db.commit()
    return _run_payload(run, dataset.name)


@router.get("/runs")
def list_runs(dataset_id: str | None = None, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    query = select(AnomalyRun, Dataset.name).join(Dataset, Dataset.id == AnomalyRun.dataset_id).where(AnomalyRun.workspace_id == ctx.id)
    if dataset_id:
        query = query.where(AnomalyRun.dataset_id == dataset_id)
    rows = db.execute(query.order_by(AnomalyRun.created_at.desc()).limit(50)).all()
    return [_run_payload(r, name) for r, name in rows]


def _get_run(db: Session, ctx: WorkspaceContext, run_id: str) -> AnomalyRun:
    run = db.scalar(select(AnomalyRun).where(AnomalyRun.id == run_id, AnomalyRun.workspace_id == ctx.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Anomaly scan not found.")
    return run


@router.get("/runs/{run_id}/results")
def list_results(
    run_id: str,
    column: str | None = None,
    method: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    ctx: WorkspaceContext = Depends(workspace_context),
    db: Session = Depends(get_db),
):
    run = _get_run(db, ctx, run_id)
    query = select(AnomalyResult).where(AnomalyResult.run_id == run.id)
    for attribute, value in ((AnomalyResult.column_name, column), (AnomalyResult.method, method), (AnomalyResult.severity, severity), (AnomalyResult.status, status), (AnomalyResult.kind, kind)):
        if value:
            query = query.where(attribute == value)
    if date_from:
        query = query.where(AnomalyResult.period >= date_from)
    if date_to:
        query = query.where(AnomalyResult.period <= date_to)
    rank = case((AnomalyResult.severity == "high", 0), (AnomalyResult.severity == "medium", 1), else_=2)
    items = db.scalars(query.order_by(rank, AnomalyResult.score.desc())).all()
    start = (page - 1) * page_size
    return {"items": [_result_payload(i) for i in items[start : start + page_size]], "total": len(items), "page": page, "page_size": page_size}


@router.patch("/results/{result_id}")
def update_result(result_id: str, body: StatusUpdate, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    item = db.scalar(select(AnomalyResult).where(AnomalyResult.id == result_id, AnomalyResult.workspace_id == ctx.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Anomaly not found.")
    item.status = body.status
    audit(db, "anomaly.status_changed", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="anomaly", entity_id=item.id, detail={"status": body.status}, ip=client_ip(request))
    db.commit()
    return _result_payload(item)


@router.get("/results/{result_id}/records")
def inspect_records(result_id: str, page_size: int = Query(default=50, ge=1, le=200), ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """Return the original records behind a finding, so it can be checked in context."""
    item = db.scalar(select(AnomalyResult).where(AnomalyResult.id == result_id, AnomalyResult.workspace_id == ctx.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Anomaly not found.")
    run = db.get(AnomalyRun, item.run_id)
    dataset = get_ready_dataset(db, ctx, item.dataset_id)
    version = get_version(db, dataset, run.version_id)
    schema = version_schema(db, version)
    path = storage.resolve_ref(version.storage_ref)
    if item.row_id is not None:
        with connect(path) as con:
            names, rows = run_query(con, "SELECT * FROM data WHERE __row_id = ?", [item.row_id])
        return {"columns": [c["name"] for c in schema], "rows": [dict(zip(names, map(json_safe, r), strict=True)) for r in rows], "total": len(rows)}
    filters: list[Filter] = []
    date_column = (run.summary or {}).get("date_column")
    if item.period and date_column:
        period = item.period
        start = f"{period}-01" if len(period) == 7 else period
        import pandas as pd

        begin = pd.Timestamp(start)
        method = item.method.lower()
        finish = begin + (pd.DateOffset(months=1) if len(period) == 7 else pd.Timedelta(days=7) if "week" in method else pd.Timedelta(days=1)) - pd.Timedelta(seconds=1)
        filters.append(Filter(column=date_column, op="between", values=[begin.isoformat(), finish.isoformat()]))
    if item.kind == "missing_pattern":
        filters.append(Filter(column=item.column_name, op="is_null"))
    if item.kind == "rare_category":
        value = (item.observed or "").rsplit(" (", 1)[0]
        filters.append(Filter(column=item.column_name, op="eq", value=value))
    return fetch_rows(path, schema, page=1, page_size=page_size, filters=filters)


@router.get("/runs/{run_id}/chart")
def chart(run_id: str, column: str, kind: str = "outlier", ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """Chart data with normal observations and flagged points separated."""
    run = _get_run(db, ctx, run_id)
    summary = run.summary or {}
    for key in (f"time:{column}", f"frequency:{column}"):
        series = summary.get("series", {}).get(key)
        if series and kind in {"time_change", "frequency_change"} and series["kind"] == kind:
            return {"type": "series", "label": series["label"], "column": column, "points": series["points"]}
    if kind != "outlier":
        return {"type": "none", "column": column}
    dataset = get_ready_dataset(db, ctx, run.dataset_id)
    version = get_version(db, dataset, run.version_id)
    schema = column_map(version_schema(db, version))
    if column not in schema or schema[column]["type"] not in NUMERIC_TYPES:
        return {"type": "none", "column": column}
    path = storage.resolve_ref(version.storage_ref)
    info = next((m for m in summary.get("methods", []) if m["column"] == column and "expected_low" in m), None)
    q = quote(column)
    with connect(path) as con:
        _, stats = run_query(con, f"SELECT MIN({q}), MAX({q}), COUNT({q}) FROM data")
        low, high, count = stats[0]
        bars = []
        if count and low != high:
            # Bins span the expected range, with outer bins collecting extreme values so the shape stays readable.
            lo = float(info["expected_low"]) if info else float(low)
            hi = float(info["expected_high"]) if info else float(high)
            lo = max(lo, float(low))
            hi = min(hi, float(high))
            width = (hi - lo) / 24 or 1
            _, rows = run_query(con, f"SELECT GREATEST(LEAST(CAST(FLOOR(({q} - ?) / ?) AS BIGINT), 24), -1) AS b, COUNT(*) FROM data WHERE {q} IS NOT NULL GROUP BY 1 ORDER BY 1", [lo, width])
            for b, c in rows:
                b = int(b)
                if b < 0:
                    bars.append({"label": f"< {lo:,.4g}", "count": int(c), "flagged": True})
                elif b >= 24:
                    bars.append({"label": f"> {hi:,.4g}", "count": int(c), "flagged": True})
                else:
                    bars.append({"label": f"{lo + b * width:,.4g}", "count": int(c), "flagged": False})
        _, sample = run_query(con, f"SELECT __row_id, {q} FROM data WHERE {q} IS NOT NULL AND __row_id % GREATEST(1, CAST(? AS BIGINT)) = 0 LIMIT 800", [max(1, int(count) // 800)])
    flagged = db.execute(select(AnomalyResult.row_id, AnomalyResult.observed_value).where(AnomalyResult.run_id == run.id, AnomalyResult.column_name == column, AnomalyResult.kind == "outlier")).all()
    flagged_ids = {r[0] for r in flagged}
    return {
        "type": "distribution",
        "column": column,
        "histogram": bars,
        "expected_low": info["expected_low"] if info else None,
        "expected_high": info["expected_high"] if info else None,
        "normal_points": [{"row": int(r[0]), "value": json_safe(r[1])} for r in sample if r[0] not in flagged_ids],
        "flagged_points": [{"row": int(r[0]), "value": json_safe(r[1])} for r in flagged],
    }
