"""Cleaning operations. They run on a copy of a version; the result is saved as a new version."""
from __future__ import annotations

import re
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .frames import NUMERIC_TYPES, STRING_TYPES, json_safe
from .inference import best_date_format
from .query_engine import ORDERED_OPS, TEXT_OPS, Filter, QueryError, is_date_only

DATA_TYPES = ("integer", "float", "boolean", "date", "category", "text")


class RemoveDuplicates(BaseModel):
    op: Literal["remove_duplicates"]
    columns: list[str] | None = None


class FillMissing(BaseModel):
    op: Literal["fill_missing"]
    column: str
    strategy: Literal["value", "mean", "median", "mode", "forward", "backward"]
    value: str | int | float | bool | None = None


class DropMissing(BaseModel):
    op: Literal["drop_missing"]
    columns: list[str] = Field(min_length=1)
    how: Literal["any", "all"] = "any"


class RenameColumn(BaseModel):
    op: Literal["rename_column"]
    column: str
    new_name: str = Field(min_length=1, max_length=200)


class ChangeType(BaseModel):
    op: Literal["change_type"]
    column: str
    to: Literal["integer", "float", "boolean", "date", "category", "text"]


class TrimWhitespace(BaseModel):
    op: Literal["trim_whitespace"]
    columns: list[str] | None = None


class StandardiseText(BaseModel):
    op: Literal["standardise_text"]
    column: str
    case: Literal["lower", "upper", "title", "keep"] = "keep"
    collapse_spaces: bool = True
    mapping: dict[str, str] | None = None


class FilterRows(BaseModel):
    op: Literal["filter_rows"]
    filters: list[Filter] = Field(min_length=1, max_length=20)
    mode: Literal["keep", "remove"] = "keep"


class DropColumn(BaseModel):
    op: Literal["drop_column"]
    column: str


class DeriveColumn(BaseModel):
    op: Literal["derive_column"]
    name: str = Field(min_length=1, max_length=200)
    left: str
    operator: Literal["add", "subtract", "multiply", "divide"]
    right_column: str | None = None
    right_value: float | None = None


CleaningOp = Annotated[
    RemoveDuplicates | FillMissing | DropMissing | RenameColumn | ChangeType | TrimWhitespace | StandardiseText | FilterRows | DropColumn | DeriveColumn,
    Field(discriminator="op"),
]


def _require(columns: list[dict], name: str) -> dict:
    for column in columns:
        if column["name"] == name:
            return column
    raise QueryError(f"Column '{name}' does not exist in this version.")


def _examples(before: pd.Series, after: pd.Series, column: str, limit: int = 6) -> tuple[list[dict], int]:
    b = before.astype(object).where(before.notna(), None)
    a = after.astype(object).where(after.notna(), None)
    changed = [i for i, (x, y) in enumerate(zip(b.tolist(), a.tolist(), strict=True)) if x != y]
    return [{"row": int(i) + 1, "column": column, "before": json_safe(b.iloc[i]), "after": json_safe(a.iloc[i])} for i in changed[:limit]], len(changed)


