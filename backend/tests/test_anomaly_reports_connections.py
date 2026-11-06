"""Anomaly detection, reports and exports, external connections and SSRF, demo data, and the dashboard."""
from __future__ import annotations

import io
import json
import time

import httpx
import numpy as np
import openpyxl
import pandas as pd
import pytest

from app.services import anomaly, connections
from app.services.exports import safe_cell, tables_to_csv, tables_to_xlsx
from tests.conftest import ApiClient, retail_path


def _frame(values, **extra) -> pd.DataFrame:
    return pd.DataFrame({"__row_id": range(1, len(values) + 1), "value": values, **extra})


SCHEMA = [{"name": "value", "type": "float"}]


def test_outlier_detected_in_symmetric_data_uses_modified_z():
    rng = np.random.default_rng(1)
    values = rng.normal(100, 5, 500).tolist() + [400.0]
    result = anomaly.run_detection(_frame(values), SCHEMA)
    flagged = [f for f in result["findings"] if f["observed_value"] == 400.0]
    assert flagged and flagged[0]["row_id"] == 501
    assert flagged[0]["method"].startswith("Modified Z-score")
    assert flagged[0]["severity"] == "high"
    assert flagged[0]["expected_low"] < 100 < flagged[0]["expected_high"]
    assert len(result["findings"]) < 10, "normal data must not produce many flags"


def test_skewed_data_uses_iqr():
    rng = np.random.default_rng(2)
    values = rng.lognormal(3, 1, 800)
    method, reason = anomaly.choose_numeric_method(pd.Series(values))
    assert method.startswith("IQR")
    assert "Skewness" in reason


def test_iqr_bounds_are_correct():
    rng = np.random.default_rng(3)
    values = rng.lognormal(3, 1, 800).tolist() + [1e6]
    series = pd.Series(values)
    result = anomaly.run_detection(_frame(values), SCHEMA)
    q1, q3 = series.quantile([0.25, 0.75])
    top = max(result["findings"], key=lambda f: f["observed_value"])
    assert top["observed_value"] == 1e6
    assert top["expected_high"] == pytest.approx(q3 + 3 * (q3 - q1))
    assert top["severity"] == "high"


def test_clean_uniform_data_has_no_outliers():
    values = np.linspace(0, 100, 500).tolist()
    assert anomaly.run_detection(_frame(values), SCHEMA)["findings"] == []


def test_small_or_constant_columns_are_skipped_with_reason():
    few = anomaly.run_detection(_frame([1.0, 2.0, 3.0]), SCHEMA)
    assert few["findings"] == [] and "at least 30" in few["summary"]["skipped"][0]
    same = anomaly.run_detection(_frame([5.0] * 100), SCHEMA)
    assert same["findings"] == [] and "skipped" in same["summary"]["skipped"][0]


def test_identifiers_are_not_scanned():
    schema = [{"name": "customer_id", "type": "integer"}]
    frame = pd.DataFrame({"__row_id": range(1, 201), "customer_id": list(range(1, 200)) + [10**9]})
    assert anomaly.run_detection(frame, schema)["findings"] == []


def _daily_frame() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    days = pd.date_range("2024-01-01", periods=90, freq="D")
    values = rng.normal(1000, 25, 90)
    values[50] = 3000  # a spike
    return pd.DataFrame({"__row_id": range(1, 91), "day": days, "sales": values})


def test_sudden_time_change_detected_on_the_right_period():
    schema = [{"name": "day", "type": "date"}, {"name": "sales", "type": "float"}]
    result = anomaly.run_detection(_daily_frame(), schema)
    changes = [f for f in result["findings"] if f["kind"] == "time_change"]
    assert "2024-02-20" in {f["period"] for f in changes}
    spike = next(f for f in changes if f["period"] == "2024-02-20")
    assert spike["baseline"] == pytest.approx(1000, abs=60)
    assert spike["severity"] == "high"
    assert len(changes) <= 4
    assert "time:sales" in result["summary"]["series"]


