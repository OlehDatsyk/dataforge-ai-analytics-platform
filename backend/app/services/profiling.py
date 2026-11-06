"""Column statistics and data quality checks. Each type receives only the statistics that make sense for it."""
from __future__ import annotations

import pandas as pd

from .frames import NUMERIC_TYPES, STRING_TYPES, json_safe
from .inference import best_date_format, parse_numbers

HISTOGRAM_BINS = 12


def _text_values(series: pd.Series) -> pd.Series:
    return series.dropna().astype(object).map(str)


def _top_values(series: pd.Series, limit: int) -> list[dict]:
    counts = series.value_counts(dropna=True).head(limit)
    total = int(series.notna().sum()) or 1
    return [{"value": json_safe(k), "count": int(v), "share": round(int(v) / total, 4)} for k, v in counts.items()]


def _numeric_stats(series: pd.Series) -> dict:
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if values.empty:
        return {}
    q1, median, q3 = values.quantile([0.25, 0.5, 0.75]).tolist()
    counts, edges = _histogram(values)
    return {
        "mean": json_safe(values.mean()),
        "median": json_safe(median),
        "min": json_safe(values.min()),
        "max": json_safe(values.max()),
        "std": json_safe(values.std()) if len(values) > 1 else None,  # sample standard deviation
        "q1": json_safe(q1),
        "q3": json_safe(q3),
        "skewness": json_safe(values.skew()) if len(values) > 2 else None,
        "zero_count": int((values == 0).sum()),
        "negative_count": int((values < 0).sum()),
        "histogram": [
            {"start": json_safe(edges[i]), "end": json_safe(edges[i + 1]), "count": int(counts[i])}
            for i in range(len(counts))
        ],
    }


def _histogram(values: pd.Series):
    import numpy as np

    return np.histogram(values.to_numpy(), bins=HISTOGRAM_BINS if values.nunique() > 1 else 1)


def _date_frequency(values: pd.Series) -> str | None:
    unique = values.drop_duplicates().sort_values()
    if len(unique) < 3:
        return None
    days = unique.diff().dropna().dt.total_seconds().median() / 86400
    for label, low, high in (
        ("sub-daily", 0, 0.99),
        ("daily", 0.99, 1.5),
        ("weekly", 6, 8),
        ("monthly", 27, 32),
        ("quarterly", 85, 95),
        ("yearly", 360, 370),
    ):
        if low <= days < high:
            return label
    return "irregular"


def profile_column(series: pd.Series, name: str, data_type: str) -> dict:
    total = len(series)
    missing = int(series.isna().sum())
    non_null = series.dropna()
    result: dict = {
        "name": name,
        "type": data_type,
        "count": int(total - missing),
        "missing": missing,
        "missing_pct": round(missing / total * 100, 2) if total else 0,
        "unique": int(non_null.nunique()),
    }
    if non_null.empty:
        return result
    if data_type in NUMERIC_TYPES:
        result.update(_numeric_stats(non_null))
    elif data_type == "date":
        values = pd.to_datetime(non_null)
        earliest, latest = values.min(), values.max()
        result.update(
            earliest=earliest.isoformat(),
            latest=latest.isoformat(),
            range_days=int((latest - earliest).days),
            frequency=_date_frequency(values),
        )
    elif data_type == "boolean":
        result.update(true_count=int((non_null == True).sum()), false_count=int((non_null == False).sum()))  # noqa: E712
    elif data_type == "category":
        result["top_values"] = _top_values(non_null, 15)
    else:
        text = _text_values(non_null)
        lengths = text.map(len)
        result.update(
            empty_count=int((text.str.strip() == "").sum()),
            average_length=round(float(lengths.mean()), 2),
            min_length=int(lengths.min()),
            max_length=int(lengths.max()),
            top_values=_top_values(text, 5),
        )
    return result


def build_profile(df: pd.DataFrame, columns: list[dict]) -> dict:
    duplicate_rows = int(df.duplicated().sum()) if len(df.columns) else 0
    missing_cells = int(df.isna().sum().sum())
    total_cells = int(df.shape[0] * df.shape[1])
    return {
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "duplicate_rows": duplicate_rows,
        "missing_cells": missing_cells,
        "total_cells": total_cells,
        "missing_pct": round(missing_cells / total_cells * 100, 2) if total_cells else 0,
        "columns": [profile_column(df[c["name"]], c["name"], c["type"]) for c in columns],
    }


def _issue(check: str, severity: str, title: str, detail: str, *, column: str | None = None, count: int = 0, fix: dict | None = None) -> dict:
    return {
        "id": f"{check}:{column or 'dataset'}",
        "check": check,
        "severity": severity,
        "title": title,
        "detail": detail,
        "column": column,
        "count": count,
        "suggested_fix": fix,
    }


def _category_variants(values: pd.Series) -> list[list[str]]:
    """Find values that differ only by case or spacing, such as 'UK', 'uk' and ' UK '."""
    uniques = pd.Series(values.dropna().astype(object).map(str).unique())
    if uniques.empty or len(uniques) > 5000:
        return []
    keys = uniques.map(lambda v: " ".join(v.split()).casefold())
    return [sorted(group.tolist()) for _, group in uniques.groupby(keys) if len(group) > 1]


