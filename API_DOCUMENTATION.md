# API documentation

Interactive documentation, generated from the code, is at `/api/docs` while the server runs, and the OpenAPI schema is at `/api/openapi.json`.

## Conventions

- **Base path:** `/api`. Requests and responses are JSON, except uploads and file downloads.
- **Authentication:** `POST /api/auth/login` or `/register` sets two cookies: `dataforge_session` (HttpOnly) and `dataforge_csrf` (readable by the page).
- **CSRF:** `POST`, `PUT`, `PATCH`, and `DELETE` on authenticated routes need an `X-CSRF-Token` header containing the value of `dataforge_csrf`.
- **Workspace:** `X-Workspace-Id` selects the workspace. Without it, the user's first workspace is used.
- **Roles:** `viewer` can read, `member` can also analyse and change data, `admin` also manages members and connections, and `owner` can also delete the workspace.
- **Errors:** `{"detail": "A readable message"}`.

| Status | Meaning |
|---|---|
| 401 | Not signed in, or the session has expired |
| 403 | Missing CSRF token, disallowed origin, or insufficient role |
| 404 | Not found, or in another workspace |
| 409 | Conflict, such as a dataset that is still processing |
| 411, 413, 415 | Upload size not declared, too large, or an unsupported file |
| 422 | Validation failure, with the reason |
| 429 | Rate limit reached |

## Example

```bash
curl -c cookies.txt -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"<your password>\"}" http://127.0.0.1:8000/api/auth/login
```

Then send the CSRF value from `cookies.txt` on later state-changing requests:

```bash
curl -b cookies.txt -H "X-CSRF-Token: <dataforge_csrf value>" -H "Content-Type: application/json" -d "{\"filters\":[{\"column\":\"revenue\",\"op\":\"gt\",\"value\":1000}],\"page_size\":25}" http://127.0.0.1:8000/api/datasets/<dataset id>/rows
```

## Authentication

| Method and path | Purpose |
|---|---|
| `POST /auth/register` | Create an account and a workspace |
| `POST /auth/login` | Sign in |
| `POST /auth/logout` | End this session |
| `GET /auth/me`, `PATCH /auth/me` | Read or update the profile |
| `POST /auth/change-password` | Change the password and end other sessions |
| `POST /auth/password-reset/request` | Request a reset link |
| `POST /auth/password-reset/confirm` | Set a new password with a token |

## Workspaces and projects

| Method and path | Purpose | Role |
|---|---|---|
| `GET /workspaces`, `POST /workspaces` | List or create workspaces | Any |
| `PATCH /workspaces/current` | Rename | Admin |
| `DELETE /workspaces/current` | Delete, along with its data | Owner |
| `GET /workspaces/current/members` | List members | Viewer |
| `POST /workspaces/current/members` | Add a registered user | Admin |
| `PATCH`, `DELETE /workspaces/current/members/{id}` | Change a role, or remove | Admin |
| `GET /projects`, `POST /projects` | List or create | Viewer, member |
| `DELETE /projects/{id}` | Delete; its datasets remain | Member |
| `GET /audit-logs` | Recent operations | Admin |

## Datasets

| Method and path | Purpose | Role |
|---|---|---|
| `POST /datasets` | Upload (multipart: `file`, optional `name`, `project_id`). Returns 202. | Member |
| `POST /datasets/demo` | Load the synthetic datasets | Member |
| `GET /datasets` | List. Query: `search`, `project_id`, `status`. | Viewer |
| `GET /datasets/{id}` | Details, versions, and columns | Viewer |
| `PATCH /datasets/{id}` | Rename, describe, or move to a project | Member |
| `DELETE /datasets/{id}` | Delete with derived data and files | Member |
| `POST /datasets/{id}/duplicate` | Copy the active version as a new dataset | Member |
| `GET /datasets/{id}/versions` | List versions | Viewer |
| `POST /datasets/{id}/versions/{version_id}/activate` | Restore a version | Member |
| `GET /datasets/{id}/profile` | Statistics and quality findings. Query: `version_id`. | Viewer |
| `POST /datasets/{id}/rows` | Query rows | Viewer |
| `POST /datasets/{id}/export` | Download the filtered view as CSV | Viewer |
| `POST /datasets/{id}/cleaning/preview` | Calculate effects without saving | Viewer |
| `POST /datasets/{id}/cleaning/apply` | Save a new version or dataset | Member |
| `GET /datasets/{id}/cleaning/history` | Saved operations | Viewer |

