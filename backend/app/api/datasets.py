"""Dataset upload, management, versions, exploration, and cleaning."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, new_id
from ..deps import WorkspaceContext, client_ip, editor_context, enforce_rate_limit, get_dataset, get_ready_dataset, get_version, version_schema, workspace_context
from ..models import CleaningOperation, DataProfile, Dataset, DatasetVersion, Project
from ..services import storage
from ..services.activity import audit, record_analysis
from ..services.cleaning import CleaningOp, apply_operations
from ..services.demo import load_demo_datasets
from ..services.exports import csv_stream
from ..services.frames import ROW_ID, json_safe, read_frame
from ..services.ingestion import process_dataset, save_version
from ..services.jobs import submit
from ..services.parsing import IngestError, detect_format
from ..services.query_engine import Filter, Sort, build_where, connect, fetch_rows, quote

router = APIRouter(prefix="/datasets", tags=["Datasets"])
CHUNK = 1024 * 1024
EXPORT_ROW_LIMIT = 1_000_000


def dataset_payload(dataset: Dataset, project_name: str | None = None) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "original_filename": dataset.original_filename,
        "file_format": dataset.file_format,
        "file_size": dataset.file_size,
        "source_type": dataset.source_type,
        "is_demo": dataset.is_demo,
        "status": dataset.status,
        "stage": dataset.stage,
        "progress": dataset.progress,
        "error_message": dataset.error_message,
        "ingest_notes": dataset.ingest_notes,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "project_id": dataset.project_id,
        "project_name": project_name,
        "current_version_id": dataset.current_version_id,
        "parent_dataset_id": dataset.parent_dataset_id,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "last_analysed_at": dataset.last_analysed_at,
    }


def _clean_name(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", stem)).strip()[:200] or "Untitled dataset"


@router.post("", status_code=202)
def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=200),
    project_id: str | None = Form(default=None),
    ctx: WorkspaceContext = Depends(editor_context),
    db: Session = Depends(get_db),
):
    """Validate an upload, store the untouched original, and queue background processing."""
    settings = get_settings()
    enforce_rate_limit(request, "upload", settings.rate_limit_upload_per_minute)
    filename = Path(file.filename or "").name[:255]
    if project_id and not db.scalar(select(Project).where(Project.id == project_id, Project.workspace_id == ctx.id)):
        raise HTTPException(status_code=404, detail="Project not found.")

    dataset_id = new_id()
    size = 0
    with tempfile.NamedTemporaryFile(delete=False, dir=storage.data_root(), prefix="upload-", suffix=".part") as temporary:
        temp_path = Path(temporary.name)
        try:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"The file exceeds the {settings.max_upload_mb} MB upload limit.")
                temporary.write(chunk)
        except HTTPException:
            temporary.close()
            temp_path.unlink(missing_ok=True)
            raise
    try:
        file_format = detect_format(temp_path, filename)
    except IngestError as exc:
        temp_path.unlink(missing_ok=True)
        audit(db, "dataset.rejected", workspace_id=ctx.id, user_id=ctx.user.id, detail={"size": size}, ip=client_ip(request))
        db.commit()
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    target = storage.original_path(ctx.id, dataset_id, Path(filename).suffix.lower())
    temp_path.replace(target)
    dataset = Dataset(
        id=dataset_id,
        workspace_id=ctx.id,
        owner_id=ctx.user.id,
        project_id=project_id or None,
        name=(name or "").strip()[:200] or _clean_name(filename),
        original_filename=filename,
        file_format=file_format,
        file_size=size,
        source_type="upload",
        status="queued",
        stage="Queued",
        storage_ref=storage.relative_ref(target),
    )
    db.add(dataset)
    audit(db, "dataset.uploaded", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"format": file_format, "size": size}, ip=client_ip(request))
    db.commit()
    submit(process_dataset, dataset.id)
    return dataset_payload(dataset)


@router.post("/demo", status_code=202)
def load_demo(request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    created = load_demo_datasets(db, ctx.id, ctx.user.id)
    audit(db, "demo.loaded", workspace_id=ctx.id, user_id=ctx.user.id, detail={"count": len(created)}, ip=client_ip(request))
    db.commit()
    return [dataset_payload(d) for d in created]


@router.get("")
def list_datasets(
    search: str | None = Query(default=None, max_length=200),
    project_id: str | None = None,
    status: str | None = None,
    ctx: WorkspaceContext = Depends(workspace_context),
    db: Session = Depends(get_db),
):
    query = select(Dataset, Project.name).outerjoin(Project, Project.id == Dataset.project_id).where(Dataset.workspace_id == ctx.id)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(Dataset.name.ilike(pattern, escape="\\"), Dataset.original_filename.ilike(pattern, escape="\\")))
    if project_id:
        query = query.where(Dataset.project_id == project_id)
    if status:
        query = query.where(Dataset.status == status)
    rows = db.execute(query.order_by(Dataset.created_at.desc())).all()
    return [dataset_payload(d, name) for d, name in rows]


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    project_id: str | None = None
    clear_project: bool = False


@router.get("/{dataset_id}")
def get_dataset_detail(dataset_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    dataset = get_dataset(db, ctx, dataset_id)
    payload = dataset_payload(dataset)
    payload["versions"] = [_version_payload(v, dataset) for v in _versions(db, dataset)]
    if dataset.status == "ready":
        version = get_version(db, dataset)
        payload["columns"] = version_schema(db, version)
    return payload


def _versions(db: Session, dataset: Dataset) -> list[DatasetVersion]:
    return list(db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id).order_by(DatasetVersion.version_number.desc())).all())


def _version_payload(version: DatasetVersion, dataset: Dataset) -> dict:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "label": version.label,
        "row_count": version.row_count,
        "column_count": version.column_count,
        "size_bytes": version.size_bytes,
        "parent_version_id": version.parent_version_id,
        "created_at": version.created_at,
        "is_current": version.id == dataset.current_version_id,
    }


@router.patch("/{dataset_id}")
def update_dataset(dataset_id: str, body: DatasetUpdate, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    dataset = get_dataset(db, ctx, dataset_id)
    if body.name is not None:
        dataset.name = body.name.strip()
    if body.description is not None:
        dataset.description = body.description.strip() or None
    if body.clear_project:
        dataset.project_id = None
    elif body.project_id:
        if not db.scalar(select(Project).where(Project.id == body.project_id, Project.workspace_id == ctx.id)):
            raise HTTPException(status_code=404, detail="Project not found.")
        dataset.project_id = body.project_id
    audit(db, "dataset.updated", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, ip=client_ip(request))
    db.commit()
    return dataset_payload(dataset)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    """Delete the dataset, its derived records (by cascade), and all of its files."""
    dataset = get_dataset(db, ctx, dataset_id)
    if dataset.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Wait for processing to finish before deleting this dataset.")
    audit(db, "dataset.deleted", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"name": dataset.name}, ip=client_ip(request))
    db.delete(dataset)
    db.commit()
    storage.delete_dataset_files(ctx.id, dataset_id)
    return {"ok": True}


def _create_derived_dataset(db: Session, ctx: WorkspaceContext, source: Dataset, name: str, df, columns: list[dict], label: str) -> tuple[Dataset, DatasetVersion]:
    derived = Dataset(
        id=new_id(), workspace_id=ctx.id, owner_id=ctx.user.id, project_id=source.project_id, parent_dataset_id=source.id,
        name=name[:200], description=source.description, original_filename=source.original_filename, file_format=source.file_format,
        file_size=0, source_type="derived", is_demo=source.is_demo, status="processing",
    )
    db.add(derived)
    db.flush()
    version = save_version(db, derived, df, columns, label=label, parent_version_id=None, user_id=ctx.user.id)
    derived.progress = 100
    derived.stage = None
    return derived, version


@router.post("/{dataset_id}/duplicate", status_code=201)
def duplicate_dataset(dataset_id: str, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    source = get_ready_dataset(db, ctx, dataset_id)
    version = get_version(db, source)
    schema = version_schema(db, version)
    df = read_frame(storage.resolve_ref(version.storage_ref))
    copy, _ = _create_derived_dataset(db, ctx, source, f"{source.name} (copy)", df, [{"name": c["name"], "type": c["type"]} for c in schema], f"Copied from {source.name} v{version.version_number}")
    audit(db, "dataset.duplicated", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=copy.id, detail={"source": source.id}, ip=client_ip(request))
    db.commit()
    return dataset_payload(copy)


@router.get("/{dataset_id}/versions")
def list_versions(dataset_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    dataset = get_dataset(db, ctx, dataset_id)
    return [_version_payload(v, dataset) for v in _versions(db, dataset)]


@router.post("/{dataset_id}/versions/{version_id}/activate")
def activate_version(dataset_id: str, version_id: str, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version = get_version(db, dataset, version_id)
    dataset.current_version_id = version.id
    dataset.row_count = version.row_count
    dataset.column_count = version.column_count
    audit(db, "dataset.version_activated", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"version": version.version_number}, ip=client_ip(request))
    db.commit()
    return _version_payload(version, dataset)


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: str, version_id: str | None = None, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version = get_version(db, dataset, version_id)
    stored = db.scalar(select(DataProfile).where(DataProfile.version_id == version.id))
    return {"version": _version_payload(version, dataset), "columns": version_schema(db, version), "profile": stored.profile, "quality": stored.quality}


class RowsRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    sort: list[Sort] = Field(default_factory=list, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    search: str | None = Field(default=None, max_length=200)
    columns: list[str] | None = Field(default=None, max_length=500)
    version_id: str | None = None


@router.post("/{dataset_id}/rows")
def query_rows(dataset_id: str, body: RowsRequest, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version = get_version(db, dataset, body.version_id)
    schema = version_schema(db, version)
    return fetch_rows(storage.resolve_ref(version.storage_ref), schema, page=body.page, page_size=body.page_size, sort=body.sort, filters=body.filters, search=body.search, columns=body.columns)


@router.post("/{dataset_id}/export")
def export_rows(dataset_id: str, body: RowsRequest, request: Request, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """Export the current filtered view as CSV, with formula-injection protection."""
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version = get_version(db, dataset, body.version_id)
    schema = version_schema(db, version)
    path = storage.resolve_ref(version.storage_ref)
    names = {c["name"] for c in schema}
    selected = [c for c in (body.columns or [c["name"] for c in schema]) if c in names]
    where, params = build_where(body.filters, schema, body.search)
    order = ", ".join([f"{quote(s.column)} {s.direction.upper()} NULLS LAST" for s in body.sort if s.column in names] + [quote(ROW_ID)])
    audit(db, "dataset.exported", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, ip=client_ip(request))
    db.commit()

    def rows():
        with connect(path) as con:
            cursor = con.execute(f"SELECT {', '.join(quote(c) for c in selected)} FROM data{where} ORDER BY {order} LIMIT {EXPORT_ROW_LIMIT}", params)
            while batch := cursor.fetchmany(5000):
                for row in batch:
                    yield dict(zip(selected, map(json_safe, row), strict=True))

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", dataset.name)[:80] or "dataset"
    return StreamingResponse(csv_stream(selected, rows()), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'})


class CleaningRequest(BaseModel):
    operations: list[CleaningOp] = Field(min_length=1, max_length=25)
    version_id: str | None = None


class CleaningApply(CleaningRequest):
    save_as: str = Field(default="new_version", pattern="^(new_version|new_dataset)$")
    name: str | None = Field(default=None, max_length=200)


def _run_cleaning(db: Session, dataset: Dataset, body: CleaningRequest):
    version = get_version(db, dataset, body.version_id)
    schema = version_schema(db, version)
    columns = [{"name": c["name"], "type": c["type"]} for c in schema]
    df = read_frame(storage.resolve_ref(version.storage_ref))
    result, new_columns, effects = apply_operations(df, columns, body.operations)
    return version, columns, df, result, new_columns, effects


@router.post("/{dataset_id}/cleaning/preview")
def preview_cleaning(dataset_id: str, body: CleaningRequest, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    """Calculate the effect of the operations without saving anything."""
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version, columns, df, result, new_columns, effects = _run_cleaning(db, dataset, body)
    sample = result.head(20)
    names = [c["name"] for c in new_columns]
    return {
        "source_version": version.version_number,
        "rows_before": len(df),
        "rows_after": len(result),
        "columns_before": [c["name"] for c in columns],
        "columns_after": names,
        "effects": effects,
        "sample": [{n: json_safe(v) for n, v in row.items()} for row in sample[names].astype(object).to_dict("records")],
        "saved": False,
    }


@router.post("/{dataset_id}/cleaning/apply", status_code=201)
def apply_cleaning(dataset_id: str, body: CleaningApply, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    """Save the cleaned result as a new version or dataset. The source version is never modified."""
    dataset = get_ready_dataset(db, ctx, dataset_id)
    version, _columns, _df, result, new_columns, effects = _run_cleaning(db, dataset, body)
    label = "; ".join(e["op"].replace("_", " ") for e in effects)[:180]
    operations = [op.model_dump() for op in body.operations]
    target = dataset
    if body.save_as == "new_dataset":
        target, new_version = _create_derived_dataset(db, ctx, dataset, (body.name or f"{dataset.name} (cleaned)").strip(), result, new_columns, f"Cleaned from v{version.version_number}: {label}")
    else:
        new_version = save_version(db, dataset, result, new_columns, label=f"Cleaned: {label}", parent_version_id=version.id, user_id=ctx.user.id)
    db.add(CleaningOperation(dataset_id=target.id, source_version_id=version.id if target.id == dataset.id else None, result_version_id=new_version.id, operations=operations,
                             summary={"effects": [{k: e[k] for k in ("op", "description", "rows_removed", "cells_changed")} for e in effects], "rows_before": version.row_count, "rows_after": len(result),
                                      "source_dataset": dataset.id, "source_version": version.version_number}, created_by=ctx.user.id))
    audit(db, "dataset.cleaned", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=target.id, detail={"operations": len(operations), "rows_after": len(result)}, ip=client_ip(request))
    record_analysis(db, workspace_id=ctx.id, dataset_id=target.id, user_id=ctx.user.id, name=f"Cleaning: {target.name}", analysis_type="cleaning", link=f"/cleaning?dataset={target.id}", summary={"rows_after": len(result)})
    db.commit()
    return {"dataset": dataset_payload(target), "version": _version_payload(new_version, target)}


@router.get("/{dataset_id}/cleaning/history")
def cleaning_history(dataset_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    dataset = get_dataset(db, ctx, dataset_id)
    rows = db.scalars(select(CleaningOperation).where(CleaningOperation.dataset_id == dataset.id).order_by(CleaningOperation.created_at.desc())).all()
    return [{"id": r.id, "operations": r.operations, "summary": r.summary, "source_version_id": r.source_version_id, "result_version_id": r.result_version_id, "created_at": r.created_at} for r in rows]
