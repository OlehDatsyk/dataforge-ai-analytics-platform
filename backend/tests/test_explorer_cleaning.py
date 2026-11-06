"""Server-side exploration, data quality checks, and non-destructive cleaning."""
from __future__ import annotations

import csv
import io

import pandas as pd
import pytest

from tests.conftest import ApiClient, retail_path


def rows(api: ApiClient, dataset_id: str, **body) -> dict:
    response = api.post(f"/api/datasets/{dataset_id}/rows", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_pagination_returns_only_the_requested_page(retail_client):
    api, dataset = retail_client
    first = rows(api, dataset["id"], page=1, page_size=25)
    second = rows(api, dataset["id"], page=2, page_size=25)
    assert first["total"] == dataset["row_count"]
    assert len(first["rows"]) == 25 and len(second["rows"]) == 25
    assert first["page_count"] == (dataset["row_count"] + 24) // 25
    assert first["rows"][-1]["__row_id"] + 1 == second["rows"][0]["__row_id"]
    too_big = api.post(f"/api/datasets/{dataset['id']}/rows", json={"page_size": 100000})
    assert too_big.status_code == 422, "page size is capped"
    beyond = rows(api, dataset["id"], page=99999, page_size=25)
    assert beyond["rows"] == [] and beyond["total"] == dataset["row_count"]


def test_sorting_matches_pandas(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path())
    top = rows(api, dataset["id"], sort=[{"column": "revenue", "direction": "desc"}], page_size=5)["rows"]
    assert [r["revenue"] for r in top] == pytest.approx(source["revenue"].nlargest(5).tolist())
    low = rows(api, dataset["id"], sort=[{"column": "revenue", "direction": "asc"}], page_size=1)["rows"]
    assert low[0]["revenue"] == pytest.approx(source["revenue"].min())


def test_filter_examples_match_pandas(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path(), parse_dates=["order_date"])
    identifier = dataset["id"]
    assert rows(api, identifier, filters=[{"column": "revenue", "op": "gt", "value": 1000}])["total"] == int((source["revenue"] > 1000).sum())
    assert rows(api, identifier, filters=[{"column": "country", "op": "eq", "value": "United Kingdom"}])["total"] == int((source["country"] == "United Kingdom").sum())
    between = rows(api, identifier, filters=[{"column": "order_date", "op": "between", "values": ["2024-03-01", "2024-03-31"]}])
    assert between["total"] == int(source["order_date"].between("2024-03-01", "2024-03-31").sum())
    contains = rows(api, identifier, filters=[{"column": "product", "op": "contains", "value": "speaker"}])
    assert contains["total"] == int(source["product"].str.contains("speaker", case=False).sum())
    missing = rows(api, identifier, filters=[{"column": "discount_pct", "op": "is_null"}])
    assert missing["total"] == int(source["discount_pct"].isna().sum())
    combined = rows(api, identifier, filters=[{"column": "region", "op": "eq", "value": "Europe"}, {"column": "quantity", "op": "gte", "value": 3}])
    assert combined["total"] == int(((source["region"] == "Europe") & (source["quantity"] >= 3)).sum())
    multiple = rows(api, identifier, filters=[{"column": "category", "op": "in", "values": ["Home", "Office"]}])
    assert multiple["total"] == int(source["category"].isin(["Home", "Office"]).sum())


def test_date_only_filters_cover_the_whole_day(api: ApiClient):
    dataset = api.upload("t.csv", b"at,n\n2024-03-30 09:00:00,1\n2024-03-31 00:00:00,2\n2024-03-31 18:30:00,3\n2024-04-01 00:00:00,4\n")
    identifier = dataset["id"]

    def ids(**item):
        found = rows(api, identifier, filters=[{"column": "at", **item}])["rows"]
        return [r["n"] for r in found]

    assert ids(op="between", values=["2024-03-30", "2024-03-31"]) == [1, 2, 3]
    assert ids(op="eq", value="2024-03-31") == [2, 3]
    assert ids(op="ne", value="2024-03-31") == [1, 4]
    assert ids(op="lte", value="2024-03-31") == [1, 2, 3]
    assert ids(op="gt", value="2024-03-31") == [4]
    assert ids(op="gte", value="2024-03-31") == [2, 3, 4]
    assert ids(op="lt", value="2024-03-31") == [1]
    assert ids(op="eq", value="2024-03-31T18:30:00") == [3]

    def kept(**item):
        preview = clean(api, identifier, {"op": "filter_rows", "filters": [{"column": "at", **item}]})
        return [r["n"] for r in preview["sample"]]

    assert kept(op="between", values=["2024-03-30", "2024-03-31"]) == [1, 2, 3]
    assert kept(op="eq", value="2024-03-31") == [2, 3]
    assert kept(op="lte", value="2024-03-31") == [1, 2, 3]
    assert kept(op="gt", value="2024-03-31") == [4]


def test_search_and_column_selection(retail_client):
    api, dataset = retail_client
    source = pd.read_csv(retail_path())
    result = rows(api, dataset["id"], search="ORD-100005", columns=["order_id", "revenue"])
    assert result["columns"] == ["order_id", "revenue"]
    assert set(result["rows"][0]) == {"__row_id", "order_id", "revenue"}
    assert result["total"] == int((source["order_id"] == "ORD-100005").sum())


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"filters": [{"column": "missing_col", "op": "eq", "value": 1}]}, "does not exist"),
        ({"filters": [{"column": "revenue", "op": "gt", "value": "abc"}]}, "not a number"),
        ({"filters": [{"column": "region", "op": "gt", "value": "a"}]}, "only applies to numbers"),
        ({"filters": [{"column": "revenue", "op": "contains", "value": "1"}]}, "only applies to text"),
        ({"filters": [{"column": "order_date", "op": "eq", "value": "yesterday"}]}, "not a valid ISO date"),
        ({"filters": [{"column": "revenue", "op": "between", "values": [1]}]}, "needs two values"),
        ({"sort": [{"column": "nope", "direction": "asc"}]}, "does not exist"),
        ({"columns": ["nope"]}, "does not exist"),
    ],
)
def test_invalid_queries_are_rejected(retail_client, body, fragment):
    api, dataset = retail_client
    response = api.post(f"/api/datasets/{dataset['id']}/rows", json=body)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


