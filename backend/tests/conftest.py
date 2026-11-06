"""Shared fixtures. Each test session uses a temporary data directory and database."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

_TEMP = Path(tempfile.mkdtemp(prefix="dataforge-tests-"))
os.environ["ENVIRONMENT"] = "test"
os.environ["DATA_DIR"] = str(_TEMP)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TEMP / 'test.db').as_posix()}")
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-else"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-not-used-anywhere-else"
os.environ["AI_PROVIDER"] = "demo"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_AI_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_UPLOAD_PER_MINUTE"] = "100000"
os.environ["MAX_ROWS"] = "20000"
os.environ["MAX_COLUMNS"] = "50"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import CSRF_COOKIE  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.create_all(get_engine())
    yield
    get_engine().dispose()
    shutil.rmtree(_TEMP, ignore_errors=True)


class ApiClient:
    """A signed-in browser-like client that sends the CSRF header and active workspace."""

    def __init__(self, email: str | None = None):
        self.client = TestClient(app, base_url="http://localhost:8000")
        self.email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
        self.password = "correct-horse-battery-9"
        response = self.client.post("/api/auth/register", json={"email": self.email, "full_name": "Test User", "password": self.password})
        assert response.status_code == 201, response.text
        self.user = response.json()
        self.workspace_id = self.user["workspaces"][0]["id"]

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"X-Workspace-Id": self.workspace_id}
        token = self.client.cookies.get(CSRF_COOKIE)
        if token:
            headers["X-CSRF-Token"] = token
        return {**headers, **(extra or {})}

    def get(self, url, **kwargs):
        return self.client.get(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def post(self, url, **kwargs):
        return self.client.post(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def patch(self, url, **kwargs):
        return self.client.patch(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def put(self, url, **kwargs):
        return self.client.put(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def delete(self, url, **kwargs):
        return self.client.delete(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def upload(self, filename: str, content: bytes, *, wait: bool = True, name: str | None = None) -> dict:
        data = {"name": name} if name else {}
        response = self.post("/api/datasets", files={"file": (filename, content)}, data=data)
        assert response.status_code == 202, response.text
        dataset = response.json()
        return self.wait_ready(dataset["id"]) if wait else dataset

    def wait_ready(self, dataset_id: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dataset = self.get(f"/api/datasets/{dataset_id}").json()
            if dataset["status"] in {"ready", "failed"}:
                return dataset
            time.sleep(0.05)
        raise AssertionError("Dataset processing timed out")


@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def other_api() -> ApiClient:
    return ApiClient()


SALES_CSV = b"""order_id,order_date,region,product,quantity,revenue,note
O-1,2024-01-05,North,Widget,2,100.00,first
O-2,2024-01-20,South,Widget,1,50.00,
O-3,2024-02-03,North,Gadget,3,300.00,bulk
O-4,2024-02-14,East,Gadget,1,100.00,
O-5,2024-03-09,South,Doohickey,5,250.00,
O-6,2024-03-22,North,Widget,4,200.00,
O-6,2024-03-22,North,Widget,4,200.00,
O-8,2024-04-01,East,,1,,missing product
"""


@pytest.fixture
def sales(api: ApiClient) -> dict:
    dataset = api.upload("sales.csv", SALES_CSV)
    assert dataset["status"] == "ready", dataset
    return dataset


def retail_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sample_datasets" / "retail_sales.csv"


@pytest.fixture(scope="session")
def retail_client() -> tuple[ApiClient, dict]:
    client = ApiClient()
    dataset = client.upload("retail_sales.csv", retail_path().read_bytes())
    assert dataset["status"] == "ready", dataset
    return client, dataset
