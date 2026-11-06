# Data visualisation

Every plotted value comes from a server-side DuckDB query. The browser receives only the aggregated values it draws, so charts stay fast on large datasets. Calculation lives in `backend/app/services/charts.py`, and drawing in `frontend/src/components/ChartView.tsx`.

## Chart types

| Type | X axis | Y axis | Notes |
|---|---|---|---|
| Bar | Any field | Numeric, or Count | Optional grouping. Date fields are grouped by period. |
| Line, Area | Date or numeric | Numeric, or Count | Categories are refused, because a line would imply an order they don't have. |
| Pie, Donut | Categorical | Numeric, or Count | Sum and Count only, no grouping, no negative values. Five slices plus "Other". |
| Scatter | Numeric | Numeric | Optional grouping. Shows an evenly spaced sample of up to 2,000 points, and says so. |
| Histogram | Numeric | Count | 3 to 100 bins |
| Box plot | Optional category | Numeric | Five-number summary, with Tukey whiskers and a count of values beyond them. Up to 12 groups. |

## Configuration

Dataset, chart type, X and Y fields, group, aggregation (sum, average, count, minimum, maximum, median), filters, time grouping (automatic, day, week, month, quarter, year), sort, maximum X values, bins, title, and axis labels.

`validate_spec` rejects incompatible choices with a specific message, such as asking for an average of a text column. The chart updates shortly after each change.

## Automatic time grouping

Date spans up to 62 days use days, up to 180 days use weeks, up to 6 years use months, and longer spans use years.

## Limits and notes

To keep charts honest, anything left out is mentioned beneath the chart:

- Up to 6 groups appear, the largest by value, and the others are excluded with a note.
- Rows with a missing X value are left out. Missing group values appear as `(missing)`.
- Charts show only the first X values up to the configured maximum.

## Colour

The six series colours were checked with a palette validator on the `#111B2B` chart surface for lightness, contrast, and colour-blind separation. Their order is deliberate: `#3B82F6`, `#D97706`, `#0891B2`, `#DB2777`, `#8B5CF6`, `#059669`. A legend appears whenever there are two or more series, so identity never relies on colour alone.

## Interaction and export

- **Tooltips** show exact values.
- **Range selection:** bar charts over 40 points and line or area charts over 36 points get a brush for zooming into part of the axis.
- **Saving:** charts are stored as specifications, not values, so they recalculate from the active version when reopened.
- **PNG export** draws the chart in the browser with its title.
- **CSV export** downloads the plotted values, with formula protection.

## Recommendations

`recommend_charts` suggests charts from column types and cardinality, and each suggestion is validated. With a live AI provider, the model may only rank these candidates and rewrite their reasons, seeing column names and types but no values. The panel states whether suggestions are rule-based or AI-ranked.

The analyst also attaches an engine-calculated chart to suitable answers.