@pytest.mark.parametrize("attack", ["'; DROP TABLE data; --", "x' OR '1'='1", "\" OR 1=1 --", "%' UNION SELECT * FROM read_csv('C:/Windows/win.ini') --"])
def test_sql_injection_is_inert(retail_client, attack):
    api, dataset = retail_client
    assert rows(api, dataset["id"], filters=[{"column": "region", "op": "eq", "value": attack}])["total"] == 0
    assert rows(api, dataset["id"], filters=[{"column": "region", "op": "contains", "value": attack}])["total"] == 0
    assert rows(api, dataset["id"], search=attack)["total"] == 0
    bad_column = api.post(f"/api/datasets/{dataset['id']}/rows", json={"sort": [{"column": attack, "direction": "asc"}]})
    assert bad_column.status_code == 422
    assert rows(api, dataset["id"], page_size=1)["total"] == dataset["row_count"]


def test_wildcards_are_literal_in_search(api: ApiClient):
    dataset = api.upload("w.csv", b"code,n\nA%B,1\nAXB,2\nA_B,3\n")
    assert rows(api, dataset["id"], filters=[{"column": "code", "op": "contains", "value": "%"}])["total"] == 1
    assert rows(api, dataset["id"], filters=[{"column": "code", "op": "contains", "value": "_"}])["total"] == 1


def test_duckdb_cannot_read_other_files(sales, api):
    from app.db import session_scope
    from app.models import DatasetVersion
    from app.services import storage
    from app.services.query_engine import connect

    with session_scope() as db:
        version = db.query(DatasetVersion).filter_by(dataset_id=sales["id"]).one()
        path = storage.resolve_ref(version.storage_ref)
    with connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM data").fetchone()[0] == 8
        with pytest.raises(Exception):
            con.execute("SELECT * FROM read_csv('C:/Windows/win.ini')").fetchall()
        with pytest.raises(Exception):
            con.execute("SET enable_external_access=true")


def test_export_protects_against_formula_injection(api: ApiClient):
    dataset = api.upload("f.csv", b'name,value\n"=HYPERLINK(""http://evil"")",1\n"+cmd|calc",-2\n@sum,3\n-5,4\nsafe,5\n')
    response = api.post(f"/api/datasets/{dataset['id']}/export", json={})
    assert response.status_code == 200
    table = list(csv.reader(io.StringIO(response.text)))
    assert table[1][0].startswith("'=")
    assert table[2][0].startswith("'+")
    assert table[2][1] == "-2", "real numbers keep their sign"
    assert table[3][0].startswith("'@")
    assert table[4][0] == "-5"
    assert table[5][0] == "safe"


def test_export_respects_filters(retail_client):
    api, dataset = retail_client
    response = api.post(f"/api/datasets/{dataset['id']}/export", json={"filters": [{"column": "region", "op": "eq", "value": "Europe"}], "columns": ["order_id", "region"]})
    table = list(csv.reader(io.StringIO(response.text)))
    source = pd.read_csv(retail_path())
    assert table[0] == ["order_id", "region"]
    assert len(table) - 1 == int((source["region"] == "Europe").sum())


