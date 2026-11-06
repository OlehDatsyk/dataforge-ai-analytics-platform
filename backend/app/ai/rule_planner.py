"""Deterministic question parser used in demonstration mode. It involves no AI model.

It recognises common analytical phrasings and maps words to real columns. Anything it cannot map is
reported as unsupported rather than guessed.
"""
from __future__ import annotations

import re

from ..services.charts import is_identifier, is_measure, primary_measure
from ..services.query_engine import Filter
from .plan import AnalysisPlan

METRIC_SYNONYMS = {
    "revenue": ["revenue", "sales", "amount", "total", "turnover", "income", "gmv"],
    "sales": ["sales", "revenue", "amount", "total"],
    "income": ["income", "revenue", "amount"],
    "spend": ["spend", "cost", "amount", "expense"],
    "profit": ["profit", "margin", "net"],
    "cost": ["cost", "expense", "spend"],
    "traffic": ["sessions", "visits", "pageviews", "users"],
    "visits": ["visits", "sessions"],
    "order value": ["order_value", "order value", "revenue", "amount", "total"],
    "value": ["value", "amount", "revenue", "total"],
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20}
GRAIN_WORDS = {"daily": "day", "day": "day", "days": "day", "weekly": "week", "week": "week", "weeks": "week", "monthly": "month", "month": "month", "months": "month",
               "quarterly": "quarter", "quarter": "quarter", "quarters": "quarter", "yearly": "year", "annual": "year", "annually": "year", "year": "year", "years": "year"}
UNSUPPORTED_RE = re.compile(r"\b(predict|prediction|forecast|will .* next|next (year|month|quarter)|future|why did|why is|why are|cause[sd]?|should we|should i)\b", re.I)
STOP_WORDS = {"the", "a", "an", "of", "in", "on", "for", "to", "by", "per", "and", "or", "what", "which", "who", "is", "are", "was", "were", "had", "has", "have", "do", "does", "did", "show", "me", "give", "my", "this", "that", "with", "across", "over", "there", "any", "it", "its"}
AVG_WORDS = re.compile(r"\b(average|avg|mean|typical)\b", re.I)
MEDIAN_WORDS = re.compile(r"\bmedian\b", re.I)
SUM_WORDS = re.compile(r"\b(total|sum|overall|altogether)\b", re.I)
COUNT_WORDS = re.compile(r"\b(how many|number of|count of|count)\b", re.I)
MAX_WORDS = re.compile(r"\b(maximum|max|largest single|biggest single)\b", re.I)
MIN_WORDS = re.compile(r"\b(minimum|min|smallest single)\b", re.I)
ASC_WORDS = re.compile(r"\b(worst|lowest|least|fewest|bottom|smallest|weakest|underperform\w*)\b", re.I)
RANK_WORDS = re.compile(r"\b(top|best|worst|highest|lowest|most|least|largest|biggest|smallest|fewest|bottom|rank\w*|strongest|weakest|perform\w*|generate[sd]?)\b", re.I)
GENERIC_NAME_WORDS = {"name", "type", "total", "value", "date", "pct", "amount"}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [_singular(t) for t in re.findall(r"[a-z0-9]+", text.lower())]