def test_frequency_change_and_missing_pattern():
    rng = np.random.default_rng(5)
    dates = list(pd.date_range("2024-01-01", periods=120, freq="D").repeat(20))
    frame = pd.DataFrame({"day": dates, "note": ["x"] * len(dates)}, dtype=object)
    frame["day"] = pd.to_datetime(frame["day"])
    keep = ~((frame["day"] >= "2024-03-01") & (frame["day"] <= "2024-03-03")) | (rng.random(len(frame)) < 0.05)
    frame = frame[keep].reset_index(drop=True)
    frame.loc[(frame["day"] >= "2024-02-01") & (frame["day"] <= "2024-02-07"), "note"] = None
    frame.loc[frame.sample(40, random_state=1).index, "note"] = None
    frame.insert(0, "__row_id", range(1, len(frame) + 1))
    schema = [{"name": "day", "type": "date"}, {"name": "note", "type": "text"}]
    result = anomaly.run_detection(frame, schema)
    frequency = [f for f in result["findings"] if f["kind"] == "frequency_change"]
    assert {"2024-03-01", "2024-03-02", "2024-03-03"} & {f["period"] for f in frequency}
    missing = [f for f in result["findings"] if f["kind"] == "missing_pattern"]
    assert {f["period"] for f in missing} & {f"2024-02-0{i}" for i in range(1, 8)}


def test_partial_final_period_does_not_create_a_false_drop():
    days = pd.date_range("2022-01-01", "2024-06-03", freq="D")
    frame = pd.DataFrame({"__row_id": range(1, len(days) + 1), "day": days, "amount": 10.0})
    schema = [{"name": "day", "type": "date"}, {"name": "amount", "type": "float"}]
    result = anomaly.run_detection(frame, schema)
    assert not [f for f in result["findings"] if f["kind"] == "time_change" and f["period"] == "2024-06"]


def test_rare_category_detected():
    values = ["A"] * 400 + ["B"] * 300 + ["C"] * 300 + ["Zzz"] * 2
    frame = pd.DataFrame({"__row_id": range(1, len(values) + 1), "kind": values})
    result = anomaly.run_detection(frame, [{"name": "kind", "type": "category"}])
    rare = [f for f in result["findings"] if f["kind"] == "rare_category"]
    assert len(rare) == 1 and rare[0]["observed"].startswith("Zzz")


def test_scan_api_inspection_status_and_filters(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path())
    run = api.post("/api/anomalies/run", json={"dataset_id": dataset["id"]})
    assert run.status_code == 201
    run = run.json()
    assert "not automatically errors" in run["summary"]["disclaimer"]
    results = api.get(f"/api/anomalies/runs/{run['id']}/results", params={"column": "revenue", "kind": "outlier"}).json()
    assert results["total"] >= 10, "the planted bulk orders are found"
    top = results["items"][0]
    assert top["severity"] == "high"
    assert top["observed_value"] == pytest.approx(source["revenue"].max())

    records = api.get(f"/api/anomalies/results/{top['id']}/records").json()
    assert records["rows"][0]["revenue"] == pytest.approx(top["observed_value"])
    assert records["rows"][0]["__row_id"] == top["row_id"]

    updated = api.patch(f"/api/anomalies/results/{top['id']}", json={"status": "investigating"})
    assert updated.json()["status"] == "investigating"
    assert api.patch(f"/api/anomalies/results/{top['id']}", json={"status": "bogus"}).status_code == 422
    assert api.get(f"/api/anomalies/runs/{run['id']}/results", params={"status": "investigating"}).json()["total"] == 1

    assert all(i["severity"] == "high" for i in api.get(f"/api/anomalies/runs/{run['id']}/results", params={"severity": "high"}).json()["items"])
    distribution = api.get(f"/api/anomalies/runs/{run['id']}/chart", params={"column": "revenue", "kind": "outlier"}).json()
    assert distribution["type"] == "distribution"
    assert len(distribution["flagged_points"]) >= 10
    assert sum(b["count"] for b in distribution["histogram"]) == source["revenue"].notna().sum()
    series = api.get(f"/api/anomalies/runs/{run['id']}/chart", params={"column": "revenue", "kind": "time_change"}).json()
    assert series["type"] == "series" and series["points"]


