"""In-process background worker pool for dataset processing. No external queue is required."""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import Dataset

logger = logging.getLogger("dataforge.jobs")
_pool: ThreadPoolExecutor | None = None


def _executor() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=get_settings().job_workers, thread_name_prefix="dataforge-job")
    return _pool


def submit(fn, *args) -> Future:
    return _executor().submit(fn, *args)


def resume_interrupted() -> int:
    """Requeue datasets that were mid-processing when the server last stopped."""
    from .ingestion import process_dataset

    with session_scope() as db:
        pending = db.scalars(select(Dataset).where(Dataset.status.in_(["queued", "processing"]))).all()
        ids = [d.id for d in pending]
    for dataset_id in ids:
        submit(process_dataset, dataset_id)
    if ids:
        logger.info("Requeued %d interrupted dataset job(s)", len(ids))
    return len(ids)


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
