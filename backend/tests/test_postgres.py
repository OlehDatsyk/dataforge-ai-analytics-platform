"""Tests against a real PostgreSQL server: migrations, the application, and read-only table import.

They use the optional `pgserver` package, which bundles PostgreSQL binaries, and skip when it is absent.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
import psycopg  # noqa: E402

# pgserver logs from an exit handler, after pytest has closed its capture streams.
logging.getLogger("pgserver").setLevel(logging.CRITICAL)
logging.raiseExceptions = False

pytestmark = pytest.mark.postgres
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pg_uri():
    directory = tempfile.mkdtemp(prefix="df-pg-")
    server = pgserver.get_server(directory, cleanup_mode="stop")
    uri = server.get_uri()
    with psycopg.connect(uri, autocommit=True) as con:
        con.execute("CREATE DATABASE dataforge_test")
        con.execute("CREATE DATABASE source_data")
    with psycopg.connect(uri.rsplit("/", 1)[0] + "/source_data", autocommit=True) as con:
        con.execute("CREATE TABLE sales (id int, region text, amount numeric, sold_at date)")
        con.execute("INSERT INTO sales VALUES (1, 'North', 10.5, '2024-01-01'), (2, 'South', 20.25, '2024-01-02')")
        con.execute('CREATE TABLE "odd name; DROP TABLE sales" (x int)')
    yield uri
    server.cleanup()


def _sub_env(uri: str) -> dict:
    env = dict(os.environ)
    env["DATABASE_URL"] = uri.rsplit("/", 1)[0] + "/dataforge_test"
    env["DATA_DIR"] = tempfile.mkdtemp(prefix="df-pg-data-")
    return env


def test_migrations_and_application_flow_on_postgres(pg_uri):
    """Run the migration, then a real end-to-end flow on PostgreSQL in a separate process."""
    env = _sub_env(pg_uri)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True)
    script = r"""
import time
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from app.db import get_engine
from app.main import app
assert get_engine().dialect.name == "postgresql"
tables = set(inspect(get_engine()).get_table_names())
assert {"users", "datasets", "dataset_versions", "reports", "audit_logs", "credentials"} <= tables
c = TestClient(app, base_url="http://localhost:8000")
r = c.post("/api/auth/register", json={"email": "pg@example.com", "full_name": "PG User", "password": "pg-password-123"})
assert r.status_code == 201, r.text
h = {"X-CSRF-Token": c.cookies.get("dataforge_csrf")}
r = c.post("/api/datasets", files={"file": ("s.csv", b"region,revenue,day\nA,1.5,2024-01-01\nB,2.5,2024-01-02\nA,3,2024-01-03\n")}, headers=h)
assert r.status_code == 202, r.text
i = r.json()["id"]
for _ in range(200):
    d = c.get(f"/api/datasets/{i}").json()
    if d["status"] in ("ready", "failed"):
        break
    time.sleep(0.05)
assert d["status"] == "ready", d
assert c.post(f"/api/datasets/{i}/rows", json={"filters": [{"column": "revenue", "op": "gt", "value": 2}]}, headers=h).json()["total"] == 2
a = c.post("/api/analyst/ask", json={"dataset_id": i, "question": "total revenue by region"}, headers=h).json()
assert a["message"]["response"]["supporting_data"]["rows"][0]["total revenue"] == 4.5
assert c.post("/api/anomalies/run", json={"dataset_id": i}, headers=h).status_code == 201
rep = c.post("/api/reports", json={"dataset_id": i, "report_type": "dataset_overview"}, headers=h)
assert rep.status_code == 201
assert c.get(f"/api/reports/{rep.json()['id']}/export/pdf").content.startswith(b"%PDF")
ov = c.get("/api/overview").json()["metrics"]
assert ov["total_datasets"] == 1 and ov["records_analysed"] == 3
assert c.delete(f"/api/datasets/{i}", headers=h).status_code == 200
assert c.get("/api/reports").json() == []
print("OK")
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    downgrade = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert downgrade.returncode == 0, downgrade.stderr[-2000:]


def test_migration_matches_models(pg_uri):
    env = _sub_env(pg_uri)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True)
    check = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True)


def _config(uri: str) -> dict:
    from urllib.parse import urlsplit

    parts = urlsplit(uri)
    return {"host": parts.hostname, "port": parts.port, "database": "source_data", "username": parts.username, "sslmode": "disable"}


def test_postgres_connection_import_real_server(pg_uri, monkeypatch):
    from app.config import get_settings
    from app.services import connections

    config = _config(pg_uri)
    with pytest.raises(connections.ConnectionFailure, match="internal"):
        connections.pg_test(config, {})
    monkeypatch.setattr(get_settings(), "allow_private_connections", True)
    connections.pg_test(config, {})
    tables = connections.pg_list_tables(config, {})
    assert {"schema": "public", "table": "sales"} in tables
    records = connections.pg_import_table(config, {}, "public", "sales")
    assert len(records) == 2 and records[0]["region"] == "North"
    with pytest.raises(connections.ConnectionFailure, match="not found"):
        connections.pg_import_table(config, {}, "public", "sales; DROP TABLE sales")
    assert connections.pg_import_table(config, {}, "public", "odd name; DROP TABLE sales") == []
    assert len(connections.pg_import_table(config, {}, "public", "sales")) == 2, "the table is untouched"
    with connections._pg_connect(config, {}) as con:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            con.execute("DELETE FROM sales")


def test_postgres_failure_message_hides_details(pg_uri, monkeypatch):
    from app.config import get_settings
    from app.services import connections

    monkeypatch.setattr(get_settings(), "allow_private_connections", True)
    config = {**_config(pg_uri), "database": "missing_db_name"}
    with pytest.raises(connections.ConnectionFailure) as caught:
        connections.pg_test(config, {})
    assert "missing_db_name" not in str(caught.value)
