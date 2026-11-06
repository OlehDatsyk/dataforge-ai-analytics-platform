@echo off
setlocal
title DataForge AI setup
cd /d "%~dp0"
echo.
echo DataForge AI setup
echo ==================
echo.

echo [1/6] Checking Python 3.12 or newer...
set "PY=python"
where python >nul 2>nul
if errorlevel 1 set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto no_python
%PY% --version

echo.
echo [2/6] Checking Node.js 20 or newer...
where node >nul 2>nul
if errorlevel 1 goto no_node
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if errorlevel 1 goto no_node
node --version

echo.
echo [3/6] Preparing the Python environment in .venv...
if exist ".venv\Scripts\python.exe" goto venv_ready
%PY% -m venv .venv
if errorlevel 1 goto venv_failed
:venv_ready
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
if errorlevel 1 goto pip_failed
".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 goto pip_failed
echo Python packages are ready.

echo.
echo [4/6] Installing and building the front end...
pushd frontend
call npm ci --no-audit --no-fund
if errorlevel 1 goto npm_failed
call npm run build
if errorlevel 1 goto build_failed
popd

echo.
echo [5/6] Preparing configuration...
".venv\Scripts\python.exe" backend\scripts\create_env.py
if errorlevel 1 goto env_failed

echo.
echo [6/6] Applying database migrations...
pushd backend
"..\.venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto migrate_failed
popd

echo.
echo Setup is complete. Run start.bat to open DataForge AI.
goto finish

:no_python
echo ERROR: Python 3.12 or newer was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
goto failed
:no_node
echo ERROR: Node.js 20 or newer was not found.
echo Install the LTS version from https://nodejs.org/ and open a new terminal.
goto failed
:venv_failed
echo ERROR: The Python virtual environment could not be created.
goto failed
:pip_failed
echo ERROR: Python packages could not be installed. Check your internet connection and try again.
goto failed
:npm_failed
popd
echo ERROR: Front-end packages could not be installed. Check your internet connection and try again.
goto failed
:build_failed
popd
echo ERROR: The front end could not be built. See the messages above.
goto failed
:env_failed
echo ERROR: The .env configuration file could not be created.
goto failed
:migrate_failed
popd
echo ERROR: Database migrations failed. Check DATABASE_URL in .env, and that the database is running.
goto failed

:failed
echo.
echo Setup did not finish.
if not defined DATAFORGE_NO_PAUSE pause
exit /b 1

:finish
if not defined DATAFORGE_NO_PAUSE pause
exit /b 0