def test_period_finding_can_be_inspected(api: ApiClient):
    days = pd.date_range("2024-01-01", periods=120, freq="D")
    values = np.round(np.random.default_rng(7).normal(1000, 20, 120), 2)
    values[60] = 5000
    csv = pd.DataFrame({"day": days.strftime("%Y-%m-%d"), "sales": values}).to_csv(index=False).encode()
    dataset = api.upload("daily.csv", csv)
    run = api.post("/api/anomalies/run", json={"dataset_id": dataset["id"]}).json()
    items = api.get(f"/api/anomalies/runs/{run['id']}/results", params={"kind": "time_change"}).json()["items"]
    spike = next(i for i in items if i["period"] == "2024-03-01")
    records = api.get(f"/api/anomalies/results/{spike['id']}/records").json()
    assert records["total"] == 1 and records["rows"][0]["sales"] == 5000


@pytest.mark.parametrize("report_type", ["dataset_overview", "data_quality", "sales_performance", "trend_analysis", "anomaly_detection"])
def test_each_report_type_and_export(retail_client, report_type):
    api, dataset = retail_client
    created = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": report_type})
    assert created.status_code == 201, created.text
    report = api.get(f"/api/reports/{created.json()['id']}").json()
    content = report["content"]
    for key in ("title", "workspace", "dataset", "generated_at", "executive_summary", "overview", "methodology", "sections", "recommendations", "limitations"):
        assert content[key] is not None and content[key] != "", key
    assert content["executive_summary"] and content["sections"]

    pdf = api.get(f"/api/reports/{report['id']}/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 2000
    assert pdf.headers["content-type"] == "application/pdf"
    exported_csv = api.get(f"/api/reports/{report['id']}/export/csv")
    assert exported_csv.status_code == 200 and "Overview" in exported_csv.text
    xlsx = api.get(f"/api/reports/{report['id']}/export/xlsx")
    book = openpyxl.load_workbook(io.BytesIO(xlsx.content))
    assert "Overview" in book.sheetnames
    assert api.get(f"/api/reports/{report['id']}/export/docx").status_code == 422


def test_sales_report_numbers_are_correct(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path())
    report = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "sales_performance", "title": "Sales Review"}).json()
    content = api.get(f"/api/reports/{report['id']}").json()["content"]
    assert content["title"] == "Sales Review"
    assert f"{source['revenue'].sum():,.2f}" in content["executive_summary"][0]
    region = next(s for s in content["sections"] if s["heading"] == "revenue by region")
    expected = source.groupby("region")["revenue"].sum().max()
    assert region["table"]["rows"][0]["total revenue"] == pytest.approx(expected)


def test_report_requirements_are_explained(api: ApiClient):
    dataset = api.upload("t.csv", b"name,score\nA,1\nB,2\n")
    sales = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "sales_performance"})
    assert sales.status_code == 422 and "date column" in sales.json()["detail"]
    trend = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "trend_analysis"})
    assert trend.status_code == 422
    custom = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "custom_ai", "questions": []})
    assert custom.status_code == 422
    unknown = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "nope"})
    assert unknown.status_code == 422


def test_custom_report_is_labelled_as_demonstration(retail_client):
    api, dataset = retail_client
    created = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "custom_ai", "questions": ["total revenue by region", "What will happen next year?"]})
    assert created.status_code == 201
    content = api.get(f"/api/reports/{created.json()['id']}").json()["content"]
    assert content["ai"]["mode"] == "demonstration"
    assert any("not an AI model" in m for m in content["methodology"])
    assert api.get(f"/api/reports/{created.json()['id']}/export/pdf").status_code == 200