**Rows request:** `page`, `page_size` (up to 500), `sort` (`[{column, direction}]`), `filters`, `search`, `columns`, `version_id`.

**Filter:** `{column, op, value}` or `{column, op, values}`. Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_null`, `not_null`. They are validated against the column's type.

**Cleaning operations** are objects with an `op` of `remove_duplicates`, `fill_missing`, `drop_missing`, `rename_column`, `change_type`, `trim_whitespace`, `standardise_text`, `filter_rows`, `drop_column`, or `derive_column`. See the interactive documentation for their fields. **Apply** also takes `save_as` (`new_version` or `new_dataset`) and `name`.

## Charts

| Method and path | Purpose | Role |
|---|---|---|
| `POST /charts/run` | Calculate chart data from `{dataset_id, spec}` | Viewer |
| `GET /charts/recommendations?dataset_id=` | Suggested charts | Viewer |
| `GET /visualisations`, `POST /visualisations` | List or save | Viewer, member |
| `PUT`, `DELETE /visualisations/{id}` | Update or delete | Member |
| `GET /visualisations/{id}/data` | Recalculate a saved chart | Viewer |

**Spec:** `chart_type`, `x`, `y`, `group`, `aggregation`, `filters`, `time_grain`, `sort`, `limit`, `bins`, `title`, `x_label`, `y_label`.

## AI Data Analyst

| Method and path | Purpose | Role |
|---|---|---|
| `GET /analyst/status` | Active mode and provider. Never includes keys. | Viewer |
| `POST /analyst/ask` | Ask with `{dataset_id, question, conversation_id?}` | Member |
| `GET /analyst/conversations` | The caller's own conversations | Viewer |
| `GET`, `DELETE /analyst/conversations/{id}` | Read or delete | Author only |

The response includes `status`, `mode`, `provider`, `model`, `narrated_by`, `direct_answer`, `key_findings`, `interpretation`, `follow_ups`, `limitations`, `assumptions`, `notices`, `supporting_data`, `chart`, `provenance`, `plan`, `grounding`, `data_shared_with_ai`, and `usage`.

## Anomaly detection

| Method and path | Purpose | Role |
|---|---|---|
| `POST /anomalies/run` | Scan with `{dataset_id, columns?}` | Member |
| `GET /anomalies/runs?dataset_id=` | List scans | Viewer |
| `GET /anomalies/runs/{id}/results` | Findings. Query: `column`, `method`, `severity`, `status`, `kind`, `date_from`, `date_to`, `page`, `page_size`. | Viewer |
| `GET /anomalies/runs/{id}/chart?column=&kind=` | Chart data | Viewer |
| `PATCH /anomalies/results/{id}` | Set the review status | Member |
| `GET /anomalies/results/{id}/records` | Original records behind a finding | Viewer |

## Reports

| Method and path | Purpose | Role |
|---|---|---|
| `GET /reports/types` | Available types | Viewer |
| `GET /reports`, `POST /reports` | List or generate from `{dataset_id, report_type, title?, questions?}` | Viewer, member |
| `GET`, `DELETE /reports/{id}` | Read or delete | Viewer, member |
| `GET /reports/{id}/export/{pdf,csv,xlsx}` | Download | Viewer |

## Data connections

| Method and path | Purpose | Role |
|---|---|---|
| `GET /connections` | List. Secrets are never included. | Viewer |
| `POST /connections` | Create a `postgresql` or `rest_api` connection | Admin |
| `DELETE /connections/{id}` | Delete with its credentials | Admin |
| `POST /connections/{id}/test` | Test | Member |
| `GET /connections/{id}/tables` | List PostgreSQL tables | Viewer |
| `POST /connections/{id}/import` | Import into a dataset | Member |

## Overview

| Method and path | Purpose |
|---|---|
| `GET /health` | Service status (no sign-in needed) |
| `GET /overview?activity_range=24h\|7d\|30d` | Dashboard metrics and recent items |
| `GET /search?q=` | Search names of datasets, reports, charts, and conversations |
| `GET /notifications` | Recent notifications |
| `POST /notifications/read-all`, `POST /notifications/{id}/read` | Mark as read |
