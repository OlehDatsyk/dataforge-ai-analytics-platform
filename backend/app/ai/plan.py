"""The structured analytical plan: the only thing a planner, AI or rule-based, can ask the engine to do."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..services.charts import is_measure
from ..services.frames import NUMERIC_TYPES, STRING_TYPES
from ..services.query_engine import Filter, build_where, column_map

Operation = Literal[
    "metric", "group_aggregate", "time_series", "period_comparison", "dataset_summary", "distribution", "correlation", "anomaly_scan", "chart_recommendation", "unsupported"
]
Aggregation = Literal["sum", "avg", "count", "min", "max", "median"]


class AnalysisPlan(BaseModel):
    operation: Operation
    metric_column: str | None = None
    secondary_column: str | None = None
    aggregation: Aggregation = "sum"
    group_by: str | None = None
    time_column: str | None = None
    time_grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    order: Literal["desc", "asc"] = "desc"
    limit: int = Field(default=10, ge=1, le=50)
    periods_to_compare: int = Field(default=2, ge=2, le=5)
    reason: str | None = Field(default=None, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class PlanError(ValueError):
    """The plan cannot run against this dataset. The message explains why, for the user."""


def validate_plan(plan: AnalysisPlan, schema: list[dict]) -> None:
    columns = column_map(schema)

    def column(name: str | None, role: str) -> dict | None:
        if name is None:
            return None
        if name not in columns:
            raise PlanError(f"The {role} column '{name}' does not exist in this dataset.")
        return columns[name]

    metric = column(plan.metric_column, "metric")
    secondary = column(plan.secondary_column, "comparison")
    group = column(plan.group_by, "grouping")
    time = column(plan.time_column, "time")
    # Executes filter validation without running a query.
    build_where(plan.filters, schema)

    op = plan.operation
    if op in {"metric", "group_aggregate", "time_series", "period_comparison"} and plan.aggregation != "count":
        if metric is None:
            raise PlanError("This analysis needs a numeric column to measure.")
        if metric["type"] not in NUMERIC_TYPES:
            raise PlanError(f"'{metric['name']}' is {metric['type']}, so a {plan.aggregation} cannot be calculated for it.")
    if op == "group_aggregate":
        if group is None:
            raise PlanError("This analysis needs a column to group by.")
        if group["type"] not in STRING_TYPES | {"boolean", "integer"}:
            raise PlanError(f"'{group['name']}' cannot be used for grouping because it is {group['type']}.")
    if op in {"time_series", "period_comparison"} and (time is None or time["type"] != "date"):
        raise PlanError("This analysis needs a date column, and none was identified.")
    if op == "distribution" and (metric is None or metric["type"] not in NUMERIC_TYPES):
        raise PlanError("A distribution can only be calculated for a numeric column.")
    if op == "correlation":
        if metric is None or metric["type"] not in NUMERIC_TYPES:
            raise PlanError("A correlation needs numeric columns.")
        if secondary is not None and secondary["type"] not in NUMERIC_TYPES:
            raise PlanError(f"'{secondary['name']}' is not numeric, so a correlation cannot be calculated.")


def measures(schema: list[dict]) -> list[dict]:
    return [c for c in schema if is_measure(c)]


# A JSON schema written for strict structured output: every property required, no extras.
PLAN_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operation", "metric_column", "secondary_column", "aggregation", "group_by", "time_column", "time_grain", "filters", "order", "limit", "periods_to_compare", "reason", "assumptions"],
    "properties": {
        "operation": {"type": "string", "enum": list(Operation.__args__)},
        "metric_column": {"type": ["string", "null"]},
        "secondary_column": {"type": ["string", "null"]},
        "aggregation": {"type": "string", "enum": list(Aggregation.__args__)},
        "group_by": {"type": ["string", "null"]},
        "time_column": {"type": ["string", "null"]},
        "time_grain": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["column", "op", "value", "values"],
                "properties": {
                    "column": {"type": "string"},
                    "op": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "contains", "not_contains", "starts_with", "ends_with", "is_null", "not_null"]},
                    "value": {"type": ["string", "number", "null"]},
                    "values": {"anyOf": [{"type": "array", "items": {"type": ["string", "number"]}}, {"type": "null"}]},
                },
            },
        },
        "order": {"type": "string", "enum": ["desc", "asc"]},
        "limit": {"type": "integer"},
        "periods_to_compare": {"type": "integer"},
        "reason": {"type": ["string", "null"]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

NARRATIVE_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["direct_answer", "key_findings", "interpretation", "follow_ups", "limitations"],
    "properties": {
        "direct_answer": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "interpretation": {"type": "string"},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}