def test_pdf_handles_hostile_text(api: ApiClient):
    dataset = api.upload("x.csv", b"<b>name</b>,value\n<script>&bad</script>,1\n=cmd,2\n\xe2\x98\x83 snow,3\n")
    report = api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "dataset_overview", "title": "<b>Title</b> & more"})
    assert report.status_code == 201
    assert api.get(f"/api/reports/{report.json()['id']}/export/pdf").content.startswith(b"%PDF")


def test_export_helpers_neutralise_formulas():
    assert safe_cell("=1+1") == "'=1+1"
    assert safe_cell("@x") == "'@x"
    assert safe_cell("-12.5") == "-12.5"
    assert safe_cell(-5) == -5
    tables = [{"title": "=T", "columns": ["=c", "n"], "rows": [{"=c": "=SUM(A1)", "n": 1}]}]
    assert "'=SUM(A1)" in tables_to_csv(tables)
    book = openpyxl.load_workbook(io.BytesIO(tables_to_xlsx(tables)))
    sheet = book.worksheets[0]
    assert sheet.cell(row=2, column=1).value == "'=SUM(A1)"
    assert sheet.cell(row=2, column=1).data_type == "s"
    assert sheet.cell(row=2, column=2).value == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pass@example.com/",
        "http://example.com:6379/",
        "http://",
    ],
)
def test_ssrf_blocked_urls(url, monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"example.com": "93.184.216.34"}))
    with pytest.raises(connections.ConnectionFailure):
        connections.validate_url(url)


def _resolver(table: dict):
    def lookup(host, port, *args, **kwargs):
        host = host.strip("[]")
        address = table.get(host, host)
        if host == "localhost":
            address = "127.0.0.1"
        return [(2, 1, 6, "", (address, port))]

    return lookup


def test_dns_rebinding_to_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"evil.example": "10.1.2.3"}))
    with pytest.raises(connections.ConnectionFailure, match="internal"):
        connections.validate_url("https://evil.example/data")


def test_redirect_to_internal_address_is_blocked(monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"public.example": "93.184.216.34"}))
    transport = httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"}))
    with pytest.raises(connections.ConnectionFailure, match="internal"):
        connections.fetch_json("https://public.example/a", transport=transport)


def test_request_is_pinned_to_the_validated_address(monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"public.example": "93.184.216.34"}))
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"a": 1}])

    assert connections.fetch_json("https://public.example/items?x=1", transport=httpx.MockTransport(handler), secret={"header_name": "X-Key", "header_value": "s3cret"}) == [{"a": 1}]
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "public.example"
    assert seen[0].url.query == b"x=1"
    assert seen[0].extensions["sni_hostname"] == "public.example"
    assert seen[0].headers["x-key"] == "s3cret"


def test_credentials_are_not_forwarded_across_hosts(monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"a.example": "93.184.216.34", "b.example": "93.184.216.35"}))
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["host"] == "a.example":
            return httpx.Response(302, headers={"location": "https://b.example/x"})
        return httpx.Response(200, json=[])

    connections.fetch_json("https://a.example/", secret={"header_name": "X-Key", "header_value": "s3cret"}, transport=httpx.MockTransport(handler))
    assert "x-key" in seen[0].headers
    assert "x-key" not in seen[1].headers


