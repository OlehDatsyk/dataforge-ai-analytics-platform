"""Relational metadata model. Dataset contents live in Parquet files, never in these tables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, new_id, utcnow


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, default=utcnow, nullable=False, index=True)


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped:
    return mapped_column(String(36), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = _created()
    user: Mapped[User] = relationship()


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = _fk("users.id")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = _created()


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    user_id: Mapped[str] = _fk("users.id")
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)  # owner|admin|member|viewer
    created_at: Mapped[datetime] = _created()
    workspace: Mapped[Workspace] = relationship()
    user: Mapped[User] = relationship()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_project_name"),)
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _created()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_workspace_created", "workspace_id", "created_at"),)
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    owner_id: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    project_id: Mapped[str | None] = _fk("projects.id", nullable=True, ondelete="SET NULL")
    connection_id: Mapped[str | None] = _fk("data_connections.id", nullable=True, ondelete="SET NULL")
    parent_dataset_id: Mapped[str | None] = _fk("datasets.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="upload", nullable=False)  # upload|connection|derived|demo
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)  # queued|processing|ready|failed
    stage: Mapped[str | None] = mapped_column(String(60))
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    storage_ref: Mapped[str | None] = mapped_column(String(500))  # original file, relative to the data directory
    ingest_notes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_analysed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version"),)
    id: Mapped[str] = _id()
    dataset_id: Mapped[str] = _fk("datasets.id")
    parent_version_id: Mapped[str | None] = _fk("dataset_versions.id", nullable=True, ondelete="SET NULL")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = _created()


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"
    __table_args__ = (UniqueConstraint("version_id", "name", name="uq_version_column"),)
    id: Mapped[str] = _id()
    version_id: Mapped[str] = _fk("dataset_versions.id")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)  # integer|float|boolean|date|category|text
    missing_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    unique_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class DataProfile(Base):
    __tablename__ = "data_profiles"
    id: Mapped[str] = _id()
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    quality: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = _created()


class CleaningOperation(Base):
    __tablename__ = "cleaning_operations"
    id: Mapped[str] = _id()
    dataset_id: Mapped[str] = _fk("datasets.id")
    source_version_id: Mapped[str | None] = _fk("dataset_versions.id", nullable=True, ondelete="SET NULL")
    result_version_id: Mapped[str | None] = _fk("dataset_versions.id", nullable=True, ondelete="SET NULL")
    operations: Mapped[list] = mapped_column(JSON, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = _created()


class AnalysisResult(Base):
    """Log of completed analyses, used for dashboard metrics and re-opening earlier work."""

    __tablename__ = "analysis_results"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str | None] = _fk("datasets.id", nullable=True)
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)  # profile|ai_question|anomaly_scan|report|chart
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    link: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()


class Visualisation(Base):
    __tablename__ = "visualisations"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("datasets.id")
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    spec: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AnomalyRun(Base):
    __tablename__ = "anomaly_runs"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("datasets.id")
    version_id: Mapped[str | None] = _fk("dataset_versions.id", nullable=True, ondelete="SET NULL")
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = _created()


class AnomalyResult(Base):
    __tablename__ = "anomaly_results"
    __table_args__ = (Index("ix_anomaly_run_severity", "run_id", "severity"),)
    id: Mapped[str] = _id()
    run_id: Mapped[str] = _fk("anomaly_runs.id")
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("datasets.id")
    row_id: Mapped[int | None] = mapped_column(BigInteger)
    period: Mapped[str | None] = mapped_column(String(40))
    column_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # outlier|time_change|frequency_change|missing_pattern|rare_category
    method: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    observed: Mapped[str | None] = mapped_column(String(255))
    observed_value: Mapped[float | None] = mapped_column(Float)
    expected_low: Mapped[float | None] = mapped_column(Float)
    expected_high: Mapped[float | None] = mapped_column(Float)
    baseline: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # low|medium|high
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|investigating|expected|resolved
    created_at: Mapped[datetime] = _created()


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("datasets.id")
    user_id: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[str] = _id()
    conversation_id: Mapped[str] = _fk("ai_conversations.id")
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON)
    mode: Mapped[str | None] = mapped_column(String(20))  # live|demonstration
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(80))
    usage: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    dataset_id: Mapped[str] = _fk("datasets.id")
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = _created()


class DataConnection(Base):
    __tablename__ = "data_connections"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    created_by: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # postgresql|rest_api
    config: Mapped[dict] = mapped_column(JSON, nullable=False)  # non-secret settings only
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = _id()
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_connections.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = _fk("workspaces.id")
    user_id: Mapped[str] = _fk("users.id")
    kind: Mapped[str] = mapped_column(String(20), default="info", nullable=False)  # info|success|warning|error
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str | None] = _fk("workspaces.id", nullable=True)
    user_id: Mapped[str | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
