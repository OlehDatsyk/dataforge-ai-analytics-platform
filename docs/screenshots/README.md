# Screenshots

These are genuine captures of the running application at 1440x900, taken automatically by a Playwright test. They use only synthetic demonstration data and a placeholder account (`Demo Analyst`, `@example.com`).

| File | Shows |
|---|---|
| `01-dashboard.png` | Main dashboard |
| `02-dataset-upload.png` | Upload dialog with a dataset preview |
| `03-data-explorer.png` | Data Explorer |
| `04-data-cleaning.png` | Quality findings and a cleaning preview |
| `05-ai-data-analyst.png` | AI Data Analyst in demonstration mode |
| `06-visualisation-studio.png` | Visualisation Studio |
| `07-anomaly-detection.png` | Anomaly Detection |
| `08-reports.png` | A generated report |

## Recapture

Build the front end, then run the capture test from `frontend/`. It starts its own server with a temporary database and overwrites these files.

```bash
npm run build && npx playwright test e2e/screenshots.spec.ts
```

Screenshot 05 shows demonstration mode because no AI provider was configured during capture.
