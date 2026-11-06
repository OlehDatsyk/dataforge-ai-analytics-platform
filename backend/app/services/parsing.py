"""Safe file validation and parsing. Uploaded content is only ever read as data.

Macros are rejected, formulas are never evaluated, and all parsers run under row and size limits.
"""
from __future__ import annotations

import codecs
import csv
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pandas as pd
import xlrd

from ..config import get_settings

ALLOWED_EXTENSIONS = {".csv": "csv", ".tsv": "csv", ".xlsx": "xlsx", ".xls": "xls", ".json": "json"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"
BINARY_SIGNATURES = (b"MZ", b"%PDF", b"\x7fELF", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"\x1f\x8b", b"Rar!", b"7z\xbc\xaf")
MAX_ZIP_ENTRIES = 20_000
MAX_ZIP_RATIO = 250
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
RESERVED_COLUMN = "__row_id"


class IngestError(Exception):
    """A problem with the uploaded file. The message is safe to show to the user."""


@dataclass
class ParsedFile:
    frame: pd.DataFrame  # every value is a string or None at this stage
    notes: list[str] = field(default_factory=list)


def detect_format(path: Path, filename: str) -> str:
    """Identify the format from file content and require it to agree with the extension."""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise IngestError(f"Unsupported file type '{extension or 'none'}'. Supported types: CSV, TSV, XLSX, XLS, JSON.")
    declared = ALLOWED_EXTENSIONS[extension]
    size = path.stat().st_size
    if size == 0:
        raise IngestError("The file is empty.")
    with path.open("rb") as handle:
        head = handle.read(65536)

    if head.startswith(ZIP_MAGIC):
        actual = "xlsx"
    elif head.startswith(OLE_MAGIC):
        actual = "xls"
    elif head.startswith(BINARY_SIGNATURES):
        raise IngestError("The file content is binary and does not match a supported data format.")
    else:
        bom = head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
        if b"\x00" in head and not bom:
            raise IngestError("The file contains binary data and cannot be read as text.")
        actual = "text"

    if declared in {"xlsx", "xls"} and actual != declared:
        raise IngestError(f"The file has a .{declared} extension, but its content is not a valid {declared.upper()} workbook.")
    if declared in {"csv", "json"} and actual != "text":
        raise IngestError(f"The file has a {extension} extension, but its content is a binary workbook or archive.")
    return declared


def parse_file(path: Path, file_format: str) -> ParsedFile:
    if file_format == "csv":
        parsed = _parse_csv(path)
    elif file_format == "xlsx":
        parsed = _parse_xlsx(path)
    elif file_format == "xls":
        parsed = _parse_xls(path)
    elif file_format == "json":
        parsed = _parse_json(path)
    else:  # pragma: no cover - guarded by detect_format
        raise IngestError("Unsupported format.")
    parsed.frame = _normalise_columns(parsed.frame, parsed.notes)
    _check_limits(parsed.frame)
    return parsed


def _check_limits(frame: pd.DataFrame) -> None:
    settings = get_settings()
    if frame.shape[1] == 0:
        raise IngestError("No columns were found in the file.")
    if frame.shape[1] > settings.max_columns:
        raise IngestError(f"The file has {frame.shape[1]} columns; the limit is {settings.max_columns}.")
    if frame.shape[0] == 0:
        raise IngestError("The file has a header but no data rows.")
    if frame.shape[0] > settings.max_rows:
        raise IngestError(f"The file exceeds the limit of {settings.max_rows:,} rows.")


def _normalise_columns(frame: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    names: list[str] = []
    seen: dict[str, int] = {}
    renamed = 0
    for position, raw in enumerate(frame.columns, start=1):
        text = "" if raw is None else str(raw)
        name = " ".join(text.split())[:200]
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{position}"
            renamed += 1
        if name == RESERVED_COLUMN:
            name = "row_id_original"
            renamed += 1
        key = name.lower()
        if key in seen:
            seen[key] += 1
            name = f"{name}_{seen[key]}"
            renamed += 1
        else:
            seen[key] = 1
        names.append(name)
    if renamed:
        notes.append(f"{renamed} blank, duplicate, or reserved column name(s) were renamed.")
    frame = frame.copy()
    frame.columns = names
    return frame


def _detect_encoding(path: Path) -> str:
    with path.open("rb") as handle:
        head = handle.read(4)
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for encoding in ("utf-8", "cp1252"):
        decoder = codecs.getincrementaldecoder(encoding)()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    raise IngestError("The file's text encoding is not supported. Save it as UTF-8 and upload it again.")


def _parse_csv(path: Path) -> ParsedFile:
    encoding = _detect_encoding(path)
    notes = [] if encoding in {"utf-8", "utf-8-sig"} else [f"Text encoding detected as {encoding}."]
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(65536)
    if not sample.strip():
        raise IngestError("The file contains no data.")
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = "," if "," in sample else "\t" if "\t" in sample else ";" if ";" in sample else ","
    settings = get_settings()
    _check_field_counts(path, encoding, delimiter, settings.max_rows + 1)
    try:
        frame = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            dtype=object,
            keep_default_na=False,
            na_filter=False,
            nrows=settings.max_rows + 1,
            on_bad_lines="error",
            skip_blank_lines=True,
            index_col=False,  # never let an extra field silently become a row index
        )
    except pd.errors.EmptyDataError as exc:
        raise IngestError("The file contains no data.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise IngestError(f"The file structure is invalid: rows have inconsistent column counts. {_short(exc)}") from exc
    return ParsedFile(frame, notes)


def _check_field_counts(path: Path, encoding: str, delimiter: str, max_rows: int) -> None:
    """Reject rows with more fields than the header, because their data could not be placed correctly."""
    csv.field_size_limit(16 * 1024 * 1024)
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next((row for row in reader if row), None)
            if header is None:
                return
            for count, row in enumerate(reader, start=1):
                if count > max_rows:
                    return
                if len(row) > len(header) and any(cell.strip() for cell in row[len(header) :]):
                    raise IngestError(
                        f"The file structure is invalid: rows have inconsistent column counts. "
                        f"Line {reader.line_num} has {len(row)} fields, but the header has {len(header)}."
                    )
        except csv.Error as exc:
            raise IngestError(f"The file structure is invalid and could not be read as CSV (line {reader.line_num}).") from exc


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return text[:160]


def _cell_to_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    return str(value)


def _rows_to_frame(rows: list[list]) -> pd.DataFrame:
    header_index = next((i for i, row in enumerate(rows) if any(c not in (None, "") for c in row)), None)
    if header_index is None:
        raise IngestError("The worksheet contains no data.")
    header = rows[header_index]
    width = max(i + 1 for row in rows for i, c in enumerate(row) if c not in (None, ""))
    header = (list(header) + [None] * width)[:width]
    body = [(list(row) + [None] * width)[:width] for row in rows[header_index + 1 :] if any(c not in (None, "") for c in row)]
    return pd.DataFrame([[_cell_to_text(c) for c in row] for row in body], columns=[_cell_to_text(h) for h in header], dtype=object)


def _validate_xlsx_container(path: Path) -> None:
    settings = get_settings()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = {i.filename for i in infos}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise IngestError("The file is a ZIP archive, but not a valid XLSX workbook.")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise IngestError("Workbooks containing macros are not accepted. Save it as a macro-free .xlsx file.")
            total = sum(i.file_size for i in infos)
            compressed = sum(i.compress_size for i in infos) or 1
            if len(infos) > MAX_ZIP_ENTRIES or total > MAX_UNCOMPRESSED_BYTES or (
                total / compressed > MAX_ZIP_RATIO and total > settings.max_upload_bytes
            ):
                raise IngestError("The workbook expands to an unsafe size and was rejected.")
    except zipfile.BadZipFile as exc:
        raise IngestError("The XLSX file is corrupted or not a valid workbook.") from exc


def _parse_xlsx(path: Path) -> ParsedFile:
    _validate_xlsx_container(path)
    settings = get_settings()
    notes = ["Excel formulas were not evaluated; only values saved in the workbook were read."]
    try:
        # data_only reads cached results. read_only streams rows instead of loading the whole file.
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        raise IngestError("The XLSX file could not be read. It may be corrupted or password protected.") from exc
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets):
            rows: list[list] = []
            for row in sheet.iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) > settings.max_rows + 2:
                    raise IngestError(f"The worksheet exceeds the limit of {settings.max_rows:,} rows.")
            if any(c not in (None, "") for row in rows for c in row):
                if len(workbook.worksheets) > 1:
                    notes.append(
                        f"The workbook has {len(workbook.worksheets)} sheets; only sheet "
                        f"'{workbook.sheetnames[sheet_index]}' was imported."
                    )
                return ParsedFile(_rows_to_frame(rows), notes)
    finally:
        workbook.close()
    raise IngestError("The workbook contains no data.")


