"""Chart calculations and the grounded analyst, checked against independent pandas calculations."""
from __future__ import annotations

import json

import httpx
import httpx2
import pandas as pd
import pytest

from app.ai.analyst import analyse, check_grounding
from app.ai.plan import AnalysisPlan, PlanError, validate_plan
from app.ai.providers import AnthropicProvider, GeminiProvider, OpenAIProvider, ProviderError, ProviderResult, ai_status
from app.services import storage
from tests.conftest import ApiClient, retail_path


@pytest.fixture(scope="module")
def source() -> pd.DataFrame:
    return pd.read_csv(retail_path(), parse_dates=["order_date"])


def chart(api: ApiClient, dataset_id: str, **spec) -> dict:
    response = api.post("/api/charts/run", json={"dataset_id": dataset_id, "spec": spec})
    assert response.status_code == 200, response.text
    return response.json()


def test_bar_chart_values_match_pandas(retail_client, source):
    api, dataset = retail_client
    result = chart(api, dataset["id"], chart_type="bar", x="region", y="revenue", aggregation="sum")
    expected = source.groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert [r["x"] for r in result["rows"]] == expected.index.tolist()
    assert [r["Total revenue"] for r in result["rows"]] == pytest.approx(expected.tolist())
    assert result["rows_matched"] == len(source)


@pytest.mark.parametrize("aggregation", ["avg", "min", "max", "median"])
def test_aggregations_match_pandas(retail_client, source, aggregation):
    api, dataset = retail_client
    result = chart(api, dataset["id"], chart_type="bar", x="category", y="revenue", aggregation=aggregation, sort="x")
    method = {"avg": "mean"}.get(aggregation, aggregation)
    expected = source.groupby("category")["revenue"].agg(method)
    series = result["series"][0]
    for row in result["rows"]:
        assert row[series] == pytest.approx(expected[row["x"]])


def test_count_chart(retail_client, source):
    api, dataset = retail_client
    result = chart(api, dataset["id"], chart_type="bar", x="category", aggregation="count")
    expected = source["category"].value_counts()
    for row in result["rows"]:
        assert row["Row count"] == expected[row["x"]]


def test_line_chart_groups_by_month(retail_client, source):
    api, dataset = retail_client
    result = chart(api, dataset["id"], chart_type="line", x="order_date", y="revenue", aggregation="sum", time_grain="month", limit=500)
    expected = source.groupby(source["order_date"].dt.to_period("M"))["revenue"].sum()
    assert len(result["rows"]) == len(expected)
    assert result["time_grain"] == "month"
    assert result["rows"][0]["Total revenue"] == pytest.approx(expected.iloc[0])
    assert result["rows"][-1]["Total revenue"] == pytest.approx(expected.iloc[-1])
    assert result["rows"] == sorted(result["rows"], key=lambda r: r["x"])


def test_grouped_chart_and_filter_update(retail_client, source):
    api, dataset = retail_client
    grouped = chart(api, dataset["id"], chart_type="bar", x="region", y="revenue", group="category")
    assert set(grouped["series"]) == set(source["category"].unique())
    row = next(r for r in grouped["rows"] if r["x"] == "Europe")
    expected = source[(source["region"] == "Europe") & (source["category"] == "Home")]["revenue"].sum()
    assert row["Home"] == pytest.approx(expected)
    filtered = chart(api, dataset["id"], chart_type="bar", x="region", y="revenue", filters=[{"column": "category", "op": "eq", "value": "Home"}])
    assert filtered["rows_matched"] == int((source["category"] == "Home").sum())
    assert next(r for r in filtered["rows"] if r["x"] == "Europe")["Total revenue"] == pytest.approx(expected)
    assert filtered["filters"] == ["category = Home"]


def test_chart_changes_with_configuration(retail_client):
    api, dataset = retail_client
    first = chart(api, dataset["id"], chart_type="bar", x="region", y="revenue")
    second = chart(api, dataset["id"], chart_type="bar", x="region", y="cost")
    assert first["rows"] != second["rows"]


