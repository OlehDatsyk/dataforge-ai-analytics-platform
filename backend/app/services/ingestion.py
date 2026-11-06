"""The ingestion pipeline and the single code path that stores a new dataset version."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import new_id, session_scope, utcnow
from ..models import DataProfile, Dataset, DatasetColumn, DatasetVersion
from . import storage
from .activity import audit, notify, record_analysis
from .frames import write_frame
from .inference import infer_frame
from .parsing import IngestError, parse_file
from .profiling import build_profile, quality_checks

logger = logging.getLogger("dataforge.ingestion")


def save_version(
    db: Session,
    dataset: Dataset,
    df: pd.DataFrame,
    columns: list[dict],
    *,
    label: str,
    parent_version_id: str | None,
    user_id: str | None,
) -> DatasetVersion:
    """Store a frame as a new immutable version with its columns, profile, and quality findings."""
    version_id = new_id()
    path = storage.version_path(dataset.workspace_id, dataset.id, version_id)
    size = write_frame(df, columns, path)
    number = (db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset.id)) or 0) + 1
    profile = build_profile(df, columns)
    quality = quality_checks(df, columns)
    version = DatasetVersion(
        id=version_id,
        dataset_id=dataset.id,
        parent_version_id=parent_version_id,
        version_number=number,
        label=label[:200],
        storage_ref=storage.relative_ref(path),
        row_count=int(df.shape[0]),
        column_count=int(df.shape[1]),
        size_bytes=size,
        created_by=user_id,
    )
    db.add(version)
    db.flush()
    by_name = {c["name"]: c for c in profile["columns"]}
    for position, column in enumerate(columns):
        stats = by_name[column["name"]]
        db.add(
            DatasetColumn(
                version_id=version_id,
                position=position,
                name=column["name"],
                data_type=column["type"],
                missing_count=stats["missing"],
                unique_count=stats["unique"],
            )
        )
    db.add(DataProfile(version_id=version_id, profile=profile, quality=quality))
    dataset.current_version_id = version_id
    dataset.row_count = version.row_count
    dataset.column_count = version.column_count
    dataset.status = "ready"
    return version


def _set_stage(dataset_id: str, stage: str, progress: int) -> None:
    with session_scope() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset:
            dataset.status = "processing"
            dataset.stage = stage
            dataset.progress = progress


def process_dataset(dataset_id: str) -> None:
    """Run the pipeline for one dataset. Failures are recorded on the dataset, not raised."""
    started = time.monotonic()
    limit = get_settings().ingest_timeout_seconds

    def check_deadline() -> None:
        if time.monotonic() - started > limit:
            raise IngestError("Processing exceeded the time limit for a single file.")

    try:
        with session_scope() as db:
            dataset = db.get(Dataset, dataset_id)
            if dataset is None:
                return
            source = storage.resolve_ref(dataset.storage_ref)
            file_format = dataset.file_format

        _set_stage(dataset_id, "Parsing file", 15)
        parsed = parse_file(Path(source), file_format)
        check_deadline()

        _set_stage(dataset_id, "Inferring column types", 45)
        typed, columns, type_notes = infer_frame(parsed.frame)
        check_deadline()

        _set_stage(dataset_id, "Profiling data", 70)
        with session_scope() as db:
            dataset = db.get(Dataset, dataset_id)
            version = save_version(
                db, dataset, typed, columns, label="Original import", parent_version_id=None, user_id=dataset.owner_id
            )
            dataset.stage = None
            dataset.progress = 100
            dataset.error_message = None
            dataset.ingest_notes = parsed.notes + type_notes
            dataset.last_analysed_at = utcnow()
            audit(db, "dataset.processed", workspace_id=dataset.workspace_id, user_id=dataset.owner_id, entity_type="dataset",
                  entity_id=dataset.id, detail={"rows": version.row_count, "columns": version.column_count})
            record_analysis(db, workspace_id=dataset.workspace_id, dataset_id=dataset.id, user_id=dataset.owner_id,
                            name=f"Data profile: {dataset.name}", analysis_type="profile", link=f"/explorer?dataset={dataset.id}",
                            summary={"rows": version.row_count, "columns": version.column_count})
            notify(db, dataset.workspace_id, dataset.owner_id, f"'{dataset.name}' is ready", kind="success",
                   body=f"{version.row_count:,} rows and {version.column_count} columns processed.", link=f"/explorer?dataset={dataset.id}")
    except IngestError as exc:
        _fail(dataset_id, str(exc))
    except MemoryError:
        _fail(dataset_id, "The file needs more memory than this server has available.")
    except Exception:
        # The exception type is logged without its message, which could contain cell values.
        logger.error("Dataset %s failed during processing", dataset_id, exc_info=False)
        _fail(dataset_id, "The file could not be processed because of an unexpected error.")


def _fail(dataset_id: str, message: str) -> None:
    with session_scope() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset:
            dataset.status = "failed"
            dataset.stage = None
            dataset.error_message = message
            notify(db, dataset.workspace_id, dataset.owner_id, f"'{dataset.name}' could not be processed", kind="error",
                   body=message, link="/datasets")
