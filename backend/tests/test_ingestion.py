"""Upload validation, parsing, type inference, and profile correctness."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import numpy as np
import openpyxl
import pandas as pd
import pytest
import xlwt

from app.services import storage
from app.services.inference import infer_column
from tests.conftest import SALES_CSV, ApiClient, retail_path


def column(profile: dict, name: str) -> dict:
    return next(c for c in profile["profile"]["columns"] if c["name"] == name)


def test_csv_upload_metadata_and_types(api: ApiClient, sales: dict):
    assert sales["row_count"] == 8
    assert sales["column_count"] == 7
    assert sales["file_format"] == "csv"
    types = {c["name"]: c["type"] for c in sales["columns"]}
    assert types["order_date"] == "date"
    assert types["quantity"] == "integer"
    assert types["revenue"] == "float"
    assert types["region"] == "category"
    assert sales["versions"][0]["label"] == "Original import"


def test_profile_statistics_match_numpy(api: ApiClient, sales: dict):
    profile = api.get(f"/api/datasets/{sales['id']}/profile").json()
    revenue = column(profile, "revenue")
    values = np.array([100, 50, 300, 100, 250, 200, 200], dtype=float)
    assert revenue["count"] == 7 and revenue["missing"] == 1
    assert revenue["mean"] == pytest.approx(values.mean())
    assert revenue["median"] == pytest.approx(np.median(values))
    assert revenue["std"] == pytest.approx(values.std(ddof=1))
    assert revenue["q1"] == pytest.approx(np.percentile(values, 25))
    assert revenue["q3"] == pytest.approx(np.percentile(values, 75))
    assert revenue["min"] == 50 and revenue["max"] == 300
    assert profile["profile"]["duplicate_rows"] == 1


def test_only_appropriate_statistics_are_calculated(api: ApiClient, sales: dict):
    profile = api.get(f"/api/datasets/{sales['id']}/profile").json()
    region = column(profile, "region")
    assert "mean" not in region and "std" not in region
    assert region["unique"] == 3
    assert region["top_values"][0] == {"value": "North", "count": 4, "share": 0.5}
    date = column(profile, "order_date")
    assert "mean" not in date
    assert date["earliest"].startswith("2024-01-05") and date["latest"].startswith("2024-04-01")
    assert date["range_days"] == 87


def test_retail_profile_matches_independent_pandas_calculation(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path())
    profile = api.get(f"/api/datasets/{dataset['id']}/profile").json()
    assert profile["profile"]["row_count"] == len(source)
    assert profile["profile"]["duplicate_rows"] == int(source.duplicated().sum())
    revenue = column(profile, "revenue")
    assert revenue["mean"] == pytest.approx(source["revenue"].mean())
    assert revenue["std"] == pytest.approx(source["revenue"].std())
    assert revenue["q3"] == pytest.approx(source["revenue"].quantile(0.75))
    assert column(profile, "discount_pct")["missing"] == int(source["discount_pct"].isna().sum())


def test_original_file_is_preserved_byte_for_byte(api: ApiClient, sales: dict):
    from app.db import session_scope
    from app.models import Dataset

    with session_scope() as db:
        ref = db.get(Dataset, sales["id"]).storage_ref
    assert storage.resolve_ref(ref).read_bytes() == SALES_CSV


def test_xlsx_upload(api: ApiClient):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Joined", "Score", "Active"])
    sheet.append(["Ann", datetime(2024, 1, 2), 1.5, True])
    sheet.append(["Bob", datetime(2024, 2, 3), 2.5, False])
    sheet.append(["Cat", datetime(2024, 3, 4), "=1+1", True])
    workbook.create_sheet("Other").append(["ignored"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    dataset = api.upload("people.xlsx", buffer.getvalue())
    assert dataset["status"] == "ready", dataset
    assert dataset["file_format"] == "xlsx" and dataset["row_count"] == 3
    types = {c["name"]: c["type"] for c in dataset["columns"]}
    assert types["Joined"] == "date" and types["Active"] == "boolean"
    assert any("sheets" in n for n in dataset["ingest_notes"])
    assert any("not evaluated" in n for n in dataset["ingest_notes"])
    rows = api.post(f"/api/datasets/{dataset['id']}/rows", json={}).json()["rows"]
    assert rows[2]["Score"] is None, "uncached formula results stay missing; the formula never runs"


def test_xls_upload(api: ApiClient):
    book = xlwt.Workbook()
    sheet = book.add_sheet("Data")
    for col, name in enumerate(["city", "sales"]):
        sheet.write(0, col, name)
    for row, (city, value) in enumerate([("Leeds", 10), ("York", 20), ("Hull", 30)], start=1):
        sheet.write(row, 0, city)
        sheet.write(row, 1, value)
    buffer = io.BytesIO()
    book.save(buffer)
    dataset = api.upload("cities.xls", buffer.getvalue())
    assert dataset["status"] == "ready", dataset
    assert dataset["file_format"] == "xls" and dataset["row_count"] == 3
    assert {c["name"]: c["type"] for c in dataset["columns"]}["sales"] == "integer"


@pytest.mark.parametrize(
    ("payload", "rows", "columns"),
    [
        ([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], 2, 2),
        ({"data": [{"a": 1}, {"a": 2}, {"a": 3}]}, 3, 1),
        ([{"a": {"nested": 1}, "tags": ["p", "q"]}], 1, 2),
    ],
)
def test_json_upload(api: ApiClient, payload, rows, columns):
    dataset = api.upload("records.json", json.dumps(payload).encode())
    assert dataset["status"] == "ready", dataset
    assert (dataset["row_count"], dataset["column_count"]) == (rows, columns)


def test_ndjson_and_encodings(api: ApiClient):
    ndjson = api.upload("lines.json", b'{"a":1}\n{"a":2}\n')
    assert ndjson["row_count"] == 2
    latin = api.upload("cafe.csv", "name,price\nCafé,3\nThé,4\n".encode("cp1252"))
    assert latin["status"] == "ready"
    rows = api.post(f"/api/datasets/{latin['id']}/rows", json={}).json()["rows"]
    assert rows[0]["name"] == "Café"
    semicolon = api.upload("semi.csv", b"a;b\n1;2\n3;4\n")
    assert semicolon["column_count"] == 2
    utf16 = api.upload("u16.csv", "a,b\n1,2\n".encode("utf-16"))
    assert utf16["status"] == "ready" and utf16["row_count"] == 1


@pytest.mark.parametrize(
    ("filename", "content", "fragment"),
    [
        ("malware.exe", b"MZ\x90\x00", "Unsupported file type"),
        ("data.csv", b"MZ\x90\x00binary", "binary"),
        ("data.csv", b"PK\x03\x04 pretend zip", "binary workbook"),
        ("fake.xlsx", b"a,b\n1,2\n", "not a valid XLSX"),
        ("fake.xls", b"a,b\n1,2\n", "not a valid XLS"),
        ("page.csv", b"%PDF-1.7 content", "binary"),
        ("nul.csv", b"a,b\n\x00\x00\x00", "binary"),
        ("empty.csv", b"", "empty"),
        ("noextension", b"a,b\n1,2\n", "Unsupported file type"),
    ],
)
def test_invalid_files_rejected_at_upload(api: ApiClient, filename, content, fragment):
    response = api.post("/api/datasets", files={"file": (filename, content)})
    assert response.status_code == 415, response.text
    assert fragment in response.json()["detail"]
    assert api.get("/api/datasets").json() == []


@pytest.mark.parametrize(
    ("filename", "content", "fragment"),
    [
        ("bad.json", b"{not json", "not valid JSON"),
        ("scalars.json", b"[1,2,3]", "must be an object"),
        ("empty.json", b"[]", "no records"),
        ("header.csv", b"a,b,c\n", "no data rows"),
        ("broken.csv", b"a,b\n1,2\n1,2,3,4,5\n", "inconsistent column counts"),
        ("blank.csv", b"   \n  \n", "no data"),
    ],
)
def test_invalid_structure_fails_safely(api: ApiClient, filename, content, fragment):
    dataset = api.upload(filename, content)
    assert dataset["status"] == "failed"
    assert fragment in dataset["error_message"]
    assert api.post(f"/api/datasets/{dataset['id']}/rows", json={}).status_code == 409


def _zip_workbook(extra: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        for name, data in extra.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_macro_workbook_rejected(api: ApiClient):
    dataset = api.upload("macro.xlsx", _zip_workbook({"xl/vbaProject.bin": b"attribute VB_Name"}))
    assert dataset["status"] == "failed" and "macros" in dataset["error_message"]


def test_zip_bomb_rejected(api: ApiClient, monkeypatch):
    from app.services import parsing

    monkeypatch.setattr(parsing, "MAX_UNCOMPRESSED_BYTES", 1024 * 1024)
    dataset = api.upload("bomb.xlsx", _zip_workbook({"xl/worksheets/sheet1.xml": b"0" * (5 * 1024 * 1024)}))
    assert dataset["status"] == "failed" and "unsafe size" in dataset["error_message"]


def test_corrupt_workbook_rejected(api: ApiClient):
    dataset = api.upload("corrupt.xlsx", _zip_workbook({}))
    assert dataset["status"] == "failed"
    assert "could not be read" in dataset["error_message"] or "no data" in dataset["error_message"]


def test_file_size_limit(api: ApiClient, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    response = api.post("/api/datasets", files={"file": ("big.csv", b"a,b\n" + b"1,2\n" * 300_000)})
    assert response.status_code == 413
    just_over = api.post("/api/datasets", files={"file": ("over.csv", b"a,b\n" + b"1,2\n" * 270_000)})
    assert just_over.status_code == 413, "the streaming check covers sizes the header check allows"


def test_row_and_column_limits(api: ApiClient):
    too_many_rows = b"a\n" + b"1\n" * 20_001
    dataset = api.upload("rows.csv", too_many_rows)
    assert dataset["status"] == "failed" and "20,000 rows" in dataset["error_message"]
    header = ",".join(f"c{i}" for i in range(51)).encode() + b"\n" + ",".join("1" for _ in range(51)).encode() + b"\n"
    wide = api.upload("wide.csv", header)
    assert wide["status"] == "failed" and "50" in wide["error_message"]


def test_duplicate_and_blank_column_names_are_made_safe(api: ApiClient):
    dataset = api.upload("cols.csv", b'a,a,,"bad""name",__row_id\n1,2,3,4,5\n6,7,8,9,10\n')
    assert dataset["status"] == "ready", dataset
    names = [c["name"] for c in dataset["columns"]]
    assert len(set(n.lower() for n in names)) == 5
    assert "__row_id" not in names
    assert 'bad"name' in names
    rows = api.post(f"/api/datasets/{dataset['id']}/rows", json={"filters": [{"column": 'bad"name', "op": "gt", "value": 5}]}).json()
    assert rows["total"] == 1


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["1", "2", "3"], "integer"),
        (["1.5", "2", "3.25"], "float"),
        (["1,234", "5,678.50", "9"], "float"),
        (["007", "012", "123"], "text"),
        (["007", "012", "007"], "category"),
        (["true", "false", "true"], "boolean"),
        (["Yes", "No", None], "boolean"),
        (["2024-01-15", "2024-02-20", None], "date"),
        (["2024-01-15T10:00:00Z", "2024-02-20T11:30:00+01:00"], "date"),
        (["15/01/2024", "20/02/2024"], "date"),
        (["1", "2", "abc"], "text"),
        (["2024-01-15", "not a date", "2024-02-20"], "text"),
        (["NA", "", "null"], "text"),
    ],
)
def test_type_inference(values, expected):
    data_type, _typed, _notes = infer_column(pd.Series(values, dtype=object), "c")
    assert data_type == expected


def test_ambiguous_dates_are_reported():
    data_type, typed, notes = infer_column(pd.Series(["01/02/2024", "03/04/2024", "05/06/2024"], dtype=object), "when")
    assert data_type == "date"
    assert notes and "month-first" in notes[0]
    assert typed.iloc[0].month == 1


def test_mixed_column_is_not_silently_converted(api: ApiClient):
    dataset = api.upload("mix.csv", b"v\n" + b"".join(f"{i}\n".encode() for i in range(30)) + b"oops\n")
    assert {c["name"]: c["type"] for c in dataset["columns"]}["v"] in {"text", "category"}
    quality = api.get(f"/api/datasets/{dataset['id']}/profile").json()["quality"]
    assert any(i["check"] == "inconsistent_types" and i["count"] == 1 for i in quality["issues"])


def test_upload_progress_fields_and_listing(api: ApiClient):
    pending = api.upload("a.csv", b"x\n1\n2\n", wait=False, name="Named set")
    assert pending["status"] in {"queued", "processing", "ready"}
    assert pending["name"] == "Named set"
    api.wait_ready(pending["id"])
    listed = api.get("/api/datasets", params={"search": "named"}).json()
    assert [d["id"] for d in listed] == [pending["id"]]
    assert api.get("/api/datasets", params={"search": "%"}).json() == [], "wildcards are treated literally"


def test_dataset_rename_duplicate_project_delete(api: ApiClient, sales: dict):
    dataset_id = sales["id"]
    project = api.post("/api/projects", json={"name": "Q1"}).json()
    updated = api.patch(f"/api/datasets/{dataset_id}", json={"name": "Renamed", "project_id": project["id"]}).json()
    assert updated["name"] == "Renamed" and updated["project_id"] == project["id"]
    assert api.get("/api/projects").json()[0]["dataset_count"] == 1
    assert api.get("/api/datasets", params={"project_id": project["id"]}).json()[0]["project_name"] == "Q1"

    copy = api.post(f"/api/datasets/{dataset_id}/duplicate")
    assert copy.status_code == 201
    copy_id = copy.json()["id"]
    assert copy.json()["row_count"] == 8 and copy.json()["source_type"] == "derived"

    api.post("/api/anomalies/run", json={"dataset_id": dataset_id})
    api.post("/api/reports", json={"dataset_id": dataset_id, "report_type": "dataset_overview"})
    folder = storage.data_root() / api.workspace_id / "datasets" / dataset_id
    assert folder.exists()
    assert api.delete(f"/api/datasets/{dataset_id}").status_code == 200
    assert not folder.exists(), "files are removed with the dataset"
    assert api.get(f"/api/datasets/{dataset_id}").status_code == 404
    assert api.get("/api/reports").json() == [], "derived reports are removed"
    assert api.get("/api/anomalies/runs", params={"dataset_id": dataset_id}).json() == []
    assert api.get(f"/api/datasets/{copy_id}").status_code == 200, "the copy is independent"
    actions = {log["action"] for log in api.get("/api/audit-logs").json()}
    assert {"dataset.uploaded", "dataset.deleted", "dataset.duplicated"} <= actions