def _parse_xls(path: Path) -> ParsedFile:
    settings = get_settings()
    # A VBA project stream name is stored in UTF-16 in the OLE directory.
    with path.open("rb") as handle:
        if "_VBA_PROJECT".encode("utf-16-le") in handle.read():
            raise IngestError("Workbooks containing macros are not accepted. Save it as a macro-free file.")
    try:
        book = xlrd.open_workbook(str(path), on_demand=True, formatting_info=False)
    except xlrd.XLRDError as exc:
        raise IngestError("The XLS file is corrupted or not a valid workbook.") from exc
    notes = ["Excel formulas were not evaluated; only values saved in the workbook were read."]
    try:
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            if sheet.nrows == 0:
                continue
            if sheet.nrows > settings.max_rows + 1:
                raise IngestError(f"The worksheet exceeds the limit of {settings.max_rows:,} rows.")
            rows = []
            for r in range(sheet.nrows):
                row = []
                for cell in sheet.row(r):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        row.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        row.append(bool(cell.value))
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        row.append(None)
                    else:
                        row.append(cell.value)
                rows.append(row)
            if book.nsheets > 1:
                notes.append(f"The workbook has {book.nsheets} sheets; only sheet '{sheet.name}' was imported.")
            return ParsedFile(_rows_to_frame(rows), notes)
    finally:
        book.release_resources()
    raise IngestError("The workbook contains no data.")


