"""Chart specification, validation, execution, and rule-based recommendations.

Every chart value comes from a DuckDB query against the stored dataset version.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .frames import NUMERIC_TYPES, STRING_TYPES, json_safe
from .query_engine import Filter, QueryError, build_where, column_map, connect, describe_filters, quote, require_column, run_query

ChartType = Literal["bar", "line", "area", "pie", "donut", "scatter", "histogram", "box"]
Aggregation = Literal["sum", "avg", "count", "min", "max", "median"]
TimeGrain = Literal["auto", "day", "week", "month", "quarter", "year"]
SQL_AGG = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "median": "MEDIAN"}
AGG_LABEL = {"sum": "Total", "avg": "Average", "count": "Count", "min": "Minimum", "max": "Maximum", "median": "Median"}
MAX_SERIES = 6  # the size of the validated colour-blind-safe chart palette
MAX_SLICES = 5  # five slices plus "Other" keeps part-to-whole charts readable
SCATTER_LIMIT = 2000
ID_RE = re.compile(r"(^|[_\s.-])(id|uuid|guid|key|code|number|no|sku|zip|postcode|phone)($|[_\s.-])|id$", re.I)


class ChartSpec(BaseModel):
    chart_type: ChartType
    x: str | None = Field(default=None, max_length=255)
    y: str | None = Field(default=None, max_length=255)
    group: str | None = Field(default=None, max_length=255)
    aggregation: Aggregation = "sum"
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    time_grain: TimeGrain = "auto"
    sort: Literal["value_desc", "value_asc", "x"] = "value_desc"
    limit: int = Field(default=30, ge=1, le=500)
    bins: int = Field(default=20, ge=3, le=100)
    title: str | None = Field(default=None, max_length=200)
    x_label: str | None = Field(default=None, max_length=100)
    y_label: str | None = Field(default=None, max_length=100)


def is_identifier(column: dict) -> bool:
    return bool(ID_RE.search(column["name"]))


def is_measure(column: dict) -> bool:
    return column["type"] in NUMERIC_TYPES and not is_identifier(column)


PRIMARY_NAMES = ("revenue", "sales", "amount", "total", "value", "profit", "sessions", "units", "quantity", "price")


def primary_measure(columns: list[dict]) -> dict | None:
    """Choose the column most likely to be the main business measure."""
    measures = [c for c in columns if is_measure(c)]
    for wanted in PRIMARY_NAMES:
        for column in measures:
            if wanted in re.split(r"[_\s.-]+", column["name"].lower()):
                return column
    return measures[0] if measures else None


def validate_spec(spec: ChartSpec, schema: list[dict]) -> None:
    """Reject field combinations that would produce a meaningless chart."""
    columns = column_map(schema)
    x = require_column(columns, spec.x) if spec.x else None
    y = require_column(columns, spec.y) if spec.y else None
    group = require_column(columns, spec.group) if spec.group else None
    chart = spec.chart_type

    if chart in {"bar", "line", "area", "pie", "donut"}:
        if x is None:
            raise QueryError("Choose a field for the X axis.")
        if spec.aggregation != "count":
            if y is None:
                raise QueryError("Choose a numeric field for the Y axis, or use the Count aggregation.")
            if y["type"] not in NUMERIC_TYPES:
                raise QueryError(f"{AGG_LABEL[spec.aggregation]} needs a numeric field; '{y['name']}' is {y['type']}.")
        if group and group["type"] not in STRING_TYPES | {"boolean"}:
            raise QueryError(f"Grouping needs a categorical field; '{group['name']}' is {group['type']}.")
    if chart in {"line", "area"} and x and x["type"] not in NUMERIC_TYPES | {"date"}:
        raise QueryError(f"{chart.title()} charts need a date or numeric X axis; '{x['name']}' is {x['type']}. Use a bar chart instead.")
    if chart in {"pie", "donut"}:
        if group:
            raise QueryError(f"{chart.title()} charts do not support grouping. Use a bar chart instead.")
        if x and x["type"] not in STRING_TYPES | {"boolean"}:
            raise QueryError(f"{chart.title()} charts need a categorical field; '{x['name']}' is {x['type']}.")
        if spec.aggregation not in {"sum", "count"}:
            raise QueryError(f"{chart.title()} charts show parts of a whole, so they support only Sum and Count.")
    if chart == "scatter":
        if x is None or y is None:
            raise QueryError("Scatter plots need numeric fields for both axes.")
        if x["type"] not in NUMERIC_TYPES or y["type"] not in NUMERIC_TYPES:
            raise QueryError("Scatter plots need numeric fields for both axes.")
        if group and group["type"] not in STRING_TYPES | {"boolean"}:
            raise QueryError("Scatter plot grouping needs a categorical field.")
    if chart == "histogram" and (x is None or x["type"] not in NUMERIC_TYPES):
        raise QueryError("Histograms need a numeric field on the X axis.")
    if chart == "box":
        if y is None or y["type"] not in NUMERIC_TYPES:
            raise QueryError("Box plots need a numeric field on the Y axis.")
        if x and x["type"] not in STRING_TYPES | {"boolean"}:
            raise QueryError("Box plots can only be split by a categorical field.")


def _metric_sql(spec: ChartSpec) -> str:
    if spec.aggregation == "count":
        return f"COUNT({quote(spec.y)})" if spec.y else "COUNT(*)"
    return f"{SQL_AGG[spec.aggregation]}({quote(spec.y)})"


def metric_label(spec: ChartSpec) -> str:
    if spec.y_label:
        return spec.y_label
    if spec.aggregation == "count":
        return f"Count of {spec.y}" if spec.y else "Row count"
    return f"{AGG_LABEL[spec.aggregation]} {spec.y}"


def _and(where: str, clause: str) -> str:
    return f"{where} AND {clause}" if where else f" WHERE {clause}"


def _auto_grain(con, column: str, where: str, params: list) -> str:
    _, result = run_query(con, f"SELECT MIN({quote(column)}), MAX({quote(column)}) FROM data{where}", params)
    low, high = result[0]
    if low is None:
        return "month"
    days = (high - low).days
    if days <= 62:
        return "day"
    if days <= 180:
        return "week"
    if days <= 365 * 6:
        return "month"
    return "year"


def _categories_and_time(spec: ChartSpec, schema_map: dict, con, where: str, params: list) -> dict:
    x_col = schema_map[spec.x]
    x_sql = quote(spec.x)
    notes: list[str] = []
    grain = None
    if x_col["type"] == "date":
        grain = spec.time_grain if spec.time_grain != "auto" else _auto_grain(con, spec.x, where, params)
        x_sql = f"DATE_TRUNC('{grain}', {quote(spec.x)})"
    where = _and(where, f"{quote(spec.x)} IS NOT NULL")
    metric = _metric_sql(spec)
    ordered_axis = spec.chart_type in {"line", "area"} or x_col["type"] == "date"
    if ordered_axis or spec.sort == "x":
        order = "x ASC"
    else:
        order = f"v {'DESC' if spec.sort == 'value_desc' else 'ASC'} NULLS LAST, x ASC"

    _, distinct = run_query(con, f"SELECT COUNT(DISTINCT {x_sql}) FROM data{where}", params)
    categories = int(distinct[0][0])
    limit = MAX_SLICES if spec.chart_type in {"pie", "donut"} else spec.limit

    if spec.group:
        group_sql = f"COALESCE(CAST({quote(spec.group)} AS VARCHAR), '(missing)')"
        _, top_groups = run_query(con, f"SELECT {group_sql} AS g, {metric} AS v FROM data{where} GROUP BY 1 ORDER BY ABS(v) DESC NULLS LAST, g", params)
        groups = [g for g, _ in top_groups]
        kept = groups[:MAX_SERIES]
        if len(groups) > MAX_SERIES:
            notes.append(f"Showing the {MAX_SERIES} largest of {len(groups)} groups; the others are excluded.")
        _, top_x = run_query(con, f"SELECT {x_sql} AS x, {metric} AS v FROM data{where} GROUP BY 1 ORDER BY {order} LIMIT ?", params + [limit])
        x_values = [row[0] for row in top_x]
        placeholders = ", ".join("?" for _ in x_values) or "NULL"
        group_filter = ", ".join("?" for _ in kept) or "NULL"
        _, rows = run_query(
            con,
            f"SELECT {x_sql} AS x, {group_sql} AS g, {metric} AS v FROM data{where} AND {x_sql} IN ({placeholders}) AND {group_sql} IN ({group_filter}) GROUP BY 1, 2",
            params + x_values + kept,
        )
        table = {json_safe(x): {"x": json_safe(x)} for x in x_values}
        for x, g, v in rows:
            table[json_safe(x)][g] = json_safe(v)
        data = list(table.values())
        series = kept
    else:
        name = metric_label(spec)
        _, rows = run_query(con, f"SELECT {x_sql} AS x, {metric} AS v FROM data{where} GROUP BY 1 ORDER BY {order} LIMIT ?", params + [limit])
        data = [{"x": json_safe(x), name: json_safe(v)} for x, v in rows]
        series = [name]
        if spec.chart_type in {"pie", "donut"}:
            if any((row[name] or 0) < 0 for row in data):
                raise QueryError("Pie and donut charts cannot show negative values. Use a bar chart instead.")
            if categories > limit:
                _, total = run_query(con, f"SELECT {metric} FROM data{where}", params)
                remainder = (json_safe(total[0][0]) or 0) - sum(row[name] or 0 for row in data)
                data.append({"x": "Other", name: remainder})
                notes.append(f"The smallest {categories - limit} categories are combined as 'Other'.")
    if categories > limit and spec.chart_type not in {"pie", "donut"}:
        notes.append(f"Showing {limit} of {categories} X-axis values. Use filters or raise the limit to see more.")
    return {"rows": data, "series": series, "x_type": x_col["type"], "time_grain": grain, "notes": notes}


def _scatter(spec: ChartSpec, con, where: str, params: list) -> dict:
    where = _and(_and(where, f"{quote(spec.x)} IS NOT NULL"), f"{quote(spec.y)} IS NOT NULL")
    _, count = run_query(con, f"SELECT COUNT(*) FROM data{where}", params)
    total = int(count[0][0])
    group_sql = f", COALESCE(CAST({quote(spec.group)} AS VARCHAR), '(missing)') AS g" if spec.group else ""
    # Taking every nth row by row id gives a deterministic, evenly spread sample.
    step = max(1, total // SCATTER_LIMIT)
    _, rows = run_query(
        con,
        f"SELECT {quote(spec.x)}, {quote(spec.y)}{group_sql} FROM (SELECT *, row_number() OVER (ORDER BY __row_id) AS rn FROM data{where}) WHERE rn % ? = 0 LIMIT ?",
        params + [step, SCATTER_LIMIT],
    )
    notes = [f"Showing an evenly spaced sample of {len(rows):,} of {total:,} points."] if step > 1 else []
    data = [{"x": json_safe(r[0]), "y": json_safe(r[1]), **({"group": r[2]} if spec.group else {})} for r in rows]
    series = sorted({d["group"] for d in data})[:MAX_SERIES] if spec.group else ["Observations"]
    if spec.group:
        data = [d for d in data if d["group"] in series]
    return {"rows": data, "series": series, "x_type": "number", "notes": notes}


def _histogram(spec: ChartSpec, con, where: str, params: list) -> dict:
    column = quote(spec.x)
    where = _and(where, f"{column} IS NOT NULL")
    _, stats = run_query(con, f"SELECT MIN({column}), MAX({column}), COUNT(*) FROM data{where}", params)
    low, high, total = stats[0]
    if not total:
        return {"rows": [], "series": ["Count"], "x_type": "bin", "notes": ["No values match the current filters."]}
    low, high = float(low), float(high)
    if low == high:
        return {"rows": [{"x": f"{low:g}", "start": low, "end": high, "Count": int(total)}], "series": ["Count"], "x_type": "bin", "notes": []}
    width = (high - low) / spec.bins
    _, rows = run_query(
        con,
        f"SELECT LEAST(CAST(FLOOR(({column} - ?) / ?) AS BIGINT), ?) AS b, COUNT(*) FROM data{where} GROUP BY 1 ORDER BY 1",
        [low, width, spec.bins - 1] + params,
    )
    counts = {int(b): int(c) for b, c in rows}
    data = []
    for i in range(spec.bins):
        start, end = low + i * width, low + (i + 1) * width
        data.append({"x": f"{start:,.4g}-{end:,.4g}", "start": start, "end": end, "Count": counts.get(i, 0)})
    return {"rows": data, "series": ["Count"], "x_type": "bin", "notes": []}


def _box(spec: ChartSpec, con, where: str, params: list) -> dict:
    column = quote(spec.y)
    where = _and(where, f"{column} IS NOT NULL")
    group_sql = f"COALESCE(CAST({quote(spec.x)} AS VARCHAR), '(missing)')" if spec.x else "'All values'"
    _, rows = run_query(
        con,
        f"""SELECT {group_sql} AS g, COUNT(*) AS n, MIN({column}) AS lo, QUANTILE_CONT({column}, 0.25) AS q1, MEDIAN({column}) AS med,
        QUANTILE_CONT({column}, 0.75) AS q3, MAX({column}) AS hi FROM data{where} GROUP BY 1 ORDER BY n DESC, g LIMIT 12""",
        params,
    )
    data = []
    for g, n, lo, q1, med, q3, hi in rows:
        lo, q1, med, q3, hi = (float(v) for v in (lo, q1, med, q3, hi))
        iqr = q3 - q1
        fence_low, fence_high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        _, whisker = run_query(
            con,
            f"SELECT MIN({column}) FILTER (WHERE {column} >= ?), MAX({column}) FILTER (WHERE {column} <= ?), COUNT(*) FILTER (WHERE {column} < ? OR {column} > ?) FROM data{_and(where, f'{group_sql} = ?')}",
            [fence_low, fence_high, fence_low, fence_high] + params + [g],
        )
        data.append({"x": g, "count": int(n), "min": lo, "q1": q1, "median": med, "q3": q3, "max": hi,
                     "whisker_low": json_safe(whisker[0][0]), "whisker_high": json_safe(whisker[0][1]), "outliers": int(whisker[0][2])})
    return {"rows": data, "series": ["distribution"], "x_type": "category", "notes": []}


def run_chart(spec: ChartSpec, schema: list[dict], path: Path) -> dict:
    validate_spec(spec, schema)
    schema_map = column_map(schema)
    where, params = build_where(spec.filters, schema)
    with connect(path) as con:
        _, count = run_query(con, f"SELECT COUNT(*) FROM data{where}", params)
        matched = int(count[0][0])
        if spec.chart_type == "scatter":
            result = _scatter(spec, con, where, params)
        elif spec.chart_type == "histogram":
            result = _histogram(spec, con, where, params)
        elif spec.chart_type == "box":
            result = _box(spec, con, where, params)
        else:
            result = _categories_and_time(spec, schema_map, con, where, params)
    result.update(
        chart_type=spec.chart_type,
        title=spec.title or default_title(spec),
        x_label=spec.x_label or spec.x or "",
        y_label=metric_label(spec) if spec.chart_type not in {"histogram", "scatter", "box"} else (spec.y_label or spec.y or "Count"),
        rows_matched=matched,
        filters=describe_filters(spec.filters),
        aggregation=spec.aggregation,
    )
    return result


def default_title(spec: ChartSpec) -> str:
    if spec.chart_type == "histogram":
        return f"Distribution of {spec.x}"
    if spec.chart_type == "box":
        return f"{spec.y} by {spec.x}" if spec.x else f"Distribution of {spec.y}"
    if spec.chart_type == "scatter":
        return f"{spec.y} vs {spec.x}"
    return f"{metric_label(spec)} by {spec.x}"


def recommend_charts(schema: list[dict], limit: int = 6) -> list[dict]:
    """Suggest charts from the dataset's actual structure. Suggestions are specs, never values."""
    measures = [c for c in schema if is_measure(c)]
    dates = [c for c in schema if c["type"] == "date"]
    categories = [c for c in schema if c["type"] == "category" and 2 <= c.get("unique", 3)]
    low_card = [c for c in categories if c.get("unique", 3) <= MAX_SLICES]
    suggestions: list[dict] = []

    def add(spec: dict, reason: str) -> None:
        chart = ChartSpec(**spec)
        validate_spec(chart, schema)
        suggestions.append({"spec": chart.model_dump(exclude_defaults=True) | {"chart_type": chart.chart_type}, "title": default_title(chart), "reason": reason})

    primary = primary_measure(schema)
    secondary = next((m for m in measures if m is not primary), None)
    if dates and primary:
        add({"chart_type": "line", "x": dates[0]["name"], "y": primary["name"], "aggregation": "sum"},
            f"'{dates[0]['name']}' is a date and '{primary['name']}' is numeric, so a line chart shows how it changes over time.")
    elif dates:
        add({"chart_type": "line", "x": dates[0]["name"], "aggregation": "count"}, f"A line chart shows how many records occur over '{dates[0]['name']}'.")
    if categories and primary:
        add({"chart_type": "bar", "x": categories[0]["name"], "y": primary["name"], "aggregation": "sum"},
            f"A bar chart compares total '{primary['name']}' across '{categories[0]['name']}'.")
    if low_card and primary and all(c.get("unique", 0) for c in low_card):
        add({"chart_type": "donut", "x": low_card[0]["name"], "y": primary["name"], "aggregation": "sum"},
            f"'{low_card[0]['name']}' has few categories, so a donut chart can show each share of the total.")
    elif low_card:
        add({"chart_type": "donut", "x": low_card[0]["name"], "aggregation": "count"}, f"'{low_card[0]['name']}' has few categories, so a donut chart can show its record share.")
    if primary:
        add({"chart_type": "histogram", "x": primary["name"]}, f"A histogram shows how '{primary['name']}' values are distributed.")
    if primary and secondary:
        add({"chart_type": "scatter", "x": secondary["name"], "y": primary["name"]},
            f"A scatter plot shows whether '{secondary['name']}' and '{primary['name']}' move together.")
    if low_card and primary:
        add({"chart_type": "box", "x": low_card[0]["name"], "y": primary["name"]},
            f"A box plot compares the spread of '{primary['name']}' across '{low_card[0]['name']}'.")
    return suggestions[:limit]
