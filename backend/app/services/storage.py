"""File storage. Each workspace has its own directory; stored names are generated, never user-supplied."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import get_settings


def data_root() -> Path:
    root = get_settings().data_path / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def dataset_dir(workspace_id: str, dataset_id: str) -> Path:
    path = data_root() / workspace_id / "datasets" / dataset_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_ref(path: Path) -> str:
    return path.resolve().relative_to(data_root()).as_posix()


def resolve_ref(ref: str) -> Path:
    """Resolve a stored reference and refuse anything outside the storage root."""
    root = data_root()
    path = (root / ref).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Storage reference is outside the data directory.")
    return path


def original_path(workspace_id: str, dataset_id: str, extension: str) -> Path:
    directory = dataset_dir(workspace_id, dataset_id) / "original"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"source{extension}"


def version_path(workspace_id: str, dataset_id: str, version_id: str) -> Path:
    directory = dataset_dir(workspace_id, dataset_id) / "versions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{version_id}.parquet"


def delete_dataset_files(workspace_id: str, dataset_id: str) -> None:
    path = data_root() / workspace_id / "datasets" / dataset_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
