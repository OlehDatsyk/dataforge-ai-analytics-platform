#!/usr/bin/env bash
# Starts DataForge AI on macOS and Linux. Use "./start.command dev" for automatic reload during development.
set -u
cd "$(dirname "$0")" || exit 1
PORT="${DATAFORGE_PORT:-8000}"

fail() {
  echo "ERROR: $1"
  exit 1
}

[ -x .venv/bin/python ] && [ -f .env ] || fail "DataForge AI has not been set up on this computer yet. Run ./setup.command first."
if [ "${1:-}" != "dev" ] && [ ! -f frontend/dist/index.html ]; then
  fail "The front end has not been built. Run ./setup.command first."
fi
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "Port $PORT is already in use. DataForge AI may already be running. To use another port: DATAFORGE_PORT=8010 ./start.command"
fi

cd backend || exit 1
echo "Applying database migrations..."
../.venv/bin/python -m alembic upgrade head || fail "Database migrations failed. Check DATABASE_URL in .env, and that the database is running."

if [ "${1:-}" = "dev" ]; then
  echo "Development mode: the front end is at http://127.0.0.1:5173 with automatic reload. Press Ctrl+C to stop."
  (cd ../frontend && npm run dev) &
  FRONTEND_PID=$!
  trap 'kill "$FRONTEND_PID" 2>/dev/null' EXIT
  ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload --reload-dir app
else
  echo "DataForge AI is running at http://127.0.0.1:$PORT. Press Ctrl+C to stop."
  if [ -z "${DATAFORGE_NO_BROWSER:-}" ]; then
    (sleep 2; command -v open >/dev/null 2>&1 && open "http://127.0.0.1:$PORT" || command -v xdg-open >/dev/null 2>&1 && xdg-open "http://127.0.0.1:$PORT") >/dev/null 2>&1 &
  fi
  ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
fi
