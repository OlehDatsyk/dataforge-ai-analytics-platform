#!/usr/bin/env bash
# DataForge AI setup for macOS and Linux. Double-click on macOS, or run ./setup.command
set -u
cd "$(dirname "$0")" || exit 1

fail() {
  echo
  echo "ERROR: $1"
  echo "Setup did not finish."
  exit 1
}

echo
echo "DataForge AI setup"
echo "=================="

echo
echo "[1/6] Checking Python 3.12 or newer..."
PYTHON=""
for candidate in python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.12 or newer was not found. Install it from https://www.python.org/downloads/"
"$PYTHON" --version

echo
echo "[2/6] Checking Node.js 20 or newer..."
command -v node >/dev/null 2>&1 || fail "Node.js was not found. Install the LTS version from https://nodejs.org/"
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)" || fail "Node.js 20 or newer is required."
node --version

echo
echo "[3/6] Preparing the Python environment in .venv..."
if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -m venv .venv || fail "The Python virtual environment could not be created."
fi
.venv/bin/python -m pip install --quiet --upgrade pip || fail "pip could not be updated. Check your internet connection."
.venv/bin/python -m pip install --quiet -r backend/requirements.txt || fail "Python packages could not be installed."
echo "Python packages are ready."

echo
echo "[4/6] Installing and building the front end..."
(cd frontend && npm ci --no-audit --no-fund) || fail "Front-end packages could not be installed."
(cd frontend && npm run build) || fail "The front end could not be built. See the messages above."

echo
echo "[5/6] Preparing configuration..."
.venv/bin/python backend/scripts/create_env.py || fail "The .env configuration file could not be created."

echo
echo "[6/6] Applying database migrations..."
(cd backend && ../.venv/bin/python -m alembic upgrade head) || fail "Database migrations failed. Check DATABASE_URL in .env, and that the database is running."

echo
echo "Setup is complete. Run ./start.command to open DataForge AI."
