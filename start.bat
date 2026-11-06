@echo off
setlocal
title DataForge AI
cd /d "%~dp0"
if not defined DATAFORGE_PORT set "DATAFORGE_PORT=8000"

if not exist ".venv\Scripts\python.exe" goto not_set_up
if not exist ".env" goto not_set_up
if /i "%~1"=="dev" goto check_port
if not exist "frontend\dist\index.html" goto not_built

:check_port
netstat -ano | findstr /r /c:":%DATAFORGE_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 goto port_busy

echo Applying database migrations...
pushd backend
"..\.venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto migrate_failed

if /i "%~1"=="dev" goto dev_mode
echo.
echo DataForge AI is running at http://127.0.0.1:%DATAFORGE_PORT%
echo Press Ctrl+C in this window to stop it.
echo.
if not defined DATAFORGE_NO_BROWSER start "" "http://127.0.0.1:%DATAFORGE_PORT%"
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %DATAFORGE_PORT%
if errorlevel 1 goto server_failed
popd
exit /b 0

:dev_mode
echo.
echo Development mode: the front end is at http://127.0.0.1:5173 with automatic reload.
echo Close this window and the front-end window to stop.
echo.
start "DataForge AI front end" /d "%~dp0frontend" cmd /k npm run dev
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %DATAFORGE_PORT% --reload --reload-dir app
popd
exit /b 0

:not_set_up
echo DataForge AI has not been set up on this computer yet. Run setup.bat first.
goto failed
:not_built
echo The front end has not been built. Run setup.bat first.
goto failed
:port_busy
echo Port %DATAFORGE_PORT% is already in use, so the server cannot start.
echo DataForge AI may already be running. To use another port: set DATAFORGE_PORT=8010
goto failed
:migrate_failed
popd
echo Database migrations failed. Check DATABASE_URL in .env, and that the database is running.
goto failed
:server_failed
popd
echo The server stopped because of an error. See the messages above.
goto failed

:failed
if not defined DATAFORGE_NO_PAUSE pause
exit /b 1
