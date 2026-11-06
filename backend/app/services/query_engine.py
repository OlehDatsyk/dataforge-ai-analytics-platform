"""DuckDB query layer over Parquet.

All SQL is assembled by this module. Column names must exist in the version's schema and are quoted;
every value is passed as a bound parameter. Neither users nor AI models can supply SQL text.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from .frames import NUMERIC_TYPES, ROW_ID, STRING_TYPES, json_safe

FilterOp = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "contains", "not_contains", "starts_with", "ends_with", "is_null", "not_null"
]
DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")
ORDERED_OPS = {"gt", "gte", "lt", "lte", "between"}
TEXT_OPS = {"contains", "not_contains", "starts_with", "ends_with"}
SQL_OPERATORS = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
OP_LABELS = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "between": "between", "in": "in", "contains": "contains",
             "not_contains": "does not contain", "starts_with": "starts with", "ends_with": "ends with", "is_null": "is missing", "not_null": "is not missing"}


class QueryError(HTTPException):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(status_code=status_code, detail=message)


class Filter(BaseModel):
    column: str = Field(max_length=255)
    op: FilterOp
    value: str | int | float | bool | None = None
    values: list[str | int | float | bool] | None = Field(default=None, max_length=500)


class Sort(BaseModel):
    column: str = Field(max_length=255)
    direction: Literal["asc", "desc"] = "asc"


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@contextmanager
def connect(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open an isolated in-memory connection limited to one Parquet file and locked down afterwards."""
    settings = get_settings()
    con = duckdb.connect(":memory:", config={"threads": 2, "memory_limit": settings.query_memory_limit})
    try:
        literal = str(path).replace("'", "''")
        con.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{literal}')")
        con.execute(f"SET allowed_paths=['{literal}']")
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
        yield con
    finally:
        con.close()


def run_query(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]:
    """Execute with a wall-clock limit. A query past the limit is interrupted."""
    timer = threading.Timer(get_settings().query_timeout_seconds, con.interrupt)
    timer.start()
    try:
        cursor = con.execute(sql, params or [])
        names = [d[0] for d in cursor.description]
        return names, cursor.fetchall()
    except duckdb.InterruptException as exc:
        raise QueryError("The query exceeded the time limit. Add filters or reduce its scope.", 408) from exc
    except duckdb.OutOfMemoryException as exc:
        raise QueryError("The query needs more memory than is allowed. Add filters or reduce its scope.", 413) from exc
    finally:
        timer.cancel()


def column_map(schema: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in schema}


def require_column(schema_map: dict[str, dict], name: str) -> dict:
    column = schema_map.get(name)
    if column is None:
        raise QueryError(f"Column '{name}' does not exist in this dataset.")
    return column


def _coerce(value, column: dict):
    data_type = column["type"]
    name = column["name"]
    if value is None:
        raise QueryError(f"A value is required for the filter on '{name}'.")
    if data_type in NUMERIC_TYPES:
        if isinstance(value, bool):
            raise QueryError(f"'{name}' is numeric; the filter value must be a number.")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise QueryError(f"'{name}' is numeric; '{value}' is not a number.") from exc
    if data_type == "date":
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise QueryError(f"'{name}' is a date; '{value}' is not a valid ISO date (YYYY-MM-DD).") from exc
    if data_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
        raise QueryError(f"'{name}' is true/false; '{value}' is not valid.")
    return str(value)


def is_date_only(value) -> bool:
    """A value such as 2024-03-31 means the whole day when compared with a timestamp."""
    return isinstance(value, str) and bool(DATE_ONLY.fullmatch(value.strip()))


def end_of_day(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=999999)