def test_response_limits_and_errors(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"public.example": "93.184.216.34"}))
    monkeypatch.setattr(get_settings(), "connection_max_response_mb", 1)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"[" + b"1," * 1_000_000 + b"1]"))
    with pytest.raises(connections.ConnectionFailure, match="limit"):
        connections.fetch_json("https://public.example/", transport=big)
    with pytest.raises(connections.ConnectionFailure, match="status 500"):
        connections.fetch_json("https://public.example/", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(connections.ConnectionFailure, match="not valid JSON"):
        connections.fetch_json("https://public.example/", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(connections.ConnectionFailure, match="timed out"):
        connections.fetch_json("https://public.example/", transport=httpx.MockTransport(timeout))


def test_connection_api_stores_secrets_encrypted_and_never_returns_them(api: ApiClient, monkeypatch):
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Credential, DataConnection

    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"api.example": "93.184.216.34"}))
    created = api.post("/api/connections", json={"name": "Orders API", "kind": "rest_api", "url": "https://api.example/orders", "records_path": "data.items", "header_name": "Authorization", "header_value": "Bearer top-secret-token"})
    assert created.status_code == 201, created.text
    assert "top-secret-token" not in created.text
    assert created.json()["has_secret"] is True
    listing = api.get("/api/connections")
    assert "top-secret-token" not in listing.text
    with session_scope() as db:
        connection = db.scalar(select(DataConnection).where(DataConnection.id == created.json()["id"]))
        assert "top-secret-token" not in json.dumps(connection.config)
        stored = db.scalar(select(Credential).where(Credential.connection_id == connection.id))
        assert "top-secret-token" not in stored.encrypted_value


def test_connection_api_rejects_internal_targets(api: ApiClient):
    response = api.post("/api/connections", json={"name": "x", "kind": "rest_api", "url": "http://127.0.0.1/secret"})
    assert response.status_code == 422 and "internal" in response.json()["detail"]
    database = api.post("/api/connections", json={"name": "x", "kind": "postgresql", "host": "127.0.0.1", "database": "d", "username": "u"})
    assert database.status_code == 422


def test_rest_import_goes_through_the_pipeline(api: ApiClient, monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"api.example": "93.184.216.34"}))
    payload = {"data": {"items": [{"id": 1, "amount": 10.5, "when": "2024-01-01"}, {"id": 2, "amount": 20.5, "when": "2024-01-02"}]}}
    monkeypatch.setattr(connections, "fetch_json", lambda url, secret=None, transport=None: payload)
    created = api.post("/api/connections", json={"name": "Orders", "kind": "rest_api", "url": "https://api.example/orders", "records_path": "data.items"}).json()
    tested = api.post(f"/api/connections/{created['id']}/test").json()
    assert tested == {"ok": True, "records": 2}
    imported = api.post(f"/api/connections/{created['id']}/import", json={})
    assert imported.status_code == 202
    dataset = api.wait_ready(imported.json()["id"])
    assert dataset["status"] == "ready" and dataset["source_type"] == "connection"
    assert {c["name"]: c["type"] for c in dataset["columns"]}["when"] == "date"
    assert api.delete(f"/api/connections/{created['id']}").status_code == 200
    assert api.get(f"/api/datasets/{dataset['id']}").status_code == 200, "imported data remains after disconnecting"


def test_failed_test_is_recorded_without_leaking(api: ApiClient, monkeypatch):
    monkeypatch.setattr(connections.socket, "getaddrinfo", _resolver({"api.example": "93.184.216.34"}))
    created = api.post("/api/connections", json={"name": "Down", "kind": "rest_api", "url": "https://api.example/down", "header_name": "X-Key", "header_value": "hidden-value"}).json()

    def fail(url, secret=None, transport=None):
        raise connections.ConnectionFailure("The request timed out.")

    monkeypatch.setattr(connections, "fetch_json", fail)
    result = api.post(f"/api/connections/{created['id']}/test")
    assert result.json() == {"ok": False, "error": "The request timed out."}
    assert "hidden-value" not in result.text
    assert api.get("/api/connections").json()[0]["last_status"] == "failed"


