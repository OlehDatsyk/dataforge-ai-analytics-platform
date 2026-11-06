"""Statistical anomaly detection. The method is chosen per column from its data type and shape.

A flagged value is statistically unusual. It is not, by itself, an error or evidence of fraud.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .charts import is_measure
from .frames import STRING_TYPES, json_safe

MIN_NUMERIC_VALUES = 30
MIN_PERIODS = 12
MAX_RECORDS_PER_COLUMN = 100
MAX_TIME_COLUMNS = 5
MAX_SERIES_POINTS = 400
MODIFIED_Z_THRESHOLD = 3.5
IQR_FAR_OUT = 3.0
SKEW_THRESHOLD = 0.2
AVERAGE_HINTS = ("rate", "ratio", "pct", "percent", "avg", "average", "price", "score", "margin", "duration", "per_", "age")
DISCLAIMER = (
    "Statistical anomalies are unusual values relative to the rest of the data. "
    "They are not automatically errors or evidence of fraud, and need review in context."
)


def _severity(score: float, medium: float, high: float) -> str:
    return "high" if score >= high else "medium" if score >= medium else "low"


def _fmt(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1e15 else f"{value:.3g}"


def choose_numeric_method(values: pd.Series) -> tuple[str | None, str]:
    """Pick an outlier method for one numeric column and explain why."""
    if values.nunique() <= 3:
        return None, "Too few distinct values for outlier analysis."
    median = float(values.median())
    mad = float((values - median).abs().median())
    q1, q3 = values.quantile([0.25, 0.75])
    iqr = float(q3 - q1)
    # Quartile skewness is used because, unlike moment skewness, a single extreme value cannot inflate it.
    skew = (float(q3) + float(q1) - 2 * median) / iqr if iqr > 0 else 0.0
    if abs(skew) > SKEW_THRESHOLD and iqr > 0:
        return "IQR (3x far-out fences)", f"Skewness (quartile-based) is {skew:.2f}, so quartile fences are more reliable than a symmetric assumption."
    if mad > 0:
        return "Modified Z-score (MAD)", f"Skewness (quartile-based) is {skew:.2f}, so the distribution is roughly symmetric and a median-based score fits."
    if iqr > 0:
        return "IQR (3x far-out fences)", "Most values are identical, so the median deviation is zero and quartile fences are used."
    return "Z-score", "Most values are identical, so only the standard deviation can measure distance."


def detect_numeric(frame: pd.DataFrame, name: str) -> tuple[list[dict], dict | None, str | None]:
    series = pd.to_numeric(frame[name], errors="coerce").astype(float)
    values = series.dropna()
    if len(values) < MIN_NUMERIC_VALUES:
        return [], None, f"'{name}': skipped; at least {MIN_NUMERIC_VALUES} values are needed, found {len(values)}."
    method, reason = choose_numeric_method(values)
    if method is None:
        return [], None, f"'{name}': skipped; {reason.lower()}"
    median = float(values.median())
    if method.startswith("IQR"):
        q1, q3 = (float(v) for v in values.quantile([0.25, 0.75]))
        iqr = q3 - q1
        low, high = q1 - IQR_FAR_OUT * iqr, q3 + IQR_FAR_OUT * iqr
        distance = np.where(values < low, low - values, np.where(values > high, values - high, 0.0))
        score = pd.Series(distance / iqr, index=values.index)
        flagged = score[score > 0]
        grade = lambda s: _severity(s, 1, 3)  # noqa: E731
        scale_text = "times the interquartile range beyond the fence"
    elif method.startswith("Modified"):
        mad = float((values - median).abs().median())
        scale = mad / 0.6745
        low, high = median - MODIFIED_Z_THRESHOLD * scale, median + MODIFIED_Z_THRESHOLD * scale
        score = ((values - median) / scale).abs()
        flagged = score[score > MODIFIED_Z_THRESHOLD]
        grade = lambda s: _severity(s, 5, 8)  # noqa: E731
        scale_text = "robust standard deviations from the median"
    else:
        mean, std = float(values.mean()), float(values.std())
        if std == 0:
            return [], None, f"'{name}': skipped; all values are identical."
        low, high = mean - 4 * std, mean + 4 * std
        score = ((values - mean) / std).abs()
        flagged = score[score > 4]
        grade = lambda s: _severity(s, 6, 9)  # noqa: E731
        scale_text = "standard deviations from the mean"
    results = []
    for index in flagged.sort_values(ascending=False).index[:MAX_RECORDS_PER_COLUMN]:
        observed = float(values.loc[index])
        s = float(score.loc[index])
        results.append(
            {
                "row_id": int(frame.loc[index, "__row_id"]),
                "period": None,
                "column_name": name,
                "kind": "outlier",
                "method": method,
                "observed": _fmt(observed),
                "observed_value": observed,
                "expected_low": low,
                "expected_high": high,
                "baseline": median,
                "score": round(s, 3),
                "severity": grade(s),
                "explanation": f"Value {_fmt(observed)} is outside the expected range {_fmt(low)} to {_fmt(high)} ({s:.1f} {scale_text}). The column median is {_fmt(median)}.",
            }
        )
    info = {"column": name, "method": method, "reason": reason, "flagged": int(len(flagged)), "listed": len(results),
            "expected_low": low, "expected_high": high, "values_checked": int(len(values))}
    return results, info, None


def _choose_grain(span_days: int) -> str:
    if span_days <= 120:
        return "D"
    if span_days <= 730:
        return "W"
    return "M"


GRAIN_NAMES = {"D": "day", "W": "week", "M": "month"}
GRAIN_FORMAT = {"D": "%Y-%m-%d", "W": "%Y-%m-%d", "M": "%Y-%m"}


def _periods(dates: pd.Series, grain: str) -> pd.Series:
    return dates.dt.to_period("W-SUN" if grain == "W" else grain).dt.start_time


def _complete_period_filter(index: pd.DatetimeIndex, dates: pd.Series, grain: str) -> pd.DatetimeIndex:
    """Exclude a partial first or last period, which would look like a false drop in the data."""
    freq = "W-SUN" if grain == "W" else grain
    first, last = dates.min(), dates.max()
    keep = index
    if first.normalize() > first.to_period(freq).start_time.normalize() and len(keep):
        keep = keep[keep != first.to_period(freq).start_time]
    if last.normalize() < last.to_period(freq).end_time.normalize() and len(keep):
        keep = keep[keep != last.to_period(freq).start_time]
    return keep


def rolling_deviation(series: pd.Series, window: int) -> pd.DataFrame:
    """Compare each period with the median of the periods before it, scaled by a robust residual spread."""
    baseline = series.rolling(window, min_periods=max(3, window // 2)).median().shift(1)
    residual = series - baseline
    mad = float((residual - residual.median()).abs().median()) * 1.4826
    floor = max(mad, 0.02 * abs(float(series.median())), 1e-9)
    return pd.DataFrame({"value": series, "baseline": baseline, "score": (residual / floor), "band": floor * MODIFIED_Z_THRESHOLD})


def _series_points(result: pd.DataFrame, grain: str) -> list[dict]:
    tail = result.tail(MAX_SERIES_POINTS)
    return [
        {
            "period": i.strftime(GRAIN_FORMAT[grain]),
            "value": json_safe(r.value),
            "baseline": json_safe(r.baseline),
            "low": json_safe(r.baseline - r.band) if r.baseline == r.baseline else None,
            "high": json_safe(r.baseline + r.band) if r.baseline == r.baseline else None,
            "flagged": bool(abs(r.score) > MODIFIED_Z_THRESHOLD) if r.score == r.score else False,
        }
        for i, r in tail.iterrows()
    ]


def _time_results(result: pd.DataFrame, grain: str, column: str, kind: str, method: str, unit: str) -> list[dict]:
    items = []
    flagged = result[result["score"].abs() > MODIFIED_Z_THRESHOLD]
    for period, row in flagged.iterrows():
        score = abs(float(row["score"]))
        direction = "above" if row["score"] > 0 else "below"
        label = period.strftime(GRAIN_FORMAT[grain])
        items.append(
            {
                "row_id": None,
                "period": label,
                "column_name": column,
                "kind": kind,
                "method": method,
                "observed": _fmt(float(row["value"])),
                "observed_value": float(row["value"]),
                "expected_low": float(row["baseline"] - row["band"]),
                "expected_high": float(row["baseline"] + row["band"]),
                "baseline": float(row["baseline"]),
                "score": round(score, 3),
                "severity": _severity(score, 5, 8),
                "explanation": f"{unit} for the {GRAIN_NAMES[grain]} of {label} was {_fmt(float(row['value']))}, {direction} the recent baseline of {_fmt(float(row['baseline']))} (deviation score {score:.1f}). Seasonal patterns can also cause this.",
            }
        )
    return items


def detect_categories(frame: pd.DataFrame, name: str) -> list[dict]:
    values = frame[name].dropna().astype(object).map(str)
    counts = values.value_counts()
    if not 3 <= len(counts) <= 100 or len(values) < 100:
        return []
    shares = counts / len(values)
    median_share = float(shares.median())
    results = []
    for category, share in shares.items():
        if share < 0.01 and share * 10 < median_share:
            ratio = median_share / float(share)
            results.append(
                {
                    "row_id": None,
                    "period": None,
                    "column_name": name,
                    "kind": "rare_category",
                    "method": "Rare category share",
                    "observed": f"{category[:120]} ({int(counts[category]):,} rows)",
                    "observed_value": float(counts[category]),
                    "expected_low": None,
                    "expected_high": None,
                    "baseline": median_share * len(values),
                    "score": round(ratio, 3),
                    "severity": _severity(ratio, 25, 100),
                    "explanation": f"'{category[:120]}' covers {share:.2%} of rows; a typical category in this column covers {median_share:.1%}. It may be a rare but valid value, or a typing variation.",
                }
            )
    return results[:25]


def detect_missing_patterns(frame: pd.DataFrame, name: str, date_column: str, periods: pd.Series, keep: pd.DatetimeIndex, grain: str) -> list[dict]:
    missing = frame[name].isna()
    overall = float(missing.mean())
    if not 0.005 <= overall <= 0.9:
        return []
    grouped = missing.groupby(periods).agg(["mean", "count"])
    grouped = grouped[grouped.index.isin(keep) & (grouped["count"] >= 10)]
    if grouped.empty:
        return []
    results = []
    deviation = (grouped["mean"] - overall) / np.sqrt(overall * (1 - overall) / grouped["count"])
    for period, row in grouped.iterrows():
        z = float(deviation.loc[period])
        if z > 4 and row["mean"] >= 2 * overall:
            label = period.strftime(GRAIN_FORMAT[grain])
            results.append(
                {
                    "row_id": None,
                    "period": label,
                    "column_name": name,
                    "kind": "missing_pattern",
                    "method": "Missing-rate binomial test",
                    "observed": f"{row['mean']:.1%} missing",
                    "observed_value": float(row["mean"]),
                    "expected_low": None,
                    "expected_high": float(overall),
                    "baseline": float(overall),
                    "score": round(z, 3),
                    "severity": _severity(z, 6, 10),
                    "explanation": f"'{name}' was missing in {row['mean']:.1%} of records in the {GRAIN_NAMES[grain]} of {label}; the overall rate is {overall:.1%}. Missing values cluster in this period, which can indicate a collection or pipeline issue.",
                }
            )
    return results[:25]


def run_detection(frame: pd.DataFrame, schema: list[dict], *, columns: list[str] | None = None) -> dict:
    """Run suitable methods for each column. `frame` must include the __row_id column."""
    selected = [c for c in schema if not columns or c["name"] in columns]
    findings: list[dict] = []
    methods: list[dict] = []
    skipped: list[str] = []
    series_data: dict[str, dict] = {}

    measures = [c for c in selected if is_measure(c)]
    for column in measures:
        results, info, skip = detect_numeric(frame, column["name"])
        findings.extend(results)
        if info:
            methods.append(info)
        if skip:
            skipped.append(skip)

    for column in selected:
        if column["type"] in STRING_TYPES and column["type"] == "category":
            found = detect_categories(frame, column["name"])
            findings.extend(found)
            if found:
                methods.append({"column": column["name"], "method": "Rare category share", "reason": "Categorical column: compares each category's share with a typical category.", "flagged": len(found), "listed": len(found)})

    date_columns = [c for c in schema if c["type"] == "date"]
    date_column = None
    if date_columns:
        date_column = max(date_columns, key=lambda c: frame[c["name"]].notna().sum())["name"]
    if date_column:
        dates = pd.to_datetime(frame[date_column], errors="coerce")
        valid_dates = dates.dropna()
        span = int((valid_dates.max() - valid_dates.min()).days) if len(valid_dates) else 0
        grain = _choose_grain(span)
        periods = _periods(dates, grain)
        # Rows without a date are not assigned to any period.
        index = pd.DatetimeIndex(sorted(periods.dropna().unique()))
        keep = _complete_period_filter(index, valid_dates, grain)
        if len(keep) < MIN_PERIODS:
            skipped.append(f"Time-based checks skipped: '{date_column}' covers {len(keep)} complete {GRAIN_NAMES[grain]}s; at least {MIN_PERIODS} are needed.")
        else:
            window = {"D": 14, "W": 8, "M": 6}[grain]
            reindex = pd.date_range(keep.min(), keep.max(), freq="D" if grain == "D" else ("W-MON" if grain == "W" else "MS"))
            if not columns or date_column in columns or any(c["name"] in columns for c in measures):
                counts = frame.groupby(periods).size().reindex(reindex, fill_value=0).astype(float)
                result = rolling_deviation(counts, window)
                method = f"Rolling median baseline ({window} {GRAIN_NAMES[grain]}s)"
                findings.extend(_time_results(result, grain, date_column, "frequency_change", method, "Record count"))
                series_data[f"frequency:{date_column}"] = {"column": date_column, "kind": "frequency_change", "label": "Record count", "points": _series_points(result, grain)}
                methods.append({"column": date_column, "method": method, "reason": f"Date column: compares the record count per {GRAIN_NAMES[grain]} with recent history.",
                                "flagged": int((result['score'].abs() > MODIFIED_Z_THRESHOLD).sum()), "listed": None})
            for column in measures[:MAX_TIME_COLUMNS]:
                name = column["name"]
                average = any(h in name.lower() for h in AVERAGE_HINTS)
                values = pd.to_numeric(frame[name], errors="coerce").astype(float)
                grouped = values.groupby(periods)
                aggregated = (grouped.mean() if average else grouped.sum(min_count=1)).reindex(reindex)
                if aggregated.notna().sum() < MIN_PERIODS:
                    continue
                result = rolling_deviation(aggregated.astype(float), window)
                label = f"{'Average' if average else 'Total'} {name}"
                method = f"Rolling median baseline ({window} {GRAIN_NAMES[grain]}s)"
                findings.extend(_time_results(result.dropna(subset=["value"]), grain, name, "time_change", method, label))
                series_data[f"time:{name}"] = {"column": name, "kind": "time_change", "label": label, "points": _series_points(result, grain)}
                methods.append({"column": name, "method": method, "reason": f"{label} per {GRAIN_NAMES[grain]} is compared with the median of the preceding periods.",
                                "flagged": int((result['score'].abs() > MODIFIED_Z_THRESHOLD).sum()), "listed": None})
            for column in selected:
                if column["name"] != date_column:
                    findings.extend(detect_missing_patterns(frame, column["name"], date_column, periods, keep, grain))
    else:
        skipped.append("Time-based checks skipped: this dataset has no date column.")

    counts = {"high": 0, "medium": 0, "low": 0}
    for item in findings:
        counts[item["severity"]] += 1
    return {
        "findings": findings,
        "summary": {
            "total": len(findings),
            "by_severity": counts,
            "methods": methods,
            "skipped": skipped,
            "series": series_data,
            "date_column": date_column,
            "rows_checked": int(len(frame)),
            "disclaimer": DISCLAIMER,
        },
    }