def _column_tokens(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return _tokens(spaced)


def _match_columns(question: str, columns: list[dict]) -> list[tuple[int, dict]]:
    """Score columns by how much of their name appears in the question. Exact phrases rank first."""
    words = set(_tokens(question)) - STOP_WORDS
    lowered = " ".join(_tokens(question))
    scored = []
    for column in columns:
        parts = _column_tokens(column["name"])
        if not parts:
            continue
        phrase = " ".join(parts)
        if f" {phrase} " in f" {lowered} ":
            scored.append((100 + len(parts), column))
            continue
        specific = [p for p in parts if p not in GENERIC_NAME_WORDS]
        hits = [p for p in specific if p in words]
        if hits and len(hits) == len(specific):
            scored.append((50 + len(hits), column))
        elif hits:
            scored.append((10 + len(hits), column))
    return sorted(scored, key=lambda s: -s[0])


_primary_measure = primary_measure


def _find_metric(question: str, measures: list[dict]) -> tuple[dict | None, list[str]]:
    matched = _match_columns(question, measures)
    if matched:
        return matched[0][1], []
    lowered = question.lower()
    for phrase, candidates in METRIC_SYNONYMS.items():
        if re.search(rf"\b{phrase}\b", lowered):
            for candidate in candidates:
                for column in measures:
                    if candidate.replace("_", " ") in " ".join(_column_tokens(column["name"])):
                        return column, [f"The dataset has no column named '{phrase}'; '{column['name']}' was used instead."] if candidate != phrase else []
            return None, []
    return None, []


def _find_dimension(question: str, dimensions: list[dict]) -> dict | None:
    """Prefer the column after 'by', 'per', 'each', or 'which', then any column mentioned."""
    lowered = question.lower()
    for pattern in (r"\b(?:by|per|each|across|for each|for every)\s+((?:[a-z0-9_]+\s?){1,3})", r"\b(?:which|what)\s+((?:[a-z0-9_]+\s?){1,3})"):
        for match in re.finditer(pattern, lowered):
            found = _match_columns(match.group(1), dimensions)
            if found and found[0][0] >= 50:
                return found[0][1]
    found = _match_columns(question, dimensions)
    return found[0][1] if found and found[0][0] >= 50 else None


def _limit(question: str, default: int = 10) -> int:
    lowered = question.lower()
    match = re.search(r"\b(?:top|bottom|best|worst|first|last)\s+(\d{1,2})\b", lowered) or re.search(r"\b(\d{1,2})\s+(?:best|worst|top|bottom|highest|lowest|largest|smallest|most|least)\b", lowered)
    if match:
        return max(1, min(int(match.group(1)), 50))
    for word, number in NUMBER_WORDS.items():
        if re.search(rf"\b(?:top|bottom|best|worst)\s+{word}\b|\b{word}\s+(?:best|worst|top|bottom|highest|lowest|largest|smallest)\b", lowered):
            return number
    return default


def _value_filters(question: str, schema: list[dict], profile: dict) -> list[Filter]:
    """Match category values named in the question, using the most frequent values from the profile."""
    filters = []
    by_name = {c["name"]: c for c in profile.get("columns", [])}
    lowered = f" {' '.join(re.findall(r'[a-z0-9]+', question.lower()))} "
    for column in schema:
        if column["type"] != "category":
            continue
        for item in by_name.get(column["name"], {}).get("top_values", []):
            value = str(item["value"])
            needle = " ".join(re.findall(r"[a-z0-9]+", value.lower()))
            if len(needle) >= 3 and f" {needle} " in lowered:
                filters.append(Filter(column=column["name"], op="eq", value=value))
                break
    return filters


def _year_filter(question: str, date_column: str | None) -> list[Filter]:
    if not date_column:
        return []
    years = re.findall(r"\b(?:in|during|for)\s+((?:19|20)\d{2})\b", question)
    if len(years) == 1:
        return [Filter(column=date_column, op="between", values=[f"{years[0]}-01-01", f"{years[0]}-12-31T23:59:59"])]
    return []


def _aggregation(question: str) -> str:
    if AVG_WORDS.search(question) or re.search(r"\border value\b", question, re.I):
        return "avg"
    if MEDIAN_WORDS.search(question):
        return "median"
    if MAX_WORDS.search(question):
        return "max"
    if MIN_WORDS.search(question):
        return "min"
    if COUNT_WORDS.search(question):
        return "count"
    return "sum"


def plan_question(question: str, schema: list[dict], profile: dict) -> AnalysisPlan:
    lowered = question.lower()
    measures = [c for c in schema if is_measure(c)]
    dimensions = [c for c in schema if c["type"] in {"category", "text", "boolean"} and not is_identifier(c)]
    dates = [c for c in schema if c["type"] == "date"]
    date_column = dates[0]["name"] if dates else None
    filters = _value_filters(question, schema, profile) + _year_filter(question, date_column)
    metric, assumptions = _find_metric(question, measures)
    order = "asc" if ASC_WORDS.search(question) else "desc"

    if UNSUPPORTED_RE.search(question):
        return AnalysisPlan(operation="unsupported", reason="Predictions, causes, and recommendations cannot be determined by calculating on this dataset. I can show what the data recorded.")
    if re.search(r"\b(chart|visuali[sz]\w*|plot|graph)\b", lowered) and re.search(r"\b(recommend|suggest|best|which|what|should)\b", lowered):
        return AnalysisPlan(operation="chart_recommendation")
    if re.search(r"\b(unusual|anomal\w*|outlier\w*|strange|odd|spike\w*|abnormal)\b", lowered):
        return AnalysisPlan(operation="anomaly_scan", metric_column=(metric or {}).get("name"), assumptions=assumptions)
    if re.search(r"\b(correlat\w*|relationship|related)\b", lowered) and measures:
        found = _match_columns(question, measures)
        first = found[0][1] if found else _primary_measure(measures)
        second = found[1][1]["name"] if len(found) > 1 else None
        return AnalysisPlan(operation="correlation", metric_column=first["name"], secondary_column=second, filters=filters)
    if re.search(r"\b(summar\w*|overview|describe|main (trend|finding)s?|key (trend|finding)s?|important (trend|finding)s?|explain .*(finding|trend|dataset|data)|what is in this|tell me about)\b", lowered):
        return AnalysisPlan(operation="dataset_summary")
    if re.search(r"\b(distribution|spread|histogram|range of)\b", lowered):
        target = metric or _primary_measure(measures)
        if target:
            return AnalysisPlan(operation="distribution", metric_column=target["name"], filters=filters, assumptions=assumptions)

    aggregation = _aggregation(question)
    grain = next((GRAIN_WORDS[w] for w in re.findall(r"[a-z]+", lowered) if w in GRAIN_WORDS), None)
    dimension = _find_dimension(question, dimensions)

    needs_metric = aggregation != "count"
    if needs_metric and metric is None and (RANK_WORDS.search(question) or grain or dimension or re.search(r"\btrend\w*|over time\b", lowered)):
        metric = _primary_measure(measures)
        if metric:
            assumptions = assumptions + [f"No measure was named, so '{metric['name']}' was used."]
    metric_name = metric["name"] if metric else None

    if date_column and metric_name and re.search(r"\b(compare|versus|vs|year[- ]over[- ]year|yoy|year[- ]on[- ]year)\b", lowered) and re.search(r"\byears?\b|\byoy\b", lowered):
        match = re.search(r"\blast\s+(two|three|four|five|\d)\s+years\b", lowered)
        periods = 2
        if match:
            periods = NUMBER_WORDS.get(match.group(1)) or int(match.group(1))
        time_grain = "quarter" if "quarter" in lowered else "month"
        return AnalysisPlan(operation="period_comparison", metric_column=metric_name, time_column=date_column, aggregation=aggregation, time_grain=time_grain, periods_to_compare=max(2, min(periods, 5)), filters=filters, assumptions=assumptions)

    if date_column and (grain or re.search(r"\b(trend\w*|over time|seasonal\w*|time series)\b", lowered)) and not (dimension and not grain):
        if metric_name or aggregation == "count":
            return AnalysisPlan(operation="time_series", metric_column=metric_name, time_column=date_column, aggregation=aggregation, time_grain=grain or "month", order=order, filters=filters, assumptions=assumptions)

    if dimension and (metric_name or aggregation == "count"):
        limit = _limit(question)
        return AnalysisPlan(operation="group_aggregate", metric_column=metric_name, group_by=dimension["name"], aggregation=aggregation, order=order, limit=limit, filters=filters, assumptions=assumptions)

    if metric_name and (AVG_WORDS.search(question) or SUM_WORDS.search(question) or MEDIAN_WORDS.search(question) or MAX_WORDS.search(question) or MIN_WORDS.search(question) or re.search(r"\border value\b", lowered)):
        return AnalysisPlan(operation="metric", metric_column=metric_name, aggregation=aggregation, filters=filters, assumptions=assumptions)
    if aggregation == "count":
        return AnalysisPlan(operation="metric", metric_column=None, aggregation="count", filters=filters, assumptions=assumptions)
    if metric_name and RANK_WORDS.search(question):
        return AnalysisPlan(operation="metric", metric_column=metric_name, aggregation="min" if order == "asc" else "max", filters=filters, assumptions=assumptions)

    available = ", ".join(c["name"] for c in schema[:15])
    return AnalysisPlan(
        operation="unsupported",
        reason=f"Demonstration mode could not match this question to columns or a supported calculation. Columns available: {available}. Try naming a column, for example 'total {(_primary_measure(measures) or {'name': 'value'})['name']} by month'.",
    )
