"""Loads synthetic demonstration datasets through the normal ingestion pipeline."""
from __future__ import annotations

import logging
import shutil

from sqlalchemy.orm import Session

from ..config import REPO_ROOT
from ..db import new_id, session_scope
from ..models import AnomalyResult, AnomalyRun, DataProfile, Dataset, DatasetColumn, DatasetVersion, Report, Visualisation
from . import storage
from .activity import record_analysis
from .anomaly import run_detection
from .charts import recommend_charts
from .frames import read_frame
from .ingestion import process_dataset
from .jobs import submit
from .reports import build_report

logger = logging.getLogger("dataforge.demo")
SAMPLE_DIR = REPO_ROOT / "sample_datasets"
DEMO_DATASETS = [
    ("retail_sales.csv", "Retail Sales (Synthetic)", "Synthetic orders for 2023 and 2024, with planted bulk orders and label inconsistencies."),
    ("customer_analytics.csv", "Customer Analytics (Synthetic)", "Synthetic customer records with plans, tenure, lifetime value, and satisfaction."),
    ("website_traffic.csv", "Website Traffic (Synthetic)", "Synthetic daily traffic by channel for 2024, with a planted outage and campaign spike."),
    ("financial_transactions.csv", "Financial Transactions (Synthetic)", "Synthetic transactions for 2024, with planted large amounts and a gap in merchant names."),
    ("product_performance.csv", "Product Performance (Synthetic)", "Synthetic product sales, returns, and ratings."),
]


def _process_with_examples(dataset_id: str, add_examples: bool) -> None:
    process_dataset(dataset_id)
    if add_examples:
        try:
            create_examples(dataset_id)
        except Exception:
            logger.error("Example analyses could not be created for dataset %s", dataset_id, exc_info=False)


def create_examples(dataset_id: str) -> None:
    """Create real example analyses for a demo dataset: an anomaly scan, charts, and a report."""
    with session_scope() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None or dataset.status != "ready":
            return
        version = db.get(DatasetVersion, dataset.current_version_id)
        columns = db.query(DatasetColumn).filter_by(version_id=version.id).order_by(DatasetColumn.position).all()
        schema = [{"name": c.name, "type": c.data_type, "unique": c.unique_count, "missing": c.missing_count} for c in columns]
        stored = db.query(DataProfile).filter_by(version_id=version.id).one()
        path = storage.resolve_ref(version.storage_ref)
        workspace_name = dataset.name

        detected = run_detection(read_frame(path, keep_row_id=True), schema)
        run = AnomalyRun(id=new_id(), workspace_id=dataset.workspace_id, dataset_id=dataset.id, version_id=version.id, created_by=dataset.owner_id, summary=detected["summary"], config={"example": True})
        db.add(run)
        db.flush()
        for finding in detected["findings"]:
            db.add(AnomalyResult(run_id=run.id, workspace_id=dataset.workspace_id, dataset_id=dataset.id, **finding))
        record_analysis(db, workspace_id=dataset.workspace_id, dataset_id=dataset.id, user_id=dataset.owner_id, name=f"Anomaly scan: {dataset.name}", analysis_type="anomaly_scan",
                        link=f"/anomalies?dataset={dataset.id}", summary={"total": detected["summary"]["total"]})

        for suggestion in recommend_charts(schema, limit=2):
            db.add(Visualisation(workspace_id=dataset.workspace_id, dataset_id=dataset.id, created_by=dataset.owner_id, name=suggestion["title"], spec=suggestion["spec"]))

        from ..models import Workspace

        workspace = db.get(Workspace, dataset.workspace_id)
        workspace_name = workspace.name if workspace else workspace_name
        content = build_report("dataset_overview", title=None, workspace_name=workspace_name, dataset_name=dataset.name, version_number=version.version_number, is_demo=True,
                               schema=schema, path=path, profile=stored.profile, quality=stored.quality)
        report = Report(id=new_id(), workspace_id=dataset.workspace_id, dataset_id=dataset.id, created_by=dataset.owner_id, title=content["title"], report_type="dataset_overview", content=content)
        db.add(report)
        record_analysis(db, workspace_id=dataset.workspace_id, dataset_id=dataset.id, user_id=dataset.owner_id, name=content["title"], analysis_type="report", link=f"/reports/{report.id}")


def load_demo_datasets(db: Session, workspace_id: str, user_id: str) -> list[Dataset]:
    """Copy the sample files in and queue processing. Datasets already loaded are skipped."""
    existing = {d.name for d in db.query(Dataset).filter_by(workspace_id=workspace_id, is_demo=True).all()}
    created = []
    for index, (filename, name, description) in enumerate(DEMO_DATASETS):
        if name in existing:
            continue
        source = SAMPLE_DIR / filename
        if not source.exists():
            continue
        dataset = Dataset(id=new_id(), workspace_id=workspace_id, owner_id=user_id, name=name, description=description, original_filename=filename, file_format="csv",
                          file_size=source.stat().st_size, source_type="demo", is_demo=True, status="queued", stage="Queued")
        target = storage.original_path(workspace_id, dataset.id, ".csv")
        shutil.copyfile(source, target)
        dataset.storage_ref = storage.relative_ref(target)
        db.add(dataset)
        created.append((dataset, index == 0))
    db.commit()
    for dataset, add_examples in created:
        submit(_process_with_examples, dataset.id, add_examples)
    return [d for d, _ in created]