def _filter_mask(df: pd.DataFrame, columns: list[dict], item: Filter) -> pd.Series:
    column = _require(columns, item.column)
    series = df[item.column]
    data_type, op = column["type"], item.op
    if op == "is_null":
        return series.isna()
    if op == "not_null":
        return series.notna()
    if op in TEXT_OPS:
        if data_type not in STRING_TYPES:
            raise QueryError(f"The '{op}' filter only applies to text columns.")
        text = series.astype(object).map(lambda v: None if v is None or v != v else str(v).lower())
        needle = str(item.value or "").lower()
        checks = {"contains": lambda v: needle in v, "not_contains": lambda v: needle not in v,
                  "starts_with": lambda v: v.startswith(needle), "ends_with": lambda v: v.endswith(needle)}
        return text.map(lambda v: False if v is None else checks[op](v)).astype(bool)
    if op in ORDERED_OPS and data_type not in NUMERIC_TYPES | {"date"}:
        raise QueryError(f"The '{op}' filter only applies to numbers and dates.")

    def coerce(value):
        if data_type in NUMERIC_TYPES:
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise QueryError(f"'{value}' is not a number.") from exc
        if data_type == "date":
            try:
                return pd.Timestamp(value)
            except ValueError as exc:
                raise QueryError(f"'{value}' is not a valid date.") from exc
        if data_type == "boolean":
            return str(value).lower() in {"true", "yes", "1"}
        return str(value)

    values = pd.to_numeric(series, errors="coerce") if data_type in NUMERIC_TYPES else series
    end_of_day = lambda stamp: stamp + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)  # noqa: E731
    if op == "between":
        if not item.values or len(item.values) != 2:
            raise QueryError("The 'between' filter needs two values.")
        low, high = coerce(item.values[0]), coerce(item.values[1])
        if data_type == "date" and is_date_only(item.values[1]):
            high = end_of_day(high)
        result = (values >= low) & (values <= high)
    elif data_type == "date" and is_date_only(item.value) and op in {"eq", "ne", "gt", "lte"}:
        day = coerce(item.value)
        same_day = values.dt.normalize() == day
        result = {"eq": same_day, "ne": ~same_day, "gt": values > end_of_day(day), "lte": values <= end_of_day(day)}[op]
    elif op == "in":
        result = values.isin([coerce(v) for v in item.values or []])
    else:
        if item.value is None:
            raise QueryError(f"A value is required for the filter on '{item.column}'.")
        target = coerce(item.value)
        comparisons = {"eq": values == target, "ne": values != target}
        if op in comparisons:
            result = comparisons[op]
        else:
            result = {"gt": lambda: values > target, "gte": lambda: values >= target, "lt": lambda: values < target, "lte": lambda: values <= target}[op]()
    # Comparisons with missing values never match, even for "not equal".
    return result.fillna(False).astype(bool) & series.notna()


def _convert(series: pd.Series, to: str) -> tuple[pd.Series, int]:
    """Convert a column. Values that cannot be converted become missing, and the count is returned."""
    present = series.notna()
    if to in {"integer", "float"}:
        if pd.api.types.is_numeric_dtype(series):
            numbers = pd.to_numeric(series, errors="coerce").astype(float)
        else:
            text = series.astype(object).map(lambda v: None if v is None or v != v else re.sub(r"[\s$€£¥,%]", "", str(v)))
            numbers = pd.to_numeric(text, errors="coerce")
        if to == "integer":
            whole = numbers.where(numbers % 1 == 0)
            result = pd.Series([None if v != v else int(v) for v in whole.tolist()], index=series.index, dtype=object)
            return result, int((present & whole.isna()).sum())
        return numbers.astype(float), int((present & numbers.isna()).sum())
    if to == "date":
        if pd.api.types.is_datetime64_any_dtype(series):
            return series, 0
        text = series.astype(object).map(lambda v: None if v is None or v != v else str(v).strip())
        valid = text.dropna()
        fmt, _ = best_date_format(valid) if len(valid) else (None, False)
        parsed = pd.to_datetime(text, format=fmt if fmt else "mixed", errors="coerce")
        return parsed, int((present & parsed.isna()).sum())
    if to == "boolean":
        mapping = {"true": True, "t": True, "yes": True, "y": True, "1": True, "false": False, "f": False, "no": False, "n": False, "0": False}
        result = series.astype(object).map(lambda v: None if v is None or v != v else mapping.get(str(v).strip().lower()))
        return result, int((present & result.isna()).sum())
    # category and text
    if pd.api.types.is_datetime64_any_dtype(series):
        result = series.map(lambda v: None if pd.isna(v) else v.isoformat()).astype(object)
    else:
        result = series.astype(object).map(lambda v: None if v is None or pd.isna(v) else str(v))
    return result, 0