def test_pie_combines_other_correctly(retail_client, source):
    api, dataset = retail_client
    result = chart(api, dataset["id"], chart_type="donut", x="country", y="revenue")
    total = sum(r[result["series"][0]] for r in result["rows"])
    assert total == pytest.approx(source["revenue"].sum())


def test_scatter_histogram_box(retail_client, source):
    api, dataset = retail_client
    scatter = chart(api, dataset["id"], chart_type="scatter", x="quantity", y="revenue")
    assert 1 < len(scatter["rows"]) <= 2000
    assert any("sample" in n for n in scatter["notes"])
    histogram = chart(api, dataset["id"], chart_type="histogram", x="revenue", bins=10)
    assert len(histogram["rows"]) == 10
    assert sum(r["Count"] for r in histogram["rows"]) == len(source)
    box = chart(api, dataset["id"], chart_type="box", x="category", y="revenue")
    home = next(r for r in box["rows"] if r["x"] == "Home")
    values = source[source["category"] == "Home"]["revenue"]
    assert home["median"] == pytest.approx(values.median())
    assert home["q1"] == pytest.approx(values.quantile(0.25))
    assert home["max"] == pytest.approx(values.max())
    assert home["count"] == len(values)


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ({"chart_type": "bar"}, "X axis"),
        ({"chart_type": "bar", "x": "region", "aggregation": "sum"}, "numeric field"),
        ({"chart_type": "bar", "x": "region", "y": "product", "aggregation": "avg"}, "needs a numeric field"),
        ({"chart_type": "line", "x": "region", "y": "revenue"}, "Use a bar chart"),
        ({"chart_type": "pie", "x": "region", "y": "revenue", "aggregation": "avg"}, "only Sum and Count"),
        ({"chart_type": "pie", "x": "revenue", "aggregation": "count"}, "categorical"),
        ({"chart_type": "pie", "x": "region", "y": "revenue", "group": "category"}, "do not support grouping"),
        ({"chart_type": "scatter", "x": "region", "y": "revenue"}, "numeric fields"),
        ({"chart_type": "histogram", "x": "region"}, "numeric"),
        ({"chart_type": "box", "y": "region"}, "numeric"),
        ({"chart_type": "bar", "x": "ghost", "y": "revenue"}, "does not exist"),
    ],
)
def test_incompatible_charts_are_rejected(retail_client, spec, fragment):
    api, dataset = retail_client
    response = api.post("/api/charts/run", json={"dataset_id": dataset["id"], "spec": spec})
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


def test_saved_visualisation_lifecycle(retail_client):
    api, dataset = retail_client
    spec = {"chart_type": "bar", "x": "region", "y": "revenue"}
    saved = api.post("/api/visualisations", json={"dataset_id": dataset["id"], "name": "Regions", "spec": spec})
    assert saved.status_code == 201
    identifier = saved.json()["id"]
    data = api.get(f"/api/visualisations/{identifier}/data").json()
    assert data["chart"]["rows"]
    updated = api.put(f"/api/visualisations/{identifier}", json={"dataset_id": dataset["id"], "name": "Renamed", "spec": {**spec, "aggregation": "avg"}})
    assert updated.json()["name"] == "Renamed"
    assert api.delete(f"/api/visualisations/{identifier}").status_code == 200
    assert api.get(f"/api/visualisations/{identifier}/data").status_code == 404


def test_recommendations_only_use_real_columns(retail_client):
    api, dataset = retail_client
    result = api.get("/api/charts/recommendations", params={"dataset_id": dataset["id"]}).json()
    assert result["source"] == "rules"
    names = {c["name"] for c in dataset["columns"]}
    assert result["suggestions"]
    for suggestion in result["suggestions"]:
        for key in ("x", "y"):
            if key in suggestion["spec"]:
                assert suggestion["spec"][key] in names
        assert api.post("/api/charts/run", json={"dataset_id": dataset["id"], "spec": suggestion["spec"]}).status_code == 200


