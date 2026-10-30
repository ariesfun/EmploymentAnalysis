@echo off
REM =====================================================================
REM  Start the dashboard (double-click to use).
REM  1) Opens a NEW independent minimized window running uvicorn (live logs,
REM     survives this .bat closing). The window closes BY ITSELF when uvicorn
REM     exits (Ctrl+C, dashboard-stop.bat, or a crash) -- no leftover window.
REM     --no-use-colors is REQUIRED: Windows conhost prints uvicorn's ANSI
REM     colour codes as garbage (e.g. "[32mINFO[0m") without it.
REM  2) Waits until the port is LISTENING, then AUTO-OPENS the dashboard in
REM     your default browser. If the server is not up after 15s it reports the
REM     failure instead of opening a dead page, and exits with code 1.
REM  3) Safe to run twice: when the dashboard already answers on that port it
REM     just opens the browser. Pre-set JOBMVP_* / DASHBOARD_* env vars to
REM     override the defaults below (e.g. DASHBOARD_PORT=8011).
REM =====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0.."

if not defined JOBMVP_DSN set "JOBMVP_DSN=postgresql://mvp:mvp@127.0.0.1:5432/jobmvp"
if not defined JOBMVP_API_KEY set "JOBMVP_API_KEY=devkey"
if not defined DASHBOARD_HOST set "DASHBOARD_HOST=127.0.0.1"
if not defined DASHBOARD_PORT set "DASHBOARD_PORT=8010"
set "DASHBOARD_URL=http://%DASHBOARD_HOST%:%DASHBOARD_PORT%/ui?key=%JOBMVP_API_KEY%"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv\Scripts\python.exe not found. Create the venv first.
    REM wait without a console: 'timeout' fails when stdin is redirected
    ping -n 11 127.0.0.1 >nul 2>&1
    exit /b 1
)

REM Warn only (never block): a down database means every API answers with 500.
echo %JOBMVP_DSN% | findstr /i "127.0.0.1:5432 localhost:5432" >nul 2>&1
if not errorlevel 1 (
    netstat -ano 2>nul | findstr ":5432" | findstr "LISTENING" >nul
    if errorlevel 1 echo [WARN] Postgres is not LISTENING on 5432 -- dashboard APIs will error.
)

set "BUSY="
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%DASHBOARD_PORT%" ^| findstr "LISTENING"') do set "BUSY=%%a"
if defined BUSY (
    REM HTTP probe: only OUR dashboard answers /ui, so a foreign process on the
    REM port is not mistaken for a running dashboard.
    curl -s -m 3 -o nul -f "%DASHBOARD_URL%" >nul 2>&1
    if not errorlevel 1 (
        echo Dashboard already running on port %DASHBOARD_PORT% ^(PID !BUSY!^). Not starting a second one.
        echo Opening it in your default browser:
        echo %DASHBOARD_URL%
        start "" "%DASHBOARD_URL%"
        goto :eof
    )
    echo [ERROR] Port %DASHBOARD_PORT% is in use by PID !BUSY!, and /ui does not answer there.
    echo         Run scripts\dashboard-stop.bat first, or pick another port.
    REM wait without a console: 'timeout' fails when stdin is redirected
    ping -n 11 127.0.0.1 >nul 2>&1
    exit /b 1
)

echo Starting dashboard (new window with live logs)...
REM cmd /c (not /k): the console closes as soon as uvicorn exits, so stop
REM leaves no black window behind. --no-use-colors kills the ANSI garbage.
start "EmploymentAnalysis-Dashboard" /min cmd /c ".venv\Scripts\python.exe -m uvicorn console.app:app --host %DASHBOARD_HOST% --port %DASHBOARD_PORT% --no-use-colors"

REM Wait until the port is LISTENING (max ~15s), then auto-open the browser.
set "WAITED=0"
:waitloop
netstat -ano 2>nul | findstr ":%DASHBOARD_PORT%" | findstr "LISTENING" >nul
if not errorlevel 1 goto :open
ping -n 2 127.0.0.1 >nul 2>&1
set /a WAITED+=1
if !WAITED! LSS 15 goto :waitloop

echo [ERROR] Port %DASHBOARD_PORT% is not LISTENING after 15s. Read the log window.
ping -n 11 127.0.0.1 >nul 2>&1
exit /b 1

:open
echo [OK] Dashboard is up. Opening your default browser:
echo %DASHBOARD_URL%
start "" "%DASHBOARD_URL%"
exit /b 0