def _fill_value(series: pd.Series, column: dict, op: FillMissing):
    data_type = column["type"]
    if op.strategy == "value":
        if op.value is None:
            raise QueryError("Enter the value to fill missing cells with.")
        converted, failed = _convert(pd.Series([op.value], dtype=object), data_type)
        if failed:
            raise QueryError(f"'{op.value}' is not a valid {data_type} value for '{op.column}'.")
        return converted.iloc[0]
    if op.strategy in {"mean", "median"}:
        if data_type not in NUMERIC_TYPES:
            raise QueryError(f"{op.strategy.title()} can only fill numeric columns; '{op.column}' is {data_type}.")
        numbers = pd.to_numeric(series, errors="coerce").astype(float)
        value = float(numbers.mean() if op.strategy == "mean" else numbers.median())
        if value != value:
            raise QueryError(f"'{op.column}' has no values to calculate a {op.strategy} from.")
        return int(value) if data_type == "integer" and value.is_integer() else value
    modes = series.dropna().mode()
    if modes.empty:
        raise QueryError(f"'{op.column}' has no values to calculate a mode from.")
    return modes.iloc[0]


def _apply_one(df: pd.DataFrame, columns: list[dict], op) -> tuple[pd.DataFrame, list[dict], dict]:
    rows_before = len(df)
    examples: list[dict] = []
    cells = 0
    description = ""
    columns = [dict(c) for c in columns]

    if isinstance(op, RemoveDuplicates):
        for name in op.columns or []:
            _require(columns, name)
        df = df.drop_duplicates(subset=op.columns or None, keep="first").reset_index(drop=True)
        description = f"Removes {rows_before - len(df):,} duplicate rows, keeping the first of each."
    elif isinstance(op, FillMissing):
        column = _require(columns, op.column)
        series = df[op.column]
        before = series.copy()
        if op.strategy == "forward":
            filled = series.ffill()
        elif op.strategy == "backward":
            filled = series.bfill()
        else:
            value = _fill_value(series, column, op)
            filled = series.astype(object).where(series.notna(), value)
            widened = column["type"] == "integer" and isinstance(value, float)
            if column["type"] == "float" or widened:
                filled = pd.to_numeric(filled, errors="coerce").astype(float)
            if widened:
                column["type"] = "float"  # keep the exact fill value rather than rounding it
        df = df.assign(**{op.column: filled})
        examples, cells = _examples(before, filled, op.column)
        description = f"Fills {cells:,} missing values in '{op.column}' using the {op.strategy} strategy."
        if column["type"] == "float" and op.strategy in {"mean", "median"} and not isinstance(before.dtype, pd.Float64Dtype) and pd.api.types.is_integer_dtype(before.dtype):
            description += " The column becomes decimal so that the fill value is not rounded."
    elif isinstance(op, DropMissing):
        for name in op.columns:
            _require(columns, name)
        df = df.dropna(subset=op.columns, how=op.how).reset_index(drop=True)
        description = f"Removes {rows_before - len(df):,} rows with missing values in {', '.join(op.columns)}."
    elif isinstance(op, RenameColumn):
        column = _require(columns, op.column)
        new_name = " ".join(op.new_name.split())
        if not new_name or new_name.startswith("__"):
            raise QueryError("Column names cannot be blank or start with '__'.")
        if any(c["name"].lower() == new_name.lower() and c["name"] != op.column for c in columns):
            raise QueryError(f"A column named '{new_name}' already exists.")
        df = df.rename(columns={op.column: new_name})
        column["name"] = new_name
        description = f"Renames '{op.column}' to '{new_name}'."
    elif isinstance(op, ChangeType):
        column = _require(columns, op.column)
        before = df[op.column]
        converted, failed = _convert(before, op.to)
        df = df.assign(**{op.column: converted})
        description = f"Converts '{op.column}' from {column['type']} to {op.to}."
        column["type"] = op.to
        if failed:
            description += f" {failed:,} values cannot be converted and become missing."
        cells = failed
        examples = [{"row": int(i) + 1, "column": op.column, "before": json_safe(before.iloc[i]), "after": None}
                    for i in np.flatnonzero((before.notna() & converted.isna()).to_numpy())[:6]]
    elif isinstance(op, TrimWhitespace):
        targets = op.columns or [c["name"] for c in columns if c["type"] in STRING_TYPES]
        updates = {}
        for name in targets:
            column = _require(columns, name)
            if column["type"] not in STRING_TYPES:
                raise QueryError(f"'{name}' is not a text column.")
            trimmed = df[name].astype(object).map(lambda v: None if v is None or v != v else " ".join(str(v).split()) or None)
            found, changed = _examples(df[name], trimmed, name)
            cells += changed
            examples.extend(found)
            updates[name] = trimmed
        df = df.assign(**updates)
        examples = examples[:6]
        description = f"Trims whitespace in {cells:,} values across {len(targets)} column(s)."
    elif isinstance(op, StandardiseText):
        column = _require(columns, op.column)
        if column["type"] not in STRING_TYPES:
            raise QueryError(f"'{op.column}' is not a text column.")
        case = {"lower": str.lower, "upper": str.upper, "title": str.title, "keep": lambda s: s}[op.case]
        mapping = op.mapping or {}

        def standardise(value):
            if value is None or value != value:
                return None
            text = " ".join(str(value).split()) if op.collapse_spaces else str(value)
            return mapping.get(text, mapping.get(str(value), case(text)))

        updated = df[op.column].astype(object).map(standardise)
        examples, cells = _examples(df[op.column], updated, op.column)
        df = df.assign(**{op.column: updated})
        description = f"Standardises {cells:,} values in '{op.column}'."
    elif isinstance(op, FilterRows):
        mask = pd.Series(True, index=df.index)
        for item in op.filters:
            mask &= _filter_mask(df, columns, item)
        df = df[mask if op.mode == "keep" else ~mask].reset_index(drop=True)
        description = f"Removes {rows_before - len(df):,} rows, leaving {len(df):,}."
    elif isinstance(op, DropColumn):
        _require(columns, op.column)
        if len(columns) == 1:
            raise QueryError("A dataset must keep at least one column.")
        df = df.drop(columns=[op.column])
        columns = [c for c in columns if c["name"] != op.column]
        description = f"Removes the column '{op.column}'."
    elif isinstance(op, DeriveColumn):
        name = " ".join(op.name.split())
        if not name or name.startswith("__") or any(c["name"].lower() == name.lower() for c in columns):
            raise QueryError(f"'{op.name}' cannot be used as a new column name.")
        left = _require(columns, op.left)
        if left["type"] not in NUMERIC_TYPES:
            raise QueryError(f"'{op.left}' must be numeric to derive a column.")
        a = pd.to_numeric(df[op.left], errors="coerce").astype(float)
        if op.right_column:
            right = _require(columns, op.right_column)
            if right["type"] not in NUMERIC_TYPES:
                raise QueryError(f"'{op.right_column}' must be numeric to derive a column.")
            b = pd.to_numeric(df[op.right_column], errors="coerce").astype(float)
        elif op.right_value is not None:
            b = pd.Series(float(op.right_value), index=df.index)
        else:
            raise QueryError("Choose a second column or enter a constant.")
        if op.operator == "divide":
            result = a / b.where(b != 0)
        else:
            result = {"add": a + b, "subtract": a - b, "multiply": a * b}[op.operator]
        df = df.assign(**{name: result})
        columns.append({"name": name, "type": "float"})
        cells = int(result.notna().sum())
        right_text = op.right_column or op.right_value
        description = f"Adds '{name}' = {op.left} {op.operator} {right_text}."
        if op.operator == "divide" and (b == 0).any():
            description += " Division by zero produces missing values."
    return df, columns, {
        "op": op.op,
        "description": description,
        "rows_before": rows_before,
        "rows_after": len(df),
        "rows_removed": rows_before - len(df),
        "cells_changed": cells,
        "examples": examples,
    }


def apply_operations(df: pd.DataFrame, columns: list[dict], operations: list) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    result = df.copy()
    current = [dict(c) for c in columns]
    effects = []
    for op in operations:
        result, current, effect = _apply_one(result, current, op)
        effects.append(effect)
    if result.empty:
        raise QueryError("These operations would remove every row. Adjust them before continuing.")
    return result, current, effects
