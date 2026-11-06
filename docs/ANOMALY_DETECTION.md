# Anomaly detection

> Statistical anomalies are unusual values relative to the rest of the data. They are not automatically errors or evidence of fraud, and they need review in context.

The code is in `backend/app/services/anomaly.py`. A scan picks methods for each column instead of applying every technique.

## Methods

### Numeric outliers

Columns that look like identifiers (such as `customer_id`) are skipped. A column needs at least 30 values and more than 3 distinct values. The method depends on the column's shape, measured with quartile skewness, because a single extreme value can't distort that measure:

| Condition | Method | Flagged when |
|---|---|---|
| Skewed (absolute quartile skewness above 0.2) | IQR with 3x far-out fences | Outside Q1 − 3xIQR or Q3 + 3xIQR |
| Roughly symmetric | Modified Z-score (median absolute deviation) | Score above 3.5 |
| Most values identical (zero spread in the median deviation) | IQR, if the IQR is above zero | As above |
| Almost all values identical | Z-score | More than 4 standard deviations |

Findings are ranked, and the 100 most significant per column are stored. The methods panel shows both the number flagged and the number listed.

| Method | Medium severity from | High severity from |
|---|---|---|
| IQR (distance beyond the fence, in IQRs) | 1 | 3 |
| Modified Z-score | 5 | 8 |
| Z-score | 6 | 9 |

### Sudden changes over time

When the dataset has a date column, numeric values are aggregated per period: days for spans up to 120 days, weeks up to two years, and months beyond that. At least 12 complete periods are needed. Each period is compared with the rolling median of the periods before it (14 days, 8 weeks, or 6 months), scaled by a robust measure of typical deviation, and flagged above 3.5.

Totals are used by default. Columns whose names suggest rates or averages (such as `price`, `rate`, or `score`) use the mean instead. Up to 5 numeric columns are checked, and partial first or last periods are excluded, so an incomplete month doesn't look like a sudden drop.

### Frequency changes

The same comparison applied to the number of records per period. This finds gaps and bursts in data arrival.

### Missing-data patterns

For columns where 0.5% to 90% of values are missing, the missing rate per period is compared with the overall rate using a binomial test. A period is flagged when it has at least 10 records, a score above 4, and at least twice the overall rate. This suggests a collection or pipeline problem during that time.

### Unusual categorical distributions

For category columns with 3 to 100 distinct values and at least 100 records, a value is flagged when it covers under 1% of records and under a tenth of a typical category's share. This often reveals typing variations.

## Results

Each finding records the record or period, column, observed value, expected range or baseline, method, score, severity, explanation, and review status (open, investigating, expected, or resolved). Results can be filtered by column, method, severity, status, and period.

**Inspect** opens the original records behind a finding: the row itself, all rows in the period, or the rows with the rare value or missing field. Findings refer to the version that was scanned.

Charts show a distribution with values outside the expected range highlighted, or a time series with its baseline and flagged points.

## Assumptions and limitations

- **Seasonality isn't modelled.** Regular peaks, such as a December rise, can be flagged. The explanation for time findings mentions this.
- **Each column is judged alone.** A combination of values can be unusual even when each value is normal, and this won't be detected.
- **Fixed thresholds.** They suit general use, not every domain. An unusual value may be important or trivial.
- **Isolation Forest and other machine-learning methods aren't implemented.** The chosen methods are explainable and need no training, and they cover the types of anomaly above.
- **A whole version loads into memory** for each scan. In measurements, 1,000,000 rows took about 1.1 seconds on the development laptop.

## Validation

Tests check that:

- planted outliers are found with the correct bounds, and clean data produces no false alarms;
- skewed data selects IQR, and symmetric data selects the modified Z-score;
- a planted spike is found in the right period, and frequency gaps and missing-data windows are detected;
- a partial final month doesn't create a false drop;
- identifiers are skipped, and small or constant columns are skipped with a reason.
