# Draft release: v0.9.0

**Recommended tag:** `v0.9.0`, marked as a **pre-release** on GitHub.

**Why not v1.0.0:** the core application is tested, but live AI has been verified only with simulated responses, the macOS and Linux scripts and Docker and CI configuration haven't been run, and there has been no independent security review or production deployment. A reasonable bar for v1.0.0 is closing those gaps.

---

**Title:** DataForge AI v0.9.0: first pre-release

**Description:**

DataForge AI is a data analytics platform for exploring datasets, detecting anomalies, building charts, asking questions in plain English, and generating reports. A data engine calculates every figure, and AI only plans the calculation and explains its result.

### Features

- Upload CSV, TSV, XLSX, XLS, and JSON files, with content-based validation and background processing
- Explore records with server-side pagination, sorting, and filters, with statistics suited to each column
- Check data quality and clean data, with previews and restorable versions
- Build eight chart types, then save and export them
- Ask questions with answers grounded in real calculations, with Claude, OpenAI, or Gemini, or in a labelled demonstration mode with no API key
- Detect outliers, sudden changes, frequency changes, missing-data patterns, and rare categories
- Generate six report types as PDF, CSV, and XLSX
- Import from PostgreSQL and REST APIs, with SSRF protection and encrypted credentials
- Workspaces with roles, an audit log, and five synthetic demonstration datasets

### Installation

Requires Python 3.12 or newer and Node.js 20 or newer. On Windows:

```bash
git clone <your-repository-url>
```

```bash
cd dataforge-ai-analytics-platform
```

```bash
setup.bat
```

```bash
start.bat
```

Then open <http://127.0.0.1:8000>. On macOS or Linux, use `./setup.command` and `./start.command`. See [docs/INSTALLATION.md](INSTALLATION.md).

### Known limitations

- Live AI providers have been tested with simulated API responses only, so try yours before relying on it.
- The macOS and Linux scripts have been syntax-checked, but not run.
- The app assumes one server process.
- Application-level encryption of dataset files, multi-factor authentication, and scheduled connection refreshes aren't included yet.
- Anomaly detection doesn't model seasonality.
- It hasn't had an independent security review, so it isn't recommended for sensitive production data yet.

### Test results

211 back-end tests (including 4 on real PostgreSQL), 12 front-end tests, and 5 end-to-end tests in Microsoft Edge all passed on Windows 11, with no known dependency vulnerabilities.
