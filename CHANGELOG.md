# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## [0.9.0] - Unreleased

First pre-release.

### Added

- MIT licence.
- Upload and validation for CSV, TSV, XLSX, XLS, and JSON, with background processing.
- Type inference, column profiling, and data quality checks.
- Data Explorer with server-side pagination, sorting, search, filters, column selection, and CSV export.
- Non-destructive cleaning with previews, versions, restore, and history.
- Visualisation Studio with eight chart types, saved charts, recommendations, and PNG and CSV export.
- Grounded AI Data Analyst with a provider abstraction, number checking, conversation history, and demonstration mode.
- Anomaly detection with per-column method selection, record inspection, and review status.
- Six report types with PDF, CSV, and XLSX export.
- PostgreSQL and REST API imports with encrypted credentials and SSRF protection.
- Accounts, workspaces, roles, projects, notifications, global search, and an audit log.
- Five synthetic demonstration datasets.
- Automated back-end, front-end, end-to-end, and PostgreSQL tests.
- Windows, macOS, and Linux scripts, and documentation.

### Known gaps

- Live AI providers have been tested with simulated responses only.
- macOS and Linux scripts, Docker Compose, and the CI workflow have not been run.
