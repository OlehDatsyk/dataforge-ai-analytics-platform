# Instructions for developers and AI coding agents

This file explains how to install, run, debug, understand, and extend DataForge AI.

## Rules that must stay true

1. **Every number shown to a user comes from the data engine.** AI models plan and explain; they never calculate. Don't bypass `validate_plan` or `check_grounding`.
2. **Never build SQL from user or AI text.** Column names go through `require_column` and `quote`. Values are bound parameters.
3. **Every query for tenant data is scoped to the workspace.** Use `get_dataset`, `get_ready_dataset`, or an explicit `workspace_id` filter. Authorisation lives on the server.
4. **Originals and versions are immutable.** Changes create new versions through `save_version`.
5. **Don't put dataset contents in logs or the audit trail.** Log types and identifiers only.
6. **Label synthetic data and demonstration mode** wherever they appear.
7. **Keep documentation honest.** Don't claim tests, providers, or platforms that haven't been verified.

## Install and run

Windows: `setup.bat`, then `start.bat`, or `start.bat dev` for automatic reload. macOS and Linux: `./setup.command`, then `./start.command`. See [docs/INSTALLATION.md](docs/INSTALLATION.md) for manual steps.

| Address | Purpose |
|---|---|
| <http://127.0.0.1:8000> | App served by FastAPI (built front end) |
| <http://127.0.0.1:5173> | Development front end, in dev mode |
| <http://127.0.0.1:8000/api/docs> | Interactive API documentation |

Use **Load demonstration data** for instant test data.

## Test

Run these from the repository root unless noted. Install the test tools once with `.venv\Scripts\python -m pip install -r backend\requirements-dev.txt`.

| Purpose | Command | Directory |
|---|---|---|
| Back-end tests | `..\.venv\Scripts\python -m pytest` | `backend` |
| Skip PostgreSQL tests | `..\.venv\Scripts\python -m pytest -m "not postgres"` | `backend` |
| Lint | `..\.venv\Scripts\python -m ruff check app scripts tests` | `backend` |
| Dependency audit | `..\.venv\Scripts\python -m pip_audit -r requirements.txt` | `backend` |
| Types and build | `npm run build` | `frontend` |
| Front-end tests | `npm test` | `frontend` |
| End-to-end tests | `npx playwright test` | `frontend` |

End-to-end tests run against the **built** front end, so build first. They start their own server on port 8765 with a temporary database, and they use Microsoft Edge unless `E2E_CHANNEL` is set.

Back-end tests use a temporary data directory. `test_postgres.py` starts a real PostgreSQL server from the `pgserver` package, and is skipped if that package is absent.

## Debug

| Symptom | Where to look |
|---|---|
| A 500 response | Server log: it names the exception type and path. Messages are hidden deliberately. To see details locally, reproduce the call in a test with `raise_server_exceptions=True`, the TestClient default. |
| A dataset stuck or failed | `datasets.status`, `stage`, and `error_message`. Failures are recorded in `process_dataset`. |
| A type inferred wrongly | `services/inference.py`. Test with `infer_column`. |
| A wrong analyst answer | The response's `plan` field shows what was asked of the engine. Fix the planner if the plan is wrong, or the executor if the plan is right. |
| AI provider problems | `GET /api/analyst/status`. Answers also include `notices`. |
| A 403 on POST | Missing `X-CSRF-Token`, or an origin not in `CORS_ORIGINS`. |
| A chart fails | The 422 message comes from `validate_spec` in `services/charts.py`. |
| Database state | SQLite file at `data/dataforge.db`, or inspect `DATABASE_URL`. |

To reset local data, stop the server and delete the `data` folder. This deletes all accounts and datasets.

## Understand the code

Start with [ARCHITECTURE.md](ARCHITECTURE.md). Suggested reading order:

1. `backend/app/models.py`, the data model
2. `backend/app/deps.py`, how authorisation works
3. `backend/app/services/ingestion.py`, the pipeline
4. `backend/app/services/query_engine.py`, safe queries
5. `backend/app/ai/analyst.py`, then `plan.py` and `executor.py`
6. `frontend/src/lib/context.tsx`, then any page in `frontend/src/pages`

## Common changes

### Add an API endpoint

Add it to a router in `backend/app/api`, using a dependency for the required role: `workspace_context` (read), `editor_context` (change), or `admin_context`. Use a Pydantic model for the body. Add a test, including one showing another user gets 404. Update [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

### Change the database

Edit `models.py`, then generate and review a migration from `backend`:

```bash
..\.venv\Scripts\python -m alembic revision --autogenerate -m "describe the change"
```

Test it on PostgreSQL, because a test compares migrations with models there.

### Add a cleaning operation

Add a Pydantic model and include it in `CleaningOp` in `services/cleaning.py`, implement it in `_apply_one`, returning a clear description, and add its form to `OPERATIONS` and `OperationForm` in `pages/Cleaning.tsx`. Add tests in `test_explorer_cleaning.py`.

### Add a chart type

Extend `ChartType`, `validate_spec`, and `run_chart` in `services/charts.py`, then `CHART_TYPES` in `pages/Visualisations.tsx`, and rendering in `ChartView.tsx`. Keep to the validated colour palette. Check values against an independent calculation in tests.

### Add an analysis operation

Add it to `Operation` and `PLAN_JSON_SCHEMA` in `ai/plan.py`, validate it in `validate_plan`, implement it in `ai/executor.py`, describe it in `PLANNER_SYSTEM`, and add phrases to `rule_planner.py` if useful. Compare results with independent calculations in `test_charts_analyst.py`.

### Add an AI provider

Implement `complete_json` in `ai/providers.py`, add settings to `config.py` and `.env.example`, and register it in `configured_provider_name` and `get_provider`. Test with a mock HTTP transport, including error handling and key safety. Say in the documentation how far it has been verified.

### Add an anomaly method

Add it to `services/anomaly.py`, with explicit conditions for when it applies. Add tests for both detection and false alarms, and update [docs/ANOMALY_DETECTION.md](docs/ANOMALY_DETECTION.md).

## Conventions

- British English in user-facing text and documentation.
- API errors are readable sentences a user can act on.
- User-facing language says what happened and what to do next.
- Backend modules stay small and focused, with routers free of business logic.
- Sample data stays synthetic. Regenerate it with `backend/scripts/generate_sample_datasets.py`, which is deterministic.
