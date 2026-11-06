"""Report assembly. Reports are built from engine calculations and stored as structured content."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..ai.analyst import analyse
from ..ai.executor import ExecutionResult, execute_plan
from ..ai.plan import AnalysisPlan
from .anomaly import DISCLAIMER, run_detection
from .charts import is_measure, primary_measure
from .frames import read_frame

REPORT_TYPES = {
    "dataset_overview": "Dataset Overview",
    "data_quality": "Data Quality Report",
    "sales_performance": "Sales Performance Report",
    "trend_analysis": "Trend Analysis",
    "anomaly_detection": "Anomaly Detection Report",
    "custom_ai": "Custom AI Analysis Report",
}
SALES_WORDS = ("revenue", "sales", "amount", "turnover")


class ReportError(ValueError):
    """The report cannot be produced from this dataset. The message explains why."""


def _table(title: str, columns: list[str], rows: list[dict]) -> dict:
    return {"title": title, "columns": columns, "rows": rows}


def _section(heading: str, *, text: str | None = None, findings: list[str] | None = None, table: dict | None = None, chart: dict | None = None) -> dict:
    return {"heading": heading, "text": text, "findings": findings or [], "table": table, "chart": _compact_chart(chart)}


def _compact_chart(chart: dict | None) -> dict | None:
    if not chart or not chart.get("rows"):
        return None
    return {k: chart.get(k) for k in ("chart_type", "title", "rows", "series", "x_label", "y_label", "x_type")}


def _from_result(heading: str, result: ExecutionResult) -> dict:
    table = _table(heading, result.table_columns, result.table_rows[:60]) if result.table_rows else None
    return _section(heading, text=result.interpretation, findings=result.key_findings[:6], table=table, chart=result.chart)


def _overview_table(profile: dict) -> dict:
    rows = []
    for c in profile["columns"]:
        rows.append({"column": c["name"], "type": c["type"], "missing": c["missing"], "missing_pct": c["missing_pct"], "unique": c["unique"],
                     "min": c.get("min", c.get("earliest", "")), "max": c.get("max", c.get("latest", "")), "mean": c.get("mean", "")})
    return _table("Column summary", ["column", "type", "missing", "missing_pct", "unique", "min", "max", "mean"], rows)


def _quality_recommendations(quality: dict) -> list[str]:
    actions = {
        "duplicates": "Review the {count:,} duplicate rows and remove them if they are not genuine repeats.",
        "missing_values": "Decide how to treat missing values in '{column}' ({count:,} cells).",
        "whitespace": "Trim whitespace in '{column}' ({count:,} values).",
        "inconsistent_categories": "Standardise the spelling and case of values in '{column}'.",
        "inconsistent_types": "Review the non-numeric values in '{column}' before converting it to a number.",
        "formatting": "Convert '{column}' to a numeric type so it can be aggregated.",
        "invalid_dates": "Correct or remove the invalid dates in '{column}'.",
        "empty_column": "Consider removing the empty column '{column}'.",
        "outliers": "Review extreme values in '{column}' ({count:,}) to confirm that they are valid.",
    }
    return [actions[i["check"]].format(column=i["column"], count=i["count"]) for i in quality.get("issues", [])[:8] if i["check"] in actions]


def _require_date(schema: list[dict], report: str) -> str:
    dates = [c["name"] for c in schema if c["type"] == "date"]
    if not dates:
        raise ReportError(f"A {report} needs a date column, and this dataset has none.")
    return dates[0]


def build_report(
    report_type: str,
    *,
    title: str | None,
    workspace_name: str,
    dataset_name: str,
    version_number: int,
    is_demo: bool,
    schema: list[dict],
    path: Path,
    profile: dict,
    quality: dict,
    questions: list[str] | None = None,
) -> dict:
    if report_type not in REPORT_TYPES:
        raise ReportError("Unknown report type.")
    label = REPORT_TYPES[report_type]
    run = lambda plan: execute_plan(plan, schema, path, profile, quality)  # noqa: E731
    measures = [c for c in schema if is_measure(c)]
    categories = [c["name"] for c in schema if c["type"] == "category"]
    sections: list[dict] = []
    summary: list[str] = []
    methodology: list[str] = [f"All figures are calculated by the DuckDB and pandas engine from version {version_number} of '{dataset_name}'."]
    recommendations: list[str] = []
    limitations: list[str] = ["Findings describe recorded data. They do not establish causes, and they depend on the completeness and accuracy of the source data."]
    ai_info: dict | None = None
    summary_rows = f"The dataset contains {profile['row_count']:,} rows and {profile['column_count']} columns."

    if report_type == "dataset_overview":
        result = run(AnalysisPlan(operation="dataset_summary"))
        summary = [summary_rows, *result.key_findings[1:4]]
        sections.append(_section("Column summary", table=_overview_table(profile)))
        sections.append(_from_result("Main patterns", result))
        for column in categories[:2]:
            primary = primary_measure(measures)
            group = run(AnalysisPlan(operation="group_aggregate", group_by=column, metric_column=primary["name"] if primary else None, aggregation="sum" if primary else "count", limit=10))
            if group.table_rows:
                sections.append(_from_result(f"Breakdown by {column}", group))
        recommendations = _quality_recommendations(quality)
        methodology.append("Column statistics come from the stored data profile. Quartiles use linear interpolation, and standard deviation is the sample value.")
    elif report_type == "data_quality":
        issues = quality.get("issues", [])
        summary = [summary_rows, f"The data quality score is {quality.get('score')}/100, with {len(issues)} issue(s) found.",
                   f"{profile['missing_pct']}% of cells are missing and {profile['duplicate_rows']:,} rows are exact duplicates."]
        sections.append(_section("Issues found", table=_table("Data quality issues", ["severity", "title", "column", "count", "detail"],
                                 [{k: i.get(k) for k in ("severity", "title", "column", "count", "detail")} for i in issues])))
        sections.append(_section("Column completeness", table=_overview_table(profile)))
        recommendations = _quality_recommendations(quality)
        methodology.append("Checks cover missing values, duplicates, inconsistent types, invalid dates, potential outliers, empty columns, inconsistent categories, and formatting.")
        methodology.append("The score starts at 100 and subtracts 15, 5, or 1 per critical, warning, or informational issue. It is a triage aid, not a formal standard.")
    elif report_type == "sales_performance":
        date_column = _require_date(schema, label)
        sales = [c for c in measures if any(w in c["name"].lower() for w in SALES_WORDS)]
        if not sales:
            raise ReportError(f"A {label} needs a revenue or sales column. Numeric columns found: {', '.join(c['name'] for c in measures) or 'none'}.")
        metric = sales[0]["name"]
        trend = run(AnalysisPlan(operation="time_series", metric_column=metric, time_column=date_column, aggregation="sum", time_grain="month"))
        total = run(AnalysisPlan(operation="metric", metric_column=metric, aggregation="sum"))
        average = run(AnalysisPlan(operation="metric", metric_column=metric, aggregation="avg"))
        summary = [total.direct_answer, average.direct_answer, *trend.key_findings[:3]]
        sections.append(_from_result(f"Monthly {metric}", trend))
        limitations.extend(trend.limitations)
        for column in categories[:3]:
            group = run(AnalysisPlan(operation="group_aggregate", metric_column=metric, group_by=column, aggregation="sum", limit=10))
            if group.table_rows:
                sections.append(_from_result(f"{metric} by {column}", group))
                limitations.extend(item for item in group.limitations if item not in limitations)
        recommendations = _quality_recommendations(quality)[:3]
        if trend.key_findings:
            recommendations.insert(0, "Investigate what drove the highest and lowest months identified above.")
        methodology.append(f"Sales are the sum of '{metric}', grouped by calendar month of '{date_column}' and by category.")
    elif report_type == "trend_analysis":
        date_column = _require_date(schema, label)
        if not measures:
            raise ReportError(f"A {label} needs at least one numeric column.")
        span = next(c for c in profile["columns"] if c["name"] == date_column).get("range_days", 0)
        grain = "day" if span <= 62 else "week" if span <= 180 else "month"
        for column in measures[:4]:
            aggregation = "avg" if any(w in column["name"].lower() for w in ("price", "rate", "pct", "percent", "score", "ratio")) else "sum"
            trend = run(AnalysisPlan(operation="time_series", metric_column=column["name"], time_column=date_column, aggregation=aggregation, time_grain=grain))
            sections.append(_from_result(f"Trend in {column['name']}", trend))
            summary.extend(trend.key_findings[2:3] or trend.key_findings[:1])
            limitations.extend(item for item in trend.limitations if item not in limitations)
        recommendations = ["Compare any large change with known events such as campaigns, outages, or pricing changes.", *_quality_recommendations(quality)[:2]]
        methodology.append(f"Values are aggregated per {grain} of '{date_column}'. Change is relative to the preceding period.")
    elif report_type == "anomaly_detection":
        frame = read_frame(path, keep_row_id=True)
        detected = run_detection(frame, schema)
        findings = sorted(detected["findings"], key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f["severity"]], -f["score"]))
        counts = detected["summary"]["by_severity"]
        summary = [f"{len(findings):,} statistical anomalies were flagged: {counts['high']} high, {counts['medium']} medium, and {counts['low']} low severity.", DISCLAIMER]
        sections.append(_section("Methods applied", table=_table("Methods applied", ["column", "method", "flagged", "reason"],
                                 [{k: m.get(k) for k in ("column", "method", "flagged", "reason")} for m in detected["summary"]["methods"]])))
        sections.append(_section("Most significant anomalies", table=_table("Anomalies", ["where", "column", "observed", "severity", "score", "method", "explanation"],
                                 [{"where": f["period"] or (f"row {f['row_id']}" if f["row_id"] else "category"), "column": f["column_name"], "observed": f["observed"], "severity": f["severity"], "score": f["score"], "method": f["method"], "explanation": f["explanation"]} for f in findings[:40]])))
        for series in list(detected["summary"]["series"].values())[:2]:
            sections.append(_section(series["label"], chart={"chart_type": "line", "title": series["label"], "rows": [{"x": p["period"], series["label"]: p["value"]} for p in series["points"]], "series": [series["label"]], "x_label": "Period", "y_label": series["label"], "x_type": "date"}))
        recommendations = ["Review the high-severity items first and confirm each against source records.", "Mark items as expected or resolved in Anomaly Detection to keep a record of the review."]
        methodology.append("Each column uses a method suited to its type and shape: modified Z-score or IQR for numbers, rolling-median baselines for time periods, and share analysis for categories.")
        limitations.extend(detected["summary"]["skipped"][:5])
        limitations.append(DISCLAIMER)
    elif report_type == "custom_ai":
        prompts = [q.strip() for q in (questions or []) if q.strip()]
        if not prompts:
            raise ReportError("Enter at least one question for a custom analysis report.")
        for question in prompts[:5]:
            answer = analyse(question, dataset_name=dataset_name, version_number=version_number, schema=schema, path=path, profile=profile, quality=quality)
            summary.append(f"{question} {answer['direct_answer']}")
            rows = answer["supporting_data"]["rows"]
            sections.append(_section(question, text=answer["interpretation"], findings=[answer["direct_answer"], *answer["key_findings"][:4]],
                                     table=_table(question, answer["supporting_data"]["columns"], rows[:60]) if rows else None, chart=answer["chart"]))
            limitations.extend(item for item in answer["limitations"] if item not in limitations)
            ai_info = {"mode": answer["mode"], "provider": answer["provider"], "model": answer["model"]}
        if ai_info and ai_info["mode"] == "demonstration":
            methodology.append("Questions were interpreted by the rule-based demonstration planner, not an AI model. Calculations are genuine.")
        elif ai_info:
            methodology.append(f"Questions were planned and explained by {ai_info['provider']} ({ai_info['model']}). All figures were calculated by the data engine.")
        recommendations = ["Check these answers against the supporting tables before acting on them."]

    if is_demo:
        limitations.insert(0, "This report uses a synthetic demonstration dataset. It does not describe a real business.")
    return {
        "title": title or f"{label}: {dataset_name}",
        "report_type": report_type,
        "report_type_label": label,
        "workspace": workspace_name,
        "dataset": dataset_name,
        "version": version_number,
        "is_demo": is_demo,
        "ai": ai_info,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "executive_summary": summary,
        "overview": {
            "rows": profile["row_count"],
            "columns": profile["column_count"],
            "missing_pct": profile["missing_pct"],
            "duplicate_rows": profile["duplicate_rows"],
            "quality_score": quality.get("score"),
        },
        "methodology": methodology,
        "sections": sections,
        "recommendations": recommendations,
        "limitations": list(dict.fromkeys(limitations)),
    }


def report_tables(content: dict) -> list[dict]:
    tables = [{"title": "Overview", "columns": ["metric", "value"], "rows": [{"metric": k, "value": v} for k, v in content["overview"].items()]}]
    tables.extend(s["table"] for s in content["sections"] if s.get("table"))
    return tables
