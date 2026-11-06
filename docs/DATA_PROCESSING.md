# Data processing

## Engine choice

The platform uses two engines, each where it fits best:

- **DuckDB over Parquet** runs every interactive query: rows, filters, charts, and analyst calculations. It reads compressed columnar files efficiently without loading them into Python, so query memory stays bounded. Each query gets its own in-memory connection, limited to one file.
- **pandas and NumPy** handle parsing, type inference, profiling, cleaning, and anomaly detection, where row-by-row logic and statistics are simpler to write and test. This work loads a whole version into memory, which is why row limits exist.

Polars was not needed. Measured on the development laptop:

| Rows | CSV size | Total ingest | Sorted, filtered page | Grouped time chart | Anomaly scan |
|---|---|---|---|---|---|
| 100,000 | 5 MB | 2.2 s | 0.08 s | 0.07 s | 0.18 s |
| 1,000,000 | 55 MB | 21 s | 0.18 s | 0.22 s | 1.1 s |

These figures come from one synthetic table with 8 columns. Real results vary with the data and hardware.

## Ingestion pipeline

Upload validation happens during the request, so bad files fail immediately. The rest runs on background workers, and the dataset's `status`, `stage`, and `progress` fields report what is happening.

1. **Size limits:** the middleware checks the declared size, and the upload handler counts the bytes it receives.
2. **Format detection:** `services/parsing.py` reads the file signature and requires it to agree with the extension. Executables, PDFs, images, and archives are refused, however they are named.
3. **Storage:** the untouched original goes to `data/workspaces/<workspace>/datasets/<dataset>/original/`, under a generated name.
4. **Parsing:** to a table in which every value is still text.
5. **Column names:** blank, duplicate, and reserved names are made safe, with a note recorded.
6. **Type inference:** see below.
7. **Profiling and quality checks:** statistics and findings for the version.
8. **Saving:** a Parquet file, plus version, column, and profile records.

### Parsers

| Format | Details |
|---|---|
| CSV, TSV | Detects UTF-8, UTF-16, and Windows-1252, and the `,` `;` tab or `\|` delimiter. Rows with extra non-empty fields are rejected rather than misaligned. |
| XLSX | Checks the archive first: required parts, entry count, expanded size, and compression ratio. Reads in streaming mode with cached values only, so formulas are never evaluated. defusedxml guards against malicious XML. Macro workbooks are rejected. |
| XLS | Uses xlrd, which doesn't run code. Files containing a VBA project are rejected. |
| JSON | An array of objects, an object wrapping one such array (such as `{"data": [...]}`), or newline-delimited JSON. Nested objects flatten to dotted names, and arrays are kept as JSON text. |

Only the first non-empty worksheet is imported, and a note says so.

### Type inference

Inference is strict, because wrong conversions silently damage data. `NA`, `N/A`, `null`, `none`, `nan`, `#N/A`, `#NULL!`, and empty values count as missing. Then:

| Type | Rule |
|---|---|
| boolean | Only true/false, yes/no, or t/f tokens (with at least one full word) |
| integer | Every value is a whole number within the 64-bit range |
| float | Every value is numeric, including thousands separators such as `1,234.50` |
| date | Every value matches one format, or is ISO-8601 with a time zone (normalised to UTC) |
| category | Repeating labels: up to 50 distinct values, or up to 1,000 when they are at most 20% of the values |
| text | Everything else |

Consequences worth knowing:

- **A single bad value keeps a column as text.** The quality checks report it, and you decide how to convert it.
- **Codes with leading zeros, such as `007`, stay as text,** so they aren't changed.
- **Ambiguous dates, such as `01/02/2024`, are read as month-first,** and a note on the dataset says so.

## Profiling

`services/profiling.py` calculates only the statistics that suit each type:

| Type | Statistics |
|---|---|
| Numeric | Count, mean, median, minimum, maximum, sample standard deviation, quartiles (linear interpolation), skewness, zero and negative counts, histogram |
| Category | Unique values, top values with share, missing count |
| Date | Earliest, latest, range in days, typical frequency |
| Text | Empty values, average, minimum, and maximum length, most common values |
| Boolean | True and false counts |

The test suite compares these with independent NumPy and pandas calculations on the synthetic retail data.

## Data quality checks

Duplicate rows, missing values, empty columns, potential outliers (beyond 3x IQR), extra whitespace, inconsistent categories (differences only in case or spacing), numbers stored with currency or percent symbols, mostly numeric columns with non-numeric values, and mostly date columns with invalid dates.

The score starts at 100 and subtracts 15, 5, or 1 for each critical, warning, or informational issue. It helps with triage and is not a formal standard.

## Cleaning and versions

`services/cleaning.py` supports:

| Operation | Effect |
|---|---|
| Remove duplicates | Keeps the first copy |
| Fill missing | Mean, median, most common value, a set value, previous row, or next row |
| Remove rows with missing values | For chosen columns |
| Rename column | Rejects name clashes and reserved names |
| Change type | Removes currency symbols, commas, and percent signs for numbers. Values that can't convert become missing, and the count is shown first. |
| Trim whitespace | One or all text columns |
| Standardise text | Case, spacing, and value mapping |
| Filter rows | Keep or remove rows matching conditions |
| Remove column | Refuses to remove the last column |
| Derive column | Add, subtract, multiply, or divide numeric columns or a constant. Dividing by zero gives a missing value. |

The workflow is designed to be safe:

1. **Preview** calculates the effect on all rows, with before-and-after examples, and saves nothing.
2. **Apply** writes a **new** Parquet version, or a new dataset, with the operations recorded in `cleaning_operations`.
3. **Earlier versions stay unchanged**, and any version can be viewed or restored. The original upload is never touched.

Filling an integer column with a non-whole mean turns it into a decimal column, so the fill value isn't silently rounded.

## Deletion

Deleting a dataset removes its database records by cascade (versions, profiles, charts, scans, reports, and conversations), then its folder. Deleting a data connection leaves the datasets already imported from it.
