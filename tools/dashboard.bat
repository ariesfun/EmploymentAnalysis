@echo off
REM =====================================================================
REM  Dashboard start/stop -- thin forwarder.
REM  The real logic lives in ..\scripts\ only (single source of truth), so
REM  this copy can never drift again (it used to keep "cmd /k" and no
REM  --no-use-colors, which brought back ANSI garbage + a leftover window).
REM
REM  Usage: dashboard.bat [start | stop | restart | status]   (default start)
REM =====================================================================

setlocal
set "ROOT=%~dp0.."
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=start"

if /i "%ACTION%"=="start"   goto :do_start
if /i "%ACTION%"=="stop"    goto :do_stop
if /i "%ACTION%"=="restart" goto :do_restart
if /i "%ACTION%"=="status"  goto :do_status

echo Usage: dashboard.bat [start ^| stop ^| restart ^| status]
exit /b 2

:do_start
call "%ROOT%\scripts\dashboard-start.bat" %2
exit /b %ERRORLEVEL%

:do_stop
call "%ROOT%\scripts\dashboard-stop.bat" %2
exit /b %ERRORLEVEL%

:do_restart
call "%ROOT%\scripts\dashboard-stop.bat" %2
call "%ROOT%\scripts\dashboard-start.bat"
exit /b %ERRORLEVEL%

:do_status
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\dashboard_manager.py" status
exit /b %ERRORLEVEL%