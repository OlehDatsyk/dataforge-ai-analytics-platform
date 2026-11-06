# Installation

The quickest route is `setup.bat` then `start.bat` on Windows, or `./setup.command` then `./start.command` on macOS and Linux. This guide explains what those scripts do, for manual installs and custom configurations.

The Windows commands below were verified on Windows 11 with Python 3.12.10 and Node.js 24.20.0. The macOS and Linux commands follow the same steps, but have not been run on those systems.

## Windows

### 1. Clone the repository

```bash
git clone <your-repository-url>
```

```bash
cd dataforge-ai-analytics-platform
```

### 2. Install back-end dependencies

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

### 3. Install front-end dependencies and build

```bash
cd frontend && npm ci && npm run build && cd ..
```

### 4. Create the environment file

```bash
.venv\Scripts\python backend\scripts\create_env.py
```

This copies `.env.example` to `.env` with new random secrets. It never overwrites an existing `.env`.

### 5. Configure the database

SQLite needs no setup. Leave `DATABASE_URL` empty, and the database file is created at `data/dataforge.db`.

For PostgreSQL, create a database and a user, then set this in `.env`:

```text
DATABASE_URL=postgresql://dataforge:<your password>@localhost:5432/dataforge
```

If you have Docker, this starts a local server bound to your machine only. It reads the password from `POSTGRES_PASSWORD`. The Compose file was written for this project, but has not been run, because Docker wasn't available during development.

```bash
docker compose up -d
```

### 6. Set up file storage

Files go to `data/` by default, which Git ignores. To use another location, such as a dedicated or encrypted volume, set `DATA_DIR` in `.env`. The folder is created automatically.

### 7. Run database migrations

```bash
cd backend && ..\.venv\Scripts\python -m alembic upgrade head && cd ..
```

### 8. Background processing

No separate service is needed. File processing runs in a worker pool inside the API process. `JOB_WORKERS` sets its size, and interrupted jobs are requeued when the server restarts.

### 9. Start the back end

```bash
cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

This also serves the built front end.

### 10. Start the front end for development (optional)

For automatic reloading while developing, run this in a second terminal. The development server forwards `/api` to port 8000.

```bash
cd frontend && npm run dev
```

`start.bat dev` starts both servers together.

### 11. Open the application

- Built front end: <http://127.0.0.1:8000>
- Development front end: <http://127.0.0.1:5173>
- API documentation: <http://127.0.0.1:8000/api/docs>

## macOS and Linux

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r backend/requirements.txt
```

```bash
(cd frontend && npm ci && npm run build)
```

```bash
.venv/bin/python backend/scripts/create_env.py
```

```bash
(cd backend && ../.venv/bin/python -m alembic upgrade head)
```

```bash
(cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000)
```

## Enabling a live AI provider

Add a key to `.env` and restart. `AI_PROVIDER=auto` picks the first provider that has a key.

```text
ANTHROPIC_API_KEY=<your key>
```

OpenAI and Gemini also need a model name, in `OPENAI_MODEL` or `GEMINI_MODEL`. Choose one that supports JSON-schema structured output. **AI and privacy** in Settings confirms the active provider. Read [DATA_PRIVACY.md](DATA_PRIVACY.md) first.

## Production deployment

The application has been run and tested locally only. For a deployment:

1. Set `ENVIRONMENT=production`, and provide `SECRET_KEY` and `ENCRYPTION_KEY` from a secrets manager. The app refuses to start without them.
2. Use PostgreSQL, with backups of both the database and `DATA_DIR`.
3. Put the app behind an HTTPS reverse proxy. Production mode forces secure cookies and adds HSTS.
4. Add `--proxy-headers --forwarded-allow-ips=<proxy address>` to Uvicorn. Otherwise all users share the proxy's address for rate limits and audit records.
5. Run one server process, and set `CORS_ORIGINS` and `PUBLIC_APP_URL` to your real domain.
6. Configure SMTP so password resets can be delivered.
7. Keep `ALLOW_PRIVATE_CONNECTIONS=false`, and restrict outbound traffic at the network level.
8. Put `DATA_DIR` on an encrypted volume.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Python 3.12 or newer was not found` | Install Python and tick **Add python.exe to PATH**, then open a new terminal. |
| `Port 8000 is already in use` | DataForge AI may already be running. Otherwise run `set DATAFORGE_PORT=8010`, then `start.bat`. |
| `Database migrations failed` | Check `DATABASE_URL`, and that PostgreSQL is running. |
| Stored connections can't be decrypted | `ENCRYPTION_KEY` changed. Restore it, or delete and re-create the connections. |
| Slow installs in a OneDrive folder | Move the project out of the synced folder, or exclude `.venv`, `node_modules`, and `data`. |
| Blank page at port 8000 | Rebuild the front end with `npm run build`, or run `setup.bat` again. |
