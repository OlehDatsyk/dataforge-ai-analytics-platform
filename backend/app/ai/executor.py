"""Runs a validated plan on the data engine and writes a plain-language summary of the exact results."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..services.anomaly import DISCLAIMER, run_detection
from ..services.charts import ChartSpec, is_measure, primary_measure, recommend_charts, run_chart
from ..services.frames import NUMERIC_TYPES, json_safe, read_frame
from ..services.query_engine import build_where, connect, describe_filters, quote, run_query
from .plan import AnalysisPlan

AGG_SQL = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "median": "MEDIAN"}
AGG_WORD = {"sum": "total", "avg": "average", "count": "count", "min": "minimum", "max": "maximum", "median": "median"}
PERIOD_FORMAT = {"day": "%Y-%m-%d", "week": "%Y-%m-%d", "month": "%Y-%m", "quarter": "%Y-%m", "year": "%Y"}


def fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.4g}" if abs(value) < 1 else f"{value:,.2f}"
    return str(value)


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


@dataclass
class ExecutionResult:
    direct_answer: str
    key_findings: list[str] = field(default_factory=list)
    interpretation: str = ""
    follow_ups: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    table_columns: list[str] = field(default_factory=list)
    table_rows: list[dict] = field(default_factory=list)
    chart: dict | None = None
    columns_used: list[str] = field(default_factory=list)
    calculation: str = ""
    time_range: str | None = None
    rows_used: int = 0
    answered: bool = True


def _metric_sql(plan: AnalysisPlan) -> str:
    if plan.aggregation == "count":
        return f"COUNT({quote(plan.metric_column)})" if plan.metric_column else "COUNT(*)"
    return f"{AGG_SQL[plan.aggregation]}({quote(plan.metric_column)})"


def _metric_label(plan: AnalysisPlan) -> str:
    if plan.aggregation == "count":
        return f"count of {plan.metric_column}" if plan.metric_column else "record count"
    return f"{AGG_WORD[plan.aggregation]} {plan.metric_column}"


def _filter_text(plan: AnalysisPlan) -> str:
    text = describe_filters(plan.filters)
    return f" (filtered to {'; '.join(text)})" if text else ""


def _chart(spec: dict, schema: list[dict], path: Path) -> dict | None:
    """Attach a chart produced by the same engine. A failed chart never hides the numeric answer."""
    try:
        return run_chart(ChartSpec(**spec), schema, path) | {"spec": spec}
    except Exception:
        return None


def _time_range(con, column: str, where: str, params: list) -> str | None:
    _, rows = run_query(con, f"SELECT MIN({quote(column)}), MAX({quote(column)}) FROM data{where}", params)
    low, high = rows[0]
    return None if low is None else f"{low.date().isoformat()} to {high.date().isoformat()}"


def _run_metric(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    where, params = build_where(plan.filters, schema)
    with connect(path) as con:
        _, rows = run_query(con, f"SELECT {_metric_sql(plan)}, COUNT(*) FROM data{where}", params)
    value, used = json_safe(rows[0][0]), int(rows[0][1])
    label = _metric_label(plan)
    if value is None:
        return ExecutionResult(f"No {label} could be calculated: no values matched{_filter_text(plan)}.", answered=True, rows_used=used,
                               calculation=f"{plan.aggregation} over the matching rows", columns_used=[c for c in [plan.metric_column] if c])
    return ExecutionResult(
        f"The {label} is {fmt(value)}{_filter_text(plan)}.",
        key_findings=[f"Calculated from {used:,} rows."],
        interpretation="This is a single figure across all matching rows. Splitting it by a category or period can show what drives it.",
        follow_ups=[f"Show the {label} by month", f"Show the {label} by category"],
        table_columns=["metric", "value", "rows_used"],
        table_rows=[{"metric": label, "value": value, "rows_used": used}],
        columns_used=[c for c in [plan.metric_column] if c],
        calculation=f"{plan.aggregation.upper()} of {plan.metric_column or 'rows'} over {used:,} rows",
        rows_used=used,
    )


def _run_group(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    where, params = build_where(plan.filters, schema)
    group = quote(plan.group_by)
    non_null = f"{where} AND {group} IS NOT NULL" if where else f" WHERE {group} IS NOT NULL"
    metric = _metric_sql(plan)
    with connect(path) as con:
        _, totals = run_query(con, f"SELECT {metric}, COUNT(*), COUNT(DISTINCT {group}) FROM data{non_null}", params)
        _, rows = run_query(
            con,
            f"SELECT {group}, {metric} AS v, COUNT(*) FROM data{non_null} GROUP BY 1 ORDER BY v {plan.order.upper()} NULLS LAST, 1 LIMIT ?",
            params + [plan.limit],
        )
    total, used, groups = json_safe(totals[0][0]), int(totals[0][1]), int(totals[0][2])
    label = _metric_label(plan)
    additive = plan.aggregation in {"sum", "count"} and total
    table = []
    for rank, (name, value, count) in enumerate(rows, start=1):
        record = {"rank": rank, plan.group_by: json_safe(name), label: json_safe(value), "rows": int(count)}
        if additive:
            record["share_pct"] = round(float(value) / float(total) * 100, 2) if value is not None else None
        table.append(record)
    if not table:
        return ExecutionResult(f"No rows matched{_filter_text(plan)}, so there is nothing to rank.", rows_used=0)
    word = "highest" if plan.order == "desc" else "lowest"
    first = table[0]
    findings = [f"{r[plan.group_by]}: {fmt(r[label])}" + (f" ({r['share_pct']:.1f}% of total)" if additive and r.get("share_pct") is not None else "") for r in table[:5]]
    answer = f"{first[plan.group_by]} has the {word} {label}, at {fmt(first[label])}{_filter_text(plan)}."
    if len(table) > 1:
        names = ", ".join(str(r[plan.group_by]) for r in table[: min(5, len(table))])
        answer = f"Ranked by {word} {label}: {names}. {answer}"
    interpretation = f"This compares {min(len(table), groups)} of {groups} '{plan.group_by}' groups."
    if additive and plan.order == "desc" and len(table) >= 2:
        share = sum(r.get("share_pct") or 0 for r in table[:3])
        interpretation += f" The top {min(3, len(table))} account for {share:.1f}% of the total."
    limitations = []
    if plan.aggregation == "sum" and groups > 1:
        limitations.append("Totals reflect both volume and value. A group can rank low because it has fewer records; compare averages to separate the two.")
    spec = {"chart_type": "bar", "x": plan.group_by, "y": plan.metric_column, "aggregation": plan.aggregation, "filters": [f.model_dump() for f in plan.filters],
            "limit": plan.limit, "sort": "value_desc" if plan.order == "desc" else "value_asc"}
    return ExecutionResult(
        answer,
        key_findings=findings,
        interpretation=interpretation,
        follow_ups=[f"Show the trend of {plan.metric_column or 'records'} over time" , f"What is the average {plan.metric_column} by {plan.group_by}?" if plan.metric_column else f"Show {plan.group_by} as a chart"],
        limitations=limitations,
        table_columns=list(table[0].keys()),
        table_rows=table,
        chart=_chart(spec, schema, path),
        columns_used=[c for c in [plan.group_by, plan.metric_column] if c],
        calculation=f"{plan.aggregation.upper()} of {plan.metric_column or 'rows'} grouped by {plan.group_by}, sorted {plan.order}, top {plan.limit}",
        rows_used=used,
    )


def _period_rows(plan: AnalysisPlan, schema, path: Path) -> tuple[list[tuple], int, str | None, object]:
    where, params = build_where(plan.filters, schema)
    time = quote(plan.time_column)
    filtered = f"{where} AND {time} IS NOT NULL" if where else f" WHERE {time} IS NOT NULL"
    with connect(path) as con:
        _, rows = run_query(con, f"SELECT DATE_TRUNC('{plan.time_grain}', {time}) AS p, {_metric_sql(plan)}, COUNT(*) FROM data{filtered} GROUP BY 1 ORDER BY 1", params)
        _, count = run_query(con, f"SELECT COUNT(*), MAX({time}) FROM data{filtered}", params)
        time_range = _time_range(con, plan.time_column, filtered, params)
    return rows, int(count[0][0]), time_range, count[0][1]


def _period_label(value, grain: str) -> str:
    if grain == "quarter":
        return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
    return value.strftime(PERIOD_FORMAT[grain])


def _partial_last_period(last_date, grain: str) -> bool:
    if last_date is None:
        return False
    freq = {"day": "D", "week": "W-SUN", "month": "M", "quarter": "Q", "year": "Y"}[grain]
    end = pd.Timestamp(last_date).to_period(freq).end_time.normalize()
    return pd.Timestamp(last_date).normalize() < end


def _run_time_series(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    rows, used, time_range, last_date = _period_rows(plan, schema, path)
    label = _metric_label(plan)
    table = []
    previous = None
    for period, value, count in rows:
        value = json_safe(value)
        change = round((value - previous) / abs(previous) * 100, 2) if previous not in (None, 0) and value is not None else None
        table.append({"period": _period_label(period, plan.time_grain), label: value, "change_pct": change, "rows": int(count)})
        previous = value
    valued = [r for r in table if r[label] is not None]
    if not valued:
        return ExecutionResult(f"No values were available to calculate the {label} over time{_filter_text(plan)}.", rows_used=used)
    high = max(valued, key=lambda r: r[label])
    low = min(valued, key=lambda r: r[label])
    best = high if plan.order == "desc" else low
    word = "highest" if plan.order == "desc" else "lowest"
    first, last = valued[0], valued[-1]
    overall = (last[label] - first[label]) / abs(first[label]) * 100 if first[label] else None
    findings = [
        f"Highest {plan.time_grain}: {high['period']} at {fmt(high[label])}.",
        f"Lowest {plan.time_grain}: {low['period']} at {fmt(low[label])}.",
    ]
    if overall is not None and len(valued) > 1:
        findings.append(f"From {first['period']} to {last['period']}, the {label} changed by {pct(overall)} ({fmt(first[label])} to {fmt(last[label])}).")
    changes = [r for r in valued if r["change_pct"] is not None]
    if changes:
        jump = max(changes, key=lambda r: abs(r["change_pct"]))
        findings.append(f"Largest {plan.time_grain}-on-{plan.time_grain} change: {jump['period']} at {pct(jump['change_pct'])}.")
    limitations = []
    if _partial_last_period(last_date, plan.time_grain):
        limitations.append(f"The final {plan.time_grain} ({last['period']}) appears incomplete, because the data ends on {pd.Timestamp(last_date).date().isoformat()}. Treat its value with care.")
    direction = "risen" if (overall or 0) > 2 else "fallen" if (overall or 0) < -2 else "stayed broadly flat"
    spec = {"chart_type": "line", "x": plan.time_column, "y": plan.metric_column, "aggregation": plan.aggregation, "time_grain": plan.time_grain,
            "filters": [f.model_dump() for f in plan.filters], "limit": 500}
    return ExecutionResult(
        f"The {word} {label} was in {best['period']}, at {fmt(best[label])}{_filter_text(plan)}.",
        key_findings=findings,
        interpretation=f"Comparing the first and last {plan.time_grain}, the {label} has {direction}. This describes what happened in the data, not why it happened.",
        follow_ups=[f"Are there unusual changes in {plan.metric_column or 'record counts'}?", "Compare this across the last two years"],
        limitations=limitations,
        table_columns=["period", label, "change_pct", "rows"],
        table_rows=table,
        chart=_chart(spec, schema, path),
        columns_used=[c for c in [plan.time_column, plan.metric_column] if c],
        calculation=f"{plan.aggregation.upper()} of {plan.metric_column or 'rows'} per {plan.time_grain} of {plan.time_column}",
        time_range=time_range,
        rows_used=used,
    )


def _run_comparison(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    where, params = build_where(plan.filters, schema)
    time = quote(plan.time_column)
    filtered = f"{where} AND {time} IS NOT NULL" if where else f" WHERE {time} IS NOT NULL"
    metric = _metric_sql(plan)
    label = _metric_label(plan)
    with connect(path) as con:
        _, years = run_query(con, f"SELECT DISTINCT EXTRACT(year FROM {time})::INT AS y FROM data{filtered} ORDER BY y DESC LIMIT ?", params + [plan.periods_to_compare])
        chosen = sorted(int(y[0]) for y in years)
        if len(chosen) < 2:
            return ExecutionResult(f"The data covers only {len(chosen)} calendar year, so years cannot be compared.", answered=False,
                                   limitations=["A year-on-year comparison needs at least two calendar years."], columns_used=[plan.time_column])
        marks = ", ".join("?" for _ in chosen)
        grain_sql = f"EXTRACT(month FROM {time})::INT" if plan.time_grain != "quarter" else f"EXTRACT(quarter FROM {time})::INT"
        _, rows = run_query(con, f"SELECT {grain_sql} AS p, EXTRACT(year FROM {time})::INT AS y, {metric} FROM data{filtered} AND EXTRACT(year FROM {time})::INT IN ({marks}) GROUP BY 1, 2 ORDER BY 1, 2", params + chosen)
        _, annual = run_query(con, f"SELECT EXTRACT(year FROM {time})::INT AS y, {metric}, COUNT(*), MIN({time}), MAX({time}) FROM data{filtered} AND EXTRACT(year FROM {time})::INT IN ({marks}) GROUP BY 1 ORDER BY 1", params + chosen)
        time_range = _time_range(con, plan.time_column, filtered, params)
    prefix = "Q" if plan.time_grain == "quarter" else "M"
    pivot: dict[int, dict] = {}
    for period, year, value in rows:
        pivot.setdefault(int(period), {"period": f"{prefix}{int(period):02d}" if prefix == "M" else f"Q{int(period)}"})[str(year)] = json_safe(value)
    table = [pivot[p] for p in sorted(pivot)]
    a, b = str(chosen[-2]), str(chosen[-1])
    for record in table:
        va, vb = record.get(a), record.get(b)
        record["change_pct"] = round((vb - va) / abs(va) * 100, 2) if va not in (None, 0) and vb is not None else None
    annual_map = {int(r[0]): json_safe(r[1]) for r in annual}
    va, vb = annual_map[chosen[-2]], annual_map[chosen[-1]]
    change = (vb - va) / abs(va) * 100 if va else None
    findings = [f"{y}: {label} {fmt(annual_map[y])}." for y in chosen]
    changes = [r for r in table if r["change_pct"] is not None]
    if changes:
        up = max(changes, key=lambda r: r["change_pct"])
        down = min(changes, key=lambda r: r["change_pct"])
        findings.append(f"Largest increase: {up['period']} ({pct(up['change_pct'])}).")
        findings.append(f"Largest decrease: {down['period']} ({pct(down['change_pct'])}).")
    limitations = []
    last_row = annual[-1]
    if last_row[4].month < 12 or last_row[3].month > 1:
        limitations.append(f"{chosen[-1]} is not a complete year in this data ({last_row[3].date()} to {last_row[4].date()}), so the annual comparison is not like-for-like. Compare matching months instead.")
    return ExecutionResult(
        f"The {label} was {fmt(vb)} in {chosen[-1]}, compared with {fmt(va)} in {chosen[-2]} ({pct(change)}){_filter_text(plan)}.",
        key_findings=findings,
        interpretation="Matching periods are compared side by side, which removes the effect of seasonality from the comparison.",
        follow_ups=["Which month had the highest value?", "Are there unusual changes over time?"],
        limitations=limitations,
        table_columns=["period", *[str(y) for y in chosen], "change_pct"],
        table_rows=table,
        chart={"chart_type": "line", "title": f"{label.capitalize()} by year", "rows": [{"x": r["period"], **{str(y): r.get(str(y)) for y in chosen}} for r in table],
               "series": [str(y) for y in chosen], "x_type": "category", "x_label": "Period", "y_label": label, "notes": [], "filters": describe_filters(plan.filters), "rows_matched": sum(int(r[2]) for r in annual)},
        columns_used=[c for c in [plan.time_column, plan.metric_column] if c],
        calculation=f"{plan.aggregation.upper()} of {plan.metric_column or 'rows'} per {plan.time_grain}, compared across {chosen}",
        time_range=time_range,
        rows_used=sum(int(r[2]) for r in annual),
    )


def _run_distribution(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    where, params = build_where(plan.filters, schema)
    c = quote(plan.metric_column)
    with connect(path) as con:
        names, rows = run_query(
            con,
            f"SELECT COUNT({c}) AS count, AVG({c}) AS mean, MEDIAN({c}) AS median, STDDEV_SAMP({c}) AS std, MIN({c}) AS min, QUANTILE_CONT({c}, 0.25) AS q1, QUANTILE_CONT({c}, 0.75) AS q3, MAX({c}) AS max FROM data{where}",
            params,
        )
    stats = dict(zip(names, map(json_safe, rows[0]), strict=True))
    if not stats["count"]:
        return ExecutionResult(f"'{plan.metric_column}' has no values{_filter_text(plan)}.", rows_used=0)
    skew = "higher values pull the average above the median" if (stats["mean"] or 0) > (stats["median"] or 0) * 1.1 else "lower values pull the average below the median" if (stats["mean"] or 0) < (stats["median"] or 0) * 0.9 else "the average and median are close, suggesting a fairly balanced spread"
    spec = {"chart_type": "histogram", "x": plan.metric_column, "filters": [f.model_dump() for f in plan.filters]}
    return ExecutionResult(
        f"'{plan.metric_column}' ranges from {fmt(stats['min'])} to {fmt(stats['max'])}, with a median of {fmt(stats['median'])} and a mean of {fmt(stats['mean'])}{_filter_text(plan)}.",
        key_findings=[f"Middle 50% of values: {fmt(stats['q1'])} to {fmt(stats['q3'])}.", f"Sample standard deviation: {fmt(stats['std'])}."],
        interpretation=f"In this column, {skew}.",
        follow_ups=[f"Are there outliers in {plan.metric_column}?"],
        table_columns=["statistic", "value"],
        table_rows=[{"statistic": k, "value": v} for k, v in stats.items()],
        chart=_chart(spec, schema, path),
        columns_used=[plan.metric_column],
        calculation=f"Descriptive statistics of {plan.metric_column}",
        rows_used=int(stats["count"]),
    )


def _run_correlation(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    where, params = build_where(plan.filters, schema)
    others = [plan.secondary_column] if plan.secondary_column else [c["name"] for c in schema if is_measure(c) and c["name"] != plan.metric_column][:10]
    if not others:
        return ExecutionResult("Only one suitable numeric column is available, so no correlation can be calculated.", answered=False)
    a = quote(plan.metric_column)
    table = []
    with connect(path) as con:
        for other in others:
            b = quote(other)
            pair = f"{where} AND {a} IS NOT NULL AND {b} IS NOT NULL" if where else f" WHERE {a} IS NOT NULL AND {b} IS NOT NULL"
            _, rows = run_query(con, f"SELECT CORR({a}, {b}), COUNT(*) FROM data{pair}", params)
            table.append({"column_a": plan.metric_column, "column_b": other, "pearson_r": round(v, 4) if (v := json_safe(rows[0][0])) is not None else None, "pairs": int(rows[0][1])})
    table.sort(key=lambda r: abs(r["pearson_r"] or 0), reverse=True)
    best = table[0]
    if best["pearson_r"] is None:
        return ExecutionResult("A correlation could not be calculated, because the selected columns do not vary.", answered=False)
    r = best["pearson_r"]
    strength = "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak"
    direction = "positive" if r > 0 else "negative"
    spec = {"chart_type": "scatter", "x": plan.metric_column, "y": best["column_b"], "filters": [f.model_dump() for f in plan.filters]}
    return ExecutionResult(
        f"'{plan.metric_column}' and '{best['column_b']}' have a {strength} {direction} linear correlation (Pearson r = {r:.3f}, {best['pairs']:,} pairs).",
        key_findings=[f"{t['column_a']} vs {t['column_b']}: r = {t['pearson_r']}" for t in table[:5]],
        interpretation="Correlation shows that two columns move together. It does not show that one causes the other.",
        limitations=["Pearson correlation only detects linear relationships and is sensitive to outliers."],
        follow_ups=[f"Are there outliers in {plan.metric_column}?"],
        table_columns=["column_a", "column_b", "pearson_r", "pairs"],
        table_rows=table,
        chart=_chart(spec, schema, path),
        columns_used=[plan.metric_column, *others],
        calculation="Pearson correlation over rows where both values are present",
        rows_used=best["pairs"],
    )


def _run_anomaly(plan: AnalysisPlan, schema, path: Path) -> ExecutionResult:
    frame = read_frame(path, keep_row_id=True)
    columns = [plan.metric_column] if plan.metric_column else None
    detected = run_detection(frame, schema, columns=columns)
    findings = sorted(detected["findings"], key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f["severity"]], -f["score"]))
    summary = detected["summary"]
    table = [{"where": f["period"] or (f"row {f['row_id']}" if f["row_id"] else "category"), "column": f["column_name"], "observed": f["observed"], "severity": f["severity"], "score": f["score"], "method": f["method"]} for f in findings[:20]]
    methods = sorted({m["method"] for m in summary["methods"]})
    scope = f"'{plan.metric_column}'" if plan.metric_column else "the dataset"
    if not findings:
        answer = f"No statistical anomalies were found in {scope} using {', '.join(methods) or 'the available methods'}."
    else:
        counts = summary["by_severity"]
        answer = f"{len(findings):,} statistical anomalies were flagged in {scope}: {counts['high']} high, {counts['medium']} medium, and {counts['low']} low severity."
    chart = None
    series_key = next((k for k in summary["series"] if plan.metric_column and k.endswith(f":{plan.metric_column}")), None)
    if series_key:
        series = summary["series"][series_key]
        chart = {"chart_type": "line", "title": series["label"], "rows": [{"x": p["period"], series["label"]: p["value"], "Baseline": p["baseline"]} for p in series["points"]],
                 "series": [series["label"], "Baseline"], "x_type": "date", "x_label": "Period", "y_label": series["label"], "notes": [], "filters": [], "rows_matched": summary["rows_checked"]}
    return ExecutionResult(
        answer,
        key_findings=[f["explanation"] for f in findings[:5]],
        interpretation=DISCLAIMER,
        limitations=summary["skipped"][:5] + ["Rolling baselines do not model seasonality, so regular seasonal peaks can be flagged."] if any(m.get("listed") is None for m in summary["methods"]) else summary["skipped"][:5],
        follow_ups=["Open Anomaly Detection to review each record"],
        table_columns=["where", "column", "observed", "severity", "score", "method"] if table else [],
        table_rows=table,
        chart=chart,
        columns_used=columns or [m["column"] for m in summary["methods"]],
        calculation="; ".join(f"{m['column']}: {m['method']}" for m in summary["methods"][:6]) or "No method applicable",
        rows_used=summary["rows_checked"],
    )


def _run_summary(plan: AnalysisPlan, schema, path: Path, profile: dict, quality: dict) -> ExecutionResult:
    findings = [
        f"The dataset has {profile['row_count']:,} rows and {profile['column_count']} columns.",
        f"{profile['missing_pct']}% of cells are missing and {profile['duplicate_rows']:,} rows are exact duplicates. The data quality score is {quality.get('score', 'n/a')}/100.",
    ]
    table = []
    by_name = {c["name"]: c for c in profile["columns"]}
    measures = [c for c in schema if is_measure(c)]
    dates = [c for c in schema if c["type"] == "date"]
    categories = [c for c in schema if c["type"] == "category"]
    primary = primary_measure(schema)
    time_range = None
    chart = None
    if dates:
        info = by_name[dates[0]["name"]]
        if info.get("earliest"):
            time_range = f"{info['earliest'][:10]} to {info['latest'][:10]}"
            findings.append(f"'{dates[0]['name']}' covers {time_range}.")
    for column in measures[:6]:
        info = by_name[column["name"]]
        if info.get("mean") is not None:
            table.append({"column": column["name"], "mean": info["mean"], "median": info["median"], "min": info["min"], "max": info["max"], "missing": info["missing"]})
    interpretation = "This overview describes the structure of the data and the size of its main values."
    if primary and dates:
        plan_t = AnalysisPlan(operation="time_series", metric_column=primary["name"], time_column=dates[0]["name"], aggregation="sum", time_grain="month")
        trend = _run_time_series(plan_t, schema, path)
        findings.extend(trend.key_findings[:3])
        chart = trend.chart
        interpretation = trend.interpretation
    if primary and categories:
        plan_g = AnalysisPlan(operation="group_aggregate", metric_column=primary["name"], group_by=categories[0]["name"], aggregation="sum", limit=5)
        grouped = _run_group(plan_g, schema, path)
        if grouped.table_rows:
            top = grouped.table_rows[0]
            label = _metric_label(plan_g)
            findings.append(f"Largest '{categories[0]['name']}' by {label}: {top[categories[0]['name']]} at {fmt(top[label])}.")
        chart = chart or grouped.chart
    for issue in quality.get("issues", [])[:2]:
        findings.append(f"Data quality: {issue['detail']}")
    return ExecutionResult(
        f"This dataset has {profile['row_count']:,} records across {profile['column_count']} columns" + (f", covering {time_range}" if time_range else "") + ".",
        key_findings=findings,
        interpretation=interpretation,
        follow_ups=[q for q in [f"Which {categories[0]['name']} has the highest {primary['name']}?" if categories and primary else None, f"Are there unusual changes in {primary['name']}?" if primary else None, "What should I clean first?" if quality.get("issues") else None] if q],
        limitations=["The summary reports what is present in the data. It cannot explain causes that are not recorded in the dataset."],
        table_columns=["column", "mean", "median", "min", "max", "missing"] if table else [],
        table_rows=table,
        chart=chart,
        columns_used=[c["name"] for c in schema],
        calculation="Stored data profile, plus monthly and category aggregates of the primary numeric column",
        time_range=time_range,
        rows_used=profile["row_count"],
    )


def _run_recommendation(schema: list[dict]) -> ExecutionResult:
    options = recommend_charts(schema)
    if not options:
        return ExecutionResult("No chart suggestion is possible, because no suitable numeric, date, or category columns were found.", answered=False)
    return ExecutionResult(
        f"Based on this dataset's structure, the best first chart is: {options[0]['title']}.",
        key_findings=[f"{o['title']}: {o['reason']}" for o in options],
        interpretation="These suggestions come from the column types only. Open one in the Visualisation Studio to see real values.",
        table_columns=["chart_type", "title", "reason"],
        table_rows=[{"chart_type": o["spec"]["chart_type"], "title": o["title"], "reason": o["reason"]} for o in options],
        calculation="Rules based on column types and cardinality",
        columns_used=sorted({v for o in options for k, v in o["spec"].items() if k in {"x", "y"}}),
    )


def execute_plan(plan: AnalysisPlan, schema: list[dict], path: Path, profile: dict, quality: dict) -> ExecutionResult:
    op = plan.operation
    if op == "metric":
        return _run_metric(plan, schema, path)
    if op == "group_aggregate":
        return _run_group(plan, schema, path)
    if op == "time_series":
        return _run_time_series(plan, schema, path)
    if op == "period_comparison":
        return _run_comparison(plan, schema, path)
    if op == "distribution":
        return _run_distribution(plan, schema, path)
    if op == "correlation":
        return _run_correlation(plan, schema, path)
    if op == "anomaly_scan":
        return _run_anomaly(plan, schema, path)
    if op == "dataset_summary":
        return _run_summary(plan, schema, path, profile, quality)
    if op == "chart_recommendation":
        return _run_recommendation(schema)
    numeric = ", ".join(c["name"] for c in schema if c["type"] in NUMERIC_TYPES)[:200]
    return ExecutionResult(
        "I can't answer that from this dataset.",
        key_findings=[plan.reason] if plan.reason else [],
        interpretation="I answer only with calculations on the data in this dataset, so I won't estimate or guess.",
        follow_ups=["Summarise this dataset", "What are the main trends?", "Are there unusual values?"],
        limitations=[f"Numeric columns available: {numeric or 'none'}."],
        answered=False,
    )