QUALITY_CSV = b"""id,name,country,amount,when,blank,price
1, Ann ,UK,10,2024-01-01,,$10.00
2,Bob,uk,20,2024-01-02,,$20.00
3,Cid,UK,,2024-01-03,,$30.00
4,Dee,France,40,not-a-date,,$40.00
5,Eve,France,50,2024-01-05,,50
5,Eve,France,50,2024-01-05,,50
"""


def test_quality_checks_identify_each_problem(api: ApiClient):
    dataset = api.upload("q.csv", QUALITY_CSV)
    quality = api.get(f"/api/datasets/{dataset['id']}/profile").json()["quality"]
    found = {(i["check"], i["column"]): i for i in quality["issues"]}
    assert found[("duplicates", None)]["count"] == 1
    assert found[("whitespace", "name")]["count"] == 1
    assert found[("inconsistent_categories", "country")]["count"] == 3
    assert found[("missing_values", "amount")]["count"] == 1
    assert found[("empty_column", "blank")]["count"] == 6
    assert found[("invalid_dates", "when")]["count"] == 1
    assert ("formatting", "price") in found
    assert quality["score"] < 100
    outliers = api.upload("o.csv", b"v\n" + b"".join(f"{i % 7}\n".encode() for i in range(40)) + b"1000\n")
    assert any(i["check"] == "outliers" and i["count"] == 1 for i in api.get(f"/api/datasets/{outliers['id']}/profile").json()["quality"]["issues"])


def clean(api: ApiClient, dataset_id: str, *operations, apply=False, **extra):
    path = "apply" if apply else "preview"
    response = api.post(f"/api/datasets/{dataset_id}/cleaning/{path}", json={"operations": list(operations), **extra})
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_preview_changes_nothing(api: ApiClient):
    dataset = api.upload("q.csv", QUALITY_CSV)
    preview = clean(api, dataset["id"], {"op": "remove_duplicates"})
    assert preview["rows_before"] == 6 and preview["rows_after"] == 5
    assert preview["saved"] is False
    assert "Removes 1 duplicate" in preview["effects"][0]["description"]
    after = api.get(f"/api/datasets/{dataset['id']}").json()
    assert after["row_count"] == 6 and len(after["versions"]) == 1


def test_apply_creates_version_and_preserves_original(api: ApiClient):
    dataset = api.upload("q.csv", QUALITY_CSV)
    original_version = dataset["current_version_id"]
    result = clean(api, dataset["id"], {"op": "remove_duplicates"}, {"op": "trim_whitespace", "columns": ["name"]}, apply=True)
    assert result["version"]["version_number"] == 2 and result["version"]["row_count"] == 5
    current = rows(api, dataset["id"])
    assert current["total"] == 5
    assert current["rows"][0]["name"] == "Ann"
    old = rows(api, dataset["id"], version_id=original_version)
    assert old["total"] == 6, "the earlier version is unchanged"
    assert old["rows"][0]["name"] == " Ann "
    history = api.get(f"/api/datasets/{dataset['id']}/cleaning/history").json()
    assert len(history) == 1 and history[0]["operations"][0]["op"] == "remove_duplicates"
    assert api.post(f"/api/datasets/{dataset['id']}/versions/{original_version}/activate").status_code == 200
    assert rows(api, dataset["id"])["total"] == 6, "a version can be restored"


def test_save_cleaned_result_as_new_dataset(api: ApiClient):
    dataset = api.upload("q.csv", QUALITY_CSV)
    result = clean(api, dataset["id"], {"op": "drop_column", "column": "blank"}, apply=True, save_as="new_dataset", name="Clean copy")
    assert result["dataset"]["name"] == "Clean copy" and result["dataset"]["id"] != dataset["id"]
    assert result["dataset"]["column_count"] == 6
    source = api.get(f"/api/datasets/{dataset['id']}").json()
    assert source["column_count"] == 7 and len(source["versions"]) == 1