def build_where(filters: list[Filter], schema: list[dict], search: str | None = None) -> tuple[str, list]:
    schema_map = column_map(schema)
    clauses: list[str] = []
    params: list = []
    for item in filters:
        column = require_column(schema_map, item.column)
        name, data_type = quote(column["name"]), column["type"]
        op = item.op
        if op == "is_null":
            clauses.append(f"{name} IS NULL")
        elif op == "not_null":
            clauses.append(f"{name} IS NOT NULL")
        elif op in TEXT_OPS:
            if data_type not in STRING_TYPES:
                raise QueryError(f"The '{op}' filter only applies to text columns; '{column['name']}' is {data_type}.")
            pattern = like_escape(str(item.value if item.value is not None else ""))
            if not pattern:
                raise QueryError(f"A value is required for the filter on '{column['name']}'.")
            prefix = "" if op == "starts_with" else "%"
            suffix = "" if op == "ends_with" else "%"
            negate = "NOT " if op == "not_contains" else ""
            clauses.append(f"{name} {negate}ILIKE ? ESCAPE '\\'")
            params.append(f"{prefix}{pattern}{suffix}")
        elif op in ORDERED_OPS and data_type not in NUMERIC_TYPES | {"date"}:
            raise QueryError(f"The '{op}' filter only applies to numbers and dates; '{column['name']}' is {data_type}.")
        elif op == "between":
            bounds = item.values or []
            if len(bounds) != 2:
                raise QueryError(f"The 'between' filter on '{column['name']}' needs two values.")
            clauses.append(f"{name} BETWEEN ? AND ?")
            low, high = (_coerce(v, column) for v in bounds)
            if data_type == "date" and is_date_only(bounds[1]):
                high = end_of_day(high)
            params.extend([low, high])
        elif op == "in":
            options = item.values or []
            if not options:
                raise QueryError(f"The 'in' filter on '{column['name']}' needs at least one value.")
            clauses.append(f"{name} IN ({', '.join('?' for _ in options)})")
            params.extend(_coerce(v, column) for v in options)
        elif data_type == "date" and is_date_only(item.value) and op in {"eq", "ne"}:
            clauses.append(f"CAST({name} AS DATE) {SQL_OPERATORS[op]} ?")
            params.append(_coerce(item.value, column).date())
        elif data_type == "date" and is_date_only(item.value) and op in {"gt", "lte"}:
            clauses.append(f"{name} {SQL_OPERATORS[op]} ?")
            params.append(end_of_day(_coerce(item.value, column)))
        else:
            clauses.append(f"{name} {SQL_OPERATORS[op]} ?")
            params.append(_coerce(item.value, column))
    if search and search.strip():
        searchable = [c for c in schema if c["type"] in STRING_TYPES]
        if searchable:
            pattern = f"%{like_escape(search.strip())}%"
            clauses.append("(" + " OR ".join(f"{quote(c['name'])} ILIKE ? ESCAPE '\\'" for c in searchable) + ")")
            params.extend([pattern] * len(searchable))
        else:
            clauses.append("FALSE")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def describe_filters(filters: list[Filter]) -> list[str]:
    result = []
    for f in filters:
        value = "" if f.op in {"is_null", "not_null"} else " " + (" and ".join(map(str, f.values or [])) if f.op == "between" else ", ".join(map(str, f.values or [])) if f.op == "in" else str(f.value))
        result.append(f"{f.column} {OP_LABELS[f.op]}{value}")
    return result


def fetch_rows(
    path: Path,
    schema: list[dict],
    *,
    page: int = 1,
    page_size: int = 50,
    sort: list[Sort] | None = None,
    filters: list[Filter] | None = None,
    search: str | None = None,
    columns: list[str] | None = None,
) -> dict:
    """Return one page of rows. Page size is capped, so the browser never receives a whole dataset."""
    settings = get_settings()
    page_size = max(1, min(page_size, settings.max_page_size))
    page = max(1, page)
    schema_map = column_map(schema)
    selected = columns or [c["name"] for c in schema]
    for name in selected:
        require_column(schema_map, name)
    where, params = build_where(filters or [], schema, search)
    order_parts = [f"{quote(require_column(schema_map, s.column)['name'])} {s.direction.upper()} NULLS LAST" for s in sort or []]
    order_parts.append(quote(ROW_ID))
    select_list = ", ".join([quote(ROW_ID)] + [quote(n) for n in selected])
    with connect(path) as con:
        _, count = run_query(con, f"SELECT COUNT(*) FROM data{where}", params)
        total = int(count[0][0])
        names, rows = run_query(
            con,
            f"SELECT {select_list} FROM data{where} ORDER BY {', '.join(order_parts)} LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        )
    return {
        "columns": selected,
        "rows": [dict(zip(names, map(json_safe, row), strict=True)) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": (total + page_size - 1) // page_size if total else 0,
    }
