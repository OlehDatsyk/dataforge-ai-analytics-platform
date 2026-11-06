"""Tabular exports. Text cells are neutralised so spreadsheets cannot run them as formulas."""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator

from openpyxl import Workbook

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "|", "%")
PLAIN_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?")


def safe_cell(value):
    """Prefix risky text with an apostrophe (OWASP guidance). Real numbers are left unchanged."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES) and not PLAIN_NUMBER.fullmatch(value):
        return "'" + value
    return value


def csv_stream(columns: list[str], rows: Iterable[dict]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([safe_cell(c) for c in columns])
    for index, row in enumerate(rows, start=1):
        writer.writerow([safe_cell(row.get(c)) for c in columns])
        if index % 1000 == 0:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue()


def tables_to_csv(tables: list[dict]) -> str:
    """Write several titled tables into one CSV file."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for table in tables:
        writer.writerow([safe_cell(table["title"])])
        writer.writerow([safe_cell(c) for c in table["columns"]])
        for row in table["rows"]:
            writer.writerow([safe_cell(row.get(c)) for c in table["columns"]])
        writer.writerow([])
    return buffer.getvalue()


def tables_to_xlsx(tables: list[dict]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    for index, table in enumerate(tables, start=1):
        base = re.sub(r"[\[\]:*?/\\']", " ", table["title"]).strip()[:26] or f"Table {index}"
        title = base if base.lower() not in used else f"{base[:22]} {index}"
        used.add(title.lower())
        sheet = workbook.create_sheet(title)
        sheet.append([str(c) for c in table["columns"]])
        for row_number, row in enumerate(table["rows"], start=2):
            for column_number, column in enumerate(table["columns"], start=1):
                value = safe_cell(row.get(column))
                cell = sheet.cell(row=row_number, column=column_number, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"  # never let openpyxl store text as a formula
    if not workbook.worksheets:
        workbook.create_sheet("Report")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