def ask(api: ApiClient, dataset_id: str, question: str, conversation_id: str | None = None) -> dict:
    body = {"dataset_id": dataset_id, "question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = api.post("/api/analyst/ask", json=body)
    assert response.status_code == 200, response.text
    return response.json()["message"]["response"]


def test_highest_month_is_correct(retail_client, source):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "Which month had the highest revenue?")
    monthly = source.groupby(source["order_date"].dt.strftime("%Y-%m"))["revenue"].sum()
    assert answer["status"] == "answered"
    assert answer["plan"]["operation"] == "time_series"
    assert monthly.idxmax() in answer["direct_answer"]
    assert f"{monthly.max():,.2f}" in answer["direct_answer"]
    rows = {r["period"]: r["total revenue"] for r in answer["supporting_data"]["rows"]}
    assert rows[monthly.idxmax()] == pytest.approx(monthly.max())


def test_top_five_products(retail_client, source):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "What were the five best-performing products by revenue?")
    expected = source.groupby("product")["revenue"].sum().nlargest(5)
    rows = answer["supporting_data"]["rows"]
    assert len(rows) == 5
    assert [r["product"] for r in rows] == expected.index.tolist()
    assert [r["total revenue"] for r in rows] == pytest.approx(expected.tolist())
    assert answer["provenance"]["columns"] == ["product", "revenue"]
    assert answer["chart"]["rows"]


def test_worst_products(retail_client, source):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "Which products performed the worst?")
    worst = source.groupby("product")["revenue"].sum().idxmin()
    assert answer["supporting_data"]["rows"][0]["product"] == worst
    assert answer["plan"]["order"] == "asc"


def test_average_order_value_states_its_assumption(retail_client, source):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "What is the average order value?")
    assert f"{source['revenue'].mean():,.2f}" in answer["direct_answer"]
    assert any("revenue" in a for a in answer["assumptions"])


def test_region_revenue_and_lowest_average(retail_client, source):
    api, dataset = retail_client
    top = ask(api, dataset["id"], "Which regions generate the most revenue?")
    expected = source.groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert top["supporting_data"]["rows"][0]["region"] == expected.index[0]
    low = ask(api, dataset["id"], "Which regions have the lowest average order value?")
    means = source.groupby("region")["revenue"].mean()
    assert low["plan"]["aggregation"] == "avg"
    assert low["supporting_data"]["rows"][0]["region"] == means.idxmin()
    assert low["supporting_data"]["rows"][0]["average revenue"] == pytest.approx(means.min())


def test_year_comparison(retail_client, source):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "Compare monthly revenue across the last two years.")
    assert answer["plan"]["operation"] == "period_comparison"
    yearly = source.groupby(source["order_date"].dt.year)["revenue"].sum()
    assert f"{yearly[2024]:,.2f}" in answer["direct_answer"]
    assert f"{yearly[2023]:,.2f}" in answer["direct_answer"]
    january = next(r for r in answer["supporting_data"]["rows"] if r["period"] == "M01")
    assert january["2024"] == pytest.approx(source[(source["order_date"].dt.year == 2024) & (source["order_date"].dt.month == 1)]["revenue"].sum())


def test_summary_anomaly_and_filter_questions(retail_client, source):
    api, dataset = retail_client
    summary = ask(api, dataset["id"], "Explain the most important trends in this dataset.")
    assert summary["plan"]["operation"] == "dataset_summary"
    assert f"{len(source):,}" in summary["direct_answer"]
    anomalies = ask(api, dataset["id"], "Are there unusual changes in revenue?")
    assert anomalies["plan"]["operation"] == "anomaly_scan"
    assert "not automatically errors" in anomalies["interpretation"]
    europe = ask(api, dataset["id"], "What is the total revenue in Europe?")
    assert f"{source[source['region'] == 'Europe']['revenue'].sum():,.2f}" in europe["direct_answer"]
    assert europe["provenance"]["filters"] == ["region = Europe"]
    year = ask(api, dataset["id"], "What was the total revenue in 2023?")
    assert f"{source[source['order_date'].dt.year == 2023]['revenue'].sum():,.2f}" in year["direct_answer"]


