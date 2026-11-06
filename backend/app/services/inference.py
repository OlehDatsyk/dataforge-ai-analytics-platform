"""Column type inference.

Inference is deliberately strict: a column is converted only when every non-missing value parses,
so conversion never destroys information. Mostly-numeric or mostly-date columns stay as text and
are reported by the data quality checks, where the user can decide how to convert them.
"""
from __future__ import annotations

import pandas as pd

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "#n/a", "#null!"}
TRUE_TOKENS = {"true", "t", "yes", "y"}
FALSE_TOKENS = {"false", "f", "no", "n"}
NUMBER_RE = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
THOUSANDS_RE = r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"
INT64_LIMIT = 2**63 - 1

# ISO formats first. Day-first and month-first are both tried, and any ambiguity is reported.
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m",
]
AMBIGUOUS_PAIRS = {"%m/%d/%Y": "%d/%m/%Y", "%m/%d/%Y %H:%M": "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S": "%d/%m/%Y %H:%M:%S", "%m-%d-%Y": "%d-%m-%Y"}


def normalise_missing(series: pd.Series) -> pd.Series:
    """Replace recognised missing-value tokens with None. Whitespace elsewhere is left untouched."""

    def convert(value):
        if value is None or (isinstance(value, float) and value != value):
            return None
        text = str(value)
        return None if text.strip().lower() in NULL_TOKENS else text

    return pd.Series([convert(v) for v in series.tolist()], index=series.index, dtype=object)


def parse_numbers(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse text into numbers. Returns (numbers, is_valid); identifiers with leading zeros stay invalid."""
    text = values.astype(object).map(lambda v: str(v).strip())
    plain = text.str.fullmatch(NUMBER_RE)
    grouped = text.str.fullmatch(THOUSANDS_RE)
    leading_zero = text.str.fullmatch(r"[+-]?0\d+(?:\.\d*)?")
    valid = (plain | grouped) & ~leading_zero
    numbers = pd.to_numeric(text.where(valid).str.replace(",", "", regex=False), errors="coerce")
    return numbers, valid & numbers.notna()


def best_date_format(values: pd.Series) -> tuple[str | None, bool]:
    """Find a single format matching every value. Returns (format, is_ambiguous)."""
    text = values.astype(object).map(lambda v: str(v).strip())
    sample = text.head(200)
    for fmt in DATE_FORMATS:
        if pd.to_datetime(sample, format=fmt, errors="coerce").notna().all():
            if pd.to_datetime(text, format=fmt, errors="coerce").notna().all():
                alternate = AMBIGUOUS_PAIRS.get(fmt)
                ambiguous = bool(alternate) and bool(pd.to_datetime(text, format=alternate, errors="coerce").notna().all())
                return fmt, ambiguous
    return None, False


def parse_iso_with_zone(values: pd.Series) -> pd.Series | None:
    """Parse ISO-8601 timestamps carrying time zones, normalised to naive UTC."""
    text = values.astype(object).map(lambda v: str(v).strip())
    if not text.head(200).str.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}.*").all():
        return None
    parsed = pd.to_datetime(text, format="ISO8601", errors="coerce", utc=True)
    return parsed.dt.tz_localize(None) if parsed.notna().all() else None


def infer_column(series: pd.Series, name: str) -> tuple[str, pd.Series, list[str]]:
    """Infer the type of a text-valued column. Returns (type, typed values, notes)."""
    values = normalise_missing(series)
    present = values.dropna()
    notes: list[str] = []
    if present.empty:
        return "text", values, notes

    lowered = present.map(lambda v: v.strip().lower())
    tokens = set(lowered.unique()[:6])
    if lowered.nunique() <= 2 and tokens <= (TRUE_TOKENS | FALSE_TOKENS) and tokens & {"true", "false", "yes", "no"}:
        mapped = values.map(lambda v: None if v is None else v.strip().lower() in TRUE_TOKENS)
        return "boolean", mapped, notes

    numbers, valid = parse_numbers(present)
    if valid.all():
        if ((numbers % 1 == 0).all() and present.map(lambda v: "." not in v and "e" not in v.lower()).all()
                and numbers.abs().max() <= INT64_LIMIT):
            as_int = present.map(lambda v: int(v.strip().replace(",", "")))
            result = pd.Series([None] * len(values), index=values.index, dtype=object)
            result.loc[present.index] = as_int
            return "integer", result, notes
        result = pd.Series(float("nan"), index=values.index, dtype=float)
        result.loc[present.index] = numbers.astype(float)
        return "float", result, notes

    if not present.map(lambda v: v[:1].strip().isalpha() and len(v) > 40).any():
        fmt, ambiguous = best_date_format(present)
        parsed = None
        if fmt:
            parsed = pd.to_datetime(present.map(str.strip), format=fmt, errors="coerce")
            if ambiguous:
                notes.append(f"Column '{name}': dates could be month-first or day-first; month-first was assumed.")
        else:
            parsed = parse_iso_with_zone(present)
        if parsed is not None:
            result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[us]")
            result.loc[present.index] = parsed.astype("datetime64[us]")
            return "date", result, notes

    unique = present.nunique()
    total = len(present)
    average_length = present.map(len).mean()
    if unique <= 50 and unique < total or (unique / total <= 0.2 and unique <= 1000 and average_length <= 60):
        return "category", values, notes
    return "text", values, notes


def infer_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], list[str]]:
    data: dict[str, pd.Series] = {}
    columns: list[dict] = []
    notes: list[str] = []
    for name in frame.columns:
        data_type, typed, column_notes = infer_column(frame[name], name)
        data[name] = typed
        columns.append({"name": name, "type": data_type})
        notes.extend(column_notes)
    return pd.DataFrame(data, index=frame.index), columns, notes