def test_demo_datasets_load_labelled_and_analysable(api: ApiClient):
    loaded = api.post("/api/datasets/demo")
    assert loaded.status_code == 202
    created = loaded.json()
    assert len(created) == 5
    assert all(d["is_demo"] and "Synthetic" in d["name"] for d in created)
    ready = [api.wait_ready(d["id"], timeout=120) for d in created]
    assert all(d["status"] == "ready" for d in ready), [d["error_message"] for d in ready]
    assert api.post("/api/datasets/demo").json() == [], "loading twice does not duplicate them"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not api.get("/api/reports").json():
        time.sleep(0.2)
    reports = api.get("/api/reports").json()
    assert reports and reports[0]["is_demo"]
    assert "synthetic" in api.get(f"/api/reports/{reports[0]['id']}").json()["content"]["limitations"][0].lower()
    assert api.get("/api/anomalies/runs").json()
    assert api.get("/api/visualisations").json()


def test_overview_metrics_reflect_database_records(api: ApiClient):
    empty = api.get("/api/overview").json()
    assert empty["metrics"]["total_datasets"] == 0 and empty["metrics"]["records_analysed"] == 0
    dataset = api.upload("a.csv", b"region,revenue\nA,1\nB,2\nC,3\n")
    api.upload("b.csv", b"x\n1\n2\n")
    api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue"})
    api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "dataset_overview"})
    overview = api.get("/api/overview", params={"activity_range": "24h"}).json()
    metrics = overview["metrics"]
    assert metrics["total_datasets"] == 2
    assert metrics["records_analysed"] == 5
    assert metrics["active_reports"] == 1
    assert metrics["total_analyses"] == 4
    assert len(overview["activity"]["points"]) == 24
    assert sum(p["count"] for p in overview["activity"]["points"]) == 4
    assert len(api.get("/api/overview", params={"activity_range": "30d"}).json()["activity"]["points"]) == 30
    assert len(overview["datasets"]) == 2 and overview["analyses"][0]["link"]
    assert api.get("/api/overview", params={"activity_range": "1y"}).status_code == 422


def test_global_search_and_notifications(api: ApiClient):
    dataset = api.upload("orders.csv", b"region,revenue\nA,1\nB,2\n", name="Quarterly Orders")
    api.post("/api/reports", json={"dataset_id": dataset["id"], "report_type": "data_quality", "title": "Quarterly review"})
    results = api.get("/api/search", params={"q": "quarterly"}).json()
    assert {r["type"] for r in results} == {"Dataset", "Report"}
    notes = api.get("/api/notifications").json()
    assert notes["unread"] >= 2
    api.post(f"/api/notifications/{notes['items'][0]['id']}/read")
    assert api.get("/api/notifications").json()["unread"] == notes["unread"] - 1
    api.post("/api/notifications/read-all")
    assert api.get("/api/notifications").json()["unread"] == 0


def test_interrupted_jobs_are_resumed(api: ApiClient):
    from app.db import session_scope
    from app.models import Dataset
    from app.services import jobs

    dataset = api.upload("resume.csv", b"a\n1\n2\n")
    with session_scope() as db:
        db.get(Dataset, dataset["id"]).status = "processing"
    assert jobs.resume_interrupted() >= 1
    assert api.wait_ready(dataset["id"])["status"] == "ready"


def test_workspace_management(api: ApiClient):
    second = api.post("/api/workspaces", json={"name": "Second"}).json()
    assert second["role"] == "owner"
    names = {w["name"] for w in api.get("/api/workspaces").json()}
    assert "Second" in names
    first_id = api.workspace_id
    api.upload("a.csv", b"x\n1\n")
    api.workspace_id = second["id"]
    assert api.get("/api/datasets").json() == [], "workspaces are separate"
    api.upload("b.csv", b"y\n1\n")
    assert api.patch("/api/workspaces/current", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert api.delete("/api/workspaces/current").status_code == 200
    api.workspace_id = first_id
    assert len(api.get("/api/datasets").json()) == 1
    assert api.delete("/api/workspaces/current").status_code == 409, "the last workspace stays"