def test_response_structure_and_labels(retail_client):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], "total revenue by region")
    for key in ("direct_answer", "supporting_data", "key_findings", "interpretation", "follow_ups", "limitations", "provenance"):
        assert key in answer
    assert answer["mode"] == "demonstration" and answer["provider"] is None
    assert answer["provenance"]["calculation"]
    assert answer["data_shared_with_ai"] is None


@pytest.mark.parametrize(
    "question",
    [
        "What will revenue be next year?",
        "Predict next month's sales",
        "Why did revenue fall?",
        "What is the capital of France?",
        "Tell me a joke",
    ],
)
def test_unsupported_questions_are_handled_honestly(retail_client, question):
    api, dataset = retail_client
    answer = ask(api, dataset["id"], question)
    assert answer["status"] == "unsupported"
    assert answer["supporting_data"]["rows"] == []
    assert "can't answer" in answer["direct_answer"]


def test_question_about_a_dataset_without_required_columns(api: ApiClient):
    dataset = api.upload("t.csv", b"name,colour\nA,red\nB,blue\n")
    answer = ask(api, dataset["id"], "What is the total revenue?")
    assert answer["status"] == "unsupported"
    trend = ask(api, dataset["id"], "Compare revenue across the last two years")
    assert trend["status"] == "unsupported"


def test_conversation_history(retail_client):
    api, dataset = retail_client
    first = api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue"}).json()
    conversation = first["conversation_id"]
    api.post("/api/analyst/ask", json={"dataset_id": dataset["id"], "question": "total revenue by region", "conversation_id": conversation})
    stored = api.get(f"/api/analyst/conversations/{conversation}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant", "user", "assistant"]
    assert stored["messages"][3]["response"]["supporting_data"]["rows"]
    assert conversation in {c["id"] for c in api.get("/api/analyst/conversations").json()}
    assert api.delete(f"/api/analyst/conversations/{conversation}").status_code == 200
    assert api.get(f"/api/analyst/conversations/{conversation}").status_code == 404


def test_plan_validation_rejects_unknown_and_unsuitable_columns():
    schema = [{"name": "a", "type": "float"}, {"name": "b", "type": "category"}]
    for plan in (
        AnalysisPlan(operation="metric", metric_column="ghost"),
        AnalysisPlan(operation="metric", metric_column="b", aggregation="sum"),
        AnalysisPlan(operation="group_aggregate", metric_column="a"),
        AnalysisPlan(operation="time_series", metric_column="a", time_column="b"),
    ):
        with pytest.raises(PlanError):
            validate_plan(plan, schema)