def quality_checks(df: pd.DataFrame, columns: list[dict]) -> dict:
    """Run the data quality checks. Findings describe the data; nothing is changed here."""
    issues: list[dict] = []
    rows = len(df)
    duplicates = int(df.duplicated().sum())
    if duplicates:
        issues.append(
            _issue("duplicates", "warning", "Duplicate rows", f"{duplicates:,} rows repeat an earlier row exactly.",
                   count=duplicates, fix={"op": "remove_duplicates"})
        )
    for column in columns:
        name, data_type = column["name"], column["type"]
        series = df[name]
        missing = int(series.isna().sum())
        if missing == rows and rows:
            issues.append(_issue("empty_column", "warning", "Empty column", f"'{name}' has no values.", column=name,
                                 count=rows, fix={"op": "drop_column", "column": name}))
            continue
        if missing:
            share = missing / rows
            severity = "critical" if share >= 0.5 else "warning" if share >= 0.05 else "info"
            strategy = "median" if data_type in NUMERIC_TYPES else "mode" if data_type in {"category", "boolean"} else None
            fix = {"op": "fill_missing", "column": name, "strategy": strategy} if strategy else {"op": "drop_missing", "columns": [name]}
            issues.append(_issue("missing_values", severity, "Missing values",
                                 f"'{name}' is missing {missing:,} values ({share:.1%}).", column=name, count=missing, fix=fix))
        if data_type in NUMERIC_TYPES:
            values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
            if len(values) >= 20 and values.nunique() > 3:
                q1, q3 = values.quantile([0.25, 0.75])
                iqr = q3 - q1
                if iqr > 0:
                    outliers = int(((values < q1 - 3 * iqr) | (values > q3 + 3 * iqr)).sum())
                    if outliers:
                        issues.append(_issue("outliers", "info", "Potential outliers",
                                             f"'{name}' has {outliers:,} values beyond 3 x IQR from the quartiles. "
                                             "These may be valid; review them in Anomaly Detection.", column=name, count=outliers))
        if data_type in STRING_TYPES:
            text = _text_values(series)
            if text.empty:
                continue
            padded = int((text != text.str.strip()).sum())
            if padded:
                issues.append(_issue("whitespace", "warning", "Extra whitespace",
                                     f"'{name}' has {padded:,} values with leading or trailing spaces.", column=name, count=padded,
                                     fix={"op": "trim_whitespace", "columns": [name]}))
            variants = _category_variants(text)
            if variants:
                example = ", ".join(repr(v) for v in variants[0][:3])
                affected = int(text.isin([v for group in variants for v in group]).sum())
                issues.append(_issue("inconsistent_categories", "warning", "Inconsistent categories",
                                     f"'{name}' has {len(variants)} value group(s) differing only by case or spacing, e.g. {example}.",
                                     column=name, count=affected, fix={"op": "standardise_text", "column": name, "case": "title"}))
            _numeric, valid = parse_numbers(text)
            symbols = text.str.fullmatch(r"\s*[-+]?[$€£¥]\s*[\d,]+(\.\d+)?\s*|\s*[-+]?[\d,]+(\.\d+)?\s*%\s*")
            share_numeric = float(valid.mean())
            if symbols.any() and float((valid | symbols).mean()) >= 0.8:
                count = int(symbols.sum())
                issues.append(_issue("formatting", "warning", "Formatted numbers stored as text",
                                     f"'{name}' stores {count:,} numbers with currency or percent symbols, so it cannot be aggregated.",
                                     column=name, count=count, fix={"op": "change_type", "column": name, "to": "float"}))
            elif 0.5 <= share_numeric < 1 and text.nunique() > 3:
                bad = int((~valid).sum())
                issues.append(_issue("inconsistent_types", "warning", "Inconsistent data types",
                                     f"'{name}' is mostly numeric ({share_numeric:.1%}), but {bad:,} values are not numbers.",
                                     column=name, count=bad, fix={"op": "change_type", "column": name, "to": "float"}))
            elif share_numeric < 0.5:
                _add_date_issue(issues, text, name)
    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order[i["severity"]], -i["count"]))
    penalty = sum({"critical": 15, "warning": 5, "info": 1}[i["severity"]] for i in issues)
    return {"score": max(0, 100 - penalty), "issue_count": len(issues), "issues": issues}


def _add_date_issue(issues: list[dict], text: pd.Series, name: str) -> None:
    """Flag text columns where most values look like dates but some cannot be parsed."""
    looks_like_date = text.str.fullmatch(r"\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}.*")
    share = float(looks_like_date.mean())
    if share < 0.5:
        return
    fmt, _ = best_date_format(text[looks_like_date].head(5000))
    if fmt:
        valid = pd.to_datetime(text.map(str.strip), format=fmt, errors="coerce").notna()
    else:
        valid = pd.to_datetime(text.map(str.strip), errors="coerce", format="mixed").notna()
    bad = int((~valid).sum())
    if bad:
        issues.append(_issue("invalid_dates", "warning", "Invalid date values",
                             f"'{name}' looks like a date column, but {bad:,} values cannot be read as dates.",
                             column=name, count=bad, fix={"op": "change_type", "column": name, "to": "date"}))