def _json_records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "records", "rows"):
            if isinstance(payload.get(key), list):
                return payload[key]
        lists = [v for v in payload.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
        return [payload]
    raise IngestError("The JSON file must contain an array of objects.")


def records_to_frame(records: list) -> ParsedFile:
    """Flatten JSON records into a text-valued frame. Shared by file uploads and REST imports."""
    settings = get_settings()
    if not records:
        raise IngestError("The JSON data contains no records.")
    if not all(isinstance(r, dict) for r in records):
        raise IngestError("Each JSON record must be an object with named fields.")
    if len(records) > settings.max_rows:
        raise IngestError(f"The data exceeds the limit of {settings.max_rows:,} rows.")
    frame = pd.json_normalize(records, sep=".", max_level=3)

    def to_text(value):
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        if value is None or (isinstance(value, float) and value != value):
            return None
        return _cell_to_text(value)

    data = {column: [to_text(v) for v in frame[column].tolist()] for column in frame.columns}
    return ParsedFile(pd.DataFrame(data, dtype=object))


def _parse_json(path: Path) -> ParsedFile:
    encoding = _detect_encoding(path)
    text = path.read_text(encoding=encoding)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:  # newline-delimited JSON
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise IngestError("The file is not valid JSON.") from exc
    except RecursionError as exc:
        raise IngestError("The JSON file is too deeply nested.") from exc
    return records_to_frame(_json_records(payload))
