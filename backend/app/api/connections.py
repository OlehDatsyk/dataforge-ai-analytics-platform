"""Data Connections: PostgreSQL tables and REST APIs, imported as separate datasets."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, new_id, utcnow
from ..deps import WorkspaceContext, admin_context, client_ip, editor_context, workspace_context
from ..models import Credential, DataConnection, Dataset
from ..security import decrypt_secret, encrypt_secret
from ..services import connections as svc
from ..services import storage
from ..services.activity import audit
from ..services.ingestion import process_dataset
from ..services.jobs import submit
from .datasets import dataset_payload

router = APIRouter(prefix="/connections", tags=["Data Connections"])


class ConnectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["postgresql", "rest_api"]
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=120)
    username: str | None = Field(default=None, max_length=120)
    sslmode: Literal["prefer", "require", "verify-full", "disable"] = "prefer"
    password: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    records_path: str | None = Field(default=None, max_length=200)
    header_name: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    header_value: str | None = Field(default=None, max_length=2000)


class ImportBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    schema_name: str | None = Field(default=None, max_length=120)
    table: str | None = Field(default=None, max_length=120)


def _split(body: ConnectionBody) -> tuple[dict, dict]:
    """Separate non-secret settings, kept in plain JSON, from secrets, which are encrypted."""
    if body.kind == "postgresql":
        if not body.host or not body.database or not body.username:
            raise HTTPException(status_code=422, detail="Host, database, and username are required.")
        return {"host": body.host.strip(), "port": body.port or 5432, "database": body.database.strip(), "username": body.username.strip(), "sslmode": body.sslmode}, {"password": body.password or ""}
    if not body.url:
        raise HTTPException(status_code=422, detail="A URL is required.")
    return {"url": body.url.strip(), "records_path": (body.records_path or "").strip()}, {"header_name": body.header_name or "", "header_value": body.header_value or ""}


def _payload(connection: DataConnection, *, has_secret: bool = False) -> dict:
    """Secrets are never returned. The response only says whether one is stored."""
    return {"id": connection.id, "name": connection.name, "kind": connection.kind, "config": connection.config, "has_secret": has_secret, "last_tested_at": connection.last_tested_at, "last_status": connection.last_status, "last_error": connection.last_error, "created_at": connection.created_at}


def _has_secret(values: dict) -> bool:
    return any(bool(v) for v in values.values())


def _get(db: Session, ctx: WorkspaceContext, connection_id: str) -> DataConnection:
    connection = db.scalar(select(DataConnection).where(DataConnection.id == connection_id, DataConnection.workspace_id == ctx.id))
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    return connection


def _secret(db: Session, connection: DataConnection) -> dict:
    stored = db.scalar(select(Credential).where(Credential.connection_id == connection.id))
    return decrypt_secret(stored.encrypted_value) if stored else {}


@router.get("")
def list_connections(ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    rows = db.scalars(select(DataConnection).where(DataConnection.workspace_id == ctx.id).order_by(DataConnection.created_at.desc())).all()
    return [_payload(c, has_secret=_has_secret(_secret(db, c))) for c in rows]


@router.post("", status_code=201)
def create_connection(body: ConnectionBody, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    config, secret = _split(body)
    try:
        if body.kind == "rest_api":
            svc.validate_url(config["url"])
        else:
            svc.resolve_public_host(config["host"], config["port"])
    except svc.ConnectionFailure as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = DataConnection(id=new_id(), workspace_id=ctx.id, created_by=ctx.user.id, name=body.name.strip(), kind=body.kind, config=config)
    db.add(connection)
    db.flush()
    db.add(Credential(connection_id=connection.id, encrypted_value=encrypt_secret(secret)))
    audit(db, "connection.created", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="connection", entity_id=connection.id, detail={"kind": body.kind}, ip=client_ip(request))
    db.commit()
    return _payload(connection, has_secret=_has_secret(secret))


@router.delete("/{connection_id}")
def delete_connection(connection_id: str, request: Request, ctx: WorkspaceContext = Depends(admin_context), db: Session = Depends(get_db)):
    connection = _get(db, ctx, connection_id)
    audit(db, "connection.deleted", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="connection", entity_id=connection.id, ip=client_ip(request))
    db.delete(connection)
    db.commit()
    return {"ok": True}


@router.post("/{connection_id}/test")
def test_connection(connection_id: str, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    connection = _get(db, ctx, connection_id)
    secret = _secret(db, connection)
    connection.last_tested_at = utcnow()
    try:
        if connection.kind == "postgresql":
            svc.pg_test(connection.config, secret)
            detail = {"tables": len(svc.pg_list_tables(connection.config, secret))}
        else:
            records = svc.records_at_path(svc.fetch_json(connection.config["url"], secret=secret), connection.config.get("records_path"))
            detail = {"records": len(records) if isinstance(records, list) else 1}
        connection.last_status, connection.last_error = "ok", None
        result = {"ok": True, **detail}
    except svc.ConnectionFailure as exc:
        connection.last_status, connection.last_error = "failed", str(exc)
        result = {"ok": False, "error": str(exc)}
    audit(db, "connection.tested", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="connection", entity_id=connection.id, detail={"ok": result["ok"]}, ip=client_ip(request))
    db.commit()
    return result


@router.get("/{connection_id}/tables")
def list_tables(connection_id: str, ctx: WorkspaceContext = Depends(workspace_context), db: Session = Depends(get_db)):
    connection = _get(db, ctx, connection_id)
    if connection.kind != "postgresql":
        raise HTTPException(status_code=422, detail="Only PostgreSQL connections have tables.")
    try:
        return svc.pg_list_tables(connection.config, _secret(db, connection))
    except svc.ConnectionFailure as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{connection_id}/import", status_code=202)
def import_data(connection_id: str, body: ImportBody, request: Request, ctx: WorkspaceContext = Depends(editor_context), db: Session = Depends(get_db)):
    """Copy data from the source into a dataset, then process it through the normal pipeline."""
    connection = _get(db, ctx, connection_id)
    secret = _secret(db, connection)
    try:
        if connection.kind == "postgresql":
            if not body.schema_name or not body.table:
                raise HTTPException(status_code=422, detail="Choose a table to import.")
            records = svc.pg_import_table(connection.config, secret, body.schema_name, body.table)
            default_name = f"{connection.name}: {body.table}"
        else:
            records = svc.records_at_path(svc.fetch_json(connection.config["url"], secret=secret), connection.config.get("records_path"))
            default_name = connection.name
    except svc.ConnectionFailure as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not isinstance(records, list):
        raise HTTPException(status_code=422, detail="The source did not return a list of records. Set the records path.")
    dataset_id = new_id()
    target = storage.original_path(ctx.id, dataset_id, ".json")
    target.write_text(json.dumps(records, default=str), encoding="utf-8")
    dataset = Dataset(id=dataset_id, workspace_id=ctx.id, owner_id=ctx.user.id, connection_id=connection.id, name=(body.name or default_name).strip()[:200], original_filename=f"{connection.kind}-import.json",
                      file_format="json", file_size=target.stat().st_size, source_type="connection", status="queued", stage="Queued", storage_ref=storage.relative_ref(target))
    db.add(dataset)
    audit(db, "connection.imported", workspace_id=ctx.id, user_id=ctx.user.id, entity_type="dataset", entity_id=dataset.id, detail={"connection": connection.id, "records": len(records)}, ip=client_ip(request))
    db.commit()
    submit(process_dataset, dataset.id)
    return dataset_payload(dataset)