def test_every_cleaning_operation(api: ApiClient):
    csv_bytes = b"id,cat,val,other,text\n1,a,10,2,  hi  there \n2,A,,3,x\n3,b,30,0,y\n4,,40,5,z\n"
    dataset = api.upload("c.csv", csv_bytes)
    identifier = dataset["id"]

    def after(*operations):
        return pd.DataFrame(clean(api, identifier, *operations)["sample"])

    assert after({"op": "fill_missing", "column": "val", "strategy": "mean"})["val"].tolist() == pytest.approx([10, 80 / 3, 30, 40])
    assert after({"op": "fill_missing", "column": "val", "strategy": "median"})["val"].tolist()[1] == 30
    assert after({"op": "fill_missing", "column": "val", "strategy": "value", "value": 7})["val"].tolist()[1] == 7
    assert after({"op": "fill_missing", "column": "cat", "strategy": "value", "value": "none"})["cat"].tolist()[3] == "none"
    assert after({"op": "fill_missing", "column": "val", "strategy": "forward"})["val"].tolist()[1] == 10
    assert len(after({"op": "drop_missing", "columns": ["val"]})) == 3
    assert "value" in after({"op": "rename_column", "column": "val", "new_name": "value"}).columns
    assert after({"op": "change_type", "column": "val", "to": "text"})["val"].tolist()[0] == "10"
    assert after({"op": "trim_whitespace", "columns": ["text"]})["text"].tolist()[0] == "hi there"
    assert after({"op": "standardise_text", "column": "cat", "case": "upper"})["cat"].tolist()[:3] == ["A", "A", "B"]
    assert after({"op": "standardise_text", "column": "cat", "mapping": {"a": "Alpha", "A": "Alpha"}})["cat"].tolist()[:2] == ["Alpha", "Alpha"]
    assert after({"op": "filter_rows", "filters": [{"column": "val", "op": "gt", "value": 15}]})["id"].tolist() == [3, 4]
    assert after({"op": "filter_rows", "filters": [{"column": "val", "op": "gt", "value": 15}], "mode": "remove"})["id"].tolist() == [1, 2]
    assert "other" not in after({"op": "drop_column", "column": "other"}).columns
    derived = after({"op": "derive_column", "name": "ratio", "left": "val", "operator": "divide", "right_column": "other"})
    assert derived["ratio"].tolist()[0] == 5
    assert pd.isna(derived["ratio"].tolist()[2]), "division by zero is missing, not infinite"
    assert after({"op": "derive_column", "name": "double", "left": "val", "operator": "multiply", "right_value": 2})["double"].tolist()[0] == 20


def test_type_conversion_reports_failures(api: ApiClient):
    dataset = api.upload("t.csv", b'price\n"$1,200.50"\n45%\nabc\n7\n')
    preview = clean(api, dataset["id"], {"op": "change_type", "column": "price", "to": "float"})
    assert [r["price"] for r in preview["sample"]][:2] == [1200.5, 45]
    assert "1 values cannot be converted" in preview["effects"][0]["description"]
    applied = clean(api, dataset["id"], {"op": "change_type", "column": "price", "to": "float"}, apply=True)
    assert applied["version"]["version_number"] == 2
    assert {c["name"]: c["type"] for c in api.get(f"/api/datasets/{dataset['id']}").json()["columns"]}["price"] == "float"
    numeric = rows(api, dataset["id"], filters=[{"column": "price", "op": "gt", "value": 100}])
    assert numeric["total"] == 1


@pytest.mark.parametrize(
    "operation",
    [
        {"op": "fill_missing", "column": "cat", "strategy": "mean"},
        {"op": "fill_missing", "column": "val", "strategy": "value"},
        {"op": "fill_missing", "column": "val", "strategy": "value", "value": "abc"},
        {"op": "rename_column", "column": "val", "new_name": "cat"},
        {"op": "rename_column", "column": "val", "new_name": "__row_id"},
        {"op": "drop_column", "column": "nope"},
        {"op": "trim_whitespace", "columns": ["val"]},
        {"op": "derive_column", "name": "x", "left": "cat", "operator": "add", "right_value": 1},
        {"op": "derive_column", "name": "val", "left": "val", "operator": "add", "right_value": 1},
        {"op": "filter_rows", "filters": [{"column": "cat", "op": "gt", "value": "a"}]},
    ],
)
def test_invalid_cleaning_operations_rejected(api: ApiClient, operation):
    dataset = api.upload("c.csv", b"id,cat,val\n1,a,10\n2,b,\n")
    response = api.post(f"/api/datasets/{dataset['id']}/cleaning/preview", json={"operations": [operation]})
    assert response.status_code == 422, response.text


def test_cannot_remove_every_row(api: ApiClient):
    dataset = api.upload("c.csv", b"val\n1\n2\n")
    response = api.post(f"/api/datasets/{dataset['id']}/cleaning/apply", json={"operations": [{"op": "filter_rows", "filters": [{"column": "val", "op": "gt", "value": 100}]}]})
    assert response.status_code == 422
    assert "every row" in response.json()["detail"]