class ScriptedProvider:
    """A stand-in AI provider that returns fixed output and records what it was sent."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, plan: dict | None, narrative: dict | None = None, error: bool = False):
        self.plan, self.narrative, self.error = plan, narrative, error
        self.sent: list[str] = []

    def complete_json(self, system, user, schema):
        self.sent.append(user)
        if self.error:
            raise ProviderError("service down")
        return ProviderResult(self.plan if "result_rows" not in user else self.narrative, {"input_tokens": 10, "output_tokens": 5})


def _inputs(retail_client):
    api, dataset = retail_client
    profile = api.get(f"/api/datasets/{dataset['id']}/profile").json()
    from app.db import session_scope
    from app.models import DatasetVersion

    with session_scope() as db:
        version = db.get(DatasetVersion, dataset["current_version_id"])
        path = storage.resolve_ref(version.storage_ref)
    return {"dataset_name": dataset["name"], "version_number": 1, "schema": profile["columns"], "path": path, "profile": profile["profile"], "quality": profile["quality"]}


GOOD_PLAN = {"operation": "group_aggregate", "metric_column": "revenue", "group_by": "region", "aggregation": "sum", "order": "desc", "limit": 3}


def test_live_ai_results_come_from_the_engine(retail_client, source):
    inputs = _inputs(retail_client)
    top = source.groupby("region")["revenue"].sum().sort_values(ascending=False)
    narrative = {"direct_answer": f"{top.index[0]} leads with {top.iloc[0]:,.2f}.", "key_findings": [], "interpretation": "Focus here.", "follow_ups": ["More?"], "limitations": []}
    provider = ScriptedProvider(GOOD_PLAN, narrative)
    answer = analyse("revenue by region", provider=provider, **inputs)
    assert answer["mode"] == "live" and answer["narrated_by"] == "ai"
    assert answer["provider"] == "scripted"
    assert answer["supporting_data"]["rows"][0]["total revenue"] == pytest.approx(top.iloc[0])
    assert answer["data_shared_with_ai"]["raw_rows"] is False
    assert answer["usage"] == {"input_tokens": 20, "output_tokens": 10}


def test_fabricated_ai_numbers_are_rejected(retail_client):
    inputs = _inputs(retail_client)
    narrative = {"direct_answer": "Revenue reached 987,654.32 last year.", "key_findings": [], "interpretation": "", "follow_ups": [], "limitations": []}
    answer = analyse("revenue by region", provider=ScriptedProvider(GOOD_PLAN, narrative), **inputs)
    assert answer["narrated_by"] == "engine"
    assert "987,654.32" not in answer["direct_answer"]
    assert "987,654.32" in answer["grounding"]["ai_figures_rejected"]
    assert any("do not match" in n for n in answer["notices"])


def test_grounding_check_allows_engine_numbers():
    evidence = [[{"total": 1234.5, "share": 12.34}], "Rows used: 5,000"]
    assert check_grounding({"direct_answer": "It was 1,234.50 (12.34%) from 5,000 rows, the top 3.", "key_findings": [], "interpretation": "", "limitations": []}, evidence) == []
    assert check_grounding({"direct_answer": "It was 9,999.", "key_findings": [], "interpretation": "", "limitations": []}, evidence) == ["9,999"]


def test_ai_plan_with_invented_column_is_unsupported(retail_client):
    inputs = _inputs(retail_client)
    answer = analyse("profit?", provider=ScriptedProvider({"operation": "metric", "metric_column": "made_up_profit", "aggregation": "sum"}), **inputs)
    assert answer["status"] == "unsupported"
    assert "does not exist" in " ".join(answer["key_findings"])


def test_ai_plan_cannot_inject_sql(retail_client):
    inputs = _inputs(retail_client)
    plan = {"operation": "metric", "metric_column": 'revenue") FROM data; DROP TABLE data; --', "aggregation": "sum"}
    answer = analyse("x", provider=ScriptedProvider(plan), **inputs)
    assert answer["status"] == "unsupported"


def test_provider_failure_falls_back_with_clear_label(retail_client, source):
    inputs = _inputs(retail_client)
    answer = analyse("total revenue", provider=ScriptedProvider(None, error=True), **inputs)
    assert answer["mode"] == "demonstration"
    assert any("Live AI was unavailable" in n for n in answer["notices"])
    assert f"{source['revenue'].sum():,.2f}" in answer["direct_answer"]


def test_only_schema_and_aggregates_reach_the_provider(retail_client, source):
    inputs = _inputs(retail_client)
    narrative = {"direct_answer": "See the table.", "key_findings": [], "interpretation": "", "follow_ups": [], "limitations": []}
    provider = ScriptedProvider(GOOD_PLAN, narrative)
    analyse("revenue by region", provider=provider, **inputs)
    sent = " ".join(provider.sent)
    assert "ORD-1" not in sent, "row-level identifiers are never sent"
    assert str(source["order_id"].iloc[0]) not in sent
    plan_message = json.loads(provider.sent[0])
    assert set(plan_message) == {"dataset", "row_count", "columns", "recent_conversation", "question"}
    answer_message = json.loads(provider.sent[1])
    assert len(answer_message["result_rows"]) <= 40


def test_category_values_can_be_withheld(retail_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ai_share_category_values", False)
    inputs = _inputs(retail_client)
    provider = ScriptedProvider({"operation": "unsupported", "reason": "x"})
    analyse("anything", provider=provider, **inputs)
    assert "Europe" not in provider.sent[0]


def _transport(status: int, body: dict, seen: list, module=httpx):
    def handler(request):
        seen.append(request)
        return module.Response(status, json=body)

    return module.Client(transport=module.MockTransport(handler))


SCHEMA = {"type": "object"}


def test_anthropic_provider_request_and_response():
    seen: list[httpx.Request] = []
    body = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": '{"ok": 1}'}], "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 4}}
    provider = AnthropicProvider("sk-test", "claude-opus-5-5", 5, http_client=_transport(200, body, seen, httpx2))
    result = provider.complete_json("sys", "user", SCHEMA)
    assert result.data == {"ok": 1}
    assert result.usage == {"input_tokens": 3, "output_tokens": 4}
    sent = json.loads(seen[0].content)
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert sent["fallbacks"] == "default"
    assert "temperature" not in sent and "budget_tokens" not in str(sent)


def test_anthropic_provider_handles_refusal_and_errors():
    refusal = {"id": "m", "type": "message", "role": "assistant", "model": "x", "content": [], "stop_reason": "refusal", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}}
    with pytest.raises(ProviderError, match="declined"):
        AnthropicProvider("k", "m", 5, http_client=_transport(200, refusal, [], httpx2)).complete_json("s", "u", SCHEMA)
    with pytest.raises(ProviderError) as caught:
        AnthropicProvider("sk-secret-key", "m", 5, http_client=_transport(401, {"type": "error", "error": {"type": "authentication_error", "message": "bad"}}, [], httpx2)).complete_json("s", "u", SCHEMA)
    assert "sk-secret-key" not in str(caught.value)


def test_openai_provider():
    seen: list[httpx.Request] = []
    body = {"choices": [{"message": {"content": '{"ok": 2}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}
    result = OpenAIProvider("key", "some-model", 5, http_client=_transport(200, body, seen)).complete_json("s", "u", SCHEMA)
    assert result.data == {"ok": 2}
    assert seen[0].headers["authorization"] == "Bearer key"
    with pytest.raises(ProviderError, match="status 500"):
        OpenAIProvider("key", "m", 5, http_client=_transport(500, {}, [])).complete_json("s", "u", SCHEMA)


def test_gemini_provider_keeps_key_out_of_the_url():
    seen: list[httpx.Request] = []
    body = {"candidates": [{"content": {"parts": [{"text": '{"ok": 3}'}]}}], "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2}}
    schema = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": ["string", "null"]}}}
    result = GeminiProvider("gem-key", "gem-model", 5, http_client=_transport(200, body, seen)).complete_json("s", "u", schema)
    assert result.data == {"ok": 3}
    assert "gem-key" not in str(seen[0].url)
    converted = json.loads(seen[0].content)["generationConfig"]["responseSchema"]
    assert "additionalProperties" not in converted
    assert converted["properties"]["a"] == {"type": "string", "nullable": True}


def test_status_endpoint_never_exposes_keys(api: ApiClient, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-super-secret")
    status = api.get("/api/analyst/status")
    assert status.json()["mode"] == "live" and status.json()["provider"] == "anthropic"
    assert "sk-ant-super-secret" not in status.text
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert ai_status()["mode"] == "demonstration"
    assert "not set" in ai_status()["problem"]
