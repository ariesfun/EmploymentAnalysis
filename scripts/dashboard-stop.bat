@echo off
REM =====================================================================
REM  Stop the dashboard (double-click to use, or: dashboard-stop.bat [port]).
REM  1) Kills the process LISTENING on port 8010, with its process tree.
REM  2) Fallback: kills that PID via .NET if taskkill is denied.
REM  3) Closes any dashboard console window still on screen (old "cmd /k"
REM     builds kept the window alive after the server died).
REM  4) Removes the stale .dashboard.pid and confirms the port is free.
REM =====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0.."
set "DASHBOARD_PORT=8010"
if not "%~1"=="" set "DASHBOARD_PORT=%~1"
set "KILLED=0"

for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%DASHBOARD_PORT%" ^| findstr "LISTENING"') do (
    echo Killing process PID %%a on port %DASHBOARD_PORT% ...
    taskkill /PID %%a /F /T >nul 2>&1
    if errorlevel 1 (
        powershell -NoProfile -Command "Stop-Process -Id %%a -Force -ErrorAction SilentlyContinue" >nul 2>&1
    )
    set "KILLED=1"
)

REM Close the dashboard console window even when its server already exited.
powershell -NoProfile -Command "Get-Process cmd,python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like 'EmploymentAnalysis-Dashboard*' } | ForEach-Object { $_.Kill() }" >nul 2>&1

if exist ".dashboard.pid" del /q ".dashboard.pid" >nul 2>&1

if !KILLED!==0 ( echo No process listening on port %DASHBOARD_PORT%. ) else ( echo Stopped. )

REM Give Windows a moment, then confirm the listener is really gone.
ping -n 2 127.0.0.1 >nul 2>&1
set "LEFT="
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%DASHBOARD_PORT%" ^| findstr "LISTENING"') do set "LEFT=%%a"
if defined LEFT (
    echo [WARN] Port %DASHBOARD_PORT% still LISTENING ^(PID !LEFT!^). Run stop again or kill it manually.
    exit /b 1
) else (
    echo Port %DASHBOARD_PORT% is free. Dashboard stopped, no window left.
    exit /b 0
)